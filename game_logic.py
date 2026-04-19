import random
import asyncio
import math
from typing import List, Dict, Tuple, Optional, Any
from datetime import datetime
import statistics
import json
from collections import Counter
from models import GameState, Player, CityPair, GameStatus, GameRoom
from database import (
    get_city_pairs,
    get_sorting_quiz_questions,
    save_game_result,
    save_high_score,
    SessionLocal,
    DBGameResult,
    get_cached_route_distance_km,
    get_cached_route_points,
    upsert_route_distance_km,
    upsert_route_points,
)
import uuid
from config import config
from graphhopper_service import fetch_route_data
import logging

logger = logging.getLogger(__name__)


class GameLogic:
    def __init__(self, game_room: GameRoom, ws_handler=None):
        self.game_room = game_room
        self.ws_handler = ws_handler
        
    def set_ws_handler(self, ws_handler):
        """Set the WebSocket handler for broadcasting messages"""
        self.ws_handler = ws_handler

    def _pick_question_variant(self, game: GameState) -> str:
        """Pick the next variant fairly, independent from host-defined ratios.

        Strategy: among enabled variants, pick one of the least-used types so far.
        Ties are broken randomly to avoid deterministic cycles.
        """
        game_config = game.config
        enabled_variants: List[str] = []
        if bool(getattr(game_config, "enable_air_questions", True)):
            enabled_variants.append("air")
        if bool(getattr(game_config, "enable_air_map_questions", True)):
            enabled_variants.append("air_map")
        if bool(getattr(game_config, "enable_road_questions", True)):
            enabled_variants.append("road")
        if bool(getattr(game_config, "enable_sorting_questions", True)):
            enabled_variants.append("sorting")

        if not enabled_variants:
            return "air_map"

        usage_counts: Dict[str, int] = {variant: 0 for variant in enabled_variants}
        for round_entry in (game.round_history or []):
            variant = str(round_entry.get("question_type") or "")
            if variant in usage_counts:
                usage_counts[variant] += 1

        min_count = min(usage_counts.values())
        candidates = [variant for variant, count in usage_counts.items() if count == min_count]
        chosen = random.choice(candidates)
        logger.info(
            "Question variant fair decision: enabled=%s usage=%s candidates=%s chosen=%s",
            enabled_variants,
            usage_counts,
            candidates,
            chosen,
        )
        return chosen

    def _should_use_speed_round(self, game_config) -> bool:
        if not getattr(game_config, "enable_speed_rounds", True):
            return False
        ratio_pct = int(getattr(game_config, "speed_round_ratio_percent", 15) or 0)
        ratio_pct = max(0, min(100, ratio_pct))
        return random.random() < (ratio_pct / 100.0)

    def _has_distinct_coordinates(self, lat1: float, lon1: float, lat2: float, lon2: float) -> bool:
        """Return False for obviously broken pairs where both cities share almost same coordinates."""
        # ~0.02 degrees are roughly ~2km in latitude; this is enough to catch bad imports
        # while keeping valid nearby-city questions.
        return not (abs(float(lat1) - float(lat2)) < 0.02 and abs(float(lon1) - float(lon2)) < 0.02)

    def _is_valid_lat_lon(self, lat: float, lon: float) -> bool:
        return -90.0 <= float(lat) <= 90.0 and -180.0 <= float(lon) <= 180.0

    def _haversine_km(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Great-circle distance in km."""
        r = 6371.0
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        dphi = math.radians(float(lat2) - float(lat1))
        dlambda = math.radians(float(lon2) - float(lon1))
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _resolve_pair_coordinates(self, lat1: float, lon1: float, lat2: float, lon2: float) -> Optional[Tuple[float, float, float, float]]:
        """Sanitize pair coordinates and auto-correct likely lat/lon swaps.

        Keeps original values when plausible, but when endpoints are implausibly close,
        tries swapped variants and picks one with meaningful separation.
        """
        raw = (float(lat1), float(lon1), float(lat2), float(lon2))
        l1, o1, l2, o2 = raw

        if not (self._is_valid_lat_lon(l1, o1) and self._is_valid_lat_lon(l2, o2)):
            return None

        direct_km = self._haversine_km(l1, o1, l2, o2)
        if direct_km >= 5.0:
            return raw

        candidates = [
            raw,
            (o1, l1, l2, o2),
            (l1, o1, o2, l2),
            (o1, l1, o2, l2),
        ]
        best = None
        best_km = -1.0
        for c in candidates:
            c_l1, c_o1, c_l2, c_o2 = c
            if not (self._is_valid_lat_lon(c_l1, c_o1) and self._is_valid_lat_lon(c_l2, c_o2)):
                continue
            km = self._haversine_km(c_l1, c_o1, c_l2, c_o2)
            if km > best_km:
                best_km = km
                best = c

        if best is None or best_km < 5.0:
            return None

        return best

    def _build_sorting_question(self) -> CityPair:
        with SessionLocal() as db:
            quiz_rows = get_sorting_quiz_questions(db)

        if quiz_rows:
            selected = random.choice(quiz_rows)
            try:
                items = json.loads(selected.items_json or "[]")
                correct_order = json.loads(selected.correct_order_json or "[]")
            except Exception:
                items = []
                correct_order = []

            if isinstance(items, list) and isinstance(correct_order, list) and len(items) >= 3 and Counter(items) == Counter(correct_order):
                return CityPair(
                    id=-1,
                    city1="-",
                    city2="-",
                    distance=0,
                    lat1=0.0,
                    lon1=0.0,
                    lat2=0.0,
                    lon2=0.0,
                    question_id=str(uuid.uuid4().hex[:8]),
                    question_variant="sorting",
                    sorting_numbers=items,
                    sorting_order="custom",
                    correct_order=correct_order,
                    sorting_prompt=selected.prompt or "Bringe die Begriffe in die richtige Reihenfolge.",
                )

        numbers = random.sample(range(1, 151), 4)
        sorting_order = random.choice(["asc", "desc"])
        correct_order = sorted(numbers, reverse=(sorting_order == "desc"))
        return CityPair(
            id=-1,
            city1="-",
            city2="-",
            distance=0,
            lat1=0.0,
            lon1=0.0,
            lat2=0.0,
            lon2=0.0,
            question_id=str(uuid.uuid4().hex[:8]),
            question_variant="sorting",
            sorting_numbers=numbers,
            sorting_order=sorting_order,
            correct_order=correct_order,
            sorting_prompt="",
        )

    def _routing_provider(self) -> str:
        return (getattr(config, "ROUTING_PROVIDER", "osrm") or "osrm").strip().lower()

    async def _try_get_road_route(self, question: CityPair) -> Optional[Dict[str, object]]:
        provider = self._routing_provider()
        provider_for_cache = provider if provider in {"osrm", "graphhopper"} else "auto"
        profile_for_cache = config.GRAPHHOPPER_PROFILE

        with SessionLocal() as db:
            cached_distance = get_cached_route_distance_km(
                db,
                city_pair_id=question.id,
                provider=provider_for_cache,
                profile=profile_for_cache,
            )
            cached_points = get_cached_route_points(
                db,
                city_pair_id=question.id,
                provider=provider_for_cache,
                profile=profile_for_cache,
            )

        if cached_distance is not None and cached_points:
            return {
                "distance_km": int(cached_distance),
                "points": cached_points,
            }

        route_data = await asyncio.to_thread(
            fetch_route_data,
            question.lat1,
            question.lon1,
            question.lat2,
            question.lon2,
            config.GRAPHHOPPER_API_KEY,
            config.GRAPHHOPPER_PROFILE,
            provider,
            config.OSRM_BASE_URL,
        )
        if route_data is None:
            return None

        distance_km = int(route_data.get("distance_km", 0) or 0)
        points = route_data.get("points") or []
        if distance_km <= 0 or len(points) < 2:
            return None

        with SessionLocal() as db:
            used_provider = str(route_data.get("provider") or provider_for_cache)
            used_profile = str(route_data.get("profile") or profile_for_cache)
            upsert_route_distance_km(
                db,
                city_pair_id=question.id,
                distance_km=distance_km,
                provider=used_provider,
                profile=used_profile,
            )
            upsert_route_points(
                db,
                city_pair_id=question.id,
                points=points,
                provider=used_provider,
                profile=used_profile,
            )
        return {
            "distance_km": distance_km,
            "points": points,
        }

    async def _build_question_from_db_pair(self, db_city_pair, game_config, preferred_variant: str = "air") -> Optional[CityPair]:
        resolved_coords = self._resolve_pair_coordinates(
            db_city_pair.lat1,
            db_city_pair.lon1,
            db_city_pair.lat2,
            db_city_pair.lon2,
        )
        if not resolved_coords:
            logger.warning(
                "Skipping invalid city pair coordinates: %s -> %s (id=%s)",
                db_city_pair.city1,
                db_city_pair.city2,
                db_city_pair.id,
            )
            return None

        lat1, lon1, lat2, lon2 = resolved_coords
        if not self._has_distinct_coordinates(lat1, lon1, lat2, lon2):
            logger.warning(
                "Skipping near-identical city pair coordinates after sanitize: %s -> %s (id=%s)",
                db_city_pair.city1,
                db_city_pair.city2,
                db_city_pair.id,
            )
            return None

        question = CityPair(
            id=db_city_pair.id,
            city1=db_city_pair.city1,
            city2=db_city_pair.city2,
            distance=db_city_pair.distance,
            lat1=lat1,
            lon1=lon1,
            lat2=lat2,
            lon2=lon2,
            question_id=str(uuid.uuid4().hex[:8]),
            question_variant="air",
        )

        air_enabled = bool(getattr(game_config, "enable_air_questions", True))
        air_map_enabled = bool(getattr(game_config, "enable_air_map_questions", True))
        road_enabled = bool(getattr(game_config, "enable_road_questions", True))

        if preferred_variant == "air_map" and air_map_enabled:
            question.question_variant = "air_map"
            return question

        if preferred_variant == "road" and road_enabled:
            road_route = await self._try_get_road_route(question)
            if road_route is not None:
                question.distance = int(road_route["distance_km"])
                question.question_variant = "road"
                question.route_points = road_route.get("points") or []
                return question
            if not air_enabled:
                return None
            return question

        if preferred_variant == "air":
            if air_enabled:
                return question
            if air_map_enabled:
                question.question_variant = "air_map"
                return question
            if road_enabled:
                road_route = await self._try_get_road_route(question)
                if road_route is not None:
                    question.distance = int(road_route["distance_km"])
                    question.question_variant = "road"
                    question.route_points = road_route.get("points") or []
                    return question
            return None

        if road_enabled:
            road_route = await self._try_get_road_route(question)
            if road_route is not None:
                question.distance = int(road_route["distance_km"])
                question.question_variant = "road"
                question.route_points = road_route.get("points") or []
                return question
        return question if air_enabled else None

    async def start_game(self, game_id: str) -> bool:
        """Start a new game if all players are ready"""
        game = self.game_room.get_game(game_id)
        if not game or not game.can_start():
            return False

        logger.info(f"Starting game {game_id}")
        game.reset()
        game.status = GameStatus.COUNTDOWN
        await self.next_round(game_id)
        return True

    async def start_warmup_round(self, game_id: str) -> bool:
        """Start a single non-scoring warmup round before the real game."""
        game = self.game_room.get_game(game_id)
        if not game or game.status != GameStatus.WAITING:
            return False

        game.warmup_active = True
        game.current_round = 0
        game.answers = {}
        game.answer_submissions = {}
        game.round_resolution_in_progress = False
        game.status = GameStatus.ACTIVE

        question = await self._assign_random_question(game)
        if not question:
            game.warmup_active = False
            game.status = GameStatus.WAITING
            return False

        game.answer_time_remaining = min(20, game.config.answer_time_seconds)
        game.question_started_at = datetime.now()

        if self.ws_handler:
            await self.ws_handler.broadcast_to_game(
                game_id,
                "warmup_started",
                {"time_limit": game.answer_time_remaining},
            )
            await self.broadcast_question(game_id)

        game.answer_deadline_task = asyncio.create_task(self.answer_timeout(game_id))
        return True

    async def pause_for_reconnect(self, game_id: str, player_name: str, grace_seconds: int = 8):
        """Temporarily pause active rounds when a player drops connection."""
        game = self.game_room.get_game(game_id)
        if not game or game.status != GameStatus.ACTIVE:
            return

        if game.pause_reason == "reconnect":
            return

        game.status = GameStatus.PAUSED
        game.pause_reason = "reconnect"

        if self.ws_handler:
            await self.ws_handler.broadcast_to_game(
                game_id,
                "game_paused",
                {
                    "reason": "player_reconnect",
                    "player_name": player_name,
                    "grace_seconds": grace_seconds,
                    "remaining_seconds": game.answer_time_remaining,
                },
            )

        if game.reconnect_resume_task and not game.reconnect_resume_task.done():
            game.reconnect_resume_task.cancel()
        game.reconnect_resume_task = asyncio.create_task(
            self._resume_after_reconnect_pause(game_id, grace_seconds)
        )

    async def resume_after_player_return(self, game_id: str):
        """Resume game early when player comes back during reconnect pause."""
        game = self.game_room.get_game(game_id)
        if not game or game.pause_reason != "reconnect":
            return

        if game.reconnect_resume_task and not game.reconnect_resume_task.done():
            game.reconnect_resume_task.cancel()

        game.status = GameStatus.ACTIVE
        game.pause_reason = None
        if self.ws_handler:
            await self.ws_handler.broadcast_to_game(
                game_id,
                "game_resumed",
                {"remaining_seconds": game.answer_time_remaining},
            )

    async def _resume_after_reconnect_pause(self, game_id: str, delay_seconds: int):
        try:
            await asyncio.sleep(delay_seconds)
            game = self.game_room.get_game(game_id)
            if not game or game.pause_reason != "reconnect":
                return

            game.status = GameStatus.ACTIVE
            game.pause_reason = None
            if self.ws_handler:
                await self.ws_handler.broadcast_to_game(
                    game_id,
                    "game_resumed",
                    {"remaining_seconds": game.answer_time_remaining},
                )
        except asyncio.CancelledError:
            return

    async def next_round(self, game_id: str) -> bool:
        """Move to next round or end game"""
        try:
            game = self.game_room.get_game(game_id)
            if not game:
                return False

            if game.current_round >= game.config.max_rounds:
                await self.end_game(game_id)
                return False

            game.current_round += 1
            game.answers = {}
            game.answer_submissions = {}
            game.answer_submission_history = {}
            game.round_resolution_in_progress = False
            game.status = GameStatus.ACTIVE
            game.pause_reason = None

            # Use pre-loaded question if available, otherwise load fresh
            if game.next_question_preloaded:
                question = game.next_question_preloaded
                game.current_question = question
                game.next_question_preloaded = None
            else:
                question = await self._assign_random_question(game)
            
            if not question:
                await self.end_game(game_id)
                return False

            is_speed = self._should_use_speed_round(game.config)
            if is_speed:
                question.speed_round = True
                game.answer_time_remaining = game.config.speed_round_time_seconds
            else:
                question.speed_round = False
                game.answer_time_remaining = game.config.answer_time_seconds
            game.question_started_at = datetime.now()

            logger.info(
                f"Game {game_id}: New question: {game.current_question.cities[0]} to {game.current_question.cities[1]}, correct distance: {game.current_question.distance} km"
                + (" [SPEED ROUND]" if is_speed else "")
            )

            # Broadcast the question to all players
            await self.broadcast_question(game_id)

            # Start answer timeout
            game.answer_deadline_task = asyncio.create_task(self.answer_timeout(game_id))
            return True
        except Exception as e:
            logger.error(f"Error in next_round for game {game_id}: {e}", exc_info=True)
            return False

    async def _assign_random_question(self, game: GameState) -> Optional[CityPair]:
        """Load and assign a random city pair for a game."""
        preferred_variant = self._pick_question_variant(game)
        if preferred_variant == "sorting":
            game.current_question = self._build_sorting_question()
            return game.current_question

        with SessionLocal() as db:
            city_pairs = get_city_pairs(db)
            if not city_pairs:
                logger.error(f"No city pairs available for game {game.id}")
                return None

            random.shuffle(city_pairs)
            game.current_question = None
            for db_city_pair in city_pairs:
                candidate = await self._build_question_from_db_pair(
                    db_city_pair,
                    game.config,
                    preferred_variant=preferred_variant,
                )
                if candidate is not None:
                    game.current_question = candidate
                    break
        return game.current_question

    async def _assign_random_question_for_preload(self, game: GameState) -> Optional[CityPair]:
        """Load a random city pair WITHOUT modifying game.current_question (for pre-loading)."""
        preferred_variant = self._pick_question_variant(game)
        if preferred_variant == "sorting":
            return self._build_sorting_question()

        with SessionLocal() as db:
            city_pairs = get_city_pairs(db)
            if not city_pairs:
                logger.error(f"No city pairs available for pre-load in game {game.id}")
                return None

            random.shuffle(city_pairs)
            for db_city_pair in city_pairs:
                candidate = await self._build_question_from_db_pair(
                    db_city_pair,
                    game.config,
                    preferred_variant=preferred_variant,
                )
                if candidate is not None:
                    return candidate
            return None

    async def broadcast_question(self, game_id: str):
        """Broadcast current question to all players in the game"""
        try:
            if not self.ws_handler:
                logger.error("WebSocket handler not set, cannot broadcast question")
                return
                
            game = self.game_room.get_game(game_id)
            if not game or not game.current_question:
                return
            
            question = game.current_question
            is_sorting = question.question_variant == "sorting"
            data = {
                "game_id": game_id,
                "question_id": str(question.question_id),
                "question_variant": question.question_variant,
                "speed_round": question.speed_round,
                "round": game.current_round,
                "max_rounds": game.config.max_rounds,
                "time_limit": game.answer_time_remaining,
                "cities": [question.city1, question.city2] if not is_sorting else [],
                "city1": question.city1 if not is_sorting else "",
                "city2": question.city2 if not is_sorting else "",
                "question": (
                    (
                        question.sorting_prompt
                        if question.sorting_order == "custom" and question.sorting_prompt
                        else f"Sort the numbers in {'descending' if question.sorting_order == 'desc' else 'ascending'} order"
                    )
                    if is_sorting
                    else (
                        f"What is the road distance from {question.city1} to {question.city2}? (in km)"
                        if question.question_variant == "road"
                        else f"How far is it from {question.city1} to {question.city2}? (in km)"
                    )
                ),
                "route_points": question.route_points if question.question_variant == "road" else [],
                "coordinates": (
                    {
                        "from": {
                            "name": question.city1,
                            "lat": question.lat1,
                            "lon": question.lon1,
                        },
                        "to": {
                            "name": question.city2,
                            "lat": question.lat2,
                            "lon": question.lon2,
                        },
                    }
                    if not is_sorting
                    else None
                ),
                "sorting_numbers": question.sorting_numbers if is_sorting else [],
                "sorting_order": question.sorting_order if is_sorting else None,
                "sorting_prompt": question.sorting_prompt if is_sorting else None,
            }
            
            # Broadcast to all players in the game
            await self.ws_handler.broadcast_to_game(game_id, "new_question", data)
            logger.info(f"Question broadcasted to game {game_id}")
        except Exception as e:
            logger.error(f"Error broadcasting question: {e}", exc_info=True)

    async def answer_timeout(self, game_id: str):
        """Handle answer timeout"""
        game = self.game_room.get_game(game_id)
        if not game:
            return

        while game.answer_time_remaining > 0:
            if game.status == GameStatus.PAUSED:
                await asyncio.sleep(1)
                continue

            if game.status != GameStatus.ACTIVE:
                return

            await asyncio.sleep(1)
            game.answer_time_remaining -= 1

        await self.evaluate_answers(game_id)

    async def submit_answer(self, game_id: str, player_id: str, answer: Any) -> Optional[Dict]:
        """Submit player's answer"""
        game = self.game_room.get_game(game_id)
        if not game or game.status != GameStatus.ACTIVE or player_id not in game.players:
            return None

        question = game.current_question
        if not question:
            return None

        answer_to_store: Any
        answer_for_history: Any
        answer_for_response: Any

        if question.question_variant == "sorting":
            if not isinstance(answer, list) or not all(isinstance(x, (int, str)) for x in answer):
                if self.ws_handler:
                    await self.ws_handler.send_error(player_id, "Invalid sorting answer format")
                return None

            expected = question.sorting_numbers
            if len(answer) != len(expected) or Counter(answer) != Counter(expected):
                if self.ws_handler:
                    await self.ws_handler.send_error(player_id, "Sorting answer must use each provided item exactly once")
                return None

            answer_to_store = list(answer)
            answer_for_history = " > ".join(str(x) for x in answer)
            answer_for_response = list(answer)
        else:
            try:
                guess = int(answer)
            except (TypeError, ValueError):
                if self.ws_handler:
                    await self.ws_handler.send_error(player_id, "Invalid answer format")
                return None

            if guess < 0 or guess > 3000:
                if self.ws_handler:
                    await self.ws_handler.send_error(player_id, "Guess out of allowed range (0-3000 km)")
                return None

            answer_to_store = guess
            answer_for_history = guess
            answer_for_response = guess

        is_first_submission = player_id not in game.answer_submissions
        game.answers[player_id] = answer_to_store
        submitted_at = datetime.now()
        game.answer_submissions[player_id] = submitted_at
        if player_id not in game.answer_submission_history:
            game.answer_submission_history[player_id] = []
        game.answer_submission_history[player_id].append(
            {
                "guess": answer_for_history,
                "submitted_at": submitted_at.isoformat(),
            }
        )

        latency_ms = None
        if game.question_started_at and is_first_submission and question.question_variant != "sorting":
            latency_ms = int((submitted_at - game.question_started_at).total_seconds() * 1000)
            await self._update_bot_signals(game, player_id, int(answer_to_store), latency_ms)

        logger.info("Game %s: Received answer from %s: %s", game_id, game.players[player_id].name, answer_for_history)

        should_end_after_first = game.config.first_answer_ends_round and is_first_submission
        all_players_answered = len(game.answers) >= len(game.players)
        should_end_after_all = game.config.auto_advance_on_all_answers and all_players_answered
        if (should_end_after_first or should_end_after_all) and not game.round_resolution_in_progress:
            if game.answer_deadline_task and not game.answer_deadline_task.done():
                game.answer_deadline_task.cancel()
            await self.evaluate_answers(game_id)

        return {
            "answer": answer_for_response,
            "submitted_at": submitted_at.isoformat(),
            "updated": not is_first_submission,
        }

    async def _update_bot_signals(self, game: GameState, player_id: str, guess: int, latency_ms: int):
        """Track suspicious patterns to help detect automated play."""
        player = game.players[player_id]

        if latency_ms < 300:
            player.fast_answers += 1
            player.suspicion_score += 2

        if player.last_guess == guess:
            player.repeat_guess_streak += 1
        else:
            player.repeat_guess_streak = 1
        player.last_guess = guess

        if player.repeat_guess_streak >= 3:
            player.suspicion_score += 1

        player.answer_latencies_ms.append(latency_ms)
        if len(player.answer_latencies_ms) > 20:
            player.answer_latencies_ms.pop(0)

        if len(player.answer_latencies_ms) >= 5:
            mean_latency = statistics.fmean(player.answer_latencies_ms)
            std_latency = statistics.pstdev(player.answer_latencies_ms)
            if mean_latency < 1500 and std_latency < 120:
                player.suspicion_score += 2

        if player.suspicion_score >= 6 and not player.bot_flagged:
            player.bot_flagged = True
            host_id = game.host_player_id
            if self.ws_handler and host_id:
                await self.ws_handler.send_to_player(
                    host_id,
                    {
                        "type": "bot_suspected",
                        "player_id": player_id,
                        "player_name": player.name,
                        "suspicion_score": player.suspicion_score,
                        "fast_answers": player.fast_answers,
                    },
                )

    async def evaluate_answers(self, game_id: str):
        """Evaluate all submitted answers"""
        game = self.game_room.get_game(game_id)
        if not game or game.status != GameStatus.ACTIVE or not game.current_question:
            return
        if game.round_resolution_in_progress:
            return

        game.round_resolution_in_progress = True

        question = game.current_question
        is_sorting = question.question_variant == "sorting"
        correct_distance = question.distance
        correct_order = question.correct_order if is_sorting else []

        def sorting_difference(answer: Any) -> int:
            if not isinstance(answer, list) or len(answer) != len(correct_order):
                return 10_000
            return sum(1 for idx, value in enumerate(answer) if value != correct_order[idx])

        empty_round_review = {
            "round": game.current_round,
            "question_type": question.question_variant,
            "question": (
                (
                    question.sorting_prompt
                    if question.sorting_order == "custom" and question.sorting_prompt
                    else f"Sortiere die Zahlen {'absteigend' if question.sorting_order == 'desc' else 'aufsteigend'}"
                )
                if is_sorting
                else (
                    f"Wie lang ist die Straßenentfernung von {question.city1} nach {question.city2}?"
                    if question.question_variant == "road"
                    else f"Wie weit ist es von {question.city1} nach {question.city2}?"
                )
            ),
            "cities": [question.city1, question.city2],
            "correct_distance": correct_distance if not is_sorting else None,
            "correct_order": correct_order if is_sorting else None,
            "winner": "Keine Antwort",
            "submissions": [
                {
                    "player_id": player.id,
                    "player_name": player.name,
                    "final_guess": None,
                    "final_submitted_at": None,
                    "received_answers": game.answer_submission_history.get(player.id, []),
                }
                for player in game.players.values()
            ],
        }

        if len(game.answers) < 1:
            logger.info(f"Game {game_id}: No valid answers received")
            if game.warmup_active:
                game.warmup_active = False
                game.status = GameStatus.WAITING
                for player in game.players.values():
                    player.ready = False
                if self.ws_handler:
                    await self.ws_handler.broadcast_to_game(
                        game_id,
                        "warmup_result",
                        {"message": "No warmup answers received"},
                    )
                    await self.ws_handler.broadcast_players_update(game_id)
                return

            game.round_history.append(empty_round_review)

            await self.pause_and_continue(game_id)
            return

        # Calculate differences and find winner
        previous_standings = sorted(
            game.players.values(),
            key=lambda p: (-p.score, p.name.lower(), p.id),
        )
        previous_rank = {player.id: index + 1 for index, player in enumerate(previous_standings)}
        previous_leader_score = previous_standings[0].score if previous_standings else 0
        diffs = {
            pid: (sorting_difference(answer) if is_sorting else abs(int(answer) - correct_distance))
            for pid, answer in game.answers.items()
        }
        winner_id = min(diffs, key=diffs.get)
        winner = game.players[winner_id]
        winner_guess = game.answers[winner_id]
        round_deltas: Dict[str, int] = {pid: 0 for pid in game.players.keys()}
        bonus_events: List[Dict[str, Any]] = []
        winner_diff_value = sorting_difference(winner_guess) if is_sorting else abs(int(winner_guess) - correct_distance)
        closest_result: Dict[str, Any] = {
            "player_name": winner.name,
        }
        if is_sorting:
            closest_result["difference_positions"] = winner_diff_value
        else:
            closest_result["guess"] = int(winner_guess)
            closest_result["difference_km"] = winner_diff_value
        biggest_miss_id = max(diffs, key=diffs.get)
        biggest_miss_player = game.players[biggest_miss_id]
        biggest_miss_answer = game.answers[biggest_miss_id]
        biggest_miss_result: Dict[str, Any] = {
            "player_name": biggest_miss_player.name,
        }
        if is_sorting:
            biggest_miss_result["difference_positions"] = diffs[biggest_miss_id]
            biggest_miss_result["guess"] = biggest_miss_answer
        else:
            biggest_miss_result["difference_km"] = diffs[biggest_miss_id]
            biggest_miss_result["guess"] = int(biggest_miss_answer)
        precision_bonus_payload: Optional[Dict[str, Any]] = None
        comeback_payload: Optional[Dict[str, Any]] = None
        if not game.warmup_active:
            winner.score += 1
            round_deltas[winner_id] = 1

            # Track winning streaks to reward momentum and keep rounds exciting.
            for player in game.players.values():
                if player.id == winner_id:
                    player.win_streak += 1
                else:
                    player.win_streak = 0

            if winner.win_streak > 0 and winner.win_streak % 3 == 0:
                winner.score += 1
                round_deltas[winner_id] = round_deltas.get(winner_id, 0) + 1
                bonus_events.append(
                    {
                        "type": "streak_bonus",
                        "player_id": winner.id,
                        "player_name": winner.name,
                        "points": 1,
                        "streak": winner.win_streak,
                    }
                )

            if not is_sorting:
                winner_diff_km = winner_diff_value
                if winner_diff_km <= 20:
                    winner.score += 1
                    round_deltas[winner_id] = round_deltas.get(winner_id, 0) + 1
                    precision_bonus_payload = {
                        "player_id": winner.id,
                        "player_name": winner.name,
                        "points": 1,
                        "distance_error_km": winner_diff_km,
                    }
                    bonus_events.append(
                        {
                            "type": "perfect_hit_bonus",
                            **precision_bonus_payload,
                        }
                    )

            if game.config.wrong_answer_points_others:
                for submitted_player_id, submitted_guess in game.answers.items():
                    if submitted_guess == correct_distance:
                        continue
                    for other_player in game.players.values():
                        if other_player.id == submitted_player_id:
                            continue
                        other_player.score += 1
                        round_deltas[other_player.id] = round_deltas.get(other_player.id, 0) + 1

            updated_standings = sorted(
                game.players.values(),
                key=lambda p: (-p.score, p.name.lower(), p.id),
            )
            updated_rank = {player.id: index + 1 for index, player in enumerate(updated_standings)}
            best_rank_gain = 0
            best_rank_gain_player: Optional[Player] = None
            for player in updated_standings:
                old_rank = previous_rank.get(player.id, updated_rank[player.id])
                rank_gain = old_rank - updated_rank[player.id]
                if rank_gain > best_rank_gain and round_deltas.get(player.id, 0) > 0:
                    best_rank_gain = rank_gain
                    best_rank_gain_player = player

            if best_rank_gain_player and best_rank_gain > 0:
                trailing_before = previous_leader_score - next(
                    (p.score for p in previous_standings if p.id == best_rank_gain_player.id),
                    previous_leader_score,
                )
                comeback_payload = {
                    "player_name": best_rank_gain_player.name,
                    "rank_gain": best_rank_gain,
                    "from_rank": previous_rank[best_rank_gain_player.id],
                    "to_rank": updated_rank[best_rank_gain_player.id],
                    "points_behind_before": trailing_before,
                }

        round_review = {
            "round": game.current_round,
            "question_type": question.question_variant,
            "question": (
                f"Sortiere die Zahlen {'absteigend' if question.sorting_order == 'desc' else 'aufsteigend'}"
                if is_sorting
                else (
                    f"Wie lang ist die Straßenentfernung von {question.city1} nach {question.city2}?"
                    if question.question_variant == "road"
                    else f"Wie weit ist es von {question.city1} nach {question.city2}?"
                )
            ),
            "cities": [question.city1, question.city2],
            "correct_distance": correct_distance if not is_sorting else None,
            "correct_order": correct_order if is_sorting else None,
            "winner": winner.name,
            "submissions": [],
        }

        for player in game.players.values():
            submission_events = game.answer_submission_history.get(player.id, [])
            round_review["submissions"].append(
                {
                    "player_id": player.id,
                    "player_name": player.name,
                    "final_guess": game.answers.get(player.id),
                    "final_submitted_at": game.answer_submissions.get(player.id).isoformat() if player.id in game.answer_submissions else None,
                    "received_answers": submission_events,
                }
            )

        # Calculate and persist accuracy for every submitted answer in this round
        winner_accuracy_pct = (
            (100.0 if sorting_difference(winner_guess) == 0 else max(0.0, 100.0 - (sorting_difference(winner_guess) / max(1, len(correct_order))) * 100.0))
            if is_sorting
            else game.calculate_accuracy_percentage(int(winner_guess), correct_distance)
        )

        logger.info(
            "Game %s Round %s: %s won with answer %s (accuracy: %.2f%%)",
            game_id,
            game.current_round,
            winner.name,
            winner_guess,
            winner_accuracy_pct,
        )

        if not game.warmup_active and not is_sorting:
            with SessionLocal() as db:
                for submitted_player_id, submitted_guess in game.answers.items():
                    submitted_player = game.players.get(submitted_player_id)
                    if not submitted_player:
                        continue

                    accuracy_pct = game.calculate_accuracy_percentage(submitted_guess, correct_distance)
                    result_data = {
                        "game_id": game_id,
                        "player_name": submitted_player.name,
                        "guess": submitted_guess,
                        "correct_distance": correct_distance,
                        "accuracy_percentage": accuracy_pct,
                        "city1": question.city1,
                        "city2": question.city2,
                        "round_number": game.current_round,
                    }
                    save_game_result(db, result_data)

        if self.ws_handler:
            standings = sorted(
                game.players.values(),
                key=lambda p: p.score,
                reverse=True,
            )
            await self.ws_handler.broadcast_to_game(
                game_id,
                "round_result",
                {
                    "round": game.current_round,
                    "question_variant": question.question_variant,
                    "winner": winner.name,
                    "correct_distance": correct_distance if not is_sorting else None,
                    "correct_order": correct_order if is_sorting else None,
                    "closest_result": closest_result,
                    "biggest_miss": biggest_miss_result,
                    "precision_bonus": precision_bonus_payload,
                    "comeback_highlight": comeback_payload,
                    "bonus_events": bonus_events,
                    "standings": [
                        {
                            "player_id": p.id,
                            "player_name": p.name,
                            "score": p.score,
                            "delta": round_deltas.get(p.id, 0),
                        }
                        for p in standings
                    ],
                },
            )

        if not game.warmup_active:
            game.round_history.append(round_review)

        if game.warmup_active:
            game.warmup_active = False
            game.status = GameStatus.WAITING
            game.answers = {}
            game.answer_submissions = {}
            game.answer_submission_history = {}
            game.answer_time_remaining = 0
            game.question_started_at = None
            for player in game.players.values():
                player.ready = False
            if self.ws_handler:
                await self.ws_handler.broadcast_to_game(
                    game_id,
                    "warmup_result",
                    {
                        "winner": winner.name,
                        "correct_distance": correct_distance if not is_sorting else None,
                        "correct_order": correct_order if is_sorting else None,
                        "guess": winner_guess,
                        "message": "Warmup complete. Ready up for the real game.",
                    },
                )
                await self.ws_handler.broadcast_players_update(game_id)
            return

        await self.pause_and_continue(game_id)

    async def pause_and_continue(self, game_id: str):
        """Pause between rounds and pre-load next question during pause"""
        game = self.game_room.get_game(game_id)
        if not game:
            return

        game.status = GameStatus.PAUSED

        # Enforce minimum pause time (1.5s) to allow client map rendering
        pause_seconds = max(1.5, game.config.pause_between_rounds_seconds)
        
        # Pre-load next question during pause in separate variable
        if game.current_round < game.config.max_rounds:
            next_question = await self._assign_random_question_for_preload(game)
            if next_question:
                game.next_question_preloaded = next_question
            else:
                logger.error(f"Failed to pre-load next question for game {game_id}")
        
        # Wait for pause period
        await asyncio.sleep(pause_seconds)
        await self.next_round(game_id)

    async def end_game(self, game_id: str):
        """End the current game and save high scores"""
        game = self.game_room.get_game(game_id)
        if not game or game.status == GameStatus.FINISHED:
            return

        logger.info(f"Game {game_id} ended")

        # Calculate final scores and accuracy for each player
        final_scores = {}
        with SessionLocal() as db:
            for player in game.players.values():
                # Get player's results for this game session
                results = db.query(DBGameResult).filter(
                    DBGameResult.game_id == game_id,
                    DBGameResult.player_name == player.name
                ).all()

                if results:
                    avg_accuracy = sum(r.accuracy_percentage for r in results) / len(results)
                    # Only save high scores for players who have results/score
                    if player.score > 0:
                        save_high_score(db, player.name, player.score, game.current_round, avg_accuracy)
                    final_scores[player.name] = {
                        "score": player.score,
                        "avg_accuracy": round(avg_accuracy, 1)
                    }
                else:
                    if player.score > 0:
                        save_high_score(db, player.name, player.score, game.current_round, 0.0)
                    # Include players with no results (0 score, no accuracy)
                    final_scores[player.name] = {
                        "score": player.score,
                        "avg_accuracy": 0.0
                    }

        game.status = GameStatus.FINISHED
        
        # Broadcast game end message to all players
        if self.ws_handler:
            await self.ws_handler.broadcast_to_game(game_id, "game_finished", {
                "message": "Game finished!",
                "final_scores": final_scores,
                "winner": max(game.players.values(), key=lambda p: p.score).name if game.players else "No winner",
                "round_history": game.round_history,
            })

    def get_game_status(self, game_id: str) -> Optional[Dict]:
        """Get current game status"""
        game = self.game_room.get_game(game_id)
        if not game:
            return None

        return {
            "id": game.id,
            "status": game.status.value,
            "current_round": game.current_round,
            "max_rounds": game.config.max_rounds,
            "players": [
                {
                    "name": p.name,
                    "ready": p.ready,
                    "score": p.score
                } for p in game.players.values()
            ],
            "current_question": {
                "cities": game.current_question.cities if game.current_question else None,
                "question": (
                    f"Sortiere die Zahlen {'absteigend' if game.current_question.sorting_order == 'desc' else 'aufsteigend'}"
                    if game.current_question and game.current_question.question_variant == "sorting"
                    else (
                        f"Wie weit ist es von {game.current_question.cities[0]} nach {game.current_question.cities[1]}? (in km)"
                        if game.current_question
                        else None
                    )
                )
            } if game.current_question else None
        }
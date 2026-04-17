import random
import asyncio
from typing import List, Dict, Tuple, Optional
from datetime import datetime
import statistics
from models import GameState, Player, CityPair, GameStatus, GameRoom
from database import get_city_pairs, save_game_result, save_high_score, SessionLocal, DBGameResult
import uuid
from config import config
import logging

logger = logging.getLogger(__name__)


class GameLogic:
    def __init__(self, game_room: GameRoom, ws_handler=None):
        self.game_room = game_room
        self.ws_handler = ws_handler
        
    def set_ws_handler(self, ws_handler):
        """Set the WebSocket handler for broadcasting messages"""
        self.ws_handler = ws_handler

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
            game.status = GameStatus.ACTIVE
            game.pause_reason = None

            question = await self._assign_random_question(game)
            if not question:
                await self.end_game(game_id)
                return False

            game.answer_time_remaining = game.config.answer_time_seconds
            game.question_started_at = datetime.now()

            logger.info(
                f"Game {game_id}: New question: {game.current_question.cities[0]} to {game.current_question.cities[1]}, correct distance: {game.current_question.distance} km"
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
        with SessionLocal() as db:
            city_pairs = get_city_pairs(db)
            if not city_pairs:
                logger.error(f"No city pairs available for game {game.id}")
                return None

            db_city_pair = random.choice(city_pairs)
            game.current_question = CityPair(
                id=db_city_pair.id,
                city1=db_city_pair.city1,
                city2=db_city_pair.city2,
                distance=db_city_pair.distance,
                lat1=db_city_pair.lat1,
                lon1=db_city_pair.lon1,
                lat2=db_city_pair.lat2,
                lon2=db_city_pair.lon2,
                question_id=str(uuid.uuid4().hex[:8]),
            )
        return game.current_question

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
            data = {
                "question_id": str(question.question_id),
                "round": game.current_round,
                "max_rounds": game.config.max_rounds,
                "time_limit": game.config.answer_time_seconds,
                "cities": [question.city1, question.city2],
                "city1": question.city1,
                "city2": question.city2,
                "question": f"Wie weit ist es von {question.city1} nach {question.city2}? (in km)",
                "coordinates": {
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
                },
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

    async def submit_answer(self, game_id: str, player_id: str, guess: int) -> Optional[Dict]:
        """Submit player's answer"""
        game = self.game_room.get_game(game_id)
        if not game or game.status != GameStatus.ACTIVE or player_id not in game.players:
            return None

        if guess < 0 or guess > 3000:
            if self.ws_handler:
                await self.ws_handler.send_error(player_id, "Guess out of allowed range (0-3000 km)")
            return None

        is_first_submission = player_id not in game.answer_submissions
        game.answers[player_id] = guess
        submitted_at = datetime.now()
        game.answer_submissions[player_id] = submitted_at
        if player_id not in game.answer_submission_history:
            game.answer_submission_history[player_id] = []
        game.answer_submission_history[player_id].append(
            {
                "guess": guess,
                "submitted_at": submitted_at.isoformat(),
            }
        )

        latency_ms = None
        if game.question_started_at and is_first_submission:
            latency_ms = int((submitted_at - game.question_started_at).total_seconds() * 1000)
            await self._update_bot_signals(game, player_id, guess, latency_ms)

        logger.info(f"Game {game_id}: Received guess from {game.players[player_id].name}: {guess} km")

        return {
            "guess": guess,
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

        question = game.current_question
        correct_distance = question.distance

        empty_round_review = {
            "round": game.current_round,
            "question": f"Wie weit ist es von {question.city1} nach {question.city2}?",
            "cities": [question.city1, question.city2],
            "correct_distance": correct_distance,
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
        diffs = {pid: abs(guess - correct_distance) for pid, guess in game.answers.items()}
        winner_id = min(diffs, key=diffs.get)
        winner = game.players[winner_id]
        round_deltas: Dict[str, int] = {pid: 0 for pid in game.players.keys()}
        if not game.warmup_active:
            winner.score += 1
            round_deltas[winner_id] = 1

        round_review = {
            "round": game.current_round,
            "question": f"Wie weit ist es von {question.city1} nach {question.city2}?",
            "cities": [question.city1, question.city2],
            "correct_distance": correct_distance,
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

        # Calculate accuracy percentage for winner
        winner_guess = game.answers[winner_id]
        accuracy_pct = game.calculate_accuracy_percentage(winner_guess, correct_distance)

        logger.info(f"Game {game_id} Round {game.current_round}: {winner.name} won with guess {winner_guess} km (accuracy: {accuracy_pct:.2f}%)")

        if not game.warmup_active:
            # Save result to database
            result_data = {
                "game_id": game_id,
                "player_name": winner.name,
                "guess": winner_guess,
                "correct_distance": correct_distance,
                "accuracy_percentage": accuracy_pct,
                "city1": question.city1,
                "city2": question.city2,
                "round_number": game.current_round,
            }

            with SessionLocal() as db:
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
                    "winner": winner.name,
                    "correct_distance": correct_distance,
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
                        "correct_distance": correct_distance,
                        "guess": winner_guess,
                        "message": "Warmup complete. Ready up for the real game.",
                    },
                )
                await self.ws_handler.broadcast_players_update(game_id)
            return

        await self.pause_and_continue(game_id)

    async def pause_and_continue(self, game_id: str):
        """Pause between rounds"""
        game = self.game_room.get_game(game_id)
        if not game:
            return

        game.status = GameStatus.PAUSED
        await asyncio.sleep(game.config.pause_between_rounds_seconds)
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
                "question": f"Wie weit ist es von {game.current_question.cities[0]} nach {game.current_question.cities[1]}? (in km)" if game.current_question else None
            } if game.current_question else None
        }
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from fastapi import WebSocket
from models import Player, GameRoom, GameConfig, GameStatus
from game_logic import GameLogic
from pydantic import BaseModel, ValidationError
import uuid
import httpx
from config import config
from database import is_captcha_valid, save_captcha_validation, get_db, delete_expired_captcha_validations

logger = logging.getLogger(__name__)


class WebSocketMessage(BaseModel):
    type: str
    data: Dict[str, Any] = {}


class SetNameMessage(BaseModel):
    name: str


class SetReadyMessage(BaseModel):
    ready: bool


class SubmitAnswerMessage(BaseModel):
    guess: int


class CreateGameMessage(BaseModel):
    game_id: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class JoinGameMessage(BaseModel):
    game_id: str
    pin: Optional[str] = None


class KickPlayerMessage(BaseModel):
    target_player_id: str


class LockSettingsMessage(BaseModel):
    locked: bool


class UpdateSettingsMessage(BaseModel):
    max_rounds: int
    countdown_seconds: int
    answer_time_seconds: int
    pause_between_rounds_seconds: int
    auto_advance_on_all_answers: bool = True
    first_answer_ends_round: bool = False
    wrong_answer_points_others: bool = False
    enable_road_questions: bool = True
    road_question_ratio_percent: int = 50


class SubmitCaptchaMessage(BaseModel):
    """Message for submitting hCaptcha token"""
    hcaptcha_token: str


class WebSocketHandler:
    def __init__(self, game_room: GameRoom, game_logic: GameLogic, default_config: Optional[GameConfig] = None):
        self.game_room = game_room
        self.game_logic = game_logic
        self.default_config = default_config or GameConfig()
        # Track multiple connections per player (for multiple tabs)
        self.active_connections: Dict[str, list] = {}
        # Delay final cleanup to allow fast reload reconnects.
        self.pending_disconnect_tasks: Dict[str, asyncio.Task] = {}
        self.disconnect_grace_seconds = 12

    async def connect(self, websocket: WebSocket) -> str:
        """Handle new WebSocket connection"""
        await websocket.accept()

        requested_player_id = websocket.query_params.get("player_id")

        # Restore known player session (e.g. hard reload) when possible.
        if requested_player_id and requested_player_id in self.game_room.players:
            player = self.game_room.players[requested_player_id]
            player_id = player.id

            if player_id in self.pending_disconnect_tasks:
                self.pending_disconnect_tasks[player_id].cancel()
                del self.pending_disconnect_tasks[player_id]

            if player_id not in self.active_connections:
                self.active_connections[player_id] = []
            self.active_connections[player_id].append(websocket)

            player.websocket = websocket
            player.tab_away = False

            logger.info(
                "Player %s reconnected (ID: %s), Total connections: %s",
                player.name,
                player_id,
                len(self.active_connections[player_id]),
            )

            await self.send_to_player(
                player_id,
                {
                    "type": "session_restored",
                    "player_id": player_id,
                    "name": player.name,
                    "game_id": player.game_id,
                },
            )

            if player.game_id:
                await self.game_logic.resume_after_player_return(player.game_id)
                await self.send_game_info(player_id, player.game_id)
                await self.broadcast_players_update(player.game_id)
            else:
                await self.send_lobby_info(player_id)

            return player_id

        # Generate unique player ID
        player_id = f"player_{uuid.uuid4().hex[:8]}"
        player = Player(
            id=player_id,
            name=f"Spieler_{player_id[-4:]}",
            websocket=websocket,
        )

        self.game_room.players[player_id] = player

        # Add websocket to player's connections list
        if player_id not in self.active_connections:
            self.active_connections[player_id] = []
        self.active_connections[player_id].append(websocket)

        logger.info(
            "Player %s connected (ID: %s), Total connections: %s",
            player.name,
            player_id,
            len(self.active_connections[player_id]),
        )

        # Send initial lobby info
        await self.send_lobby_info(player_id)

        return player_id

    async def _cleanup_disconnected_player(self, player_id: str):
        """Remove player after grace period if they did not reconnect."""
        try:
            await asyncio.sleep(self.disconnect_grace_seconds)

            if self.active_connections.get(player_id):
                return

            player = self.game_room.players.get(player_id)
            if player and player.game_id:
                game_id = player.game_id
                game = self.game_room.get_game(game_id)
                if game:
                    game.remove_player(player_id)
                    await self.broadcast_players_update(game_id)
                    if game.is_empty():
                        self.game_room.delete_game(game_id)

            if player_id in self.active_connections:
                del self.active_connections[player_id]

            if player_id in self.game_room.players:
                del self.game_room.players[player_id]

            await self.broadcast_lobby_info_all()
            logger.info("Player %s fully disconnected (all tabs closed)", player_id)
        except asyncio.CancelledError:
            logger.debug("Disconnect cleanup cancelled for %s", player_id)
        finally:
            if player_id in self.pending_disconnect_tasks:
                del self.pending_disconnect_tasks[player_id]

    async def disconnect(self, player_id: str, websocket: WebSocket):
        """Handle WebSocket disconnection"""
        if player_id in self.active_connections:
            # Remove this specific websocket connection
            if websocket in self.active_connections[player_id]:
                self.active_connections[player_id].remove(websocket)
                logger.info(
                    "Websocket disconnected for %s, remaining connections: %s",
                    player_id,
                    len(self.active_connections[player_id]),
                )

            # If no more connections exist, mark away and schedule deferred cleanup.
            if not self.active_connections[player_id]:
                player = self.game_room.players.get(player_id)
                if player and player.game_id:
                    player.tab_away = True
                    await self.game_logic.pause_for_reconnect(player.game_id, player.name)
                    await self.broadcast_to_game(
                        player.game_id,
                        "player_tab_left",
                        {"player_id": player_id, "name": player.name},
                    )
                    await self.broadcast_players_update(player.game_id)

                if player_id not in self.pending_disconnect_tasks:
                    self.pending_disconnect_tasks[player_id] = asyncio.create_task(
                        self._cleanup_disconnected_player(player_id)
                    )

    async def handle_message(self, player_id: str, message_data: str):
        """Handle incoming WebSocket message"""
        try:
            try:
                message = WebSocketMessage.parse_raw(message_data)
            except TypeError as te:
                logger.error("TypeError parsing message (likely dict as key): %s, raw_data=%s", te, message_data)
                raise
            msg_type = message.type

            if msg_type == "create_game":
                await self.handle_create_game(player_id, message.data)
            elif msg_type == "join_game":
                await self.handle_join_game(player_id, message.data)
            elif msg_type == "leave_game":
                await self.handle_leave_game(player_id)
            elif msg_type == "set_name":
                await self.handle_set_name(player_id, message.data)
            elif msg_type == "submit_captcha":
                await self.handle_submit_captcha(player_id, message.data)
            elif msg_type == "tab_leaving":
                await self.handle_tab_leaving(player_id)
            elif msg_type == "tab_active":
                await self.handle_tab_active(player_id)
            elif msg_type == "set_ready":
                await self.handle_set_ready(player_id, message.data)
            elif msg_type == "kick_player":
                await self.handle_kick_player(player_id, message.data)
            elif msg_type == "lock_settings":
                await self.handle_lock_settings(player_id, message.data)
            elif msg_type == "update_settings":
                await self.handle_update_settings(player_id, message.data)
            elif msg_type == "start_warmup":
                await self.handle_start_warmup(player_id)
            elif msg_type == "submit_answer":
                await self.handle_submit_answer(player_id, message.data)
            elif msg_type == "start_game":
                await self.handle_start_game(player_id)
            else:
                logger.warning("Unknown message type: %s", msg_type)
                await self.send_error(player_id, "Unknown message type")

        except ValidationError as e:
            logger.error(
                "Invalid message format from %s. payload=%r validation=%s",
                player_id,
                message_data,
                e,
            )
            await self.send_error(player_id, "Invalid message format")
        except json.JSONDecodeError:
            logger.error("Invalid JSON received")
            await self.send_error(player_id, "Invalid JSON")
        except Exception as e:
            logger.error("Error handling message: %s", e)
            await self.send_error(player_id, "Internal server error")

    async def handle_create_game(self, player_id: str, data: Dict[str, Any]):
        """Handle game creation"""
        try:
            db = next(get_db())
            try:
                if not is_captcha_valid(db, player_id):
                    await self.send_error(player_id, "Please complete the CAPTCHA first")
                    return
            finally:
                db.close()

            create_msg = CreateGameMessage.parse_obj(data)
            game_id = create_msg.game_id or f"game_{uuid.uuid4().hex[:8]}"

            requested_config = create_msg.config or {}

            def _int_setting(key: str, default: int, min_value: int, max_value: int) -> int:
                raw = requested_config.get(key, default)
                try:
                    value = int(raw)
                except (TypeError, ValueError):
                    return default
                return max(min_value, min(max_value, value))

            def _bool_setting(key: str, default: bool) -> bool:
                raw = requested_config.get(key, default)
                if isinstance(raw, bool):
                    return raw
                if isinstance(raw, str):
                    return raw.strip().lower() in {"1", "true", "yes", "on"}
                return bool(raw)

            # Start new games with admin defaults but allow validated creator overrides.
            config = GameConfig(
                max_rounds=_int_setting("max_rounds", self.default_config.max_rounds, 1, 20),
                countdown_seconds=_int_setting("countdown_seconds", self.default_config.countdown_seconds, 1, 30),
                answer_time_seconds=_int_setting("answer_time_seconds", self.default_config.answer_time_seconds, 5, 180),
                pause_between_rounds_seconds=_int_setting(
                    "pause_between_rounds_seconds",
                    self.default_config.pause_between_rounds_seconds,
                    1,
                    30,
                ),
                auto_advance_on_all_answers=_bool_setting(
                    "auto_advance_on_all_answers",
                    self.default_config.auto_advance_on_all_answers,
                ),
                first_answer_ends_round=_bool_setting(
                    "first_answer_ends_round",
                    self.default_config.first_answer_ends_round,
                ),
                wrong_answer_points_others=_bool_setting(
                    "wrong_answer_points_others",
                    self.default_config.wrong_answer_points_others,
                ),
                enable_road_questions=_bool_setting(
                    "enable_road_questions",
                    self.default_config.enable_road_questions,
                ),
                road_question_ratio_percent=_int_setting(
                    "road_question_ratio_percent",
                    self.default_config.road_question_ratio_percent,
                    0,
                    100,
                ),
            )

            game = self.game_room.create_game(game_id, config)

            player = self.game_room.players[player_id]
            player.tab_away = False
            self.game_room.add_player_to_game(player, game_id)

            logger.info("Player %s created game %s", player.name, game_id)
            await self.send_to_player(
                player_id,
                {"type": "game_created", "game_id": game_id, "pin": game.pin},
            )
            await self.send_game_info(player_id, game_id)
            await self.broadcast_lobby_info_all()

        except ValidationError:
            await self.send_error(player_id, "Invalid game creation data")

    async def handle_join_game(self, player_id: str, data: Dict[str, Any]):
        """Handle joining a game"""
        try:
            # Check if player has valid captcha
            db = next(get_db())
            try:
                if not is_captcha_valid(db, player_id):
                    await self.send_error(player_id, "Please complete the CAPTCHA first")
                    return
            finally:
                db.close()

            join_msg = JoinGameMessage.parse_obj(data)
            game_id = join_msg.game_id

            game = self.game_room.get_game(game_id)
            
            # Check if game exists
            if not game:
                await self.send_error(player_id, f"Game {game_id} not found")
                return
            
            # Validate PIN if game has one
            if game.pin and join_msg.pin != game.pin:
                await self.send_error(player_id, "Invalid PIN")
                return
            
            if game.settings_locked:
                await self.send_error(player_id, "Host has locked the lobby")
                return

            player = self.game_room.players[player_id]
            success = self.game_room.add_player_to_game(player, game_id)

            if success:
                player.tab_away = False
                logger.info("Player %s joined game %s", player.name, game_id)
                await self.send_to_player(player_id, {"type": "game_joined", "game_id": game_id})
                await self.send_game_info(player_id, game_id)
                await self.broadcast_players_update(game_id)
                await self.broadcast_lobby_info_all()
            else:
                await self.send_error(player_id, f"Cannot join game {game_id}")

        except ValidationError:
            await self.send_error(player_id, "Invalid game join data")

    async def handle_submit_captcha(self, player_id: str, data: Dict[str, Any]):
        """Verify an hCaptcha token and persist the validation."""
        try:
            logger.debug("Received captcha submission data: %s (type: %s)", data, type(data).__name__)
            submit_msg = SubmitCaptchaMessage.parse_obj(data)
            player = self.game_room.players.get(player_id)

            if not player:
                await self.send_error(player_id, "Player not found")
                return

            if not config.HCAPTCHA_SECRET_KEY:
                logger.error("HCAPTCHA_SECRET_KEY is not configured")
                await self.send_error(player_id, "CAPTCHA configuration is incomplete")
                return

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        config.HCAPTCHA_VERIFY_URL,
                        data={
                            "secret": config.HCAPTCHA_SECRET_KEY,
                            "response": submit_msg.hcaptcha_token,
                        },
                        timeout=5,
                    )
                response.raise_for_status()
                verification = response.json()
            except httpx.HTTPError as exc:
                logger.error("Error verifying hCaptcha token: %s", exc)
                await self.send_error(player_id, "Error verifying CAPTCHA. Please try again.")
                return

            if not verification.get("success"):
                logger.warning(
                    "hCaptcha verification failed for %s: %s",
                    player_id,
                    verification.get("error-codes", []),
                )
                await self.send_error(player_id, "CAPTCHA verification failed. Please try again.")
                return

            db = next(get_db())
            try:
                delete_expired_captcha_validations(db)
                expiry = datetime.utcnow() + timedelta(days=1)
                save_captcha_validation(
                    db,
                    player_id,
                    "hcaptcha",
                    verification.get("challenge_ts", "verified"),
                    expiry,
                )

                await self.send_to_player(
                    player_id,
                    {
                        "type": "captcha_validated",
                        "message": "CAPTCHA verified successfully!",
                    },
                )
            finally:
                db.close()

        except ValidationError as e:
            logger.error("Validation error in captcha submission: %s", e)
            await self.send_error(player_id, "Invalid CAPTCHA token format")
        except Exception as e:
            logger.error("Error processing captcha submission: %s", e)
            await self.send_error(player_id, "Error processing CAPTCHA")

    async def handle_leave_game(self, player_id: str):
        """Handle leaving a game"""
        player = self.game_room.players.get(player_id)
        if player and player.game_id:
            game_id = player.game_id
            game = self.game_room.get_game(game_id)
            if game:
                game.remove_player(player_id)

                if game.is_empty():
                    self.game_room.delete_game(game_id)
                else:
                    await self.broadcast_players_update(game_id)

            player.game_id = None
            player.tab_away = False
            logger.info("Player %s left game %s", player.name, game_id)
            await self.send_lobby_info(player_id)
            await self.broadcast_lobby_info_all()

    async def handle_set_name(self, player_id: str, data: Dict[str, Any]):
        """Handle player name change"""
        logger.info("handle_set_name called for player_id: %s with data: %s", player_id, data)
        try:
            name_msg = SetNameMessage.parse_obj(data)
            if player_id in self.game_room.players:
                old_name = self.game_room.players[player_id].name
                self.game_room.players[player_id].name = name_msg.name
                self.game_room.players[player_id].tab_away = False
                logger.info("Player %s changed name to %s", old_name, name_msg.name)

                await self.send_to_player(
                    player_id,
                    {
                        "type": "name_set",
                        "player_id": player_id,
                        "name": name_msg.name,
                    },
                )

                player = self.game_room.players[player_id]
                if player.game_id:
                    await self.broadcast_to_game(
                        player.game_id,
                        "player_updated",
                        {
                            "player_id": player_id,
                            "name": name_msg.name,
                        },
                    )
            else:
                logger.warning("Player %s not found in game_room.players", player_id)
                await self.send_error(player_id, "Player not registered")

        except ValidationError as e:
            logger.error("Validation error in set_name: %s", e)
            await self.send_error(player_id, "Invalid name format")
        except Exception as e:
            logger.error("Error setting name: %s", e, exc_info=True)
            await self.send_error(player_id, "Error setting name")

    async def handle_tab_leaving(self, player_id: str):
        """Mark player as temporarily away when browser tab is hidden/closed."""
        player = self.game_room.players.get(player_id)
        if not player:
            return

        player.tab_away = True
        if player.game_id:
            await self.game_logic.pause_for_reconnect(player.game_id, player.name)
            await self.broadcast_to_game(
                player.game_id,
                "player_tab_left",
                {"player_id": player_id, "name": player.name},
            )
            await self.broadcast_players_update(player.game_id)

    async def handle_tab_active(self, player_id: str):
        """Clear away marker when player returns to the tab."""
        player = self.game_room.players.get(player_id)
        if not player:
            return

        if player.tab_away:
            player.tab_away = False
            if player.game_id:
                await self.game_logic.resume_after_player_return(player.game_id)
                await self.broadcast_players_update(player.game_id)

    async def handle_set_ready(self, player_id: str, data: Dict[str, Any]):
        """Handle player ready status change"""
        try:
            ready_msg = SetReadyMessage.parse_obj(data)
            player = self.game_room.players.get(player_id)
            if player and player.game_id:
                game = self.game_room.get_game(player.game_id)
                if game and player_id in game.players:
                    game.players[player_id].ready = ready_msg.ready
                    logger.info("Player %s ready status: %s", player.name, ready_msg.ready)

                    await self.broadcast_players_update(player.game_id)

                    if game.all_players_ready() and game.status == GameStatus.WAITING:
                        await self.start_countdown(player.game_id)

        except ValidationError:
            await self.send_error(player_id, "Invalid ready status")

    async def handle_kick_player(self, player_id: str, data: Dict[str, Any]):
        """Host can kick a player before countdown starts."""
        try:
            msg = KickPlayerMessage.parse_obj(data)
        except ValidationError:
            await self.send_error(player_id, "Invalid kick request")
            return

        host_player = self.game_room.players.get(player_id)
        if not host_player or not host_player.game_id:
            await self.send_error(player_id, "You are not in a game")
            return

        game = self.game_room.get_game(host_player.game_id)
        if not game or game.host_player_id != player_id:
            await self.send_error(player_id, "Only host can kick players")
            return

        if game.status != GameStatus.WAITING:
            await self.send_error(player_id, "Players can only be kicked before countdown")
            return

        if msg.target_player_id == player_id:
            await self.send_error(player_id, "Host cannot kick themselves")
            return

        target = game.players.get(msg.target_player_id)
        if not target:
            await self.send_error(player_id, "Player not found in this game")
            return

        game.remove_player(msg.target_player_id)
        target.game_id = None
        target.ready = False
        target.tab_away = False

        await self.send_to_player(
            msg.target_player_id,
            {"type": "kicked", "game_id": game.id, "message": "You were removed by the host"},
        )
        await self.send_lobby_info(msg.target_player_id)
        await self.broadcast_players_update(game.id)
        await self.broadcast_lobby_info_all()

    async def handle_lock_settings(self, player_id: str, data: Dict[str, Any]):
        """Host can lock/unlock settings in waiting state."""
        try:
            msg = LockSettingsMessage.parse_obj(data)
        except ValidationError:
            await self.send_error(player_id, "Invalid lock settings request")
            return

        host_player = self.game_room.players.get(player_id)
        if not host_player or not host_player.game_id:
            await self.send_error(player_id, "You are not in a game")
            return

        game = self.game_room.get_game(host_player.game_id)
        if not game or game.host_player_id != player_id:
            await self.send_error(player_id, "Only host can lock settings")
            return

        if game.status != GameStatus.WAITING:
            await self.send_error(player_id, "Settings can only be changed before countdown")
            return

        game.settings_locked = msg.locked
        await self.broadcast_players_update(game.id)

    async def handle_update_settings(self, player_id: str, data: Dict[str, Any]):
        """Host can update game settings before countdown starts."""
        try:
            msg = UpdateSettingsMessage.parse_obj(data)
        except ValidationError:
            await self.send_error(player_id, "Invalid update settings request")
            return

        host_player = self.game_room.players.get(player_id)
        if not host_player or not host_player.game_id:
            await self.send_error(player_id, "You are not in a game")
            return

        game = self.game_room.get_game(host_player.game_id)
        if not game or game.host_player_id != player_id:
            await self.send_error(player_id, "Only host can update settings")
            return

        if game.status != GameStatus.WAITING:
            await self.send_error(player_id, "Settings can only be changed before countdown")
            return

        if game.settings_locked:
            await self.send_error(player_id, "Settings are locked")
            return

        if not (1 <= msg.max_rounds <= 20):
            await self.send_error(player_id, "Invalid settings values")
            return
        if not (1 <= msg.countdown_seconds <= 30):
            await self.send_error(player_id, "Invalid settings values")
            return
        if not (5 <= msg.answer_time_seconds <= 180):
            await self.send_error(player_id, "Invalid settings values")
            return
        if not (1 <= msg.pause_between_rounds_seconds <= 30):
            await self.send_error(player_id, "Invalid settings values")
            return
        if not (0 <= msg.road_question_ratio_percent <= 100):
            await self.send_error(player_id, "Invalid settings values")
            return

        game.config = GameConfig(
            max_rounds=msg.max_rounds,
            countdown_seconds=msg.countdown_seconds,
            answer_time_seconds=msg.answer_time_seconds,
            pause_between_rounds_seconds=msg.pause_between_rounds_seconds,
            auto_advance_on_all_answers=msg.auto_advance_on_all_answers,
            first_answer_ends_round=msg.first_answer_ends_round,
            wrong_answer_points_others=msg.wrong_answer_points_others,
            enable_road_questions=msg.enable_road_questions,
            road_question_ratio_percent=msg.road_question_ratio_percent,
        )

        await self.broadcast_players_update(game.id)

    async def handle_start_warmup(self, player_id: str):
        """Host starts a non-scoring warmup round."""
        player = self.game_room.players.get(player_id)
        if not player or not player.game_id:
            await self.send_error(player_id, "You are not in a game")
            return

        game = self.game_room.get_game(player.game_id)
        if not game or game.host_player_id != player_id:
            await self.send_error(player_id, "Only host can start warmup")
            return

        if game.status != GameStatus.WAITING:
            await self.send_error(player_id, "Warmup only available before countdown")
            return

        ok = await self.game_logic.start_warmup_round(player.game_id)
        if not ok:
            await self.send_error(player_id, "Could not start warmup")

    async def handle_submit_answer(self, player_id: str, data: Dict[str, Any]):
        """Handle answer submission"""
        try:
            answer_msg = SubmitAnswerMessage.parse_obj(data)
            player = self.game_room.players.get(player_id)
            if player and player.game_id:
                game = self.game_room.get_game(player.game_id)
                if game and game.current_question:
                    submission_info = await self.game_logic.submit_answer(player.game_id, player_id, answer_msg.guess)
                    if submission_info:
                        await self.send_to_player(
                            player_id,
                            {
                                "type": "answer_received",
                                "guess": submission_info["guess"],
                                "submitted_at": submission_info["submitted_at"],
                                "updated": submission_info["updated"],
                            },
                        )
                else:
                    await self.send_error(player_id, "No active question")
            else:
                await self.send_error(player_id, "Not in a game")

        except ValidationError:
            await self.send_error(player_id, "Invalid answer format")

    async def handle_start_game(self, player_id: str):
        """Handle manual game start (host only)"""
        player = self.game_room.players.get(player_id)
        if player and player.game_id:
            game = self.game_room.get_game(player.game_id)
            if game and game.host_player_id == player_id:
                await self.start_countdown(player.game_id)

    async def start_countdown(self, game_id: str):
        """Start game countdown"""
        try:
            game = self.game_room.get_game(game_id)
            if not game:
                return

            game.status = GameStatus.COUNTDOWN
            await self.broadcast_lobby_info_all()
            await self.broadcast_to_game(game_id, "game_starting", {"countdown": game.config.countdown_seconds})

            for i in range(game.config.countdown_seconds, 0, -1):
                await self.broadcast_to_game(game_id, "countdown", {"value": i})
                await asyncio.sleep(1)

            await self.broadcast_to_game(game_id, "countdown", {"value": 0})
            await self.broadcast_to_game(
                game_id,
                "game_started",
                {
                    "config": {
                        "max_rounds": game.config.max_rounds,
                        "countdown_seconds": game.config.countdown_seconds,
                        "answer_time_seconds": game.config.answer_time_seconds,
                        "pause_between_rounds_seconds": game.config.pause_between_rounds_seconds,
                        "auto_advance_on_all_answers": game.config.auto_advance_on_all_answers,
                        "first_answer_ends_round": game.config.first_answer_ends_round,
                        "wrong_answer_points_others": game.config.wrong_answer_points_others,
                        "enable_road_questions": game.config.enable_road_questions,
                        "road_question_ratio_percent": game.config.road_question_ratio_percent,
                    }
                },
            )

            success = await self.game_logic.start_game(game_id)
            if not success:
                logger.warning("Failed to start game %s", game_id)
                await self.broadcast_to_game(game_id, "error", {"message": "Failed to start game"})
        except Exception as e:
            logger.error("Error in start_countdown: %s", e, exc_info=True)
            await self.broadcast_to_game(game_id, "error", {"message": f"Game error: {str(e)}"})

    async def send_lobby_info(self, player_id: str):
        """Send lobby information to player on all connections"""
        player = self.game_room.players.get(player_id)
        if not player:
            return

        lobby_data = {
            "type": "lobby_info",
            "active_games": self.game_room.list_active_games(),
            "started_games_count": self.game_room.started_games_count(),
            "player_name": player.name,
        }
        if player_id in self.active_connections:
            for websocket in self.active_connections[player_id]:
                try:
                    await websocket.send_text(json.dumps(lobby_data))
                except Exception as e:
                    logger.error("Failed to send lobby info to %s: %s", player_id, e)

    async def send_game_info(self, player_id: str, game_id: str):
        """Send game information to player on all connections"""
        game = self.game_room.get_game(game_id)
        if game and player_id in self.active_connections:
            is_host = player_id == game.host_player_id
            game_data = {
                "type": "game_info",
                "game_id": game_id,
                "status": game.status.value,
                "settings_locked": game.settings_locked,
                "config": {
                    "max_rounds": game.config.max_rounds,
                    "countdown_seconds": game.config.countdown_seconds,
                    "answer_time_seconds": game.config.answer_time_seconds,
                    "pause_between_rounds_seconds": game.config.pause_between_rounds_seconds,
                    "auto_advance_on_all_answers": game.config.auto_advance_on_all_answers,
                    "first_answer_ends_round": game.config.first_answer_ends_round,
                    "wrong_answer_points_others": game.config.wrong_answer_points_others,
                    "enable_road_questions": game.config.enable_road_questions,
                    "road_question_ratio_percent": game.config.road_question_ratio_percent,
                },
                "players": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "ready": p.ready,
                        "score": p.score,
                        "tab_away": p.tab_away,
                        "is_host": p.id == game.host_player_id,
                        "suspicion_score": p.suspicion_score,
                        "bot_flagged": p.bot_flagged,
                    }
                    for p in game.players.values()
                ],
                "is_host": is_host,
            }
            # Only show PIN to host
            if is_host:
                game_data["pin"] = game.pin
            
            for websocket in self.active_connections[player_id]:
                try:
                    await websocket.send_text(json.dumps(game_data))
                except Exception as e:
                    logger.error("Failed to send game info to %s: %s", player_id, e)

    async def broadcast_players_update(self, game_id: str):
        """Broadcast updated player list to all players in a game"""
        game = self.game_room.get_game(game_id)
        if not game:
            logger.warning("broadcast_players_update: Game %s not found", game_id)
            return

        logger.info("broadcast_players_update: Sending to %s players in game %s", len(game.players), game_id)

        for player in game.players.values():
            if player.id in self.active_connections:
                game_data = {
                    "type": "game_info",
                    "game_id": game_id,
                    "status": game.status.value,
                    "settings_locked": game.settings_locked,
                    "config": {
                        "max_rounds": game.config.max_rounds,
                        "countdown_seconds": game.config.countdown_seconds,
                        "answer_time_seconds": game.config.answer_time_seconds,
                        "pause_between_rounds_seconds": game.config.pause_between_rounds_seconds,
                        "auto_advance_on_all_answers": game.config.auto_advance_on_all_answers,
                        "first_answer_ends_round": game.config.first_answer_ends_round,
                        "wrong_answer_points_others": game.config.wrong_answer_points_others,
                        "enable_road_questions": game.config.enable_road_questions,
                        "road_question_ratio_percent": game.config.road_question_ratio_percent,
                    },
                    "players": [
                        {
                            "id": p.id,
                            "name": p.name,
                            "ready": p.ready,
                            "score": p.score,
                            "tab_away": p.tab_away,
                            "is_host": p.id == game.host_player_id,
                            "suspicion_score": p.suspicion_score,
                            "bot_flagged": p.bot_flagged,
                        }
                        for p in game.players.values()
                    ],
                    "is_host": player.id == game.host_player_id,
                }
                for websocket in self.active_connections[player.id]:
                    try:
                        await websocket.send_text(json.dumps(game_data))
                    except Exception as e:
                        logger.error("Failed to send game info to %s: %s", player.id, e)

    async def broadcast_to_game(self, game_id: str, message_type: str, data: Optional[Dict[str, Any]] = None):
        """Broadcast message to all players in a game"""
        game = self.game_room.get_game(game_id)
        if not game:
            return

        message = {"type": message_type}
        if data:
            message.update(data)

        for player in game.players.values():
            if player.id in self.active_connections:
                for websocket in self.active_connections[player.id]:
                    try:
                        await websocket.send_text(json.dumps(message))
                    except Exception as e:
                        logger.error("Failed to send message to %s: %s", player.id, e)

    async def send_to_player(self, player_id: str, data: Dict[str, Any]):
        """Send a message to a specific player on all active connections."""
        if player_id in self.active_connections:
            for websocket in self.active_connections[player_id]:
                try:
                    await websocket.send_text(json.dumps(data))
                except Exception as e:
                    logger.error("Failed to send message to %s: %s", player_id, e)

    async def send_error(self, player_id: str, error_message: str):
        """Send an error message to a specific player."""
        await self.send_to_player(player_id, {"type": "error", "message": error_message})

    async def broadcast_game_status(self, game_id: str):
        """Broadcast the current game status to all players in a game."""
        status = self.game_logic.get_game_status(game_id)
        if status:
            await self.broadcast_to_game(game_id, "game_status", status)

    async def broadcast_lobby_info_all(self):
        """Broadcast lobby information to all currently connected players."""
        for player_id in list(self.active_connections.keys()):
            if player_id in self.game_room.players:
                await self.send_lobby_info(player_id)

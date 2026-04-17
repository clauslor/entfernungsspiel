import json
import logging
import asyncio
from typing import Dict, Any, Optional
from fastapi import WebSocket, WebSocketDisconnect
from models import GameState, Player, GameRoom, GameConfig, GameStatus
from game_logic import GameLogic
from pydantic import BaseModel, ValidationError
import uuid

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


class WebSocketHandler:
    def __init__(self, game_room: GameRoom, game_logic: GameLogic):
        self.game_room = game_room
        self.game_logic = game_logic
        # Track multiple connections per player (for multiple tabs)
        self.active_connections: Dict[str, list] = {}

    async def connect(self, websocket: WebSocket) -> str:
        """Handle new WebSocket connection"""
        await websocket.accept()

        # Generate unique player ID
        player_id = f"player_{uuid.uuid4().hex[:8]}"
        player = Player(
            id=player_id,
            name=f"Spieler_{player_id[-4:]}",
            websocket=websocket
        )

        self.game_room.players[player_id] = player
        
        # Add websocket to player's connections list
        if player_id not in self.active_connections:
            self.active_connections[player_id] = []
        self.active_connections[player_id].append(websocket)

        logger.info(f"Player {player.name} connected (ID: {player_id}), Total connections: {len(self.active_connections[player_id])}")

        # Send initial lobby info
        await self.send_lobby_info(player_id)

        return player_id

    async def disconnect(self, player_id: str, websocket: WebSocket):
        """Handle WebSocket disconnection"""
        if player_id in self.active_connections:
            # Remove this specific websocket connection
            if websocket in self.active_connections[player_id]:
                self.active_connections[player_id].remove(websocket)
                logger.info(f"Websocket disconnected for {player_id}, remaining connections: {len(self.active_connections[player_id])}")
            
            # Only remove player from game if NO MORE connections exist for this player
            if not self.active_connections[player_id]:
                del self.active_connections[player_id]
                
                player = self.game_room.players.get(player_id)
                if player and player.game_id:
                    game = self.game_room.get_game(player.game_id)
                    if game:
                        game.remove_player(player_id)
                        # Broadcast updated player list to remaining players
                        await self.broadcast_players_update(player.game_id)

                        # If game becomes empty, clean it up
                        if game.is_empty():
                            self.game_room.delete_game(player.game_id)

                if player_id in self.game_room.players:
                    del self.game_room.players[player_id]

                logger.info(f"Player {player_id} fully disconnected (all tabs closed)")

    async def handle_message(self, player_id: str, message_data: str):
        """Handle incoming WebSocket message"""
        try:
            # Parse and validate message
            message = WebSocketMessage.parse_raw(message_data)
            msg_type = message.type

            if msg_type == "create_game":
                await self.handle_create_game(player_id, message.data)
            elif msg_type == "join_game":
                await self.handle_join_game(player_id, message.data)
            elif msg_type == "leave_game":
                await self.handle_leave_game(player_id)
            elif msg_type == "set_name":
                await self.handle_set_name(player_id, message.data)
            elif msg_type == "set_ready":
                await self.handle_set_ready(player_id, message.data)
            elif msg_type == "submit_answer":
                await self.handle_submit_answer(player_id, message.data)
            elif msg_type == "start_game":
                await self.handle_start_game(player_id)
            else:
                logger.warning(f"Unknown message type: {msg_type}")
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
            logger.error(f"Error handling message: {e}")
            await self.send_error(player_id, "Internal server error")

    async def handle_create_game(self, player_id: str, data: Dict[str, Any]):
        """Handle game creation"""
        try:
            create_msg = CreateGameMessage.parse_obj(data)
            game_id = create_msg.game_id or f"game_{uuid.uuid4().hex[:8]}"

            # Create game config
            config = GameConfig()
            if create_msg.config:
                config.max_rounds = create_msg.config.get("max_rounds", config.max_rounds)
                config.countdown_seconds = create_msg.config.get("countdown_seconds", config.countdown_seconds)
                config.answer_time_seconds = create_msg.config.get("answer_time_seconds", config.answer_time_seconds)
                config.pause_between_rounds_seconds = create_msg.config.get("pause_between_rounds_seconds", config.pause_between_rounds_seconds)

            # Create the game
            game = self.game_room.create_game(game_id, config)

            # Add player to the game
            player = self.game_room.players[player_id]
            self.game_room.add_player_to_game(player, game_id)

            logger.info(f"Player {player.name} created game {game_id}")
            await self.send_to_player(player_id, {"type": "game_created", "game_id": game_id})
            await self.send_game_info(player_id, game_id)

        except ValidationError:
            await self.send_error(player_id, "Invalid game creation data")

    async def handle_join_game(self, player_id: str, data: Dict[str, Any]):
        """Handle joining a game"""
        try:
            join_msg = JoinGameMessage.parse_obj(data)
            game_id = join_msg.game_id

            player = self.game_room.players[player_id]
            success = self.game_room.add_player_to_game(player, game_id)

            if success:
                logger.info(f"Player {player.name} joined game {game_id}")
                # First send confirmation to new player
                await self.send_to_player(player_id, {"type": "game_joined", "game_id": game_id})
                # Then send complete game info to new player
                await self.send_game_info(player_id, game_id)
                # Broadcast updated player list to ALL players in the game (both existing and new)
                await self.broadcast_players_update(game_id)
            else:
                await self.send_error(player_id, f"Cannot join game {game_id}")

        except ValidationError:
            await self.send_error(player_id, "Invalid game join data")

    async def handle_leave_game(self, player_id: str):
        """Handle leaving a game"""
        player = self.game_room.players.get(player_id)
        if player and player.game_id:
            game_id = player.game_id
            game = self.game_room.get_game(game_id)
            if game:
                game.remove_player(player_id)
                
                # If game becomes empty, clean it up
                if game.is_empty():
                    self.game_room.delete_game(game_id)
                else:
                    # Broadcast updated player list to remaining players
                    await self.broadcast_players_update(game_id)

            player.game_id = None
            logger.info(f"Player {player.name} left game {game_id}")
            await self.send_lobby_info(player_id)

    async def handle_set_name(self, player_id: str, data: Dict[str, Any]):
        """Handle player name change"""
        logger.info(f"handle_set_name called for player_id: {player_id} with data: {data}")
        try:
            name_msg = SetNameMessage.parse_obj(data)
            if player_id in self.game_room.players:
                old_name = self.game_room.players[player_id].name
                self.game_room.players[player_id].name = name_msg.name
                logger.info(f"Player {old_name} changed name to {name_msg.name}")

                # Send confirmation to player with player_id
                await self.send_to_player(player_id, {
                    "type": "name_set",
                    "player_id": player_id,
                    "name": name_msg.name
                })

                # Notify game if player is in one
                player = self.game_room.players[player_id]
                if player.game_id:
                    await self.broadcast_to_game(player.game_id, "player_updated", {
                        "player_id": player_id,
                        "name": name_msg.name
                    })
            else:
                logger.warning(f"Player {player_id} not found in game_room.players")
                await self.send_error(player_id, "Player not registered")

        except ValidationError as e:
            logger.error(f"Validation error in set_name: {e}")
            await self.send_error(player_id, "Invalid name format")
        except Exception as e:
            logger.error(f"Error setting name: {e}", exc_info=True)
            await self.send_error(player_id, "Error setting name")

    async def handle_set_ready(self, player_id: str, data: Dict[str, Any]):
        """Handle player ready status change"""
        try:
            ready_msg = SetReadyMessage.parse_obj(data)
            player = self.game_room.players.get(player_id)
            if player and player.game_id:
                game = self.game_room.get_game(player.game_id)
                if game and player_id in game.players:
                    game.players[player_id].ready = ready_msg.ready
                    logger.info(f"Player {player.name} ready status: {ready_msg.ready}")
                    
                    # Broadcast updated player list to all players in game
                    await self.broadcast_players_update(player.game_id)

                    # Check if all players are ready to start countdown
                    if game.all_players_ready() and game.status == GameStatus.WAITING:
                        await self.start_countdown(player.game_id)

        except ValidationError:
            await self.send_error(player_id, "Invalid ready status")

    async def handle_submit_answer(self, player_id: str, data: Dict[str, Any]):
        """Handle answer submission"""
        try:
            answer_msg = SubmitAnswerMessage.parse_obj(data)
            player = self.game_room.players.get(player_id)
            if player and player.game_id:
                game = self.game_room.get_game(player.game_id)
                if game and game.current_question:
                    success = await self.game_logic.submit_answer(player.game_id, player_id, answer_msg.guess)
                    if success:
                        correct_distance = game.current_question.distance
                        accuracy = game.calculate_accuracy_percentage(answer_msg.guess, correct_distance)
                        difference = abs(answer_msg.guess - correct_distance)
                        
                        await self.send_to_player(player_id, {
                            "type": "answer_received",
                            "guess": answer_msg.guess #,
                            #"correct_distance": correct_distance,
                            #"difference": difference,
                            #"accuracy_percent": round(accuracy, 1)
                        })
                    else:
                        await self.send_error(player_id, "Could not submit answer at this time")
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
            await self.broadcast_to_game(game_id, "game_starting", {"countdown": game.config.countdown_seconds})

            for i in range(game.config.countdown_seconds, 0, -1):
                await self.broadcast_to_game(game_id, "countdown", {"value": i})
                await asyncio.sleep(1)

            await self.broadcast_to_game(game_id, "countdown", {"value": 0})
            await self.broadcast_to_game(game_id, "game_started", {"config": game.config})
            
            # Start the game with error handling
            success = await self.game_logic.start_game(game_id)
            if not success:
                logger.warning(f"Failed to start game {game_id}")
                await self.broadcast_to_game(game_id, "error", {"message": "Failed to start game"})
        except Exception as e:
            logger.error(f"Error in start_countdown: {e}", exc_info=True)
            await self.broadcast_to_game(game_id, "error", {"message": f"Game error: {str(e)}"})


    async def send_lobby_info(self, player_id: str):
        """Send lobby information to player on all connections"""
        lobby_data = {
            "type": "lobby_info",
            "active_games": self.game_room.list_active_games(),
            "player_name": self.game_room.players[player_id].name
        }
        # Send to all connections for this player
        if player_id in self.active_connections:
            for websocket in self.active_connections[player_id]:
                try:
                    await websocket.send_text(json.dumps(lobby_data))
                except Exception as e:
                    logger.error(f"Failed to send lobby info to {player_id}: {e}")

    async def send_game_info(self, player_id: str, game_id: str):
        """Send game information to player on all connections"""
        game = self.game_room.get_game(game_id)
        if game and player_id in self.active_connections:
            game_data = {
                "type": "game_info",
                "game_id": game_id,
                "config": {
                    "max_rounds": game.config.max_rounds,
                    "countdown_seconds": game.config.countdown_seconds,
                    "answer_time_seconds": game.config.answer_time_seconds,
                    "pause_between_rounds_seconds": game.config.pause_between_rounds_seconds
                },
                "players": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "ready": p.ready,
                        "score": p.score,
                        "is_host": p.id == game.host_player_id
                    } for p in game.players.values()
                ],
                "is_host": player_id == game.host_player_id
            }
            # Send to all connections for this player
            for websocket in self.active_connections[player_id]:
                try:
                    await websocket.send_text(json.dumps(game_data))
                except Exception as e:
                    logger.error(f"Failed to send game info to {player_id}: {e}")

    async def broadcast_players_update(self, game_id: str):
        """Broadcast updated player list to all players in a game"""
        game = self.game_room.get_game(game_id)
        if not game:
            logger.warning(f"broadcast_players_update: Game {game_id} not found")
            return
        
        logger.info(f"broadcast_players_update: Sending to {len(game.players)} players in game {game_id}")
        
        # Send game info to all connections of all players
        for player in game.players.values():
            logger.info(f"  - Sending to player {player.name} ({player.id}), {len(self.active_connections.get(player.id, []))} connections")
            if player.id in self.active_connections:
                game_data = {
                    "type": "game_info",
                    "game_id": game_id,
                    "config": {
                        "max_rounds": game.config.max_rounds,
                        "countdown_seconds": game.config.countdown_seconds,
                        "answer_time_seconds": game.config.answer_time_seconds,
                        "pause_between_rounds_seconds": game.config.pause_between_rounds_seconds
                    },
                    "players": [
                        {
                            "id": p.id,
                            "name": p.name,
                            "ready": p.ready,
                            "score": p.score,
                            "is_host": p.id == game.host_player_id
                        } for p in game.players.values()
                    ],
                    "is_host": player.id == game.host_player_id
                }
                # Send to ALL connections for this player
                for websocket in self.active_connections[player.id]:
                    try:
                        await websocket.send_text(json.dumps(game_data))
                    except Exception as e:
                        logger.error(f"Failed to send game info to {player.id}: {e}")

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
                # Send to all connections for this player
                for websocket in self.active_connections[player.id]:
                    try:
                        await websocket.send_text(json.dumps(message))
                    except Exception as e:
                        logger.error(f"Failed to send message to {player.id}: {e}")

    async def send_to_player(self, player_id: str, data: Dict[str, Any]):
        """Send message to specific player on all connections"""
        if player_id in self.active_connections:
            # Send to all connections for this player
            for websocket in self.active_connections[player_id]:
                try:
                    await websocket.send_text(json.dumps(data))
                except Exception as e:
                    logger.error(f"Failed to send message to {player_id}: {e}")

    async def send_error(self, player_id: str, error_message: str):
        """Send error message to player on all connections"""
        error_data = {
            "type": "error",
            "message": error_message
        }
        # Send to all connections for this player
        if player_id in self.active_connections:
            for websocket in self.active_connections[player_id]:
                try:
                    await websocket.send_text(json.dumps(error_data))
                except Exception as e:
                    logger.error(f"Failed to send error to {player_id}: {e}")

    async def broadcast_game_status(self, game_id: str):
        """Broadcast current game status"""
        status = self.game_logic.get_game_status(game_id)
        if status:
            await self.broadcast_to_game(game_id, "game_status", status)
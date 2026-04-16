from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from enum import Enum
import uuid
import asyncio


class GameStatus(Enum):
    WAITING = "waiting"
    COUNTDOWN = "countdown"
    ACTIVE = "active"
    PAUSED = "paused"
    FINISHED = "finished"


@dataclass
class GameConfig:
    max_rounds: int = 5
    countdown_seconds: int = 3
    answer_time_seconds: int = 15
    pause_between_rounds_seconds: int = 3



@dataclass
class Player:
    id: str
    name: str
    ready: bool = False
    score: int = 0
    websocket: Optional['WebSocket'] = None
    game_id: Optional[str] = None


@dataclass
class CityPair:
    id: int
    city1: str
    city2: str
    distance: int
    lat1: float
    lon1: float
    lat2: float
    lon2: float
    question_id: str

    @property
    def cities(self) -> Tuple[str, str]:
        return (self.city1, self.city2)


@dataclass
class Question:
    id: uuid
    question: CityPair

@dataclass
class GameState:
    id: str
    players: Dict[str, Player] = field(default_factory=dict)
    config: GameConfig = field(default_factory=GameConfig)
    status: GameStatus = GameStatus.WAITING
    current_round: int = 0
    current_question: Optional[CityPair] = None
    answers: Dict[str, int] = field(default_factory=dict)
    answer_deadline_task: Optional[asyncio.Task] = None
    created_at: datetime = field(default_factory=datetime.now)
    host_player_id: Optional[str] = None

    def reset(self):
        """Reset game state for a new game"""
        self.status = GameStatus.WAITING
        self.current_round = 0
        self.current_question = None
        self.answers = {}
        if self.answer_deadline_task and not self.answer_deadline_task.done():
            self.answer_deadline_task.cancel()
        self.answer_deadline_task = None
        for player in self.players.values():
            player.ready = False
            player.score = 0

    def add_player(self, player: Player):
        self.players[player.id] = player
        player.game_id = self.id
        if self.host_player_id is None:
            self.host_player_id = player.id

    def remove_player(self, player_id: str):
        if player_id in self.players:
            del self.players[player_id]
            if self.host_player_id == player_id and self.players:
                # Assign new host
                self.host_player_id = next(iter(self.players.keys()))

    def get_ready_players(self) -> List[Player]:
        return [p for p in self.players.values() if p.ready]

    def all_players_ready(self) -> bool:
        return len(self.players) >= 1 and all(p.ready for p in self.players.values())

    def calculate_accuracy_percentage(self, guess: int, correct: int) -> float:
        """Calculate percentage accuracy (lower is better)"""
        if correct == 0:
            return 100.0 if guess == 0 else float('inf')
        return abs(guess - correct) / correct * 100

    def is_empty(self) -> bool:
        return len(self.players) == 0

    def can_start(self) -> bool:
        return not self.status == GameStatus.ACTIVE and self.all_players_ready()


@dataclass
class GameRoom:
    """Manages multiple concurrent games"""
    games: Dict[str, GameState] = field(default_factory=dict)
    players: Dict[str, Player] = field(default_factory=dict)  # Global player registry

    def create_game(self, game_id: str, config: Optional[GameConfig] = None) -> GameState:
        """Create a new game"""
        if game_id in self.games:
            raise ValueError(f"Game {game_id} already exists")

        game = GameState(
            id=game_id,
            config=config or GameConfig()
        )
        self.games[game_id] = game
        return game

    def get_game(self, game_id: str) -> Optional[GameState]:
        """Get a game by ID"""
        return self.games.get(game_id)

    def delete_game(self, game_id: str):
        """Delete a game and clean up players"""
        if game_id in self.games:
            game = self.games[game_id]
            # Remove all players from this game
            for player_id in list(game.players.keys()):
                self.remove_player_from_game(player_id, game_id)
            del self.games[game_id]

    def add_player_to_game(self, player: Player, game_id: str) -> bool:
        """Add a player to a specific game"""
        game = self.get_game(game_id)
        if not game:
            return False

        # Remove player from any existing game
        if player.game_id and player.game_id != game_id:
            self.remove_player_from_game(player.id, player.game_id)

        game.add_player(player)
        self.players[player.id] = player
        return True

    def remove_player_from_game(self, player_id: str, game_id: str):
        """Remove a player from a specific game"""
        game = self.get_game(game_id)
        if game:
            game.remove_player(player_id)

        # Remove from global registry if they're not in any game
        if player_id in self.players and self.players[player_id].game_id is None:
            del self.players[player_id]

    def get_player_game(self, player_id: str) -> Optional[GameState]:
        """Get the game a player is currently in"""
        player = self.players.get(player_id)
        if player and player.game_id:
            return self.get_game(player.game_id)
        return None

    def cleanup_empty_games(self):
        """Remove games with no players"""
        empty_games = [game_id for game_id, game in self.games.items() if game.is_empty()]
        for game_id in empty_games:
            del self.games[game_id]

    def list_active_games(self) -> List[Dict]:
        """List all active games with basic info"""
        return [
            {
                "id": game.id,
                "status": game.status.value,
                "player_count": len(game.players),
                "max_rounds": game.config.max_rounds,
                "current_round": game.current_round,
                "host": game.players.get(game.host_player_id, Player("", "")).name if game.host_player_id else None
            }
            for game in self.games.values()
        ]


@dataclass
class GameResult:
    game_id: str
    player_name: str
    guess: int
    correct_distance: int
    accuracy_percentage: float
    cities: Tuple[str, str]
    round_number: int
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class HighScore:
    player_name: str
    score: int
    total_rounds: int
    average_accuracy: float
    games_played: int
    timestamp: datetime = field(default_factory=datetime.now)



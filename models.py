from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from enum import Enum
import uuid
import asyncio
import random


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
    auto_advance_on_all_answers: bool = True
    first_answer_ends_round: bool = False
    wrong_answer_points_others: bool = False
    # "pause": pause game while player is away (default); "kick": remove player immediately
    disconnect_behavior: str = "pause"



@dataclass
class Player:
    id: str
    name: str
    ready: bool = False
    score: int = 0
    tab_away: bool = False
    suspicion_score: int = 0
    fast_answers: int = 0
    repeat_guess_streak: int = 0
    last_guess: Optional[int] = None
    answer_latencies_ms: List[int] = field(default_factory=list)
    bot_flagged: bool = False
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
    settings_locked: bool = False
    current_round: int = 0
    current_question: Optional[CityPair] = None
    next_question_preloaded: Optional[CityPair] = None
    answers: Dict[str, int] = field(default_factory=dict)
    answer_submissions: Dict[str, datetime] = field(default_factory=dict)
    answer_submission_history: Dict[str, List[Dict]] = field(default_factory=dict)
    answer_time_remaining: int = 0
    question_started_at: Optional[datetime] = None
    pause_reason: Optional[str] = None
    warmup_active: bool = False
    round_history: List[Dict] = field(default_factory=list)
    answer_deadline_task: Optional[asyncio.Task] = None
    reconnect_resume_task: Optional[asyncio.Task] = None
    round_resolution_in_progress: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    host_player_id: Optional[str] = None
    pin: str = ""
    
    def __post_init__(self):
        """Generate PIN if not set"""
        if not self.pin:
            self.pin = f"{random.randint(0, 9999):04d}"

    def reset(self):
        """Reset game state for a new game"""
        self.status = GameStatus.WAITING
        self.current_round = 0
        self.current_question = None
        self.next_question_preloaded = None
        self.answers = {}
        self.answer_submissions = {}
        self.answer_submission_history = {}
        self.answer_time_remaining = 0
        self.question_started_at = None
        self.pause_reason = None
        self.warmup_active = False
        self.round_history = []
        self.round_resolution_in_progress = False
        if self.answer_deadline_task and not self.answer_deadline_task.done():
            self.answer_deadline_task.cancel()
        self.answer_deadline_task = None
        if self.reconnect_resume_task and not self.reconnect_resume_task.done():
            self.reconnect_resume_task.cancel()
        self.reconnect_resume_task = None
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
        """Calculate percentage accuracy (higher is better, clamped to 0-100)."""
        if correct == 0:
            return 100.0 if guess == 0 else 0.0

        error_pct = abs(guess - correct) / correct * 100
        return max(0.0, 100.0 - error_pct)

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

    def started_games_count(self) -> int:
        """Count games that have already started at least once."""
        started_statuses = {
            GameStatus.COUNTDOWN,
            GameStatus.ACTIVE,
            GameStatus.PAUSED,
            GameStatus.FINISHED,
        }
        return sum(1 for game in self.games.values() if game.status in started_statuses)


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



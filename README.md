# Entfernungsspiel (Distance Game) v3.0

A real-time multiplayer web-based distance guessing game where players can create and join multiple concurrent games.

## Features

### Core Gameplay
- **Multiple concurrent games**: Support for multiple games running simultaneously
- **Real-time multiplayer**: WebSocket-based communication for instant gameplay
- **Distance guessing**: Players guess distances between German city pairs
- **Scoring system**: Closest guess wins each round
- **Multiple rounds**: Configurable number of rounds per game
- **Accuracy tracking**: Percentage accuracy calculation for each guess

### Enhanced Features (v3.0)
- **Game rooms**: Players can create private game rooms or join existing ones
- **Lobby system**: Browse and join active games
- **Host controls**: Game hosts can configure settings and start games manually
- **Database persistence**: SQLite database for storing game results, high scores, and city pairs
- **Admin panel**: Web-based administration interface with authentication
- **Dynamic city management**: Add/edit city pairs through the admin interface
- **Comprehensive statistics**: High scores, game history, and player analytics
- **RESTful API**: Full API for integration and data access
- **Improved security**: Input validation, CORS configuration, and basic authentication
- **Modular architecture**: Clean separation of concerns with proper error handling
- **Health monitoring**: Health check endpoints for monitoring
- **Environment configuration**: Configurable via environment variables

## Quick Start

### Local Development

1. **Clone and setup**:
   ```bash
   git clone <repository-url>
   cd entfernungsspiel
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Run the application**:
   ```bash
   python main.py
   ```

3. **Open in browser**:
   - Game: http://localhost:8080
   - Admin panel: http://localhost:8080/admin (admin/admin123)

### Docker

```bash
docker build -t entfernungsspiel .
docker run -p 8080:8080 entfernungsspiel
```

### Game Management
- **Create games**: Players can create new game rooms with custom settings
- **Join games**: Browse available games in the lobby and join existing ones
- **Game isolation**: Each game runs independently with its own state and players
- **Player management**: Players can leave games and join different ones
- **Automatic cleanup**: Empty games are automatically removed

## Architecture

### Project Structure
```
entfernungsspiel/
├── main.py                 # FastAPI application entry point
├── models.py              # Data models and state management
├── game_logic.py          # Game mechanics and logic
├── websocket_handlers.py  # WebSocket message handling
├── database.py            # Database operations and models
├── config.py              # Configuration management
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker container configuration
├── static/               # Static web assets
├── templates/            # Jinja2 HTML templates
└── .vscode/              # VS Code configuration
```

### Key Components

#### Game Room Management
- **GameRoom**: Manages multiple concurrent games and global player registry
- **GameState**: Individual game state with status tracking (waiting, countdown, active, paused, finished)
- **Player**: Player model with game association and connection tracking

#### Game Logic
- **GameLogic**: Handles game flow, scoring, and round management per game
- **WebSocketHandler**: Manages real-time communication with game-specific broadcasting
- **Database Layer**: Persistent storage for results, high scores, and city pairs

#### API Endpoints
- **WebSocket**: `/ws` - Real-time game communication
- **REST API**:
  - `GET /` - Main game page
  - `GET /admin` - Admin panel (authenticated)
  - `POST /admin` - Update game configuration
  - `GET /api/high-scores` - Get high scores
  - `GET /api/game-history` - Get game history
  - `GET /api/city-pairs` - Get city pairs
  - `POST /api/city-pairs` - Add city pair (admin)
  - `GET /health` - Health check

### Health Check
The health check endpoint provides server status and multi-game metrics:

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "version": "1.0.0",
  "games": {
    "active": 3,
    "waiting": 2,
    "total_players": 15,
    "finished_today": 42
  },
  "database": {
    "status": "connected",
    "total_games": 156,
    "total_city_pairs": 89
  },
  "websocket": {
    "connections": 15,
    "active_games": 3
  }
}
```

**Metrics:**
- `games.active`: Number of currently running games
- `games.waiting`: Number of games waiting for players to start
- `games.total_players`: Total players across all active games
- `games.finished_today`: Games completed today
- `database.total_games`: Total games stored in database
- `database.total_city_pairs`: Total city pairs available
- `websocket.connections`: Active WebSocket connections
- `websocket.active_games`: Games with active WebSocket connections

## Configuration

### Environment Variables
```bash
# Server
HOST=0.0.0.0
PORT=8080
DEBUG=false

# Database
DATABASE_URL=sqlite:///./highscores.db

# CORS
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Game defaults
DEFAULT_MAX_ROUNDS=5
DEFAULT_COUNTDOWN=3
DEFAULT_ANSWER_TIME=15
DEFAULT_PAUSE_BETWEEN_ROUNDS=3

# Logging
LOG_LEVEL=INFO
LOG_FILE=server.log
```

### Game Configuration (Admin Panel)
- **Max Rounds**: Number of rounds per game (1-50)
- **Countdown**: Initial start countdown in seconds (1-60)
- **Answer Time**: Time allowed for answers in seconds (5-300)
- **Pause Between Rounds**: Pause duration between rounds (1-30)

## API Documentation

### WebSocket Messages

#### Client → Server
```json
// Create a new game
{"type": "create_game", "data": {"game_id": "my_game", "config": {"max_rounds": 5}}}

// Join an existing game
{"type": "join_game", "data": {"game_id": "existing_game"}}

// Leave current game
{"type": "leave_game"}

// Set player name
{"type": "set_name", "data": {"name": "PlayerName"}}

// Set ready status
{"type": "set_ready", "data": {"ready": true}}

// Submit answer
{"type": "submit_answer", "data": {"guess": 250}}

// Start game (host only)
{"type": "start_game"}
```

#### Server → Client
```json
// Lobby information
{"type": "lobby_info", "active_games": [...], "player_name": "Player1"}

// Game created successfully
{"type": "game_created", "game_id": "game_123"}

// Game joined successfully
{"type": "game_joined", "game_id": "game_123"}

// Game information
{"type": "game_info", "game_id": "game_123", "config": {...}, "players": [...], "is_host": true}

// Player joined/left game
{"type": "player_joined", "player": "Alice"}
{"type": "player_left", "player": "Bob"}

// Player updated
{"type": "player_updated", "player_id": "player_123", "name": "NewName"}

// Ready status changed
{"type": "player_ready_changed", "player_id": "player_123", "ready": true}

// Game starting countdown
{"type": "game_starting", "countdown": 3}

// Game countdown
{"type": "countdown", "value": 3}

// Game started
{"type": "game_started"}

// New question
{"type": "new_question", "round": 1, "max_rounds": 5, "cities": ["Berlin", "Hamburg"], "question": "..."}

// Answer received confirmation
{"type": "answer_received"}

// Score update
{"type": "score_update", "scores": {"Alice": 1}, "high_score": 1}

// Error message
{"type": "error", "message": "Invalid input"}
```

### REST API Examples

#### Get High Scores
```bash
curl http://localhost:8080/api/high-scores?limit=10
```

#### Get Game History
```bash
# Get all game history
curl http://localhost:8080/api/game-history

# Filter by game ID
curl http://localhost:8080/api/game-history?game_id=game_123

# Get recent games with limit
curl http://localhost:8080/api/game-history?limit=20

# Filter by date range
curl "http://localhost:8080/api/game-history?start_date=2024-01-01&end_date=2024-01-31"
```

#### Add City Pair (Admin)
```bash
curl -X POST http://localhost:8080/api/city-pairs \
  -u admin:admin123 \
  -d "city1=Munich&city2=Vienna&distance=400"
```

## Development

### Running Tests
```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run tests
pytest
```

### Code Quality
```bash
# Lint code
flake8 .

# Format code
black .

# Type checking
mypy .
```

### Database Management
The application automatically initializes the database on startup. To reset the database:
```bash
rm highscores.db
python -c "from database import init_db; init_db()"
```

## Security Considerations

### Production Deployment
1. **Change default admin credentials** in `main.py`
2. **Configure proper CORS origins** via `ALLOWED_ORIGINS`
3. **Use environment variables** for sensitive configuration
4. **Enable HTTPS** in production
5. **Set up proper logging** and monitoring
6. **Use a production database** (PostgreSQL, MySQL) instead of SQLite

### Admin Authentication
The admin panel uses HTTP Basic Authentication with hardcoded credentials. For production:
- Implement proper user authentication
- Use secure password hashing
- Add role-based access control

## Troubleshooting

### Common Issues

1. **WebSocket connection fails**
   - Check firewall settings
   - Ensure correct port configuration
   - Verify CORS settings

2. **Database errors**
   - Check file permissions for SQLite database
   - Ensure database URL is correct
   - Run database initialization

3. **Admin panel not accessible**
   - Verify admin credentials
   - Check browser console for CORS errors
   - Ensure templates directory exists

### Logs
Check `server.log` for detailed error information and debugging information.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
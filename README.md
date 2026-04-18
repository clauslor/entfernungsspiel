# Entfernungsspiel

A real-time multiplayer distance guessing game. Players estimate the distance between German city pairs and compete to be the most accurate. Supports multiple concurrent game rooms, optional road-distance questions (via OSRM or GraphHopper), bot detection, reconnect grace periods, and a web-based admin panel.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn (async Python) |
| Database | SQLite + SQLAlchemy |
| WebSocket | FastAPI WebSocket + asyncio |
| Frontend | Vanilla JavaScript, OpenLayers 9, custom i18n |
| Bot prevention | hCaptcha |
| Routing | OSRM (default) or GraphHopper (optional) |

## Project Structure

```
entfernungsspiel/
├── main.py                  # FastAPI app, REST routes, auth
├── config.py                # Environment-based configuration
├── models.py                # Game models (GameState, Player, CityPair, GameConfig)
├── game_logic.py            # Round flow, scoring, question assignment
├── websocket_handlers.py    # WebSocket message routing and broadcasting
├── database.py              # SQLAlchemy models and CRUD operations
├── populate_db.py           # City pair seeding script
├── requirements.txt
├── Dockerfile
├── templates/
│   ├── index.html           # Main game UI (Jinja2)
│   └── admin.html           # Admin panel
├── js/
│   ├── main.js              # Client-side game logic, WebSocket, OpenLayers map
│   ├── captcha.js           # hCaptcha modal and token management
│   └── ...
├── css/
│   └── style.css
└── static/
    └── i18n/
        ├── de.json          # German translations
        └── en.json          # English translations
```

## Quick Start

### Local Development

```bash
git clone <repository-url>
cd entfernungsspiel
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
```

Set the required secrets as environment variables:

```bash
# Windows
set HCAPTCHA_SECRET_KEY=your_hcaptcha_secret_key
set ADMIN_PASSWORD=your_admin_password

# Linux/macOS
export HCAPTCHA_SECRET_KEY=your_hcaptcha_secret_key
export ADMIN_PASSWORD=your_admin_password
```

Then start the server:

```bash
python main.py
```

- Game: http://localhost:9000/entfernungsspiel
- Admin panel: http://localhost:9000/entfernungsspiel/admin

### Docker

```bash
docker build -t entfernungsspiel .
docker run -p 9000:9000 \
  -e HCAPTCHA_SECRET_KEY=your_key \
  -e ADMIN_PASSWORD=your_password \
  entfernungsspiel
```

## Configuration

All configuration is read from environment variables. Defaults are shown below.

```bash
# Server
HOST=0.0.0.0
PORT=9000
DEBUG=false
ROOT_PATH=/entfernungsspiel

# Database
DATABASE_URL=sqlite:///./highscores.db

# CORS
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Game defaults (configurable per game and via admin panel)
DEFAULT_MAX_ROUNDS=1
DEFAULT_COUNTDOWN=3
DEFAULT_ANSWER_TIME=15
DEFAULT_PAUSE_BETWEEN_ROUNDS=3
DEFAULT_ENABLE_ROAD_QUESTIONS=true
DEFAULT_ROAD_QUESTION_RATIO_PERCENT=50

# Logging
LOG_LEVEL=INFO
LOG_FILE=server.log

# Routing (for road-distance questions)
# Options: osrm (free, no key required) | graphhopper
ROUTING_PROVIDER=osrm
OSRM_BASE_URL=https://router.project-osrm.org
GRAPHHOPPER_API_KEY=
GRAPHHOPPER_PROFILE=car
ROAD_DISTANCE_QUESTION_CHANCE=1.0

# hCaptcha — obtain keys at https://dashboard.hcaptcha.com
HCAPTCHA_SITE_KEY=259e5380-5d2e-4d64-8184-ad0896de011c  # public, already set
HCAPTCHA_SECRET_KEY=                                       # required — set via env
HCAPTCHA_VERIFY_URL=https://hcaptcha.com/siteverify

# Admin panel (HTTP Basic Auth)
ADMIN_USER=admin
ADMIN_PASSWORD=                                            # required — set via env
```

## API

### REST Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | — | Main game UI |
| `GET` | `/admin` | Basic | Admin panel |
| `POST` | `/admin` | Basic | Update game defaults (countdown, answer time, etc.) |
| `GET` | `/api/high-scores` | — | Top scores (`?limit=10`) |
| `GET` | `/api/game-history` | — | Game history (`?player_name=&limit=50`) |
| `GET` | `/api/city-pairs` | — | All city pairs |
| `POST` | `/api/city-pairs` | Basic | Add a single city pair |
| `POST` | `/api/city-pairs/import-csv` | Basic | Bulk import from CSV |
| `GET` | `/api/city-pairs/suggestions` | Basic | AI-generated city pair suggestions |
| `WebSocket` | `/ws` | — | Real-time game channel (reconnect with `?player_id=`) |
| `GET` | `/health` | — | Health check |

### WebSocket — Client → Server

| Message type | Description |
|---|---|
| `submit_captcha` | Submit hCaptcha token for verification |
| `create_game` | Create a new game room (optional config) |
| `join_game` | Join an existing game by ID and optional PIN |
| `leave_game` | Leave the current game |
| `set_name` | Set display name |
| `set_ready` | Toggle ready status |
| `update_settings` | Host updates game config |
| `lock_settings` | Host locks settings before countdown |
| `kick_player` | Host kicks a player |
| `start_warmup` | Host starts a non-scoring practice round |
| `start_game` | Host starts the actual game |
| `submit_answer` | Submit a distance guess in km (0–3000) |
| `tab_leaving` | Notify that the browser tab is closing |
| `tab_active` | Notify that the tab is active again |

### WebSocket — Server → Client

| Message type | Description |
|---|---|
| `session_restored` | Session resumed after reconnect |
| `lobby_info` | List of open games in the lobby |
| `game_created` | Game created (includes PIN) |
| `game_joined` | Joined game successfully |
| `game_info` | Full game state snapshot |
| `players_update` | Player list changed |
| `game_left` | Confirmation of leaving a game |
| `countdown_started` | Countdown phase started |
| `warmup_started` | Warmup round started |
| `warmup_result` | Warmup round results |
| `new_question` | New round question (cities, coordinates, variant, time limit) |
| `answer_submission_acknowledged` | Guess received by server |
| `answer_locked_for_round` | Answer window closed |
| `question_result` | Round result (correct distance, winner, all submissions) |
| `game_finished` | Game ended (final scores, winner) |
| `game_paused` | Game paused (e.g. player disconnected) |
| `game_resumed` | Game resumed |
| `player_tab_left` | Player disconnected, grace period active |
| `bot_suspected` | Host notified of suspicious player (bot detection) |
| `error` | Error message |

## Game Mechanics

### Round Flow

1. **Waiting** — Host configures the game; players set their name and ready up.
2. **Countdown** — Short countdown before the question appears.
3. **Active** — Question displayed; players submit their guess in km. A map shows city locations.
4. **Pause** — Brief pause to show results before the next round.
5. **Finished** — Final scores and winner announced.

### Question Variants

- **Air-line** (default): Great-circle distance between city centers.
- **Road** (optional): Actual driving distance via OSRM or GraphHopper, with route visualization on the map. Ratio is configurable (default 50%).

### Scoring Options

Configured per game by the host:

| Option | Effect |
|---|---|
| Default | Closest guess wins 1 point per round |
| `first_answer_ends_round` | Round ends immediately when the first answer arrives |
| `auto_advance_on_all_answers` | Skip the pause if all players have answered |
| `wrong_answer_points_others` | Non-answerers receive +1 if someone answers incorrectly |

### Bot Detection

Each player accumulates a suspicion score. At ≥ 6 points the host receives a `bot_suspected` notification:

- Answer submitted < 300 ms after question: +2
- Same guess 3+ rounds in a row: +1
- Mean latency < 1500 ms and standard deviation < 120 ms: +2

### Reconnect Grace Period

Players who disconnect have a 12-second window to reconnect. The game is paused during this window and automatically resumes when the player returns.

## Admin Panel

Access at `/admin` with HTTP Basic Auth (`ADMIN_USER` / `ADMIN_PASSWORD`).

- **Game defaults**: rounds, countdown, answer time, pause duration
- **City pair management**: add single pair, bulk CSV import (columns: `city1, city2, distance, lat1, lon1, lat2, lon2`), AI-generated suggestions from a German city catalog filtered by population and distance
- **Analytics**: high scores leaderboard, per-game history with accuracy percentages

## Database Schema

| Table | Purpose |
|---|---|
| `city_pairs` | Game questions (city names, coordinates, distance) |
| `route_distance_cache` | Cached road distances per provider/profile |
| `route_points_cache` | Cached route coordinates for map display |
| `game_results` | Per-round submissions (player, guess, accuracy) |
| `high_scores` | Aggregated player statistics |
| `captcha_validations` | hCaptcha tokens with expiry (24 h TTL) |

The database is initialised automatically on first startup. To reset:

```bash
del highscores.db          # Windows
# rm highscores.db         # Linux/macOS
python -c "from database import init_db; import asyncio; asyncio.run(init_db())"
```

## Production Deployment (Linux / systemd)

### First-time setup

```bash
# 1. Clone the repo
sudo git clone <repository-url> /opt/entfernungsspiel
cd /opt/entfernungsspiel

# 2. Create a virtual environment and install dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Create the secrets file (never commit this)
sudo cp .env.example /etc/entfernungsspiel.env
sudo nano /etc/entfernungsspiel.env          # fill in HCAPTCHA_SECRET_KEY and ADMIN_PASSWORD
sudo chown root:www-data /etc/entfernungsspiel.env
sudo chmod 640 /etc/entfernungsspiel.env

# 4. Edit the service unit — set User= and WorkingDirectory= to match your paths
nano deploy/entfernungsspiel.service

# 5. Install and start the service
sudo cp deploy/entfernungsspiel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now entfernungsspiel

# 6. Make the deploy script executable
chmod +x deploy/deploy.sh
```

### Updating the server

`deploy/deploy.sh` pulls the latest code and restarts the service automatically if anything changed. It also re-installs dependencies when `requirements.txt` changes.

```bash
./deploy/deploy.sh
```

**Automated updates via cron** (every 5 minutes):

```bash
crontab -e
# add:
*/5 * * * * /opt/entfernungsspiel/deploy/deploy.sh >> /var/log/entfernungsspiel-deploy.log 2>&1
```

**Automated updates via git post-receive hook** (triggered on every `git push` to the server):

```bash
ln -s /opt/entfernungsspiel/deploy/deploy.sh /opt/entfernungsspiel/.git/hooks/post-receive
```

### Service management

```bash
sudo systemctl status entfernungsspiel
sudo systemctl restart entfernungsspiel
sudo systemctl stop entfernungsspiel
journalctl -u entfernungsspiel -f          # live logs
```

### Gunicorn configuration

The server runs with **1 gunicorn worker** (`uvicorn.workers.UvicornWorker`). This is intentional: all game state is held in-process. Increasing `workers` in `gunicorn.conf.py` would give each worker its own isolated state, breaking multiplayer. Migrate to a shared state backend (e.g. Redis) before scaling beyond 1 worker.

---

## Security

- **No secrets in source code.** `HCAPTCHA_SECRET_KEY` and `ADMIN_PASSWORD` must be provided via environment variables.
- **hCaptcha** is verified server-side on every `create_game` and `join_game` request. Tokens are stored in the DB with a 24-hour expiry so verified users do not need to solve the CAPTCHA again in the same session.
- **Admin routes** are protected with HTTP Basic Auth.
- **CORS** origins are configurable via `ALLOWED_ORIGINS`.
- For production: use HTTPS, set strong passwords, and consider replacing SQLite with PostgreSQL.

## Troubleshooting

| Problem | Solution |
|---|---|
| WebSocket connection fails | Check `ALLOWED_ORIGINS`, firewall, and port settings |
| Database error on startup | Delete `highscores.db` and let init recreate it |
| Admin panel returns 401 | Verify `ADMIN_USER` and `ADMIN_PASSWORD` env vars are set |
| hCaptcha not loading | Check `HCAPTCHA_SITE_KEY` in `config.py` |
| hCaptcha verification fails | Ensure `HCAPTCHA_SECRET_KEY` env var is set correctly |
| Road questions not working | Check `ROUTING_PROVIDER` and network access to OSRM/GraphHopper |

Detailed logs are written to `server.log` (level controlled by `LOG_LEVEL`).
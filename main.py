from urllib import request

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi import UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import asyncio
import json
import csv
import io
import os
import logging
import subprocess
import secrets
import math
import random
from dataclasses import asdict
from typing import Optional, Dict, Tuple, List

from models import GameState, GameConfig, GameRoom, GameStatus
from game_logic import GameLogic
from websocket_handlers import WebSocketHandler
from database import init_db, get_db, get_high_scores, get_game_history, add_city_pair, get_city_pairs, init_default_city_pairs
from config import config

# Initialize logging
log_kwargs = {
    "level": getattr(logging, config.LOG_LEVEL.upper()),
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
}
if config.LOG_FILE.strip():
    log_kwargs["filename"] = config.LOG_FILE
logging.basicConfig(**log_kwargs)
logger = logging.getLogger(__name__)


def _resolve_app_commit_short() -> str:
    """Resolve the currently deployed app revision for footer diagnostics."""
    env_commit = os.getenv("APP_COMMIT") or os.getenv("GIT_COMMIT")
    if env_commit:
        return env_commit.strip()[:12]

    try:
        repo_root = os.path.dirname(os.path.abspath(__file__))
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


APP_COMMIT_SHORT = _resolve_app_commit_short()

# Initialize database
init_db()
with next(get_db()) as db:
    init_default_city_pairs(db)

# Initialize FastAPI app
app = FastAPI(
    title="Kilometer Knobelei API",
    description="A multiplayer distance guessing game",
    version="2.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure static files and templates
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/templates", StaticFiles(directory="templates"), name="templates")
app.mount("/css", StaticFiles(directory="css"), name="css")
app.mount("/js", StaticFiles(directory="js"), name="js")

templates = Jinja2Templates(directory="templates")

# Initialize game room and handlers
game_room = GameRoom()
game_config = GameConfig(
    max_rounds=config.DEFAULT_MAX_ROUNDS,
    countdown_seconds=config.DEFAULT_COUNTDOWN,
    answer_time_seconds=config.DEFAULT_ANSWER_TIME,
    pause_between_rounds_seconds=config.DEFAULT_PAUSE_BETWEEN_ROUNDS,
    enable_road_questions=config.DEFAULT_ENABLE_ROAD_QUESTIONS,
    road_question_ratio_percent=max(0, min(100, config.DEFAULT_ROAD_QUESTION_RATIO_PERCENT)),
    enable_sorting_questions=config.DEFAULT_ENABLE_SORTING_QUESTIONS,
    sorting_question_ratio_percent=max(0, min(100, config.DEFAULT_SORTING_QUESTION_RATIO_PERCENT)),
    enable_speed_rounds=config.DEFAULT_ENABLE_SPEED_ROUNDS,
    speed_round_ratio_percent=max(0, min(100, config.DEFAULT_SPEED_ROUND_RATIO_PERCENT)),
    speed_round_time_seconds=max(5, min(30, config.DEFAULT_SPEED_ROUND_TIME_SECONDS)),
)  # Global configuration for admin panel and new games
game_logic = GameLogic(game_room)
ws_handler = WebSocketHandler(game_room, game_logic, default_config=game_config)
game_logic.set_ws_handler(ws_handler)  # Set the handler for broadcasting

# Security
security = HTTPBasic()

def authenticate_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Basic authentication for admin endpoints"""
    correct_username = secrets.compare_digest(credentials.username, config.ADMIN_USER)
    correct_password = secrets.compare_digest(credentials.password, config.ADMIN_PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def _normalize_pair_key(city1: str, city2: str) -> Tuple[str, str]:
    a = (city1 or "").strip().lower()
    b = (city2 or "").strip().lower()
    return (a, b) if a <= b else (b, a)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c


def _load_german_city_catalog(min_population: int) -> List[Dict]:
    """Load German cities catalog and keep cities above min_population."""
    catalog_path = os.path.join("static", "data", "germany_cities_30k.json")
    if not os.path.exists(catalog_path):
        logger.warning("German city catalog not found at %s", catalog_path)
        return []

    try:
        with open(catalog_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.error("Could not load German city catalog: %s", exc)
        return []

    filtered = []
    for city in data:
        try:
            population = int(city.get("population", 0))
            if population < min_population:
                continue
            filtered.append(
                {
                    "name": str(city["name"]),
                    "lat": float(city["lat"]),
                    "lon": float(city["lon"]),
                    "population": population,
                }
            )
        except Exception:
            continue

    return filtered


def _build_city_pair_suggestions(
    city_pairs,
    city_catalog: List[Dict],
    limit: int,
    min_distance: int,
    max_distance: int,
) -> List[Dict]:
    existing_pair_keys = {
        _normalize_pair_key(cp.city1, cp.city2)
        for cp in city_pairs
        if cp.city1 and cp.city2
    }

    city_items = [
        (entry["name"], (float(entry["lat"]), float(entry["lon"]), int(entry["population"])))
        for entry in city_catalog
        if entry.get("name") is not None and entry.get("lat") is not None and entry.get("lon") is not None
    ]

    if len(city_items) < 2:
        return []

    # Prevent heavy O(n^2) work with very large city lists.
    max_city_pool = 280
    if len(city_items) > max_city_pool:
        city_items = random.sample(city_items, max_city_pool)
    else:
        random.shuffle(city_items)

    suggested_keys = set()
    usage_count: Dict[str, int] = {}
    max_usage_per_city = 3
    buckets: Dict[str, List[Dict]] = {
        "short": [],
        "medium": [],
        "long": [],
    }

    for i in range(len(city_items)):
        city1, (lat1, lon1, pop1) = city_items[i]
        for j in range(i + 1, len(city_items)):
            city2, (lat2, lon2, pop2) = city_items[j]

            pair_key = _normalize_pair_key(city1, city2)
            if pair_key in existing_pair_keys or pair_key in suggested_keys:
                continue

            if usage_count.get(city1, 0) >= max_usage_per_city or usage_count.get(city2, 0) >= max_usage_per_city:
                continue

            distance = int(round(_haversine_km(lat1, lon1, lat2, lon2)))
            if distance < min_distance or distance > max_distance:
                continue

            # Prefer medium-range distances for better playability.
            target = 900
            score = max(0, 1000 - abs(distance - target))

            suggestion = {
                "city1": city1,
                "city2": city2,
                "distance": distance,
                "lat1": round(lat1, 6),
                "lon1": round(lon1, 6),
                "lat2": round(lat2, 6),
                "lon2": round(lon2, 6),
                "quality_score": score,
                "population1": pop1,
                "population2": pop2,
            }

            if distance < 500:
                buckets["short"].append(suggestion)
            elif distance < 1400:
                buckets["medium"].append(suggestion)
            else:
                buckets["long"].append(suggestion)

            suggested_keys.add(pair_key)
            usage_count[city1] = usage_count.get(city1, 0) + 1
            usage_count[city2] = usage_count.get(city2, 0) + 1

            if len(suggested_keys) >= max(limit * 5, 100):
                break
        if len(suggested_keys) >= max(limit * 5, 100):
            break

    for bucket in buckets.values():
        bucket.sort(key=lambda s: s["quality_score"], reverse=True)

    # Interleave buckets for more variety
    merged: List[Dict] = []
    bucket_order = ["short", "medium", "long"]
    while len(merged) < limit and any(buckets[b] for b in bucket_order):
        for b in bucket_order:
            if buckets[b] and len(merged) < limit:
                merged.append(buckets[b].pop(0))

    # Fallback if one bucket dominated
    if len(merged) < limit:
        remainder = buckets["short"] + buckets["medium"] + buckets["long"]
        remainder.sort(key=lambda s: s["quality_score"], reverse=True)
        merged.extend(remainder[: limit - len(merged)])

    return merged[:limit]


@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    """Serve the main game page"""
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "hcaptcha_site_key": config.HCAPTCHA_SITE_KEY,
            "app_commit_short": APP_COMMIT_SHORT,
        },
    )


@app.get("/admin", response_class=HTMLResponse)
async def get_admin(request: Request, username: str = Depends(authenticate_admin)):
    """Serve the admin configuration page"""
    return templates.TemplateResponse(request, "admin.html", {
        "config": asdict(game_config),
        "username": username
    })


@app.post("/admin", response_class=HTMLResponse)
async def post_admin(
    request: Request,
    countdown: int = Form(..., ge=1, le=60),
    answer_time: int = Form(..., ge=5, le=300),
    pause_between_rounds: int = Form(..., ge=1, le=30),
    max_rounds: int = Form(..., ge=1, le=50),
    username: str = Depends(authenticate_admin)
):
    """Update game configuration"""
    # Check if any game is currently active
    active_games = [g for g in game_room.games.values() if g.status != GameStatus.WAITING]
    if active_games:
        return templates.TemplateResponse(request, "admin.html", {
            "config": asdict(game_config),
            "error": "Cannot change configuration while game is active",
            "username": username
        })

    # Update configuration
    game_config.countdown_seconds = countdown
    game_config.answer_time_seconds = answer_time
    game_config.pause_between_rounds_seconds = pause_between_rounds
    game_config.max_rounds = max_rounds

    logger.info(f"Configuration updated by {username}: {game_config}")

    return templates.TemplateResponse(request, "admin.html", {
        "config": asdict(game_config),
        "success": "Configuration updated successfully",
        "username": username
    })


@app.get("/api/high-scores")
async def get_high_scores_api(limit: int = 10, db=Depends(get_db)):
    """Get high scores via API"""
    high_scores = get_high_scores(db, limit)
    return {
        "high_scores": [
            {
                "player_name": hs.player_name,
                "score": hs.score,
                "total_rounds": hs.total_rounds,
                "average_accuracy": round(hs.average_accuracy, 2),
                "games_played": hs.games_played,
                "timestamp": hs.timestamp.isoformat()
            } for hs in high_scores
        ]
    }


@app.get("/api/game-history")
async def get_game_history_api(player_name: Optional[str] = None, limit: int = 50, db=Depends(get_db)):
    """Get game history via API"""
    history = get_game_history(db, player_name, limit)
    return {
        "game_history": [
            {
                "player_name": result.player_name,
                "guess": result.guess,
                "correct_distance": result.correct_distance,
                "accuracy_percentage": round(result.accuracy_percentage, 2),
                "cities": [result.city1, result.city2],
                "city1": result.city1,
                "city2": result.city2,
                "round_number": result.round_number,
                "timestamp": result.timestamp.isoformat()
            } for result in history
        ]
    }


@app.get("/api/city-pairs")
async def get_city_pairs_api(db=Depends(get_db)):
    """Get all city pairs"""
    city_pairs = get_city_pairs(db)
    return {
        "city_pairs": [
            {
                "id": cp.id,
                "city1": cp.city1,
                "city2": cp.city2,
                "distance": cp.distance,
                "lat1": cp.lat1,
                "lon1": cp.lon1,
                "lat2": cp.lat2,
                "lon2": cp.lon2,
            } for cp in city_pairs
        ]
    }


@app.get("/api/city-pairs/suggestions")
async def get_city_pair_suggestions_api(
    limit: int = 30,
    min_distance: int = 80,
    max_distance: int = 2800,
    min_population: int = 30000,
    db=Depends(get_db),
    username: str = Depends(authenticate_admin),
):
    """Suggest new German city pairs from catalog (not already present in DB)."""
    safe_limit = max(1, min(limit, 200))
    safe_min_distance = max(1, min(min_distance, 10000))
    safe_max_distance = max(safe_min_distance, min(max_distance, 10000))
    safe_min_population = max(30000, min(min_population, 2_000_000))

    city_pairs = get_city_pairs(db)
    city_catalog = _load_german_city_catalog(safe_min_population)
    suggestions = _build_city_pair_suggestions(
        city_pairs,
        city_catalog,
        safe_limit,
        safe_min_distance,
        safe_max_distance,
    )

    logger.info(
        "Generated %s city pair suggestions for admin user %s",
        len(suggestions),
        username,
    )

    return {
        "suggestions": suggestions,
        "count": len(suggestions),
        "filters": {
            "limit": safe_limit,
            "min_distance": safe_min_distance,
            "max_distance": safe_max_distance,
            "min_population": safe_min_population,
        },
    }


@app.post("/api/city-pairs")
async def add_city_pair_api(
    city1: str = Form(...),
    city2: str = Form(...),
    distance: int = Form(..., gt=0),
    lat1: float = Form(..., ge=-90, le=90),
    lon1: float = Form(..., ge=-180, le=180),
    lat2: float = Form(..., ge=-90, le=90),
    lon2: float = Form(..., ge=-180, le=180),
    db=Depends(get_db),
    username: str = Depends(authenticate_admin)
):
    """Add a new city pair (admin only)"""
    try:
        city_pair = add_city_pair(db, city1, city2, distance, lat1, lon1, lat2, lon2)
        logger.info(f"New city pair added by {username}: {city1} - {city2} = {distance}km")
        return {"message": "City pair added successfully", "city_pair": {
            "id": city_pair.id,
            "city1": city_pair.city1,
            "city2": city_pair.city2,
            "distance": city_pair.distance,
            "lat1": city_pair.lat1,
            "lon1": city_pair.lon1,
            "lat2": city_pair.lat2,
            "lon2": city_pair.lon2,
        }}
    except Exception as e:
        logger.error(f"Error adding city pair: {e}")
        raise HTTPException(status_code=400, detail="Error adding city pair")


@app.post("/api/city-pairs/import-csv")
async def import_city_pairs_csv_api(
    file: UploadFile = File(...),
    db=Depends(get_db),
    username: str = Depends(authenticate_admin),
):
    """Import city pairs from CSV (admin only).

    Required CSV columns: city1, city2, distance, lat1, lon1, lat2, lon2
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file")

    try:
        raw = await file.read()
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(content))
    required_columns = {"city1", "city2", "distance", "lat1", "lon1", "lat2", "lon2"}

    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV is empty or missing header row")

    missing_columns = sorted(required_columns - set(reader.fieldnames))
    if missing_columns:
        raise HTTPException(
            status_code=400,
            detail=f"CSV missing required columns: {', '.join(missing_columns)}",
        )

    inserted = 0
    errors = []

    for line_number, row in enumerate(reader, start=2):
        if not row or all((value or "").strip() == "" for value in row.values()):
            continue

        try:
            city1 = (row.get("city1") or "").strip()
            city2 = (row.get("city2") or "").strip()
            distance = int(float((row.get("distance") or "").strip()))
            lat1 = float((row.get("lat1") or "").strip())
            lon1 = float((row.get("lon1") or "").strip())
            lat2 = float((row.get("lat2") or "").strip())
            lon2 = float((row.get("lon2") or "").strip())

            if not city1 or not city2:
                raise ValueError("city1/city2 must not be empty")
            if distance <= 0:
                raise ValueError("distance must be > 0")
            if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90):
                raise ValueError("latitude must be between -90 and 90")
            if not (-180 <= lon1 <= 180 and -180 <= lon2 <= 180):
                raise ValueError("longitude must be between -180 and 180")

            add_city_pair(db, city1, city2, distance, lat1, lon1, lat2, lon2)
            inserted += 1
        except Exception as exc:
            errors.append(f"Line {line_number}: {exc}")

    logger.info(
        "CSV city-pair import by %s: inserted=%s errors=%s",
        username,
        inserted,
        len(errors),
    )

    return {
        "message": "CSV import completed",
        "inserted": inserted,
        "errors": errors[:50],
        "error_count": len(errors),
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time game communication"""
    logger.info("New WebSocket connection")
    player_id = await ws_handler.connect(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            await ws_handler.handle_message(player_id, data)
    except WebSocketDisconnect as e:
        logger.info(f"WebSocket disconnected for player {player_id} with close code {getattr(e, 'code', None)}")
        await ws_handler.disconnect(player_id, websocket)
    except Exception as e:
        logger.error(f"WebSocket error for player {player_id}: {e}", exc_info=True)
        await ws_handler.disconnect(player_id, websocket)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    active_games = len([g for g in game_room.games.values() if g.status.value in ['waiting', 'countdown', 'active', 'paused']])
    total_players = len(game_room.players)
    active_players = len([p for p in game_room.players.values() if p.game_id])

    return {
        "status": "healthy",
        "active_games": active_games,
        "total_players": total_players,
        "active_players": active_players,
        "total_games_created": len(game_room.games)
    }

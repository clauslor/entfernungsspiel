from urllib import request

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import asyncio
import json
import os
import logging
import secrets
from dataclasses import asdict
from typing import Optional

from models import GameState, GameConfig, GameRoom, GameStatus
from game_logic import GameLogic
from websocket_handlers import WebSocketHandler
from database import init_db, get_db, get_high_scores, get_game_history, add_city_pair, get_city_pairs, init_default_city_pairs
from config import config

# Initialize logging
logging.basicConfig(
    filename=config.LOG_FILE,
    level=getattr(logging, config.LOG_LEVEL.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize database
init_db()
with next(get_db()) as db:
    init_default_city_pairs(db)

# Initialize FastAPI app
app = FastAPI(
    title="Entfernungsspiel API",
    description="A multiplayer distance guessing game",
    version="2.0.0",
    root_path = config.ROOT_PATH  # Set root path for reverse proxy
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
app.mount("/templates", StaticFiles(directory="css"), name="css")
app.mount("/css", StaticFiles(directory="css"), name="css")
app.mount("/js", StaticFiles(directory="js"), name="js")

templates = Jinja2Templates(directory="templates")

# Initialize game room and handlers
game_room = GameRoom()
game_config = GameConfig()  # Global configuration for admin panel
game_logic = GameLogic(game_room)
ws_handler = WebSocketHandler(game_room, game_logic)
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


@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    """Serve the main game page"""
    return templates.TemplateResponse(request, "index.html")


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
                "distance": cp.distance
            } for cp in city_pairs
        ]
    }


@app.post("/api/city-pairs")
async def add_city_pair_api(
    city1: str = Form(...),
    city2: str = Form(...),
    distance: int = Form(..., gt=0),
    db=Depends(get_db),
    username: str = Depends(authenticate_admin)
):
    """Add a new city pair (admin only)"""
    try:
        city_pair = add_city_pair(db, city1, city2, distance)
        logger.info(f"New city pair added by {username}: {city1} - {city2} = {distance}km")
        return {"message": "City pair added successfully", "city_pair": {
            "id": city_pair.id,
            "city1": city_pair.city1,
            "city2": city_pair.city2,
            "distance": city_pair.distance
        }}
    except Exception as e:
        logger.error(f"Error adding city pair: {e}")
        raise HTTPException(status_code=400, detail="Error adding city pair")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time game communication"""
    logger.info("New WebSocket connection")
    player_id = await ws_handler.connect(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            await ws_handler.handle_message(player_id, data)
    except WebSocketDisconnect:
        await ws_handler.disconnect(player_id, websocket)
    except Exception as e:
        logger.error(f"WebSocket error for player {player_id}: {e}")
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

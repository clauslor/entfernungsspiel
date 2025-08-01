from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import asyncio
import json
import random
from typing import Dict

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

clients = {}
scores = {}
names = {}
high_score = 0
current_game = "game3"
game_active = False

# Spielkonfiguration
MAX_ROUNDS = 5
current_round = 0

# Entfernungsspiel
city_distances = {
    ("Berlin", "Hamburg"): 289,
    ("München", "Frankfurt"): 393,
    ("Köln", "Stuttgart"): 357,
    ("Dresden", "Leipzig"): 121,
    ("Hannover", "Dortmund"): 207,
    ("Bremen", "Nürnberg"): 540,
    ("Essen", "Düsseldorf"): 35,
    ("Mainz", "Erfurt"): 280,
}

distance_question = None
distance_answers: Dict[str, int] = {}
distance_answer_deadline = None

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    player_id = str(id(websocket))
    clients[player_id] = websocket
    scores[player_id] = 0
    names[player_id] = f"Spieler_{player_id[-4:]}"
    await broadcast(f"{names[player_id]} ist beigetreten.")

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                await handle_message(player_id, msg)
            except json.JSONDecodeError:
                await handle_guess(player_id, data)
    except WebSocketDisconnect:
        await remove_player(player_id)

async def handle_message(player_id, msg):
    global current_game, game_active

    if msg["type"] == "set_name":
        names[player_id] = msg["name"]
        await broadcast(f"{names[player_id]} heißt jetzt {msg['name']}.")
    elif msg["type"] == "remove_player":
        await remove_player(player_id)
    elif msg["type"] == "select_game":
        current_game = msg["game"]
        await broadcast(f"{names[player_id]} hat das Spiel auf '{current_game}' gesetzt.")
    elif msg["type"] == "start_countdown":
        await countdown()
        await start_game()

async def handle_guess(player_id, data):
    global distance_answers
    if current_game == "game3" and game_active:
        try:
            guess = int(data)
            distance_answers[player_id] = guess
            await clients[player_id].send_text(json.dumps({
                "type": "answer_received",
                "player": names[player_id],
                "guess": guess
            }))
            if len(distance_answers) >= len(clients):
                distance_answer_deadline.cancel()
                await evaluate_distance_answers()
        except ValueError:
            await clients[player_id].send_text("Ungültige Eingabe. Bitte gib eine Zahl ein.")

async def remove_player(player_id):
    if player_id in clients:
        await broadcast(f"{names[player_id]} wurde entfernt.")
        del clients[player_id]
        del scores[player_id]
        del names[player_id]

async def broadcast(message: str):
    for ws in clients.values():
        await ws.send_text(message)

async def broadcast_json(payload: dict):
    for ws in clients.values():
        await ws.send_text(json.dumps(payload))

async def update_scores():
    global high_score
    high_score = max(high_score, max(scores.values(), default=0))
    score_board = {names[pid]: score for pid, score in scores.items()}
    await broadcast_json({
        "type": "score_update",
        "scores": score_board,
        "high_score": high_score
    })

async def countdown():
    for i in range(3, 0, -1):
        await broadcast(f"Spiel startet in {i}...")
        await asyncio.sleep(1)
    await broadcast("Los geht's!")

async def start_game():
    global current_round
    current_round = 0
    await next_round()

async def next_round():
    global current_round, game_active, distance_question, distance_answers, distance_answer_deadline

    if current_round >= MAX_ROUNDS:
        await broadcast("🎉 Spiel beendet!")
        await update_scores()
        return

    current_round += 1
    game_active = True
    distance_answers = {}

    distance_question = random.choice(list(city_distances.items()))
    cities, correct_distance = distance_question

    await broadcast_json({
        "type": "new_question",
        "round": current_round,
        "max_rounds": MAX_ROUNDS,
        "question": f"Wie weit ist es von {cities[0]} nach {cities[1]}? (in km)"
    })

    distance_answer_deadline = asyncio.create_task(distance_answer_timeout())

async def distance_answer_timeout():
    await asyncio.sleep(15)
    await evaluate_distance_answers()

async def evaluate_distance_answers():
    global game_active
    game_active = False

    cities, correct = distance_question
    await broadcast(f"Richtige Entfernung zwischen {cities[0]} und {cities[1]}: {correct} km")

    if len(distance_answers) < 1:
        await broadcast("Keine gültigen Antworten erhalten.")
        await next_round()
        return
    diffs = {
        pid: abs(guess - correct)
        for pid, guess in distance_answers.items()
    }

    winner_id = min(diffs, key=diffs.get)
    scores[winner_id] += 1

    await broadcast(f"{names[winner_id]} war am nächsten dran und bekommt einen Punkt!")
    await update_scores()
    await asyncio.sleep(3)
    await next_round()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

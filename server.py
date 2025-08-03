from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
import os
import random
import logging

app = FastAPI()
logger = logging.getLogger(__name__)
logging.basicConfig(filename='server.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/css", StaticFiles(directory="css"), name="css")

clients = {}
names = {}
ready_status = {}
scores = {}
game_active = False
current_round = 0
MAX_ROUNDS = 5

timeouts = {
    "countdown": 3,
    "answer_time": 15, 
    "pause_between_rounds": 3
}

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
distance_answers = {}
distance_answer_deadline = None

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return FileResponse("static/index.html")

@app.get("/admin", response_class=HTMLResponse)
async def get_admin():
    return HTMLResponse(f"""
    <html>
    <body>
        <h2>Admin Timeout Configuration</h2>
        <form action="/admin" method="post">
            Max Rounds: <input type="number" name="max_rounds1" value="{MAX_ROUNDS}"><br>
            Initaler Start Countdown (seconds): <input type="number" name="countdown" value="{timeouts['countdown']}"><br>
            Antwort Zeit (seconds): <input type="number" name="answer_time" value="{timeouts['answer_time']}"><br>
            Pause zwischen den Runden (seconds): <input type="number" name="pause_between_rounds" value="{timeouts['pause_between_rounds']}"><br>
            <input type="submit" value="Update">
        </form>
    </body>
    </html>
    """)

@app.post("/admin", response_class=HTMLResponse)
async def post_admin(countdown: int = Form(...), answer_time: int = Form(...), pause_between_rounds: int = Form(...), max_rounds1: int = Form(...)):
    if game_active is False:
        timeouts["countdown"] = countdown
        timeouts["answer_time"] = answer_time
        timeouts["pause_between_rounds"] = pause_between_rounds
        MAX_ROUNDS = max_rounds1
        return HTMLResponse(f"""
        <html>
        <body>
            <h2>Spiel läuft gerade. Keine Änderungen möglich</h2>
            <a href="/admin">Back</a>
        </body>
        </html>
        """)
    else:
        return HTMLResponse(f"""
        <html>
        <body>
            <h2>Spiel läuft gerade. Keine Änderungen möglich</h2>
            <p>Max Rounds: {max_rounds1} rounds</p>
            <p>Countdown: {countdown} seconds</p>
            <p>Answer Time: {answer_time} seconds</p>
            <p>Pause Between Rounds: {pause_between_rounds} seconds</p>
            <a href="/admin">Back</a>
        </body>
        </html>
        """)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    player_id = str(id(websocket))
    clients[player_id] = websocket
    names[player_id] = f"Spieler_{player_id[-4:]}"
    ready_status[player_id] = False
    scores[player_id] = 0
    await broadcast_player_list()
    await broadcast_json({
            "type": "view_config",
            "countdown": timeouts["countdown"],
            "answer_time": timeouts["answer_time"], 
            "pause_between_rounds":   timeouts["pause_between_rounds"],
            "max_rounds": MAX_ROUNDS
        })
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if isinstance(msg, dict) and "type" in msg:
                    await handle_message(player_id, msg)
                else:
                    await handle_guess(player_id, data)
            except json.JSONDecodeError:
                await handle_guess(player_id, data)
    except WebSocketDisconnect:
        await remove_player(player_id)

async def handle_message(player_id, msg):
    global game_active
    if msg["type"] == "set_name":
        names[player_id] = msg["name"]
        await broadcast_player_list()
    elif msg["type"] == "set_ready":
        ready_status[player_id] = True
        await broadcast_player_list()
        if all(ready_status.values()) and len(ready_status) >= 1:
            await start_countdown()

async def handle_guess(player_id, data):
    global distance_answers
    logger.info(f"Received guess from {names[player_id]}: {data} km. (game is {'active' if game_active else 'inactive'})")
    if game_active:
        try:
            guess = int(data)
            distance_answers[player_id] = guess
            await clients[player_id].send_text(json.dumps({
                "type": "answer_received",
                "player": names[player_id],
                "guess": guess
            }))
            if len(distance_answers) >= len(clients):
                if distance_answer_deadline and not distance_answer_deadline.done():
                    logger.info("All players submitted an answer. Cancelling distance answer deadline")
                    distance_answer_deadline.cancel()
                await evaluate_distance_answers()
        except ValueError:
            await clients[player_id].send_text("Ungültige Eingabe. Bitte gib eine Zahl ein.")

async def remove_player(player_id):
    if player_id in clients:
        del clients[player_id]
        del names[player_id]
        del ready_status[player_id]
        del scores[player_id]
        await broadcast_player_list()

async def broadcast_player_list():
    player_list = [{"name": names[pid], "ready": ready_status[pid]} for pid in clients]
    await broadcast_json({"type": "player_list", "players": player_list})

async def broadcast_json(payload: dict):
    for ws in clients.values():
        await ws.send_text(json.dumps(payload))

async def broadcast(message: str):
    for ws in clients.values():
        await ws.send_text(message)

async def start_countdown():
    for i in range(timeouts["countdown"], 0, -1):
        await broadcast_json({"type": "countdown", "value": i})
        await asyncio.sleep(1)
    await broadcast_json({"type": "countdown", "value": 0})
    await broadcast_json({"type": "game_start"})
    

    await start_game()

async def start_game():
    global current_round, game_active
    current_round = 0
    game_active = True
    
    await next_round()

async def next_round():
    global current_round, distance_question, distance_answers, distance_answer_deadline, game_active

    if current_round >= MAX_ROUNDS:
        await broadcast("🎉 Spiel beendet!")
        await broadcast_json({"type": "game_end"})
        await reset_game()
        return

    current_round += 1
    distance_answers = {}
    distance_question = random.choice(list(city_distances.items()))
    cities, correct_distance = distance_question

    await broadcast_json({
        "type": "new_question",
        "round": current_round,
        "max_rounds": MAX_ROUNDS,
        "cities": cities,
        "question": f"Wie weit ist es von {cities[0]} nach {cities[1]}? (in km)"
    })
    logger.info(f"New question: {cities[0]} to {cities[1]}, correct distance: {correct_distance} km")
    distance_answer_deadline = asyncio.create_task(distance_answer_timeout())

async def distance_answer_timeout():
        for i in range(timeouts["answer_time"], 0, -1):
            await broadcast_json({"type": "countdown_round", "value": i})
            await asyncio.sleep(1)
        await broadcast_json({"type": "countdown_round", "value": 0})
        await evaluate_distance_answers()

async def evaluate_distance_answers():
    global game_active
    if not game_active:
        return

    cities, correct = distance_question
    await broadcast(f"Richtige Entfernung zwischen {cities[0]} und {cities[1]}: {correct} km")

    if len(distance_answers) < 1:
        await broadcast("Keine gültigen Antworten erhalten.")
        await pause_and_continue()
        return

    diffs = {pid: abs(guess - correct) for pid, guess in distance_answers.items()}
    winner_id = min(diffs, key=diffs.get)
    scores[winner_id] += 1

    await broadcast(f"{names[winner_id]} war mit {distance_answers[winner_id]} km also einer einer Diffenrenz von {round((float)(1-(distance_answers[winner_id]/correct))*100, 4)} % am nächsten dran und bekommt den Punkt!")
    await update_scores()
    await pause_and_continue()

async def pause_and_continue():
    await broadcast_json({"type": "pause", "seconds": timeouts["pause_between_rounds"]})
    await asyncio.sleep(timeouts["pause_between_rounds"])
    await next_round()

async def update_scores():
    score_board = {names[pid]: score for pid, score in scores.items()}
    await broadcast_json({
        "type": "score_update",
        "scores": score_board,
        "high_score": max(scores.values(), default=0)
    })

async def reset_game():
    global ready_status, scores, game_active, current_round
    ready_status = {pid: False for pid in clients}
    scores = {pid: 0 for pid in clients}
    game_active = False
    current_round = 0
    await broadcast_player_list()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
import random
import asyncio
from typing import List, Dict, Tuple, Optional
from models import GameState, Player, CityPair, GameStatus, GameRoom
from database import get_city_pairs, save_game_result, save_high_score, SessionLocal, DBGameResult
import uuid
from config import config
import logging

logger = logging.getLogger(__name__)


class GameLogic:
    def __init__(self, game_room: GameRoom, ws_handler=None):
        self.game_room = game_room
        self.ws_handler = ws_handler

    def generate_map_svg(self, lat1: float, lon1: float, lat2: float, lon2: float, city1: str, city2: str) -> str:
        """Generate SVG map of Germany with two cities and a line between them"""
        # Germany approximate bounds: lat 47-55, lon 5-15
        # SVG viewBox: 0 0 450 600 (matching the static map)
        # Map scale: 45 units per degree lon, 75 units per degree lat
        
        def coord_to_svg(lat: float, lon: float) -> Tuple[float, float]:
            # Transform lat/lon to SVG coordinates
            x = (lon - 5) * 45  # 10 degrees lon -> 450 units
            y = (55 - lat) * 75  # 8 degrees lat -> 600 units, inverted
            return x, y
        
        x1, y1 = coord_to_svg(lat1, lon1)
        x2, y2 = coord_to_svg(lat2, lon2)
        
        # Load the static Germany map
        with open('static/Karte_gruenes_deutschland.svg', 'r', encoding='utf-8') as f:
            static_svg = f.read()
        
        # Extract the content between <svg> and </svg>
        start = static_svg.find('<g')
        end = static_svg.rfind('</g>') + 4
        germany_map = static_svg[start:end]
        
        svg = f'''<svg width="450" height="600" viewBox="0 0 450 600" xmlns="http://www.w3.org/2000/svg">
            <!-- Germany map background -->
            {germany_map}
            
            <!-- Line between cities -->
            <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="green" stroke-width="3"/>
            
            <!-- City 1 -->
            <circle cx="{x1}" cy="{y1}" r="8" fill="red" stroke="black" stroke-width="2"/>
            <text x="{x1}" y="{y1-10}" text-anchor="middle" font-size="12" font-weight="bold" fill="black">{city1}</text>
            
            <!-- City 2 -->
            <circle cx="{x2}" cy="{y2}" r="8" fill="blue" stroke="black" stroke-width="2"/>
            <text x="{x2}" y="{y2-10}" text-anchor="middle" font-size="12" font-weight="bold" fill="black">{city2}</text>
        </svg>'''
        
        return svg
        
    def set_ws_handler(self, ws_handler):
        """Set the WebSocket handler for broadcasting messages"""
        self.ws_handler = ws_handler

    async def start_game(self, game_id: str) -> bool:
        """Start a new game if all players are ready"""
        game = self.game_room.get_game(game_id)
        if not game or not game.can_start():
            return False

        logger.info(f"Starting game {game_id}")
        game.reset()
        game.status = GameStatus.COUNTDOWN
        await self.next_round(game_id)
        return True

    async def next_round(self, game_id: str) -> bool:
        """Move to next round or end game"""
        try:
            game = self.game_room.get_game(game_id)
            if not game:
                return False

            if game.current_round >= game.config.max_rounds:
                await self.end_game(game_id)
                return False

            game.current_round += 1
            game.answers = {}
            game.status = GameStatus.ACTIVE

            # Get random city pair from database
            with SessionLocal() as db:
                city_pairs = get_city_pairs(db)
                if not city_pairs:
                    logger.error(f"No city pairs available for game {game_id}")
                    await self.end_game(game_id)
                    return False

                db_city_pair = random.choice(city_pairs)
                game.current_question = CityPair(
                    id=db_city_pair.id,
                    city1=db_city_pair.city1,
                    city2=db_city_pair.city2,
                    distance=db_city_pair.distance,
                    lat1=db_city_pair.lat1,
                    lon1=db_city_pair.lon1,
                    lat2=db_city_pair.lat2,
                    lon2=db_city_pair.lon2,
                    question_id= str(uuid.uuid4().hex[:8])
                )

            logger.info(f"Game {game_id}: New question: {game.current_question.cities[0]} to {game.current_question.cities[1]}, correct distance: {game.current_question.distance} km")

            # Broadcast the question to all players
            await self.broadcast_question(game_id)

            # Start answer timeout
            game.answer_deadline_task = asyncio.create_task(self.answer_timeout(game_id))
            return True
        except Exception as e:
            logger.error(f"Error in next_round for game {game_id}: {e}", exc_info=True)
            return False

    async def broadcast_question(self, game_id: str):
        """Broadcast current question to all players in the game"""
        try:
            if not self.ws_handler:
                logger.error("WebSocket handler not set, cannot broadcast question")
                return
                
            game = self.game_room.get_game(game_id)
            if not game or not game.current_question:
                return
            
            question = game.current_question
            svg_map = self.generate_map_svg(question.lat1, question.lon1, question.lat2, question.lon2, question.city1, question.city2)
            data = {
                "question_id": str(question.question_id),
                "round": game.current_round,
                "max_rounds": game.config.max_rounds,
                "time_limit": game.config.answer_time_seconds,
                "cities": [question.city1, question.city2],
                "city1": question.city1,
                "city2": question.city2,
                "question": f"Wie weit ist es von {question.city1} nach {question.city2}? (in km)",
                "map_svg": svg_map
            }
            
            # Broadcast to all players in the game
            await self.ws_handler.broadcast_to_game(game_id, "new_question", data)
            logger.info(f"Question broadcasted to game {game_id}")
        except Exception as e:
            logger.error(f"Error broadcasting question: {e}", exc_info=True)

    async def answer_timeout(self, game_id: str):
        """Handle answer timeout"""
        game = self.game_room.get_game(game_id)
        if not game:
            return

        for i in range(game.config.answer_time_seconds, 0, -1):
            if game.status != GameStatus.ACTIVE:
                return
            await asyncio.sleep(1)

        await self.evaluate_answers(game_id)

    async def submit_answer(self, game_id: str, player_id: str, guess: int) -> bool:
        """Submit player's answer"""
        game = self.game_room.get_game(game_id)
        if not game or game.status != GameStatus.ACTIVE or player_id not in game.players:
            return False

        game.answers[player_id] = guess
        logger.info(f"Game {game_id}: Received guess from {game.players[player_id].name}: {guess} km")

        # Check if all players have answered
        if len(game.answers) >= len(game.players):
            if game.answer_deadline_task and not game.answer_deadline_task.done():
                logger.info(f"Game {game_id}: All players submitted answers. Cancelling timeout")
                game.answer_deadline_task.cancel()
            await self.evaluate_answers(game_id)

        return True

    async def evaluate_answers(self, game_id: str):
        """Evaluate all submitted answers"""
        game = self.game_room.get_game(game_id)
        if not game or game.status != GameStatus.ACTIVE or not game.current_question:
            return

        question = game.current_question
        correct_distance = question.distance

        if len(game.answers) < 1:
            logger.info(f"Game {game_id}: No valid answers received")
            await self.pause_and_continue(game_id)
            return

        # Calculate differences and find winner
        diffs = {pid: abs(guess - correct_distance) for pid, guess in game.answers.items()}
        winner_id = min(diffs, key=diffs.get)
        winner = game.players[winner_id]
        winner.score += 1

        # Calculate accuracy percentage for winner
        winner_guess = game.answers[winner_id]
        accuracy_pct = game.calculate_accuracy_percentage(winner_guess, correct_distance)

        logger.info(f"Game {game_id} Round {game.current_round}: {winner.name} won with guess {winner_guess} km (accuracy: {accuracy_pct:.2f}%)")

        # Save result to database
        result_data = {
            "game_id": game_id,
            "player_name": winner.name,
            "guess": winner_guess,
            "correct_distance": correct_distance,
            "accuracy_percentage": accuracy_pct,
            "city1": question.city1,
            "city2": question.city2,
            "round_number": game.current_round
        }

        with SessionLocal() as db:
            save_game_result(db, result_data)

        await self.pause_and_continue(game_id)

    async def pause_and_continue(self, game_id: str):
        """Pause between rounds"""
        game = self.game_room.get_game(game_id)
        if not game:
            return

        game.status = GameStatus.PAUSED
        await asyncio.sleep(game.config.pause_between_rounds_seconds)
        await self.next_round(game_id)

    async def end_game(self, game_id: str):
        """End the current game and save high scores"""
        game = self.game_room.get_game(game_id)
        if not game or game.status == GameStatus.FINISHED:
            return

        logger.info(f"Game {game_id} ended")

        # Calculate final scores and accuracy for each player
        final_scores = {}
        with SessionLocal() as db:
            for player in game.players.values():
                # Get player's results for this game session
                results = db.query(DBGameResult).filter(
                    DBGameResult.game_id == game_id,
                    DBGameResult.player_name == player.name
                ).all()

                if results:
                    avg_accuracy = sum(r.accuracy_percentage for r in results) / len(results)
                    # Only save high scores for players who have results/score
                    if player.score > 0:
                        save_high_score(db, player.name, player.score, game.current_round, avg_accuracy)
                    final_scores[player.name] = {
                        "score": player.score,
                        "avg_accuracy": round(avg_accuracy, 1)
                    }
                else:
                    # Include players with no results (0 score, no accuracy)
                    final_scores[player.name] = {
                        "score": player.score,
                        "avg_accuracy": 0.0
                    }

        game.status = GameStatus.FINISHED
        
        # Broadcast game end message to all players
        if self.ws_handler:
            await self.ws_handler.broadcast_to_game(game_id, "game_finished", {
                "message": "Game finished!",
                "final_scores": final_scores,
                "winner": max(game.players.values(), key=lambda p: p.score).name if game.players else "No winner"
            })

    def get_game_status(self, game_id: str) -> Optional[Dict]:
        """Get current game status"""
        game = self.game_room.get_game(game_id)
        if not game:
            return None

        return {
            "id": game.id,
            "status": game.status.value,
            "current_round": game.current_round,
            "max_rounds": game.config.max_rounds,
            "players": [
                {
                    "name": p.name,
                    "ready": p.ready,
                    "score": p.score
                } for p in game.players.values()
            ],
            "current_question": {
                "cities": game.current_question.cities if game.current_question else None,
                "question": f"Wie weit ist es von {game.current_question.cities[0]} nach {game.current_question.cities[1]}? (in km)" if game.current_question else None
            } if game.current_question else None
        }
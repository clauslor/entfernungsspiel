from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
from typing import List, Optional
from config import config

Base = declarative_base()
engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class DBCityPair(Base):
    __tablename__ = "city_pairs"

    id = Column(Integer, primary_key=True, index=True)
    city1 = Column(String, index=True)
    city2 = Column(String, index=True)
    distance = Column(Integer)
    lat1 = Column(Float)
    lon1 = Column(Float)
    lat2 = Column(Float)
    lon2 = Column(Float)


class DBGameResult(Base):
    __tablename__ = "game_results"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(String, index=True)
    player_name = Column(String, index=True)
    guess = Column(Integer)
    correct_distance = Column(Integer)
    accuracy_percentage = Column(Float)
    city1 = Column(String)
    city2 = Column(String)
    round_number = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow)


class DBHighScore(Base):
    __tablename__ = "high_scores"

    id = Column(Integer, primary_key=True, index=True)
    player_name = Column(String, index=True)
    score = Column(Integer)
    total_rounds = Column(Integer)
    average_accuracy = Column(Float)
    games_played = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow)


class DBSortCitiesQuestion(Base):
    __tablename__ = "sort_cities_questions"

    id = Column(Integer, primary_key=True, index=True)
    prompt = Column(String)
    option1 = Column(String)
    option2 = Column(String)
    option3 = Column(String)
    option4 = Column(String)
    correct_order = Column(String)  # Comma-separated city names in correct order


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_city_pairs(db) -> List[DBCityPair]:
    """Get all city pairs from database"""
    return db.query(DBCityPair).all()


def get_sort_cities_questions(db) -> List[DBSortCitiesQuestion]:
    """Get all sort-cities questions from database"""
    return db.query(DBSortCitiesQuestion).all()


def add_city_pair(db, city1: str, city2: str, distance: int, lat1: float, lon1: float, lat2: float, lon2: float) -> DBCityPair:
    """Add a new city pair to database"""
    city_pair = DBCityPair(city1=city1, city2=city2, distance=distance, lat1=lat1, lon1=lon1, lat2=lat2, lon2=lon2)
    db.add(city_pair)
    db.commit()
    db.refresh(city_pair)
    return city_pair


def add_sort_cities_question(
    db,
    prompt: str,
    option1: str,
    option2: str,
    option3: str,
    option4: str,
    correct_order: str,
) -> DBSortCitiesQuestion:
    """Add a sort-cities question to database"""
    question = DBSortCitiesQuestion(
        prompt=prompt,
        option1=option1,
        option2=option2,
        option3=option3,
        option4=option4,
        correct_order=correct_order,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


def save_game_result(db, result_data: dict):
    """Save game result to database"""
    result = DBGameResult(**result_data)
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def get_high_scores(db, limit: int = 10) -> List[DBHighScore]:
    """Get top high scores"""
    return db.query(DBHighScore).order_by(DBHighScore.score.desc()).limit(limit).all()


def save_high_score(db, player_name: str, score: int, total_rounds: int, average_accuracy: float):
    """Save or update high score"""
    # Check if player already has a high score
    existing = db.query(DBHighScore).filter(DBHighScore.player_name == player_name).first()

    if existing:
        # Update if better score
        if score > existing.score:
            existing.score = score
            existing.total_rounds = total_rounds
            existing.average_accuracy = average_accuracy
            existing.games_played += 1
            existing.timestamp = datetime.utcnow()
    else:
        # Create new high score
        high_score = DBHighScore(
            player_name=player_name,
            score=score,
            total_rounds=total_rounds,
            average_accuracy=average_accuracy,
            games_played=1
        )
        db.add(high_score)

    db.commit()


def get_game_history(db, player_name: Optional[str] = None, limit: int = 50) -> List[DBGameResult]:
    """Get game history"""
    query = db.query(DBGameResult)
    if player_name:
        query = query.filter(DBGameResult.player_name == player_name)
    return query.order_by(DBGameResult.timestamp.desc()).limit(limit).all()


# Initialize default city pairs if database is empty
def init_default_city_pairs(db):
    """Initialize database with default city pairs"""
    if db.query(DBCityPair).count() == 0:
        default_pairs = [
            ("Berlin",	"Hamburg",	280,	52.52,	13.405,	53.5511,	9.9937),
            ("Berlin",	"München",	600,	52.52,	13.405,	48.1351,	11.582),
            ("Hamburg",	"München",	780,	53.5511,	9.9937,	48.1351,	11.582),
            ("Köln",	"Frankfurt",	180,	50.9375,	6.9603,	50.1109,	8.6821),
            ("Stuttgart",	"Dresden",	530,	48.7758,	9.1829,	51.0504,	13.7373),
            ("Leipzig",	"Nürnberg",	270,	51.3397,	12.3731,	49.4521,	11.0767)
        ]

        for city1, city2, distance, lat1, lon1, lat2, lon2 in default_pairs:
            add_city_pair(db, city1, city2, distance, lat1, lon1, lat2, lon2)


def init_default_sort_cities_questions(db):
    """Initialize database with default sort-cities questions"""
    if db.query(DBSortCitiesQuestion).count() == 0:
        default_sort_questions = [
            {
                "prompt": "Sortiere diese Staedte von Nord nach Sued",
                "options": ["Hamburg", "Berlin", "Muenchen", "Koeln"],
                "correct_order": ["Hamburg", "Berlin", "Koeln", "Muenchen"],
            },
            {
                "prompt": "Sortiere diese Staedte von West nach Ost",
                "options": ["Koeln", "Hamburg", "Berlin", "Dresden"],
                "correct_order": ["Koeln", "Hamburg", "Berlin", "Dresden"],
            },
            {
                "prompt": "Sortiere diese Staedte von Nord nach Sued",
                "options": ["Rostock", "Leipzig", "Frankfurt", "Stuttgart"],
                "correct_order": ["Rostock", "Leipzig", "Frankfurt", "Stuttgart"],
            },
        ]

        for entry in default_sort_questions:
            add_sort_cities_question(
                db,
                prompt=entry["prompt"],
                option1=entry["options"][0],
                option2=entry["options"][1],
                option3=entry["options"][2],
                option4=entry["options"][3],
                correct_order=",".join(entry["correct_order"]),
            )
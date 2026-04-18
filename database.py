from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
from typing import List, Optional
import json
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


class DBRouteDistanceCache(Base):
    __tablename__ = "route_distance_cache"

    id = Column(Integer, primary_key=True, index=True)
    city_pair_id = Column(Integer, index=True)
    provider = Column(String, default="graphhopper")
    profile = Column(String, default="car")
    distance_km = Column(Integer)
    updated_at = Column(DateTime, default=datetime.utcnow)


class DBRoutePointsCache(Base):
    __tablename__ = "route_points_cache"

    id = Column(Integer, primary_key=True, index=True)
    city_pair_id = Column(Integer, index=True)
    provider = Column(String, default="graphhopper")
    profile = Column(String, default="car")
    points_json = Column(String)
    updated_at = Column(DateTime, default=datetime.utcnow)


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


class DBCaptchaValidation(Base):
    __tablename__ = "captcha_validations"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(String, index=True, unique=True)
    validated_at = Column(DateTime, default=datetime.utcnow, index=True)
    expiry = Column(DateTime, index=True)
    question = Column(String)
    answer_hash = Column(String)


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


def add_city_pair(db, city1: str, city2: str, distance: int, lat1: float, lon1: float, lat2: float, lon2: float) -> DBCityPair:
    """Add a new city pair to database"""
    city_pair = DBCityPair(city1=city1, city2=city2, distance=distance, lat1=lat1, lon1=lon1, lat2=lat2, lon2=lon2)
    db.add(city_pair)
    db.commit()
    db.refresh(city_pair)
    return city_pair


def get_cached_route_distance_km(db, city_pair_id: int, provider: str = "graphhopper", profile: str = "car") -> Optional[int]:
    """Get cached route distance (km) for a city pair and routing profile."""
    row = (
        db.query(DBRouteDistanceCache)
        .filter(DBRouteDistanceCache.city_pair_id == city_pair_id)
        .filter(DBRouteDistanceCache.provider == provider)
        .filter(DBRouteDistanceCache.profile == profile)
        .first()
    )
    if not row:
        return None
    return int(row.distance_km)


def upsert_route_distance_km(
    db,
    city_pair_id: int,
    distance_km: int,
    provider: str = "graphhopper",
    profile: str = "car",
) -> DBRouteDistanceCache:
    """Insert or update cached route distance for a city pair/profile."""
    row = (
        db.query(DBRouteDistanceCache)
        .filter(DBRouteDistanceCache.city_pair_id == city_pair_id)
        .filter(DBRouteDistanceCache.provider == provider)
        .filter(DBRouteDistanceCache.profile == profile)
        .first()
    )
    if row:
        row.distance_km = int(distance_km)
        row.updated_at = datetime.utcnow()
    else:
        row = DBRouteDistanceCache(
            city_pair_id=city_pair_id,
            provider=provider,
            profile=profile,
            distance_km=int(distance_km),
            updated_at=datetime.utcnow(),
        )
        db.add(row)

    db.commit()
    db.refresh(row)
    return row


def get_cached_route_points(
    db,
    city_pair_id: int,
    provider: str = "graphhopper",
    profile: str = "car",
) -> Optional[list]:
    """Get cached route points list for a city pair/profile."""
    row = (
        db.query(DBRoutePointsCache)
        .filter(DBRoutePointsCache.city_pair_id == city_pair_id)
        .filter(DBRoutePointsCache.provider == provider)
        .filter(DBRoutePointsCache.profile == profile)
        .first()
    )
    if not row or not row.points_json:
        return None
    try:
        points = json.loads(row.points_json)
    except Exception:
        return None
    if not isinstance(points, list):
        return None
    return points


def upsert_route_points(
    db,
    city_pair_id: int,
    points: list,
    provider: str = "graphhopper",
    profile: str = "car",
) -> DBRoutePointsCache:
    """Insert or update cached route points for a city pair/profile."""
    row = (
        db.query(DBRoutePointsCache)
        .filter(DBRoutePointsCache.city_pair_id == city_pair_id)
        .filter(DBRoutePointsCache.provider == provider)
        .filter(DBRoutePointsCache.profile == profile)
        .first()
    )
    payload = json.dumps(points)
    if row:
        row.points_json = payload
        row.updated_at = datetime.utcnow()
    else:
        row = DBRoutePointsCache(
            city_pair_id=city_pair_id,
            provider=provider,
            profile=profile,
            points_json=payload,
            updated_at=datetime.utcnow(),
        )
        db.add(row)

    db.commit()
    db.refresh(row)
    return row


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


# ============= CAPTCHA VALIDATION FUNCTIONS =============

def is_captcha_valid(db, player_id: str) -> bool:
    """
    Check if a player has a valid captcha validation.
    
    Args:
        db: Database session
        player_id: Player's unique ID
        
    Returns:
        True if player has a valid, non-expired captcha validation
    """
    validation = db.query(DBCaptchaValidation).filter(
        DBCaptchaValidation.player_id == player_id
    ).first()
    
    if not validation:
        return False
    
    # Check if expired
    if datetime.utcnow() > validation.expiry:
        # Delete expired record
        db.delete(validation)
        db.commit()
        return False
    
    return True


def save_captcha_validation(db, player_id: str, question: str, answer_hash: str, expiry: datetime):
    """
    Save a successful captcha validation to database.
    
    Args:
        db: Database session
        player_id: Player's unique ID
        question: The question that was answered
        answer_hash: Hash of the correct answer
        expiry: When this validation expires
    """
    # Delete any existing validation for this player
    existing = db.query(DBCaptchaValidation).filter(
        DBCaptchaValidation.player_id == player_id
    ).first()
    
    if existing:
        db.delete(existing)
    
    # Create new validation record
    validation = DBCaptchaValidation(
        player_id=player_id,
        question=question,
        answer_hash=answer_hash,
        expiry=expiry,
        validated_at=datetime.utcnow()
    )
    db.add(validation)
    db.commit()
    db.refresh(validation)
    return validation


def get_captcha_validation(db, player_id: str) -> Optional[DBCaptchaValidation]:
    """Get captcha validation record for a player."""
    return db.query(DBCaptchaValidation).filter(
        DBCaptchaValidation.player_id == player_id
    ).first()


def delete_expired_captcha_validations(db):
    """Clean up expired captcha validations from database."""
    now = datetime.utcnow()
    db.query(DBCaptchaValidation).filter(
        DBCaptchaValidation.expiry <= now
    ).delete()
    db.commit()


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
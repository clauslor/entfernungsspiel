import os
from typing import List


class Config:
    # Server config
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "9000"))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    ROOT_PATH: str = os.getenv("ROOT_PATH", "/entfernungsspiel")

    # Database config
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./highscores.db")

    # CORS config
    ALLOWED_ORIGINS: List[str] = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")

    # Game config defaults
    DEFAULT_MAX_ROUNDS: int = int(os.getenv("DEFAULT_MAX_ROUNDS", "1"))
    DEFAULT_COUNTDOWN: int = int(os.getenv("DEFAULT_COUNTDOWN", "3"))
    DEFAULT_ANSWER_TIME: int = int(os.getenv("DEFAULT_ANSWER_TIME", "15"))
    DEFAULT_PAUSE_BETWEEN_ROUNDS: int = int(os.getenv("DEFAULT_PAUSE_BETWEEN_ROUNDS", "3"))

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "server.log")

    # External routing (optional)
    GRAPHHOPPER_API_KEY: str = os.getenv("GRAPHHOPPER_API_KEY", "")
    GRAPHHOPPER_PROFILE: str = os.getenv("GRAPHHOPPER_PROFILE", "car")
    ROAD_DISTANCE_QUESTION_CHANCE: float = float(os.getenv("ROAD_DISTANCE_QUESTION_CHANCE", "0.35"))

    # Admin
    ADMIN_USER: str = os.getenv("ADMIN_USER", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")


config = Config()
"""
Captcha service for bot protection.
Generates simple math questions and validates answers.
Stores validation tokens that are valid for 1 day.
"""

import random
import hashlib
import json
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict


class CaptchaService:
    """Service for generating and validating simple math CAPTCHAs."""

    # Difficulty levels with ranges
    OPERATORS = ["+", "-", "*"]
    MIN_OPERAND = 1
    MAX_OPERAND = 20

    @staticmethod
    def generate_captcha() -> Tuple[str, int]:
        """
        Generate a random math captcha question.
        
        Returns:
            Tuple of (question_text, correct_answer)
        """
        a = random.randint(CaptchaService.MIN_OPERAND, CaptchaService.MAX_OPERAND)
        b = random.randint(CaptchaService.MIN_OPERAND, CaptchaService.MAX_OPERAND)
        operator = random.choice(CaptchaService.OPERATORS)

        if operator == "+":
            answer = a + b
        elif operator == "-":
            # Avoid negative results
            a, b = max(a, b), min(a, b)
            answer = a - b
        else:  # operator == "*"
            # Keep products reasonable
            a = min(a, 10)
            b = min(b, 10)
            answer = a * b

        question = f"{a} {operator} {b}"
        return question, answer

    @staticmethod
    def hash_answer(answer: int) -> str:
        """
        Hash the answer for storage (never store raw answers in DB).
        
        Args:
            answer: The correct answer
            
        Returns:
            SHA256 hash of the answer
        """
        return hashlib.sha256(str(answer).encode()).hexdigest()

    @staticmethod
    def verify_answer(provided_answer: int, stored_hash: str) -> bool:
        """
        Verify that a provided answer matches the stored hash.
        
        Args:
            provided_answer: User's answer
            stored_hash: Stored hash from database
            
        Returns:
            True if answer is correct
        """
        try:
            provided_hash = CaptchaService.hash_answer(provided_answer)
            return provided_hash == stored_hash
        except (ValueError, TypeError):
            return False

    @staticmethod
    def create_validation_token(player_id: str) -> str:
        """
        Create a token to store in localStorage after successful captcha.
        
        Args:
            player_id: The player's unique ID
            
        Returns:
            Validation token
        """
        timestamp = datetime.utcnow().isoformat()
        token_data = f"{player_id}:{timestamp}"
        return hashlib.sha256(token_data.encode()).hexdigest()

    @staticmethod
    def get_expiry_time() -> datetime:
        """Get the expiry datetime (1 day from now)."""
        return datetime.utcnow() + timedelta(days=1)

    @staticmethod
    def is_expired(validated_at: datetime) -> bool:
        """Check if a captcha validation has expired (older than 1 day)."""
        if not validated_at:
            return True
        age = datetime.utcnow() - validated_at
        return age > timedelta(days=1)

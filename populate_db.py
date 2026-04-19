#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, add_city_pair, add_sorting_quiz_question, init_db, Base, engine
from sqlalchemy import text

# Drop and recreate table
with engine.connect() as conn:
    conn.execute(text("DROP TABLE IF EXISTS city_pairs"))
    conn.execute(text("DROP TABLE IF EXISTS sorting_quiz_questions"))
    conn.commit()

# Initialize database
init_db()

# Initialize database
init_db()

# German cities with approximate coordinates
cities_data = [
    ("Berlin", 52.5200, 13.4050, "Hamburg", 53.5511, 9.9937, 280),
    ("Berlin", 52.5200, 13.4050, "Munich", 48.1351, 11.5820, 600),
    ("Hamburg", 53.5511, 9.9937, "Munich", 48.1351, 11.5820, 780),
    ("Cologne", 50.9375, 6.9603, "Frankfurt", 50.1109, 8.6821, 180),
    ("Stuttgart", 48.7758, 9.1829, "Dresden", 51.0504, 13.7373, 530),
    ("Leipzig", 51.3397, 12.3731, "Nuremberg", 49.4521, 11.0767, 270),
]

with SessionLocal() as db:
    for city1, lat1, lon1, city2, lat2, lon2, dist in cities_data:
        add_city_pair(db, city1, city2, dist, lat1, lon1, lat2, lon2)
        print(f"Added: {city1} to {city2}, distance: {dist} km")

    pubquiz_sorting_questions = [
        {
            "prompt": "Ordne diese Fluesse nach Laenge (kurz nach lang).",
            "items": ["Rhein", "Main", "Mosel", "Neckar"],
            "correct_order": ["Main", "Neckar", "Mosel", "Rhein"],
        },
        {
            "prompt": "Ordne diese Planeten nach Abstand zur Sonne (nah nach fern).",
            "items": ["Mars", "Venus", "Jupiter", "Erde"],
            "correct_order": ["Venus", "Erde", "Mars", "Jupiter"],
        },
        {
            "prompt": "Ordne die Jahre chronologisch (frueh nach spaet).",
            "items": ["1989", "2006", "1998", "2014"],
            "correct_order": ["1989", "1998", "2006", "2014"],
        },
        {
            "prompt": "Ordne diese deutschen Staedte nach Einwohnerzahl (klein nach gross).",
            "items": ["Leipzig", "Koeln", "Hamburg", "Berlin"],
            "correct_order": ["Leipzig", "Koeln", "Hamburg", "Berlin"],
        },
        {
            "prompt": "Ordne diese Berge nach Hoehe (niedrig nach hoch).",
            "items": ["Watzmann", "Zugspitze", "Brocken", "Feldberg"],
            "correct_order": ["Brocken", "Feldberg", "Watzmann", "Zugspitze"],
        },
        {
            "prompt": "Ordne diese Bundeslaender nach Flaeche (klein nach gross).",
            "items": ["Saarland", "Hessen", "Niedersachsen", "Bayern"],
            "correct_order": ["Saarland", "Hessen", "Niedersachsen", "Bayern"],
        },
        {
            "prompt": "Ordne diese Planeten nach Durchmesser (klein nach gross).",
            "items": ["Venus", "Mars", "Erde", "Merkur"],
            "correct_order": ["Merkur", "Mars", "Venus", "Erde"],
        },
        {
            "prompt": "Ordne diese Ozeane nach Flaeche (klein nach gross).",
            "items": ["Indischer Ozean", "Pazifik", "Atlantik", "Arktischer Ozean"],
            "correct_order": ["Arktischer Ozean", "Indischer Ozean", "Atlantik", "Pazifik"],
        },
        {
            "prompt": "Ordne diese Baende nach Erscheinungsjahr (frueh nach spaet).",
            "items": ["Nirvana", "The Beatles", "Radiohead", "Queen"],
            "correct_order": ["The Beatles", "Queen", "Radiohead", "Nirvana"],
        },
        {
            "prompt": "Ordne diese Erfindungen nach Jahr (frueh nach spaet).",
            "items": ["Telefon", "Dampfmaschine", "Gluehbirne", "Buchdruck"],
            "correct_order": ["Buchdruck", "Dampfmaschine", "Telefon", "Gluehbirne"],
        },
    ]

    for question in pubquiz_sorting_questions:
        add_sorting_quiz_question(
            db,
            prompt=question["prompt"],
            items=question["items"],
            correct_order=question["correct_order"],
            source="pubquiz",
        )
        print(f"Added sorting question: {question['prompt']}")

print("Database populated with city pairs and pub-quiz sorting questions.")
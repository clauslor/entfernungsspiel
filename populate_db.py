#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, add_city_pair, init_db, engine
from sqlalchemy import text

# Drop and recreate table
with engine.connect() as conn:
    conn.execute(text("DROP TABLE IF EXISTS city_pairs"))
    conn.execute(text("DROP TABLE IF EXISTS sorting_quiz_questions"))
    conn.commit()

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

print("Database populated with city pairs and pub-quiz sorting questions.")
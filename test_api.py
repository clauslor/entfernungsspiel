#!/usr/bin/env python
"""Test the game API endpoints"""
import httpx
import json

BASE_URL = "http://localhost:8080"

print("=" * 60)
print("Testing Entfernungsspiel API")
print("=" * 60)

# Test 1: Health check
print("\n1. Health Check")
print("-" * 40)
try:
    response = httpx.get(f"{BASE_URL}/health", timeout=2)
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Server is running")
        print(f"  Active games: {data.get('active_games', 0)}")
        print(f"  Total players: {data.get('total_players', 0)}")
        print(f"  Active players: {data.get('active_players', 0)}")
    else:
        print(f"✗ Server returned status {response.status_code}")
except Exception as e:
    print(f"✗ Connection failed: {e}")

# Test 2: City pairs
print("\n2. City Pairs")
print("-" * 40)
try:
    response = httpx.get(f"{BASE_URL}/api/city-pairs", timeout=2)
    if response.status_code == 200:
        data = response.json()
        pairs = data.get('city_pairs', [])
        print(f"✓ Loaded {len(pairs)} city pairs")
        if pairs:
            for i, pair in enumerate(pairs[:3]):
                print(f"  {i+1}. {pair['city1']} - {pair['city2']}: {pair['distance']} km")
            if len(pairs) > 3:
                print(f"  ... and {len(pairs) - 3} more")
    else:
        print(f"✗ Request failed with status {response.status_code}")
except Exception as e:
    print(f"✗ Request failed: {e}")

# Test 3: High scores
print("\n3. High Scores")
print("-" * 40)
try:
    response = httpx.get(f"{BASE_URL}/api/high-scores", timeout=2)
    if response.status_code == 200:
        data = response.json()
        scores = data.get('high_scores', [])
        if scores:
            print(f"✓ Found {len(scores)} high scores")
            for i, score in enumerate(scores[:3]):
                print(f"  {i+1}. {score['player_name']}: {score['score']} points")
        else:
            print(f"✓ No high scores yet (first games haven't been played)")
    else:
        print(f"✗ Request failed with status {response.status_code}")
except Exception as e:
    print(f"✗ Request failed: {e}")

# Test 4: Game history
print("\n4. Game History")
print("-" * 40)
try:
    response = httpx.get(f"{BASE_URL}/api/game-history?limit=5", timeout=2)
    if response.status_code == 200:
        data = response.json()
        history = data.get('game_history', [])
        if history:
            print(f"✓ Found {len(history)} game history entries")
            for i, entry in enumerate(history[:3]):
                print(f"  {i+1}. {entry['player_name']}: {entry['city1']}-{entry['city2']} (guess: {entry['guess']}km)")
        else:
            print(f"✓ No game history yet")
    else:
        print(f"✗ Request failed with status {response.status_code}")
except Exception as e:
    print(f"✗ Request failed: {e}")

print("\n" + "=" * 60)
print("API Tests Complete")
print("=" * 60)
print("\nNow open http://localhost:8080 in your browser to play!")
print("Instructions:")
print("1. Enter your player name")
print("2. Click 'Create Game' or 'Join Game'")
print("3. Click 'Ready' button")
print("4. Answer distance questions for city pairs")
print("5. Try to get as close as possible to the correct distance!")

import json
import logging
from typing import Optional, Dict, Any
from urllib.parse import urlencode
from urllib.request import urlopen

logger = logging.getLogger(__name__)


def fetch_route_distance_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    api_key: str,
    profile: str = "car",
    timeout_seconds: int = 8,
) -> Optional[int]:
    """Fetch route distance from GraphHopper and return rounded km."""
    if not api_key:
        return None

    params = urlencode(
        {
            "point": [f"{lat1},{lon1}", f"{lat2},{lon2}"],
            "profile": profile,
            "calc_points": "false",
            "instructions": "false",
            "locale": "de",
            "key": api_key,
        },
        doseq=True,
    )
    url = f"https://graphhopper.com/api/1/route?{params}"

    try:
        with urlopen(url, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        paths = payload.get("paths") or []
        if not paths:
            return None
        meters = paths[0].get("distance")
        if meters is None:
            return None
        km = int(round(float(meters) / 1000.0))
        return max(1, km)
    except Exception as exc:
        logger.warning("GraphHopper route lookup failed: %s", exc)
        return None


def fetch_route_data(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    api_key: str,
    profile: str = "car",
    timeout_seconds: int = 8,
) -> Optional[Dict[str, Any]]:
    """Fetch route distance and route coordinates from GraphHopper.

    Returns:
      {
        "distance_km": int,
        "points": [{"lat": float, "lon": float}, ...]
      }
    """
    if not api_key:
        return None

    params = urlencode(
        {
            "point": [f"{lat1},{lon1}", f"{lat2},{lon2}"],
            "profile": profile,
            "calc_points": "true",
            "points_encoded": "false",
            "instructions": "false",
            "locale": "de",
            "key": api_key,
        },
        doseq=True,
    )
    url = f"https://graphhopper.com/api/1/route?{params}"

    try:
        with urlopen(url, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))

        paths = payload.get("paths") or []
        if not paths:
            return None

        path0 = paths[0]
        meters = path0.get("distance")
        if meters is None:
            return None

        points_data = (path0.get("points") or {}).get("coordinates") or []
        points = []
        for coord in points_data:
            if not isinstance(coord, list) or len(coord) < 2:
                continue
            lon = float(coord[0])
            lat = float(coord[1])
            points.append({"lat": lat, "lon": lon})

        km = int(round(float(meters) / 1000.0))
        return {
            "distance_km": max(1, km),
            "points": points,
        }
    except Exception as exc:
        logger.warning("GraphHopper route data lookup failed: %s", exc)
        return None

import json
import logging
from typing import Optional, Dict, Any
from urllib.parse import urlencode
from urllib.request import urlopen

logger = logging.getLogger(__name__)


def _normalize_osrm_profile(profile: str) -> str:
    value = (profile or "car").strip().lower()
    if value in {"car", "driving", "auto"}:
        return "driving"
    if value in {"bike", "bicycle", "cycling"}:
        return "cycling"
    if value in {"foot", "walk", "walking", "hike", "hiking"}:
        return "foot"
    return "driving"


def _fetch_graphhopper_route_data(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    api_key: str,
    profile: str = "car",
    timeout_seconds: int = 8,
) -> Optional[Dict[str, Any]]:
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
            "provider": "graphhopper",
            "profile": profile,
        }
    except Exception as exc:
        logger.warning("GraphHopper route data lookup failed: %s", exc)
        return None


def _fetch_osrm_route_data(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    profile: str = "car",
    base_url: str = "https://router.project-osrm.org",
    timeout_seconds: int = 8,
) -> Optional[Dict[str, Any]]:
    osrm_profile = _normalize_osrm_profile(profile)
    clean_base = (base_url or "https://router.project-osrm.org").rstrip("/")
    url = (
        f"{clean_base}/route/v1/{osrm_profile}/{lon1},{lat1};{lon2},{lat2}"
        "?overview=full&geometries=geojson&steps=false"
    )

    try:
        with urlopen(url, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))

        routes = payload.get("routes") or []
        if not routes:
            return None

        route = routes[0]
        meters = route.get("distance")
        if meters is None:
            return None

        coords = (route.get("geometry") or {}).get("coordinates") or []
        points = []
        for coord in coords:
            if not isinstance(coord, list) or len(coord) < 2:
                continue
            lon = float(coord[0])
            lat = float(coord[1])
            points.append({"lat": lat, "lon": lon})

        km = int(round(float(meters) / 1000.0))
        return {
            "distance_km": max(1, km),
            "points": points,
            "provider": "osrm",
            "profile": osrm_profile,
        }
    except Exception as exc:
        logger.warning("OSRM route data lookup failed: %s", exc)
        return None


def fetch_route_distance_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    api_key: str,
    profile: str = "car",
    timeout_seconds: int = 8,
) -> Optional[int]:
    """Backward-compatible helper that returns only distance in km."""
    route_data = fetch_route_data(
        lat1,
        lon1,
        lat2,
        lon2,
        api_key=api_key,
        profile=profile,
        timeout_seconds=timeout_seconds,
    )
    if not route_data:
        return None
    return int(route_data.get("distance_km") or 0) or None


def fetch_route_data(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    api_key: str = "",
    profile: str = "car",
    provider: str = "auto",
    osrm_base_url: str = "https://router.project-osrm.org",
    timeout_seconds: int = 8,
) -> Optional[Dict[str, Any]]:
    """Fetch route distance and route coordinates from configured routing provider.

    Returns:
      {
        "distance_km": int,
        "points": [{"lat": float, "lon": float}, ...]
      }
    """
    selected_provider = (provider or "auto").strip().lower()

    if selected_provider == "graphhopper":
        return _fetch_graphhopper_route_data(
            lat1,
            lon1,
            lat2,
            lon2,
            api_key=api_key,
            profile=profile,
            timeout_seconds=timeout_seconds,
        )

    if selected_provider == "osrm":
        return _fetch_osrm_route_data(
            lat1,
            lon1,
            lat2,
            lon2,
            profile=profile,
            base_url=osrm_base_url,
            timeout_seconds=timeout_seconds,
        )

    # auto mode: prefer GraphHopper when a key is available, otherwise use free OSRM.
    if api_key:
        gh_data = _fetch_graphhopper_route_data(
            lat1,
            lon1,
            lat2,
            lon2,
            api_key=api_key,
            profile=profile,
            timeout_seconds=timeout_seconds,
        )
        if gh_data:
            return gh_data

    return _fetch_osrm_route_data(
        lat1,
        lon1,
        lat2,
        lon2,
        profile=profile,
        base_url=osrm_base_url,
        timeout_seconds=timeout_seconds,
    )

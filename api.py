"""JSON API over the weather_api helpers."""

from pathlib import Path

import time

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from disasters import get_combined_feed
from weather_api import (
    ACTIVITIES,
    _get_api_key,
    get_advisory,
    get_air_quality,
    get_current_weather,
    get_forecast,
    get_hourly_forecast,
    search_cities,
)

app = FastAPI(title="Weather API")


def _call(func, *args):
    """Run a weather_api call, turning its RuntimeError into a 502."""
    try:
        return func(*args)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/search")
def search(q: str = Query(...)):
    return _call(search_cities, q)


@app.get("/api/weather")
def weather(lat: float = Query(...), lon: float = Query(...)):
    return _call(get_current_weather, lat, lon)


@app.get("/api/forecast")
def forecast(lat: float = Query(...), lon: float = Query(...)):
    return _call(get_forecast, lat, lon)


@app.get("/api/hourly")
def hourly(lat: float = Query(...), lon: float = Query(...)):
    return _call(get_hourly_forecast, lat, lon)


@app.get("/api/air")
def air(lat: float = Query(...), lon: float = Query(...)):
    return _call(get_air_quality, lat, lon)


@app.get("/api/advisory")
def advisory(
    lat: float = Query(...), lon: float = Query(...), activity: str = Query(...)
):
    if activity not in ACTIVITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown activity '{activity}'. Expected one of: "
            f"{', '.join(ACTIVITIES)}.",
        )
    days = _call(get_forecast, lat, lon)
    return _call(get_advisory, days, activity)


FEED_TTL_SECONDS = 600

# {(limit, include_minor): (fetched_at, items)}
_feed_cache = {}


@app.get("/api/feed")
def feed(limit: int = Query(40), include_minor: bool = Query(False)):
    key = (limit, include_minor)
    cached = _feed_cache.get(key)
    if cached and time.monotonic() - cached[0] < FEED_TTL_SECONDS:
        return cached[1]

    items = _call(get_combined_feed, limit, include_minor)
    _feed_cache[key] = (time.monotonic(), items)
    return items


TILE_LAYERS = ("clouds_new", "precipitation_new", "temp_new", "wind_new")

TILE_URL = "https://tile.openweathermap.org/map/{layer}/{z}/{x}/{y}.png"


@app.get("/api/tiles/{layer}/{z}/{x}/{y}.png")
def tile(layer: str, z: int, x: int, y: int):
    if layer not in TILE_LAYERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown layer '{layer}'. Expected one of: "
            f"{', '.join(TILE_LAYERS)}.",
        )

    try:
        api_key = _get_api_key()
        response = requests.get(
            TILE_URL.format(layer=layer, z=z, x=x, y=y),
            params={"appid": api_key},
            timeout=10,
        )
        response.raise_for_status()
    except (requests.RequestException, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return Response(
        content=response.content,
        media_type="image/png",
        headers={"Cache-Control": "max-age=600"},
    )


# Mounted last so every /api/ route above is matched first.
app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="static",
)

"""JSON API over the weather_api helpers."""

from pathlib import Path

import time

import requests
from fastapi import FastAPI, HTTPException, Query
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from disasters import get_combined_feed, get_event_detail
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


# {event_id: (fetched_at, detail)}
_event_cache = {}


@app.get("/api/event/{event_id}")
def event(event_id: str):
    cached = _event_cache.get(event_id)
    if cached and time.monotonic() - cached[0] < FEED_TTL_SECONDS:
        return cached[1]

    try:
        detail = get_event_detail(event_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=404, detail="No detail available for this source"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _event_cache[event_id] = (time.monotonic(), detail)
    return detail


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


STATIC_DIR = Path(__file__).parent / "static"


class SPAStaticFiles(StaticFiles):
    """Serve static files, falling back to index.html for client-side routes.

    A mount at "/" matches every path, so any route registered after it is
    unreachable - the fallback has to live inside the mount rather than in a
    catch-all route behind it. Unknown /api/ paths keep their 404.
    """

    async def get_response(self, path, scope):
        # With html=True a missing file is raised, not returned, so catch both.
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith("api/"):
                return FileResponse(STATIC_DIR / "index.html")
            raise

        if response.status_code == 404 and not path.startswith("api/"):
            return FileResponse(STATIC_DIR / "index.html")
        return response


# Mounted last so every /api/ route above is matched first.
app.mount("/", SPAStaticFiles(directory=STATIC_DIR, html=True), name="static")

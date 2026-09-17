"""OpenWeatherMap API helpers."""

import os
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

try:
    import streamlit as st
except ImportError:  # The module still works when run outside Streamlit.
    st = None

load_dotenv()

GEOCODING_URL = "http://api.openweathermap.org/geo/1.0/direct"
CURRENT_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
AIR_POLLUTION_URL = "http://api.openweathermap.org/data/2.5/air_pollution"

AQI_LABELS = {1: "Good", 2: "Fair", 3: "Moderate", 4: "Poor", 5: "Very Poor"}

ACTIVITIES = ("spraying", "event", "drying")


def _get_api_key():
    """Return the OpenWeatherMap API key from st.secrets or the environment.

    Prefers Streamlit secrets so the app works when deployed, and falls back
    to OPENWEATHER_API_KEY from .env / the environment when running locally.
    """
    if st is not None:
        try:
            return st.secrets["OPENWEATHER_API_KEY"]
        except Exception:
            # No secrets file, no such key, or no Streamlit runtime - fall back.
            pass

    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENWEATHER_API_KEY is not set. Add it to your .env file or to "
            "Streamlit secrets."
        )
    return api_key


def search_cities(city_name, limit=5):
    """Search for cities matching `city_name` via the OpenWeatherMap Geocoding API.

    Returns a list of dicts with keys: name, state, country, lat, lon.
    Returns an empty list if nothing matches.
    """
    api_key = _get_api_key()

    params = {"q": city_name, "limit": limit, "appid": api_key}

    try:
        response = requests.get(GEOCODING_URL, params=params, timeout=10)
        response.raise_for_status()
        results = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to search for '{city_name}': {exc}") from exc
    except ValueError as exc:
        raise RuntimeError(
            f"Got an invalid response while searching for '{city_name}': {exc}"
        ) from exc

    return [
        {
            "name": city.get("name", ""),
            "state": city.get("state", ""),
            "country": city.get("country", ""),
            "lat": city.get("lat"),
            "lon": city.get("lon"),
        }
        for city in results
    ]


def get_current_weather(lat, lon):
    """Fetch current weather for a coordinate via the OpenWeatherMap API.

    Returns a dict with keys: temp, feels_like, humidity, wind_speed,
    description, icon, city_name, timezone_offset (seconds from UTC).
    """
    api_key = _get_api_key()

    params = {"lat": lat, "lon": lon, "units": "metric", "appid": api_key}

    try:
        response = requests.get(CURRENT_WEATHER_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Failed to get weather for ({lat}, {lon}): {exc}"
        ) from exc
    except ValueError as exc:
        raise RuntimeError(
            f"Got an invalid response while getting weather for ({lat}, {lon}): {exc}"
        ) from exc

    main = data.get("main", {})
    wind = data.get("wind", {})
    weather = (data.get("weather") or [{}])[0]

    return {
        "temp": main.get("temp"),
        "feels_like": main.get("feels_like"),
        "humidity": main.get("humidity"),
        "wind_speed": wind.get("speed"),
        "description": weather.get("description", ""),
        "icon": weather.get("icon", ""),
        "city_name": data.get("name", ""),
        "timezone_offset": data.get("timezone", 0),
    }


def get_forecast(lat, lon):
    """Fetch the 5-day / 3-hour forecast for a coordinate and summarize it per day.

    Entries are grouped by LOCAL date (using the city's timezone offset).
    Returns a list of dicts in chronological order with keys:
    date (a date object), temp_min, temp_max, icon, description.
    The icon and description come from the entry closest to 12:00 local time.
    """
    api_key = _get_api_key()

    params = {"lat": lat, "lon": lon, "units": "metric", "appid": api_key}

    try:
        response = requests.get(FORECAST_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Failed to get forecast for ({lat}, {lon}): {exc}"
        ) from exc
    except ValueError as exc:
        raise RuntimeError(
            f"Got an invalid response while getting forecast for ({lat}, {lon}): {exc}"
        ) from exc

    offset = timedelta(seconds=data.get("city", {}).get("timezone", 0))

    days = {}
    for entry in data.get("list", []):
        local = datetime.fromtimestamp(entry["dt"], tz=timezone.utc) + offset
        temp = entry.get("main", {}).get("temp")
        weather = (entry.get("weather") or [{}])[0]
        # Distance from 12:00 local time, used to pick the day's representative entry.
        noon_delta = abs(
            (local.hour * 3600 + local.minute * 60 + local.second) - 12 * 3600
        )

        day = days.get(local.date())
        if day is None:
            days[local.date()] = {
                "date": local.date(),
                "temp_min": temp,
                "temp_max": temp,
                "icon": weather.get("icon", ""),
                "description": weather.get("description", ""),
                "_noon_delta": noon_delta,
            }
            continue

        if temp is not None:
            if day["temp_min"] is None or temp < day["temp_min"]:
                day["temp_min"] = temp
            if day["temp_max"] is None or temp > day["temp_max"]:
                day["temp_max"] = temp
        if noon_delta < day["_noon_delta"]:
            day["_noon_delta"] = noon_delta
            day["icon"] = weather.get("icon", "")
            day["description"] = weather.get("description", "")

    forecast = []
    for date in sorted(days):
        day = days[date]
        del day["_noon_delta"]
        forecast.append(day)
    return forecast


def get_air_quality(lat, lon):
    """Fetch current air quality for a coordinate via the OpenWeatherMap API.

    Returns a dict with keys: aqi (1-5), aqi_label, and the pollutant
    concentrations pm2_5, pm10, o3, no2, so2, co (all in µg/m³).
    """
    api_key = _get_api_key()

    params = {"lat": lat, "lon": lon, "appid": api_key}

    try:
        response = requests.get(AIR_POLLUTION_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Failed to get air quality for ({lat}, {lon}): {exc}"
        ) from exc
    except ValueError as exc:
        raise RuntimeError(
            f"Got an invalid response while getting air quality for ({lat}, {lon}): {exc}"
        ) from exc

    readings = data.get("list") or []
    if not readings:
        raise RuntimeError(f"No air quality data available for ({lat}, {lon}).")

    reading = readings[0]
    aqi = reading.get("main", {}).get("aqi")
    components = reading.get("components", {})

    return {
        "aqi": aqi,
        "aqi_label": AQI_LABELS.get(aqi, "Unknown"),
        "pm2_5": components.get("pm2_5"),
        "pm10": components.get("pm10"),
        "o3": components.get("o3"),
        "no2": components.get("no2"),
        "so2": components.get("so2"),
        "co": components.get("co"),
    }


def get_advisory(forecast, activity):
    """Judge each forecast day for an activity: "spraying", "event" or "drying".

    Takes the list returned by get_forecast(). Returns a list of dicts with
    keys: date (passed through), verdict ("go", "caution" or "no-go"), and
    reason (a short plain-language explanation).
    """
    if activity not in ACTIVITIES:
        raise ValueError(
            f"Unknown activity '{activity}'. Expected one of: {', '.join(ACTIVITIES)}."
        )

    advisory = []
    for day in forecast:
        description = (day.get("description") or "").lower()
        temp_max = day.get("temp_max")
        hot = temp_max is not None and temp_max > 32
        very_hot = temp_max is not None and temp_max > 33
        summary = description.capitalize() if description else "No description"

        if activity == "spraying":
            if "rain" in description:
                verdict = "no-go"
                reason = f"{summary} - spray will wash off"
            elif hot:
                verdict = "caution"
                reason = f"High of {round(temp_max)}°C - spray early or late in the day"
            else:
                verdict = "go"
                reason = f"{summary} - good spraying window"

        elif activity == "event":
            if "moderate rain" in description or "heavy" in description:
                verdict = "no-go"
                reason = f"{summary} - too wet to hold outdoors"
            elif "rain" in description:
                verdict = "caution"
                reason = f"{summary} - have cover ready"
            elif very_hot:
                verdict = "caution"
                reason = f"High of {round(temp_max)}°C - arrange shade and water"
            else:
                verdict = "go"
                reason = f"{summary} - comfortable conditions"

        else:  # drying
            if "rain" in description:
                verdict = "no-go"
                reason = f"{summary} - crop will not dry"
            elif "clouds" in description:
                verdict = "caution"
                reason = f"{summary} - drying will be slow"
            else:
                verdict = "go"
                reason = "Clear enough - good drying conditions"

        advisory.append({"date": day.get("date"), "verdict": verdict, "reason": reason})

    return advisory


if __name__ == "__main__":
    fc = get_forecast(13.0059, 5.2476)   # Sokoto
    for row in get_advisory(fc, "spraying"):
        print(row)
"""Natural disaster feeds. None of these sources need an API key."""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlparse

import requests

logger = logging.getLogger(__name__)

# Every feed is normalised to this shape, with None where a source has nothing.
FEED_KEYS = (
    "id",
    "type",
    "title",
    "location",
    "magnitude",
    "value",
    "unit",
    "depth_km",
    "severity",
    "level",
    "time",
    "since",
    "lat",
    "lon",
    "url",
)

USGS_URL = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/"
    "{significance}_{period}.geojson"
)

PERIODS = ("hour", "day", "week")


def get_earthquakes(min_magnitude=4.5, period="day"):
    """Fetch recent earthquakes from the USGS feed, newest first.

    period is "hour", "day" or "week". The closest USGS feed is fetched and
    then filtered locally, so min_magnitude is honoured exactly.

    Returns a list of dicts with keys: type, title, location, magnitude,
    depth_km, time (timezone-aware UTC), lat, lon, url.
    """
    if period not in PERIODS:
        raise ValueError(
            f"Unknown period '{period}'. Expected one of: {', '.join(PERIODS)}."
        )

    if min_magnitude == 4.5:
        significance = "4.5"
    elif min_magnitude == 2.5:
        significance = "2.5"
    else:
        significance = "all"

    url = USGS_URL.format(significance=significance, period=period)

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to get earthquakes: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError(
            f"Got an invalid response from the USGS feed: {exc}"
        ) from exc

    events = []
    for feature in data.get("features", []):
        properties = feature.get("properties", {})
        magnitude = properties.get("mag")
        if magnitude is None or magnitude < min_magnitude:
            continue

        coordinates = feature.get("geometry", {}).get("coordinates") or []
        lon, lat, depth = (list(coordinates) + [None, None, None])[:3]
        milliseconds = properties.get("time")

        # The event id is the last path segment of the event page url.
        event_url = properties.get("url", "")
        raw_id = urlparse(event_url).path.rsplit("/", 1)[-1] or feature.get("id")

        events.append(
            {
                "id": f"usgs:{raw_id}" if raw_id else None,
                "type": "earthquake",
                "title": f"M {magnitude:.1f} earthquake",
                "location": properties.get("place", ""),
                "magnitude": magnitude,
                "depth_km": depth,
                "time": (
                    datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
                    if milliseconds is not None
                    else None
                ),
                "lat": lat,
                "lon": lon,
                "url": properties.get("url", ""),
            }
        )

    events.sort(key=lambda event: event["time"] or datetime.min.replace(
        tzinfo=timezone.utc
    ), reverse=True)
    return events

GDACS_URL = "https://www.gdacs.org/xml/rss.xml"

GDACS_NS = "{http://www.gdacs.org}"
GEORSS_NS = "{http://www.georss.org/georss}"

# GDACS uses two-letter codes for the event type.
GDACS_EVENT_TYPES = {
    "FL": "flood",
    "TC": "cyclone",
    "DR": "drought",
    "WF": "wildfire",
    "EQ": "earthquake",
    "VO": "volcano",
}

EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"


def _text(element, path):
    """Return stripped text for a child element, or None when it is absent/empty."""
    if element is None:
        return None
    value = element.findtext(path)
    value = value.strip() if value else ""
    return value or None


def get_gdacs_alerts():
    """Fetch current GDACS alerts, newest first.

    Returns dicts in the shared feed shape. GDACS earthquake items are skipped
    because get_earthquakes covers them in more detail.
    """
    try:
        response = requests.get(GDACS_URL, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to get GDACS alerts: {exc}") from exc
    except ET.ParseError as exc:
        raise RuntimeError(f"Got invalid XML from the GDACS feed: {exc}") from exc

    alerts = []
    for item in root.findall("./channel/item"):
        code = _text(item, f"{GDACS_NS}eventtype")
        event_type = GDACS_EVENT_TYPES.get(code, code.lower() if code else None)
        if event_type == "earthquake":
            continue

        # georss:point is "lat lon" in one string.
        lat = lon = None
        point = _text(item, f"{GEORSS_NS}point")
        if point:
            parts = point.split()
            if len(parts) == 2:
                try:
                    lat, lon = float(parts[0]), float(parts[1])
                except ValueError:
                    lat = lon = None

        # gdacs:severity carries the measurement as attributes: km/h for
        # cyclones, ha for wildfires, km2 for droughts, nothing for floods.
        value = unit = None
        severity_el = item.find(f"{GDACS_NS}severity")
        if severity_el is not None:
            unit = (severity_el.get("unit") or "").strip() or None
            if unit:
                try:
                    value = float(severity_el.get("value"))
                except (TypeError, ValueError):
                    value = None
        if value is None:
            unit = None

        alert_level = _text(item, f"{GDACS_NS}alertlevel")

        published = _text(item, "pubDate")
        when = None
        if published:
            try:
                when = parsedate_to_datetime(published).astimezone(timezone.utc)
            except (TypeError, ValueError):
                when = None

        # eventtype and eventid live in the report url's query string.
        link = _text(item, "link") or ""
        query = parse_qs(urlparse(link).query)
        gdacs_type = (query.get("eventtype") or [None])[0]
        gdacs_id = (query.get("eventid") or [None])[0]

        alerts.append(
            {
                "id": (
                    f"gdacs:{gdacs_type}-{gdacs_id}"
                    if gdacs_type and gdacs_id
                    else None
                ),
                "type": event_type,
                "title": _text(item, "title"),
                "location": _text(item, f"{GDACS_NS}country"),
                "magnitude": None,
                "value": value,
                "unit": unit,
                "depth_km": None,
                "severity": _text(item, f"{GDACS_NS}severity"),
                "level": (alert_level.lower() if alert_level else None),
                "time": when,
                "lat": lat,
                "lon": lon,
                "url": _text(item, "link"),
            }
        )

    return _sort_newest_first(alerts)


def get_eonet_events(limit=20):
    """Fetch open NASA EONET events, newest first, in the shared feed shape."""
    try:
        response = requests.get(
            EONET_URL, params={"status": "open", "limit": limit}, timeout=10
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to get EONET events: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError(f"Got an invalid response from EONET: {exc}") from exc

    events = []
    for event in data.get("events", []):
        # Controlled burns are planned operations, not disasters.
        title = event.get("title") or ""
        if "Prescribed Fire" in title or "RX" in title:
            continue

        categories = event.get("categories") or []
        category = categories[0].get("title") if categories else None

        geometry = event.get("geometry") or []
        latest = geometry[-1] if geometry else {}
        when = _parse_iso(latest.get("date"))

        # Only Point geometries give a single coordinate; tracks/polygons do not.
        lat = lon = None
        coordinates = latest.get("coordinates")
        if latest.get("type") == "Point" and isinstance(coordinates, list):
            if len(coordinates) >= 2:
                lon, lat = coordinates[0], coordinates[1]

        sources = event.get("sources") or []
        url = sources[0].get("url") if sources else event.get("link")

        events.append(
            {
                "id": f"eonet:{event['id']}" if event.get("id") else None,
                "type": category.lower() if category else None,
                "title": title,
                "location": event.get("description") or None,
                "magnitude": None,
                "value": latest.get("magnitudeValue"),
                "unit": latest.get("magnitudeUnit"),
                "depth_km": None,
                "severity": None,
                "level": None,
                "time": when,
                "lat": lat,
                "lon": lon,
                "url": url,
            }
        )

    return _sort_newest_first(events)


def _parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime, or None."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sort_newest_first(events):
    """Sort in place by time, newest first, with undated events last."""
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    events.sort(key=lambda event: event["time"] or oldest, reverse=True)
    return events


def _deduplicate(events):
    """Keep one item per (type, title), the newest.

    Sources re-report the same event with different timestamps, sometimes days
    apart, so the time gap is not part of the key. The newest is chosen by
    comparing times, so this does not depend on the incoming order.
    """
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    best = {}
    for event in events:
        key = (event["type"], event["title"])
        current = best.get(key)
        if current is None or (event["time"] or oldest) > (current["time"] or oldest):
            best[key] = event

    return list(best.values())


RECENT_DAYS = 7

MAX_ONGOING = 10

MAX_PER_TYPE = 15

# Wildfires vastly outnumber everything else, so they get a tighter cap.
# Both spellings appear: GDACS says "wildfire", EONET says "wildfires".
MAX_PER_TYPE_OVERRIDES = {"wildfire": 5, "wildfires": 5}


def _balance_types(events):
    """Keep only the first N items of each type, then re-sort newest first.

    Expects newest-first input, so the survivors of each group are its newest.
    N is MAX_PER_TYPE unless MAX_PER_TYPE_OVERRIDES names the type.
    """
    groups = {}
    for event in events:
        groups.setdefault(event["type"], []).append(event)

    merged = []
    for event_type, group in groups.items():
        cap = MAX_PER_TYPE_OVERRIDES.get(event_type, MAX_PER_TYPE)
        merged.extend(group[:cap])

    return _sort_newest_first(merged)


MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _since_label(when, now):
    """A human "since ..." string for a long-running event.

    Recent enough to place precisely, give the day: "since 30 April". Older
    than a month, the month alone reads better: "since February", plus the
    year once it is no longer the current one.
    """
    if when is None:
        return None

    month = MONTHS[when.month - 1]
    if when.year != now.year:
        return f"since {month} {when.year}"
    if (now - when).days < 30:
        return f"since {when.day} {month}"
    return f"since {month}"


def get_combined_feed(limit=40, include_minor=False):
    """Merge every feed into two groups: "recent" and "ongoing".

    "recent" holds events from the last RECENT_DAYS days, "ongoing" everything
    older, each carrying a "since" label for the UI. Both are newest first.

    A source that fails is logged and skipped so one dead feed cannot empty
    the page. Green GDACS alerts are dropped unless include_minor is True.
    Dedup and the per-type caps are applied to each group separately; `limit`
    bounds "recent" only, while "ongoing" is capped at MAX_ONGOING.
    """
    combined = []
    for name, fetch in (
        ("USGS earthquakes", get_earthquakes),
        ("GDACS alerts", get_gdacs_alerts),
        ("EONET events", get_eonet_events),
    ):
        try:
            combined.extend(fetch())
        except (RuntimeError, ValueError) as exc:
            logger.warning("Skipping %s: %s", name, exc)

    events = [{key: event.get(key) for key in FEED_KEYS} for event in combined]

    if not include_minor:
        events = [event for event in events if event["level"] != "green"]

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RECENT_DAYS)

    recent = [e for e in events if e["time"] is not None and e["time"] >= cutoff]
    ongoing = [e for e in events if e["time"] is None or e["time"] < cutoff]

    # Dedup and cap each group on its own, so a long-running event cannot
    # use up a type's allowance in the recent list, or the other way round.
    recent = _balance_types(_sort_newest_first(_deduplicate(recent)))
    ongoing = _balance_types(_sort_newest_first(_deduplicate(ongoing)))

    for event in ongoing:
        event["since"] = _since_label(event["time"], now)

    return {"recent": recent[:limit], "ongoing": ongoing[:MAX_ONGOING]}

USGS_DETAIL_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"


def get_event_detail(event_id):
    """Look up one event by its prefixed feed id.

    Only USGS earthquakes have a detail endpoint. GDACS and EONET raise
    LookupError so the UI can fall back to what the feed already gave it.
    """
    source, _, raw_id = (event_id or "").partition(":")

    if source in ("gdacs", "eonet"):
        raise LookupError(f"{source} has no detail endpoint for '{raw_id}'.")
    if source != "usgs":
        raise ValueError(f"Unknown event id '{event_id}'.")

    try:
        response = requests.get(
            USGS_DETAIL_URL,
            params={"eventid": raw_id, "format": "geojson"},
            timeout=10,
        )
        response.raise_for_status()
        feature = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to get event '{event_id}': {exc}") from exc
    except ValueError as exc:
        raise RuntimeError(
            f"Got an invalid response for event '{event_id}': {exc}"
        ) from exc

    properties = feature.get("properties", {})
    coordinates = feature.get("geometry", {}).get("coordinates") or []
    lon, lat, depth = (list(coordinates) + [None, None, None])[:3]
    magnitude = properties.get("mag")
    milliseconds = properties.get("time")

    return {
        "id": f"usgs:{raw_id}",
        "type": "earthquake",
        "title": (
            f"M {magnitude:.1f} earthquake" if magnitude is not None else "Earthquake"
        ),
        "location": properties.get("place", ""),
        "magnitude": magnitude,
        "value": None,
        "unit": None,
        "depth_km": depth,
        "severity": None,
        "level": None,
        "time": (
            datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
            if milliseconds is not None
            else None
        ),
        "since": None,
        "lat": lat,
        "lon": lon,
        "url": properties.get("url", ""),
        "felt": properties.get("felt"),
        "alert": properties.get("alert"),
        "tsunami": bool(properties.get("tsunami")),
        "significance": properties.get("sig"),
        "status": properties.get("status"),
    }


if __name__ == "__main__":
    feed = get_combined_feed()

    for group in ("recent", "ongoing"):
        items = feed[group]
        print(f"\n{group}: {len(items)} items")
        for item in items[:8]:
            when = item["since"] or item["time"]
            print(" ", item["type"], "|", item["title"], "|", when)

        counts = {}
        for item in items:
            counts[item["type"]] = counts.get(item["type"], 0) + 1
        print(f"  per-type counts ({group}):")
        for event_type, count in sorted(counts.items(), key=lambda pair: -pair[1]):
            cap = MAX_PER_TYPE_OVERRIDES.get(event_type, MAX_PER_TYPE)
            print(f"    {event_type:<15} {count:>3}  (cap {cap})")

if __name__ == "__main__":
    feed = get_combined_feed()
    quake = next(i for i in feed["recent"] if i["type"] == "earthquake")
    print(quake["id"])
    print(get_event_detail(quake["id"]))
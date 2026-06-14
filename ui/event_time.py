from __future__ import annotations
from datetime import datetime, timezone, timedelta
import re


def parse_gmt_offset(value: str) -> timezone:
    """Parse 'GMT-6', 'GMT+5:30', 'GMT+0', etc. → datetime.timezone.

    Falls back to GMT-6 (Mexico City) on any parse error.
    """
    value = (value or "GMT-6").strip().upper()
    m = re.fullmatch(r"GMT([+-])(\d{1,2})(?::?(\d{2}))?", value)
    if not m:
        return timezone(timedelta(hours=-6))
    sign, hours, minutes = m.groups()
    delta = timedelta(hours=int(hours), minutes=int(minutes or 0))
    if sign == "-":
        delta = -delta
    return timezone(delta)


def _parse_date_time(date_str: str, hour_str: str, tz: timezone) -> datetime:
    """Flexible parser — handles '2026-6-8' and '2026-06-08' equally."""
    parts = date_str.strip().split("-")
    y, mo, d = int(parts[0]), int(parts[1]), int(parts[2])
    h_parts = hour_str.strip().split(":")
    hh, mm = int(h_parts[0]), int(h_parts[1]) if len(h_parts) > 1 else 0
    return datetime(y, mo, d, hh, mm, tzinfo=tz)


def event_start_dt(event: dict) -> datetime:
    """Return timezone-aware start datetime for an event."""
    tz        = parse_gmt_offset(event.get("h_format", "GMT-6"))
    date_part = event.get("start", "2000-01-01")
    hour_part = event.get("init_hour", "00:00")
    return _parse_date_time(date_part, hour_part, tz)


def event_end_dt(event: dict) -> datetime:
    """Return timezone-aware end datetime for an event."""
    tz        = parse_gmt_offset(event.get("h_format", "GMT-6"))
    date_part = event.get("end", "2000-01-01")
    hour_part = event.get("fin_hour", "23:59")
    return _parse_date_time(date_part, hour_part, tz)


def event_state(event: dict, user_tz: str = "GMT-6") -> tuple[str, datetime]:
    """Return (state, target_datetime_in_user_tz).

    state is one of:
      "upcoming"  — hasn't started yet
      "active"    — currently running
      "expired"   — already ended

    target is:
      start_dt for "upcoming"
      end_dt   for "active" / "expired"

    All datetimes are converted to the user's timezone.
    """
    utz   = parse_gmt_offset(user_tz)
    now   = datetime.now(utz)
    start = event_start_dt(event).astimezone(utz)
    end   = event_end_dt(event).astimezone(utz)

    if now < start:
        return "upcoming", start
    if now <= end:
        return "active", end
    return "expired", end


def visible_events(events: list[dict], user_tz: str = "GMT-6") -> list[dict]:
    """Return events that are not yet expired, preserving JSON order."""
    return [e for e in events if event_state(e, user_tz)[0] != "expired"]


def hero_event(events: list[dict], user_tz: str = "GMT-6") -> dict | None:
    """Select the hero event from a list of visible events.

    Priority:
      1. BANNER_FEATURED key if present and not expired.
      2. First active event.
      3. First upcoming event.
    Returns None if all events are expired.
    """
    vis = visible_events(events, user_tz)
    if not vis:
        return None
    featured = next((e for e in vis if e.get("key") == "BANNER_FEATURED"), None)
    return featured or vis[0]

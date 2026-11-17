"""iCalendar: one file, one request. Recurrences are unfolded inside the window."""
from __future__ import annotations

from datetime import datetime, timedelta

import icalendar
import recurring_ical_events

from .common import clean, local_iso, plain, to_float

KIND = "ics"


def looks_like(text: str) -> bool:
    return "BEGIN:VCALENDAR" in text[:2000] and "BEGIN:VEVENT" in text


def parse(text: str, tz: str, since: str, until: str) -> list[dict]:
    cal = icalendar.Calendar.from_ical(text)
    start = datetime.fromisoformat(since)
    end = datetime.fromisoformat(until) + timedelta(days=1)
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        dtstart = ev.get("DTSTART")
        s = local_iso(dtstart.dt if dtstart else None, tz)
        title = clean(str(ev.get("SUMMARY") or ""))
        if not s or not title:
            continue
        dtend = ev.get("DTEND")
        e = local_iso(dtend.dt if dtend else None, tz)
        geo = ev.get("GEO")
        location = clean(str(ev.get("LOCATION") or "")) or None
        cats = ev.get("CATEGORIES")
        if cats is not None and not isinstance(cats, list):
            cats = [cats]
        raw = ", ".join(str(c) for cat in cats or [] for c in getattr(cat, "cats", [cat]))
        out.append({
            "external_id": str(ev.get("UID") or "") or None,
            "title": title,
            "description": plain(str(ev.get("DESCRIPTION") or "")),
            "starts_at": s[0], "all_day": s[1],
            "ends_at": e[0] if e else None,
            "url": str(ev.get("URL") or "") or None,
            "venue": location,
            "lat": to_float(getattr(geo, "latitude", None)),
            "lon": to_float(getattr(geo, "longitude", None)),
            "category_raw": raw or None,
        })
    return out


async def harvest(web, endpoint: str, tz: str, since: str, until: str) -> list[dict]:
    r = await web.get(endpoint.replace("webcal://", "https://"))
    if r is None or r.status_code != 200:
        raise RuntimeError(f"HTTP {getattr(r, 'status_code', 'kein Zugriff')}")
    if not looks_like(r.text):
        raise RuntimeError("keine iCalendar-Datei")
    return parse(r.text, tz, since, until)

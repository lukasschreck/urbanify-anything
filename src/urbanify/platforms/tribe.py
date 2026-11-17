"""The Events Calendar (WordPress plugin, "Tribe") — open REST API.

    GET {base}/wp-json/tribe/events/v1/events?per_page=50&page=N

`total_pages` is the end of the list, never the length of a page. `venue` is
an object, or an empty list when none is maintained.
"""
from __future__ import annotations

import re

from .common import clean, local_iso, plain, to_float

KIND = "tribe"
API_PATH = "/wp-json/tribe/events/v1/events"
PER_PAGE = 50
MAX_PAGES = 40

_ZIP_CITY = re.compile(r"^(\d{4,5})\s+(\S.*)$")


def parse(payload: dict, tz: str) -> list[dict]:
    out = []
    for e in payload.get("events") or []:
        all_day = bool(e.get("all_day"))
        start = local_iso(e.get("start_date"), tz)
        if not start:
            continue
        end = local_iso(e.get("end_date"), tz)
        v = e.get("venue")
        if isinstance(v, list):
            v = v[0] if v else {}
        v = v if isinstance(v, dict) else {}
        city, postal = clean(v.get("city")) or None, clean(v.get("zip")) or None
        m = _ZIP_CITY.match(city or "")
        if m:
            postal, city = postal or m.group(1), m.group(2)
        out.append({
            "external_id": e.get("id"),
            "title": clean(e.get("title")),
            "description": plain(e.get("description")),
            "starts_at": start[0][:11] + "00:00:00" if all_day else start[0],
            "all_day": all_day,
            "ends_at": end[0] if end else None,
            "url": e.get("url") or None,
            "venue": clean(v.get("venue")) or None,
            "street": clean(v.get("address")) or None,
            "postal_code": postal, "city": city,
            "lat": to_float(v.get("geo_lat")), "lon": to_float(v.get("geo_lng")),
            "category_raw": ", ".join(clean(c.get("name")) for c in e.get("categories") or []
                                      if isinstance(c, dict)) or None,
        })
    return out


async def harvest(web, endpoint: str, tz: str, since: str, until: str) -> list[dict]:
    events: list[dict] = []
    page, last = 1, 1
    while page <= min(last, MAX_PAGES):
        r = await web.get(endpoint, params={
            "per_page": PER_PAGE, "page": page,
            "start_date": f"{since} 00:00:00", "end_date": f"{until} 23:59:59"})
        if r is None or r.status_code != 200:
            if page == 1:
                raise RuntimeError(f"HTTP {getattr(r, 'status_code', 'kein Zugriff')}")
            break
        data = r.json()
        last = int(data.get("total_pages") or 1)
        events += parse(data, tz)
        page += 1
    return events

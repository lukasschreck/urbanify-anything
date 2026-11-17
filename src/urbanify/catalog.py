"""Supra-regional sources and their adapters — see catalog.yaml.

Whether an entry applies to a place is geometry: its coverage box against the
measured hour. Berlin's culture platform applies to Potsdam's hour as well,
because Potsdam's hour reaches into Berlin.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import os

import yaml
from dateutil.rrule import rrulestr
from shapely.geometry import box

from .place import Place
from .store import stable_id
from .platforms.common import clean, local_iso, plain, to_float
from .web import Polite

# Der Katalog ist Daten, nicht Code, und steht darum nicht im Repo. Gesucht
# wird in dieser Reihenfolge:
#
#   1. $URBANIFY_CATALOG, wenn gesetzt
#   2. catalog.yaml neben diesem Modul
#
# Findet sich keine Datei, ist der Katalog leer: die Erhebung läuft vollständig,
# nur eben allein mit dem, was OpenStreetMap kennt. `catalog.example.yaml` zeigt
# das Format und ist zum Kopieren gedacht, nicht zum Benutzen.
NAME = "catalog.yaml"


def file() -> Path | None:
    env = os.environ.get("URBANIFY_CATALOG", "").strip()
    if env:
        return Path(env).expanduser()
    own = Path(__file__).with_name(NAME)
    return own if own.exists() else None


def entries() -> list[dict]:
    path = file()
    if path is None:
        return []
    if not path.exists():
        raise FileNotFoundError(f"URBANIFY_CATALOG zeigt auf {path}, dort liegt nichts")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def applies(entry: dict, outer) -> bool:
    cov = entry.get("coverage")
    return cov == "world" or (isinstance(cov, list) and box(*cov).intersects(outer))


# ------------------------------------------------------------------ radar

async def radar(web: Polite, entry: dict, place: Place, since: str, until: str) -> list[dict]:
    tz = ZoneInfo(place.tz)
    lo = datetime.fromisoformat(since).replace(tzinfo=tz)
    hi = datetime.fromisoformat(until).replace(tzinfo=tz) + timedelta(days=1)
    out: list[dict] = []
    offset, total = 0, None
    while total is None or offset < min(total, 2000):
        r = await web.get(entry["endpoint"], params={
            "facets[city][]": place.name, "limit": 100, "offset": offset,
            "fields": "title,date_time,offline:address,offline:map,url,uuid,category"}, timeout=90)
        if r is None or r.status_code != 200:
            if total is None:
                raise RuntimeError(f"HTTP {getattr(r, 'status_code', 'kein Zugriff')}")
            break
        data = r.json()
        total = int(data.get("count") or 0)
        result = data.get("result") or {}
        if not result:
            break
        for e in result.values():
            loc = (e.get("offline") or [{}])[0] or {}
            addr, geo = loc.get("address") or {}, loc.get("map") or {}
            base = {
                "title": clean(e.get("title")), "url": e.get("url"),
                "venue": clean(addr.get("name_line")) or None,
                "street": clean(addr.get("thoroughfare")) or None,
                "postal_code": clean(addr.get("postal_code")) or None,
                "city": clean(addr.get("locality")) or None,
                "lat": to_float(geo.get("lat")), "lon": to_float(geo.get("lon")),
                "category_raw": ", ".join(dict.fromkeys(
                    c.get("name", "") for c in e.get("category") or [])) or None,
            }
            # radar führt jede Wiederholung einer Serie als eigenen Eintrag, und
            # jeder trägt die Regel der ganzen Serie. Über die uuid gezählt, stünde
            # ein wöchentlicher Termin neunmal am selben Abend. Was denselben
            # Titel am selben Ort zur selben Zeit hat, ist ein Termin.
            series = stable_id(base["title"], base["venue"], base["street"])
            for dt in e.get("date_time") or []:
                try:
                    start = datetime.fromisoformat(dt["time_start"])
                except (KeyError, TypeError, ValueError):
                    continue
                if dt.get("rrule"):
                    try:
                        rule = rrulestr(dt["rrule"].removeprefix("RRULE:"), dtstart=start)
                        hits = rule.between(lo, hi, inc=True)[:60]
                    except (ValueError, TypeError):
                        hits = []
                    for h in hits:
                        s = local_iso(h, place.tz)
                        out.append({**base, "external_id": series, "starts_at": s[0]})
                else:
                    s = local_iso(start, place.tz)
                    end = local_iso(dt.get("time_end"), place.tz)
                    out.append({**base, "external_id": series, "starts_at": s[0],
                                "ends_at": end[0] if end else None})
        offset += len(result)
    return out


# ------------------------------------------------------------ kulturdaten

async def _kd_pages(web: Polite, url: str, key: str, params: dict | None = None,
                    max_pages: int = 60) -> list[dict]:
    items: list[dict] = []
    page = 1
    while page <= max_pages:
        r = await web.get(url, params={**(params or {}), "pageSize": 500, "page": page})
        if r is None or r.status_code != 200:
            if page == 1:
                raise RuntimeError(f"HTTP {getattr(r, 'status_code', 'kein Zugriff')}")
            break
        data = r.json().get("data") or {}
        batch = data.get(key) or []
        items += batch
        # Maßgeblich ist totalCount, nicht die Länge der Seite.
        if not batch or len(items) >= int(data.get("totalCount") or 0):
            break
        page += 1
    return items


def _de(label) -> str:
    if isinstance(label, dict):
        return clean(label.get("de") or label.get("en") or next(iter(label.values()), ""))
    return clean(label)


async def kulturdaten(web: Polite, entry: dict, place: Place, since: str, until: str) -> list[dict]:
    base = entry["endpoint"].rstrip("/")
    events = await _kd_pages(web, f"{base}/events", "events",
                             {"startDate": since, "endDate": until})
    locations = {loc["identifier"]: loc
                 for loc in await _kd_pages(web, f"{base}/locations", "locations")}
    out = []
    for e in events:
        if e.get("status") != "event.published" or e.get("scheduleStatus") == "event.cancelled":
            continue
        sch = e.get("schedule") or {}
        if not sch.get("startDate"):
            continue
        t0, t1 = sch.get("startTime") or "00:00:00", sch.get("endTime") or "00:00:00"
        all_day = t0 == "00:00:00" and t1 == "00:00:00"
        ref = (e.get("locations") or [{}])[0]
        loc = locations.get(ref.get("referenceId"), {})
        addr = loc.get("address") or {}
        out.append({
            "external_id": e.get("identifier"),
            "title": " · ".join(_de(a.get("referenceLabel")) for a in e.get("attractions") or [])[:300],
            "starts_at": f"{sch['startDate']}T{t0}", "all_day": all_day,
            "ends_at": f"{sch.get('endDate') or sch['startDate']}T{t1}",
            "venue": _de(ref.get("referenceLabel")) or _de(loc.get("title")) or None,
            "street": clean(addr.get("streetAddress")) or None,
            "postal_code": clean(addr.get("postalCode")) or None,
            "city": clean(addr.get("addressLocality")) or entry.get("city"),
            "category_raw": (e.get("metadata") or {}).get("origin"),
        })
    return out


# ----------------------------------------------------------- simplesearch

def _german_date(text: str) -> str | None:
    try:
        return datetime.strptime((text or "").strip(), "%d.%m.%Y").strftime("%Y-%m-%dT00:00:00")
    except ValueError:
        return None


async def simplesearch(web: Polite, entry: dict, place: Place, since: str, until: str) -> list[dict]:
    """berlin.de „SimpleSearch": eine Tabelle als JSON, je Datensatz ein Fest."""
    r = await web.get(entry["endpoint"])
    if r is None or r.status_code != 200:
        raise RuntimeError(f"HTTP {getattr(r, 'status_code', 'kein Zugriff')}")
    out = []
    for row in r.json().get("index") or []:
        start = _german_date(row.get("von"))
        if not start:
            continue
        postal = clean(str(row.get("plz") or row.get("plz_ort") or ""))[:5] or None
        out.append({
            "external_id": row.get("id"),
            "title": clean(row.get("bezeichnung") or row.get("name")),
            "description": plain("\n".join(filter(None, (
                row.get("zeit") or row.get("oeffnungszeiten"), row.get("bemerkungen"))))),
            "starts_at": start, "ends_at": _german_date(row.get("bis")), "all_day": True,
            "venue": clean(row.get("strasse")) or None,
            "street": clean(row.get("strasse")) or None,
            "postal_code": postal, "city": entry.get("city"),
            "url": clean(row.get("www")) or None,
            "category_raw": entry["name"].split("—")[-1].strip(),
        })
    return out


ADAPTERS = {"radar": radar, "kulturdaten": kulturdaten, "simplesearch": simplesearch}

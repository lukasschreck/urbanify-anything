"""Addresses to coordinates, for events whose source gives none.

One request per second against Nominatim, cached forever in a file shared by
all places. A miss is cached too — asking again tomorrow finds the same nothing.

A hit must lie near the measured hour. Without that check a geocoder always
finds *something*: "Berlin" is also a bridge in Pforzheim.
"""
from __future__ import annotations

import sqlite3
import time

import httpx

from . import config

_SCHEMA = """CREATE TABLE IF NOT EXISTS geocode (
  query TEXT PRIMARY KEY, lat REAL, lon REAL, asked_at TEXT)"""


def _cache() -> sqlite3.Connection:
    config.DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DATA / "geocode.sqlite", timeout=30)
    conn.execute(_SCHEMA)
    return conn


def address_of(row) -> str | None:
    """The query for one event — or None when there is nothing to ask with."""
    street, city = row["street"], row["city"]
    if not city and not row["postal_code"]:
        return None
    head = street or row["venue"]
    if not head:
        return None
    place = " ".join(p for p in (row["postal_code"], city) if p)
    return f"{head}, {place}"


def fill(conn: sqlite3.Connection, country: str, bbox: tuple[float, float, float, float],
         limit: int = 400, progress=None) -> dict:
    """Geocode distinct addresses of events without coordinates, busiest first."""
    cache = _cache()
    rows = conn.execute(
        """SELECT venue, street, postal_code, city, COUNT(*) AS n FROM event
           WHERE geo = 'offen' GROUP BY venue, street, postal_code, city
           ORDER BY n DESC""").fetchall()
    minlon, minlat, maxlon, maxlat = bbox
    pad = 0.3
    stats = {"adressen": len(rows), "gefragt": 0, "gefunden": 0, "aus_cache": 0, "ohne_adresse": 0}
    last = 0.0
    client = httpx.Client(headers={"User-Agent": config.USER_AGENT}, timeout=30)
    for row in rows:
        q = address_of(row)
        where = ("venue IS ? AND street IS ? AND postal_code IS ? AND city IS ? AND geo='offen'",
                 (row["venue"], row["street"], row["postal_code"], row["city"]))
        if not q:
            stats["ohne_adresse"] += 1
            conn.execute(f"UPDATE event SET geo='fehlt' WHERE {where[0]}", where[1])
            continue
        key = f"{country}|{q}"
        hit = cache.execute("SELECT lat, lon FROM geocode WHERE query=?", (key,)).fetchone()
        if hit is None:
            if stats["gefragt"] >= limit:
                continue                      # bleibt 'offen' für den nächsten Lauf
            gap = time.monotonic() - last
            if gap < 1.05:
                time.sleep(1.05 - gap)
            last = time.monotonic()
            stats["gefragt"] += 1
            lat = lon = None
            try:
                r = client.get(f"{config.NOMINATIM_URL}/search", params={
                    "q": q, "format": "jsonv2", "limit": 1,
                    "countrycodes": country.lower() or None,
                    "viewbox": f"{minlon - pad},{maxlat + pad},{maxlon + pad},{minlat - pad}",
                    "bounded": 1})
                data = r.json() if r.status_code == 200 else []
                if data:
                    lat, lon = float(data[0]["lat"]), float(data[0]["lon"])
            except Exception:  # noqa: BLE001 - ein Aussetzer ist kein Befund
                continue
            cache.execute("INSERT OR REPLACE INTO geocode VALUES (?,?,?,datetime('now'))",
                          (key, lat, lon))
            cache.commit()
            hit = (lat, lon)
            if progress and stats["gefragt"] % 25 == 0:
                progress(f"Geocoder: {stats['gefragt']} gefragt, {stats['gefunden']} gefunden")
                conn.commit()
        else:
            stats["aus_cache"] += 1
        if hit[0] is None:
            conn.execute(f"UPDATE event SET geo='fehlt' WHERE {where[0]}", where[1])
        else:
            stats["gefunden"] += 1
            conn.execute(f"UPDATE event SET lat=?, lon=?, geo='geocoder' WHERE {where[0]}",
                         (hit[0], hit[1], *where[1]))
    conn.commit()
    client.close()
    return stats

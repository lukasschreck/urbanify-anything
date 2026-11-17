"""Who runs a place inside the hour? Ask OpenStreetMap.

This is what makes the survey work for any city: nobody has to know the local
scene. Every theatre, club, museum, community centre and town hall that OSM
knows *and* that carries a website becomes a candidate. Whether that website
can be asked for dates is the next step's question (`probe.py`).
"""
from __future__ import annotations

import re
import time
from urllib.parse import urlparse, urlunparse

import httpx

from . import config
from .isochrone import Zones

# Tag → unser Wort dafür. Die Reihenfolge ist die Rangfolge, wenn mehrere
# OSM-Objekte dieselbe Website tragen.
KINDS: dict[tuple[str, str], str] = {
    ("amenity", "theatre"): "Theater",
    ("amenity", "concert_hall"): "Konzerthaus",
    ("amenity", "music_venue"): "Musikspielstätte",
    ("amenity", "arts_centre"): "Kulturzentrum",
    ("amenity", "nightclub"): "Club",
    ("amenity", "cinema"): "Kino",
    ("amenity", "events_venue"): "Veranstaltungsort",
    ("amenity", "social_centre"): "Soziales Zentrum",
    ("amenity", "community_centre"): "Gemeindezentrum",
    ("amenity", "planetarium"): "Planetarium",
    ("amenity", "library"): "Bibliothek",
    ("tourism", "museum"): "Museum",
    ("tourism", "gallery"): "Galerie",
    ("tourism", "zoo"): "Zoo",
    ("leisure", "hackerspace"): "Hackspace",
    ("boundary", "administrative"): "Gemeinde",
    ("place", "city"): "Gemeinde",
    ("place", "town"): "Gemeinde",
    ("place", "village"): "Gemeinde",
}

# Hosts, hinter denen kein eigener Kalender eines Hauses steht.
NOT_A_SITE = re.compile(
    r"(^|\.)(facebook|instagram|twitter|x|youtube|youtu|tiktok|linktr|wikipedia|"
    r"google|goo|t|bit|yelp|tripadvisor|booking|eventbrite|meetup)\.(com|ee|org|gl|me|ly|be|de)$")


def query(bbox: tuple[float, float, float, float]) -> str:
    minlon, minlat, maxlon, maxlat = bbox
    box = f"({minlat:.5f},{minlon:.5f},{maxlat:.5f},{maxlon:.5f})"
    by_key: dict[str, list[str]] = {}
    for key, value in KINDS:
        if key != "boundary":
            by_key.setdefault(key, []).append(value)
    parts = []
    for key, values in by_key.items():
        rx = "^(" + "|".join(values) + ")$"
        for site_key in ("website", "contact:website", "url"):
            parts.append(f'nwr["{key}"~"{rx}"]["{site_key}"]{box};')
    # Gemeinden: admin_level 8 ist in DE/FR/AT/CH die Gemeinde, 6 der Kreis
    # oder die kreisfreie Stadt. Anderswo liegt das anders — dann fehlen sie
    # hier einfach, und die Häuser tragen die Erhebung.
    parts.append(f'relation["boundary"="administrative"]["admin_level"~"^(6|8)$"]["website"]{box};')
    return "[out:json][timeout:240];(" + "".join(parts) + ");out center tags;"


def normalise(url: str) -> tuple[str, str] | None:
    """(start URL, host) — or None when the tag is no website of its own."""
    url = (url or "").strip().split(";")[0].split(" ")[0]
    if not url:
        return None
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url.lstrip("/")
    p = urlparse(url)
    host = p.netloc.lower()
    if not host or "." not in host or "@" in host or NOT_A_SITE.search(host.removeprefix("www.")):
        return None
    path = re.sub(r"/+$", "", p.path)
    return urlunparse((p.scheme.lower(), host, path or "/", "", p.query, "")), host


def fetch(bbox: tuple[float, float, float, float]) -> list[dict]:
    """Overpass ist ein geteilter Dienst und antwortet gelegentlich mit 429/502/504.
    Dann warten, noch einmal fragen, und beim dritten Mal einen Spiegel nehmen."""
    servers = [config.OVERPASS_URL, config.OVERPASS_URL, *config.OVERPASS_MIRRORS]
    last: Exception | None = None
    for attempt, server in enumerate(servers):
        if attempt:
            time.sleep(15 * attempt)
        try:
            r = httpx.post(server, data={"data": query(bbox)}, timeout=300,
                           headers={"User-Agent": config.USER_AGENT})
            r.raise_for_status()
            return r.json().get("elements", [])
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
    raise RuntimeError(f"Overpass antwortet nicht: {last}")


def candidates(elements: list[dict], zones: Zones) -> list[dict]:
    """One row per distinct website inside the outermost zone."""
    rank = {kind: i for i, kind in enumerate(KINDS.values())}
    out: dict[str, dict] = {}
    for el in elements:
        tags = el.get("tags") or {}
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        minutes = zones.minutes_at(lat, lon)
        if minutes is None:
            continue
        hit = normalise(tags.get("website") or tags.get("contact:website") or tags.get("url") or "")
        if not hit:
            continue
        url, host = hit
        kind = next((label for (k, v), label in KINDS.items() if tags.get(k) == v), "Ort")
        row = {
            "url": url, "host": host, "name": tags.get("name") or host, "kind": kind,
            "osm": f"{el['type']}/{el['id']}", "lat": lat, "lon": lon,
            "minutes": minutes, "n_objects": 1,
        }
        seen = out.get(url)
        if seen is None:
            out[url] = row
        else:
            seen["n_objects"] += 1
            if rank.get(kind, 99) < rank.get(seen["kind"], 99):
                row["n_objects"] = seen["n_objects"]
                out[url] = row
    return sorted(out.values(), key=lambda r: (r["minutes"], r["host"]))

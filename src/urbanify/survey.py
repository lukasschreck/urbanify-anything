"""The survey: from a name to "which sources hold which events".

Six steps, each resumable and each writing into the place's own file:

  1. place     Nominatim: name → start point
  2. zones     Valhalla: the measured hour, per profile
  3. discover  catalog entries whose coverage meets the hour, plus every
               website OSM knows inside it
  4. probe     which of those websites can be asked for dates
  5. harvest   ask them
  6. locate    geocode what has no coordinates, assign zones

Nothing in here knows a city.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import date, timedelta
from typing import Callable

from . import catalog, config, geocode, isochrone, osm, place as places, store
from .isochrone import Zones
from .platforms import ics, jsonld, tribe
from .platforms.common import in_window
from .probe import crawl, probe
from .web import Polite

Progress = Callable[[str], None]

STEPS = ("zones", "discover", "probe", "harvest", "locate")


class StepFailed(RuntimeError):
    """Ein Schritt ist gescheitert; alles davor steht in der Datei des Ortes."""

    def __init__(self, slug: str, step: str, cause: Exception):
        super().__init__(f"{step}: {cause}")
        self.slug, self.step, self.cause = slug, step, cause


def _say(conn: sqlite3.Connection, progress: Progress | None, step: str, text: str) -> None:
    store.set_meta(conn, "progress", {"step": step, "text": text, "at": store.now()})
    if progress:
        progress(f"[{step}] {text}")


def window(days: int | None = None) -> tuple[str, str]:
    today = date.today()
    return today.isoformat(), (today + timedelta(days=days or config.DAYS_AHEAD)).isoformat()


# ---------------------------------------------------------------- 1 and 2

def locate(query: str) -> tuple[sqlite3.Connection, places.Place]:
    if not config.CONTACT:
        print("Hinweis: URBANIFY_CONTACT ist leer. Die Erhebung fragt fremde Websites und "
              "öffentliche Dienste in deinem Namen ab — trag einen Kontakt in .env ein, "
              "bevor du mehr als einen Versuch machst. Verantwortlich für die Abfragen "
              "bist du selbst (README, „Verantwortung“).", file=sys.stderr, flush=True)
    p = places.find(query)
    conn = store.connect(p.slug, create=True)
    store.save_place(conn, p)
    return conn, p


def measure(conn: sqlite3.Connection, progress: Progress | None = None) -> dict:
    p = store.load_place(conn)
    graph = isochrone.graph_version()
    out = {}
    for profile in config.PROFILES:
        _say(conn, progress, "zones", f"Valhalla rechnet {profile} …")
        feats = isochrone.fetch(p, profile)
        store.save_zones(conn, profile, feats, graph)
        out[profile] = [f["properties"]["minutes"] for f in feats]
    return out


# ---------------------------------------------------------------------- 3

def discover(conn: sqlite3.Connection, progress: Progress | None = None) -> dict:
    zones = Zones(store.load_zones(conn, "auto"))
    n_cat = 0
    for entry in catalog.entries():
        if not catalog.applies(entry, zones.outer):
            continue
        n_cat += 1
        store.upsert_source(
            conn, entry["slug"], name=entry["name"], kind=entry["kind"],
            endpoint=entry["endpoint"], origin="katalog", license=entry.get("license"),
            note=entry.get("note"),
            status="nicht-angeschlossen" if entry["kind"] not in catalog.ADAPTERS else "offen")
    conn.commit()

    _say(conn, progress, "discover", "Overpass: Häuser mit Website in der Stunde …")
    elements = osm.fetch(zones.bbox)
    rows = osm.candidates(elements, zones)
    for r in rows:
        conn.execute(
            """INSERT INTO site (url, host, name, kind, osm, lat, lon, minutes, n_objects)
               VALUES (:url, :host, :name, :kind, :osm, :lat, :lon, :minutes, :n_objects)
               ON CONFLICT(url) DO UPDATE SET
                 name=excluded.name, kind=excluded.kind, osm=excluded.osm, lat=excluded.lat,
                 lon=excluded.lon, minutes=excluded.minutes, n_objects=excluded.n_objects""", r)
    conn.commit()
    return {"katalog": n_cat, "osm_objekte": len(elements), "websites": len(rows)}


# ---------------------------------------------------------------------- 4

async def _probe_all(conn: sqlite3.Connection, sites: list[sqlite3.Row],
                     progress: Progress | None) -> dict:
    counts: dict[str, int] = {}
    done = 0
    # Die Frist läuft erst, wenn die Website an der Reihe ist — sonst liefe sie
    # schon in der Warteschlange ab.
    gate = asyncio.Semaphore(config.CONCURRENCY)

    async with Polite(concurrency=config.CONCURRENCY * 2) as web:
        async def one(site: sqlite3.Row) -> None:
            nonlocal done
            try:
                async with gate:
                    found = await asyncio.wait_for(probe(web, site["url"]), timeout=300)
            except Exception as exc:  # noqa: BLE001 - eine kaputte Seite hält nichts auf
                from .probe import Finding
                found = Finding("unerreichbar", note=type(exc).__name__)
            counts[found.status] = counts.get(found.status, 0) + 1
            conn.execute(
                "UPDATE site SET status=?, platform=?, feeds=?, note=?, probed_at=? WHERE id=?",
                (found.status, found.platform,
                 json.dumps([f.__dict__ for f in found.feeds]) if found.feeds else None,
                 found.note, store.now(), site["id"]))
            best = found.best
            # Zwei Häuser, ein Kalender: der Feed ist eine Quelle, nicht zwei.
            shared = best and conn.execute(
                "SELECT 1 FROM source WHERE endpoint=? AND COALESCE(site_id, -1) != ?",
                (best.url, site["id"])).fetchone()
            if best and shared:
                conn.execute("UPDATE site SET note=? WHERE id=?",
                             (f"teilt den Feed {best.url}", site["id"]))
            elif best:
                store.upsert_source(
                    conn, f"{best.kind}-{site['host'].removeprefix('www.')}-{site['id']}",
                    name=site["name"], kind=best.kind, endpoint=best.url, origin="osm",
                    site_id=site["id"], note=site["kind"])
            done += 1
            if done % 50 == 0 or done == len(sites):
                conn.commit()
                _say(conn, progress, "probe",
                     f"{done}/{len(sites)} Websites · " +
                     ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))

        await asyncio.gather(*(one(s) for s in sites))
    conn.commit()
    return counts


def probe_sites(conn: sqlite3.Connection, progress: Progress | None = None,
                max_sites: int | None = None, per_host: int = 12, again: bool = False) -> dict:
    """Probe what has not been probed yet, innermost zone first.

    `per_host` caps how many pages of one shared host are asked — a city portal
    that hosts two hundred libraries is one website, not two hundred.
    """
    rows = conn.execute(
        "SELECT * FROM site WHERE status IN ('offen'" + (",'unerreichbar'" if again else "") +
        ") ORDER BY minutes, n_objects DESC, id").fetchall()
    seen: dict[str, int] = {}
    todo, skipped = [], 0
    for r in rows:
        seen[r["host"]] = seen.get(r["host"], 0) + 1
        if seen[r["host"]] > per_host:
            skipped += 1
            conn.execute("UPDATE site SET status='uebersprungen', note=? WHERE id=?",
                         (f"mehr als {per_host} Seiten auf {r['host']}", r["id"]))
            continue
        todo.append(r)
    if max_sites:
        todo = todo[:max_sites]
    conn.commit()
    _say(conn, progress, "probe", f"{len(todo)} Websites zu prüfen")
    counts = asyncio.run(_probe_all(conn, todo, progress)) if todo else {}
    counts["uebersprungen"] = skipped
    return counts


# ---------------------------------------------------------------------- 5

async def _harvest_all(conn: sqlite3.Connection, sources: list[sqlite3.Row],
                       p: places.Place, since: str, until: str,
                       progress: Progress | None) -> dict:
    total = {"quellen": 0, "termine": 0, "fehler": 0}
    done = 0

    async with Polite() as web:
        async def one(src: sqlite3.Row) -> None:
            nonlocal done
            site = conn.execute("SELECT * FROM site WHERE id=?", (src["site_id"],)).fetchone() \
                if src["site_id"] else None
            try:
                if src["kind"] in catalog.ADAPTERS:
                    entry = next(e for e in catalog.entries() if e["slug"] == src["slug"])
                    events = await catalog.ADAPTERS[src["kind"]](web, entry, p, since, until)
                elif src["kind"] == "tribe":
                    events = await tribe.harvest(web, src["endpoint"], p.tz, since, until)
                elif src["kind"] == "ics":
                    events = await ics.harvest(web, src["endpoint"], p.tz, since, until)
                elif src["kind"] == "jsonld":
                    r = await web.get(src["endpoint"])
                    if r is None or r.status_code != 200:
                        raise RuntimeError(f"HTTP {getattr(r, 'status_code', 'kein Zugriff')}")
                    events = jsonld.parse(r.text, p.tz)
                elif src["kind"] == "crawl":
                    events = await crawl(web, src["endpoint"], p.tz)
                else:
                    return
                n = 0
                for ev in events:
                    if not ev.get("starts_at") or not in_window(
                            ev["starts_at"], ev.get("ends_at"), since, until):
                        continue
                    if site is not None:
                        # Die Website eines Hauses: ohne eigene Ortsangabe
                        # steht der Termin am Haus.
                        ev.setdefault("venue", None)
                        if ev.get("lat") is None and not ev.get("street") and not ev.get("city"):
                            ev.update(lat=site["lat"], lon=site["lon"], geo="ort",
                                      venue=ev.get("venue") or site["name"])
                    n += store.upsert_event(conn, src["slug"], ev)
                conn.execute(
                    "UPDATE source SET status=?, fetched=?, error=NULL, harvested_at=? WHERE slug=?",
                    ("ok" if n else "leer", n, store.now(), src["slug"]))
                total["termine"] += n
                total["quellen"] += bool(n)
            except Exception as exc:  # noqa: BLE001 - Teilerfolg ist Erfolg
                total["fehler"] += 1
                conn.execute("UPDATE source SET status='fehler', error=?, harvested_at=? WHERE slug=?",
                             (f"{type(exc).__name__}: {exc}"[:300], store.now(), src["slug"]))
            done += 1
            if done % 25 == 0 or done == len(sources):
                conn.commit()
                _say(conn, progress, "harvest",
                     f"{done}/{len(sources)} Quellen · {total['termine']} Termine")

        await asyncio.gather(*(one(s) for s in sources))
    conn.commit()
    return total


def harvest(conn: sqlite3.Connection, progress: Progress | None = None,
            days: int | None = None, only: str | None = None) -> dict:
    p = store.load_place(conn)
    since, until = window(days)
    store.set_meta(conn, "window", {"since": since, "until": until})
    sql = "SELECT * FROM source WHERE status != 'nicht-angeschlossen'"
    args: tuple = ()
    if only:
        sql += " AND slug LIKE ?"
        args = (f"%{only}%",)
    sources = conn.execute(sql, args).fetchall()
    _say(conn, progress, "harvest", f"{len(sources)} Quellen, Fenster {since} bis {until}")
    return asyncio.run(_harvest_all(conn, sources, p, since, until, progress))


# ---------------------------------------------------------------------- 6

def assign(conn: sqlite3.Connection, progress: Progress | None = None,
           geocode_limit: int = 400) -> dict:
    p = store.load_place(conn)
    auto = Zones(store.load_zones(conn, "auto"))
    ebike = Zones(store.load_zones(conn, "ebike"))
    _say(conn, progress, "locate", "Adressen ohne Koordinaten gehen zum Geocoder …")
    geo = geocode.fill(conn, p.country, auto.bbox, limit=geocode_limit,
                       progress=lambda t: _say(conn, progress, "locate", t))
    rows = conn.execute("SELECT id, title, starts_at, venue, lat, lon FROM event").fetchall()
    cache: dict[tuple, tuple] = {}
    for r in rows:
        key = (r["lat"], r["lon"])
        if key not in cache:
            cache[key] = (auto.minutes_at(*key), ebike.minutes_at(*key) if ebike else None)
        za, zb = cache[key]
        conn.execute("UPDATE event SET zone_auto=?, zone_ebike=?, dedup_key=? WHERE id=?",
                     (za, zb, store.dedup_key(r["title"], r["starts_at"], r["lat"], r["lon"],
                                              r["venue"]), r["id"]))
    conn.commit()
    _say(conn, progress, "fertig", f"{len(rows)} Termine verortet")
    return {"termine": len(rows), "geocoder": geo}


def run(query: str, progress: Progress | None = None, *, days: int | None = None,
        max_sites: int | None = None, geocode_limit: int = 400) -> str:
    """The whole thing. Returns the slug of the place."""
    conn, p = locate(query)
    _say(conn, progress, "place", f"{p.display} ({p.lat:.4f}, {p.lon:.4f}, {p.tz})")
    step = "zones"
    try:
        measure(conn, progress)
        step = "discover"
        d = discover(conn, progress)
        _say(conn, progress, "discover", f"{d['katalog']} Katalogquellen, {d['websites']} Websites")
        step = "probe"
        probe_sites(conn, progress, max_sites=max_sites)
        step = "harvest"
        harvest(conn, progress, days=days)
        step = "locate"
        assign(conn, progress, geocode_limit=geocode_limit)
    except Exception as exc:  # noqa: BLE001 - der Aufrufer soll wissen, wo es weitergeht
        raise StepFailed(p.slug, step, exc) from exc
    finally:
        conn.close()
    return p.slug

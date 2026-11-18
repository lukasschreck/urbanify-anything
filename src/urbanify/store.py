"""One SQLite file per place: data/<slug>/urbanify.sqlite.

Everything in it is derived and can be rebuilt by `urbanify survey`. Places do
not share a file, so removing a city is removing a directory.

What a person adds — bookmarks, verdicts, rules — is not derived and lives in
a second file, see `personal.py`. `connect` attaches it.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import config, personal
from .categories import describe
from .place import Place

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS zone (
  profile TEXT NOT NULL, minutes INTEGER NOT NULL, geojson TEXT NOT NULL,
  computed_at TEXT, graph TEXT,
  PRIMARY KEY (profile, minutes));

-- Eine Website, die in der Zone einen Ort betreibt. Fundstelle, noch keine Quelle.
CREATE TABLE IF NOT EXISTS site (
  id INTEGER PRIMARY KEY,
  url TEXT NOT NULL UNIQUE, host TEXT NOT NULL,
  name TEXT, kind TEXT, osm TEXT,
  lat REAL, lon REAL, minutes INTEGER, n_objects INTEGER DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'offen',
  platform TEXT, feeds TEXT, note TEXT, probed_at TEXT);

-- Etwas, das sich maschinell nach Terminen fragen lässt.
CREATE TABLE IF NOT EXISTS source (
  slug TEXT PRIMARY KEY, name TEXT, kind TEXT, endpoint TEXT,
  origin TEXT, site_id INTEGER, license TEXT, note TEXT,
  status TEXT NOT NULL DEFAULT 'offen',
  fetched INTEGER DEFAULT 0, error TEXT, harvested_at TEXT);

CREATE TABLE IF NOT EXISTS event (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL, external_id TEXT NOT NULL,
  title TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT, all_day INTEGER DEFAULT 0,
  venue TEXT, street TEXT, postal_code TEXT, city TEXT,
  lat REAL, lon REAL, geo TEXT NOT NULL DEFAULT 'fehlt',
  zone_auto INTEGER, zone_ebike INTEGER,
  category TEXT, category_raw TEXT, is_kids INTEGER DEFAULT 0,
  url TEXT, description TEXT, dedup_key TEXT,
  UNIQUE (source, external_id, starts_at));
CREATE INDEX IF NOT EXISTS event_dedup ON event (dedup_key);
CREATE INDEX IF NOT EXISTS event_source ON event (source);
"""

# Später dazugekommene Spalten. Eine Datei von früher bekommt sie beim Öffnen,
# und was sich aus dem Bestand ableiten lässt, wird dabei nachgezogen.
#   event_key   Quelle, deren ID, Beginn — daran hängt ein Lesezeichen
#   series_key  Titel und Haus — daran hängt ein Urteil über alle Termine
ADDED = (("is_adult", "INTEGER DEFAULT 0"), ("age_min", "INTEGER"), ("age_max", "INTEGER"),
         ("event_key", "TEXT"), ("series_key", "TEXT"))
INDEXES = """
CREATE INDEX IF NOT EXISTS event_by_key ON event (event_key);
CREATE INDEX IF NOT EXISTS event_series ON event (series_key);
CREATE INDEX IF NOT EXISTS event_starts ON event (starts_at);
"""

# Wo eine Koordinate herkommt. `ort` heißt: die Quelle ist die Website eines
# Hauses, der Termin nennt keinen eigenen Ort, also steht er am Haus.
GEO = ("quelle", "ort", "geocoder", "fehlt", "offen")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def path_for(slug: str) -> Path:
    return config.DATA / slug / "urbanify.sqlite"


def connect(slug: str, create: bool = False) -> sqlite3.Connection:
    p = path_for(slug)
    if not p.exists() and not create:
        raise FileNotFoundError(f"Für {slug!r} gibt es noch keine Erhebung.")
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    personal.attach(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    have = {r["name"] for r in conn.execute("PRAGMA table_info(event)")}
    missing = [(n, t) for n, t in ADDED if n not in have]
    for name, kind in missing:
        conn.execute(f"ALTER TABLE event ADD COLUMN {name} {kind}")
    conn.executescript(INDEXES)
    if missing:
        reclassify(conn)


def reclassify(conn: sqlite3.Connection) -> int:
    """Kategorie, Kennzeichen und Schlüssel aus dem Bestand neu ableiten.

    Nach einer Änderung an `categories.py` — und für Dateien, die älter sind
    als die Spalten. Fragt keine fremde Website."""
    rows = conn.execute("SELECT id, source, external_id, starts_at, title, venue, "
                        "category_raw, description FROM event").fetchall()
    for r in rows:
        told = describe(r["category_raw"], r["title"], r["description"] or "")
        conn.execute(
            """UPDATE event SET category=?, is_kids=?, is_adult=?, age_min=?, age_max=?,
                                event_key=?, series_key=? WHERE id=?""",
            (told.category, int(told.is_kids), int(told.is_adult), told.age_min, told.age_max,
             event_key(r["source"], r["external_id"], r["starts_at"]),
             series_key(r["title"], r["venue"]), r["id"]))
    conn.commit()
    return len(rows)


def places() -> list[str]:
    if not config.DATA.exists():
        return []
    return sorted(p.parent.name for p in config.DATA.glob("*/urbanify.sqlite"))


# ------------------------------------------------------------------ meta

def set_meta(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, json.dumps(value, ensure_ascii=False)))
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def save_place(conn: sqlite3.Connection, place: Place) -> None:
    set_meta(conn, "place", place.as_dict())


def load_place(conn: sqlite3.Connection) -> Place:
    return Place.from_dict(get_meta(conn, "place"))


# ----------------------------------------------------------------- zones

def save_zones(conn: sqlite3.Connection, profile: str, features: list[dict], graph: str) -> None:
    conn.execute("DELETE FROM zone WHERE profile=?", (profile,))
    for f in features:
        conn.execute("INSERT INTO zone VALUES (?,?,?,?,?)",
                     (profile, f["properties"]["minutes"],
                      json.dumps(f, ensure_ascii=False), now(), graph))
    conn.commit()


def load_zones(conn: sqlite3.Connection, profile: str) -> list[dict]:
    rows = conn.execute("SELECT geojson FROM zone WHERE profile=? ORDER BY minutes",
                        (profile,)).fetchall()
    return [json.loads(r["geojson"]) for r in rows]


# ---------------------------------------------------------------- events

def fold(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower().replace("ß", "ss"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def dedup_key(title: str, starts_at: str, lat: float | None, lon: float | None,
              venue: str | None) -> str:
    """Derselbe Termin in zwei Quellen: gleicher Tag, gleicher Titelanfang,
    gleicher Ort (auf rund einen Kilometer, sonst der Name des Hauses).

    Das ist eine Näherung, kein Beweis — Quellen schreiben Titel verschieden.
    Sie unterschätzt Überschneidungen eher, als dass sie welche erfindet.
    """
    where = f"{lat:.2f},{lon:.2f}" if lat is not None and lon is not None else fold(venue)[:24]
    raw = f"{fold(title)[:32]}|{starts_at[:10]}|{where}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def stable_id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:20]


def event_key(source: str, external_id: str, starts_at: str) -> str:
    """Quelle, deren ID, Beginn. Wird ein Termin verlegt, ändert sich der
    Schlüssel mit — es ist ein anderer Termin. Darum trägt ein Lesezeichen
    eine Kopie von Titel und Beginn."""
    return stable_id("event", source, external_id, starts_at)


def series_key(title: str, venue: str | None) -> str:
    """Was derselbe Weihnachtsmarkt an 24 Tagen gemeinsam hat: Titel und Haus,
    nicht das Datum und nicht die Quelle. Wer den Schlüssel anders bildet,
    lässt alle bisherigen Urteile still ins Leere zeigen."""
    return f"{fold(title)}|{fold(venue) or '-'}"


def web_url(value) -> str | None:
    """Eine Termin-URL kommt aus fremden Feeds. Was kein http(s) ist — etwa
    `javascript:` —, wird nicht gespeichert und damit nie zum Link."""
    value = value.strip() if isinstance(value, str) else ""
    return value if re.match(r"^https?://", value, re.I) else None


def upsert_source(conn: sqlite3.Connection, slug: str, **f) -> None:
    cols = ("name", "kind", "endpoint", "origin", "site_id", "license", "note", "status")
    vals = [f.get(c) for c in cols]
    if f.get("status") is None:
        vals[-1] = "offen"
    conn.execute(
        f"""INSERT INTO source (slug, {', '.join(cols)}) VALUES (?,{','.join('?' * len(cols))})
            ON CONFLICT(slug) DO UPDATE SET
              name=excluded.name, kind=excluded.kind, endpoint=excluded.endpoint,
              origin=excluded.origin, site_id=excluded.site_id,
              license=COALESCE(excluded.license, source.license),
              note=COALESCE(excluded.note, source.note)""",
        (slug, *vals))


def upsert_event(conn: sqlite3.Connection, source: str, ev: dict) -> bool:
    """Ein Termin ohne Titel oder Beginn wird nicht gespeichert, alles andere schon.

    Der Ingest filtert nie nach Ort: was außerhalb der Stunde liegt, bleibt
    drin und bekommt keine Zone. Erst der Bericht zählt getrennt.
    """
    # Manche Feeds liefern den Titel mit HTML-Entitäten („Mairie &amp; Poste").
    title = html.unescape(ev.get("title") or "").strip()
    starts = ev.get("starts_at")
    if not title or not starts:
        return False
    lat, lon = ev.get("lat"), ev.get("lon")
    geo = ev.get("geo") or ("quelle" if lat is not None and lon is not None else "offen")
    told = describe(ev.get("category_raw"), title, ev.get("description") or "")
    ext = str(ev.get("external_id") or stable_id(title, starts, ev.get("venue")))
    conn.execute(
        """INSERT INTO event (source, external_id, title, starts_at, ends_at, all_day,
                              venue, street, postal_code, city, lat, lon, geo,
                              category, category_raw, is_kids, is_adult, age_min, age_max,
                              url, description, dedup_key, event_key, series_key)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(source, external_id, starts_at) DO UPDATE SET
             title=excluded.title, ends_at=excluded.ends_at, all_day=excluded.all_day,
             venue=excluded.venue, street=excluded.street,
             postal_code=excluded.postal_code, city=excluded.city,
             lat=COALESCE(excluded.lat, event.lat), lon=COALESCE(excluded.lon, event.lon),
             geo=CASE WHEN excluded.lat IS NOT NULL THEN excluded.geo ELSE event.geo END,
             category=excluded.category, category_raw=excluded.category_raw,
             is_kids=excluded.is_kids, is_adult=excluded.is_adult,
             age_min=excluded.age_min, age_max=excluded.age_max, url=excluded.url,
             description=excluded.description, dedup_key=excluded.dedup_key,
             event_key=excluded.event_key, series_key=excluded.series_key""",
        (source, ext, title[:300], starts, ev.get("ends_at"), int(bool(ev.get("all_day"))),
         ev.get("venue"), ev.get("street"), ev.get("postal_code"), ev.get("city"),
         lat, lon, geo, told.category, ev.get("category_raw"), int(told.is_kids),
         int(told.is_adult), told.age_min, told.age_max,
         web_url(ev.get("url")), (ev.get("description") or "")[:2000] or None,
         dedup_key(title, starts, lat, lon, ev.get("venue")),
         event_key(source, ext, starts), series_key(title[:300], ev.get("venue"))))
    return True

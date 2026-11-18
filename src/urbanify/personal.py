"""Die zweite Datei: was ein Mensch angelegt hat.

`data/<slug>/urbanify.sqlite` kann jederzeit neu entstehen, das hier nicht.
Darum liegt es getrennt, in `data/personal.sqlite`, und gilt für alle Orte:
Interessen und Regeln gehören zur Person, nicht zur Stadt.

`store.connect` hängt die Datei als `personal` an. Die Tabellen gibt es nur
hier, SQLite findet sie ohne Präfix. Zwischen den Dateien gibt es keine
Fremdschlüssel — was ein Mensch angelegt hat, hängt an einem Schlüssel, der
eine neue Erhebung überlebt (`event_key`, `series_key`), nie an `event.id`,
und trägt eine Kopie dessen, was gemeint war.

Ein Werkzeug für eine Person an ihrem Rechner: keine Konten, nichts wird
geteilt.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from . import config
from .categories import CATEGORIES

NAME = "personal.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS personal.setting (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS personal.rule (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL, field TEXT NOT NULL, matcher TEXT NOT NULL, pattern TEXT NOT NULL,
  weight REAL NOT NULL DEFAULT 1.0, note TEXT, enabled INTEGER NOT NULL DEFAULT 1,
  origin TEXT NOT NULL DEFAULT 'api', created_at TEXT NOT NULL,
  UNIQUE (kind, field, matcher, pattern));

-- ja = Highlight, vielleicht = im Bestand, nein = ausgeblendet. Nichts löscht.
-- scope 'serie' meint die Veranstaltung über alle Termine, 'event' den einen.
CREATE TABLE IF NOT EXISTS personal.verdict (
  scope TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
  note TEXT, created_at TEXT NOT NULL,
  place TEXT, title TEXT, venue TEXT,
  PRIMARY KEY (scope, key));

-- „Da will ich hin" hängt am einzelnen Termin. Die Spalten nach created_at
-- sind die Kopie: verschwindet der Termin, bleibt lesbar, was gemeint war.
CREATE TABLE IF NOT EXISTS personal.bookmark (
  event_key TEXT PRIMARY KEY, note TEXT, created_at TEXT NOT NULL,
  place TEXT, source TEXT, external_id TEXT, title TEXT, starts_at TEXT, venue TEXT);
"""

DEFAULTS = {"interests": [], "travel_mode": "auto", "show_adult": False}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def attach(conn: sqlite3.Connection) -> None:
    config.DATA.mkdir(parents=True, exist_ok=True)
    conn.execute("ATTACH DATABASE ? AS personal", (str(config.DATA / NAME),))
    conn.execute("PRAGMA personal.journal_mode=WAL")
    conn.executescript(SCHEMA)


def profile(conn: sqlite3.Connection) -> dict:
    out = dict(DEFAULTS)
    for r in conn.execute("SELECT key, value FROM setting"):
        if r["key"] in out:
            out[r["key"]] = json.loads(r["value"])
    return out


def update_profile(conn: sqlite3.Connection, **changes) -> dict:
    """Interessen ordnen die Listen und sonst nichts; das Verkehrsmittel wählt
    die Zonen; 18+ bleibt aus, bis man es einschaltet."""
    clean: dict = {}
    if changes.get("interests") is not None:
        unknown = [c for c in changes["interests"] if c not in CATEGORIES]
        if unknown:
            raise ValueError(f"Kategorie unbekannt: {', '.join(unknown)}")
        clean["interests"] = [c for c in CATEGORIES if c in set(changes["interests"])]
    if changes.get("travel_mode") is not None:
        if changes["travel_mode"] not in config.PROFILES:
            raise ValueError(f"travel_mode muss eines von {config.PROFILES} sein")
        clean["travel_mode"] = changes["travel_mode"]
    if changes.get("show_adult") is not None:
        clean["show_adult"] = bool(changes["show_adult"])
    for key, value in clean.items():
        conn.execute("INSERT INTO setting VALUES (?,?) ON CONFLICT(key) DO UPDATE SET "
                     "value=excluded.value", (key, json.dumps(value)))
    conn.commit()
    return profile(conn)

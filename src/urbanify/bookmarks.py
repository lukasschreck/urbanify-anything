"""Vorgemerkt — „da will ich hin".

Regeln sagen, was interessiert; Urteile, was man von einer Veranstaltung hält;
ein Lesezeichen sagt, dass man hingehen will. Darum hängt es am **Termin**,
nicht an der Serie: ein Urteil über den Weihnachtsmarkt gilt für alle 24 Tage,
hingehen will man an einem Samstag.

Gespeichert wird der `event_key`, nicht die `event.id`: die Nummer ist nach
außen die Adresse (`/api/places/<slug>/events/<id>/bookmark`), aber sie
überlebt keine neue Erhebung.

Ein Lesezeichen ändert keine Bewertung. Es ist eine eigene Achse — und der
stärkste Wille: Vorgemerktes bleibt sichtbar, auch wenn eine Regel es
ausblenden würde.
"""
from __future__ import annotations

import sqlite3

from .personal import now


def put(conn: sqlite3.Connection, event_id: int, note: str | None = None,
        place: str | None = None) -> dict:
    ev = conn.execute("SELECT event_key, source, external_id, title, starts_at, venue "
                      "FROM event WHERE id = ?", (int(event_id),)).fetchone()
    if not ev:
        raise KeyError(f"Kein Termin mit der ID {event_id}")
    conn.execute(
        """INSERT INTO bookmark (event_key, note, created_at, place, source, external_id,
                                 title, starts_at, venue)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(event_key) DO UPDATE SET
             note=COALESCE(excluded.note, bookmark.note), title=excluded.title,
             starts_at=excluded.starts_at, venue=excluded.venue""",
        (ev["event_key"], note, now(), place, ev["source"], ev["external_id"],
         ev["title"], ev["starts_at"], ev["venue"]))
    conn.commit()
    return dict(conn.execute("SELECT * FROM bookmark WHERE event_key=?",
                             (ev["event_key"],)).fetchone())


def drop(conn: sqlite3.Connection, event_id: int) -> bool:
    cur = conn.execute("DELETE FROM bookmark WHERE event_key = "
                       "(SELECT event_key FROM event WHERE id = ?)", (int(event_id),))
    conn.commit()
    return bool(cur.rowcount)


def load(conn: sqlite3.Connection) -> set[int]:
    """Die IDs der vorgemerkten Termine, die es im Bestand dieses Orts gibt."""
    return {int(r["id"]) for r in conn.execute(
        "SELECT e.id FROM bookmark b JOIN event e ON e.event_key = b.event_key")}


def orphans(conn: sqlite3.Connection, place: str) -> list[dict]:
    """Lesezeichen dieses Orts, deren Termin es so nicht mehr gibt — mit einem
    Vorschlag, wohin er gekommen sein könnte (derselbe Eintrag der Quelle mit
    dem nächstliegenden Beginn). Ein Vorschlag, kein Umhängen."""
    out = []
    for b in conn.execute(
            """SELECT b.* FROM bookmark b WHERE b.place = ? AND NOT EXISTS
                 (SELECT 1 FROM event e WHERE e.event_key = b.event_key)
               ORDER BY b.starts_at""", (place,)).fetchall():
        d = dict(b)
        hit = conn.execute(
            """SELECT id, title, starts_at FROM event WHERE source = ? AND external_id = ?
               ORDER BY ABS(julianday(starts_at) - julianday(?)) LIMIT 1""",
            (b["source"], b["external_id"], b["starts_at"])).fetchone()
        d["candidate"] = dict(hit) if hit else None
        out.append(d)
    return out

"""Die eine Abfrage, aus der Karte, Listen und Regelvorschau leben.

Gefiltert wird hier, nicht beim Einlesen. Wer eine Regel zurücknimmt, bekommt
die Termine zurück — das geht nur, weil der Bestand vollständig ist.

    Regel    score > 0 Highlight, = 0 im Bestand, < 0 ausgeblendet
    Urteil   schlägt die Regel vollständig, löscht aber nichts
    Vorgemerkt  bleibt sichtbar, was auch immer Regel und Urteil sagen
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from . import bookmarks, rules, verdicts
from .rules import Rule, score, subject_of

EVENT_SQL = """SELECT e.*, s.name AS source_name, s.license
               FROM event e LEFT JOIN source s ON s.slug = e.source"""
WINDOWS = ("heute", "wochenende", "14tage", "monat", "alles")
VISIBILITY = ("highlights", "all", "hidden")
PUBLIC = ("id", "title", "starts_at", "ends_at", "all_day", "venue", "city", "url",
          "category", "category_raw", "is_kids", "is_adult", "age_min", "age_max",
          "geo", "source", "source_name", "zone", "score", "bucket", "verdict", "bookmarked")


def window(name: str, today: date | None = None) -> tuple[str, str]:
    """Benannte Zeitfenster. ISO-Tage, beide Enden eingeschlossen."""
    t = today or date.today()
    if name == "heute":
        return t.isoformat(), t.isoformat()
    if name == "wochenende":
        # Freitag bis Sonntag. An einem dieser Tage ist das Wochenende gemeint,
        # in dem man steht, nicht das nächste.
        offset = t.weekday() - 4
        friday = t - timedelta(days=offset) if offset >= 0 else t + timedelta(days=-offset)
        return friday.isoformat(), (friday + timedelta(days=2)).isoformat()
    if name == "14tage":
        return t.isoformat(), (t + timedelta(days=14)).isoformat()
    if name == "monat":
        return t.isoformat(), (t + timedelta(days=31)).isoformat()
    if name == "alles":
        return t.isoformat(), (t + timedelta(days=400)).isoformat()
    raise ValueError(f"Zeitfenster unbekannt: {name!r}")


def fetch_events(
    conn: sqlite3.Connection, *,
    date_from: str | None = None, date_to: str | None = None,
    profile: str = "auto",
    categories: set[str] | None = None, source: str | None = None,
    kids_only: bool = False, bookmarked_only: bool = False, adult: bool = True,
    visibility: str = "hidden",
    ruleset: list[Rule] | None = None, extra_rules: list[Rule] | None = None,
    require_zone: bool = True, limit: int = 20000,
) -> list[dict]:
    """Termine mit ihrem Rang, gefiltert, wie die Karte sie braucht.

    Ohne Angaben kommt alles, was in der Stunde liegt — das ist die Sicht der
    Erhebung. Die Karte zum Leben fragt enger. `extra_rules` gelten zusätzlich,
    ohne gespeichert zu sein: so rechnet die Regelvorschau.
    """
    ruleset = (ruleset if ruleset is not None else rules.load(conn)) + (extra_rules or [])
    judged = verdicts.load(conn)
    marked = bookmarks.load(conn)
    zone_col = "zone_ebike" if profile == "ebike" else "zone_auto"

    where, params = ["1=1"], []
    # Überlappung, nicht Enthaltensein: eine Ausstellung, die letzten Monat
    # eröffnet hat und bis Dezember läuft, gehört in „dieses Wochenende".
    if date_from:
        where.append("date(COALESCE(e.ends_at, e.starts_at)) >= date(?)")
        params.append(date_from)
    if date_to:
        where.append("date(e.starts_at) <= date(?)")
        params.append(date_to)
    if require_zone:
        where.append(f"e.{zone_col} IS NOT NULL AND e.lat IS NOT NULL")
    if categories:
        where.append(f"e.category IN ({','.join('?' * len(categories))})")
        params.extend(sorted(categories))
    if source:
        where.append("e.source = ?")
        params.append(source)
    if kids_only:
        where.append("e.is_kids = 1")
    if not adult:
        # Was man selbst vorgemerkt hat, bleibt trotzdem stehen.
        where.append("COALESCE(e.is_adult, 0) = 0 "
                     "OR e.event_key IN (SELECT event_key FROM bookmark)")
    if bookmarked_only:
        where.append("e.event_key IN (SELECT event_key FROM bookmark)")

    sql = f"{EVENT_SQL} WHERE {' AND '.join(f'({w})' for w in where)} ORDER BY e.starts_at LIMIT ?"
    out: list[dict] = []
    for row in conn.execute(sql, (*params, limit)):
        sc = score(subject_of(row), ruleset)
        verdict = verdicts.verdict_for(row, judged)
        bucket = verdicts.BUCKET[verdict] if verdict else sc.bucket
        marked_here = int(row["id"]) in marked
        if not (bookmarked_only or marked_here):
            if visibility == "highlights" and bucket != "highlight":
                continue
            if visibility == "all" and bucket == "hidden":
                continue
        d = dict(row)
        d.update(zone=d[zone_col], score=sc.score, bucket=bucket, rule_bucket=sc.bucket,
                 verdict=verdict, white=sc.white, black=sc.black, bookmarked=marked_here)
        out.append(d)
    return out


def curation_queue(conn: sqlite3.Connection, *, date_from: str | None = None,
                   date_to: str | None = None, profile: str = "auto", adult: bool = False,
                   limit: int = 60, only_unjudged: bool = True) -> list[dict]:
    """Was noch kein Urteil hat — eine Veranstaltung je Zeile, nicht ein Termin,
    sortiert nach dem nächsten Termin."""
    events = fetch_events(conn, date_from=date_from, date_to=date_to, profile=profile,
                          adult=adult)
    floor = date_from or date.today().isoformat()
    events.sort(key=lambda e: max(e["starts_at"][:10], floor))
    dates: dict[str, int] = {}
    for e in events:
        dates[e["series_key"]] = dates.get(e["series_key"], 0) + 1
    seen: set[str] = set()
    queue: list[dict] = []
    for e in events:
        key = e["series_key"]
        if key in seen:
            continue
        seen.add(key)
        if only_unjudged and e["verdict"]:
            continue
        queue.append({**public(e), "description": (e["description"] or "")[:600],
                      "termine": dates[key], "rule_bucket": e["rule_bucket"]})
        if len(queue) >= limit:
            break
    return queue


def public(e: dict) -> dict:
    d = {k: e.get(k) for k in PUBLIC}
    for flag in ("all_day", "is_kids", "is_adult", "bookmarked"):
        d[flag] = bool(d[flag])
    return d


def to_geojson(events: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [e["lon"], e["lat"]]},
         "properties": public(e)} for e in events]}


def counts(events: list[dict]) -> dict:
    out = {"highlight": 0, "normal": 0, "hidden": 0}
    for e in events:
        out[e["bucket"]] += 1
    return out

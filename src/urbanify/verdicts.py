"""Urteile von Hand — die Kuratierung.

Regeln sind Muster, Urteile sind Einzelfälle. Beides zusammen ergibt die
Auswahl: das Urteil schlägt die Regel, weil ein Mensch, der auf „uninteressant"
geklickt hat, mehr weiß als jede Heuristik.

Drei Stufen:

    ja          sehr interessant    → Highlight
    vielleicht  prinzipiell         → im Bestand, nicht hervorgehoben
    nein        uninteressant       → ausgeblendet, aber nicht gelöscht

Nichts davon löscht etwas. Ein Urteil lässt sich zurücknehmen, und dann gilt
wieder, was die Regeln sagen — dasselbe Versprechen wie beim Filter.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .categories import fold
from .personal import now

VALUES = ("ja", "vielleicht", "nein")
SCOPES = ("serie", "event")

BUCKET = {"ja": "highlight", "vielleicht": "normal", "nein": "hidden"}


@dataclass(frozen=True)
class Verdict:
    scope: str
    key: str
    value: str
    note: str | None = None
    created_at: str | None = None

    def as_dict(self) -> dict:
        return {"scope": self.scope, "key": self.key, "value": self.value,
                "note": self.note, "created_at": self.created_at}


def put(conn: sqlite3.Connection, scope: str, key: str, value: str,
        note: str | None = None, *, title: str | None = None,
        venue: str | None = None, place: str | None = None) -> Verdict:
    """`key` ist der `series_key` oder der `event_key` — nie eine Nummer.
    `title` und `venue` sind die Kopie dessen, worüber geurteilt wurde."""
    if scope not in SCOPES:
        raise ValueError(f"scope muss serie|event sein, nicht {scope!r}")
    if value not in VALUES:
        raise ValueError(f"value muss ja|vielleicht|nein sein, nicht {value!r}")
    stamp = now()
    conn.execute(
        """INSERT INTO verdict (scope, key, value, note, created_at, place, title, venue)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(scope, key) DO UPDATE SET
             value=excluded.value, note=excluded.note, created_at=excluded.created_at,
             title=COALESCE(excluded.title, verdict.title),
             venue=COALESCE(excluded.venue, verdict.venue)""",
        (scope, str(key), value, note, stamp, place, title, venue))
    conn.commit()
    return Verdict(scope, str(key), value, note, stamp)


def drop(conn: sqlite3.Connection, scope: str, key: str) -> bool:
    cur = conn.execute("DELETE FROM verdict WHERE scope=? AND key=?", (scope, str(key)))
    conn.commit()
    return bool(cur.rowcount)


def load(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    return {(r["scope"], r["key"]): r["value"]
            for r in conn.execute("SELECT scope, key, value FROM verdict")}


def verdict_for(row, table: dict[tuple[str, str], str]) -> str | None:
    """Das Urteil über einen Event-Datensatz. Der Einzeltermin sticht die Serie."""
    keys = row.keys()
    single = table.get(("event", row["event_key"])) if "event_key" in keys else None
    if single:
        return single
    key = row["series_key"] if "series_key" in keys else None
    return table.get(("serie", key)) if key else None


def counts(conn: sqlite3.Connection) -> dict:
    """Gezählt wird, was auf eine Veranstaltung dieses Orts zeigt."""
    out = {v: 0 for v in VALUES}
    for r in conn.execute(
            """SELECT v.value, COUNT(*) n FROM verdict v WHERE EXISTS (
                 SELECT 1 FROM event e
                 WHERE (v.scope = 'serie' AND e.series_key = v.key)
                    OR (v.scope = 'event' AND e.event_key = v.key))
               GROUP BY v.value"""):
        out[r["value"]] = r["n"]
    out["gesamt"] = sum(out[v] for v in VALUES)
    return out


# ------------------------------------------------------------ Vorschläge

STOPWORDS = {
    "der", "die", "das", "und", "oder", "mit", "von", "fuer", "fur", "im", "in",
    "am", "an", "auf", "aus", "bei", "zum", "zur", "des", "dem", "den", "ein",
    "eine", "einen", "einem", "eines", "ist", "sind", "wird", "werden", "nach",
    "ueber", "uber", "vor", "sowie", "als", "wie", "zu", "la", "le", "les",
    "du", "et", "pour", "avec", "sur", "dans",
}

MIN_HITS = 3
RATIO = 2.5


def suggestions(conn: sqlite3.Connection, limit: int = 12,
                skip: set[str] | None = None) -> list[dict]:
    """Regelvorschläge aus den Urteilen ableiten.

    Der Schritt von „ich habe geklickt" zu „die Karte weiß Bescheid": wer
    fünfmal Theater mit „ja" bewertet hat, will vermutlich eine Regel, die das
    künftig von allein hervorhebt. Vorgeschlagen, nicht gesetzt.

    `skip` sind Wörter, die als Titelmuster nichts sagen — der Name des Orts
    etwa, der in jedem zweiten Titel steht.
    """
    skip = STOPWORDS | {fold(w) for w in (skip or ())}
    rows = conn.execute(
        """SELECT e.title, e.category, e.series_key, e.id, e.venue AS venue_name, e.city,
                  e.source AS source_slug, COALESCE(ve.value, vs.value) AS verdict
           FROM event e
           LEFT JOIN verdict ve ON ve.scope = 'event' AND ve.key = e.event_key
           LEFT JOIN verdict vs ON vs.scope = 'serie' AND vs.key = e.series_key
           WHERE COALESCE(ve.value, vs.value) IS NOT NULL""").fetchall()
    if not rows:
        return []

    # Eine Serie zählt einmal, nicht einmal pro Termin.
    seen: set[str] = set()
    judged: list[sqlite3.Row] = []
    for r in rows:
        marker = r["series_key"] or f"id-{r['id']}"
        if marker in seen:
            continue
        seen.add(marker)
        judged.append(r)

    tally: dict[tuple[str, str, str], dict[str, int]] = {}

    def note(field: str, matcher: str, pattern: str, verdict: str) -> None:
        if not pattern:
            return
        bucket = tally.setdefault((field, matcher, pattern), {"ja": 0, "nein": 0})
        if verdict in bucket:
            bucket[verdict] += 1

    for r in judged:
        v = r["verdict"]
        note("category", "equals", r["category"] or "", v)
        note("venue", "contains", (r["venue_name"] or "").strip(), v)
        note("city", "contains", (r["city"] or "").strip(), v)
        note("source", "equals", r["source_slug"] or "", v)
        for word in {w for w in fold(r["title"] or "").split()
                     if len(w) >= 5 and w not in skip and not w.isdigit()}:
            note("title", "contains", word, v)

    out: list[dict] = []
    for (field, matcher, pattern), c in tally.items():
        ja, nein = c["ja"], c["nein"]
        if ja >= MIN_HITS and ja >= RATIO * max(nein, 1) - (RATIO - 1):
            kind, weight, hits = "white", min(4.0, 1.0 + ja / 3), ja
        elif nein >= MIN_HITS and nein >= RATIO * max(ja, 1) - (RATIO - 1):
            kind, weight, hits = "black", min(5.0, 1.0 + nein / 3), nein
        else:
            continue
        out.append({
            "kind": kind, "field": field, "matcher": matcher, "pattern": pattern,
            "weight": round(weight * 2) / 2,
            "ja": ja, "nein": nein, "hits": hits,
            "note": f"aus {ja + nein} Bewertungen",
        })

    # Schon vorhandene Regeln nicht noch einmal vorschlagen.
    existing = {(r["kind"], r["field"], r["matcher"], fold(r["pattern"]))
                for r in conn.execute(
                    "SELECT kind, field, matcher, pattern FROM rule")}
    out = [s for s in out
           if (s["kind"], s["field"], s["matcher"], fold(s["pattern"])) not in existing]
    out.sort(key=lambda s: (-s["hits"], s["field"]))
    return out[:limit]

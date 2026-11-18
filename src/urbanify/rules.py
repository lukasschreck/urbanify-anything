"""Interest filter.

score = Σ weight(white hits) − Σ weight(black hits)

  score > 0  → highlight
  score == 0 → in the corpus, shown when "alles" is on
  score < 0  → hidden, but kept and reachable via "auch Ausgeblendetes"

Scoring happens at query time, never at ingest. A rule change is always
reversible because nothing was ever thrown away.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

import yaml

import os
from pathlib import Path

from . import config
from .categories import fold
from .personal import now

FIELDS = ("title", "description", "category", "venue", "city", "source")
MATCHERS = ("contains", "regex", "equals")
KINDS = ("white", "black")


@dataclass(frozen=True)
class Rule:
    id: int | None
    kind: str
    field: str
    matcher: str
    pattern: str
    weight: float
    note: str | None = None
    enabled: bool = True
    origin: str = "api"

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"kind muss white|black sein, nicht {self.kind!r}")
        if self.field not in FIELDS:
            raise ValueError(f"field unbekannt: {self.field!r}")
        if self.matcher not in MATCHERS:
            raise ValueError(f"matcher unbekannt: {self.matcher!r}")
        if self.matcher == "regex":
            try:
                re.compile(self.pattern, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"regex ungültig: {exc}") from exc

    def matches(self, subject: dict) -> bool:
        value = subject.get(self.field) or ""
        if self.matcher == "regex":
            return re.search(self.pattern, str(value), re.IGNORECASE) is not None
        hay, needle = fold(str(value)), fold(self.pattern)
        if not needle:
            return False
        return hay == needle if self.matcher == "equals" else needle in hay

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "field": self.field,
            "matcher": self.matcher,
            "pattern": self.pattern,
            "weight": self.weight,
            "note": self.note,
            "enabled": self.enabled,
            "origin": self.origin,
        }


@dataclass
class Scored:
    score: float = 0.0
    white: list[str] = field(default_factory=list)
    black: list[str] = field(default_factory=list)

    @property
    def bucket(self) -> str:
        if self.score > 0:
            return "highlight"
        return "normal" if self.score == 0 else "hidden"


def subject_of(row: sqlite3.Row | dict) -> dict:
    """The six fields a rule may look at, pulled out of an event row."""
    keys = set(row.keys())

    def pick(*names: str) -> str:
        for n in names:
            if n in keys and row[n]:
                return str(row[n])
        return ""
    return {
        "title": pick("title"),
        "description": pick("description"),
        "category": pick("category"),
        "venue": pick("venue"),
        "city": pick("city"),
        "source": pick("source"),
    }


def score(subject: dict, rules: list[Rule]) -> Scored:
    out = Scored()
    for r in rules:
        if not r.enabled or not r.matches(subject):
            continue
        if r.kind == "white":
            out.score += r.weight
            out.white.append(_label(r))
        else:
            out.score -= r.weight
            out.black.append(_label(r))
    return out


def _label(r: Rule) -> str:
    return f"{r.field} {r.matcher} “{r.pattern}” ({r.weight:+g})".replace("+-", "-")


# ---------------------------------------------------------------- persistence

def load(conn: sqlite3.Connection, include_disabled: bool = False) -> list[Rule]:
    sql = "SELECT * FROM rule"
    if not include_disabled:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY kind, field, pattern"
    return [_from_row(r) for r in conn.execute(sql)]


def _from_row(r: sqlite3.Row) -> Rule:
    return Rule(
        id=r["id"], kind=r["kind"], field=r["field"], matcher=r["matcher"],
        pattern=r["pattern"], weight=r["weight"], note=r["note"],
        enabled=bool(r["enabled"]), origin=r["origin"],
    )


def insert(conn: sqlite3.Connection, rule: Rule) -> int:
    conn.execute(
        """INSERT INTO rule (kind, field, matcher, pattern, weight, note, enabled, origin, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(kind, field, matcher, pattern) DO UPDATE SET
             weight=excluded.weight, note=excluded.note, enabled=excluded.enabled""",
        (rule.kind, rule.field, rule.matcher, rule.pattern, rule.weight,
         rule.note, int(rule.enabled), rule.origin, now()),
    )
    row = conn.execute(
        "SELECT id FROM rule WHERE kind=? AND field=? AND matcher=? AND pattern=?",
        (rule.kind, rule.field, rule.matcher, rule.pattern),
    ).fetchone()
    return int(row["id"])


def rules_file() -> Path:
    """Die eigenen Startregeln: `URBANIFY_RULES`, sonst `rules.yaml` im Repo.
    Wie der Katalog nicht versioniert — Vorlage ist `rules.example.yaml`."""
    return Path(os.environ.get("URBANIFY_RULES") or config.ROOT / "rules.yaml")


def sync_from_yaml(conn: sqlite3.Connection, path=None) -> int:
    """Mirror the rules file into the DB. Additive: rules made in the UI survive."""
    p = Path(path) if path else rules_file()
    if not p.is_file():
        return 0
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    count = 0
    for kind in KINDS:
        for item in raw.get(kind) or []:
            insert(conn, Rule(
                id=None, kind=kind,
                field=item["field"], matcher=item.get("matcher", "contains"),
                pattern=str(item["pattern"]), weight=float(item.get("weight", 1)),
                note=item.get("note"), enabled=bool(item.get("enabled", True)),
                origin="yaml",
            ))
            count += 1
    conn.commit()
    return count

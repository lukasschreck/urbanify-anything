"""The web surface: type a city, watch the survey, read the answer — and
then live with it: mark, judge, sharpen.

Local tool, no login, one person. A survey talks to a few thousand foreign servers and
takes a quarter of an hour, so it runs in a thread and reports through the
`progress` entry in the place's own file.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import bookmarks, config, personal, queries, report, rules, store, survey, verdicts
from .categories import CATEGORIES


def _personal() -> sqlite3.Connection:
    """Für alles, was keinem Ort gehört: Regeln und Profil."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    personal.attach(conn)
    return conn


@asynccontextmanager
async def lifespan(_app: FastAPI):
    conn = _personal()
    try:
        rules.sync_from_yaml(conn)
    finally:
        conn.close()
    yield


app = FastAPI(title="urbanify-anything", lifespan=lifespan)
WEB = config.ROOT / "web"
_running: dict[str, threading.Thread] = {}


class SurveyRequest(BaseModel):
    query: str
    days: int | None = None
    max_sites: int | None = None


def _conn(slug: str):
    try:
        return store.connect(slug)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


def _work(slug: str, req: SurveyRequest) -> None:
    conn = store.connect(slug)
    try:
        survey.measure(conn)
        survey.discover(conn)
        survey.probe_sites(conn, max_sites=req.max_sites)
        survey.harvest(conn, days=req.days)
        survey.assign(conn)
    except Exception as exc:  # noqa: BLE001 - der Fehler gehört in die Oberfläche
        store.set_meta(conn, "progress", {"step": "fehler", "text": f"{type(exc).__name__}: {exc}",
                                          "at": store.now()})
    finally:
        conn.close()
        _running.pop(slug, None)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "places": store.places(), "valhalla": config.VALHALLA_URL}


@app.get("/api/places")
def places() -> list[dict]:
    out = []
    for slug in store.places():
        conn = store.connect(slug)
        p = store.load_place(conn)
        n = conn.execute("SELECT COUNT(*) FROM event WHERE zone_auto IS NOT NULL").fetchone()[0]
        out.append({"slug": slug, "name": p.name, "display": p.display, "lat": p.lat,
                    "lon": p.lon, "events": n, "running": slug in _running,
                    "progress": store.get_meta(conn, "progress", {})})
        conn.close()
    return out


@app.post("/api/survey")
def start(req: SurveyRequest) -> dict:
    try:
        conn, p = survey.locate(req.query)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    store.set_meta(conn, "progress", {"step": "place", "text": p.display, "at": store.now()})
    conn.close()
    if p.slug not in _running:
        t = threading.Thread(target=_work, args=(p.slug, req), daemon=True)
        _running[p.slug] = t
        t.start()
    return {"slug": p.slug, "place": p.as_dict()}


@app.get("/api/places/{slug}/report")
def get_report(slug: str) -> dict:
    conn = _conn(slug)
    try:
        rep = report.build(conn)
        rep["running"] = slug in _running
        return rep
    finally:
        conn.close()


@app.get("/api/places/{slug}/zones")
def zones(slug: str) -> dict:
    conn = _conn(slug)
    feats = [json.loads(r["geojson"]) for r in
             conn.execute("SELECT geojson FROM zone ORDER BY profile, minutes DESC")]
    conn.close()
    return {"type": "FeatureCollection", "features": feats}


@app.get("/api/places/{slug}/sites")
def sites(slug: str) -> dict:
    conn = _conn(slug)
    feats = [{"type": "Feature",
              "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
              "properties": {k: r[k] for k in ("name", "kind", "url", "status", "platform", "minutes")}}
             for r in conn.execute("SELECT * FROM site WHERE lat IS NOT NULL")]
    conn.close()
    return {"type": "FeatureCollection", "features": feats}


@app.get("/api/places/{slug}/events")
def events(slug: str, source: str | None = None, category: str | None = None,
           window: str | None = None, profile: Literal["auto", "ebike"] = "auto",
           kids: bool = False, bookmarked: bool = False, adult: bool = True,
           visibility: Literal["highlights", "all", "hidden"] = "hidden") -> dict:
    """Ohne Angaben: alles in der Stunde, wie die Erhebung es zählt. Die Karte
    zum Leben fragt mit Fenster, Sichtbarkeit und `adult` aus dem Profil."""
    conn = _conn(slug)
    try:
        since = until = None
        if window:
            try:
                since, until = queries.window(window)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        evs = queries.fetch_events(
            conn, date_from=since, date_to=until, profile=profile, source=source,
            categories={c.strip() for c in category.split(",") if c.strip()} if category else None,
            kids_only=kids, bookmarked_only=bookmarked, adult=adult, visibility=visibility)
        out = queries.to_geojson(evs)
        # Die Töpfe zählen den ganzen Ausschnitt, nicht nur das Gezeigte —
        # sonst weiß man nicht, was „Nur Highlights" gerade weglässt.
        every = evs if visibility == "hidden" else queries.fetch_events(
            conn, date_from=since, date_to=until, profile=profile, source=source,
            categories={c.strip() for c in category.split(",") if c.strip()} if category else None,
            kids_only=kids, bookmarked_only=bookmarked, adult=adult)
        out["properties"] = {"count": len(evs), "counts": queries.counts(every)}
        return out
    finally:
        conn.close()


def _event(conn, event_id: int):
    row = conn.execute(f"{queries.EVENT_SQL} WHERE e.id = ?", (event_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Kein Termin mit dieser ID")
    return row


@app.get("/api/places/{slug}/events/{event_id}")
def event_detail(slug: str, event_id: int) -> dict:
    conn = _conn(slug)
    try:
        row = _event(conn, event_id)
        sc = rules.score(rules.subject_of(row), rules.load(conn))
        verdict = verdicts.verdict_for(row, verdicts.load(conn))
        d = dict(row)
        d.update(zone=d["zone_auto"], score=sc.score, verdict=verdict,
                 bucket=verdicts.BUCKET[verdict] if verdict else sc.bucket,
                 bookmarked=event_id in bookmarks.load(conn))
        n = conn.execute("SELECT COUNT(*) FROM event WHERE series_key = ?",
                         (row["series_key"],)).fetchone()[0]
        return {**queries.public(d), "description": row["description"],
                "street": row["street"], "postal_code": row["postal_code"],
                "zone_auto": row["zone_auto"], "zone_ebike": row["zone_ebike"],
                "lat": row["lat"], "lon": row["lon"], "license": row["license"],
                "rule_bucket": sc.bucket, "white": sc.white, "black": sc.black, "termine": n}
    finally:
        conn.close()


# ------------------------------------------------- vormerken und urteilen

class BookmarkIn(BaseModel):
    note: str | None = Field(None, max_length=500)


@app.put("/api/places/{slug}/events/{event_id}/bookmark")
def set_bookmark(slug: str, event_id: int, payload: BookmarkIn | None = None) -> dict:
    conn = _conn(slug)
    try:
        _event(conn, event_id)
        return {"bookmarked": True,
                **bookmarks.put(conn, event_id, payload.note if payload else None, slug)}
    finally:
        conn.close()


@app.delete("/api/places/{slug}/events/{event_id}/bookmark")
def clear_bookmark(slug: str, event_id: int) -> dict:
    conn = _conn(slug)
    try:
        return {"bookmarked": False, "removed": bookmarks.drop(conn, event_id)}
    finally:
        conn.close()


@app.get("/api/places/{slug}/bookmarks")
def list_bookmarks(slug: str) -> dict:
    """Die Merkliste, nächster Termin zuerst. Vergangenes bleibt stehen; was
    es nach einer neuen Erhebung nicht mehr gibt, steht unter `orphans`."""
    conn = _conn(slug)
    try:
        evs = queries.fetch_events(conn, bookmarked_only=True, require_zone=False)
        return {"bookmarks": [{**queries.public(e), "lat": e["lat"], "lon": e["lon"]} for e in evs],
                "orphans": bookmarks.orphans(conn, slug)}
    finally:
        conn.close()


class VerdictIn(BaseModel):
    value: Literal["ja", "vielleicht", "nein"]
    scope: Literal["serie", "event"] = "serie"
    note: str | None = Field(None, max_length=500)


@app.put("/api/places/{slug}/events/{event_id}/verdict")
def set_verdict(slug: str, event_id: int, payload: VerdictIn) -> dict:
    """Ein Urteil über diesen Termin oder die ganze Veranstaltung."""
    conn = _conn(slug)
    try:
        row = _event(conn, event_id)
        key = row["event_key"] if payload.scope == "event" else row["series_key"]
        v = verdicts.put(conn, payload.scope, key, payload.value, payload.note,
                         title=row["title"], venue=row["venue"], place=slug)
        n = conn.execute("SELECT COUNT(*) FROM event WHERE series_key = ?",
                         (row["series_key"],)).fetchone()[0] if payload.scope == "serie" else 1
        return {**v.as_dict(), "title": row["title"], "termine": n,
                "counts": verdicts.counts(conn)}
    finally:
        conn.close()


@app.delete("/api/places/{slug}/events/{event_id}/verdict")
def clear_verdict(slug: str, event_id: int,
                  scope: Literal["serie", "event"] = "serie") -> dict:
    conn = _conn(slug)
    try:
        row = _event(conn, event_id)
        key = row["event_key"] if scope == "event" else row["series_key"]
        return {"removed": verdicts.drop(conn, scope, key), "counts": verdicts.counts(conn)}
    finally:
        conn.close()


@app.get("/api/places/{slug}/curate")
def curate(slug: str, window: str = "alles", profile: Literal["auto", "ebike"] = "auto",
           limit: int = 60, alle: bool = False) -> dict:
    """Die Warteschlange: Veranstaltungen ohne Urteil, nächster Termin zuerst."""
    conn = _conn(slug)
    try:
        try:
            since, until = queries.window(window)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        adult = personal.profile(conn)["show_adult"]
        return {"counts": verdicts.counts(conn),
                "queue": queries.curation_queue(conn, date_from=since, date_to=until,
                                                profile=profile, adult=adult,
                                                limit=min(limit, 500), only_unjudged=not alle)}
    finally:
        conn.close()


# ----------------------------------------------------------------- regeln

class RuleIn(BaseModel):
    kind: Literal["white", "black"]
    field: Literal["title", "description", "category", "venue", "city", "source"]
    matcher: Literal["contains", "regex", "equals"] = "contains"
    pattern: str = Field(min_length=1, max_length=200)
    weight: float = Field(1.0, gt=0, le=10)
    note: str | None = Field(None, max_length=200)

    def to_rule(self) -> rules.Rule:
        try:
            return rules.Rule(id=None, kind=self.kind, field=self.field, matcher=self.matcher,
                              pattern=self.pattern, weight=self.weight, note=self.note)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc


@app.get("/api/rules")
def list_rules() -> list[dict]:
    conn = _personal()
    try:
        return [r.as_dict() for r in rules.load(conn, include_disabled=True)]
    finally:
        conn.close()


@app.post("/api/rules")
def add_rule(payload: RuleIn) -> dict:
    conn = _personal()
    try:
        rid = rules.insert(conn, payload.to_rule())
        conn.commit()
        return {"id": rid, **payload.model_dump()}
    finally:
        conn.close()


@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: int) -> dict:
    conn = _personal()
    try:
        cur = conn.execute("DELETE FROM rule WHERE id = ?", (rule_id,))
        conn.commit()
        if not cur.rowcount:
            raise HTTPException(404, "Keine Regel mit dieser ID")
        return {"deleted": rule_id}
    finally:
        conn.close()


@app.patch("/api/rules/{rule_id}")
def toggle_rule(rule_id: int, enabled: bool) -> dict:
    conn = _personal()
    try:
        cur = conn.execute("UPDATE rule SET enabled=? WHERE id=?", (int(enabled), rule_id))
        conn.commit()
        if not cur.rowcount:
            raise HTTPException(404, "Keine Regel mit dieser ID")
        return {"id": rule_id, "enabled": enabled}
    finally:
        conn.close()


class PreviewIn(BaseModel):
    rule: RuleIn | None = None
    without_rule_id: int | None = None
    examples: int = Field(8, ge=0, le=50)


@app.post("/api/places/{slug}/rules/preview")
def preview(slug: str, payload: PreviewIn) -> dict:
    """Was eine Regel an diesem Ort tut, bevor sie gespeichert wird: die drei
    Töpfe vorher und nachher, und Beispiele für das, was den Topf wechselt."""
    conn = _conn(slug)
    try:
        base = [r for r in rules.load(conn) if r.id != payload.without_rule_id]
        extra = [payload.rule.to_rule()] if payload.rule else []
        since, until = queries.window("alles")
        common = dict(date_from=since, date_to=until, require_zone=False, limit=100000)
        before = {e["id"]: e for e in queries.fetch_events(conn, ruleset=base, **common)}
        after = queries.fetch_events(conn, ruleset=base, extra_rules=extra, **common)
        # Nach Titel bündeln: ein Weihnachtsmarkt an 27 Tagen ist für die
        # Beurteilung einer Regel ein Fall, nicht 27.
        grouped: dict[str, dict] = {}
        changed = 0
        for ev in after:
            was = before[ev["id"]]
            if was["bucket"] == ev["bucket"]:
                continue
            changed += 1
            item = grouped.setdefault(f"{ev['title']}|{ev['bucket']}", {
                "title": ev["title"], "starts_at": ev["starts_at"], "venue": ev["venue"],
                "category": ev["category"], "from": was["bucket"], "to": ev["bucket"],
                "occurrences": 0})
            item["occurrences"] += 1
        return {"before": {"total": len(before), **queries.counts(list(before.values()))},
                "after": {"total": len(after), **queries.counts(after)},
                "changed": changed, "distinct": len(grouped),
                "examples": list(grouped.values())[:payload.examples]}
    finally:
        conn.close()


@app.get("/api/places/{slug}/rules/suggestions")
def rule_suggestions(slug: str, limit: int = 12) -> dict:
    """Regelvorschläge aus den Urteilen. Vorgeschlagen, nicht gesetzt."""
    conn = _conn(slug)
    try:
        p = store.load_place(conn)
        return {"counts": verdicts.counts(conn),
                "suggestions": verdicts.suggestions(conn, min(limit, 50),
                                                    skip=set(p.name.split()))}
    finally:
        conn.close()


# ----------------------------------------------------------------- profil

class ProfileIn(BaseModel):
    interests: list[str] | None = None
    travel_mode: Literal["auto", "ebike"] | None = None
    show_adult: bool | None = None


@app.get("/api/profile")
def get_profile() -> dict:
    conn = _personal()
    try:
        return {**personal.profile(conn), "categories": list(CATEGORIES)}
    finally:
        conn.close()


@app.put("/api/profile")
def put_profile(payload: ProfileIn) -> dict:
    conn = _personal()
    try:
        return {**personal.update_profile(conn, **payload.model_dump()),
                "categories": list(CATEGORIES)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        conn.close()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")

"""The web surface: type a city, watch the survey, read the answer.

Local tool, no login. A survey talks to a few thousand foreign servers and
takes a quarter of an hour, so it runs in a thread and reports through the
`progress` entry in the place's own file.
"""
from __future__ import annotations

import json
import threading

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, report, store, survey

app = FastAPI(title="urbanify-anything")
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
def events(slug: str, source: str | None = None, category: str | None = None) -> dict:
    conn = _conn(slug)
    sql = """SELECT e.title, e.starts_at, e.venue, e.url, e.category, e.lat, e.lon,
                    e.zone_auto, e.geo, e.source, s.name AS source_name
             FROM event e JOIN source s ON s.slug = e.source
             WHERE e.zone_auto IS NOT NULL"""
    args: list = []
    if source:
        sql += " AND e.source = ?"
        args.append(source)
    if category:
        sql += " AND e.category = ?"
        args.append(category)
    feats = [{"type": "Feature",
              "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
              "properties": {k: r[k] for k in r.keys() if k not in ("lat", "lon")}}
             for r in conn.execute(sql + " ORDER BY e.starts_at", args)]
    conn.close()
    return {"type": "FeatureCollection", "features": feats}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")

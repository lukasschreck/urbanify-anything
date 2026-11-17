"""Valhalla isochrones. Zones come from measurement, never from a radius.

Two profiles, car and e-bike. There is exactly one place where "what an
e-bike is" is defined.
"""
from __future__ import annotations

import httpx
from shapely.geometry import Point, shape
from shapely.prepared import prep

from . import config
from .place import Place

PROFILES: dict[str, dict] = {
    "auto": {"costing": "auto", "costing_options": {"auto": {}}},
    "ebike": {
        "costing": "bicycle",
        "costing_options": {"bicycle": {
            "bicycle_type": "Hybrid", "cycling_speed": 20,
            "use_hills": 0.25, "use_roads": 0.4,
        }},
    },
}


class ValhallaUnavailable(RuntimeError):
    pass


def graph_version(base_url: str | None = None) -> str:
    url = (base_url or config.VALHALLA_URL).rstrip("/")
    try:
        s = httpx.get(f"{url}/status", timeout=15,
                      headers={"User-Agent": config.USER_AGENT}).json()
        return f"{url} · {s.get('version', '?')} · {s.get('tileset_last_modified', '?')}"
    except Exception:  # noqa: BLE001
        return f"{url} · unbekannt"


def fetch(place: Place, profile: str,
          minutes: tuple[int, ...] = config.ZONE_MINUTES,
          base_url: str | None = None) -> list[dict]:
    """One GeoJSON feature per entry in `minutes`, innermost first."""
    if profile not in PROFILES:
        raise ValueError(f"Profil unbekannt: {profile!r}")
    url = (base_url or config.VALHALLA_URL).rstrip("/")
    body = {
        "locations": [{"lat": place.lat, "lon": place.lon}],
        "contours": [{"time": m} for m in minutes],
        "polygons": True, "denoise": 0.3, "generalize": 100,
        **PROFILES[profile],
    }
    try:
        r = httpx.post(f"{url}/isochrone", json=body, timeout=300,
                       headers={"User-Agent": config.USER_AGENT})
        r.raise_for_status()
        fc = r.json()
    except Exception as exc:  # noqa: BLE001
        raise ValhallaUnavailable(f"{url}/isochrone: {exc}") from exc
    feats = []
    for f in fc.get("features", []):
        if f.get("geometry", {}).get("type") not in ("Polygon", "MultiPolygon"):
            continue
        contour = f.get("properties", {}).get("contour")
        if contour is None:
            continue
        f["properties"] = {"minutes": int(float(contour)), "profile": profile}
        feats.append(f)
    feats.sort(key=lambda f: f["properties"]["minutes"])
    if not feats:
        raise ValhallaUnavailable(f"{url}/isochrone lieferte keine Fläche für {profile}")
    return feats


class Zones:
    """Point in polygon, innermost zone wins. Returns minutes, or None."""

    def __init__(self, features: list[dict]):
        feats = sorted(features, key=lambda f: f["properties"]["minutes"])
        self._geoms = [(f["properties"]["minutes"], shape(f["geometry"])) for f in feats]
        self._prep = [(m, prep(g)) for m, g in self._geoms]

    def __bool__(self) -> bool:
        return bool(self._geoms)

    def minutes_at(self, lat: float | None, lon: float | None) -> int | None:
        if lat is None or lon is None:
            return None
        pt = Point(lon, lat)
        for minutes, geom in self._prep:
            if geom.contains(pt):
                return minutes
        return None

    @property
    def outer(self):
        return self._geoms[-1][1]

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return self.outer.bounds  # minlon, minlat, maxlon, maxlat

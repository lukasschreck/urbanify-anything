"""From a name to a start point.

A place is whatever Nominatim makes of the query — a city, a village, a
district, an address. Nothing downstream cares which.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

import httpx

from . import config


@dataclass(frozen=True)
class Place:
    slug: str
    name: str            # „Berlin"
    display: str         # „Berlin, Deutschland"
    lat: float
    lon: float
    country: str         # ISO 3166-1 alpha-2, groß
    tz: str              # IANA, z. B. Europe/Berlin
    bbox: tuple[float, float, float, float] | None = None  # minlon, minlat, maxlon, maxlat

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Place":
        d = dict(d)
        if d.get("bbox"):
            d["bbox"] = tuple(d["bbox"])
        return cls(**d)


def slugify(text: str) -> str:
    text = text.lower().replace("ß", "ss")
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue")):
        text = text.replace(a, b)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "ort"


def timezone_at(lat: float, lon: float) -> str:
    from timezonefinder import TimezoneFinder
    return TimezoneFinder().timezone_at(lat=lat, lng=lon) or "UTC"


def find(query: str) -> Place:
    """Ask Nominatim once. Raises LookupError when nothing comes back."""
    r = httpx.get(
        f"{config.NOMINATIM_URL}/search",
        params={"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1,
                "accept-language": "de"},
        headers={"User-Agent": config.USER_AGENT}, timeout=30,
    )
    r.raise_for_status()
    hits = r.json()
    if not hits:
        raise LookupError(f"Nominatim kennt keinen Ort namens {query!r}.")
    h = hits[0]
    lat, lon = float(h["lat"]), float(h["lon"])
    name = h.get("name") or query
    s, n, w, e = (float(x) for x in h["boundingbox"])
    return Place(
        slug=slugify(name), name=name, display=h.get("display_name", name),
        lat=lat, lon=lon,
        country=(h.get("address", {}).get("country_code") or "").upper(),
        tz=timezone_at(lat, lon), bbox=(w, s, e, n),
    )

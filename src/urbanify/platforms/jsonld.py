"""schema.org/Event out of an HTML page."""
from __future__ import annotations

import json
import re
from typing import Any, Iterator

from .common import clean, local_iso, plain, to_float

KIND = "jsonld"

_SCRIPT = re.compile(
    r'<script[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I)


def _blocks(page: str) -> Iterator[Any]:
    for m in _SCRIPT.finditer(page):
        try:
            yield json.loads(m.group(1).strip(), strict=False)
        except json.JSONDecodeError:
            continue


def _walk(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for key in ("@graph", "subEvent", "subEvents", "itemListElement", "item", "event", "events"):
            child = node.get(key)
            if child:
                yield from _walk(child)
    elif isinstance(node, list):
        for child in node:
            yield from _walk(child)


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _text(value: Any) -> str | None:
    value = _first(value)
    if isinstance(value, dict):
        value = value.get("name") or value.get("url") or value.get("@id")
    return clean(str(value)) or None if value is not None else None


def count(page: str) -> int:
    return len(parse(page, "UTC"))


def parse(page: str, tz: str) -> list[dict]:
    out: list[dict] = []
    for block in _blocks(page):
        for node in _walk(block):
            types = node.get("@type")
            types = [types] if isinstance(types, str) else (types or [])
            if not any(str(t).endswith("Event") or str(t) == "Festival" for t in types):
                continue
            start = local_iso(_text(node.get("startDate")), tz)
            name = _text(node.get("name"))
            if not start or not name:
                continue
            end = local_iso(_text(node.get("endDate")), tz)
            loc = _first(node.get("location")) or {}
            if isinstance(loc, str):
                loc = {"name": loc}
            addr = _first(loc.get("address")) or {}
            if isinstance(addr, str):
                addr = {"streetAddress": addr}
            geo = _first(loc.get("geo")) or {}
            if not isinstance(geo, dict):
                geo = {}
            zip_ = _text(addr.get("postalCode"))
            out.append({
                "external_id": _text(node.get("@id")) or _text(node.get("url")),
                "title": name,
                "description": plain(_text(node.get("description")) or ""),
                "starts_at": start[0], "all_day": start[1],
                "ends_at": end[0] if end else None,
                "url": _text(node.get("url")),
                "venue": _text(loc.get("name")),
                "street": _text(addr.get("streetAddress")),
                "postal_code": None if zip_ in (None, "0") else zip_,
                "city": _text(addr.get("addressLocality")),
                "lat": to_float(geo.get("latitude")), "lon": to_float(geo.get("longitude")),
                "category_raw": ", ".join(t for t in map(str, types) if t != "Event") or None,
            })
    return out

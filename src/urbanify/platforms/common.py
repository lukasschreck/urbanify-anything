"""What all platform parsers share: time handling and text cleaning.

Times are stored as naive local ISO strings in the place's own timezone —
"2026-11-14T20:00:00" means eight in the evening where the event happens.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser

_TAGS = re.compile(r"<[^>]+>")


def clean(value) -> str:
    if not isinstance(value, str):
        return ""
    value = html.unescape(value).replace("­", "")
    return re.sub(r"\s+", " ", value).strip()


def plain(fragment) -> str | None:
    if not isinstance(fragment, str) or not fragment.strip():
        return None
    s = re.sub(r"(?i)<br\s*/?>|</p>", "\n", fragment)
    s = html.unescape(_TAGS.sub(" ", s))
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    return re.sub(r"\s*\n\s*", "\n", s).strip() or None


def local_iso(value, tz: str) -> tuple[str, bool] | None:
    """(ISO string, all_day) from a datetime, a date or a string."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = value.strip()
        all_day = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", text))
        try:
            value = dateparser.isoparse(text)
        except (ValueError, OverflowError):
            try:
                value = dateparser.parse(text, dayfirst=True)
            except (ValueError, OverflowError):
                return None
        if all_day:
            return value.strftime("%Y-%m-%dT00:00:00"), True
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(ZoneInfo(tz)).replace(tzinfo=None)
        return value.strftime("%Y-%m-%dT%H:%M:%S"), False
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00"), True
    return None


def to_float(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f != 0.0 else None   # 0/0 ist „nicht gepflegt"


def in_window(starts_at: str, ends_at: str | None, since: str, until: str) -> bool:
    """Läuft der Termin im Fenster? Eine Ausstellung, die schon begonnen hat, zählt."""
    return starts_at[:10] <= until and (ends_at or starts_at)[:10] >= since

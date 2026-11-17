"""Configuration. Nothing in here names a city.

Every service is a URL in the environment, so a self-hosted Valhalla or
Nominatim can replace the public one without touching code.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_env(path: Path) -> None:
    """Liest `.env` neben dem Repo. Was schon in der Umgebung steht, gewinnt."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_env(ROOT / ".env")
DATA = Path(os.environ.get("URBANIFY_DATA", ROOT / "data"))

# Öffentliche Instanz des FOSSGIS: weltweiter Graph, mit Höhendaten. Für
# Dauerbetrieb gehört hier ein eigener Graph hin — die öffentliche ist für
# gelegentliche Anfragen gedacht.
VALHALLA_URL = os.environ.get("URBANIFY_VALHALLA", "https://valhalla1.openstreetmap.de")
NOMINATIM_URL = os.environ.get("URBANIFY_NOMINATIM", "https://nominatim.openstreetmap.org")
OVERPASS_URL = os.environ.get("URBANIFY_OVERPASS", "https://overpass-api.de/api/interpreter")
OVERPASS_MIRRORS = ["https://overpass.private.coffee/api/interpreter"]

# Der Name, unter dem wir uns ausweisen und unter dem robots.txt uns anspricht.
# Ein Kontakt gehört für Dauerbetrieb dazu (Nominatim verlangt ihn); er kommt
# aus der Umgebung und steht nie im Repo.
UA_TOKEN = "urbanify-anything"
CONTACT = os.environ.get("URBANIFY_CONTACT", "").strip()
USER_AGENT = f"{UA_TOKEN}/0.1 ({CONTACT or 'ohne Kontaktangabe'})"

# Fremde Websites dürfen die Erhebung nicht ins eigene Netz schicken: Adressen,
# die nicht öffentlich sind (localhost, 192.168.x, Metadaten-Dienste), werden
# nicht abgerufen. Wer einen Katalog-Endpunkt im eigenen Netz hat, schaltet das
# bewusst ab.
ALLOW_PRIVATE = os.environ.get("URBANIFY_ALLOW_PRIVATE", "").strip().lower() in ("1", "true", "ja")

REQUEST_DELAY_S = float(os.environ.get("URBANIFY_DELAY", "1.0"))
CONCURRENCY = int(os.environ.get("URBANIFY_CONCURRENCY", "24"))

# Minuten je Zone, innerste zuerst. Die äußerste ist „die Stunde".
ZONE_MINUTES = (15, 30, 60)
PROFILES = ("auto", "ebike")

# Wie weit in die Zukunft Termine eingesammelt werden.
DAYS_AHEAD = int(os.environ.get("URBANIFY_DAYS", "60"))

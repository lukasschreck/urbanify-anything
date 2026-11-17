"""Normalisation of source categories onto our own set.

`category_raw` always keeps the source's own wording; this module only decides
what we file it under. The mapping is deliberately keyword-based and will be
wrong sometimes — that is why the raw value is kept.
"""
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

CATEGORIES = (
    "kunst",
    "musik",
    "theater",
    "comedy",
    "literatur",
    "film",
    "kinder",
    "museum",
    "markt/fest",
    "party",
    "kulinarik",
    "draussen",
    "sport",
    "kurs",
    "vortrag",
    "gemeinde",
    "sonstiges",
)

# Order matters: the first matching rule wins. More specific first.
_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("kinder", (
        "kinder", "kids", "familie", "jeune public", "enfant", "famille",
        "puppenspiel", "puppentheater", "marionnette", "maerchen", "marchen",
        "jugend", "schulkind", "kindertheater", "bastel", "krabbel",
    )),
    ("film", (
        "film", "kino", "cinema", "cine", "kurzfilm", "dokumentarfilm",
        "projection", "leinwand",
    )),
    # Vor dem Theater: Kabarett steht auf derselben Bühne, ist aber ein
    # anderer Abend.
    ("comedy", (
        "kabarett", "cabaret", "comedy", "comedie", "comedian", "humour",
        "humor", "variete", "stand-up", "standup", "kleinkunst", "satire",
        "one man show", "one woman show",
    )),
    ("theater", (
        "theater", "theatre", "schauspiel", "buehne", "buhne", "scene",
        "cirque", "zirkus", "oper", "opera", "operette",
        "musical", "tanz", "danse", "ballett", "improtheater", "spectacle",
    )),
    # Vor der Musik, weil dort „dj" und „techno" stehen: eine Clubnacht ist
    # kein Konzert.
    ("party", (
        "party", "nightlife", "disco", "diskothek", "clubnacht", "clubbing",
        "aftershow", "duesterdisco", "tanznacht", "soiree dansante",
    )),
    ("musik", (
        "musik", "musique", "konzert", "concert", "chor", "chorale", "jazz",
        "klassik", "classique", "rock", "pop", "blues", "folk", "orgel",
        "orchester", "orchestre", "band", "dj", "elektro", "techno", "hiphop",
        "liederabend", "serenade", "big band", "brass", "metal", "chanson",
    )),
    ("literatur", (
        "literatur", "litterature", "lesung", "lecture", "autoren", "buch",
        "livre", "poesie", "poetry", "slam", "erzaehl", "erzahl", "vorlese",
        "bibliothek", "bibliotheque", "mediathek",
    )),
    ("museum", (
        "museum", "musee", "ausstellung", "exposition", "vernissage",
        "galerie", "gallery", "sammlung", "patrimoine", "denkmal",
    )),
    ("kunst", (
        "kunst", "art", "arts", "bildend", "skulptur", "malerei", "fotografie",
        "photographie", "installation", "performance", "atelier", "werkstatt",
        "workshop", "street art", "design",
    )),
    # Vor Markt und Fest: ein Weinfest bleibt ein Fest, eine Weinprobe nicht.
    ("kulinarik", (
        "kulinarik", "kulinarisch", "essen & trinken", "dinner", "erlebnisdinner",
        "degustation", "verkostung", "weinprobe", "bierprobe", "tasting",
        "genuss", "brunch", "cuisine", "gastronomie", "whisky", "kochkurs",
        "muschelabend", "schlachtfest", "menue",
    )),
    ("markt/fest", (
        "markt", "marche", "fest", "fete", "festival", "kirmes", "messe",
        "jahrmarkt", "weihnachtsmarkt", "flohmarkt", "brocante", "hock",
        "umzug", "fasnet", "fastnacht", "fasnacht", "narren", "carnaval",
        "braderie", "kerwe", "strassenfest", "stadtfest", "weinfest", "wein",
    )),
    # Vor dem Sport: wer wandert, will kein Turnier.
    ("draussen", (
        "wander", "randonnee", "schwarzwaldverein", "nordic walking",
        "spaziergang", "radtour", "motorradtour", "schifffahrt", "ausflug",
        "busausfahrt", "balade", "krippenweg", "naturerlebnis", "naturpark",
        "naturschutz", "naturfuehrung", "pilzwanderung",
    )),
    ("sport", (
        "sport", "lauf", "course", "turnier", "tournoi", "wettkampf", "fussball",
        "football", "handball", "basketball", "radrennen", "velo", "schwimm",
        "yoga", "gymnastik", "fitness", "tanzsport", "zumba", "tai-chi",
        "pilates", "qigong", "kampfsport", "tennis", "marathon",
    )),
    # Mitmachen statt zuhören. Vor dem Vortrag, der früher „kurs" mit abholte.
    ("kurs", (
        "kurs", "cours", "workshop", "kreativtreff", "kreativkurs",
        "kreativprogramm", "basteln", "gesundheitskurs", "entspannung",
        "mitmach", "schnupper", "naehtreff", "strick",
        # „kurs" ist zu kurz, um hinten im Wort zu zählen — sonst wäre der
        # Diskurs einer. Die üblichen Zusammensetzungen stehen deshalb einzeln.
        "kurse", "toepferkurs", "malkurs", "zeichenkurs", "tanzkurs", "naehkurs",
        "sprachkurs", "schwimmkurs", "computerkurs", "backkurs", "fotokurs",
    )),
    # Was eine Gemeinde mitteilt, ohne dass es eine Veranstaltung im engeren
    # Sinn ist: Sitzungen, Gottesdienste, Müllabfuhr. Vor dem Vortrag, sonst
    # fängt dessen „info" die Bekanntmachungen ein.
    ("gemeinde", (
        "sitzung", "gemeinderat", "ortschaftsrat", "ausschuss", "bekanntmachung",
        "bekanntmachungen", "kirchliche", "gottesdienst", "patrozinium",
        "volkstrauertag", "gedenkfeier", "muellabfuhr", "feuerwehr",
        "hauptversammlung", "generalversammlung", "mitgliederversammlung",
        "seniorentreff", "senioren", "neujahrsempfang",
        "wirtschaftsrunde", "sprechstunde", "buergerversammlung",
    )),
    ("vortrag", (
        "vortrag", "conference", "lesungsvortrag", "seminar", "tagung",
        "diskussion", "debat", "podium", "fuehrung", "fuhrung", "visite",
        "rundgang", "exkursion", "info", "bildung", "talkrunde",
        "stadtfuehrung", "stadtfuhrung",
    )),
]

_FOLD = {
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "ae", "Ö": "oe", "Ü": "ue",
}

_KIDS_HINTS = _RULES[0][1]


def fold(text: str) -> str:
    """Lowercase, umlaut-folded, accent-stripped — for keyword matching."""
    if not text:
        return ""
    for src, dst in _FOLD.items():
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


def classify(category_raw: str | None, title: str = "", description: str = "") -> tuple[str, bool]:
    """Return (category, is_kids).

    The raw category carries most of the weight; title is consulted next,
    description last and only for the kids flag, because descriptions mention
    many things an event is not about.
    """
    raw = fold(category_raw or "")
    tit = fold(title)
    desc = fold(description or "")

    is_kids = _hit(_KIDS_HINTS, raw) or _hit(_KIDS_HINTS, tit) or _hit(_KIDS_HINTS, desc[:400])

    for cat, words in _RULES:
        if _hit(words, raw):
            return cat, is_kids
    for cat, words in _RULES:
        if _hit(words, tit):
            return cat, is_kids
    return "sonstiges", is_kids


# ------------------------------------------------------------------ 18+
#
# Kein Urteil über eine Szene, sondern über einen Abend: gemeint sind
# Veranstaltungen, die sich selbst als erotisch ausweisen. Dass ein Club erst
# ab 18 einlässt, zählt nicht — das gilt für jede Disco —, und eine queere
# Veranstaltung ist nicht deshalb 18+, weil sie queer ist.
#
# Im Titel und in der Kategorie der Quelle reicht ein Wort. In der
# Beschreibung braucht es zwei verschiedene: dort steht „Erotik" auch im
# Programmheft eines Theaters, und was fälschlich als 18+ gilt, verschwindet
# aus der Karte, ohne dass es jemand merkt.
_ADULT = (
    "erotik", "erotisch", "erotische", "erotic", "erotisme", "erotique",
    "fetisch", "fetish", "fetischparty", "kinky", "bdsm", "swinger",
    "playparty", "play party", "darkroom", "bondage", "shibari", "striptease",
    "sexparty", "sexpositiv", "sex-positiv", "fsk 18", "fsk18",
)
_ADULT_RE = re.compile("|".join(rf"\b{re.escape(w)}\b" for w in _ADULT))


def is_adult(category_raw: str | None, title: str = "", description: str = "") -> bool:
    """Weist sich die Veranstaltung selbst als 18+ aus?"""
    if _ADULT_RE.search(fold(category_raw or "")) or _ADULT_RE.search(fold(title)):
        return True
    return len(set(_ADULT_RE.findall(fold(description or "")[:800]))) >= 2


# ----------------------------------------------------------- Kinderalter
#
# Nur was dasteht, und nur in Formen, die ein Alter meinen: „ab 5 Jahren",
# „von 6 bis 12 Jahren", „dès 4 ans", „(4-7)" im Titel. Zahlen ohne solchen
# Rahmen sind Preise, Jubiläen oder Uhrzeiten. Lieber kein Alter als ein
# falsches — an der Zahl entscheidet jemand, ob er mit dem Kind hinfährt.
_J = r"(?:jahren?|j\.|ans?\b)"
_AGE_RANGE = re.compile(
    rf"(?:von |de |les |^|[\s(])(\d{{1,2}})\s*(?:-|–|bis|a)\s*(\d{{1,2}})\s*{_J}")
# „dès 6 ans" heißt im Programm „ab 6" und in einer Biografie „seit sie 6 war" —
# gezählt wird es nur dort, wo ein Programm es hinschreibt.
_AGE_FROM = re.compile(
    rf"(?:\bab|a partir de|(?:public|familiale?|famille|enfants|min|[|/(—–-])\s*des)"
    rf"\s+(\d{{1,2}})\s*{_J}")
_AGE_TITLE_RANGE = re.compile(r"\((\d{1,2})\s*[-–]\s*(\d{1,2})\)")
_AGE_TITLE_FROM = re.compile(r"\((?:ab\s*)?(\d{1,2})\s*\+\)|\bab (\d{1,2})\b(?! ?uhr| ?h\b)")


def kids_age(category_raw: str | None, title: str = "",
             description: str = "") -> tuple[int | None, int | None]:
    """(ab, bis) in Jahren, soweit die Quelle es sagt. Sonst (None, None)."""
    def plausible(lo: int, hi: int | None) -> bool:
        return 0 <= lo <= 16 and (hi is None or lo < hi <= 18)

    tit = fold(title)
    for text in (tit, fold(category_raw or ""), fold(description or "")[:1500]):
        m = _AGE_RANGE.search(text)
        if m and plausible(int(m.group(1)), int(m.group(2))):
            return int(m.group(1)), int(m.group(2))
        m = _AGE_FROM.search(text)
        if m and plausible(int(m.group(1)), None):
            return int(m.group(1)), None
        if text is tit:
            m = _AGE_TITLE_RANGE.search(text)
            if m and plausible(int(m.group(1)), int(m.group(2))):
                return int(m.group(1)), int(m.group(2))
            m = _AGE_TITLE_FROM.search(text)
            if m:
                lo = int(m.group(1) or m.group(2))
                if plausible(lo, None):
                    return lo, None
    return None, None


# --------------------------------------------------------- alles zusammen

class Described(NamedTuple):
    """Was wir über einen Termin aus seinem Text ableiten."""
    category: str
    is_kids: bool
    is_adult: bool
    age_min: int | None
    age_max: int | None


def describe(category_raw: str | None, title: str = "", description: str = "") -> Described:
    """Kategorie, Kinder- und 18+-Kennzeichen, Kinderalter — an einer Stelle.

    Einlesen und `cli reclassify` rufen beide nur das hier. Als jedes von
    ihnen die Teile selbst zusammensetzte, musste ein neues Kennzeichen an
    zwei Stellen nachgetragen werden, und eine vergessene fällt nicht auf:
    der Ingest schreibt dann nachts wieder weg, was die Neuzuordnung gesetzt hat.
    """
    category, kids = classify(category_raw, title, description)
    age = kids_age(category_raw, title, description) if kids else (None, None)
    return Described(category, kids, is_adult(category_raw, title, description), *age)


_PATTERNS: dict[tuple[str, ...], re.Pattern[str]] = {}


def _pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    """Treffer nur am Wortanfang oder Wortende, nie mitten im Wort.

    Deutsche Komposita setzen das Grundwort nach hinten, also muss
    „Orgelkonzert" auf `konzert` passen und „Festhalle" auf `fest`. Was
    dagegen *innerhalb* eines Wortes steckt, ist Zufall: „Martinsfeier"
    enthält `art` und wurde damit zu Kunst, „Verlauf" enthält `lauf` und
    wurde zu Sport.
    """
    cached = _PATTERNS.get(words)
    if cached is None:
        # Kurze Wörter nur am Wortanfang: „lauf" in „Verlauf" und „kurs" in
        # „Diskurs" sind Zufall, „Laufgruppe" und „Kurstage" nicht. Längere
        # dürfen auch hinten stehen, weil das deutsche Kompositum sein
        # Grundwort dorthin setzt — „Orgelkonzert".
        short = "|".join(re.escape(w) for w in words if len(w) < 5)
        long = "|".join(re.escape(w) for w in words if len(w) >= 5)
        parts = []
        if short:
            parts.append(rf"\b(?:{short})")
        if long:
            parts.append(rf"\b(?:{long})")
            parts.append(rf"(?:{long})\b")
        cached = re.compile("|".join(parts) if parts else r"(?!)")
        _PATTERNS[words] = cached
    return cached


def _hit(words: tuple[str, ...], haystack: str) -> bool:
    return bool(haystack) and _pattern(words).search(haystack) is not None

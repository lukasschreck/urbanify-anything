"""Can this website be asked for dates?

Adapters hang off platforms, not cities. So the question for each website is
not "who is this?" but "which platform answers here?" — and that can be found
out without knowing the place:

  tribe    WordPress with The Events Calendar: open REST API
  ics      a calendar feed, linked from the page
  jsonld   schema.org/Event embedded in the programme page
  crawl    the same, but only on each event's own page: the programme page
           is the list of links, every linked page carries one event

A site that has a programme page and none of the three is `nur-html`: there
are dates, but only for people. That list is the to-do list for new adapters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .platforms import ics, jsonld, tribe
from .web import Polite

# Wörter, an denen man eine Programmseite erkennt — Deutsch, Englisch,
# Französisch, Niederländisch, Spanisch, Italienisch, Polnisch. Eine weitere
# Sprache ist eine Zeile hier.
PROGRAMME = re.compile(
    r"(programm|spielplan|veranstaltung|kalender|termine|konzerte|vorstellungen|"
    r"events?\b|calendar|whats-?on|what.s on|schedule|agenda|programme|"
    r"program\b|activiteiten|calendario|eventi|eventos|wydarzenia|kalendarz)", re.I)
_ICS_HREF = re.compile(r"(\.ics(\?|$)|^webcal:|[?&]ical=1|format=ical|outputformat=ical|/ical/?$)", re.I)
_GENERATOR = re.compile(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', re.I)

MAX_PROGRAMME_PAGES = 3
MAX_DETAIL_PAGES = 40
PREFERENCE = ("tribe", "ics", "jsonld", "crawl")   # beste zuerst; geerntet wird nur eine


@dataclass
class Feed:
    kind: str
    url: str
    hint: int = 0           # wie viele Termine die Probe schon gesehen hat


@dataclass
class Finding:
    status: str                      # feed | nur-html | nichts | unerreichbar | robots
    platform: str | None = None
    feeds: list[Feed] = field(default_factory=list)
    note: str | None = None

    @property
    def best(self) -> Feed | None:
        for kind in PREFERENCE:
            hits = [f for f in self.feeds if f.kind == kind]
            if hits:
                return max(hits, key=lambda f: f.hint)
        return None


def platform_of(page: str) -> str | None:
    m = _GENERATOR.search(page)
    if m:
        name = re.split(r"[\s;,/]", m.group(1).strip())[0][:30]
        if name and name.lower() not in ("all", "site", "powered", "by"):
            return name
    low = page.lower()
    for needle, name in (("wp-content", "WordPress"), ("typo3", "TYPO3"),
                         ("squarespace", "Squarespace"), ("wixstatic", "Wix"),
                         ("jimdo", "Jimdo"), ("drupal", "Drupal"), ("joomla", "Joomla"),
                         ("webflow", "Webflow"), ("contao", "Contao")):
        if needle in low:
            return name
    return None


def read_page(page: str, base: str) -> tuple[list[str], list[str]]:
    """(ICS links, programme links on the same host), best first."""
    soup = BeautifulSoup(page, "lxml")
    host = urlparse(base).netloc.lower().removeprefix("www.")
    here = urlparse(base).path.rstrip("/")
    feeds: list[str] = []
    for link in soup.find_all("link", attrs={"type": re.compile("text/calendar", re.I)}):
        if link.get("href"):
            feeds.append(urljoin(base, link["href"]))
    linked: list[str] = []
    programme: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if _ICS_HREF.search(href):
            # Der Export dieser einen Seite („…/konzert-x?format=ical") ist ein
            # einzelner Termin zum Herunterladen, kein Kalender.
            target = urljoin(base, href)
            own = re.sub(r"(\.ics|/ical)?/?$", "", urlparse(target).path)
            if own != here:
                linked.append(target)
            continue
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(base, href).split("#")[0]
        p = urlparse(url)
        if p.netloc.lower().removeprefix("www.") != host or url.rstrip("/") == base.rstrip("/"):
            continue
        score = 2 * bool(PROGRAMME.search(p.path)) + bool(PROGRAMME.search(a.get_text(" ", strip=True)))
        if score:
            # Kurze Pfade sind Übersichten, lange sind einzelne Termine.
            score = score * 10 - p.path.strip("/").count("/")
            programme[url] = max(programme.get(url, -99), score)
    # Viele .ics-Links auf einer Seite sind Einzeltermine zum Herunterladen,
    # kein Abo. Dann zählt nur, was die Seite selbst als Feed ausweist.
    if len(set(linked)) <= 3:
        feeds += linked
    ranked = sorted(programme, key=lambda u: (-programme[u], len(u)))
    return list(dict.fromkeys(feeds))[:2], ranked[:MAX_PROGRAMME_PAGES]


def detail_links(page: str, listing: str) -> list[str]:
    """Links one level below the listing — the pages of single events."""
    lp = urlparse(listing)
    host = lp.netloc.lower().removeprefix("www.")
    prefix = lp.path.rstrip("/") + "/"
    out: dict[str, None] = {}
    for a in BeautifulSoup(page, "lxml").find_all("a", href=True):
        url = urljoin(listing, a["href"].strip()).split("#")[0]
        p = urlparse(url)
        if p.scheme not in ("http", "https") or p.netloc.lower().removeprefix("www.") != host:
            continue
        if prefix == "/":
            ok = bool(PROGRAMME.search(p.path)) and p.path.strip("/").count("/") >= 1
        else:
            ok = p.path.startswith(prefix) and len(p.path) > len(prefix)
        if ok and not re.search(r"\.(jpe?g|png|webp|pdf|ics)$", p.path, re.I):
            out[url] = None
    return list(out)


async def crawl(web: Polite, listing: str, tz: str) -> list[dict]:
    """Harvest for `crawl` feeds: the listing, then each event page once."""
    r = await web.get(listing)
    if r is None or r.status_code != 200:
        raise RuntimeError(f"HTTP {getattr(r, 'status_code', 'kein Zugriff')}")
    events = jsonld.parse(r.text, tz)
    for link in detail_links(r.text, str(r.url))[:MAX_DETAIL_PAGES]:
        p = await web.get(link)
        if p is not None and p.status_code == 200:
            for ev in jsonld.parse(p.text, tz):
                ev.setdefault("url", link)
                ev["url"] = ev["url"] or link
                events.append(ev)
    return events


async def probe(web: Polite, url: str) -> Finding:
    r = await web.get(url)
    if r is None:
        return Finding("robots" if web.forbidden(url) else "unerreichbar")
    if r.status_code in (404, 410) and urlparse(url).path.strip("/"):
        # OSM merkt sich Unterseiten, Websites ziehen um. Das Haus gibt es noch.
        r = await web.get("{0.scheme}://{0.netloc}/".format(urlparse(url))) or r
    if r.status_code >= 400:
        return Finding("unerreichbar", note=f"HTTP {r.status_code}")
    if "html" not in r.headers.get("content-type", "html"):
        return Finding("nichts", note=r.headers.get("content-type"))
    base, page = str(r.url), r.text
    root = "{0.scheme}://{0.netloc}".format(urlparse(base))
    found = Finding("nichts", platform=platform_of(page))

    ics_links, programme = read_page(page, base)
    pages = [(base, page)]
    n = jsonld.count(page)
    if n:
        found.feeds.append(Feed("jsonld", base, n))

    if "wp-content" in page or "wp-json" in page:
        api = root + tribe.API_PATH
        t = await web.get(api, params={"per_page": 1})
        if t is not None and t.status_code == 200 and "json" in t.headers.get("content-type", ""):
            try:
                data = t.json()
                if isinstance(data, dict) and "events" in data:
                    found.feeds.append(Feed("tribe", api, int(data.get("total") or 0)))
            except ValueError:
                pass

    if not any(f.kind == "tribe" for f in found.feeds):
        for link in programme:
            p = await web.get(link)
            if p is None or p.status_code != 200 or "html" not in p.headers.get("content-type", ""):
                continue
            pages.append((str(p.url), p.text))
            n = jsonld.count(p.text)
            if n:
                found.feeds.append(Feed("jsonld", str(p.url), n))
            more, _ = read_page(p.text, str(p.url))
            ics_links += more

    for link in list(dict.fromkeys(ics_links))[:2]:
        found.feeds.append(Feed("ics", link))

    # Eine Programmseite ohne eigene Daten, deren Einzelseiten welche tragen.
    lists = [f for f in found.feeds if f.kind == "jsonld" and f.hint >= 3]
    if not lists and not any(f.kind in ("tribe", "ics") for f in found.feeds):
        best_url, best_links = None, []
        for page_url, text in reversed(pages):          # Programmseiten vor der Startseite
            links = detail_links(text, page_url)
            if len(links) > len(best_links):
                best_url, best_links = page_url, links
        if len(best_links) >= 3:
            sample = await web.get(best_links[0])
            if sample is not None and sample.status_code == 200 and jsonld.count(sample.text):
                found.feeds = [f for f in found.feeds if f.kind != "jsonld"]
                found.feeds.append(Feed("crawl", best_url, len(best_links)))

    if found.feeds:
        found.status = "feed"
    elif programme:
        found.status = "nur-html"
        found.note = programme[0]
    return found

"""Polite fetching, for many hosts at once.

Politeness is per host: one request per second to any single server, however
many servers we talk to in parallel. robots.txt is read once per host and its
Crawl-delay is honoured (some hosts ask for 20 seconds, and get them).

Two guards against what a foreign website can do to us: an address that is
not public is never fetched (a website tag in OSM or a redirect must not send
the survey into the local network), and a body is read only up to MAX_BYTES.
"""
from __future__ import annotations

import asyncio
import ipaddress
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import httpx

from . import config

MAX_CRAWL_DELAY = 30.0
MAX_BYTES = 3_000_000
MAX_REDIRECTS = 5
_DROP = {"content-encoding", "content-length", "transfer-encoding"}


def is_public_ip(address: str) -> bool:
    """Öffentlich erreichbar — nicht Loopback, privat, link-local, reserviert."""
    try:
        return ipaddress.ip_address(address.split("%")[0]).is_global
    except ValueError:
        return False


class Polite:
    def __init__(self, delay: float | None = None, concurrency: int | None = None,
                 timeout: float = 20.0):
        self.delay = config.REQUEST_DELAY_S if delay is None else delay
        self._sem = asyncio.Semaphore(concurrency or config.CONCURRENCY)
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._public: dict[str, bool] = {}
        self.requests = 0
        # Weiterleitungen folgen wir selbst, damit jedes Ziel geprüft wird.
        self.client = httpx.AsyncClient(
            headers={"User-Agent": config.USER_AGENT,
                     "Accept-Language": "de,en;q=0.7"},
            follow_redirects=False, timeout=timeout,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.client.aclose()

    def _lock(self, host: str) -> asyncio.Lock:
        return self._locks.setdefault(host, asyncio.Lock())

    async def allowed(self, url: str) -> bool:
        """http(s), und der Host löst nur auf öffentliche Adressen auf."""
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        if config.ALLOW_PRIVATE:
            return True
        host = p.hostname.lower()
        if host not in self._public:
            try:
                ipaddress.ip_address(host)
                addrs = [host]
            except ValueError:
                try:
                    infos = await asyncio.get_running_loop().getaddrinfo(host, None)
                    addrs = [i[4][0] for i in infos]
                except OSError:
                    addrs = []
            self._public[host] = bool(addrs) and all(is_public_ip(a) for a in addrs)
        return self._public[host]

    async def _one(self, url: str, **kw) -> httpx.Response | None:
        """Ein Abruf, höchstens MAX_BYTES. None, wenn der Körper größer ist."""
        async with self.client.stream("GET", url, **kw) as r:
            if r.is_redirect:
                return r
            chunks, size = [], 0
            async for chunk in r.aiter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    return None
                chunks.append(chunk)
            # Der Körper ist schon entpackt; die Köpfe dazu dürfen nicht mit.
            headers = [(k, v) for k, v in r.headers.items() if k.lower() not in _DROP]
            return httpx.Response(r.status_code, headers=headers, content=b"".join(chunks),
                                  request=r.request)

    async def _raw(self, url: str, host: str, wait: float, **kw) -> httpx.Response | None:
        gap = time.monotonic() - self._last.get(host, 0.0)
        if gap < wait:
            await asyncio.sleep(wait - gap)
        try:
            for _ in range(MAX_REDIRECTS + 1):
                if not await self.allowed(url):
                    return None
                self.requests += 1
                r = await self._one(url, **kw)
                if r is None or not r.is_redirect or "location" not in r.headers:
                    return r
                url, kw = urljoin(str(r.url), r.headers["location"]), {}
            return None
        finally:
            self._last[host] = time.monotonic()

    async def _rules(self, root: str, host: str):
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = await self._raw(f"{root}/robots.txt", host, self.delay)
                # Ein robots.txt, das HTML ausliefert, ist keines.
                ok = r is not None and r.status_code == 200 and "<html" not in r.text[:400].lower()
                rp.parse(r.text.splitlines() if ok else [])
            except Exception:  # noqa: BLE001 - kein robots.txt heißt kein Verbot
                rp.parse([])
            self._robots[host] = rp
        return self._robots[host]

    async def get(self, url: str, *, robots: bool = True, **kw) -> httpx.Response | None:
        """Die Antwort, oder None: robots verbietet es, die Adresse ist nicht
        öffentlich, der Körper ist zu groß oder der Server schweigt.

        `robots=False` ist für Dienste gedacht, deren API wir nach deren
        eigenen Regeln benutzen (Nominatim, Overpass, Valhalla) — nie für
        fremde Websites.
        """
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.netloc:
            return None
        host, root = p.netloc.lower(), f"{p.scheme}://{p.netloc}"
        async with self._sem, self._lock(host):
            wait = self.delay
            if robots:
                rp = await self._rules(root, host)
                if not rp.can_fetch(config.UA_TOKEN, url):
                    return None
                cd = rp.crawl_delay(config.UA_TOKEN)
                if cd:
                    wait = min(max(wait, float(cd)), MAX_CRAWL_DELAY)
            try:
                return await self._raw(url, host, wait, **kw)
            except Exception:  # noqa: BLE001
                return None

    def forbidden(self, url: str) -> bool:
        """Nach einem `get`, das None lieferte: lag es an robots.txt?"""
        p = urlparse(url)
        rp = self._robots.get(p.netloc.lower())
        return bool(rp) and not rp.can_fetch(config.UA_TOKEN, url)

"""Ohne Netz: was die Erhebung nicht abruft, und wie sie abruft."""
import asyncio

import httpx

from urbanify import config, store, web


def test_nur_oeffentliche_adressen():
    for a in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "fe80::1", "kein-ip"):
        assert not web.is_public_ip(a), a
    assert web.is_public_ip("8.8.8.8") and web.is_public_ip("2606:4700:4700::1111")


def _polite(handler) -> web.Polite:
    p = web.Polite(delay=0)
    p.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return p


def test_private_ziele_und_weiterleitungen_dorthin_werden_nicht_geholt():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if req.url.path == "/weiter":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/geheim"})
        if req.url.path == "/um":
            return httpx.Response(301, headers={"location": "/ziel"})
        return httpx.Response(200, text="ok")

    async def run():
        async with _polite(handler) as p:
            assert await p.get("http://192.168.0.1/", robots=False) is None
            assert await p.get("http://8.8.8.8/weiter", robots=False) is None
            r = await p.get("http://8.8.8.8/um", robots=False)
            assert r.status_code == 200 and r.text == "ok" and r.url.path == "/ziel"
    asyncio.run(run())
    assert not any("127.0.0.1" in u or "192.168" in u for u in seen)


def test_zu_grosse_antworten_werden_abgebrochen(monkeypatch):
    monkeypatch.setattr(web, "MAX_BYTES", 1000)

    async def run():
        async with _polite(lambda req: httpx.Response(200, content=b"x" * 5000)) as p:
            assert await p.get("http://8.8.8.8/gross", robots=False) is None
        async with _polite(lambda req: httpx.Response(200, content=b"x" * 500)) as p:
            assert len((await p.get("http://8.8.8.8/klein", robots=False)).content) == 500
    asyncio.run(run())


def test_termin_urls_nur_http():
    assert store.web_url(" https://haus.example/x ") == "https://haus.example/x"
    for bad in ("javascript:alert(1)", "data:text/html,x", "/relativ", "", None, 7):
        assert store.web_url(bad) is None


def test_env_datei_wird_gelesen_und_die_umgebung_gewinnt(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('# Kommentar\nURBANIFY_TEST_A="aus datei"\nexport URBANIFY_TEST_B=b\n', encoding="utf-8")
    monkeypatch.setenv("URBANIFY_TEST_B", "aus umgebung")
    monkeypatch.delenv("URBANIFY_TEST_A", raising=False)
    config._load_env(f)
    import os
    assert os.environ.pop("URBANIFY_TEST_A") == "aus datei"
    assert os.environ["URBANIFY_TEST_B"] == "aus umgebung"

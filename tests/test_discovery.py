"""Ohne Netz: was eine Fundstelle ist, und was eine Seite über sich verrät."""
from urbanify import catalog, osm, probe, store
from urbanify.isochrone import Zones

SQUARE = {"type": "Feature", "properties": {"minutes": 60, "profile": "auto"},
          "geometry": {"type": "Polygon", "coordinates": [[[13, 52], [14, 52], [14, 53], [13, 53], [13, 52]]]}}
INNER = {"type": "Feature", "properties": {"minutes": 15, "profile": "auto"},
         "geometry": {"type": "Polygon", "coordinates": [[[13.3, 52.4], [13.5, 52.4], [13.5, 52.6], [13.3, 52.6], [13.3, 52.4]]]}}


def test_die_innerste_zone_gewinnt_und_draussen_ist_none():
    z = Zones([SQUARE, INNER])
    assert z.minutes_at(52.5, 13.4) == 15
    assert z.minutes_at(52.9, 13.9) == 60
    assert z.minutes_at(48.6, 8.07) is None and z.minutes_at(None, None) is None


def test_soziale_netze_sind_keine_website_eines_hauses():
    assert osm.normalise("https://www.facebook.com/einclub") is None
    assert osm.normalise("instagram.com/x") is None
    assert osm.normalise("www.buehne.example/") == ("https://www.buehne.example/", "www.buehne.example")
    assert osm.normalise("http://example.org/haus/;http://zwei.example") == ("http://example.org/haus", "example.org")


def test_kandidaten_eine_zeile_je_website_und_nur_in_der_stunde():
    els = [
        {"type": "node", "id": 1, "lat": 52.5, "lon": 13.4, "tags": {"amenity": "library", "name": "Bib", "website": "https://haus.example"}},
        {"type": "way", "id": 2, "center": {"lat": 52.5, "lon": 13.4}, "tags": {"amenity": "theatre", "name": "Bühne", "website": "https://haus.example/"}},
        {"type": "node", "id": 3, "lat": 48.6, "lon": 8.07, "tags": {"amenity": "theatre", "website": "https://weit.example"}},
    ]
    rows = osm.candidates(els, Zones([SQUARE, INNER]))
    assert len(rows) == 1
    assert rows[0]["kind"] == "Theater" and rows[0]["n_objects"] == 2 and rows[0]["minutes"] == 15


def test_katalog_gilt_per_flaeche_nicht_per_namen():
    # Die Stunde dieses Tests: 13–14 Ost, 52–53 Nord.
    outer = Zones([SQUARE]).outer
    gilt = {"slug": "weltweit", "coverage": "world"}
    schneidet = {"slug": "nachbarland", "coverage": [13.6, 52.9, 15.0, 54.0]}
    daneben = {"slug": "anderes-ende", "coverage": [7.5, 47.5, 10.5, 49.8]}
    assert catalog.applies(gilt, outer)
    # Ein Eintrag gilt, sobald seine Fläche die Stunde berührt — ein Landesportal
    # also auch für den Ort knapp jenseits der Grenze.
    assert catalog.applies(schneidet, outer)
    assert not catalog.applies(daneben, outer)
    assert not catalog.applies({"slug": "ohne-angabe"}, outer)


def test_der_katalog_ist_daten_und_kommt_aus_der_umgebung(tmp_path, monkeypatch):
    eigener = tmp_path / "katalog.yaml"
    eigener.write_text('- slug: eigen\n  name: Eigene Sammelstelle\n  kind: none\n'
                       '  endpoint: https://example.org\n  coverage: world\n', encoding="utf-8")
    monkeypatch.setenv("URBANIFY_CATALOG", str(eigener))
    assert [e["slug"] for e in catalog.entries()] == ["eigen"]
    # Kein Katalog ist kein Fehler: dann zählt allein, was OSM kennt.
    monkeypatch.setenv("URBANIFY_CATALOG", "")
    monkeypatch.setattr(catalog, "NAME", "gibt-es-nicht.yaml")
    assert catalog.entries() == []


def test_seite_lesen_feed_und_programmseiten():
    page = """<html><head><link rel="alternate" type="text/calendar" href="/kalender.ics">
      <meta name="generator" content="WordPress 6.6"></head><body>
      <a href="/programm">Spielplan</a> <a href="/programm/2026/11/stueck">Stück</a>
      <a href="/kontakt">Kontakt</a> <a href="https://anderswo.example/events">fremd</a>
      <a href="/stueck-x?format=ical">Termin speichern</a></body></html>"""
    feeds, programme = probe.read_page(page, "https://haus.example/")
    assert feeds == ["https://haus.example/kalender.ics", "https://haus.example/stueck-x?format=ical"]
    assert programme[0] == "https://haus.example/programm"
    assert probe.platform_of(page) == "WordPress"
    # Der Export der Seite selbst ist ein einzelner Termin, kein Kalender.
    assert probe.read_page(page, "https://haus.example/stueck-x")[0] == ["https://haus.example/kalender.ics"]
    assert probe.detail_links(page, "https://haus.example/programm") == ["https://haus.example/programm/2026/11/stueck"]


def test_bester_feed_tribe_vor_ics_vor_jsonld():
    f = probe.Finding("feed", feeds=[probe.Feed("jsonld", "a", 9), probe.Feed("ics", "b"), probe.Feed("tribe", "c", 3)])
    assert f.best.kind == "tribe"


def test_dublettenschluessel_haelt_titel_tag_und_ort_zusammen():
    a = store.dedup_key("Trio & Gast – Releasekonzert", "2026-11-14T20:00:00", 52.5201, 13.4049, "b-flat")
    b = store.dedup_key("Trio &amp; Gast - Releasekonzert", "2026-11-14T21:00:00", 52.5204, 13.4041, "B Flat")
    c = store.dedup_key("Trio & Gast – Releasekonzert", "2026-11-15T20:00:00", 52.5201, 13.4049, "b-flat")
    assert a != c
    assert store.dedup_key("Trio Gast", "2026-11-14T20:00:00", 52.5201, 13.4049, None) == \
           store.dedup_key("TRIO  gast", "2026-11-14T22:00:00", 52.5204, 13.4041, None)
    assert a != b   # „&amp;" ist ein anderer Titel — die Parser lösen Entitäten vorher auf

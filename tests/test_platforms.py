"""Ohne Netz: die Parser gegen kleine, echte Formen ihrer Plattformen."""
from urbanify.platforms import ics, jsonld, tribe
from urbanify.platforms.common import local_iso

TZ = "Europe/Berlin"


def test_local_iso_rechnet_in_die_ortszeit_um():
    assert local_iso("2026-11-14T19:00:00Z", TZ) == ("2026-11-14T20:00:00", False)
    assert local_iso("2026-11-14T20:00:00+01:00", TZ) == ("2026-11-14T20:00:00", False)
    assert local_iso("2026-11-14", TZ) == ("2026-11-14T00:00:00", True)
    assert local_iso("kein Datum", TZ) is None


def test_jsonld_findet_events_im_graph_und_in_listen():
    page = """<html><script type="application/ld+json">
    {"@graph": [{"@type": "WebSite", "name": "x"},
      {"@type": "MusicEvent", "name": "Trio &amp; Gast", "startDate": "2026-11-14T20:00:00+01:00",
       "location": {"@type": "Place", "name": "b-flat", "address": {"streetAddress": "Dircksenstr. 40",
       "postalCode": "10178", "addressLocality": "Berlin"}, "geo": {"latitude": "52.52", "longitude": 13.4}}}]}
    </script><script type="application/ld+json">{kaputt</script>
    <script type="application/ld+json">[{"@type": "Event", "name": "Ohne Datum"}]</script></html>"""
    events = jsonld.parse(page, TZ)
    assert len(events) == 1
    e = events[0]
    assert e["title"] == "Trio & Gast" and e["starts_at"] == "2026-11-14T20:00:00"
    assert (e["lat"], e["lon"]) == (52.52, 13.4) and e["city"] == "Berlin"
    assert e["category_raw"] == "MusicEvent"


def test_tribe_venue_als_leere_liste_und_plz_in_der_stadt():
    payload = {"total_pages": 1, "events": [
        {"id": 7, "title": "Jazz&#8217;n", "start_date": "2026-11-14 22:00:00",
         "end_date": "2026-11-15 02:00:00", "venue": [], "categories": [{"name": "Konzert"}]},
        {"id": 8, "title": "Markt", "start_date": "2026-11-15 10:00:00", "all_day": True,
         "venue": {"venue": "Rathaus", "city": "14467 Potsdam", "geo_lat": 0, "geo_lng": 0}}]}
    a, b = tribe.parse(payload, TZ)
    assert a["title"] == "Jazz’n" and a["venue"] is None and a["category_raw"] == "Konzert"
    assert b["starts_at"] == "2026-11-15T00:00:00" and b["all_day"]
    assert (b["postal_code"], b["city"]) == ("14467", "Potsdam")
    assert b["lat"] is None            # 0/0 heißt „nicht gepflegt", nicht „im Golf von Guinea"


def test_ics_faltet_wiederholungen_nur_im_fenster_auf():
    text = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//", "BEGIN:VEVENT", "UID:a@x",
        "SUMMARY:Offene Werkstatt", "DTSTART;TZID=Europe/Berlin:20261102T180000",
        "DTEND;TZID=Europe/Berlin:20261102T200000", "RRULE:FREQ=WEEKLY;BYDAY=MO",
        "LOCATION:c-base", "END:VEVENT", "END:VCALENDAR"])
    assert ics.looks_like(text)
    events = ics.parse(text, TZ, "2026-11-13", "2026-11-30")
    assert [e["starts_at"] for e in events] == [
        "2026-11-16T18:00:00", "2026-11-23T18:00:00", "2026-11-30T18:00:00"]
    assert events[0]["venue"] == "c-base"

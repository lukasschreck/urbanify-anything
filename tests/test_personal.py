"""Vormerken, urteilen, schärfen — an der Datenschicht und an den Endpunkten.

Ein Test der Datenschicht beweist keinen Endpunkt, darum ruft die zweite
Hälfte sie auf.
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from urbanify import bookmarks, config, personal, queries, rules, store, verdicts
from urbanify.place import Place

DAY = (date.today() + timedelta(days=3)).isoformat()


def ev(title, **more):
    return {"title": title, "starts_at": f"{DAY}T19:00:00", "venue": "Altes Kino",
            "lat": 1.0, "lon": 2.0, "external_id": title, **more}


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setenv("URBANIFY_RULES", str(tmp_path / "keine-regeln.yaml"))
    c = store.connect("ort", create=True)
    store.save_place(c, Place(slug="ort", name="Ort", display="Ort", lat=1.0, lon=2.0,
                              country="de", tz="Europe/Berlin"))
    store.upsert_source(c, "haus", name="Haus", kind="ics", status="ok")
    for e in (ev("Lesung im Hof", category_raw="Lesung"),
              ev("Hauptversammlung des Vereins"),
              ev("Puppentheater ab 4 Jahren", category_raw="Kinder"),
              ev("Fetisch Night", category_raw="Party")):
        store.upsert_event(c, "haus", e)
    c.execute("UPDATE event SET zone_auto = 15")
    c.commit()
    yield c
    c.close()


def ids(evs):
    return {e["title"] for e in evs}


def test_kennzeichen_und_schluessel_stehen_am_termin(conn):
    rows = {r["title"]: r for r in conn.execute("SELECT * FROM event")}
    assert rows["Fetisch Night"]["is_adult"] == 1
    assert rows["Puppentheater ab 4 Jahren"]["is_kids"] == 1
    assert rows["Puppentheater ab 4 Jahren"]["age_min"] == 4
    assert all(r["event_key"] and r["series_key"] for r in rows.values())


def test_eine_alte_datei_bekommt_die_spalten_beim_oeffnen(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setattr(config, "DATA", tmp_path)
    (tmp_path / "alt").mkdir()
    old = sqlite3.connect(tmp_path / "alt" / "urbanify.sqlite")
    old.executescript("""CREATE TABLE event (id INTEGER PRIMARY KEY, source TEXT NOT NULL,
        external_id TEXT NOT NULL, title TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT,
        all_day INTEGER DEFAULT 0, venue TEXT, street TEXT, postal_code TEXT, city TEXT,
        lat REAL, lon REAL, geo TEXT NOT NULL DEFAULT 'fehlt', zone_auto INTEGER,
        zone_ebike INTEGER, category TEXT, category_raw TEXT, is_kids INTEGER DEFAULT 0,
        url TEXT, description TEXT, dedup_key TEXT, UNIQUE (source, external_id, starts_at));
        INSERT INTO event (source, external_id, title, starts_at)
        VALUES ('haus', 'x', 'BDSM Stammtisch', '2030-01-01T20:00:00');""")
    old.close()
    c = store.connect("alt")
    row = c.execute("SELECT * FROM event").fetchone()
    assert row["is_adult"] == 1 and row["event_key"] and row["series_key"]


def test_regel_urteil_lesezeichen_in_dieser_rangfolge(conn):
    rules.insert(conn, rules.Rule(None, "white", "category", "equals", "literatur", 2))
    rules.insert(conn, rules.Rule(None, "black", "title", "contains", "Hauptversammlung", 5))
    conn.commit()
    assert ids(queries.fetch_events(conn, visibility="highlights")) == {"Lesung im Hof"}
    assert "Hauptversammlung des Vereins" not in ids(queries.fetch_events(conn, visibility="all"))
    # Nichts ist verworfen: wer auch Ausgeblendetes sehen will, bekommt es.
    assert len(queries.fetch_events(conn)) == 4

    # Das Urteil schlägt die Regel …
    row = conn.execute("SELECT * FROM event WHERE title LIKE 'Lesung%'").fetchone()
    verdicts.put(conn, "serie", row["series_key"], "nein")
    assert ids(queries.fetch_events(conn, visibility="highlights")) == set()
    # … und das Lesezeichen beide.
    bookmarks.put(conn, row["id"], place="ort")
    got = queries.fetch_events(conn, visibility="highlights")
    assert ids(got) == {"Lesung im Hof"} and got[0]["bookmarked"] and got[0]["bucket"] == "hidden"
    # Zurücknehmen bringt den Regelstand zurück.
    verdicts.drop(conn, "serie", row["series_key"])
    bookmarks.drop(conn, row["id"])
    assert ids(queries.fetch_events(conn, visibility="highlights")) == {"Lesung im Hof"}


def test_18plus_bleibt_aus_bis_man_es_einschaltet(conn):
    assert "Fetisch Night" not in ids(queries.fetch_events(conn, adult=False))
    assert "Fetisch Night" in ids(queries.fetch_events(conn, adult=True))


def test_lesezeichen_ueberlebt_eine_neue_erhebung(conn):
    row = conn.execute("SELECT id FROM event WHERE title LIKE 'Lesung%'").fetchone()
    bookmarks.put(conn, row["id"], place="ort")
    conn.execute("DELETE FROM event")            # die Erhebung baut neu …
    store.upsert_event(conn, "haus", ev("Lesung im Hof", category_raw="Lesung"))
    conn.execute("UPDATE event SET zone_auto = 15")
    conn.commit()                                 # … mit neuen Nummern
    assert ids(queries.fetch_events(conn, bookmarked_only=True)) == {"Lesung im Hof"}
    # Verlegt: derselbe Eintrag der Quelle, anderer Beginn — ein Vorschlag.
    conn.execute("UPDATE event SET starts_at = ?, event_key = 'neu'", (f"{DAY}T20:00:00",))
    conn.commit()
    lost = bookmarks.orphans(conn, "ort")
    assert len(lost) == 1 and lost[0]["candidate"]["title"] == "Lesung im Hof"


def test_vorschlaege_aus_urteilen_ohne_den_ortsnamen(conn):
    for i in range(4):
        store.upsert_event(conn, "haus", ev(f"Ort Jazzabend {i}", venue=f"Keller {i}"))
    for r in conn.execute("SELECT series_key FROM event WHERE title LIKE '%Jazzabend%'").fetchall():
        verdicts.put(conn, "serie", r["series_key"], "ja")
    got = verdicts.suggestions(conn, skip={"Ort"})
    patterns = {(s["field"], s["pattern"]) for s in got}
    assert ("title", "jazzabend") in patterns and ("title", "ort") not in patterns


def test_profil_ordnet_und_prueft(conn):
    assert personal.profile(conn)["show_adult"] is False
    p = personal.update_profile(conn, interests=["theater", "musik"], travel_mode="ebike")
    assert p["interests"] == ["musik", "theater"] and p["travel_mode"] == "ebike"
    with pytest.raises(ValueError):
        personal.update_profile(conn, interests=["gibt-es-nicht"])


def test_startregeln_kommen_aus_der_datei_und_bleiben_additiv(conn, tmp_path):
    f = tmp_path / "rules.yaml"
    f.write_text("white:\n  - {field: category, matcher: equals, pattern: theater, weight: 3}\n")
    rules.insert(conn, rules.Rule(None, "black", "title", "contains", "Blutspende", 5))
    assert rules.sync_from_yaml(conn, f) == 1 and rules.sync_from_yaml(conn, f) == 1
    assert len(rules.load(conn)) == 2
    assert rules.sync_from_yaml(conn, tmp_path / "fehlt.yaml") == 0


# ------------------------------------------------------------ Endpunkte

@pytest.fixture
def client(conn):
    from urbanify import main
    with TestClient(main.app) as c:
        yield c


def test_endpunkte_vormerken_urteilen_schaerfen(client, conn):
    fc = client.get("/api/places/ort/events").json()
    assert fc["properties"]["count"] == 4
    lesung = next(f["properties"] for f in fc["features"] if f["properties"]["title"].startswith("Lesung"))
    eid = lesung["id"]

    assert client.put(f"/api/places/ort/events/{eid}/bookmark").json()["bookmarked"]
    marks = client.get("/api/places/ort/bookmarks").json()
    assert [b["title"] for b in marks["bookmarks"]] == ["Lesung im Hof"] and marks["orphans"] == []
    assert client.get(f"/api/places/ort/events/{eid}").json()["bookmarked"] is True
    assert client.delete(f"/api/places/ort/events/{eid}/bookmark").json()["removed"]

    r = client.put(f"/api/places/ort/events/{eid}/verdict", json={"value": "ja"}).json()
    assert r["termine"] == 1 and r["counts"]["ja"] == 1
    high = client.get("/api/places/ort/events?visibility=highlights&window=14tage").json()
    assert [f["properties"]["title"] for f in high["features"]] == ["Lesung im Hof"]
    assert high["properties"]["counts"] == {"highlight": 1, "normal": 3, "hidden": 0}
    queue = client.get("/api/places/ort/curate").json()["queue"]
    assert "Lesung im Hof" not in {q["title"] for q in queue}
    assert "Fetisch Night" not in {q["title"] for q in queue}     # 18+ steht im Profil
    assert client.delete(f"/api/places/ort/events/{eid}/verdict").json()["removed"]

    rule = {"kind": "black", "field": "title", "pattern": "Hauptversammlung", "weight": 5}
    pre = client.post("/api/places/ort/rules/preview", json={"rule": rule}).json()
    assert pre["changed"] == 1 and pre["examples"][0]["to"] == "hidden"
    rid = client.post("/api/rules", json=rule).json()["id"]
    assert len(client.get("/api/rules").json()) == 1
    assert client.patch(f"/api/rules/{rid}?enabled=false").json()["enabled"] is False
    assert client.delete(f"/api/rules/{rid}").json() == {"deleted": rid}
    assert client.post("/api/rules", json={**rule, "matcher": "regex", "pattern": "("}).status_code == 400

    assert client.put("/api/profile", json={"show_adult": True}).json()["show_adult"] is True
    assert client.put("/api/profile", json={"interests": ["nope"]}).status_code == 400
    assert client.get("/api/places/ort/events/99999").status_code == 404
    assert client.get("/api/places/ort/events?window=morgen").status_code == 400
    assert client.get("/api/places/ort/rules/suggestions").json()["suggestions"] == []

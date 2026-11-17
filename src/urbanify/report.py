"""Which sources hold which events — the answer the survey exists for.

"Inside" always means: inside the outermost car zone. Events outside it or
without a known place are counted separately, never dropped.
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict

from . import store


def build(conn: sqlite3.Connection) -> dict:
    place = store.load_place(conn)
    win = store.get_meta(conn, "window", {})
    zones = [dict(r) for r in conn.execute(
        "SELECT profile, minutes, computed_at, graph FROM zone ORDER BY profile, minutes")]

    sites = Counter()
    for r in conn.execute("SELECT status, COUNT(*) n FROM site GROUP BY status"):
        sites[r["status"]] = r["n"]
    site_kinds = [dict(r) for r in conn.execute(
        """SELECT kind, COUNT(*) AS websites,
                  SUM(status='feed') AS feed, SUM(status='nur-html') AS nur_html
           FROM site GROUP BY kind ORDER BY websites DESC""")]
    platforms = [dict(r) for r in conn.execute(
        """SELECT COALESCE(platform, 'unbekannt') AS platform, COUNT(*) AS n,
                  SUM(status='feed') AS feed
           FROM site WHERE status NOT IN ('offen','uebersprungen','unerreichbar','robots')
           GROUP BY 1 ORDER BY n DESC LIMIT 12""")]

    # Wer hat einen Termin noch? dedup_key → Menge der Quellen.
    holders: dict[str, set[str]] = defaultdict(set)
    for r in conn.execute("SELECT dedup_key, source FROM event WHERE zone_auto IS NOT NULL"):
        holders[r["dedup_key"]].add(r["source"])

    sources = []
    for s in conn.execute("SELECT * FROM source ORDER BY origin, slug"):
        rows = conn.execute(
            "SELECT zone_auto, geo, category, dedup_key, venue FROM event WHERE source=?",
            (s["slug"],)).fetchall()
        inside = [r for r in rows if r["zone_auto"] is not None]
        keys = {r["dedup_key"] for r in inside}
        sources.append({
            "slug": s["slug"], "name": s["name"], "kind": s["kind"], "origin": s["origin"],
            "endpoint": s["endpoint"], "status": s["status"], "error": s["error"],
            "license": s["license"], "note": s["note"],
            "events": len(rows), "inside": len(inside),
            "outside": sum(1 for r in rows if r["zone_auto"] is None and r["geo"] not in ("fehlt", "offen")),
            "unplaced": sum(1 for r in rows if r["geo"] in ("fehlt", "offen")),
            "unique": sum(1 for k in keys if len(holders[k]) == 1),
            "venues": len({r["venue"] for r in inside if r["venue"]}),
            "categories": dict(Counter(r["category"] for r in inside).most_common()),
            "by_zone": dict(sorted(Counter(r["zone_auto"] for r in inside).items())),
        })
    sources.sort(key=lambda s: (-s["inside"], -s["events"], s["slug"]))

    by_kind = defaultdict(lambda: {"sources": 0, "with_events": 0, "inside": 0})
    for s in sources:
        k = by_kind[s["kind"]]
        k["sources"] += 1
        k["with_events"] += bool(s["events"])
        k["inside"] += s["inside"]

    # Überschneidung: welche Quellen führen dieselben Termine?
    pairs = Counter()
    for srcs in holders.values():
        ordered = sorted(srcs)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                pairs[(a, b)] += 1
    names = {s["slug"]: s["name"] for s in sources}

    cats = defaultdict(Counter)       # Kategorie → Quelle → Anzahl
    for r in conn.execute(
            "SELECT category, source, COUNT(*) n FROM event WHERE zone_auto IS NOT NULL GROUP BY 1,2"):
        cats[r["category"]][r["source"]] = r["n"]
    categories = [{
        "category": c, "events": sum(cnt.values()), "sources": len(cnt),
        "top": [{"slug": s, "name": names.get(s, s), "n": n} for s, n in cnt.most_common(3)],
    } for c, cnt in sorted(cats.items(), key=lambda kv: -sum(kv[1].values()))]

    total = conn.execute(
        """SELECT COUNT(*) AS events, SUM(zone_auto IS NOT NULL) AS inside,
                  SUM(zone_ebike IS NOT NULL) AS inside_ebike,
                  SUM(geo IN ('fehlt','offen')) AS unplaced,
                  COUNT(DISTINCT CASE WHEN zone_auto IS NOT NULL THEN dedup_key END) AS distinct_inside
           FROM event""").fetchone()

    return {
        "place": place.as_dict(), "window": win, "zones": zones,
        "progress": store.get_meta(conn, "progress", {}),
        "totals": {k: total[k] or 0 for k in total.keys()},
        "sites": {"total": sum(sites.values()), **sites},
        "site_kinds": site_kinds, "platforms": platforms,
        "by_kind": dict(by_kind), "sources": sources, "categories": categories,
        "overlap": [{"a": a, "b": b, "a_name": names.get(a, a), "b_name": names.get(b, b), "n": n}
                    for (a, b), n in pairs.most_common(15)],
        "html_only": [dict(r) for r in conn.execute(
            """SELECT name, kind, url, note, minutes FROM site WHERE status='nur-html'
               ORDER BY minutes, n_objects DESC, name LIMIT 400""")],
    }


def _row(*cells) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def markdown(rep: dict, top: int = 40) -> str:
    p, t, s = rep["place"], rep["totals"], rep["sites"]
    w = rep["window"]
    out = [
        f"# Erhebung: {p['name']}", "",
        f"Startpunkt {p['display']} ({p['lat']:.4f}, {p['lon']:.4f}), Zeitzone {p['tz']}.",
        f"Fenster: {w.get('since')} bis {w.get('until')}. „In der Stunde\" heißt: in der "
        "äußersten gemessenen Autozone.", "",
        "## Ergebnis", "",
        _row("", "Anzahl"), _row("---", "---:"),
        _row("Termine eingesammelt", t["events"]),
        _row("davon in der Stunde (Auto)", t["inside"]),
        _row("davon in der Stunde (E-Bike)", t["inside_ebike"]),
        _row("verschiedene Termine in der Stunde (ohne Dubletten)", t["distinct_inside"]),
        _row("ohne verortbare Adresse", t["unplaced"]),
        _row("Quellen mit Terminen", sum(1 for x in rep["sources"] if x["events"])), "",
        "## Wie die Quellen gefunden wurden", "",
        f"OpenStreetMap kennt in der Stunde **{s['total']} Websites** von Häusern und Gemeinden. "
        f"Davon lassen sich **{s.get('feed', 0)}** maschinell nach Terminen fragen, "
        f"**{s.get('nur-html', 0)}** haben eine Programmseite nur für Menschen, "
        f"{s.get('nichts', 0)} zeigen gar kein Programm, {s.get('unerreichbar', 0)} waren nicht "
        f"erreichbar, {s.get('robots', 0)} verbieten den Abruf, "
        f"{s.get('uebersprungen', 0)} wurden übersprungen und {s.get('offen', 0)} sind noch ungeprüft.", "",
        _row("Art des Hauses", "Websites", "mit Feed", "nur HTML"), _row("---", "---:", "---:", "---:"),
        *(_row(k["kind"], k["websites"], k["feed"], k["nur_html"]) for k in rep["site_kinds"]), "",
        _row("Plattform", "Quellen", "mit Terminen", "Termine in der Stunde"),
        _row("---", "---:", "---:", "---:"),
        *(_row(k, v["sources"], v["with_events"], v["inside"])
          for k, v in sorted(rep["by_kind"].items(), key=lambda kv: -kv[1]["inside"])), "",
        "## Welche Quelle welche Termine führt", "",
        _row("Quelle", "Plattform", "Herkunft", "Termine", "in der Stunde", "nur hier", "Orte", "häufigste Kategorien"),
        _row("---", "---", "---", "---:", "---:", "---:", "---:", "---"),
    ]
    shown = [x for x in rep["sources"] if x["events"] or x["origin"] == "katalog"]
    for x in shown[:top]:
        cats = ", ".join(f"{c} {n}" for c, n in list(x["categories"].items())[:3])
        status = "" if x["status"] == "ok" else f" *({x['status']})*"
        out.append(_row(x["name"] + status, x["kind"], x["origin"], x["events"], x["inside"],
                        x["unique"], x["venues"], cats))
    if len(shown) > top:
        rest = shown[top:]
        out.append(_row(f"… {len(rest)} weitere", "", "", sum(x["events"] for x in rest),
                        sum(x["inside"] for x in rest), sum(x["unique"] for x in rest), "", ""))
    out += ["", "## Welche Kategorie woher kommt", "",
            _row("Kategorie", "Termine", "Quellen", "die größten drei"),
            _row("---", "---:", "---:", "---")]
    for c in rep["categories"]:
        out.append(_row(c["category"], c["events"], c["sources"],
                        ", ".join(f"{x['name']} ({x['n']})" for x in c["top"])))
    if rep["overlap"]:
        out += ["", "## Überschneidungen", "",
                "Derselbe Termin in zwei Quellen — gleicher Tag, gleicher Titelanfang, gleicher Ort. "
                "Eine Näherung, die eher zu wenig findet als zu viel.", "",
                _row("Quelle A", "Quelle B", "gemeinsame Termine"), _row("---", "---", "---:")]
        out += [_row(o["a_name"], o["b_name"], o["n"]) for o in rep["overlap"]]
    failed = [x for x in rep["sources"] if x["status"] == "fehler"]
    if failed:
        out += ["", "## Quellen mit Fehler", ""]
        out += [f"- {x['name']} ({x['kind']}): {x['error']}" for x in failed[:30]]
    out += ["", "## Zonen", "",
            _row("Profil", "Minuten", "gerechnet", "Graph"), _row("---", "---:", "---", "---"),
            *(_row(z["profile"], z["minutes"], z["computed_at"], z["graph"]) for z in rep["zones"]), ""]
    return "\n".join(out)

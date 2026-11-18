"""urbanify — command line.

    urbanify survey "Berlin"            alles, von der Ortssuche bis zum Bericht
    urbanify report berlin              der Bericht als Markdown
    urbanify places                     was schon erhoben ist

Die Schritte einzeln, wenn einer wiederholt werden soll:

    urbanify zones berlin | discover berlin | probe berlin | harvest berlin | locate berlin

Das Eigene:

    urbanify marks berlin               Vorgemerktes, und was davon ins Leere zeigt
    urbanify rules                      rules.yaml spiegeln, Regeln zeigen
    urbanify reclassify berlin          nach einer Änderung an categories.py
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time

import httpx

from . import bookmarks, personal, queries, report, rules, store, survey


def _progress(text: str) -> None:
    print(time.strftime("%H:%M:%S"), text, flush=True)


def _fail(text: str) -> int:
    print(text, file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    """Fehler der Dienste sind erwartbar und enden in einem Satz, nicht im Traceback."""
    try:
        return _main(argv)
    except survey.StepFailed as exc:
        rest = survey.STEPS[survey.STEPS.index(exc.step):]
        return _fail(
            f"\nDer Schritt „{exc.step}“ ist gescheitert: {exc.cause}\n"
            "Die öffentlichen Dienste (Valhalla, Overpass, Nominatim) sind geteilt und "
            "antworten gelegentlich nicht. Was bis hierher erhoben wurde, ist gespeichert.\n"
            "Später fortsetzen, Schritt für Schritt:\n" +
            "".join(f"    urbanify {s} {exc.slug}\n" for s in rest) +
            f"    urbanify report {exc.slug}")
    except LookupError as exc:
        return _fail(str(exc))
    except (RuntimeError, httpx.HTTPError) as exc:
        return _fail(f"Gescheitert: {exc}\nDie öffentlichen Dienste antworten gelegentlich "
                     "nicht — denselben Befehl später noch einmal ausführen.")


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="urbanify", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("survey", help="eine Stadt vollständig erheben")
    s.add_argument("query", help='Ortsname, z. B. "Berlin" oder "Achern, Ortenaukreis"')
    s.add_argument("--days", type=int, help="Fenster in Tagen (Vorgabe 60)")
    s.add_argument("--max-sites", type=int, help="höchstens so viele Websites prüfen")
    s.add_argument("--geocode-limit", type=int, default=400)

    for name, text in (("zones", "Isochronen neu rechnen"),
                       ("discover", "Katalog und OSM-Websites einsammeln"),
                       ("probe", "Websites auf Plattformen prüfen"),
                       ("harvest", "Termine abholen"),
                       ("locate", "Geocoder und Zonen"),
                       ("report", "Bericht ausgeben"),
                       ("reclassify", "Kategorien und Kennzeichen aus dem Bestand neu ableiten"),
                       ("marks", "Vorgemerktes, und was davon ins Leere zeigt")):
        c = sub.add_parser(name, help=text)
        c.add_argument("slug")
        if name == "probe":
            c.add_argument("--max-sites", type=int)
            c.add_argument("--per-host", type=int, default=12)
            c.add_argument("--again", action="store_true", help="Unerreichbare noch einmal")
        if name == "harvest":
            c.add_argument("--days", type=int)
            c.add_argument("--only", help="nur Quellen, deren Slug das enthält")
        if name == "locate":
            c.add_argument("--geocode-limit", type=int, default=400)
        if name == "report":
            c.add_argument("--json", action="store_true")
            c.add_argument("--top", type=int, default=40)

    sub.add_parser("places", help="erhobene Orte")
    sub.add_parser("rules", help="rules.yaml in die eigenen Regeln spiegeln und sie zeigen")
    args = ap.parse_args(argv)

    if args.cmd == "rules":
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        personal.attach(conn)
        n = rules.sync_from_yaml(conn)
        print(f"{n} aus {rules.rules_file()}" if n else f"keine Datei {rules.rules_file()}")
        for r in rules.load(conn, include_disabled=True):
            print(f"  {'+' if r.kind == 'white' else '-'}{r.weight:g} {r.field} {r.matcher} "
                  f"„{r.pattern}“{'' if r.enabled else ' (aus)'}")
        return 0

    if args.cmd == "places":
        for slug in store.places():
            print(slug)
        return 0

    if args.cmd == "survey":
        slug = survey.run(args.query, _progress, days=args.days, max_sites=args.max_sites,
                          geocode_limit=args.geocode_limit)
        print(report.markdown(report.build(store.connect(slug))))
        return 0

    try:
        conn = store.connect(args.slug)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.cmd == "zones":
        print(survey.measure(conn, _progress))
    elif args.cmd == "discover":
        print(survey.discover(conn, _progress))
    elif args.cmd == "probe":
        print(survey.probe_sites(conn, _progress, max_sites=args.max_sites,
                                 per_host=args.per_host, again=args.again))
    elif args.cmd == "harvest":
        print(survey.harvest(conn, _progress, days=args.days, only=args.only))
    elif args.cmd == "locate":
        print(survey.assign(conn, _progress, geocode_limit=args.geocode_limit))
    elif args.cmd == "reclassify":
        print(f"{store.reclassify(conn)} Termine neu zugeordnet")
    elif args.cmd == "marks":
        for e in queries.fetch_events(conn, bookmarked_only=True, require_zone=False):
            print(f"  ☆ {e['starts_at'][:16]} {e['title']} — {e['venue'] or '?'}")
        for b in bookmarks.orphans(conn, args.slug):
            hint = f" → vielleicht {b['candidate']['starts_at'][:16]}" if b["candidate"] else ""
            print(f"  ? {(b['starts_at'] or '?')[:16]} {b['title']} (nicht mehr im Bestand){hint}")
    elif args.cmd == "report":
        rep = report.build(conn)
        print(json.dumps(rep, ensure_ascii=False, indent=1) if args.json
              else report.markdown(rep, top=args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

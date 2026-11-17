"""urbanify — command line.

    urbanify survey "Berlin"            alles, von der Ortssuche bis zum Bericht
    urbanify report berlin              der Bericht als Markdown
    urbanify places                     was schon erhoben ist

Die Schritte einzeln, wenn einer wiederholt werden soll:

    urbanify zones berlin | discover berlin | probe berlin | harvest berlin | locate berlin
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import httpx

from . import report, store, survey


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
                       ("report", "Bericht ausgeben")):
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
    args = ap.parse_args(argv)

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
    elif args.cmd == "report":
        rep = report.build(conn)
        print(json.dumps(rep, ensure_ascii=False, indent=1) if args.json
              else report.markdown(rep, top=args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

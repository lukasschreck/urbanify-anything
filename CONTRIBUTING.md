# Mitmachen

Das Werkzeug ist klein und soll klein bleiben. Was es braucht, ist nicht mehr Oberfläche,
sondern mehr Plattformen, die es lesen kann.

## Aufsetzen

```bash
uv sync
uv run pytest tests -q
```

Die Tests laufen ohne Netz und müssen das bleiben. Jeder Parser wird gegen eine kleine, echte
Form seiner Plattform geprüft, die als String im Test steht — kein `requests_mock`, keine
Fixtures auf der Platte, keine Live-Abfrage in CI.

Was Netz braucht, prüft man von Hand und schreibt das Ergebnis in die Beschreibung des
Pull Requests:

```bash
uv run urbanify survey "Deine Stadt"
uv run urbanify probe <slug> --max-sites 50   # begrenzt, zum Nachsehen
uv run urbanify report <slug>
```

## Der nützlichste Beitrag: ein Plattform-Adapter

`urbanify report <slug>` endet mit einer Liste von Häusern, die eine Programmseite haben, aber
nichts Maschinenlesbares (`nur-html`). Das ist die Arbeitsliste. Nützlich ist ein Adapter für
die Plattform, die darin am häufigsten vorkommt — nicht für ein einzelnes Haus.

So geht es:

1. In der Liste nachsehen, welche Plattform mehrfach vorkommt. `site.platform` hält, was die
   Seite über sich verrät (`<meta name="generator">` und Ähnliches).
2. Erkennung in `probe.py` ergänzen: woran man die Plattform sieht, und welche URL man fragt.
   `probe.Finding.best` entscheidet die Rangfolge, wenn eine Seite mehrere Feeds anbietet.
3. Den Parser als neues Modul unter `src/urbanify/platforms/` anlegen. Er bekommt den Rohtext
   und die Zeitzone des Ortes und gibt Dicts zurück; welche Felder, zeigt
   `platforms/tribe.py` am kürzesten.
4. In `survey._harvest_all` einhängen.
5. Einen Test in `tests/test_platforms.py` dazu, mit einem echten, aber gekürzten Stück Antwort.

Drei Dinge, die dabei regelmäßig schiefgehen und die im Review auffallen:

- **Zeitzonen.** Alles geht durch `platforms.common.local_iso` und landet als lokale Zeit des
  Ortes. Ein `Z` aus dem Feed ist nicht die Ortszeit.
- **Seitenweise abholen.** Maßgeblich ist das Gesamtzahl-Feld der API, nie die Länge der
  Antwort.
- **Serien.** Eine Wiederholungsregel wird nur im Fenster aufgefaltet, und was denselben Titel
  am selben Ort zur selben Zeit hat, ist ein Termin, kein zweiter.

## Ein Katalog-Adapter

Für Sammelstellen, die an keinem einzelnen Haus hängen: eine Funktion in `catalog.py`, in
`ADAPTERS` eingetragen, und ein Eintrag in der eigenen `catalog.yaml`. Der Adapter gehört ins
Repo, die Quellenliste **nicht** — `catalog.yaml` ist nicht versioniert. Wer einen Adapter
beiträgt, dokumentiert in `catalog.example.yaml`, welche Felder sein `kind` erwartet.

Jeder Eintrag sagt über `coverage` selbst, wo er zuständig ist. Niemals ein Städtename in einer
Bedingung.

## Was abgelehnt wird

- **Ein Stadtname im Code.** In keiner Signatur, Bedingung oder Vorgabe. Der Ort ist eine
  Eingabe. Ein Katalog-Adapter darf die Plattform eines bestimmten Portals kennen; wo er gilt,
  sagt der Katalogeintrag.
- **Ein Luftlinienradius.** Zonen kommen aus Valhalla. Wer rechnen will, ob etwas „in der Stunde"
  liegt, nimmt das Polygon.
- **Unhöfliches Abfragen.** Kein vorgetäuschtes Browserkennzeichen, kein Umgehen von
  `robots.txt`, keine Abkürzung am Sekundentakt je Host vorbei. `web.Polite` ist der einzige Weg zu
  fremden Websites, und das ist Absicht — dort sitzen auch die Sperre für nicht öffentliche
  Adressen und die Größengrenze. Nur die Dienste mit eigener API (Nominatim, Overpass, Valhalla)
  werden direkt gefragt.
- **Eine Quellenliste.** Siehe oben.
- **Filtern beim Einlesen.** Regeln und Urteile wirken bei der Abfrage (`queries.fetch_events`),
  damit jede Entscheidung umkehrbar bleibt. Gespeichert wird alles.
- **Etwas Persönliches an `event.id`.** Lesezeichen und Urteile hängen an `event_key` und
  `series_key`; die Nummer überlebt keine neue Erhebung.
- **Konten, Teilen, ein gehosteter Betrieb.** Das Werkzeug ist für eine Person an ihrem Rechner.

## Stil

Doku und Commits auf Deutsch, Code und Identifier auf Englisch. Zeilen bis 100 Zeichen. Ein
Kommentar erklärt, *warum* etwas so ist — meist, weil es anders einmal falsch war. In CI
läuft kein Linter; der Code sieht aus wie der Code, der schon da ist. Die `noqa`-Kommentare
sind für ruff, falls du es lokal benutzt.

## Lizenz

Beiträge stehen unter MIT, wie das Repo (`LICENSE`). Es gibt kein CLA.

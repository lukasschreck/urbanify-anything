# Arbeiten in diesem Repo

Über eine Stadt ist hier **nichts bekannt**: man nennt einen Ort, die Stunde drumherum wird
gemessen, und welche Quellen dort Termine führen, findet die Erhebung selbst heraus. Aufbau und
Befehle stehen in der `README.md`, ein durchgerechnetes Beispiel in `docs/showcase-achern.md`.

## Die Dinge, die man leicht falsch macht

**Kein Stadtname im Code.** Weder in einer Signatur noch in einer Bedingung noch in einem
Vorgabewert. Was nur für eine Region gilt, steht im Katalog und sagt dort selbst, wo es zuständig
ist — als Fläche. Ob ein Katalogeintrag gilt, entscheidet der Schnitt mit der gemessenen Stunde
(`catalog.applies`), nicht ein Namensvergleich: das Portal eines Landes gilt auch für den
Nachbarort jenseits der Grenze. Ein Katalog-Adapter darf die Plattform eines bestimmten Portals
kennen (`kulturdaten`, `simplesearch`) — aber nie, wo es liegt.

**Der Katalog ist Daten, nicht Code.** `src/urbanify/catalog.yaml` ist nicht versioniert.
Fehlt sie, ist der Katalog leer und die Erhebung läuft trotzdem vollständig — allein mit dem, was
OpenStreetMap kennt. Niemals eine Quellenliste ins Repo schreiben; Format und Platz dafür stehen
in `catalog.example.yaml`.

**Der Luftlinienradius ist der Feind.** Zonen kommen aus Valhalla, immer. Das gilt auch für
„welche Häuser liegen drin": Overpass wird mit der Bounding-Box gefragt, aber gezählt wird, was
im Polygon liegt (`osm.candidates`).

**Adapter hängen an Plattformen, nicht an Häusern.** `tribe`, `ics`, `jsonld`, `crawl` — eine
neue Stadt braucht keine Zeile Code. Wer für ein einzelnes Haus einen Adapter schreiben will,
fragt erst, welche Plattform dahintersteckt und wie viele Häuser in `nur-html` sie noch benutzen
(`site.platform`).

**Der Ingest filtert nie nach Ort.** Ein Termin außerhalb der Stunde wird gespeichert und bekommt
keine Zone. Überregionale Quellen und ICS-Feeds führen Termine weit weg; dass sie nicht zählen,
entscheidet der Bericht.

**Eine kurze Seite ist nicht das Ende der Liste.** Maßgeblich ist das Gesamtzahl-Feld der API
(`total_pages` bei Tribe, `totalCount` bei anderen), nie die Länge der Antwort.

**Die Zonen sind leise, die Termine laut.** Die Entfernung bekommt eine kühle, nach außen
abnehmende Hue-Familie (`--zone1/2/3`), alles, was aus der Karte heraustreten muss, bekommt
Terracotta (`--accent`). Andersherum — bunte Zonen, in denen die Termine untergehen — war es
einmal, und auf der Karte war dann der Zonenrand das Lauteste. Farben stehen in `web/app.css`;
`web/app.js` liest dieselben Token über `css()`, damit Oberfläche und Karte nicht auseinander-
laufen und der Dunkelmodus mitkommt. Keine Hex-Werte in die Kartenebenen schreiben.

**Der Geocoder findet immer etwas.** Darum fragt `geocode.fill` mit `bounded=1` in der Box der
Stunde, und ein Fehlschlag wird als Fehlschlag gemerkt. Ein Termin ohne Ort ist `fehlt`, nicht
irgendwo.

**Ein Termin an der Website eines Hauses steht am Haus.** Nennt die Quelle keinen eigenen Ort,
bekommt der Termin die OSM-Koordinate der Fundstelle (`geo='ort'`). Das spart den Geocoder für
fast alles, was über OSM gefunden wird — und ist falsch, wenn ein Haus Gastspiele anderswo
ankündigt, ohne den Ort maschinenlesbar zu nennen.

**Die Dienste fallen aus, und das ist normal.** Overpass antwortet gelegentlich mit 429 oder
504. `survey.run` meldet dann `StepFailed` mit Ort und Schritt, die CLI nennt die Befehle zum
Fortsetzen. Nicht mit mehr Wiederholungen oder kürzeren Pausen „reparieren“ — der Dienst ist
geteilt.

**Der Export einer einzelnen Seite ist kein Kalender.** `…/konzert-x?format=ical` liefert einen
Termin. `probe.read_page` wirft ICS-Links weg, die auf die eigene Seite zeigen; viele ICS-Links
auf einer Seite sind ebenfalls Einzeltermine.

**Die Frist beim Prüfen läuft erst, wenn die Website dran ist.** `asyncio.wait_for` um eine
Aufgabe, die noch auf ihren Platz wartet, läuft in der Warteschlange ab — dann sind zweitausend
Websites „unerreichbar", ohne dass eine gefragt wurde. Darum das `gate` in `survey._probe_all`.

**Höflich abfragen.** Ein Request pro Sekunde *je Host*, robots.txt und Crawl-delay gelten
(`web.Polite`). Kein vorgetäuschtes Browserkennzeichen. Die öffentlichen Dienste (Valhalla des
FOSSGIS, Nominatim, Overpass) sind für gelegentliche Erhebungen in Ordnung; wer das im
Dauerbetrieb oder für viele Städte laufen lässt, stellt eigene Instanzen hin
(`URBANIFY_VALHALLA`, `URBANIFY_NOMINATIM`, `URBANIFY_OVERPASS`) und setzt `URBANIFY_CONTACT`.

**Fremde Websites sind nicht vertrauenswürdig.** `web.Polite` ruft keine Adresse ab, die nicht
öffentlich ist (auch nicht nach einer Weiterleitung), und liest höchstens `MAX_BYTES`. Eine
Termin-URL wird nur gespeichert, wenn sie http(s) ist (`store.web_url`). Beides nicht umgehen.

**Die Dublettenerkennung ist eine Näherung.** Gleicher Tag, gleicher Titelanfang, gleiche
Kilometerzelle. Sie findet eher zu wenig. Wer aus „nur hier" eine Aussage über eine Quelle
ableitet, liest erst `store.dedup_key`.

**Das ist kein Dienst.** Lokales Werkzeug ohne Anmeldung. Für die über OSM gefundenen Websites
ist die Lizenzlage ungeklärt — die Erhebung zeigt, *dass* dort Termine maschinenlesbar stehen,
nicht, dass man sie weiterverbreiten darf.

## Sprache

Doku und Commits auf Deutsch, Code und Identifier auf Englisch. `category_raw` behält das
Original der Quelle. `categories.py` kennt bisher deutsche Schlagwörter — in einer französischen
Stadt landet fast alles in `sonstiges`.

## Verifying your work

```bash
uv run pytest tests -q                       # ohne Netz
uv run urbanify probe <slug> --max-sites 50  # die Erkennung an echten Websites, begrenzt
uv run urbanify report <slug>                # der Befund
```

Die Karte prüft man im Browser. Ein eingebetteter Browser-Pane rendert WebGL nur, wenn er
sichtbar ist.

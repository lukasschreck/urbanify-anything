# urbanify-anything

**English:** Name any city. The tool measures the real 15/30/60-minute travel zones around it
(car and e-bike, via Valhalla — not a radius), finds every venue with a website inside the hour
(OpenStreetMap), checks which of those websites publish machine-readable event calendars, and
shows the result on an interactive map. Local tool, MIT. Full English guide:
**[README.en.md](README.en.md)**.

---

Eine beliebige Stadt, die Stunde drumherum, und welche Quellen dort Termine führen.

## Warum es das gibt

Mein letzter Besuch in Berlin war wie ein Upgrade fürs Gehirn. Ich wohne in Achern, und mit
zwei Kindern sind kurze Wege im Alltag mit das Wichtigste. Überrascht hat mich in Berlin, dass
es dort völlig normal schien, für eine Veranstaltung vierzig Minuten ans andere Ende der Stadt
zu fahren.

Von Achern aus komme ich in denselben vierzig Minuten nach Karlsruhe, nach Straßburg oder fast
nach Freiburg — drei Städte mit einem breiten Angebot an Kultur, Musik und Kinderprogramm. Die
Reichweite ist also da. Sie ist nur unsichtbar, weil niemand sie für seinen Ort ausrechnet.

Dieses Werkzeug rechnet sie aus, für jede beliebige Stadt: das Veranstaltungsprogramm in drei
tatsächlichen Bewegungszonen — 15, 30 und 60 Minuten, mit dem Auto oder dem E-Bike — auf einer
interaktiven Karte.

## Was es tut

Man nennt eine Stadt. Was eine Stunde entfernt liegt, wird gemessen statt geschätzt. Welche
Häuser darin stehen, weiß OpenStreetMap. Und welche davon einen maschinenlesbaren
Terminkalender führen, probiert die Erhebung selbst aus — eine Website nach der anderen,
höflich, im Sekundentakt.

Was dabei herauskommt, ist mehr als ein Veranstaltungskalender. Es ist auch ein Befund: wie
viele Häuser in einer Stunde um einen Ort herum Programm machen, wie viele davon sich maschinell
fragen lassen, und wie viele ihr Programm nur für Menschen aufschreiben.

Der Ort ist eine Eingabe. Keine Stadt steht in einer Signatur, einer Bedingung oder einem
Vorgabewert; was nur für eine Region gilt, steht im Katalog (siehe unten).

**Was es nicht tut:** Vormerken, eigene Vorlieben, Konten. Das hier ist die Erhebung und die
Karte dazu, kein persönlicher Kalender.

## Ein Beispiel

![Die gemessene Stunde um Achern: 15/30/60 Minuten mit dem Auto, gestrichelt die E-Bike-Stunde,
in Terracotta die Termine](docs/bilder/achern.jpg)

Achern, 25.000 Einwohner, Rheinebene zwischen Schwarzwald und Elsass. Die gemessene Stunde
reicht von Karlsruhe bis Freiburg und weit nach Frankreich hinein — 829 Häuser mit Website
liegen darin, 132 davon französisch. 79 lassen sich maschinell nach Terminen fragen, 426 haben
ein Programm nur für Menschen. Und 1,6 Prozent der Termine sind mit dem E-Bike erreichbar.

Gefunden ohne jede Vorkenntnis und ohne einen einzigen eingetragenen Quellen-Eintrag, in 18
Minuten. Der ganze Befund, mit dem Vergleich zu Berlin: **[docs/showcase-achern.md](docs/showcase-achern.md)**.

## Anfangen

```bash
uv sync
uv run urbanify survey "Leipzig"
uv run uvicorn urbanify.main:app --port 8090
```

Dann <http://localhost:8090>: Stadt eingeben, zusehen, lesen. Eine Erhebung dauert je nach Stadt
zwanzig Minuten bis eine Stunde — die meiste Zeit davon wartet sie absichtlich. Zum Ausprobieren
geht es schneller mit `--max-sites 50`.

Gebraucht werden Python 3.12 oder neuer und [uv](https://docs.astral.sh/uv/). Kein API-Schlüssel,
kein Konto, kein Docker.

### Mit einem Coding-Agenten

Das Repo ist dafür gebaut, dass man es einem Agenten wie Claude Code übergibt: „Klone
`lukasschreck/urbanify-anything` und erhebe meine Stadt.“ Was man hier leicht falsch macht,
steht für ihn in [`CLAUDE.md`](CLAUDE.md), wie ein Beitrag aussieht in
[`CONTRIBUTING.md`](CONTRIBUTING.md). Bevor er loslegt: `URBANIFY_CONTACT` in `.env` setzen
und den Abschnitt [Verantwortung](#verantwortung) lesen — die Abfragen laufen in deinem Namen.

### Wenn es hakt

| Was man sieht | Was los ist | Was hilft |
| --- | --- | --- |
| „Der Schritt ‚discover‘ ist gescheitert … 429/504“ | Overpass ist ein geteilter Dienst und gelegentlich überlastet | ein paar Minuten warten, dann die genannten Befehle ausführen — der Stand ist gespeichert |
| „Der Schritt ‚zones‘ ist gescheitert“ | die öffentliche Valhalla-Instanz antwortet nicht | später `urbanify zones <slug>`, oder eine eigene Instanz über `URBANIFY_VALHALLA` |
| „Nominatim kennt keinen Ort namens …“ | der Name ist nicht eindeutig oder falsch geschrieben | genauer werden: `"Achern, Ortenaukreis"` |
| viele Websites `unerreichbar` | Zeitüberschreitungen, meist vorübergehend | `urbanify probe <slug> --again` |
| die Karte bleibt leer | noch keine Termine verortet, oder der Browser blockiert WebGL | `urbanify report <slug>` zeigt, ob Termine da sind |

## Was eine Erhebung tut

| Schritt | Dienst | Ergebnis |
| --- | --- | --- |
| `place` | Nominatim | Name → Startpunkt, Land, Zeitzone |
| `zones` | Valhalla | gemessene 15/30/60 Minuten, Auto und E-Bike |
| `discover` | Overpass (+ Katalog) | jede Website eines Hauses in der Stunde |
| `probe` | die Websites selbst | welche Plattform antwortet: `tribe`, `ics`, `jsonld`, `crawl` — oder `nur-html` |
| `harvest` | die Feeds | Termine im Fenster (Vorgabe 60 Tage) |
| `locate` | Nominatim | Koordinaten, wo die Quelle keine nennt; Zone je Termin |

Jeder Schritt lässt sich einzeln wiederholen (`urbanify probe leipzig`, `urbanify harvest leipzig
--only stadt`, …). Je Ort entsteht eine Datei `data/<slug>/urbanify.sqlite`; einen Ort entfernen
heißt, sein Verzeichnis löschen.

## Wie die Quellen gefunden werden

Niemand muss die Szene einer Stadt kennen. OpenStreetMap kennt Theater, Clubs, Museen, Galerien,
Kinos, Bibliotheken, Gemeindezentren, Hackspaces und Rathäuser, und viele tragen eine Website.
Jede davon wird einmal besucht:

- **tribe** — WordPress mit The Events Calendar, offene REST-API
- **ics** — ein Kalender-Feed, von der Seite verlinkt
- **jsonld** — `schema.org/Event` in der Programmseite
- **crawl** — dasselbe, aber nur auf den Einzelseiten; die Programmseite ist die Linkliste
- **nur-html** — es gibt eine Programmseite, aber nichts Maschinenlesbares

Diese letzte Liste ist das Interessanteste am ganzen Werkzeug. Sie ist die Arbeitsliste: Häuser,
die ihr Programm veröffentlichen, aber so, dass es niemand weiterverwenden kann. Wer einen neuen
Adapter schreiben will, sucht hier die Plattform, die am häufigsten darin vorkommt.

Adapter hängen an Plattformen, nicht an Häusern — und nicht an Städten. Eine neue Stadt braucht
keine Zeile Code.

## Der Katalog

Manches findet man über kein einzelnes Haus: ein Landesportal, ein offenes Register, ein Netzwerk
selbstorganisierter Räume. Dafür gibt es den Katalog — eine YAML-Datei, die *nicht* im Repo
liegt, weil sie Daten sind und nicht Werkzeug:

```bash
cp src/urbanify/catalog.example.yaml src/urbanify/catalog.yaml
```

Ohne diese Datei läuft eine Erhebung vollständig, nur eben allein mit dem, was OpenStreetMap
kennt. Das ist der Normalfall und kein Mangel.

Jeder Eintrag sagt selbst, wo er zuständig ist — als Fläche, nicht als Städtename. Ob er für
eine Stadt gilt, entscheidet der Schnitt dieser Fläche mit der gemessenen Stunde. Ein
Landesportal gilt darum auch für den Nachbarort jenseits der Grenze, wenn dessen Stunde ins Land
hineinreicht. Das Format steht in `catalog.example.yaml`.

Drei Adapterarten sind mitgeliefert, als Beispiele dafür, wie ein Portal angeschlossen wird:

| `kind` | Wofür | Was der Eintrag braucht |
| --- | --- | --- |
| `radar` | radar.squat.net, weltweit | `endpoint`; gefragt wird mit dem Namen des Ortes |
| `kulturdaten` | die API von kulturdaten.berlin | `endpoint`, `city` als Rückfall für Termine ohne Ort |
| `simplesearch` | „SimpleSearch“-Tabellen von berlin.de | `endpoint` (JSON-Export), `city` |
| `none` | noch kein Adapter | steht im Bericht als „zuständig, aber nicht angeschlossen“ |

Die beiden letzten Adapter kennen die Plattform eines bestimmten Portals. Wo sie gelten, sagt
trotzdem der Katalogeintrag mit seiner Fläche, nicht der Code.

## Der Bericht

`urbanify report <slug>` und die Oberfläche zeigen dasselbe: je Quelle, wie viele Termine sie
führt, wie viele davon in der Stunde liegen, wie viele es *nur dort* gibt, an wie vielen Orten
und in welchen Kategorien — dazu, welche Quellen sich überschneiden und welche Häuser ein
Programm nur für Menschen haben.

Die Dublettenerkennung ist eine Näherung: gleicher Tag, gleicher Titelanfang, gleiche
Kilometerzelle. Sie findet eher zu wenig. Wer aus „nur hier" eine Aussage über eine Quelle
ableiten will, liest vorher `store.dedup_key`.

## Einstellungen

| Variable | Vorgabe | |
| --- | --- | --- |
| `URBANIFY_VALHALLA` | `https://valhalla1.openstreetmap.de` | öffentliche FOSSGIS-Instanz, weltweit, mit Höhendaten |
| `URBANIFY_NOMINATIM` | `https://nominatim.openstreetmap.org` | |
| `URBANIFY_OVERPASS` | `https://overpass-api.de/api/interpreter` | |
| `URBANIFY_CONTACT` | leer | Kontakt im User-Agent; für alles jenseits eines Versuchs setzen |
| `URBANIFY_CATALOG` | leer | eigene Quellenliste, wenn sie nicht neben dem Modul liegt |
| `URBANIFY_DAYS` | `60` | Fenster |
| `URBANIFY_DELAY` | `1.0` | Sekunden je Host |
| `URBANIFY_CONCURRENCY` | `24` | Hosts gleichzeitig |
| `URBANIFY_DATA` | `./data` | |
| `URBANIFY_ALLOW_PRIVATE` | aus | `1` erlaubt Abrufe in nicht öffentliche Netze — nur für einen Katalog-Endpunkt im eigenen Netz |

Vorlage: `.env.example`. Eine `.env` im Wurzelverzeichnis des Repos wird beim Start gelesen; was
schon in der Umgebung steht, hat Vorrang.

## Höflichkeit, und was das Werkzeug nicht darf

Eine Erhebung besucht einige hundert bis einige tausend fremde Websites. Darum:

- Ein Request pro Sekunde **je Host**, wie viele Hosts auch parallel laufen.
- `robots.txt` wird gelesen und befolgt, `Crawl-delay` eingehalten.
- Der User-Agent sagt die Wahrheit. Kein vorgetäuschtes Browserkennzeichen.
- Die öffentlichen Dienste (Valhalla des FOSSGIS, Nominatim, Overpass) sind für gelegentliche
  Erhebungen gedacht. Wer regelmäßig oder für viele Städte erhebt, stellt eigene Instanzen hin
  und setzt `URBANIFY_CONTACT`.

Und die unbequeme Hälfte: **dass Termine irgendwo maschinenlesbar stehen, heißt nicht, dass man
sie weiterverbreiten darf.** Für die über OpenStreetMap gefundenen Websites ist die Lizenzlage
ungeklärt — je Haus, je Land. Die Erhebung zeigt, *dass* dort etwas steht. Was man damit tun
darf, muss man selbst klären, bevor man es veröffentlicht. Der Katalog hat darum je Eintrag ein
Feld `license`, und es gehört ausgefüllt.

Das hier ist ein lokales Werkzeug ohne Anmeldung und ohne Mandantentrennung. Es ist nicht dafür
gebaut, öffentlich zu stehen.

Zwei Schutzvorkehrungen gegen das, was eine fremde Website mit der Erhebung anstellen könnte:
Adressen, die nicht öffentlich sind (localhost, private Netze, Metadaten-Dienste), werden nicht
abgerufen — auch nicht über eine Weiterleitung —, und keine Antwort wird über 3 MB hinaus
gelesen.

## Verantwortung

**Wer dieses Werkzeug laufen lässt, fragt in eigenem Namen und auf eigene Verantwortung ab.**
Das Repo liefert Code, keinen Dienst und keine Erlaubnis. Konkret heißt das:

- Jede Abfrage geht von deinem Rechner und deiner Adresse aus. Ob du die Websites einer Region
  automatisiert besuchen darfst — Nutzungsbedingungen der Häuser, Urheber- und
  Datenbankrecht, Datenschutz, das Recht deines Landes —, klärst du selbst. `robots.txt` zu
  befolgen ist Höflichkeit, keine Rechtsgrundlage.
- Die öffentlichen Dienste haben eigene Regeln, und sie gelten für dich, nicht für dieses
  Projekt: die [Nominatim Usage Policy](https://operations.osmfoundation.org/policies/nominatim/),
  die Bedingungen von [Overpass](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html)
  und die der FOSSGIS-Instanz von Valhalla. Nominatim verlangt einen Kontakt im User-Agent —
  darum `URBANIFY_CONTACT`. Ohne ihn warnt das Werkzeug bei jeder Erhebung.
- Was du mit den eingesammelten Terminen tust, insbesondere sie zu veröffentlichen, ist deine
  Entscheidung und deine Haftung (siehe oben: maschinenlesbar heißt nicht frei).
- Die Autoren übernehmen keine Verantwortung dafür, wie Klone und Abwandlungen eingesetzt
  werden. Das steht so auch in der MIT-Lizenz („as is“, ohne Gewähr).

## Daten und Nennung

Fundstellen, Zonen und Karte stammen aus [OpenStreetMap](https://www.openstreetmap.org/copyright):
© OpenStreetMap-Mitwirkende, lizenziert unter der ODbL. Das gilt auch für die Zahlen und das
Bild im Showcase. Wer Ergebnisse einer Erhebung veröffentlicht, nennt OpenStreetMap ebenso.
Die Zonen rechnet Valhalla, die Kartenkacheln liefert OpenFreeMap.

## Was noch fehlt

- **ÖPNV als Profil.** Für eine Großstadt ist die Auto-Stunde die falsche Stunde; die
  öffentliche Valhalla-Instanz hat keine Fahrplandaten.
- **Kategorien in anderen Sprachen als Deutsch.** `categories.py` arbeitet mit deutschen
  Schlagwörtern — in einer französischen Stadt landet fast alles in `sonstiges`. Das Rohwort der
  Quelle bleibt in `category_raw` erhalten, die Zuordnung ist also nachholbar.
- **Adapter für die häufigsten Plattformen unter `nur-html`.** Siehe oben: das ist die
  Arbeitsliste.
- **Feeds, die sich nur in einer Sitzungskennung unterscheiden,** zählen als mehrere Quellen
  (Beispiel im Showcase). Die Dublettenerkennung fängt die Termine ab, die Quellenzahl nicht.
- **Vormerken und eigene Vorlieben.** Gibt es hier nicht.

## Mitmachen

`CONTRIBUTING.md`. Kurz: Tests laufen ohne Netz, Doku auf Deutsch, Code auf Englisch, und keine
Stadt in Signatur, Bedingung oder Vorgabe.

## Lizenz

MIT, siehe `LICENSE`. Die Daten, die das Werkzeug einsammelt, sind davon nicht berührt — die
gehören denen, von deren Websites sie kommen.

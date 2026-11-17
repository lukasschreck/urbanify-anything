# Showcase: Achern

Achern hat 25.000 Einwohner und liegt in der Rheinebene zwischen Schwarzwald und Elsass. Es ist
der uninteressanteste denkbare Startpunkt, und genau darum steht er hier: eine Großstadt findet
immer etwas. Die Frage ist, was eine Kleinstadt findet.

Erhoben am 18. November 2026, Fenster 60 Tage, **ohne jeden Katalogeintrag** — alles, was hier
steht, hat die Erhebung über OpenStreetMap selbst gefunden. Dauer: 18 Minuten, davon 14 fürs
Prüfen der Websites.

![Die gemessene Stunde um Achern: 15/30/60 Minuten mit dem Auto, gestrichelt die E-Bike-Stunde,
in Terracotta die Termine](bilder/achern.jpg)

*Kartendaten und Fundstellen: © OpenStreetMap-Mitwirkende (ODbL). Kacheln: OpenFreeMap.*

Die zackige Form ist der Punkt. Ein Kreis um Achern wäre falsch: die Autobahn zieht die Stunde
nach Norden bis Karlsruhe und nach Süden bis Freiburg, der Schwarzwald schneidet sie nach Osten
ab, und nach Westen läuft sie ungehindert ins Elsass. Gemessen, nicht geschätzt.

## Der Befund

|  | Anzahl |
| --- | ---: |
| Termine eingesammelt | 2113 |
| davon in der Stunde (Auto) | 1991 |
| davon in der Stunde (E-Bike) | 32 |
| verschiedene Termine in der Stunde (ohne Dubletten) | 1538 |
| ohne verortbare Adresse | 116 |
| Quellen mit Terminen | 66 |

## Wie die Quellen gefunden wurden

OpenStreetMap kennt in der Stunde **829 Websites** von Häusern und Gemeinden. Davon lassen sich
**79** maschinell nach Terminen fragen, **426** haben eine Programmseite nur für Menschen, 206
zeigen gar kein Programm, 82 waren nicht erreichbar, 36 verbieten den Abruf.

| Art des Hauses | Websites | mit Feed | nur HTML |
| --- | ---: | ---: | ---: |
| Museum | 170 | 20 | 90 |
| Gemeindezentrum | 170 | 16 | 86 |
| Bibliothek | 96 | 4 | 54 |
| Gemeinde | 87 | 7 | 53 |
| Theater | 60 | 2 | 38 |
| Veranstaltungsort | 55 | 4 | 28 |
| Kulturzentrum | 51 | 4 | 28 |
| Club | 40 | 7 | 13 |
| Kino | 33 | 5 | 12 |
| Galerie | 23 | 1 | 3 |
| Hackspace | 17 | 7 | 5 |
| Zoo | 11 | 1 | 5 |
| Soziales Zentrum | 7 | 0 | 4 |
| Musikspielstätte | 6 | 1 | 4 |
| Planetarium | 2 | 0 | 2 |
| Konzerthaus | 1 | 0 | 1 |

| Plattform | Quellen | mit Terminen | Termine in der Stunde |
| --- | ---: | ---: | ---: |
| ics | 12 | 9 | 1107 |
| tribe | 29 | 23 | 403 |
| jsonld | 26 | 24 | 267 |
| crawl | 11 | 10 | 214 |

Bemerkenswert daran ist die Bibliothek: 96 Häuser, vier Feeds. Und der Hackspace: 17 Häuser,
sieben Feeds. Wer Kalender lesbar macht, tut das nicht nach Größe, sondern nach Haltung.

## Die Stunde hört nicht an der Grenze auf

Von den 829 Websites sind **132 französisch**, und 15 der 66 Quellen mit Terminen liegen im
Elsass. Straßburg ist von Achern aus näher als Karlsruhe. Jede Erhebung, die an der Landesgrenze
aufhört — und das tut jedes Portal, jeder Verteiler, jede Landesdatenbank — verliert hier ein
Sechstel des Programms. Das ist kein Nebeneffekt der Methode, es ist ihr Zweck: die Stunde ist
eine physikalische Größe, keine Verwaltungseinheit.

## Die E-Bike-Stunde ist fast leer

32 von 1991 Terminen liegen in der E-Bike-Stunde. Anderthalb Prozent.

Das ist der härteste Befund dieser Erhebung, und er ist kein Fehler. Die Auto-Stunde um Achern
umfasst drei Großstädte; die E-Bike-Stunde umfasst Achern, Oberkirch, Bühl und ein paar Dörfer.
Wer hier ohne Auto lebt, lebt in einer anderen Stadt als der Nachbar mit Auto — nicht in einer
etwas kleineren, sondern in einer um den Faktor sechzig kleineren.

In einer Großstadt verschwindet dieser Unterschied fast (siehe unten). Er ist eine Eigenschaft
des Landes, und er wird nur sichtbar, wenn man beide Profile misst statt eines.

## Drei Häuser, ein Kalender

Stadtmuseum, Stadtbibliothek und Riedmuseum führen je 340 Termine — dieselben 340. Alle drei
verlinken denselben städtischen Kalender, und die drei Links unterscheiden sich nur in einer
Sitzungskennung:

```
…/zmservice/2787976/ical/vevent.ics?zm.sid=zmx3i2o12q52
…/zmservice/2787976/ical/vevent.ics?zm.sid=zm24zsbn2vk1
…/zmservice/2787976/ical/vevent.ics?zm.sid=zm6sts2w2wv3
```

Für die Erhebung sind das drei verschiedene Endpunkte, also drei Quellen. Die
Dublettenerkennung fängt es hinterher ab — die Spalte „nur hier" steht bei zweien auf 0 —, aber
der Feed wurde dreimal geholt und die Quellenzahl ist um zwei zu hoch.

Das ist eine offene Schwäche und als solche notiert: Endpunkte müssten vor dem Abholen um
Sitzungsparameter bereinigt und dann verglichen werden. Es steht hier, weil ein Showcase, der
nur zeigt, was funktioniert, nichts wert ist.

## Was die Kategorien nicht können

Die größte Einzelquelle im Elsass, das Fort de Mutzig, führt 177 Termine — und alle 177 landen
in `sonstiges`. `categories.py` arbeitet mit deutschen Schlagwörtern; ein französisches
`visite guidée` trifft keines davon. Dasselbe gilt für die Kinos: ihre JSON-LD-Einträge nennen
Filmtitel, keine Gattung.

Das Rohwort der Quelle bleibt in `category_raw` erhalten, die Zuordnung ist also nachholbar,
ohne noch einmal zu erheben. Trotzdem: die Kategorien sind das schwächste Stück dieser
Erhebung, und in einer zweisprachigen Region sieht man es sofort.

## Zum Vergleich: eine Großstadt

Dieselbe Erhebung für Berlin, nur die über OpenStreetMap gefundenen Quellen, ohne Katalog:

|  | Achern | Berlin |
| --- | ---: | ---: |
| Websites in der Stunde | 829 | 2121 |
| davon maschinell lesbar | 79 | 199 |
| Anteil | 9,5 % | 9,4 % |
| nur für Menschen | 426 | 1051 |
| Anteil | 51 % | 50 % |
| Termine in der Stunde (Auto) | 1991 | 3234 |
| davon auch in der E-Bike-Stunde | 1,6 % | 95 % |

Die Trefferquote ist gleich. Eine Kleinstadt im Schwarzwald und die größte Stadt des Landes
veröffentlichen ihr Programm im selben Verhältnis maschinenlesbar: jedes zehnte Haus. Jedes
zweite schreibt sein Programm auf, aber nur für Menschen.

Was sich unterscheidet, ist nicht die Technik, sondern die Entfernung — und damit, wer das
Programm überhaupt erreichen kann.

## Nachstellen

```bash
uv sync
uv run urbanify survey "Achern, Ortenaukreis"
uv run urbanify report achern
uv run uvicorn urbanify.main:app --port 8090   # dann http://localhost:8090/?ort=achern
```

Die Zahlen werden andere sein. Websites verschwinden, Feeds kommen dazu, und das Fenster
verschiebt sich mit dem Tag der Erhebung.

# urbanify-anything

Any city, the hour around it, and which sources publish events there.

*German original: [README.md](README.md). Code comments, CLI output and the remaining docs are
in German; identifiers are in English.*

## Why this exists

My last visit to Berlin felt like an upgrade for my brain. I live in Achern, a small town in
south-west Germany, and with two kids, short distances are among the most important things in
everyday life. What surprised me in Berlin was how normal it seemed to travel forty minutes
across the city for an event.

From Achern, the same forty minutes take me to Karlsruhe, to Strasbourg, or almost to
Freiburg — three cities with a broad range of culture, music and children's programmes. The
reach is there. It is just invisible, because nobody works it out for their own place.

This tool works it out, for any city: the events inside three real travel zones — 15, 30 and
60 minutes, by car or by e-bike — on an interactive map.

## What it does

You name a city. What lies within an hour is measured, not estimated. Which venues stand inside
it is known to OpenStreetMap. And which of them publish a machine-readable calendar is something
the survey finds out by itself — one website after another, politely, one request per second.

The result is more than an event calendar. It is also a finding: how many venues within an hour
of a place run a programme, how many of them can be asked by a machine, and how many write
their programme down for humans only.

The place is an input. No city appears in a signature, a condition or a default value; anything
that only applies to one region lives in the catalog (see below).

And then you live with it: bookmark events, judge them, and sharpen with rules what comes out
on top — see [The map to live with](#the-map-to-live-with).

**What it does not do:** accounts, sharing with others, a hosted service. A tool for one person
on their own machine.

## An example

![The measured hour around Achern: 15/30/60 minutes by car, dashed the e-bike hour, events in
terracotta](docs/bilder/achern.jpg)

Achern, 25,000 inhabitants, in the Rhine plain between the Black Forest and Alsace. The measured
hour reaches from Karlsruhe to Freiburg and far into France — 829 venues with a website lie
inside it, 132 of them French. 79 can be asked for events by a machine, 426 have a programme
for humans only. And 1.6 percent of the events can be reached by e-bike.

Found without any prior knowledge and without a single hand-entered source, in 18 minutes. The
full finding, including a comparison with Berlin (in German):
**[docs/showcase-achern.md](docs/showcase-achern.md)**.

## Getting started

```bash
uv sync
uv run urbanify survey "Leipzig"
uv run uvicorn urbanify.main:app --port 8090
```

Then open <http://localhost:8090>: enter a city, watch, read. A survey takes twenty minutes to
an hour depending on the city — most of that time it is waiting on purpose. For a first try,
`--max-sites 50` is much faster.

You need Python 3.12 or newer and [uv](https://docs.astral.sh/uv/). No API key, no account, no
Docker.

### With a coding agent

The repository is built to be handed to an agent such as Claude Code: "Clone
`lukasschreck/urbanify-anything` and survey my city." The things that are easy to get wrong
here are written down for it in [`CLAUDE.md`](CLAUDE.md), and what a contribution looks like in
[`CONTRIBUTING.md`](CONTRIBUTING.md). Before it starts: set `URBANIFY_CONTACT` in `.env` and
read [Responsibility](#responsibility) — the requests are made in your name.

### When something goes wrong

| What you see | What is happening | What helps |
| --- | --- | --- |
| "Der Schritt 'discover' ist gescheitert … 429/504" | Overpass is a shared service and occasionally overloaded | wait a few minutes, then run the commands it lists — progress is saved |
| "Der Schritt 'zones' ist gescheitert" | the public Valhalla instance does not answer | `urbanify zones <slug>` later, or your own instance via `URBANIFY_VALHALLA` |
| "Nominatim kennt keinen Ort namens …" | the name is ambiguous or misspelt | be more specific: `"Achern, Ortenaukreis"` |
| many websites `unerreichbar` (unreachable) | timeouts, mostly temporary | `urbanify probe <slug> --again` |
| the map stays empty | no events located yet, or the browser blocks WebGL | `urbanify report <slug>` shows whether events exist |

## What a survey does

| Step | Service | Result |
| --- | --- | --- |
| `place` | Nominatim | name → start point, country, time zone |
| `zones` | Valhalla | measured 15/30/60 minutes, car and e-bike |
| `discover` | Overpass (+ catalog) | every venue website inside the hour |
| `probe` | the websites themselves | which platform answers: `tribe`, `ics`, `jsonld`, `crawl` — or `nur-html` |
| `harvest` | the feeds | events inside the window (default 60 days) |
| `locate` | Nominatim | coordinates where the source gives none; zone per event |

Every step can be repeated on its own (`urbanify probe leipzig`, `urbanify harvest leipzig
--only stadt`, …). Each place gets one file, `data/<slug>/urbanify.sqlite`; removing a place
means deleting its directory.

## How sources are found

Nobody has to know a city's scene. OpenStreetMap knows theatres, clubs, museums, galleries,
cinemas, libraries, community centres, hackspaces and town halls, and many of them carry a
website. Each one is visited once:

- **tribe** — WordPress with The Events Calendar, open REST API
- **ics** — a calendar feed linked from the page
- **jsonld** — `schema.org/Event` in the programme page
- **crawl** — the same, but only on each event's own page; the programme page is the link list
- **nur-html** ("HTML only") — there is a programme page, but nothing machine-readable

That last list is the most interesting part of the whole tool. It is the to-do list: venues
that publish their programme, but in a way nobody can reuse. If you want to write a new
adapter, look there for the platform that shows up most often.

Adapters hang off platforms, not venues — and not cities. A new city needs no code at all.

## The catalog

Some things cannot be found through any single venue: a state portal, an open registry, a
network of self-organised spaces. That is what the catalog is for — a YAML file that is *not*
in the repository, because it is data, not tooling:

```bash
cp src/urbanify/catalog.example.yaml src/urbanify/catalog.yaml
```

Without this file a survey runs completely, just with what OpenStreetMap knows. That is the
normal case, not a shortcoming.

Every entry states where it applies — as an area, not as a city name. Whether it applies to a
city is decided by intersecting that area with the measured hour. A state portal therefore also
applies to the neighbouring town across the border if that town's hour reaches into the state.
The format is described in `catalog.example.yaml`.

Three adapter kinds ship with the tool, as examples of how a portal is connected:

| `kind` | For | What the entry needs |
| --- | --- | --- |
| `radar` | radar.squat.net, worldwide | `endpoint`; queried with the name of the place |
| `kulturdaten` | the kulturdaten.berlin API | `endpoint`, `city` as fallback for events without a place |
| `simplesearch` | berlin.de "SimpleSearch" tables | `endpoint` (JSON export), `city` |
| `none` | no adapter yet | listed in the report as "responsible, but not connected" |

The last two adapters know the platform of one particular portal. Where they apply is still
stated by the catalog entry and its area, not by the code.

## The report

`urbanify report <slug>` and the web interface show the same thing: per source, how many events
it holds, how many of them lie inside the hour, how many exist *only there*, at how many venues
and in which categories — plus which sources overlap and which venues have a programme for
humans only.

Duplicate detection is an approximation: same day, same start of the title, same one-kilometre
cell. It tends to find too few. If you want to derive a statement about a source from "only
here", read `store.dedup_key` first.

## The map to live with

The survey answers what exists. The second tab of the interface, **Karte** (map), is for the
question after that: where do I want to go?

- **How, when, what.** Car or e-bike (the zones follow), today to everything, categories,
  children's programme only — with an age where the source states one. 18+ stays off until you
  switch it on.
- **Bookmarks.** A star on an event: "I want to go there". Bookmarked events are listed at the
  top, carry a ring on the map and stay visible whatever the rules say.
- **Verdicts.** Very interesting, in principle, not interesting — once per event series, not
  per date. "Kuratieren …" walks through them one by one, with the keys 1, 2, 3.
- **Rules.** Rules highlight or hide ("title contains Hauptversammlung"), with a preview of what
  a rule moves in the selected place. Verdicts turn into rule suggestions. Starting rules can
  come from your own `rules.yaml` (template: `rules.example.yaml`).
- **Interests** order the lists — and change nothing else.

None of this deletes an event. A rule never discards anything, a verdict can be taken back, and
"Auch Ausgeblendetes" (also hidden) always shows the full stock.

What you add yourself is kept apart from the survey in `data/personal.sqlite` and survives a
place being surveyed again. Rules and interests apply to every place. There is one person and
no accounts: whoever starts the tool owns the file. Backing up means copying that one file.

## Settings

| Variable | Default | |
| --- | --- | --- |
| `URBANIFY_VALHALLA` | `https://valhalla1.openstreetmap.de` | public FOSSGIS instance, worldwide, with elevation data |
| `URBANIFY_NOMINATIM` | `https://nominatim.openstreetmap.org` | |
| `URBANIFY_OVERPASS` | `https://overpass-api.de/api/interpreter` | |
| `URBANIFY_CONTACT` | empty | contact in the User-Agent; set it for anything beyond a first try |
| `URBANIFY_CATALOG` | empty | your own source list, if it does not sit next to the module |
| `URBANIFY_DAYS` | `60` | window |
| `URBANIFY_DELAY` | `1.0` | seconds per host |
| `URBANIFY_CONCURRENCY` | `24` | hosts in parallel |
| `URBANIFY_DATA` | `./data` | surveys per place, and `personal.sqlite` |
| `URBANIFY_RULES` | `./rules.yaml` | your own starting rules, if they live elsewhere |
| `URBANIFY_ALLOW_PRIVATE` | off | `1` allows requests into non-public networks — only for a catalog endpoint in your own network |

Template: `.env.example`. A `.env` in the repository root is read at start-up; anything already
set in the environment takes precedence.

## Politeness, and what the tool must not do

A survey visits a few hundred to a few thousand third-party websites. Therefore:

- One request per second **per host**, however many hosts run in parallel.
- `robots.txt` is read and obeyed, `Crawl-delay` is honoured.
- The User-Agent tells the truth. No fake browser identity.
- The public services (FOSSGIS Valhalla, Nominatim, Overpass) are meant for occasional surveys.
  If you survey regularly or for many cities, run your own instances and set
  `URBANIFY_CONTACT`.

And the uncomfortable half: **that events are machine-readable somewhere does not mean you may
redistribute them.** For the websites found through OpenStreetMap the licensing situation is
unresolved — per venue, per country. The survey shows *that* something is there. What you may
do with it is for you to clarify before you publish anything. That is why every catalog entry
has a `license` field, and it should be filled in.

This is a local tool without login and without multi-tenancy. It is not built to be exposed to
the public internet.

Two safeguards against what a third-party website could do to the survey: addresses that are
not public (localhost, private networks, metadata services) are never fetched — not even via a
redirect — and no response is read beyond 3 MB.

## Responsibility

**Whoever runs this tool makes the requests in their own name and at their own
responsibility.** The repository provides code, not a service and not a permission. In concrete
terms:

- Every request originates from your machine and your address. Whether you may visit a region's
  websites automatically — the venues' terms of use, copyright and database rights, data
  protection, the law of your country — is yours to clarify. Obeying `robots.txt` is courtesy,
  not a legal basis.
- The public services have their own rules, and they apply to you, not to this project: the
  [Nominatim Usage Policy](https://operations.osmfoundation.org/policies/nominatim/), the
  terms of [Overpass](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html) and
  those of the FOSSGIS Valhalla instance. Nominatim requires a contact in the User-Agent —
  hence `URBANIFY_CONTACT`. Without it the tool warns on every survey.
- What you do with the collected events, in particular publishing them, is your decision and
  your liability (see above: machine-readable does not mean free).
- The authors take no responsibility for how clones and derivatives are used. The MIT licence
  says the same ("as is", without warranty).

## Data and attribution

Venues, zones and map come from [OpenStreetMap](https://www.openstreetmap.org/copyright):
© OpenStreetMap contributors, licensed under the ODbL. This also covers the figures and the
image in the showcase. If you publish results of a survey, credit OpenStreetMap as well. Zones
are computed by Valhalla, map tiles are served by OpenFreeMap.

## What is still missing

- **Public transport as a profile.** For a large city the car hour is the wrong hour; the
  public Valhalla instance has no timetable data.
- **Categories in languages other than German.** `categories.py` works with German keywords —
  in a French city almost everything ends up in `sonstiges` ("other"). The source's own wording
  is kept in `category_raw`, so the mapping can be redone later.
- **Adapters for the most common platforms under `nur-html`.** See above: that is the to-do
  list.
- **Feeds that differ only in a session parameter** count as several sources (example in the
  showcase). Duplicate detection catches the events, but not the source count.
- **Several people.** Bookmarks, verdicts and rules exist for exactly one person; accounts and
  sharing are not part of this tool.

## Contributing

See `CONTRIBUTING.md` (German). In short: tests run offline, docs in German, code in English,
and no city in a signature, condition or default.

## Licence

MIT, see `LICENSE`. The data the tool collects is not covered by it — that belongs to those
whose websites it comes from.

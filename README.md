# colosseum-volume-db

Manga **volume → chapter-range** database for Colosseum's volume-first manga reading.
Each record maps a series' published tankōbon volumes to the chapter numbers they contain,
so the app can present manga as volumes (Volume 1 = chapters 1–7, …) instead of a flat chapter list.

- **Source of ranges:** [Comick](https://comick.io) open API (`api.comick.dev`, token-free) — every
  chapter is tagged with its volume; we group by that tag. Complete where MangaDex was partial
  (Bleach 74/74, Naruto 72/72, Death Note 13/13).
- **All languages, majority vote.** We pull chapters in *every* language, because English scanlators
  frequently leave `vol` untagged (My Hero Academia: volumes 1, 19, 38 from English rows vs a
  complete 1–42 from all rows). Chapter numbers are canonical across translations, so ranges
  transfer. Where uploaders disagree about a chapter's volume the volume most rows voted for wins;
  a dead tie is left unassigned rather than guessed. A lone stray tag whose neighbours on both
  sides agree joins its neighbours — physical volumes are sequential, so a later chapter is never
  bound into an earlier book.
- **Sub-chapters are ordinals, not fractions.** `315.9` < `315.10` < `315.11`: those are the 9th,
  10th and 11th side chapters of 315. Reading them as floats makes `315.10 == 315.1`, which merges
  two different chapters and loses one.
- **Key:** WeebCentral series id (ULID) — the id the app already holds when a series is open.
- **No covers here.** A volume's cover = the thumbnail of its first chapter, assigned app-side from
  the WeebCentral chapter list. This DB is ranges only.

## Record shape

`db/<weebcentral-ulid>.json`:
```json
{
  "seriesTitle": "Death Note",
  "comickHid": "CKlytjyb",
  "comickSlug": "death-note",
  "weebCentral": { "seriesId": "01J76XY7FYW2T2SDXP32NEFY8H" },
  "volumes": [ { "number": 1, "chapterStart": "1", "chapterEnd": "7" }, ... ],
  "numberingQuirk": false,
  "complete": true,
  "qualified": true,
  "gateReason": "",
  "scrapedAt": "2026-07-25T..."
}
```
`numberingQuirk` = the series' chapter numbering starts fractional (e.g. Berserk's `0.01` prologue),
so its ranges need normalization before joining WeebCentral's integer chapters.

**`qualified` is the switch the app reads.** `true` = the volume shelf may be shown; `false` = show
the plain chapter list instead, with `gateReason` saying why. A series qualifies only when its
mapped volumes form one unbroken integer run starting at 0 or 1 **and** those volumes account for
the chapters they came from:

| Rejected when | `gateReason` |
|---|---|
| chapter numbering starts fractional | `numbering quirk (fractional chapter origin)` |
| nothing mapped | `no mapped volumes` |
| the shelf opens past volume 1 | `first mapped volume is 25, not 0/1` |
| a volume number is missing mid-run | `gap after volume 18` |
| one volume's chapters run into the next's | `volume 49 span overlaps volume 50` |
| a whole chapter inside the shelf is in no volume | `9 chapter(s) in no volume (first: 210)` |

The last two need the source rows, not just the spans. The coverage rule is one check doing three
jobs — every whole chapter between the **first** volume's start and the **last** volume's end must
be assigned to some volume:

- chapters stranded *between* volumes — Vinland Saga's volume numbers run 1–29 unbroken while
  chapters 210–218 carry no volume tag in any language, so nine chapters belong to no book;
- chapters swallowed *inside* a volume — tag only chapters 11 and 20 as volume 2 and its span
  stretches to `11–20`, quietly absorbing eight chapters nobody tagged. This is the sparse-anchor
  interpolation the gate exists to refuse, and spans alone cannot show it;
- chapters *before* volume 1, which the old pairwise seam check never looked at.

Out of scope by design: chapters after the last volume's end (the uncollected tail of an ongoing
series, shown as "Latest chapters") and chapters before the first volume's start (Bleach's untagged
chapter `0` one-shot, genuinely in no book).

Only **whole** chapters are covered. An untagged **side** chapter (`168.5`) between two back-to-back
volumes is assumed to be an extra that was never bound into either book. That assumption is an
inference from today's data, not something the code verifies — all it checks is whether the label
has a dot. Side chapters can be real volume content (Bleach volume 36 is `315.1–315.9`), so a long
untagged run of them would slip through; the longest run observed anywhere is 2, against the 9 it
would take to matter. Revisit with evidence if that grows.

We never estimate or interpolate a missing boundary — that would invent book edges that don't
exist. `volumes` is kept either way so failing data stays inspectable.

## App read path (Phase 1)

Read-only over the GitHub raw CDN (no auth, no token):
```
https://raw.githubusercontent.com/kingoftheseas56/colosseum-volume-db/main/db/<weebcentral-ulid>.json
```

## Rebuild / extend

```
pip install -r requirements.txt
# add titles to comick_volume_db/seeds.json, then:
python -m comick_volume_db.build_db      # writes db/<ulid>.json
python -m pytest -m "not live"           # unit + acceptance
```

## Coverage (measured 2026-07-29, all-language rebuild)

- 11 seeds · 9 qualified. Berserk fails on its fractional `0.01` numbering origin; Vinland Saga
  fails because chapters 210–218 carry no volume tag in any language.
- Ongoing series may be tagged short of their newest volume; those chapters surface in the app's
  "Latest chapters" shelf, never lost. Conversely the newest volume numbers on a running series can
  be uploader-assigned ahead of the physical release — the gate proves *completeness*, not that the
  final volume is on shelves yet.

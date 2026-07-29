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
  transfer. Where uploaders disagree about a chapter's volume, the volume most rows voted for wins
  (ties → the smaller volume).
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
the plain chapter list instead, with `gateReason` saying why (numbering quirk, a gap mid-run, or a
first volume that isn't 0/1). A series qualifies only when its mapped volumes form one unbroken
integer run starting at 0 or 1 — we never estimate or interpolate a missing boundary, because that
would invent book edges that don't exist. `volumes` is kept either way so failing data stays
inspectable.

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

- 11 seeds · 10 qualified. Only Berserk fails the gate (fractional `0.01` numbering origin).
- Ongoing series may be tagged short of their newest volume; those chapters surface in the app's
  "Latest chapters" shelf, never lost. Conversely the newest volume numbers on a running series can
  be uploader-assigned ahead of the physical release — the gate proves *completeness*, not that the
  final volume is on shelves yet.

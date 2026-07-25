# colosseum-volume-db

Manga **volume → chapter-range** database for Colosseum's volume-first manga reading.
Each record maps a series' published tankōbon volumes to the chapter numbers they contain,
so the app can present manga as volumes (Volume 1 = chapters 1–7, …) instead of a flat chapter list.

- **Source of ranges:** [Comick](https://comick.io) open API (`api.comick.dev`, token-free) — every
  chapter is tagged with its volume; we group by that tag. Complete where MangaDex was partial
  (Bleach 74/74, Naruto 72/72, Death Note 13/13).
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
  "scrapedAt": "2026-07-25T..."
}
```
`numberingQuirk` = the series' chapter numbering starts fractional (e.g. Berserk's `0.01` prologue),
so its ranges need normalization before joining WeebCentral's integer chapters.

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

## Coverage (measured 2026-07-25)

- Flagships 10/10 · obscure-title sweep 10/10 (Comick volume data + WeebCentral resolve).
- Ongoing series may be tagged short of their newest volume; those chapters surface in the app's
  "Latest chapters" shelf, never lost.

# Task 7 — THE HARVEST TABLE (proposed writes to `db/`)

**Plan:** `docs/superpowers/plans/2026-07-29-manga-volume-gap-fallback-sources.md`
**Companion DB repo:** `kingoftheseas56/colosseum-volume-db`
**Population (Note 1 — named explicitly):** the **11 Comick-failed series** in the 40-series
`gap_rate` sample (29 qualified / 11 failed by gate). This is NOT the 11 WeebCentral seed
records in `db/` — those seeds are separate. Both happen to be 11.

**Status: PROPOSAL ONLY. Nothing is written to `db/`. Agent 1 and Hemanth rule on this table
before a single record lands.** `db/` has been pristine for the entire arc; it stays that way
until they say go.

---

## What the harvest would write

`build_fallback_record` produces **two record types** for gap series (mirroring the Comick path,
which writes unqualified records too):

- **`fallback_qualified`** — the wins. A qualified record flips the series' shelf from a flat
  chapter list to a volume view. These are the records that justify the whole arc.
- **`fallback_unqualified`** — fallback data WAS read, but the gate (or the contiguity guard)
  refused it. A record is STILL written, unqualified, with the fallback volumes + provenance so
  the data stays inspectable — exactly as the Comick path writes unqualified records. The app
  shows the flat list for these; the volumes are recorded for diagnosis.

The other actions produce **no record** (skipped_qualified / skipped_numbering_quirk /
no_fallback_data / unreachable).

## The table (live re-resolution, 2026-07-30)

Source for all rows: Wikipedia `{{Graphic novel list}}` (publisher-cited).

| # | Series | Action | Would write to `db/`? | Vols | First range | Last range | Refusal reason (if unqualified) |
|---|--------|--------|-----------------------|------|-------------|------------|---------------------------------|
| 1 | **Demon Slayer** | fallback_qualified | ✅ yes (qualified) | 23 | v1: 1-7 | v23: 197-205 | — (gate clean, perfect tiling) |
| 2 | **One-Punch Man** | fallback_qualified | ✅ yes (qualified) | 37 | v1: 1-8 | v37: 189-194 | — (gate clean, perfect tiling) |
| 3 | **Sakamoto Days** | fallback_qualified | ✅ yes (qualified) | 28 | v1: 1-7 | v28: 246-255 | — (gate clean) |
| 4 | Hunter x Hunter | fallback_unqualified | ✅ yes (unqualified) | 10 | v30: 311-320 | v39: 401-410 | "first mapped volume is 30, not 0/1" (only v30-39 on Wikipedia) |
| 5 | Black Clover | fallback_unqualified | ✅ yes (unqualified) | 35 | v1: 1-7 | v37: 370-380 | "gap after volume 29" — vol 30 absent; 3 inter-volume breaks (ch 293-303, 326-336, 369) |
| 6 | Chainsaw Man | fallback_unqualified | ✅ yes (unqualified) | 24 | v1: 1-7 | v24: 223-232 | tiling broken — ch 34 missing between v4 (ends 33) and v5 (starts 35) |
| 7 | Dandadan | fallback_unqualified | ✅ yes (unqualified) | 25 | v2: 6-14 | v26: 220-228 | "first mapped volume is 2" + ch 138 missing between v16/v17 |
| 8 | Battle Angel Alita | skipped_numbering_quirk | ❌ no (fence) | — | — | — | numberingQuirk:true — fence refuses (our bug, §below) |
| 9 | Soul Eater | skipped_numbering_quirk | ❌ no (fence) | — | — | — | numberingQuirk:true — fence refuses (our bug) |
| 10 | JoJo's Bizarre Adventure | no_fallback_data | ❌ no | — | — | — | Wikipedia `List of ... volumes` carries zero GNL blocks |
| 11 | Tower of God | no_fallback_data | ❌ no | — | — | — | ChapterList genuinely empty (manhwa, no listings) |

### Tally

| Outcome | Count | Writes to `db/`? |
|---------|-------|------------------|
| **fallback_qualified** (the wins) | **3** | 3 qualified records |
| fallback_unqualified (read, refused) | 4 | 4 unqualified records (inspectability) |
| skipped_numbering_quirk (our bug) | 2 | none |
| no_fallback_data (honest refusal) | 2 | none |
| **TOTAL records proposed** | | **7** (3 qualified + 4 unqualified) |

**The headline number: 3 of 11 Comick-failed series would flip to a qualified volume shelf.**
That is the real close-rate of this arc on the gap population.

---

## Two corrections to the earlier `gap_coverage.md` report (honesty, surfaced not buried)

The committed `reports/gap_coverage.md` (2026-07-30, earlier today) labeled Black Clover,
Chainsaw Man, and Dandadan as **`no_fallback_data`**. Today's live re-resolution shows them as
**`fallback_unqualified`** — the data IS read (Wikipedia returns volumes), the gate/contiguity
guard refuses it for genuine source-data gaps, and a record is still written (unqualified) for
inspectability. This is **more accurate**, not less:

- **`no_fallback_data`** means no fallback source had any data (nothing to write).
- **`fallback_unqualified`** means data was read but refused — a record with the fallback
  volumes + provenance is written so the refusal is auditable.

The OUTCOME for the user is identical (flat chapter list, no volume shelf) — both are
unqualified. The distinction matters for the harvest: `fallback_unqualified` writes an
unqualified record to `db/`; `no_fallback_data` writes nothing. `gap_coverage.md` should be
updated to reflect this when it is next touched. This table is the corrected source of truth
for the harvest decision.

The 3 qualified wins (Demon Slayer, One-Punch Man, Sakamoto Days) and the 2 fence refusals
(Battle Angel Alita, Soul Eater) match `gap_coverage.md` exactly.

---

## Recorded findings for the ruling (NOT auto-fixed)

### The fractional-origin bug is OURS, Agent 1 decides if it jumps the queue

Battle Angel Alita and Soul Eater are refused by the numbering-quirk fence
(`skipped_numbering_quirk`), not because the source lacks data. The fence exists because
`volume_builder.gate`'s numbering-quirk check is **source-coupled and blind to a fractional
origin** when fed the fallback's derived rows. **This is our bug, needs no external source, and
is cheaper than anything left in this plan.** Agent 1 decides if it jumps the queue.

### One-Punch Man's overlap resolved cleanly by fallback — evidence the grouper may not need fixing

One-Punch Man's Comick failure was a **volume span overlap** (vol 34 overlaps vol 35). The
Wikipedia fallback resolved it cleanly into 37 perfectly-tiling volumes (1→194). This is
evidence the **overlap class may not need a grouper fix at all** — the fallback source sidesteps
it. Recorded, not acted on; Agent 1 + Hemanth decide whether the grouper overlap work
(§5.2 of `gap_coverage.md`) is still worth doing now that the fallback handles this case.

### Synopses: separate, optional, decoupled (Task 6)

Per-volume synopses are fetched **independently** from Fandom regardless of which source won the
ranges (Task 6 bug fix). They write to a **sibling file** `db/<id>.synopsis.json` with their own
`source: fandom` provenance — never inlined into the record. **18 of the 40-series sample have a
Fandom Volume_1 blurb section** (`reports/synopsis_reach_vol1_probe.json`); full-walk reach is
proven ~180s/series. Synopses never affect the gate and never block a record. Whether to ship
synopses in the harvest is a separate Agent 1 / Hemanth product call.

---

## What this table does NOT include

- The **9 WeebCentral seed records already qualified via Comick** are untouched (HARD SCOPE
  FENCE: `qualified: true` is never overwritten).
- The **2 unqualified seeds** (Berserk, Vinland Saga) are untouched — Berserk is fractional
  (the same bug class); Vinland Saga was the proof case (29 Wikipedia volumes that pass the
  gate) and would qualify under the same logic as the 3 wins here.
- This is the **40-series `gap_rate` sample only.** A full harvest over the whole Comick catalog
  is a separate, larger operation; this table is the gap population in the measured sample.

*No rounding up. Every number above is the actual measured count from today's live re-resolution.*

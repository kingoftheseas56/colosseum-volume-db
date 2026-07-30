# Report populations — name them every time (Note 1)

This repo has TWO "gap" populations that both number around 11. "11" or "3 of 11" without naming
the population is ambiguous and has caused confusion. **Name the population every time.**

## The two populations

### 1. The unqualified WeebCentral seed records — `gap_list.json` (2 series)

The WeebCentral seed records in `db/` that Comick left unqualified. **Only 2:**
- **Berserk** — `numbering quirk (fractional chapter origin)`, `inScopeForFallback: false`
- **Vinland Saga** — `9 chapter(s) in no volume (first: 210)`, `inScopeForFallback: true`

These are real records that already exist in `db/` (unqualified). Vinland Saga is the proof case
and **would qualify** via the Wikipedia fallback (29 vols, v1=1-5 to v29=210-220, gate clean —
verified live 2026-07-30). Berserk is fractional-origin (our bug) and stays unqualified.

### 2. The 11 failures in the 40-series `gap_rate` sample — `gap_rate.json` (11 series)

A **random sample of 40 ordinary series** (`reports/gap_rate.json`): 29 qualified via Comick,
**11 failed**. These 11 are the gap population the fallback sources exist to close:
Hunter x Hunter, JoJo's Bizarre Adventure, Black Clover, Battle Angel Alita, Demon Slayer,
Soul Eater, One-Punch Man, Chainsaw Man, Sakamoto Days, Dandadan, Tower of God.

**"3 of 11"** (the headline close-rate of this arc) means **3 of these 11 sample failures**
(Demon Slayer, One-Punch Man, Sakamoto Days) — NOT 3 of the 2 seed records, NOT 3 of the 11
seeds. Name it: *"3 of the 11 Comick-failed series in the 40-series gap_rate sample."*

## Rule

Any number quoted in a report must name its population. No bare "11," no bare "3 of 11." If the
population is the seed records, say "seed records (`gap_list.json`)." If it is the rate sample,
say "the 40-series `gap_rate` sample." They overlap incidentally (Vinland Saga is a seed record
AND would qualify under fallback logic) but they are not the same set.

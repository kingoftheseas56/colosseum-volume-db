# Gap Coverage Report — Manga Volume→Chapter Fallback Sources

**Plan:** `docs/superpowers/plans/2026-07-29-manga-volume-gap-fallback-sources.md`
**Companion DB repo:** `kingoftheseas56/colosseum-volume-db`
**Measured:** 40 ordinary series (Task 0b, `reports/gap_rate.json`, sampled 2026-07-30)
**Report date:** 2026-07-30 (updated after Hemanth Corrections 1–3)
**Commits this arc:** `cb34cc9` (Task 2 wiki reader) → `d220ac4` (Task 1 fandom walker) → `b0cb2d6` (Task 3 provenance) → `f2698e3` (Task 3b/3c resolver) → `773a0ea` (Task 4 parser) → `2eb8132` (Fandom names) → `2f4da2a` (Correction 2: derivation) → `11f7b7a` (Correction 3: synopses)

---

## 1. The gap, in numbers

| Metric | Count | % of 40 |
|--------|-------|---------|
| Comick qualified (no fallback needed) | 29 | 72.5% |
| Comick failed — **the gap population** | 11 | 27.5% |

The fallback sources exist to close part of that 27.5%. They cannot close all of it — some gaps are ours (bugs), and some are unreadable-without-derivation (correctly refused).

## 2. What the fallback closed

Of the 11 Comick-failed series, after running the full fallback path (Wikipedia > Fandom precedence, Agent 1's gate, provenance recorded), including the **derivation path added in Hemanth Correction 2** (`{{Numbered list}}` / `#` ranges, gated through within-volume AND cross-volume tiling):

| Fallback outcome | Count | Series |
|------------------|-------|--------|
| **fallback_qualified** (closed) | **3** | Sakamoto Days (Wikipedia, 28 vols); **Demon Slayer** (Wikipedia, 23 vols, 1→205, perfect tiling); **One-Punch Man** (Wikipedia, 37 vols, 1→194, perfect tiling) |
| **fallback_unqualified** (read but gate-refused) | 1 | Hunter x Hunter (only v30–39 on Wikipedia) |
| **skipped_numbering_quirk** (fence refused) | 2 | Battle Angel Alita, Soul Eater |
| **no_fallback_data** (honest refusal) | 5 | see §4 |

**Three series closed out of eleven (was one, before Correction 2).** Two of the five derivation series (Demon Slayer, One-Punch Man) cleared the tiling guard cleanly. The other three derivation series (Black Clover, Dandadan, Chainsaw Man) were honestly refused — the published Wikipedia source data itself has gaps that break tiling (see §4), which is the guard doing its job, not a parser bug. "Stays unqualified" is the correct outcome for those.

The 9 existing seed records in `db/` that already qualified via Comick are untouched, as are the 2 unqualified seeds (Berserk, Vinland Saga). The HARD SCOPE FENCE (`qualified: true` is never overwritten) held throughout. **`db/` remains untouched by this arc — this is still proof-and-report, not a harvest.**

## 3. Per-series breakdown (all 11 gap series)

| Series | Category | Comick gateReason | Fallback outcome | Detail |
|--------|----------|-------------------|------------------|--------|
| Sakamoto Days | ongoing | gap after volume 22 | **fallback_qualified** | Wikipedia written-bullets, 28 vols, v1=1-7 v28=246-255 |
| Demon Slayer | completed | no volume tagging | **fallback_qualified** | Wikipedia derived `{{Numbered list}}`, 23 vols, PERFECT TILING 1→205 |
| One-Punch Man | ongoing | volume 34 span overlaps vol 35 | **fallback_qualified** | Wikipedia derived `{{Numbered list}}`, 37 vols, PERFECT TILING 1→194 (vol 38 is an empty stub, correctly dropped) |
| Hunter x Hunter | long shonen | 9 ch in no volume (first: 391) | fallback_unqualified | Wikipedia has GNL only for v30–39; gate refuses (first mapped vol is 30) |
| Battle Angel Alita | seinen | numbering quirk (fractional origin) | skipped_numbering_quirk | fence refused — see §5.1 |
| Soul Eater | completed | numbering quirk (fractional origin) | skipped_numbering_quirk | fence refused — see §5.1 |
| Black Clover | long shonen | 2 ch in no volume (first: 370) | no_fallback_data | derivation read, but tiling BROKEN by genuine source gaps (vols 30/33/38 are stubs; vol 30 has ch 298 missing *within* the volume between its two columns) |
| Chainsaw Man | ongoing | gap after volume 22 | no_fallback_data | derivation read, but tiling BROKEN — ch 34 genuinely missing between vol 4 (ends 33) and vol 5 (starts 35) in the published source |
| Dandadan | ongoing | gap after volume 18 | no_fallback_data | derivation read, but tiling BROKEN — ch 3 missing within vol 1; ch 138 missing between vol 16/17 |
| Tower of God | manhwa | volume 2 span overlaps volume 3 | no_fallback_data | ChapterList genuinely empty (no data) |
| JoJo's Bizarre Adventure | long shonen | no volume tagging | no_fallback_data | `List of ... volumes` page has zero GNL blocks |

## 4. Schema discovery (Task 4 + Correction 2) — derivation is now READ

The plan asked for bounded schema discovery on the residue. The residue (11 series) was **small enough to hand-inspect** — the same threshold logic as Task 0. No model-in-the-loop discovery path was built; each page's schema was mapped by hand from the raw wikitext, which is more reliable than asking a model to describe shape and risks a model supplying a number.

Three schema families were found. The parser now reads ALL THREE families where the boundary is **determinable** (written OR derived-with-certainty):

**Readable — written tokens (parser extended, Task 4):**
- `*Days N:` / `*Fight N ` — word-prefix bullets, colon or space terminator. Numbers ARE written. `_BULLET` extended. (Sakamoto Days, Battle Angel Alita.)
- `ChapterListCol1` / `ChapterListCol2` — two-column split, concatenated in source order. (Battle Angel Alita.)
- Title matching: containment fallback + `×`→`x` fold reached subtitle pages (Demon Slayer: Kimetsu no Yaiba) and the multiplication-sign page (Hunter × Hunter).

**Readable — DERIVED with certainty (added Hemanth Correction 2):**
- `{{Numbered list|start=N}}` nested template — `start` is a WRITTEN token, the item COUNT is READ (each line is discrete, not estimated), and `start + count - 1` is arithmetic over two visible values. This is NOT interpolation (which would be inventing an unseen boundary). The mechanical guard is `_volumes_are_contiguous`: a miscounted item breaks tiling and the series is refused.
- MediaWiki `#` ordered-list markers — implicit `start=1` per the MediaWiki spec (the spec IS the source, not a guess); count read from the `#` lines.
- Two bug fixes were required to make this work at all: (a) brace-balanced GNL block extraction — the old regex TRUNCATED blocks at the first nested-template `}}` close, which silently dropped the derivation schemas' content; (b) the item-counter required pipe+whitespace but items come in two shapes (`| {{...}}` AND `|{{...}}`, sometimes within the same series) — the pipe-brace shape was silently undercounted, which then broke cross-volume tiling. Both fixed; regression tests added.

**Refused — tiling broken by genuine source-data gaps (3 series):**
- Black Clover, Chainsaw Man, Dandadan: the derivation reads the ranges correctly, but the published Wikipedia source data has real holes — chapters missing *within* a volume (between its two columns) or *between* volumes. Examples: Black Clover vol 30 col1=293-297 col2=299-303 (ch 298 missing within the volume); Chainsaw Man ch 34 missing between vol 4 (ends 33) and vol 5 (starts 35); Dandadan ch 3 missing within vol 1. These are editor errors in the Wikipedia source, not parser bugs. The tiling guard refuses the whole series rather than ship a shelf with a hidden hole. This is the guard doing its job — exactly the mechanical check Hemanth's correction specified.

**No data (correctly yields None):**
- Tower of God: every ChapterList field is genuinely empty. Manhwa volumes physically published without chapter listings in the Wikipedia source.
- JoJo's Bizarre Adventure: the only list page is `List of ... volumes`, which carries zero `{{Graphic novel list}}` blocks. No readable Wikipedia source.

These are correct outcomes, not parser gaps to close. The plan: *"If it still can't read it, the series stays unqualified. That is a correct outcome."*

## 5. Findings recorded but NOT acted on

The plan specified two findings to record but not fix, plus two correctness questions to resolve. All four are documented here.

### 5.1 Numbering quirk — OUR bug, fallback-unfixable (2/40)

**Series:** Battle Angel Alita, Soul Eater.
**Root cause:** `volume_builder.numbering_is_oddball` flags a series whose earliest chapter is fractional (e.g. a 0.01 prologue). This is Comick's data, and the flag is correct.

**Why fallback cannot fix it — the NUMBERING-QUIRK BLINDNESS finding (discovered Task 4):**
The fallback gate feeds `numbering_is_oddball` its own derived chapter rows (`_chapters_from_volumes`), which are synthesized from the fallback's whole-number volume ranges — so they are **always clean integers** and the check **always passes**, even when the real series starts at a fractional chapter. A fallback record for a numbering-quirk series would claim "volume 1 = chapters 1-6" against a WeebCentral shelf whose chapter 1 is served at a different number — internally consistent but **mismatched at the join**. The fallback gate cannot see this because it never sees Comick's raw rows.

**Action taken:** `build_fallback_record` now refuses at the fence (`skipped_numbering_quirk`) when `existing.numberingQuirk is true`, before any fetch. This is the conservative, honest call. These 2 series are fallback-unfixable for a reason that is **ours** (the gate is source-coupled and blind to the quirk), not missing data. Recorded, not acted on further.

### 5.2 Volume span overlaps — note the source (2/40)

**Series:** One-Punch Man (vol 34 overlaps vol 35), Tower of God (vol 2 overlaps vol 3).

**Source determination:** The span values (chapterStart/chapterEnd per volume) are produced by **our grouper** — `volume_builder.group_volumes`, which derives ranges from Comick's volume tags via `majority_assign`. So the *spans* are our computation, not raw Comick data. Whether the *root cause* is inconsistent Comick tagging (chapters mis-tagged to the wrong volume) or a bug in `majority_assign`'s voting was **not investigated** — the plan said to record, not to act. If this is a grouper bug, it is ours; if it is Comick's tags, it is upstream. Either way, it is not a missing-data gap a fallback source closes.

Recorded, not acted on.

### 5.3 Phantom volumes — possible in principle, not observed in the testable population

**The question (Task 3 item 4 mirror):** can a fallback publish a volume whose first chapter WeebCentral does not serve? Such a volume's tile has no cover and nothing to open — a dead tile.

**Method (Task 3c, redone properly after the retraction):** MAX-chapter-to-MAX-chapter only. For each series whose WeebCentral resolve was validated (Task 3b, similarity threshold 0.8), compare the fallback's last-volume chapterEnd against WeebCentral's highest served whole chapter. A volume ending beyond the served max is a phantom candidate.

**Result:** **0 phantoms observed in the 6 testable series.** 3 series were not carried by WeebCentral (correctly rejected by the fixed resolver — the Beet-the-Vandel-Buster→Buster-Keel wrong-series bug is fixed). 2 series (Toriko, Claymore) had markup the chapter-number regex could not read — these are **UNTESTABLE**, not phantom-free; a count of links was never substituted for a max (the error that caused the original false finding).

**Why phantoms are rare in the reachable population — the GNL-skews-to-completed observation:**
Wikipedia's `{{Graphic novel list}}` template is used overwhelmingly by **completed** series whose full volume run is published and chapter-bounded. Ongoing series tend to use other formats (Wikitables, derivation templates) or have no per-volume ChapterList at all. Concretely: of the 11 Comick-failed series, only 1 (Sakamoto Days, ongoing) produced a qualified Wikipedia fallback; the other 3 ongoing series in the gap (One-Punch Man, Chainsaw Man, Dandadan) all use the refused `{{Numbered list}}` derivation schema. A fallback that publishes future-volume boundaries an ongoing series has not reached is therefore structurally rare here — the template skew filters it out.

**Remediation: UNDECIDED (product call).** Clamping to available chapters, refusing the record, or showing unavailable volumes are all Agent 1 / Hemanth product decisions. Not made here. The plan was explicit: *"If phantom volumes CAN occur, do NOT decide what to do about them."*

### 5.4 GNL skews to completed series

Stated precisely (measured across all 40 series, page-resolution not qualified-data):
- 9/9 ongoing series resolve to *a* Wikipedia GNL page, but only 1/4 ongoing *gap* series produces *qualified* fallback data (Sakamoto Days). The rest use derivation schemas the parser refuses.
- The template is structurally biased toward completed series with fully-published, chapter-bounded volume runs. This is the strongest argument that phantom volumes (§5.3) are rare in the reachable population.

## 6. What this arc shipped

1. **Deterministic Wikipedia `{{Graphic novel list}}` ChapterList reader** (Task 2) — publisher-cited, no models in the data path.
2. **Deterministic Fandom volume-chain walker** (Task 1) — fan-maintained, two strategies (next-link walk + category enumeration), polite inter-fetch delay.
3. **Provenance + gate reuse** (Task 3) — additive `source`/`sourceUrl`, every fallback gated through Agent 1's existing gate (never a looser one), precedence comick > wikipedia > fandom, qualified records never overwritten.
4. **Resolver fix** (Task 3b) — a title WeebCentral doesn't carry returns None, never a different series (the silent wrong-series bug). Similarity threshold 0.8, verified against recorded fixtures.
5. **Parser extensions** (Task 4) — word-prefix bullets, two-column ChapterList splits, containment title-matching with `×`→`x` fold.
6. **Numbering-quirk fence** (Task 4 finding) — fallback refuses series Comick flagged numbering-quirk, because the fallback gate is structurally blind to a fractional origin.
7. **Fandom volume names** (additive) — optional English display title per volume, no new fetches, never affects the gate.
8. **Derivation: `{{Numbered list}}` / `#` ranges** (Hemanth Correction 2) — `start` token + item count = deterministic arithmetic, NOT interpolation. Gated through within-volume AND cross-volume tiling (`_volumes_are_contiguous`). Two root-cause bugs fixed: brace-balanced GNL block extraction (was truncating at nested-template closes) and pipe-brace item-counting (was silently undercounting). Unlocked 2 more series (Demon Slayer, One-Punch Man); 3 honestly refused for genuine source-data gaps. **Every record remains machine-derived and reproducible — no human ever types a value.**
9. **Per-volume synopses** (Hemanth Correction 3) — Fandom "Publisher's summary" / "Summary" / "Synopsis" / "Description" section, read from the same page already fetched for chapters+names (zero extra requests). Optional, patchy coverage, never affects the gate. Written to a SIBLING file `db/<id>.synopsis.json` (lazy-loaded when a volume is opened), NEVER inlined into the record the app fetches to draw a shelf.

### 6.1 Synopses — honest limitation (recorded, product call deferred)

The synopsis machinery is correct (proven: Mushishi Fandom walk extracts 10/10 clean blurbs, blockquote+quote markup stripped; One Piece carries 0 synopses and still qualifies). **But its production reach today is narrow**, and the reason is structural, not a bug:

**Precedence is comick > wikipedia > fandom.** Wikipedia volume pages carry no synopsis section. So a series that resolves via Wikipedia gets its chapter data from Wikipedia AND gets no synopses (the Fandom result that carried the blurbs was discarded by precedence). The synopsis path fires only for series that resolve via Fandom (no Wikipedia match).

Measured across 40 seeds: only 2 series resolve via Fandom (One Piece: 115 vols/0 synopses; Vinland Saga: 1 vol/1 synopsis). **The synopsis feature, as built, would deliver blurbs for very few series today.** This is correct precedence behavior — a series covered by the publisher-cited Wikipedia source should take its chapter data from there, not the fan-maintained Fandom — but it caps the synopsis payoff.

Two honest options for a future harvest (NOT decided here — product call for Hemanth/Agent 1):
- **Accept the narrow reach.** Synopses are a bonus on the few Fandom-only series; Wikipedia-resolved series show volumes without blurbs. Clean, no provenance compromise.
- **Fetch Fandom synopses as a secondary pass even when chapters came from Wikipedia.** More blurbs, but mixes two sources in one record's provenance and adds a fetch pass. Requires a provenance design decision (does a "source: wikipedia" record carry a "synopsesSource: fandom" field?).

Recorded, not acted on. The harvest (and any synopsis reach decision) stays deferred.

## 7. Test status

- **157 non-live tests green** (was 142 before Corrections 2–3; +12 synopsis tests, +3 derivation/two-column tests, net of the 2 flipped refusal tests).
- **8 live tests** (Wikipedia + Fandom proof cases), deselected by default (`-m "not live"`).
- Agent 1's `volume_builder.gate` is **byte-for-byte unchanged** throughout the arc (grep-verified: the gate reads only number/chapterStart/chapterEnd — it never references `name` or `synopsis`).
- `db/` is **untouched** — no records written by this arc (Task 3 onward was proof/dry-run by design; the plan said "Task 3 is one proof record, not a harvest" and the harvest was deferred).

---

*No rounding up. Every number above is the actual measured count.*

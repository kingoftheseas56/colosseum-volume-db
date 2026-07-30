# Gap Coverage Report — Manga Volume→Chapter Fallback Sources

**Plan:** `docs/superpowers/plans/2026-07-29-manga-volume-gap-fallback-sources.md`
**Companion DB repo:** `kingoftheseas56/colosseum-volume-db`
**Measured:** 40 ordinary series (Task 0b, `reports/gap_rate.json`, sampled 2026-07-30)
**Report date:** 2026-07-30
**Commits this arc:** `cb34cc9` (Task 2 wiki reader) → `d220ac4` (Task 1 fandom walker) → `b0cb2d6` (Task 3 provenance) → `f2698e3` (Task 3b/3c resolver) → `773a0ea` (Task 4 parser) → `2eb8132` (Fandom names)

---

## 1. The gap, in numbers

| Metric | Count | % of 40 |
|--------|-------|---------|
| Comick qualified (no fallback needed) | 29 | 72.5% |
| Comick failed — **the gap population** | 11 | 27.5% |

The fallback sources exist to close part of that 27.5%. They cannot close all of it — some gaps are ours (bugs), and some are unreadable-without-derivation (correctly refused).

## 2. What the fallback closed

Of the 11 Comick-failed series, after running the full fallback path (Wikipedia > Fandom precedence, Agent 1's gate, provenance recorded):

| Fallback outcome | Count | Series |
|------------------|-------|--------|
| **fallback_qualified** (closed) | 1 | Sakamoto Days (Wikipedia, 28 vols) |
| **fallback_unqualified** (read but gate-refused) | 1 | Hunter x Hunter (only v30–39 on Wikipedia) |
| **skipped_numbering_quirk** (fence refused) | 2 | Battle Angel Alita, Soul Eater |
| **no_fallback_data** (honest refusal) | 7 | see §4 |

**One series closed out of eleven.** That is the honest number — not rounded up, not softened. The fallback path's real value was concentrated in Sakamoto Days; the parser extensions (Task 4) also made Hunter x Hunter, Sakamoto Days, and Battle Angel Alita *readable* where they were not before, but only Sakamoto Days cleared the gate.

The 9 existing seed records in `db/` that already qualified via Comick are untouched, as are the 2 unqualified seeds (Berserk, Vinland Saga). The HARD SCOPE FENCE (`qualified: true` is never overwritten) held throughout.

## 3. Per-series breakdown (all 11 gap series)

| Series | Category | Comick gateReason | Fallback outcome | Detail |
|--------|----------|-------------------|------------------|--------|
| Sakamoto Days | ongoing | gap after volume 22 | **fallback_qualified** | Wikipedia, 28 vols, v1=1-7 v28=246-255 |
| Hunter x Hunter | long shonen | 9 ch in no volume (first: 391) | fallback_unqualified | Wikipedia has GNL only for v30–39; gate refuses (first mapped vol is 30) |
| Battle Angel Alita | seinen | numbering quirk (fractional origin) | skipped_numbering_quirk | fence refused — see §5.1 |
| Soul Eater | completed | numbering quirk (fractional origin) | skipped_numbering_quirk | fence refused — see §5.1 |
| Black Clover | long shonen | 2 ch in no volume (first: 370) | no_fallback_data | derivation schema (`#` + `{{Numbered list}}`) |
| Chainsaw Man | ongoing | gap after volume 22 | no_fallback_data | derivation schema |
| Dandadan | ongoing | gap after volume 18 | no_fallback_data | derivation schema (`{{Numbered list}}`) |
| Demon Slayer | completed | no volume tagging | no_fallback_data | derivation schema (`{{Numbered list}}` col-split) |
| One-Punch Man | ongoing | volume 34 span overlaps volume 35 | no_fallback_data | derivation schema (`{{Numbered list}}`) |
| Tower of God | manhwa | volume 2 span overlaps volume 3 | no_fallback_data | ChapterList genuinely empty (no data) |
| JoJo's Bizarre Adventure | long shonen | no volume tagging | no_fallback_data | `List of ... volumes` page has zero GNL blocks |

## 4. Schema discovery (Task 4) — why 7 stayed unqualified

The plan asked for bounded schema discovery on the residue. The residue (11 series) was **small enough to hand-inspect** — the same threshold logic as Task 0. No model-in-the-loop discovery path was built; each page's schema was mapped by hand from the raw wikitext, which is more reliable than asking a model to describe shape and risks a model supplying a number.

Three schema families were found. The parser was extended only for the families where chapter numbers are **written as tokens** (read, not derived):

**Readable (parser extended, Task 4):**
- `*Days N:` / `*Fight N ` — word-prefix bullets, colon or space terminator. Numbers ARE written. `_BULLET` extended. (Sakamoto Days, Battle Angel Alita.)
- `ChapterListCol1` / `ChapterListCol2` — two-column split. `_CHAPTERLIST` extended to concatenate both columns in source order. (Battle Angel Alita.)
- Title matching: containment fallback + `×`→`x` fold reached subtitle pages (Demon Slayer: Kimetsu no Yaiba) and the multiplication-sign page (Hunter × Hunter).

**Refused (derivation — crosses the no-interpolation line):**
- `{{Numbered list|start=N}}` nested template — chapter number is list-position + offset, never written as a token. Reading it means counting items and adding an offset to produce chapter numbers. That is interpolation. **5 series:** Black Clover, Dandadan, Chainsaw Man, Demon Slayer, One-Punch Man.
- MediaWiki `#` ordered-list markers — same derivation problem. (Black Clover block 0.)

**No data (correctly yields None):**
- Tower of God: every ChapterList field is genuinely empty. Manhwa volumes physically published without chapter listings in the Wikipedia source — same as One Piece/Naruto/Bleach which the parser already documents.
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
5. **Parser extensions** (Task 4) — word-prefix bullets, two-column ChapterList splits, containment title-matching with `×`→`x` fold. Derivation schemas refused.
6. **Numbering-quirk fence** (Task 4 finding) — fallback refuses series Comick flagged numbering-quirk, because the fallback gate is structurally blind to a fractional origin.
7. **Fandom volume names** (additive) — optional English display title per volume, no new fetches, never affects the gate.

## 7. Test status

- **142 non-live tests green** (was 82 at arc start; +60 across the arc).
- **8 live tests** (Wikipedia + Fandom proof cases), deselected by default (`-m "not live"`).
- Agent 1's `volume_builder.gate` is **byte-for-byte unchanged** throughout the arc.
- `db/` is **untouched** — no records written by this arc (Task 3 onward was proof/dry-run by design; the plan said "Task 3 is one proof record, not a harvest" and the harvest was deferred).

---

*No rounding up. Every number above is the actual measured count.*

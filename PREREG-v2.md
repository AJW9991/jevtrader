# PREREG-v2 — the second 28-day block, written blind, before v1 is read

**Status: DRAFT, to be FROZEN before `make results` on 2026-10-23 and SEALED at T0_v2.**
Written 2026-09-29 by Claude from Alex's decisions of the same day ("approved for all
recommended choices"), with nothing of `prereg-v1`'s §4–§7 read: every number used here is a
health quantity (report §1–§3, PREREG-v1 §8.4) or a shakedown fact already printed in the
sealed `PREREG.md`. The freeze is `git tag prereg-v2-draft <commit>` BEFORE `make results`
runs on 2026-10-23; after that tag only the fields §12 lists may change, and the seal
(`git tag prereg-v2`) prints the diff between the two tags into RESULTS-v2 §0. A change
outside §12 after the draft tag is not this pre-registration.

Everything measured is defined in `SPEC.md` as revised for v2 (§10 below lists the revisions;
every v2 row carries the revised sha); nothing here redefines a number.

## 0. What v1 could not answer, and what v2 changes

v1 (PREREG.md) tests whether a nightly rewrite of one typed question makes Jev decide better
than the rule its thresholds imply, on one product, at one cadence, with a frozen arm that
restates the rule. Four things are known before any v1 result is read, all from health
sections or from the sealed text itself:

1. **Arm A is arm C.** `v1`'s action criteria restate `rule_c` (PREREG-v1 §5: 181/181 on the
   shakedown), so A − C is zero by construction and the "frozen prompt" arm measures nothing.
2. **One adjective is dead.** `liq` read `thin` on 0 of 3,908 in-sample live rows through
   2026-09-29 (report §2; `fill1k_bps` p10 0.417, p50 0.843, p90 1.658, p99 2.447, max 3.749
   bps against cuts at 1.0 and 5.0), so 48 of 81 states have occurred and arm C's `liq != thin`
   clause never fires.
3. **Jev does not call direction.** `up15`/`down15` sat in 0.26–0.63 on the shakedown and lean
   tracked the `trend` word at r 0.99 (PREREG-v1 §5). A co-primary on them tests the word.
4. **One cadence, one product.** A minute-cadence decision pays the spread on every flip and
   the daily MDE is fixed by one product's variance; the fee arithmetic that decides whether
   any of this could ever matter for money needs the same decisions held over longer horizons.

v2 therefore: gives A a real frozen prompt, recalibrates `liq` from measured occupancy, drops
the direction co-primary to descriptive, adds two products and two longer cadences from the
same minute stream, adds a no-call arm D that says whether the per-minute Jev call is a lookup,
fixes the nightly's inputs (fee, per-state table, pinned model, CURRENT-only reading), and
pre-registers the promotion schedule. One primary hypothesis, a small claimable family,
everything else descriptive.

## 1. What is being tested

Four arms decide `buy | sell | hold` every minute on one state string per product:

| arm | what decides | changes when |
|---|---|---|
| **A** | Jev on the FROZEN `v2` action wording (`prompts/v2.json`, sha `b3291ca4a550…`, the wording promoted 2026-09-26 in v1: sells on a non-violent dump, holds a violent one; differs from `rule_c` on 27 of 81 states by its own table) | never during v2 |
| **B** | Jev on the CURRENT action wording, rewritten only by a person applying a nightly proposal under §8's schedule | at a promotion |
| **C** | `rule_c`, the no-model rule, with v2's `liq` cuts (§3) | never |
| **D** | the CURRENT wording's own 81-state table: Jev's answer on the synthetic state string, recorded once at promotion (`prompts/v<N>.table.<product>.json`), looked up by the live state; no call | at a promotion, with B |

The question is whether the nightly rewrite does anything: **H1: B beats C** in direction,
gross of fees, pooled over products, at the 15-minute cadence. Beside it, as a claimable
family (§6): B − C held at 60 and at 240 minutes, A − C, and B − A. Arm D is descriptive: if
B and D agree on nearly every tick, the fast model's per-minute call is a table lookup and a
third block can run it as 81 calls per promotion instead of 1,440 a day.

A and B ride one request on one state string per product, with the three nouls from `v1`
unchanged (SPEC §7); the only difference between A and B is the wording of `action`. At T0_v2
CURRENT is `v2`, so B ≡ A ≡ D until the first v2-block promotion: a free test-retest.

## 2. Products, warm-up, sample, clock

- **Products.** `SOL-USD` (the v1 stream, unbroken) and two more chosen by a probe run BEFORE
  T0_v2 and recorded in §12. The probe walks, in this order, `ETH-USD`, `XRP-USD`, `DOGE-USD`,
  `AVAX-USD`, `LINK-USD`, `ADA-USD`, and takes the first two that pass all of: the three
  public GETs the feed uses answer for the product; 30-day volume ≥ $50M/day on the venue's
  own stats; over the product's shakedown day the median `fill1k_bps` lies in [0.3, 3.0] bps
  and its p10 < p90 strictly (so `liq` has three words); no stablecoin. A product that fails
  is named in §12 with the failing criterion. Fewer than two passing → v2 runs on what passed.
- **Loops.** One loop process per product (its own launchd job, its own `data/<PRODUCT>/`
  store for the added products; SOL keeps `data/`), one shared key, one shared `data/HALT`,
  one spend tripwire over all logs (`DAILY_SPEND_HALT_USD` = 0.75 for three products).
- **No statistical warm-up** (PREREG-v1 §2 stands: the alphabet's windows come from the venue's
  own last 300 candles). The operational shakedown is one day per product.
- **T_first_v2** = the `tick_id` of the first `mode: "live"`, `absence: null` row written under
  the v2 code by the LAST product to start. **T0_v2** = the first minute boundary
  ≥ T_first_v2 + 86,400 s, written into §12 at sealing.
- **Days** are T0-anchored: d N = [T0_v2 + 86,400 (N − 1), T0_v2 + 86,400 N), N = 1 … 28
  (Alex, 2026-09-26, the v1 reading; ERRATA.md). **Sample** = every row with
  T0_v2 ≤ tick_id < T0_v2 + 28 · 86,400 s, minus whole product-days excluded by stop rule 3.
- The v1 stream between 2026-10-23 21:40Z and T0_v2 (the switch and shakedown) is logged and
  reported by `make health`; it enters no test of either pre-registration.

## 3. The alphabet: `liq` recalibrated, the rest unchanged

Three of four adjectives are relative already (`flow` by the window's own p10/p90, `trend` by
its own sd, `vol` by its own median) and occupied every word on the v1 health look (report §2:
quiet 11 %, bot_war 10 %, dumping 15 %, pumping 13 %, calm 18 %, violent 20 %). `liq` is
absolute and dead (§0.2). v2 sets its cuts from the measured distribution of `fill1k_bps`, a
feature that is logged and never sent, over live rows; the rule is fixed now and the values
follow from it:

- **`LIQ_DEEP_BPS`, `LIQ_THIN_BPS` per product = the nearest-rank p10 and p90 of `fill1k_bps`**
  over the product's live rows in a fixed window, each rounded to one decimal. For `SOL-USD`
  the window is the v1 sample's live rows through 2026-09-29 04:30Z (3,908 rows, features
  only): p10 0.417 → **`deep` < 0.4**, p90 1.658 → **`thin` > 1.7**. For an added product the
  window is its shakedown day; the values go into §12 before T0_v2.
- Strict cuts as before; a value ON a cut is `normal`; `fill1k_short` is `thin`.
- **Arm C changes with it** (its `liq != thin` clause now fires on about a tenth of ticks: a
  spread wider than the product's usual, not a $1,000 order the book cannot fill) and so does
  every table built on the 81 states. v2's `rule_c` truth table is re-pinned at the freeze.
- The occupancy flag (CONTRACT §4.2, > 95 % on one word) stays the health check; a word that
  goes dead during v2 is reported, never re-cut mid-sample.

## 4. The sampling unit, cadences, and the pooled statistic

**Cadences.** The loop decides every minute. A cadence c ∈ {900, 3600, 14400} s is a
REPLAY-TIME transform, `book.at_cadence(rows, c)`: within each c-block
[T0_v2 + c·j, T0_v2 + c·(j+1)), an arm's intent is its `argmax` (or the named column) on the
block's **anchor row** — the first `mode: "live"`, `absence: null` row of the block with
`columns` present — and `hold` on every other row of the block. Rule C is transformed the same
way (its `rule_c` at the anchor). A block with no anchor row is `hold` throughout. The
transformed intents feed `book.replay` unchanged, so the book, the marks, the spread and the
fee columns are exactly SPEC §10's. c = 900 is v1's design: at minute cadence the arms flip
inside a 15-minute block; v2's primary holds the anchor decision for the block. (v1's
minute-by-minute replay is also printed for B − C at 0 bps, descriptive, so the two blocks can
be read side by side.)

**Unit and statistic** (per cadence c, per product p): block k = the rows with
T0_v2 + c·k ≤ tick_id < T0_v2 + c·(k+1); S_k,p(X − Y, col, fee) = Σ over the block's rows of
d_t from `book.paired(at_cadence(rows_p, c), ·, X, Y, col, fee)`. The replay starts flat at
T0_v2 on the sample rows only.

**Pooling.** Crypto products move together, so the products are not three independent samples
and are never treated as such. The pooled unit is the TIME block: **S̄_k = mean over the
products p whose day containing block k is kept of S_k,p**; a block with no kept product is
dropped (no placeholder). n at c = 900 is at most 96 × 28 = 2,688 pooled blocks; at 3,600,
672; at 14,400, 168. Per-product S_k series are printed beside the pooled one, descriptive.

## 5. H1 (the one primary): the nightly's arm beats the rule, pooled, at 15 minutes

- **Statistic:** mean over the sample's pooled blocks of S̄_k(B − C, `argmax`, `FEE_BPS_PRIMARY`
  = 0.0) at c = 900 s: direction net of the spread, gross of fees (PREREG-v1 §4's reasoning
  stands; the venue's fees are arithmetic, §6).
- **Hypothesis:** H0: mean ≤ 0; H1: mean > 0. One-sided, **α = 0.025** (v1's level, kept for
  comparability although v2 has one primary).
- **Inference:** circular block bootstrap of the pooled block series in block order, block
  length L = 4 pooled blocks (1 h), 10,000 resamples, **seed 20261023**, each resample the
  same length as the series, blocks drawn with replacement from the circularly wrapped series;
  the draw written out exactly as PREREG-v1 §5 steps 1–3 (one `random.Random(20261023)` for
  H1; ⌈n/4⌉ starts per resample, `rng.randrange(n)`, four consecutive wrapped units each,
  truncated to n; the mean recomputed per resample; the bound is `sorted[249]` of the 10,000,
  no interpolation). Reject H0 iff that bound is > 0. Ties (S̄_k = 0) stay in.
- **Reported beside it, no inference:** the same cell per product; the disagreement-block
  count and share (a block holding a tick where B and C are on different SIDES) and the mean on
  disagreement blocks only; trades/day per arm and product; the minute-cadence B − C of v1's
  design; the cell at every fee of §6.

## 6. The claimable family, the fee arithmetic, and everything descriptive

**Family F (claimable), each at α = 0.025 / 4 = 0.00625, the §5 procedure with its own seed
20261023 + i, i = 1 … 4, in this order:**

| i | cell | what it says if rejected |
|---|---|---|
| 1 | B − C, `argmax`, 0 bps, c = 3,600 | the rewrite's direction survives an hour |
| 2 | B − C, `argmax`, 0 bps, c = 14,400 | … and four hours |
| 3 | A − C, `argmax`, 0 bps, c = 900 | a fixed non-rule prompt beats the rule (v1 could not ask this) |
| 4 | B − A, `argmax`, 0 bps, c = 900 | the nightly adds to the frozen prompt (stop rule 2 reads its sign) |

**Descriptive, printed, never tested:** every pair (B−C, A−C, B−A, D−B, D−C) × every column
(`rules.COLUMNS`, 11) × every fee × every cadence; per product and pooled. The fee columns are
`FEE_BPS_COLUMNS = (0, 2, 10, 25, 50, 90)`: 0 = gross (the primary), 2 = Binance.US, 10 = the
article's, 25, **50 = the venue's retail maker, 90 = the venue's retail taker, both VERIFIED
in-account by Alex 2026-09-27** (`FEE_BPS_VENUE = 90.0`, source line filled; ERRATA.md §10).
The 120 bps column of v1 is gone.

**The fee arithmetic (descriptive, the money question answered by subtraction).** For each
cadence and each arm pair, the day-28 output prints the gross edge per round trip
(mean S̄_k over disagreement blocks ÷ round trips per disagreement block) beside the round-trip
cost at each of the venue's published fee tiers, transcribed in-account into §12 at sealing
(30-day volume band, maker, taker). A tier whose round trip is below the gross edge is named
with the 30-day volume it requires. No inference; no cell of this table is ever claimed. It
says at what volume, if any, the measured direction would have paid, and nothing about whether
it will.

**Arm D (descriptive, with a pre-registered reading).** Per product and prompt version: the
share of live answered ticks on which `columns.b.argmax == columns.d`. Reading fixed now:
≥ 0.99 → "the per-minute call is a lookup of its own table; a third block may run D in B's
place at 81 calls per promotion"; < 0.95 → "Jev's live answer depends on something other than
the state string (drift, non-determinism); the model pin and the drift counter are read
first". Between: reported as measured.

**Direction probabilities (descriptive; v1's H2 retired).** `up15`, `down15`, lean, Brier
against the base rate, the measured-tail counts, and r(lean, ret_h) with the `trend`-word
comparator, exactly as PREREG-v1 §5's beside-numbers, per product. No hypothesis: on the
shakedown lean was the `trend` word and never reached a tail, so a test of it is a test of a
threshold the rule already acts on.

**Health (no inference):** test-retest (rows with `prompt_a_sha == prompt_b_sha` — none after
the first promotion, since A is `v2` and B moves), A's agreement with C, occupancy per word
and product, drift count, the D-agreement above.

## 7. Power, honestly

Per product at c = 900 the arithmetic of PREREG-v1 §7 stands: sd of a 15-minute paired
difference ≈ 33 bps, MDE = (1.960 + 0.842)·sd/√n = **1.78 bps per block = 171 bps/day** at
2,688 blocks, and the information lives on the disagreement blocks (with A = `v2` and B
starting there, B ≠ C on roughly the `vol violent` share, about a fifth of ticks on v1's
health look: n_eff ≈ 540 per product, MDE on disagreement blocks ≈ 4 bps).

**What pooling buys.** With pairwise correlation ρ between the products' block differences
the pooled mean's variance is σ²(1 + 2ρ)/3. Crypto products' 15-minute returns correlate at
roughly 0.6–0.8, but the ARMS' differences correlate less (they depend on each product's own
words), so ρ is unknown before the data and is printed at day 28:

| ρ | variance factor | pooled MDE per block | per day |
|---|---|---|---|
| 0.0 (independent) | 0.33 | 1.03 bps | 99 bps |
| 0.5 | 0.67 | 1.45 bps | 139 bps |
| 0.7 | 0.80 | 1.59 bps | 153 bps |
| 1.0 (one product thrice) | 1.00 | 1.78 bps | 171 bps |

**Cadence.** Holding the anchor decision for c seconds multiplies the per-block sd by
√(c/900) and divides n by the same factor, so the DAILY MDE is the same 171 bps/day per
product at every cadence; the per-block figures are 7.1 bps at 60 minutes (672 blocks) and
28.5 bps at 240 (168 blocks). Fewer blocks make the bootstrap's bound coarser; family F's α
of 0.00625 makes the 60- and 240-minute cells hard to reject at 28 days. Accepted now: those
two cells are there to be read beside the primary, and their rejection would be a strong
result, not an expected one.

**The 56-day lever.** Doubling the block to 56 days cuts every MDE by √2 (121 bps/day per
product). v2 keeps 28 days for comparability with v1 and so that each promotion has a month
of nights; a third block may take 56 and say so before its own T0.

## 8. The treatment: what the nightly is, and when a person may promote

The treatment under H1 is the nightly rewrite AND its inputs. v2 fixes these before T0_v2 and
they do not change during the block:

- **`nightly/PROMPT.md` (v2 text):** the v1 rules, plus: the product name is the first word of
  the state and the wording must read identically for every product (one CURRENT for all);
  the measured fact that Jev reads "volatility is calm" as "not violent" (proposals/2026-09-25.review.md),
  so a candidate whose only lever is calm-vs-normal changes nothing; no numbers, full text,
  one to three candidates, only `action`, as before.
- **The digest (v2 content):** per product and pooled, the summary line at 0 bps and at the
  venue's verified maker and taker; **every arm-B figure from rows whose `prompt_b` is CURRENT
  only** (v1's summary line replayed B over a promotion day's mixed rows: ERRATA.md); the
  disagreement rows (confidence ≥ 0.85, up to 25) as before; and new, a **per-state table**
  over the 81 states per product: rows seen, B's choice distribution, mean `ret_h_bps` and the
  label rates (up/flat/down) at the 15-minute join. Nothing in the digest is a test.
- **The slow model:** `claude -p` pinned with `--model <id>`, the id the v1 nights recorded as
  `claude model <id>` in logs/propose.log from 2026-09-29 (filled into §12 on 2026-09-30, before
  any v1 result exists); from an empty temp cwd, tools off, `nightly/settings.json`, the 45-min
  cap; CLI version, user-memory sha and answering model logged each night, as now.
- **Scoring a candidate:** the 81-state table per product (243 Jev calls, ~$0.01), Jev's
  answers on the synthetic strings, never a backtest; under each candidate the table says
  which states move from CURRENT's answer (the 2026-09-28 addition).
- **Promotion (Alex alone, `bin/promote`), on a pre-registered schedule enforced in code:**
  only inside the five minutes after a T0-anchored day boundary (so every product-day has one
  `prompt_b` version); at most one promotion per seven days; none after the start of day 22
  (so every version lives at least seven days); the committed table diff names the states
  moved. A candidate whose table changes 0 states is refused (a no-op promotion would still
  reset the version stretch). The person's reason is one line in the promote commit.
- **What a promotion writes:** `prompts/v<N>.json`, `prompts/CURRENT`, and
  `prompts/v<N>.table.<product>.json` for every product (arm D's lookup; its sha goes on the row
  as `table_sha`).

## 9. Stop rules — fixed now

1. **Day 28, neither A nor B beats C on H1's cell** (B − C at α 0.025 as §5; A − C at its family
   α as §6 i=3) → the model arms are retired; C and the feeds keep logging only if a third
   pre-registration wants them.
2. **B − A ≤ 0** at day 28 (point estimate of the pooled mean S̄_k(B − A, argmax, 0 bps),
   c = 900) → the nightly is stopped (its plist booted out); A is kept.
3. **A BAD product-day is excluded, logged, and three of them pause that product.** A
   product's T0-anchored day is BAD when its outcome fill (live answered rows whose t + h the
   log has reached, with a non-`gap` outcome) is < 95 %, or its Jev error share (rows with
   `absence: "jev"` of every kind over all rows of `mode: "live"`) is > 5 %. **A product-day with
   no live answered row is excluded whole** (Alex, 2026-09-29; fill is 0/0 there). The day is
   excluded from every statistic for that product; the pooled S̄_k on its blocks averages the
   remaining products. One line per exclusion (`dNN  product  fill%  jev-err%  reason`) in
   `data/exclusions.tsv`, in the parser's accepted forms, written by Alex the morning after;
   `make status` shows the table and day 28 recomputes the rule beside the file and names any
   disagreement. On a product's third BAD day its sends pause by hand (`data/HALT` names it),
   the cause is fixed, sends resume; the calendar does not stop.
4. **Void.** A product with fewer than 21 kept days is void for v2 and leaves the pool. If the
   pool has no product with 21 kept days, the block is void, reported as void, and a third
   block is a new pre-registration.
5. **The day-14 look is health only:** `make health` (report §1–§3 per product and pooled).
   Nothing of §4–§7 is computed or printed; `make report` withholds them until
   T0_v2 + 28 d and `--unblind` is a recorded look. No bootstrap runs before day 28.
6. **No extension after looking.** The sample ends at T0_v2 + 28 days whatever the numbers say.

## 10. What SPEC, CONTRACT and the code change for v2 (the build, blind, in a worktree)

Built on branch `prereg-v2` in a worktree without `data/`, tested by `make test` and CI, merged
to `main` only after RESULTS.md (v1) is committed on 2026-10-23, then installed by the switch
procedure of STEPS §10 (v2). Nothing here changes what a v1 row means; v1's readers stay and
read the v1 log as they do now.

- **SPEC (v2 sha on every v2 row):** §2 row gains `product`, `columns.d` (arm D's intent from
  the CURRENT table, `null` when the table lacks the state), `table_sha`; §5 `liq` cuts per
  product from §3; §6 rule C's truth table re-pinned; §7 four arms, A = `v2`; §10 fee columns
  (0, 2, 10, 25, 50, 90), `FEE_BPS_VENUE = 90.0` verified; §14 the new constants
  (`PRODUCTS`, `CADENCES = (900, 3600, 14400)`, `FROZEN_A = "v2"`, the per-product liq cuts,
  `DAILY_SPEND_HALT_USD = 0.75`). ERRATA.md's SPEC rows that describe what the code already does
  are folded into the text.
- **config / cycle / feed:** `JEVLOOP_PRODUCT` selects the product and its store
  (`data/` for SOL-USD, `data/<PRODUCT>/` otherwise); the spend guard sums every product's log;
  one shared `HALT`; the row carries `product`; per-product heartbeat and lock.
- **prompts:** `build(frozen_a, current)` sends `a_action` from `FROZEN_A`'s file; the nouls
  stay `v1`'s. `bin/promote` writes the table files and enforces §8's schedule (day-boundary
  window, seven-day spacing, none after day 22, no zero-state candidate) and refuses otherwise.
- **book:** `at_cadence(rows, c)`; `replay`/`paired` unchanged.
- **report / status / dash / inference:** per-product and pooled series; the cadence loop;
  family F with its seeds and α; the D-agreement reading; the fee-tier arithmetic table; stop
  rules 3–4 per product with the NO LIVE ROWS exclusion; `make results` for v2 reads all logs
  and refuses before T0_v2 + 28 d; the day-14 look stays `make health`.
- **nightly:** the digest of §8 (pooled, CURRENT-only, per-state table, verified fees), PROMPT.md
  v2, `--model` pin, per-product tables in `policy_table.py`.
- **launchd:** one loop plist per added product (`com.alexward.jevloop.loop.<product>`), the
  same nightly, the same backup (which copies every store). Hand-installed (STEPS §10 v2).
- **tests:** `tests/test_frozen.py` re-pinned at the seal for SPEC v2, PREREG-v2.md, PROMPT.md
  v2, `prompts/v2.json` (arm A) and the tables, the constants, the alphabet, rule C v2;
  `test_invariants.py` extended to the cadence transform and the pooled unit against
  independent transcriptions of §4–§5; `tests/synth.py` gains products and a cadence knob.
- **The switch (STEPS §10 v2, 2026-10-23 after `make results`):** commit RESULTS.md; merge
  `prereg-v2`; `make test` on the Mac; bootout and bootstrap the SOL loop plist (the code
  changes what the next tick writes: `product`, `columns.d`, the v2 spec sha, A = v2);
  bootstrap the added products' plists; `make status` shows three heartbeats; the nightly
  plist is unchanged; the shakedown day begins; T_first_v2 is the last product's first live
  row.

## 11. What would falsify what

- H1 rejected: the nightly-rewritten wording, held for fifteen minutes, beat the rule in
  direction, pooled over these products and days. With i=4 also rejected: the rewrite added to
  the frozen prompt. With i=3 rejected and i=4 not: the frozen `v2` wording did the work.
- H1 not rejected: the model arm is no better than the rule in direction, gross, at fifteen
  minutes, on these products over these 28 days (stop rule 1 with i=3).
- i=1 or i=2 rejected without H1: direction at a longer hold that the minute-scale replay
  does not show; a third block puts that cadence first.
- D-agreement ≥ 0.99: the fast model is a lookup here, and its cost is 81 calls per promotion.
- The fee table names no tier below the gross edge: nothing measured here pays at the venue,
  at any volume; the arithmetic settles it.

## 12. Fields filled after the draft tag (and nothing else)

| field | filled when | from |
|---|---|---|
| the pinned slow-model id (§8) | 2026-09-30 | `logs/propose.log`'s `claude model <id>` on the 2026-09-29 night (majority of the v1 nights from then, if they differ) |
| the two added products and each failing candidate's criterion (§2) | at the switch, before T0_v2 | the probe over the shakedown day |
| `LIQ_DEEP_BPS`, `LIQ_THIN_BPS` per added product (§3) | at the switch, before T0_v2 | p10/p90 of `fill1k_bps` over the shakedown day |
| the venue's fee-tier table (§6) | at sealing | read in-account, transcribed with the read time |
| T_first_v2, T0_v2, sealed-by, sealed-on | at sealing | the logs and the person |

Pinned slow model: `________`   Products: `SOL-USD`, `________`, `________`   Liq cuts: `________`
Fee tiers (30-day band / maker / taker, read UTC `________`): `________`
T_first_v2: `________`   T0_v2: `________`   Sealed by: `________`   on: `________`

## 13. Sealing

Freeze, before `make results` on 2026-10-23:
```bash
cd ~/Projects/jev-paper-loop && git add PREREG-v2.md && git commit -m "PREREG-v2: frozen draft" && git tag prereg-v2-draft "$(git rev-parse HEAD)"
```
Seal, once §12 is filled and before the first v2 sample row:
```bash
cd ~/Projects/jev-paper-loop && git add PREREG-v2.md tests/test_frozen.py && git commit -m "PREREG-v2: T0_v2, products, cuts, model, tiers, signature; pins" && git tag prereg-v2 "$(git rev-parse HEAD)" && git diff --stat prereg-v2-draft prereg-v2
```
The diff between the tags must touch only §12's fields, the §3 and §10 constants those fields
set, and `tests/test_frozen.py`. Anything else, and the tag is not this pre-registration.

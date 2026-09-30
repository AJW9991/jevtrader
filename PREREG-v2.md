# PREREG-v2 — the second 28-day block, written before v1 is read

**Status: DRAFT.** Three tags carry it: `prereg-v2-doc` (this text, once the 2026-09-29 review
and its recheck are in), `prereg-v2-draft` (an annotated tag on the BUILD branch, pushed, made
before `make results` runs on v1 on 2026-10-23: text, SPEC v2, the treatment, the code, the
tables, the probe's output and a `tests/test_frozen.py` that already pins all of it), and
`prereg-v2-seal` (after the switch, once §12's fields are filled, tagged only after
`bin/seal-check` exits 0, §13). After `prereg-v2-draft` nothing in the tree changes but what
§13 (c) allows; anything else, and the seal is not this pre-registration. Every edit between
`prereg-v2-doc` and `prereg-v2-draft` is a dated entry in §14 that says what its author had read.

**What was read before this was written.** Nothing of v1's report §4–§7 or of any
`loop.inference` output on the v1 sample: no `--unblind`, no `make results`, no `loop.inference
--sample`. The draft is NOT blind to in-sample nightly material: before drafting, the drafting
session had read `proposals/2026-09-24..27.md` and the 2026-09-27 proposal's candidate
rationales (which quote digest outcomes), `proposals/2026-09-25.review.md` (one day's
disagreement counts; its recommendation is arm A's wording), HANDOFF.md's nightly notes, and the
first twelve lines of `data/digest-2026-09-27.md` (that day's summary line, with each arm's paper
pnl at 0 and 120 bps, and four of its disagreement rows with their 15-minute returns and labels).
Digest pnl is an outcome proxy; an editor who has read one says so here. Whether Alex opened a
`data/digest-*.md` or a `logs/claude-*.txt` directly before 2026-09-29: **No, neither** (Alex, 2026-09-29
~07:00Z: `make status`, the dash and the proposal tables only).
Every number here is a health quantity (report §1–§3, PREREG-v1 §8.4), a logged feature of v1's
live rows read with no answer or outcome beside it (§3, by `bin/fill1k-quantiles`), a synthetic
policy-table fact (`proposals/`), or a shakedown fact printed in the sealed `PREREG.md`. Until
`prereg-v2-draft`, nobody editing v2 opens a digest, a nightly transcript, or a proposal
rationale dated 2026-09-28 or later; an exposure is logged in §14. The build is blind by
procedure, not by construction: its worktree has no `data/`, so no report or result can be
computed there by accident, and its authors are bound by this paragraph.

Everything measured is defined in `SPEC.md` as revised for v2 (§10; every v2 row carries the
revised sha); nothing here redefines a number. "Block k" below is the c-second unit; "the block"
elsewhere is the 28-day experiment; the bootstrap resamples runs of L = 4 units.

## 0. What v1 could not answer, what v2 changes, and that v2 runs whatever v1 says

v1 (PREREG.md) asks whether a nightly rewrite of one typed question makes Jev decide better
than the rule its thresholds imply, on one product, deciding every minute, with a frozen arm
that restates the rule. Four things are known before any v1 result is read:

1. **Arm A is arm C.** `v1`'s action criteria restate `rule_c` (PREREG-v1 §5: 181/181 on the
   shakedown), so A − C is zero by construction and the frozen-prompt arm measures nothing.
2. **One adjective is dead.** `liq` read `thin` on 0 of 3,467 rows carrying adjectives, and 48 of 81 states had
   occurred (report §2 by `make health`, 2026-09-28 21:34Z, a health quantity); the quantiles tool
   counts 3,877 live rows through 2026-09-29 04:30Z (§3). The cuts (`deep` < 1.0 bps, `thin` > 5.0 bps of fill cost) sit outside where the
   fill cost lives (§3).
3. **Jev does not call direction.** `up15`/`down15` sat in 0.26–0.63 on the shakedown and lean
   tracked the `trend` word at r 0.99 (PREREG-v1 §5). A co-primary on them tests the word.
4. **One cadence, one product.** A minute-cadence decision pays the spread on every flip, and the
   daily MDE is fixed by one product's variance. Whether any measured direction could ever have
   paid a fee is arithmetic on decisions held longer, which v1 does not print.

v2 therefore: freezes A at a real non-rule wording, re-cuts `liq` in a price-free unit from
measured occupancy, retires the direction probabilities to descriptive, adds two products and
three decision-held cadences (15, 60 and 240 minutes) from the same minute stream, adds a
no-call arm D that says whether the per-minute Jev call is a table lookup, fixes the nightly's
inputs, and pre-registers the promotion schedule. One primary, a four-cell claimable family,
everything else descriptive.

**v2 runs whatever v1 found.** v2 is installed on 2026-10-23 after `make results`, as written
here, whatever RESULTS.md (v1) reads: H1 rejected or not, either v1 stop rule firing, or v1
void. RESULTS.md reports v1's stop rules 1 and 2 (PREREG-v1 §8.1–§8.2) as v1's verdicts on v1's
arms; for the second block this pre-registration supersedes their operational acts (the loop
stops sending; the nightly plist is booted out). PREREG-v1 §8.1 ("only if a second
pre-registration wants them") and §8.5 anticipate exactly this, and this document is frozen
before either rule is read. If the switch is not made, RESULTS.md records v2 as not run, with
the reason in one line. **v2's A, C and H1 are not v1's**: C now holds on `thin` pumping ticks
that v1's C bought, B's state string carries `thin`, and H1 is pooled and decision-held. No v1
and v2 number is pooled or read as a replication.

## 1. What is being tested

Four arms decide `buy | sell | hold` every minute on one state string per product:

| arm | what decides | changes when |
|---|---|---|
| **A** | Jev on the FROZEN `v2` action wording: `prompts/v2.json`, the wording promoted 2026-09-26 in v1 (sells on a non-violent dump, holds a violent one). Canonical prompt sha (SPEC §2, the row's `prompt_a_sha`) `b3291ca4a55091bd8a331e87ac95dfccfca6b81664f38f9430f42f0afc473c0e`; file sha256 `dcc848e5ad1452bede8631cf0d2f9801175070746ced883857e86366ec4a8ab4`. By its own 81-state table (`proposals/2026-09-25.md` cand_2, `proposals/2026-09-27.md` "current (v2)", both 2026-09) it differs from `rule_c` on 27 of 81 states for `SOL-USD`; `__` of 81 for `<P2>` and `__` of 81 for `<P3>`, each from that product's pinned table (§8), written before the draft tag. | never during v2 |
| **B** | Jev on the CURRENT action wording: a human-gated rewrite, at most weekly, from nightly proposals (§8) | at a promotion, effective at a day boundary |
| **C** | `rule_c`, the no-model rule; its truth table over the 81 words is unchanged (12 buy / 45 sell / 24 hold, SPEC §6); which live ticks read `thin` moves with §3 | never |
| **D** | the CURRENT wording's own 81-state table: Jev's answer on the synthetic state string per product, copied at promotion from the promoted candidate's column of the proposal night's table (`prompts/v<N>.table.<product>.json`, one request per state carrying the candidates and CURRENT; `bin/promote` sends nothing), looked up by the live state; no call | at a promotion, with B |

**Arm A's text and the added products.** `prompts/v2.json`'s instructions begin "Decide whether
to be long SOL". `prompts.build` renders the action text per product: in `prompts/v2.json` the
token `SOL` is the base placeholder and is replaced by the row's base; files `v3` and later name
no base in `PRODUCTS` and may use the literal `{BASE}`; the loader and `bin/promote` refuse any
other product word. `SOL-USD`'s requests stay byte-identical to v1's for A. A test asserts each
product's rendered A differs from SOL's only in that token.

The question is whether the nightly rewrite does anything: **H1: B beats C** in direction,
gross of fees, pooled over products, decided once per 15-minute block. Beside it, as a
claimable family (§6): B − C decided once an hour and once every four hours, A − C, and B − A.
Arm D is descriptive with a pre-registered reading: if B and D agree on nearly every tick, the
fast model's per-minute call is a lookup of its own table, and a third block may run D in B's
place at 81 calls per product per promotion (243 for three products) instead of one request a
minute per product (1,440 a day, which A and the nouls also ride).

A and B ride one request on one state string per product, with the three nouls from `v1`
unchanged (SPEC §7); the only difference between A and B is the wording of `action`. At T0_v2
CURRENT is `v2` (§10 sets it at the switch if v1's CURRENT names anything else), so until the
first v2-block promotion B asks A's wording as a second question (A vs B is a free test-retest)
and D is that wording's table (B vs D is §6's D-agreement).

## 2. Products, loops, terms, warm-up, sample, clock

- **Live row** = a row with `mode: "live"` and `absence: null` (PREREG-v1 §5, PREREG.md:156;
  `report._live`). Used in that sense everywhere below.
- **Products.** `SOL-USD` (the v1 stream, unbroken) and two more chosen by `bin/probe`, committed
  and tested, over the UTC day **D = 2026-09-30**, named here before it runs and before the draft
  tag. `bin/probe run --day 2026-09-30 --out probe/2026-09-30` is started by hand from
  `~/Projects/jev-paper-loop-v2` before D's 00:00Z under `caffeinate -i`; it makes public GETs
  only (the feed's three, one candidate at a time, at most one request per second overall,
  starting at second :30 of each minute so the live loop's :00 requests see no added load; the
  feed never retries), uses no Jev key, and writes nothing under any `data/`, `logs/` or lock:
  its rows go to `probe/2026-09-30/` and are committed verbatim. There is no re-run; a restart
  within D into the same directory continues the run. `bin/probe volume --day 2026-09-30 --out
  probe/2026-09-30` runs once on 2026-10-01 (UTC), so its 30 closed `ONE_DAY` candles are
  2026-09-01 … 2026-09-30; if that endpoint does not answer, `bin/probe volume` fails and criterion
  (2) is restated in §14 before D. Candidates, in this order: `ETH-USD`, `XRP-USD`, `DOGE-USD`,
  `AVAX-USD`, `LINK-USD`, `ADA-USD`. `bin/probe summarize probe/2026-09-30` computes every
  criterion and takes the first two that pass all of: (1) the candidate's ok rows (the three
  public GETs answered and features computed) are ≥ 99 % of the minutes of D in which the probe
  wrote a row for any candidate; (2) Σ(volume × close)/30 over exactly 30 daily rows ≥ $50M
  (fewer rows fails; volume is in base units, so the figure is an approximation and is printed);
  (3) `liq` occupancy under §3's rule over D's ok rows gives every word ≥ 3 % and ≤ 90 %; (4) not
  a stablecoin. `TICK_p` = the mode, over D's ok rows and both sides, of each side's smallest
  positive level-price step (ties: the smaller). A candidate that fails is named with the failing
  value. If the probe wrote rows in fewer than 95 % of D's 1,440 minutes, or more than 5 % of D's
  candidate-minutes (1,440 × the number of candidates; 432 of 8,640 with six) end in a transport
  failure, D becomes the next UTC day, once, named in §14 before that day starts. Fewer than two passing → v2 runs on `SOL-USD` and what passed, and
  every count written for three products scales with the number of products
  (`DAILY_SPEND_HALT_USD` = 0.25 × products; one table per product; §7's pooling at the actual
  count). Alex approved running the probe from the worktree during v1's sample on 2026-09-29 (~07:00Z; Claude starts it).
  Written before the draft tag: Products: `SOL-USD`, `________`, `________`. `TICK_p`:
  `<P2>` `________`, `<P3>` `________`. Atoms (a10, a90): `<P2>` `________`, `<P3>` `________`.
- **Loops and stores.** One loop process per product (`JEVLOOP_PRODUCT`; unset means `SOL-USD`;
  a value not in `PRODUCTS` exits 2 before any directory is made). `config.store(p)` returns the
  decision log, sends ledger, lock and heartbeat under `data/` for `SOL-USD` and under
  `data/<PRODUCT>/` otherwise. **`data/HALT` stays the one global stop** (the spend trip, a key
  rejection and the nightly write and read only it; every loop and the nightly stop on its
  existence). **`data/PAUSE.<PRODUCT>`** pauses one product's sends: that loop skips the send and
  writes the existing absence `halt`; observation and t + h outcomes continue; the nightly and the
  spend guard ignore PAUSE. `make status`, the dash and the report show HALT and each PAUSE. The
  one-process mode (one loop ticking `PRODUCTS` in sequence) is built and tested in the draft tree
  as its own plist; moving to it, should the shakedown show `feed: http-429` lines, changes
  launchd only, not the repo.
- **Spend.** One tripwire over the products' decision logs (`DAILY_SPEND_HALT_USD` = 0.25 × the
  number of products). The nightly's table sends (81 per product a night, about $0.01) never
  reach a decision log and fall outside it; they are bounded by `policy_table.py`'s deadline, its
  failure limits and its per-send HALT check.
- **No statistical warm-up** (PREREG-v1 §2 stands). The operational shakedown is one day per
  product after the switch.
- **T_first_v2** = the latest, over products, of each product's first live row carrying the draft
  tree's SPEC `spec_sha`. **T0_v2** = the first minute boundary ≥ T_first_v2 + 86,400 s, written
  into §12 at sealing. The seal falls in [T_first_v2, T0_v2) (§13 says what happens if it does
  not). Probe and shakedown rows enter no test.
- **Days** are T0-anchored: d N = [T0_v2 + 86,400 (N − 1), T0_v2 + 86,400 N), N = 1 … 28 (Alex,
  2026-09-26; ERRATA.md). **Sample window** = every row with T0_v2 ≤ tick_id < T0_v2 + 28 · 86,400 s,
  cut before any replay. A product-day excluded by stop rule 3 removes that product's blocks (and
  its rows, for row-level descriptives) from every statistic; it removes no row from the replay (§4).
- The v1 stream keeps sending through the switch under §0's clause; its rows between 2026-10-23
  21:40Z and T0_v2 are logged and reported by `make health` and enter no test of either block.

## 3. The alphabet: `liq` re-cut in a price-free unit, the rest unchanged

Three of four adjectives are relative already (`flow` by the window's own p10/p90, `trend` by
its own sd, `vol` by its own median) and occupied every word on the v1 health look (report §2:
quiet 11 %, bot_war 10 %, dumping 15 %, pumping 13 %, calm 18 %, violent 20 %). `liq` is
absolute and dead (§0.2), and its feature is quantised: at a level-1 fill, `fill1k_bps` is the
half-spread, 50 · k / P bps for a spread of k ticks at price P on a 1c tick, so a cut in bps
moves with the price. v2 counts spread ticks instead:

- **h = fill1k_bps · mid / (1e4 · TICK_p / 2)**: the fill cost in half-tick units; at a level-1
  fill, the spread in ticks. `TICK_p` is per product in `config.py` (0.01 for `SOL-USD`; §2's
  probe reads each added product's from its book grid).
- **`deep` ⇔ h < a10 + 0.5; `thin` ⇔ h > a90 + 0.5**, where a10 and a90 are the integer atoms
  nearest the nearest-rank p10 and p90 of h over the product's window; if `thin` then holds
  < 3 % of the window's rows, once, `thin` ⇔ h > a90 − 0.5. `fill1k_short` stays `thin`. `normal`
  otherwise; where the cuts overlap, `deep` is read first. Every word must hold ≥ 3 % and ≤ 90 %
  of the window's rows (this is the eligibility test for an added product, §2; if `SOL-USD`'s
  window fails it, the rule is restated in §14 before the draft tag).
- **Windows.** For `SOL-USD`: the v1 sample's live rows in [2026-09-25T21:40Z, 2026-09-29T04:30Z),
  by `~/Projects/jev-paper-loop-v2/bin/fill1k-quantiles --log ~/Projects/jev-paper-loop/data/decisions.jsonl
  --t0 20260925T214000Z --until 20260929T043000Z --tick 0.01`, which reads `mode`, `absence`,
  `tick_id` and `product` to select live SOL rows and, of each, only `features.fill1k_bps`,
  `features.fill1k_short` and `features.mid` (its source is scanned for the words it must not
  contain), excludes short rows from the quantiles while counting them, and prints N, the
  p10/p50/p90/p99/max of `fill1k_bps` and of h, the atoms and each word's occupancy. Its output
  on 2026-09-29 06:30Z, its selection and quantile lines verbatim (one fact per line; the
  header lines naming the log, window, base, tick and the parsed/not-live/outside-window counts are
  left out here and are in the tool's output):
  ```
  live_rows: 3877
  short_rows_excluded: 0
  quantile_rows: 3877
  fill1k_bps_p10: 0.4170
  fill1k_bps_p50: 0.8427
  fill1k_bps_p90: 1.6541
  fill1k_bps_p99: 2.4526
  fill1k_bps_max: 3.7485
  h_p10: 1.0000
  h_p50: 2.0000
  h_p90: 3.9915
  h_p99: 5.9600
  h_max: 8.9706
  a10: 1
  a90: 4
  rule: deep iff h < 1.5; thin iff h > 4.5 or fill1k_short; normal otherwise
  thin_fallback: no
  deep: 641/3877 16.53%
  normal: 2990/3877 77.12%
  thin: 246/3877 6.35%
  every_word_within_3_90: yes
  ```
  **So for `SOL-USD`: `deep` ⇔ h < 1.5 (a one-tick spread), `thin` ⇔ h > 4.5 (wider than four
  ticks).** For an added product: `bin/probe summarize probe/2026-09-30`, which applies the
  quantiles tool's own rule (imported) to D's ok rows; its atoms are written into §2.
- **Arm C's rule and its truth table are unchanged.** What moves is which live ticks read
  `thin`, and so which rows fill each state in row-built tables (the digest's per-state table).
  The synthetic 81-state answer tables (arm D, candidate scoring) do not depend on the cuts.
  `RULE_C`'s pin for `SOL-USD` is unchanged; one pin per added product, whose base prefixes the
  state string, is set at the draft tag.
- `liq` counts spread ticks, so its occupancy may still drift with the price over 28 days; the
  > 95 % occupancy flag (CONTRACT §4.2) reports that, and nothing is re-cut mid-sample.

## 4. Cadences, the sampling unit, and the pooled statistic

**Cadences.** The loop decides every minute. A cadence c ∈ {900, 3600, 14400} s is a
REPLAY-TIME transform, `book.at_cadence(rows, c, t0)` with t0 = T0_v2 (the book has no T0 and
T0_v2 is not aligned to c): within each c-block [T0_v2 + c·j, T0_v2 + c·(j+1)), an arm's intent
is its `argmax` (or the named column) on the block's **decision row** — the first row of the
block in `book._order` (least `tick_id`, then `ts_rx`) on which `book.replay` would not force a
hold: a live row, priced (`bid`, `ask` and `mid` all pass `book._px`), whose `columns.a` and
`columns.b` are not both null or argmax-null (`book._intent`'s test) — and `hold` on every other
row of the block. The decision row is shared by every arm: A and B read `columns.a`/`columns.b`,
C reads `rule_c`, D reads `columns.d` (null means hold for D only). A block with no decision row
holds throughout. The transformed intents feed `book.replay`, so the book, the marks, the spread
and the fee columns are SPEC §10's. **c = 900 keeps v1's 15-minute block but not its policy**:
v1 decided every minute and summed d_t over the block; v2's primary acts on the decision row's
intent once per block and holds it until an opposite decision, so v2's H1 is not v1's H1. The
minute-cadence B − C (v1's design applied to v2's arms; not v1's quantity) is printed beside it,
descriptive, so v1 and v2 can be read side by side.

**Replay and exclusion.** Per product, `at_cadence` and `book.replay` run from flat at T0_v2
over every row of the sample window, excluded days included (the v1 code's reading, ERRATA
PREREG §4/§8.3, settled here). An excluded product-day's blocks are then dropped from S_k,p. A
position carried into an excluded day is marked on that day's priced rows; where an excluded
day has no priced row, the move across it lands on the first priced tick after it (SPEC §10),
in a kept block that stays kept. **`gap_blocks`** = the kept blocks of the cell's cadence that
hold the first priced tick after more than 900 s without a priced row, whatever the cause (an
excluded day, an outage, HALT or PAUSE), printed per cadence.

**Unit and statistic** (per cadence c, per product p): block k = the rows with
T0_v2 + c·k ≤ tick_id < T0_v2 + c·(k+1); **S_k,p(X − Y, col, fee)** = Σ over the block's rows of
d_t from `book.paired(at_cadence(rows_p, c, T0_v2), ·, X, Y, col, fee)`.

**Pooling.** Crypto products move together, so the products are not three independent samples
and are never treated as such. The pooled unit is the TIME block: **S̄_k = mean over the
products p not void under §9.4 whose day containing block k is kept (§9.3) of S_k,p**; a block
with no such product is dropped (no placeholder). n at c = 900 is at most 96 × 28 = 2,688
pooled blocks; at 3,600, 672; at 14,400, 168. Per-product series are printed beside the pooled
one, descriptive. A **disagreement tick** is a tick going into or out of which the two arms are
on different SIDES, long vs flat (`report._disagreement`); a **pooled disagreement block** is a
pooled block with at least one kept product's disagreement tick, and the count of disagreement
product-blocks is printed beside it.

## 5. H1 (the one primary): the nightly's arm beats the rule, pooled, decided once per 15-minute block

- **Statistic:** mean over the sample's pooled blocks of S̄_k(B − C, `argmax`, `FEE_BPS_PRIMARY`
  = 0.0) at c = 900 s: direction net of the spread, gross of fees (PREREG-v1 §4's reasoning
  stands; the venue's fees are arithmetic, §6).
- **Hypothesis:** H0: mean ≤ 0; H1: mean > 0. One-sided, **α = 1/40 = 0.025** (v1's level, kept
  for comparability although v2 has one primary).
- **Inference:** circular block bootstrap of the pooled block series in block order, block
  length **L = 4 units of the cell's own cadence** at every cadence (1 h at 900 s, 4 h at 3,600 s,
  16 h at 14,400 s; the draw below is the definition and L is kept by choice), R = 10,000
  resamples, **seed 20261023**, each resample the same length as the series: the draw of
  PREREG-v1 §5 step 2 (`inference.resample_indices`: ⌈n/4⌉ starts per resample, each
  `rng.randrange(n)`, four consecutive wrapped units from each, concatenated in draw order,
  truncated to n) over step 1's indexing of this cell's pooled series, with this cell's seed in
  place of 20260923 and the mean in place of step 3's r; one `random.Random(seed)` per cell.
  **The bound is `sorted[⌈α·R⌉ − 1]` of the R sorted resampled means, nearest rank, integer
  arithmetic, no interpolation: `sorted[249]` at α = 1/40 (H1), `sorted[62]` at α = 1/160 (every
  family-F cell, §6, and stop rule 1's A − C).** Reject H0 iff the bound is > 0. Ties (S̄_k = 0)
  stay in. α is carried as an exact fraction in code, never as a float.
- **Reported beside it, no inference:** the same cell per product; the pooled disagreement-block
  count and share and the mean on disagreement blocks only; trades/day per arm and product; the
  minute-cadence B − C; the cell at every fee of §6; the `gap_blocks` count.

## 6. The claimable family, the fee arithmetic, and everything descriptive

**Family F (claimable), each at α = 1/160 = 0.00625 with `sorted[62]`, the §5 procedure with
seed 20261023 + i, in this order:**

| i | cell | what it says if rejected |
|---|---|---|
| 1 | B − C, `argmax`, 0 bps, c = 3,600 | B's decisions, acted on once an hour, beat C's |
| 2 | B − C, `argmax`, 0 bps, c = 14,400 | … acted on every four hours |
| 3 | A − C, `argmax`, 0 bps, c = 900 | a fixed non-rule prompt beats the rule (v1 could not ask this) |
| 4 | B − A, `argmax`, 0 bps, c = 900 | the nightly adds to the frozen prompt (stop rule 2 reads its sign; §9.2's NO PROMOTION case withdraws this cell) |

Claims are at a nominal one-sided family-wise error rate of at most 0.05 (Bonferroni: 0.025 for
H1 plus 4 × 0.00625 for F); the percentile bootstrap's actual size may exceed nominal, most at
c = 14,400 (§7). H1 is not a member of F.

**Descriptive, printed, never tested:** B − C, A − C and B − A × every column (`rules.COLUMNS`,
11); D − B and D − C at `argmax` only (D's table holds the action choice alone); each × every
fee × every cadence, per product and pooled. `FEE_BPS_COLUMNS = (0, 2, 10, 25, 50, 90)`: 0 =
gross (the primary), 2 = Binance.US, 10 = the article's, 25, **50 = the venue's retail maker,
90 = the venue's retail taker, both read in-account by Alex on 2026-09-27** (ERRATA.md, the
SPEC §10 row; `FEE_BPS_VENUE = 90.0` with its source line filled). v1's unverified 60 and 120
bps columns are replaced by the verified 50 and 90.

**The fee arithmetic (descriptive; the money question answered by subtraction).** Per product
p and cadence, on the `at_cadence` replay, with the affine fact that positions do not depend on
the fee (SPEC §10; the fee enters only the fills):

1. **Each arm's own break-even fee.** E_X,p(f) = Σ of `book.replay`'s pnl for arm X on p's
   `at_cadence` rows over the ticks of p's kept days (an open position at the window's end is
   marked; a fill counts when its tick is on a kept day); pooled E_X(f) = Σ over non-void
   products of E_X,p(f). f*_X = 90 · E_X(0) / (E_X(0) − E_X(90)) bps per fill, from the 0 and 90
   columns. "X never pays" when E_X(0) ≤ 0; undefined when X has no fill. Printed for A, B, C
   and D, pooled and per product, plus a buy-and-hold line over the same span.
2. **Tiers.** The venue's published spot schedule (§12: every row of the schedule at
   coinbase.com/advanced-fees read in-account at sealing; no stable-pair, promotional or
   subscription schedule; if it differs from ERRATA's 2026-09-27 reading, both are printed). A
   tier's round-trip cost is 2 × its taker fee (the book fills at ask and bid, SPEC §10); 2 ×
   maker is printed beside it labelled "needs a passive-fill model not measured here". A tier is
   named for X when its taker fee is below the pooled f*_X, beside the tier's 30-day volume and
   X's own 30-day volume: Σ over non-void products of (fill value on p's kept days × 30 / p's
   kept days), one account-level figure per cadence.
3. **Pairs.** Δ_p(f) = E_X,p(f) − E_Y,p(f) = Σ_k S_k,p(X − Y, f) exactly; pooled Δ(f) = Σ_p
   Δ_p(f), affine in f. If Δ(0) = Δ(90): "fees cancel" (Δ(0)'s sign at every fee). Otherwise
   f*_XY = 90 · Δ(0) / (Δ(0) − Δ(90)). If f*_XY > 0: "X stops beating Y above f*_XY bps per
   fill" when Δ(0) > 0, and "X starts beating Y above f*_XY bps per fill" when Δ(0) < 0. If
   f*_XY ≤ 0: "the sign of Δ(90) holds at every fee > 0". Never "pays".
4. Pooled figures are sums over kept product-days, never averages of per-product ratios.
5. Costs above $1,000 notional are not measured.

**Arm D (descriptive, with a pre-registered reading).** Agreement(p, v) = #(live rows with
`columns.d` non-null and `columns.b.argmax == columns.d`) ÷ #(live rows with `columns.d`
non-null), per product p and prompt version v; each cell prints its denominator and its null
count, and a nonzero null count marks the cell a table defect that is not read. **Lookup
reading: at least one readable cell, and every readable cell ≥ 0.99** → the per-minute call is
a lookup of its own table; no readable cell → "D not read: table defect". **Drift reading: any
readable cell < 0.95** → Jev's live answer depends on something other than the state string;
the causes to name, in order: the other questions in the table's request (the candidates and
CURRENT, against `a_action`, `b_action` and the nouls in the live request), the days between
table and tick, drift (`model_answered`), non-determinism. Between: reported per cell. Beside
it: within-state live consistency, and the count of states seen ≥ 10 times whose modal live
answer differs from the table's. Answer-level, withheld with §4–§7 until day 28.

**Direction probabilities (descriptive; v1's H2 retired).** `up15`, `down15`, lean, Brier
against the base rate, the measured-tail counts, and r(lean, ret_h) with the `trend`-word
comparator, as PREREG-v1 §5's beside-numbers, per product. No hypothesis: on the shakedown lean
was the `trend` word and never reached a tail.

**Health (report §1–§3, `make health`, readable any day):** test-retest (rows with
`prompt_a_sha == prompt_b_sha`: every row until the first promotion, none after), occupancy per
word and product, drift count, fill, absences, spend. **Answer-level descriptives, withheld
with §4–§7 until T0_v2 + 28 d:** A's agreement with C, the D-agreement, every cell above.

## 7. Power, honestly

Per product at c = 900 the arithmetic of PREREG-v1 §7 stands: sd of a 15-minute paired
difference ≈ 33 bps (SOL's v1 guess), z = 1.960 + 0.842 = 2.802, MDE = 2.802 · sd / √n =
**1.78 bps per block = 171 bps/day** at 2,688 blocks. At family F's α = 0.00625 (z = 2.4977 +
0.8416 = 3.3393) every MDE is × 1.192: 2.13 bps/block at 900 s (cell 3), 8.5 at 3,600 s
(cell 1), 34.0 at 14,400 s (cell 2); 204 bps/day per product at ρ = 1 and 118 pooled at ρ = 0.
Cell 4 (B − A) gets no all-block figure: before the first promotion A and B ask the same wording
as two questions, so B − A there is test-retest noise, and a rewrite's effect can live only on
the days after a promotion (at most 21 of 28).

**The effective-n caveat.** The information lives on the blocks where the arms' SIDES differ.
For `SOL-USD`'s v2 table, before any promotion and where B answers as its table, B's and C's
intents differ on the 27 `vol violent` states, but their sides differ only from a violent tick
that finds B long, until B's next buy or non-violent dump (C long implies B long), so the
disagreement-block share is unknown before the data and may be above or below the one-fifth
`violent` occupancy; other products, live deviations from the table and promoted wordings can
differ elsewhere. PREREG-v1 §7's table gives n_eff and the MDE per agreement share; day 28
prints the measured share per cadence.

**What pooling buys.** With pairwise correlation ρ between the products' block differences the
pooled mean's variance is σ²(1 + 2ρ)/3. Crypto products' 15-minute returns correlate at roughly
0.6–0.8, but the arms' DIFFERENCES correlate less (they depend on each product's own words), so
ρ is unknown before the data and is printed at day 28:

| ρ | variance factor | pooled MDE per block (α 0.025) | per day |
|---|---|---|---|
| 0.0 (independent) | 0.33 | 1.03 bps | 99 bps |
| 0.5 | 0.67 | 1.46 bps | 140 bps |
| 0.7 | 0.80 | 1.59 bps | 153 bps |
| 1.0 (one product thrice) | 1.00 | 1.78 bps | 171 bps |

Computed with the exact z = 1.95996 + 0.84162 = 2.80159 and sd 33 bps per product, equal σ and
ρ, all three products kept. With unequal σ_p the factor is ΣΣ ρ_pq σ_p σ_q / (9 · 33²). A pooled
block with two products kept carries (1 + ρ)/2, one with a single product kept carries 1.

**Cadence.** Under v1's arithmetic (a random-walk mid, a side difference on every block) the
daily MDE is AT MOST 171 bps/day per product at α 0.025 and 204 at F's α, where cells 1 and 2
are read: holding the decision for c seconds multiplies the per-block sd by √(c/900) and divides
n by c/900. Below that bound the all-block MDE scales with √f_c, where f_c is the
side-disagreement share at cadence c, while the MDE per disagreement block scales with 1/√f_c
(PREREG-v1 §7's two columns); both are printed per cadence at day 28. At c = 14,400 the bound
rests on ≤ 168 units and 42 drawn blocks per resample, and a percentile bound from so few blocks
tends to under-cover; accepted now: cells 1 and 2 are there to be read beside the primary, and
their rejection would be a strong result, not an expected one.

**The 56-day lever.** Doubling the block to 56 days cuts every MDE by √2 (121 bps/day per
product). v2 keeps 28 days for comparability with v1 and so that the nightly has a month of
nights and at most three promotions; a third block may take 56 and say so before its own T0.

## 8. The treatment: what the nightly is, what is fixed, what is only logged, and when a person may promote

The treatment under H1 is the nightly rewrite AND its inputs. **Fixed before the draft tag and
unchanged through the block:** `nightly/PROMPT.md` (v2 text, quoted in full in the build), the
digest's content (`nightly/digest.py` source, pinned), the slow model id (below), the call's
shape (an empty temp cwd; tools off; `nightly/settings.json`; the 45-min cap; **no user memory:
`propose.sh` exports `CLAUDE_CONFIG_DIR` as a fresh `mktemp -d` outside the repo, created and
removed each night like the work dir, for the call and for `answered_model.py`, and fails the
night, sending nothing, if that directory holds `CLAUDE.md`, `CLAUDE.local.md`, `rules/`,
`skills/`, `agents/` or `plugins/`; it logs "user memory not loaded"**). **Logged, not fixed:**
the CLI version (it cannot be pinned) and the answering model line each night.

**One trial night before the draft tag** — a real `claude -p` call, not `propose.sh --dry`,
which makes none — runs from the worktree with `--root` a temp dir outside both checkouts,
holding a synthetic three-product log from `tests/synth.py`, and `--date` that log's day; it
writes nothing under the live repo's `data/`, `logs/` or `proposals/`, and only its exit code
and its `claude model` and "user memory not loaded" lines are read. It must exit 0, the OAuth
token must answer, and `claude model` must log exactly one id. (Whether `--settings` applies under
the fresh config dir cannot be shown with tools off: the trial prints NOT SHOWN for it, and the
clause is withdrawn, §14.) If it fails on the config dir, the fallback before the
tag is to pin the user-memory sha instead (`propose.sh` logs FAIL and makes no call on any other
sha, and `~/.claude/CLAUDE.md` is left unedited until T0_v2 + 28 d). The change of the
treatment's context versus v1 is recorded for the write-up (ERRATA.md's precedent).

- **`nightly/PROMPT.md` (v2):** the v1 rules, plus: the product name is the first word of the
  state and the wording must read identically for every product up to the base token (one
  CURRENT for all); the measured fact that Jev reads "volatility is calm" as "not violent"
  (`proposals/2026-09-25.review.md`, a synthetic-table fact), so a candidate whose only lever is
  calm-vs-normal changes nothing; no numbers, full text, one to three candidates, only `action`.
- **The digest (v2 content):** covers the UTC day just closed (CONTRACT §5; `propose.sh`'s
  default date) and only rows carrying the v2 SPEC's `spec_sha`, so the switch-day digests
  never mix v1-code rows in; per product and pooled, the summary line at 0 bps and at the
  verified maker and taker; **every arm-B figure from rows whose `prompt_b` is the version
  `prompts.current(tick)` names for that row's tick** (v1's summary line replayed B over a
  promotion day's mixed rows, HANDOFF.md's prereg-v2 note); the disagreement rows (confidence
  ≥ 0.85, up to 25) as before; and new, a **per-state table** over the 81 states per product:
  rows seen, B's choice distribution, mean `ret_h_bps` and the label rates at the 15-minute
  join, that day's. Nothing in the digest is a test.
- **The slow model, pinned:** `claude -p --model <id>`, where id is the one on the `claude model`
  line of `logs/propose.log` from the run of 2026-09-29 08:30Z; if that line is `unrecorded`,
  lists more than one id, or is missing, the first later v1 night whose line is exactly one id.
  Written here with the night it came from, before the draft tag: **id `claude-sonnet-5` (night
  2026-09-29 08:30Z; the log's line reads `claude model claude-sonnet-5 (read from the CLI's transcript of
  this call, which names no model)`).** If the id is refused on the trial night (before the draft tag), one substitute
  is allowed by this rule alone and written here before the draft tag: the latest v1 night before
  the draft tag whose line names exactly one id. From the draft tag on there is no substitute: a
  refusal at the switch, in the shakedown or on any later night fails that night like any failed
  night — no proposal; the report counts failed nights with their reasons, and if no promotion
  results §9.2's NO PROMOTION reading applies.
- **Scoring a candidate:** `policy_table.py` (v2) renders `state_string(adj, base)` per product
  and, beside `proposals/<date>.md`, writes `proposals/<date>.table.json` holding every wording's
  81 answers per product, with its sha in the committed .md (the `.table.json` stays gitignored,
  vouched for by that sha; `bin/promote` refuses on a mismatch); one request per state carrying
  the candidates and CURRENT (81 per product; `DEADLINE_S` scaled by the product count). Jev's
  answers on synthetic strings, never a backtest; under each candidate the table says which
  states move from CURRENT's answer. An unanswered state is re-sent only by
  `python3 -m nightly.policy_table --fill proposals/<date>.table.json` (attended; it asks only
  unanswered states, writes their answers into the same file and the new sha into the .md; an
  answered state is never re-sent).
- **Promotion (Alex alone, `bin/promote`), on a pre-registered schedule enforced in code.**
  Effective days E with **8 ≤ E ≤ 22**, E_k − E_(k−1) ≥ 7, none during the shakedown: at most
  three promotions (days 8, 15, 22). `bin/promote` may run at any time on day E − 1 and refuses
  when now ≥ activation − 600 s. It writes `prompts/v<N>.json` with `activation_tick`
  (= T0_v2 + 86,400 · (E − 1)) and `replaces` (the version active when it ran), the tables, then
  CURRENT; **`prompts.current(tick_id)` follows `replaces` while tick_id < activation_tick**; a
  second pending version is refused. Every reader calls `current(tick_id)` with the tick it
  describes: the loop its own tick, the digest each row's tick, `policy_table` and `promote` now,
  dash and status now with a pending version shown on its own line; so every row and every
  c-block of a product-day carries one `prompt_b`. A hand edit of CURRENT after T_first_v2 is a
  deviation; RESULTS-v2 §0 prints each product-day's `prompt_b` set and names any day with two
  values. `bin/promote` reads T0_v2 from this file's §12 and refuses while it is blank; refuses
  E < 8, E > 22 or spacing < 7; refuses without the `prereg-v2-seal` tag (`PREREG_TAG` becomes
  `prereg-v2-seal`); refuses a candidate whose table moves 0 of 81 states on every product;
  copies candidate k's per-product column from the proposal night's `.table.json` under an 81/81
  refusal and refuses unless the table's CURRENT sha equals the sha of the version CURRENT names;
  writes the tables before CURRENT changes; the person's reason is one line in the promote
  commit, with the states moved. `bin/promote --table-only <proposal.json>` is attended, sends
  nothing (promote never sends, with or without it), and keeps promote the only writer of
  `prompts/`.
- **v2's own tables, before the draft tag:** `prompts/v2.table.<product>.json` for `SOL-USD` and
  the probe products, from a `policy_table.py` (v2) run on a proposal with no candidates
  (CURRENT = `v2` only), named in §14 (attended, 81 sends per product, ~$0.01), copied by
  `--table-only` (which refuses unless the table's CURRENT sha equals `prompts/v2.json`'s),
  committed with the answering Jev version and pinned. If a different Jev version answers at the
  switch, the tables are rebuilt once under the same rule and the new shas and version go into
  §12's line for it.

## 9. Stop rules — fixed now

1. **Day 28, neither A nor B beats C on H1's cell** (B − C at α 1/40, §5; A − C at F's α 1/160,
   §6 i = 3, stricter than v1's stop-rule-only 0.025) → the model arms are retired for this block
   (sends stop at day 28); C and the feeds keep logging only if a third pre-registration wants
   them, which may re-open a cadence §6 i = 1 or 2 rejected, as v2 re-opens v1's arms.
2. **B − A ≤ 0** at day 28 (point estimate of the pooled mean S̄_k(B − A, argmax, 0 bps), c = 900,
   over all kept blocks) → the nightly is stopped (its plist booted out); A is kept. **If no live
   row on a kept product-day of a non-void product has `prompt_b_sha ≠ prompt_a_sha` (CURRENT
   never left `v2`), stop rule 2 reads NO PROMOTION:** the nightly is stopped because it produced
   no promoted candidate, not because of B − A's sign; §6 i = 4 is not read, and B − A is reported
   as test-retest, descriptive only. Pre-promotion test-retest blocks stay in: that is the
   pre-registered intent-to-treat.
3. **A BAD product-day is excluded, logged, and three of them pause that product.** A product's
   T0-anchored day is BAD when its outcome fill (live rows whose t + h the log has reached, with a
   non-`gap` outcome, over such live rows) is < 95 %, or its Jev error share (rows with `absence:
   "jev"`, every error kind, over rows with `mode: "live"` and `absence` null or `"jev"`; ERRATA
   PREREG §8.3's reading, `report.py days_table`) is > 5 %. **A product-day with no live row is
   excluded whole** (Alex, 2026-09-29). **The rule recomputed from the log governs.** The file is
   Alex's log of what he saw: `data/exclusions-v2.tsv`, header `day<TAB>product<TAB>fill%<TAB>
   jev-err%<TAB>reason`, days d01–d28 of T0_v2; the v2 parser returns {(N, product)} and refuses a
   line whose product is missing or not in `PRODUCTS`; written the morning after by Alex. At day 28
   inference uses the recomputed set, prints the file verbatim beside it and names every
   disagreement; a listed day the rule judges fine is not excluded. On a product's third BAD day
   its sends pause by hand: `data/PAUSE.<PRODUCT>` with the reason line "prereg: 3 bad days",
   removed when the cause is fixed; observation continues; the calendar does not stop.
4. **Void.** A product with fewer than 21 kept days is void for v2 and leaves the pool; rules 1–2
   are read on the remaining pool. If no product has 21 kept days the block is void, reported as
   void, and reads neither rule 1 nor 2 (as v1's `inference.reading()` does); rules 3, 5 and 6
   bind regardless. A third block is a new pre-registration.
5. **The day-14 look is health only:** `make health` (report §1–§3 per product and pooled).
   Withholding reads T0_v2 from this file's §12, whatever `--t0`, `--since`, `--prereg` or `--log`
   say, and withholds §4–§7 whenever the rows read include one with T0_v2 ≤ tick_id < T0_v2 + 28 d,
   SOL's rows in `data/decisions.jsonl` included; while §12's T0_v2 is blank it withholds them over
   every row carrying the v2 `spec_sha`; v1's own withholding is kept beside it. `report --unblind`
   is a look: it appends (UTC, argv, HEAD) to `data/looks.tsv`, which RESULTS-v2 §0 reproduces.
   No bootstrap runs before day 28.
6. **No extension after looking.** The sample ends at T0_v2 + 28 days whatever the numbers say.

## 10. The build, the freeze, and the switch

**Built** on branch `prereg-v2` in the worktree `~/Projects/jev-paper-loop-v2` (no `data/`
there, so no report or result can be computed there by accident; the build is blind by
procedure, header), tested by `make test` and CI, **complete, committed and pinned BEFORE the
draft tag**, merged to `main` only after RESULTS.md (v1) is committed on 2026-10-23, then
installed by the switch below. Nothing changes what a v1 row means; v1's rows are read as before, but
the report's fee columns over the v1 log are v2's (50 and 90 in place of 60 and 120). v1's
committed result and its cells are reproduced from `results-v1` only by `loop.report --sample
--log <the live SOL log>` and `loop.inference --sample --log … --out …` (STEPS §10.5); a v1 row's
`spec_sha` resolves with `git show prereg-v1:SPEC.md`; no reader prints §4–§7 over a v2 sample
row before T0_v2 + 28 d, v1's `loop.inference` included (it applies this file's withholding after
its own cut). **The backup-job fix (STEPS §9) and any other `main` tooling
land before the draft tag.**

- **SPEC (v2 sha on every v2 row):** §2 `product` takes the loop's `JEVLOOP_PRODUCT` (the key
  exists on every row, `loop/cycle.py`; always `SOL-USD` in v1); the row gains `columns.d` and
  `table_sha`; `prompt_a`/`prompt_a_sha` come from `FROZEN_A` instead of the literal `v1`; §5
  `liq` in h with per-product `TICK_p` and atoms; §6's `liq` sentence points to the per-product
  cuts, the truth table unchanged; §7 four arms, A = `v2`; §10 fee columns (0, 2, 10, 25, 50, 90),
  `FEE_BPS_VENUE = 90.0` verified, the "Verified tier-0 taker fee" row filled; §13.2 step 2 gains
  PAUSE; §14 the new constants (`PRODUCTS`, `TICK_p`, the atoms, `CADENCES = (900, 3600, 14400)`,
  `FROZEN_A = "v2"`, `DAILY_SPEND_HALT_USD`). SPEC v2 names §12 for T0_v2 and the fee tiers and
  restates neither. ERRATA.md's SPEC and PREREG rows that describe what the code already does
  are folded into the text.
- **config / cycle / feed / state:** `config.PRODUCTS` fixed at the draft tag; `config.store(p)`;
  `HALT`, `PAUSE.*`, `exclusions-v2.tsv` and `looks.tsv` at `REPO/data/` (dash and status stop
  building HALT from `--data`); `state_string` takes a base; the spend guard sums every product's
  log; the row carries `columns.d` and `table_sha`; a test with `JEVLOOP_PRODUCT` unset asserts
  every v1 path and the `RULE_C` pin unchanged. Each added plist has its own log
  (`logs/loop-launchd-<product>.log`); the one-process plist (§2) is built and tested beside them.
- **prompts:** `build(frozen_a, current, base)` renders the base token (§1); `current(tick_id)`
  honours `activation_tick`/`replaces` (§8; CONTRACT §5 amended); `bin/promote` as §8, its
  `PREREG_TAG` `prereg-v2-seal`.
- **book:** `at_cadence(rows, c, t0)`; `ARMS` gains `d`; `_intent` for `d` returns
  `columns.d` at `argmax` and raises on any other column; the every-arm forced hold applies to D;
  a null `columns.d` on an otherwise answered row is a hold for D only, counted in D's forced
  holds; `report.PAIRS` gains (d, b) and (d, c) at `argmax`.
- **exclusions:** a v2 reader beside `loop/exclusions.py` (v1's stays unedited); the new default
  path in inference, status, report and dash; the per-product recompute; `!data/exclusions-v2.tsv`
  and `!data/looks.tsv` in `.gitignore`; CONTRACT updated. The switch commits v1's
  `data/exclusions.tsv` (or records that it is absent) with RESULTS.md, and nothing appends to it
  afterwards.
- **report / status / dash / inference:** inference, report, dash and `bin/promote` read T0_v2 and
  the fee-tier table from PREREG-v2.md §12 (as `dash.read_t0` reads PREREG.md §11); per-product
  and pooled series; the cadence loop; family F with its seeds and `sorted[62]` (α as an exact
  fraction; `alpha_rank` never the float; F never reuses the 0.025-only `bootstrap()`); the
  D-agreement in a withheld section (HEALTH_N stays 3); the fee arithmetic of §6; stop rules 3–4
  per product; the NO PROMOTION check (§9.2's row set) before `ba` is read; v2's `make results`
  reads all logs, refuses before T0_v2 + 28 d, checks `prereg-v2-seal` and runs `bin/seal-check
  --since prereg-v2-seal` (§13); `--unblind` writes `data/looks.tsv`. `test_invariants.py` holds
  the readers to independent transcriptions of §4–§6 written from the text (H1 seed 20261023 at
  `sorted[249]`; F seeds 20261024–20261027 in §6's order, each at `sorted[62]`; L = 4 units;
  R = 10,000; each cell's bound on a fixed series hard-coded; a golden series on which
  `sorted[61] ≠ sorted[62]`); `test_inference_golden` stays at v1's seed for v1's readers; a test
  with an excluded day between two kept days and arm positions that differ across it;
  `tests/synth.py` gains products and a cadence knob.
- **nightly:** the digest of §8; PROMPT.md v2; `--model` pin; `CLAUDE_CONFIG_DIR`; per-product
  tables, `.table.json` and `--fill` in `policy_table.py`; `propose.sh` passes every product's log
  to the digest and the dash.
- **tools:** `bin/probe` (§2, matching its text: 99 % of the probe's minutes, exactly 30 daily
  rows, `volume --day`, `TICK_p` as defined), `bin/fill1k-quantiles` (§3), `bin/seal-check` (§13,
  with `--draft` and `--since`).
- **launchd:** one loop plist per added product (`com.alexward.jevloop.loop.<product>`) and the
  one-process plist, pinned in `tests/test_nightly.py`; the nightly and backup plists unchanged
  (the backup copies every store). Hand-installed (STEPS §10 v2, written in the build and frozen
  by the draft tag).
- **Tests, beyond each change's own:** `data/PAUSE.<X>` stops only X's sends while X's
  observation and t + h outcomes continue, and `data/HALT` stops every product and the nightly;
  report withholds §4–§7 with no flags, with `--t0` T0_v2 and with `--since`, over
  `tests/synth.py`'s three-product log, and dash and status print health only, neither
  A-agreement nor D-agreement; `bin/promote` refuses with §12's T0_v2 blank, at E < 8, at E > 22,
  at spacing < 7, within 600 s of activation, on a second pending version and without the
  `prereg-v2-seal` tag; a pending version is invisible to the digest and to `policy_table`;
  every added product's table strings begin with its own base; `--table-only` refuses a table
  whose CURRENT sha ≠ `prompts/v2.json`'s.
- **tests/test_frozen.py at the draft tag** pins by sha: SPEC v2, CONTRACT, this file,
  `nightly/PROMPT.md` v2, the sources of `nightly/digest.py` and `nightly/policy_table.py`,
  `prompts/v2.json`, one v2 table per product, `THRESHOLDS` with `TICK_p` and the per-product
  atoms, every §14 constant, the inference constants (seeds, L, R, the ranks), `RULE_C` per
  product; each pin updated in the same commit as the file it pins so CI is green on every push.

**Makefile guard (on `main`, committed before `prereg-v2-draft` and carried into the build by the
pre-tag merge; tooling only, one ERRATA line):** `results` refuses unless
`git rev-parse -q --verify "refs/tags/prereg-v2-draft^{tag}"` succeeds and
`git merge-base --is-ancestor prereg-v2-draft prereg-v2`; `NO_V2=1` overrides and writes into
RESULTS.md "v2 draft tag absent: v2 as drafted is not run; a second block is a new
pre-registration written after v1 was read"; the target echoes the tag's sha into RESULTS.md's
header. v2's own `results` target, in the build, checks `prereg-v2-seal` instead.

**The switch (STEPS §10 v2; 2026-10-23, after `make results`):** (1) `make results` exits 0 (not
before ~21:56Z, when the last block's t + h row exists); (2) commit RESULTS.md with v1's
`data/exclusions.tsv` or a line that it is absent; (3) `git tag -a results-v1 … && git push
origin results-v1`; (4) in the worktree, merge `main` into `prereg-v2`, run `make test` there,
and check `git merge-base --is-ancestor main prereg-v2`, or stop with v1 running; (4a) after
07:30Z on the switch day the nightly is booted out and re-bootstrapped after (11); (5) wait for
the current minute's heartbeat, then `launchctl bootout` the SOL loop; any stop from (6) to (8)
is `git reset --hard ORIG_HEAD` and a re-bootstrap of v1; (6) on `main`,
`git merge --ff-only prereg-v2`; (7) `make test`; (8) if `prompts/CURRENT` does not name `v2`,
set it and commit, naming what it replaced; otherwise record "CURRENT already v2" in HANDOFF.md;
(8a) `data/HALT` absent, or its v1 cause recorded and the file removed; (8b) copy
`launchd/*.plist` to `~/Library/LaunchAgents` and `cmp` each; (9) bootstrap SOL in a later minute
than the bootout; (10) bootstrap the two named products; (11) `make status` shows three
heartbeats; (11a) compare the answering Jev version (`model_answered` of the first shakedown
rows) with the pinned tables' version and, if different, rebuild the tables once (§8, §12). The
merge, not the bootstrap, changes what the next SOL tick writes (`columns.d`, `table_sha`, the
v2 spec sha, A = `v2`). The switch's missed or duplicated minutes precede T_first_v2 and enter
no test. The reading lines of `make results` ("the model arms are retired") do not gate the
switch (§0).

## 11. What would falsify what

- H1 rejected: B's wording (a human-gated rewrite, at most weekly, from nightly proposals),
  decided once per 15-minute block, beat the rule in direction, pooled over these products and
  days. With i = 4 also rejected: the rewrite added to the frozen prompt. With i = 3 rejected and
  i = 4 not: the frozen `v2` wording beat the rule; an addition by the rewrite was not detected
  (its effect can live only on the days after a promotion, §7). If no promotion occurred (§9.2),
  an H1 rejection reads as the frozen `v2` wording beating the rule (B = A throughout), never as
  the rewrite.
- H1 not rejected: no B − C difference detectable at §7's MDE (pooled 99–171 bps/day by ρ) in
  direction, gross, decided once per 15-minute block, on these products over these 28 days (stop
  rule 1 with i = 3); edges below that are not ruled out.
- i = 1 or i = 2 rejected without H1: direction at a longer hold that the 15-minute hold does not
  show; a third block puts that cadence first.
- D-agreement ≥ 0.99 on every readable cell: the fast model is a lookup here, and its cost is 81
  calls per product per promotion.
- No arm's pooled break-even fee f*_X, per cadence (per-product figures printed beside it, not
  read), exceeds the taker fee of any tier its own account-level volume reaches: nothing measured
  here paid at the venue at $1,000; a pair's break-even says only at what fee one arm stops, or
  starts, beating the other.

## 12. Fields filled after the draft tag (and nothing else)

| field | filled when | from |
|---|---|---|
| the venue's fee-tier table (§6) | at sealing | every row of the spot schedule, read in-account, with the read time |
| tables rebuilt at the switch (§8) | at the switch | `no`, or the answering Jev version and one sha per product, under the once-only rule |
| T_first_v2, T0_v2, sealed-by, sealed-on | at sealing | the logs and the person |

Products, their `TICK_p` and atoms, arm A's per-product state counts, the probe approval date and
the slow-model id are set in §1, §2, §3 and §8 BEFORE the draft tag and are not fields here.

Fee tiers (30-day band / maker / taker, read UTC `________`): `________`
Tables rebuilt at the switch: `________`
T_first_v2: `________`   T0_v2: `________`   Sealed by: `________`   on: `________`

## 13. The tags, `bin/seal-check`, and what `main` may take

**Doc tag, once the 2026-09-29 review and its recheck are in:**
```bash
cd ~/Projects/jev-paper-loop && git tag -a prereg-v2-doc -m "PREREG-v2 text after the five-lens review and its recheck" HEAD && git push origin prereg-v2-doc
```
(0) Before any further edit of PREREG-v2.md on the build branch, `main` is merged into
`prereg-v2`. Every later edit before the draft tag is a §14 entry.

**Draft tag, before `make results` on 2026-10-23,** on the build branch, with §1, §2, §3 and §8's
pre-tag values written, the probe's output and one v2 table per product committed and pinned:
```bash
cd ~/Projects/jev-paper-loop-v2 && git merge --no-edit main && make test && git push origin prereg-v2
```
then, once CI is green on that sha:
```bash
cd ~/Projects/jev-paper-loop-v2 && test -z "$(git status --porcelain)" && bin/seal-check --draft && git tag -a prereg-v2-draft -m "frozen before make results (v1)" HEAD && git push origin prereg-v2-draft
```
`bin/seal-check --draft` refuses if any `________` remains outside §12, if `probe/<D>/` or
`prompts/v2.table.<p>.json` is missing for any p in `config.PRODUCTS`, or if PREREG-v2.md changed
since `prereg-v2-doc` while §14 reads "(none yet)".

**From `prereg-v2-draft` until switch step (6), `main` takes only** RESULTS.md, HANDOFF.md,
additions at the end of ERRATA.md, `proposals/`, `data/exclusions.tsv` and v1's `bin/promote`
commits (`prompts/v<N>.json`, `prompts/CURRENT`). Anything else waits for the switch or is a
listed deviation (below).

**Seal,** on `main` after the switch, once §12 is filled and before the first v2 sample row:
```bash
cd ~/Projects/jev-paper-loop && bin/seal-check && git tag -a prereg-v2-seal -m "PREREG-v2 sealed" HEAD && git push origin prereg-v2-seal
```
`bin/seal-check` is committed and tested in the draft tree. It exits non-zero unless all of:
(a) `git merge-base --is-ancestor refs/tags/prereg-v2-draft HEAD`; (b) `git status --porcelain`
is empty; (c) `git diff -U0 refs/tags/prereg-v2-draft HEAD -- . ':(exclude)RESULTS.md'
':(exclude)HANDOFF.md' ':(exclude)proposals' ':(exclude)data/exclusions.tsv'` has hunks only:
inside this file's §12 blank fields; in `prompts/v2.table.<product>.json` and §12's rebuild line,
only under §8's once-only rebuild rule; in `prompts/CURRENT` (its value is (d)); in
`prompts/v<N>.json` (N ≥ 3) added by v1's `bin/promote` and not named by CURRENT; as pure
additions at the end of ERRATA.md; in the `tests/test_frozen.py` lines that pin PREREG-v2.md or
those tables; and in commits listed in ERRATA.md's "v2 deviations" table; (d) `prompts/CURRENT`
is `v2`; (e) `make test` passes. RESULTS-v2 §0 prints the full `-U0` diff, seal-check's verdict,
and the `--stat` of the excluded paths.

**A listed deviation:** a fix needed between `prereg-v2-draft` and the seal that falls outside
(c) is its own commit, one row in ERRATA.md's "v2 deviations" table naming that commit, and its
diff, which seal-check prints and RESULTS-v2 §0 reproduces. A deviation that touches
`at_cadence`, `replay`/`paired`, inference, the pooling or exclusion readers, `rule_c`, the
alphabet or its cuts, PROMPT.md v2, the digest or promote's schedule voids the draft tag: v2 is
then not this pre-registration.

**If the seal is not made before T0_v2,** the block has not started: the loops keep running;
T0_v2 is re-derived as the first minute boundary ≥ (the commit time of the fix that lets
seal-check pass) + 86,400 s, written into §12 at sealing; no row before it enters any test; each
re-derivation is listed in RESULTS-v2 §0. If no seal exists by 2026-11-06, RESULTS.md records v2
as not run and v1's §8.1–§8.2 acts apply from then.

**From `prereg-v2-seal` until T0_v2 + 28 d, `main` takes only** `bin/promote` commits
(`prompts/v<N>.json`, `prompts/v<N>.table.<product>.json`, `prompts/CURRENT`), HANDOFF.md,
`proposals/`, `data/exclusions-v2.tsv` and `data/looks.tsv`. v2's `make results` runs
`bin/seal-check --since prereg-v2-seal` with that allowlist and refuses on any other hunk unless
`NO_SEAL=1`, which it records. RESULTS-v2 §0 prints `git diff -U0 prereg-v2-seal HEAD` and the
set of `spec_sha` over sample rows, which must hold exactly one value.

## 14. Amendments between `prereg-v2-doc` and `prereg-v2-draft`

Each entry: date, author, what changed, and what the author had read (digest included).

- 2026-09-29 ~07:05Z, Claude (Fable 5.1): header — Alex's disclosure line filled ("No, neither"); §2 — the probe
  approval date filled. Nothing else changed. The author had read nothing new since `prereg-v2-doc` (no digest, no
  transcript, no proposal rationale).
- 2026-09-29 ~08:00Z, Claude (Fable 5.1): §2 — the transport-failure share is defined over candidate-minutes
  (the reading `bin/probe summarize` implements); §0.2 — the 0-thin count is attributed to `make health` of
  2026-09-28 21:34Z (3,467 rows with adjectives), the earlier 3,908 was an ad-hoc count and its explanation
  was wrong; §3 — the tool's output quoted line for line as it prints it. Read since the doc tag: the tool
  build's reports (code and tests), nothing of the live log beyond the features-only tool's output.
- 2026-09-29 ~20:05Z, Claude (Fable 5.1): §8 — the pinned slow-model id filled from the 2026-09-29 08:30Z
  night's `claude model` line (`claude-sonnet-5`), exactly one id, the rule's first case. Read since the last
  entry: logs/propose.log's lines for that night and the two header lines of proposals/2026-09-28.md (`proposal
  written by`, `model answered`); no rationale, no digest, no transcript.
- 2026-09-30 ~04:30Z, Claude (Fable 5.1), after the §10 build (seven stages, each built, refuted and fixed; 1,237
  tests; branch `prereg-v2`, this file edited there from now on, §13 (0)). Readings the build fixed where the
  text was silent or wrong, adopted as written unless a section is amended below; each is also in the code's
  docstrings and commit messages:
  - **§10** was wrong that v1's readers read the v1 log "exactly as before": the fee columns over the v1 log
    are v2's; §10 now says so, and names the two commands that reproduce `results-v1`. v1's `loop.inference`
    applies this file's withholding (T0_v2 from §12; a malformed §12 reads blank) after its own cut, exit 3.
  - **§2/§9.5** `make health` = `report --health --pre-sample --sample`: first the rows from v1's end (PREREG.md
    §11's T0 + 28 d) to T0_v2, or every later row while §12 is blank, per product and pooled, no day judged;
    then the sample, or a "none yet" line with exit 0 while §12 is blank.
  - **§2** T_first_v2 is read by `tick_id` (each product's least `tick_id` among live rows carrying the sealed
    tree's SPEC sha; the latest over products); T0_v2 = T_first_v2 + 86,400 s, a `tick_id` already being a
    minute boundary. **§13**'s re-derivation as enforced: a later T0_v2 passes only if a commit in
    `prereg-v2-draft..HEAD` has committer time ≥ the first boundary and (that time + 86,400 s), rounded up to a
    minute, equals T0_v2; the seal's clock (or the annotated tag's tagger date, in a replay) must fall in
    [T_first_v2, T0_v2). `bin/seal-check` checks these as (§2) and §12's fill as (§12) beside (a)–(e).
  - **§4** `gap_blocks`: HALT and PAUSE rows are priced (observation continues), so they make no gap; only more
    than 900 s without a priced row does. **§5** trades/day keeps v1's unit: trades on kept blocks per 1,440 of
    the kept blocks' observed ticks. **§4** the row-level descriptives (A- and D-agreement, direction
    probabilities, confidence, trades/day) read only the rows of kept product-days of non-void products;
    health §1–§3 reads every row because it judges the days.
  - **§6** fee arithmetic runs at `argmax` only, at the three held cadences; "undefined" (no fill on a kept day)
    is judged before "never pays"; "fees cancel" at |Δ(0) − Δ(90)| ≤ 1e-9 bps; pairs are all five of `PAIRS`;
    buy-and-hold buys at the ask of the first priced row on a kept day and holds to the window's end, its one
    fill counting; a position opened on an excluded day brings its kept-day marks into E(0) but not its entry
    fill; "p's kept days" for the 30-day volume = kept blocks × c / 86,400. While §12's tier table is blank or
    unreadable, ERRATA's 2026-09-27 reading (maker 50 / taker 90) is the one tier used for naming. **§12**'s
    tier table form: rows joined by `;`, each `[name:] $LOW-$HIGH / maker / taker` or `[name:] $LOW+ / maker /
    taker`, bands from $0, contiguous, the last open; read time and table both filled or both blank.
  - **§6** D-agreement: when modal live answers tie and the table's answer is among them, the state does not
    differ; the minute-cadence B − C is printed at every column and fee (66 cells).
  - **§8** `--table-only` targets `prompts/v2.json` only, refuses under any `prereg-v2-seal` tag, and accepts only
    a CURRENT-only night (no candidates); the once-only rebuild is enforced after the draft tag and refused
    when the new table's `model_answered` equals the pinned tables'; a promotion, for the count and spacing, is a
    version file with an `activation_tick` in the block that is on CURRENT's `replaces` chain or whose
    activation has passed; a promote that cannot finish removes what it wrote; PROMPT.md rules 4 and 9 are
    applied per candidate (a candidate with a digit or a product word other than `{BASE}` is discarded and the
    rest are scored; a night fails only when none remain); the product-word screen refuses the uppercase bases
    of `PRODUCTS` and the probe candidates as whole words in the four question slots, and nothing else (coin
    names and lowercase forms are the promoter's to catch: rule 9 is his reading, the screen is the floor);
    **a candidate whose rendered action equals CURRENT's is refused** (it moves no state and changes no word
    Jev reads; the flag becomes a refusal, §14 decision); the failed-night count is printed in RESULTS-v2 beside
    §9.2's reading, not in `loop.report`; the nightly's 45-min cap is `${JEVLOOP_CLAUDE_CAP_S:-2700}`, a test
    knob no plist sets. The `--settings` clause of the trial night is withdrawn (§8 amended above).
  - **§8** the promoter reads each proposal's rationale, which may quote the digest's outcome proxies: that is
    the human gate the design has, and it is not a look at §4–§7. Nobody but the promoter reads
    `data/digest-*.md` or `logs/claude-*.txt` during the block.
  - **§9.2** the NO PROMOTION row set is §9.2's; **§9.5** every `report --unblind` appends a look, including
    `--health` and runs where nothing was withheld, into the running tree's `data/looks.tsv` (a look that cannot
    be recorded is refused, exit 2); a `looks.tsv` made between the switch and the seal is a listed deviation.
  - **§13** "exactly one `spec_sha`" is a refusal (exit 3) before any number, overridden only by `NO_SEAL=1`, which
    RESULTS-v2 records; no sample row at all is a void block, not a refusal. RESULTS-v2 §0's seal material is
    `bin/seal-check --at prereg-v2-seal` printed verbatim ((b) and (e) not rerun; the `--stat` of the excluded
    paths included). A listed deviation may be any non-merge commit in `prereg-v2-draft..HEAD`, a fix `main` made
    between the draft tag and switch step (6) included; the VOIDING set (READ lines) adds this file, SPEC.md,
    `loop/prompts.py`, `loop/report.py` and `loop/outcomes.py`; `--since` passes `prompts/v<N>.json` and tables
    with N ≥ 3 as additions only. The seal's clean tree commits the shakedown nights' `proposals/<date>.md`.
    `main`'s readers between `results-v1` and switch step (6) carry no v2 withholding; STEPS §10.5 names the
    only v1 re-reads made there.
  - **§10** pinned by sha beyond the list: `nightly/propose.sh`, `nightly/settings.json`, `nightly/capped.py`
    (the call's shape §8 fixes); every capitalised constant of the named modules is in SPEC §14 unless
    `tests/test_spec.py` lists it with a reason; bin/promote's schedule constants and tags are §14 rows.
  - **§2** one-process mode: `python3 -m loop.cycle --once --every-product` shares one watchdog budget across
    products; a product reached with under 1 s left is not ticked that minute (stderr says so, no row).
  - Read since the last entry: the build's reports (code, tests, refuters' and verifiers' findings), nothing of
    the live log. The probe's rows for D are public feed data.

# PREREG-v2 — the second 28-day block, written before v1 is read

**Status: DRAFT.** Three tags carry it: `prereg-v2-doc` (this text, once the 2026-09-29 review's
changes are in), `prereg-v2-draft` (an annotated tag on the BUILD branch, pushed, made before
`make results` runs on v1 on 2026-10-23: text, SPEC v2, the treatment, the code, the tables, the
probe's output and a `tests/test_frozen.py` that already pins all of it), and `prereg-v2-seal`
(after the switch, once §12's fields are filled, made only by `bin/seal-check`). After
`prereg-v2-draft` nothing changes but §12's fields and the pins that set them; anything else, and
the seal is not this pre-registration. Every edit between `prereg-v2-doc` and `prereg-v2-draft`
is a dated entry in §14 that says what its author had read.

**What was read before this was written.** Nothing of v1's report §4–§7 or of any
`loop.inference` output on the v1 sample: no `--unblind`, no `make results`, no `loop.inference
--sample`. The draft is NOT blind to in-sample nightly material: before drafting, the drafting
session had read `proposals/2026-09-24..27.md` and the 2026-09-27 proposal's candidate
rationales (which quote digest outcomes), `proposals/2026-09-25.review.md` (one day's
disagreement counts; its recommendation is arm A's wording), HANDOFF.md's nightly notes, and the
first twelve lines of `data/digest-2026-09-27.md` (that day's summary line, with each arm's paper
pnl at 0 and 120 bps, and four of its disagreement rows with their 15-minute returns and labels).
Digest pnl is an outcome proxy; an editor who has read one says so here. Whether Alex opened a
`data/digest-*.md` or a `logs/claude-*.txt` directly before 2026-09-29: `________` (Alex states).
Every number here is a health quantity (report §1–§3, PREREG-v1 §8.4), a logged feature of v1's
live rows read with no answer or outcome beside it (§3, by `bin/fill1k-quantiles`), a synthetic
policy-table fact (`proposals/`), or a shakedown fact printed in the sealed `PREREG.md`. Until
`prereg-v2-draft`, nobody editing v2 opens a digest, a nightly transcript, or a proposal
rationale dated 2026-09-28 or later; an exposure is logged in §14.

Everything measured is defined in `SPEC.md` as revised for v2 (§10; every v2 row carries the
revised sha); nothing here redefines a number. "Block k" below is the c-second unit; "the block"
elsewhere is the 28-day experiment; the bootstrap resamples runs of L = 4 units.

## 0. What v1 could not answer, what v2 changes, and that v2 runs whatever v1 says

v1 (PREREG.md) asks whether a nightly rewrite of one typed question makes Jev decide better
than the rule its thresholds imply, on one product, deciding every minute, with a frozen arm
that restates the rule. Four things are known before any v1 result is read:

1. **Arm A is arm C.** `v1`'s action criteria restate `rule_c` (PREREG-v1 §5: 181/181 on the
   shakedown), so A − C is zero by construction and the frozen-prompt arm measures nothing.
2. **One adjective is dead.** `liq` read `thin` on 0 of 3,908 live rows of the v1 sample through
   2026-09-29 04:30Z and 48 of 81 states had occurred (report §2, a health quantity). The cuts
   (`deep` < 1.0 bps, `thin` > 5.0 bps of fill cost) sit outside where the fill cost lives (§3).
3. **Jev does not call direction.** `up15`/`down15` sat in 0.26–0.63 on the shakedown and lean
   tracked the `trend` word at r 0.99 (PREREG-v1 §5). A co-primary on them tests the word.
4. **One cadence, one product.** A minute-cadence decision pays the spread on every flip, and the
   daily MDE is fixed by one product's variance. Whether any measured direction could ever have
   paid a fee is arithmetic on decisions held longer, which v1 does not print.

v2 therefore: freezes A at a real non-rule wording, re-cuts `liq` in a price-free unit from
measured occupancy, retires the direction probabilities to descriptive, adds two products and
two held cadences from the same minute stream, adds a no-call arm D that says whether the
per-minute Jev call is a table lookup, fixes the nightly's inputs, and pre-registers the
promotion schedule. One primary, a four-cell claimable family, everything else descriptive.

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
| **A** | Jev on the FROZEN `v2` action wording: `prompts/v2.json`, the wording promoted 2026-09-26 in v1 (sells on a non-violent dump, holds a violent one). Canonical prompt sha (SPEC §2, the row's `prompt_a_sha`) `b3291ca4a55091bd8a331e87ac95dfccfca6b81664f38f9430f42f0afc473c0e`; file sha256 `dcc848e5ad1452bede8631cf0d2f9801175070746ced883857e86366ec4a8ab4`. By its own 81-state table (`proposals/2026-09-25.md` cand_2, `proposals/2026-09-27.md` "current (v2)", both 2026-09) it differs from `rule_c` on 27 of 81 states for `SOL-USD`; the count per added product is read from that product's pinned table (§8) at the draft tag. | never during v2 |
| **B** | Jev on the CURRENT action wording: a human-gated rewrite, at most weekly, from nightly proposals (§8) | at a promotion, effective at a day boundary |
| **C** | `rule_c`, the no-model rule; its truth table over the 81 words is unchanged (12 buy / 45 sell / 24 hold, SPEC §6); which live ticks read `thin` moves with §3 | never |
| **D** | the CURRENT wording's own 81-state table: Jev's answer on the synthetic state string per product, copied at promotion from the promoted candidate's column of the proposal night's committed table (`prompts/v<N>.table.<product>.json`, one request per state carrying the candidates and CURRENT; `bin/promote` sends nothing), looked up by the live state; no call | at a promotion, with B |

**Arm A's text and the added products.** `prompts/v2.json`'s instructions begin "Decide whether
to be long SOL". `prompts.build` renders the action text per product: in `prompts/v2.json` the
token `SOL` is the base placeholder and is replaced by the row's base; files `v3` and later name
no base in `PRODUCTS` and may use the literal `{BASE}`; the loader and `bin/promote` refuse any
other product word. `SOL-USD`'s requests stay byte-identical to v1's for A. A test asserts each
product's rendered A differs from SOL's only in that token.

The question is whether the nightly rewrite does anything: **H1: B beats C** in direction,
gross of fees, pooled over products, with each decision held for fifteen minutes. Beside it, as
a claimable family (§6): B − C held for 60 and for 240 minutes, A − C, and B − A. Arm D is
descriptive with a pre-registered reading: if B and D agree on nearly every tick, the fast
model's per-minute call is a lookup of its own table, and a third block may run D in B's place
at 81 calls per product per promotion (243 for three products) instead of one request a minute
per product (1,440 a day, which A and the nouls also ride).

A and B ride one request on one state string per product, with the three nouls from `v1`
unchanged (SPEC §7); the only difference between A and B is the wording of `action`. At T0_v2
CURRENT is `v2` (§10 sets it at the switch whatever v1's CURRENT names), so until the first
v2-block promotion B asks A's wording (A vs B is a free test-retest) and D is that wording's
table (B vs D is §6's D-agreement).

## 2. Products, loops, terms, warm-up, sample, clock

- **Live row** = a row with `mode: "live"` and `absence: null` (PREREG-v1 §4, CONTRACT §5). Used
  in that sense everywhere below.
- **Products.** `SOL-USD` (the v1 stream, unbroken) and two more chosen by `bin/probe`, committed
  and tested, run ONCE from `~/Projects/jev-paper-loop-v2` over the UTC day **D = 2026-09-30**,
  named here before it runs and before the draft tag. It makes public GETs only (the feed's three,
  one candidate at a time, at most one request per second, starting at second :30 of each minute
  so the live loop's :00 requests see no added load; the feed never retries), uses no Jev key,
  and writes nothing under any `data/`, `logs/` or lock: its rows go to `probe/2026-09-30/` and
  are committed verbatim. Candidates, in this order: `ETH-USD`, `XRP-USD`, `DOGE-USD`,
  `AVAX-USD`, `LINK-USD`, `ADA-USD`. `bin/probe summarize` computes every criterion and takes the
  first two that pass all of: (1) the book and candles GETs answered on ≥ 99 % of D's minutes;
  (2) mean daily USD volume ≥ $50M, computed as Σ(volume × close)/30 over the 30 `ONE_DAY`
  candles ending at D's midnight (fewer than 30 rows fails; volume is in base units, so the
  figure is an approximation and is printed); (3) `liq` occupancy under §3's rule over D's rows
  gives every word ≥ 3 % and ≤ 90 %; (4) not a stablecoin. A candidate that fails is named with
  the failing value. Fewer than two passing → v2 runs on what passed. The two products, their
  `TICK_p` (the mode of positive consecutive level-price differences in D's books) and their
  §3 atoms are written into this section and into `config.py` before the draft tag:
  Products: `SOL-USD`, `________`, `________`.
- **Loops and stores.** One loop process per product (`JEVLOOP_PRODUCT`; unset means `SOL-USD`;
  a value not in `PRODUCTS` exits 2 before any directory is made). `config.store(p)` returns the
  decision log, sends ledger, lock and heartbeat under `data/` for `SOL-USD` and under
  `data/<PRODUCT>/` otherwise. **`data/HALT` stays the one global stop** (the spend trip, a key
  rejection and the nightly write and read only it; every loop and the nightly stop on its
  existence). **`data/PAUSE.<PRODUCT>`** pauses one product's sends: that loop skips the send and
  writes the existing absence `halt`; observation and t + h outcomes continue; the nightly and the
  spend guard ignore PAUSE. `make status`, the dash and the report show HALT and each PAUSE.
- **Spend.** One tripwire over the products' decision logs (`DAILY_SPEND_HALT_USD` = 0.75 for
  three products). The nightly's table sends (243 a night, about $0.01) never reach a decision
  log and fall outside it; they are bounded by `policy_table.py`'s deadline, its failure limits
  and its per-send HALT check.
- **No statistical warm-up** (PREREG-v1 §2 stands). The operational shakedown is one day per
  product after the switch.
- **T_first_v2** = the `tick_id` of the first live row written under the v2 code by the LAST
  product to start. **T0_v2** = the first minute boundary ≥ T_first_v2 + 86,400 s, written into
  §12 at sealing.
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
  fill, the spread in ticks. `TICK_p` is per product in `config.py` (0.01 for `SOL-USD`; the
  probe reads each added product's from its book grid).
- **`deep` ⇔ h < a10 + 0.5; `thin` ⇔ h > a90 + 0.5**, where a10 and a90 are the integer atoms
  nearest the nearest-rank p10 and p90 of h over the product's window; if `thin` then holds
  < 3 % of the window's rows, once, `thin` ⇔ h > a90 − 0.5. `fill1k_short` stays `thin`. `normal`
  otherwise. Every word must hold ≥ 3 % and ≤ 90 % of the window's rows (this replaces v1's
  "p10 < p90" eligibility for an added product, §2).
- **Windows.** For `SOL-USD`: the v1 sample's live rows in [2026-09-25T21:40Z, 2026-09-29T04:30Z),
  by `bin/fill1k-quantiles --log data/decisions.jsonl --t0 20260925T214000Z --until 20260929T043000Z
  --tick 0.01`, which reads `features.fill1k_bps`, `features.fill1k_short` and `features.mid` and
  nothing else (its source is scanned for the words it must not contain), excludes short rows
  from the quantiles while counting them, and prints N, the quantiles of `fill1k_bps` and of h,
  the atoms and each word's occupancy. Its output for SOL, verbatim: `________` (N must be 3,908
  or the count in §0.2 is corrected to the tool's). For an added product: D's probe rows, the
  same tool over `probe/2026-09-30/<product>.jsonl`.
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
block in `book._order` (least `tick_id`, then `ts_rx`) that is a live row and not SPEC §10's
forced hold (`columns.a` and `columns.b` not both null) — and `hold` on every other row of the
block. The decision row is shared by every arm: A and B read `columns.a`/`columns.b`, C reads
`rule_c`, D reads `columns.d` (null means hold for D only). A block with no decision row holds
throughout. The transformed intents feed `book.replay`, so the book, the marks, the spread and
the fee columns are SPEC §10's. **c = 900 keeps v1's 15-minute block but not its policy**: v1
decided every minute and summed d_t over the block; v2's primary acts on the decision row's
intent once per block and holds it until an opposite decision, so v2's H1 is not v1's H1. The
minute-cadence B − C (v1's design applied to v2's arms; not v1's quantity) is printed beside
it, descriptive, so v1 and v2 can be read side by side.

**Replay and exclusion.** Per product, `at_cadence` and `book.replay` run from flat at T0_v2
over every row of the sample window, excluded days included (the v1 code's reading, ERRATA
PREREG §4/§8.3, settled here). An excluded product-day's blocks are then dropped from S_k,p. A
position carried into an excluded day is marked on that day's priced rows; where an excluded
day has no priced row, the move across it lands on the first priced tick after it (SPEC §10),
in a kept block that stays kept and is counted in a printed `gap_blocks` line.

**Unit and statistic** (per cadence c, per product p): block k = the rows with
T0_v2 + c·k ≤ tick_id < T0_v2 + c·(k+1); **S_k,p(X − Y, col, fee)** = Σ over the block's rows of
d_t from `book.paired(at_cadence(rows_p, c, T0_v2), ·, X, Y, col, fee)`.

**Pooling.** Crypto products move together, so the products are not three independent samples
and are never treated as such. The pooled unit is the TIME block: **S̄_k = mean over the
products p not void under §9.4 whose day containing block k is kept (§9.3) of S_k,p**; a block
with no such product is dropped (no placeholder). n at c = 900 is at most 96 × 28 = 2,688
pooled blocks; at 3,600, 672; at 14,400, 168. Per-product series are printed beside the pooled
one, descriptive. A **pooled disagreement block** is a pooled block with at least one kept
product's disagreement tick (a tick where the two arms are on different SIDES, long vs flat);
the count of disagreement product-blocks is printed beside it.

## 5. H1 (the one primary): the nightly's arm beats the rule, pooled, held 15 minutes

- **Statistic:** mean over the sample's pooled blocks of S̄_k(B − C, `argmax`, `FEE_BPS_PRIMARY`
  = 0.0) at c = 900 s: direction net of the spread, gross of fees (PREREG-v1 §4's reasoning
  stands; the venue's fees are arithmetic, §6).
- **Hypothesis:** H0: mean ≤ 0; H1: mean > 0. One-sided, **α = 1/40 = 0.025** (v1's level, kept
  for comparability although v2 has one primary).
- **Inference:** circular block bootstrap of the pooled block series in block order, block
  length **L = 4 units of the cell's own cadence** at every cadence (1 h at 900 s, 4 h at 3,600 s,
  16 h at 14,400 s; the draw below is the definition and L is kept by choice), R = 10,000
  resamples, **seed 20261023**, each resample the same length as the series, blocks drawn with
  replacement from the circularly wrapped series; the draw exactly as PREREG-v1 §5 steps 1–3
  (one `random.Random(seed)` per cell; ⌈n/4⌉ starts per resample, `rng.randrange(n)`, four
  consecutive wrapped units each, truncated to n; the mean recomputed per resample). **The bound
  is `sorted[⌈α·R⌉ − 1]` of the R sorted resampled means, nearest rank, integer arithmetic, no
  interpolation: `sorted[249]` at α = 1/40 (H1), `sorted[62]` at α = 1/160 (every family-F cell,
  §6, and stop rule 1's A − C).** Reject H0 iff the bound is > 0. Ties (S̄_k = 0) stay in. α is
  carried as an exact fraction in code, never as a float.
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

Claims are at a one-sided family-wise error rate of at most 0.05 (Bonferroni: 0.025 for H1
plus 4 × 0.00625 for F). H1 is not a member of F.

**Descriptive, printed, never tested:** B − C, A − C and B − A × every column (`rules.COLUMNS`,
11); D − B and D − C at `argmax` only (D's table holds the action choice alone); each × every
fee × every cadence, per product and pooled. `FEE_BPS_COLUMNS = (0, 2, 10, 25, 50, 90)`: 0 =
gross (the primary), 2 = Binance.US, 10 = the article's, 25, **50 = the venue's retail maker,
90 = the venue's retail taker, both read in-account by Alex on 2026-09-27** (ERRATA.md, the
SPEC §10 row; `FEE_BPS_VENUE = 90.0` with its source line filled). v1's unverified 60 and 120
bps columns are replaced by the verified 50 and 90.

**The fee arithmetic (descriptive; the money question answered by subtraction).** Per product
and cadence, on the `at_cadence` replay, with the affine fact that positions do not depend on
the fee (SPEC §10; the fee enters only the fills):

1. **Each arm's own break-even fee.** With E_X(f) the arm's end equity at fee f (an open position
   at the end is marked and its entry fill counts), f*_X = 90 · E_X(0) / (E_X(0) − E_X(90)) bps
   per fill, from the 0 and 90 columns. "X never pays" when E_X(0) ≤ 0; undefined when X has no
   fill. Printed for A, B, C and D, plus a buy-and-hold line over the same span.
2. **Tiers.** The venue's published spot schedule (§12: every row of the schedule at
   coinbase.com/advanced-fees read in-account at sealing; no stable-pair, promotional or
   subscription schedule; if it differs from ERRATA's 2026-09-27 reading, both are printed). A
   tier's round-trip cost is 2 × its taker fee (the book fills at ask and bid, SPEC §10); 2 ×
   maker is printed beside it labelled "needs a passive-fill model not measured here". A tier is
   named for X when its taker fee is below f*_X, beside the tier's 30-day volume and X's own
   30-day volume at $1,000 notional (Σ fill value × 30/28).
3. **Pairs.** Δ(f) = Σ_k S_k(X − Y, f) and f*_XY = 90 · Δ(0) / (Δ(0) − Δ(90)): "the fee at which X
   stops beating Y", never "pays"; "keeps its sign at every fee" when Δ(0)'s sign is opposite to
   the slope; "fees cancel" when Δ(0) = Δ(90).
4. Pooled figures are sums over kept product-days, never averages of per-product ratios.
5. Costs above $1,000 notional are not measured.

**Arm D (descriptive, with a pre-registered reading).** Agreement(p, v) = #(live rows with
`columns.d` non-null and `columns.b.argmax == columns.d`) ÷ #(live rows with `columns.d`
non-null), per product p and prompt version v. The null count is printed beside it; a nonzero
count marks the cell a table defect and it is not read. **Lookup reading: every readable cell
≥ 0.99** → the per-minute call is a lookup of its own table. **Drift reading: any readable cell
< 0.95** → Jev's live answer depends on something other than the state string; the causes to
name, in order: the other questions in the table's request (the candidates and CURRENT, against
`a_action`, `b_action` and the nouls in the live request), the days between table and tick,
drift (`model_answered`), non-determinism. Between: reported per cell. Beside it: within-state
live consistency, and the count of states seen ≥ 10 times whose modal live answer differs from
the table's. This is answer-level and withheld with §4–§7 until day 28.

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
**1.78 bps per block = 171 bps/day** at 2,688 blocks. At family F's α = 0.00625 (z = 2.498 +
0.842 = 3.340) every MDE is × 1.192: 2.13 bps/block at 900 s (cells 3 and 4), 8.5 at 3,600 s
(cell 1), 34.0 at 14,400 s (cell 2); 204 bps/day per product at ρ = 1 and 118 pooled at ρ = 0.
B − A gets no figure: it is 0 on every block before the first promotion.

**The effective-n caveat.** The information lives on the blocks where the arms' SIDES differ.
B's and C's intents differ on the 27 `vol violent` states, but their sides differ only from a
violent tick that finds B long, until B's next buy or non-violent dump (C long implies B long),
so the disagreement-block share is unknown before the data and may be above or below the
one-fifth `violent` occupancy. PREREG-v1 §7's table gives n_eff and the MDE per agreement share;
day 28 prints the measured share per cadence.

**What pooling buys.** With pairwise correlation ρ between the products' block differences the
pooled mean's variance is σ²(1 + 2ρ)/3 (equal σ and ρ, all three kept; with unequal σ_p the
factor is ΣΣ ρ_pq σ_p σ_q / (9σ²); a block with one excluded product carries (1 + ρ)/2 or 1).
Crypto products' 15-minute returns correlate at roughly 0.6–0.8, but the arms' DIFFERENCES
correlate less (they depend on each product's own words), so ρ is unknown before the data and
is printed at day 28:

| ρ | variance factor | pooled MDE per block (α 0.025) | per day |
|---|---|---|---|
| 0.0 (independent) | 0.33 | 1.03 bps | 99 bps |
| 0.5 | 0.67 | 1.46 bps | 140 bps |
| 0.7 | 0.80 | 1.59 bps | 153 bps |
| 1.0 (one product thrice) | 1.00 | 1.78 bps | 171 bps |

**Cadence.** Under v1's arithmetic (a random-walk mid, a side difference on every block) the
daily MDE is AT MOST 171 bps/day per product at every cadence: holding the decision for c
seconds multiplies the per-block sd by √(c/900) and divides n by c/900. Below that bound it
scales with √f_c, where f_c is the side-disagreement share at cadence c, printed per cadence at
day 28. At c = 14,400 the bound rests on ≤ 168 units and 42 drawn blocks per resample, and a
percentile bound from so few blocks tends to under-cover; accepted now: cells 1 and 2 are there
to be read beside the primary, and their rejection would be a strong result, not an expected one.

**The 56-day lever.** Doubling the block to 56 days cuts every MDE by √2 (121 bps/day per
product). v2 keeps 28 days for comparability with v1 and so that each promotion has a month of
nights; a third block may take 56 and say so before its own T0.

## 8. The treatment: what the nightly is, what is fixed, what is only logged, and when a person may promote

The treatment under H1 is the nightly rewrite AND its inputs. **Fixed before the draft tag and
unchanged through the block:** `nightly/PROMPT.md` (v2 text, quoted in full in the build),
the digest's content (`nightly/digest.py` source, pinned), the slow model id (below), the
call's shape (an empty temp cwd; tools off; `nightly/settings.json`; the 45-min cap; **no user
memory: `propose.sh` exports `CLAUDE_CONFIG_DIR` as a fresh `mktemp -d` outside the repo,
created and removed each night like the work dir, for the call and for `answered_model.py`, and
fails the night, sending nothing, if that directory holds `CLAUDE.md`, `CLAUDE.local.md`,
`rules/`, `skills/`, `agents/` or `plugins/`; it logs "user memory not loaded"**). **Logged,
not fixed:** the CLI version (it cannot be pinned) and the answering model line each night.
One dry night under this setup runs before the draft tag (STEPS §10 v2): it must exit 0, the
OAuth token must answer, `claude model` must log exactly one id, and it shows whether
`--settings` still applies; if it fails, the fallback before the tag is to pin the user-memory
sha instead (`propose.sh` logs FAIL and makes no call on any other sha, and `~/.claude/CLAUDE.md`
is left unedited until T0_v2 + 28 d). The change of the treatment's context versus v1 is
recorded for the write-up (ERRATA.md's precedent).

- **`nightly/PROMPT.md` (v2):** the v1 rules, plus: the product name is the first word of the
  state and the wording must read identically for every product up to the base token (one
  CURRENT for all); the measured fact that Jev reads "volatility is calm" as "not violent"
  (`proposals/2026-09-25.review.md`, a synthetic-table fact), so a candidate whose only lever is
  calm-vs-normal changes nothing; no numbers, full text, one to three candidates, only `action`.
- **The digest (v2 content):** covers the UTC day just closed (CONTRACT §5; `propose.sh`'s
  default date) and only rows carrying the v2 SPEC's `spec_sha`, so the switch-day digests
  never mix v1-code rows in; per product and pooled, the summary line at 0 bps and at the
  verified maker and taker; **every arm-B figure from rows whose `prompt_b` is CURRENT only**
  (v1's summary line replayed B over a promotion day's mixed rows, HANDOFF.md's prereg-v2 note);
  the disagreement rows (confidence ≥ 0.85, up to 25) as before; and new, a **per-state table**
  over the 81 states per product: rows seen, B's choice distribution, mean `ret_h_bps` and the
  label rates at the 15-minute join, that day's. Nothing in the digest is a test.
- **The slow model, pinned:** `claude -p --model <id>`, where id is the one on the `claude model`
  line of `logs/propose.log` from the run of 2026-09-29 08:30Z; if that line is `unrecorded`,
  lists more than one id, or is missing, the first later v1 night whose line is exactly one id.
  Written here with the night it came from, before the draft tag: **id `________` (night
  `________`).** If the id is refused before the seal (the dry night fails on it), one substitute
  is allowed by this rule alone, chosen before the seal: the latest v1 night naming exactly one
  id. If `--model <id>` is refused at T0_v2 or on any later night, that night fails like any
  failed night: no proposal, no substitute; the report counts failed nights with their reasons,
  and if no promotion results §9.2's NO PROMOTION reading applies.
- **Scoring a candidate:** `policy_table.py` (v2) renders `state_string(adj, base)` per product
  and, beside `proposals/<date>.md`, emits `proposals/<date>.table.json` holding every wording's
  81 answers per product, its sha in the .md; one request per state carrying the candidates and
  CURRENT (243 requests for three products; `DEADLINE_S` scaled by the product count). Jev's
  answers on synthetic strings, never a backtest; under each candidate the table says which
  states move from CURRENT's answer.
- **Promotion (Alex alone, `bin/promote`), on a pre-registered schedule enforced in code.**
  Effective days E with **8 ≤ E ≤ 22**, E_k − E_(k−1) ≥ 7, none during the shakedown: at most
  three promotions (days 8, 15, 22). `bin/promote` may run at any time on day E − 1; it writes
  `prompts/v<N>.json` and the tables with **activation tick_id = T0_v2 + 86,400 · (E − 1)**, and
  `prompts.current(tick_id)` returns the new version only for ticks at or after that (CONTRACT §5
  amended), so every row and every c-block of a product-day carries one `prompt_b`. `bin/promote`
  reads T0_v2 from this file's §12 and refuses while it is blank; refuses E < 8, E > 22 or spacing
  < 7; refuses a candidate whose table moves 0 of 81 states on every product; copies candidate k's
  per-product column from the proposal night's committed `.table.json` under an 81/81 refusal
  (an unanswered state is re-sent by `--table-only`, an answered one never is) and writes the
  tables before CURRENT changes; the person's reason is one line in the promote commit, with the
  states moved. `bin/promote --table-only <proposal.json>` is attended, sends nothing, and keeps
  promote the only writer of `prompts/`.
- **v2's own tables, before the draft tag:** `prompts/v2.table.<product>.json` for `SOL-USD` and
  the two probe products, from a `policy_table.py` (v2) run with CURRENT = v2 (attended, 243
  sends, ~$0.01), copied by `--table-only`, committed with the answering Jev version and pinned.
  If a different Jev version answers at the switch, the tables are rebuilt once under the same
  rule and the new shas and version go into §12.

## 9. Stop rules — fixed now

1. **Day 28, neither A nor B beats C on H1's cell** (B − C at α 1/40, §5; A − C at F's α 1/160,
   §6 i = 3, stricter than v1's stop-rule-only 0.025) → the model arms are retired for this block
   (sends stop at day 28); C and the feeds keep logging only if a third pre-registration wants
   them, which may re-open a cadence §6 i = 1 or 2 rejected, as v2 re-opens v1's arms.
2. **B − A ≤ 0** at day 28 (point estimate of the pooled mean S̄_k(B − A, argmax, 0 bps), c = 900,
   over all kept blocks) → the nightly is stopped (its plist booted out); A is kept. **If no v2
   sample row has `prompt_b_sha ≠ prompt_a_sha` (CURRENT never left `v2`), stop rule 2 reads NO
   PROMOTION:** the nightly is stopped because it produced no promoted candidate, not because of
   B − A's sign; §6 i = 4 is not read, and B − A is reported as test-retest, descriptive only.
   Pre-promotion dilution stays: it is the pre-registered intent-to-treat.
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
   SOL's rows in `data/decisions.jsonl` included; v1's own withholding is kept beside it.
   `report --unblind` is a look: it appends (UTC, argv, HEAD) to `data/looks.tsv`, which
   RESULTS-v2 §0 reproduces. No bootstrap runs before day 28.
6. **No extension after looking.** The sample ends at T0_v2 + 28 days whatever the numbers say.

## 10. The build, the freeze, and the switch

**Built blind** on branch `prereg-v2` in the worktree `~/Projects/jev-paper-loop-v2` (no
`data/` there), tested by `make test` and CI, **complete, committed and pinned BEFORE the draft
tag**, merged to `main` only after RESULTS.md (v1) is committed on 2026-10-23, then installed by
the switch below. Nothing changes what a v1 row means or how v1's readers read the v1 log: v1's
committed result and its descriptive cells are reproduced from `results-v1`; a v1 row's
`spec_sha` resolves with `git show prereg-v1:SPEC.md`; no reader prints §4–§7 over a v2 sample
row before T0_v2 + 28 d.

- **SPEC (v2 sha on every v2 row):** §2 the row gains `product` (from `JEVLOOP_PRODUCT`; always
  `SOL-USD` in v1), `columns.d` and `table_sha`; `prompt_a`/`prompt_a_sha` come from `FROZEN_A`
  instead of the literal `v1`; §5 `liq` in h with per-product `TICK_p` and atoms; §6's `liq`
  sentence points to the per-product cuts, the truth table unchanged; §7 four arms, A = `v2`;
  §10 fee columns (0, 2, 10, 25, 50, 90), `FEE_BPS_VENUE = 90.0` verified, the "Verified
  tier-0 taker fee" row filled; §13.2 step 2 gains PAUSE; §14 the new constants (`PRODUCTS`,
  `TICK_p`, the atoms, `CADENCES = (900, 3600, 14400)`, `FROZEN_A = "v2"`,
  `DAILY_SPEND_HALT_USD = 0.75`). ERRATA.md's SPEC and PREREG rows that describe what the code
  already does are folded into the text.
- **config / cycle / feed / state:** `config.PRODUCTS` fixed at the draft tag; `config.store(p)`;
  `HALT`, `PAUSE.*` and `exclusions-v2.tsv` at `REPO/data/` (dash and status stop building HALT
  from `--data`); `state_string` takes a base; the spend guard sums every product's log; the row
  carries `product`, `columns.d`, `table_sha`; a test with `JEVLOOP_PRODUCT` unset asserts every
  v1 path and the `RULE_C` pin unchanged. Each added plist has its own log
  (`logs/loop-launchd-<product>.log`). STEPS counts `feed: http-429` lines per product over the
  shakedown; if any appear, the loops move to one process ticking the products in sequence
  before the seal (feed.py's note: 9 GETs per :00 against the venue's recorded 10 req/s).
- **prompts:** `build(frozen_a, current, base)` renders the base token (§1); `current(tick_id)`
  honours activation; `bin/promote` as §8.
- **book:** `at_cadence(rows, c, t0)`; `ARMS` gains `d`; `_intent` for `d` returns
  `columns.d` at `argmax` and raises on any other column; the every-arm forced hold applies to D;
  a null `columns.d` on an otherwise answered row is a hold for D only, counted in D's forced
  holds; `report.PAIRS` gains (d, b) and (d, c) at `argmax`.
- **exclusions:** a v2 reader beside `loop/exclusions.py` (v1's stays unedited); the new default
  path in inference, status, report and dash; the per-product recompute; `!data/exclusions-v2.tsv`
  in `.gitignore`; CONTRACT updated. The switch commits v1's `data/exclusions.tsv` (or records
  that it is absent) with RESULTS.md, and nothing appends to it afterwards.
- **report / status / dash / inference:** per-product and pooled series; the cadence loop; family
  F with its seeds and `sorted[62]` (α as an exact fraction; `alpha_rank` never the float; F never
  reuses the 0.025-only `bootstrap()`); the D-agreement in a withheld section (HEALTH_N stays 3;
  a test that `--health` prints neither A-agreement nor D-agreement); the fee arithmetic of §6;
  stop rules 3–4 per product; the NO PROMOTION check before `ba` is read; `make results` for v2
  reads all logs and refuses before T0_v2 + 28 d; `--unblind` writes `data/looks.tsv`.
  `test_invariants.py` holds the readers to independent transcriptions of §4–§6 written from the
  text (H1 seed 20261023 at `sorted[249]`; F seeds 20261024–20261027 in §6's order, each at
  `sorted[62]`; L = 4 units; R = 10,000; each cell's bound on a fixed series hard-coded; a golden
  series on which `sorted[61] ≠ sorted[62]`); `test_inference_golden` stays at v1's seed for v1's
  readers; a test with an excluded day between two kept days and arm positions that differ
  across it; `tests/synth.py` gains products and a cadence knob.
- **nightly:** the digest of §8; PROMPT.md v2; `--model` pin; `CLAUDE_CONFIG_DIR`; per-product
  tables and `.table.json` in `policy_table.py`; `propose.sh` passes every product's log to the
  digest and the dash.
- **tools:** `bin/probe` (§2), `bin/fill1k-quantiles` (§3), `bin/seal-check` (§13).
- **Makefile:** `results` refuses unless `git rev-parse -q --verify refs/tags/prereg-v2-draft`
  succeeds; the explicit override `NO_V2=1` is allowed and is recorded in RESULTS.md; the target
  echoes the tag's sha into RESULTS.md's header. Tooling only; the statistics are untouched.
- **launchd:** one loop plist per added product (`com.alexward.jevloop.loop.<product>`), pinned
  in `tests/test_nightly.py`; the nightly and backup plists unchanged (the backup copies every
  store). Hand-installed (STEPS §10 v2, written in the build and frozen by the draft tag).
- **tests/test_frozen.py at the draft tag** pins by sha: SPEC v2, CONTRACT, this file,
  `nightly/PROMPT.md` v2, the sources of `nightly/digest.py` and `nightly/policy_table.py`,
  `prompts/v2.json`, the three v2 tables, `THRESHOLDS` with `TICK_p` and the per-product atoms,
  every §14 constant, the inference constants (seeds, L, R, the ranks), `RULE_C` per product;
  each pin updated in the same commit as the file it pins so CI is green on every push.

**The switch (STEPS §10 v2; 2026-10-23, after `make results`):** (1) `make results` exits 0
(not before ~21:56Z, when the last block's t + h row exists); (2) commit RESULTS.md with v1's
`data/exclusions.tsv` or a line that it is absent; (3) `git tag results-v1`; (4) in the worktree,
merge `main` into `prereg-v2` and run `make test` there; (5) wait for the current minute's
heartbeat, then `launchctl bootout` the SOL loop; (6) on `main`, `git merge --ff-only prereg-v2`,
stopping if it is not a fast-forward; (7) `make test`; if red, `git reset --hard ORIG_HEAD` and
re-bootstrap v1; (8) set `prompts/CURRENT` to `v2` by hand whatever it names (the documented
rollback, `bin/promote`), in a commit of its own naming what it replaced; (9) bootstrap SOL in a
later minute than the bootout; (10) bootstrap the two named products; (11) `make status` shows
three heartbeats. The merge, not the bootstrap, changes what the next SOL tick writes
(`columns.d`, `table_sha`, the v2 spec sha, A = `v2`). The switch's missed or duplicated minutes
precede T_first_v2 and enter no test. The reading lines of `make results` ("the model arms are
retired") do not gate the switch (§0).

## 11. What would falsify what

- H1 rejected: the nightly-rewritten wording, held for fifteen minutes, beat the rule in
  direction, pooled over these products and days. With i = 4 also rejected: the rewrite added to
  the frozen prompt. With i = 3 rejected and i = 4 not: the frozen `v2` wording did the work. If
  no promotion occurred (§9.2), an H1 rejection reads as the frozen `v2` wording beating the rule
  (B = A throughout), never as the rewrite.
- H1 not rejected: no B − C difference detectable at §7's MDE (pooled 99–171 bps/day by ρ) in
  direction, gross, held 15 minutes, on these products over these 28 days (stop rule 1 with
  i = 3); edges below that are not ruled out.
- i = 1 or i = 2 rejected without H1: direction at a longer hold that the 15-minute hold does not
  show; a third block puts that cadence first.
- D-agreement ≥ 0.99 on every readable cell: the fast model is a lookup here, and its cost is 81
  calls per product per promotion.
- No arm's break-even fee exceeds the taker fee of any tier its own volume reaches: nothing
  measured here paid at the venue at $1,000; a pair's break-even says only at what fee one arm
  stops beating the other.

## 12. Fields filled after the draft tag (and nothing else)

| field | filled when | from |
|---|---|---|
| the venue's fee-tier table (§6) | at sealing | every row of the spot schedule, read in-account, with the read time |
| the v2 tables' shas and Jev version, ONLY if rebuilt at the switch (§8) | at the switch | the once-only rebuild rule |
| T_first_v2, T0_v2, sealed-by, sealed-on | at sealing | the logs and the person |

Products, their cuts, arm A's per-product state counts and the slow-model id are set in §1, §2,
§3 and §8 BEFORE the draft tag and are not fields here.

Fee tiers (30-day band / maker / taker, read UTC `________`): `________`
T_first_v2: `________`   T0_v2: `________`   Sealed by: `________`   on: `________`

## 13. The tags, and `bin/seal-check`

**Doc tag, once the 2026-09-29 review's changes are in:**
```bash
cd ~/Projects/jev-paper-loop && git tag -a prereg-v2-doc -m "PREREG-v2 text after the five-lens review" HEAD && git push origin prereg-v2-doc
```
**Draft tag, before `make results` on 2026-10-23,** on the build branch in the worktree, with
`git status --porcelain` empty and `make test` and CI green, `main` merged in, §2, §3 and §8's
pre-tag values written, the probe's output and the three tables committed and pinned:
```bash
cd ~/Projects/jev-paper-loop-v2 && git merge --no-edit main && make test && git tag -a prereg-v2-draft -m "frozen before make results (v1)" HEAD && git push origin prereg-v2 prereg-v2-draft
```
**Seal,** on `main` after the switch, once §12 is filled and before the first v2 sample row:
```bash
cd ~/Projects/jev-paper-loop && bin/seal-check && git tag -a prereg-v2-seal -m "PREREG-v2 sealed" HEAD && git push origin prereg-v2-seal
```
`bin/seal-check` is committed and tested in the draft tree. It exits non-zero unless all of:
(a) `git merge-base --is-ancestor refs/tags/prereg-v2-draft HEAD`; (b) `git status --porcelain`
is empty; (c) `git diff -U0 refs/tags/prereg-v2-draft HEAD -- . ':(exclude)RESULTS.md'
':(exclude)HANDOFF.md' ':(exclude)ERRATA.md' ':(exclude)proposals'` has hunks only inside this
file's §12 blank fields, in `prompts/v2.table.<product>.json` replaced under §8's once-only
rebuild rule, and in the `tests/test_frozen.py` lines that pin those files; (d) `prompts/CURRENT`
is `v2`; (e) `make test` passes. RESULTS-v2 §0 prints the full `-U0` diff, seal-check's verdict,
and the `--stat` of the excluded paths.

## 14. Amendments between `prereg-v2-doc` and `prereg-v2-draft`

Each entry: date, author, what changed, and what the author had read (digest included).

- (none yet)

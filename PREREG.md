# PREREG — the 28-day test, written before the data

**Status: DRAFT until sealed.** Sealed by `git tag prereg-v1 <commit>` on the
commit that fills the two blanks in §11, BEFORE the first tick whose
`prompt_b != "v1"` and in any case before the day-14 look (§8.4). After the tag
this file does not change; a change is `prereg-v2` and applies only to a second
block. `make report` prints no p-value; the inference below is run once, at the
end, by hand, and its output is committed beside this file.

Everything measured is defined in `SPEC.md` (whose sha every row carries);
nothing here redefines a number.

## 1. What is being tested

Three arms decide `buy | sell | hold` every minute on one state string (SPEC
§5–7): **A** = Jev on the frozen `v1` action question, **B** = Jev on the
CURRENT action question (rewritten only by a person applying a nightly
proposal), **C** = the no-model rule the thresholds already imply. The question
is whether the nightly rewrite does anything: does B beat C, and does B beat A.
And, co-primary with H1, whether Jev's own direction probabilities — the `up15` and
`down15` nouls, asked once per tick from the frozen `v1` and never rewritten —
say anything about the next 15 minutes (H2; 2026-09-24, decided by Alex, §5).
Jev sees only the four words, and on the shakedown its lean was close to a
recoding of the `trend` word that the rule and the action arms already act on,
so H2 asks whether that word, as Jev maps it, predicts the return; whether Jev
adds anything beyond the word is not tested here (§5, §9).

## 2. Warm-up, sample, clock

**No local warm-up exists.** The percentile and median windows of the alphabet
(`vol5_p10/p90`, `ret15_sd_bps`, `rv15_med`) are computed on every tick from
the venue's own last 300 closed candles, which `feed.py` fetches whole
(`CANDLES_REQ = 350` → 349 closed rows) and `state.py::features` takes the last
`WINDOW_MIN = 300` of. Row 1 already has a complete alphabet; nothing in the
loop learns from earlier rows. The decision's "24 h warm-up" is therefore kept
as an operational shakedown, not a statistical one: the first day of launchd
operation is where install mistakes (HALT, lock, feed absences, a wrong key
path) show up, and it is excluded from the sample so they cannot be cherry-
picked either way.

- **T_first** = `tick_id` of the first row with `mode: "live"` and `absence:
  null` written under launchd (STEPS.md step 7).
- **T0** = the first minute boundary ≥ T_first + 86,400 s, written into §11
  in the sealing commit. Every UTC day boundary from T0 is a "day".
- **Sample** = every row with `T0 ≤ tick_id < T0 + 28 · 86,400 s` (days 1–28),
  minus whole days excluded by stop rule 3.
- Rows before T0 and the day-0 rows are logged, reported by `make report`, and
  never enter §4–§6.

## 3. The sampling unit: non-overlapping 15-minute blocks

A per-tick `d_t` (SPEC §10) is a one-minute mark; consecutive marks share the
position and the 15-minute horizon of the decision that opened it, so they
are not independent samples. The pre-registered unit is the horizon:

- Block k (k = 0, 1, …) = the rows with `T0 + 900k ≤ tick_id < T0 + 900(k+1)`.
- **S_k(X−Y, col, fee)** = Σ over block k's rows of `d_t` from
  `book.paired(rows, ·, X, Y, col, fee)`. Forced holds contribute `0.0`; a
  block with no live row has S_k = 0 and is kept (the arms agree on nothing).
- n = 96 blocks/day × 28 days = **2,688** blocks when every day is kept.

This is the "every-15th-tick non-overlapping subsample" first written into
CONTRACT §4.5, made exact: the block boundaries are T0 + 900k (by `tick_id`
time, never by row index, so a missing minute does not shift a block), and
the block sum is the paired 15-minute pnl difference, equal to `position ×
15-min return − fees` whenever no trade falls inside the block. A literal
`d_t` at every 15th tick is a one-minute quantity with 1/15 of the variance
and is NOT the statistic below. `make report` prints S_k this way (`python3
-m loop.report --t0 <T0>`).
- **The replay starts flat at T0, on the sample rows only.** The rows are cut
  to `[T0, T0 + 28 · 86,400 s)` before `book.replay` sees them, so no
  shakedown, attended or `--dry` row before T0 carries a position into the
  sample. (A dry row inside the sample is a forced hold for every arm, SPEC
  §10.)

## 4. H1 (co-primary): the nightly's arm beats the rule

- **Statistic:** mean over the sample blocks of `S_k(B − C, "argmax",
  FEE_BPS_PRIMARY)`, where `FEE_BPS_PRIMARY = 0.0` bps — gross of fees: a
  difference between the arms is direction net of the spread. Turnover
  still costs one spread per round trip (every open fills at the ask and
  every close at the bid, marked to mid, SPEC §10: ~0.9–1.7 bps at a 1–2c
  spread on ~$115, the same order as the 1.78 bps per-block MDE of §7), so
  trades/day is read beside the cell.
- **Hypothesis:** H0: mean ≤ 0; H1: mean > 0. One-sided, α = 0.025.
- **Inference:** circular block bootstrap of the block series, block length
  = 4 samples = 1 h (the autocorrelation of a 15-min mark decays inside an
  hour; 4 also keeps every day divisible), 10,000 resamples, seed 20260923,
  each resample the same length as the sample, blocks drawn with replacement
  from a circularly wrapped series. Reject H0 iff the 2.5th percentile of the
  resampled means is > 0. Ties (S_k = 0, the agreement blocks) stay in.
- **Reported beside it, no inference:** the same cell on every tick
  (`d_t`, n ≈ 40,320), the count and share of disagreement blocks (a block
  holding a tick where B and C are on different SIDES, long vs flat, going
  into or out of it; two longs opened on different ticks differ in quantity
  and are not a disagreement, SPEC §10), the mean on disagreement blocks
  only, trades/day each side. These are descriptive.
- The same procedure is run for **A − C** at the primary cell, at α = 0.025,
  ONLY as the decision input of stop rule 1 (§8) and the reading of §9. As a
  claim ("A beats C") it is a secondary and takes the family α of §6.

**2026-09-24, decided by Alex: H1 is at 0 bps, gross.** The Coinbase
Advanced retail tier-0 ("Intro 1") taker fee is 120 bps per two secondary
sources (April 2026; the official table is behind sign-in, so
`FEE_BPS_VENUE = 120.0` stays UNVERIFIED, SPEC §10). A round trip is
2 × 120 = 240 bps against a 15-minute return sd of ~33 bps (§7; 28.9 bps in
the fixture window): one extra round trip costs about seven standard
deviations of the move it trades on, so an H1 net of that fee would mostly
rank which arm trades less (an arm that never trades cannot lose), and an arm
with real direction but more turnover would lose on fees before direction
could show. **Profitability at retail fees is not tested; it is settled by
arithmetic.** H1 is therefore: mean S_k(B − C, `argmax`, 0 bps) > 0,
one-sided, circular block bootstrap exactly as above, α = 0.025. H2 (§5) is
at α = 0.025 (its statistic moved to the direction probabilities later the
same day, §5; its α did not). Every net-of-fee cell (2, 10, 25, 60, 120 bps) is
DESCRIPTIVE: printed by `make report`, never tested (§6). Stop rules 1 and 2
(§8) name the same 0 bps cell. This replaces the paragraph that set out three
options for Alex before sealing; the other two, H1 at the venue fee (the
2026-09-23 decision) and venue fee plus gross as co-primaries at α = 0.0125
each, were not taken, so the MDE of §7 stays at 1.78 bps per block.

## 5. H2 (co-primary): Jev's direction probabilities against the 15-minute return

**2026-09-24, decided by Alex: H2 moves to the direction probabilities.**
Decided before sealing, before T0 was set and before any sample row existed;
it replaces the H2 first written here entirely (H1, §4, is untouched). The
evidence is the first live run: 181 ticks, 2026-09-24 16:47–19:48Z,
shakedown rows that never enter the sample (§2). Arm A's `argmax` matched
`rule_c` on 181/181: `v1`'s action criteria restate the rule (SPEC §8). Its
choice confidence ranged 0.86–0.99 and was "correct" against the 15-minute
label on 17 % of the [0.85, 0.99) bin (n 153) and 15 % of the ≥ 0.99 bin
(n 13), because nearly every answer is `hold` and `hold` is correct only when
|ret_h| < 5 bps. Choice confidence therefore measures how well Jev matched the
stated rule, not the market, and the old H2 (the point-biserial r between arm
A's choice confidence and whether `a.argmax` was correct) tested nothing
useful. `up15` and `down15` ranged 0.26–0.63 over the run, never in a measured
tail: they ARE Jev's price predictions, asked once per tick from `v1` and
never rewritten (SPEC §7–§8), so H2 is about them. The old table stays in
`make report` as a descriptive section, titled as what it measures (CONTRACT
§4.7: confidence vs rule-matching, not outcomes), and is never claimed.

**What a supported H2 would mean** (review, 2026-09-24, before T0; the
statistic is unchanged). The model sees one of the 81 state strings and
nothing else (SPEC §5), so lean is a function of the four words plus Jev's
answer noise. On the same shakedown, lean was +0.28 to +0.32 on every
`pumping` tick (6), −0.37 to −0.22 on every `dumping` tick (4) and 0.00 to
0.05 on every `flat` tick (156): r(lean, trend sign) = 0.99 over the 12 units
and 0.98 over the 166 ticks with an outcome. `rule_c` buys only on `pumping`
and sells on `dumping` (or `violent`, SPEC §6), and `v1`'s action restates it
(SPEC §8), so the action arms already act on that word. H2 therefore tests
whether the `trend` word (the 15-minute return z-scored and cut at ±1), as
Jev maps it into probabilities, predicts `ret_h_bps`. Whether Jev adds
anything beyond the word is not tested here; the word is printed beside the
statistic as a no-model comparator (below), descriptive only.

- **Unit:** unchanged: the first live row (`mode: "live"`, `absence: null`)
  of each block k of §3 (`tick_id = T0 + 900k` when present, else the first
  live row in the block; none → the block is dropped), so consecutive units
  have non-overlapping horizons. Only units with an outcome count: a `gap`
  outcome on that row drops the block, and so does a missing `up15` or
  `down15` noul. The block is never refilled from a later row.
- **x_k = lean_k** = `answers.up15.noul − answers.down15.noul`, in [−1, 1],
  rounded to 12 decimals (SPEC §8: the nouls arrive as short decimals, two
  places in the first run, and unrounded 0.4 − 0.3 and 0.3 − 0.2 differ in the
  last binary digit, which would rank equal leans apart; on the first run's 12
  units that noise moved ρ from 0.086 to 0.116). A and B share it (one
  request, one state, the `v1` nouls: SPEC §7).
- **y_k** = `ret_h_bps` of that row from the outcome join (SPEC §11: the mid
  nearest t + 900 s within ± 30 s), the one join `make report` computes over
  the whole log, so a unit near the end of the sample finds its t + h after
  it. (H1's book is marked to mid tick by tick and reads no label.)
- **Statistic:** Pearson r(x, y) over the units. Spearman ρ (average ranks)
  is printed beside it, descriptive.
- **Hypothesis:** H0: r ≤ 0; H1: r > 0. One-sided, α = 0.025.
- **Inference:** circular block bootstrap of the unit series in block order,
  block length 4 units ≈ 1 h (as §4), 10,000 resamples, seed 20260923, each
  resample the same length as the series, blocks drawn with replacement from
  the circularly wrapped series of (x, y) pairs; r is recomputed on each
  resample. Reject H0 iff the one-sided 97.5 % lower bound (the 2.5th
  percentile of the resampled r) is > 0. A resample on which r is undefined
  (every x or every y in it equal) counts as r = 0, which never rejects.
  Pinned before sealing (review, 2026-09-24): unlike §4's series, n here is
  generally not a multiple of 4 (dropped blocks and excluded days remove
  units), so the draw is written out exactly, in CPython's standard library:
  1. The series is the n units' (x, y) pairs in block order k, concatenated
     across dropped blocks and excluded days (a dropped block leaves no
     placeholder), indexed 0 … n − 1; index i ≥ n wraps to i − n.
  2. One generator, `rng = random.Random(20260923)`, used for H2 alone. For
     each of the 10,000 resamples in turn, draw ⌈n / 4⌉ start indices in
     order, each `rng.randrange(n)`; from each start s take the 4 units s,
     s + 1, s + 2, s + 3 (wrapped); concatenate in draw order and keep the
     first n units.
  3. r* = Pearson r of the resample (as `loop/report.py::pearson`; undefined
     → 0, above). Sort the 10,000 r* ascending; the lower bound is
     `sorted_r[249]`, the nearest-rank 2.5th percentile (the ⌈0.025 × 10,000⌉
     = 250th value), with no interpolation. Reject H0 iff it is > 0.
- **Degenerate cases, decided now:** if every lean_k is equal (the model
  reports one lean for everything) or every y_k is equal, r is undefined and
  H2 is recorded as "not supported: no variance in {lean|ret}". A lean that
  never reaches a measured tail is not degenerate: r reads the whole band,
  which is where the first run's nouls sat.
- **Reported beside it, never claimed:** Spearman ρ; r and ρ on every live
  tick (overlapping horizons, not independent); the Brier score of
  `up15.noul` against 1[label = up] and of `down15.noul` against 1[label =
  down], each beside the base-rate Brier p̄(1 − p̄) of predicting the sample's
  own frequency p̄; the counts of `up15` and `down15` in each measured tail
  (≥ 0.99 = `NOUL_TAIL`, < 0.15). The `noultail` column (SPEC §9) is those
  tails as a rule; it is one of the §6 cells and takes that family's α.
  The `trend` word as a no-model comparator, trend = +1 `pumping`, 0 `flat`,
  −1 `dumping` (`adj.trend` of the same row), on the units and on every
  tick: r(lean, trend), r(trend, `ret_h_bps`), and r(lean, `ret_h_bps`)
  within `trend = flat`, where the word is constant and any r is lean's own.

Both primaries must hold for the experiment to be reported as "the loop
works as described": H1 that the nightly arm's direction beats the rule's,
gross of fees and net of the spread; H2 that Jev's own direction
probabilities carry information about the next 15-minute return: information
in the four words as Jev maps them, which on the shakedown was mostly the
`trend` word (above), not shown to go beyond the words or to be a signal the
action arms ignore. Either alone is reported as exactly that. Neither says the loop earns anything at a
retail fee: that is not tested (§4).

## 6. Secondaries — descriptive, Bonferroni if ever claimed

- **A − C** and **B − A** at the primary cell, 0 bps (B − A is what the
  nightly adds over the frozen prompt; B − A ≤ 0 is stop rule 2).
- Every pair × every column × every fee: 3 pairs (B−C, A−C, B−A) × 11 columns
  (`rules.COLUMNS`) × 6 fees (`FEE_BPS_COLUMNS` = 0, 2, 10, 25, 60, 120 bps) =
  **198 cells**, printed by `make report` with no p-values.
- The **165 net-of-fee cells** (3 pairs × 11 columns × 5 fees: 2, 10, 25, 60,
  120 bps) are DESCRIPTIVE: never tested and never claimed as significant in
  this pre-registration. The 120 bps column is the venue's own taker
  (`FEE_BPS_VENUE`, UNVERIFIED), printed as the realistic cost.
- Only the **33 gross cells** (3 pairs × 11 columns at 0 bps) may ever be
  claimed. The H1 cell (B − C, `argmax`, 0 bps) is the primary: §4 tests it
  at α = 0.025 and it is NOT a member of the Bonferroni family. The family
  is the **other 32 gross cells**; a claim from it is tested with the §4
  procedure at α = 0.025 / 32 ≈ 7.81 × 10⁻⁴, and says so. A − C at the
  primary cell is one of the 32: §4 runs it at 0.025 for stop rule 1 and §9
  only. (Until 2026-09-24 the family was all 198 cells at 0.025 / 198 ≈
  1.26 × 10⁻⁴; the net cells left it when they became descriptive. The same
  day, before sealing, text that put the H1 cell inside a family of 33 at
  0.025 / 33 while §4 tested it at 0.025 was made one cell, one α, as above.)
- Test-retest agreement (rows with `prompt_a_sha == prompt_b_sha`), agreement
  of `a.argmax` with `rule_c`, adjective occupancy, drift count: health
  numbers, no inference.
- Arm A's choice-confidence table (P(`a.argmax` correct) per confidence bin,
  with the share of each bin where `a.argmax == rule_c`; CONTRACT §4.7): what
  the old H2 read until 2026-09-24 (§5). Descriptive, no inference, never
  claimed: with `v1`'s criteria restating the rule it measures rule-matching,
  not outcomes. H2's own beside-numbers (§5: ρ, every-tick r, Brier against
  the base rate, tail counts, the `trend`-word comparator) are descriptive
  likewise.

## 7. Power, honestly

Assume the 15-minute paired difference on a block has sd ≈ **33 bps** (the
fixture window's `ret15_sd_bps` was 28.9 bps over 285 overlapping returns in a
quiet five hours; 33 is a round, slightly wider guess for a full month
including violent hours). With one-sided α = 0.025 and power 0.80,
MDE = (1.960 + 0.842) · sd / √n:

| kept days | n blocks | MDE per block | MDE per day (96 blocks) |
|---|---|---|---|
| 28 | 2,688 | **1.78 bps** | 171 bps |
| 27 | 2,592 | 1.82 bps | 174 bps |
| 25 | 2,400 | 1.89 bps | 181 bps |

**The effective-n caveat.** `d_t` — and so S_k — is exactly `0.0` wherever
the two arms are flat through the block, and is only entry-price noise,
`(q_x − q_y) · Δmid` (SPEC §10), where both are long through it on entries
opened at different ticks. The zeros are real samples of the difference
(they are what "the arms agree" costs and earns), but the information sits
in the disagreement blocks (a difference of SIDE) alone. If the arms agree
on a share a of blocks, n_eff = (1 − a) · 2,688 for any effect that lives on
the disagreement blocks:

| agreement a | n_eff | MDE on the disagreement blocks | MDE on the all-block mean |
|---|---|---|---|
| 50 % | 1,344 | 2.5 bps | 1.26 bps |
| 80 % | 538 | 4.0 bps | 0.80 bps |
| 90 % | 269 | 5.6 bps | 0.56 bps |
| 95 % | 134 | 8.0 bps | 0.40 bps |
| 98 % | 54 | 12.6 bps | 0.25 bps |

Two things follow and are accepted now. First, 1.78 bps per block is 171
bps/day: a big edge in direction, measured gross (`FEE_BPS_PRIMARY = 0`). At
the venue's taker (`FEE_BPS_VENUE` = 120 bps, UNVERIFIED, SPEC §10) one extra
round trip per day costs 240 bps — more than the whole daily MDE — which is
why H1 is gross and profitability at retail fees is settled by arithmetic,
not tested (§4).
Second, if `make report` on day 14 shows agreement above 95 % on the primary
cell, the block is under-powered for anything under ~8 bps per disagreement
and the final write-up says so; that is a finding about the prompts, not a
reason to change the test (§8.5).

**H2 (§5, 2026-09-24).** One unit per block, so n ≤ 2,688 at 28 kept days
(blocks whose first live row has a `gap` or a missing noul drop out). By the
Fisher z approximation, the smallest r detected with power 0.80 at one-sided
α = 0.025 is tanh((1.960 + 0.842) / √(n − 3)):

| kept days | n units (all blocks kept) | MDE r | r² |
|---|---|---|---|
| 28 | 2,688 | **0.054** | 0.3 % |
| 25 | 2,400 | 0.057 | 0.3 % |
| 21 | 2,016 | 0.062 | 0.4 % |

That assumes independent units. The horizons do not overlap, but lean and
the 15-minute return can each be autocorrelated across blocks; the block
bootstrap of §5 carries that into the interval, so the realised MDE is
somewhat larger. An r of 0.054 explains 0.3 % of the variance of the return:
a supported H2 says the nouls carry direction information, not that it is
large nor that it goes beyond the `trend` word (§5), and the final write-up
says so beside the Brier scores and the comparator.

## 8. Stop rules — fixed now

1. **Day 28, neither A nor B beats C on H1** (§4 procedure, primary cell at
   0 bps, for B−C and A−C) → the model arms are retired: the loop stops
   sending, arm C and the feed keep logging only if a second
   pre-registration wants them.
2. **B − A ≤ 0** at day 28 (point estimate of mean S_k(B−A, argmax,
   FEE_BPS_PRIMARY = 0 bps) on the sample) → the nightly is stopped (its
   plist booted out); arm A is kept. The rewrite did not add to the frozen
   prompt.
3. **A bad day is excluded, logged, and three of them pause the run.** A UTC
   day is bad when its outcome fill (share of live rows with a non-`gap`
   outcome) is < 95 %, or its Jev error share (rows with `absence: "jev"` over
   rows that reached the ask) is > 5 %. The day is excluded whole from §4–§6
   (H1's blocks and H2's units alike) and one line (`day  fill%  jev-err%  reason`) is appended to
   `data/exclusions.tsv`, which the final write-up reproduces verbatim. On the
   third bad day `data/HALT` is written by hand ("prereg: 3 bad days"), the
   cause is fixed, and sends resume; the calendar does not stop. If fewer than
   21 days are kept at day 28 the block is void, reported as void, and a
   second block is a new pre-registration.
4. **The day-14 look is health only:** `/opt/homebrew/bin/python3 -m
   loop.report --health --t0 <T0>`, which prints report §1–§3 (rows,
   absences, fill, errors, latency, spend, drift, occupancy, test-retest) and
   neither computes nor prints §4–§7. No cell of §4–§7 of the report is read
   — its §6 is H2 (r, ρ, Brier, tails, the `trend` comparator) and its §7 the
   arm-A confidence table, and neither is looked at; a plain `make report`
   prints H1's and H2's statistics on lines of their own, so it is not the
   look, and the same `--health` command serves any routine health check
   during the sample — no bootstrap is run, and the nightly is neither
   stopped nor promoted on the strength of it.
5. **No extension after looking.** The sample ends at T0 + 28 days whatever
   the numbers say; nothing is added to n. A second block is a new
   pre-registration (`prereg-v2`), sealed before its own T0.

## 9. What would falsify what

- H1 rejected for B and not for A: the rewrite earned its keep over the rule.
- H1 rejected for A and not for B: the frozen prompt beat the rule and the
  rewriting hurt (stop rule 2 fires with it).
- Neither: the model arms are no better than four words and three lines of
  `if`, in direction, gross of fees, on this product, over these 28 days
  (stop rule 1).
- H2 not supported: Jev's `up15` / `down15` carry no linear information
  about the next 15-minute return on this product over these 28 days; the
  `noultail` column is then noise around `hold` and is reported as such.
- H2 supported and H1 not: the `trend` word, as Jev maps it into direction
  probabilities, predicts the next 15-minute return, and the rewritten
  action did not beat the rule that already acts on that word. It does not
  show that Jev has a signal the action question ignores: lean tracked the
  word at r 0.99 on the shakedown (§5), and whether Jev adds anything beyond
  it is read only from the descriptive comparator beside the statistic. That
  is a finding for a second pre-registration, not a change to this one.
- Arm A's choice confidence (report §7) falsifies nothing: it is descriptive
  (§5, §6).

## 10. Sealing

```bash
cd ~/Projects/jev-paper-loop && git add PREREG.md && git commit -m "PREREG: T0 and signature" && git tag prereg-v1 "$(git rev-parse HEAD)" && git tag --points-at HEAD
```

The tag must exist before the first row whose `prompt_b` is not `v1` (the
first `bin/promote`), and before the day-14 look. The sealing commit fills the
two fields below and changes nothing else. A file changed after the tag is not
this pre-registration.

## 11. Signature

Written by Claude on 2026-09-23 from the decisions Alex made the same day
(H1 + H2 co-primary over 28 days at the venue's fee; 24 h warm-up; every-15th-
tick samples; block bootstrap; the five stop rules). Amended 2026-09-24,
before any decision row existed, from two decisions Alex made that day: H1 at
0 bps gross, net-of-fee cells descriptive (§4, §6); and `liq` by walking the
book for one $1,000 order (SPEC §4–§5), which changes what arm C's `liq !=
thin` means and so what arm C is. Two review corrections the same day, also
before any decision row, change neither primary's statistic nor its α: §4 says the 0 bps cell is
direction net of the spread (a round trip still pays one spread), not free of
turnover; §6 takes the H1 cell out of the Bonferroni family (H1 at 0.025, the
other 32 gross cells at 0.025 / 32). Amended again 2026-09-24, after the first
181 live shakedown rows and before T0 was set or any sample row existed, from
a decision Alex made that day: H2 moves from arm A's choice confidence to the
direction probabilities, Pearson r between `up15 − down15` and `ret_h_bps`
(§5); its unit, α and bootstrap scheme are unchanged, H1 is untouched, and the
old confidence table stays in the report as descriptive (§6). Review
corrections the same day, also before T0, change neither H2's statistic nor
its α: §5 pins the bootstrap's draw (generator, block count, truncation,
percentile rank) and says what a supported H2 would mean given that lean
tracked the `trend` word on the shakedown, with the word printed beside the
statistic as a descriptive comparator; §1, §7 and §9 read H2 accordingly; §8.4
names the health-only command for the day-14 look.

T0 (first tick_id of day 1): `20260925T214000Z`   Sealed by: `Alex Ward — approved in chat 2026-09-24 ("approved for all"), fields filled by Claude`   on: `2026-09-24T21:40:33Z`

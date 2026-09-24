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
Secondarily, whether the confidence Jev attaches to its choice is worth
anything (H2).

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

This is the "every-15th-tick non-overlapping subsample" of CONTRACT §4.5 made
exact: the block boundaries are the 15th ticks, and the block sum is the
paired 15-minute pnl difference, equal to `position × 15-min return − fees`
whenever no trade falls inside the block. A literal `d_t` at every 15th tick
is a one-minute quantity with 1/15 of the variance and is NOT the statistic
below.

## 4. H1 (co-primary): the nightly's arm beats the rule

- **Statistic:** mean over the sample blocks of `S_k(B − C, "argmax",
  FEE_BPS_PRIMARY)`.
- **Hypothesis:** H0: mean ≤ 0; H1: mean > 0. One-sided, α = 0.025.
- **Inference:** circular block bootstrap of the block series, block length
  = 4 samples = 1 h (the autocorrelation of a 15-min mark decays inside an
  hour; 4 also keeps every day divisible), 10,000 resamples, seed 20260923,
  each resample the same length as the sample, blocks drawn with replacement
  from a circularly wrapped series. Reject H0 iff the 2.5th percentile of the
  resampled means is > 0. Ties (S_k = 0, the agreement blocks) stay in.
- **Reported beside it, no inference:** the same cell on every tick
  (`d_t`, n ≈ 40,320), the count and share of disagreement blocks (a block
  where `replay(...)["position"]` differs between B and C on any tick), the
  mean on disagreement blocks only, trades/day each side. These are
  descriptive.
- The same procedure is run for **A − C** at the primary cell (needed by stop
  rule 1) and reported as secondary.

## 5. H2 (co-primary): choice-confidence calibration on the frozen arm

- **Unit:** the first live row of each block k (`tick_id = T0 + 900k` when
  present, else the first live row in the block; none → the block is dropped),
  so consecutive decisions have non-overlapping horizons.
- **x_k** = `answers.a_action.confidence`. **y_k** = 1 if `columns.a.argmax`
  is correct, else 0, where correct = `buy & up`, `sell & down`, `hold & flat`
  by the outcome label at t + 900 s (SPEC §11); a `gap` outcome drops the
  block.
- **Statistic:** the point-biserial correlation r_pb(x, y) = Pearson r between
  x and the 0/1 y.
- **Hypothesis:** H0: r ≤ 0; H1: r > 0. Supported iff the lower bound of the
  95 % percentile block-bootstrap interval of r (same scheme as §4: block 4 =
  1 h, 10,000 resamples, seed 20260923, resampling the (x, y) pairs) is > 0,
  i.e. one-sided α = 0.025.
- **Degenerate cases, decided now:** if every y_k is equal, or every x_k is
  equal (the model reports one confidence for everything), r is undefined and
  H2 is recorded as "not supported: no variance in {x|y}". A near-constant x
  with a handful of tail values is not degenerate; it is what the 0.99 column
  exists to catch, and the bins of CONTRACT §4.6 are printed beside r.

Both primaries must hold for the experiment to be reported as "the loop
works as described": H1 that the nightly arm earns something net of the
venue's fee, H2 that the number the fast model attaches to its choice carries
information. Either alone is reported as exactly that.

## 6. Secondaries — descriptive, Bonferroni if ever claimed

- **A − C** and **B − A** at the primary cell (B − A is what the nightly adds
  over the frozen prompt; B − A ≤ 0 is stop rule 2).
- Every pair × every column × every fee: 3 pairs (B−C, A−C, B−A) × 11 columns
  (`rules.COLUMNS`) × 4 fees (`FEE_BPS_COLUMNS`) = **132 cells**, printed by
  `make report` with no p-values. If any secondary cell is ever claimed as
  significant it is tested with the §4 procedure at α = 0.025 / 132 ≈
  1.9 × 10⁻⁴, and the claim says so.
- Test-retest agreement (rows with `prompt_a_sha == prompt_b_sha`), agreement
  of `a.argmax` with `rule_c`, adjective occupancy, drift count: health
  numbers, no inference.

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
the two arms carry the same position through the block. The zeros are real
samples of the difference (they are what "the arms agree" costs and earns),
but the information sits in the disagreement blocks alone. If the arms agree
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
bps/day: a big edge, and one extra round trip per day costs 2 × fee = 120 bps
at the placeholder fee and 240 bps if the verified taker fee is 120 bps (SPEC
§10), so a B that trades more than C must earn back a lot before it shows.
Second, if `make report` on day 14 shows agreement above 95 % on the primary
cell, the block is under-powered for anything under ~8 bps per disagreement
and the final write-up says so; that is a finding about the prompts, not a
reason to change the test (§8.5).

## 8. Stop rules — fixed now

1. **Day 28, neither A nor B beats C on H1** (§4 procedure, primary cell, for
   B−C and A−C) → the model arms are retired: the loop stops sending, arm C
   and the feed keep logging only if a second pre-registration wants them.
2. **B − A ≤ 0** at day 28 (point estimate of mean S_k(B−A, argmax,
   FEE_BPS_PRIMARY) on the sample) → the nightly is stopped (its plist booted
   out); arm A is kept. The rewrite did not add to the frozen prompt.
3. **A bad day is excluded, logged, and three of them pause the run.** A UTC
   day is bad when its outcome fill (share of live rows with a non-`gap`
   outcome) is < 95 %, or its Jev error share (rows with `absence: "jev"` over
   rows that reached the ask) is > 5 %. The day is excluded whole from §4–§6
   and one line (`day  fill%  jev-err%  reason`) is appended to
   `data/exclusions.tsv`, which the final write-up reproduces verbatim. On the
   third bad day `data/HALT` is written by hand ("prereg: 3 bad days"), the
   cause is fixed, and sends resume; the calendar does not stop. If fewer than
   21 days are kept at day 28 the block is void, reported as void, and a
   second block is a new pre-registration.
4. **The day-14 look is health only:** `make report` §1–§3 (rows, absences,
   fill, errors, latency, spend, drift, occupancy, test-retest). No cell of
   §4–§6 of the report is read, no bootstrap is run, and the nightly is
   neither stopped nor promoted on the strength of it.
5. **No extension after looking.** The sample ends at T0 + 28 days whatever
   the numbers say; nothing is added to n. A second block is a new
   pre-registration (`prereg-v2`), sealed before its own T0.

## 9. What would falsify what

- H1 rejected for B and not for A: the rewrite earned its keep over the rule.
- H1 rejected for A and not for B: the frozen prompt beat the rule and the
  rewriting hurt (stop rule 2 fires with it).
- Neither: the model arms are no better than four words and three lines of
  `if`, at this fee, on this product, over these 28 days (stop rule 1).
- H2 not supported: the confidence is not a probability of being right on
  this task; the `c*` columns are then noise around `argmax` and are reported
  as such.

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
tick samples; block bootstrap; the five stop rules).

T0 (first tick_id of day 1): `____________________`   Sealed by: `____________`   on: `____________`

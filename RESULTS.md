jev-paper-loop inference (PREREG §4-§5), mode sample, run at 2026-10-26T02:44Z
v2 draft tag absent: v2 as drafted is not run; a second block is a new pre-registration written after v1 was read
(NO_V2=1 given; the guard found: no annotated tag prereg-v2-draft)
  python 3.14.6 (main, Jun 10 2026, 10:03:53) [Clang 21.0.0 (clang-2100.0.123.102)]
  log /Users/alexanderward/Projects/JEV/jev-paper-loop/data/decisions.jsonl: 64310097 bytes, sha256 ce9a0e75d29b5cc1b8d07d7d60de0f325d8cd63a81e695f8d0c159d031eb53f8, last tick_id 20261017T050700Z (a later copy: head -c 64310097 FILE | shasum -a 256); skipped lines 0; rows in scope 29845
  T0 2026-09-25T21:40Z; anchor for blocks and days T0
  days kept 22 of 28; excluded [23, 24, 25, 26, 27, 28] (/Users/alexanderward/Projects/JEV/jev-paper-loop/data/exclusions.tsv, reproduced below)
  bootstrap: circular blocks of 4, 10000 resamples, seed 20260923, one generator per statistic; lower bound = sorted[249] (nearest-rank 2.5th percentile); reject iff > 0
  --accept-pending given: 1 H2 unit(s) whose t + h the log has not reached are counted as gaps (for a log that really stopped; without the flag the run is refused): 20261017T045500Z

H1 -- mean S_k of the paired 15-minute pnl difference, column argmax, 0 bps (gross of fees, net of the spread)
  descriptive: blocks on which a gap longer than the horizon lands 16 of 2112 (SPEC §10: the move across a gap is marked on the first priced tick after it; kept as pre-registered)
  B - C: H1 (co-primary): B - C at the primary cell, alpha 0.025
    n blocks 2112; mean S_k -0.2752 bps; lower bound -0.8086 bps -> not rejected
    descriptive, kept days only: disagreement blocks 382 (18.1%), mean S_k on them -1.5195; every tick mean d_t -0.0195 over 29844; trades 597 vs 797 (27.14 vs 36.23 per day over 22 kept days); forced holds 327 vs 327
  A - C: A - C at the primary cell, alpha 0.025: stop rule 1's input and §9's reading only (a claim would be a §6 secondary)
    n blocks 2112; mean S_k 0.0000 bps; lower bound 0.0000 bps -> not rejected
    descriptive, kept days only: disagreement blocks 0 (0.0%), mean S_k on them n/a; every tick mean d_t 0.0000 over 29844; trades 797 vs 797 (36.23 vs 36.23 per day over 22 kept days); forced holds 327 vs 327
  B - A: B - A at the primary cell: point estimate only, stop rule 2 (<= 0 stops the nightly)
    n blocks 2112; mean S_k -0.2752 bps; lower bound n/a bps -> no test (point estimate)
    descriptive, kept days only: disagreement blocks 382 (18.1%), mean S_k on them -1.5195; every tick mean d_t -0.0195 over 29844; trades 597 vs 797 (27.14 vs 36.23 per day over 22 kept days); forced holds 327 vs 327

H2 -- Pearson r(lean, ret_h_bps) over the units (first live row of each block), alpha 0.025
  n units 1969 (blocks with a live row 1986; dropped {'gap': 17}); r -0.0133; lower bound -0.0683 -> not rejected
  descriptive (PREREG §5, never claimed): Spearman rho -0.0117 over the 1969 units; every kept live row (overlapping horizons; a second decision in a minute shares its outcome): r -0.0108, rho -0.0208 over 29452 rows (dropped: gap 66, missing noul 0)
  descriptive: Brier on the units up15 0.2517 vs base 0.2403 (p(up) 0.402); down15 0.2541 vs base 0.2414 (p(down) 0.407); on every kept live row up15 0.2489 vs base 0.2387 (p(up) 0.393); down15 0.2512 vs base 0.2416 (p(down) 0.408)
  descriptive: measured tails (>= 0.99 / < 0.15) on the units up15 0/0, down15 0/0; on every kept live row up15 0/0, down15 0/0
  descriptive: the trend word (no model): units r(lean, trend) 0.9648; r(trend, ret_h_bps) -0.0208; r(lean, ret_h_bps | trend flat) 0.0495 over 1392; every kept live row r(lean, trend) 0.9651; r(trend, ret_h_bps) -0.0130; r(lean, ret_h_bps | trend flat) 0.0327 over 21051

reading (PREREG §5, §8-§9): the stop rules and what the verdicts above mean, nothing new tested
  stop rule 1: B-C reject=False, A-C reject=False -> fires
    (§8.1: fires when neither B - C nor A - C rejects on H1, whatever H2 shows: the model arms are retired)
  stop rule 2: mean S_k(B-A) = -0.2752 -> fires
    (§8.2: fires when the point estimate of mean S_k(B - A, argmax, 0 bps) is <= 0: the nightly is stopped, arm A kept)
  primaries: H1 (B - C) reject=False, H2 reject=False -> neither primary holds
  H1 (§9): neither A nor B beats C on H1: the model arms are no better than four words and three lines of `if`, in direction, gross of fees, on this product, over these 28 days (stop rule 1)
  H2 (§9): H2 not supported: Jev's up15 / down15 carry no linear information about the next 15-minute return on this product over these 28 days; the noultail column is then noise around hold
  Secondaries (§6) are not tested here; a claim from the 32 gross secondaries would take alpha 0.025 / 32.

per kept day (descriptive): blocks holding a live row, of 96, and the H2 units the day gave
  d01  55/96 blocks  40 units
  d02  96/96 blocks  96 units
  d03  96/96 blocks  96 units
  d04  96/96 blocks  96 units
  d05  96/96 blocks  96 units
  d06  96/96 blocks  96 units
  d07  77/96 blocks  76 units
  d08  96/96 blocks  96 units
  d09  96/96 blocks  96 units
  d10  96/96 blocks  96 units
  d11  96/96 blocks  96 units
  d12  96/96 blocks  96 units
  d13  96/96 blocks  96 units
  d14  96/96 blocks  96 units
  d15  96/96 blocks  96 units
  d16  96/96 blocks  96 units
  d17  96/96 blocks  96 units
  d18  96/96 blocks  96 units
  d19  96/96 blocks  96 units
  d20  96/96 blocks  96 units
  d21  96/96 blocks  96 units
  d22  30/96 blocks  29 units

stop rule 3 cross-check (PREREG §8.3, descriptive; the exclusions file above decides, this changes no number):
  BAD by the rule, recomputed from the log: none (0; the rule pauses the run at 3)
  listed and BAD: none; listed but judged fine by the rule: none; BAD but NOT listed: none
  open, not yet judged (a day's last t + h is not in the log): d22
  no live rows (0/0, the rule undefined; Alex's call; includes any day after the log's last row): d23 d24 d25 d26 d27 d28, listed: d23 d24 d25 d26 d27 d28

/Users/alexanderward/Projects/JEV/jev-paper-loop/data/exclusions.tsv, verbatim:
  d23	n/a	n/a	NO LIVE ROWS: the plists named the old repo path after the move at 2026-10-17 05:07Z
  d24	n/a	n/a	NO LIVE ROWS: the plists named the old repo path after the move at 2026-10-17 05:07Z
  d25	n/a	n/a	NO LIVE ROWS: the plists named the old repo path after the move at 2026-10-17 05:07Z
  d26	n/a	n/a	NO LIVE ROWS: the plists named the old repo path after the move at 2026-10-17 05:07Z
  d27	n/a	n/a	NO LIVE ROWS: the plists named the old repo path after the move at 2026-10-17 05:07Z
  d28	n/a	n/a	NO LIVE ROWS: the plists named the old repo path after the move at 2026-10-17 05:07Z

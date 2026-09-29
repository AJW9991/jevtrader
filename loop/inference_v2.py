"""loop/inference_v2.py -- PREREG-v2's day-28 inference over every product's store, run once.

v1's loop/inference.py stays byte for byte as it is (v1's readers, its golden test and `results-v1` read it); this
module reads PREREG-v2.md and nothing of PREREG.md's inference. It takes from v1 only the draw itself
(inference.resample_indices, PREREG-v1 §5 step 2, which PREREG-v2 §5 names) and the one-read log reader.

The draw and the bound (PREREG-v2 §5, §6): a circular block bootstrap of a cell's pooled block series in block order,
L = 4 units of the cell's own cadence, R = 10,000 resamples each the length of the series, one random.Random(seed)
per cell (H1 20261023; family F 20261024..20261027 in §6's order), the mean of each resample; the bound is
sorted[ceil(alpha R) - 1] of the sorted resampled means, nearest rank, integer arithmetic, no interpolation:
sorted[249] at alpha = 1/40 (H1) and sorted[62] at alpha = 1/160 (every F cell, and stop rule 1's A - C). alpha is a
fractions.Fraction everywhere and alpha_rank refuses anything else: as floats 0.025 x 10,000 happens to be 250.0,
but 0.00625 x 10,000 is 62.5, where round() and int() both give 62, i.e. sorted[61], and a float alpha from any other
arithmetic can land a hair either side of an integer. F never reuses v1's inference.bootstrap, whose rank is 0.025's
alone. Ties (a block whose S-bar_k is 0.0) stay in.
Standard library only."""
import math, random
from fractions import Fraction

from . import inference

SEED_H1 = 20261023                     # PREREG-v2 §5; family F's cell i takes SEED_H1 + i (§6)
RESAMPLES = 10000                      # R
BLOCK_LEN = 4                          # L, in units of the cell's own cadence: 1 h at 900 s, 4 h at 3,600 s, 16 h at 14,400 s
ALPHA_H1 = Fraction(1, 40)             # §5: H1's one-sided level, sorted[249] at R = 10,000
ALPHA_F = Fraction(1, 160)             # §6: each family-F cell's level (and stop rule 1's A - C), sorted[62]


def alpha_rank(alpha, resamples):
    """The 0-based index of the one-sided bound among `resamples` sorted values: ceil(alpha x R) - 1, exact.
    alpha must be a Fraction in (0, 1) and R a positive int: a float alpha is refused (TypeError), never rounded."""
    if not isinstance(alpha, Fraction):
        raise TypeError(f"alpha must be a fractions.Fraction (PREREG-v2 §5: an exact fraction, never a float), got {alpha!r}")
    if not 0 < alpha < 1:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError(f"resamples must be a positive int, got {resamples!r}")
    return math.ceil(alpha * resamples) - 1


def bootstrap(series, seed, alpha, resamples=RESAMPLES, L=BLOCK_LEN):
    """One cell's bootstrap: {"n", "rank", "lower", "reject", "sorted"}. `series` is the cell's pooled values in block
    order (S-bar_k, the kept blocks only); each resample is inference.resample_indices(rng, n, L) over them with one
    random.Random(seed) drawn continuously through the R resamples, its statistic the mean; the bound is
    sorted[alpha_rank(alpha, R)]; reject iff it is > 0. An empty series is no test (lower None, reject False)."""
    rank = alpha_rank(alpha, resamples)
    n = len(series)
    if n == 0:
        return {"n": 0, "rank": rank, "lower": None, "reject": False, "sorted": []}
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        idx = inference.resample_indices(rng, n, L)
        means.append(sum([series[i] for i in idx]) / n)
    means.sort()
    lower = means[rank]
    return {"n": n, "rank": rank, "lower": lower, "reject": lower > 0, "sorted": means}

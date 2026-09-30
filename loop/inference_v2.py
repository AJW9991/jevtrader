"""loop/inference_v2.py -- PREREG-v2's day-28 inference over every product's store, run once (make results).

    python3 -m loop.inference_v2 --sample [--out RESULTS-v2.md] [--accept-pending] [--no-seal]

v1's loop/inference.py stays byte for byte as it is (v1's readers, its golden test and `results-v1` read it); this
module reads PREREG-v2.md and nothing of PREREG.md's inference. It takes from v1 only the draw itself
(inference.resample_indices, PREREG-v1 §5 step 2, which PREREG-v2 §5 names) and the one-read log reader.

It REFUSES (exit 3, before any log is opened) while PREREG-v2.md §12's T0_v2 is blank or malformed, before
T0_v2 + 28 d on the clock, and while the seal check fails (§10's inference bullet, §13: the annotated tag prereg-v2-seal
exists and is an ancestor of HEAD, and `bin/seal-check --since prereg-v2-seal` exits 0) unless --no-seal, which `make
results NO_SEAL=1` passes and RESULTS-v2 §0 and the header record; and (exit 3, after reading) while the sample's last
day is open: d28 closes, and stop rule 3 can judge its last live rows, once some product's log has reached a tick at or
after T0_v2 + 28 d + h + 30 s (report.days_table's closure, ~16 min after the sample ends). --accept-pending is for logs
that really stopped: every sample day is then closed and a live row whose t + h never came counts as a gap, and the
header says so. It is refused (exit 3, before any log is opened) until a minute after the minute d28's closing tick
falls in: before then no running loop could have written that tick, so no log can be said to have stopped short of it,
and the flag would only turn the last rows' pending outcomes into gaps (PREREG-v2 says nothing of the flag; v1's
inference.py is its precedent). Neither the clock nor the resample count is a flag: main(argv, now=, resamples=) takes
them for the tests, and a run at R != 10,000 says it is not the pre-registered one. T0_v2 is §12's, read through dash.read_t0_v2, and nothing else.

What it computes (PREREG-v2 §2, §4-§7, §9; SPEC §10), in this order:
- Stores: config.store(p).decisions for p in config.PRODUCTS, each read once (inference.read_log: the sha and the byte
  length printed are of the bytes the rows were parsed from). The sample is T0_v2 <= tick_id < T0_v2 + 28 d, cut
  before any replay; the outcome join is over each product's whole log. A product whose log is absent has no row.
- Stop rule 3 (§9.3) recomputed per product from its own log (report.days_table, T0_v2-anchored, every product's days
  closing on the latest tick any product's log has reached; exclusions_v2.recompute): BAD days and closed days with no
  live row. The recomputed set governs; data/exclusions-v2.tsv is printed verbatim beside it and every disagreement is
  named. Void (§9.4): a product with fewer than 21 kept days leaves the pool; none with 21 -> the block is VOID and reads
  neither rule 1 nor rule 2.
- §4 (pooled): per pooled product p and cadence c, book.at_cadence(rows_p, c, T0_v2) replayed by book.replay from flat
  at T0_v2 over every sample row, excluded days included; S_k,p(X - Y) = the sum over block k's ticks of d_t, the two
  arms' pnl difference at argmax and 0 bps; S-bar_k = the mean over the pooled products whose day holding block k is
  kept of S_k,p; a block with none is dropped (no placeholder), and a kept block with no row is S_k,p = 0.0 (an empty
  sum). The sums run in the order report.cadence_table's run, so its pooled cells are these series to the bit.
- §5 H1 and §6 family F (bootstrap, below). F4 is withdrawn, neither bootstrapped nor read, when §9.2's row set holds no
  promotion: the NO PROMOTION check runs before B - A is read.
- §9 rules 1-2 from the verdicts: rule 1 fires when neither H1 nor F3 rejects; rule 2 reads NO PROMOTION when no live
  row on a kept product-day of a pooled product has prompt_b_sha != prompt_a_sha, else fires when the point estimate
  mean S-bar_k(B - A) at 900 s is <= 0. §11's reading of what was rejected.
- §7's figures, measured: per tested cell the pooled disagreement-block share f, n_eff = f n (the disagreement blocks),
  the sd of S-bar_k and the MDE (z = the one-sided alpha's quantile + power 0.80's) on all blocks and on the
  disagreement blocks alone; rho between each pair of pooled products' S_k,p over the blocks both keep; gap_blocks.
- Descriptive, never tested: report.cadence_table at §6's fee columns (pairs x columns x fees x cadences, per product and
  pooled, D - B and D - C at argmax only, the minute-cadence B - C, trades/day per arm and product, and after each
  replay cadence §6's fee arithmetic: E_X,p at 0 and 90 bps over kept days, pooled sums, f*_X for A, B, C, D and
  buy-and-hold, the 30-day account-level volume, the tiers of §12's table, each pair's Delta and f*_XY); arm D's
  agreement and A's agreement with C; the direction probabilities per product (PREREG-v1 §5's beside-numbers).
RESULTS-v2 §0 (§8, §9.5, §13): the seal check as main made it (the tag, its commit and HEAD, bin/seal-check's exit and
output verbatim, `git diff -U0 prereg-v2-seal HEAD` verbatim, and NO_SEAL=1 when given), data/looks.tsv verbatim,
the set of spec_sha over the sample's rows, which must hold exactly one value (main refuses, exit 3 after reading, on two
or more unless NO_SEAL=1, §13's one override, which the header and §0 then record; no sample row at all is a void block,
reported as void, not a refusal), and each product-day's prompt_b set, naming every product-day with two or more values
(§8: a promotion takes effect at a day's first tick, so a product-day carries one; a row stopped before the prompts step
has a null prompt_b and carries none).

The draw and the bound (PREREG-v2 §5, §6): a circular block bootstrap of a cell's pooled block series in block order,
L = 4 units of the cell's own cadence, R = 10,000 resamples each the length of the series, one random.Random(seed)
per cell (H1 20261023; family F 20261024..20261027 in §6's order), the mean of each resample; the bound is
sorted[ceil(alpha R) - 1] of the sorted resampled means, nearest rank, integer arithmetic, no interpolation:
sorted[249] at alpha = 1/40 (H1) and sorted[62] at alpha = 1/160 (every F cell, and stop rule 1's A - C). alpha is a
fractions.Fraction everywhere and alpha_rank refuses anything else: as floats 0.025 x 10,000 happens to be 250.0,
but 0.00625 x 10,000 is 62.5, where round() and int() both give 62, i.e. sorted[61], and a float alpha from any other
arithmetic can land a hair either side of an integer. F never reuses v1's inference.bootstrap, whose rank is 0.025's
alone. Ties (a block whose S-bar_k is 0.0) stay in. At day 28 a cell of 2,688 blocks takes ~12 s (R x ceil(n/4)
draws), the five ~1 min; report.cadence_table ~2 min on three products of minute rows.
Standard library only. --out writes a NEW file and never overwrites one."""
import argparse, collections, datetime, math, os, random, statistics, subprocess, sys
from fractions import Fraction

from . import book, config, dash, exclusions_v2, inference, nights, outcomes, report

SEED_H1 = 20261023                     # PREREG-v2 §5; family F's cell i takes SEED_H1 + i (§6)
RESAMPLES = 10000                      # R
BLOCK_LEN = 4                          # L, in units of the cell's own cadence: 1 h at 900 s, 4 h at 3,600 s, 16 h at 14,400 s
ALPHA_H1 = Fraction(1, 40)             # §5: H1's one-sided level, sorted[249] at R = 10,000
ALPHA_F = Fraction(1, 160)             # §6: each family-F cell's level (and stop rule 1's A - C), sorted[62]
N_DAYS = report.SAMPLE_DAYS            # 28: the sample [T0_v2, T0_v2 + 28 d) (§2)
MIN_KEPT_DAYS = 21                     # §9.4: a product with fewer kept days is void and leaves the pool
EXIT_REFUSED = 3                       # every refusal of the pre-registered run (v1's code, kept)
POWER = 0.8                            # §7: the MDE's power (z = 1.960 + 0.842 at alpha 1/40)
# §6's printed fee columns, transcribed: 0 = gross (the primary), 2 = Binance.US, 10 = the article's, 25, 50 and 90 = the
# venue's retail maker and taker, read in-account 2026-09-27; config.FEE_BPS_COLUMNS holds the same six (tests/test_config.py).
FEE_COLUMNS = (0.0, 2.0, 10.0, 25.0, 50.0, 90.0)
SEAL_TAG = "prereg-v2-seal"            # §13: v2's make results checks it and runs bin/seal-check --since it
SEAL_CHECK_TIMEOUT_S = 3600            # bin/seal-check may run `make test` (§13 (e)); a hung tool is a failed check
Cell = collections.namedtuple("Cell", "name x y c seed alpha says")
CELLS = (Cell("H1", "b", "c", 900, SEED_H1, ALPHA_H1, "the nightly's arm beats the rule, pooled, decided once per 15-minute block"),
         Cell("F1", "b", "c", 3600, SEED_H1 + 1, ALPHA_F, "B's decisions, acted on once an hour, beat C's"),
         Cell("F2", "b", "c", 14400, SEED_H1 + 2, ALPHA_F, "B's decisions, acted on every four hours, beat C's"),
         Cell("F3", "a", "c", 900, SEED_H1 + 3, ALPHA_F, "a fixed non-rule prompt beats the rule (v1 could not ask this)"),
         Cell("F4", "b", "a", 900, SEED_H1 + 4, ALPHA_F, "the nightly adds to the frozen prompt"))
UTC = datetime.timezone.utc


# ---- the draw and the bound (§5) ---------------------------------------------------------------------------------------
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


def frac(a):
    return f"{a.numerator}/{a.denominator}"


# ---- §4: the pooled statistic ------------------------------------------------------------------------------------------
def day_of_block(k, c):
    """The T0_v2-anchored day N (d N = [T0_v2 + 86400 (N - 1), T0_v2 + 86400 N)) holding c-block k: c divides 86,400 at
    every cadence, so a block nests in one day."""
    return c * k // 86400 + 1


def pooled(per, t0, c, x, y, excluded, pool, cache=None):
    """§4 for the pair X - Y at cadence c, argmax, 0 bps. per: {product: its sample rows}; excluded: {(N, product)}, the
    recomputed stop-rule-3 set; pool: the non-void products, in config.PRODUCTS order. Returns {"series": [(k, S-bar_k)]
    over the blocks with a kept pooled product, "S_p": {p: {k: S_k,p}}, "hot_p": {p: p's disagreement blocks}, "hot":
    the pooled disagreement blocks (a kept product's disagreement tick in them), "pdis": disagreement product-blocks,
    "n_blocks": 28 x 86,400 / c}. A disagreement tick is report._disagreement's: the arms' SIDES differ into or out of it.
    cache: {(p, c): the at_cadence rows, (p, arm, c): the replay}, shared by the cells of one run (H1, F3 and F4 are all at
    900 s): a replay depends on the product, the arm and the cadence alone at argmax and 0 bps."""
    n = N_DAYS * 86400 // c
    cache = {} if cache is None else cache
    S_p, hot_p = {}, {}
    for p in pool:
        if (p, c) not in cache:
            cache[(p, c)] = book.at_cadence(per[p], c, t0)
        for a in (x, y):
            if (p, a, c) not in cache:
                cache[(p, a, c)] = book.replay(cache[(p, c)], None, a, "argmax", config.FEE_BPS_PRIMARY)
        px, py = cache[(p, x, c)], cache[(p, y, c)]
        dis = report._disagreement(px, py)
        s, h = collections.defaultdict(float), set()
        for t, _ in px["equity"]:                               # tick order, a minute's two rows folded (book.replay)
            k = int((report.tick_epoch(t) - t0) // c)
            s[k] += px["pnl_bps_per_tick"][t] - py["pnl_bps_per_tick"][t]
            if t in dis:
                h.add(k)
        S_p[p], hot_p[p] = dict(s), h
    series, hot, pdis = [], set(), 0
    for k in range(n):
        ps = [p for p in pool if (day_of_block(k, c), p) not in excluded]
        if not ps:
            continue                                            # no placeholder
        v = sum(S_p[p].get(k, 0.0) for p in ps) / len(ps)
        series.append((k, v))
        nd = sum(1 for p in ps if k in hot_p[p])
        pdis += nd
        if nd:
            hot.add(k)
    return {"series": series, "S_p": S_p, "hot_p": hot_p, "hot": hot, "pdis": pdis, "n_blocks": n}


def tested(per, t0, excluded, pool, promoted, resamples=RESAMPLES):
    """H1 and family F (§5, §6), in CELLS' order: {name: {"cell", "n", "mean", "rank", "lower", "reject", "withdrawn",
    "dis", "pdis", "share", "mean_dis", plus pooled()'s}}. F4 is withdrawn (no bootstrap, reject None) when `promoted`
    is false (§9.2's NO PROMOTION)."""
    out, cache = {}, {}
    for cell in CELLS:
        s = pooled(per, t0, cell.c, cell.x, cell.y, excluded, pool, cache)
        vals = [v for _, v in s["series"]]
        withdrawn = cell.name == "F4" and bool(pool) and not promoted     # a void block has no row set to read (§9.4)
        bs = None if withdrawn else bootstrap(vals, cell.seed, cell.alpha, resamples)
        dv = [v for k, v in s["series"] if k in s["hot"]]
        out[cell.name] = dict(s, cell=cell, n=len(vals), mean=inference.mean(vals), rank=alpha_rank(cell.alpha, resamples),
                              lower=bs["lower"] if bs else None, reject=bs["reject"] if bs else None, withdrawn=withdrawn,
                              dis=len(dv), share=report._rate(len(dv), len(vals)), mean_dis=inference.mean(dv))
    return out


def rules12(cells, void, promoted):
    """§9.1-§9.2 from the verdicts: rule1 True (fires) / False / None (void); rule2 "NO PROMOTION" / True (fires: the
    point estimate is <= 0) / False / None (void, or no block)."""
    if void:
        return {"rule1": None, "rule2": None}
    rule1 = not (cells["H1"]["reject"] or cells["F3"]["reject"])
    ba = cells["F4"]["mean"]
    rule2 = "NO PROMOTION" if not promoted else None if ba is None else ba <= 0
    return {"rule1": rule1, "rule2": rule2}


# ---- the run -----------------------------------------------------------------------------------------------------------
def _iso(epoch):
    return report._iso_minute(epoch)


def _f(x, nd=4):
    return "n/a" if x is None else f"{x:.{nd}f}"


def load(products):
    """[{"product", "log", "missing", "rows", "bad", "sha", "bytes"}] for each product's store, each log read once."""
    out = []
    for p in products:
        path = config.store(p).decisions
        if not os.path.exists(path):
            out.append({"product": p, "log": path, "missing": True, "rows": [], "bad": [], "sha": None, "bytes": 0})
            continue
        rows, bad, sha, nbytes = inference.read_log(path)
        out.append({"product": p, "log": path, "missing": False, "rows": rows, "bad": bad, "sha": sha, "bytes": nbytes})
    return out


def last_reached(stores, now):
    """The latest tick any product's whole log has reached on the clock (report.last_reached per log), or None."""
    return max((x for x in (report.last_reached(s["rows"], now) for s in stores) if x is not None), default=None)


def closes_at(t0):
    """The tick d28 closes on (report.days_table: a day closes once the log's last tick is >= its end + h + 30 s)."""
    return t0 + N_DAYS * 86400 + config.HORIZON_S + outcomes.JOIN_TOL_S


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=120)


def seal(repo=None):
    """§10's inference bullet and §13: {"ok", "why" (the first failure, None when ok), "lines" (§0's seal lines)}. ok when
    the annotated tag prereg-v2-seal exists (`git rev-parse -q --verify refs/tags/prereg-v2-seal^{tag}`), is an ancestor
    of HEAD (`git merge-base --is-ancestor`), and `bin/seal-check --since prereg-v2-seal` (run in `repo`, its output
    printed verbatim) exits 0; §0 also prints `git diff -U0 prereg-v2-seal HEAD` verbatim (§13). Before --since, §0
    prints `bin/seal-check --at prereg-v2-seal` verbatim: the seal's own verdict replayed on the sealed commit, which is
    what §13 has RESULTS-v2 §0 print of the seal (the full -U0 diff from the draft tag, seal-check's verdict, the --stat
    of the excluded paths, each listed deviation's diff, and the T0_v2 re-derivation if there was one); it is printed,
    not a gate (§13 gates make results on --since alone), and its verdict line is repeated after it. bin/seal-check is
    another stage's tool: absent or not executable, the check fails. The tool reads the logs for T_first_v2 (§2) and
    nothing else of them; this function opens no log."""
    repo = config.REPO if repo is None else repo
    lines, why = [], None
    try:
        t = _git(repo, "rev-parse", "-q", "--verify", f"refs/tags/{SEAL_TAG}^{{tag}}")
        if t.returncode != 0:
            why = f"no annotated tag {SEAL_TAG}"
            return {"ok": False, "why": why, "lines": [f"  seal: {why} in {repo}: nothing else checked"]}
        commit = _git(repo, "rev-parse", "-q", "--verify", f"{SEAL_TAG}^{{commit}}").stdout.strip()
        head = _git(repo, "rev-parse", "-q", "--verify", "HEAD").stdout.strip()
        if _git(repo, "merge-base", "--is-ancestor", SEAL_TAG, "HEAD").returncode != 0:
            why = f"{SEAL_TAG} is not an ancestor of HEAD"
            lines.append(f"  seal: annotated tag {SEAL_TAG} {t.stdout.strip()} (commit {commit}): NOT an ancestor of HEAD {head}")
        else:
            lines.append(f"  seal: annotated tag {SEAL_TAG} {t.stdout.strip()} (commit {commit}), an ancestor of HEAD {head}")
        tool = os.path.join(repo, "bin", "seal-check")
        if not (os.path.isfile(tool) and os.access(tool, os.X_OK)):
            why = why or "bin/seal-check is not in this tree (PREREG-v2 §10 builds it in the draft tree)"
            lines.append(f"  bin/seal-check --since {SEAL_TAG}: NOT RUN: {tool} is absent or not executable")
        else:
            a = subprocess.run([tool, "--at", SEAL_TAG], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=SEAL_CHECK_TIMEOUT_S)
            lines.append(f"  bin/seal-check --at {SEAL_TAG} (the seal's verdict replayed on the sealed commit, PREREG-v2 §13; printed,"
                         f" not a gate): exit {a.returncode}, its output verbatim:")
            out = (a.stdout + a.stderr).splitlines()
            lines += [f"    | {l}" for l in out]
            lines.append(f"  the seal's verdict, replayed: {'PASS' if a.returncode == 0 else 'FAIL'} (exit {a.returncode})")
            r = subprocess.run([tool, "--since", SEAL_TAG], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=SEAL_CHECK_TIMEOUT_S)
            if r.returncode != 0:
                why = why or f"bin/seal-check --since {SEAL_TAG} exited {r.returncode}"
            lines.append(f"  bin/seal-check --since {SEAL_TAG}: exit {r.returncode}, its output verbatim:")
            lines += [f"    | {l}" for l in (r.stdout + r.stderr).splitlines()]
        d = _git(repo, "diff", "-U0", SEAL_TAG, "HEAD")
        lines.append(f"  git diff -U0 {SEAL_TAG} HEAD (PREREG-v2 §13), verbatim:" if d.returncode == 0 else
                     f"  git diff -U0 {SEAL_TAG} HEAD: FAILED (exit {d.returncode}): {d.stderr.strip()}")
        lines += [f"    | {l}" for l in d.stdout.splitlines()] if d.returncode == 0 else []
        if d.returncode == 0 and not d.stdout.strip():
            lines.append("    (empty: HEAD is the sealed tree)")
    except (OSError, subprocess.SubprocessError) as e:
        why = f"git could not be run: {e}" if why is None else why
        lines.append(f"  seal: the check could not complete: {type(e).__name__}: {e}")
        return {"ok": False, "why": why, "lines": lines}
    return {"ok": why is None, "why": why, "lines": lines}


def seal_lines(sealed, no_seal):
    """§0's seal lines: main's check (seal()) and NO_SEAL=1 when given (§13: the override is recorded)."""
    if sealed is None:
        lines = ["  seal: NOT CHECKED: run() was called without main's seal check (a test, never the result)"]
    else:
        lines = list(sealed["lines"])
    if no_seal:
        lines.append("  NO_SEAL=1 given (make results NO_SEAL=1, --no-seal): " +
                     ("the seal check passed; nothing was overridden" if sealed is not None and sealed["ok"] else
                      f"the seal check FAILED and was overridden: {sealed['why'] if sealed else 'not checked'}"))
    return lines


def read_looks(path=None):
    """data/looks.tsv as {"path", "lines" (None when absent), "error"}: RESULTS-v2 §0 reproduces it verbatim (§9.5)."""
    path = config.LOOKS if path is None else path
    if not os.path.exists(path):
        return {"path": path, "lines": None, "error": None}
    try:
        with open(path, encoding="utf-8") as fh:
            return {"path": path, "lines": fh.read().splitlines(), "error": None}
    except (OSError, UnicodeDecodeError) as e:
        return {"path": path, "lines": None, "error": str(e)}


def prompt_b_days(rows, t0):
    """§8: {N: the set of non-null prompt_b over one product's sample rows on day N}, N = 1 .. 28. A null prompt_b (a row
    stopped before the prompts step, cycle.new_row's) names no version and is left out."""
    out = {n: set() for n in range(1, N_DAYS + 1)}
    for r in rows:
        v = r.get("prompt_b")
        if v is not None:
            out[report._day_n(r, t0)].add(str(v))
    return out


def prompt_b_lines(pb):
    """§8's lines of §0: per product, the sample days as runs of one prompt_b set ({} for none), a day with two or more
    values on its own and marked; then every such product-day named."""
    lines = ["  prompt_b per product-day (PREREG-v2 §8: every row of a product-day carries one; over the sample's rows that"
             " reached the prompts step, a null prompt_b carrying none):"]
    named = []
    for p, days in pb.items():
        runs = []                                               # [first day, last day, the set]
        for n in range(1, N_DAYS + 1):
            v = frozenset(days[n])
            if len(v) > 1:
                named.append(f"{p} d{n:02d}")
            if runs and runs[-1][2] == v and len(v) < 2:
                runs[-1][1] = n
            else:
                runs.append([n, n, v])
        parts = []
        for a, b, v in runs:
            vs = ", ".join(sorted(v, key=lambda x: (len(x), x)))          # v2 before v10
            parts.append((f"d{a:02d}" if a == b else f"d{a:02d}-d{b:02d}") + f" {{{vs}}}"
                         + (f" {'TWO' if len(v) == 2 else len(v)} VALUES" if len(v) > 1 else ""))
        lines.append(f"    {p}: " + "; ".join(parts))
    lines.append("  product-days with two or more prompt_b values (§8): " + (", ".join(named) or "none"))
    return lines


def section0(looks, shas, tree_sha, pb=None, sealed=None, no_seal=False):
    """RESULTS-v2 §0: the seal check (seal_lines), the looks verbatim, the sample's spec_sha set (§9.5, §13) and, with
    `pb` (prompt_b_days per product), each product-day's prompt_b set (§8)."""
    lines = ["§0. The seal, the looks, the sample's spec_sha and prompt_b (PREREG-v2 §8, §9.5, §13)"] + seal_lines(sealed, no_seal)
    if looks["error"]:
        lines.append(f"  {looks['path']}: cannot be read: {looks['error']}")
    elif looks["lines"] is None:
        lines.append(f"  {looks['path']}: absent: no `report --unblind` look was recorded (§9.5)")
    else:
        n = sum(1 for l in looks["lines"] if l.strip() and l != "utc\targv\thead")
        lines.append(f"  {looks['path']}: {n} look(s), each `report --unblind` as (UTC, argv, HEAD) (§9.5), verbatim:")
        lines += [f"    | {l}" for l in looks["lines"]]
    lines.append("  spec_sha over the sample's rows (every product, every row with T0_v2 <= tick_id < T0_v2 + 28 d):")
    for sha, n in sorted(shas.items(), key=lambda kv: str(kv[0])):
        lines.append(f"    {sha} {n} rows")
    if not shas:
        lines.append("    no sample row")
    elif len(shas) == 1:
        (one,) = shas
        lines.append("  one value, as §13 requires" + ("" if tree_sha is None or one == tree_sha else
                                                         f"; it is NOT this tree's SPEC.md sha {tree_sha}"))
    else:
        lines.append(f"  NOT ONE VALUE: {len(shas)} values over the sample's rows; §13 requires exactly one (a sample row whose"
                     " sha is not SPEC v2's does not mean what SPEC v2 says)"
                     + ("; this run was made under NO_SEAL=1, recorded here" if no_seal else ""))
    if pb is not None:
        lines += prompt_b_lines(pb)
    return lines


def rule3_lines(stores, days, excluded, kept_days, void, listed):
    """§9.3-§9.4: each product's day table, the recomputed set beside the file, kept days and void."""
    lines = ["§1. Stop rule 3 and void (PREREG-v2 §9.3-§9.4)"]
    for s in stores:
        p = s["product"]
        lines += [f"  -- {p}"] + days[p]["lines"]
    if listed.get("error"):
        lines.append(f"  {listed['path']}: REFUSED, so not read: {listed['error']} (the recomputed rule governs regardless)")
    lines += exclusions_v2.lines(listed.get("set") or set(), excluded, listed.get("lines") or [], listed["path"])
    lines.append(f"  kept days (of {N_DAYS}; void below {MIN_KEPT_DAYS}, §9.4): "
                 + ", ".join(f"{s['product']} {kept_days[s['product']]}{' VOID: leaves the pool' if s['product'] in void else ''}"
                             for s in stores))
    return lines


def power_lines(cells, pool, excluded, gaps):
    """§7's figures at day 28, measured, per tested cell; rho between the pooled products; gap_blocks per cadence."""
    nd = statistics.NormalDist()
    lines = ["§5. Power as measured (PREREG-v2 §7; descriptive): per tested cell, n pooled blocks, the pooled disagreement blocks"
             " (a kept product's SIDES differ into or out of a tick in them) and their share f, n_eff = f n, the sd of S-bar_k"
             " over all blocks and over the disagreement blocks, and the MDE at the cell's one-sided alpha and power 0.80"
             " (z sd / sqrt(n) on all blocks, per block and per day; z sd_dis / sqrt(n_eff) on the disagreement blocks alone);"
             " §7's figures before the data took sd 33 bps per 900 s block per product. F4 (B - A) gets no all-block figure (§7),"
             " and a withdrawn cell, not tested, no MDE at all"]
    for name, x in cells.items():
        cell = x["cell"]
        z = nd.inv_cdf(float(1 - cell.alpha)) + nd.inv_cdf(POWER)
        vals = [v for _, v in x["series"]]
        dv = [v for k, v in x["series"] if k in x["hot"]]
        sd = statistics.stdev(vals) if len(vals) > 1 else None
        sdd = statistics.stdev(dv) if len(dv) > 1 else None
        mde = z * sd / math.sqrt(len(vals)) if sd is not None else None
        mdd = z * sdd / math.sqrt(len(dv)) if sdd is not None else None
        head = f"  {name} {cell.x.upper()} - {cell.y.upper()} at {cell.c} s: "
        counts = (f"n {x['n']}; disagreement blocks {x['dis']} (f {report._r(x['share'])}, n_eff {x['dis']}; product-blocks {x['pdis']});"
                  f" sd {_f(sd, 3)}, sd_dis {_f(sdd, 3)} bps")
        if x["withdrawn"]:                                     # §9.2's NO PROMOTION: F4 is not tested, so it has no power
            lines.append(head + "withdrawn (NO PROMOTION, §9.2): not tested, no z and no MDE; " + counts)
            continue
        if name == "F4":                                       # §7: "Cell 4 (B - A) gets no all-block figure"
            allb = "no all-block MDE (§7: cell 4 gets none; before the first promotion B - A is test-retest)"
        else:
            allb = f"MDE {_f(mde, 3)} bps/block = {_f(None if mde is None else mde * 86400 / cell.c, 1)} bps/day"
        lines.append(head + counts + f"; z {z:.4f}; {allb}; MDE on the disagreement blocks {_f(mdd, 3)} bps/block")
    lines.append("  rho between the pooled products' S_k,p (over the blocks both keep; §7: the pooled mean's variance is"
                 " sigma^2 (1 + 2 rho) / 3 at three products, equal sigma):")
    for name, x in cells.items():
        c, pairs = x["cell"].c, []
        for i, p in enumerate(pool):
            for q in pool[i + 1:]:
                ks = [k for k in range(x["n_blocks"]) if (day_of_block(k, c), p) not in excluded and (day_of_block(k, c), q) not in excluded]
                r = report.pearson([x["S_p"][p].get(k, 0.0) for k in ks], [x["S_p"][q].get(k, 0.0) for k in ks])
                pairs.append(f"{p}~{q} {_f(r, 3) if r is not None else 'undefined'} over {len(ks)}")
        lines.append(f"    {name}: " + ("; ".join(pairs) if pairs else "fewer than two pooled products"))
    lines.append("  gap_blocks (§4: the kept blocks holding the first priced tick after more than 900 s without one, whatever the"
                 " cause), per cadence:")
    for c, per_p in gaps.items():
        union = sorted({k for p in pool for k in per_p[p]})
        lines.append(f"    {c} s: " + ", ".join(f"{p} {len(ks)}" for p, ks in per_p.items()) + f"; pooled blocks holding one {len(union)}")
    return lines


def beside_h1(ct, gaps, pool):
    """§5's "reported beside it, no inference", from the descriptive table: the minute-cadence B - C, the H1 cell at every
    fee column, trades/day per arm and product at 900 s, and gap_blocks at 900 s."""
    m = ct["cells"][("minute", "b", "c", "argmax", config.FEE_BPS_PRIMARY)]
    fees = "; ".join(f"{f:g} bps {_f(ct['cells'][(900, 'b', 'c', 'argmax', f)]['mean'])}" for f in ct["fees"])
    tpd = " | ".join(f"{p} " + " ".join(f"{a.upper()} {_f(ct['trades_per_day'][900][p][a], 1)}" for a in book.ARMS) for p in pool)
    return [f"    beside it: the minute-cadence B - C (decided every minute, 900 s blocks: v1's design on v2's arms, not v1's quantity):"
            f" n {m['n']}, mean {_f(m['mean'])} bps",
            f"    beside it: the H1 cell at every fee column (mean S-bar_k, bps): {fees}",
            f"    beside it: trades/day at 900 s (argmax, kept blocks, per 1440 of their ticks): {tpd or 'no pooled product'}",
            "    beside it: gap_blocks at 900 s: " + ", ".join(f"{p} {len(ks)}" for p, ks in gaps[900].items())]


def tested_lines(cells, pool, excluded, void, beside=None):
    """§2 (H1, with `beside`, beside_h1's lines, when the descriptive table ran) and §3 (family F). B - A is called
    test-retest only when F4 is withdrawn (§9.2's NO PROMOTION on a pooled row set); a void block has no row set to read."""
    v = "VOID: " if void else ""

    def verdict(x):
        if x["withdrawn"]:
            return "WITHDRAWN: NO PROMOTION (§9.2): not bootstrapped and not read"
        if not x["n"]:
            return f"{v}no blocks: nothing to test"
        return f"{v}" + (f"REJECT H0: {x['cell'].x.upper()} beats {x['cell'].y.upper()}" if x["reject"] else "not rejected")

    def per_product(x):
        c, out = x["cell"].c, []
        for p in pool:
            ks = [k for k in range(x["n_blocks"]) if (day_of_block(k, c), p) not in excluded]
            vs = [x["S_p"][p].get(k, 0.0) for k in ks]
            out.append(f"{p} n {len(vs)} mean {_f(inference.mean(vs))} dis {sum(1 for k in ks if k in x['hot_p'][p])}")
        return "; ".join(out) or "no pooled product"

    def cell_lines(x):
        c = x["cell"]
        head = (f"  {c.name} {c.x.upper()} - {c.y.upper()}, argmax, 0 bps, c = {c.c} s, seed {c.seed}, one-sided alpha {frac(c.alpha)},"
                f" bound sorted[{x['rank']}]: {c.says}")
        return [head,
                f"    n pooled blocks {x['n']}; mean S-bar_k {_f(x['mean'])} bps; bound {_f(x['lower'])} bps -> {verdict(x)}",
                f"    beside it, no inference: disagreement blocks {x['dis']} ({report._r(x['share'])}), product-blocks {x['pdis']},"
                f" mean S-bar_k on them {_f(x['mean_dis'])}; per product (kept blocks): {per_product(x)}"]
    h1 = cells["H1"]
    lines = ["§2. H1, the one primary (PREREG-v2 §5): H0 mean S-bar_k(B - C, argmax, 0 bps) at 900 s <= 0, H1 > 0; direction net"
             " of the spread, gross of fees, pooled over the time block"] + cell_lines(h1) + (beside or [])
    lines += ["", f"§3. Family F, claimable (PREREG-v2 §6), each at one-sided alpha 1/160 with sorted[{cells['F1']['rank']}], in §6's order; claims at a"
              " nominal one-sided family-wise error rate of at most 0.05 (Bonferroni: 1/40 for H1 plus 4 x 1/160); the percentile"
              " bootstrap's actual size may exceed nominal, most at 14,400 s (§7); H1 is not a member of F"]
    for name in ("F1", "F2", "F3", "F4"):
        lines += cell_lines(cells[name])
    if cells["F4"]["withdrawn"]:
        lines.append(f"    F4's B - A is test-retest, descriptive only: before any promotion A and B ask the same wording as two questions (§9.2)")
    return lines


def reading(cells, rules, void, promoted, d_reading=None, fee_lines=None):
    """§9.1-§9.2's acts and §11's reading, from the verdicts above; nothing new is tested here."""
    lines = ["§4. Stop rules 1-2 and the reading (PREREG-v2 §9, §11): what the verdicts above mean; nothing new is tested here"]
    h1, f = cells["H1"], cells
    if void:
        lines.append(f"  VOID (§9.4): no product has {MIN_KEPT_DAYS} kept days: the block is void and reported as void; it reads neither"
                     " stop rule 1 nor 2 (rules 3, 5 and 6 bind regardless); a third block is a new pre-registration")
        return lines
    lines.append(f"  stop rule 1 (§9.1): H1 (B - C, alpha 1/40) reject={h1['reject']}, F3 (A - C, alpha 1/160) reject={f['F3']['reject']} -> "
                 + ("FIRES: neither A nor B beats C on H1's cell: the model arms are retired for this block (sends stop at day 28);"
                    " C and the feeds keep logging only if a third pre-registration wants them" if rules["rule1"] else "does not fire"))
    if rules["rule2"] == "NO PROMOTION":
        lines.append(f"  stop rule 2 (§9.2): NO PROMOTION: no live row on a kept product-day of a pooled product has prompt_b_sha !="
                     f" prompt_a_sha (CURRENT never left v2): the nightly is stopped (its plist booted out) because it produced no"
                     f" promoted candidate, not because of B - A's sign; F4 is not read; B - A (mean {_f(f['F4']['mean'])} bps over"
                     f" {f['F4']['n']} blocks) is test-retest, descriptive only; pre-promotion blocks stay in (intent-to-treat)")
    elif rules["rule2"] is None:
        lines.append("  stop rule 2 (§9.2): not read: no pooled block")
    else:
        lines.append(f"  stop rule 2 (§9.2): the point estimate mean S-bar_k(B - A, argmax, 0 bps) at 900 s over all {f['F4']['n']} kept"
                     f" blocks = {_f(f['F4']['mean'])} bps -> " + ("FIRES (<= 0): the nightly is stopped (its plist booted out); A is kept"
                                                                   if rules["rule2"] else "does not fire (> 0)"))
    if h1["reject"]:
        s = ("H1 rejected: B's wording (a human-gated rewrite, at most weekly, from nightly proposals), decided once per 15-minute"
             " block, beat the rule in direction, gross of fees, pooled over these products and days")
        if not promoted:
            s += ("; no promotion occurred (§9.2), so this reads as the frozen v2 wording beating the rule (B = A throughout),"
                  " never as the rewrite")
        elif f["F4"]["reject"]:
            s += "; with F4 also rejected: the rewrite added to the frozen prompt"
        elif f["F3"]["reject"]:
            s += ("; with F3 rejected and F4 not: the frozen v2 wording beat the rule; an addition by the rewrite was not detected"
                  " (its effect can live only on the days after a promotion, §7)")
    else:
        s = ("H1 not rejected: no B - C difference detectable at §7's MDE (pooled 99-171 bps/day by rho) in direction, gross, decided"
             " once per 15-minute block, on these products over these 28 days; edges below that are not ruled out")
    lines.append(f"  §11: {s}")
    for name in ("F1", "F2"):
        if f[name]["reject"] and not h1["reject"]:
            lines.append(f"  §11: {name} rejected without H1: direction at a longer hold ({f[name]['cell'].c} s) that the 15-minute hold does"
                         " not show; a third block puts that cadence first")
    for name in ("F1", "F2", "F3", "F4"):
        if f[name]["reject"]:
            lines.append(f"  {name} rejected (§6): {f[name]['cell'].says}")
    if d_reading is not None:
        lines.append(f"  arm D (§6, §11; descriptive): {d_reading}")
    if fee_lines:
        lines += fee_lines
    return lines


def fee_reading(fa, tiers):
    """§11's last bullet, from the fee arithmetic (descriptive): an arm's pooled f*_X at a cadence against the taker of each
    tier its own account-level 30-day volume reaches (the band's low end at or below the volume)."""
    paid = []
    for c, x in fa.items():
        for arm in book.ARMS:
            a = x["pooled"][arm]
            if a["fstar"] is None:
                continue
            for t in tiers:
                if a["volume_30d"] >= t["low"] and a["fstar"] > t["taker"]:
                    paid.append(f"{arm.upper()} at {c} s: f* {a['fstar']:.2f} bps per fill exceeds the taker {t['taker']:g} bps of"
                                f" {(t['name'] + ' ') if t['name'] else ''}{t['band']}, which its 30-day volume ${a['volume_30d']:,.0f} reaches")
    if not paid:
        return ["  §11 (fees, descriptive): no arm's pooled break-even fee f*_X, at any cadence, exceeds the taker fee of a tier its own"
                " account-level volume reaches: nothing measured here paid at the venue at $1,000"]
    return ["  §11 (fees, descriptive): an arm's pooled break-even fee exceeds the taker of a tier its own volume reaches:"] + \
           [f"    {p}" for p in paid] + ["    (a pair's break-even says only at what fee one arm stops, or starts, beating the other)"]


def direction_lines(rows, outs, t0):
    """§6's direction probabilities for one product's kept rows (PREREG-v1 §5's beside-numbers, no hypothesis)."""
    live = sorted((r for r in rows if report._live(r)), key=lambda r: r["tick_id"])
    units, drop, firsts = report.h2_units(live, outs, t0)
    every, drop_every = [], collections.Counter()
    for r in live:
        p = report._h2_pair(r, outs)
        if isinstance(p, dict):
            every.append(p)
        else:
            drop_every[p] += 1
    h = {"side_units": report._h2_stats(units), "side_every": report._h2_stats(every), "dropped_every": dict(drop_every)}
    su = h["side_units"]
    return ([f"  units (the first live row of each 900 s block from T0_v2, kept days): {su['n']} of {len(firsts)} blocks with a live"
             f" row (dropped: gap {drop.get('gap', 0)}, missing noul {drop.get('noul', 0)}); Pearson r(lean, ret_h_bps)"
             f" {inference._rv(su)} (v1's H2 statistic, retired: no bootstrap, no test; 'PREREG §5' below is PREREG-v1's)"]
            + inference.side_lines(h))


def run(stores, t0, now, resamples=RESAMPLES, accept=False, listed=None, tiers=None, looks=None, tree_sha=None, descriptive=True,
        sealed=None, no_seal=False, propose_log=None):
    """The whole computation and its text. stores: load()'s, in config.PRODUCTS order (rows: each product's WHOLE log);
    t0: T0_v2 (epoch); now: the clock (epoch); accept: --accept-pending; listed: {"set", "lines", "path", "error"} from
    data/exclusions-v2.tsv; tiers: dash.read_fee_tiers()'s (None, {"error"} or the table); looks: read_looks()'s;
    tree_sha: dash.v2_spec_sha(); descriptive: False skips report.cadence_table, §7's agreements and the direction
    probabilities (tests of the tested cells); sealed: seal()'s, main's check (None: not checked, said in §0); no_seal:
    --no-seal (NO_SEAL=1), recorded in the header and §0; propose_log: nights.read()'s, logs/propose.log, whose failed
    nights §8 has the report count with their reasons, beside §9.2's reading (None: not read, said). Returns {"text",
    "cells", "rules", "excluded", "kept_days", "void_products", "pool", "void", "promoted", "pending", "shas", "prompt_b",
    "ct"}. Reads no file."""
    listed = listed or {"set": set(), "lines": [], "path": config.EXCLUSIONS_V2, "error": None}
    looks = looks or {"path": config.LOOKS, "lines": None, "error": None}
    end = t0 + N_DAYS * 86400
    prods = [s["product"] for s in stores]
    outs = {s["product"]: outcomes.join(s["rows"]) for s in stores}
    per = {s["product"]: report.in_sample(s["rows"], t0) for s in stores}
    last = last_reached(stores, now)
    pending = last is None or last < closes_at(t0)
    last_eff, cap = (closes_at(t0), None) if pending and accept else (last, now)
    days = {p: report.days_table(per[p], outs[p], t0, last_eff, cap, v2=True) for p in prods}
    excluded = exclusions_v2.recompute({p: days[p]["days"] for p in prods})
    kept_days = {p: N_DAYS - sum(1 for _, q in excluded if q == p) for p in prods}
    void_p = {p for p in prods if kept_days[p] < MIN_KEPT_DAYS}
    pool = [p for p in prods if p not in void_p]
    void = not pool
    kept_rows = {p: [r for r in per[p] if (report._day_n(r, t0), p) not in excluded] if p in pool else [] for p in prods}
    live_kept = [r for p in pool for r in kept_rows[p] if report._live(r)]
    promoted = sum(1 for r in live_kept if r.get("prompt_b_sha") != r.get("prompt_a_sha"))
    cells = tested(per, t0, excluded, pool, promoted > 0, resamples)
    rules = rules12(cells, void, promoted > 0)
    shas = collections.Counter(r.get("spec_sha") for p in prods for r in per[p])
    pb = {p: prompt_b_days(per[p], t0) for p in prods}
    gaps = {c: {p: report.gap_blocks(per[p], t0, c, lambda k, p=p, c=c: p in pool and (day_of_block(k, c), p) not in excluded)
                for p in prods} for c in config.CADENCES}

    out = {"cells": cells, "rules": rules, "excluded": excluded, "kept_days": kept_days, "void_products": void_p, "pool": pool,
           "void": void, "promoted": promoted, "pending": pending, "days": days, "shas": shas, "prompt_b": pb, "gaps": gaps,
           "ct": None}
    ct = da = None
    if descriptive:
        tl, used = report.tier_lines(tiers)
        ct = report.cadence_table(per, t0, lambda c: N_DAYS * 86400 // c,
                                  lambda p, k, c: p in pool and (day_of_block(k, c), p) not in excluded, pool, True,
                                  tiers=used, fees=FEE_COLUMNS)
        da = report.d_agreement({p: kept_rows[p] for p in pool})
        out.update(ct=ct, d_agreement=da)

    head = [f"jev-paper-loop RESULTS-v2: PREREG-v2 §4-§7 and §9 on the sample, run at {datetime.datetime.fromtimestamp(now, UTC):%Y-%m-%dT%H:%MZ}",
            f"  python {' '.join(sys.version.split())}",
            f"  T0_v2 {_iso(t0)} (PREREG-v2.md §12); the sample [T0_v2, T0_v2 + {N_DAYS} d) ended {_iso(end)}; products"
            f" {', '.join(prods)} (config.PRODUCTS)"]
    for s in stores:
        if s["missing"]:
            head.append(f"  {s['product']}: no log at {s['log']}: no row, so every sample day has no live row (§9.3)")
        else:
            head.append(f"  {s['product']}: log {s['log']}: {s['bytes']} bytes, sha256 {s['sha']}, last tick_id"
                        f" {s['rows'][-1]['tick_id'] if s['rows'] else '-'} (a later copy: head -c {s['bytes']} FILE | shasum -a 256);"
                        f" skipped lines {len(s['bad'])}; sample rows {len(per[s['product']])}")
    head.append(f"  the logs' latest tick reached {_iso(last) if last is not None else 'none'}; d28 closes on a tick at or after"
                f" {_iso(math.ceil(closes_at(t0) / 60) * 60)} (T0_v2 + 28 d + h + 30 s)")
    head.append(f"  bootstrap (§5): circular blocks of L = {BLOCK_LEN} units of the cell's own cadence, R = {resamples} resamples, one"
                " random.Random(seed) per cell, PREREG-v1 §5 step 2's draw (inference.resample_indices), the mean of each resample;"
                " bound = sorted[ceil(alpha x R) - 1], nearest rank, alpha an exact fraction; reject iff the bound > 0")
    if resamples != RESAMPLES:
        head.append(f"  NOT the pre-registered run (R = {resamples}, not {RESAMPLES}): a test or a smoke, never the result")
    if pending and accept:
        head.append("  --accept-pending given and the sample's last day was open: every sample day is judged closed at T0_v2 + 28 d"
                    " + h + 30 s, and a live row whose t + h the logs never reached counts as a gap (for logs that really stopped)")
    elif pending:
        head.append("  d28 OPEN: the logs have not reached its closing tick, so the open days are not judged (main refuses this run"
                    " without --accept-pending)")
    if no_seal and not (sealed and sealed["ok"]):
        head.append(f"  NO_SEAL=1 (§13): the seal check FAILED and this run was made anyway: {sealed['why'] if sealed else 'not checked'}")
    if no_seal and len(shas) > 1:
        head.append(f"  NO_SEAL=1 (§13): the sample's spec_sha set is NOT ONE VALUE ({len(shas)} values) and this run was made anyway")
    if void:
        head.append(f"  VOID (§9.4): no product has {MIN_KEPT_DAYS} kept days; every verdict is prefixed VOID and stop rules 1 and 2"
                    " are not read")
    lines = head + [""] + section0(looks, shas, tree_sha, pb, sealed, no_seal) + [""] + rule3_lines(stores, days, excluded, kept_days, void_p, listed)
    lines.append(f"  pooled products (not void): {', '.join(pool) or 'none'}")
    lines.append(f"  §9.2's row set, live rows on the kept product-days of the pooled products: {len(live_kept)}; with prompt_b_sha !="
                 f" prompt_a_sha: {promoted} -> " + ("not read: the block is void" if void else
                                                     "a promotion took effect: F4 is read" if promoted else
                                                     "NO PROMOTION (CURRENT never left v2): F4 is withdrawn, B - A is test-retest"))
    if propose_log is None:
        lines.append("  failed nights (PREREG-v2 §8): NOT COUNTED: run() was called without logs/propose.log (a test, never the result)")
    else:
        lines += nights.lines(nights.count(propose_log, t0, N_DAYS), propose_log["path"])
    lines += [""] + tested_lines(cells, pool, excluded, void, beside_h1(ct, gaps, pool) if ct else None)
    lines += [""] + reading(cells, rules, void, promoted > 0, da["reading"] if da else None,
                            fee_reading(ct["fee_arithmetic"], used) if ct else None)
    lines += [""] + power_lines(cells, pool, excluded, gaps)
    if ct:
        lines += ["", "§6. Descriptive, never tested (PREREG-v2 §4-§6): pair x column x fee x cadence, per product and pooled, and"
                  f" the fee arithmetic after each replay cadence; fee columns {', '.join(f'{x:g}' for x in FEE_COLUMNS)} bps (§6)",
                  "  d_t = pnl_x - pnl_y in bps of NOTIONAL per tick; S_k,p = the sum of d_t over block k's ticks; pooled: n = pooled"
                  " blocks, mean_S = the mean of S-bar_k, dis = pooled disagreement blocks, pdis = disagreement product-blocks; per"
                  " product: n kept blocks, mean S_k,p, dis blocks; each product replayed from flat at T0_v2 over every sample row, its"
                  " excluded days' blocks dropped after; the minute cadence is v1's design on v2's arms (B - C only)"] + tl + ct["lines"]
        lines += ["", "§7. Descriptive: A's argmax vs rule_c and arm D's agreement (PREREG-v2 §6), kept product-days of pooled products",
                  "  A's argmax vs rule_c, pooled:"] + report.agreement(live_kept)["lines"]
        for p in pool:
            lines += [f"  -- {p}"] + report.agreement([r for r in kept_rows[p] if report._live(r)])["lines"]
        lines += da["lines"]
        lines += ["", "§8. Descriptive: the direction probabilities per product (PREREG-v2 §6; v1's H2 retired, no hypothesis)"]
        for p in pool:
            lines += [f"  -- {p}"] + direction_lines(kept_rows[p], outs[p], t0)
        if not pool:
            lines.append("  no pooled product")
    out["text"] = "\n".join(lines) + "\n"
    return out


def main(argv=None, now=None, resamples=RESAMPLES):
    """`now` (epoch) and `resamples` are for the tests; the run uses the clock and R = 10,000."""
    ap = argparse.ArgumentParser(prog="python3 -m loop.inference_v2",
                                 description="PREREG-v2's day-28 inference over every product's store, run once (make results)")
    ap.add_argument("--sample", action="store_true", required=True,
                    help=f"the sample [T0_v2, T0_v2 + {N_DAYS} d), T0_v2 from PREREG-v2.md §12; refused before its end")
    ap.add_argument("--out", help="also write the text to this NEW file (an existing file is never overwritten)")
    ap.add_argument("--accept-pending", action="store_true",
                    help="logs that really stopped: judge every sample day closed and count a t + h never reached as a gap (printed)")
    ap.add_argument("--no-seal", action="store_true",
                    help="NO_SEAL=1 (make results NO_SEAL=1): run although the prereg-v2-seal check or bin/seal-check --since"
                         " fails, or the sample's spec_sha set is not one value; RESULTS-v2 §0 and its header record it"
                         " (PREREG-v2 §13)")
    args = ap.parse_args(argv)
    clock = datetime.datetime.now(UTC).timestamp() if now is None else now

    def refuse(why, code=EXIT_REFUSED):
        sys.stderr.write(f"inference_v2: refusing: {why}\n")
        return code
    try:
        t0 = dash.read_t0_v2()
    except ValueError as e:
        return refuse(f"{e} (PREREG-v2 §12)")
    if t0 is None:
        return refuse("PREREG-v2.md §12's T0_v2 is blank: the block is not sealed, so there is no sample to read (§12, §13)")
    end = t0 + N_DAYS * 86400
    if clock < end:
        return refuse(f"the sample ends {_iso(end)} and it is {datetime.datetime.fromtimestamp(clock, UTC):%Y-%m-%dT%H:%MZ}; no"
                      " bootstrap runs before day 28 (PREREG-v2 §9.5-§9.6)")
    need = math.ceil(closes_at(t0) / 60) * 60                   # the minute d28's closing tick is written in
    if args.accept_pending and clock < need + 60:
        return refuse(f"--accept-pending is for logs that really stopped, and before {_iso(need + 60)} no running loop could have"
                      f" written d28's closing tick (a tick at or after {_iso(need)}, T0_v2 + 28 d + h + 30 s): run without it"
                      " once the logs reach that tick (PREREG-v2 §9.3: a row whose t + h has not come would count as a gap)")
    if args.out and os.path.exists(args.out):
        return refuse(f"--out {args.out} exists; the result is written once: name a new file", 2)
    sealed = seal()                                             # before any log is opened
    if not sealed["ok"] and not args.no_seal:
        return refuse(f"the seal check failed: {sealed['why']}. PREREG-v2 §10, §13: make results checks {SEAL_TAG} and runs"
                      f" bin/seal-check --since {SEAL_TAG}, and refuses unless NO_SEAL=1 (make results NO_SEAL=1, --no-seal),"
                      " which RESULTS-v2 §0 records")
    stores = load(config.PRODUCTS)
    if all(s["missing"] for s in stores):
        return refuse("no log at any product's store: " + ", ".join(s["log"] for s in stores), 2)
    shas = collections.Counter(r.get("spec_sha") for s in stores for r in report.in_sample(s["rows"], t0))
    if len(shas) > 1 and not args.no_seal:                     # §13: "which must hold exactly one value"
        return refuse(f"the sample's rows carry {len(shas)} spec_sha values ("
                      + ", ".join(f"{sha} {n} rows" for sha, n in sorted(shas.items(), key=lambda kv: str(kv[0])))
                      + "); PREREG-v2 §13 requires exactly one (a row whose sha is not SPEC v2's does not mean what SPEC v2 says);"
                        " NO_SEAL=1 (make results NO_SEAL=1, --no-seal) runs anyway and RESULTS-v2 records it")
    last = last_reached(stores, clock)
    if (last is None or last < closes_at(t0)) and not args.accept_pending:
        return refuse(f"the sample's last day d28 is open: stop rule 3 judges it once a product's log has reached a tick at or after"
                      f" {_iso(need)} (T0_v2 + 28 d + h + 30 s), and the latest any log has reached is"
                      f" {_iso(last) if last is not None else 'none'}; run again then, or pass --accept-pending if the logs really"
                      " stopped (PREREG-v2 §9.3)")
    listed = {"set": set(), "lines": [], "path": config.EXCLUSIONS_V2, "error": None}
    try:
        listed["set"], listed["lines"] = exclusions_v2.read()
    except (ValueError, OSError) as e:
        listed["error"] = str(e)
    try:
        tiers = dash.read_fee_tiers()
    except ValueError as e:
        tiers = {"error": str(e)}
    text = run(stores, t0, clock, resamples, args.accept_pending, listed, tiers, read_looks(), dash.v2_spec_sha(),
               sealed=sealed, no_seal=args.no_seal, propose_log=nights.read())["text"]
    sys.stdout.write(text)
    if args.out:
        try:
            with open(args.out, "x", encoding="utf-8") as fh:
                fh.write(text)
        except FileExistsError:
            sys.stderr.write(f"inference_v2: --out {args.out} appeared during the run; refusing to overwrite it (the text is on stdout)\n")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

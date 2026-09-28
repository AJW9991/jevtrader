"""loop/inference.py -- PREREG §4-§5's inference, written before the data, run once at day 28.

    python3 -m loop.inference --sample [--now YYYY-MM-DDTHH:MM] [--exclusions data/exclusions.tsv] [--out FILE]
                                       [--accept-pending]
    python3 -m loop.inference --pre-t0                       # the shakedown rows before T0: a smoke, never a claim

Written 2026-09-26 (day 2 of 28), decided by Alex the same day: the code that will be run is
committed while no sample number has been looked at, and it REFUSES the sample until
T0 + 28 days (exit 3, before the log is opened). --now exists for the tests and is printed
in the header, so a run that overrode the clock says so in its own output. On the live log
(--log resolving to config.DECISIONS) nothing may move the clock or the anchor: --now, a --t0
other than PREREG §11's and another --prereg are refused (exit 3) in both modes, and so is
--sample at any --resamples but 10,000; --pre-t0 cuts at the EARLIER of --t0 and the sealed
T0, so a later --t0 never pulls a sample row into the smoke (the seal is read from the
repository's own PREREG.md as well as from --prereg's). A copy of the live log is the live log
while the sample runs: a log holding a row of the repository's sealed sample refuses --sample
until the sample's end on this checkout's real clock, whatever --now, --t0 or --prereg say. The clock is not
the whole guard: the last block's H2 unit needs the row at t + 900 s +- 30 s, which is written
up to ~15.5 min after T0 + 28 d, so --sample also refuses (exit 3) while any kept block's
first live row has a gap outcome whose t + h the log has not reached (pending_units); a
pending unit would otherwise be counted as a gap and silently dropped. --accept-pending is
for a log that really stopped, and the header says it was given. --pre-t0 takes
the rows before T0 (PREREG §2: shakedown and day 0, never in the sample) with the log's
first tick as the anchor, as a live check that the procedure runs end to end.

What it computes, and nothing else (PREREG §4, §5, §8; SPEC §10-§11):
- Sample: rows with T0 <= tick_id < T0 + 28 d, cut BEFORE any replay (every arm starts
  flat at T0); the outcome join is over the whole log (a unit near the end finds its t+h).
- Days: d = [T0 + 86400(N-1), T0 + 86400 N) (Alex, 2026-09-26, before any look); a day named
  in data/exclusions.tsv (stop rule 3) is dropped whole: its 96 blocks and its H2 units.
  Fewer than 21 kept days -> the block is VOID (§8.3) and printed as such.
- H1: S_k = sum of d_t over block k of (B - C, argmax, 0 bps), k = 0 .. 2687, an empty block
  is 0 and kept; statistic = mean S_k; H0: mean <= 0, one-sided alpha 0.025; circular block
  bootstrap, block length 4, 10,000 resamples, seed 20260923, the §5 draw; reject iff the
  250th of the sorted resampled means (nearest-rank 2.5th percentile) is > 0. The same for
  A - C (stop rule 1's input, §9), and B - A as a point estimate (stop rule 2).
- H2: units = the first live row of each block (report.h2_units), (lean, ret_h_bps) in block
  order, dropped blocks leave no placeholder; statistic = Pearson r; same bootstrap with its
  own generator, r undefined on a resample -> 0; reject iff the 250th sorted r* is > 0.
  Degenerate: all leans equal or all returns equal -> "not supported: no variance"; one unit
  -> "fewer than 2 units"; none -> "no units".
Everything beside a statistic is descriptive and says so. No other cell is tested here: a
claim from the 32 gross secondaries would take alpha 0.025 / 32 (§6) and is not made by code.
The log is read once (read_log): the sha, the byte length and the last tick_id in the header
are of the bytes the rows were parsed from, so a later copy of the growing log is checked with
`head -c <bytes> <copy> | shasum -a 256`. --out writes a NEW file and never overwrites one.
Standard library only. The output is meant to be committed beside PREREG.md (§10)."""
import argparse, datetime, hashlib, math, os, random, sys, tempfile

from . import book, config, exclusions, outcomes, report

SEED = 20260923
RESAMPLES = 10000
BLOCK_LEN = 4                    # units per bootstrap block: 4 x 15 min = 1 h (PREREG §4, §5)
ALPHA_RANK = 249                 # sorted[249] = the 250th value = ceil(0.025 x 10,000), nearest rank, no interpolation
BLOCKS_PER_DAY = 86400 // report.BLOCK_S     # 96
N_DAYS = report.SAMPLE_DAYS                  # 28
MIN_KEPT_DAYS = 21               # PREREG §8.3: fewer kept at day 28 -> void
EXIT_NOT_YET = 3
EXIT_REFUSED = 3                 # every refusal of the pre-registered run is exit 3 (the day-28 clock is one of them)
PAIRS = (("b", "c", "H1 (co-primary): B - C at the primary cell, alpha 0.025"),
         ("a", "c", "A - C at the primary cell, alpha 0.025: stop rule 1's input and §9's reading only (a claim would be a §6 secondary)"),
         ("b", "a", "B - A at the primary cell: point estimate only, stop rule 2 (<= 0 stops the nightly)"))


# ---- the draw (PREREG §5, steps 1-3, applied to H1 too with its own generator: §4 does not pin the draw) ------------------------------
def resample_indices(rng, n, L=BLOCK_LEN):
    """One circular-block resample of 0..n-1: ceil(n/L) starts, each rng.randrange(n), L
    consecutive wrapped indices from each, concatenated in draw order, the first n kept."""
    out = []
    for _ in range(-(-n // L)):
        s = rng.randrange(n)
        out.extend((s + i) % n for i in range(L))
    return out[:n]


def alpha_rank(resamples):
    """The 0-based index of the nearest-rank 2.5th percentile of `resamples` sorted values:
    ceil(0.025 x R) - 1, in integer arithmetic (0.025 x R is not exact in binary). 249 at the
    pre-registered R = 10,000 (PREREG §5 step 3); a fixed 249 would read the 25th percentile
    at R = 1,000, which is why a test run at another R goes through here too."""
    if resamples < 1:
        raise ValueError(f"resamples must be >= 1, got {resamples}")
    return (25 * resamples + 999) // 1000 - 1


def bootstrap(series, stat, seed=SEED, resamples=RESAMPLES, L=BLOCK_LEN):
    """The sorted resampled statistics and the one-sided lower bound sorted[alpha_rank(R)]
    (= sorted[ALPHA_RANK] at R = 10,000). `stat` maps a list of series elements to a float
    (None -> 0.0, PREREG §5: undefined never rejects). One generator per call: H1 and H2 each
    get their own random.Random(seed)."""
    n = len(series)
    rank = alpha_rank(resamples)
    if n == 0:
        return {"n": 0, "lower": None, "reject": False, "sorted": []}
    rng = random.Random(seed)
    stats = []
    for _ in range(resamples):
        idx = resample_indices(rng, n, L)
        v = stat([series[i] for i in idx])
        stats.append(0.0 if v is None else v)
    stats.sort()
    lower = stats[rank]
    return {"n": n, "lower": lower, "reject": lower > 0, "sorted": stats}


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def pearson_pairs(ps):
    return report.pearson([x for x, _ in ps], [y for _, y in ps])


# ---- days and exclusions ----------------------------------------------------------------------
def day_of_block(k):
    """Block k (0-based from T0) sits in day N = k // 96 + 1 (1-based, d01 .. d28)."""
    return k // BLOCKS_PER_DAY + 1


read_exclusions = exclusions.read_exclusions      # loop/exclusions.py; kept here for the callers that name it


def kept_tick(tick_id, anchor, excluded=(), n_blocks=BLOCKS_PER_DAY * N_DAYS):
    """True when the tick's block k is in [0, n_blocks) and its day (day_of_block, T0-anchored)
    is not excluded: the rows every number of the output reads, the descriptive ones included."""
    k = int((report.tick_epoch(tick_id) - anchor) // report.BLOCK_S)
    return 0 <= k < n_blocks and day_of_block(k) not in excluded


# ---- H1 ----------------------------------------------------------------------------------------
def h1_series(rows, outs, x, y, anchor, excluded=(), n_blocks=BLOCKS_PER_DAY * N_DAYS):
    """[(k, S_k)] for every block k in [0, n_blocks) whose day is not excluded, S_k = 0 where no
    row (PREREG §3), from book.replay on the sample rows at (argmax, FEE_BPS_PRIMARY). n_blocks is
    96 x 28 for the sample; --pre-t0 passes the shakedown's own span. The replay runs over every
    sample row, excluded days included, exactly as pre-registered (a day is dropped from the
    series, the book is not re-run without it). Also the descriptive pieces, each over the
    kept days only: disagreement blocks, every-tick d_t, trades and forced holds per side."""
    col, fee = "argmax", config.FEE_BPS_PRIMARY
    px, py = book.replay(rows, outs, x, col, fee), book.replay(rows, outs, y, col, fee)
    dis = report._disagreement(px, py)
    cell = report._cell(px, py, dis)
    S, hot = {}, set()
    for t, v in cell["d"]:
        k = int((report.tick_epoch(t) - anchor) // report.BLOCK_S)
        if 0 <= k < n_blocks:
            S[k] = S.get(k, 0.0) + v
            if t in dis:
                hot.add(k)
    series = [(k, S.get(k, 0.0)) for k in range(n_blocks) if day_of_block(k) not in excluded]
    kept = [v for _, v in series]
    on_dis = [v for k, v in series if k in hot]
    keep = lambda t: kept_tick(t, anchor, excluded, n_blocks)
    d_kept = [v for t, v in cell["d"] if keep(t)]
    tx, ty = (sum(1 for tr in p["trades"] if keep(tr["tick_id"])) for p in (px, py))
    if excluded:                                            # a forced hold is row-local, so a replay of the kept rows counts them
        kept_rows = [r for r in rows if keep(r["tick_id"])]
        fx, fy = (book.replay(kept_rows, outs, a, col, fee)["forced_hold"] for a in (x, y))
    else:
        fx, fy = px["forced_hold"], py["forced_hold"]
    # descriptive: blocks on which a gap longer than the horizon lands (SPEC §10 carries the position
    # across a gap and marks the whole move on the first priced tick after it; PREREG-v2 material).
    # "Priced" is book.replay's own test (bid, ask and mid all usable): a run of unpriced rows (a feed
    # outage logs a row a minute with no mid) is a gap to the book as much as a run of missing rows.
    priced = sorted({r["tick_id"] for r in rows if all(book._px(r.get(f)) for f in ("bid", "ask", "mid"))})
    absorbing = set()
    for a, b in zip(priced, priced[1:]):
        if report.tick_epoch(b) - report.tick_epoch(a) > config.HORIZON_S:
            k = int((report.tick_epoch(b) - anchor) // report.BLOCK_S)
            if 0 <= k < n_blocks and day_of_block(k) not in excluded:
                absorbing.add(k)
    return {"series": series, "S": kept, "dis_blocks": len(on_dis), "mean_dis": mean(on_dis), "gap_blocks": len(absorbing),
            "trades_x": tx, "trades_y": ty, "forced_x": fx, "forced_y": fy, "ticks": len(d_kept), "mean_tick": mean(d_kept),
            "days": len(series) / BLOCKS_PER_DAY}


def h1(rows, outs, anchor, excluded=(), resamples=RESAMPLES, n_blocks=BLOCKS_PER_DAY * N_DAYS):
    out = []
    for x, y, title in PAIRS:
        s = h1_series(rows, outs, x, y, anchor, excluded, n_blocks)
        m = mean(s["S"])
        bs = bootstrap(s["S"], mean, resamples=resamples) if x != "b" or y != "a" else None   # B - A: point estimate only
        out.append({"pair": f"{x.upper()} - {y.upper()}", "title": title, "n": len(s["S"]), "mean": m,
                    "lower": bs["lower"] if bs else None, "reject": bs["reject"] if bs else None,
                    "dis_blocks": s["dis_blocks"], "mean_dis": s["mean_dis"], "gap_blocks": s["gap_blocks"], "ticks": s["ticks"], "mean_tick": s["mean_tick"],
                    "trades_x": s["trades_x"], "trades_y": s["trades_y"], "forced_x": s["forced_x"], "forced_y": s["forced_y"], "days": s["days"]})
    return out


# ---- H2 ----------------------------------------------------------------------------------------
def h2(rows, outs, anchor, excluded=(), resamples=RESAMPLES, n_blocks=BLOCKS_PER_DAY * N_DAYS):
    """PREREG §5 on the kept days' live rows only: the units (report.h2_units; blocks nest in days,
    so they are the units of every live row with the excluded days' units removed), the statistic
    and its bootstrap, and the descriptive side numbers (report._h2_stats) on the kept units and on
    every kept live row with an outcome (a second decision in a minute shares its outcome)."""
    live = sorted((r for r in rows if report._live(r) and kept_tick(r["tick_id"], anchor, excluded, n_blocks)),
                  key=lambda r: r["tick_id"])
    units, drop, firsts = report.h2_units(live, outs, anchor)
    units = [u for u in units if 0 <= u["k"] < n_blocks and day_of_block(u["k"]) not in excluded]   # a no-op now; kept as the rule
    every, drop_every = [], {}
    for r in live:                                          # every kept live ROW: a second decision in a minute shares
        p = report._h2_pair(r, outs)                        # its minute's outcome (the join is per tick), as in report §5
        if isinstance(p, dict):
            every.append(p)
        else:
            drop_every[p] = drop_every.get(p, 0) + 1
    ps = [(u["lean"], u["ret"]) for u in units]
    xs, ys = [x for x, _ in ps], [y for _, y in ps]
    degenerate = None                                       # n = 0 is "no units", printed as such, never a variance
    if len(ps) == 1:
        degenerate = "fewer than 2 units (n 1): r is undefined"
    elif ps and len(set(xs)) == 1:
        degenerate = "no variance in lean"
    elif ps and len(set(ys)) == 1:
        degenerate = "no variance in ret"
    r = report.pearson(xs, ys) if ps else None
    rho = report.spearman(xs, ys) if ps else None
    bs = bootstrap(ps, pearson_pairs, resamples=resamples) if ps and degenerate is None else None
    per_day = {d: [0, 0] for d in range(1, -(-n_blocks // BLOCKS_PER_DAY) + 1) if d not in excluded}   # every kept day, rows or not
    for k in firsts:
        if 0 <= k < n_blocks and day_of_block(k) in per_day:
            per_day[day_of_block(k)][0] += 1
    for u in units:
        per_day[day_of_block(u["k"])][1] += 1
    return {"n": len(ps), "blocks_with_row": len(firsts), "dropped": dict(drop), "r": r, "rho": rho, "degenerate": degenerate, "per_day": per_day,
            "lower": bs["lower"] if bs else None, "reject": bs["reject"] if bs else False,
            "units": [(u["k"], u["lean"], u["ret"]) for u in units],
            "side_units": report._h2_stats(units), "side_every": report._h2_stats(every), "dropped_every": drop_every}


def _rv(s, what="r"):
    """A correlation from report._h2_stats, or why it is undefined."""
    return _f(s[what]) if s[what] is not None else f"undefined ({s.get('why') or 'fewer than 2 pairs'})"


def side_lines(h):
    """PREREG §5's numbers beside the statistic, on the kept units and every kept live row: all
    descriptive, never claimed (§6). Spearman rho; r and rho on every row (overlapping horizons);
    Brier of up15 and down15 against the base rate's; the measured-tail counts; the `trend` word as
    a no-model comparator (+1 pumping, 0 flat, -1 dumping)."""
    su, se = h["side_units"], h["side_every"]

    def brier(s):
        bu, bd = s["brier_up"], s["brier_down"]
        return (f"up15 {_f(bu[0])} vs base {_f(bu[1])} (p(up) {_f(bu[2], 3)}); down15 {_f(bd[0])} vs base {_f(bd[1])}"
                f" (p(down) {_f(bd[2], 3)})")

    def tails(s):
        t = s["tails"]
        return f"up15 {t['up'][0]}/{t['up'][1]}, down15 {t['down'][0]}/{t['down'][1]}"

    def word(s):
        w = s["word"]
        return (f"r(lean, trend) {_rv(w['lean_trend'])}; r(trend, ret_h_bps) {_rv(w['trend_ret'])};"
                f" r(lean, ret_h_bps | trend flat) {_rv(w['flat'])} over {w['flat']['n']}")

    de = h["dropped_every"]
    return [f"  descriptive (PREREG §5, never claimed): Spearman rho {_rv(su, 'rho')} over the {su['n']} units;"
            f" every kept live row (overlapping horizons; a second decision in a minute shares its outcome): r {_rv(se)}, rho {_rv(se, 'rho')} over {se['n']} rows"
            f" (dropped: gap {de.get('gap', 0)}, missing noul {de.get('noul', 0)})",
            f"  descriptive: Brier on the units {brier(su)}; on every kept live row {brier(se)}",
            f"  descriptive: measured tails (>= {report.NOUL_HIGH:g} / < {report.NOUL_LOW:g}) on the units {tails(su)}; on every kept live row {tails(se)}",
            f"  descriptive: the trend word (no model): units {word(su)}; every kept live row {word(se)}"]


def reached(rows, now=None):
    """How far the log has got on the clock `now` (epoch; the live log's real clock, None for any other
    log): (its rows stamped at or before `now`, its rows stamped after it), each in file order. A row
    stamped after the clock (a clock that stepped forward) has not happened, so the log's last row is
    the last one stamped at or before the clock; never the clock itself, since a row stamped before
    it can still be on its way (a tick writes its row after the ask, up to cycle.WATCHDOG_S later).
    `rows` are outcomes.load's, whose ts_rx always parses."""
    if now is None:
        return list(rows), []
    before, after = [], []
    for r in rows:
        (after if outcomes.ts_epoch(r["ts_rx"]) > now else before).append(r)
    return before, after


def pending_units(rows, scope, outs, anchor, excluded=(), n_blocks=BLOCKS_PER_DAY * N_DAYS, now=None):
    """The H2 units whose t + h the log has not reached yet: a kept block's first live row with
    both nouls (report._h2_pair says "gap", not "noul") whose ts_rx + HORIZON_S + JOIN_TOL_S is
    later than the last ts_rx of the whole log (`rows`), so a row inside its join window can still
    be written. Counting such a unit as a gap would drop it for good (PREREG §5: the join is over
    the whole log, the block is never refilled). `now` (epoch, the live log's real clock): the log's
    last ts_rx is its last one stamped at or before the clock (reached), so neither a row stamped
    after the clock (a forward step) nor the clock itself reads as the t + h a unit waits for; a log
    with no row at or before the clock has reached nothing. Returns [(tick_id, the ts_rx epoch it
    waits for)]."""
    seen, _ = reached(rows, now)
    last = max((outcomes.ts_epoch(r["ts_rx"]) for r in seen), default=-math.inf)
    live = sorted((r for r in scope if report._live(r)), key=lambda r: r["tick_id"])
    _, _, firsts = report.h2_units(live, outs, anchor)
    out = []
    for k in sorted(firsts):
        r = firsts[k]
        if not 0 <= k < n_blocks or day_of_block(k) in excluded or report._h2_pair(r, outs) != "gap":
            continue
        until = outcomes.ts_epoch(r["ts_rx"]) + config.HORIZON_S + outcomes.JOIN_TOL_S
        if until > last:
            out.append((r["tick_id"], until))
    return out


# ---- the run -----------------------------------------------------------------------------------
def read_log(path):
    """The log read ONCE: its bytes are hashed and the rows are parsed from those same bytes, so
    the sha printed is the sha of what was measured while launchd appends a row a minute. The
    rows go through outcomes.load itself (on a private copy of the bytes), so a skipped line is
    skipped exactly as every other reader skips it. Returns (rows, bad, sha256 hex, byte length)."""
    with open(path, "rb") as fh:
        data = fh.read()
    fd, tmp = tempfile.mkstemp(prefix="inference-", suffix=".jsonl")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        bad = []
        rows = outcomes.load(tmp, bad)
    finally:
        os.unlink(tmp)
    return rows, bad, hashlib.sha256(data).hexdigest(), len(data)


def _f(x, nd=4):
    return "n/a" if x is None else f"{x:.{nd}f}"


def _share(k, n):
    return f"{100.0 * k / n:.1f}%" if n else "n/a"


def _iso_second(epoch):
    """epoch -> 'YYYY-MM-DDTHH:MM:SSZ', rounded UP to the second (a wait-until time is never early)."""
    return datetime.datetime.fromtimestamp(math.ceil(epoch), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


NO_LIVE_ROWS = ("no live rows: stop rule 3 is undefined (fill 0/0); the exclusion is Alex's call (PREREG §8.3)")


def day_lines(per_day):
    """Per kept day (T0-anchored dNN): how many of its 96 blocks hold a live row and how many H2
    units it gave. Descriptive; a kept day with no live row at all is flagged, because its fill
    is 0/0 and stop rule 3 cannot judge it: excluding it is a person's act, never this code's."""
    lines = [f"per kept day (descriptive): blocks holding a live row, of {BLOCKS_PER_DAY}, and the H2 units the day gave"]
    for d in sorted(per_day):
        blocks, units = per_day[d]
        lines.append(f"  d{d:02d} {blocks:>3}/{BLOCKS_PER_DAY} blocks {units:>3} units" + (f"  {NO_LIVE_ROWS}" if blocks == 0 else ""))
    if not per_day:
        lines.append("  no kept day")
    return lines


def rule3_lines(table, excluded, n_days=N_DAYS):
    """PREREG §8.3's stop rule 3 recomputed from the log (report.days_table over the sample) beside
    the exclusions file that decided: the file is Alex's act and is applied as written; this only
    says where the two differ, so a mistaken or missing line is visible in the one pre-registered
    output. Every sample day d01..d28 is placed once: BAD (closed, and the rule says so), open (its
    last rows' t + h not yet in the log: the rule cannot judge it yet), no live rows (0/0, undefined:
    a closed day of absences only, or a day after the log's last row), or judged fine. Descriptive:
    no number above changes."""
    rows = {x["day"]: x for x in table["days"]}
    sample = [f"d{d:02d}" for d in range(1, n_days + 1)]
    bad = [d for d in sample if d in rows and rows[d]["bad"]]
    open_ = [d for d in sample if d in rows and rows[d]["open"] and not rows[d]["bad"]]
    none = [d for d in sample if d not in rows or (rows[d]["empty"] and not rows[d]["bad"])]
    listed = {f"d{d:02d}" for d in excluded}
    fine = set(sample) - set(bad) - set(open_) - set(none)
    fmt = lambda xs: " ".join(sorted(xs)) if xs else "none"
    return [f"stop rule 3 cross-check (PREREG §8.3, descriptive; the exclusions file above decides, this changes no number):",
            f"  BAD by the rule, recomputed from the log: {fmt(bad)} ({len(bad)}; the rule pauses the run at 3)",
            f"  listed and BAD: {fmt(listed & set(bad))}; listed but judged fine by the rule: {fmt(listed & fine)};"
            f" BAD but NOT listed: {fmt(set(bad) - listed)}",
            f"  open, not yet judged (a day's last t + h is not in the log): {fmt(open_)}" + (f", listed: {fmt(listed & set(open_))}" if listed & set(open_) else ""),
            f"  no live rows (0/0, the rule undefined; Alex's call; includes any day after the log's last row): {fmt(none)}"
            + (f", listed: {fmt(listed & set(none))}" if listed & set(none) else "")]


def reading(h1s, h2s, void=False, pre_t0=False):
    """The stop rules (PREREG §8.1-§8.2) and the reading (§5's last paragraph, §9) from the verdicts
    already computed; nothing new is tested here. Stop rule 1 fires when NEITHER B - C nor A - C
    rejects on H1, whatever H2 shows; stop rule 2 fires when the B - A point estimate is <= 0. A
    void block (§8.3) prints every line prefixed VOID and reads no stop rule."""
    p = {h["pair"]: h for h in h1s}
    b, a = bool((p.get("B - C") or {}).get("reject")), bool((p.get("A - C") or {}).get("reject"))
    h2r = bool(h2s.get("reject"))
    ba = (p.get("B - A") or {}).get("mean")
    v = "VOID: " if void else ""
    lines = ["reading (PREREG §5, §8-§9): the stop rules and what the verdicts above mean, nothing new tested"]
    if void:
        lines.append(f"  VOID (PREREG §8.3): fewer than {MIN_KEPT_DAYS} days kept: the block is void and the stop rules are not read")
    if pre_t0:
        lines.append("  PRE-T0: a smoke of the procedure; no stop rule and no reading applies before T0")
    lines.append(f"  {v}stop rule 1: B-C reject={b}, A-C reject={a} -> {'does not fire' if b or a else 'fires'}")
    lines.append("    (§8.1: fires when neither B - C nor A - C rejects on H1, whatever H2 shows: the model arms are retired)")
    lines.append(f"  {v}stop rule 2: mean S_k(B-A) = {_f(ba)} -> " + ("not read (no blocks)" if ba is None else "fires" if ba <= 0 else "does not fire"))
    lines.append("    (§8.2: fires when the point estimate of mean S_k(B - A, argmax, 0 bps) is <= 0: the nightly is stopped, arm A kept)")
    if b and h2r:
        prim = "both primaries hold: 'the loop works as described' (§5), which does not say it earns anything at a retail fee (§4)"
    elif b:
        prim = "H1 alone: reported as exactly that (§5), not as 'the loop works as described'"
    elif h2r:
        prim = "H2 alone: reported as exactly that (§5), not as 'the loop works as described'"
    else:
        prim = "neither primary holds"
    lines.append(f"  {v}primaries: H1 (B - C) reject={b}, H2 reject={h2r} -> {prim}")
    if b and not a:
        h1 = "H1 rejected for B and not for A: the rewrite earned its keep over the rule"
    elif a and not b:
        h1 = ("H1 rejected for A and not for B: the frozen prompt beat the rule and the rewriting hurt"
              " (stop rule 2, above, reads the B - A point estimate)")
    elif a and b:
        h1 = ("H1 rejected for B and for A: both model arms beat the rule in direction; what the rewrite adds over the"
              " frozen prompt is B - A, a point estimate read by stop rule 2 and never tested here")
    else:
        h1 = ("neither A nor B beats C on H1: the model arms are no better than four words and three lines of `if`,"
              " in direction, gross of fees, on this product, over these 28 days (stop rule 1)")
    lines.append(f"  {v}H1 (§9): {h1}")
    if h2r and not b:
        h2 = ("H2 supported and H1 not: the `trend` word, as Jev maps it into direction probabilities, predicts the next"
              " 15-minute return, and the rewritten action did not beat the rule that already acts on that word; it does"
              " not show that Jev has a signal the action question ignores (read the comparator, descriptive)")
    elif h2r:
        h2 = ("H2 supported: Jev's up15 / down15 carry information about the next 15-minute return, in the four words as"
              " Jev maps them (mostly the `trend` word on the shakedown), not shown to go beyond the words (§5)")
    elif not h2s.get("n"):
        h2 = "no units: no block's first live row has both nouls and an outcome, so H2 is not read"
    else:
        h2 = ("H2 not supported: Jev's up15 / down15 carry no linear information about the next 15-minute return on this"
              " product over these 28 days; the noultail column is then noise around hold")
    lines.append(f"  {v}H2 (§9): {h2}")
    lines.append("  Secondaries (§6) are not tested here; a claim from the 32 gross secondaries would take alpha 0.025 / 32.")
    return lines


def render(mode, t0, now, log, excluded, excl_lines, kept_days, h1s, h2s, resamples, pending=None, cut=None, excl_path=None, rule3=None):
    """log: {"path", "sha", "bytes", "last", "scope"} of the one read (read_log) and the rows in scope.
    pending: None when --accept-pending was not given, else the pending_units it overrode.
    cut: --pre-t0's end of scope, the earlier of --t0 and PREREG §11's T0. excl_path: the
    exclusions file actually read (or looked for). rule3: rule3_lines' output, sample mode only."""
    excl_path = excl_path or os.path.join(config.DATA, "exclusions.tsv")
    lines = [f"jev-paper-loop inference (PREREG §4-§5), mode {mode}, run at {now.strftime('%Y-%m-%dT%H:%MZ')}",
             f"  python {' '.join(sys.version.split())}",
             f"  log {log['path']}: {log['bytes']} bytes, sha256 {log['sha']}, last tick_id {log['last']}"
             f" (a later copy: head -c {log['bytes']} FILE | shasum -a 256); skipped lines {log['skipped']}; rows in scope {log['scope']}",
             f"  T0 {report._iso_minute(t0)}; anchor for blocks and days {'T0' if mode == 'sample' else 'the log first tick (pre-T0, descriptive)'}",
             (f"  days kept {kept_days} of {N_DAYS}; excluded {sorted(excluded) or 'none'} ({excl_path}, reproduced below)" if mode == "sample"
              else "  days and exclusions: not applicable before T0; blocks run over the shakedown's own span"),
             f"  bootstrap: circular blocks of {BLOCK_LEN}, {resamples} resamples, seed {SEED}, one generator per statistic;"
             f" lower bound = sorted[{alpha_rank(resamples)}] (nearest-rank 2.5th percentile); reject iff > 0"]
    if resamples != RESAMPLES:
        lines.append(f"  NOT the pre-registered run (resamples R != {RESAMPLES}): R = {resamples}, lower bound = sorted[ceil(0.025 x R) - 1];"
                     " a test or a smoke, never the result")
    if pending is not None:
        lines.append(f"  --accept-pending given: {len(pending)} H2 unit(s) whose t + h the log has not reached are counted as gaps"
                     " (for a log that really stopped; without the flag the run is refused)"
                     + (": " + ", ".join(t for t, _ in pending) if pending else ""))
    if mode == "pre-t0":
        lines.append("  PRE-T0: shakedown rows only (PREREG §2), never in the sample; every number here is a smoke of the procedure, not a result;"
                     f" rows before {report._iso_minute(cut if cut is not None else t0)} (the earlier of --t0 and PREREG §11's T0)")
    void = mode == "sample" and kept_days < MIN_KEPT_DAYS
    v = "VOID: " if void else ""                            # every verdict of a void block says so where it is printed
    if void:
        lines.append(f"  VOID (PREREG §8.3): fewer than {MIN_KEPT_DAYS} days kept; reported as void, a second block is a new pre-registration;"
                     " every verdict below is prefixed VOID and the stop rules are not read")
    lines.append("")
    lines.append("H1 -- mean S_k of the paired 15-minute pnl difference, column argmax, 0 bps (gross of fees, net of the spread)")
    if h1s:
        lines.append(f"  descriptive: blocks on which a gap longer than the horizon lands {h1s[0]['gap_blocks']} of {h1s[0]['n']}"
                     " (SPEC §10: the move across a gap is marked on the first priced tick after it; kept as pre-registered)")
    for h in h1s:
        lines.append(f"  {h['pair']}: {h['title']}")
        verdict = ("REJECT H0: the arm beats the other" if h["reject"] else "not rejected") if h["reject"] is not None else "no test (point estimate)"
        if not h["n"]:
            verdict = "no blocks: nothing to test"
        lines.append(f"    n blocks {h['n']}; mean S_k {_f(h['mean'])} bps; lower bound {_f(h['lower'])} bps -> {v}{verdict}")
        days = h["days"]
        per_day = (f" ({h['trades_x'] / days:.2f} vs {h['trades_y'] / days:.2f} per day over {days:g}"
                   f" {'kept days' if mode == 'sample' else 'days of the span'})") if days else ""
        lines.append(f"    descriptive, kept days only: disagreement blocks {h['dis_blocks']} ({_share(h['dis_blocks'], h['n'])}), mean S_k on them {_f(h['mean_dis'])};"
                     f" every tick mean d_t {_f(h['mean_tick'])} over {h['ticks']}; trades {h['trades_x']} vs {h['trades_y']}{per_day};"
                     f" forced holds {h['forced_x']} vs {h['forced_y']}")
    lines.append("")
    lines.append("H2 -- Pearson r(lean, ret_h_bps) over the units (first live row of each block), alpha 0.025")
    h = h2s
    units = f"  n units {h['n']} (blocks with a live row {h['blocks_with_row']}; dropped {h['dropped'] or 'none'})"
    if not h["n"]:
        lines.append(f"{units}: {v}no units: no block's first live row has both nouls and an outcome; nothing to test")
    elif h["degenerate"]:
        lines.append(f"{units}: {v}not supported: {h['degenerate']} (PREREG §5 degenerate case)")
    else:
        verdict = "REJECT H0: r > 0" if h["reject"] else "not rejected"
        lines.append(f"{units}; r {_f(h['r'])}; lower bound {_f(h['lower'])} -> {v}{verdict}")
    lines.extend(side_lines(h))
    lines.append("")
    lines.extend(reading(h1s, h2s, void, mode == "pre-t0"))
    lines.append("")
    if mode == "sample":
        lines.extend(day_lines(h2s["per_day"]))
        lines.append("")
        if rule3:
            lines.extend(rule3)
            lines.append("")
    if mode == "sample":
        lines.append(f"{excl_path}, verbatim:" if excl_lines else f"{excl_path}: absent or empty")
        lines.extend("  " + l for l in excl_lines)
    else:
        lines.append(f"{excl_path}: not applied before T0 (exclusions name sample days)")
    return "\n".join(lines) + "\n"


def main(argv=None, now=None):
    repo_prereg = _repo_prereg()                            # the repository's PREREG.md
    ap = argparse.ArgumentParser(prog="python3 -m loop.inference", description="PREREG §4-§5 inference, once, at day 28")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sample", action="store_true", help=f"the sample [T0, T0 + {N_DAYS} d); refused before T0 + {N_DAYS} d")
    g.add_argument("--pre-t0", action="store_true", help="the rows before T0 (shakedown): a smoke of the procedure, never a claim")
    ap.add_argument("--log", default=config.DECISIONS)
    ap.add_argument("--t0", help="T0 (UTC minute or tick_id); default: PREREG.md §11")
    ap.add_argument("--prereg", default=repo_prereg)
    ap.add_argument("--exclusions", help="stop rule 3's exclusions (default data/exclusions.tsv, which may be absent: no exclusions);"
                                         " a path given here must exist")
    ap.add_argument("--now", help="override the clock (tests). Printed in the header when used.")
    ap.add_argument("--resamples", type=int, default=RESAMPLES,
                    help=f"tests only; the pre-registered number is {RESAMPLES}, and --sample on the live log refuses any other")
    ap.add_argument("--out", help="also write the text to this NEW file (an existing file is never overwritten)")
    ap.add_argument("--accept-pending", action="store_true",
                    help="--sample on a log that really stopped: count the units whose t + h it never reached as gaps (printed)")
    args = ap.parse_args(argv)
    real_now = now or datetime.datetime.now(datetime.timezone.utc)   # this checkout's clock; --now never moves it
    if args.resamples < 1:
        ap.error(f"--resamples wants a positive count, got {args.resamples}")
    live_log = os.path.realpath(args.log) == os.path.realpath(config.DECISIONS)   # the launchd log, not a copy or a fixture
    try:                                                                            # (a hard link to it is it: samefile)
        live_log = live_log or os.path.samefile(args.log, config.DECISIONS)
    except OSError:
        pass
    if args.sample and live_log and args.resamples != RESAMPLES:
        sys.stderr.write(f"inference: refusing: --sample on the live log {config.DECISIONS} runs the pre-registered"
                         f" {RESAMPLES} resamples only, got --resamples {args.resamples} (PREREG §4-§5)\n")
        return EXIT_REFUSED
    try:
        t0 = report._t0(args.t0) if args.t0 else _read_t0(args.prereg)
    except ValueError:
        ap.error(f"--t0 wants YYYY-MM-DDTHH:MM (UTC) or a tick_id, got {args.t0!r}")
    if t0 is None:
        ap.error("no T0: PREREG.md §11 is unsealed and no --t0 given")
    sealed = _read_t0(args.prereg)                          # PREREG §11's T0 (None before sealing)
    sealed_repo = _read_t0(repo_prereg)                     # the repository's own seal, whatever --prereg names
    if live_log:                                            # the clock and T0 of the live log are the real ones, in both modes
        why = None
        if args.now:
            why = f"--now {args.now} overrides the clock, and the live log is read on the real clock only (tests use a temporary log)"
        elif os.path.realpath(args.prereg) != os.path.realpath(repo_prereg):
            why = f"--prereg {args.prereg} is not the repository's PREREG.md, whose §11 anchors the live log"
        elif args.t0 and t0 != sealed:
            why = (f"--t0 {args.t0} is not PREREG §11's T0 {report._iso_minute(sealed) if sealed is not None else '(unsealed)'};"
                   " the live log's blocks and days are anchored at the sealed T0 only")
        if why:
            sys.stderr.write(f"inference: refusing: {why} (PREREG §2, §8.4-§8.5)\n")
            return EXIT_REFUSED
    if args.now:
        try:
            now = datetime.datetime.strptime(args.now, "%Y-%m-%dT%H:%M").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            ap.error(f"--now wants YYYY-MM-DDTHH:MM (UTC), got {args.now!r}")
    now = now or datetime.datetime.now(datetime.timezone.utc)
    end = t0 + N_DAYS * 86400
    if args.sample and now.timestamp() < end:
        sys.stderr.write(f"inference: refusing to look: the sample ends {report._iso_minute(end)} and it is {now.strftime('%Y-%m-%dT%H:%MZ')}"
                         f" (PREREG §8.4-§8.5; --pre-t0 runs the shakedown rows)\n")
        return EXIT_NOT_YET
    excl_path = args.exclusions or os.path.join(config.DATA, "exclusions.tsv")
    if args.exclusions and not os.path.exists(args.exclusions):      # only the default may be absent (no exclusions)
        sys.stderr.write(f"inference: no exclusions file at {args.exclusions} (given with --exclusions; leave the flag out"
                         " when there are none)\n")
        return 2
    try:
        excluded, excl_lines = read_exclusions(excl_path)
    except ValueError as e:
        sys.stderr.write(f"inference: {e}\n")
        return 2
    if args.out and os.path.exists(args.out):               # before an hour of bootstrap, not after
        sys.stderr.write(f"inference: --out {args.out} exists; refusing to overwrite it (the result is written once: name a new file)\n")
        return 2
    if not os.path.exists(args.log):
        sys.stderr.write(f"inference: no log at {args.log}\n")
        return 2
    rows, bad, sha, nbytes = read_log(args.log)             # one read: the sha is of the bytes the rows came from
    if args.sample and sealed_repo is not None and real_now.timestamp() < sealed_repo + N_DAYS * 86400:
        held = report.in_sample(rows, sealed_repo)         # a copy of the live log is the live log: read on the real clock
        if held:
            sys.stderr.write(f"inference: refusing to look: {args.log} holds {len(held)} rows of the sealed sample"
                             f" [{report._iso_minute(sealed_repo)}, {report._iso_minute(sealed_repo + N_DAYS * 86400)}) and it is"
                             f" {real_now.strftime('%Y-%m-%dT%H:%MZ')}: a copy of the live log is read on the real clock, whatever"
                             " --now, --t0 or --prereg say (PREREG §8.4-§8.5; --pre-t0 runs the shakedown rows)\n")
            return EXIT_NOT_YET
    outs = outcomes.join(rows)
    cut = None
    cap = now.timestamp() if live_log else None           # the live log's real clock: a row stamped after it is not reached
    if args.sample:
        mode, anchor = "sample", t0
        scope = report.in_sample(rows, t0)
        kept = N_DAYS - len(excluded)
    else:
        mode = "pre-t0"
        cut = min([t0] + [s for s in (sealed, sealed_repo) if s is not None])   # a later --t0 or another --prereg never pulls a sample row into the smoke
        scope = [r for r in rows if report.tick_epoch(r["tick_id"]) < cut]
        anchor = report.tick_epoch(min(r["tick_id"] for r in scope)) if scope else t0
        excluded, excl_lines = set(), []                    # exclusions name sample days; none apply before T0
        kept = N_DAYS
    n_blocks = BLOCKS_PER_DAY * N_DAYS
    if mode == "pre-t0":                                    # the shakedown's own span, like report._blocks
        n_blocks = max((int((report.tick_epoch(r["tick_id"]) - anchor) // report.BLOCK_S) for r in scope), default=-1) + 1
    pending = None
    if mode == "sample":                                    # before any number: a pending unit would be dropped as a gap
        pend = pending_units(rows, scope, outs, anchor, excluded, n_blocks, cap)
        if pend and not args.accept_pending:
            sys.stderr.write(f"inference: refusing to run: {len(pend)} H2 unit(s) wait for a t + h the log has not reached"
                             f" (first live row {pend[0][0]}; the log's last row is {rows[-1]['tick_id']}); counted now they would"
                             f" be dropped as gaps. Run again once the log has a row with ts_rx at or after {_iso_second(max(u for _, u in pend))},"
                             " or pass --accept-pending if the log really stopped (PREREG §5: the join is over the whole log)\n")
            return EXIT_NOT_YET
        pending = pend if args.accept_pending else None
    log = {"path": args.log, "sha": sha, "bytes": nbytes, "last": rows[-1]["tick_id"] if rows else "-", "skipped": len(bad), "scope": len(scope)}
    text = render(mode, t0, now, log, excluded, excl_lines, kept,
                  h1(scope, outs, anchor, excluded, args.resamples, n_blocks), h2(scope, outs, anchor, excluded, args.resamples, n_blocks),
                  args.resamples, pending, cut, excl_path,
                  rule3_lines(report.days_table(scope, outs, t0, max(report.tick_epoch(r["tick_id"]) for r in rows), cap), excluded)
                  if mode == "sample" and rows else None)
    if args.now:
        text = text.replace("\n", f" (clock overridden with --now {args.now})\n", 1)
    sys.stdout.write(text)
    if args.out:
        try:
            with open(args.out, "x", encoding="utf-8") as fh:
                fh.write(text)
        except FileExistsError:
            sys.stderr.write(f"inference: --out {args.out} appeared during the run; refusing to overwrite it (the text is on stdout)\n")
            return 2
    return 0


def _read_t0(prereg):
    from .dash import read_t0
    return read_t0(prereg)


def _repo_prereg():
    """The repository's PREREG.md: dash.PREREG_PATH, looked up at call time (tests pin a fixture there)."""
    from . import dash
    return dash.PREREG_PATH


if __name__ == "__main__":
    sys.exit(main())

"""loop/inference.py -- PREREG §4-§5's inference, written before the data, run once at day 28.

    python3 -m loop.inference --sample [--now YYYY-MM-DDTHH:MM] [--exclusions data/exclusions.tsv] [--out FILE]
                                       [--accept-pending]
    python3 -m loop.inference --pre-t0                       # the shakedown rows before T0: a smoke, never a claim

Written 2026-09-26 (day 2 of 28), decided by Alex the same day: the code that will be run is
committed while no sample number has been looked at, and it REFUSES the sample until
T0 + 28 days (exit 3, before the log is opened). --now exists for the tests and is printed
in the header, so a run that overrode the clock says so in its own output. The clock is not
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
  Degenerate: all leans equal or all returns equal -> "not supported: no variance".
Everything beside a statistic is descriptive and says so. No other cell is tested here: a
claim from the 32 gross secondaries would take alpha 0.025 / 32 (§6) and is not made by code.
Standard library only. The output is meant to be committed beside PREREG.md (§10)."""
import argparse, datetime, hashlib, math, os, random, sys

from . import book, config, outcomes, report

SEED = 20260923
RESAMPLES = 10000
BLOCK_LEN = 4                    # units per bootstrap block: 4 x 15 min = 1 h (PREREG §4, §5)
ALPHA_RANK = 249                 # sorted[249] = the 250th value = ceil(0.025 x 10,000), nearest rank, no interpolation
BLOCKS_PER_DAY = 86400 // report.BLOCK_S     # 96
N_DAYS = report.SAMPLE_DAYS                  # 28
MIN_KEPT_DAYS = 21               # PREREG §8.3: fewer kept at day 28 -> void
EXIT_NOT_YET = 3
PAIRS = (("b", "c", "H1 (co-primary): B - C at the primary cell, alpha 0.025"),
         ("a", "c", "A - C at the primary cell, alpha 0.025: stop rule 1's input and §9's reading only (a claim would be a §6 secondary)"),
         ("b", "a", "B - A at the primary cell: point estimate only, stop rule 2 (<= 0 stops the nightly)"))


# ---- the draw (PREREG §5, steps 1-3; §4 says 'as above' for H1) ------------------------------
def resample_indices(rng, n, L=BLOCK_LEN):
    """One circular-block resample of 0..n-1: ceil(n/L) starts, each rng.randrange(n), L
    consecutive wrapped indices from each, concatenated in draw order, the first n kept."""
    out = []
    for _ in range(-(-n // L)):
        s = rng.randrange(n)
        out.extend((s + i) % n for i in range(L))
    return out[:n]


def bootstrap(series, stat, seed=SEED, resamples=RESAMPLES, L=BLOCK_LEN):
    """The sorted resampled statistics and the one-sided lower bound sorted[ALPHA_RANK].
    `stat` maps a list of series elements to a float (None -> 0.0, PREREG §5: undefined never
    rejects). One generator per call: H1 and H2 each get their own random.Random(seed)."""
    n = len(series)
    if n == 0:
        return {"n": 0, "lower": None, "reject": False, "sorted": []}
    rng = random.Random(seed)
    stats = []
    for _ in range(resamples):
        idx = resample_indices(rng, n, L)
        v = stat([series[i] for i in idx])
        stats.append(0.0 if v is None else v)
    stats.sort()
    lower = stats[ALPHA_RANK] if len(stats) > ALPHA_RANK else stats[-1]
    return {"n": n, "lower": lower, "reject": lower > 0, "sorted": stats}


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def pearson_pairs(ps):
    return report.pearson([x for x, _ in ps], [y for _, y in ps])


# ---- days and exclusions ----------------------------------------------------------------------
def day_of_block(k):
    """Block k (0-based from T0) sits in day N = k // 96 + 1 (1-based, d01 .. d28)."""
    return k // BLOCKS_PER_DAY + 1


def read_exclusions(path):
    """data/exclusions.tsv: header 'day\\tfill%\\tjev-err%\\treason', one line per excluded day, the day
    as dNN or NN (T0-anchored, PREREG §2 as read 2026-09-26). Returns (set of N, the lines verbatim).
    A day outside 1..28 or an unparseable day is an error: the file is reproduced in the write-up."""
    days, lines = set(), []
    if not path or not os.path.exists(path):
        return days, lines
    with open(path, encoding="utf-8") as fh:
        for i, raw in enumerate(fh):
            line = raw.rstrip("\n")
            if not line.strip() or (i == 0 and line.lower().startswith("day")):
                continue
            tok = line.split("\t")[0].strip()
            num = tok[1:] if tok[:1] in "dD" else tok
            if not num.isdigit() or not 1 <= int(num) <= N_DAYS:
                raise ValueError(f"{path}:{i + 1}: day {tok!r} is not d01..d{N_DAYS:02d}")
            days.add(int(num))
            lines.append(line)
    return days, lines


# ---- H1 ----------------------------------------------------------------------------------------
def h1_series(rows, outs, x, y, anchor, excluded=(), n_blocks=BLOCKS_PER_DAY * N_DAYS):
    """[(k, S_k)] for every block k in [0, n_blocks) whose day is not excluded, S_k = 0 where no
    row (PREREG §3), from book.replay on the sample rows at (argmax, FEE_BPS_PRIMARY). n_blocks is
    96 x 28 for the sample; --pre-t0 passes the shakedown's own span. Also the descriptive
    pieces: disagreement blocks, trades per side."""
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
    # descriptive: blocks on which a gap longer than the horizon lands (SPEC §10 carries the position
    # across a gap and marks the whole move on the first priced tick after it; PREREG-v2 material)
    priced = sorted(t for t, _ in cell["d"])
    absorbing = set()
    for a, b in zip(priced, priced[1:]):
        if report.tick_epoch(b) - report.tick_epoch(a) > config.HORIZON_S:
            k = int((report.tick_epoch(b) - anchor) // report.BLOCK_S)
            if 0 <= k < n_blocks and day_of_block(k) not in excluded:
                absorbing.add(k)
    return {"series": series, "S": kept, "dis_blocks": len(on_dis), "mean_dis": mean(on_dis), "gap_blocks": len(absorbing),
            "trades_x": len(px["trades"]), "trades_y": len(py["trades"]), "forced_x": px["forced_hold"], "forced_y": py["forced_hold"],
            "ticks": cell["n"], "mean_tick": cell["mean"]}


def h1(rows, outs, anchor, excluded=(), resamples=RESAMPLES, n_blocks=BLOCKS_PER_DAY * N_DAYS):
    out = []
    for x, y, title in PAIRS:
        s = h1_series(rows, outs, x, y, anchor, excluded, n_blocks)
        m = mean(s["S"])
        bs = bootstrap(s["S"], mean, resamples=resamples) if x != "b" or y != "a" else None   # B - A: point estimate only
        out.append({"pair": f"{x.upper()} - {y.upper()}", "title": title, "n": len(s["S"]), "mean": m,
                    "lower": bs["lower"] if bs else None, "reject": bs["reject"] if bs else None,
                    "dis_blocks": s["dis_blocks"], "mean_dis": s["mean_dis"], "gap_blocks": s["gap_blocks"], "ticks": s["ticks"], "mean_tick": s["mean_tick"],
                    "trades_x": s["trades_x"], "trades_y": s["trades_y"], "forced_x": s["forced_x"], "forced_y": s["forced_y"]})
    return out


# ---- H2 ----------------------------------------------------------------------------------------
def h2(rows, outs, anchor, excluded=(), resamples=RESAMPLES, n_blocks=BLOCKS_PER_DAY * N_DAYS):
    live = sorted((r for r in rows if report._live(r)), key=lambda r: r["tick_id"])
    units, drop, firsts = report.h2_units(live, outs, anchor)
    units = [u for u in units if 0 <= u["k"] < n_blocks and day_of_block(u["k"]) not in excluded]
    ps = [(u["lean"], u["ret"]) for u in units]
    xs, ys = [x for x, _ in ps], [y for _, y in ps]
    degenerate = None
    if ps and len(set(xs)) == 1:
        degenerate = "no variance in lean"
    elif ps and len(set(ys)) == 1:
        degenerate = "no variance in ret"
    r = report.pearson(xs, ys) if ps else None
    rho = report.spearman(xs, ys) if ps else None
    bs = bootstrap(ps, pearson_pairs, resamples=resamples) if ps and degenerate is None else None
    return {"n": len(ps), "blocks_with_row": len(firsts), "dropped": dict(drop), "r": r, "rho": rho, "degenerate": degenerate,
            "lower": bs["lower"] if bs else None, "reject": bs["reject"] if bs else False}


def pending_units(rows, scope, outs, anchor, excluded=(), n_blocks=BLOCKS_PER_DAY * N_DAYS):
    """The H2 units whose t + h the log has not reached yet: a kept block's first live row with
    both nouls (report._h2_pair says "gap", not "noul") whose ts_rx + HORIZON_S + JOIN_TOL_S is
    later than the last ts_rx of the whole log (`rows`), so a row inside its join window can still
    be written. Counting such a unit as a gap would drop it for good (PREREG §5: the join is over
    the whole log, the block is never refilled). Returns [(tick_id, the ts_rx epoch it waits for)]."""
    last = max((outcomes.ts_epoch(r["ts_rx"]) for r in rows), default=None)
    if last is None:
        return []
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
def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _f(x, nd=4):
    return "n/a" if x is None else f"{x:.{nd}f}"


def _iso_second(epoch):
    """epoch -> 'YYYY-MM-DDTHH:MM:SSZ', rounded UP to the second (a wait-until time is never early)."""
    return datetime.datetime.fromtimestamp(math.ceil(epoch), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def render(mode, t0, now, log, log_sha, n_rows, excluded, excl_lines, kept_days, h1s, h2s, resamples, pending=None):
    """pending: None when --accept-pending was not given, else the pending_units it overrode."""
    lines = [f"jev-paper-loop inference (PREREG §4-§5), mode {mode}, run at {now.strftime('%Y-%m-%dT%H:%MZ')}",
             f"  log {log} sha256 {log_sha}; rows in scope {n_rows}",
             f"  T0 {report._iso_minute(t0)}; anchor for blocks and days {'T0' if mode == 'sample' else 'the log first tick (pre-T0, descriptive)'}",
             (f"  days kept {kept_days} of {N_DAYS}; excluded {sorted(excluded) or 'none'} (data/exclusions.tsv, reproduced below)" if mode == "sample"
              else "  days and exclusions: not applicable before T0; blocks run over the shakedown's own span"),
             f"  bootstrap: circular blocks of {BLOCK_LEN}, {resamples} resamples, seed {SEED}, one generator per statistic;"
             f" lower bound = sorted[{ALPHA_RANK}] (nearest-rank 2.5th percentile); reject iff > 0"]
    if pending is not None:
        lines.append(f"  --accept-pending given: {len(pending)} H2 unit(s) whose t + h the log has not reached are counted as gaps"
                     " (for a log that really stopped; without the flag the run is refused)"
                     + (": " + ", ".join(t for t, _ in pending) if pending else ""))
    if mode == "pre-t0":
        lines.append("  PRE-T0: shakedown rows only (PREREG §2), never in the sample; every number here is a smoke of the procedure, not a result")
    if mode == "sample" and kept_days < MIN_KEPT_DAYS:
        lines.append(f"  VOID (PREREG §8.3): fewer than {MIN_KEPT_DAYS} days kept; reported as void, a second block is a new pre-registration")
    lines.append("")
    lines.append("H1 -- mean S_k of the paired 15-minute pnl difference, column argmax, 0 bps (gross of fees, net of the spread)")
    if h1s:
        lines.append(f"  descriptive: blocks on which a gap longer than the horizon lands {h1s[0]['gap_blocks']} of {h1s[0]['n']}"
                     " (SPEC §10: the move across a gap is marked on the first priced tick after it; kept as pre-registered)")
    for h in h1s:
        lines.append(f"  {h['pair']}: {h['title']}")
        verdict = ("REJECT H0: the arm beats the other" if h["reject"] else "not rejected") if h["reject"] is not None else "no test (point estimate)"
        lines.append(f"    n blocks {h['n']}; mean S_k {_f(h['mean'])} bps; lower bound {_f(h['lower'])} bps -> {verdict}")
        lines.append(f"    descriptive: disagreement blocks {h['dis_blocks']} ({100.0 * h['dis_blocks'] / h['n']:.1f}%), mean S_k on them {_f(h['mean_dis'])};"
                     f" every tick mean d_t {_f(h['mean_tick'])} over {h['ticks']}; trades {h['trades_x']} vs {h['trades_y']};"
                     f" forced holds {h['forced_x']} vs {h['forced_y']}")
    lines.append("")
    lines.append("H2 -- Pearson r(lean, ret_h_bps) over the units (first live row of each block), alpha 0.025")
    h = h2s
    units = f"  n units {h['n']} (blocks with a live row {h['blocks_with_row']}; dropped {h['dropped'] or 'none'})"
    if h["degenerate"]:
        lines.append(f"{units}: not supported: {h['degenerate']} (PREREG §5 degenerate case)")
    else:
        verdict = "REJECT H0: r > 0" if h["reject"] else "not rejected"
        lines.append(f"{units}; r {_f(h['r'])}; lower bound {_f(h['lower'])} -> {verdict}")
        lines.append(f"  descriptive: Spearman rho {_f(h['rho'])}")
    lines.append("")
    lines.append("reading (PREREG §9): both primaries rejected -> 'the loop works as described'; either alone -> exactly that;"
                 " neither -> stop rule 1. Stop rule 2 reads B - A's point estimate. Secondaries (§6) are not tested here.")
    lines.append("")
    lines.append("data/exclusions.tsv, verbatim:" if excl_lines else "data/exclusions.tsv: absent or empty")
    lines.extend("  " + l for l in excl_lines)
    return "\n".join(lines) + "\n"


def main(argv=None, now=None):
    ap = argparse.ArgumentParser(prog="python3 -m loop.inference", description="PREREG §4-§5 inference, once, at day 28")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sample", action="store_true", help=f"the sample [T0, T0 + {N_DAYS} d); refused before T0 + {N_DAYS} d")
    g.add_argument("--pre-t0", action="store_true", help="the rows before T0 (shakedown): a smoke of the procedure, never a claim")
    ap.add_argument("--log", default=config.DECISIONS)
    ap.add_argument("--t0", help="T0 (UTC minute or tick_id); default: PREREG.md §11")
    ap.add_argument("--prereg", default=os.path.join(config.REPO, "PREREG.md"))
    ap.add_argument("--exclusions", default=os.path.join(config.DATA, "exclusions.tsv"))
    ap.add_argument("--now", help="override the clock (tests). Printed in the header when used.")
    ap.add_argument("--resamples", type=int, default=RESAMPLES, help="tests only; the pre-registered number is 10000")
    ap.add_argument("--out", help="also write the text here")
    ap.add_argument("--accept-pending", action="store_true",
                    help="--sample on a log that really stopped: count the units whose t + h it never reached as gaps (printed)")
    args = ap.parse_args(argv)
    try:
        t0 = report._t0(args.t0) if args.t0 else _read_t0(args.prereg)
    except ValueError:
        ap.error(f"--t0 wants YYYY-MM-DDTHH:MM (UTC) or a tick_id, got {args.t0!r}")
    if t0 is None:
        ap.error("no T0: PREREG.md §11 is unsealed and no --t0 given")
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
    try:
        excluded, excl_lines = read_exclusions(args.exclusions)
    except ValueError as e:
        sys.stderr.write(f"inference: {e}\n")
        return 2
    bad = []
    rows = outcomes.load(args.log, bad)
    outs = outcomes.join(rows)
    if args.sample:
        mode, anchor = "sample", t0
        scope = report.in_sample(rows, t0)
        kept = N_DAYS - len(excluded)
    else:
        mode = "pre-t0"
        scope = [r for r in rows if report.tick_epoch(r["tick_id"]) < t0]
        anchor = report.tick_epoch(min(r["tick_id"] for r in scope)) if scope else t0
        excluded, excl_lines = set(), []                    # exclusions name sample days; none apply before T0
        kept = N_DAYS
    n_blocks = BLOCKS_PER_DAY * N_DAYS
    if mode == "pre-t0":                                    # the shakedown's own span, like report._blocks
        n_blocks = max((int((report.tick_epoch(r["tick_id"]) - anchor) // report.BLOCK_S) for r in scope), default=-1) + 1
    pending = None
    if mode == "sample":                                    # before any number: a pending unit would be dropped as a gap
        pend = pending_units(rows, scope, outs, anchor, excluded, n_blocks)
        if pend and not args.accept_pending:
            sys.stderr.write(f"inference: refusing to run: {len(pend)} H2 unit(s) wait for a t + h the log has not reached"
                             f" (first live row {pend[0][0]}; the log's last row is {rows[-1]['tick_id']}); counted now they would"
                             f" be dropped as gaps. Run again once the log has a row with ts_rx at or after {_iso_second(max(u for _, u in pend))},"
                             " or pass --accept-pending if the log really stopped (PREREG §5: the join is over the whole log)\n")
            return EXIT_NOT_YET
        pending = pend if args.accept_pending else None
    text = render(mode, t0, now, args.log, sha256_of(args.log) if os.path.exists(args.log) else "-", len(scope), excluded, excl_lines,
                  kept, h1(scope, outs, anchor, excluded, args.resamples, n_blocks), h2(scope, outs, anchor, excluded, args.resamples, n_blocks),
                  args.resamples, pending)
    if args.now:
        text = text.replace("\n", f" (clock overridden with --now {args.now})\n", 1)
    sys.stdout.write(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    return 0


def _read_t0(prereg):
    from .dash import read_t0
    return read_t0(prereg)


if __name__ == "__main__":
    sys.exit(main())

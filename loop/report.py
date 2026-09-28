"""make report: the seven sections of CONTRACT §4, plain text, from the decision log alone.

May: read data/decisions.jsonl (outcomes.load), join every tick to t+h (outcomes.join),
replay the paper book per arm, column and fee (book.replay) and print counts, rates and
means to stdout. May not: write a file, send anything, see the key, read prompts/ or
anything under the crypto repo, or print a p-value -- inference is PREREG.md's and runs
once; this prints the numbers PREREG names, and nothing here decides anything.

Blinding (CLAUDE.md): a run without --health on rows of the sealed sample prints §1-§3 and
a WITHHELD line until T0 + 28 d; that T0 is read from the repo's own PREREG.md §11
(dash.read_t0) whatever --prereg says; --sample takes --t0 from PREREG §11; --unblind prints
§4-§7 and says so on stderr. Besides the log, main reads PREREG.md §11 and looks for data/HALT.

Every section is one function returning its numbers and its rendered lines from a single
computation, so a test asserts the number and the text together. The pair table (§4.5) is
3 pairs x 11 columns x len(config.FEE_BPS_COLUMNS) fees (6 today: 198 cells, ascending; the
primary config.FEE_BPS_PRIMARY = 0 bps, gross, is the first and the venue's own taker
config.FEE_BPS_VENUE = 120 bps, the realistic-cost column, the last); book.paired per cell
is two replays, ~396 at 0.065 s per replay of 40,320 rows (28 days, measured), ~26 s. One
replay per (arm, column, fee) is kept instead: 2 arms x 11 x 6 + 6 for arm C, which reads
no column = 138, ~9 s. d_t is book.paired's own expression, px[t] - py[t], on the cached
pnl dicts, and tests/test_report.py pins the primary cell to book.paired itself.

The pre-registered unit is the 900 s block (PREREG §3): S_k = the sum of d_t over the ticks
with T0 + 900k <= tick_id < T0 + 900(k+1). --t0 names T0 (PREREG §11): rows are cut to the
sample [T0, T0 + 28 days) BEFORE anything is replayed, so every arm starts flat at T0 and no
shakedown, attended or dry row before it carries a position in. Without --t0 the blocks are
anchored at the log's first tick and the figures are descriptive only. Disagreement is on the
SIDE (long vs flat), never on the quantity: two arms long on entries opened at different ticks
hold different qty (NOTIONAL/ask at each entry), so their d_t is (qx - qy) * dmid, entry-price
noise, not a disagreement. The t+h join runs over the whole log, so a sample row near the end
still finds its outcome in the row after the sample.

H2 (PREREG §5; 2026-09-24, decided by Alex: H2 moves to the direction probabilities) is read
in §6: lean_t = up15.noul - down15.noul (v1's nouls, one pair per tick, shared by A and B)
against ret_h_bps of the same outcome join, Pearson r on the first live row of each 900 s
block (the same anchor as the blocks above), with Spearman rho, Brier against the base rate
and the measured-tail counts beside it. Pearson, Spearman (average ranks) and Brier are
written out here, stdlib only; no interval and no p-value (PREREG §5's bootstrap runs once,
by hand). Beside the statistic, the `trend` word as a no-model comparator (-1/0/+1): Jev sees only
the four words, so r(lean, trend), r(trend, ret) and r(lean, ret) within `flat` show how much of
lean the word already is. §7 keeps the old arm-A confidence table, descriptive: v1's action
criteria restate rule_c, so that confidence reads how well the answer matched the rule, not the
market. --health prints sections 1-3 only (PREREG §8.4's day-14 look) and computes nothing else.

An empty, missing or dry-only log is said so at the top; health and occupancy still print
(a dry log has adjectives), the other sections say what they lack.
"""
import argparse, bisect, collections, datetime, functools, math, os, sys

from loop import book, config, outcomes, rules, state

PAIRS = (("b", "c"), ("a", "c"), ("b", "a"))       # §4.5 order: the night shift's arm against the rule first
# The primary CELL, PREREG §4's H1: (B, C, argmax, FEE_BPS_PRIMARY). The fee is 0 bps, gross
# (2026-09-24, decided by Alex): at 0 a difference between arms is direction NET OF THE SPREAD
# (a round trip still pays one spread: 0.87 bps at 1c, 1.74 at 2c on ~$115, against a 1.78 bps
# per-block MDE, so trades/day is printed beside every cell and read with it); at the venue's 120 bps taker a round trip is 240 bps against a ~33 bps 15-min sd, so a net
# cell mostly ranks turnover and is printed beside it as the realistic cost, descriptive only.
# argmax is the one column with no threshold in it (every other column carries an unmeasured
# cut this project exists to measure).
PRIMARY = ("b", "c", "argmax", config.FEE_BPS_PRIMARY)
VENUE_FEE = config.FEE_BPS_VENUE                      # the realistic-cost column, printed with its source
BLOCK_S = config.HORIZON_S                          # 900: PREREG §3's block, one horizon, anchored at T0
SAMPLE_DAYS = 28                                    # PREREG §2: the sample is [T0, T0 + 28 days)
TICKS_PER_DAY = 86400 // config.CADENCE_S          # 1440: trades/day is per 1440 TICKS, so a day of outage does not dilute it
OCCUPANCY_FLAG = 0.95                               # §4.2: a word above this share is a constant, and arms cannot disagree on one
CAL_EDGES = tuple(config.CONF_THRESHOLDS) + (1.0,)  # §4.7: [0.5,0.7) [0.7,0.85) [0.85,0.99) [0.99,1.0]; the last edge is closed
CORRECT = {("buy", "up"), ("sell", "down"), ("hold", "flat")}   # §4.7: argmax was right iff it named the move that came
NOUL_HIGH = config.NOUL_TAIL                        # §4.6 tails: the measured noul tails (JEV PROTOCOL 2.2), >= 0.99 ...
NOUL_LOW = 0.15                                     # ... and < 0.15; everything between is the unmeasured band
LEAN_DP = 12                                        # lean = round(up - down, 12): the nouls are decimals, so this drops
                                                    # binary noise only (0.4 - 0.3 != 0.3 - 0.2 in floats) and equal
                                                    # leans stay equal for "no variance" and for tied ranks
TREND_SIGN = {"dumping": -1, "flat": 0, "pumping": 1}   # §4.6's no-model comparator: the `trend` word as a sign. Jev
                                                    # sees only the four words and rule_c acts on this one, so the
                                                    # report shows how much of lean it already is (PREREG §5, §9)
CHOICES = rules.CHOICES
ARMS = ("a", "b", "c")


# ---- small helpers: every rate in the report goes through _pct so n/0 is never a crash ----
def _num(x):
    """A finite real number. An int past a float's range is not one (math.isfinite would raise on it)."""
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        return False
    try:
        return math.isfinite(x)
    except OverflowError:
        return False


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _p95(xs):
    """Nearest-rank p95, sorted[ceil(0.95 N) - 1], in integer arithmetic (0.95 * 20 is
    18.999999999999996 in binary and a float ceil would land one rank low)."""
    s = sorted(xs)
    return s[(95 * len(s) + 99) // 100 - 1] if s else None


def _pct(n, d):
    return f"{n}/{d} ({100.0 * n / d:.1f}%)" if d else f"{n}/{d} (n/a)"


def _rate(n, d):
    return n / d if d else None


def _f(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def _r(x):
    return "n/a" if x is None else f"{100.0 * x:.1f}%"


def _col(row, arm, name):
    cols = (row.get("columns") or {}).get(arm)
    return cols.get(name) if isinstance(cols, dict) else None


def _answer(row, qid):
    a = row.get("answers")
    return a.get(qid) if isinstance(a, dict) and isinstance(a.get(qid), dict) else None


def _jev(row, k):
    j = row.get("jev")
    return j.get(k) if isinstance(j, dict) else None


def answered(rows):
    """Rows that carry a model column: what sections 3-7 need and a dry log lacks."""
    return [r for r in rows if _col(r, "a", "argmax") in CHOICES or _col(r, "b", "argmax") in CHOICES]


# ---- §4.1 health ---------------------------------------------------------------------------
def health(rows, outs, bad=(), t0=None, last=None, now=None, since=None):
    """`last`: the epoch of the whole log's last tick when `rows` were cut to a sample (--t0), so
    the sample's last day can close; None reads it from `rows`. `now`, `since` (epoch): see days_table."""
    live = [r for r in rows if r.get("mode") == "live" and r.get("absence") is None]
    dry = [r for r in rows if r.get("mode") == "dry"]
    absence = collections.Counter(r["absence"] for r in rows if r.get("absence") is not None)
    ticks = sorted({r["tick_id"] for r in rows})
    days = sorted({day_of(t, t0) for t in ticks})   # the table's days: T0-anchored dNN with T0, else UTC dates (a
                                                    # 28-day sample from 21:40Z touches 29 dates and would read "29 days")
    priced = {r["tick_id"] for r in rows if _num(r.get("mid"))}          # a tick can have an outcome only with a mid
    filled = sum(1 for t in priced if (outs.get(t) or {}).get("absence") is None)
    # attempted = the send happened or was tried: live rows that got past the feed and the guards
    attempted = [r for r in rows if r.get("mode") == "live" and r.get("absence") in (None, "jev")]
    errors = collections.Counter((_jev(r, "error") or "?") for r in attempted if r.get("absence") == "jev")
    lat = [_jev(r, "latency_ms") for r in rows if _num(_jev(r, "latency_ms"))]
    uncounted = sum(1 for r in rows if type(_jev(r, "input_tokens")) is int and not _num(_jev(r, "input_tokens")))   # not a
                                                                    # bool: an int subclass that _num refuses, and cycle.billed_tokens skips
    try:
        tokens = sum(_jev(r, "input_tokens") for r in rows if _num(_jev(r, "input_tokens")))   # in the try: two int counts of 1e308
                                            # sum to an int past a float's range, and a float count after them raises here
        usd = tokens * config.USD_PER_MTOK / 1e6
    except OverflowError:                   # counts that each fit a float can sum past one (two server replies of 1e308)
        tokens = usd = math.inf             # still a float: the dash's spend tile formats it
    spent = (f"  input tokens {tokens} = ${usd:.6f} to date" if math.isfinite(usd)
             else "  input tokens: their sum is past a float's range, so no dollar figure") + f" at ${config.USD_PER_MTOK}/Mtok"
    models = collections.Counter(r["model_answered"] for r in rows if isinstance(r.get("model_answered"), str))
    drift = sum(1 for r in rows if r.get("drift") is True)
    versions = collections.Counter(str(r.get("prompt_b")) for r in rows)
    span = f"{ticks[0]}..{ticks[-1]}" if ticks else "-"
    per_day = days_table(rows, outs, t0, last, now, since)
    keys = collections.Counter(_jev(r, "key_path") for r in rows if isinstance(_jev(r, "key_path"), str))
    shared = sum(v for k, v in keys.items() if "loop" not in k.lower())      # PROTOCOL §3.6: the loop's own key, or it says so
    hz = realised_horizon(rows)
    halt = os.path.exists(config.HALT)
    lines = [
        f"  rows {len(rows)} ({len(ticks)} ticks, {len(days)} day{'s' if len(days) != 1 else ''}, {span}); skipped lines {len(bad)}",
        f"  live answered {len(live)}; dry {len(dry)}; absence: "
        + (", ".join(f"{k} {v}" for k, v in sorted(absence.items())) or "none"),
        f"  outcome fill {_pct(filled, len(priced))} of priced ticks",
        f"  jev errors {_pct(sum(errors.values()), len(attempted))} of attempted sends"
        + (": " + ", ".join(f"{k} {v}" for k, v in sorted(errors.items())) if errors else ""),
        f"  latency ms: mean {_f(_mean(lat), 1)}, p95 {_f(_p95(lat), 0)} (n {len(lat)})",
        spent
        + (f"; {uncounted} row(s) report a count past a float's range, left out (the spend guard trips on one)" if uncounted else ""),
        f"  model_answered: " + (", ".join(f"{k} {v}" for k, v in sorted(models.items())) or "none")
        + f" ({len(models)} distinct); drift {drift}",
        f"  prompt_b versions: " + ", ".join(f"{k} {v}" for k, v in sorted(versions.items())),
        f"  key answering: " + (", ".join(f"{k} {v}" for k, v in sorted(keys.items())) or "none")
        + (f"; SHARED KEY on {shared} rows (PROTOCOL §3.6: the loop key file is missing or empty)" if shared else ""),
        f"  realised horizon, ts_rx to ts_rx of the row the join picked: mean {_f(hz['mean'], 1)} s, |offset from {config.HORIZON_S}| p95 {_f(hz['p95'], 0)} s,"
        f" max {_f(hz['max'], 0)} s (n {hz['n']}); isolated skipped minutes {hz['skips']}"
        + (" (a missed :00 fire; until 2026-09-27 05:18Z launchd's 60 s StartInterval ran a ~61 s grid, ~28 a day; each costs the row 15 min earlier its outcome)" if hz["skips"] else ""),
        ("  HALT: PRESENT since " + _halt_when() + " (the reason is the file's text; nothing is sent; the feed, arm C, the join and this"
         " report go on; clearing it is a person's act, STEPS §5)") if halt else "  HALT: absent",
    ] + per_day["lines"]
    return {"lines": lines, "rows": len(rows), "ticks": len(ticks), "live": len(live), "dry": len(dry),
            "days": per_day["days"], "bad_days": per_day["bad"], "empty_days": per_day["empty"], "keys": dict(keys), "shared_key_rows": shared,
            "horizon": hz, "halt": halt,
            "absence": dict(absence), "priced": len(priced), "filled": len(priced) and filled,
            "fill": _rate(filled, len(priced)), "attempted": len(attempted), "errors": dict(errors),
            "error_rate": _rate(sum(errors.values()), len(attempted)), "latency_mean": _mean(lat),
            "latency_p95": _p95(lat), "tokens": tokens, "usd": usd, "models": dict(models), "drift": drift,
            "versions": dict(versions), "skipped": len(bad)}


def _halt_when():
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(config.HALT), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    except OSError:
        return "?"


def realised_horizon(rows):
    """What the outcome join actually reached, in wall-clock seconds between the two snapshots:
    for the row that speaks for each tick (outcomes.rank: the live decision first), the ts_rx of
    the row outcomes.pick takes for it minus its own ts_rx, so the line measures the horizon the
    join realised and nothing else (until 2026-09-28 this paired rows by tick_id, 900 s apart by
    the minute, and reported offsets outside the join's +-30 s window from rows it never used).
    Also the isolated skipped minutes: a minute with no row whose neighbours both have one, which
    is what launchd's ~61 s StartInterval grid produced (~28 a day until 2026-09-27 05:18Z) and
    which since then means one missed :00 fire; each costs the row 15 minutes earlier its outcome.
    A longer hole is sleep or an outage."""
    speaks = {}
    for r in rows:
        t = r.get("tick_id")
        if isinstance(t, str) and (t not in speaks or outcomes.rank(r) < outcomes.rank(speaks[t])):
            speaks[t] = r
    times, _ = outcomes.priced_points(rows)
    offs = []
    for r in speaks.values():
        a = outcomes.ts_epoch(r.get("ts_rx"))
        if a is None or not _num(r.get("mid")):
            continue
        j = outcomes.pick(times, a)
        if j is not None:
            offs.append(times[j] - a - config.HORIZON_S)
    all_ticks = sorted({tick_epoch(r["tick_id"]) for r in rows if isinstance(r.get("tick_id"), str)})
    skips = sum(1 for a, b in zip(all_ticks, all_ticks[1:]) if b - a == 2 * config.CADENCE_S)
    ab = [abs(o) for o in offs]
    return {"n": len(offs), "mean": (config.HORIZON_S + _mean(offs)) if offs else None, "p95": _p95(ab), "max": max(ab) if ab else None,
            "skips": skips}


# ---- §4.1 per day: PREREG §8 stop rule 3 ----------------------------------------------------
BAD_FILL = 0.95             # a UTC day is BAD when live rows with a non-gap outcome are under this share ...
BAD_JEV_ERR = 0.05          # ... or rows with absence "jev" over rows that reached the ask are over this
BAD_DAYS_PAUSE = 3          # the third BAD day writes data/HALT by hand (PREREG §8.3); the calendar goes on
DAY_TICKS = 86400 // config.CADENCE_S   # 1440: cov is ticks over a full day, so a partial day reads low on purpose


def day_of(tick, t0=None):
    """The 'day' a tick belongs to. With T0 (PREREG §2, read as decided by Alex 2026-09-26 before any
    look: 'every UTC day boundary from T0' = 24 h periods anchored at T0, day j = [T0 + 86400(j-1),
    T0 + 86400 j), 96 whole blocks each, so n = 96 x 28 = 2,688): the label 'dNN', d01 the first
    sample day, d00 the day before T0, d29 the day after the sample. Without T0: the UTC calendar day,
    the first 8 chars of tick_id, which is what the nightly's digest and the launchd logs use."""
    if t0 is None:
        return str(tick)[:8]
    j = math.floor((tick_epoch(tick) - t0) / 86400) + 1
    return f"d{j:02d}" if 0 <= j <= 99 else f"d{j}"


def day_span(label, t0):
    """The [from, to) tick_ids of a T0-anchored day label 'dNN'; None for a calendar label."""
    if t0 is None or not (label.startswith("d") and label[1:].lstrip("-").isdigit()):
        return None
    j = int(label[1:])
    a = t0 + 86400 * (j - 1)
    return (_tick_of(a), _tick_of(a + 86400))


def _day_key(label):
    """dNN labels by number (d-1 < d00 < d01 < d10); calendar labels as they are."""
    return (0, int(label[1:])) if label[:1] == "d" and label[1:].lstrip("-").isdigit() else (1, label)


def _tick_of(epoch):
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def days_table(rows, outs, t0=None, last=None, now=None, since=None):
    """Per day (day_of: T0-anchored 'dNN' with T0, else the UTC calendar day): distinct ticks,
    coverage of a full day, live rows, the share of them with a non-gap outcome, the Jev error
    share over rows that reached the ask, and the BAD flag of PREREG §8 stop rule 3. `outs` is the
    join over the WHOLE log, so a day's last 15 minutes are filled by the next day's rows.
    `last` is the epoch of the whole log's last tick: with --t0 the rows are cut to the sample,
    and without it the sample's last day (d28) could never close, since its last row can fill
    only from rows after the cut. None reads it from `rows`. `now` (epoch), when given, caps it:
    a row stamped after the clock (a forward clock step) closes no day that has not happened, turns
    no pending row into a gap, and lists no future day as NO LIVE ROWS; it shows as an open day.
    `since` (epoch), report's --since: a display cut, not a sample cut. No day that ends before it is
    listed (it would read 0 ticks, NO LIVE ROWS, on a full day), and the day it falls inside is
    marked partial and not judged: its coverage and fill are of a subset of its rows.
    With T0, every day from d01 to the day of `last` (at most d28) is listed, rows or not: a day
    the log has no row for is the worst health event and would otherwise be the one day the
    table never shows (2026-09-28). Its fill is 0/0, which PREREG §8.3 does not define, so it is
    flagged NO LIVE ROWS (so is a closed day of absences or dry rows only), counted in `empty`, and
    never marked BAD here: the exclusion is Alex's call.
    Descriptive: the exclusion itself is a line a person appends to data/exclusions.tsv; nothing
    here removes a day from any section."""
    per = {}
    rows_last = max((tick_epoch(r["tick_id"]) for r in rows if isinstance(r.get("tick_id"), str)), default=None)
    last = rows_last if last is None else max(last, rows_last or last)
    if now is not None and last is not None:
        last = min(last, now)
    if t0 is not None and last is not None:
        for j in range(1, min(SAMPLE_DAYS, math.floor((last - t0) / 86400) + 1) + 1):
            if since is not None and t0 + 86400 * j <= since:
                continue                              # the day ended before --since: cut from view, not empty
            per.setdefault(f"d{j:02d}", {"ticks": set(), "live": 0, "filled": 0, "pending": 0, "attempted": 0, "errors": 0})
    all_ticks = sorted({r["tick_id"] for r in rows if isinstance(r.get("tick_id"), str)})
    skips = collections.Counter()
    for a, b in zip(all_ticks, all_ticks[1:]):
        if tick_epoch(b) - tick_epoch(a) == 2 * config.CADENCE_S:
            skips[day_of(_tick_of(tick_epoch(a) + config.CADENCE_S), t0)] += 1   # the missing minute's own day
    for r in rows:
        d = day_of(r.get("tick_id"), t0)
        x = per.setdefault(d, {"ticks": set(), "live": 0, "filled": 0, "pending": 0, "attempted": 0, "errors": 0})
        x["ticks"].add(r["tick_id"])
        if r.get("mode") != "live":
            continue
        if r.get("absence") in (None, "jev"):
            x["attempted"] += 1
        if r.get("absence") == "jev":
            x["errors"] += 1
        elif r.get("absence") is None:
            if (outs.get(r["tick_id"]) or {}).get("absence") is None:
                x["live"] += 1
                x["filled"] += 1
            elif tick_epoch(r["tick_id"]) + config.HORIZON_S + outcomes.JOIN_TOL_S > last:
                x["pending"] += 1                     # the log has not reached t + h yet: not a gap, not decided
            else:
                x["live"] += 1
    days, bad, empty = [], [], []
    for d in sorted(per, key=_day_key):
        x = per[d]
        span = day_span(d, t0)
        end = tick_epoch(span[1]) if span else tick_epoch(d + "T000000Z") + 86400
        is_open = last is None or end + config.HORIZON_S + outcomes.JOIN_TOL_S > last   # its last row can still fill
        fill, err = _rate(x["filled"], x["live"]), _rate(x["errors"], x["attempted"])
        partial = since is not None and span is not None and tick_epoch(span[0]) < since   # --since cuts into it
        is_bad = not is_open and not partial and ((fill is not None and fill < BAD_FILL) or (err is not None and err > BAD_JEV_ERR))
        in_sample_day = span is not None and 1 <= int(d[1:]) <= SAMPLE_DAYS   # only a day the exclusions file could name
        is_empty = in_sample_day and not is_open and not partial and x["live"] == 0 and x["pending"] == 0   # closed, and no live row reached
                                                                    # its t + h: no row at all, or absences (HALT, feed) or dry rows only
        why = []
        if fill is not None and fill < BAD_FILL:
            why.append("fill")
        if err is not None and err > BAD_JEV_ERR:
            why.append("jev-err")
        days.append({"day": d, "span": span, "ticks": len(x["ticks"]), "cov": _rate(len(x["ticks"]), DAY_TICKS), "live": x["live"],
                     "filled": x["filled"], "pending": x["pending"], "skips": skips.get(d, 0), "fill": fill, "attempted": x["attempted"],
                     "errors": x["errors"], "jev_err": err, "open": is_open, "bad": is_bad, "empty": is_empty, "why": why,
                     "partial": partial})
        if is_bad:
            bad.append(d)
        if is_empty:
            empty.append(d)
    what = (f"per day from T0 (dNN = [T0 + 86400(N-1), T0 + 86400 N), 96 blocks; d00 is before T0)" if t0 is not None
            else "per UTC calendar day (no --t0; the sample's days are counted from T0)")
    lines = [f"  {what} (stop rule 3: BAD when fill < {100 * BAD_FILL:.0f}% of live rows or jev errors"
             f" > {100 * BAD_JEV_ERR:.0f}% of attempted; {BAD_DAYS_PAUSE} BAD days pause the run, PREREG §8.3):",
             f"    {'day':<9}{'ticks':>6}{'cov':>7}{'live':>6}{'fill':>7}{'pend':>6}{'skip':>6}{'jev-err':>9}" + ("  from..to" if t0 is not None else "")]
    for x in days:
        lines.append(f"    {x['day']:<9}{x['ticks']:>6}{_pc(x['cov']):>7}{x['live']:>6}{_pc(x['fill']):>7}{x['pending']:>6}{x['skips']:>6}{_pc(x['jev_err']):>9}"
                     + (f"  {x['span'][0]}..{x['span'][1]}" if x["span"] else "")
                     + (f"  BAD ({', '.join(x['why'])})" if x["bad"] else "  NO LIVE ROWS" if x["empty"] else "  open" if x["open"]
                        else "  partial (--since), not judged" if x["partial"] else ""))
    if not days:
        lines.append("    no rows")
    lines.append(f"  BAD days {len(bad)}" + (": " + ", ".join(bad) if bad else "")
                 + "; the exclusion is a line in data/exclusions.tsv, written by hand, never here."
                 " fill counts live rows whose t + h the log has reached (pend = not yet); skip = isolated missing minutes; an open day is not judged")
    if empty:
        lines.append(f"  NO LIVE ROWS on {len(empty)} closed day{'s' if len(empty) != 1 else ''}: {', '.join(empty)}: fill is 0/0, which PREREG"
                     " §8.3 does not define, so the day is not marked BAD here; whether it is excluded is Alex's call, before day 28")
    return {"lines": lines, "days": days, "bad": bad, "empty": empty}


def _pc(x):
    return "n/a" if x is None else f"{100.0 * x:.1f}%"


# ---- §4.2 occupancy ------------------------------------------------------------------------
def occupancy(rows):
    adjs = [r["adj"] for r in rows if isinstance(r.get("adj"), dict)]
    share, flags, lines = {}, [], []
    for d in state.DIMS:
        c = collections.Counter(a.get(d) if isinstance(a.get(d), str) else "?" for a in adjs)   # a non-string (a list, None)
        n = sum(c.values())                                                                    # is OUTSIDE-ALPHABET, never a crash
        parts = []
        for w in state.ALPHABET[d]:
            p = _rate(c.get(w, 0), n)
            share[(d, w)] = p
            parts.append(f"{w} {_pct(c.get(w, 0), n)}")
            if p is not None and p > OCCUPANCY_FLAG:
                flags.append((d, w, p))
        other = n - sum(c.get(w, 0) for w in state.ALPHABET[d])
        if other:
            parts.append(f"OUTSIDE-ALPHABET {other}")                # a word the SPEC does not have: loud, never folded
        lines.append(f"  {d:<5} " + "  ".join(parts))
    states = collections.Counter(r.get("state") for r in rows if isinstance(r.get("state"), str))
    lines.append(f"  distinct states {len(states)} of {3 ** len(state.DIMS)} over {len(adjs)} rows with adjectives")
    for d, w, p in flags:
        lines.append(f"  FLAG {d} is {w} on {100.0 * p:.1f}% > {100 * OCCUPANCY_FLAG:.0f}%: a constant; arms cannot disagree on it")
    if not adjs:
        lines.append("  no rows with adjectives")
    return {"lines": lines, "n": len(adjs), "share": share, "flags": [(d, w) for d, w, _ in flags], "states": len(states)}


# ---- §4.3 test-retest ----------------------------------------------------------------------
def retest(rows):
    """Rows where a_action and b_action were the SAME question (equal shas): two answers to
    one text on one state in one request, so any disagreement is the model's own noise."""
    pairs = []
    for r in rows:
        if not isinstance(r.get("prompt_a_sha"), str) or r.get("prompt_a_sha") != r.get("prompt_b_sha"):
            continue
        a, b = _answer(r, "a_action"), _answer(r, "b_action")
        if a is None or b is None or a.get("choice") not in CHOICES or b.get("choice") not in CHOICES:
            continue
        pairs.append((a, b))
    agree = sum(1 for a, b in pairs if a["choice"] == b["choice"])
    dconf = [abs(a["confidence"] - b["confidence"]) for a, b in pairs
             if _num(a.get("confidence")) and _num(b.get("confidence"))]
    lines = [f"  rows with prompt_a_sha == prompt_b_sha and both answers: {len(pairs)}",
             f"  choice agreement {_pct(agree, len(pairs))}; mean |dconfidence| {_f(_mean(dconf), 4)} (n {len(dconf)})"]
    if not pairs:
        lines.append("  nothing to compare: no answered row carries the same question twice")
    return {"lines": lines, "n": len(pairs), "agree": agree, "agree_rate": _rate(agree, len(pairs)),
            "dconf": _mean(dconf)}


# ---- §4.4 argmax vs rule_c -----------------------------------------------------------------
def agreement(rows):
    conf = collections.Counter()
    for r in rows:
        x, c = _col(r, "a", "argmax"), r.get("rule_c")
        if x in CHOICES and c in CHOICES:
            conf[(x, c)] += 1
    n = sum(conf.values())
    agree = sum(conf[(k, k)] for k in CHOICES)
    lines = [f"  a.argmax == rule_c on {_pct(agree, n)} of rows with both",
             "  a.argmax \\ rule_c   " + "".join(f"{c:>6}" for c in CHOICES)]
    for x in CHOICES:
        lines.append(f"  {x:<20}" + "".join(f"{conf[(x, c)]:>6}" for c in CHOICES))
    if not n:
        lines.append("  no row carries both a model column and rule_c")
    return {"lines": lines, "n": n, "agree": agree, "agree_rate": _rate(agree, n), "confusion": dict(conf)}


# ---- §4.5 the pair table -------------------------------------------------------------------
@functools.lru_cache(maxsize=None)
def tick_epoch(tid):
    """tick_id 'YYYYMMDDTHHMM00Z' -> epoch seconds (UTC). Cached: the pair table asks for every
    tick's epoch in each of its 198 cells (~8M calls over 28 days) and strptime cost 20 us each,
    two thirds of `--health`'s time on a 28-day log (2026-09-28). The fields are cut by position
    and handed to datetime, which refuses what strptime refused (a 13th month, February 30th);
    a string of the wrong shape raises ValueError the same way."""
    if len(tid) != 16 or tid[8] != "T" or tid[15] != "Z" or not (tid[:8] + tid[9:15]).isdigit():
        raise ValueError(f"not a tick_id: {tid!r}")
    return datetime.datetime(int(tid[0:4]), int(tid[4:6]), int(tid[6:8]), int(tid[9:11]), int(tid[11:13]), int(tid[13:15]),
                             tzinfo=datetime.timezone.utc).timestamp()


def _disagreement(px, py):
    """Ticks where the two arms are on different SIDES (one long, one flat) going INTO or OUT
    OF the tick. A quantity difference alone is not a disagreement: two longs opened on
    different ticks hold different qty and give d_t = (qx - qy) * dmid, entry-price noise
    (SPEC §10). The out-only reading would miss a close that leaves both flat."""
    out, prev_x, prev_y = set(), False, False
    for t, _ in px["equity"]:                                        # equity is in tick order, duplicates folded
        lx, ly = px["position"][t] > 0, py["position"][t] > 0
        if lx != ly or prev_x != prev_y:
            out.add(t)
        prev_x, prev_y = lx, ly
    return out


def _blocks(d, dis, anchor, kof=None, n_blocks=None):
    """PREREG §3: S_k = sum of d_t over the ticks with anchor + 900k <= tick < anchor + 900(k+1),
    k = 0 .. n_blocks - 1, where n_blocks is the block of the log's last tick + 1 (capped at the
    sample's 2,688 with --t0; `table` passes it), else the block of the last tick in `d` + 1. A
    block with no row is kept with S_k = 0 (PREREG: the arms agree on nothing), trailing empty
    blocks included when n_blocks says so. A disagreement block holds at least one disagreement
    tick. `kof` maps tick_id -> k, computed once per table (198 cells x every tick). A tick before
    the anchor (never, once the rows are cut to [T0, ...)) is counted in `pre` and left out."""
    if not d:
        return {"n": 0, "dis": 0, "share": None, "mean": None, "mean_dis": None, "S": [], "pre": 0}
    S, hot, pre = collections.defaultdict(float), set(), 0
    for t, v in d:
        k = kof[t] if kof is not None else int((tick_epoch(t) - anchor) // BLOCK_S)
        if k < 0:
            pre += 1
            continue
        S[k] += v
        if t in dis:
            hot.add(k)
    n = n_blocks if n_blocks is not None else (max(S) + 1 if S else 0)
    s = [(k, S.get(k, 0.0)) for k in range(n)]
    sd = [v for k, v in s if k in hot]
    return {"n": len(s), "dis": len(sd), "share": _rate(len(sd), len(s)), "mean": _mean([v for _, v in s]),
            "mean_dis": _mean(sd), "S": s, "pre": pre}


def _cell(px, py, dis):
    """One cell over every tick in tick order. d_t is book.paired's expression on the two
    cached pnl dicts."""
    ticks = [t for t, _ in px["equity"]]
    d = [(t, px["pnl_bps_per_tick"][t] - py["pnl_bps_per_tick"][t]) for t in ticks]
    dd = [v for t, v in d if t in dis]
    return {"n": len(ticks), "dis": len(dd), "mean": _mean([v for _, v in d]), "mean_dis": _mean(dd),
            "hit": _rate(sum(1 for v in dd if v > 0), len(dd)), "d": d}


def by_version(rows, d, dis, kof):
    """The H1 cell by arm B's prompt version, the nightly rewrite's iterations: descriptive, not in
    PREREG (approved 2026-09-28 as a report line, read only after day 28 like the rest of §4-§7).
    d: the primary cell's (tick, d_t) in tick order; dis: its disagreement ticks; kof: tick -> block.
    A tick's version is the prompt_b of its answered live row (the latest ts_rx if two disagree), and
    a tick with none (an absence) takes the version in force before it (the first version for ticks
    before any). A version's blocks run from the block of its first tick to the block of its last,
    an empty one inside counted as S_k = 0 as PREREG §3 keeps it; the block a promotion splits
    counts under both versions, each with its own ticks' d_t; excluded days are not removed; the
    replay runs straight through a promotion (a position opened under one version is closed under
    the next). Each contiguous stretch of one version is a row of its own: a version that comes back
    after another (a rollback: CURRENT set back by hand, bin/promote's docstring) is '<version> #2',
    so no stretch's span covers another version's blocks. Returns [(label, first tick, last tick,
    ticks, blocks)] and the lines."""
    named = {}
    for r in rows:
        v = r.get("prompt_b")
        if _live(r) and r.get("answers") and isinstance(v, str) and v:
            t, ts = r["tick_id"], str(r.get("ts_rx") or "")
            if t not in named or ts >= named[t][0]:
                named[t] = (ts, v)
    first = next((named[t][1] for t in sorted(named)), None)
    if first is None or not d:
        return [], ["  by arm B's prompt version: no answered live row names one"]
    stretches, cur, prev = [], first, None                             # contiguous: a version that comes back after
    for t, v in d:                                                     # another (a rollback) is a stretch of its own,
        cur = named[t][1] if t in named else cur                       # labelled '<version> #2', '#3', ...
        if cur != prev:
            n = sum(1 for name, _, _ in stretches if name == cur)
            stretches.append((cur, f"{cur} #{n + 1}" if n else cur, []))
            prev = cur
        stretches[-1][2].append((t, v))
    out, lines = [], [
        "  H1 cell by arm B's prompt version (the rewrite's iterations), descriptive and NOT in PREREG: a version's",
        "  blocks run from its first tick's to its last tick's (the block a promotion splits counts under both, each",
        "  with its own ticks), excluded days are not removed, and the replay runs straight through a promotion",
        f"    {'version':<9}{'first tick':<18}{'last tick':<18}{'ticks':>7}{'blocks':>7}{'mean_S':>9}{'dis':>6}{'dis%':>7}{'mean_S|dis':>12}"]
    for _, v, dv in stretches:                                         # in order of first tick
        S, hot = collections.defaultdict(float), set()
        for t, x in dv:
            k = kof[t]
            if k < 0:
                continue
            S[k] += x
            if t in dis:
                hot.add(k)
        span = range(min(S), max(S) + 1) if S else range(0)          # an empty block inside the span is S_k = 0, as PREREG §3 keeps it
        sv = [S.get(k, 0.0) for k in span]
        sd = [S[k] for k in S if k in hot]
        a, b = dv[0][0], dv[-1][0]
        out.append((v, a, b, len(dv), len(sv)))
        lines.append(f"    {v:<9}{_iso_minute(tick_epoch(a)):<18}{_iso_minute(tick_epoch(b)):<18}{len(dv):>7,}{len(sv):>7,}"
                     f"{_f(_mean(sv)):>9}{len(sd):>6}{_r(_rate(len(sd), len(sv))):>7}{_f(_mean(sd)):>12}")
    return out, lines


def table(rows, outs, t0=None, last=None):
    """t0: T0 as epoch seconds (the rows are already cut to the sample), or None: blocks are
    then anchored at the first tick of the log. last: the whole log's last tick (epoch), so the
    block count runs to the end of the log (capped at the sample's 2,688) and not just to the
    last tick in the cut."""
    fees = tuple(config.FEE_BPS_COLUMNS)
    if PRIMARY[3] not in fees:
        fees = (PRIMARY[3],) + fees                                  # the primary fee is always a column of the table
    if VENUE_FEE not in fees:
        fees = fees + (VENUE_FEE,)                                       # and so is the venue's own cost
    cache = {}

    def rep(arm, col, fee):
        k = (arm, None if arm == "c" else col, fee)                  # arm C reads rule_c, never a column
        if k not in cache:
            cache[k] = book.replay(rows, outs, arm, col, fee)
        return cache[k]

    n_ticks = len({r["tick_id"] for r in rows})

    def arms_at(fee):
        out = {}
        for arm in ARMS:
            r = rep(arm, PRIMARY[2], fee)
            out[arm] = {"equity": r["equity"][-1][1] if r["equity"] else 0.0, "trades": len(r["trades"]),
                        "forced_hold": r["forced_hold"]}
        return out

    def arms_line(what, fee, pa):
        return (f"  per arm at the {what} (column {PRIMARY[2]}, fee {fee:g} bps): "
                + " | ".join(f"{a.upper()} equity {pa[a]['equity']:.2f} bps, trades {pa[a]['trades']},"
                             f" forced holds {pa[a]['forced_hold']}" for a in ARMS))

    per_arm, per_arm_venue, lines = arms_at(PRIMARY[3]), arms_at(VENUE_FEE), []
    lines.append(f"  primary fee {PRIMARY[3]:g} bps (config.FEE_BPS_PRIMARY): gross of fees, the H1 cell (PREREG §4):"
                 " a difference between arms here is direction net of the spread; turnover still costs one spread"
                 " per round trip (~0.9-1.7 bps at a 1-2c spread, the order of the 1.78 bps per-block MDE), so read"
                 " tr/d beside the cell")
    lines.append(f"  venue fee {VENUE_FEE:g} bps (config.FEE_BPS_VENUE), the realistic-cost column, descriptive only"
                 f" (a round trip is {2 * VENUE_FEE:g} bps): {config.FEE_BPS_VENUE_SOURCE}")
    lines.append(arms_line("primary", PRIMARY[3], per_arm))
    lines.append(arms_line("venue fee", VENUE_FEE, per_arm_venue))
    head_n = len(lines)                                              # the H1 statistic goes after these
    cells = {}
    if not answered(rows):
        lines.append("  no answered rows: arms A and B replay as forced holds, so the pair table is omitted")
        return {"lines": lines, "cells": cells, "per_arm": per_arm, "per_arm_venue": per_arm_venue, "fees": fees}
    first = min(r["tick_id"] for r in rows)
    anchor = t0 if t0 is not None else tick_epoch(first)
    where = (f"T0 {_iso_minute(t0)} (--t0), replayed from flat at T0" if t0 is not None
             else f"the log's first tick {first}; no --t0, so descriptive only")
    kof = {t: int((tick_epoch(t) - anchor) // BLOCK_S) for t in {r["tick_id"] for r in rows}}
    n_blocks = None
    if last is not None:
        n_blocks = int((last - anchor) // BLOCK_S) + 1
        if t0 is not None:
            n_blocks = min(n_blocks, SAMPLE_DAYS * 86400 // BLOCK_S)
    lines.append("  d_t = pnl_x - pnl_y in bps of NOTIONAL per tick; dis = ticks where the SIDES (long vs flat) differ"
                 " into or out of the tick; hit = share of dis ticks with d_t > 0 (a zero is not a hit);"
                 f" tr/d = trades per {TICKS_PER_DAY} ticks")
    lines.append(f"  blocks: S_k = sum of d_t over {BLOCK_S} s block k (PREREG §3), anchored at {where}; n = blocks to the"
                 " log's last tick (an empty block is S_k = 0 and kept); dis = blocks holding a dis tick; mean_S at the * cell"
                 " is PREREG §4's cell, descriptive here; days excluded by stop rule 3 are NOT removed here")
    head = (f"  {'':1} {'column':<9}{'n':>6}{'dis':>6}{'mean_d':>10}{'mean_d|dis':>12}{'hit':>8}{'tr/d x':>8}{'tr/d y':>8}"
            f"  | blocks:{'n':>6}{'dis':>6}{'dis%':>7}{'mean_S':>10}{'mean_S|dis':>12}")
    for x, y in PAIRS:
        for fee in fees:
            lines.append("")
            lines.append(f"  pair {x.upper()}-{y.upper()}  fee {fee:g} bps"
                         + ("  [* primary]" if (x, y, fee) == (PRIMARY[0], PRIMARY[1], PRIMARY[3]) else "")
                         + ("  [venue fee]" if fee == VENUE_FEE else ""))
            lines.append(head)
            for col in rules.COLUMNS:
                px, py = rep(x, col, fee), rep(y, col, fee)
                dis = _disagreement(px, py)
                a = _cell(px, py, dis)
                b = _blocks(a["d"], dis, anchor, kof, n_blocks)
                tpd = (_rate(len(px["trades"]) * TICKS_PER_DAY, n_ticks), _rate(len(py["trades"]) * TICKS_PER_DAY, n_ticks))
                cells[(x, y, col, fee)] = {"all": a, "blocks": b, "trades_per_day": tpd}
                mark = "*" if (x, y, col, fee) == PRIMARY else " "
                lines.append(f"  {mark} {col:<9}{a['n']:>6}{a['dis']:>6}{_f(a['mean']):>10}{_f(a['mean_dis']):>12}"
                             f"{_r(a['hit']):>8}{_f(tpd[0], 1):>8}{_f(tpd[1], 1):>8}"
                             f"  |        {b['n']:>6}{b['dis']:>6}{_r(b['share']):>7}{_f(b['mean']):>10}{_f(b['mean_dis']):>12}")
    pb = cells[PRIMARY]["blocks"]
    pdis = _disagreement(rep(PRIMARY[0], PRIMARY[2], PRIMARY[3]), rep(PRIMARY[1], PRIMARY[2], PRIMARY[3]))
    versions, vlines = by_version(rows, cells[PRIMARY]["all"]["d"], pdis, kof)
    lines[head_n:head_n] = vlines
    lines.insert(head_n, f"  H1 cell (PREREG §4), mean S_k at the primary cell, descriptive here (the statistic is loop.inference's, over"
                    f" the sample's {SAMPLE_DAYS * 86400 // BLOCK_S} blocks with excluded days dropped): {_f(pb['mean'])} bps over {pb['n']} blocks;"
                    f" disagreement blocks {pb['dis']} ({_r(pb['share'])}), mean S_k on them {_f(pb['mean_dis'])}"
                    + (f"; {pb['pre']} ticks before the anchor left out" if pb["pre"] else ""))
    return {"lines": lines, "cells": cells, "per_arm": per_arm, "per_arm_venue": per_arm_venue, "fees": fees,
            "anchor": anchor, "versions": versions}


# ---- §4.6 H2: the direction lean against the 15-minute return (PREREG §5) -------------------
def pearson(xs, ys):
    """Pearson r of two equal-length sequences, or None where it is undefined: fewer than two
    pairs, or either side constant. Constancy is tested on the values (a float mean of equal
    values can differ from them in the last bit, and r of that residue is noise, not 0)."""
    n = len(xs)
    if n < 2 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))       # clamp the last-bit overshoot of a perfect fit


def ranks(xs):
    """1-based ranks; a run of equal values shares the mean of the ranks it spans."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out, i = [0.0] * len(xs), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(xs, ys):
    """Spearman rho = Pearson r of the average ranks; None where that is undefined."""
    return pearson(ranks(xs), ranks(ys))


def brier(ps, ys):
    """(Brier, base-rate Brier, base rate) for probabilities ps of the 0/1 events ys. The base
    rate predicts the sample frequency ybar for every row, so its Brier is ybar * (1 - ybar);
    it is computed the same way as the forecast's. (None, None, None) with no pairs."""
    if not ps:
        return None, None, None
    n = len(ps)
    ybar = sum(ys) / n
    return (sum((p - y) ** 2 for p, y in zip(ps, ys)) / n, sum((ybar - y) ** 2 for y in ys) / n, ybar)


def _why_undefined(xs, ys, xn="lean", yn="ret_h_bps"):
    if len(xs) < 2:
        return f"fewer than 2 pairs (n {len(xs)})"
    if len(set(xs)) < 2:
        return f"no variance in {xn}"
    if len(set(ys)) < 2:
        return f"no variance in {yn}"
    return None


def _corr(xs, ys, xn, yn):
    return {"n": len(xs), "r": pearson(xs, ys), "why": _why_undefined(xs, ys, xn, yn)}


def _live(r):
    return r.get("mode") == "live" and r.get("absence") is None


def h2_units(live, outs, anchor):
    """PREREG §5's units: the first live row of each 900 s block k from `anchor`, that row's
    (lean, ret) pair with k, or the block is dropped ("gap": no outcome; "noul": a direction
    noul missing). `live` is the live rows (mode live, absence null) in tick order; anchor is
    T0 in epoch seconds (or the log's first tick, descriptive). Returns (units, drop, firsts).
    loop/inference.py takes the same units, so the statistic and the test read one function."""
    units, drop, firsts = [], collections.Counter(), {}
    if anchor is None:
        return units, drop, firsts
    for r in live:
        firsts.setdefault(int((tick_epoch(r["tick_id"]) - anchor) // BLOCK_S), r)
    for k in sorted(firsts):
        p = _h2_pair(firsts[k], outs)
        if isinstance(p, dict):
            units.append(dict(p, k=k))
        else:
            drop[p] += 1
    return units, drop, firsts


def _h2_pair(r, outs):
    """One tick's (lean, ret) with what Brier and the tails need, or the reason it is not one:
    "noul" (either direction noul missing or not a number) or "gap" (no outcome at t + h)."""
    u, d = (_answer(r, "up15") or {}).get("noul"), (_answer(r, "down15") or {}).get("noul")
    if not (_num(u) and _num(d)):
        return "noul"
    o = outs.get(r.get("tick_id")) or {}
    if o.get("absence") is not None or not _num(o.get("ret_h_bps")) or o.get("label") is None:
        return "gap"
    return {"tick": r["tick_id"], "up": u, "down": d, "lean": round(u - d, LEAN_DP), "ret": o["ret_h_bps"],
            "label": o["label"], "trend": TREND_SIGN.get((r.get("adj") or {}).get("trend"))}


def _h2_stats(ps):
    xs, ys = [p["lean"] for p in ps], [p["ret"] for p in ps]
    tails = {q: (sum(1 for p in ps if p[q] >= NOUL_HIGH), sum(1 for p in ps if p[q] < NOUL_LOW)) for q in ("up", "down")}
    w = [p for p in ps if p.get("trend") is not None]                # the pairs whose row names a trend word
    fl = [p for p in w if p["trend"] == 0]
    word = {"lean_trend": _corr([p["lean"] for p in w], [p["trend"] for p in w], "lean", "trend"),
            "trend_ret": _corr([p["trend"] for p in w], [p["ret"] for p in w], "trend", "ret_h_bps"),
            "flat": _corr([p["lean"] for p in fl], [p["ret"] for p in fl], "lean", "ret_h_bps")}
    return {"n": len(ps), "r": pearson(xs, ys), "rho": spearman(xs, ys), "why": _why_undefined(xs, ys),
            "brier_up": brier([p["up"] for p in ps], [1.0 if p["label"] == "up" else 0.0 for p in ps]),
            "brier_down": brier([p["down"] for p in ps], [1.0 if p["label"] == "down" else 0.0 for p in ps]),
            "tails": tails, "word": word, "pairs": ps}


def _rv(s, what):
    return f"{s[what]:.4f}" if s[what] is not None else f"undefined ({s['why']})"


def _word_line(name, s):
    w = s["word"]
    return (f"    {name:<12}r(lean, trend) {_rv(w['lean_trend'], 'r')}; r(trend, ret_h_bps) {_rv(w['trend_ret'], 'r')};"
            f" r(lean, ret_h_bps | trend flat) {_rv(w['flat'], 'r')} over {w['flat']['n']}")


def _span(ps, k):
    v = [p[k] for p in ps]
    return f"{min(v):.2f}..{max(v):.2f}" if v else "-"


def h2(rows, outs, t0=None):
    """PREREG §5. Units: the first live row (mode live, absence null) of each 900 s block
    anchored at T0 (--t0) or the log's first tick; that row's pair, or the block is dropped
    (a gap outcome, or a noul missing). "every tick" is every live row with a pair: the
    horizons overlap, so it is printed beside the statistic, never as it."""
    live = sorted((r for r in rows if _live(r)), key=lambda r: r["tick_id"])   # stable: log order within a minute
    every, drop_every = [], collections.Counter()
    for r in live:
        p = _h2_pair(r, outs)
        if isinstance(p, dict):
            every.append(p)
        else:
            drop_every[p] += 1
    anchor = where = None
    if live:                                                         # the table's anchor: the log's first tick, any row
        first = min(r["tick_id"] for r in rows)
        anchor = t0 if t0 is not None else tick_epoch(first)
        where = (f"T0 {_iso_minute(t0)} (--t0)" if t0 is not None
                 else f"the log's first tick {first}; no --t0, so descriptive only")
    units, drop, firsts = h2_units(live, outs, anchor)
    su, se = _h2_stats(units), _h2_stats(every)
    lines = [
        "  lean_t = up15.noul - down15.noul, in [-1, 1]: Jev's own direction probabilities, asked from v1 once per tick"
        " and shared by A and B (never rewritten); y = ret_h_bps of the outcome join (SPEC §11). No inference here:"
        " PREREG §5's block bootstrap runs once, at the end",
        f"  units (PREREG §5): the first live row of each {BLOCK_S} s block anchored at {where or '-'}; {len(firsts)}"
        f" blocks with a live row, dropped: gap {drop['gap']}, missing noul {drop['noul']}; {su['n']} units."
        " Days excluded by stop rule 3 are NOT removed here",
        f"  H2 statistic (PREREG §5), Pearson r(lean, ret_h_bps) over {su['n']} units: {_rv(su, 'r')};"
        f" Spearman rho {_rv(su, 'rho')} (descriptive)",
        f"  every live tick (overlapping horizons, descriptive, never the statistic): r {_rv(se, 'r')},"
        f" rho {_rv(se, 'rho')} over {se['n']} ticks; dropped: gap {drop_every['gap']}, missing noul {drop_every['noul']}",
        "  the trend word beside it (no model; descriptive, never claimed): Jev sees only the four words (SPEC §5) and"
        " rule_c buys only on pumping and sells on dumping or violent (SPEC §6), so lean may recode the word;"
        " trend = +1 pumping, 0 flat, -1 dumping, on the same pairs",
        _word_line("units", su),
        _word_line("every tick", se),
    ]
    if units:
        xs = [p["lean"] for p in units]
        lines.append(f"  over the units: lean min {min(xs):.2f}, mean {_mean(xs):.4f}, max {max(xs):.2f};"
                     f" up15 {_span(units, 'up')}, down15 {_span(units, 'down')}")
    lines.append("  Brier (descriptive; base = the base rate's Brier, predicting the sample frequency p)")
    lines.append(f"    {'':<12}{'n':>6}{'up15':>9}{'base':>9}{'p(up)':>8}{'down15':>9}{'base':>9}{'p(down)':>9}")
    for name, s in (("units", su), ("every tick", se)):
        bu, bd = s["brier_up"], s["brier_down"]
        lines.append(f"    {name:<12}{s['n']:>6}{_f(bu[0], 4):>9}{_f(bu[1], 4):>9}{_f(bu[2], 3):>8}"
                     f"{_f(bd[0], 4):>9}{_f(bd[1], 4):>9}{_f(bd[2], 3):>9}")

    def tl(s):
        return f"up15 {s['tails']['up'][0]}/{s['tails']['up'][1]}, down15 {s['tails']['down'][0]}/{s['tails']['down'][1]}"
    lines.append(f"  measured tails (>= {NOUL_HIGH:g} / < {NOUL_LOW:g}): units {tl(su)}; every tick {tl(se)}")
    if not units:
        lines.append("  no unit yet: no block's first live row has both nouls and an outcome")
    return {"lines": lines, "units": su, "every": se, "blocks": len(firsts), "dropped": dict(drop),
            "dropped_every": dict(drop_every), "anchor": anchor}


# ---- §4.7 arm A's choice confidence: rule-matching, not outcomes (descriptive) --------------
def _bin(c):
    for i in range(len(CAL_EDGES) - 1):
        lo, hi = CAL_EDGES[i], CAL_EDGES[i + 1]
        if lo <= c < hi or (i == len(CAL_EDGES) - 2 and c == hi):
            return i
    return None


def calibration(rows, outs):
    """The table the first H2 read (until 2026-09-24): P(a.argmax correct against the label)
    per confidence bin, now descriptive, with the share of each bin where a.argmax == rule_c
    beside it, which is what the confidence tracks when the criteria restate the rule."""
    bins = [[0, 0, 0] for _ in CAL_EDGES[:-1]]
    below, n = 0, 0
    for r in rows:
        a, x = _answer(r, "a_action"), _col(r, "a", "argmax")
        lab = (outs.get(r.get("tick_id")) or {}).get("label")
        if a is None or x not in CHOICES or lab is None or not _num(a.get("confidence")):
            continue
        i = _bin(a["confidence"])
        if i is None:
            below += 1                                               # under 0.5 (or over 1): not a §4.7 bin, but counted, never hidden
            continue
        bins[i][0] += 1
        bins[i][1] += (x, lab) in CORRECT
        bins[i][2] += x == r.get("rule_c")
        n += 1
    lines = ["  not H2 (PREREG §5, 2026-09-24): v1's action criteria restate rule_c (SPEC §8), so a.argmax is the rule"
             " and this confidence reads how well the answer matched it, not the market; nearly every answer is hold,"
             " which is correct only when |ret_h| < 5 bps",
             f"  arm A rows with an answer and an outcome label: {n} in bins, {below} outside [{CAL_EDGES[0]}, {CAL_EDGES[-1]}]",
             f"  {'confidence':<14}{'n':>6}{'correct':>9}{'P(correct)':>12}{'= rule_c':>10}"]
    out = []
    for i, (k, c, m) in enumerate(bins):
        lo, hi = CAL_EDGES[i], CAL_EDGES[i + 1]
        close = "]" if i == len(bins) - 1 else ")"
        lines.append(f"  [{lo:.2f}, {hi:.2f}{close:<3}{k:>6}{c:>9}{_r(_rate(c, k)):>12}{_r(_rate(m, k)):>10}")
        out.append({"lo": lo, "hi": hi, "n": k, "correct": c, "p": _rate(c, k), "rule": m, "p_rule": _rate(m, k)})
    if not n:
        lines.append("  nothing to calibrate: no arm-A answer has an outcome yet")
    return {"lines": lines, "n": n, "below": below, "bins": out}


# ---- the whole thing -----------------------------------------------------------------------
TITLES = ("1. health", "2. adjective occupancy", "3. test-retest (a_action vs b_action on the same question)",
          "4. a.argmax vs rule_c", "5. paired book: pair x column x fee",
          "6. H2: direction lean (up15 - down15) vs the 15-min return",
          "7. arm A choice confidence vs rule-matching, not outcomes (descriptive)")


HEALTH_N = 3                                        # --health: sections 1-3, PREREG §8.4's day-14 look


def withheld_until(rows, t0, now=None):
    """The end of the sealed sample (epoch) when sections 4-7 must not be printed for `rows`:
    `t0` is PREREG §11's sealed T0 (dash.read_t0; None before sealing), the sample has not ended,
    and a row of the sample is among them (CLAUDE.md: nobody reads §4-§7 before day 28; the
    day-14 look is --health). None otherwise: a log of shakedown rows before T0, or after the
    sample, prints in full."""
    if t0 is None:
        return None
    end = t0 + SAMPLE_DAYS * 86400
    now = datetime.datetime.now(datetime.timezone.utc).timestamp() if now is None else now
    if now >= end:
        return None
    return end if any(t0 <= tick_epoch(r["tick_id"]) < end for r in rows) else None


def render(rows, bad=(), log=None, since=None, missing=False, t0=None, outs=None, health_only=False, last=None, withheld=None, now=None):
    """t0: T0 in epoch seconds when the rows were cut to the sample; outs: the join over the
    WHOLE log (a sample row's t+h may sit after the sample), else the join over `rows`; last:
    the whole log's last tick (epoch) for the same reason, so the sample's last day can close.
    health_only: sections 1-3 only (PREREG §8.4); 4-7 are neither computed nor printed, so the
    blind look cannot show an H1 or H2 number by accident."""
    outs = outcomes.join(rows) if outs is None else outs
    since_ep = tick_epoch(_since(since) + "T000000Z") if since else None   # the day main() validated: fromisoformat
                                                                          # also takes a week date (2026-W40-1) from 3.11 on
    secs = (health(rows, outs, bad, t0, last, now, since_ep), occupancy(rows), retest(rows))
    if not health_only:
        secs += (agreement(rows), table(rows, outs, t0, last), h2(rows, outs, t0), calibration(rows, outs))
    lines = [f"jev-paper-loop report: {config.VENUE} {config.PRODUCT}, cadence {config.CADENCE_S} s, horizon {config.HORIZON_S} s"
             + (f", log {log}" if log else "") + (f", since {since}" if since else "")
             + (f", T0 {_iso_minute(t0)} (sample [T0, T0 + {SAMPLE_DAYS} d), replayed from flat at T0)" if t0 is not None else "")]
    if health_only:
        lines.append(f"health only (--health, PREREG §8.4's day-14 look): sections 1-{HEALTH_N};"
                     f" sections {HEALTH_N + 1}-{len(TITLES)} are neither computed nor printed")
    if withheld is not None:
        lines.append(f"sections {HEALTH_N + 1}-{len(TITLES)} WITHHELD until {_iso_minute(withheld)}: these rows are in the sealed sample and nobody"
                     " reads H1, H2, the pairs or the calibration before day 28 (CLAUDE.md, PREREG §8.4); --unblind prints them, and says so")
    if missing:
        lines.append(f"no log at {log}: nothing has run yet (health and occupancy print anyway)")
    elif not rows:
        lines.append("empty log" + (f" since {since}" if since else "") + (" in the sample window" if t0 is not None else "")
                     + ": no rows (health and occupancy print anyway)")
    elif not answered(rows):
        n_dry = sum(1 for r in rows if r.get("mode") == "dry")
        lines.append(f"no answered rows: {len(rows)} rows ({n_dry} dry, {len(rows) - n_dry} absences); sections 3-7 need live rows")
    for title, sec in zip(TITLES, secs):
        lines.append("")
        lines.append(title)
        lines.extend(sec["lines"])
    return "\n".join(lines) + "\n"


def _since(s):
    """--since YYYY-MM-DD -> the tick_id prefix YYYYMMDD, or None; ValueError on a bad date. isoformat, not
    strftime: glibc's %Y does not pad a year below 1000 ('9990101'), which tick_epoch refuses and which sorts
    after every real tick_id, so main's filter kept no row."""
    return None if s is None else datetime.date.fromisoformat(s).isoformat().replace("-", "")


def _t0(s):
    """--t0 as an ISO minute 'YYYY-MM-DDTHH:MM' (UTC) or a tick_id 'YYYYMMDDTHHMM00Z' (what
    PREREG §11 records) -> epoch seconds, or None; ValueError on anything else."""
    if s is None:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y%m%dT%H%M00Z"):
        try:
            return datetime.datetime.strptime(s, fmt).replace(tzinfo=datetime.timezone.utc).timestamp()
        except ValueError:
            pass
    raise ValueError(s)


def _iso_minute(epoch):
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def in_sample(rows, t0):
    """PREREG §2: the rows with T0 <= tick_id < T0 + SAMPLE_DAYS days, nothing else."""
    end = t0 + SAMPLE_DAYS * 86400
    return [r for r in rows if t0 <= tick_epoch(r["tick_id"]) < end]


def main(argv=None, now=None):
    """`now` (epoch) pins the clock for tests of the withholding; the live run uses the clock."""
    ap = argparse.ArgumentParser(prog="python3 -m loop.report", description="CONTRACT §4 report, plain text, no p-values.")
    ap.add_argument("--since", metavar="YYYY-MM-DD", help="rows whose tick_id date is on or after this day")
    ap.add_argument("--t0", metavar="YYYY-MM-DDTHH:MM",
                    help=f"PREREG T0 (UTC minute, or its tick_id): only [T0, T0 + {SAMPLE_DAYS} d), replayed from flat at T0")
    ap.add_argument("--log", default=config.DECISIONS, help=f"decision log (default {config.DECISIONS})")
    ap.add_argument("--health", action="store_true",
                    help=f"sections 1-{HEALTH_N} only (PREREG §8.4's day-14 look): no H1, H2 or confidence number")
    ap.add_argument("--sample", action="store_true", help="--t0 read from PREREG.md §11 (the sealed T0)")
    ap.add_argument("--prereg", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--unblind", action="store_true",
                    help=f"print sections {HEALTH_N + 1}-{len(TITLES)} on sample rows before the sample has ended (a look; it is printed as one)")
    args = ap.parse_args(argv)
    try:
        since = _since(args.since)
    except ValueError:
        ap.error(f"--since wants YYYY-MM-DD, got {args.since!r}")     # exit 2: the contract's usage-error code
    try:
        t0 = _t0(args.t0)
    except ValueError:
        ap.error(f"--t0 wants YYYY-MM-DDTHH:MM (UTC) or a tick_id, got {args.t0!r}")
    from . import dash                                               # here, not at the top: dash imports report
    sealed = dash.read_t0(args.prereg)                               # PREREG §11's T0, None before sealing
    sealed_repo = dash.read_t0(dash.PREREG_PATH)                     # the withholding reads the REPO's PREREG whatever
                                                                     # --prereg says: a pointer at another file is not a look
    if args.sample:
        if args.t0:
            ap.error("--sample reads T0 from PREREG.md; do not pass --t0 with it")
        if sealed is None:
            ap.error("--sample: PREREG.md §11 is not sealed (no T0 line)")
        t0 = sealed
    rows, bad = [], []
    missing = not os.path.exists(args.log)                           # load() raises on a missing file: day zero is not an error
    if not missing:
        rows = outcomes.load(args.log, bad)
    outs = outcomes.join(rows)                                       # over the whole log: forward only, t+h may follow the cut
    last = max((tick_epoch(r["tick_id"]) for r in rows), default=None)   # likewise: the sample's last day closes on rows after the cut
    if since:
        rows = [r for r in rows if r["tick_id"][:8] >= since]         # tick_id is YYYYMMDDTHHMM00Z; the first 8 chars are the day
    if t0 is not None:
        rows = in_sample(rows, t0)                                   # cut BEFORE any replay: every arm starts flat at T0
    withheld, health_only = None, args.health
    if not health_only:
        withheld = withheld_until(rows, sealed_repo, now)
        if withheld is not None and args.unblind:
            sys.stderr.write(f"report: --unblind: sections {HEALTH_N + 1}-{len(TITLES)} printed on sample rows before"
                             f" {_iso_minute(withheld)}; this is a look (PREREG §8.4)\n")
            withheld = None
        elif withheld is not None:
            health_only = True
    clock = datetime.datetime.now(datetime.timezone.utc).timestamp() if now is None else now
    sys.stdout.write(render(rows, bad, args.log, args.since, missing, t0, outs, health_only, last, withheld, clock))
    return 0


if __name__ == "__main__":
    sys.exit(main())

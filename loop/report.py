"""make report: the six sections of CONTRACT §4, plain text, from the decision log alone.

May: read data/decisions.jsonl (outcomes.load), join every tick to t+h (outcomes.join),
replay the paper book per arm, column and fee (book.replay) and print counts, rates and
means to stdout. May not: write a file, send anything, see the key, read prompts/ or
anything under the crypto repo, or print a p-value -- inference is PREREG.md's and runs
once; this prints the numbers PREREG names, and nothing here decides anything.

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

An empty, missing or dry-only log is said so at the top; health and occupancy still print
(a dry log has adjectives), the other sections say what they lack.
"""
import argparse, collections, datetime, math, os, sys

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
CAL_EDGES = tuple(config.CONF_THRESHOLDS) + (1.0,)  # §4.6: [0.5,0.7) [0.7,0.85) [0.85,0.99) [0.99,1.0]; the last edge is closed
CORRECT = {("buy", "up"), ("sell", "down"), ("hold", "flat")}   # §4.6: argmax was right iff it named the move that came
CHOICES = rules.CHOICES
ARMS = ("a", "b", "c")


# ---- small helpers: every rate in the report goes through _pct so n/0 is never a crash ----
def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


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
    """Rows that carry a model column: what sections 3-6 need and a dry log lacks."""
    return [r for r in rows if _col(r, "a", "argmax") in CHOICES or _col(r, "b", "argmax") in CHOICES]


# ---- §4.1 health ---------------------------------------------------------------------------
def health(rows, outs, bad=()):
    live = [r for r in rows if r.get("mode") == "live" and r.get("absence") is None]
    dry = [r for r in rows if r.get("mode") == "dry"]
    absence = collections.Counter(r["absence"] for r in rows if r.get("absence") is not None)
    ticks = sorted({r["tick_id"] for r in rows})
    days = sorted({t[:8] for t in ticks})
    priced = {r["tick_id"] for r in rows if _num(r.get("mid"))}          # a tick can have an outcome only with a mid
    filled = sum(1 for t in priced if (outs.get(t) or {}).get("absence") is None)
    # attempted = the send happened or was tried: live rows that got past the feed and the guards
    attempted = [r for r in rows if r.get("mode") == "live" and r.get("absence") in (None, "jev")]
    errors = collections.Counter((_jev(r, "error") or "?") for r in attempted if r.get("absence") == "jev")
    lat = [_jev(r, "latency_ms") for r in rows if _num(_jev(r, "latency_ms"))]
    tokens = sum(_jev(r, "input_tokens") for r in rows if _num(_jev(r, "input_tokens")))
    usd = tokens * config.USD_PER_MTOK / 1e6
    models = collections.Counter(r["model_answered"] for r in rows if isinstance(r.get("model_answered"), str))
    drift = sum(1 for r in rows if r.get("drift") is True)
    versions = collections.Counter(str(r.get("prompt_b")) for r in rows)
    span = f"{ticks[0]}..{ticks[-1]}" if ticks else "-"
    lines = [
        f"  rows {len(rows)} ({len(ticks)} ticks, {len(days)} day{'s' if len(days) != 1 else ''}, {span}); skipped lines {len(bad)}",
        f"  live answered {len(live)}; dry {len(dry)}; absence: "
        + (", ".join(f"{k} {v}" for k, v in sorted(absence.items())) or "none"),
        f"  outcome fill {_pct(filled, len(priced))} of priced ticks",
        f"  jev errors {_pct(sum(errors.values()), len(attempted))} of attempted sends"
        + (": " + ", ".join(f"{k} {v}" for k, v in sorted(errors.items())) if errors else ""),
        f"  latency ms: mean {_f(_mean(lat), 1)}, p95 {_f(_p95(lat), 0)} (n {len(lat)})",
        f"  input tokens {tokens} = ${usd:.6f} to date at ${config.USD_PER_MTOK}/Mtok",
        f"  model_answered: " + (", ".join(f"{k} {v}" for k, v in sorted(models.items())) or "none")
        + f" ({len(models)} distinct); drift {drift}",
        f"  prompt_b versions: " + ", ".join(f"{k} {v}" for k, v in sorted(versions.items())),
    ]
    return {"lines": lines, "rows": len(rows), "ticks": len(ticks), "live": len(live), "dry": len(dry),
            "absence": dict(absence), "priced": len(priced), "filled": len(priced) and filled,
            "fill": _rate(filled, len(priced)), "attempted": len(attempted), "errors": dict(errors),
            "error_rate": _rate(sum(errors.values()), len(attempted)), "latency_mean": _mean(lat),
            "latency_p95": _p95(lat), "tokens": tokens, "usd": usd, "models": dict(models), "drift": drift,
            "versions": dict(versions), "skipped": len(bad)}


# ---- §4.2 occupancy ------------------------------------------------------------------------
def occupancy(rows):
    adjs = [r["adj"] for r in rows if isinstance(r.get("adj"), dict)]
    share, flags, lines = {}, [], []
    for d in state.DIMS:
        c = collections.Counter(a.get(d) for a in adjs)
        n = sum(c.values())
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
def tick_epoch(tid):
    """tick_id 'YYYYMMDDTHHMM00Z' -> epoch seconds (UTC)."""
    return datetime.datetime.strptime(tid, "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc).timestamp()


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


def _blocks(d, dis, anchor):
    """PREREG §3: S_k = sum of d_t over the ticks with anchor + 900k <= tick < anchor + 900(k+1),
    k = 0 .. the block of the last tick. A block with no row is kept with S_k = 0 (PREREG: the
    arms agree on nothing). A disagreement block holds at least one disagreement tick."""
    if not d:
        return {"n": 0, "dis": 0, "share": None, "mean": None, "mean_dis": None, "S": []}
    S, hot = collections.defaultdict(float), set()
    for t, v in d:
        k = int((tick_epoch(t) - anchor) // BLOCK_S)
        S[k] += v
        if t in dis:
            hot.add(k)
    ks = range(max(S) + 1)
    s = [(k, S.get(k, 0.0)) for k in ks]
    sd = [v for k, v in s if k in hot]
    return {"n": len(s), "dis": len(sd), "share": _rate(len(sd), len(s)), "mean": _mean([v for _, v in s]),
            "mean_dis": _mean(sd), "S": s}


def _cell(px, py, dis):
    """One cell over every tick in tick order. d_t is book.paired's expression on the two
    cached pnl dicts."""
    ticks = [t for t, _ in px["equity"]]
    d = [(t, px["pnl_bps_per_tick"][t] - py["pnl_bps_per_tick"][t]) for t in ticks]
    dd = [v for t, v in d if t in dis]
    return {"n": len(ticks), "dis": len(dd), "mean": _mean([v for _, v in d]), "mean_dis": _mean(dd),
            "hit": _rate(sum(1 for v in dd if v > 0), len(dd)), "d": d}


def table(rows, outs, t0=None):
    """t0: T0 as epoch seconds (the rows are already cut to the sample), or None: blocks are
    then anchored at the first tick of the log."""
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
    lines.append("  d_t = pnl_x - pnl_y in bps of NOTIONAL per tick; dis = ticks where the SIDES (long vs flat) differ"
                 " into or out of the tick; hit = share of dis ticks with d_t > 0 (a zero is not a hit);"
                 f" tr/d = trades per {TICKS_PER_DAY} ticks")
    lines.append(f"  blocks: S_k = sum of d_t over {BLOCK_S} s block k (PREREG §3), anchored at {where}; n = blocks"
                 " (an empty block is S_k = 0 and kept); dis = blocks holding a dis tick; mean_S at the * cell is"
                 " PREREG §4's H1 statistic; days excluded by stop rule 3 are NOT removed here")
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
                b = _blocks(a["d"], dis, anchor)
                tpd = (_rate(len(px["trades"]) * TICKS_PER_DAY, n_ticks), _rate(len(py["trades"]) * TICKS_PER_DAY, n_ticks))
                cells[(x, y, col, fee)] = {"all": a, "blocks": b, "trades_per_day": tpd}
                mark = "*" if (x, y, col, fee) == PRIMARY else " "
                lines.append(f"  {mark} {col:<9}{a['n']:>6}{a['dis']:>6}{_f(a['mean']):>10}{_f(a['mean_dis']):>12}"
                             f"{_r(a['hit']):>8}{_f(tpd[0], 1):>8}{_f(tpd[1], 1):>8}"
                             f"  |        {b['n']:>6}{b['dis']:>6}{_r(b['share']):>7}{_f(b['mean']):>10}{_f(b['mean_dis']):>12}")
    pb = cells[PRIMARY]["blocks"]
    lines.insert(head_n, f"  H1 statistic (PREREG §4), mean S_k at the primary cell: {_f(pb['mean'])} bps over {pb['n']} blocks;"
                    f" disagreement blocks {pb['dis']} ({_r(pb['share'])}), mean S_k on them {_f(pb['mean_dis'])}")
    return {"lines": lines, "cells": cells, "per_arm": per_arm, "per_arm_venue": per_arm_venue, "fees": fees,
            "anchor": anchor}


# ---- §4.6 calibration, arm A ---------------------------------------------------------------
def _bin(c):
    for i in range(len(CAL_EDGES) - 1):
        lo, hi = CAL_EDGES[i], CAL_EDGES[i + 1]
        if lo <= c < hi or (i == len(CAL_EDGES) - 2 and c == hi):
            return i
    return None


def calibration(rows, outs):
    bins = [[0, 0] for _ in CAL_EDGES[:-1]]
    below, n = 0, 0
    for r in rows:
        a, x = _answer(r, "a_action"), _col(r, "a", "argmax")
        lab = (outs.get(r.get("tick_id")) or {}).get("label")
        if a is None or x not in CHOICES or lab is None or not _num(a.get("confidence")):
            continue
        i = _bin(a["confidence"])
        if i is None:
            below += 1                                               # under 0.5 (or over 1): not a §4.6 bin, but counted, never hidden
            continue
        bins[i][0] += 1
        bins[i][1] += (x, lab) in CORRECT
        n += 1
    lines = [f"  arm A rows with an answer and an outcome label: {n} in bins, {below} outside [{CAL_EDGES[0]}, {CAL_EDGES[-1]}]",
             f"  {'confidence':<14}{'n':>6}{'correct':>9}{'P(correct)':>12}"]
    out = []
    for i, (k, c) in enumerate(bins):
        lo, hi = CAL_EDGES[i], CAL_EDGES[i + 1]
        close = "]" if i == len(bins) - 1 else ")"
        lines.append(f"  [{lo:.2f}, {hi:.2f}{close:<3}{k:>6}{c:>9}{_r(_rate(c, k)):>12}")
        out.append({"lo": lo, "hi": hi, "n": k, "correct": c, "p": _rate(c, k)})
    if not n:
        lines.append("  nothing to calibrate: no arm-A answer has an outcome yet")
    return {"lines": lines, "n": n, "below": below, "bins": out}


# ---- the whole thing -----------------------------------------------------------------------
TITLES = ("1. health", "2. adjective occupancy", "3. test-retest (a_action vs b_action on the same question)",
          "4. a.argmax vs rule_c", "5. paired book: pair x column x fee", "6. calibration, arm A")


def render(rows, bad=(), log=None, since=None, missing=False, t0=None, outs=None):
    """t0: T0 in epoch seconds when the rows were cut to the sample; outs: the join over the
    WHOLE log (a sample row's t+h may sit after the sample), else the join over `rows`."""
    outs = outcomes.join(rows) if outs is None else outs
    secs = (health(rows, outs, bad), occupancy(rows), retest(rows), agreement(rows), table(rows, outs, t0),
            calibration(rows, outs))
    lines = [f"jev-paper-loop report: {config.VENUE} {config.PRODUCT}, cadence {config.CADENCE_S} s, horizon {config.HORIZON_S} s"
             + (f", log {log}" if log else "") + (f", since {since}" if since else "")
             + (f", T0 {_iso_minute(t0)} (sample [T0, T0 + {SAMPLE_DAYS} d), replayed from flat at T0)" if t0 is not None else "")]
    if missing:
        lines.append(f"no log at {log}: nothing has run yet (health and occupancy print anyway)")
    elif not rows:
        lines.append("empty log" + (f" since {since}" if since else "") + (" in the sample window" if t0 is not None else "")
                     + ": no rows (health and occupancy print anyway)")
    elif not answered(rows):
        lines.append(f"dry-only log: {len(rows)} rows and none answered; sections 3-6 need live rows")
    for title, sec in zip(TITLES, secs):
        lines.append("")
        lines.append(title)
        lines.extend(sec["lines"])
    return "\n".join(lines) + "\n"


def _since(s):
    """--since YYYY-MM-DD -> the tick_id prefix YYYYMMDD, or None; ValueError on a bad date."""
    return None if s is None else datetime.date.fromisoformat(s).strftime("%Y%m%d")


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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m loop.report", description="CONTRACT §4 report, plain text, no p-values.")
    ap.add_argument("--since", metavar="YYYY-MM-DD", help="rows whose tick_id date is on or after this day")
    ap.add_argument("--t0", metavar="YYYY-MM-DDTHH:MM",
                    help=f"PREREG T0 (UTC minute, or its tick_id): only [T0, T0 + {SAMPLE_DAYS} d), replayed from flat at T0")
    ap.add_argument("--log", default=config.DECISIONS, help=f"decision log (default {config.DECISIONS})")
    args = ap.parse_args(argv)
    try:
        since = _since(args.since)
    except ValueError:
        ap.error(f"--since wants YYYY-MM-DD, got {args.since!r}")     # exit 2: the contract's usage-error code
    try:
        t0 = _t0(args.t0)
    except ValueError:
        ap.error(f"--t0 wants YYYY-MM-DDTHH:MM (UTC) or a tick_id, got {args.t0!r}")
    rows, bad = [], []
    missing = not os.path.exists(args.log)                           # load() raises on a missing file: day zero is not an error
    if not missing:
        rows = outcomes.load(args.log, bad)
    outs = outcomes.join(rows)                                       # over the whole log: forward only, t+h may follow the cut
    if since:
        rows = [r for r in rows if r["tick_id"][:8] >= since]         # tick_id is YYYYMMDDTHHMM00Z; the first 8 chars are the day
    if t0 is not None:
        rows = in_sample(rows, t0)                                   # cut BEFORE any replay: every arm starts flat at T0
    sys.stdout.write(render(rows, bad, args.log, args.since, missing, t0, outs))
    return 0


if __name__ == "__main__":
    sys.exit(main())

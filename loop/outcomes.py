"""The t+h join: what the log recorded a horizon after each decision, and the
reader for the log itself.

May: read data/decisions.jsonl line by line, and pair each row at t with the
priced row whose ts_rx is NEAREST t+h, within +-JOIN_TOL_S (half a cadence).
May not: fetch anything, back-fill anything, or ever hand back a row outside
that window. A missing row is `gap`, never the nearest one outside it: a wrong
row would score a decision against a price it was not made about.

Why nearest-within-half-a-cadence and not "first row in [t+h, t+h+90 s]" (the
first form, replaced 2026-09-24 before any sample row): ts_rx is the feed-entry
clock, i.e. the minute boundary plus timing noise (sleep overshoot and the
guards under --forever; launchd's calendar-minute fire (StartInterval's phase
until 2026-09-27) and interpreter start). A one-sided window starting AT t+h drops the t+15 row whenever its
noise is 1 ms smaller than t's, and then takes the t+16 row: a 15- or 16-minute
horizon on a coin flip. A +-30 s window around t+h holds exactly one on-cadence
row whatever the phase (rows 60 s apart always leave one within 30 s of any
instant), so |horizon - 900| <= 30 s, and a missing t+15 row is a gap because
its neighbours are 60 s away. Ties (two rows exactly 30 s either side) go to the
earlier row. Everything here is forward-only: t sees t+h, never the reverse.
"""
import bisect, datetime, json, math, re

from loop import config

JOIN_TOL_S = config.CADENCE_S / 2   # 30.0: half a cadence either side of t+h (docstring)
DEAD_BAND_BPS = config.DEAD_BAND_BPS   # |ret| below this is "flat"; at the band it is a move
GAP = {"mid_h": None, "ret_h_bps": None, "label": None, "absence": "gap"}
_TICK = re.compile(r"^\d{8}T\d{6}Z$")     # parseable by every reader's clock; SPEC §2 floors it, a reader does not police that
ROW_START = '{"v":'                        # every row cycle.write_row appends begins so (compact JSON, "v" first)


def _tick_ok(t):
    """The same parse report.tick_epoch does; None when the digits are not a date (20261399T...)."""
    try:
        return datetime.datetime.strptime(t, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None


def _num(x):
    """A finite positive number: bool is an int in Python and a null mid is None."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def ts_epoch(s):
    """ISO8601 (the row's ts_rx, UTC ms with a Z) -> epoch seconds, or None if
    the string cannot be read, so a bad clock string becomes a gap and never a
    candidate for someone else's join."""
    if not isinstance(s, str):
        return None
    try:
        d = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:                       # the loop writes Z; a naive string is treated as UTC,
        d = d.replace(tzinfo=datetime.timezone.utc)   # never as local time
    return d.timestamp()


def ret_bps(mid_t, mid_h):
    return 1e4 * math.log(mid_h / mid_t)


def label(bps):
    """up / down / flat with the +-DEAD_BAND_BPS band. Exactly +-5 is a move:
    config says |ret| BELOW the band is flat."""
    if bps >= DEAD_BAND_BPS:
        return "up"
    if bps <= -DEAD_BAND_BPS:
        return "down"
    return "flat"


def outcome(mid_t, mid_h):
    r = ret_bps(mid_t, mid_h)
    return {"mid_h": mid_h, "ret_h_bps": r, "label": label(r), "absence": None}


def _ms(x):
    """Whole milliseconds: ts_rx carries three decimals, and a tie judged on binary float
    distances went to the LATER row about a quarter of the time (2026-09-28, review)."""
    return int(round(x * 1000.0))


def priced_points(rows):
    """(times, mids) of every row with a mid, sorted by ts_rx: the candidates of the join."""
    pts = sorted(((t, r["mid"]) for r in rows
                  if _num(r.get("mid")) and (t := ts_epoch(r.get("ts_rx"))) is not None),
                 key=lambda p: p[0])                 # by time only: two rows can share a ts_rx
    return [p[0] for p in pts], [p[1] for p in pts]


def pick(times, t, horizon_s=config.HORIZON_S):
    """The index in `times` (sorted epochs of the priced rows) of the row the join takes for a
    decision at `t`: the one nearest t + h within [t + h - JOIN_TOL_S, t + h + JOIN_TOL_S], strictly
    after t, ties (in whole milliseconds) to the earlier row; None when the window is empty. The one
    rule, used by join() and by report.realised_horizon(), so the health line measures the horizon
    the join actually realised."""
    target = t + horizon_s
    i, best, best_d = bisect.bisect_left(times, target - JOIN_TOL_S), None, None
    while i < len(times) and times[i] <= target + JOIN_TOL_S:
        d = abs(_ms(times[i]) - _ms(target))
        if times[i] > t and (best is None or d < best_d):   # strict <: a tie keeps the earlier row
            best, best_d = i, d
        i += 1
    return best


def rank(r):
    """Which row speaks for a tick_id when two share it (a launchd double-fire, a `make dry`
    between two live ticks): the live decision first (mode live, absence null), then any other
    priced row, then an unpriced one. A lower rank wins; equal ranks keep the FIRST row in file
    order. Before 2026-09-28 a later priced row replaced an earlier row's gap, so a dry row
    written 35 s into the minute could score the live decision against a mid up to t + 16 min
    from its own, shifted window (SPEC §11: never a row outside it)."""
    if not _num(r.get("mid")):
        return 2
    return 0 if r.get("mode") == "live" and r.get("absence") is None else 1


def join(rows, horizon_s=config.HORIZON_S):
    """{tick_id: outcome}. For each row at t with a mid, the priced row whose ts_rx is
    nearest t+h, within [t+h-JOIN_TOL_S, t+h+JOIN_TOL_S] (ties: the earlier), gives
    mid_h; anything else is the GAP outcome. A row without a mid (absence before the
    feed) is a gap itself and never a candidate, so an absence row at t+h does not
    hide the priced row one second behind it. Two rows with one tick_id: rank() says
    which one's outcome is the tick's."""
    times, mids = priced_points(rows)
    out, ranks = {}, {}
    for r in rows:
        tid, t, mid_t = r.get("tick_id"), ts_epoch(r.get("ts_rx")), r.get("mid")
        o = dict(GAP)
        if t is not None and _num(mid_t):
            best = pick(times, t, horizon_s)
            if best is not None:
                o = outcome(mid_t, mids[best])
        k = rank(r)
        if tid not in out or k < ranks[tid]:         # a better-ranked row speaks for the tick; equal keeps the first
            out[tid], ranks[tid] = o, k
    return out


def load(path, bad=None):
    """Rows of a decisions.jsonl, file order. A line that is not a JSON object
    carrying string tick_id and ts_rx is skipped: the log is append-only and a
    crash mid-write leaves one truncated line, which must cost one row, not
    the report. Pass a list as `bad` to receive (line_no, reason) per skip;
    blank lines are neither rows nor errors. A missing file raises: "0 rows"
    from a wrong path would be a silent failure."""
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except (ValueError, RecursionError) as e:          # a line nested past the parser's depth is garbage too
                # A torn line (a crash or a full disk mid-write) with the next whole row appended onto
                # it: the tail from the last row start parses on its own, and that row was written in
                # full, so it is kept and only the torn head is the skip; when the head parses too the
                # line is whole rows that lost their newlines, and every one is kept (2026-09-28;
                # cycle.write_row now also starts a fresh line after a torn one, so this recovers the
                # older cases). One skip entry per line, saying what was kept and what was not a row.
                found = _glued(line)
                kept = [x for x, rescued in found if _not_row(x) is None and (not rescued or _writer_row(x))]
                if bad is not None:
                    extra = len(found) - len(kept)
                    bad.append((n, f"json: {e}" + _glued_note(len(kept))
                                + (f"; {extra} parsed object(s) on it not a row" if extra else "")))
                rows.extend(kept)
                continue
            why = _not_row(r)
            if why is not None:
                if bad is not None:
                    bad.append((n, why))
                continue
            rows.append(r)
    return rows


def _not_row(r):
    """None when `r` is a row a reader's clock can use; else the reason it is not one."""
    if not (isinstance(r, dict) and isinstance(r.get("tick_id"), str) and isinstance(r.get("ts_rx"), str)):
        return "not a row: needs tick_id and ts_rx"
    if not _TICK.match(r["tick_id"]) or _tick_ok(r["tick_id"]) is None or ts_epoch(r["ts_rx"]) is None:
        return "not a row: tick_id is not YYYYMMDDTHHMMSSZ or ts_rx is not a time"   # a string that is not a minute would crash every reader's clock
    return None


def _glued_note(k):
    """What a glued line's skip entry says was kept (bin/readers-diff counts the lines saying "kept")."""
    if k == 0:
        return ""
    if k == 1:
        return "; the whole row appended onto the torn line is kept"
    if k == 2:
        return "; two whole rows on one line (a lost newline), both kept"
    return f"; {k} whole rows on one line (lost newlines), all kept"


_DECODER = json.JSONDecoder()
WRITER_KEYS = ("venue", "product", "cadence_s", "horizon_s")   # in every row cycle.new_row writes; in no Jev answer


def _writer_row(r):
    """A rescued piece must carry the writer's own keys: a row start can sit inside a row (an answer
    kept verbatim may hold an object whose first key is "v"), and such a nested object is never a row."""
    return isinstance(r, dict) and all(k in r for k in WRITER_KEYS)


def _glued(line):
    """[(value, rescued)] for a line that is not one JSON value. First forward from its start: whole
    values one after another (rows that lost only their newlines), each found where the previous one
    ended, so nothing nested inside a row can surface here. Where a value does not parse (a torn
    row), the whole rows after it are rescued from the right: each from a row start whose value ends
    exactly where the next rescued piece (or the line) begins, and each must carry the writer's keys
    (_writer_row), so an object nested in the torn row is never taken for a row. raw_decode reads
    each piece once, and a depth past the parser's limit is a failed piece, not an exception. Each
    value is then read as a row only if _not_row says so."""
    out, pos, end = [], 0, len(line.rstrip())
    while True:
        while pos < end and line[pos].isspace():
            pos += 1
        if pos >= end:
            return [(v, False) for v in out]
        try:
            v, pos = _DECODER.raw_decode(line, pos)
        except (ValueError, RecursionError):
            break
        out.append(v)
    rescued, right, hi = [], end, end
    while True:
        i = line.rfind(ROW_START, pos + 1, hi)
        if i <= pos:
            break
        hi = i + len(ROW_START) - 1                             # the next candidate starts left of this one
        try:
            v, stop = _DECODER.raw_decode(line, i)
        except (ValueError, RecursionError):
            continue
        if line[stop:right].strip() == "" and _writer_row(v):
            rescued.insert(0, v)
            right = i
    return [(v, False) for v in out] + [(v, True) for v in rescued]

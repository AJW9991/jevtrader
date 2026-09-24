"""The t+h join: what the log recorded a horizon after each decision, and the
reader for the log itself.

May: read data/decisions.jsonl line by line, and pair each row at t with the
first row whose ts_rx falls in [t+h, t+h+90 s].
May not: fetch anything, back-fill anything, or ever hand back a row outside
that window. A missing row is `gap`, never the nearest one: a wrong row would
score a decision against a price it was not made about.

The 90 s slack is one cadence (60 s) plus half a cadence. The tick's own
watchdog is 50 s, so a late tick lands under 50 s after its minute; 90 admits
the next tick even when both t and t+h slipped, and a 20-minute outage can
never match. Everything here is forward-only: t sees t+h, never the reverse.
"""
import bisect, datetime, json, math

from loop import config

JOIN_SLACK_S = 90.0
DEAD_BAND_BPS = config.DEAD_BAND_BPS   # |ret| below this is "flat"; at the band it is a move
GAP = {"mid_h": None, "ret_h_bps": None, "label": None, "absence": "gap"}


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


def join(rows, horizon_s=config.HORIZON_S):
    """{tick_id: outcome}. For each row at t with a mid, the FIRST row (by
    ts_rx) with a mid whose ts_rx is in [t+h, t+h+JOIN_SLACK_S] gives mid_h;
    anything else is the GAP outcome. A row without a mid (absence before the
    feed) is a gap itself and is skipped as a candidate, so an absence row at
    t+h does not hide the priced row one second behind it."""
    pts = sorted((t, r.get("mid")) for r in rows if (t := ts_epoch(r.get("ts_rx"))) is not None)
    times = [p[0] for p in pts]
    out = {}
    for r in rows:
        tid, t, mid_t = r.get("tick_id"), ts_epoch(r.get("ts_rx")), r.get("mid")
        o = dict(GAP)
        if t is not None and _num(mid_t):
            lo, hi = t + horizon_s, t + horizon_s + JOIN_SLACK_S
            i = bisect.bisect_left(times, lo)
            while i < len(times) and times[i] <= hi:
                if _num(pts[i][1]):
                    o = outcome(mid_t, pts[i][1])
                    break
                i += 1
        if tid not in out or out[tid]["absence"] is not None:   # two rows one minute: keep the priced one
            out[tid] = o
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
            except ValueError as e:
                if bad is not None:
                    bad.append((n, f"json: {e}"))
                continue
            if not (isinstance(r, dict) and isinstance(r.get("tick_id"), str)
                    and isinstance(r.get("ts_rx"), str)):
                if bad is not None:
                    bad.append((n, "not a row: needs tick_id and ts_rx"))
                continue
            rows.append(r)
    return rows

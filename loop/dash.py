"""loop/dash.py -- one HTML page of the loop's HEALTH, built from the log, the nightly's tables,
the heartbeat, HALT, prompts/CURRENT and PREREG §11.

    python3 -m loop.dash [--log FILE] [--t0 YYYY-MM-DDTHH:MM|tick_id] [--no-t0] [--prereg FILE]
                         [--data DIR] [--proposals DIR] [--prompts DIR] [--out data/dash.html]

Health only, by construction (PREREG §8.4): the page is report §1-§3 (health, the per-day
stop-rule-3 table, occupancy, test-retest) plus what those already imply -- a ticks-per-hour
strip that shows every gap, the 81-state occupancy map, spend per day -- and the nightly's
own summary lines from proposals/*.md (synthetic states, never an outcome). It calls
report.health, report.days_table, report.occupancy and report.retest and nothing that
replays a book, joins a return to an answer or prints a confidence table (the report module
it imports holds that code, but no name of it is used here), so no H1, H2, pair, calibration
or confidence number can appear by accident; tests/test_dash.py holds every `report.<name>`
in this file to an allowlist.
Standard library only; the page carries no script and loads nothing from the network, so
it can be opened from a file and shared without reaching for anything."""
import argparse, collections, datetime, glob, html, math, os, re, sys

from . import config, outcomes, report, state

T0_RE = re.compile(r"T0 \(first tick_id of day 1\): `(\d{8}T\d{6}Z)`")   # PREREG §11's sealed line
PREREG_PATH = os.path.join(config.REPO, "PREREG.md")   # the repository's PREREG, read at call time (tests pin a fixture)
PROPOSAL_HEAD = re.compile(r"requests: (\d+), answered: (\d+), errors: (\d+)")
PROPOSAL_NAME = re.compile(r"^(cand_\d+)\n")
PROPOSAL_COUNTS = re.compile(r"^differs from CURRENT on (\d+) of (\d+) answered states; from rule_c on (\d+) of (\d+)", re.M)
CURRENT_CAND = re.compile(r"^## current \((v\d+)\)\n\ndiffers from rule_c on (\d+) of (\d+)", re.M)
HOURS = 24
DAY_TICKS = report.DAY_TICKS
SEQ = ("#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281")     # dataviz reference ramp, steps 250..650, light->dark
SEQ_DARK = ("#86b6ef", "#5598e7", "#3987e5", "#256abf", "#184f95")   # on the dark surface: no darker than step 600
RULE_MARK = {"buy": "B", "sell": "S", "hold": "H"}


def _esc(x):
    return html.escape("" if x is None else str(x), quote=True)


def _pc(x, nd=1):
    return "n/a" if x is None else f"{100.0 * x:.{nd}f}%"


def _bin(n, top):
    """0 -> -1 (empty); else 0..4 by share of `top`, so a full hour and a full cell read darkest."""
    if not n:
        return -1
    if top <= 0:
        return 4
    return min(4, int(5 * n / top - 1e-9))


def _bin_state(n, top):
    """The 81-state map's bin: state occupancy is heavy-tailed (one state can hold a quarter of
    the rows), so linear fifths of the busiest cell put every other cell in the lightest bin.
    Bins by share of `top`: >= 50% -> 4, >= 20% -> 3, >= 5% -> 2, >= 1% -> 1, > 0 -> 0, 0 -> -1."""
    if not n:
        return -1
    if top <= 0:
        return 4
    x = n / top
    return 4 if x >= 0.5 else 3 if x >= 0.2 else 2 if x >= 0.05 else 1 if x >= 0.01 else 0


def read_t0(prereg=None):
    """PREREG §11's T0 line as epoch seconds, or None before sealing. report.main, status and
    inference read it here (report.py itself opens no file, by test). `prereg` None is the
    repository's own, PREREG_PATH, looked up at call time."""
    try:
        with open(prereg or PREREG_PATH, encoding="utf-8") as fh:
            m = T0_RE.search(fh.read())
    except OSError:
        return None
    return report.tick_epoch(m.group(1)) if m else None


def heartbeat(path=None):
    try:
        with open(path or config.HEARTBEAT) as fh:                  # resolved now, not at import: tests patch config
            return fh.read().strip() or None
    except OSError:
        return None


def hourly(rows):
    """(day, hour) -> distinct PRICED ticks (a row with a mid: the feed answered), so a feed
    outage or a HALT stretch draws as the gap it is; the absence rows of the hour are counted
    beside them in absent(). Until 2026-09-28 every row with a tick_id counted, so two hours of
    feed absences drew as two full hours."""
    c = collections.defaultdict(set)
    for r in rows:
        t = str(r.get("tick_id"))
        if len(t) >= 11 and report._num(r.get("mid")):
            c[(t[:8], int(t[9:11]))].add(t)
    return {k: len(v) for k, v in c.items()}


def absent(rows):
    """(day, hour) -> Counter of absence reasons over the hour's rows."""
    c = collections.defaultdict(collections.Counter)
    for r in rows:
        t = str(r.get("tick_id"))
        if len(t) >= 11 and r.get("absence"):
            c[(t[:8], int(t[9:11]))][r["absence"]] += 1
    return c


def ahead(rows, now):
    """(day, hour) keys, as hourly() and absent() make them, of every row stamped after `now` (a
    datetime): a clock stepped forward. Any row, priced or an absence. A tick_id sorts as its time
    (SPEC: YYYYMMDDTHHMMSSZ), so it is compared with `now` in that form; a row stamped in the
    minute under way is not after it."""
    cut = now.strftime("%Y%m%dT%H%M%SZ")
    out = set()
    for r in rows:
        t = str(r.get("tick_id"))
        if len(t) >= 11 and t > cut:
            out.add((t[:8], int(t[9:11])))
    return out


def _bin_hour(n):
    """The strip's bin by SHORTFALL from a full hour: 60 -> 4 (darkest), 55-59 -> 3, 45-54 -> 2,
    30-44 -> 1, 1-29 -> 0, 0 -> -1 (empty). Fifths of 60 read 49 and 60 the same, and an hour
    short eleven minutes (about 15% of a day's stop-rule budget) looked full."""
    if n <= 0:
        return -1
    return 4 if n >= 60 else 3 if n >= 55 else 2 if n >= 45 else 1 if n >= 30 else 0


def _hour_cell(n, start, now, late=False):
    """(css class, title tail) of the strip's cell for the UTC hour beginning at epoch `start`, with
    `n` priced ticks, at render time `now` (epoch). An hour over is binned by _bin_hour. Only an hour
    not begun that holds no row is 'not yet' (a dashed cell), never a gap; an hour that has begun
    never is. The hour in progress reads n of the minutes begun, and bins by its shortfall from the
    minutes over, so the minute under way (its row may not be written yet) is no shortfall; with no
    priced tick it is an empty cell, and in its first minute it reads 0/1, as today's label counts
    that minute (until the evening of 2026-09-28 an hour begun under a minute before the render with
    no priced tick was 'not yet', so a HALT hour rendered at 10:00:20, its 10:00 row an absence,
    drew dashed instead of as the gap it is). An hour holding a row stamped after the clock (`late`,
    from ahead(): a clock stepped forward), priced or an absence, is drawn as logged, n of 60, like
    an hour over, so its count is never above its denominator (sixty such rows read '60/45 so far'
    at 09:44, and two absence rows at 15:00 read 'not yet', until the evening of 2026-09-28). Until
    2026-09-28 every hour of today drew as a full hour, so the hours after the render read 0/60 like
    an outage."""
    if now >= start + 3600 or late or (now < start and n):
        b = _bin_hour(n)
        return "cell" + (f" b{b}" if b >= 0 else ""), f"{n}/60 priced ticks"
    if now < start:                                                      # not begun, and no row in it
        return "cell future", "not yet"
    begun = int((now - start) // 60) + 1
    b = _bin_hour(60 - max(0, begun - 1 - n)) if n else -1
    return "cell" + (f" b{b}" if b >= 0 else ""), f"{n}/{begun} priced ticks so far, the hour in progress"


def spend_by_day(rows, t0=None, over=None):
    """day label -> dollars: the input tokens the rows logged, at config.USD_PER_MTOK. A count past a
    float's range is left out (report._num). A day whose counts, each in range, sum past it is left out
    too, and its label goes on `over` (a list) when one is given, so the page can name it: until
    2026-09-28 two rows of int(1e308) on one day raised OverflowError here and the page was not built,
    and until the evening of that day two float counts of 1e308 (or an int and a float) summed to inf
    without raising, were charted as inf, named nowhere, and the page died drawing that bar; and until
    later that evening two int counts whose sum passed a float's range, then a float count on the same
    day, raised OverflowError in the adding itself (int + float), as report.health did before 64aaa4e."""
    c, past = collections.Counter(), set()
    for r in rows:
        j = r.get("jev")
        tok = j.get("input_tokens") if isinstance(j, dict) else None     # a foreign row's jev may not be a dict
        if report._num(tok) and tok > 0:                                     # a count past a float's range is not charted
            d = report.day_of(r.get("tick_id"), t0)
            if d in past:
                continue
            try:
                c[d] += tok
            except OverflowError:                                            # an int sum past a float's range meets a float
                past.add(d)
                del c[d]
    out = {}
    for d, t in c.items():
        try:
            usd = t * config.USD_PER_MTOK / 1e6                              # an int sum becomes a float here
        except OverflowError:                                                # an int sum past a float's range raises
            usd = None
        if report._num(usd):
            out[d] = usd
        else:                                                                # a float sum past it is inf, and raises nothing
            past.add(d)
    if over is not None:
        over.extend(sorted(past))
    return out


def latency_by_day(rows, t0=None):
    """day label -> (mean ms, p95 ms, n) over the rows with a latency (report §1's numbers, per day)."""
    by = collections.defaultdict(list)
    for r in rows:
        j = r.get("jev")
        ms = j.get("latency_ms") if isinstance(j, dict) else None
        if report._num(ms):
            by[report.day_of(r.get("tick_id"), t0)].append(ms)
    return {d: (report._mean(v), report._p95(v), len(v)) for d, v in by.items()}


def absence_by_day(rows, t0=None):
    """day label -> Counter of absence reasons (report §1's absence line, per day)."""
    by = collections.defaultdict(collections.Counter)
    for r in rows:
        if r.get("absence"):
            by[report.day_of(r.get("tick_id"), t0)][r["absence"]] += 1
    return by


GAP_MIN = 3             # a hole of at least this many missing minutes is listed; a single missing minute is the table's
                        # isolated skip (report §1 counts holes of exactly one minute); a 2-minute hole shows in neither
GAPS_SHOWN = 10


def gaps(rows, t0=None, min_minutes=GAP_MIN):
    """Holes in the tick sequence of at least min_minutes missing minutes, longest first: the
    first missing tick_id, the next row's, the minutes missing, the day label of the first
    missing minute. From tick_ids alone. The per-day table's `skipped min` counts the isolated
    single skips only, so a 200-minute hole read 0 there."""
    ticks = sorted({r["tick_id"] for r in rows if isinstance(r.get("tick_id"), str)})
    out = []
    for a, b in zip(ticks, ticks[1:]):
        gap = int((report.tick_epoch(b) - report.tick_epoch(a)) // config.CADENCE_S) - 1
        if gap >= min_minutes:
            first = report.tick_epoch(a) + config.CADENCE_S
            out.append({"from": report._tick_of(first), "to": b, "minutes": gap, "day": report.day_of(report._tick_of(first), t0)})
    out.sort(key=lambda g: (-g["minutes"], g["from"]))
    return out


def state_counts(rows):
    c = collections.Counter()
    for r in rows:
        a = r.get("adj")
        if isinstance(a, dict) and all(a.get(d) in state.ALPHABET[d] for d in state.DIMS):
            c[(a["liq"], a["flow"], a["trend"], a["vol"])] += 1
    return c


def proposals(root=None):
    """One dict per proposals/<date>.md: the nightly's own header and per-candidate lines."""
    out = []
    for path in sorted(glob.glob(os.path.join(root or config.PROPOSALS, "????-??-??.md"))):
        try:
            with open(path, encoding="utf-8") as fh:
                txt = fh.read()
        except OSError:
            continue
        head = PROPOSAL_HEAD.search(txt)
        cur = CURRENT_CAND.search(txt)
        cands = []
        for sec in txt.split("\n## ")[1:]:                        # one section per candidate: a regex cannot span two
            name, counts = PROPOSAL_NAME.match(sec), PROPOSAL_COUNTS.search(sec)
            if name and counts:                                       # the rationale between them may run to any length
                cands.append({"name": name.group(1), "vs_current": int(counts.group(1)), "of": int(counts.group(2)),
                              "vs_rule": int(counts.group(3))})
        out.append({"date": os.path.basename(path)[:-3],
                    "requests": int(head.group(1)) if head else None, "answered": int(head.group(2)) if head else None,
                    "errors": int(head.group(3)) if head else None,
                    "current": cur.group(1) if cur else None, "current_vs_rule": int(cur.group(2)) if cur else None,
                    "current_of": int(cur.group(3)) if cur else None, "candidates": cands})
    return out


def current_version(root=None):
    try:
        with open(os.path.join(root or config.PROMPTS, "CURRENT")) as fh:
            return fh.read().strip()
    except OSError:
        return None


# ---- the page ------------------------------------------------------------------------------
CSS = """
:root { color-scheme: light dark; --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7;
        --good:#0ca30c; --warn:#fab219; --crit:#d03b3b; --s1:#86b6ef; --s2:#5598e7; --s3:#2a78d6; --s4:#1c5cab; --s5:#104281; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781; --grid:#2c2c2a; --axis:#383835;
  --s1:#86b6ef; --s2:#5598e7; --s3:#3987e5; --s4:#256abf; --s5:#184f95; } }
:root[data-theme="dark"] { --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781; --grid:#2c2c2a; --axis:#383835;
  --s1:#86b6ef; --s2:#5598e7; --s3:#3987e5; --s4:#256abf; --s5:#184f95; }
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px 48px; background:var(--page); color:var(--ink);
       font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; font-variant-numeric: tabular-nums; }
main { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 20px; margin: 0 0 4px; font-weight: 600; }
h2 { font-size: 15px; margin: 28px 0 10px; font-weight: 600; }
.sub { color: var(--ink2); margin: 0 0 16px; }
.badge { display:inline-block; padding:1px 8px; border-radius: 10px; font-size: 12px; font-weight:600; vertical-align: middle; }
.badge.ok { background: var(--good); color:#0b0b0b; } .badge.warn { background: var(--warn); color:#0b0b0b; } .badge.crit { background: var(--crit); color:#fff; }
.tiles { display:grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.tile { background: var(--surface); border: 1px solid var(--grid); border-radius: 8px; padding: 10px 12px; }
.tile .k { color: var(--ink2); font-size: 12px; } .tile .v { font-size: 22px; font-weight: 600; margin-top: 2px; }
.tile .n { color: var(--muted); font-size: 12px; } .tile.crit .v { color: var(--crit); }
table { border-collapse: collapse; background: var(--surface); border: 1px solid var(--grid); border-radius: 8px; width: 100%; }
th, td { padding: 6px 10px; text-align: right; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th { color: var(--ink2); font-weight: 500; font-size: 12px; } td:first-child, th:first-child { text-align: left; }
tr:last-child td { border-bottom: 0; } td.l, th.l { text-align: left; white-space: normal; }
.wrap { overflow-x: auto; }
.strip { display: grid; grid-template-columns: 150px repeat(24, minmax(14px, 1fr)); gap: 2px; align-items: center; min-width: 560px; }
.strip .lab { color: var(--ink2); font-size: 12px; text-align: right; padding-right: 8px; white-space: nowrap; }
.strip .lab b { font-weight: 600; color: var(--ink); }
.strip .hr { color: var(--muted); font-size: 10px; text-align: center; }
.cell { height: 18px; border-radius: 3px; background: var(--surface); border: 1px solid var(--grid); }
.cell.future, .sw.future { background: transparent; border: 1px dashed var(--axis); }
.b0 { background: var(--s1); border-color: var(--s1); } .b1 { background: var(--s2); border-color: var(--s2); }
.b2 { background: var(--s3); border-color: var(--s3); } .b3 { background: var(--s4); border-color: var(--s4); } .b4 { background: var(--s5); border-color: var(--s5); }
.legend { color: var(--ink2); font-size: 12px; margin-top: 8px; display:flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.sw { display:inline-block; width: 14px; height: 14px; border-radius: 3px; vertical-align: -2px; margin-right: 3px; border: 1px solid var(--grid); }
.sw.out { background: var(--muted); border-color: var(--muted); }
.bar { display:flex; height: 22px; border-radius: 4px; overflow: hidden; gap: 2px; background: var(--page); }
.bar span { display:block; height: 100%; } .bar span.out { background: var(--muted); }
.occ { display:grid; grid-template-columns: 60px 1fr; gap: 6px 12px; align-items: center; }
.occ .lab { color: var(--ink2); font-size: 12px; text-align: right; }
.occ .words { color: var(--ink2); font-size: 12px; grid-column: 2; margin-top: -2px; margin-bottom: 6px; }
.map { display: grid; grid-template-columns: 120px repeat(9, minmax(44px, 1fr)); gap: 3px; min-width: 560px; }
.map .rl { color: var(--ink2); font-size: 11px; text-align: right; padding-right: 6px; line-height: 1.1; }
.map .cl { color: var(--muted); font-size: 10px; text-align: center; line-height: 1.1; }
.map .c { height: 34px; border-radius: 4px; background: var(--surface); border: 1px solid var(--grid); position: relative; }
.map .c.b0 { background: var(--s1); border-color: var(--s1); } .map .c.b1 { background: var(--s2); border-color: var(--s2); }
.map .c.b2 { background: var(--s3); border-color: var(--s3); } .map .c.b3 { background: var(--s4); border-color: var(--s4); }
.map .c.b4 { background: var(--s5); border-color: var(--s5); }   /* .map .c outranks a bare .bN: without these the map was never coloured */
.map .c i { position: absolute; left: 4px; top: 2px; font: 10px/1 monospace; color: var(--muted); font-style: normal; }
.map .c b { position: absolute; right: 4px; bottom: 2px; font-size: 11px; font-weight: 500; color: var(--ink2); }
.map .c.b0 i, .map .c.b1 i, .map .c.b2 i, .map .c.b0 b, .map .c.b1 b, .map .c.b2 b { color: #0b0b0b; }
.map .c.b3 i, .map .c.b4 i, .map .c.b3 b, .map .c.b4 b { color: #fff; }
.mb { display:inline-block; width: 46px; height: 8px; background: var(--grid); border-radius: 4px; vertical-align: middle; margin-right: 6px; overflow: hidden; }
.mb i { display:block; height: 100%; background: var(--s3); } .mb.crit i { background: var(--crit); } .mb.warn i { background: var(--warn); }
.vb { display:flex; align-items: flex-end; gap: 3px; height: 90px; margin: 0 0 22px; position: relative; border-bottom: 1px solid var(--axis); }
.vbc { flex: 1 1 0; min-width: 6px; height: 100%; display:flex; flex-direction: column; justify-content: flex-end; position: relative; }
.vbar { background: var(--s3); border-radius: 2px 2px 0 0; } .vbar.crit { background: var(--crit); }
.vbl { position: absolute; top: 100%; left: 0; right: 0; text-align: center; color: var(--muted); font-size: 10px; padding-top: 3px; white-space: nowrap; overflow: hidden; }
.days { display:grid; grid-template-columns: repeat(28, minmax(10px, 1fr)); gap: 3px; }
.days .d { height: 22px; border-radius: 3px; border: 1px solid var(--grid); background: var(--surface); font-size: 9px; color: var(--muted); text-align: center; line-height: 22px; }
.days .d.ok { background: var(--good); border-color: var(--good); color: #0b0b0b; } .days .d.bad { background: var(--crit); border-color: var(--crit); color: #fff; }
.days .d.open { background: var(--warn); border-color: var(--warn); color: #0b0b0b; } .days .d.empty { background: var(--muted); border-color: var(--muted); color: #fff; }
.foot { color: var(--muted); font-size: 12px; margin-top: 32px; border-top: 1px solid var(--grid); padding-top: 10px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
@media (max-width: 700px) { .strip { grid-template-columns: 110px repeat(24, minmax(12px, 1fr)); } .map { grid-template-columns: 70px repeat(9, minmax(40px, 1fr)); } .map .c { height: 26px; } }
"""


def _tile(k, v, n="", cls=""):
    return f'<div class="tile{" " + cls if cls else ""}"><div class="k">{_esc(k)}</div><div class="v">{_esc(v)}</div><div class="n">{_esc(n)}</div></div>'


def _age(hb, now):
    if not hb:
        return None
    try:
        t = datetime.datetime.strptime(hb[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    return max(0.0, (now - t).total_seconds())          # a heartbeat ahead of the clock (a clock step) is "just now", never negative


def _mbar(x, crit_below=None, warn_below=None):
    """A 46 px mini bar for a share in [0, 1], crit (red) below a threshold."""
    if x is None:
        return ""
    cls = " crit" if crit_below is not None and x < crit_below else " warn" if warn_below is not None and x < warn_below else ""
    return f"<span class='mb{cls}'><i style='width:{100 * min(1.0, max(0.0, x)):.1f}%'></i></span>"


def _vbars(items, top, label_every=1):
    """Vertical bars, CSS only: items = [(label, value, title, crit)], heights as a share of `top`. The
    share is taken before the percent, and a value that is no finite number draws no bar: 100 * v was
    inf for a latency p95 of 1e308 (a value report._num accepts), and until the evening of 2026-09-28
    the page died on it. The share is then held to [0, 1] and a share that is no finite number draws no
    bar either: a negative value (a foreign or hand-edited log; the loop measures latency with a
    monotonic clock) made 100 * (v / top) -inf, or v / top inf when the top itself was negative
    (round-4c checker), and the page died the same way; a top that is not above zero draws no bar at
    all. The title still gives the value."""
    out = ["<div class='vb'>"]
    for i, (lab, v, title, crit) in enumerate(items):
        share = v / top if report._num(v) and report._num(top) and top > 0 else None
        h = max(2, int(round(100 * min(share, 1.0)))) if share is not None and math.isfinite(share) and share >= 0 else 0
        out.append(f"<div class='vbc' title='{_esc(title)}'><div class='vbar{' crit' if crit else ''}' style='height:{h}%'></div>"
                   f"<div class='vbl'>{_esc(lab) if i % label_every == 0 else ''}</div></div>")
    out.append("</div>")
    return "".join(out)


def _short(day):
    """A day label for a bar: 'd07' -> '07', '20260927' -> '27'."""
    return day[1:] if day.startswith("d") else day[6:]


STRIP_DAYS = 35         # the strip's window: the 28-day sample and a week, ending today
STRIP_LOOKBACK_DAYS = 365   # a row this close before the window: the loop ran before it (a reset clock lands years back)


def _calendar_run(days, now, max_days=STRIP_DAYS):
    """(the strip's days, the logged days older than its window). `days` are sorted YYYYMMDD labels.
    The window is the `max_days` calendar days ending TODAY, and a day in it with no row at all (the
    Mac off, or the loop stopped while the nightly still rebuilds this page) is drawn as 24 empty
    cells rather than left out. The strip starts at the window's floor when the log has no row inside
    the window (an outage still under way, of any length, is the whole window empty) or when its last
    row before the window falls within 365 days of the floor (the loop ran before the window, so each
    empty day in it is a gap, however long the outage that ended inside it). Otherwise it starts at
    the first logged day inside the window: the only rows before it are more than a year older, a
    clock stepped back to 1970 or 2001, and they are counted (the second list), not filled up to. A
    clock stepped back by less than a year pads the window with at most its own empty days. A logged
    day after `now` (a clock stepped forward) is drawn as a line of its own."""
    if not days:
        return [], []
    today = now.date()
    day = lambda d: datetime.date(int(d[:4]), int(d[4:6]), int(d[6:]))
    past = [d for d in days if day(d) <= today]
    floor = today - datetime.timedelta(days=max_days - 1)
    recent = [d for d in past if day(d) >= floor]
    older = [d for d in past if day(d) < floor]
    run = []
    if past:
        # until 2026-09-28 the lookback was 7 days: a loop that ran until 08-19 and came back on 09-30
        # drew 09-30 alone, and the 34 empty days it drew the evening before vanished with one row
        ran_before = bool(older) and day(older[-1]) >= floor - datetime.timedelta(days=STRIP_LOOKBACK_DAYS)
        a = floor if ran_before or not recent else day(recent[0])
        run = [(a + datetime.timedelta(days=i)).strftime("%Y%m%d") for i in range((today - a).days + 1)]
    return run + [d for d in days if day(d) > today], older


def render(rows, outs, t0=None, now=None, hb=None, halt=False, props=(), current=None, log=None, bad=()):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    sample = report.in_sample(rows, t0) if t0 is not None else rows
    # the whole log's last tick REACHED on this clock, as status and report --health take it: a row stamped
    # after the clock (a clock stepped forward) is not a row yet, and after the sample the days_table drops
    # a `last` past the clock, so the whole log's max tick left d28 open on the dash alone (round-4c checker)
    last = report.last_reached(rows, now.timestamp())
    h_all = report.health(rows, outs, now=now.timestamp())
    h = report.health(sample, outs, bad, t0=t0, last=last, now=now.timestamp())   # bad: the log's skipped lines, as report --health counts them                # last: the sample's last day closes on rows after the cut
    occ = report.occupancy(sample)
    rt = report.retest(sample)
    age = _age(hb, now)
    day_n = None
    if t0 is not None:
        day_n = int((now.timestamp() - t0) // 86400) + 1
        day_n = "not started" if day_n < 1 else f"{report.SAMPLE_DAYS} of {report.SAMPLE_DAYS} (ended)" if day_n > report.SAMPLE_DAYS else f"{day_n} of {report.SAMPLE_DAYS}"
    cov_since = None
    if t0 is not None and now.timestamp() > t0:
        cov_since = min(1.0, h["priced"] / max(1.0, (min(now.timestamp(), t0 + report.SAMPLE_DAYS * 86400) - t0) / config.CADENCE_S))
    spend_over = []                                                      # days whose summed tokens are past a float's range
    spend = spend_by_day(rows, t0, over=spend_over)
    usd_all = h_all.get("usd")                                           # a whole-log sum past a float's range may come back as no number
    lat = latency_by_day(sample, t0)
    abs_day = absence_by_day(sample, t0)
    days_seen = sorted({d["day"] for d in h_all["days"]})
    strip_days, strip_older = _calendar_run(days_seen, now)
    hourly_c, absent_c = hourly(rows), absent(rows)
    late = ahead(rows, now)                                              # hours holding a row stamped after the clock
    late_days = {d for d, _ in late}
    sc = state_counts(sample)
    top_state = max(sc.values()) if sc else 0
    decided_live = sum(d["live"] for d in h["days"])                  # stop-rule fill: live rows whose t + h the log has reached
    decided_filled = sum(d["filled"] for d in h["days"])
    rule_fill = decided_filled / decided_live if decided_live else None
    stamp = now.strftime("%H:%MZ")

    # -- header: the page is static and rebuilt once a night, so every age is "at render"
    if halt:
        status = '<span class="badge crit">HALT present: nothing is sent</span>'
    elif age is None:
        status = f'<span class="badge warn">at render {stamp}: no heartbeat</span>'
    elif age > 3 * config.CADENCE_S:
        status = f'<span class="badge crit">at render {stamp}: last tick {age / 60:.0f} min before</span>'
    else:
        status = f'<span class="badge ok">at render {stamp}: last tick {age:.0f} s before</span>'
    parts = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>",
             "<title>JevTrader health</title>", f"<style>{CSS}</style></head><body><main>",
             f"<h1>JevTrader &middot; paper loop health {status}</h1>",
             f"<p class='sub'>{_esc(config.VENUE)} {_esc(config.PRODUCT)}, one tick a minute, horizon {config.HORIZON_S // 60} min &middot; "
             f"rendered {now.strftime('%Y-%m-%d %H:%MZ')}" + (f" &middot; heartbeat {_esc(hb)}" if hb else "")
             + (f" &middot; T0 {report._iso_minute(t0)}" if t0 is not None else " &middot; no T0: whole log")
             + (f" &middot; prompt_b {_esc(current)}" if current else "") + "</p>"]

    # -- tiles (sample)
    hz = h["horizon"]
    keys = h["keys"]
    key_txt = ", ".join(f"{k.split(':')[-1].split('/')[-1]} {v}" for k, v in sorted(keys.items())) or "none"
    tiles = [_tile("sample day", day_n or "-", "days from T0" if t0 is not None else "no T0"),
             _tile("ticks in sample", f"{h['ticks']:,}", f"{h_all['ticks']:,} in the whole log"),
             _tile("coverage since T0", _pc(cov_since), "priced ticks per minute elapsed"),
             _tile("stop-rule fill", _pc(rule_fill), f"{decided_filled}/{decided_live} live rows decided; {_pc(h['fill'])} of {h['priced']} priced ticks",
                   "crit" if rule_fill is not None and rule_fill < report.BAD_FILL else ""),
             _tile("jev errors", _pc(h["error_rate"]), f"{sum(h['errors'].values())}/{h['attempted']} attempted"
                   + (": " + ", ".join(f"{k} {v}" for k, v in sorted(h["errors"].items())) if h["errors"] else ""),
                   "crit" if h["error_rate"] is not None and h["error_rate"] > report.BAD_JEV_ERR else ""),
             _tile("latency p95", f"{h['latency_p95']:.0f} ms" if h["latency_p95"] is not None else "-", f"mean {h['latency_mean']:.0f} ms" if h["latency_mean"] else ""),
             _tile("realised horizon", f"{hz['mean']:.0f} s" if hz["mean"] is not None else "-",
                   (f"|offset| p95 {hz['p95']:.0f} s, max {hz['max']:.0f} s; " if hz["p95"] is not None else "") + f"isolated skips {hz['skips']}"),
             (_tile("spend, whole log", f"${usd_all:.4f}", f"${usd_all / max(1, len(days_seen)):.4f} per logged day; tripwire ${config.DAILY_SPEND_HALT_USD:g}/day")
              if report._num(usd_all) else
              _tile("spend, whole log", "past range", f"the logged input tokens sum past a float's range; tripwire ${config.DAILY_SPEND_HALT_USD:g}/day", "crit")),
             _tile("drift", str(h["drift"]), ", ".join(f"{k} {v}" for k, v in sorted(h["models"].items())) or "no answers", "crit" if h["drift"] else ""),
             _tile("key answering", "loop key" if keys and not h["shared_key_rows"] else "SHARED KEY" if h["shared_key_rows"] else "-",
                   key_txt, "crit" if h["shared_key_rows"] else ""),
             _tile("prompt_b versions", ", ".join(f"{k} {v}" for k, v in sorted(h["versions"].items())) or "-", "rows per wording in the sample"),
             _tile("BAD days", str(len(h["bad_days"])), f"of {len(h['days'])} in sample; 3 pause the run"
                   + (f"; {len(h['empty_days'])} with no live rows" if h.get("empty_days") else ""), "crit" if h["bad_days"] else "")]
    parts.append("<div class='tiles'>" + "".join(tiles) + "</div>")
    parts.append("<p class='sub' style='margin-top:10px'>absence in the sample: "
                 + (", ".join(f"{k} {v}" for k, v in sorted(h["absence"].items())) or "none")
                 + f" &middot; live answered {h['live']:,}, dry {h['dry']}"
                 + (f" &middot; skipped log lines {h['skipped']}" if h["skipped"] else "") + "</p>")

    # -- the 28 days
    if t0 is not None:
        by = {d["day"]: d for d in h["days"]}
        cells = []
        for n in range(1, report.SAMPLE_DAYS + 1):
            lab = f"d{n:02d}"
            d = by.get(lab)
            if d is None:
                cls, title = "", f"{lab}: not yet"
            else:
                cls = "bad" if d["bad"] else "empty" if d.get("empty") else "open" if d["open"] else "ok"
                title = (f"{lab}: {d['ticks']} ticks, fill {_pc(d['fill'])}, jev-err {_pc(d['jev_err'])}"
                         + (f", BAD ({', '.join(d['why'])})" if d["bad"] else ", NO LIVE ROWS" if d.get("empty") else ", open" if d["open"] else ", ok"))
            cells.append(f"<div class='d {cls}' title='{_esc(title)}'>{n}</div>")
        parts.append("<h2>the 28 days</h2><p class='sub'>one cell per T0-anchored day: green ok, red BAD (stop rule 3), grey NO LIVE ROWS "
                     "(fill 0/0, undefined; the exclusion is Alex's call), amber open (its last row can still fill), blank not yet.</p>"
                     f"<div class='days'>{''.join(cells)}</div>")

    # -- hourly strip: every gap is a light cell; only priced ticks count
    parts.append("<h2>priced ticks per hour (UTC)</h2><p class='sub'>a full hour is 60 ticks with a mid; a pale or empty cell is a gap "
                 "(the Mac asleep or logged out, the feed down, a HALT: absence rows do not count, hover for them). A dashed cell is an "
                 "hour not yet begun at render; today's count and its hour in progress are out of the minutes begun, unless they hold "
                 "a row stamped after the clock (a clock stepped forward): then they read as logged, out of 1440 and 60. Calendar days; "
                 + ("T0 days start at " + report._iso_minute(t0)[11:] + ". " if t0 is not None else "")
                 + "Days before T0 are labelled.</p>")
    strip = ["<div class='wrap'><div class='strip'><div class='lab'>day &middot; <b>ticks</b></div>"] + [f"<div class='hr'>{hh:02d}</div>" for hh in range(HOURS)]
    if strip_older:
        strip.append(f"<div class='lab'>{len(strip_older)} earlier logged day(s), the last {strip_older[-1][:4]}-{strip_older[-1][4:6]}-{strip_older[-1][6:]}: not drawn</div>"
                     + "".join("<div class='cell'></div>" for _ in range(HOURS)))
    now_s = now.timestamp()
    for d in strip_days:
        d0 = report.tick_epoch(d + "T000000Z")
        pre = t0 is not None and d0 + 86400 <= t0
        lab = f"{d[:4]}-{d[4:6]}-{d[6:]}" + (" (pre-T0)" if pre else "")
        total = sum(hourly_c.get((d, hh), 0) for hh in range(HOURS))
        so_far = d0 <= now_s < d0 + 86400 and d not in late_days       # a day holding a row after the clock: as logged
        of = int((now_s - d0) // 60) + 1 if so_far else DAY_TICKS        # today: out of the minutes begun
        strip.append(f"<div class='lab'>{_esc(lab)} &middot; <b>{total}</b>/{of}</div>")
        for hh in range(HOURS):
            n = hourly_c.get((d, hh), 0)
            cls, tip = _hour_cell(n, d0 + 3600 * hh, now_s, (d, hh) in late)
            ab = absent_c.get((d, hh))
            ab_txt = ("; absent " + ", ".join(f"{k} {v}" for k, v in sorted(ab.items()))) if ab else ""
            strip.append(f"<div class='{cls}' title='{_esc(lab)} {hh:02d}:00Z: {_esc(tip)}{_esc(ab_txt)}'></div>")
    strip.append("</div></div>")
    strip.append("<div class='legend'><span>priced ticks/hour</span>"
                 + "".join(f"<span><i class='sw b{i}'></i>{lo}</span>" for i, lo in enumerate(("1-29", "30-44", "45-54", "55-59", "60")))
                 + "<span><i class='sw'></i>0</span><span><i class='sw future'></i>not yet</span></div>")
    parts.extend(strip)

    # -- per-day table (stop rule 3)
    parts.append(("<h2>per day from T0 &middot; PREREG §8 stop rule 3</h2>" if t0 is not None else "<h2>per UTC day &middot; PREREG §8 stop rule 3</h2>")
                 + f"<p class='sub'>BAD when fill &lt; {100 * report.BAD_FILL:.0f}% of live rows or jev errors &gt; {100 * report.BAD_JEV_ERR:.0f}% of attempted; "
                 f"{report.BAD_DAYS_PAUSE} BAD days pause the run. fill counts live rows whose t + h the log has reached (pending = not yet). "
                 "The exclusion is a hand-written line in data/exclusions.tsv, never this page.</p>")
    t = ["<div class='wrap'><table><tr><th>day</th><th>ticks</th><th>coverage</th><th>live</th><th>fill</th><th>pending</th><th>skipped min</th>"
         "<th>jev-err</th><th class='l'>absence</th><th>latency p95</th><th>spend</th><th class='l'>flag</th></tr>"]
    for d in h["days"]:
        flag = (f"<span class='badge crit'>BAD ({', '.join(d['why'])})</span>" if d["bad"]
                else "<span class='badge crit'>NO LIVE ROWS</span>" if d.get("empty")
                else "<span class='badge warn'>open</span>" if d["open"] else "<span class='badge ok'>ok</span>")
        lab = (f"{d['day']} <span class='mono'>{d['span'][0][:13]}Z..{d['span'][1][:13]}Z</span>" if d["span"]
               else f"{d['day'][:4]}-{d['day'][4:6]}-{d['day'][6:]}")
        ab = abs_day.get(d["day"])
        p95 = (lat.get(d["day"]) or (None, None, 0))[1]
        usd = "past range" if d["day"] in spend_over else f"${spend.get(d['day'], 0.0):.4f}"
        t.append(f"<tr><td>{lab}</td><td>{d['ticks']}</td><td>{_mbar(d['cov'])}{_pc(d['cov'])}</td><td>{d['live']}</td>"
                 f"<td>{_mbar(d['fill'], report.BAD_FILL)}{_pc(d['fill'])}</td><td>{d['pending']}</td><td>{d['skips']}</td>"
                 f"<td>{_pc(d['jev_err'])}</td><td class='l'>{_esc(', '.join(f'{k} {v}' for k, v in sorted(ab.items())) if ab else '')}</td>"
                 f"<td>{f'{p95:.0f} ms' if p95 is not None else ''}</td><td>{usd}</td><td class='l'>{flag}</td></tr>")
    if not h["days"]:
        t.append("<tr><td colspan='12'>no rows in the sample yet</td></tr>")
    t.append("</table></div>")
    parts.extend(t)

    # -- spend and latency per day
    days = [d["day"] for d in h["days"]]
    if days:
        left_out = [d for d in days if d in spend_over]                  # no bar: their summed tokens are past a float's range
        items = [(_short(d), None, f"{d}: input tokens summed past a float's range, not charted", False) if d in spend_over else
                 (_short(d), spend.get(d, 0.0), f"{d}: ${spend.get(d, 0.0):.4f} of the ${config.DAILY_SPEND_HALT_USD:g} tripwire", False) for d in days]
        mx = max((v for _, v, _, _ in items if v is not None), default=0.0)
        parts.append(f"<h2>spend per day &middot; max ${mx:.4f}, tripwire ${config.DAILY_SPEND_HALT_USD:g}</h2>"
                     "<p class='sub'>input tokens the rows logged, at the configured rate; the top of the chart is the tripwire's dollar amount. The guard"
                     " itself counts per UTC day and charges a send with no logged count at 2,000 tokens, so it can trip on a day whose bar"
                     " stays lower (make status shows its count)."
                     + (f" <span class='badge crit'>{len(left_out)} day(s) not charted</span> {_esc(', '.join(left_out))}: the input tokens"
                        " logged that day sum past a float's range." if left_out else "")
                     + "</p>" + _vbars(items, config.DAILY_SPEND_HALT_USD, max(1, len(items) // 14)))
        items = []
        for d in days:
            m, p95, n = lat.get(d) or (None, None, 0)
            items.append((_short(d), p95, f"{d}: p95 {p95:.0f} ms, mean {m:.0f} ms, n {n}" if p95 is not None else f"{d}: no latency", False))
        top = max((v for _, v, _, _ in items if v is not None), default=0)
        parts.append(f"<h2>jev latency p95 per day &middot; tallest bar {top:.0f} ms</h2>"
                     f"<p class='sub'>the answering request alone (jev.latency_ms); the request times out at {config.JEV_TIMEOUT_S} s and one retry still fits under the tick's 50 s watchdog.</p>"
                     + _vbars(items, top, max(1, len(items) // 14)))

    # -- holes
    g = gaps(sample, t0)
    parts.append(f"<h2>holes &middot; {len(g)} of {GAP_MIN}+ missing minutes, {sum(x['minutes'] for x in g)} minutes in all</h2>"
                 "<p class='sub'>runs of missing minutes in the sample's tick sequence (the Mac asleep or logged out); each costs the rows of the "
                 "15 minutes before it their outcome. The per-day table's skipped minutes are the isolated ones.</p>")
    if g:
        t = ["<div class='wrap'><table><tr><th>day</th><th class='l'>first missing minute</th><th class='l'>next row</th><th>minutes</th></tr>"]
        for x in g[:GAPS_SHOWN]:
            t.append(f"<tr><td>{_esc(x['day'])}</td><td class='l mono'>{_esc(x['from'])}</td><td class='l mono'>{_esc(x['to'])}</td><td>{x['minutes']}</td></tr>")
        if len(g) > GAPS_SHOWN:
            t.append(f"<tr><td colspan='4' class='l'>and {len(g) - GAPS_SHOWN} shorter ones</td></tr>")
        t.append("</table></div>")
        parts.extend(t)
    else:
        parts.append("<p class='sub'>none</p>")

    # -- occupancy bars
    parts.append(f"<h2>adjective occupancy &middot; {occ['n']:,} rows, {occ['states']} of 81 states seen</h2>"
                 "<p class='sub'>the four words Jev sees, per dimension, light to dark in the alphabet's order. "
                 f"A word above {100 * report.OCCUPANCY_FLAG:.0f}% is a constant the arms cannot disagree on.</p><div class='occ'>")
    outside = []
    for dname in state.DIMS:
        segs, words, seen = [], [], 0.0
        for i, w in enumerate(state.ALPHABET[dname]):
            p = occ["share"].get((dname, w)) or 0.0
            seen += p
            segs.append(f"<span class='b{(0, 2, 4)[i]}' style='width:{100 * p:.2f}%' title='{_esc(dname)} {_esc(w)}: {_pc(p)}'></span>")
            words.append(f"<span><i class='sw b{(0, 2, 4)[i]}'></i>{_esc(w)} {_pc(p)}</span>")
        other = 1.0 - seen if occ["n"] else 0.0
        if other > 1e-9:                                              # a word the SPEC does not have: loud, as report §2 prints it
            outside.append(dname)
            segs.append(f"<span class='out' style='width:{100 * other:.2f}%' title='{_esc(dname)}: OUTSIDE-ALPHABET {_pc(other)}'></span>")
            words.append(f"<span><i class='sw out'></i>OUTSIDE-ALPHABET {_pc(other)}</span>")
        parts.append(f"<div class='lab'>{_esc(dname)}</div><div class='bar'>{''.join(segs)}</div>"
                     f"<div class='words legend'>{''.join(words)}</div>")
    parts.append("</div>")
    for d, w in occ["flags"]:
        parts.append(f"<p class='sub'><span class='badge warn'>FLAG</span> {_esc(d)} is {_esc(w)} above {100 * report.OCCUPANCY_FLAG:.0f}%: a constant</p>")
    for d in outside:
        parts.append(f"<p class='sub'><span class='badge crit'>OUTSIDE-ALPHABET</span> {_esc(d)} carries a word the SPEC does not have (report §2 counts it)</p>")

    # -- the 81-state map
    parts.append("<h2>the 81 states &middot; occupancy in the sample</h2>"
                 "<p class='sub'>rows: trend &times; vol; columns: liquidity &times; flow. The letter is arm C's rule for the state "
                 "(B buy, S sell, H hold; SPEC §6), fixed by the words, not an answer. The number is rows seen; the shade is its share of the "
                 "busiest state (1%, 5%, 20%, 50%).</p>")
    cols = [(l, f) for l in state.LIQ for f in state.FLOW]
    m = ["<div class='wrap'><div class='map'><div></div>"] + [f"<div class='cl'>{_esc(l)}<br>{_esc(f)}</div>" for l, f in cols]
    for tr in state.TREND:
        for v in state.VOL:
            m.append(f"<div class='rl'>{_esc(tr)}<br>{_esc(v)}</div>")
            for l, f in cols:
                n = sc.get((l, f, tr, v), 0)
                adj = {"liq": l, "flow": f, "trend": tr, "vol": v}
                rc = state.rule_c(adj)
                b = _bin_state(n, top_state)
                cls = "c" + (f" b{b}" if b >= 0 else "")
                m.append(f"<div class='{cls}' title='{_esc(state.state_string(adj))}: {n} rows ({_pc(n / occ['n'] if occ['n'] else None)}), rule_c {rc}'>"
                         f"<i>{RULE_MARK.get(rc, '?')}</i>{'<b>' + str(n) + '</b>' if n else ''}</div>")
    m.append("</div></div>")
    parts.extend(m)

    # -- test-retest
    parts.append("<h2>test-retest &middot; a_action vs b_action on the same question</h2>")
    parts.append("<p class='sub'>" + " &middot; ".join(_esc(x.strip()) for x in rt["lines"]) + "</p>")

    # -- nightly
    parts.append("<h2>the nightly &middot; proposals on the 81 synthetic states</h2>"
                 "<p class='sub'>what the slow model proposed and how Jev answered each candidate across every state the alphabet can make. "
                 "Nothing here touches a logged outcome, and the rationale (which quotes the digest) stays in proposals/. A person promotes with bin/promote; nothing else changes prompts/.</p>")
    if props:
        t = ["<div class='wrap'><table><tr><th class='l'>night</th><th>sends</th><th class='l'>candidate</th><th>vs CURRENT</th><th>vs rule_c</th></tr>"]
        for p in props:
            sends = f"{p['answered']}/{p['requests']}" + (f", {p['errors']} err" if p["errors"] else "") if p["requests"] is not None else "-"
            cur = f"current {p['current']}: {p['current_vs_rule']}/{p.get('current_of') or '?'} vs rule_c" if p["current"] else ""
            if not p["candidates"]:
                t.append(f"<tr><td class='l'>{_esc(p['date'])}</td><td>{_esc(sends)}</td><td class='l' colspan='3'>{_esc(cur) or 'no candidates parsed'}</td></tr>")
            for i, c in enumerate(p["candidates"]):
                first = f"<td class='l'>{_esc(p['date'])}<br><span class='mono'>{_esc(cur)}</span></td><td>{_esc(sends)}</td>" if i == 0 else "<td></td><td></td>"
                noop = " <span class='badge warn'>no-op</span>" if c["vs_current"] == 0 else ""
                t.append(f"<tr>{first}<td class='l'>{_esc(c['name'])}{noop}</td><td>{c['vs_current']}/{c['of']}</td><td>{c['vs_rule']}/{c['of']}</td></tr>")
        t.append("</table></div>")
        parts.extend(t)
    else:
        parts.append("<p class='sub'>no proposals yet</p>")

    parts.append("<div class='foot'>Health only (PREREG §8.4): this page is report §1-§3 and the nightly's synthetic tables, rebuilt by the "
                 "nightly once a day (every age above is at render time). It calls only report.health, days_table, occupancy and retest, so no "
                 "H1, H2, pair, calibration or confidence number can appear here; tests/test_dash.py holds it to that. "
                 f"Log: {_esc(log or config.DECISIONS)}. Standard library, no script, nothing loaded from the network.</div>")
    parts.append("</main></body></html>")
    return "\n".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m loop.dash", description="the loop's health as one HTML page (report §1-§3 only)")
    ap.add_argument("--log", default=config.DECISIONS)
    ap.add_argument("--t0", help="PREREG T0 (UTC minute or tick_id); default: read from PREREG.md §11, else the whole log")
    ap.add_argument("--out", default=os.path.join(config.DATA, "dash.html"))
    ap.add_argument("--prereg", default=PREREG_PATH)
    ap.add_argument("--no-t0", action="store_true", help="ignore PREREG's T0: the whole log is the sample")
    ap.add_argument("--data", default=None, help="the data/ holding heartbeat and HALT (default: the repo's; propose.sh --root passes its own)")
    ap.add_argument("--proposals", default=None, help="the proposals/ to read the tables from (default: the repo's)")
    ap.add_argument("--prompts", default=None, help="prompts root for CURRENT (default: the repo's; the suite pins v1)")
    args = ap.parse_args(argv)
    try:
        t0 = report._t0(args.t0) if args.t0 else (None if args.no_t0 else read_t0(args.prereg))
    except ValueError:
        ap.error(f"--t0 wants YYYY-MM-DDTHH:MM (UTC) or a tick_id, got {args.t0!r}")
    rows, bad = [], []
    if os.path.exists(args.log):
        rows = outcomes.load(args.log, bad)
    outs = outcomes.join(rows)
    hb_path = os.path.join(args.data, "heartbeat") if args.data else None       # None: config.HEARTBEAT / config.HALT
    halt_path = os.path.join(args.data, "HALT") if args.data else config.HALT
    page = render(rows, outs, t0=t0, hb=heartbeat(hb_path), halt=os.path.exists(halt_path), props=proposals(args.proposals),
                  current=current_version(args.prompts), log=args.log, bad=bad)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    # errors="replace": a path that is not UTF-8 (Linux; APFS names are UTF-8) reaches the page as a lone
    # surrogate and stopped the write; each such character is written as '?' instead (the pre-merge check, 2026-09-28)
    with open(args.out, "w", encoding="utf-8", errors="replace") as fh:
        fh.write(page)
    sys.stdout.write(f"{args.out}\t{len(rows)} rows, {len(bad)} skipped\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

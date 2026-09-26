"""loop/dash.py -- one HTML page of the loop's HEALTH, built from the log and nothing else.

    python3 -m loop.dash [--log FILE] [--t0 YYYY-MM-DDTHH:MM|tick_id] [--out data/dash.html]

Health only, by construction (PREREG §8.4): the page is report §1-§3 (health, the per-day
stop-rule-3 table, occupancy, test-retest) plus what those already imply -- a ticks-per-hour
strip that shows every gap, the 81-state occupancy map, spend per day -- and the nightly's
own summary lines from proposals/*.md (synthetic states, never an outcome). It imports
report.health, report.occupancy, report.retest and nothing that replays a book, joins a
return to an answer or prints a confidence table, so no H1, H2, pair, calibration or
confidence number can appear here by accident; tests/test_dash.py holds it to that.
Standard library only; the page carries no script and loads nothing from the network, so
it can be opened from a file and shared without reaching for anything."""
import argparse, collections, datetime, glob, html, os, re, sys

from . import config, outcomes, report, state

T0_RE = re.compile(r"T0 \(first tick_id of day 1\): `(\d{8}T\d{6}Z)`")
PROPOSAL_HEAD = re.compile(r"requests: (\d+), answered: (\d+), errors: (\d+)")
PROPOSAL_CAND = re.compile(r"^## (cand_\d+)\n\nrationale: (.*?)\n\ndiffers from CURRENT on (\d+) of (\d+) answered states; from rule_c on (\d+) of \d+",
                           re.M | re.S)
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


def read_t0(prereg=os.path.join(config.REPO, "PREREG.md")):
    """PREREG §11's T0 line, or None before sealing."""
    try:
        with open(prereg, encoding="utf-8") as fh:
            m = T0_RE.search(fh.read())
    except OSError:
        return None
    return report.tick_epoch(m.group(1)) if m else None


def heartbeat(path=config.HEARTBEAT):
    try:
        with open(path) as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def hourly(rows):
    """(day, hour) -> distinct ticks, over every row that has a tick_id."""
    c = collections.defaultdict(set)
    for r in rows:
        t = str(r.get("tick_id"))
        if len(t) >= 11:
            c[(t[:8], int(t[9:11]))].add(t)
    return {k: len(v) for k, v in c.items()}


def spend_by_day(rows, t0=None):
    c = collections.Counter()
    for r in rows:
        tok = (r.get("jev") or {}).get("input_tokens")
        if isinstance(tok, (int, float)) and tok > 0:
            c[report.day_of(r.get("tick_id"), t0)] += tok
    return {d: t * config.USD_PER_MTOK / 1e6 for d, t in c.items()}


def state_counts(rows):
    c = collections.Counter()
    for r in rows:
        a = r.get("adj")
        if isinstance(a, dict) and all(a.get(d) in state.ALPHABET[d] for d in state.DIMS):
            c[(a["liq"], a["flow"], a["trend"], a["vol"])] += 1
    return c


def proposals(root=config.PROPOSALS):
    """One dict per proposals/<date>.md: the nightly's own header and per-candidate lines."""
    out = []
    for path in sorted(glob.glob(os.path.join(root, "????-??-??.md"))):
        try:
            with open(path, encoding="utf-8") as fh:
                txt = fh.read()
        except OSError:
            continue
        head = PROPOSAL_HEAD.search(txt)
        cur = CURRENT_CAND.search(txt)
        cands = [{"name": m.group(1), "rationale": m.group(2).strip(), "vs_current": int(m.group(3)),
                  "of": int(m.group(4)), "vs_rule": int(m.group(5))} for m in PROPOSAL_CAND.finditer(txt)]
        out.append({"date": os.path.basename(path)[:-3],
                    "requests": int(head.group(1)) if head else None, "answered": int(head.group(2)) if head else None,
                    "errors": int(head.group(3)) if head else None,
                    "current": cur.group(1) if cur else None, "current_vs_rule": int(cur.group(2)) if cur else None,
                    "candidates": cands})
    return out


def current_version(root=config.PROMPTS):
    try:
        with open(os.path.join(root, "CURRENT")) as fh:
            return fh.read().strip()
    except OSError:
        return None


# ---- the page ------------------------------------------------------------------------------
CSS = """
:root { --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7;
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
.badge.ok { background: var(--good); color:#fff; } .badge.warn { background: var(--warn); color:#0b0b0b; } .badge.crit { background: var(--crit); color:#fff; }
.tiles { display:grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.tile { background: var(--surface); border: 1px solid var(--grid); border-radius: 8px; padding: 10px 12px; }
.tile .k { color: var(--ink2); font-size: 12px; } .tile .v { font-size: 22px; font-weight: 600; margin-top: 2px; }
.tile .n { color: var(--muted); font-size: 12px; }
table { border-collapse: collapse; background: var(--surface); border: 1px solid var(--grid); border-radius: 8px; width: 100%; }
th, td { padding: 6px 10px; text-align: right; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th { color: var(--ink2); font-weight: 500; font-size: 12px; } td:first-child, th:first-child { text-align: left; }
tr:last-child td { border-bottom: 0; } td.l, th.l { text-align: left; white-space: normal; }
.wrap { overflow-x: auto; }
.strip { display: grid; grid-template-columns: 90px repeat(24, 1fr); gap: 2px; align-items: center; }
.strip .lab { color: var(--ink2); font-size: 12px; text-align: right; padding-right: 8px; }
.strip .hr { color: var(--muted); font-size: 10px; text-align: center; }
.cell { height: 18px; border-radius: 3px; background: var(--surface); border: 1px solid var(--grid); }
.b0 { background: var(--s1); border-color: var(--s1); } .b1 { background: var(--s2); border-color: var(--s2); }
.b2 { background: var(--s3); border-color: var(--s3); } .b3 { background: var(--s4); border-color: var(--s4); } .b4 { background: var(--s5); border-color: var(--s5); }
.legend { color: var(--ink2); font-size: 12px; margin-top: 8px; display:flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.sw { display:inline-block; width: 14px; height: 14px; border-radius: 3px; vertical-align: -2px; margin-right: 3px; border: 1px solid var(--grid); }
.bar { display:flex; height: 22px; border-radius: 4px; overflow: hidden; gap: 2px; background: var(--page); }
.bar span { display:block; height: 100%; }
.occ { display:grid; grid-template-columns: 60px 1fr; gap: 6px 12px; align-items: center; }
.occ .lab { color: var(--ink2); font-size: 12px; text-align: right; }
.occ .words { color: var(--ink2); font-size: 12px; grid-column: 2; margin-top: -2px; margin-bottom: 6px; }
.map { display: grid; grid-template-columns: 120px repeat(9, 1fr); gap: 3px; }
.map .rl { color: var(--ink2); font-size: 11px; text-align: right; padding-right: 6px; line-height: 1.1; }
.map .cl { color: var(--muted); font-size: 10px; text-align: center; line-height: 1.1; }
.map .c { height: 34px; border-radius: 4px; background: var(--surface); border: 1px solid var(--grid); position: relative; }
.map .c i { position: absolute; left: 4px; top: 2px; font: 10px/1 monospace; color: var(--muted); font-style: normal; }
.map .c.b2 i, .map .c.b3 i, .map .c.b4 i { color: #fff; }
.map .c b { position: absolute; right: 4px; bottom: 2px; font-size: 11px; font-weight: 500; color: var(--ink2); }
.map .c.b2 b, .map .c.b3 b, .map .c.b4 b { color: #fff; }
.foot { color: var(--muted); font-size: 12px; margin-top: 32px; border-top: 1px solid var(--grid); padding-top: 10px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
@media (max-width: 700px) { .strip { grid-template-columns: 60px repeat(24, 1fr); } .map { grid-template-columns: 70px repeat(9, 1fr); } .map .c { height: 26px; } }
"""


def _tile(k, v, n=""):
    return f'<div class="tile"><div class="k">{_esc(k)}</div><div class="v">{_esc(v)}</div><div class="n">{_esc(n)}</div></div>'


def _age(hb, now):
    if not hb:
        return None
    try:
        t = datetime.datetime.strptime(hb[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    return (now - t).total_seconds()


def render(rows, outs, t0=None, now=None, hb=None, halt=False, props=(), current=None, log=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    sample = report.in_sample(rows, t0) if t0 is not None else rows
    h_all = report.health(rows, outs)
    h = report.health(sample, outs, t0=t0)
    occ = report.occupancy(sample)
    rt = report.retest(sample)
    age = _age(hb, now)
    day_n = None
    if t0 is not None:
        day_n = int((now.timestamp() - t0) // 86400) + 1
    cov_since = None
    if t0 is not None and now.timestamp() > t0:
        cov_since = h["ticks"] / max(1.0, (min(now.timestamp(), t0 + report.SAMPLE_DAYS * 86400) - t0) / config.CADENCE_S)
    spend = spend_by_day(rows, t0)

    def spend_of(d):
        return spend.get(d["day"], 0.0)
    days_seen = sorted({d["day"] for d in h_all["days"]})
    hourly_c = hourly(rows)
    sc = state_counts(sample)
    top_state = max(sc.values()) if sc else 0

    # -- header
    if halt:
        status = '<span class="badge crit">HALT present: nothing is sent</span>'
    elif age is None:
        status = '<span class="badge warn">no heartbeat</span>'
    elif age > 3 * config.CADENCE_S:
        status = f'<span class="badge crit">last tick {age / 60:.0f} min ago</span>'
    else:
        status = f'<span class="badge ok">ticking, last {age:.0f} s ago</span>'
    parts = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>",
             "<title>JevTrader health</title>", f"<style>{CSS}</style></head><body><main>",
             f"<h1>JevTrader &middot; paper loop health {status}</h1>",
             f"<p class='sub'>{_esc(config.VENUE)} {_esc(config.PRODUCT)}, one tick a minute, horizon {config.HORIZON_S // 60} min &middot; "
             f"rendered {now.strftime('%Y-%m-%d %H:%MZ')}"
             + (f" &middot; T0 {report._iso_minute(t0)}" if t0 is not None else " &middot; no T0: whole log")
             + (f" &middot; prompt_b {_esc(current)}" if current else "") + "</p>"]

    # -- tiles (sample)
    tiles = [_tile("sample day", f"{day_n} of {report.SAMPLE_DAYS}" if day_n else "-", "days from T0" if t0 is not None else "no T0"),
             _tile("ticks in sample", f"{h['ticks']:,}", f"{h_all['ticks']:,} in the whole log"),
             _tile("coverage since T0", _pc(cov_since), "ticks per minute elapsed"),
             _tile("outcome fill", _pc(h["fill"]), f"{h['filled']}/{h['priced']} priced ticks"),
             _tile("jev errors", _pc(h["error_rate"]), f"{sum(h['errors'].values())}/{h['attempted']} attempted"),
             _tile("latency p95", f"{h['latency_p95']:.0f} ms" if h["latency_p95"] is not None else "-", f"mean {h['latency_mean']:.0f} ms" if h["latency_mean"] else ""),
             _tile("spend, whole log", f"${h_all['usd']:.4f}", f"${h_all['usd'] / max(1, len(days_seen)):.4f} per logged day"),
             _tile("drift", str(h["drift"]), ", ".join(f"{k} {v}" for k, v in sorted(h["models"].items())) or "no answers"),
             _tile("BAD days", str(len(h["bad_days"])), f"of {len(h['days'])} in sample; 3 pause the run")]
    parts.append("<div class='tiles'>" + "".join(tiles) + "</div>")

    # -- hourly strip: every gap is a light cell
    parts.append("<h2>ticks per hour (UTC)</h2><p class='sub'>a full hour is 60 ticks; a pale or empty cell is a gap "
                 "(the Mac asleep, logged out, or the feed down). Days before T0 are labelled.</p>")
    strip = ["<div class='strip'><div></div>"] + [f"<div class='hr'>{hh:02d}</div>" for hh in range(HOURS)]
    for d in days_seen:
        pre = t0 is not None and report.tick_epoch(d + "T000000Z") + 86400 <= t0
        lab = f"{d[:4]}-{d[4:6]}-{d[6:]}" + (" (pre-T0)" if pre else "")
        strip.append(f"<div class='lab'>{_esc(lab)}</div>")
        for hh in range(HOURS):
            n = hourly_c.get((d, hh), 0)
            b = _bin(n, 60)
            cls = "cell" + (f" b{b}" if b >= 0 else "")
            strip.append(f"<div class='{cls}' title='{_esc(lab)} {hh:02d}:00Z: {n}/60 ticks'></div>")
    strip.append("</div>")
    strip.append("<div class='legend'><span>ticks/hour</span>"
                 + "".join(f"<span><i class='sw b{i}'></i>{lo}-{hi}</span>" for i, (lo, hi) in enumerate(((1, 12), (13, 24), (25, 36), (37, 48), (49, 60))))
                 + "<span><i class='sw'></i>0</span></div>")
    parts.extend(strip)

    # -- per-day table (stop rule 3)
    parts.append(("<h2>per day from T0 &middot; PREREG §8 stop rule 3</h2>" if t0 is not None else "<h2>per UTC day &middot; PREREG §8 stop rule 3</h2>")
                 + f"<p class='sub'>BAD when fill &lt; {100 * report.BAD_FILL:.0f}% of live rows or jev errors &gt; {100 * report.BAD_JEV_ERR:.0f}% of attempted; "
                 f"{report.BAD_DAYS_PAUSE} BAD days pause the run. The exclusion is a hand-written line in data/exclusions.tsv, never this page.</p>")
    t = ["<div class='wrap'><table><tr><th>day</th><th>ticks</th><th>coverage</th><th>live</th><th>fill</th><th>pending</th><th>jev-err</th><th>spend</th><th class='l'>flag</th></tr>"]
    for d in h["days"]:
        flag = (f"<span class='badge crit'>BAD ({', '.join(d['why'])})</span>" if d["bad"]
                else "<span class='badge warn'>open</span>" if d["open"] else "<span class='badge ok'>ok</span>")
        lab = (f"{d['day']} <span class='mono'>{d['span'][0][:13]}Z..{d['span'][1][:13]}Z</span>" if d["span"]
               else f"{d['day'][:4]}-{d['day'][4:6]}-{d['day'][6:]}")
        t.append(f"<tr><td>{lab}</td><td>{d['ticks']}</td><td>{_pc(d['cov'])}</td><td>{d['live']}</td>"
                 f"<td>{_pc(d['fill'])}</td><td>{d['pending']}</td><td>{_pc(d['jev_err'])}</td><td>${spend_of(d):.4f}</td><td class='l'>{flag}</td></tr>")
    if not h["days"]:
        t.append("<tr><td colspan='9'>no rows in the sample yet</td></tr>")
    t.append("</table></div>")
    parts.extend(t)

    # -- occupancy bars
    parts.append(f"<h2>adjective occupancy &middot; {occ['n']:,} rows, {occ['states']} of 81 states seen</h2>"
                 "<p class='sub'>the four words Jev sees, per dimension, light to dark in the alphabet's order. "
                 f"A word above {100 * report.OCCUPANCY_FLAG:.0f}% is a constant the arms cannot disagree on.</p><div class='occ'>")
    for dname in state.DIMS:
        segs, words = [], []
        for i, w in enumerate(state.ALPHABET[dname]):
            p = occ["share"].get((dname, w)) or 0.0
            segs.append(f"<span class='b{(0, 2, 4)[i]}' style='width:{100 * p:.2f}%' title='{_esc(dname)} {_esc(w)}: {_pc(p)}'></span>")
            words.append(f"<span><i class='sw b{(0, 2, 4)[i]}'></i>{_esc(w)} {_pc(p)}</span>")
        parts.append(f"<div class='lab'>{_esc(dname)}</div><div class='bar'>{''.join(segs)}</div>"
                     f"<div class='words legend'>{''.join(words)}</div>")
    parts.append("</div>")
    for d, w in occ["flags"]:
        parts.append(f"<p class='sub'><span class='badge warn'>FLAG</span> {_esc(d)} is {_esc(w)} above {100 * report.OCCUPANCY_FLAG:.0f}%: a constant</p>")

    # -- the 81-state map
    parts.append("<h2>the 81 states &middot; occupancy in the sample</h2>"
                 "<p class='sub'>rows: trend &times; vol; columns: liquidity &times; flow. The letter is arm C's rule for the state "
                 "(B buy, S sell, H hold; SPEC §6), fixed by the words, not an answer. The number is rows seen.</p>")
    cols = [(l, f) for l in state.LIQ for f in state.FLOW]
    m = ["<div class='map'><div></div>"] + [f"<div class='cl'>{_esc(l)}<br>{_esc(f)}</div>" for l, f in cols]
    for tr in state.TREND:
        for v in state.VOL:
            m.append(f"<div class='rl'>{_esc(tr)}<br>{_esc(v)}</div>")
            for l, f in cols:
                n = sc.get((l, f, tr, v), 0)
                adj = {"liq": l, "flow": f, "trend": tr, "vol": v}
                rc = state.rule_c(adj)
                b = _bin(n, top_state)
                cls = "c" + (f" b{b}" if b >= 0 else "")
                m.append(f"<div class='{cls}' title='{_esc(state.state_string(adj))}: {n} rows ({_pc(n / occ['n'] if occ['n'] else None)}), rule_c {rc}'>"
                         f"<i>{RULE_MARK.get(rc, '?')}</i>{'<b>' + str(n) + '</b>' if n else ''}</div>")
    m.append("</div>")
    parts.extend(m)

    # -- test-retest
    parts.append("<h2>test-retest &middot; a_action vs b_action on the same question</h2>")
    parts.append("<p class='sub'>" + " &middot; ".join(_esc(x.strip()) for x in rt["lines"]) + "</p>")

    # -- nightly
    parts.append("<h2>the nightly &middot; proposals on the 81 synthetic states</h2>"
                 "<p class='sub'>what the slow model proposed and how Jev answered each candidate across every state the alphabet can make. "
                 "Nothing here touches a logged outcome. A person promotes with bin/promote; nothing else changes prompts/.</p>")
    if props:
        t = ["<div class='wrap'><table><tr><th class='l'>night</th><th>sends</th><th class='l'>candidate</th><th>vs CURRENT</th><th>vs rule_c</th><th class='l'>rationale</th></tr>"]
        for p in props:
            sends = f"{p['answered']}/{p['requests']}" + (f", {p['errors']} err" if p["errors"] else "") if p["requests"] is not None else "-"
            cur = f"current {p['current']}: {p['current_vs_rule']}/81 vs rule_c" if p["current"] else ""
            if not p["candidates"]:
                t.append(f"<tr><td class='l'>{_esc(p['date'])}</td><td>{_esc(sends)}</td><td class='l' colspan='4'>{_esc(cur) or 'no candidates parsed'}</td></tr>")
            for i, c in enumerate(p["candidates"]):
                first = f"<td class='l'>{_esc(p['date'])}<br><span class='mono'>{_esc(cur)}</span></td><td>{_esc(sends)}</td>" if i == 0 else "<td></td><td></td>"
                noop = " <span class='badge warn'>no-op</span>" if c["vs_current"] == 0 else ""
                t.append(f"<tr>{first}<td class='l'>{_esc(c['name'])}{noop}</td><td>{c['vs_current']}/{c['of']}</td><td>{c['vs_rule']}/{c['of']}</td>"
                         f"<td class='l'>{_esc(c['rationale'][:220])}{'…' if len(c['rationale']) > 220 else ''}</td></tr>")
        t.append("</table></div>")
        parts.extend(t)
    else:
        parts.append("<p class='sub'>no proposals yet</p>")

    parts.append("<div class='foot'>Health only (PREREG §8.4): this page is report §1-§3 and the nightly's synthetic tables. "
                 "It computes no H1, H2, pair, calibration or confidence number, and cannot: it never imports the code that would. "
                 f"Log: {_esc(log or config.DECISIONS)}. Standard library, no script, nothing loaded from the network.</div>")
    parts.append("</main></body></html>")
    return "\n".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m loop.dash", description="the loop's health as one HTML page (report §1-§3 only)")
    ap.add_argument("--log", default=config.DECISIONS)
    ap.add_argument("--t0", help="PREREG T0 (UTC minute or tick_id); default: read from PREREG.md §11, else the whole log")
    ap.add_argument("--out", default=os.path.join(config.DATA, "dash.html"))
    ap.add_argument("--prereg", default=os.path.join(config.REPO, "PREREG.md"))
    ap.add_argument("--no-t0", action="store_true", help="ignore PREREG's T0: the whole log is the sample")
    args = ap.parse_args(argv)
    try:
        t0 = report._t0(args.t0) if args.t0 else (None if args.no_t0 else read_t0(args.prereg))
    except ValueError:
        ap.error(f"--t0 wants YYYY-MM-DDTHH:MM (UTC) or a tick_id, got {args.t0!r}")
    rows, bad = [], []
    if os.path.exists(args.log):
        rows = outcomes.load(args.log, bad)
    outs = outcomes.join(rows)
    page = render(rows, outs, t0=t0, hb=heartbeat(), halt=os.path.exists(config.HALT), props=proposals(),
                  current=current_version(), log=args.log)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    sys.stdout.write(f"{args.out}\t{len(rows)} rows, {len(bad)} skipped\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""loop/status.py -- the morning check as one command, `make status`: a dozen lines on the
loop's health from the heartbeat, data/HALT, the log, proposals/ and logs/propose.log.

    python3 -m loop.status [--log FILE] [--t0 YYYY-MM-DDTHH:MM|tick_id] [--prereg FILE] [--now YYYY-MM-DDTHH:MM]

Health only, by construction (PREREG §8.4): it reads report.days_table (report §1's per-day
stop-rule-3 table), cycle.spend_today and data/exclusions.tsv (loop.exclusions), plus the heartbeat, HALT, the last row (its DRIFT
flag), proposals/ and logs/propose.log, and nothing that replays a book, joins a return to an answer, or prints a confidence, so no H1, H2,
pair, calibration or confidence number can appear here by accident; tests/test_status.py holds
it to that, as test_dash.py holds the dash. It writes nothing. What HANDOFF.md's "Watch" list
asks a person to read each morning -- `cat data/heartbeat`, `ls proposals/`, `tail
logs/propose.log`, the per-day table -- is here in one screen, and a stale heartbeat or
a HALT is in the first lines under the title.
"""
import argparse, collections, datetime, glob, os, sys

from . import config, cycle, dash, exclusions, outcomes, report

STALE_S = 3 * config.CADENCE_S      # a heartbeat older than three ticks is a stopped loop, not a slow one
LOG_TAIL = 3                        # lines of logs/propose.log shown
DAYS_SHOWN = 3                      # rows of the per-day table shown: yesterday closes, today is open
# The nightly starts 03:30 America/Chicago and its claude call is capped at 45 min awake: under CDT
# it starts 08:30Z and is done by 09:15Z, under CST (from 2026-11-01) it starts 09:30Z and may run to
# 10:15Z. At 10Z a slow winter night is still running, so MISSING waits for 11Z.
NIGHTLY_DONE_UTC_H = 11


def _age_line(hb, now):
    age = dash._age(hb, now)
    if hb is None:
        return "STOPPED? no heartbeat (data/heartbeat absent or empty: the loop has never run here, or the plist is not loaded)"
    if age is None:
        return f"STOPPED? heartbeat unreadable: {hb!r}"
    if age > STALE_S:
        return f"STOPPED? last tick {age / 60:.0f} min ago ({hb}); a healthy loop is under {STALE_S} s"
    return f"ticking: last tick {age:.0f} s ago ({hb})"


def _halt_line(path=None):
    path = path or config.HALT
    if not os.path.exists(path):
        return "HALT absent: sends allowed"
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            why = fh.readline().strip()
        since = datetime.datetime.fromtimestamp(os.path.getmtime(path), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    except OSError:
        why, since = "?", "?"
    return f"HALT PRESENT since {since}: {why or '(empty file)'} -- nothing is sent until a person clears it (STEPS §5)"


def _last_row_line(rows):
    if not rows:
        return "last row: none"
    r = rows[-1]                                  # file order: the row written last
    j = r.get("jev") if isinstance(r.get("jev"), dict) else {}
    adj = r.get("adj") if isinstance(r.get("adj"), dict) else {}
    words = " ".join(str(adj.get(d, "-")) for d in ("liq", "flow", "trend", "vol"))
    return (f"last row: {r.get('tick_id')} {r.get('mode')} {r.get('absence') or 'ok'} state={words} c={r.get('rule_c')}"
            f" prompt_b={r.get('prompt_b')} jev={j.get('latency_ms')}ms/{j.get('input_tokens')}tok err={j.get('error')}"
            f" key={j.get('key_path')}{' DRIFT' if r.get('drift') else ''}")


def _today_line(rows, now, log):
    day = now.strftime("%Y%m%d")
    today = [r for r in rows if str(r.get("tick_id", ""))[:8] == day]
    live = sum(1 for r in today if r.get("mode") == "live" and r.get("absence") is None)
    absent = collections.Counter(r["absence"] for r in today if r.get("absence"))
    usd = cycle.spend_today(now.timestamp(), log)          # a missing log is $0 there; an unreadable one is inf
    elapsed = max(1, int((now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() // config.CADENCE_S))
    return (f"today {now.strftime('%Y-%m-%d')}Z: {len(today)} rows in {elapsed} min ({100.0 * len(today) / elapsed:.0f}%), live answered {live},"
            f" absence " + (", ".join(f"{k} {v}" for k, v in sorted(absent.items())) or "none")
            + (f"; spend UNREADABLE: the log cannot be read, so the next tick's guard trips (HALT) rather than count it" if usd == float("inf")
               else f"; spend UNCOUNTED: a token count today, or today's sum of them, is past a float's range, so the next tick's guard"
                    " trips (HALT)" if usd == cycle.SPEND_UNCOUNTED
               else f"; spend ${usd:.4f} of the ${config.DAILY_SPEND_HALT_USD:g} tripwire (as the guard counts it)"))


def _sample_line(t0, now):
    if t0 is None:
        return "sample: no T0 (PREREG §11 unsealed, or --t0 not given)"
    n = int((now.timestamp() - t0) // 86400) + 1
    end = report._iso_minute(t0 + report.SAMPLE_DAYS * 86400)
    if n < 1:
        return f"sample: not started (T0 {report._iso_minute(t0)})"
    if n > report.SAMPLE_DAYS:
        return f"sample: ended {end}; day 28's inference is `python3 -m loop.inference --sample --out RESULTS.md`"
    return f"sample: day d{n:02d} of {report.SAMPLE_DAYS} (T0 {report._iso_minute(t0)}, ends {end})"


def _days_lines(rows, outs, t0, now=None):
    """The sample's per-day table (rows cut to [T0, T0 + 28 d) with the whole log's last tick, as the
    dash and `make health` do), so a pre-T0 or post-sample day never counts as BAD here."""
    if not rows:
        return ["per day: no rows"]
    last = max((report.tick_epoch(r["tick_id"]) for r in rows if isinstance(r.get("tick_id"), str)), default=None)
    scope = report.in_sample(rows, t0) if t0 is not None else rows
    d = report.days_table(scope, outs, t0, last, now.timestamp() if now is not None else None)
    shown = d["days"][-DAYS_SHOWN:]
    out = [f"per day (last {len(shown)} of {len(d['days'])}; BAD days so far {len(d['bad'])}" + (": " + ", ".join(d["bad"]) if d["bad"] else "")
           + (f"; NO LIVE ROWS {len(d['empty'])}: " + ", ".join(d["empty"]) + " (fill 0/0; the exclusion is Alex's call)" if d["empty"] else "") + "):"]
    for x in shown:
        flag = f"BAD ({', '.join(x['why'])})" if x["bad"] else "NO LIVE ROWS" if x.get("empty") else "open" if x["open"] else "ok"
        out.append(f"  {x['day']:<9} ticks {x['ticks']:>5} ({report._pc(x['cov']):>6})  live {x['live']:>5}  fill {report._pc(x['fill']):>6}"
                   f"  pend {x['pending']:>4}  skip {x['skips']:>3}  jev-err {report._pc(x['jev_err']):>6}  {flag}")
    return out


def _nightly_lines(proposals_root, log_path, now):
    out = []
    md = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(proposals_root, "????-??-??.md")))
    js = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(proposals_root, "????-??-??.json")))
    # The nightly runs at 03:30 America/Chicago = 08:30Z (CDT) or 09:30Z (CST) and digests the UTC day
    # before; by NIGHTLY_DONE_UTC_H yesterday's proposal should exist, before that the day before's.
    expected = (now - datetime.timedelta(days=1 if now.hour >= NIGHTLY_DONE_UTC_H else 2)).strftime("%Y-%m-%d")
    latest = max(md + js) if md or js else None
    line = f"nightly: {len(md)} tables, {len(js)} proposal files in proposals/; latest {latest or 'none'}"
    if latest is None or latest < expected:
        line += f" -- MISSING: no proposal for {expected} yet (the nightly runs 03:30 America/Chicago; read logs/propose.log)"
    out.append(line)
    if os.path.exists(log_path):
        try:
            with open(log_path, encoding="utf-8", errors="replace") as fh:
                tail = [l.rstrip("\n") for l in fh][-LOG_TAIL:]
        except OSError:
            tail = []
        out.extend("  " + l for l in tail)
    else:
        out.append(f"  no {_short(log_path)} yet")
    return out


def _short(path):
    """A path under the repo as the repo-relative name the docs use; any other path as given."""
    rel = os.path.relpath(path, config.REPO)
    return path if rel.startswith("..") else rel


def render(rows, outs, t0, now, hb, halt_path, log, proposals_root, propose_log, current, excl_path=None):
    lines = [f"jev-paper-loop status at {now.strftime('%Y-%m-%dT%H:%MZ')} (health only, PREREG §8.4; nothing here is H1 or H2)",
             _age_line(hb, now), _halt_line(halt_path), _last_row_line(rows), _today_line(rows, now, log), _sample_line(t0, now)]
    lines.append(f"prompt_b CURRENT: {current or '?'}; rows {len(rows)} in the log")
    lines.extend(_days_lines(rows, outs, t0, now))
    if excl_path:
        lines.append(exclusions.status_line(excl_path))
    lines.extend(_nightly_lines(proposals_root, propose_log, now))
    return "\n".join(lines) + "\n"


def main(argv=None, now=None):
    ap = argparse.ArgumentParser(prog="python3 -m loop.status", description="the loop's health in one screen (report §1 only)")
    ap.add_argument("--log", default=config.DECISIONS)
    ap.add_argument("--t0", help="PREREG T0 (UTC minute or tick_id); default: read from PREREG.md §11")
    ap.add_argument("--prereg", default=dash.PREREG_PATH)
    ap.add_argument("--now", help="override the clock (tests): YYYY-MM-DDTHH:MM UTC")
    args = ap.parse_args(argv)
    try:
        t0 = report._t0(args.t0) if args.t0 else dash.read_t0(args.prereg)
    except ValueError:
        ap.error(f"--t0 wants YYYY-MM-DDTHH:MM (UTC) or a tick_id, got {args.t0!r}")
    if args.now:
        try:
            now = datetime.datetime.strptime(args.now, "%Y-%m-%dT%H:%M").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            ap.error(f"--now wants YYYY-MM-DDTHH:MM (UTC), got {args.now!r}")
    now = now or datetime.datetime.now(datetime.timezone.utc)
    unreadable = None
    try:
        rows = outcomes.load(args.log, [])
    except FileNotFoundError:
        rows = []
    except OSError as e:                                    # a 0200 log (write_row still appends), a directory, EIO,
                                                            # a data/ this user cannot enter (exists() says False there)
        rows, unreadable = [], f"LOG UNREADABLE: {args.log}: {e.strerror or e}; the next tick's spend guard trips (HALT) until it can be read\n"
    outs = outcomes.join(rows)
    text = (unreadable or "") + render(rows, outs, t0, now, dash.heartbeat(), config.HALT, args.log, config.PROPOSALS,
                  os.path.join(config.REPO, "logs", "propose.log"), dash.current_version(),
                                         os.path.join(config.DATA, "exclusions.tsv"))
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

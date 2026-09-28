"""One tick: guards -> feed -> state -> prompts -> (dry | ask) -> columns -> write -> heartbeat.

May: run the nine steps of CONTRACT §3 in that order, once (--once) or once a
minute on the wall clock (--forever), and print the would-be Jev body instead of
sending it (--dry). This is the only module that appends to data/decisions.jsonl,
writes data/HALT from inside a tick, touches data/heartbeat, or holds
data/loop.lock. May not: compute a position (book.py replays the log), act on a
confidence (rules.py derives columns; report.py compares them), retry the feed
or the model (feed never retries; jev retries once on its own terms), see the
key (jev.py names its path in the row, never its value), or open any file when
the resolved repo path sits under a forbidden prefix -- that check runs first
and exits 3, the one exit besides a usage error (2) that is not 0.

Every path past the path guard writes exactly one row; `absence` names the FIRST
step that did not happen:
  halt   the send, and only the send: data/HALT was present, or this tick tripped
         the spend guard and wrote it. HALT stops SENDS (PROTOCOL §3.8, SPEC §13.2):
         the lock, the feed, the state, rule_c and the prompt shas all still run and
         are logged, so the marks, arm C's rule and the t+h outcomes of the 15
         minutes before a HALT survive it. No ledger row, no request, no body printed.
         A feed or prompts failure under HALT keeps its own absence (it came first).
  lock   another process holds data/loop.lock (launchd double-fire)
  feed   FeedError, or state.py refusing the window (ValueError)
  jev    JevError (its kind in jev.error; 401/403 also write HALT), an answer the
         rules refuse (jev.error "parse", the raw answer still logged), the watchdog
         firing inside the send (jev.error "watchdog"), or any other exception once
         the send had begun (jev.error "unexpected"): the request may have left, so
         the spend guard must charge the row, and "guard" rows are charged nothing
  guard  anything else that stopped the tick before the send: prompts that do
         not load, the watchdog before the feed answered, an unexpected exception
The path guard writes nothing: a row under a forbidden tree is what it prevents.
SIGTERM mid-tick writes nothing either -- an operator stop is not a measurement
event -- unless the write has begun, in which case it completes, the lock is
released and the exit is 0.

Timing: --forever sleeps to the next multiple of CADENCE_S computed from
time.time() each round, so a slow tick shortens the next wait instead of
shifting every later tick. A 50 s SIGALRM watchdog wraps each tick (macOS has
no `timeout`): feed is 3 x 10 s and jev is 20 + 5 + 20 s, 75 s worst case, so
the alarm CAN land inside the send, and the row then says so.
"""
import argparse, fcntl, hashlib, json, os, signal, sys, time, traceback

from loop import config, feed, jev, prompts, rules, state

ROW_V = 1
EXIT_GUARD, EXIT_USAGE = 3, 2
WATCHDOG_S = 50         # < CADENCE_S = 60 so a hung tick can never overlap the next one
TAIL_BYTES = 8 << 20    # spend guard reads the log's tail: a day is 1,440 rows at ~2.5 KB = 3.6 MB,
                        # so 8 MB holds today twice over and the guard costs ~50 ms, not a 60 MB read
                        # of a 28-day log every minute
HALT_KEY_REJECTED = "key rejected"
HALT_SPEND = "spend"


class _Stop(BaseException):
    """SIGTERM. BaseException so feed's `except Exception` and jev's `except TRANSIENT`
    cannot swallow it on the way up to main()."""


class _Watchdog(BaseException):
    """SIGALRM after WATCHDOG_S inside a tick; tick() turns it into the absence row."""


_SIG = {"critical": False, "term": False}   # critical: the row write is in progress; signals wait


def _on_term(signum, frame):
    _SIG["term"] = True
    if not _SIG["critical"]:
        raise _Stop()


def _on_alarm(signum, frame):
    if not _SIG["critical"]:     # mid-write the tick is ending anyway: let the write land
        raise _Watchdog()


# ---- small pure helpers -----------------------------------------------------------------
def iso_ms(epoch):
    """The row's ts_rx shape, same as feed's: '2026-09-24T02:28:49.000Z'."""
    t = time.gmtime(epoch)
    return time.strftime("%Y-%m-%dT%H:%M:%S", t) + ".%03dZ" % (int(epoch * 1000) % 1000)


def tick_id(ts_rx):
    """ts_rx floored to the minute: '2026-09-24T02:28:49.000Z' -> '20260924T022800Z'."""
    return ts_rx[:4] + ts_rx[5:7] + ts_rx[8:10] + "T" + ts_rx[11:13] + ts_rx[14:16] + "00Z"


def forbidden(repo=None):
    """The forbidden prefix the resolved repo path sits under, or None. Both the literal
    prefix and its realpath are tried: ~/Projects could itself be a symlink one day and
    the guard must not depend on which spelling the shell used."""
    rp = os.path.realpath(repo or config.REPO)
    for p in config.FORBIDDEN_PREFIXES:
        for q in {p.rstrip(os.sep), os.path.realpath(p).rstrip(os.sep)}:
            if rp == q or rp.startswith(q + os.sep):
                return p
    return None


def spec_sha():
    """sha256 of SPEC.md's bytes, or "unsealed" until it exists: the row says which
    frozen definitions it was produced under, and "unsealed" rows are pre-registration."""
    try:
        with open(config.SPEC, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return "unsealed"


def _tail(path, nbytes):
    """(bytes, cut): the last `nbytes` of the file trimmed to whole lines; nbytes 0 = all."""
    with open(path, "rb") as fh:
        size = fh.seek(0, os.SEEK_END)
        start = max(0, size - nbytes) if nbytes else 0
        fh.seek(start)
        buf = fh.read()
    if start:
        buf = buf.split(b"\n", 1)[1] if b"\n" in buf else b""
    return buf, bool(start)


def _rows(buf):
    out = []
    for line in buf.splitlines():
        if line.strip():
            try:
                r = json.loads(line)
            except ValueError:
                continue                     # a truncated line (crash mid-write) costs one row
            if isinstance(r, dict):
                out.append(r)
    return out


UNSENT_KINDS = ("unsigned", "no-key", "ledger")   # JevError kinds raised before any request left: nothing billed


def billed_tokens(r):
    """Input tokens the spend guard charges one row. Logged tokens when positive. Otherwise,
    a live row that reached the model -- absence null, or absence "jev" with any kind but
    the two raised before a request -- is charged config.JEV_TOKENS_IF_UNKNOWN: jev.ask
    logs 0 when the reply has no `usage` and null when the send failed, and reading either
    as free would blind the tripwire exactly when the server stops reporting. Dry rows and
    the halt/lock/feed/guard absences never sent and cost 0."""
    j = r.get("jev") if isinstance(r.get("jev"), dict) else {}
    t = j.get("input_tokens")
    if isinstance(t, (int, float)) and not isinstance(t, bool) and t > 0:
        return t
    if r.get("mode") != "live":
        return 0
    ab = r.get("absence")
    if ab is None or (ab == "jev" and j.get("error") not in UNSENT_KINDS):
        return config.JEV_TOKENS_IF_UNKNOWN
    return 0


def spend_today(now, path=None):
    """USD of input tokens over today's rows (UTC date of `now`, matched on tick_id), each
    row charged billed_tokens(). Reads the tail (TAIL_BYTES) and widens to the whole file
    only when the tail's first row is already today's, i.e. today did not fit. A missing
    log is $0."""
    path = path or config.DECISIONS
    day = time.strftime("%Y%m%d", time.gmtime(now))
    try:
        buf, cut = _tail(path, TAIL_BYTES)
        rows = _rows(buf)
        if cut and rows and str(rows[0].get("tick_id", ""))[:8] == day:
            rows = _rows(_tail(path, 0)[0])
    except OSError:
        return 0.0
    tokens = sum(billed_tokens(r) for r in rows if str(r.get("tick_id", ""))[:8] == day)
    return tokens * config.USD_PER_MTOK / 1e6


def new_row(ts_rx, mode):
    """CONTRACT §2 Row, every key present, everything the tick has not filled null."""
    return {"v": ROW_V, "tick_id": tick_id(ts_rx), "ts_rx": ts_rx, "mode": mode,
            "venue": config.VENUE, "product": config.PRODUCT,
            "cadence_s": config.CADENCE_S, "horizon_s": config.HORIZON_S,
            "bid": None, "bid_size": None, "ask": None, "ask_size": None, "mid": None,
            "book_time": None, "feed_age_s": None,
            "features": None, "adj": None, "state": None, "spec_sha": spec_sha(),
            "prompt_a": None, "prompt_a_sha": None, "prompt_b": None, "prompt_b_sha": None,
            "model_requested": config.MODEL, "model_answered": None, "drift": False,
            "jev": {"latency_ms": None, "input_tokens": None, "error": None, "key_path": None},
            "answers": None, "rule_c": None, "columns": {"a": None, "b": None}, "absence": None}


# ---- files: lock, HALT, the row, the heartbeat ----------------------------------------------
def _lock():
    """data/loop.lock held for this tick, or None when another process has it. flock, not
    a pid file: the kernel drops it when the holder dies, so a crash never wedges the loop."""
    try:
        fh = open(config.LOCK, "a")
    except OSError:
        return None
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:                          # BlockingIOError (errno 35 here): held elsewhere
        fh.close()
        return None
    return fh


def _unlock(fh):
    if fh is not None:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def _halt(reason):
    """data/HALT with the reason. HALT stops SENDS (the next tick's guard); it is never
    removed by code -- a person deletes it after reading the reason."""
    try:
        with open(config.HALT, "w") as fh:
            fh.write(reason + "\n")
    except OSError as e:
        _err(f"cannot write {config.HALT}: {e}")


def _err(msg):
    print("cycle: " + msg, file=sys.stderr)


def write_row(row):
    """Atomic append: the whole line in ONE os.write on an O_APPEND fd, then fsync. A
    reader (report, nightly) or a crash can therefore see at most one truncated line,
    which outcomes.load() skips. NaN is allowed through rather than raised on: a
    non-finite feature must still cost only that feature, and every reader already
    checks isfinite. SIGTERM arriving inside is deferred until the heartbeat is written."""
    line = (json.dumps(row, separators=(",", ":")) + "\n").encode()
    _SIG["critical"] = True
    try:
        fd = os.open(config.DECISIONS, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            n = os.write(fd, line)
            while n < len(line):             # never on a regular file; the loop is the contract
                n += os.write(fd, line[n:])
            os.fsync(fd)
        finally:
            os.close(fd)
        tmp = config.HEARTBEAT + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(row["ts_rx"] + "\n")
        os.replace(tmp, config.HEARTBEAT)    # a watcher never reads a half-written heartbeat
    finally:
        _SIG["critical"] = False
    if _SIG["term"]:
        raise _Stop()


# ---- the tick ------------------------------------------------------------------------------
def _run(row, dry, halt=False):
    """Steps 2-7 of CONTRACT §3 into `row`. Every failure lands in row["absence"]; the
    caller writes the row whatever happened here. `halt`: steps 2-4 run as usual and the
    row is closed with absence "halt" where step 5/6 would begin -- nothing is printed,
    ledgered or sent."""
    stage = "feed"
    try:
        snap = feed.snapshot()
        row["ts_rx"], row["tick_id"] = snap["ts_rx"], tick_id(snap["ts_rx"])
        row.update(bid=snap["bid"], bid_size=snap["bid_size"], ask=snap["ask"],
                   ask_size=snap["ask_size"], book_time=snap["book_time"],
                   feed_age_s=snap["feed_age_s"])
        stage = "state"
        feat = state.features(snap)
        adj = state.adjectives(feat)
        s = state.state_string(adj)
        row.update(mid=feat["mid"], features=feat, adj=adj, state=s, rule_c=state.rule_c(adj))
        stage = "prompts"
        v1, cur = prompts.load("v1"), prompts.current()
        curdoc = prompts.load(cur)
        qs = prompts.build(v1, curdoc)
        row.update(prompt_a="v1", prompt_a_sha=prompts.sha_of(v1),
                   prompt_b=cur, prompt_b_sha=prompts.sha_of(curdoc))
        if halt:                             # HALT stops SENDS only: everything above is the observation
            row["absence"] = "halt"
            return
        if dry:                              # the free thing: the exact body, on stdout, unsent
            print(json.dumps(jev.dry_payload(s, qs)))
            return
        stage = "ask"
        res = jev.ask(s, qs)
        row["jev"].update(latency_ms=res["latency_ms"], input_tokens=res["input_tokens"],
                          key_path=res["key_path"])
        row.update(answers=res["answers"], model_answered=res["model"],
                   drift=res["model"] != config.MODEL)
        stage = "columns"
        row["columns"] = {"a": rules.for_arm(res["answers"], "a"),
                          "b": rules.for_arm(res["answers"], "b")}
    except feed.FeedError as e:
        row["absence"] = "feed"
        _err(f"feed: {e}")
    except jev.JevError as e:
        row["absence"], row["jev"]["error"], row["jev"]["key_path"] = "jev", e.kind, e.key_path
        _err(f"jev: {e}")                    # kind and detail; a key's PATH at most, never a value
        if e.status in (401, 403):
            _halt(f"{HALT_KEY_REJECTED}: {e.kind} {e.status} via {e.key_path} at {row['ts_rx']}")
    except prompts.PromptError as e:         # a ValueError subclass: must precede the next clause
        row["absence"] = "guard"
        _err(f"prompts: {e}")
    except ValueError as e:
        if stage == "columns":               # a choice outside buy/sell/hold, a bool or non-finite
            row["absence"], row["jev"]["error"] = "jev", "parse"   # field: the answer is logged, the columns are not
        elif stage == "ask":                 # past the ledger row: the request may have left
            row["absence"], row["jev"]["error"] = "jev", "unexpected"
        else:
            row["absence"] = "feed" if stage == "state" else "guard"
        _err(f"{stage}: {e}")
    except _Watchdog:
        if stage == "ask":
            row["absence"], row["jev"]["error"] = "jev", "watchdog"
        else:
            row["absence"] = "feed" if stage == "feed" else "guard"
        _err(f"watchdog: {WATCHDOG_S} s passed during {stage}")
    except Exception as e:
        if stage == "columns" and isinstance(e, (TypeError, AttributeError)):
            # a field of the wrong type (a null confidence, probabilities "x"): jev._parse checks
            # only that the fields exist, so the rules refuse it here, exactly as a bad choice
            row["absence"], row["jev"]["error"] = "jev", "parse"
            _err(f"columns: {type(e).__name__}: {e}")
            return
        if stage in ("ask", "columns"):      # the send had begun: "guard" would bill it $0 (billed_tokens)
            row["absence"], row["jev"]["error"] = "jev", "unexpected"
        else:
            row["absence"] = "guard"
        _err(f"unexpected during {stage}:\n" + traceback.format_exc())


def _summary(row):
    a = (row["columns"].get("a") or {}).get("argmax")
    b = (row["columns"].get("b") or {}).get("argmax")
    j = row["jev"]
    adj = row["adj"] or {}
    return (f"cycle {row['tick_id']} {row['mode']} {row['absence'] or 'ok'}"
            f" state={' '.join(adj.get(d, '-') for d in ('liq', 'flow', 'trend', 'vol'))}"
            f" c={row['rule_c']} a={a} b={b} jev={j['latency_ms']}ms/{j['input_tokens']}tok"
            f" err={j['error']} key={j['key_path']}{' DRIFT' if row['drift'] else ''}")


def _finish(row):
    try:
        write_row(row)
    except OSError as e:
        _err(f"row NOT written ({e}); the tick is lost")   # exit stays 0: the loop must go on
    _err(_summary(row))
    return 0


def tick(dry=False, now=None):
    """One tick in CONTRACT §3 order. Returns the exit code: EXIT_GUARD before any file
    is touched, otherwise 0. `now` (epoch s) pins the clock for tests."""
    p = forbidden()
    if p:
        _err(f"refusing to run under {p}; exit {EXIT_GUARD}")
        return EXIT_GUARD
    t0 = time.time() if now is None else float(now)
    row = new_row(iso_ms(t0), "dry" if dry else "live")
    try:
        os.makedirs(config.DATA, exist_ok=True)   # gitignored: a fresh clone has none
    except OSError as e:
        _err(f"cannot create {config.DATA}: {e}")
        return 0
    halt = os.path.exists(config.HALT)      # HALT stops SENDS; the observation below still runs
    if not halt:
        usd = spend_today(t0)
        if usd >= config.DAILY_SPEND_HALT_USD:
            _halt(f"{HALT_SPEND}: ${usd:.4f} of input tokens today >= "
                  f"${config.DAILY_SPEND_HALT_USD} (config.DAILY_SPEND_HALT_USD) at {row['ts_rx']}")
            halt = True
    lk = _lock()
    if lk is None:
        row["absence"] = "lock"
        return _finish(row)
    try:
        _run(row, dry, halt)
        return _finish(row)
    finally:
        _unlock(lk)


def _guarded_tick(dry):
    """tick() under the watchdog. An alarm that escapes tick() fired in the guards, before
    any row could be owed; it is reported and the round ends with 0."""
    signal.alarm(WATCHDOG_S)
    try:
        return tick(dry)
    except _Watchdog:
        _err(f"watchdog: {WATCHDOG_S} s passed in the guards; no row")
        return 0
    finally:
        signal.alarm(0)


def _sleep_to_boundary():
    """Sleep to the next multiple of CADENCE_S on the wall clock, recomputed from
    time.time() every round: no accumulated drift, and a 1.3 s tick still fires the
    next one at :00. Loops until the clock has actually crossed the boundary:
    time.sleep can return early (measured 2026-09-24: woke at :59.910 twice in 181
    ticks), and a tick started before :00 floors to the minute just done -- a
    duplicate send, and the next minute never recorded."""
    nxt = (int(time.time()) // config.CADENCE_S + 1) * config.CADENCE_S
    while True:
        left = nxt - time.time()
        if left <= 0:
            return
        time.sleep(left)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m loop.cycle",
                                 description="one tick of the paper loop (CONTRACT.md §3)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true", help="one tick, then exit")
    g.add_argument("--forever", action="store_true",
                   help="a tick at every wall-clock minute until SIGTERM")
    ap.add_argument("--dry", action="store_true",
                    help="no ledger row, no send: print the would-be body, log the row as dry")
    a = ap.parse_args(argv)                  # argparse exits 2 on a usage error
    p = forbidden()
    if p:                                    # before a handler, a directory, or a file
        _err(f"refusing to run under {p}; exit {EXIT_GUARD}")
        return EXIT_GUARD
    _SIG["term"] = _SIG["critical"] = False
    old = signal.signal(signal.SIGTERM, _on_term), signal.signal(signal.SIGALRM, _on_alarm)
    try:
        if a.once:
            return _guarded_tick(a.dry)
        while True:                          # aligned first: a tick at :37 would be one odd row
            _sleep_to_boundary()
            code = _guarded_tick(a.dry)
            if code or _SIG["term"]:
                return code
    except _Stop:
        return 0
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGTERM, old[0])
        signal.signal(signal.SIGALRM, old[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

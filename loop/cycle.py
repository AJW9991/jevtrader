"""One tick: guards -> feed -> state -> prompts -> (dry | ask) -> columns -> write -> heartbeat.

May: run the nine steps of CONTRACT §3 in that order, once (--once) or once a
minute on the wall clock (--forever), and print the would-be Jev body instead of
sending it (--dry). This is the only module that appends to a decision log,
writes data/HALT from inside a tick, touches a heartbeat, or holds a loop lock.
One process ticks one product (PREREG-v2 §2): JEVLOOP_PRODUCT names it (unset:
SOL-USD, whose store is v1's data/decisions.jsonl, data/sends.tsv, data/loop.lock
and data/heartbeat; any other product in config.PRODUCTS has the same four under
data/<PRODUCT>/), and a value outside config.PRODUCTS exits 2 before any directory
is made. data/HALT stops every product's sends; data/PAUSE.<PRODUCT> stops only this
product's, with the same absence "halt", and the spend guard, which sums every
product's decision log, ignores it. May not: compute a position (book.py replays the log), act on a
confidence (rules.py derives columns; report.py compares them), retry the feed
or the model (feed never retries; jev retries once on its own terms), see the
key (jev.py names its path in the row, never its value), or open any file when
the resolved repo path sits under a forbidden prefix -- that check runs first
and exits 3, the one exit besides a usage error (2) that is not 0.

Every tick past the path guard and data/ writes exactly one row (a HALT, spend-trip or
lock row included) unless SIGTERM stops it before the write begins, the watchdog lands in
the guards before the lock, or the append itself fails (logged, exit 0); `absence` names
the FIRST step that did not happen:
  halt   the send, and only the send: data/HALT was present, or this tick tripped
         the spend guard and wrote it, or data/PAUSE.<PRODUCT> was present (that product
         only). HALT stops SENDS (PROTOCOL §3.8, SPEC §13.2):
         the lock, the feed, the state, rule_c and the prompt shas all still run and
         are logged, so the marks, arm C's rule and the t+h outcomes of the 15
         minutes before a HALT survive it. No ledger row, no request, no body printed.
         A feed or prompts failure under HALT keeps its own absence (it came first).
  lock   another process holds data/loop.lock (launchd double-fire)
  feed   FeedError, state.py refusing the window (ValueError), or the watchdog
         firing while the feed was still fetching
  jev    JevError (its kind in jev.error; 401/403 also write HALT), an answer the
         rules refuse (jev.error "parse", the raw answer still logged), the watchdog
         firing inside the send or while its answer became columns (jev.error
         "watchdog", no answer kept), or any other exception once the send had begun
         (jev.error "unexpected"): the request may have left, so the spend guard must
         charge the row, and "guard" rows are charged nothing
  guard  anything else that stopped the tick before the send: prompts that do
         not load, the watchdog after the feed answered (state, prompts), an
         unexpected exception
The path guard writes nothing: a row under a forbidden tree is what it prevents.
SIGTERM mid-tick writes nothing either -- an operator stop is not a measurement
event -- unless the write has begun, in which case it completes, the lock is
released and the exit is 0.

Timing: --forever sleeps to the next multiple of CADENCE_S computed from
time.time() each round, so a slow tick shortens the next wait instead of
shifting every later tick. --once (launchd's calendar minute) sleeps to the
boundary first only when it starts in a minute's last 2 s AND data/heartbeat shows
this minute already has its row (a late fire keeps its minute). A 50 s SIGALRM
watchdog wraps each tick (macOS has no `timeout`): feed is 3 x 10 s and jev is
20 + 5 + 20 s, 75 s worst case, so the alarm CAN land inside the send, and the
row then says so. Past the lock the
row is written wherever the alarm lands (inside _run's handlers too); the write
disarms it. In the guards before the lock it costs the row, never the exit code.
"""
import argparse, fcntl, hashlib, json, math, os, signal, sys, time, traceback

SPEND_UNCOUNTED = sys.float_info.max   # spend_today: a token count, or today's sum of them, past a float's range (over any limit; not 'unreadable')

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
    the guard must not depend on which spelling the shell used. Then by identity, since
    realpath does not unify every second name for one directory: each existing ancestor of
    the resolved path, the path itself included, is compared with each existing prefix by
    (st_dev, st_ino). That knows the tree by a second name that keeps its device and inode,
    for the tree itself or for one of its ancestors (on the Mac a case-only difference on
    case-insensitive APFS, or the /System/Volumes/Data firmlink; on Linux a bind mount of the
    tree or of a directory above it). It does not know a name with a device of its own (an
    overlay, an NFS or SMB loopback mount, a FUSE mirror such as bindfs: the same files under
    another st_dev), nor a second name for a directory inside the tree (a bind mount of a
    subdirectory, say: the path's ancestors are then that directory's, never the tree's);
    either would take a walk of the tree or the mount table. None of these is on the Mac as
    set up (STEPS). That is a stat per prefix and per ancestor, never a walk of a tree;
    a prefix or an ancestor that does not exist or cannot be stat-ed is skipped by it (the
    string match above still applies)."""
    rp = os.path.realpath(repo or config.REPO)
    for p in config.FORBIDDEN_PREFIXES:
        for q in {p.rstrip(os.sep), os.path.realpath(p).rstrip(os.sep)}:
            if rp == q or rp.startswith(q + os.sep):
                return p
    ids = []
    for p in config.FORBIDDEN_PREFIXES:
        try:
            st = os.stat(p)
        except (OSError, ValueError):
            continue
        ids.append(((st.st_dev, st.st_ino), p))
    a = rp
    while ids:
        try:
            st = os.stat(a)
        except (OSError, ValueError):
            pass
        else:
            for key, p in ids:
                if key == (st.st_dev, st.st_ino):
                    return p
        up = os.path.dirname(a)
        if up == a:
            break
        a = up
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
                continue                     # a truncated line (crash mid-write) costs that one row:
                                             # write_row starts the next row on a fresh line
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
    """USD of input tokens over today's rows (UTC date of `now`, matched on tick_id), each row
    charged billed_tokens(), in the one log `path` or, without one, summed over every product's
    decision log (config.store(p).decisions for p in config.PRODUCTS: PREREG-v2 §2's one tripwire).
    Over several logs an unreadable one is math.inf and one past a float's range SPEND_UNCOUNTED,
    whatever the others hold; a sum past a float's range is SPEND_UNCOUNTED."""
    if path is not None:
        return _spend_one(now, path)
    each = [_spend_one(now, config.store(p).decisions) for p in config.PRODUCTS]
    if math.inf in each:
        return math.inf
    if SPEND_UNCOUNTED in each:
        return SPEND_UNCOUNTED
    usd = sum(each)
    return SPEND_UNCOUNTED if usd == math.inf else usd


def _spend_one(now, path):
    """USD of input tokens over today's rows of one log (UTC date of `now`, matched on tick_id), each
    row charged billed_tokens(). Reads the tail (TAIL_BYTES) and widens to the whole file
    only when the tail's first row is already today's, i.e. today did not fit. A missing
    log is $0. A log that exists but cannot be read (a 0200 mode or an ACL, which write_row
    still appends to; a directory; an I/O error) is math.inf: the guard cannot count, so it
    trips and nothing is sent, as the ledger fails closed. A count, or today's sum of them, past
    a float's range is SPEND_UNCOUNTED, in whatever order and of whatever type the counts are."""
    day = time.strftime("%Y%m%d", time.gmtime(now))
    try:
        buf, cut = _tail(path, TAIL_BYTES)
        rows = _rows(buf)
        if cut and rows and str(rows[0].get("tick_id", ""))[:8] >= day:   # today's first rows may lie before the tail,
                                                                            # behind rows stamped later (a clock stepped back)
            rows = _rows(_tail(path, 0)[0])
    except FileNotFoundError:
        return 0.0                  # no log yet: nothing spent
    except OSError:
        return math.inf             # it exists and cannot be read: the spend cannot be counted
    try:
        tokens = sum(billed_tokens(r) for r in rows if str(r.get("tick_id", ""))[:8] == day)   # in the try: two int counts
                                            # of 1e308 sum to an int no float holds, and a float count after them raises here
        usd = tokens * config.USD_PER_MTOK / 1e6
    except OverflowError:                   # a server-reported count past a float's range, or counts that each fit one
                                            # and sum past it: over any limit,
        return SPEND_UNCOUNTED              # and a raise here would cost every later tick of the day its row
    return SPEND_UNCOUNTED if usd == math.inf else usd   # float counts (a foreign row's) that sum to inf, or a logged
                                            # Infinity: the same sum past a float's range, not a log that cannot be read


def null_columns():
    """The columns of a row that did not reach step 7: every arm null, D's included (SPEC §2)."""
    return {"a": None, "b": None, "d": None}


def new_row(ts_rx, mode, product=None):
    """CONTRACT §2 Row, every key present, everything the tick has not filled null. v2 adds
    `table_sha` (the canonical sha of the CURRENT version's table for the product, null when none)
    and `columns.d` (that table's answer for the state, arm D), PREREG-v2 §10."""
    return {"v": ROW_V, "tick_id": tick_id(ts_rx), "ts_rx": ts_rx, "mode": mode,
            "venue": config.VENUE, "product": product or config.PRODUCT,
            "cadence_s": config.CADENCE_S, "horizon_s": config.HORIZON_S,
            "bid": None, "bid_size": None, "ask": None, "ask_size": None, "mid": None,
            "book_time": None, "feed_age_s": None,
            "features": None, "adj": None, "state": None, "spec_sha": spec_sha(),
            "prompt_a": None, "prompt_a_sha": None, "prompt_b": None, "prompt_b_sha": None, "table_sha": None,
            "model_requested": config.MODEL, "model_answered": None, "drift": False,
            "jev": {"latency_ms": None, "input_tokens": None, "error": None, "key_path": None},
            "answers": None, "rule_c": None, "columns": null_columns(), "absence": None}


# ---- files: lock, HALT, the row, the heartbeat ----------------------------------------------
def _lock(path=None):
    """The product's loop.lock (config.LOCK, SOL-USD's, by default) held for this tick, or None when
    another process has it. flock, not a pid file: the kernel drops it when the holder dies, so a crash
    never wedges the loop."""
    try:
        fh = open(path or config.LOCK, "a")
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


def _heartbeat(ts_rx, path=None):
    """The product's heartbeat (config.HEARTBEAT by default) = ts_rx, replaced whole, so a watcher
    never reads a half-written one.
    Called once the row is on disk, so a failure here is its own message and never the
    row's: the row IS in the log. The temporary name is per pid: a lock-row writer and the
    lock holder can both be here in the same second, and a shared name let one rename the
    other's file away (or away from under it)."""
    path = path or config.HEARTBEAT
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w") as fh:
            fh.write(ts_rx + "\n")
        os.replace(tmp, path)
    except OSError as e:
        _err(f"heartbeat NOT written ({e}); the row is")
        try:
            os.remove(tmp)
        except OSError:
            pass


def write_row(row, store=None):
    """Atomic append to the product's decision log (store: config.store(p); SOL-USD's by default),
    then its heartbeat: the whole line in ONE os.write on an O_APPEND fd, then fsync. A
    reader (report, nightly) or a crash can therefore see at most one truncated line,
    which outcomes.load() skips. A torn last line (a short write on a full disk, a crash
    mid-write) is closed first: when the file does not end in a newline this row goes
    out as "\\n" + line, so the torn line costs itself only, instead of gluing the next
    healthy row onto it and costing both. Never a truncate: lock rows are appended
    without the lock, and a race costs at most a blank line, which every reader skips.
    NaN is allowed through rather than raised on: a non-finite feature must still cost
    only that feature, and every reader already checks isfinite. SIGTERM arriving
    inside is deferred until the heartbeat is written. The critical section opens before
    the row is serialised and disarms the watchdog first: the tick is ending anyway, and
    an alarm landing in json.dumps or just after the write would otherwise lose the row."""
    _SIG["critical"] = True
    try:
        signal.alarm(0)
        log, beat = (store.decisions, store.heartbeat) if store is not None else (config.DECISIONS, config.HEARTBEAT)
        line = (json.dumps(row, separators=(",", ":")) + "\n").encode()
        try:
            fd = os.open(log, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o644)   # RDWR: pread below
            readable = True
        except PermissionError:              # writable but not readable (a 0200 log, an ACL): append as before,
            fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)   # without the torn-line check
            readable = False
        try:
            if readable:
                size = os.fstat(fd).st_size
                if size and os.pread(fd, 1, size - 1) != b"\n":
                    line = b"\n" + line      # close the torn line; the bytes before it stay as they are
            n = os.write(fd, line)
            while n < len(line):             # never on a regular file; the loop is the contract
                n += os.write(fd, line[n:])
            os.fsync(fd)
        finally:
            os.close(fd)
        _heartbeat(row["ts_rx"], beat)
    finally:
        _SIG["critical"] = False
    if _SIG["term"]:
        raise _Stop()


# ---- the tick ------------------------------------------------------------------------------
def _watchdog_absence(row, stage):
    """The row of a tick the watchdog stopped at `stage`. From "ask" on, the request may have
    left: jev/watchdog, which the spend guard bills, keeping no answer and no column (SPEC §2
    keeps answers on a parse row only). During the feed: feed. Otherwise: guard."""
    if stage in ("ask", "columns"):
        row["absence"], row["jev"]["error"] = "jev", "watchdog"
        row["answers"], row["columns"] = None, null_columns()
    else:
        row["absence"] = "feed" if stage == "feed" else "guard"


def _table(version, product):
    """The CURRENT version's table for the product (prompts.table), or None when it is absent or
    refused: arm D and table_sha are then null and the tick goes on, A, B and C untouched (a null
    columns.d is a hold for D only, PREREG-v2 §10's book bullet). A refusal is said on stderr, and so is
    any other failure to read it (a RecursionError from a file nested past the decoder's depth, a
    MemoryError): the table is D's alone, so nothing it does may cost the other arms."""
    try:
        return prompts.table(version, product)
    except ValueError as e:                  # PromptError included
        _err(f"table: {e}; columns.d and table_sha null")
    except Exception as e:                   # not BaseException: the watchdog and SIGTERM still stop the tick
        _err(f"table: {type(e).__name__}: {e}; columns.d and table_sha null")
    return None


def _run(row, dry, halt=False, where=None, product=None, store=None):
    """Steps 2-7 of CONTRACT §3 into `row` for `product` (SOL-USD by default). Every failure lands in
    row["absence"]; the caller writes the row whatever happened here. `halt`: steps 2-4 run as usual
    and the row is closed with absence "halt" where step 5/6 would begin -- nothing is printed,
    ledgered or sent. `where` (a dict) receives the stage reached and, after a 401/403,
    the HALT reason: the watchdog can fire inside one of the handlers below, and tick()
    then closes the row and writes that HALT from them. `store` names the sends ledger."""
    where = {} if where is None else where
    product = product or config.PRODUCT
    base = config.base(product)
    stage = where["stage"] = "feed"
    try:
        snap = feed.snapshot(product)
        row["ts_rx"], row["tick_id"] = snap["ts_rx"], tick_id(snap["ts_rx"])
        row.update(bid=snap["bid"], bid_size=snap["bid_size"], ask=snap["ask"],
                   ask_size=snap["ask_size"], book_time=snap["book_time"],
                   feed_age_s=snap["feed_age_s"])
        stage = where["stage"] = "state"
        feat = state.features(snap)
        adj = state.adjectives(feat, product)
        s = state.state_string(adj, base)
        row.update(mid=feat["mid"], features=feat, adj=adj, state=s, rule_c=state.rule_c(adj))
        stage = where["stage"] = "prompts"
        cur = prompts.current(row["tick_id"])        # the version B asks at THIS tick (PREREG-v2 §8)
        v1, frozen, curdoc = prompts.load("v1"), prompts.load(config.FROZEN_A), prompts.load(cur)
        qs = prompts.build(frozen, curdoc, base, v1=v1)
        row.update(prompt_a=config.FROZEN_A, prompt_a_sha=prompts.sha_of(frozen),
                   prompt_b=cur, prompt_b_sha=prompts.sha_of(curdoc))
        tab = _table(cur, product)                   # arm D: no call, the CURRENT table looked up by the state
        row["table_sha"] = tab["sha"] if tab else None
        d = tab["answers"].get(s) if tab else None
        if halt:                             # HALT stops SENDS only: everything above is the observation
            row["absence"] = "halt"
            return
        if dry:                              # the free thing: the exact body, on stdout, unsent
            print(json.dumps(jev.dry_payload(s, qs)))
            return
        stage = where["stage"] = "ask"
        res = jev.ask(s, qs, store.sends if store is not None else None)
        row["jev"].update(latency_ms=res["latency_ms"], input_tokens=res["input_tokens"],
                          key_path=res["key_path"])
        row.update(answers=res["answers"], model_answered=res["model"],
                   drift=res["model"] != config.MODEL)
        stage = where["stage"] = "columns"
        row["columns"] = {"a": rules.for_arm(res["answers"], "a"),
                          "b": rules.for_arm(res["answers"], "b"), "d": d}
    except feed.FeedError as e:
        row["absence"] = "feed"
        _err(f"feed: {e}")
    except jev.JevError as e:
        row["absence"], row["jev"]["error"], row["jev"]["key_path"] = "jev", e.kind, e.key_path
        if e.status in (401, 403):           # recorded before any call: see `where` above
            where["halt"] = f"{HALT_KEY_REJECTED}: {e.kind} {e.status} via {e.key_path} at {row['ts_rx']}"
        _err(f"jev: {e}")                    # kind and detail; a key's PATH at most, never a value
        if "halt" in where:
            _halt(where["halt"])
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
    except _Watchdog:                        # at "columns" too: the send had left and is billed
        _watchdog_absence(row, stage)
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


def _finish(row, store=None):
    try:
        write_row(row, store)
    except OSError as e:
        _err(f"row NOT written ({e}); the tick is lost")   # exit stays 0: the loop must go on
    _err(_summary(row))
    return 0


def tick(dry=False, now=None, product=None):
    """One tick of `product` (SOL-USD by default; main() passes JEVLOOP_PRODUCT's) in CONTRACT §3
    order. Returns the exit code: EXIT_GUARD before any file is touched, otherwise 0. `now` (epoch s)
    pins the clock for tests."""
    p = forbidden()
    if p:
        _err(f"refusing to run under {p}; exit {EXIT_GUARD}")
        return EXIT_GUARD
    product = product or config.PRODUCT
    st = config.store(product)
    t0 = time.time() if now is None else float(now)
    row = new_row(iso_ms(t0), "dry" if dry else "live", product)
    here = os.path.dirname(st.decisions)
    try:
        os.makedirs(here, exist_ok=True)     # gitignored: a fresh clone has none (data/, or data/<PRODUCT>/)
    except OSError as e:
        _err(f"cannot create {here}: {e}")
        return 0
    halt = os.path.exists(config.HALT)      # HALT stops SENDS; the observation below still runs
    if not halt:                             # the spend guard ignores PAUSE (PREREG-v2 §2)
        usd = spend_today(t0)
        if usd == math.inf:
            logs = ", ".join(config.store(q).decisions for q in config.PRODUCTS)
            _halt(f"{HALT_SPEND}: a decision log ({logs}) exists but cannot be read, so today's spend cannot be counted"
                  f" against ${config.DAILY_SPEND_HALT_USD} (config.DAILY_SPEND_HALT_USD) at {row['ts_rx']}; make it readable")
            halt = True
        elif usd == SPEND_UNCOUNTED:
            _halt(f"{HALT_SPEND}: today's input_tokens (one logged count, or the sum of today's counts) is past a float's range"
                  f" (the server reported them), over ${config.DAILY_SPEND_HALT_USD} (config.DAILY_SPEND_HALT_USD) whatever the rest is,"
                  f" at {row['ts_rx']}")
            halt = True
        elif usd >= config.DAILY_SPEND_HALT_USD:
            _halt(f"{HALT_SPEND}: ${usd:.4f} of input tokens today >= "
                  f"${config.DAILY_SPEND_HALT_USD} (config.DAILY_SPEND_HALT_USD) at {row['ts_rx']}")
            halt = True
    paused = os.path.exists(config.pause(product))   # this product's sends only; observation goes on
    if paused and not halt:
        _err(f"{config.pause(product)} present: {product}'s send skipped (absence halt)")
    lk = _lock(st.lock)
    try:
        if lk is None:
            row["absence"] = "lock"
        else:
            where = {}
            try:
                _run(row, dry, halt or paused, where, product, st)
            except _Watchdog:                # fired inside one of _run's own handlers (a 401's _halt,
                if row["absence"] is None:   # an _err to a stalled stderr); the one alarm is now spent.
                    _watchdog_absence(row, where.get("stage"))   # an absence already set stays: it came first
                if "halt" in where:
                    _halt(where["halt"])     # the key-rejected HALT the handler may not have written
                _err(f"watchdog: {WATCHDOG_S} s passed while handling {where.get('stage')}")
        _SIG["critical"] = True              # the row is complete: an alarm from here on is ignored and
        return _finish(row, st)              # SIGTERM waits for the write (write_row clears the flag)
    finally:
        _unlock(lk)


def _guarded_tick(dry, product=None):
    """tick() under the watchdog, armed and disarmed inside one outer try, so that no alarm
    can leave this function (main() would exit 1 with a traceback). An alarm that escapes
    tick() fired in the guards, before the lock, when no row is owed yet: it is reported
    and the round ends with 0. One that lands in the finally, after tick() returned and
    before alarm(0) ran, finds the tick over and is dropped; tick()'s code stands."""
    code = 0
    try:
        try:
            signal.alarm(WATCHDOG_S)
            code = tick(dry, product=product)
        except _Watchdog:
            _err(f"watchdog: {WATCHDOG_S} s passed in the guards; no row")
        finally:
            signal.alarm(0)
    except _Watchdog:
        pass
    return code


def _this_minute_has_its_row(now, path=None):
    """True when data/heartbeat names a row in the minute `now` is in: a --once fire in that
    minute's last seconds is then launchd being EARLY for the next minute (the pre-sleep case),
    not late for this one. A heartbeat from another minute, or none, means this minute is
    still owed its row and the tick runs at once (a RunAtLoad or a wake can land at any
    second of a minute; sleeping there would tick the next minute instead)."""
    try:
        with open(path or config.HEARTBEAT) as fh:
            hb = fh.read().strip()
    except OSError:
        return False
    return len(hb) >= 16 and tick_id(hb) == tick_id(iso_ms(now))


def _sleep_to_boundary(now=None):
    """Sleep to the next multiple of CADENCE_S after `now` (the clock, by default) on the wall clock, recomputed from
    time.time() every round: no accumulated drift, and a 1.3 s tick still fires the
    next one at :00. Loops until the clock has actually crossed the boundary:
    time.sleep can return early (measured 2026-09-24: woke at :59.910 twice in 181
    ticks), and a tick started before :00 floors to the minute just done -- a
    duplicate send, and the next minute never recorded. `now` is the clock a caller already
    read: a --once fire at :59.9999 must wake at the :00 a hair away, not the one after it, if
    the boundary passed between the caller's read and this one (that cost the minute a row)."""
    nxt = (int(time.time() if now is None else now) // config.CADENCE_S + 1) * config.CADENCE_S
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
    try:
        product = config.loop_product()      # JEVLOOP_PRODUCT, unset: SOL-USD (PREREG-v2 §2)
    except ValueError as e:                  # before any directory is made
        _err(f"{e}; exit {EXIT_USAGE}")
        return EXIT_USAGE
    beat = config.store(product).heartbeat
    _SIG["term"] = _SIG["critical"] = False
    old = signal.signal(signal.SIGTERM, _on_term), signal.signal(signal.SIGALRM, _on_alarm)
    try:
        if a.once:                           # launchd's StartCalendarInterval can fire a hair before :00;
            now = time.time()                # started there, the tick would floor to the minute just done
            if now % config.CADENCE_S > config.CADENCE_S - 2 and _this_minute_has_its_row(now, beat):
                _sleep_to_boundary(now)      # (only when this minute already has its row: a late fire keeps its minute)
            return _guarded_tick(a.dry, product)
        while True:                          # aligned first: a tick at :37 would be one odd row
            _sleep_to_boundary()
            code = _guarded_tick(a.dry, product)
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

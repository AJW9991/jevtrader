"""nightly: the digest lists the right arm-B disagreements in the right order and
leaks no feature; the policy table enumerates 81 digit-free states and sends nothing
in --dry; promote refuses on a dirty tree and carries v1's three nouls byte for byte;
propose.sh --dry turns the fixture reply into a proposals json. Offline: loop.jev.ask
is mocked wherever the table is run, subprocess.run is mocked for git, and every
write lands in a temp dir. Nothing here opens a socket."""
import ast, datetime, hashlib, importlib.util, io, json, os, plistlib, re, shutil, signal, subprocess, sys, tempfile, time, unittest, urllib.request
from contextlib import redirect_stdout
from unittest import mock

from fixture_prompts import pin_v1
from loop import config, jev, prompts, rules, state
from nightly import digest, policy_table

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = datetime.date(2026, 9, 22)
T0 = datetime.datetime(2026, 9, 22, 10, 0, 0, tzinfo=datetime.timezone.utc)
ADJ = {"liq": "deep", "flow": "quiet", "trend": "pumping", "vol": "normal"}
STATE = state.state_string(ADJ)
NOUL = {"noul": 0.0}


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _answer(choice, conf):
    p = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
    p[choice] = conf
    return {"choice": choice, "probabilities": p, "confidence": conf}


def _row(minute, mid, b=None, absence=None):
    """A CONTRACT §2 row at T0 + minute. b = (choice, confidence) for b_action; a_action
    is always hold. absence rows carry null answers and a null mid."""
    d = T0 + datetime.timedelta(minutes=minute)
    answers = None if absence or b is None else {
        "a_action": _answer("hold", 0.9), "b_action": _answer(*b), "skip": NOUL, "up15": NOUL, "down15": NOUL}
    return {"v": 1, "tick_id": d.strftime("%Y%m%dT%H%M00Z"), "ts_rx": _iso(d), "mode": "live",
            "venue": "coinbase", "product": "SOL-USD", "cadence_s": 60, "horizon_s": 900,
            "bid": None if mid is None else mid - 0.01, "ask": None if mid is None else mid + 0.01,
            "mid": mid, "features": {"ret15_z": 1.7, "rv_ratio": 0.9}, "adj": ADJ, "state": STATE,
            "answers": answers, "rule_c": "buy",
            "columns": {"a": rules.for_arm(answers, "a"), "b": rules.for_arm(answers, "b")},
            "absence": absence}


def synthetic_log():
    """41 minutes. Mids are 100 except at the six t+15 rows that resolve minutes 0..5:
      0 buy 0.95 -> down   listed (1st)      3 buy 0.80 -> down  below the cut
      1 sell 0.90 -> up    listed (2nd)      4 hold 0.99 -> down hold is never listed
      2 buy 0.99 -> up     correct           5 sell 0.86 -> up   listed (3rd)
    plus an absence row at minute 6 (null answers, null mid) and a sell at 0.97 at
    minute 30 whose t+15 is past the log (gap: never listed)."""
    mids = {15: 99.85, 16: 100.15, 17: 100.20, 18: 99.80, 19: 99.80, 20: 100.10}
    b = {0: ("buy", 0.95), 1: ("sell", 0.90), 2: ("buy", 0.99), 3: ("buy", 0.80), 4: ("hold", 0.99),
         5: ("sell", 0.86), 30: ("sell", 0.97)}
    rows = []
    for m in range(41):
        if m == 6:
            rows.append(_row(m, None, absence="feed"))
        else:
            rows.append(_row(m, mids.get(m, 100.0), b.get(m, ("hold", 0.6))))
    return rows


def _write_log(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


PROXY_VARS = ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY")


class Reached(BaseException):
    """A wall a test put up was reached. BaseException: no `except Exception` on the way can swallow it."""


def _sh_env(tc, tmp=None, **extra):
    """propose.sh's (or a nightly script's) environment for the test `tc`. JEVLOOP_PY is the
    interpreter running the suite (under `make test` on the Mac that is /opt/homebrew/bin/python3,
    the script's default); on a host with no /usr/bin/caffeinate (a Linux checkout, CI)
    JEVLOOP_CAFFEINATE is a stub in `tmp` that drops `-i` and runs the command, so the live branch
    can be driven there too.
    Nothing started with it can reach a real key or the live prompts/. HOME is an empty temp dir:
    blank TYPESAFE_API_KEY* variables alone do not stop jev.py finding a key FILE (config.KEY_PATHS
    looks under ~/.secondbrain-secrets), and propose.sh's default token path is under HOME too.
    TYPESAFE_BASE_URL is a closed local port, so a send that got that far still could not leave the
    machine, and every proxy variable is blank with NO_PROXY "*", so that port is never handed to a
    proxy off the machine either (none of these scripts needs the network). CLAUDE_CODE_OAUTH_TOKEN
    is blank: the only token a stub claude can see is the one propose.sh read from its token file,
    whatever the runner exports. JEVLOOP_PROMPTS is a pinned v1 root (fixture_prompts.pin_v1), so the
    digest and the table never quote the live CURRENT. TMPDIR is a fresh directory under /tmp, removed
    after the test: propose.sh fails a live night whose temp cwd has a CLAUDE.md, CLAUDE.local.md or
    .claude in any ancestor, and the runner's own TMPDIR may sit under ~ (beside ~/.claude) or inside
    a checkout. `extra` overrides any of it."""
    env = {**os.environ, "TYPESAFE_API_KEY_LOOP": "", "TYPESAFE_API_KEY": "", "CLAUDE_CODE_OAUTH_TOKEN": "",
           "CLAUDE_CONFIG_DIR": "",                       # the CLI's sessions: under HOME (a temp dir), never the runner's
           "HOME": tc.enterContext(tempfile.TemporaryDirectory()), "TYPESAFE_BASE_URL": "http://127.0.0.1:9",
           "JEVLOOP_PY": sys.executable, **{v: "" for v in PROXY_VARS}, "NO_PROXY": "*", "no_proxy": "*",
           "TMPDIR": tc.enterContext(tempfile.TemporaryDirectory(dir="/tmp"))}
    if "JEVLOOP_PROMPTS" not in extra:
        env["JEVLOOP_PROMPTS"] = pin_v1(tc)
    env.update(extra)
    if tmp is not None and not os.access("/usr/bin/caffeinate", os.X_OK):
        stub = os.path.join(tmp, "caffeinate")
        with open(stub, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/bash\n[ "$1" = "-i" ] && shift\nexec "$@"\n')
        os.chmod(stub, 0o755)
        env["JEVLOOP_CAFFEINATE"] = stub
    return env


def _tree_copy(tc):
    """A copy of the code propose.sh runs (loop/ and nightly/, no bytecode) in a temp dir, removed after
    the test `tc`. A test that points --dry --root at "the repo" points it at this copy and runs the
    copy's propose.sh: a guard that failed would write the fixture into the copy, never the checkout."""
    copy = os.path.join(tc.enterContext(tempfile.TemporaryDirectory()), "tree")
    for d in ("loop", "nightly"):
        shutil.copytree(os.path.join(REPO, d), os.path.join(copy, d), ignore=shutil.ignore_patterns("__pycache__"))
    return copy


def _second_name(tc, path, env):
    """(argv prefix, alias): a second name for the existing directory `path` that os.path.realpath does
    not unify with it, and what a command must be started under to see it by that name. On the Mac:
    the last component with its case flipped (case-insensitive APFS, the default) or the path under
    the /System/Volumes/Data firmlink. On Linux: a bind mount in a private mount namespace (unshare
    -rm), which lasts as long as the command; `env` is the one the command runs with (_sh_env). Skips the
    test `tc` where there is none."""
    real = os.path.realpath(path)
    head, tail = os.path.split(real)
    for alias in (os.path.join(head, tail.swapcase()), "/System/Volumes/Data" + real):
        if os.path.exists(alias) and os.path.samefile(alias, real) and os.path.realpath(alias) != real:
            return [], alias
    if shutil.which("unshare") and shutil.which("mount"):
        alias = os.path.join(tc.enterContext(tempfile.TemporaryDirectory()), "alias")
        os.mkdir(alias)
        wrap = ["unshare", "-rm", "/bin/sh", "-c", 'mount --bind "$1" "$2" || exit 97; shift 2; exec "$@"', "sh", real, alias]
        probe = subprocess.run(wrap + [sys.executable, "-c", "import os, sys; sys.exit(not os.path.samefile(*sys.argv[1:]))",
                                       real, alias], capture_output=True, timeout=30, env=env)
        if probe.returncode == 0:
            return wrap, alias
    tc.skipTest("no second name for one directory here: case-sensitive, no firmlink, no unshare -rm")


def _alive(pid):
    """True while `pid` is a live process: gone, or a zombie waiting for its reaper (Linux /proc), is not."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def _gone(pids, within=5.0):
    """The pids of `pids` still alive after up to `within` seconds."""
    deadline = time.monotonic() + within
    while any(_alive(p) for p in pids) and time.monotonic() < deadline:
        time.sleep(0.02)
    return [p for p in pids if _alive(p)]


def _pids(path, n, within=10.0):
    """The first `n` pids written one per line to `path`, once there are `n`."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            with open(path, encoding="utf-8") as fh:
                got = [int(x) for x in fh.read().split()]
            if len(got) >= n:
                return got[:n]
        except (OSError, ValueError):
            pass
        time.sleep(0.01)
    raise AssertionError(f"{path}: fewer than {n} pids after {within} s")


def _table_rows(text):
    """[(choice, confidence, label)] of the disagreement table, file order."""
    out = []
    for line in text.splitlines():
        if line.startswith("| SOL:"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            out.append((cells[1], float(cells[2]), cells[4]))
    return out


class DigestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.log = os.path.join(self.tmp, "data", "decisions.jsonl")
        _write_log(self.log, synthetic_log())
        pin_v1(self)                                                 # the digest quotes CURRENT: pin it to v1

    def test_disagreement_rows_and_order(self):
        text, n = digest.build(DAY, self.log)
        self.assertEqual(n, 41)
        self.assertEqual(_table_rows(text), [("buy", 0.95, "down"), ("sell", 0.90, "up"), ("sell", 0.86, "up")])
        self.assertIn("B disagreements 3", text)
        self.assertIn("3 of 3 shown", text)

    def test_rows_of_a_superseded_wording_are_not_arm_b_on_current(self):
        rows = synthetic_log()
        rows[0]["prompt_b"], rows[1]["prompt_b"] = "v2", "v2"            # the two most confident listed rows answered v2
        rows[5]["prompt_b"] = "v1"                                       # CURRENT is pinned to v1: this one stays
        _write_log(self.log, rows)
        text, n = digest.build(DAY, self.log)
        self.assertEqual(n, 41)
        self.assertEqual(_table_rows(text), [("sell", 0.86, "up")])
        self.assertIn("B disagreements 1 | prompt_b v1 1, v2 2 (arm B is read from the v1 rows only; the other rows answered a superseded wording)", text)
        self.assertEqual(digest.versions(rows), {"v1": 1, "v2": 2})
        self.assertEqual(len(digest.on_current(rows, "v1")), 39)

    def test_never_features_never_the_log(self):
        text, _ = digest.build(DAY, self.log)
        self.assertNotIn("features", text)
        self.assertNotIn("ret15_z", text)
        self.assertNotIn("1.7", text)                     # the feature value planted in every row
        self.assertNotIn("tick_id", text)                 # no raw row
        self.assertNotIn("Bearer", text)

    def test_current_question_verbatim_and_both_shas(self):
        text, _ = digest.build(DAY, self.log)
        v1 = prompts.load("v1")
        self.assertIn(v1["action"]["instructions"], text)
        for k in ("buy", "sell", "hold"):
            self.assertIn(v1["action"]["criteria"][k], text)
        self.assertIn(f"prompt_a v1 {prompts.sha('v1')}", text)
        self.assertIn(f"prompt_b {prompts.current()} {prompts.sha(prompts.current())}", text)

    def test_summary_line_counts(self):
        text, _ = digest.build(DAY, self.log)
        line = text.splitlines()[2]
        self.assertTrue(line.startswith("2026-09-22 | ticks 41, answered 40, absence feed:1"))
        self.assertIn("outcomes joined 25/40", line)      # minutes 0..24 resolve inside the 41-row log (6 is unpriced)
        self.assertIn("trend dumping 0% flat 0% pumping 100%", line)
        # 2026-09-24, decided by Alex: PnL per arm twice, labelled -- at 0 bps (H1, direction)
        # and at the venue's own taker fee (the realistic cost)
        self.assertIn(f"column argmax, paper PnL at {config.FEE_BPS_PRIMARY:g} bps (direction) / at "
                      f"{config.FEE_BPS_VENUE:g} bps (venue fee): A 0 trades +0.0 / +0.0 bps", line)
        self.assertIn("paper PnL at 0 bps (direction) / at 120 bps (venue fee)", line)
        # a trade is a FILL (book.replay "trades"), not a round trip: B opens at 0, closes at 1,
        # opens again at 2 (buy 0.99), holds through 3-4 and closes at 5 (sell 0.86); the
        # sell at 30 finds it flat and is a no-op. Four fills, two round trips.
        self.assertIn("B 4 trades", line)
        self.assertIn("C 1 trades", line)                 # rule_c buy at minute 0, then held long
        self.assertIn("B disagreements 3", line)

    def test_summary_pnl_at_both_fees(self):
        # the trade count is the same at both fees (a fee never changes a decision); the net
        # figure is the gross one minus each fill's fee. C: one fill, the open at minute 0 at
        # ask 100.01 on $1,000, fee exactly FEE_BPS_VENUE bps of notional.
        day = [r for r in digest.outcomes.load(self.log, []) if r["tick_id"].startswith("20260922")]
        gross, net = digest.arms(day, config.FEE_BPS_PRIMARY), digest.arms(day, config.FEE_BPS_VENUE)
        for arm in ("a", "b", "c"):
            self.assertEqual(gross[arm][0], net[arm][0], arm)
        self.assertEqual(gross["c"][0], 1)
        self.assertAlmostEqual(gross["c"][1] - net["c"][1], config.FEE_BPS_VENUE, places=9)
        self.assertEqual(gross["b"][0], 4)
        self.assertGreater(gross["b"][1] - net["b"][1], 3.9 * config.FEE_BPS_VENUE)   # four fills, ~120 each
        line = digest.build(DAY, self.log)[0].splitlines()[2]
        self.assertIn(f"C 1 trades {gross['c'][1]:+.1f} / {net['c'][1]:+.1f} bps", line)
        self.assertIn(f"B 4 trades {gross['b'][1]:+.1f} / {net['b'][1]:+.1f} bps", line)

    def test_cap_at_25(self):
        # forty buys at 0.9 on a mid that falls 0.1 a minute: every t+15 is ~-150 bps, so
        # all forty are disagreements and exactly DISAGREE_MAX = 25 are listed. (The earlier
        # form set the mid at t AND at t+15 to 99.0, so those buys were flat, not wrong,
        # and only 2 rows could ever be listed: the fixture, not the cap, was under test.)
        rows = [_row(m, 100.0 - 0.1 * m, ("buy", 0.9) if m < 40 else ("hold", 0.6)) for m in range(60)]
        _write_log(self.log, rows)
        text, _ = digest.build(DAY, self.log)
        self.assertEqual(len(_table_rows(text)), digest.DISAGREE_MAX)
        self.assertEqual(digest.DISAGREE_MAX, 25)
        self.assertIn("25 of 40 shown", text)
        self.assertIn("B disagreements 40", text)

    def test_other_days_are_excluded_but_join_across_midnight(self):
        rows = synthetic_log()
        late = datetime.datetime(2026, 9, 22, 23, 50, 0, tzinfo=datetime.timezone.utc)
        for i in range(20):                               # 23:50 .. 00:09 next day; the 23:50 buy resolves at 00:05
            d = late + datetime.timedelta(minutes=i)
            r = _row(0, 100.0 if i < 15 else 99.5, ("buy", 0.93) if i == 0 else ("hold", 0.6))
            r["tick_id"], r["ts_rx"] = d.strftime("%Y%m%dT%H%M00Z"), _iso(d)
            rows.append(r)
        _write_log(self.log, rows)
        text, n = digest.build(DAY, self.log)
        self.assertEqual(n, 41 + 10)                      # the 10 next-day rows are not the day's
        self.assertEqual(_table_rows(text)[0], ("buy", 0.95, "down"))
        self.assertIn(("buy", 0.93, "down"), _table_rows(text))

    def test_a_parse_row_with_a_list_or_dict_choice_neither_crashes_nor_changes_the_digest(self):
        # cycle keeps the answers of a jev/parse row (a wrong-typed field); a b_action choice that is a
        # list or dict made the digest raise TypeError (unhashable) and that date never got a proposal.
        # Such a row is not a disagreement; every other byte of the digest is what it was without it.
        base, _ = digest.build(DAY, self.log)
        for bad in (["buy"], {"x": "buy"}):
            rows = synthetic_log()
            odd = dict(rows[7], absence="jev", columns={"a": None, "b": None})
            odd["answers"] = dict(odd["answers"], b_action={"choice": bad, "confidence": 0.95,
                                                             "probabilities": {"buy": 0.95, "sell": 0.025, "hold": 0.025}})
            rows[7] = odd
            _write_log(self.log, rows)
            text, n = digest.build(DAY, self.log)
            self.assertEqual(_table_rows(text), [("buy", 0.95, "down"), ("sell", 0.90, "up"), ("sell", 0.86, "up")], bad)
            self.assertIn("B disagreements 3", text)
            out = os.path.join(self.tmp, "d.md")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(digest.main(["--date", "2026-09-22", "--log", self.log, "--out", out]), 0)
        _write_log(self.log, synthetic_log())
        self.assertEqual(digest.build(DAY, self.log)[0], base)                       # the clean day is byte-identical

    def test_a_confidence_past_a_floats_range_neither_crashes_nor_changes_the_digest(self):
        # the same kind of jev/parse row as a list choice: an integer confidence of 10**400 passed the
        # >= 0.85 filter and float() raised OverflowError, so that date never got a proposal
        rows = synthetic_log()
        odd = dict(rows[0], absence="jev", columns={"a": None, "b": None})    # minute 0: a buy the next 15 min contradicts
        odd["answers"] = dict(odd["answers"], b_action={"choice": "buy", "confidence": 10 ** 400,
                                                         "probabilities": {"buy": 1.0, "sell": 0.0, "hold": 0.0}})
        rows[0] = odd
        _write_log(self.log, rows)
        text, _ = digest.build(DAY, self.log)                                  # reaches float(): raised before the guard
        self.assertEqual(_table_rows(text), [("sell", 0.90, "up"), ("sell", 0.86, "up")])
        out = os.path.join(self.tmp, "d.md")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(digest.main(["--date", "2026-09-22", "--log", self.log, "--out", out]), 0)

    def test_the_policy_table_formats_a_confidence_past_a_floats_range(self):
        self.assertEqual(policy_table._cell(("buy", 10 ** 400)), ("buy", "?"))
        self.assertEqual(policy_table._cell(("sell", 0.8765)), ("sell", "0.88"))
        self.assertEqual(policy_table._cell(("hold", True)), ("hold", "-"))

    def test_the_digest_of_the_fixture_day_is_the_bytes_main_wrote(self):
        # the digest's content is the treatment (CLAUDE.md): every byte of it must stay what the code on
        # main (09e867f) produced for the same log and the same CURRENT. The sha was taken by running
        # main's own nightly/digest.py on synthetic_log() with prompts pinned to v1, 2026-09-28; a change
        # to the digest's text, order or numbers on this day turns this red.
        text, n = digest.build(DAY, self.log)
        self.assertEqual(n, 41)
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), "6201884e4235a5b271aab78714c0779a1c627f289633bb20dcf293a62835b679")

    def test_main_writes_file_and_day_zero_exits_4(self):
        out = os.path.join(self.tmp, "digest.md")
        with redirect_stdout(io.StringIO()):
            rc = digest.main(["--date", "2026-09-22", "--log", self.log, "--out", out])
        self.assertEqual(rc, 0)
        with open(out, encoding="utf-8") as fh:
            self.assertIn("B disagreements 3", fh.read())
        with redirect_stdout(io.StringIO()):
            rc = digest.main(["--date", "2026-09-22", "--log", os.path.join(self.tmp, "none.jsonl"), "--out", out])
        self.assertEqual(rc, digest.EXIT_EMPTY)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("ticks 0", text)
        self.assertIn("(none)", text)
        self.assertNotIn("features", text)

    def test_yesterday_is_the_previous_utc_day(self):
        now = datetime.datetime(2026, 9, 23, 0, 5, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(digest.yesterday(now), "2026-09-22")


CAND = {"rationale": "test", "instructions": "Decide whether to be long for the next quarter of an hour.",
        "criteria": {"buy": "the trend is pumping and liquidity is deep", "sell": "the trend is dumping",
                     "hold": "anything else"}}


def _by_state():
    return {state.state_string(a): a for a in state.all_states()}


class PolicyTableTest(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.ask = self.enterContext(mock.patch("loop.jev.ask"))
        self.urlopen = self.enterContext(mock.patch("urllib.request.urlopen", side_effect=Reached("urlopen was reached")))
        self.enterContext(mock.patch.object(config, "JEV_URL", "http://127.0.0.1:9/v1/systemone"))   # a second wall: discard
        self.halt = os.path.join(self.tmp, "HALT")                  # never the repo's data/HALT
        self.enterContext(mock.patch.object(config, "HALT", self.halt))
        pin_v1(self)                                                 # current_action() reads CURRENT: pin it to v1
        self.prop = os.path.join(self.tmp, "2026-09-22.json")
        with open(self.prop, "w", encoding="utf-8") as fh:
            json.dump({"candidates": [CAND]}, fh)

    def test_a_send_past_the_mocked_ask_meets_two_walls(self):
        # jev.ask is mocked, but a path that reached urllib would meet a raising urlopen, and behind it
        # a closed local port instead of api.typesafe.ai
        self.assertTrue(config.JEV_URL.startswith("http://127.0.0.1:9/"), config.JEV_URL)
        with self.assertRaises(Reached):
            urllib.request.urlopen(config.JEV_URL)

    def test_81_distinct_digit_free_states(self):
        st = policy_table.states()
        self.assertEqual(len(st), 81)
        strings = [s for s, _ in st]
        self.assertEqual(len(set(strings)), 81)
        for s in strings:
            self.assertFalse(any(ch.isdigit() for ch in s), s)
            self.assertTrue(s.startswith("SOL: liquidity "), s)
        self.assertEqual(sorted({rc for _, rc in st}), ["buy", "hold", "sell"])
        self.assertEqual(sum(rc == "buy" for _, rc in st), 12)

    def test_dry_prints_81_and_sends_nothing(self):
        buf = io.StringIO()
        ledger = os.path.join(self.tmp, "sends.tsv")                # the ledger jev.ask would append to: none here
        with redirect_stdout(buf), mock.patch.object(config, "SENDS", ledger):
            rc = policy_table.main(["--dry", self.prop])
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(ledger))
        self.ask.assert_not_called()
        first, body = buf.getvalue().split("\n", 1)
        self.assertEqual(first, "dry: 81 payloads, 0 sent")
        p = json.loads(body)
        self.assertEqual(p["model"], config.MODEL)
        self.assertEqual(p["state"], policy_table.states()[0][0])
        self.assertEqual(list(p["questions"]), ["cand_0", "current"])
        self.assertEqual(p["questions"]["cand_0"], {"type": "choice", **{k: CAND[k] for k in ("instructions", "criteria")}})
        self.assertEqual(p["questions"]["current"]["instructions"], prompts.load("v1")["action"]["instructions"])
        self.ask.assert_not_called()
        self.urlopen.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "2026-09-22.md")))

    def test_runs_by_path_as_the_contract_names_it(self):
        # CONTRACT §5 says `policy_table.py proposals/<date>.json` and `nightly/digest.py`:
        # run by path, sys.path[0] is nightly/ and `from loop import` must still resolve.
        env = _sh_env(self)                                                 # no key reachable, CURRENT pinned to v1
        r = subprocess.run([sys.executable, os.path.join(REPO, "nightly", "policy_table.py"), "--dry",
                            "--prompts", env["JEVLOOP_PROMPTS"], self.prop],
                           cwd=self.tmp, capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        first, body = r.stdout.split("\n", 1)
        self.assertEqual(first, "dry: 81 payloads, 0 sent")
        self.assertEqual(json.loads(body)["questions"]["current"]["instructions"], prompts.load("v1")["action"]["instructions"])
        r = subprocess.run([sys.executable, os.path.join(REPO, "nightly", "digest.py"), "--help"],
                           cwd=self.tmp, capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_payloads_are_81_one_per_state_all_candidates_in_each(self):
        cands = policy_table.load_candidates(self.prop)
        _, cur_q, _ = policy_table.current_action()
        ps = policy_table.payloads(policy_table.questions(cands, cur_q))
        self.assertEqual(len(ps), 81)
        self.assertEqual(len({p["state"] for p in ps}), 81)
        for p in ps:
            self.assertEqual(list(p["questions"]), ["cand_0", "current"])
            self.assertFalse(any(ch.isdigit() for ch in p["state"]))

    def test_run_writes_table_with_counts(self):
        by = _by_state()

        def fake(s, qs, **kw):                                  # current follows rule_c exactly; cand_0 always holds
            rc = state.rule_c(by[s])
            return {"answers": {"cand_0": _answer("hold", 0.7), "current": _answer(rc, 0.9)},
                    "model": config.MODEL, "input_tokens": 100, "latency_ms": 5, "key_path": "env:X"}
        self.ask.side_effect = fake
        out = os.path.join(self.tmp, "2026-09-22.md")
        with redirect_stdout(io.StringIO()):
            rc = policy_table.main([self.prop, "--out", out])
        self.assertEqual(rc, 0)
        self.assertEqual(self.ask.call_count, 81)
        for call in self.ask.call_args_list:
            self.assertEqual(list(call.args[1]), ["cand_0", "current"])
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("differs from rule_c on 0 of 81 answered states", text)          # current
        self.assertIn("differs from CURRENT on 57 of 81 answered states; from rule_c on 57 of 81", text)
        self.assertIn("-buy: the trend is pumping, volatility is not violent, and liquidity is not thin", text)
        self.assertIn("+buy: the trend is pumping and liquidity is deep", text)
        self.assertIn("rationale: test", text)
        self.assertIn("requests: 81, answered: 81, errors: 0", text)
        self.assertNotIn("INCOMPLETE", text)
        self.assertNotIn("DRIFT", text)
        self.assertEqual(text.count("| SOL: liquidity "), 162)                            # 81 rows x 2 tables
        self.assertIn("| SOL: liquidity deep, flow quiet, trend pumping, vol normal | hold | 0.70 | buy | buy |", text)
        self.assertIn("scored against a logged outcome", text)

    def test_key_rejected_stops_after_one_and_marks_incomplete(self):
        self.ask.side_effect = jev.JevError("http-4xx", "401", 401, "env:X")
        out = os.path.join(self.tmp, "t.md")
        with redirect_stdout(io.StringIO()):
            rc = policy_table.main([self.prop, "--out", out])
        self.assertEqual(rc, policy_table.EXIT_INCOMPLETE)
        self.assertEqual(self.ask.call_count, 1)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("INCOMPLETE", text)
        self.assertIn("errors: 81", text)
        with open(self.halt, encoding="utf-8") as fh:                                   # the caller writes HALT (CONTRACT §2)
            reason = fh.read()
        self.assertIn("key rejected", reason)
        self.assertIn("401", reason)

    def test_halt_present_sends_nothing(self):
        # PROTOCOL §3.8: HALT stops sends. These never reach decisions.jsonl, so the spend
        # guard cannot see them; without this check the nightly sent 81 after a HALT.
        with open(self.halt, "w", encoding="utf-8") as fh:
            fh.write("spend: by hand\n")
        out = os.path.join(self.tmp, "t.md")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = policy_table.main([self.prop, "--out", out])
        self.assertEqual(rc, 0)
        self.assertIn("HALT present", buf.getvalue())
        self.ask.assert_not_called()
        self.urlopen.assert_not_called()
        self.assertFalse(os.path.exists(out))

    def test_persistent_429_ends_the_night_after_one_ask(self):
        self.ask.side_effect = jev.JevError("http-429", "429 Too Many Requests", 429, "env:X")
        results = policy_table.run(policy_table.questions(policy_table.load_candidates(self.prop),
                                                          policy_table.current_action()[1]))
        self.assertEqual(self.ask.call_count, 1)                     # jev.ask's own retry is its only one
        self.assertEqual({r["error"] for r in results}, {"http-429"})
        self.assertFalse(os.path.exists(self.halt))                  # a limit is not a rejected key

    def test_transient_failures_in_a_row_end_the_night(self):
        self.ask.side_effect = jev.JevError("http-5xx", "503", 503, "env:X")
        results = policy_table.run(policy_table.questions(policy_table.load_candidates(self.prop),
                                                          policy_table.current_action()[1]))
        self.assertEqual(self.ask.call_count, policy_table.MAX_TRANSIENT_RUN)
        self.assertEqual(sum(1 for r in results if r["error"]), 81)

    def test_three_other_errors_in_a_row_end_the_night(self):
        by = _by_state()
        calls = []

        def fake(s, qs, **kw):
            calls.append(s)
            if len(calls) >= 3:
                raise jev.JevError("http-4xx", "x", 404, "env:X")        # not 401/403: not a HALT, not fatal alone
            return {"answers": {"cand_0": _answer("hold", 0.5), "current": _answer(state.rule_c(by[s]), 0.9)},
                    "model": config.MODEL}
        self.ask.side_effect = fake
        results = policy_table.run(policy_table.questions(policy_table.load_candidates(self.prop),
                                                          policy_table.current_action()[1]))
        self.assertEqual(len(calls), 5)                                  # 2 answers, then 3 in a row end it
        self.assertEqual(sum(1 for r in results if r["error"] == "http-4xx"), 79)
        self.assertEqual(policy_table.counts(results, "cand_0")[2], 2)

    def test_table_names_the_proposal_sha(self):
        by = _by_state()
        self.ask.side_effect = lambda s, qs, **kw: {"answers": {"cand_0": _answer("hold", 0.5), "current": _answer(state.rule_c(by[s]), 0.9)},
                                                    "model": config.MODEL}
        out = os.path.join(self.tmp, "t.md")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(policy_table.main([self.prop, "--out", out]), 0)
        with open(self.prop, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        with open(out, encoding="utf-8") as fh:
            self.assertIn(f"proposal sha256: {sha}", fh.read())

    def test_the_table_says_where_each_candidate_changes_current(self):
        # the 09-25 review's hand read, by table: a wording that holds on every violent state moves
        # exactly the 27 violent states (all sell under rule_c), a third of each other adjective
        by = _by_state()

        def fake(s, qs, **kw):
            rc = state.rule_c(by[s])
            if s == policy_table.states()[0][0]:
                raise jev.JevError("timeout", "slow")               # one unanswered state: the counts are of answered ones
            return {"answers": {"cand_0": _answer("hold" if by[s]["vol"] == "violent" else rc, 0.7),
                                "current": _answer(rc, 0.9)}, "model": config.MODEL}
        self.ask.side_effect = fake
        out = os.path.join(self.tmp, "t.md")
        with redirect_stdout(io.StringIO()):
            policy_table.main([self.prop, "--out", out])
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        first = by[policy_table.states()[0][0]]                    # liq thin, flow quiet, trend dumping, vol calm
        self.assertEqual((first["liq"], first["flow"], first["trend"], first["vol"]), ("thin", "quiet", "dumping", "calm"))
        block = ("where it changes CURRENT's answer (27 of 80 answered states; per adjective, changed / answered):\n"
                 "- liq: thin 9/26, normal 9/27, deep 9/27\n"
                 "- flow: quiet 9/26, organic 9/27, bot_war 9/27\n"
                 "- trend: dumping 9/26, flat 9/27, pumping 9/27\n"
                 "- vol: calm 0/26, normal 0/27, violent 27/27\n"
                 "- moves: sell -> hold 27\n")
        self.assertIn("differs from CURRENT on 27 of 80 answered states; from rule_c on 27 of 80\n\n" + block + "\n```diff", text)
        from loop import dash                                      # the dash still reads the counts line
        self.assertEqual(dash.PROPOSAL_COUNTS.search(text).groups(), ("27", "80", "27", "80"))

    def test_a_candidate_that_changes_nothing_says_so(self):
        self.ask.side_effect = lambda s, qs, **kw: {"answers": {q: _answer("hold", 0.6) for q in qs}, "model": config.MODEL}
        out = os.path.join(self.tmp, "t.md")
        with redirect_stdout(io.StringIO()):
            policy_table.main([self.prop, "--out", out])
        with open(out, encoding="utf-8") as fh:
            self.assertIn("\nwhere it changes CURRENT's answer: nowhere (0 of 81 answered states)\n", fh.read())

    def test_the_moves_are_listed_most_first(self):
        results = [{"state": s, "rule_c": rc, "error": None, "model": config.MODEL,
                    "answers": {"cand_0": (("buy" if i % 3 else "sell") if i < 5 else rc, 0.5), "current": (rc, 0.5)}}
                   for i, (s, rc) in enumerate(policy_table.states())]
        moves = [ln for ln in policy_table.landing(results, "cand_0") if ln.startswith("- moves: ")]
        self.assertEqual(len(moves), 1)
        got = moves[0][len("- moves: "):].split(", ")
        counts = [int(m.rsplit(" ", 1)[1]) for m in got]
        self.assertEqual(counts, sorted(counts, reverse=True), got)
        self.assertEqual(sum(counts), sum(1 for r in results if r["answers"]["cand_0"][0] != r["answers"]["current"][0]))

    def test_the_header_names_the_proposals_writer_when_given(self):
        by = _by_state()
        self.ask.side_effect = lambda s, qs, **kw: {"answers": {"cand_0": _answer("hold", 0.5), "current": _answer(state.rule_c(by[s]), 0.9)},
                                                    "model": config.MODEL}
        for argv, line in ((["--writer-model", "claude-test-1"], "proposal written by: claude-test-1  \n"),
                           ([], "proposal written by: not given  \n")):
            out = os.path.join(self.tmp, "w.md")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(policy_table.main([self.prop, "--out", out, *argv]), 0)
            with open(out, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn(line, text)
            self.assertRegex(text, r"(?m)^proposal sha256: [0-9a-f]{64}  \nproposal written by: ")   # promote's line stays whole

    def test_transient_error_continues(self):
        by = _by_state()
        calls = []

        def fake(s, qs, **kw):
            calls.append(s)
            if len(calls) == 3:
                raise jev.JevError("timeout", "x", None, "env:X")
            return {"answers": {"cand_0": _answer("hold", 0.5), "current": _answer(state.rule_c(by[s]), 0.9)},
                    "model": config.MODEL}
        self.ask.side_effect = fake
        results = policy_table.run(policy_table.questions(policy_table.load_candidates(self.prop),
                                                          policy_table.current_action()[1]))
        self.assertEqual(len(calls), 81)
        self.assertEqual(sum(1 for r in results if r["error"]), 1)
        self.assertEqual(policy_table.counts(results, "cand_0")[2], 80)

    def test_deadline_stops_sending(self):
        t = [0.0]

        def clock():
            t[0] += 100.0
            return t[0]
        self.ask.return_value = {"answers": {"cand_0": _answer("hold", 0.5), "current": _answer("hold", 0.5)}}
        results = policy_table.run(policy_table.questions(policy_table.load_candidates(self.prop),
                                                          policy_table.current_action()[1]),
                                   deadline_s=250.0, clock=clock)
        self.assertLess(self.ask.call_count, 81)
        self.assertEqual(sum(1 for r in results if r["error"] == "deadline"), 81 - self.ask.call_count)

    def test_bad_candidates_refused_before_any_send(self):
        for bad in ({"candidates": []}, {"candidates": [CAND] * 4},
                    {"candidates": [{**CAND, "criteria": {"yes": "a", "no": "b"}}]},
                    {"candidates": [{**CAND, "instructions": "wait 15 minutes"}]}):
            with open(self.prop, "w", encoding="utf-8") as fh:
                json.dump(bad, fh)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(policy_table.main([self.prop]), 1)
        self.ask.assert_not_called()

    def _answers(self, s, model=config.MODEL):
        r = {"answers": {"cand_0": _answer("hold", 0.5), "current": _answer(state.rule_c(_by_state()[s]), 0.9)}}
        if model is not None:
            r["model"] = model
        return r

    def test_a_halt_written_mid_table_stops_the_rest(self):
        # PROTOCOL §3.8: HALT stops sends. main() checks it once before the first send; a HALT a
        # person or the loop writes while the table runs must stop every send after it too.
        calls = []

        def fake(s, qs, **kw):
            calls.append(s)
            if len(calls) == 3:
                with open(self.halt, "w", encoding="utf-8") as fh:
                    fh.write("spend: by hand, mid-table\n")
            return self._answers(s)
        self.ask.side_effect = fake
        out = os.path.join(self.tmp, "t.md")
        with redirect_stdout(io.StringIO()):
            rc = policy_table.main([self.prop, "--out", out])
        self.assertEqual(rc, policy_table.EXIT_INCOMPLETE)
        self.assertEqual(len(calls), 3)                                  # the fourth state found HALT: no send
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("requests: 81, answered: 3, errors: 78 -- INCOMPLETE", text)
        self.assertIn("error kinds: halt", text)
        self.urlopen.assert_not_called()

    def test_alternating_error_kinds_end_the_night(self):
        # timeout resets the "other" run and a 404 resets the transient run, so each per-kind
        # counter alone never reaches 3; the any-kind counter does.
        kinds = [("timeout", None), ("http-4xx", 404)]
        calls = []

        def fake(s, qs, **kw):
            k, st = kinds[len(calls) % 2]
            calls.append(s)
            raise jev.JevError(k, "x", st, "env:X")
        self.ask.side_effect = fake
        results = policy_table.run(policy_table.questions(policy_table.load_candidates(self.prop),
                                                          policy_table.current_action()[1]))
        self.assertEqual(len(calls), policy_table.MAX_ERROR_RUN)
        self.assertEqual(policy_table.MAX_ERROR_RUN, 3)
        self.assertEqual(sum(1 for r in results if r["error"]), 81)
        self.assertFalse(os.path.exists(self.halt))                      # neither kind is a rejected key

    def test_an_answer_between_errors_resets_the_any_kind_run(self):
        seq = ["timeout", "http-4xx", "ok"] * 27                          # never three errors in a row

        def fake(s, qs, **kw):
            k = seq[self.ask.call_count - 1]
            if k == "ok":
                return self._answers(s)
            raise jev.JevError(k, "x", 404 if k == "http-4xx" else None, "env:X")
        self.ask.side_effect = fake
        results = policy_table.run(policy_table.questions(policy_table.load_candidates(self.prop),
                                                          policy_table.current_action()[1]))
        self.assertEqual(self.ask.call_count, 81)
        self.assertEqual(sum(1 for r in results if r["answers"]), 27)

    def test_the_sha_is_of_the_bytes_the_candidates_were_read_from(self):
        # the json is read once: a rewrite while the 81 sends run must not give the table a sha
        # of bytes it never described (bin/promote trusts that line)
        with open(self.prop, "rb") as fh:
            original = fh.read()

        def fake(s, qs, **kw):
            if self.ask.call_count == 1:
                with open(self.prop, "w", encoding="utf-8") as fh:
                    json.dump({"candidates": [{**CAND, "rationale": "rewritten mid-table"}]}, fh)
            return self._answers(s)
        self.ask.side_effect = fake
        out = os.path.join(self.tmp, "t.md")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(policy_table.main([self.prop, "--out", out]), 0)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(f"proposal sha256: {hashlib.sha256(original).hexdigest()}", text)
        self.assertIn("rationale: test", text)
        self.assertNotIn("rewritten mid-table", text)

    def test_an_answer_naming_no_model_is_drift(self):
        # cycle.py logs drift when the reply's model is not config.MODEL, None included
        self.ask.side_effect = lambda s, qs, **kw: self._answers(s, model=None)
        out = os.path.join(self.tmp, "t.md")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(policy_table.main([self.prop, "--out", out]), 0)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(f"model answered: no model named on 81 -- DRIFT, requested {config.MODEL}", text)
        self.ask.side_effect = lambda s, qs, **kw: self._answers(s, model=None if s.endswith("calm") else config.MODEL)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(policy_table.main([self.prop, "--out", out]), 0)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(f"model answered: {config.MODEL}, no model named on 27 -- DRIFT", text)


def _load_promote():
    path = os.path.join(REPO, "bin", "promote")
    spec = importlib.util.spec_from_file_location("promote", path, loader=importlib.machinery.SourceFileLoader("promote", path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _block(text, name):
    """The raw text of the top-level `"name": {...}` block in a 2-space-indented file."""
    start = text.index(f'  "{name}": {{')
    end = text.index("\n  }", start) + len("\n  }")
    return text[start:end]


class PromoteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = os.path.join(self.tmp, "prompts")
        os.makedirs(self.root)
        shutil.copy(os.path.join(REPO, "prompts", "v1.json"), self.root)
        with open(os.path.join(self.root, "CURRENT"), "w", encoding="utf-8") as fh:  # v1, not the live CURRENT (v2 since 2026-09-26)
            fh.write("v1\n")
        self.prop = os.path.join(self.tmp, "2026-09-22.json")
        with open(self.prop, "w", encoding="utf-8") as fh:
            json.dump({"candidates": [CAND, {**CAND, "instructions": "Second candidate."}]}, fh)
        self.enterContext(mock.patch.object(sys, "path", list(sys.path)))   # bin/promote inserts REPO at import
        self.promote = _load_promote()
        self.git = self.enterContext(mock.patch.object(self.promote.subprocess, "run"))
        self.status, self.tags = "", "prereg-v1\n"                   # a clean tree, PREREG sealed

        def git(argv, **kw):
            out = self.status if argv[:2] == ["git", "status"] else self.tags if argv[:2] == ["git", "tag"] else None
            if out is None:
                raise AssertionError(f"unexpected command {argv}")
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
        self.git.side_effect = git
        self.enterContext(mock.patch.object(self.promote, "_attended", return_value=True))

    def _run(self, *argv):
        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), mock.patch("sys.stderr", err):
            rc = self.promote.main(list(argv))
        return rc, buf.getvalue(), err.getvalue()

    def test_the_committed_table_vouches_for_the_json(self):
        md = self.prop[:-5] + ".md"
        with open(md, "w", encoding="utf-8") as fh:
            fh.write("# policy table\n\nproposal sha256: " + "0" * 64 + "  \n")
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("changed after its table was made", err)
        self.assertFalse(os.path.exists(os.path.join(self.root, "v2.json")))
        with open(self.prop, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        with open(md, "w", encoding="utf-8") as fh:
            fh.write("# policy table\n\nproposal sha256: " + sha + "  \n")
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        self.assertNotIn("WARNING", err)

    def test_no_table_warns_and_proceeds(self):
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        self.assertIn("WARNING no policy table", err)

    def test_an_incomplete_table_warns(self):
        # a table that answered 2 of 81 states vouches for the json's bytes but not for the
        # candidate's behaviour: the person at the terminal is told before CURRENT moves
        with open(self.prop, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        md = self.prop[:-5] + ".md"
        with open(md, "w", encoding="utf-8") as fh:
            fh.write("# policy table\n\nproposal sha256: " + sha + "  \n"
                     "requests: 81, answered: 2, errors: 79 -- INCOMPLETE  \n")
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        self.assertIn(f"WARNING {md} is INCOMPLETE (answered 2 of 81 states)", err)
        self.assertEqual(prompts.current(self.root), "v2")

    def test_current_is_replaced_whole_never_truncated_in_place(self):
        # the loop reads CURRENT every minute: it is written beside and renamed over, so no tick
        # can read an empty file between a truncate and a write
        current, tmp = os.path.join(self.root, "CURRENT"), os.path.join(self.root, "CURRENT.tmp")
        with mock.patch.object(self.promote.os, "replace", wraps=os.replace) as rep:
            rc, _, _ = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        rep.assert_called_once_with(tmp, current)
        with open(current, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "v2\n")
        self.assertFalse(os.path.exists(tmp))
        # a rename that fails leaves CURRENT exactly as it was, and no CURRENT.tmp behind
        with mock.patch.object(self.promote.os, "replace", side_effect=OSError("disk full")):
            rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("could not switch CURRENT (disk full); CURRENT still names v2", err)
        with open(current, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "v2\n")
        self.assertFalse(os.path.exists(tmp))
        self.assertTrue(os.path.exists(os.path.join(self.root, "v3.json")))

    def test_dirty_tree_refuses_and_writes_nothing(self):
        self.status = " M loop/x.py\n"
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("dirty", err)
        self.assertEqual(sorted(os.listdir(self.root)), ["CURRENT", "v1.json"])
        self.assertEqual(prompts.current(self.root), "v1")
        self.git.assert_called_once()
        self.assertEqual(self.git.call_args.args[0], ["git", "status", "--porcelain"])

    def test_unsealed_prereg_refuses_and_writes_nothing(self):
        # PREREG §10: the tag must exist before the first row whose prompt_b is not v1.
        for tags in ("", "prereg-v1-draft\n", "other\n"):
            self.tags = tags
            rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
            self.assertEqual(rc, 1, tags)
            self.assertIn("prereg-v1", err)
            self.assertEqual(sorted(os.listdir(self.root)), ["CURRENT", "v1.json"])
            self.assertEqual(prompts.current(self.root), "v1")
        self.assertEqual(self.git.call_args.args[0], ["git", "tag", "-l", "prereg-v1"])

    def test_loading_promote_leaves_sys_path_as_it_was(self):
        # bin/promote does sys.path.insert(0, REPO) at import, and setUp loads it for every test: the
        # suite used to end with a dozen extra REPO entries on sys.path. Run two tests as the runner would.
        before = list(sys.path)
        suite = unittest.TestSuite([PromoteTest("test_no_table_warns_and_proceeds"), PromoteTest("test_no_tty_refuses")])
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        self.assertEqual((result.testsRun, result.errors, result.failures), (2, [], []))
        self.assertEqual(sys.path, before)
        self.assertEqual(sys.path[0], self.promote.REPO)                   # setUp's own load inserted it: into the copy

    def test_promote_is_executable_as_the_contract_runs_it(self):
        # CONTRACT §5 and STEPS.md run `bin/promote proposals/<date>.json <k>` by path
        self.assertTrue(os.access(os.path.join(REPO, "bin", "promote"), os.X_OK))

    def test_no_tty_refuses(self):
        with mock.patch.object(self.promote, "_attended", return_value=False):
            rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("tty", err)
        self.assertEqual(sorted(os.listdir(self.root)), ["CURRENT", "v1.json"])

    def test_v2_carries_v1_nouls_byte_identical(self):
        rc, out, _ = self._run(self.prop, "1", "--prompts", self.root)
        self.assertEqual(rc, 0, out)
        self.assertEqual(prompts.current(self.root), "v2")
        with open(os.path.join(self.root, "v1.json"), encoding="utf-8") as fh:
            t1 = fh.read()
        with open(os.path.join(self.root, "v2.json"), encoding="utf-8") as fh:
            t2 = fh.read()
        for q in ("skip", "up15", "down15"):
            self.assertEqual(_block(t1, q), _block(t2, q))
        v1, v2 = json.loads(t1), json.loads(t2)
        self.assertEqual(list(v2), list(v1))                                  # same key order
        self.assertEqual(v2["version"], "v2")
        self.assertEqual(v2["action"], {"type": "choice", "instructions": "Second candidate.", "criteria": CAND["criteria"]})
        self.assertIn("candidate 1", v2["note"])
        with open(os.path.join(REPO, "prompts", "v1.json"), encoding="utf-8") as fh:
            self.assertEqual(t1, fh.read())                                    # v1 untouched
        qs = prompts.build(v1, v2)                                             # and the loop can build from it
        self.assertEqual(qs["b_action"]["instructions"], "Second candidate.")
        self.assertEqual(qs["a_action"], prompts.question(v1["action"], "choice"))
        self.assertIn("+++ v2.action", out)
        self.assertIn("-instructions: " + v1["action"]["instructions"], out)
        self.assertIn("+instructions: Second candidate.", out)

    def test_promoted_action_has_type_choice_so_the_next_tick_builds(self):
        # nightly candidates carry only instructions + criteria (+ rationale); prompts.build()
        # refuses a question without "type", so a promote that copied the candidate verbatim
        # would make the first tick after it raise PromptError. Replayed with exactly the
        # calls cycle._run makes: load v1, current(), load(current), build.
        self.assertNotIn("type", CAND)
        rc, _, _ = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        cur = prompts.current(self.root)
        doc = prompts.load(cur, self.root)
        self.assertEqual(doc["action"]["type"], "choice")
        qs = prompts.build(prompts.load("v1", self.root), doc)
        self.assertEqual(list(qs), ["a_action", "b_action", "skip", "up15", "down15"])
        self.assertEqual(qs["b_action"], {"type": "choice", "instructions": CAND["instructions"],
                                          "criteria": CAND["criteria"]})

    def test_numbers_from_highest_file_not_current(self):
        self._run(self.prop, "0", "--prompts", self.root)                     # v2
        with open(os.path.join(self.root, "CURRENT"), "w", encoding="utf-8") as fh:
            fh.write("v1\n")                                                    # rolled back by hand
        rc, out, _ = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        self.assertEqual(prompts.current(self.root), "v3")
        self.assertIn("--- v1.action", out)

    def test_bad_k_and_digit_refused(self):
        rc, _, err = self._run(self.prop, "2", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("no candidate 2", err)
        with open(self.prop, "w", encoding="utf-8") as fh:
            json.dump({"candidates": [{**CAND, "instructions": "wait 15 minutes"}]}, fh)
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("digit", err)
        self.assertEqual(sorted(os.listdir(self.root)), ["CURRENT", "v1.json"])


class ProposeDryTest(unittest.TestCase):
    def test_dry_writes_proposal_from_fixture_and_sends_nothing(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        _write_log(os.path.join(tmp, "data", "decisions.jsonl"), synthetic_log())
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry",
                            "--date", "2026-09-22", "--root", tmp],
                           cwd=tmp, capture_output=True, text=True, timeout=120, env=_sh_env(self))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(tmp, "proposals", "2026-09-22.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(list(doc), ["candidates"])
        self.assertEqual(len(doc["candidates"]), 1)
        c = doc["candidates"][0]
        self.assertEqual(sorted(c), ["criteria", "instructions", "rationale"])
        self.assertEqual(list(c["criteria"]), ["buy", "sell", "hold"])
        self.assertIn("liquidity is deep", c["criteria"]["buy"])
        self.assertFalse(any(ch.isdigit() for ch in c["instructions"] + "".join(c["criteria"].values())))
        policy_table.load_candidates(os.path.join(tmp, "proposals", "2026-09-22.json"))   # the table accepts it
        with open(os.path.join(tmp, "logs", "propose.log"), encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("OK proposals/2026-09-22.json", log)
        self.assertIn("dry: 81 payloads, 0 sent", log)
        self.assertTrue(os.path.exists(os.path.join(tmp, "data", "digest-2026-09-22.md")))
        # the digest (and the table) read the pinned v1 root, never the live CURRENT (v2 since 2026-09-26)
        with open(os.path.join(tmp, "data", "digest-2026-09-22.md"), encoding="utf-8") as fh:
            dig = fh.read()
        self.assertIn(f"prompt_b v1 {prompts.sha('v1')}", dig)
        self.assertIn(prompts.load("v1")["action"]["instructions"], dig)
        self.assertFalse(os.path.exists(os.path.join(tmp, "proposals", "2026-09-22.md")))   # dry writes no table
        # no ledger row: jev and the table write only config.SENDS, which --root never moves, so the
        # dry night's no-send is held by "dry: 81 payloads, 0 sent" above and, in process, by
        # PolicyTableTest.test_dry_prints_81_and_sends_nothing with the ledger pointed at a temp file
        # (the repo's own data/sends.tsv is never read here: on the Mac the live loop appends to it
        # every minute, and a size compared across the run went red about once in fifty runs)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", log + r.stdout + r.stderr)

    def test_dry_needs_a_root_outside_the_repo(self):
        # 2026-09-28 (verifier): `propose.sh --dry` with no --root wrote the fixture proposal as the
        # repo's real proposals/<date>.json, and the one-run-per-date refusal then blocked that
        # night's real Claude call for good. Refused before anything is written, exit 2.
        for argv in (["--dry", "--date", "2026-09-22"], ["--dry", "--date", "2026-09-22", "--root", REPO]):
            r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), *argv],
                               cwd=REPO, capture_output=True, text=True, timeout=30, env=_sh_env(self))
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("--dry writes fixture files; pass --root DIR outside the repo", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(REPO, "proposals", "2026-09-22.json")))
        # a relative --root is taken from the invocation directory, never from the repo
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22", "--root", "sub"],
                           cwd=tmp, capture_output=True, text=True, timeout=120, env=_sh_env(self))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(tmp, "sub", "proposals", "2026-09-22.json")))
        self.assertFalse(os.path.exists(os.path.join(REPO, "sub")))

    def test_dry_refuses_the_repo_when_the_script_is_run_by_a_double_slash_path(self):
        # bash's `pwd -P` keeps a leading '//' that os.path.realpath drops, so REPO was "//<repo>" and
        # ROOT_REAL "/<repo>": the check compared the two strings and the fixture went into the repo's
        # proposals/ (61ebbb1 compares REPO_REAL). Run on a copy of the tree, never the checkout.
        copy = _tree_copy(self)
        r = subprocess.run(["/bin/bash", "/" + os.path.join(copy, "nightly", "propose.sh"), "--dry", "--date", "2026-09-23",
                            "--root", copy], capture_output=True, text=True, timeout=120, env=_sh_env(self))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("--dry writes fixture files; pass --root DIR outside the repo", r.stderr)
        self.assertEqual(sorted(os.listdir(copy)), ["loop", "nightly"])        # no proposals/, logs/ or data/

    def test_dry_refuses_the_repo_by_a_second_name(self):
        # realpath does not unify every second name for one directory (a bind mount; on the Mac a
        # case-only difference on case-insensitive APFS, or the /System/Volumes/Data firmlink): the check
        # compared two realpath strings, so --dry --root <the repo by such a name> wrote the fixture into
        # the repo's proposals/ and that date's real night was then refused. It compares identity too.
        env = _sh_env(self)
        copy = _tree_copy(self)
        wrap, alias = _second_name(self, copy, env)
        r = subprocess.run(wrap + ["/bin/bash", os.path.join(copy, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22",
                                   "--root", alias], capture_output=True, text=True, timeout=120, env=env)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("--dry writes fixture files; pass --root DIR outside the repo", r.stderr)
        self.assertEqual(sorted(os.listdir(copy)), ["loop", "nightly"])        # no proposals/, logs/ or data/

    def test_a_committed_table_also_refuses_a_second_run(self):
        # the json is gitignored: after a re-clone only the .md is there, and a rerun would rewrite
        # the committed table
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        _write_log(os.path.join(tmp, "data", "decisions.jsonl"), synthetic_log())
        os.makedirs(os.path.join(tmp, "proposals"))
        with open(os.path.join(tmp, "proposals", "2026-09-22.md"), "w", encoding="utf-8") as fh:
            fh.write("# policy table 2026-09-22\n")
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22", "--root", tmp],
                           cwd=tmp, capture_output=True, text=True, timeout=120, env=_sh_env(self))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("FAIL proposals/2026-09-22.md exists (the committed table)", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(tmp, "proposals", "2026-09-22.json")))
        with open(os.path.join(tmp, "proposals", "2026-09-22.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "# policy table 2026-09-22\n")

    def test_halt_present_skips_the_table(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        _write_log(os.path.join(tmp, "data", "decisions.jsonl"), synthetic_log())
        with open(os.path.join(tmp, "data", "HALT"), "w", encoding="utf-8") as fh:
            fh.write("by hand\n")
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry",
                            "--date", "2026-09-22", "--root", tmp],
                           cwd=tmp, capture_output=True, text=True, timeout=120, env=_sh_env(self))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(tmp, "logs", "propose.log"), encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("HALT present", log)
        self.assertNotIn("dry: 81 payloads", log)                    # policy_table.py never ran
        self.assertNotIn("OK proposals/", log)
        self.assertTrue(os.path.exists(os.path.join(tmp, "proposals", "2026-09-22.json")))
        # a HALT night still rebuilds the health page (the EXIT trap), where the HALT shows
        self.assertTrue(os.path.exists(os.path.join(tmp, "data", "dash.html")))
        self.assertNotIn("dash: loop.dash exit", log)

    def test_a_dash_that_fails_is_one_line_and_the_night_keeps_its_status(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        _write_log(os.path.join(tmp, "data", "decisions.jsonl"), synthetic_log())
        os.makedirs(os.path.join(tmp, "data", "dash.html"))                 # the page cannot be written
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry",
                            "--date", "2026-09-22", "--root", tmp],
                           cwd=tmp, capture_output=True, text=True, timeout=120, env=_sh_env(self))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(tmp, "logs", "propose.log"), encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("OK proposals/2026-09-22.json", log)
        self.assertIn("dash: loop.dash exit", log)
        self.assertNotIn("FAIL", log)
        self.assertLess(log.index("OK proposals/"), log.index("dash: loop.dash exit"))

    def test_usage_error_is_2_and_dry_needs_no_claude(self):
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--bogus"],
                           capture_output=True, text=True, timeout=30, env=_sh_env(self))
        self.assertEqual(r.returncode, 2)
        with open(os.path.join(REPO, "nightly", "propose.sh"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('--tools ""', src)
        self.assertNotIn("echo $CLAUDE_CODE_OAUTH_TOKEN", src)
        # The header's "May not" line NAMES prompts/ -- it is the promise never to write there
        # (CONTRACT §5) -- so the promise is asserted as present, and kept by checking that no
        # line of code (comments excluded) mentions prompts/ at all.
        self.assertIn("write under prompts/", src.split("# May not")[1].split("\n")[0])
        code = [l for l in src.splitlines() if not l.lstrip().startswith("#")]
        self.assertEqual([l for l in code if "prompts/" in l or "/prompts" in l], [])

    def test_the_scripts_environment_reaches_no_key_and_no_live_prompts(self):
        # blank key variables alone left jev.key() free to find a key FILE under the real HOME
        env = _sh_env(self)
        self.assertNotEqual(env["HOME"], os.path.expanduser("~"))
        self.assertEqual(os.listdir(env["HOME"]), [])
        code = ("from loop import config, jev, prompts\n"
                "try:\n    jev.key(); print('KEY FOUND')\nexcept jev.JevError as e:\n    print(e.kind)\n"
                "print(config.JEV_URL)\nimport sys\nprint(prompts.current(sys.argv[1]))\n")
        r = subprocess.run([sys.executable, "-c", code, env["JEVLOOP_PROMPTS"]], cwd=REPO, env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["no-key", "http://127.0.0.1:9/v1/systemone", "v1"])

    def test_a_trailing_date_or_root_is_a_usage_error_not_a_hang(self):
        # `shift 2` with one argument left fails and the loop never advanced: this used to spin
        for args in (["--date"], ["--root"], ["--dry", "--date"], ["--date", "2026-09-22", "--root"]):
            r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), *args],
                               capture_output=True, text=True, timeout=10, env=_sh_env(self))
            self.assertEqual(r.returncode, 2, args)
            self.assertIn("usage:", r.stderr, args)

    def _dry(self, tmp):
        return subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry",
                               "--date", "2026-09-22", "--root", tmp],
                              cwd=tmp, capture_output=True, text=True, timeout=120, env=_sh_env(self))

    def test_a_second_run_for_the_same_date_is_refused(self):
        # a missed slot that fires after 00:00Z and the regular slot digest the same day: the second
        # run must neither spend a Claude call nor overwrite the json (gitignored: gone for good)
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        _write_log(os.path.join(tmp, "data", "decisions.jsonl"), synthetic_log())
        self.assertEqual(self._dry(tmp).returncode, 0)
        paths = [os.path.join(tmp, "proposals", "2026-09-22.json"), os.path.join(tmp, "data", "digest-2026-09-22.md"),
                 os.path.join(tmp, "logs", "claude-2026-09-22.txt")]
        before = []
        for p in paths:
            with open(p, "rb") as fh:
                before.append((fh.read(), os.stat(p).st_mtime_ns))
        r = self._dry(tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr.count("FAIL"), 1, r.stderr)
        self.assertIn("FAIL proposals/2026-09-22.json exists: one run per day", r.stderr)
        self.assertNotIn("dry: 81 payloads", r.stderr)
        for p, (data, mtime) in zip(paths, before):
            with open(p, "rb") as fh:
                self.assertEqual(fh.read(), data, p)
            self.assertEqual(os.stat(p).st_mtime_ns, mtime, p)                 # not even rewritten in place

    def test_the_missed_slot_note_sees_a_table_under_the_root(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        _write_log(os.path.join(tmp, "data", "decisions.jsonl"), synthetic_log())
        os.makedirs(os.path.join(tmp, "proposals"))
        with open(os.path.join(tmp, "proposals", "2026-09-21.md"), "w", encoding="utf-8") as fh:
            fh.write("# policy table 2026-09-21\n")
        self.assertEqual(self._dry(tmp).returncode, 0)
        with open(os.path.join(tmp, "logs", "propose.log"), encoding="utf-8") as fh:
            self.assertNotIn("note: no proposal exists", fh.read())



class ShEnv(unittest.TestCase):
    """_sh_env, the environment every script in this module is started with."""

    def test_proxies_and_the_token_are_blank_whatever_the_runner_exports(self):
        runner = {v: "http://proxy.example:3128" for v in PROXY_VARS}
        runner.update(NO_PROXY="localhost", no_proxy="localhost", CLAUDE_CODE_OAUTH_TOKEN="runner-token",
                      TYPESAFE_API_KEY_LOOP="runner-key", TYPESAFE_API_KEY="runner-key")
        with mock.patch.dict(os.environ, runner):
            env = _sh_env(self)
        self.assertEqual({v: env[v] for v in PROXY_VARS}, dict.fromkeys(PROXY_VARS, ""))
        self.assertEqual((env["NO_PROXY"], env["no_proxy"]), ("*", "*"))
        self.assertEqual((env["CLAUDE_CODE_OAUTH_TOKEN"], env["TYPESAFE_API_KEY_LOOP"], env["TYPESAFE_API_KEY"]), ("", "", ""))
        self.assertEqual(env["TYPESAFE_BASE_URL"], "http://127.0.0.1:9")
        self.assertNotIn("runner-", "".join(env.values()))

    def test_tmpdir_is_a_fresh_dir_under_tmp_whatever_the_runners_is(self):
        with mock.patch.dict(os.environ, TMPDIR=REPO):                     # a runner TMPDIR inside the checkout
            env = _sh_env(self)
        self.assertEqual(os.path.dirname(env["TMPDIR"]), "/tmp")
        self.assertEqual(os.listdir(env["TMPDIR"]), [])
        self.assertNotEqual(env["TMPDIR"], _sh_env(self)["TMPDIR"])

    def test_every_script_this_module_starts_gets_it(self):
        # a subprocess.run without env= inherits the runner's proxies, token and HOME
        with open(__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        runs = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "run" and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess"]
        self.assertGreater(len(runs), 15)
        self.assertEqual([n.lineno for n in runs if not any(k.arg == "env" for k in n.keywords)], [])


class LiveBranch(unittest.TestCase):
    """propose.sh's live branch, driven end to end with a stub claude (JEVLOOP_CLAUDE), a temp token
    file (JEVLOOP_TOKEN_FILE) and a short cap (JEVLOOP_CLAUDE_CAP_S). data/HALT in the temp root
    keeps policy_table from sending (PROTOCOL §3.8), so nothing here reaches api.typesafe.ai."""
    TOKEN = "sekrit-token-value-never-printed"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)                  # holds a fake token and a stub claude
        _write_log(os.path.join(self.tmp, "data", "decisions.jsonl"), synthetic_log())
        with open(os.path.join(self.tmp, "data", "HALT"), "w", encoding="utf-8") as fh:
            fh.write("test: no sends\n")
        self.token = os.path.join(self.tmp, "token")
        with open(self.token, "w", encoding="utf-8") as fh:
            fh.write(self.TOKEN + "\n")
        self.saw = os.path.join(self.tmp, "saw")                         # what the stub saw: argv, cwd, token
        os.makedirs(self.saw)
        self.prompts = pin_v1(self)                                      # the digest in the prompt quotes v1

    def _stub(self, body):
        p = os.path.join(self.tmp, "claude")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/bash\n" + body)
        os.chmod(p, 0o755)
        return p

    def _run(self, stub, cap="2700", **extra):
        env = _sh_env(self, self.tmp, JEVLOOP_CLAUDE=stub, JEVLOOP_TOKEN_FILE=self.token, JEVLOOP_CLAUDE_CAP_S=cap,
                      JEVLOOP_PROMPTS=self.prompts, **extra)
        return subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--date", DAY.isoformat(), "--root", self.tmp],
                              capture_output=True, text=True, timeout=120, env=env, cwd=REPO)

    def _home(self, memory=None):
        """A HOME for the run: empty, or with ~/.claude/CLAUDE.md holding `memory`."""
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, ".claude"), exist_ok=True)
        if memory is not None:
            with open(os.path.join(home, ".claude", "CLAUDE.md"), "w", encoding="utf-8") as fh:
                fh.write(memory)
        return home

    def _everything_written(self):
        out = []
        for d in ("logs", "proposals", "data"):
            for f in os.listdir(os.path.join(self.tmp, d)):
                with open(os.path.join(self.tmp, d, f), errors="replace", encoding="utf-8") as fh:
                    out.append(fh.read())
        return "\n".join(out)

    def test_live_branch_end_to_end_token_set_never_printed(self):
        # the stub answers --version (propose.sh logs it), then records what the real call gets:
        # its argv NUL-separated (the prompt spans lines, and --tools takes an EMPTY argument), its
        # working directory and that directory's listing, and whether the token reached it
        stub = self._stub('[ "$1" = --version ] && {{ echo "9.9.9 (stub claude)"; exit 0; }}\n'
                          '[ -n "$CLAUDE_CODE_OAUTH_TOKEN" ] && echo TOKEN_SET >"{saw}/token"\n'
                          'printf "%s\\0" "$@" >"{saw}/argv"\n'
                          'pwd -P >"{saw}/cwd"\n'
                          'ls -A >"{saw}/ls"\n'
                          'cat <<"EOF"\nreply\n\n```json\n{{"candidates": [{{"rationale": "t", "instructions": "Decide.",'
                          ' "criteria": {{"buy": "pumping", "sell": "dumping", "hold": "else"}}}}]}}\n```\nEOF\n'.format(saw=self.saw))
        memory = "user memory the CLI loads\n"
        r = self._run(stub, HOME=self._home(memory))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.saw, "token")), "the stub never saw the token in its environment")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "proposals", f"{DAY.isoformat()}.json")))
        with open(os.path.join(self.tmp, "logs", "propose.log"), encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("claude exit 0 after", log)
        self.assertIn("(cap 2700 s awake)", log)
        self.assertIn("HALT present", log)                                    # policy_table never ran: no send
        self.assertNotIn("OK proposals/", log)
        for blob in (r.stdout, r.stderr, self._everything_written()):
            self.assertNotIn(self.TOKEN, blob)
        # the flags, exactly: no tool, no MCP, no settings file but ours, text out
        with open(os.path.join(self.saw, "argv"), "rb") as fh:
            argv = fh.read().decode("utf-8").split("\0")[:-1]
        repo = os.path.realpath(REPO)
        self.assertEqual(argv[0], "-p")
        with open(os.path.join(REPO, "nightly", "PROMPT.md"), encoding="utf-8") as fh:
            self.assertTrue(argv[1].startswith(fh.read().rstrip("\n") + "\n\n"))   # PROMPT.md, then the digest
        self.assertIn("B disagreements", argv[1])
        self.assertEqual(argv[2:], ["--tools", "", "--restricted", "--strict-mcp-config",
                                    "--settings", os.path.join(repo, "nightly", "settings.json"), "--output-format", "text"])
        for a in argv:
            self.assertNotIn(self.TOKEN, a)
        # the working directory: not the repo, not under it, empty, no CLAUDE.md above it, gone after
        with open(os.path.join(self.saw, "cwd"), encoding="utf-8") as fh:
            cwd = fh.read().strip()
        self.assertNotEqual(cwd, repo)
        self.assertFalse(cwd.startswith(repo + os.sep), cwd)
        with open(os.path.join(self.saw, "ls"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")
        d = os.path.dirname(cwd)
        while True:
            self.assertFalse(os.path.exists(os.path.join(d, "CLAUDE.md")), d)
            if d == os.path.dirname(d):
                break
            d = os.path.dirname(d)
        self.assertFalse(os.path.exists(cwd), "the empty cwd was not removed")
        # and the night's record: that cwd, the user memory's sha, the CLI's version
        self.assertIn("(empty); user memory ", log)
        self.assertIn("CLAUDE.md sha256 " + hashlib.sha256(memory.encode()).hexdigest()[:12] + "; cli 9.9.9 (stub claude)", log)

    REPLY = ('cat <<"EOF"\nreply\n\n```json\n{"candidates": [{"rationale": "t", "instructions": "Decide.",'
             ' "criteria": {"buy": "pumping", "sell": "dumping", "hold": "else"}}]}\n```\nEOF\n')

    def test_the_model_that_answered_is_logged_from_the_clis_own_transcript(self):
        # the stub keeps a session as the CLI does, under HOME's .claude/projects/<its cwd as a slug>;
        # propose.sh reads the model back after the call, which itself names none
        stub = self._stub('[ "$1" = --version ] && { echo "9.9.9 (stub claude)"; exit 0; }\n'
                          'printf "%s\\0" "$@" >"' + self.saw + '/argv"\n'
                          'd="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/$(pwd -P | sed "s/[^A-Za-z0-9]/-/g")"\n'
                          'mkdir -p "$d"\n'
                          'printf "%s\\n" \'{"type":"user","message":{"content":"x"}}\' '
                          '\'{"type":"assistant","message":{"model":"claude-stub-1","content":[]}}\' >"$d/0b9d.jsonl"\n'
                          + self.REPLY)
        home = self._home()
        r = self._run(stub, HOME=home)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.tmp, "logs", "propose.log"), encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("claude model claude-stub-1 (read from the CLI's transcript of this call, which names no model)", log)
        self.assertIn("$PY -m nightly.policy_table --writer-model claude-stub-1 --out proposals/", log.replace(sys.executable, "$PY"))
        with open(os.path.join(self.saw, "argv"), "rb") as fh:
            argv = fh.read().decode("utf-8").split("\0")[:-1]
        self.assertNotIn("--model", argv)                                     # recorded, not pinned
        self.assertEqual(argv[-2:], ["--output-format", "text"])
        projects = os.listdir(os.path.join(home, ".claude", "projects"))             # the temp HOME's, nowhere else
        self.assertEqual(len(projects), 1, projects)
        self.assertRegex(projects[0], r"-jevloop-claude-[A-Za-z0-9]+$")

    def test_a_night_whose_transcript_is_not_found_logs_unrecorded(self):
        stub = self._stub('[ "$1" = --version ] && { echo "9.9.9 (stub claude)"; exit 0; }\n' + self.REPLY)
        r = self._run(stub, HOME=self._home())
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.tmp, "logs", "propose.log"), encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("claude model unrecorded (read from the CLI's transcript", log)
        self.assertIn("HALT present", log)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "proposals", f"{DAY.isoformat()}.json")))   # the night went on

    def test_a_claude_md_above_the_temp_cwd_fails_the_night_before_any_send(self):
        # /tmp is shared and world-writable: a CLAUDE.md planted above claude's empty cwd would be
        # auto-loaded like the repo's was. The ancestors are walked and the night fails, nothing sent.
        tmpdir = os.path.join(self.tmp, "tmpbase")
        os.makedirs(tmpdir)
        with open(os.path.join(tmpdir, "CLAUDE.md"), "w", encoding="utf-8") as fh:
            fh.write("# planted\n")
        stub = self._stub('printf "%s\\0" "$@" >"' + self.saw + '/argv"\necho "{}"\n')
        r = self._run(stub, TMPDIR=tmpdir)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.tmp, "logs", "propose.log"), encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("/CLAUDE.md exists above claude's cwd", log)
        self.assertIn("nothing sent", log)
        self.assertFalse(os.path.exists(os.path.join(self.saw, "argv")))          # the stub never ran
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "proposals", f"{DAY.isoformat()}.json")))
        self.assertEqual([d for d in os.listdir(tmpdir) if d.startswith("jevloop-claude.")], [])   # the temp cwd is gone

    def test_a_claude_file_in_any_ancestor_of_tmpdir_fails_the_night_and_the_suites_tmpdir_passes(self):
        # the ancestor walk goes all the way up, and knows all three names; the suite's own TMPDIR
        # (_sh_env: a fresh dir under /tmp) has none of them above it, so the night runs there
        stub = self._stub('[ "$1" = --version ] && { echo "9.9.9 (stub claude)"; exit 0; }\n'
                          'pwd -P >"' + self.saw + '/cwd"\n'
                          'cat <<"EOF"\n```json\n{"candidates": [{"rationale": "t", "instructions": "Decide.",'
                          ' "criteria": {"buy": "pumping", "sell": "dumping", "hold": "else"}}]}\n```\nEOF\n')
        for name, make in (("CLAUDE.md", "file"), (".claude", "dir")):
            base = os.path.join(self.tmp, "anc-" + name.strip("."))
            tmpdir = os.path.join(base, "deeper", "tmp")                   # the file two levels above TMPDIR
            os.makedirs(tmpdir)
            if make == "dir":
                os.makedirs(os.path.join(base, name))
            else:
                with open(os.path.join(base, name), "w", encoding="utf-8") as fh:
                    fh.write("# planted\n")
            r = self._run(stub, TMPDIR=tmpdir)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(f"FAIL {os.path.realpath(base)}/{name} exists above claude's cwd", r.stderr)
            self.assertIn("nothing sent", r.stderr)
            self.assertFalse(os.path.exists(os.path.join(self.saw, "cwd")), name)             # the stub never ran
            self.assertEqual(os.listdir(tmpdir), [], name)                                     # the temp cwd is gone
        r = self._run(stub)                                                                     # _sh_env's own TMPDIR
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("FAIL", r.stderr)
        self.assertIn("claude exit 0 after", r.stderr)
        with open(os.path.join(self.saw, "cwd"), encoding="utf-8") as fh:
            self.assertTrue(fh.read().startswith(os.path.realpath("/tmp") + os.sep))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "proposals", f"{DAY.isoformat()}.json")))

    def test_a_hung_claude_is_one_fail_line_and_the_night_ends_clean(self):
        stub = self._stub('[ "$1" = --version ] && { echo "9.9.9 (stub claude)"; exit 0; }\nsleep 30\n')
        t = time.monotonic()
        r = self._run(stub, cap="1")
        self.assertEqual(r.returncode, 0)
        self.assertLess(time.monotonic() - t, 25)
        with open(os.path.join(self.tmp, "logs", "propose.log"), encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("claude exit 124 after", log)
        self.assertIn("FAIL claude capped at 1 s awake", log)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "proposals", f"{DAY.isoformat()}.json")))

    def test_a_failing_claude_is_one_fail_line(self):
        stub = self._stub('pwd -P >"%s/cwd"; echo boom >&2; exit 7\n' % self.saw)
        r = self._run(stub, HOME=self._home())
        self.assertEqual(r.returncode, 0)
        with open(os.path.join(self.tmp, "logs", "propose.log"), encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("FAIL claude exit 7", log)
        self.assertIn("CLAUDE.md absent; cli unknown", log)                  # no user memory; --version failed too
        with open(os.path.join(self.saw, "cwd"), encoding="utf-8") as fh:
            self.assertFalse(os.path.exists(fh.read().strip()), "a failed night left its empty cwd behind")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "data", "dash.html")))   # a failed night rebuilds it too
        with open(os.path.join(self.tmp, "logs", f"claude-{DAY.isoformat()}.err"), encoding="utf-8") as fh:
            self.assertIn("boom", fh.read())

    def test_a_reply_without_one_json_block_is_invalid(self):
        stub = self._stub('echo "no block here"\n')
        r = self._run(stub)
        self.assertEqual(r.returncode, 0)
        with open(os.path.join(self.tmp, "logs", "propose.log"), encoding="utf-8") as fh:
            self.assertIn("FAIL invalid proposal", fh.read())

    def test_a_reply_that_cannot_be_written_leaves_no_json(self):
        # "\ud800" parses to a lone surrogate, which UTF-8 cannot encode: the write fails. Dumped
        # into the target directly, that left a truncated json for a table or a promote to read.
        stub = self._stub('cat <<"EOF"\n```json\n{"candidates": [{"rationale": "\\ud800", "instructions": "Decide.",'
                          ' "criteria": {"buy": "pumping", "sell": "dumping", "hold": "else"}}]}\n```\nEOF\n')
        r = self._run(stub)
        self.assertEqual(r.returncode, 0)
        with open(os.path.join(self.tmp, "logs", "propose.log"), encoding="utf-8") as fh:
            self.assertIn("FAIL invalid proposal", fh.read())
        self.assertEqual([f for f in os.listdir(os.path.join(self.tmp, "proposals")) if f.startswith(DAY.isoformat())], [])

    def test_a_day_that_has_a_json_spends_no_claude_call(self):
        prop = os.path.join(self.tmp, "proposals", f"{DAY.isoformat()}.json")
        os.makedirs(os.path.dirname(prop))
        with open(prop, "w", encoding="utf-8") as fh:
            fh.write('{"candidates": "the first run\'s, which a table may vouch for"}\n')
        stub = self._stub('echo called >"%s/called"\n' % self.saw)
        r = self._run(stub)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(os.listdir(self.saw), [])                                 # not even --version
        with open(prop, encoding="utf-8") as fh:
            self.assertIn("the first run's", fh.read())
        with open(os.path.join(self.tmp, "logs", "propose.log"), encoding="utf-8") as fh:
            self.assertIn(f"FAIL proposals/{DAY.isoformat()}.json exists", fh.read())


class Capped(unittest.TestCase):
    """nightly/capped.py: the claude call's cap on awake seconds (propose.sh wires it in)."""
    PY = sys.executable                       # /opt/homebrew/bin/python3 under `make test` on the Mac; whatever runs the suite elsewhere

    def _run(self, *args):
        return subprocess.run([self.PY, "-m", "nightly.capped", *args], cwd=REPO, capture_output=True, text=True, timeout=30,
                              env=_sh_env(self))

    def test_exit_is_the_commands_own(self):
        self.assertEqual(self._run("5", "--", "true").returncode, 0)
        self.assertEqual(self._run("5", "--", "sh", "-c", "exit 7").returncode, 7)

    def test_a_hang_exits_124_and_kills_the_child(self):
        t = time.monotonic()
        r = self._run("1", "--", "sleep", "20")
        self.assertEqual(r.returncode, 124)
        self.assertLess(time.monotonic() - t, 10)
        self.assertIn("exceeded 1 s awake", r.stderr)

    def test_the_cap_ends_the_childs_whole_process_group(self):
        # a stub that hangs in `wait` on two children of its own: one that dies of SIGTERM and one that
        # ignores it. Only the direct child used to be terminated, and the stub's `sleep 30` outlived
        # every hung-claude test. Now the group gets SIGTERM, then SIGKILL once the child is gone.
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        pids = os.path.join(tmp, "pids")
        script = (f'sleep 30 >/dev/null 2>&1 & echo $! >>"{pids}"; (trap "" TERM; exec sleep 30) >/dev/null 2>&1 &'
                  f' echo $! >>"{pids}"; wait')                        # (off the pipes: a survivor must not hold run() open)
        t = time.monotonic()
        r = self._run("0.3", "--", "sh", "-c", script)
        self.assertEqual(r.returncode, 124, r.stderr)
        self.assertLess(time.monotonic() - t, 5)                         # SIGKILL follows the child, not the whole grace
        self.assertEqual(_gone(_pids(pids, 2)), [], "a grandchild outlived the cap")

    def test_a_signal_to_capped_is_passed_on_to_the_childs_group(self):
        # the child leads a session of its own, so launchd's SIGTERM (or ^C at a terminal) no longer
        # reaches it directly: capped passes it on, and exits as the child did (128 + 15)
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        pids = os.path.join(tmp, "pids")
        p = subprocess.Popen([self.PY, "-m", "nightly.capped", "30", "--", "sh", "-c", f'sleep 30 & echo $! >"{pids}"; wait'],
                             cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=_sh_env(self))
        self.addCleanup(p.stderr.close)
        grandchild = _pids(pids, 1)
        p.send_signal(signal.SIGTERM)
        self.assertEqual(p.wait(timeout=10), 128 + signal.SIGTERM)
        self.assertEqual(_gone(grandchild), [])

    def test_what_the_command_leaves_running_is_ended_when_it_exits(self):
        # 2026-09-28 (pre-merge verifier): in a session of its own, a helper the command forked and left
        # running escaped launchd's cleanup of the job's group after a NORMAL exit; capped ends the group
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        pids = os.path.join(tmp, "pids")
        r = self._run("30", "--", "sh", "-c", f'sleep 30 >/dev/null 2>&1 & echo $! >"{pids}"; exit 3')
        self.assertEqual(r.returncode, 3, r.stderr)                     # the command's own code, unchanged
        self.assertEqual(_gone(_pids(pids, 1)), [], "a process the command left behind outlived capped")

    def test_a_leftover_that_ignores_sigterm_is_killed_after_the_grace(self):
        # _end_group's SIGKILL fallback: a process the command left behind that ignores SIGTERM
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        pids = os.path.join(tmp, "pids")
        t = time.monotonic()
        r = self._run("30", "--", "sh", "-c", f'(trap "" TERM; exec sleep 30) >/dev/null 2>&1 & echo $! >"{pids}"; exit 0')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(time.monotonic() - t, 10)
        self.assertEqual(_gone(_pids(pids, 1)), [], "a leftover that ignores SIGTERM outlived capped")

    def test_sigquit_is_passed_on_too(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        pids = os.path.join(tmp, "pids")
        import resource
        p = subprocess.Popen([self.PY, "-m", "nightly.capped", "30", "--", "sh", "-c", f'sleep 30 & echo $! >"{pids}"; wait'],
                             cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=_sh_env(self),
                             preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0)))   # SIGQUIT dumps core: not in the checkout
        self.addCleanup(p.stderr.close)
        grandchild = _pids(pids, 1)
        p.send_signal(signal.SIGQUIT)
        self.assertEqual(p.wait(timeout=10), 128 + signal.SIGQUIT)
        self.assertEqual(_gone(grandchild), [])

    def test_usage_is_2_and_a_missing_command_is_127(self):
        self.assertEqual(self._run("x", "--", "true").returncode, 2)
        self.assertEqual(self._run("5", "true").returncode, 2)
        self.assertEqual(self._run("0", "--", "true").returncode, 2)
        self.assertEqual(self._run("5", "--", "/nonexistent-cmd").returncode, 127)

    def test_a_child_killed_by_a_signal_exits_128_plus_the_signal(self):
        # subprocess reports -15 for SIGTERM; sys.exit(-15) would exit 241, which reads as the
        # command's own code. A shell says 143, and so does capped.
        r = subprocess.run([sys.executable, "-m", "nightly.capped", "5", "--", "sh", "-c", "kill -TERM $$"],
                           cwd=REPO, capture_output=True, text=True, timeout=30, env=_sh_env(self))
        self.assertEqual(r.returncode, 128 + 15)

    def test_propose_sh_rebuilds_the_dash_at_the_end_of_every_night_non_fatally(self):
        with open(os.path.join(REPO, "nightly", "propose.sh"), encoding="utf-8") as fh:
            src = fh.read()
        code = [l for l in src.splitlines() if not l.lstrip().startswith("#")]
        dash = [l for l in code if "-m loop.dash" in l]
        self.assertEqual(len(dash), 1)
        self.assertIn('--log "$ROOT/data/decisions.jsonl" --out "$ROOT/data/dash.html"', dash[0])
        self.assertIn('|| log "dash:', code[code.index(dash[0]) + 2])                # the call spans two lines
        self.assertIn('--data "$ROOT/data" --proposals "$ROOT/proposals" ${PROMPTS_ROOT:+--prompts "$PROMPTS_ROOT"}', code[code.index(dash[0]) + 1])
        # the rebuild runs from an EXIT trap, so a HALT night or a failed claude night rebuilds it
        # too. The trap is installed after the usage (2) and guard (3) exits and after logs/ exists,
        # and before the first FAIL can end a night; it keeps the night's exit status.
        at = lambda frag: [i for i, l in enumerate(code) if frag in l]
        trap = at("trap on_exit EXIT")
        self.assertEqual(len(trap), 1)
        self.assertGreater(trap[0], at('guard_path "$CWD_REAL" cwd')[0])
        self.assertGreater(trap[0], at('mkdir -p "$LOGS"')[0])
        self.assertLess(trap[0], at('[ -x "$PY" ] || fail')[0])
        self.assertTrue(all(i > trap[0] for i in at('fail "')), "a FAIL before the trap would skip the dash")
        self.assertEqual(at("trap "), trap)                                           # no second EXIT trap replaces it
        self.assertIn("exit $st", src.split("on_exit() {")[1].split("\n}")[0])
        # the table's OK line is still logged before the night exits, so before the dash runs
        self.assertEqual(len(at('log "OK proposals/$DATE.json"')), 1)
        # and a --dry run against a temp root writes the page there, never into the repo's data/
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with open(os.path.join(tmp, "decisions.jsonl"), "w", encoding="utf-8") as fh:
            pass
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22", "--root", tmp],
                           capture_output=True, text=True, timeout=120, env=_sh_env(self))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(tmp, "data", "dash.html")))
        with open(os.path.join(tmp, "logs", "propose.log"), encoding="utf-8") as fh:
            self.assertIn("note: no proposal exists for 2026-09-21 (a missed slot?); this run is for 2026-09-22 only", fh.read())

    def test_propose_sh_guards_repo_root_and_cwd(self):
        with open(os.path.join(REPO, "nightly", "propose.sh"), encoding="utf-8") as fh:
            code = [l for l in fh.read().splitlines() if not l.lstrip().startswith("#")]
        self.assertEqual([l for l in code if l.startswith("guard_path ")],
                         ['guard_path "$REPO" repo', 'guard_path "$ROOT_REAL" root', 'guard_path "$CWD_REAL" cwd'])
        self.assertLess(code.index('ROOT_REAL="$(realpath_py "$ROOT")"'), code.index('guard_path "$ROOT_REAL" root'))
        # the cwd as realpath_py spells it, refused when empty, for the guard and a relative --root alike
        rel = [l for l in code if l.startswith('case "$ROOT" in /*) ;; *) ROOT=')]
        self.assertEqual(len(rel), 1)
        self.assertIn('ROOT="$CWD_REAL/$ROOT"', rel[0])
        self.assertLess(code.index('CWD_REAL="$(realpath_py .)"'), code.index(rel[0]))
        self.assertTrue(code[code.index('CWD_REAL="$(realpath_py .)"') + 1].startswith('[ -n "$CWD_REAL" ] || {'))
        self.assertTrue(any('"$PY" -I -B -c' in l and "cycle.forbidden" in l for l in code))   # isolated, no bytecode
        self.assertTrue(any("cycle.forbidden(sys.argv[2])" in l for l in code))          # the same guard as the tick's
        env = _sh_env(self)                                      # the guard reads $HOME: the forbidden prefix is under the run's HOME
        forbidden = os.path.join(env["HOME"], "Projects", "crypto-trading-system")
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--root", os.path.join(forbidden, "x")],
                           capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(r.returncode, 3)
        self.assertIn("forbidden prefix (root)", r.stderr)

    def test_the_guard_sees_the_forbidden_tree_through_a_symlinked_home(self):
        # the paths checked are physical (pwd -P) and the prefixes were matched only as written: with
        # HOME a symlink, --root under the forbidden tree ran the whole dry night there (cycle.forbidden,
        # which realpaths the prefix, refused). Both spellings are matched now; nothing is written.
        env = _sh_env(self)
        real = os.path.join(env["HOME"], "real")
        link = os.path.join(env["HOME"], "link")
        forbidden_real = os.path.join(real, "Projects", "crypto-trading-system", "x")      # the forbidden tree
        forbidden_via_link = os.path.join(link, "Projects", "crypto-trading-system", "x")  # the forbidden tree, symlinked
        os.makedirs(forbidden_real)
        os.symlink(real, link)
        for home in (link, real):                                  # HOME a link; HOME real and --root through the link
            env["HOME"] = home
            r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22",
                                "--root", forbidden_via_link], capture_output=True, text=True, timeout=30, env=env)
            self.assertEqual(r.returncode, 3, (home, r.stderr))
            self.assertIn("forbidden prefix (root)", r.stderr)
            self.assertEqual(os.listdir(forbidden_real), [])      # nothing written under the tree
        # a --root that does not exist yet is resolved, not checked as typed (pre-merge verifier): through
        # the link, with '//', '/./' or '..' in it, or relative from a sibling directory
        env["HOME"] = real
        sib = os.path.join(real, "Projects", "jevtrader")
        os.makedirs(sib)
        projects = os.path.join(real, "Projects")
        for root, cwd in ((os.path.join(link, "Projects", "crypto-trading-system", "new1"), None),       # the forbidden tree, via the link
                          (projects + "//crypto-trading-system/new2", None),                          # the forbidden tree, '//'
                          (projects + "/./crypto-trading-system/new3", None),                         # the forbidden tree, '/./'
                          (projects + "/../Projects/crypto-trading-system/new4", None),               # the forbidden tree, '..'
                          ("../crypto-trading-system/new5", sib)):                                    # the forbidden tree, relative
            r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22",
                                "--root", root], capture_output=True, text=True, timeout=30, env=env, cwd=cwd)
            self.assertEqual(r.returncode, 3, (root, r.stderr))
            self.assertIn("forbidden prefix (root)", r.stderr)
        self.assertEqual(sorted(os.listdir(os.path.join(real, "Projects", "crypto-trading-system"))), ["x"])   # nothing created

    def test_the_guard_knows_the_forbidden_tree_by_a_second_name(self):
        # realpath does not unify every second name for one directory (a bind mount; on the Mac a
        # case-only difference on case-insensitive APFS, or the /System/Volumes/Data firmlink), and
        # cycle.forbidden matched strings only: --root under the tree by such a name ran the whole dry
        # night there. It now knows the tree by (st_dev, st_ino) as well.
        env = _sh_env(self)
        forbidden = os.path.join(env["HOME"], "Projects", "crypto-trading-system")   # the forbidden tree, under the run's HOME
        os.makedirs(os.path.join(forbidden, "x"))
        wrap, alias = _second_name(self, forbidden, env)
        r = subprocess.run(wrap + ["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22",
                                   "--root", os.path.join(alias, "night")], capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("forbidden prefix (root)", r.stderr)
        self.assertEqual(os.listdir(forbidden), ["x"])                                # nothing written under the tree

    def test_the_header_claims_what_the_identity_check_covers_and_no_more(self):
        # The header said a second name realpath keeps, "a bind mount" first, could not hide the tree.
        # cycle.forbidden compares each prefix with the path's ancestors: a bind mount of <tree>/sub
        # ran the whole dry night inside the tree (round-4 checker). The header now names the gap;
        # tests/test_cycle.py holds the docstring to the same claim and the behaviour to both.
        with open(os.path.join(REPO, "nightly", "propose.sh"), encoding="utf-8") as fh:
            words = " ".join(l.strip().lstrip("#").strip() for l in fh.read().splitlines() if l.lstrip().startswith("#"))
        # The round-4c checker then mounted an overlay of the tree (the same files under another st_dev), which
        # the identity check cannot know either: the header names that gap too
        for claim, said in (("a second name realpath keeps (a bind mount;", False),
                            ("a second name realpath keeps for the tree itself or one of its ancestors", False),
                            ("a second name that keeps the device and inode of the tree or one of its ancestors", True),
                            ("Not known: a name with a device of its own (an overlay,", True),
                            ("or a second name for a directory inside the tree (a bind mount of a subdirectory)", True)):
            self.assertEqual(claim in words, said, claim)                           # the claim, not the whole header, on a failure

    def test_every_write_goes_under_the_root_the_guard_checked(self):
        # the guard checked the --root's realpath and every write went to the --root as typed: realpath
        # pops a '..' after a directory that does not exist, so the guard saw a path beside the tree,
        # while `mkdir -p` on the typed path created that directory inside the tree on its way there
        env = _sh_env(self)
        forbidden = os.path.join(env["HOME"], "Projects", "crypto-trading-system")   # the forbidden tree, under the run's HOME
        os.makedirs(os.path.join(forbidden, "x"))
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22",
                            "--root", os.path.join(forbidden, "newdir", "..", "..", "jevroot")],
                           capture_output=True, text=True, timeout=120, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.listdir(forbidden), ["x"])                                # no newdir inside the tree
        self.assertTrue(os.path.exists(os.path.join(env["HOME"], "Projects", "jevroot", "proposals", "2026-09-22.json")), r.stderr)

    def test_a_root_with_a_newline_is_refused(self):
        # `$(...)` strips trailing newlines: a --root ending in one reached the guard as its sibling
        # without it (here a symlink out of the tree) while the night was written under the directory
        # with it, inside the tree. A --root that names such a directory through a symlink, or has a
        # newline anywhere, is refused too, before anything is written.
        env = _sh_env(self)
        forbidden = os.path.join(env["HOME"], "Projects", "crypto-trading-system")   # the forbidden tree, under the run's HOME
        elsewhere = os.path.join(env["HOME"], "elsewhere")
        os.makedirs(os.path.join(forbidden, "d\n"))
        os.makedirs(elsewhere)
        os.symlink(elsewhere, os.path.join(forbidden, "d"))                  # "d" leads out of the tree, "d\n" does not
        os.symlink(os.path.join(forbidden, "d\n"), os.path.join(env["HOME"], "s"))   # no newline, but its realpath has one
        for root, why in ((os.path.join(forbidden, "d\n"), "propose: --root contains a newline; refusing"),
                          (os.path.join(env["HOME"], "a\nb"), "propose: --root contains a newline; refusing"),
                          (os.path.join(env["HOME"], "s"), "propose: cannot resolve --root")):
            r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22",
                                "--root", root], capture_output=True, text=True, timeout=120, env=env)
            self.assertEqual(r.returncode, 3, (root, r.stderr))
            self.assertIn(why, r.stderr)
        self.assertEqual(os.listdir(os.path.join(forbidden, "d\n")), [])
        self.assertEqual(os.listdir(elsewhere), [])
        self.assertFalse(os.path.exists(os.path.join(env["HOME"], "a\nb")))

    def test_a_working_directory_whose_name_ends_in_a_newline_is_refused(self):
        # The cwd was taken as `$(pwd -P)`, which strips trailing newlines, for the cwd guard and for a
        # relative --root (round-4 checker): started from <tree>/d<newline>, with <tree>/d a symlink out
        # of the tree, the guard checked the symlink's target and the dry night ran from inside the
        # tree; and a relative --root from <home>/c<newline> was written under <home>/c's target, not
        # the directory named. The cwd is now taken as realpath_py spells it, which refuses a newline.
        env = _sh_env(self)
        forbidden = os.path.join(env["HOME"], "Projects", "crypto-trading-system")   # the forbidden tree, under the run's HOME
        elsewhere = os.path.join(env["HOME"], "elsewhere")
        os.makedirs(os.path.join(forbidden, "d\n"))
        os.makedirs(elsewhere)
        os.symlink(elsewhere, os.path.join(forbidden, "d"))                   # "d" leads out of the tree, "d\n" does not
        os.makedirs(os.path.join(env["HOME"], "c\n"))
        os.symlink(elsewhere, os.path.join(env["HOME"], "c"))                 # "c" leads elsewhere, "c\n" is itself
        for cwd, root in ((os.path.join(forbidden, "d\n"), os.path.join(env["HOME"], "root2")),   # the cwd is inside the tree
                          (os.path.join(env["HOME"], "c\n"), "rel")):                            # a relative --root
            r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22",
                                "--root", root], capture_output=True, text=True, timeout=120, env=env, cwd=cwd)
            self.assertEqual(r.returncode, 3, (cwd, r.stderr))
            self.assertIn("propose: cannot resolve the working directory (or its name has a newline); refusing", r.stderr)
            self.assertEqual(os.listdir(cwd), [], cwd)                        # nothing written where it was started
        self.assertFalse(os.path.exists(os.path.join(env["HOME"], "root2")))
        self.assertEqual(os.listdir(elsewhere), [])                           # nor under a sibling's target

    def test_realpath_py_answers_for_a_name_that_is_not_utf8_whatever_stdout_encodes(self):
        # realpath_py printed the path as text: under a strict UTF-8 locale print() raised on a name that is not
        # UTF-8, the error went to /dev/null, and the empty answer refused a good directory as 'cannot resolve
        # (or its name has a newline)' (round-4c checker, Linux only: APFS names are UTF-8). It writes bytes
        # now. Its snippet is run as propose.sh has it, without -I so PYTHONIOENCODING can make stdout strict.
        with open(os.path.join(REPO, "nightly", "propose.sh"), encoding="utf-8") as fh:
            body = re.search(r"(?ms)^realpath_py\(\) \{.*?-c '([^']*)'", fh.read()).group(1)
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        odd = os.path.join(os.fsencode(tmp), b"a\xffb")
        try:
            os.mkdir(odd)
        except OSError as e:                                                  # a filesystem that takes only UTF-8 names
            self.skipTest(f"cannot make a directory whose name is not UTF-8 here: {e}")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8:strict"}
        r = subprocess.run([sys.executable, "-B", "-c", body, odd], capture_output=True, timeout=60, env=env)
        self.assertEqual((r.returncode, r.stdout), (0, b"path:" + os.path.realpath(odd) + b"\n"), r.stderr)
        r = subprocess.run([sys.executable, "-B", "-c", body, os.path.join(os.fsencode(tmp), b"x\ny")],
                           capture_output=True, timeout=60, env=env)
        self.assertEqual((r.returncode, r.stdout), (0, b""))                 # a newline still gives nothing

    def test_the_guard_never_imports_the_working_directory_and_refuses_when_it_cannot_answer(self):
        # 2026-09-28 (second pre-merge pass): the guard's python had the cwd on sys.path, after the repo
        # (so loop/ always came from the repo) but before the standard library: started from inside
        # another tree, that tree's json.py, hashlib.py, ... shadowed the modules loop.cycle imports, ran,
        # and left their bytecode there, before the guard answered. And an interpreter that printed
        # nothing and exited 0 read as "not forbidden".
        env = _sh_env(self)
        elsewhere = os.path.join(env["HOME"], "elsewhere")
        os.makedirs(elsewhere)
        marker = os.path.join(elsewhere, "imported")
        with open(os.path.join(elsewhere, "json.py"), "w", encoding="utf-8") as fh:   # loop.cycle imports json
            fh.write(f"open({marker!r}, 'w').close()\n")
        root = os.path.join(env["HOME"], "root")
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22", "--root", root],
                           capture_output=True, text=True, timeout=60, env=env, cwd=elsewhere)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(marker), "the guard imported the working directory's json.py")
        self.assertEqual(sorted(os.listdir(elsewhere)), ["json.py"])            # no __pycache__ written there
        silent = os.path.join(env["HOME"], "silent-python")
        with open(silent, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nexit 0\n")                              # runs, answers nothing, exits 0
        os.chmod(silent, 0o755)
        env["JEVLOOP_PY"] = silent
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22",
                            "--root", os.path.join(env["HOME"], "root2")], capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("refusing", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(env["HOME"], "root2")))

    def test_the_default_date_never_imports_the_working_directory(self):
        # Without --date the day was computed by a plain "$PY" -c before `cd "$REPO"`, so from the
        # invocation directory: run by hand from one holding a datetime.py, propose.sh imported it, left
        # its bytecode there, and the night ended 'FAIL bad --date' (round-4 guard implementer). It runs
        # -I -B now, like every python before the cd. That python ignores the suite's clock modes
        # (PYTHONPATH), so the date is the real clock's yesterday: its value is never checked, only
        # that the night ran on it.
        env = _sh_env(self)
        elsewhere = os.path.join(env["HOME"], "elsewhere")
        os.makedirs(elsewhere)
        marker = os.path.join(env["HOME"], "imported")
        with open(os.path.join(elsewhere, "datetime.py"), "w", encoding="utf-8") as fh:
            fh.write(f"open({marker!r}, 'w').close()\n")
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--root", os.path.join(env["HOME"], "root")],
                           capture_output=True, text=True, timeout=120, env=env, cwd=elsewhere)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(marker), "the default date imported the working directory's datetime.py")
        self.assertEqual(os.listdir(elsewhere), ["datetime.py"])                  # no __pycache__ written there
        m = re.search(r" propose start date=(\d{4}-\d\d-\d\d) dry=1 ", r.stderr)
        self.assertIsNotNone(m, r.stderr)
        self.assertIn(f" propose OK proposals/{m.group(1)}.json", r.stderr)
        # every python started before `cd "$REPO"` runs isolated and writes no bytecode (the dash's runs
        # in a subshell that cds there first)
        with open(os.path.join(REPO, "nightly", "propose.sh"), encoding="utf-8") as fh:
            code = [l for l in fh.read().splitlines() if not l.lstrip().startswith("#")]
        runs = [l for l in code[:code.index('cd "$REPO" || fail "cd $REPO"')]
                if re.search(r'"\$PY" -', l) and 'cd "$REPO" && "$PY" -' not in l]
        self.assertEqual(len(runs), 3, runs)                                        # the guard, realpath_py, the default date
        self.assertTrue(all('"$PY" -I -B -c ' in l for l in runs), runs)

    def test_a_guard_that_answers_nothing_refuses(self):
        # The silent interpreter above never reaches the guard: realpath_py refuses first. This one runs
        # every other call and answers nothing (exit 0, no output) only to cycle.forbidden, so the
        # guard's own "neither ok nor forbidden" branch is what must refuse. Before 61ebbb1 the empty
        # answer read as "not forbidden" and the night ran.
        env = _sh_env(self)
        wrapper = os.path.join(env["HOME"], "python-silent-at-the-guard")
        with open(wrapper, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\ncase "$*" in *cycle.forbidden*) exit 0 ;; esac\nexec "$REAL_PY" "$@"\n')
        os.chmod(wrapper, 0o755)
        env.update(JEVLOOP_PY=wrapper, REAL_PY=sys.executable)
        root = os.path.join(env["HOME"], "root")
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22", "--root", root],
                           capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("propose: the path guard could not run (repo); refusing", r.stderr)
        self.assertFalse(os.path.exists(root))

    def test_propose_sh_defaults_are_the_mac_paths_and_launchd_sets_no_knob(self):
        # The JEVLOOP_* variables are for the suite (here, and on a host without Homebrew or
        # caffeinate). Under launchd the plist sets only PATH, so every one of them is its default,
        # and the defaults must stay the paths STEPS.md installs against.
        with open(os.path.join(REPO, "nightly", "propose.sh"), encoding="utf-8") as fh:
            src = fh.read()
        for line in ('PY="${JEVLOOP_PY:-/opt/homebrew/bin/python3}"',
                     'CLAUDE="${JEVLOOP_CLAUDE:-/opt/homebrew/bin/claude}"',
                     'CAFFEINATE="${JEVLOOP_CAFFEINATE:-/usr/bin/caffeinate}"',
                     'TOKEN_FILE="${JEVLOOP_TOKEN_FILE:-$HOME/.secondbrain-secrets/oauth_token}"'):
            self.assertIn(line, src)
        for plist in ("com.alexward.jevloop.loop.plist", "com.alexward.jevloop.nightly.plist"):
            with open(os.path.join(REPO, "launchd", plist), encoding="utf-8") as fh:
                self.assertNotIn("JEVLOOP", fh.read(), plist)
        # and a --dry run with no knob at all still refuses, in one FAIL line, when the Mac's
        # python is absent, rather than falling back to whatever python3 is on PATH
        if not os.path.exists("/opt/homebrew/bin/python3"):
            tmp = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
            r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22", "--root", tmp],
                               capture_output=True, text=True, timeout=30, env=_sh_env(self, JEVLOOP_PY=""))
            self.assertEqual(r.returncode, 0)
            self.assertIn("FAIL no python at /opt/homebrew/bin/python3", r.stderr)

    def test_propose_sh_wires_the_cap_around_claude_under_caffeinate(self):
        with open(os.path.join(REPO, "nightly", "propose.sh"), encoding="utf-8") as fh:
            src = fh.read()
        code = [l for l in src.splitlines() if not l.lstrip().startswith("#")]
        call = [l for l in code if '"$CAFFEINATE" -i' in l]
        self.assertEqual(len(call), 1)
        # caffeinate outermost, then capped BY PATH: the call runs in an empty temp dir, where
        # `-m nightly.capped` would not resolve
        self.assertIn('cd "$WORK"', call[0])
        self.assertIn('"$CAFFEINATE" -i "$PY" "$REPO/nightly/capped.py" "$CLAUDE_CAP_S" --', call[0])
        self.assertEqual([l for l in code if "-m nightly.capped" in l], [])
        self.assertIn('CLAUDE_CAP_S="${JEVLOOP_CLAUDE_CAP_S:-2700}"', src)
        self.assertIn('[ $rc -eq 124 ] && fail "claude capped', src)


class LaunchdPlists(unittest.TestCase):
    """Both launchd/*.plist files are well-formed XML and parse to exactly the keys and values
    STEPS.md installs. A '--' inside a comment (XML 1.0 §2.5 forbids it) made expat and xmllint
    refuse the whole loop plist, though the installed copy loads on the Mac (Apple's reader looks
    only for a comment's end), and nothing parsed either file, so a real break, a missing
    </string>, would have reached a hand install unseen. The pinned dicts are the whole of each
    file: a comment may change, a key or a value may not without this test changing with it.
    plistlib alone is looser than Apple's reader: it skips a tag it does not know and drops text
    between elements, so an arrow '-->' inside a comment, a stray word, or a wrapper element
    still parsed to the pinned dict, though CoreFoundation's reader, the one plutil and launchd
    use, refuses each. So every file is also read closer to the way that reader reads it
    (_strict_problems, whose docstring says what it checks and the two things it does not).
    Neither parser fetches the DOCTYPE's DTD; nothing here opens a socket."""
    HOME = "/Users/alexanderward/Projects/jev-paper-loop"
    PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    EXPECTED = {
        "com.alexward.jevloop.loop.plist": {
            "Label": "com.alexward.jevloop.loop",
            "ProgramArguments": ["/opt/homebrew/bin/python3", "-m", "loop.cycle", "--once"],
            "WorkingDirectory": HOME,
            "StartCalendarInterval": {},
            "RunAtLoad": True,
            "EnvironmentVariables": {"PATH": PATH},
            "StandardOutPath": HOME + "/logs/loop-launchd.log",
            "StandardErrorPath": HOME + "/logs/loop-launchd.log"},
        "com.alexward.jevloop.nightly.plist": {
            "Label": "com.alexward.jevloop.nightly",
            "ProgramArguments": ["/bin/bash", HOME + "/nightly/propose.sh"],
            "WorkingDirectory": HOME,
            "StartCalendarInterval": {"Hour": 3, "Minute": 30},
            "EnvironmentVariables": {"PATH": PATH},
            "StandardOutPath": HOME + "/logs/nightly-launchd.log",
            "StandardErrorPath": HOME + "/logs/nightly-launchd.log",
            "RunAtLoad": False},
    }

    @staticmethod
    def _typed(v):
        # assertEqual alone takes True for 1 and 3.0 for 3; a <true/> or an <integer> must stay one
        if isinstance(v, dict):
            return {k: LaunchdPlists._typed(x) for k, x in v.items()}
        if isinstance(v, list):
            return [LaunchdPlists._typed(x) for x in v]
        return (type(v).__name__, v)

    def test_every_plist_parses_to_its_pinned_keys_and_values(self):
        here = os.path.join(REPO, "launchd")
        names = sorted(n for n in os.listdir(here) if n.endswith(".plist"))
        self.assertEqual(names, sorted(self.EXPECTED))                  # a new plist gets pinned here too
        for name in names:
            with self.subTest(plist=name):
                with open(os.path.join(here, name), "rb") as fh:
                    got = plistlib.load(fh, fmt=plistlib.FMT_XML)
                self.assertEqual(self._typed(got), self._typed(self.EXPECTED[name]))

    def test_no_comment_holds_a_double_hyphen(self):
        # the same break as above, named by line: expat says only "not well-formed (invalid token)"
        for name in sorted(self.EXPECTED):
            with open(os.path.join(REPO, "launchd", name), encoding="utf-8") as fh:
                text = fh.read()
            bad = [text.count("\n", 0, m.start()) + 1 for m in re.finditer(r"<!--(.*?)-->", text, re.S)
                   if "--" in m.group(1) or m.group(1).endswith("-")]
            self.assertEqual(bad, [], f"{name}: a comment starting on these lines holds '--'")

    CONTAINERS = ("plist", "dict", "array")
    SCALARS = ("key", "string", "integer", "real", "date", "data", "true", "false")

    @classmethod
    def _strict_problems(cls, raw):
        """What CoreFoundation's XML plist reader refuses in these bytes and plistlib lets through,
        one line each: a tag outside the plist vocabulary ('unknown tag'), text that is not
        whitespace between elements ('unexpected character ... while looking for open tag'), an
        element, comment or processing instruction inside a key or a scalar, and any text inside
        <true/> or <false/> (the reader wants the close tag at once), an <integer> that is not an
        optionally signed decimal or 0x number after optional leading whitespace (Python's int() also
        takes a trailing space or an underscore), and a <plist> that holds other than one object
        (plistlib keeps the last). Whitespace is XML's four characters, which is what that reader
        skips; str.strip's wider set would pass a no-break space. Not checked: a character reference
        (&#32;) or a CDATA section between elements, which the XML parser decodes before this check
        sees the text, though CoreFoundation refuses both. A file that is not well-formed raises here,
        as it does in plistlib."""
        from xml.etree import ElementTree as ET
        ws = " \t\r\n"
        integer = re.compile(r"[ \t\r\n]*[+-]?[ \t\r\n]*(?:0[xX][0-9a-fA-F]+|[0-9]+)")
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
        parser.feed(raw)
        root = parser.close()

        def named(el, parent):
            if el is None:
                return f"the end of <{parent.tag}>"
            if el.tag is ET.Comment:
                return f"the comment {(el.text or '').strip(ws)[:30]!r}"
            if el.tag is ET.PI:
                return "a processing instruction"
            return f"<key>{el.text}</key>" if el.tag == "key" else f"<{el.tag}>"

        def snip(text):
            return repr(text.strip(ws)[:40])

        bad = []

        def walk(el):
            if not isinstance(el.tag, str):
                return                                   # a comment or a PI: its parent judges its place
            if el.tag not in cls.CONTAINERS + cls.SCALARS:
                bad.append(f"<{el.tag}> is not a plist tag")
            kids = list(el)
            if el.tag in cls.SCALARS:
                if kids:
                    bad.append(f"<{el.tag}> holds {named(kids[0], el)}")
                if el.tag in ("true", "false") and el.text:
                    bad.append(f"<{el.tag}/> holds text {el.text[:40]!r}")
                if el.tag == "integer" and not integer.fullmatch(el.text or ""):
                    bad.append(f"<integer> holds {(el.text or '')[:40]!r}")
            else:
                if (el.text or "").strip(ws):
                    bad.append(f"text {snip(el.text)} at the start of <{el.tag}>, before "
                               f"{named(kids[0] if kids else None, el)}")
                for i, kid in enumerate(kids):
                    if (kid.tail or "").strip(ws):
                        after = kids[i + 1] if i + 1 < len(kids) else None
                        bad.append(f"text {snip(kid.tail)} between {named(kid, el)} and {named(after, el)}")
            for kid in kids:
                walk(kid)

        if root.tag == "plist":
            n = sum(1 for kid in root if isinstance(kid.tag, str))
            if n != 1:
                bad.append(f"<plist> holds {n} objects")
        walk(root)
        return bad

    def test_every_plist_holds_nothing_apples_reader_refuses(self):
        for name in sorted(self.EXPECTED):
            with self.subTest(plist=name):
                with open(os.path.join(REPO, "launchd", name), "rb") as fh:
                    self.assertEqual(self._strict_problems(fh.read()), [], name)

    # a small plist in the shape of the real two, and edits of it that plistlib reads to the same
    # dict while CoreFoundation refuses them: the first three are the independent checker's
    SAMPLE = (b'<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0">\n<dict>\n'
              b'  <!-- a comment -->\n  <key>Label</key>\n  <string>x</string>\n\n'
              b'  <key>RunAtLoad</key>\n  <true/>\n\n'
              b'  <key>EnvironmentVariables</key>\n  <dict>\n    <key>PATH</key>\n'
              b'    <string>/bin</string>\n  </dict>\n  <key>StartInterval</key>\n  <integer>60</integer>\n'
              b'</dict>\n</plist>\n')
    LOOSE = {   # what: (bytes found once in SAMPLE, what replaces them, what the refusal names)
        "an arrow inside a comment": (b"a comment -->", b"a comment. A --> B -->", "'B -->'"),
        "a bare word on its own line": (b"\n  <key>RunAtLoad</key>", b"\n  oops\n  <key>RunAtLoad</key>",
                                        "'oops' between <string> and <key>RunAtLoad</key>"),
        "an unknown wrapper element": (b"<string>/bin</string>", b"<foo><string>/bin</string></foo>",
                                       "<foo> is not a plist tag"),
        "a word at the start of <plist>": (b'<plist version="1.0">\n', b'<plist version="1.0">\noops\n',
                                           "'oops' at the start of <plist>"),
        "a no-break space between elements": (b"\n\n  <key>RunAtLoad</key>", b"\n\xc2\xa0\n  <key>RunAtLoad</key>",
                                              "'\\xa0' between <string>"),
        "a comment inside a string": (b"<string>/bin</string>", b"<string>/b<!-- c -->in</string>",
                                      "<string> holds the comment 'c'"),
        "a space inside <true/>": (b"<true/>", b"<true> </true>", "<true/> holds text ' '"),
        "a space before </integer>": (b"<integer>60</integer>", b"<integer>60 </integer>", "<integer> holds '60 '"),
        "an underscore in an integer": (b"<integer>60</integer>", b"<integer>6_0</integer>", "<integer> holds '6_0'"),
        "a second object in <plist>": (b'<plist version="1.0">\n<dict>', b'<plist version="1.0">\n<true/>\n<dict>',
                                       "<plist> holds 2 objects"),
    }

    def test_the_strict_read_refuses_what_plistlib_lets_through(self):
        self.assertEqual(self._strict_problems(self.SAMPLE), [])
        want = self._typed(plistlib.loads(self.SAMPLE, fmt=plistlib.FMT_XML))
        for what, (line, edit, named) in self.LOOSE.items():
            with self.subTest(edit=what):
                self.assertEqual(self.SAMPLE.count(line), 1)
                raw = self.SAMPLE.replace(line, edit)
                self.assertEqual(self._typed(plistlib.loads(raw, fmt=plistlib.FMT_XML)), want)   # the gap
                problems = self._strict_problems(raw)
                self.assertTrue(any(named in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()

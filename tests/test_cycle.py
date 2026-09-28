"""loop.cycle, offline. Every test: urllib.request.urlopen is mocked and raises unless a
test hands it a reply (so a call that reaches it is a failing test, never a packet);
config.JEV_URL points at 127.0.0.1:9 (discard) as a second wall; every data path in
config points into a temp dir; feed.snapshot is replaced by the fixture snapshot
(fixtures/: candles and trades 2026-09-24T02:28:49Z, the 100-level book 04:51:41Z,
assembled through feed.assemble); time.time is pinned
to the fixture's ts_rx so tick_id is known. main() installs and restores its own
SIGTERM/SIGALRM handlers; the two signal tests raise the signal in-process."""
import email.message, io, fcntl, hashlib, json, os, re, signal, sys, tempfile, time, unittest, urllib.error
from unittest import mock
from fixture_prompts import pin_v1
from loop import book, config, cycle, feed, jev, outcomes, prompts, rules

_SLEEP = time.sleep                                  # the real one: time.sleep is mocked in setUp
FIX = os.path.join(config.REPO, "fixtures")


def _load(n):
    with open(os.path.join(FIX, n), encoding="utf-8") as fh:
        return json.load(fh)


META = _load("meta.json")
NOW = float(META["ts_rx_epoch"])                     # 1790216929 -> 2026-09-24T02:28:49Z
TS_RX = "2026-09-24T02:28:49.000Z"
TICK = "20260924T022800Z"
DAY = "20260924"
STATE = "SOL: liquidity deep, flow quiet, trend pumping, vol normal"   # liq pinned by test_feed's fixture walk
SNAP = feed.assemble(META["product"], NOW, _load("book.json"), _load("candles.json"),
                     _load("trades.json"), {"calls": 3, "ms": 600})
KEY = "unit-test-key-not-real-0000"
URL = "http://127.0.0.1:9/v1/systemone"
ANSWERS = {"a_action": {"choice": "buy", "probabilities": {"buy": 0.7, "sell": 0.1, "hold": 0.2},
                        "confidence": 0.72},
           "b_action": {"choice": "hold", "probabilities": {"buy": 0.3, "sell": 0.1, "hold": 0.6},
                        "confidence": 0.55},
           "skip": {"noul": 0.1}, "up15": {"noul": 0.6}, "down15": {"noul": 0.05}}
GOOD = {"model": config.MODEL, "usage": {"input_tokens": 480, "output_tokens": 9}, "answers": ANSWERS}
QIDS = ("a_action", "b_action", "skip", "up15", "down15")
# tokens * 0.042 / 1e6 >= 0.25  <=>  tokens >= 5,952,381
OVER = 3_000_000                                      # x2 rows = $0.252, over the $0.25 tripwire
UNDER = 2_900_000                                     # x2 rows = $0.2436, under it


class _Resp:
    def __init__(self, doc):
        self._b = json.dumps(doc).encode()
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def read(self):
        return self._b


_OPEN = []                                            # HTTPErrors to close (3.14 warns at GC otherwise)


class Reached(BaseException):
    """urlopen was reached with no reply handed to it. A BaseException: cycle._run's `except Exception`
    would turn an AssertionError into a jev/unexpected row and the tick would end 0, the test green."""


def _http(code):
    e = urllib.error.HTTPError(URL, code, "status text", email.message.Message(), io.BytesIO(b""))
    _OPEN.append(e)
    return e


def _row(tick_id, tokens, mode="live"):
    """A minimal earlier row for the spend guard: what it reads is tick_id and jev.input_tokens."""
    return {"v": 1, "tick_id": tick_id, "ts_rx": TS_RX, "mode": mode,
            "jev": {"latency_ms": 500, "input_tokens": tokens, "error": None, "key_path": "env:X"}}


class CycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.data = os.path.join(self.tmp, "data")            # absent, like a fresh clone
        paths = {"DATA": self.data, "DECISIONS": "decisions.jsonl", "SENDS": "sends.tsv",
                 "HALT": "HALT", "LOCK": "loop.lock", "HEARTBEAT": "heartbeat"}
        for k, v in paths.items():
            self.enterContext(mock.patch.object(config, k, v if k == "DATA" else os.path.join(self.data, v)))
        self.spec = os.path.join(self.tmp, "SPEC.md")         # absent: spec_sha is "unsealed"
        self.enterContext(mock.patch.object(config, "SPEC", self.spec))
        self.enterContext(mock.patch.object(config, "JEV_URL", URL))
        self.enterContext(mock.patch.dict(os.environ, {"TYPESAFE_API_KEY_LOOP": KEY}))
        self.protocol = os.path.join(self.tmp, "PROTOCOL.md")    # signed; the unsigned test rewrites it
        with open(self.protocol, "w", encoding="utf-8") as fh:
            fh.write("In force from: `2026-09-24`  Signed: `test`\n")
        self.enterContext(mock.patch.object(config, "PROTOCOL", self.protocol))
        self.prompts_root = pin_v1(self)                        # never the live prompts/: CURRENT moves with bin/promote
        # main() clears _SIG on entry, not on exit: a SIGTERM test leaves term True, and a later test
        # that calls write_row directly would then raise _Stop. Each test starts clear and leaves it so.
        self.enterContext(mock.patch.dict(cycle._SIG, critical=False, term=False))
        self.urlopen = self.enterContext(mock.patch("urllib.request.urlopen",
                                                    side_effect=Reached("urlopen was reached")))
        self.snapshot = self.enterContext(mock.patch.object(feed, "snapshot", return_value=SNAP))
        self.enterContext(mock.patch("time.time", return_value=NOW))
        self.sleeps = []
        self.enterContext(mock.patch("time.sleep", side_effect=self.sleeps.append))
        self.err = self.enterContext(mock.patch("sys.stderr", new_callable=io.StringIO))
        self.out = self.enterContext(mock.patch("sys.stdout", new_callable=io.StringIO))

    def tearDown(self):
        while _OPEN:
            _OPEN.pop().close()

    # ---- helpers ------------------------------------------------------------------------
    def rows(self):
        """Through outcomes.load: every row the tick writes must be one it can read."""
        if not os.path.exists(config.DECISIONS):
            return []
        bad = []
        rows = outcomes.load(config.DECISIONS, bad)
        self.assertEqual(bad, [])
        return rows

    def only_row(self):
        rows = self.rows()
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def sends(self):
        if not os.path.exists(config.SENDS):
            return None
        with open(config.SENDS, encoding="utf-8") as fh:
            return fh.read().splitlines()

    def heartbeat(self):
        with open(config.HEARTBEAT, encoding="utf-8") as fh:
            return fh.read().strip()

    def assert_nothing_sent(self):
        self.urlopen.assert_not_called()
        self.assertIsNone(self.sends())

    def assert_shape(self, row):
        self.assertEqual(sorted(row), sorted(cycle.new_row(TS_RX, "live")))
        self.assertEqual(sorted(row["jev"]), ["error", "input_tokens", "key_path", "latency_ms"])
        self.assertEqual(sorted(row["columns"]), ["a", "b"])
        self.assertRegex(row["tick_id"], r"^\d{8}T\d{4}00Z$")
        self.assertRegex(row["ts_rx"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertEqual(row["tick_id"], cycle.tick_id(row["ts_rx"]))
        self.assertEqual((row["v"], row["venue"], row["product"], row["cadence_s"], row["horizon_s"]),
                         (1, config.VENUE, config.PRODUCT, config.CADENCE_S, config.HORIZON_S))
        self.assertEqual(row["model_requested"], config.MODEL)

    # ---- CONTRACT §6: the path guard -----------------------------------------------------
    def test_a_tick_that_reaches_the_urlopen_wall_fails_the_test(self):
        # a live tick with no reply handed to urlopen: the wall's exception escapes main, not a row
        with self.assertRaises(Reached):
            cycle.main(["--once"])
        self.assertEqual(self.urlopen.call_count, 1)
        self.assertEqual(self.rows(), [])

    def test_path_guard_exits_3_under_either_prefix_and_touches_nothing(self):
        for prefix in config.FORBIDDEN_PREFIXES:
            for repo in (prefix, os.path.join(prefix, "sub", "jev-paper-loop")):
                with mock.patch.object(config, "REPO", repo):
                    self.assertEqual(cycle.main(["--once"]), 3)
                    self.assertEqual(cycle.main(["--dry", "--forever"]), 3)
                    self.assertEqual(cycle.tick(), 3)
        self.assertFalse(os.path.exists(self.data))           # not even data/ was created
        self.snapshot.assert_not_called()
        self.assert_nothing_sent()
        self.assertIn("exit 3", self.err.getvalue())

    def test_path_guard_is_a_prefix_match_not_a_substring(self):
        sibling = config.FORBIDDEN_PREFIXES[0] + "-notes"    # ~/Projects/crypto-trading-system-notes
        self.assertIsNone(cycle.forbidden(sibling))
        self.assertIsNone(cycle.forbidden(config.REPO))
        self.assertEqual(cycle.forbidden(config.FORBIDDEN_PREFIXES[1] + "/x"), config.FORBIDDEN_PREFIXES[1])

    def test_usage_error_exits_2(self):
        for argv in ([], ["--dry"], ["--once", "--forever"], ["--bogus"]):
            with self.assertRaises(SystemExit) as cm:
                cycle.main(argv)
            self.assertEqual(cm.exception.code, 2, argv)
        self.assertFalse(os.path.exists(self.data))

    # ---- CONTRACT §6: HALT present -> absence halt, no send --------------------------------
    # PROTOCOL §3.8 / SPEC §13.2: HALT stops SENDS only; the feed, arm C's rule_c and the
    # outcome join keep running. (The first form of this test asserted the feed was NOT
    # called and rule_c was null: it pinned a HALT that stopped observation too.)
    def test_halt_present_observes_and_sends_nothing(self):
        os.makedirs(self.data)
        with open(config.HALT, "w", encoding="utf-8") as fh:
            fh.write("by hand\n")
        self.assertEqual(cycle.main(["--once"]), 0)
        row = self.only_row()
        self.assert_shape(row)
        self.assertEqual((row["absence"], row["mode"], row["tick_id"], row["ts_rx"]), ("halt", "live", TICK, TS_RX))
        self.snapshot.assert_called_once()                    # the feed ran
        self.assertEqual((row["bid"], row["ask"], row["mid"]), (SNAP["bid"], SNAP["ask"], (114.95 + 114.97) / 2))   # the 04:51:41Z book
        self.assertEqual((row["state"], row["rule_c"]), (STATE, "buy"))
        self.assertEqual(row["prompt_a_sha"], prompts.sha("v1"))
        self.assertIsNone(row["answers"])
        self.assertEqual(row["columns"], {"a": None, "b": None})
        self.assertEqual(row["jev"], {"latency_ms": None, "input_tokens": None, "error": None, "key_path": None})
        self.assertEqual(cycle.billed_tokens(row), 0)
        self.assertEqual(row["spec_sha"], "unsealed")
        self.assert_nothing_sent()                             # no ledger row, no request
        self.assertEqual(self.out.getvalue(), "")              # and no body printed
        self.assertEqual(self.heartbeat(), TS_RX)
        with open(config.HALT, encoding="utf-8") as fh:                          # HALT is never removed by code
            self.assertEqual(fh.read(), "by hand\n")

    def test_halt_keeps_marks_and_outcomes_but_every_arm_holds(self):
        os.makedirs(self.data)
        open(config.HALT, "w", encoding="utf-8").close()
        for dt in (0, 900):                                    # two halted ticks one horizon apart
            with mock.patch("time.time", return_value=NOW + dt):
                self.snapshot.side_effect = lambda: dict(SNAP, ts_rx=cycle.iso_ms(NOW + dt))
                self.assertEqual(cycle.main(["--once"]), 0)
        rows = self.rows()
        self.assertEqual([r["absence"] for r in rows], ["halt", "halt"])
        self.assertIsNone(outcomes.join(rows)[TICK]["absence"])            # t+h still resolves
        c = book.replay(rows, None, "c", "argmax", config.FEE_BPS_PRIMARY)
        self.assertEqual((c["trades"], c["forced_hold"]), ([], 2))       # rule_c buy is logged, not traded
        self.assert_nothing_sent()

    def test_halt_under_a_held_lock_is_a_lock_row(self):
        os.makedirs(self.data)
        open(config.HALT, "w", encoding="utf-8").close()
        holder = open(config.LOCK, "a", encoding="utf-8")
        self.addCleanup(holder.close)
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(cycle.main(["--once"]), 0)
        self.assertEqual(self.only_row()["absence"], "lock")
        self.snapshot.assert_not_called()                     # the other holder fetches this minute

    def test_halt_in_dry_mode_is_a_dry_halt_row(self):
        os.makedirs(self.data)
        open(config.HALT, "w", encoding="utf-8").close()
        self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        row = self.only_row()
        self.assertEqual((row["absence"], row["mode"], row["state"]), ("halt", "dry", STATE))
        self.assertEqual(self.out.getvalue(), "")              # under HALT no body is built for sending

    # ---- CONTRACT §6: spend over the limit writes HALT -------------------------------------
    def test_spend_over_limit_writes_halt_and_a_halt_row(self):
        os.makedirs(self.data)
        with open(config.DECISIONS, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(_row("20260923T235900Z", 50_000_000)) + "\n")   # yesterday: not counted
            fh.write(json.dumps(_row(DAY + "T010000Z", OVER)) + "\n")
            fh.write(json.dumps(_row(DAY + "T010100Z", None, "dry")) + "\n")    # dry: null tokens
            fh.write(json.dumps(_row(DAY + "T010200Z", OVER)) + "\n")
        self.assertAlmostEqual(cycle.spend_today(NOW), 2 * OVER * config.USD_PER_MTOK / 1e6)
        self.assertEqual(cycle.main(["--once"]), 0)
        self.assertTrue(os.path.exists(config.HALT))
        with open(config.HALT, encoding="utf-8") as fh:
            reason = fh.read()
        self.assertIn(cycle.HALT_SPEND, reason)
        self.assertIn(str(config.DAILY_SPEND_HALT_USD), reason)
        rows = self.rows()
        self.assertEqual(len(rows), 5)
        self.assertEqual((rows[-1]["absence"], rows[-1]["tick_id"], rows[-1]["state"]), ("halt", TICK, STATE))
        self.snapshot.assert_called_once()                    # the trip stops the send, not the feed
        self.assert_nothing_sent()
        # the next tick sees HALT and halts again, still without a send
        self.assertEqual(cycle.main(["--once"]), 0)
        self.assertEqual(self.rows()[-1]["absence"], "halt")
        self.assert_nothing_sent()

    def test_a_log_that_exists_but_cannot_be_read_trips_the_guard(self):
        # write_row keeps appending to a 0200 (or ACL) log it cannot read; spend_today used to read
        # that as $0 and the tick sent past the tripwire. It now fails closed: HALT, a halt row, no send.
        os.makedirs(self.data)
        with open(config.DECISIONS, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(_row(DAY + "T010000Z", OVER)) + "\n")
            fh.write(json.dumps(_row(DAY + "T010200Z", OVER)) + "\n")
        real_open = open

        def no_read(path, mode="r", *a, **k):
            if os.path.abspath(str(path)) == os.path.abspath(config.DECISIONS) and "r" in mode and "+" not in mode:
                raise PermissionError(13, "Permission denied", path)
            return real_open(path, mode, *a, **k)
        with mock.patch("builtins.open", side_effect=no_read):
            self.assertEqual(cycle.spend_today(NOW), float("inf"))
            self.assertEqual(cycle.main(["--once"]), 0)
        with open(config.HALT, encoding="utf-8") as fh:
            reason = fh.read()
        self.assertIn(cycle.HALT_SPEND, reason)
        self.assertIn("cannot be read", reason)
        self.assertEqual(self.rows()[-1]["absence"], "halt")
        self.assert_nothing_sent()
        self.assertEqual(cycle.spend_today(NOW, os.path.join(self.tmp, "missing")), 0.0)     # missing is still $0
        self.assertEqual(cycle.spend_today(NOW, self.data), float("inf"))                   # a directory: cannot count

    def test_a_token_count_past_a_floats_range_trips_the_guard_instead_of_crashing(self):
        # the server reports input_tokens; a count past a float's range made spend_today raise
        # OverflowError, and every later tick that UTC day exited 1 with no row and no HALT
        os.makedirs(self.data)
        with open(config.DECISIONS, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(_row(DAY + "T010000Z", 10 ** 400)) + "\n")
        self.assertEqual(cycle.spend_today(NOW), cycle.SPEND_UNCOUNTED)
        self.assertEqual(cycle.main(["--once"]), 0)
        self.assertEqual(self.rows()[-1]["absence"], "halt")
        self.assert_nothing_sent()
        with open(config.HALT, encoding="utf-8") as fh:
            reason = fh.read()
        self.assertIn("past a float's range", reason)                   # the cause, not "cannot be read"
        self.assertNotIn("cannot be read", reason)

    def test_counts_that_fit_a_float_but_sum_past_one_trip_the_guard_and_the_halt_says_so(self):
        # jev._parse int()s a server reply of 1e308, which fits a float, so no single count today is past
        # a float's range; their sum is. The guard trips (right), but the HALT named "a logged input_tokens
        # count today" past a float's range, and Alex would look for a row that is not there.
        os.makedirs(self.data)
        with open(config.DECISIONS, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(_row(DAY + "T010000Z", 10 ** 308)) + "\n")
            fh.write(json.dumps(_row(DAY + "T010100Z", 10 ** 308)) + "\n")
        self.assertEqual(float(10 ** 308), 1e308)                            # each count fits a float
        self.assertEqual(cycle.spend_today(NOW), cycle.SPEND_UNCOUNTED)
        self.assertEqual(cycle.main(["--once"]), 0)
        self.assertEqual(self.rows()[-1]["absence"], "halt")
        self.assert_nothing_sent()
        with open(config.HALT, encoding="utf-8") as fh:
            reason = fh.read()
        self.assertTrue(reason.startswith(cycle.HALT_SPEND + ": today's input_tokens (one logged count, or the sum of today's counts)"
                                          " is past a float's range"), reason)
        self.assertNotIn("a logged input_tokens count today is past", reason)

    def test_spend_widens_when_the_tail_starts_after_today(self):
        # rows stamped later than today (a clock that ran ahead, then stepped back) fill the tail, so
        # its first row is not today's: the read used to stop there and miss today's earlier rows
        os.makedirs(self.data)
        with open(config.DECISIONS, "w", encoding="utf-8") as fh:
            for m in range(3):
                fh.write(json.dumps(_row(DAY + f"T00{m:02d}00Z", 2_000_000)) + "\n")       # today, early: $0.252
            for m in range(40):
                fh.write(json.dumps(_row("20260925T01" + f"{m:02d}00Z", 1)) + "\n")         # tomorrow, from a clock ahead
            fh.write(json.dumps(_row(DAY + "T020000Z", 1000)) + "\n")                        # today again
        with mock.patch.object(cycle, "TAIL_BYTES", 2000):
            self.assertAlmostEqual(cycle.spend_today(NOW), (3 * 2_000_000 + 1000) * config.USD_PER_MTOK / 1e6)

    def test_spend_just_under_limit_proceeds(self):
        os.makedirs(self.data)
        with open(config.DECISIONS, "w", encoding="utf-8") as fh:
            for i in range(2):
                fh.write(json.dumps(_row(DAY + "T0100%02dZ" % i, UNDER)) + "\n")
        self.assertLess(cycle.spend_today(NOW), config.DAILY_SPEND_HALT_USD)
        self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        self.assertFalse(os.path.exists(config.HALT))
        self.assertEqual(self.rows()[-1]["absence"], None)
        self.snapshot.assert_called_once()

    def test_spend_reads_the_tail_and_widens_when_today_overflows_it(self):
        os.makedirs(self.data)
        with open(config.DECISIONS, "w", encoding="utf-8") as fh:
            for i in range(20):
                fh.write(json.dumps(_row(DAY + "T01%02d00Z" % i, 1000)) + "\n")
            fh.write("{truncated line with no newline")
        with open(config.DECISIONS, encoding="utf-8") as fh:
            size = len(fh.read())
        with mock.patch.object(cycle, "TAIL_BYTES", size // 3):     # the tail holds ~6 of the 20
            self.assertAlmostEqual(cycle.spend_today(NOW), 20_000 * config.USD_PER_MTOK / 1e6)
        self.assertAlmostEqual(cycle.spend_today(NOW), 20_000 * config.USD_PER_MTOK / 1e6)
        self.assertEqual(cycle.spend_today(NOW, os.path.join(self.tmp, "missing")), 0.0)

    def _days(self, fh, day, n, tokens, pad):
        """n rows of `day`, one a minute from 00:00, each padded to about a real row's size."""
        for i in range(n):
            r = _row("%sT%02d%02d00Z" % (day, i // 60 % 24, i % 60), tokens)
            r["features"] = pad
            fh.write(json.dumps(r) + "\n")

    def test_spend_with_the_tail_cut_in_earlier_days_reads_the_tail_only(self):
        # The production case: two full days of ~2.6 KB rows behind today's 10 hours, so the
        # 8 MiB tail starts inside an earlier day, today fits in it, and nothing widens.
        self.assertEqual(cycle.TAIL_BYTES, 8 << 20)
        os.makedirs(self.data)
        with open(config.DECISIONS, "w", encoding="utf-8") as fh:
            self._days(fh, "20260922", 1440, 50_000_000, "x" * 2500)
            self._days(fh, "20260923", 1440, 50_000_000, "x" * 2500)
            self._days(fh, DAY, 600, 1000, "x" * 2500)
        self.assertGreater(os.path.getsize(config.DECISIONS), cycle.TAIL_BYTES)
        buf, cut = cycle._tail(config.DECISIONS, cycle.TAIL_BYTES)
        self.assertTrue(cut)
        self.assertTrue(json.loads(buf.split(b"\n", 1)[0])["tick_id"].startswith("20260922"))   # the tail's first row
        with mock.patch.object(cycle, "_tail", wraps=cycle._tail) as tail:
            self.assertAlmostEqual(cycle.spend_today(NOW), 600 * 1000 * config.USD_PER_MTOK / 1e6)
        self.assertEqual([c.args for c in tail.call_args_list], [(config.DECISIONS, cycle.TAIL_BYTES)])

    def test_spend_with_today_overflowing_the_tail_widens_to_the_whole_file(self):
        # Rows three times the usual size: today alone no longer fits in 8 MiB, the tail's first
        # row is today's, and the guard reads the whole file rather than miss today's first hours.
        os.makedirs(self.data)
        with open(config.DECISIONS, "w", encoding="utf-8") as fh:
            self._days(fh, "20260923", 200, 50_000_000, "x" * 2500)
            self._days(fh, DAY, 1440, 100, "x" * 6500)
        buf, cut = cycle._tail(config.DECISIONS, cycle.TAIL_BYTES)
        self.assertTrue(cut)
        self.assertTrue(json.loads(buf.split(b"\n", 1)[0])["tick_id"].startswith(DAY))
        with mock.patch.object(cycle, "_tail", wraps=cycle._tail) as tail:
            self.assertAlmostEqual(cycle.spend_today(NOW), 1440 * 100 * config.USD_PER_MTOK / 1e6)
        self.assertEqual([c.args for c in tail.call_args_list],
                         [(config.DECISIONS, cycle.TAIL_BYTES), (config.DECISIONS, 0)])

    def test_spend_charges_a_send_with_unknown_tokens_at_the_ceiling(self):
        # jev.ask logs input_tokens 0 when the reply has no `usage` (null when the send failed);
        # read as free, the tripwire would never fire. A live row that reached the model with 0
        # or null tokens is charged config.JEV_TOKENS_IF_UNKNOWN; rows that never sent cost 0.
        U = config.JEV_TOKENS_IF_UNKNOWN

        def r(i, tokens, mode="live", absence=None, error=None):
            row = _row(DAY + "T02%02d00Z" % i, tokens, mode)
            row["absence"], row["jev"]["error"] = absence, error
            return row
        rows = [r(0, 0), r(1, None, absence="jev", error="timeout"), r(2, None, absence="jev", error="http-4xx"),
                r(3, None, absence="jev", error="no-key"), r(4, None, absence="jev", error="ledger"),
                r(5, None, absence="feed"), r(6, None, absence="halt"), r(7, None, absence="lock"),
                r(8, None, mode="dry"), r(9, 480)]
        self.assertEqual([cycle.billed_tokens(x) for x in rows], [U, U, U, 0, 0, 0, 0, 0, 0, 480])
        os.makedirs(self.data)
        with open(config.DECISIONS, "w", encoding="utf-8") as fh:
            fh.writelines(json.dumps(x) + "\n" for x in rows)
        self.assertAlmostEqual(cycle.spend_today(NOW), (3 * U + 480) * config.USD_PER_MTOK / 1e6)
        # enough of them trip it: a runaway whose replies carry no usage still writes HALT
        n = int(config.DAILY_SPEND_HALT_USD / (U * config.USD_PER_MTOK / 1e6)) + 1
        with open(config.DECISIONS, "w", encoding="utf-8") as fh:
            fh.writelines(json.dumps(r(i % 60, 0)) + "\n" for i in range(n))
        self.assertGreaterEqual(cycle.spend_today(NOW), config.DAILY_SPEND_HALT_USD)
        self.assertEqual(cycle.main(["--once"]), 0)
        self.assertTrue(os.path.exists(config.HALT))
        self.assertEqual(self.rows()[-1]["absence"], "halt")
        self.snapshot.assert_called_once()
        self.assert_nothing_sent()

    # ---- CONTRACT §6: --dry writes a row with answers null and no sends.tsv line ---------------
    def test_dry_writes_row_answers_null_and_no_ledger_line(self):
        self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        row = self.only_row()
        self.assert_shape(row)
        self.assertEqual((row["mode"], row["absence"], row["tick_id"], row["ts_rx"]), ("dry", None, TICK, TS_RX))
        self.assertIsNone(row["answers"])
        self.assertEqual(row["columns"], {"a": None, "b": None})
        self.assertEqual(row["jev"], {"latency_ms": None, "input_tokens": None, "error": None, "key_path": None})
        self.assertIsNone(row["model_answered"])
        self.assertFalse(row["drift"])
        # the feed and the state are all there: the dry row is a full observation minus the model
        self.assertEqual((row["bid"], row["ask"], row["mid"]), (SNAP["bid"], SNAP["ask"], (114.95 + 114.97) / 2))   # the 04:51:41Z book
        self.assertEqual((row["bid_size"], row["ask_size"]), (SNAP["bid_size"], SNAP["ask_size"]))
        self.assertEqual((row["book_time"], row["feed_age_s"]), (SNAP["book_time"], SNAP["feed_age_s"]))
        self.assertEqual(row["state"], STATE)
        self.assertEqual(row["adj"], {"liq": "deep", "flow": "quiet", "trend": "pumping", "vol": "normal"})
        self.assertEqual(row["rule_c"], "buy")
        self.assertEqual(sorted(row["features"]), sorted(("mid", "spread_bps", "l1_min_usd", "fill1k_bps",
                         "fill1k_short", "vol5_usd", "vol5_p10", "vol5_p90", "ret15_bps", "ret15_sd_bps",
                         "ret15_z", "rv15", "rv15_med", "rv_ratio", "window_min")))
        self.assertAlmostEqual(row["features"]["fill1k_bps"], META["expect"]["fill1k_bps"], places=12)
        self.assertIs(row["features"]["fill1k_short"], False)
        self.assertNotIn("bids", row)                                  # the levels feed the walk; the row keeps L1
        self.assertNotIn("asks", row)
        self.assertEqual((row["prompt_a"], row["prompt_b"]), ("v1", "v1"))
        self.assertEqual(row["prompt_a_sha"], prompts.sha("v1"))
        self.assertEqual(row["prompt_a_sha"], row["prompt_b_sha"])
        self.assertEqual(row["spec_sha"], "unsealed")
        self.assert_nothing_sent()
        self.assertEqual(self.heartbeat(), TS_RX)
        # the would-be body is printed, exactly what ask() would serialise, five questions
        body = json.loads(self.out.getvalue())
        self.assertEqual(list(body), ["model", "state", "questions"])
        self.assertEqual((body["model"], body["state"]), (config.MODEL, STATE))
        self.assertEqual(tuple(body["questions"]), QIDS)
        self.assertNotIn(KEY, self.out.getvalue() + self.err.getvalue())

    def test_state_string_in_the_row_has_no_digit(self):
        cycle.main(["--dry", "--once"])
        self.assertFalse(any(ch.isdigit() for ch in self.only_row()["state"]))

    def test_spec_sha_is_the_file_sha256_when_present(self):
        with open(self.spec, "wb") as fh:
            fh.write(b"# SPEC\nfrozen\n")
        self.assertEqual(cycle.spec_sha(), hashlib.sha256(b"# SPEC\nfrozen\n").hexdigest())
        cycle.main(["--dry", "--once"])
        self.assertEqual(self.only_row()["spec_sha"], cycle.spec_sha())

    # ---- a FeedError -> absence feed ----------------------------------------------------------
    def test_feed_error_writes_absence_feed_row(self):
        self.snapshot.side_effect = feed.FeedError("http-503 /product_book")
        self.assertEqual(cycle.main(["--once"]), 0)
        row = self.only_row()
        self.assert_shape(row)
        self.assertEqual((row["absence"], row["mode"], row["tick_id"], row["ts_rx"]), ("feed", "live", TICK, TS_RX))
        for k in ("bid", "ask", "mid", "features", "adj", "state", "rule_c", "prompt_a", "prompt_a_sha", "answers"):
            self.assertIsNone(row[k], k)
        self.assertEqual(row["columns"], {"a": None, "b": None})
        self.assert_nothing_sent()
        self.assertIn("http-503", self.err.getvalue())
        self.assertEqual(self.heartbeat(), TS_RX)

    def test_state_refusing_the_window_is_absence_feed(self):
        short = dict(SNAP, candles=SNAP["candles"][-100:])
        self.snapshot.return_value = short
        self.assertEqual(cycle.main(["--once"]), 0)
        row = self.only_row()
        self.assertEqual(row["absence"], "feed")
        self.assertEqual(row["bid"], SNAP["bid"])          # what the feed did give is kept
        self.assertIsNone(row["state"])
        self.assert_nothing_sent()

    def test_a_garbage_candle_value_is_absence_feed_on_every_python(self):
        # Through feed.assemble, as live: a NaN volume on the newest minute used to read flow
        # `organic` with absence null; a zero close was ZeroDivisionError, logged `guard`; a NaN
        # close was AttributeError on 3.11/3.12 (`guard`) and ValueError on 3.13+ (`feed`).
        raw, book_j, trades_j = _load("candles.json"), _load("book.json"), _load("trades.json")
        cases = (("volume", "nan", 1), ("volume", "inf", 1), ("close", "0", 1), ("close", "0", 150),
                 ("close", "nan", 150), ("high", "inf", 1), ("low", "0", 2))
        for i, (field, value, at) in enumerate(cases):
            with self.subTest(field=field, value=value, at=at):
                c = json.loads(json.dumps(raw))
                c["candles"][at][field] = value
                self.snapshot.side_effect = lambda c=c: feed.assemble(META["product"], NOW, book_j, c, trades_j,
                                                                      {"calls": 3, "ms": 0})
                with mock.patch("time.time", return_value=NOW + 60 * i):
                    self.assertEqual(cycle.main(["--dry", "--once"]), 0)
                row = self.rows()[-1]
                self.assertEqual((row["absence"], row["mode"]), ("feed", "dry"))
                self.assertEqual((row["state"], row["rule_c"], row["features"]), (None, None, None))
                self.assertEqual(self.out.getvalue(), "")                   # no body: the tick stopped at the feed
        self.assertEqual(len(self.rows()), len(cases))
        self.assertNotIn("Traceback", self.err.getvalue())
        self.assert_nothing_sent()

    def test_broken_prompts_is_absence_guard_after_the_state(self):
        with mock.patch.object(prompts, "current", side_effect=prompts.PromptError("CURRENT: two names")):
            self.assertEqual(cycle.main(["--once"]), 0)
        row = self.only_row()
        self.assertEqual((row["absence"], row["state"], row["rule_c"]), ("guard", STATE, "buy"))
        self.assertIsNone(row["prompt_a"])
        self.assert_nothing_sent()

    # ---- the live path, with urlopen stubbed ----------------------------------------------------
    def test_live_tick_asks_once_logs_answers_and_both_column_sets(self):
        self.urlopen.side_effect = None
        self.urlopen.return_value = _Resp(GOOD)
        self.assertEqual(cycle.main(["--once"]), 0)
        row = self.only_row()
        self.assert_shape(row)
        self.assertEqual((row["mode"], row["absence"], row["tick_id"]), ("live", None, TICK))
        self.assertEqual(row["answers"], ANSWERS)
        self.assertEqual(row["model_answered"], config.MODEL)
        self.assertFalse(row["drift"])
        self.assertEqual(row["jev"]["input_tokens"], 480)
        self.assertIsInstance(row["jev"]["latency_ms"], int)
        self.assertIsNone(row["jev"]["error"])
        self.assertEqual(row["jev"]["key_path"], "env:TYPESAFE_API_KEY_LOOP")
        self.assertEqual(row["columns"]["a"], rules.for_arm(ANSWERS, "a"))
        self.assertEqual(row["columns"]["b"], rules.for_arm(ANSWERS, "b"))
        self.assertEqual((row["columns"]["a"]["argmax"], row["columns"]["b"]["argmax"]), ("buy", "hold"))
        self.assertEqual(tuple(row["columns"]["a"]), rules.COLUMNS)
        self.assertEqual(row["rule_c"], "buy")
        self.assertEqual(self.urlopen.call_count, 1)
        req = self.urlopen.call_args.args[0]
        self.assertEqual(req.full_url, URL)                    # the patched URL, not api.typesafe.ai
        self.assertEqual(json.loads(req.data), {"model": config.MODEL, "state": STATE,
                                                "questions": prompts.build(prompts.load("v1"), prompts.load("v1"))})
        lines = self.sends()
        self.assertEqual(lines[0], jev.HEADER.rstrip("\n"))
        self.assertEqual(len(lines), 2)                        # one attempt, one ledger row
        self.assertEqual(lines[1].split("\t")[1], jev.SOURCE)
        self.assertEqual(self.heartbeat(), TS_RX)
        self.assertEqual(self.out.getvalue(), "")              # live prints no body
        self.assertNotIn(KEY, self.err.getvalue())

    def test_drift_is_logged_not_refused(self):
        self.urlopen.side_effect = None
        self.urlopen.return_value = _Resp(dict(GOOD, model="jev-9.9.9"))
        cycle.main(["--once"])
        row = self.only_row()
        self.assertEqual((row["model_answered"], row["drift"], row["absence"]), ("jev-9.9.9", True, None))
        self.assertIsNotNone(row["columns"]["a"])
        self.assertIn("DRIFT", self.err.getvalue())

    def test_key_rejected_writes_halt_and_absence_jev(self):
        for code in (401, 403):
            with self.subTest(code=code):
                if os.path.exists(config.HALT):
                    os.remove(config.HALT)
                self.urlopen.side_effect = _http(code)
                self.assertEqual(cycle.main(["--once"]), 0)
                row = self.rows()[-1]
                self.assertEqual((row["absence"], row["jev"]["error"]), ("jev", "http-4xx"))
                self.assertEqual(row["jev"]["key_path"], "env:TYPESAFE_API_KEY_LOOP")
                self.assertIsNone(row["answers"])
                self.assertEqual(row["columns"], {"a": None, "b": None})
                self.assertEqual(row["state"], STATE)          # the observation survives the refusal
                with open(config.HALT, encoding="utf-8") as fh:
                    reason = fh.read()
                self.assertIn(cycle.HALT_KEY_REJECTED, reason)
                self.assertIn(str(code), reason)
                self.assertNotIn(KEY, reason)
        self.assertEqual(self.urlopen.call_count, 2)            # no retry on a 4xx
        self.assertEqual(len(self.sends()), 3)                  # header + one ledger row per send

    def test_transient_failure_twice_is_absence_jev_with_two_ledger_rows(self):
        self.urlopen.side_effect = TimeoutError("timed out")
        self.assertEqual(cycle.main(["--once"]), 0)
        row = self.only_row()
        self.assertEqual((row["absence"], row["jev"]["error"]), ("jev", "timeout"))
        self.assertFalse(os.path.exists(config.HALT))
        self.assertEqual(self.urlopen.call_count, 2)            # one retry
        self.assertEqual(len(self.sends()), 3)                  # header + a row per attempt
        self.assertEqual(self.sleeps, [jev.RETRY_S])

    def test_no_key_is_absence_jev_with_no_ledger_row(self):
        with mock.patch.object(config, "KEY_PATHS", (("env", "NO_SUCH_KEY_VAR_FOR_TEST"),)):
            self.assertEqual(cycle.main(["--once"]), 0)
        row = self.only_row()
        self.assertEqual((row["absence"], row["jev"]["error"], row["jev"]["key_path"]), ("jev", "no-key", None))
        self.assert_nothing_sent()

    def test_sleep_to_boundary_resleeps_when_woken_early(self):
        # 2026-09-24 attended run: time.sleep returned ~90 ms early twice in 181 ticks, so
        # the next tick floored to the minute just done. The sleep must not return before
        # the wall clock crosses the boundary, however early each wake is.
        clock = [1000.0]                                       # 16 min 40 s: boundary at 1020
        def fake_sleep(s):
            clock[0] += s - min(0.09, s / 2)                   # every wake early: 90 ms, or half a short sleep
        with mock.patch("time.time", side_effect=lambda: clock[0]), \
             mock.patch("time.sleep", side_effect=fake_sleep):
            cycle._sleep_to_boundary()
        self.assertGreaterEqual(clock[0], 1020.0)
        self.assertEqual(int(clock[0]) // config.CADENCE_S, 17)

    def test_sleep_to_boundary_takes_the_boundary_after_the_callers_clock(self):
        # --once reads the clock at :59.99995, then _sleep_to_boundary reads it again at :00.00005:
        # computed from the second read, the boundary would be the NEXT :00, a 60 s sleep and a
        # minute with no row. Given the caller's read, it is the :00 a hair away.
        clock = [1020.00005]                                   # already past the boundary at 1020
        slept = []
        with mock.patch("time.time", side_effect=lambda: clock[0]), \
             mock.patch("time.sleep", side_effect=slept.append):
            cycle._sleep_to_boundary(1019.99995)
        self.assertEqual(slept, [])                            # the boundary has passed: no sleep at all
        with mock.patch("time.time", side_effect=lambda: clock[0]), \
             mock.patch("time.sleep", side_effect=lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s))):
            cycle._sleep_to_boundary()                         # without it, the next boundary: 1080
        self.assertEqual(len(slept), 1)
        self.assertAlmostEqual(slept[0], 59.99995, places=4)

    def test_once_fired_a_hair_before_the_minute_waits_for_it(self):
        # Production runs --once from launchd's StartCalendarInterval; a fire at :59.x would
        # take the minute just done (a duplicate) and leave the next one unrecorded. More than
        # CADENCE_S - 2 s into a minute, --once first sleeps to the boundary.
        # Only when this minute already has its row (data/heartbeat in it): a RunAtLoad or a wake
        # can land at :59 of a minute that has NO row yet, and that fire is late for this minute,
        # not early for the next (2026-09-28, verifier).
        base = NOW - 49                                        # 02:28:00
        for at, hb, sleeps, tick in ((59.5, "2026-09-24T02:28:00.100Z", [0.5], "20260924T022900Z"),
                                     (59.5, "2026-09-24T02:27:00.100Z", [], "20260924T022800Z"),
                                     (59.5, None, [], "20260924T022800Z"),
                                     (57.5, "2026-09-24T02:28:00.100Z", [], "20260924T022800Z")):
            with self.subTest(at=at, hb=hb):
                if hb:
                    os.makedirs(self.data, exist_ok=True)
                    with open(config.HEARTBEAT, "w", encoding="utf-8") as fh:
                        fh.write(hb + "\n")
                elif os.path.exists(config.HEARTBEAT):
                    os.remove(config.HEARTBEAT)
                clock, self.sleeps[:] = [base + at], []
                def sleep(s):
                    self.sleeps.append(s)
                    clock[0] += s
                self.snapshot.side_effect = lambda: dict(SNAP, ts_rx=cycle.iso_ms(clock[0]))   # feed's own clock
                with mock.patch("time.time", side_effect=lambda: clock[0]), \
                        mock.patch("time.sleep", side_effect=sleep):
                    self.assertEqual(cycle.main(["--dry", "--once"]), 0)
                self.assertEqual(self.sleeps, sleeps)
                self.assertEqual(self.rows()[-1]["tick_id"], tick)

    def test_unsigned_protocol_observes_but_never_sends_or_bills(self):
        # The repo as committed: PROTOCOL.md unsigned. A live tick still records the feed,
        # the state and arm C -- observation is free and outlives sending -- but jev.ask
        # refuses before the key, the ledger or a socket, and the row bills nothing.
        with open(self.protocol, "w", encoding="utf-8") as fh:
            fh.write("In force from: `____________`  Signed: `____________`\n")
        self.assertEqual(cycle.main(["--once"]), 0)
        row = self.only_row()
        self.assertEqual((row["mode"], row["absence"], row["jev"]["error"]), ("live", "jev", "unsigned"))
        self.assertIsNotNone(row["state"]); self.assertIn(row["rule_c"], ("buy", "sell", "hold"))
        self.assertEqual(cycle.billed_tokens(row), 0)
        self.assertFalse(os.path.exists(config.HALT))        # unsigned is a state, not an incident
        self.assert_nothing_sent()

    def test_choice_outside_the_alphabet_is_parse_with_the_answer_logged(self):
        bad = json.loads(json.dumps(GOOD))
        bad["answers"]["b_action"]["choice"] = "maybe"
        self.urlopen.side_effect = None
        self.urlopen.return_value = _Resp(bad)
        self.assertEqual(cycle.main(["--once"]), 0)
        row = self.only_row()
        self.assertEqual((row["absence"], row["jev"]["error"]), ("jev", "parse"))
        self.assertEqual(row["answers"]["b_action"]["choice"], "maybe")   # paid for: kept
        self.assertEqual(row["columns"], {"a": None, "b": None})
        self.assertEqual(row["jev"]["input_tokens"], 480)

    def test_a_wrong_typed_bool_or_non_finite_answer_field_is_parse_with_the_answer_logged(self):
        # jev._parse checks only that the fields exist; the rules refuse what no cut can read.
        # SPEC §2 keeps answers only on a `parse` row, so none of these may log "unexpected"
        # (answers kept on a row that says the rules never saw them) or reach the columns.
        cases = {"confidence null": ("a_action", "confidence", None),
                 "skip.noul null": ("skip", "noul", None),
                 "probabilities x": ("b_action", "probabilities", "x"),
                 "confidence true": ("a_action", "confidence", True),     # float(True) = 1.0 would pass c99
                 "confidence NaN": ("b_action", "confidence", float("nan")),
                 "up15.noul Infinity": ("up15", "noul", float("inf")),
                 "probabilities.buy true": ("a_action", "probabilities", {"buy": True, "sell": 0.0, "hold": 0.0})}
        self.urlopen.side_effect = None
        for i, (name, (qid, field, value)) in enumerate(cases.items()):
            with self.subTest(name):
                bad = json.loads(json.dumps(GOOD))
                bad["answers"][qid][field] = value
                self.urlopen.return_value = _Resp(bad)
                with mock.patch("time.time", return_value=NOW + 60 * i):
                    self.assertEqual(cycle.main(["--once"]), 0)
                row = self.rows()[-1]
                self.assertEqual((row["absence"], row["jev"]["error"]), ("jev", "parse"))
                self.assertEqual(row["answers"]["a_action"]["choice"], "buy")     # paid for: kept
                got = row["answers"][qid][field]
                self.assertTrue(got == value or (got != got and value != value), (got, value))
                self.assertEqual(row["columns"], {"a": None, "b": None})
                self.assertEqual(row["jev"]["input_tokens"], 480)
                self.assertNotIn("Traceback", self.err.getvalue())
        self.assertEqual(len(self.rows()), len(cases))

    def test_an_unexpected_failure_after_the_send_began_is_billed(self):
        # "guard" rows are charged $0 by the spend guard; an exception once the request may
        # have left must not be one. usage.input_tokens = Infinity is jev's own `parse`.
        inf = json.loads(json.dumps(GOOD)); inf["usage"]["input_tokens"] = float("inf")
        self.urlopen.side_effect = None
        self.urlopen.return_value = _Resp(inf)
        self.assertEqual(cycle.main(["--once"]), 0)
        row = self.rows()[-1]
        self.assertEqual((row["absence"], row["jev"]["error"]), ("jev", "parse"))
        self.assertEqual(cycle.billed_tokens(row), config.JEV_TOKENS_IF_UNKNOWN)
        for exc in (RuntimeError("boom"), ValueError("odd")):
            with mock.patch.object(jev, "ask", side_effect=exc):
                self.assertEqual(cycle.main(["--once"]), 0)
            row = self.rows()[-1]
            self.assertEqual((row["absence"], row["jev"]["error"]), ("jev", "unexpected"), exc)
            self.assertEqual(cycle.billed_tokens(row), config.JEV_TOKENS_IF_UNKNOWN)
        with mock.patch.object(rules, "for_arm", side_effect=RuntimeError("columns")):
            self.urlopen.return_value = _Resp(GOOD)
            self.assertEqual(cycle.main(["--once"]), 0)
        row = self.rows()[-1]
        self.assertEqual((row["absence"], row["jev"]["error"], row["jev"]["input_tokens"]), ("jev", "unexpected", 480))

    # ---- the lock ----------------------------------------------------------------------------------
    def test_lock_held_elsewhere_is_absence_lock(self):
        os.makedirs(self.data)
        holder = open(config.LOCK, "a", encoding="utf-8")
        self.addCleanup(holder.close)
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(cycle.main(["--once"]), 0)
        row = self.only_row()
        self.assertEqual((row["absence"], row["tick_id"]), ("lock", TICK))
        self.snapshot.assert_not_called()
        self.assert_nothing_sent()
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        self.assertEqual(cycle.main(["--dry", "--once"]), 0)   # released: the next tick runs
        self.assertEqual(self.rows()[-1]["absence"], None)

    def test_lock_is_released_after_the_tick(self):
        cycle.main(["--dry", "--once"])
        fh = open(config.LOCK, "a", encoding="utf-8")
        self.addCleanup(fh.close)
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # would raise if the tick kept it

    # ---- the write ---------------------------------------------------------------------------------
    def test_rows_append_one_line_each_and_stay_readable(self):
        cycle.main(["--dry", "--once"])
        self.snapshot.side_effect = feed.FeedError("net")
        with mock.patch("time.time", return_value=NOW + 60):   # the next minute's tick
            cycle.main(["--once"])
        with open(config.DECISIONS, "rb") as fh:
            raw = fh.read()
        self.assertTrue(raw.endswith(b"\n"))
        self.assertEqual(raw.count(b"\n"), 2)
        rows = self.rows()
        self.assertEqual([r["absence"] for r in rows], [None, "feed"])
        self.assertEqual([r["mode"] for r in rows], ["dry", "live"])
        self.assertEqual([r["tick_id"] for r in rows], [TICK, "20260924T022900Z"])
        self.assertEqual(outcomes.join(rows)[TICK]["absence"], "gap")   # one minute apart: no t+h yet

    def test_a_log_that_is_writable_but_not_readable_still_gets_its_row(self):
        # the torn-line check opens the log O_RDWR; a log writable but not readable (mode 0200,
        # an ACL) refused that where the old O_WRONLY append worked, and every row was lost.
        # It now falls back to a plain append (no torn-line check) on PermissionError.
        real_open = os.open
        calls = []

        def fake_open(path, flags, *a):
            calls.append(flags)
            if flags & os.O_RDWR:
                raise PermissionError(13, "Permission denied", path)
            return real_open(path, flags, *a)
        os.makedirs(self.data, exist_ok=True)
        with open(config.DECISIONS, "wb") as fh:
            fh.write(b'{"v":1,"tick_id":"20260924T022700Z","ts_rx":"2026-09-24T02:27:00.100Z"')   # torn, no newline
        with mock.patch("os.open", side_effect=fake_open):
            cycle.write_row(cycle.new_row(TS_RX, "dry"))
        self.assertTrue(any(f & os.O_RDWR for f in calls) and any(not (f & os.O_RDWR) and f & os.O_WRONLY for f in calls))
        with open(config.DECISIONS, "rb") as fh:
            data = fh.read()
        self.assertEqual(data.count(b"\n"), 1)                              # appended without the fix-up: as before
        self.assertTrue(data.endswith(b"\n"))

    def test_a_torn_last_line_costs_itself_only(self):
        # A short write (disk full) or a crash mid-write leaves the log without its final
        # newline. The next row must start on a fresh line: glued onto the torn one, both fail
        # to parse. Nothing is truncated: the torn bytes stay where they are.
        cycle.main(["--dry", "--once"])
        with open(config.DECISIONS, "rb") as fh:
            whole = fh.read()
        torn = whole[:len(whole) // 2]
        with open(config.DECISIONS, "ab") as fh:
            fh.write(torn)                                     # half a row, no newline
        self.snapshot.side_effect = lambda: dict(SNAP, ts_rx=cycle.iso_ms(NOW + 60))
        cycle.main(["--dry", "--once"])
        bad = []
        rows = outcomes.load(config.DECISIONS, bad)
        self.assertEqual([r["tick_id"] for r in rows], [TICK, "20260924T022900Z"])   # both whole rows
        self.assertEqual([n for n, _ in bad], [2])                                    # exactly one bad line
        with open(config.DECISIONS, "rb") as fh:
            raw = fh.read()
        self.assertTrue(raw.startswith(whole + torn + b"\n{"))
        self.assertTrue(raw.endswith(b"\n"))
        self.assertEqual(raw.count(b"\n"), 3)
        cycle.main(["--dry", "--once"])                          # an intact end gets no blank line
        with open(config.DECISIONS, "rb") as fh:
            self.assertEqual(fh.read().count(b"\n"), 4)

    def test_an_unwritable_heartbeat_still_leaves_the_row_and_exit_0(self):
        # The heartbeat is written after the row: its failure used to print "row NOT written;
        # the tick is lost" about a row that was in the log.
        os.makedirs(config.HEARTBEAT)                          # a directory where the file goes
        with mock.patch("os.replace", wraps=os.replace) as rep:
            self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        self.assertEqual((self.only_row()["absence"], self.only_row()["state"]), (None, STATE))
        err = self.err.getvalue()
        self.assertIn("heartbeat NOT written", err)
        self.assertIn("the row is", err)
        self.assertNotIn("row NOT written", err)
        self.assertEqual(rep.call_args.args, (config.HEARTBEAT + ".tmp." + str(os.getpid()), config.HEARTBEAT))
        self.assertEqual(sorted(os.listdir(self.data)), ["decisions.jsonl", "heartbeat", "loop.lock"])  # no temp left
        os.rmdir(config.HEARTBEAT)
        self.snapshot.side_effect = lambda: dict(SNAP, ts_rx=cycle.iso_ms(NOW + 60))
        self.assertEqual(cycle.main(["--dry", "--once"]), 0)                   # and the next one lands again
        self.assertEqual(self.heartbeat(), cycle.iso_ms(NOW + 60))
        self.assertEqual(len(self.rows()), 2)

    def test_tick_id_floors_ts_rx_to_the_minute(self):
        self.assertEqual(cycle.tick_id("2026-09-24T02:28:49.000Z"), "20260924T022800Z")
        self.assertEqual(cycle.tick_id("2026-12-31T23:59:59.999Z"), "20261231T235900Z")
        self.assertEqual(cycle.iso_ms(NOW), TS_RX)
        self.assertEqual(cycle.iso_ms(NOW + 0.0425), "2026-09-24T02:28:49.042Z")

    # ---- the watchdog ------------------------------------------------------------------------------
    def test_watchdog_during_the_feed_is_absence_feed(self):
        self.snapshot.side_effect = lambda: _SLEEP(5)
        with mock.patch.object(cycle, "WATCHDOG_S", 1):
            t0 = time.monotonic()
            self.assertEqual(cycle.main(["--once"]), 0)
            self.assertLess(time.monotonic() - t0, 4.0)
        row = self.only_row()
        self.assertEqual(row["absence"], "feed")
        self.assertIn("watchdog", self.err.getvalue())
        self.assert_nothing_sent()
        self.assertEqual(signal.alarm(0), 0)                   # no alarm left armed

    def test_watchdog_during_the_send_is_absence_jev_watchdog(self):
        self.urlopen.side_effect = lambda *a, **k: _SLEEP(5)
        with mock.patch.object(cycle, "WATCHDOG_S", 1):
            self.assertEqual(cycle.main(["--once"]), 0)
        row = self.only_row()
        self.assertEqual((row["absence"], row["jev"]["error"]), ("jev", "watchdog"))
        self.assertEqual(row["state"], STATE)
        self.assertEqual(len(self.sends()), 2)                 # the ledger row preceded the hung send
        self.assertEqual(signal.alarm(0), 0)

    # A real SIGALRM, raised in-process at the moment a mock is reached: main()'s handler runs
    # before signal.raise_signal returns, exactly as when the 50 s alarm lands there.
    def test_watchdog_while_the_answer_becomes_columns_is_jev_watchdog_and_billed(self):
        self.urlopen.side_effect = None
        self.urlopen.return_value = _Resp(GOOD)
        def for_arm(answers, arm):
            signal.raise_signal(signal.SIGALRM)
            return rules.null_columns()
        with mock.patch.object(rules, "for_arm", side_effect=for_arm):
            self.assertEqual(cycle.main(["--once"]), 0)
        row = self.only_row()
        self.assertEqual((row["absence"], row["jev"]["error"]), ("jev", "watchdog"))   # was "guard", billed 0
        self.assertEqual(cycle.billed_tokens(row), 480)
        self.assertIsNone(row["answers"])                      # SPEC §2: answers on a parse row only
        self.assertEqual(row["columns"], {"a": None, "b": None})
        self.assertEqual(self.heartbeat(), TS_RX)
        self.assertEqual(signal.alarm(0), 0)

    def test_watchdog_inside_a_handler_still_writes_the_row_and_the_halt(self):
        # The alarm lands in the 401 handler's _halt, before HALT is written: the row was lost
        # ("in the guards; no row") and so was the HALT, until the next tick's 401.
        self.urlopen.side_effect = _http(401)
        real, calls = cycle._halt, []
        def halt(reason):
            calls.append(reason)
            if len(calls) == 1:
                signal.raise_signal(signal.SIGALRM)
            real(reason)
        with mock.patch.object(cycle, "_halt", side_effect=halt):
            self.assertEqual(cycle.main(["--once"]), 0)
        row = self.only_row()
        self.assertEqual((row["absence"], row["jev"]["error"]), ("jev", "http-4xx"))    # the first failure stays
        self.assertEqual(cycle.billed_tokens(row), config.JEV_TOKENS_IF_UNKNOWN)
        self.assertEqual(len(calls), 2)
        with open(config.HALT, encoding="utf-8") as fh:
            self.assertIn(cycle.HALT_KEY_REJECTED + ": http-4xx 401", fh.read())
        self.assertNotIn("no row", self.err.getvalue())
        self.assertIn("watchdog", self.err.getvalue())
        self.assertEqual(self.heartbeat(), TS_RX)
        self.assertEqual(signal.alarm(0), 0)

    def test_watchdog_escaping_run_marks_the_row_by_the_stage_it_reached(self):
        cases = (("feed", ("feed", None)), ("state", ("guard", None)), ("prompts", ("guard", None)),
                 ("ask", ("jev", "watchdog")), ("columns", ("jev", "watchdog")))
        for i, (stage, want) in enumerate(cases):
            def run(row, dry, halt, where, stage=stage):
                where["stage"] = stage
                if stage == "columns":
                    row["answers"] = ANSWERS
                signal.raise_signal(signal.SIGALRM)
            with self.subTest(stage=stage), mock.patch.object(cycle, "_run", side_effect=run), \
                    mock.patch("time.time", return_value=NOW + 60 * i):
                self.assertEqual(cycle.main(["--once"]), 0)
                row = self.rows()[-1]
                self.assertEqual((row["absence"], row["jev"]["error"]), want)
                self.assertIsNone(row["answers"])
        self.assertEqual(len(self.rows()), len(cases))
        self.assertNotIn("no row", self.err.getvalue())
        self.assertEqual(signal.alarm(0), 0)

    def test_watchdog_while_the_row_is_serialised_still_writes_it(self):
        real, fired = json.dumps, []
        def dumps(obj, *a, **k):
            if isinstance(obj, dict) and "tick_id" in obj and not fired:   # write_row's, not the body's or a sha's
                fired.append(1)
                signal.raise_signal(signal.SIGALRM)
            return real(obj, *a, **k)
        with mock.patch("json.dumps", side_effect=dumps):
            self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        self.assertEqual(fired, [1])
        self.assertEqual((self.only_row()["absence"], self.only_row()["state"]), (None, STATE))
        self.assertNotIn("no row", self.err.getvalue())

    def test_write_row_serialises_in_its_critical_section_and_disarms_the_alarm(self):
        os.makedirs(self.data)
        old = signal.signal(signal.SIGALRM, cycle._on_alarm)
        self.addCleanup(signal.signal, signal.SIGALRM, old)
        self.addCleanup(signal.alarm, 0)
        real = json.dumps
        def dumps(obj, *a, **k):
            signal.raise_signal(signal.SIGALRM)                        # ignored: the write has begun
            return real(obj, *a, **k)
        with mock.patch("json.dumps", side_effect=dumps):
            cycle.write_row(cycle.new_row(TS_RX, "dry"))
        signal.alarm(30)
        cycle.write_row(cycle.new_row(TS_RX, "dry"))
        self.assertEqual(signal.alarm(0), 0)                            # the write disarmed it
        self.assertEqual(len(self.rows()), 2)
        self.assertFalse(cycle._SIG["critical"])

    def test_watchdog_after_the_tick_ended_never_escapes_main(self):
        # A SIGALRM pending as the tick ends runs its handler at the next call: the disarm in
        # _guarded_tick's finally. It used to leave main() with exit 1 and a traceback.
        real = signal.alarm
        def alarm(n):
            left = real(n)
            if n == 0 and sys._getframe(1).f_code.co_name == "_guarded_tick":
                signal.raise_signal(signal.SIGALRM)
            return left
        with mock.patch.object(signal, "alarm", new=alarm):
            self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        self.assertEqual(self.only_row()["absence"], None)
        self.assertNotIn("Traceback", self.err.getvalue())
        self.assertEqual(signal.alarm(0), 0)

    def test_watchdog_in_the_guards_costs_the_row_never_the_exit_code(self):
        def spend(now):
            signal.raise_signal(signal.SIGALRM)
        with mock.patch.object(cycle, "spend_today", side_effect=spend):
            self.assertEqual(cycle.main(["--once"]), 0)
        self.assertEqual(self.rows(), [])
        self.assertIn("in the guards; no row", self.err.getvalue())
        self.snapshot.assert_not_called()
        self.assertEqual(signal.alarm(0), 0)

    # ---- SIGTERM -----------------------------------------------------------------------------------
    def test_sigterm_during_the_write_finishes_the_row_and_exits_0(self):
        real, real_term, got = os.fsync, cycle._on_term, []
        def fsync(fd):
            signal.raise_signal(signal.SIGTERM)                # arrives inside the critical section
            real(fd)
        def on_term(signum, frame):                            # main() installs this one
            got.append((signum, cycle._SIG["critical"]))
            return real_term(signum, frame)
        with mock.patch("os.fsync", side_effect=fsync), mock.patch.object(cycle, "_on_term", on_term):
            self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        self.assertEqual(got, [(signal.SIGTERM, True)])        # it did fire, and mid-write
        self.assertTrue(cycle._SIG["term"])
        row = self.only_row()                                  # complete, parseable, single line
        self.assertEqual((row["absence"], row["state"]), (None, STATE))
        self.assertEqual(self.heartbeat(), TS_RX)
        fh = open(config.LOCK, "a", encoding="utf-8")
        self.addCleanup(fh.close)
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # released on the way out
        self.assertEqual(signal.getsignal(signal.SIGTERM), signal.SIG_DFL)   # handlers restored

    def test_forever_waits_for_the_minute_boundary_and_sigterm_in_the_wait_exits_0(self):
        def sleep(s):
            self.sleeps.append(s)
            signal.raise_signal(signal.SIGTERM)
        with mock.patch("time.sleep", side_effect=sleep):
            self.assertEqual(cycle.main(["--forever"]), 0)
        self.assertEqual(self.sleeps, [11.0])                  # NOW is :49 -> 11 s to the next :00
        self.assertEqual(self.rows(), [])                      # no tick ran: no odd row at :49
        self.snapshot.assert_not_called()
        self.assert_nothing_sent()

    def test_forever_ticks_at_each_boundary_without_drift(self):
        clock = {"t": NOW}
        def now():
            return clock["t"]
        def sleep(s):
            self.sleeps.append(s)
            clock["t"] += s + 1.3                              # the wake-up plus a 1.3 s tick
            if len(self.sleeps) == 3:
                signal.raise_signal(signal.SIGTERM)
        self.snapshot.side_effect = lambda: dict(SNAP, ts_rx=cycle.iso_ms(clock["t"]))   # feed's own clock
        with mock.patch("time.time", side_effect=now), mock.patch("time.sleep", side_effect=sleep):
            self.assertEqual(cycle.main(["--dry", "--forever"]), 0)
        self.assertEqual([round(x, 6) for x in self.sleeps], [11.0, 58.7, 58.7])   # each wait absorbs the tick
        self.assertEqual([r["tick_id"] for r in self.rows()], ["20260924T022900Z", "20260924T023000Z"])

    def test_a_sigterm_test_leaves_no_pending_stop_for_the_next_test(self):
        # 2026-09-28 (review): the SIGTERM tests leave _SIG["term"] True (main clears it on entry only),
        # and in a shuffled order a later test calling write_row directly raised _Stop. Run the pair
        # as the runner would, SIGTERM first: the direct write must land.
        suite = unittest.TestSuite([CycleTest("test_sigterm_during_the_write_finishes_the_row_and_exits_0"),
                                    CycleTest("test_a_log_that_is_writable_but_not_readable_still_gets_its_row")])
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        self.assertEqual((result.testsRun, result.errors, result.failures), (2, [], []))
        self.assertEqual(cycle._SIG, {"critical": False, "term": False})
        # what the leak did: a stop left pending makes write_row write its row and then raise _Stop
        # (setUp's patch.dict puts _SIG back after this test, as after every other)
        cycle._SIG["term"] = True
        os.makedirs(self.data, exist_ok=True)
        with self.assertRaises(cycle._Stop):
            cycle.write_row(cycle.new_row(TS_RX, "dry"))
        self.assertEqual(len(self.rows()), 1)

    def test_sigterm_after_a_tick_in_forever_exits_0_after_that_tick(self):
        # The fake sleep advances the clock, as a real one does: _sleep_to_boundary loops
        # until the wall clock crosses :00 (the 2026-09-24 early-wake fix), so a frozen
        # clock would never let the first tick run.
        clock = [NOW]
        def sleep(s):
            self.sleeps.append(s)
            clock[0] += s
            if len(self.sleeps) == 2:
                signal.raise_signal(signal.SIGTERM)
        with mock.patch("time.time", side_effect=lambda: clock[0]), \
             mock.patch("time.sleep", side_effect=sleep):
            self.assertEqual(cycle.main(["--dry", "--forever"]), 0)
        self.assertEqual(len(self.rows()), 1)


if __name__ == "__main__":
    unittest.main()

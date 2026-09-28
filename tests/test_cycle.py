"""loop.cycle, offline. Every test: urllib.request.urlopen is mocked and raises unless a
test hands it a reply (so a call that reaches it is a failing test, never a packet);
config.JEV_URL points at 127.0.0.1:9 (discard) as a second wall; every data path in
config points into a temp dir; feed.snapshot is replaced by the fixture snapshot
(fixtures/: candles and trades 2026-09-24T02:28:49Z, the 100-level book 04:51:41Z,
assembled through feed.assemble); time.time is pinned
to the fixture's ts_rx so tick_id is known. main() installs and restores its own
SIGTERM/SIGALRM handlers; the two signal tests raise the signal in-process."""
import email.message, io, fcntl, hashlib, json, os, re, signal, tempfile, time, unittest, urllib.error
from unittest import mock
from fixture_prompts import pin_v1
from loop import book, config, cycle, feed, jev, outcomes, prompts, rules

_SLEEP = time.sleep                                  # the real one: time.sleep is mocked in setUp
FIX = os.path.join(config.REPO, "fixtures")


def _load(n):
    with open(os.path.join(FIX, n)) as fh:
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
        with open(self.protocol, "w") as fh:
            fh.write("In force from: `2026-09-24`  Signed: `test`\n")
        self.enterContext(mock.patch.object(config, "PROTOCOL", self.protocol))
        self.prompts_root = pin_v1(self)                        # never the live prompts/: CURRENT moves with bin/promote
        self.urlopen = self.enterContext(mock.patch("urllib.request.urlopen",
                                                    side_effect=AssertionError("urlopen was reached")))
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
        with open(config.SENDS) as fh:
            return fh.read().splitlines()

    def heartbeat(self):
        with open(config.HEARTBEAT) as fh:
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
        with open(config.HALT, "w") as fh:
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
        with open(config.HALT) as fh:                          # HALT is never removed by code
            self.assertEqual(fh.read(), "by hand\n")

    def test_halt_keeps_marks_and_outcomes_but_every_arm_holds(self):
        os.makedirs(self.data)
        open(config.HALT, "w").close()
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
        open(config.HALT, "w").close()
        holder = open(config.LOCK, "a")
        self.addCleanup(holder.close)
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(cycle.main(["--once"]), 0)
        self.assertEqual(self.only_row()["absence"], "lock")
        self.snapshot.assert_not_called()                     # the other holder fetches this minute

    def test_halt_in_dry_mode_is_a_dry_halt_row(self):
        os.makedirs(self.data)
        open(config.HALT, "w").close()
        self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        row = self.only_row()
        self.assertEqual((row["absence"], row["mode"], row["state"]), ("halt", "dry", STATE))
        self.assertEqual(self.out.getvalue(), "")              # under HALT no body is built for sending

    # ---- CONTRACT §6: spend over the limit writes HALT -------------------------------------
    def test_spend_over_limit_writes_halt_and_a_halt_row(self):
        os.makedirs(self.data)
        with open(config.DECISIONS, "w") as fh:
            fh.write(json.dumps(_row("20260923T235900Z", 50_000_000)) + "\n")   # yesterday: not counted
            fh.write(json.dumps(_row(DAY + "T010000Z", OVER)) + "\n")
            fh.write(json.dumps(_row(DAY + "T010100Z", None, "dry")) + "\n")    # dry: null tokens
            fh.write(json.dumps(_row(DAY + "T010200Z", OVER)) + "\n")
        self.assertAlmostEqual(cycle.spend_today(NOW), 2 * OVER * config.USD_PER_MTOK / 1e6)
        self.assertEqual(cycle.main(["--once"]), 0)
        self.assertTrue(os.path.exists(config.HALT))
        with open(config.HALT) as fh:
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

    def test_spend_just_under_limit_proceeds(self):
        os.makedirs(self.data)
        with open(config.DECISIONS, "w") as fh:
            for i in range(2):
                fh.write(json.dumps(_row(DAY + "T0100%02dZ" % i, UNDER)) + "\n")
        self.assertLess(cycle.spend_today(NOW), config.DAILY_SPEND_HALT_USD)
        self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        self.assertFalse(os.path.exists(config.HALT))
        self.assertEqual(self.rows()[-1]["absence"], None)
        self.snapshot.assert_called_once()

    def test_spend_reads_the_tail_and_widens_when_today_overflows_it(self):
        os.makedirs(self.data)
        with open(config.DECISIONS, "w") as fh:
            for i in range(20):
                fh.write(json.dumps(_row(DAY + "T01%02d00Z" % i, 1000)) + "\n")
            fh.write("{truncated line with no newline")
        with open(config.DECISIONS) as fh:
            size = len(fh.read())
        with mock.patch.object(cycle, "TAIL_BYTES", size // 3):     # the tail holds ~6 of the 20
            self.assertAlmostEqual(cycle.spend_today(NOW), 20_000 * config.USD_PER_MTOK / 1e6)
        self.assertAlmostEqual(cycle.spend_today(NOW), 20_000 * config.USD_PER_MTOK / 1e6)
        self.assertEqual(cycle.spend_today(NOW, os.path.join(self.tmp, "missing")), 0.0)

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
        with open(config.DECISIONS, "w") as fh:
            fh.writelines(json.dumps(x) + "\n" for x in rows)
        self.assertAlmostEqual(cycle.spend_today(NOW), (3 * U + 480) * config.USD_PER_MTOK / 1e6)
        # enough of them trip it: a runaway whose replies carry no usage still writes HALT
        n = int(config.DAILY_SPEND_HALT_USD / (U * config.USD_PER_MTOK / 1e6)) + 1
        with open(config.DECISIONS, "w") as fh:
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
                with open(config.HALT) as fh:
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

    def test_unsigned_protocol_observes_but_never_sends_or_bills(self):
        # The repo as committed: PROTOCOL.md unsigned. A live tick still records the feed,
        # the state and arm C -- observation is free and outlives sending -- but jev.ask
        # refuses before the key, the ledger or a socket, and the row bills nothing.
        with open(self.protocol, "w") as fh:
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
        holder = open(config.LOCK, "a")
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
        fh = open(config.LOCK, "a")
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

    # ---- SIGTERM -----------------------------------------------------------------------------------
    def test_sigterm_during_the_write_finishes_the_row_and_exits_0(self):
        real = os.fsync
        def fsync(fd):
            signal.raise_signal(signal.SIGTERM)                # arrives inside the critical section
            real(fd)
        with mock.patch("os.fsync", side_effect=fsync):
            self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        row = self.only_row()                                  # complete, parseable, single line
        self.assertEqual((row["absence"], row["state"]), (None, STATE))
        self.assertEqual(self.heartbeat(), TS_RX)
        fh = open(config.LOCK, "a")
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

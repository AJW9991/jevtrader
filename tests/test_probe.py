"""bin/probe: the path guard's refusals, the pacer (never two requests less than 1 s apart, on a fake
clock), run over the recorded fixtures (one row per candidate, the row's shape, an error row, SIGTERM,
the day's end, the hourly line), volume's file, and summarize on a directory this test writes (one
product passing, one failing volume, one failing occupancy). Offline: feed._get is replaced and
urlopen raises, so no test opens a socket."""
import fcntl, importlib.machinery, importlib.util, io, json, os, re, shutil, signal, subprocess, sys, tempfile, unittest
from unittest import mock

from loop import feed

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS)
TOOL = os.path.join(REPO, "bin", "probe")
FIX = os.path.join(REPO, "fixtures")
T_FIX = 1790216929.0                 # fixtures/meta.json ts_rx_epoch: 2026-09-24T02:28:49Z
DAY = "2026-09-24"
D0 = 1790208000                      # 2026-09-24T00:00:00Z


def _load_probe():
    path = os.path.join(REPO, "bin", "probe")
    loader = importlib.machinery.SourceFileLoader("probe_under_test", path)
    spec = importlib.util.spec_from_file_location("probe_under_test", path, loader=loader)
    mod = importlib.util.module_from_spec(spec)
    before, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = before
    return mod


probe = _load_probe()
_LOCK_DIR = None


def setUpModule():
    # the suite's runs take a lock of their own: a real probe run holds bin/probe's all day on D, and
    # `make test` in this worktree must still pass then (and must never stall or refuse that run)
    global _LOCK_DIR
    _LOCK_DIR = tempfile.mkdtemp()
    probe.LOCK_PATH = os.path.join(_LOCK_DIR, "probe.lock")
    with open(probe.LOCK_PATH, "w", encoding="utf-8"):
        pass


def tearDownModule():
    shutil.rmtree(_LOCK_DIR, ignore_errors=True)


class Clock:
    """A fake wall and monotonic clock in one: sleep(d) moves it by d; requests take no time."""
    def __init__(self, t):
        self.t, self.sleeps = float(t), []

    def now(self):
        return self.t

    def sleep(self, d):
        self.sleeps.append(d)
        self.t += d


def _read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


BOOK, CANDLES, TRADES = _read("book.json"), _read("candles.json"), _read("trades.json")


def _product(url):
    m = re.search(r"product_id=([A-Z0-9-]+)", url) or re.search(r"/products/([A-Z0-9-]+)/", url)
    return m.group(1)


class Offline(unittest.TestCase):
    """feed._get is the fixture server below; urlopen and create_connection raise if anything gets past it."""
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch("urllib.request.urlopen", side_effect=AssertionError("a socket")))
        self.enterContext(mock.patch("socket.create_connection", side_effect=AssertionError("a socket")))
        self.calls = []
        self.refuse = lambda url: None                      # a test sets it to fail some URLs (not self.fail: that is TestCase's)
        self.hook = lambda url: None                        # and this to act mid-request
        self.candles = CANDLES                              # and this to send other candles

    def fixture_get(self, clock):
        def get(url):
            self.calls.append((clock.now(), url))
            self.hook(url)
            why = self.refuse(url)
            if why:
                raise feed.FeedError(why)
            if "/product_book?" in url:
                j = json.loads(BOOK)
                j["pricebook"]["product_id"] = _product(url)
                return j
            if "/candles?" in url:
                return json.loads(self.candles)
            if "/ticker?" in url:
                return json.loads(TRADES)
            raise AssertionError(url)
        return get

    def main(self, argv, clock):
        err, fake = io.StringIO(), self.fixture_get(clock)
        with mock.patch.object(feed, "_get", fake):
            code = probe.main(argv, wall=clock.now, mono=clock.now, sleep=clock.sleep, err=err)
            self.assertIs(feed._get, fake)                  # the pacer's wrapper is gone again
        return code, err.getvalue()

    def rows(self, out, product):
        with open(os.path.join(out, f"{product}.jsonl"), encoding="utf-8") as fh:
            return [json.loads(l) for l in fh.read().splitlines()]


class Run(Offline):
    KEYS = {"tick_id", "ts_rx", "product", "ok", "mid", "spread_bps", "fill1k_bps", "fill1k_short", "vol5_usd",
            "trades_5m", "feed_age_s", "tick_est", "gets"}

    def test_one_cycle_one_row_per_candidate_paced(self):
        clock, out = Clock(T_FIX), os.path.join(self.tmp, "out")
        code, err = self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1", "--every", "1"], clock)
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(os.listdir(out)), sorted([f"{p}.jsonl" for p in probe.DEFAULT_CANDIDATES] + ["run.json"]))
        for p in probe.DEFAULT_CANDIDATES:
            (row,) = self.rows(out, p)
            self.assertEqual(set(row), self.KEYS, p)
            self.assertIs(row["ok"], True)
            self.assertEqual(row["product"], p)
            self.assertRegex(row["tick_id"], r"^20260924T02(28|29)00Z$")
            self.assertEqual(row["tick_id"][9:13], row["ts_rx"][11:13] + row["ts_rx"][14:16])   # the minute floor of ts_rx
            self.assertEqual(row["fill1k_bps"], 0.8698677800991063)   # fixtures/meta.json expect: the book's pinned cost
            self.assertIs(row["fill1k_short"], False)
            self.assertAlmostEqual(row["mid"], 114.96)
            self.assertEqual(row["tick_est"], {"ask": 0.01, "bid": 0.01})
            self.assertGreaterEqual(row["trades_5m"], 0)
            self.assertEqual(row["gets"], {"book": "ok", "candles": "ok", "ticker": "ok"})
        with open(os.path.join(out, "run.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"day": DAY, "candidates": list(probe.DEFAULT_CANDIDATES), "every": 1,
                                             "start_second": 30})
        # three GETs per candidate, in candidate order, never two less than 1 s apart
        self.assertEqual(len(self.calls), 3 * len(probe.DEFAULT_CANDIDATES))
        self.assertEqual([_product(u) for _, u in self.calls], [p for p in probe.DEFAULT_CANDIDATES for _ in range(3)])
        self.assertEqual([re.search(r"(product_book|candles|ticker)", u).group(1) for _, u in self.calls],
                         ["product_book", "candles", "ticker"] * len(probe.DEFAULT_CANDIDATES))
        gaps = [b - a for (a, _), (b, _) in zip(self.calls, self.calls[1:])]
        self.assertTrue(all(g >= 1.0 for g in gaps), gaps)
        self.assertEqual(clock.sleeps, [1.0] * 17)          # requests take no fake time: every gap is the pacer's sleep
        self.assertIn("done (--max-minutes 1), 1 cycles", err)
        self.assertNotIn("Traceback", err)

    def test_a_failed_get_writes_an_error_row_and_moves_on(self):
        clock, out = Clock(T_FIX), os.path.join(self.tmp, "out")
        self.refuse = lambda url: "http-503 /product_book" if "XRP-USD" in url and "product_book" in url else None
        code, err = self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1", "--every", "1",
                               "--candidates", "ETH-USD,XRP-USD,DOGE-USD"], clock)
        self.assertEqual(code, 0, err)
        (bad,) = self.rows(out, "XRP-USD")
        self.assertEqual(set(bad), {"tick_id", "ts_rx", "product", "ok", "error", "gets"})
        self.assertIs(bad["ok"], False)
        self.assertEqual(bad["error"], "FeedError: http-503 /product_book")
        self.assertEqual(bad["gets"], {"book": "http-503 /product_book"})     # the two after it never ran
        self.assertIs(self.rows(out, "ETH-USD")[0]["ok"], True)
        self.assertIs(self.rows(out, "DOGE-USD")[0]["ok"], True)
        self.assertNotIn("Traceback", err)
        self.assertIn("XRP-USD ok 0 error 1", err)
        gaps = [b - a for (a, _), (b, _) in zip(self.calls, self.calls[1:])]
        self.assertEqual(len(self.calls), 7)                 # the failed book stops XRP's snapshot: 3 + 1 + 3
        self.assertTrue(all(g >= 1.0 for g in gaps), gaps)

    def test_a_failed_ticker_shows_in_the_row(self):
        # the feed tolerates a dead ticker (trades_5m -1, the snapshot assembles): only the record shows it
        clock, out = Clock(T_FIX), os.path.join(self.tmp, "out")
        self.refuse = lambda url: "http-503 /products/XRP-USD/ticker" if "XRP-USD/ticker" in url else None
        code, err = self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1", "--every", "1",
                               "--candidates", "ETH-USD,XRP-USD"], clock)
        self.assertEqual(code, 0, err)
        (xrp,) = self.rows(out, "XRP-USD")
        self.assertIs(xrp["ok"], True)
        self.assertEqual(xrp["trades_5m"], -1)
        self.assertEqual(xrp["gets"], {"book": "ok", "candles": "ok", "ticker": "http-503 /products/XRP-USD/ticker"})
        self.assertFalse(probe.ok_row(xrp))
        self.assertTrue(probe.transport_failed(xrp))
        self.assertTrue(probe.ok_row(self.rows(out, "ETH-USD")[0]))

    def test_a_quiet_minute_is_an_error_row_but_no_transport_failure(self):
        # the refuter's gap.py: one closed minute missing inside the window; all three GETs answered
        j = json.loads(CANDLES)
        starts = sorted(int(c["start"]) for c in j["candles"])
        j["candles"] = [c for c in j["candles"] if int(c["start"]) != starts[-10]]
        self.candles = json.dumps(j)
        clock, out = Clock(T_FIX), os.path.join(self.tmp, "out")
        code, err = self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1", "--every", "1",
                               "--candidates", "ETH-USD"], clock)
        self.assertEqual(code, 0, err)
        (row,) = self.rows(out, "ETH-USD")
        self.assertIs(row["ok"], False)
        self.assertTrue(row["error"].startswith("FeedError: candles: not contiguous"), row["error"])
        self.assertEqual(row["gets"], {"book": "ok", "candles": "ok", "ticker": "ok"})
        self.assertFalse(probe.ok_row(row))                 # features were not computed: not an ok row
        self.assertFalse(probe.transport_failed(row))       # and not a transport failure either

    def test_a_short_window_is_an_error_row_too(self):
        clock, out = Clock(T_FIX), os.path.join(self.tmp, "out")

        def no_window(product, now):                        # a snapshot the feed accepted, then no candles in it
            book = json.loads(BOOK)
            book["pricebook"]["product_id"] = product
            snap = feed.assemble(product, now, book, json.loads(CANDLES), json.loads(TRADES), {"calls": 0, "ms": 0})
            snap["candles"] = []
            return snap
        with mock.patch.object(feed, "snapshot", no_window):
            code, err = self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1", "--every", "1",
                                   "--candidates", "ETH-USD"], clock)
        self.assertEqual(code, 0, err)
        (row,) = self.rows(out, "ETH-USD")
        self.assertEqual(row["error"], "ValueError: window: 0 candles < WINDOW_MIN 300")

    def test_sigterm_finishes_the_row_then_exits_0(self):
        clock, out = Clock(T_FIX), os.path.join(self.tmp, "out")
        before = signal.getsignal(signal.SIGTERM)

        def term_on_xrp_candles(url):                       # the handler bin/probe installed, as a SIGTERM would call it
            if "XRP-USD" in url and "/candles?" in url:
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        self.hook = term_on_xrp_candles
        code, err = self.main(["run", "--day", DAY, "--out", out, "--every", "1"], clock)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.rows(out, "ETH-USD")), 1)
        (xrp,) = self.rows(out, "XRP-USD")                  # the row in flight is finished, whole
        self.assertIs(xrp["ok"], True)
        self.assertFalse(os.path.exists(os.path.join(out, "DOGE-USD.jsonl")))
        self.assertEqual(len(self.calls), 6)
        self.assertIn("done (SIGTERM), 0 cycles", err)
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)

    def test_samples_only_its_day_and_exits_after_the_last_slot(self):
        clock, out = Clock(D0 + 86400 - 130), os.path.join(self.tmp, "out")      # 23:57:50
        self.refuse = lambda url: "http-503 /product_book"
        code, err = self.main(["run", "--day", DAY, "--out", out, "--candidates", "ETH-USD,XRP-USD"], clock)
        self.assertEqual(code, 0, err)
        self.assertEqual([r["tick_id"] for r in self.rows(out, "ETH-USD")], ["20260924T235800Z", "20260924T235900Z"])
        self.assertEqual([r["ts_rx"] for r in self.rows(out, "ETH-USD")],
                         ["2026-09-24T23:58:30.000Z", "2026-09-24T23:59:30.000Z"])
        self.assertIn("done (the day is over), 2 cycles; ETH-USD ok 0 error 2; XRP-USD ok 0 error 2", err)
        self.assertTrue(all(s <= 1.0 for s in clock.sleeps))  # naps of a second at most: SIGTERM is seen quickly

    def test_waits_for_its_day_and_refuses_one_that_is_over(self):
        clock, out = Clock(D0 - 15), os.path.join(self.tmp, "early")               # 2026-09-23T23:59:45Z
        self.refuse = lambda url: "http-503 /product_book"
        code, err = self.main(["run", "--day", DAY, "--out", out, "--candidates", "ETH-USD", "--max-minutes", "1"], clock)
        self.assertEqual(code, 0, err)
        self.assertEqual([r["ts_rx"] for r in self.rows(out, "ETH-USD")], ["2026-09-24T00:00:30.000Z"])
        late = os.path.join(self.tmp, "late")
        code, err = self.main(["run", "--day", DAY, "--out", late], Clock(D0 + 86400 - 20))   # 23:59:40: no slot left
        self.assertEqual(code, 2)
        self.assertIn("no slot left", err)
        self.assertFalse(os.path.exists(late))

    def test_one_line_an_hour_with_the_counts(self):
        clock, out = Clock(D0 + 3600 - 110), os.path.join(self.tmp, "out")        # 00:58:10
        self.refuse = lambda url: "http-503 /product_book"
        code, err = self.main(["run", "--day", DAY, "--out", out, "--candidates", "ETH-USD,XRP-USD",
                               "--max-minutes", "3"], clock)
        self.assertEqual(code, 0, err)
        lines = err.splitlines()
        self.assertEqual(len(lines), 3, err)                # the start, one hourly line, the end
        self.assertEqual(lines[1], "2026-09-24T01:00:30.000Z probe: 2 cycles; ETH-USD ok 0 error 2; XRP-USD ok 0 error 2")

    def test_a_directory_of_another_run_is_refused(self):
        out = os.path.join(self.tmp, "out")
        self.refuse = lambda url: "http-503 /product_book"
        self.assertEqual(self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1"], Clock(T_FIX))[0], 0)
        code, err = self.main(["run", "--day", "2026-09-25", "--out", out, "--max-minutes", "1"], Clock(T_FIX))
        self.assertEqual(code, 2)
        self.assertIn("another day", err)
        code, err = self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1", "--candidates", "ETH-USD"],
                              Clock(T_FIX))
        self.assertEqual(code, 2)
        self.assertEqual(self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1"], Clock(T_FIX))[0], 0)
        self.assertEqual(len(self.rows(out, "ETH-USD")), 2)  # the same day resumes, appending
        for other in (["--every", "1"], ["--start-second", "10"]):                # a resume keeps the cadence too
            code, err = self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1", *other], Clock(T_FIX))
            self.assertEqual(code, 2, other)
            self.assertIn('"every": 60', err)
        self.assertEqual(len(self.rows(out, "ETH-USD")), 2)


class Deadline(Offline):
    """A slow cycle stops two seconds before the live loop's :00: at the defaults no request starts at or
    after :58 of the slot's minute (T_FIX is 02:28:49, so the slot is 02:29:30 and the deadline 02:29:58)."""
    def slow(self, clock, cost):
        def take(url):                                      # each request costs `cost` seconds of the fake clock
            clock.t += cost
        self.hook = take

    def test_candidates_not_begun_by_the_deadline_get_no_row(self):
        clock, out = Clock(T_FIX), os.path.join(self.tmp, "out")
        self.slow(clock, 2.5)                               # four candidates fit: 12 GETs from :30.0 to :57.5
        code, err = self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1"], clock)
        self.assertEqual(code, 0, err)
        until = T_FIX - 49 + 60 + 58                          # 02:29:58
        self.assertEqual(len(self.calls), 12)
        self.assertLess(max(t for t, _ in self.calls), until)
        for p in probe.DEFAULT_CANDIDATES[:4]:
            self.assertEqual([r["tick_id"] for r in self.rows(out, p)], ["20260924T022900Z"], p)
        for p in probe.DEFAULT_CANDIDATES[4:]:
            self.assertFalse(os.path.exists(os.path.join(out, f"{p}.jsonl")), p)
        self.assertIn("LINK-USD ok 0 error 0 skipped 1; ADA-USD ok 0 error 0 skipped 1", err)

    def test_a_get_after_the_deadline_is_not_sent_and_is_no_transport_failure(self):
        clock, out = Clock(T_FIX), os.path.join(self.tmp, "out")
        self.slow(clock, 1.7)                               # the 18th GET (ADA's ticker) would start at :58.9
        code, err = self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1"], clock)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.calls), 17)
        self.assertLess(max(t for t, _ in self.calls), T_FIX - 49 + 60 + 58)
        (ada,) = self.rows(out, "ADA-USD")
        self.assertEqual(ada["gets"], {"book": "ok", "candles": "ok", "ticker": "deadline"})
        self.assertEqual(ada["trades_5m"], -1)              # the feed tolerates a ticker it did not get
        self.assertFalse(probe.ok_row(ada))
        self.assertFalse(probe.transport_failed(ada))

    def test_a_start_second_that_leaves_no_room_is_a_usage_error(self):
        with mock.patch("sys.stderr", io.StringIO()):
            for s in ("58", "59"):
                with self.assertRaises(SystemExit):
                    probe.main(["run", "--day", DAY, "--out", os.path.join(self.tmp, "x"), "--start-second", s])
        self.assertEqual(probe.LIVE_GUARD_S, 2)


class Harness(unittest.TestCase):
    def test_offline_keeps_testcase_fail(self):
        # Offline once kept its URL-failure hook in self.fail, which is TestCase.fail: every assertion that
        # reports through fail() (assertIn, assertIs, list and str assertEqual) then passed whatever it saw
        t = Run("test_one_cycle_one_row_per_candidate_paced")
        t.setUp()
        self.addCleanup(t.doCleanups)
        for bad in (lambda: t.assertIn("x", "y"), lambda: t.assertEqual([1], [2]), lambda: t.assertIs(True, False)):
            with self.assertRaises(AssertionError):
                bad()


class OneAtATime(Offline):
    """The rate is one request a second overall: a second run or volume, into any DIR, is refused while
    one is running (both flock bin/probe itself, read-only)."""
    def hold(self, path=None):
        fd = os.open(path or probe.LOCK_PATH, os.O_RDONLY)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd

    def test_the_lock_is_bin_probe_itself(self):
        self.assertEqual(os.path.realpath(_load_probe().LOCK_PATH), os.path.realpath(TOOL))   # not the suite's

    def test_the_suite_runs_while_a_real_probe_holds_the_lock(self):
        fd = self.hold(TOOL)                                # as bin/probe run does all day on D
        try:
            self.refuse = lambda url: "http-503 /product_book"
            code, err = self.main(["run", "--day", DAY, "--out", os.path.join(self.tmp, "out"), "--max-minutes", "1",
                                   "--every", "1"], Clock(T_FIX))
            self.assertEqual(code, 0, err)
        finally:
            os.close(fd)

    def test_a_second_run_or_volume_is_refused_and_creates_nothing(self):
        fd = self.hold()
        try:
            for cmd in (["run", "--day", DAY, "--max-minutes", "1", "--every", "1"], ["volume", "--day", "2026-09-23"]):
                out = os.path.join(self.tmp, cmd[0])
                code, err = self.main(cmd + ["--out", out], Clock(T_FIX))
                self.assertEqual(code, 2, cmd)
                self.assertIn("holds the lock", err)
                self.assertFalse(os.path.exists(out))
            self.assertEqual(self.calls, [])
        finally:
            os.close(fd)
        out = os.path.join(self.tmp, "after")
        self.refuse = lambda url: "http-503 /product_book"
        self.assertEqual(self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1", "--every", "1"],
                                   Clock(T_FIX))[0], 0)

    def test_a_run_holds_the_lock_while_it_requests_and_frees_it_after(self):
        seen = []

        def try_lock(url):
            try:
                os.close(self.hold())
                seen.append("free")
            except BlockingIOError:
                seen.append("held")
        self.hook = try_lock
        out = os.path.join(self.tmp, "out")
        code, err = self.main(["run", "--day", DAY, "--out", out, "--candidates", "ETH-USD", "--max-minutes", "1",
                               "--every", "1"], Clock(T_FIX))
        self.assertEqual(code, 0, err)
        self.assertEqual(seen, ["held"] * 3)
        os.close(self.hold())                                # free again once main returned


class Pacing(unittest.TestCase):
    def test_at_least_the_gap_between_request_starts(self):
        c = Clock(100.0)
        p = probe.Pacer(1.0, c.now, c.sleep)
        starts = []
        for elapsed in (0.0, 0.0, 0.5, 2.5, 0.0):
            c.t += elapsed                                   # time the caller spent between requests
            p.mark()
            starts.append(c.now())
        self.assertEqual(starts, [100.0, 101.0, 102.0, 104.5, 105.5])
        self.assertEqual(c.sleeps, [1.0, 0.5, 1.0])
        self.assertEqual(probe.MIN_GAP_S, 1.0)


class Guard(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(self.enterContext(tempfile.TemporaryDirectory()))
        self.live = os.path.join(self.tmp, "live")
        os.makedirs(self.live)

    def test_the_live_checkout_and_the_forbidden_prefixes_are_the_defaults(self):
        self.assertEqual(probe.LIVE_CHECKOUT, "/Users/alexanderward/Projects/jev-paper-loop")
        self.assertIn(probe.LIVE_CHECKOUT, probe.FORBIDDEN)
        for p in probe.config.FORBIDDEN_PREFIXES:
            self.assertIn(p, probe.FORBIDDEN)
        self.assertIsNotNone(probe.refused(probe.LIVE_CHECKOUT + "/probe-out"))
        self.assertIsNotNone(probe.refused(probe.LIVE_CHECKOUT))
        self.assertIsNone(probe.refused(probe.LIVE_CHECKOUT + "-v2/probe-out"))    # a '/' boundary, not a prefix string

    def test_inside_a_forbidden_tree_by_any_name(self):
        pre = (self.live,)
        self.assertIsNotNone(probe.refused(os.path.join(self.live, "x", "y"), pre))
        self.assertIsNotNone(probe.refused(os.path.join(self.tmp, "elsewhere", "..", "live", "x"), pre))
        os.symlink(self.live, os.path.join(self.tmp, "link"))
        self.assertIsNotNone(probe.refused(os.path.join(self.tmp, "link", "x"), pre))
        self.assertIsNone(probe.refused(os.path.join(self.tmp, "live-v2", "x"), pre))
        upper = os.path.join(self.tmp, "LIVE")
        if os.path.exists(upper):                           # a case-insensitive volume (the Mac): the same directory
            self.assertIsNotNone(probe.refused(os.path.join(upper, "x"), pre))

    def test_any_directory_named_data(self):
        for parts in (("data",), ("data", "out"), ("Data", "probe"), ("a", "DATA", "b")):
            self.assertIsNotNone(probe.refused(os.path.join(self.tmp, *parts), ()), parts)
        os.makedirs(os.path.join(self.tmp, "data"))
        os.symlink(os.path.join(self.tmp, "data"), os.path.join(self.tmp, "innocent"))
        self.assertIsNotNone(probe.refused(os.path.join(self.tmp, "innocent", "out"), ()))
        self.assertIsNone(probe.refused(os.path.join(self.tmp, "database", "out"), ()))
        self.assertIsNone(probe.refused(os.path.join(self.tmp, "probe-2026-10-01"), ()))

    def test_any_directory_named_logs(self):
        # PREREG-v2 section 2: nothing under any data/ or logs/
        for parts in (("logs",), ("logs", "probe"), ("Logs", "probe"), ("a", "LOGS", "b")):
            self.assertIsNotNone(probe.refused(os.path.join(self.tmp, *parts), ()), parts)
        self.assertIsNotNone(probe.refused(os.path.join(REPO, "logs", "probe")))
        os.makedirs(os.path.join(self.tmp, "logs"))
        os.symlink(os.path.join(self.tmp, "logs"), os.path.join(self.tmp, "plain"))
        self.assertIsNotNone(probe.refused(os.path.join(self.tmp, "plain", "out"), ()))
        self.assertIsNone(probe.refused(os.path.join(self.tmp, "logsheet", "out"), ()))
        self.assertIsNone(probe.refused(os.path.join(self.tmp, "catalogs", "out"), ()))

    def test_run_and_volume_exit_3_and_create_nothing(self):
        def main(argv):                                     # a guard that let it through would run one cycle and stop
            c, err = Clock(T_FIX), io.StringIO()
            with mock.patch.object(feed, "_get", side_effect=feed.FeedError("a request")):
                return probe.main(argv, wall=c.now, mono=c.now, sleep=c.sleep, err=err), err.getvalue()
        for cmd in (["run", "--day", DAY, "--max-minutes", "1"], ["volume", "--day", "2026-09-23"]):
            code, err = main(cmd + ["--out", os.path.join(self.tmp, "data", "probe")])
            self.assertEqual(code, 3, cmd)
            self.assertIn("refusing --out", err)
            self.assertFalse(os.path.exists(os.path.join(self.tmp, "data")))
            with mock.patch.object(probe, "FORBIDDEN", (self.live,)):
                self.assertEqual(main(cmd + ["--out", os.path.join(self.live, "p")])[0], 3)
            self.assertEqual(os.listdir(self.live), [])


class Files(Offline):
    """A file inside an accepted DIR that is a symlink or a hard link is never written through."""
    def setUp(self):
        super().setUp()
        self.out = os.path.join(self.tmp, "out")
        self.elsewhere = os.path.join(self.tmp, "data")      # where a link would carry the rows
        os.makedirs(self.out)
        os.makedirs(self.elsewhere)
        self.target = os.path.join(self.elsewhere, "target.jsonl")
        with open(self.target, "w", encoding="utf-8") as fh:
            fh.write("sealed\n")

    def assertTargetUntouched(self):
        with open(self.target, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "sealed\n")

    def test_a_symlinked_product_file_refuses_the_run_before_anything(self):
        os.symlink(self.target, os.path.join(self.out, "ETH-USD.jsonl"))
        code, err = self.main(["run", "--day", DAY, "--out", self.out, "--candidates", "ETH-USD", "--max-minutes",
                               "1", "--every", "1"], Clock(T_FIX))
        self.assertEqual(code, 3, err)
        self.assertIn("refusing to write", err)
        self.assertTargetUntouched()
        self.assertEqual(os.listdir(self.out), ["ETH-USD.jsonl"])     # no run.json either
        self.assertEqual(self.calls, [])

    def test_a_hard_linked_product_file_is_refused_too(self):
        os.link(self.target, os.path.join(self.out, "ETH-USD.jsonl"))
        code, err = self.main(["run", "--day", DAY, "--out", self.out, "--candidates", "ETH-USD", "--max-minutes",
                               "1", "--every", "1"], Clock(T_FIX))
        self.assertEqual(code, 3, err)
        self.assertTargetUntouched()

    def test_a_link_swapped_in_mid_run_is_refused_at_the_write(self):
        def swap(url):                                      # while ETH is fetched, XRP's file becomes a symlink
            path = os.path.join(self.out, "XRP-USD.jsonl")
            if "ETH-USD" in url and not os.path.lexists(path):
                os.symlink(self.target, path)
        self.hook = swap
        code, err = self.main(["run", "--day", DAY, "--out", self.out, "--candidates", "ETH-USD,XRP-USD",
                               "--max-minutes", "1", "--every", "1"], Clock(T_FIX))
        self.assertEqual(code, 3, err)
        self.assertTargetUntouched()
        self.assertEqual(len(self.rows(self.out, "ETH-USD")), 1)

    def test_a_symlinked_tmp_or_json_file_is_refused(self):
        os.symlink(self.target, os.path.join(self.out, "run.json.tmp"))
        code, err = self.main(["run", "--day", DAY, "--out", self.out, "--candidates", "ETH-USD", "--max-minutes",
                               "1", "--every", "1"], Clock(T_FIX))
        self.assertEqual(code, 3, err)
        self.assertTargetUntouched()
        vol = os.path.join(self.tmp, "vol")
        os.makedirs(vol)
        os.symlink(self.target, os.path.join(vol, "volume.json.tmp"))
        c = Clock(T_FIX)
        with mock.patch.object(feed, "_get", lambda url: {"candles": []}):
            code = probe.main(["volume", "--day", "2026-09-23", "--out", vol, "--candidates", "ETH-USD"], wall=c.now,
                              mono=c.now, sleep=c.sleep, err=io.StringIO())
        self.assertEqual(code, 3)
        self.assertTargetUntouched()


class Volume(Offline):
    DAYS = [{"start": str(D0 - 86400 * k), "low": "1", "high": "3", "open": "2", "close": "2000", "volume": "1000"}
            for k in range(0, 32)]                            # k = 0 is 09-24, open at T_FIX; k = 30, 31 are before

    def volume(self, argv, clock, get=None):
        err = io.StringIO()
        with mock.patch.object(feed, "_get", get or self.days_get(clock)):
            code = probe.main(["volume", *argv], wall=clock.now, mono=clock.now, sleep=clock.sleep, err=err)
        return code, err.getvalue()

    def days_get(self, clock, days=None):
        def get(url):
            self.calls.append((clock.now(), url))
            if "XRP-USD" in url:
                raise feed.FeedError("http-404 /products/XRP-USD/candles")
            return {"candles": self.DAYS if days is None else days}
        return get

    def read(self, out):
        with open(os.path.join(out, "volume.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_the_thirty_days_ending_with_d_per_candidate(self):
        clock, out = Clock(T_FIX), os.path.join(self.tmp, "out")     # D = 09-23, run on 09-24 at 02:28:49
        code, err = self.volume(["--day", "2026-09-23", "--out", out, "--candidates", "ETH-USD,XRP-USD"], clock)
        self.assertEqual(code, 1, err)                        # XRP's endpoint did not answer
        self.assertIn("did not answer for XRP-USD", err)
        self.assertTrue(err.isascii(), err)                  # printable under a C locale (make test-mode c-locale)
        v = self.read(out)
        self.assertEqual(v["products"]["ETH-USD"], {"usd_per_day": 2e6, "rows": 30, "candles": self.DAYS})
        self.assertEqual(v["products"]["XRP-USD"], {"error": "FeedError: http-404 /products/XRP-USD/candles"})
        self.assertEqual((v["day"], v["start"], v["end"], v["days"]),
                         ("2026-09-23", "2026-08-25T00:00:00.000Z", "2026-09-24T00:00:00.000Z", 30))
        self.assertEqual([u for _, u in self.calls], [
            f"{feed.BASE}/products/{p}/candles?start={D0 - 30 * 86400}&end={D0}&granularity=ONE_DAY"
            for p in ("ETH-USD", "XRP-USD")])
        self.assertEqual(self.calls[1][0] - self.calls[0][0], 1.0)

    def test_the_window_is_d_s_whenever_it_runs(self):
        # the refuter: at 09-24 01:00Z it asked for end=1790208000, at 09-29 for end=1790640000
        urls = []
        for when in (D0 + 3600, D0 + 5 * 86400 + 3600):
            self.calls = []
            code, err = self.volume(["--day", "2026-09-23", "--out", os.path.join(self.tmp, str(when)),
                                     "--candidates", "ETH-USD"], Clock(when))
            self.assertEqual(code, 0, err)
            urls.append(self.calls[0][1])
        self.assertEqual(urls, [f"{feed.BASE}/products/ETH-USD/candles?start={D0 - 30 * 86400}&end={D0}"
                                "&granularity=ONE_DAY"] * 2)

    def test_refused_before_d_closes_a_second_time_and_into_another_day_s_run(self):
        out = os.path.join(self.tmp, "out")
        code, err = self.volume(["--day", DAY, "--out", out], Clock(D0 + 86400 - 1))     # 09-24 23:59:59
        self.assertEqual(code, 2)
        self.assertIn("closes at 2026-09-25T00:00:00.000Z", err)
        self.assertFalse(os.path.exists(out))
        self.assertEqual(self.volume(["--day", DAY, "--out", out, "--candidates", "ETH-USD"], Clock(D0 + 86400))[0], 0)
        before = self.read(out)
        code, err = self.volume(["--day", DAY, "--out", out, "--candidates", "ETH-USD"], Clock(D0 + 2 * 86400))
        self.assertEqual(code, 2)
        self.assertIn("runs once", err)
        self.assertEqual(self.read(out), before)
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        with open(os.path.join(other, "run.json"), "w", encoding="utf-8") as fh:
            json.dump({"day": "2026-09-22", "candidates": ["ETH-USD"], "every": 60, "start_second": 30}, fh)
        code, err = self.volume(["--day", DAY, "--out", other, "--candidates", "ETH-USD"], Clock(D0 + 86400))
        self.assertEqual(code, 2)
        self.assertIn("holds the run of 2026-09-22", err)
        self.assertEqual(os.listdir(other), ["run.json"])

    def test_fewer_than_thirty_days_give_no_figure(self):
        # the refuter: zero candles gave usd_per_day 0.0, and five rows a figure that passed
        clock = Clock(T_FIX)
        for days, rows in (([], 0), (self.DAYS[1:6], 5), (self.DAYS[2:32], 29)):
            out = os.path.join(self.tmp, str(rows))
            code, err = self.volume(["--day", "2026-09-23", "--out", out, "--candidates", "ETH-USD"], clock,
                                    self.days_get(clock, days))
            self.assertEqual(code, 0, err)
            self.assertEqual(self.read(out)["products"]["ETH-USD"], {"usd_per_day": None, "rows": rows, "candles": days})
            self.assertIn(f"{rows} daily rows, not the 30 days ending with 2026-09-23: no figure", err)


ALL_OK = {"book": "ok", "candles": "ok", "ticker": "ok"}
NO_BOOK = {"book": "http-503 /product_book"}


def _prow(m, fill, ok=True, day="20260924", tick=0.0001):
    t = f"{day}T{m // 60:02d}{m % 60:02d}00Z"
    if not ok:                                              # a transport failure: the book did not answer
        return {"tick_id": t, "ts_rx": "x", "product": "P", "ok": False, "error": "FeedError: http-503 /product_book",
                "gets": dict(NO_BOOK)}
    return {"tick_id": t, "ts_rx": "x", "product": "P", "ok": True, "mid": 0.5, "spread_bps": 1.0, "fill1k_bps": fill,
            "fill1k_short": False, "vol5_usd": 1.0, "trades_5m": 10, "feed_age_s": 5.0,
            "tick_est": {"ask": tick, "bid": tick}, "gets": dict(ALL_OK)}


# h = fill * 0.5 / (1e4 * 0.0001 / 2) = fill. One row a minute over D's 1,440: a 20-minute pattern of
# 3 x 1, 13 x 2, 3 x 3, 1 x 4 repeated 72 times (15 %, 65 %, 15 %, 5 %), or every minute at 2
PASSING = ([1.0] * 3 + [2.0] * 13 + [3.0] * 3 + [4.0]) * 72
FLAT = [2.0] * 1440
TEN = tuple(range(3, 13))                                   # ten minutes whose pattern value is 2


def _write_product(d, product, fills, errors=(), extra=True):
    """One row a minute from fills; the minutes in `errors` are transport-failure rows instead."""
    rows = [_prow(m, f, ok=m not in errors) for m, f in enumerate(fills)]
    if extra:
        if len(rows) > 20:
            rows[20]["tick_est"] = {"ask": 0.0002, "bid": 0.0002}    # the mode still wins
        rows.append(_prow(0, 9.0))                                   # minute 0 again: counted, not read
        rows.append(_prow(0, 9.0, day="20260925"))                   # the next day: not read
    with open(os.path.join(d, f"{product}.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
        if extra:
            fh.write('{"tick_id": "20260924T0031')                      # torn


def _write_dir(d, products, volumes, errors=None):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "run.json"), "w", encoding="utf-8") as fh:
        json.dump({"day": DAY, "candidates": list(products), "every": 60, "start_second": 30}, fh)
    for p, fills in products.items():
        _write_product(d, p, fills, (errors or {}).get(p, ()))
    with open(os.path.join(d, "volume.json"), "w", encoding="utf-8") as fh:
        json.dump({"day": DAY, "start": VOL_START, "end": VOL_END, "days": 30,
                   "products": {p: {"usd_per_day": v, "rows": 30, "candles": []} for p, v in volumes.items()}}, fh)


def _summarize(d, *extra):
    out, err = io.StringIO(), io.StringIO()
    code = probe.main(["summarize", d, *extra], out=out, err=err)
    return code, out.getvalue(), err.getvalue()


CRITERIA = ("criteria: (1) ok rows (the three public GETs answered, features computed) >= 99% of D's minutes with a"
            " row for any candidate; (2) sum(volume x close)/30 over exactly the 30 daily candles ending with D >="
            " 50000000 USD/day; (3) each liq word in [3%, 90%] of D's ok rows under the h-rule; (4) not a stablecoin")
VOL_START, VOL_END = "2026-08-26T00:00:00.000Z", "2026-09-25T00:00:00.000Z"     # D = 2026-09-24: 08-26 ... 09-24
VOID = "chosen: none (D is void; PREREG-v2 section 2: D becomes the next UTC day, once, named in section 14)"


def _h(p10, p50, p90, p99, mx):
    return [f"h_p10: {p10:.4f}", f"h_p50: {p50:.4f}", f"h_p90: {p90:.4f}", f"h_p99: {p99:.4f}", f"h_max: {mx:.4f}"]


class Summarize(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())

    def test_passing_and_failing_ok_rows_volume_and_occupancy(self):
        d = os.path.join(self.tmp, "probe")
        _write_dir(d, {"ETH-USD": PASSING, "XRP-USD": PASSING, "DOGE-USD": FLAT, "AVAX-USD": PASSING},
                   {"ETH-USD": 60e6, "XRP-USD": 40e6, "DOGE-USD": 80e6, "AVAX-USD": 70e6},
                   errors={"ETH-USD": TEN, "AVAX-USD": TEN + tuple(m + 20 for m in TEN)})
        code, out, err = _summarize(d)
        self.assertEqual(code, 0, err)
        tail = ["a10: 1", "a90: 3", "rule: deep iff h < 1.5; thin iff h > 3.5 or fill1k_short; normal otherwise",
                "thin_fallback: no"]
        seen = "unparsable lines 1, rows outside the day 1, repeated minutes 1)"
        self.assertEqual(out.splitlines(), [
            f"dir: {d}", "day: 2026-09-24", "candidates: ETH-USD XRP-USD DOGE-USD AVAX-USD", CRITERIA,
            "minutes_with_rows: 1440/1440 100.00% (D is void below 95%)",
            "transport_failures: 30/5760 0.52% of D's minutes summed over 4 candidates (D is void above 5%)",
            "day_valid: yes",
            f"volume_window: {VOL_START} <= daily candle start < {VOL_END}",
            "== ETH-USD",                                   # ten transport failures: 1430 ok minutes, 99.31 %
            f"rows: 1440 (features computed 1430, error 10; {seen}", "transport_failures: 10",
            "ok_rows: 1430/1440 99.31%", "tick: 0.0001 (mode of 2860 per-side minimum steps, 2858 at the mode)",
            "fill1k_bps_median: 2.0000", *_h(1, 2, 3, 4, 4), *tail,
            "deep: 216/1430 15.10%", "normal: 1142/1430 79.86%", "thin: 72/1430 5.03%",
            "volume_usd_per_day: 60000000 (30 daily rows / 30)",
            "criterion_ok_rows: PASS", "criterion_volume: PASS", "criterion_occupancy: PASS",
            "criterion_stablecoin: PASS", "result: PASS",
            "== XRP-USD",
            f"rows: 1440 (features computed 1440, error 0; {seen}", "transport_failures: 0",
            "ok_rows: 1440/1440 100.00%", "tick: 0.0001 (mode of 2880 per-side minimum steps, 2878 at the mode)",
            "fill1k_bps_median: 2.0000", *_h(1, 2, 3, 4, 4), *tail,
            "deep: 216/1440 15.00%", "normal: 1152/1440 80.00%", "thin: 72/1440 5.00%",
            "volume_usd_per_day: 40000000 (30 daily rows / 30)",
            "criterion_ok_rows: PASS", "criterion_volume: FAIL 40000000 < 50000000", "criterion_occupancy: PASS",
            "criterion_stablecoin: PASS", "result: FAIL",
            "== DOGE-USD",
            f"rows: 1440 (features computed 1440, error 0; {seen}", "transport_failures: 0",
            "ok_rows: 1440/1440 100.00%", "tick: 0.0001 (mode of 2880 per-side minimum steps, 2878 at the mode)",
            "fill1k_bps_median: 2.0000", *_h(2, 2, 2, 2, 2),
            "a10: 2", "a90: 2", "rule: deep iff h < 2.5; thin iff h > 1.5 or fill1k_short; normal otherwise",
            "thin_fallback: yes (thin held 0/1440 0.00% under h > 2.5)",
            "deep: 1440/1440 100.00%", "normal: 0/1440 0.00%", "thin: 0/1440 0.00%",
            "volume_usd_per_day: 80000000 (30 daily rows / 30)",
            "criterion_ok_rows: PASS", "criterion_volume: PASS",
            "criterion_occupancy: FAIL deep 100.00%, normal 0.00%, thin 0.00% outside [3%, 90%]",
            "criterion_stablecoin: PASS", "result: FAIL",
            "== AVAX-USD",                                  # twenty: 1420 ok minutes, 98.61 % < 99 %
            f"rows: 1440 (features computed 1420, error 20; {seen}", "transport_failures: 20",
            "ok_rows: 1420/1440 98.61%", "tick: 0.0001 (mode of 2840 per-side minimum steps, 2838 at the mode)",
            "fill1k_bps_median: 2.0000", *_h(1, 2, 3, 4, 4), *tail,
            "deep: 216/1420 15.21%", "normal: 1132/1420 79.72%", "thin: 72/1420 5.07%",
            "volume_usd_per_day: 70000000 (30 daily rows / 30)",
            "criterion_ok_rows: FAIL 1420/1440 98.61% < 99%", "criterion_volume: PASS", "criterion_occupancy: PASS",
            "criterion_stablecoin: PASS", "result: FAIL",
            "chosen: ETH-USD (only 1 of 4 passed; v2 runs on what passed)",
        ])

    def test_a_partial_day_is_void_and_a_partial_candidate_fails(self):
        # the refuter's S1/S2: a candidate with 20 rows passed on 20/20. The share is of D's minutes with a row
        # for any candidate, and a day with rows in fewer than 95 % of its 1,440 minutes chooses nothing
        d = os.path.join(self.tmp, "probe")
        _write_dir(d, {"ETH-USD": PASSING[:1300], "ADA-USD": PASSING[:20]}, {"ETH-USD": 60e6, "ADA-USD": 60e6})
        code, out, _ = _summarize(d)
        lines = out.splitlines()
        self.assertEqual(code, 1)
        self.assertIn("minutes_with_rows: 1300/1440 90.28% (D is void below 95%)", lines)
        self.assertIn("day_valid: no (rows in 1300/1440 90.28% of D's minutes < 95%)", lines)
        ada = lines[lines.index("== ADA-USD"):]
        self.assertIn("ok_rows: 20/1300 1.54%", ada)
        self.assertIn("criterion_ok_rows: FAIL 20/1300 1.54% < 99%", ada)
        self.assertIn("result: FAIL", ada)
        self.assertIn("result: PASS", lines[lines.index("== ETH-USD"):lines.index("== ADA-USD")])
        self.assertEqual(lines[-1], VOID)                    # ETH passed its criteria; a void D chooses nothing
        self.assertTrue(out.isascii(), out)                  # printable under a C locale (make test-mode c-locale)
        _write_dir(d, {"ETH-USD": PASSING[:1368]}, {"ETH-USD": 60e6})   # 1368/1440 is exactly 95 %: D stands
        code, out, _ = _summarize(d)
        self.assertEqual(code, 0)
        self.assertIn("day_valid: yes", out.splitlines())
        self.assertEqual(out.splitlines()[-1], "chosen: ETH-USD (only 1 of 1 passed; v2 runs on what passed)")

    def test_transport_failures_above_five_percent_void_the_day(self):
        d = os.path.join(self.tmp, "probe")
        for n, void in ((144, False), (145, True)):          # of 1440 x 2 = 2880 candidate-minutes; 144 is 5.00 %
            _write_dir(d, {"ETH-USD": PASSING, "XRP-USD": PASSING}, {"ETH-USD": 60e6, "XRP-USD": 60e6},
                       errors={"XRP-USD": tuple(range(n))})
            code, out, _ = _summarize(d)
            lines = out.splitlines()
            self.assertEqual(code, 1 if void else 0, n)
            share = f"{n}/2880 {100.0 * n / 2880:.2f}%"
            self.assertIn(f"transport_failures: {share} of D's minutes summed over 2 candidates (D is void above 5%)",
                          lines)
            self.assertEqual(lines[lines.index("transport_failures: " + share + " of D's minutes summed over 2"
                                               " candidates (D is void above 5%)") + 1],
                             f"day_valid: no (transport failures {share} > 5%)" if void else "day_valid: yes")
            self.assertEqual(lines[-1], VOID if void else "chosen: ETH-USD (only 1 of 2 passed; v2 runs on what passed)")

    def test_what_is_an_ok_row_and_what_is_a_transport_failure(self):
        good = _prow(0, 1.0)
        quiet = {**_prow(1, None, ok=False), "error": "FeedError: candles: not contiguous inside the last 300",
                 "gets": dict(ALL_OK)}                     # the refuter's gap.py: three answers, no features
        no_ticker = {**_prow(2, 1.0), "trades_5m": -1, "gets": {**ALL_OK, "ticker": "http-503 /products/P/ticker"}}
        no_list = {**_prow(3, 1.0), "trades_5m": -1}        # the ticker answered with no trades list
        refused = _prow(4, None, ok=False)
        self.assertEqual([probe.ok_row(r) for r in (good, quiet, no_ticker, no_list, refused)],
                         [True, False, False, False, False])
        self.assertEqual([probe.transport_failed(r) for r in (good, quiet, no_ticker, no_list, refused)],
                         [False, False, True, False, True])

    def test_volume_must_be_d_s_thirty_days(self):
        d = os.path.join(self.tmp, "probe")
        _write_dir(d, {"ETH-USD": PASSING, "XRP-USD": PASSING}, {"ETH-USD": 60e6, "XRP-USD": 60e6})
        path = os.path.join(d, "volume.json")
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        v["products"]["XRP-USD"] = {"usd_per_day": 52e6, "rows": 5, "candles": []}      # the refuter's S2
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(v, fh)
        lines = _summarize(d)[1].splitlines()
        self.assertIn("criterion_volume: PASS", lines[lines.index("== ETH-USD"):lines.index("== XRP-USD")])
        self.assertIn("criterion_volume: FAIL 5 daily rows, not the 30 days ending with D", lines)
        self.assertEqual(lines[-1], "chosen: ETH-USD (only 1 of 2 passed; v2 runs on what passed)")
        v.update(day="2026-09-23", start="2026-08-25T00:00:00.000Z", end="2026-09-24T00:00:00.000Z")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(v, fh)
        lines = _summarize(d)[1].splitlines()
        wrong = ("criterion_volume: FAIL volume.json is for 2026-09-23 (2026-08-25T00:00:00.000Z to"
                 f" 2026-09-24T00:00:00.000Z), not 2026-09-24 ({VOL_START} to {VOL_END})")
        self.assertEqual([l for l in lines if l.startswith("criterion_volume")], [wrong, wrong])
        self.assertEqual(lines[-1], "chosen: none (only 0 of 2 passed; v2 runs on what passed)")

    def test_the_first_two_passing_in_candidate_order(self):
        d = os.path.join(self.tmp, "probe")
        order = {"ETH-USD": PASSING, "XRP-USD": PASSING, "DOGE-USD": FLAT, "AVAX-USD": PASSING, "LINK-USD": PASSING}
        _write_dir(d, order, {"ETH-USD": 1e6, "XRP-USD": 60e6, "DOGE-USD": 80e6, "AVAX-USD": 50e6, "LINK-USD": 9e9})
        code, out, _ = _summarize(d)
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-1], "chosen: XRP-USD AVAX-USD")   # 50e6 is on the line: it passes

    def test_tick_override_and_what_fails_without_inputs(self):
        d = os.path.join(self.tmp, "probe")
        _write_dir(d, {"ETH-USD": PASSING, "XRP-USD": PASSING}, {"ETH-USD": 60e6})
        os.remove(os.path.join(d, "XRP-USD.jsonl"))
        code, out, _ = _summarize(d, "--tick-override", "ETH-USD=0.0002")
        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertIn("tick: 0.0002 (--tick-override)", lines)
        self.assertIn("a10: 1", lines)                       # h halves: p10 0.5 rounds up to 1
        self.assertIn("a90: 2", lines)
        self.assertIn("rows: 0 (features computed 0, error 0; unparsable lines 0, rows outside the day 0,"
                      " repeated minutes 0)", lines)
        self.assertIn("criterion_ok_rows: FAIL 0/1440 0.00% < 99%", lines)
        self.assertIn("criterion_occupancy: FAIL no usable fill1k_bps in an ok row", lines)
        self.assertIn("criterion_volume: FAIL not in volume.json", lines)
        os.remove(os.path.join(d, "volume.json"))
        self.assertIn("criterion_volume: FAIL no volume.json", _summarize(d)[1].splitlines())
        self.assertEqual(_summarize(os.path.join(self.tmp, "absent"))[0], 2)
        os.remove(os.path.join(d, "run.json"))               # no run.json: no day to judge
        code, _, err = _summarize(d)
        self.assertEqual(code, 2)
        self.assertIn("no run.json", err)

    def test_run_json_names_are_checked_before_any_path_is_made(self):
        d = os.path.join(self.tmp, "probe")
        _write_dir(d, {"ETH-USD": PASSING}, {"ETH-USD": 60e6})
        for day, cands, why in (("2026-09-24", ["../ETH-USD"], "'../ETH-USD' is not a product name"),
                                ("2026-09-24", ["ETH-USD\n"], "is not a product name"),
                                ("2026-09-24", "ETH-USD", "'E' is not a product name"),
                                ("2026-09-24", ["ETH-USD", "ETH-USD"], "named twice"),
                                ("2026-09-24", [], "no candidates"),
                                ("2026-13-01", ["ETH-USD"], "is not a date"),
                                (20260924, ["ETH-USD"], "is not YYYY-MM-DD")):
            with open(os.path.join(d, "run.json"), "w", encoding="utf-8") as fh:
                json.dump({"day": day, "candidates": cands, "every": 60, "start_second": 30}, fh)
            code, out, err = _summarize(d)
            self.assertEqual((code, out), (2, ""), (day, cands))
            self.assertIn(why, err)
            self.assertIn("refusing", err)

    def test_a_stablecoin_fails(self):
        rows = [_prow(m, f) for m, f in enumerate(PASSING)]
        counts = {"bad": 0, "outside": 0, "repeated": 0}
        lines, passed = probe.summarize_product("USDT-USD", rows, counts, 1440, None, {"USDT-USD": {"usd_per_day": 1e9, "rows": 30}})
        self.assertFalse(passed)
        self.assertIn("criterion_stablecoin: FAIL USDT is a stablecoin", lines)
        lines, passed = probe.summarize_product("ETH-USD", rows, counts, 1440, None, {"ETH-USD": {"usd_per_day": 1e9, "rows": 30}})
        self.assertTrue(passed, lines)

    def test_criteria_constants_are_the_prereg_revision(self):
        self.assertEqual(probe.DEFAULT_CANDIDATES, ("ETH-USD", "XRP-USD", "DOGE-USD", "AVAX-USD", "LINK-USD", "ADA-USD"))
        self.assertEqual((probe.MIN_USD_PER_DAY, probe.VOLUME_DAYS, probe.CHOOSE), (50e6, 30, 2))
        self.assertEqual((probe.OK_ROWS_MIN_PCT, probe.DAY_MINUTES, probe.DAY_ROWS_MIN_PCT, probe.TRANSPORT_MAX_PCT),
                         (99, 1440, 95, 5))
        self.assertEqual((probe.OCC_LO_PCT, probe.OCC_HI_PCT), (probe.RULE.OCC_LO_PCT, probe.RULE.OCC_HI_PCT))
        self.assertEqual((probe.OCC_LO_PCT, probe.OCC_HI_PCT), (3, 90))


class Isolation(unittest.TestCase):
    def test_never_imports_the_send_path(self):
        code = ("import importlib.machinery, importlib.util, sys; p = sys.argv[1]; "
                "l = importlib.machinery.SourceFileLoader('probe', p); "
                "m = importlib.util.module_from_spec(importlib.util.spec_from_loader('probe', l)); l.exec_module(m); "
                "print(sorted(n for n in sys.modules if n == 'loop' or n.startswith('loop.')))")
        r = subprocess.run([sys.executable, "-I", "-B", "-c", code, TOOL], capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "['loop', 'loop.config', 'loop.feed', 'loop.state']")

    def test_source_names_no_send(self):
        with open(TOOL, encoding="utf-8") as fh:
            code = [l for l in fh.read().splitlines() if not l.lstrip().startswith("#")]
        for word in ("typesafe", "JEV_URL", "urlopen", "loop.jev", "loop.cycle", "api_key", "TYPESAFE"):
            self.assertEqual([l for l in code if word in l], [], word)
        self.assertEqual([l for l in code if re.match(r"\s*(from|import)\s", l) and re.search(r"\b(jev|cycle)\b", l)], [])


if __name__ == "__main__":
    unittest.main()

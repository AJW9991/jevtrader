"""bin/probe: the path guard's refusals, the pacer (never two requests less than 1 s apart, on a fake
clock), run over the recorded fixtures (one row per candidate, the row's shape, an error row, SIGTERM,
the day's end, the hourly line), volume's file, and summarize on a directory this test writes (one
product passing, one failing volume, one failing occupancy). Offline: feed._get is replaced and
urlopen raises, so no test opens a socket."""
import importlib.machinery, importlib.util, io, json, os, re, shutil, signal, subprocess, sys, tempfile, unittest
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
        self.fail = lambda url: None                        # a test sets it to raise on some URLs
        self.hook = lambda url: None                        # and this to act mid-request

    def fixture_get(self, clock):
        def get(url):
            self.calls.append((clock.now(), url))
            self.hook(url)
            why = self.fail(url)
            if why:
                raise feed.FeedError(why)
            if "/product_book?" in url:
                j = json.loads(BOOK)
                j["pricebook"]["product_id"] = _product(url)
                return j
            if "/candles?" in url:
                return json.loads(CANDLES)
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
            "trades_5m", "feed_age_s", "tick_est"}

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
        self.fail = lambda url: "http-503 /product_book" if "XRP-USD" in url and "product_book" in url else None
        code, err = self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1", "--every", "1",
                               "--candidates", "ETH-USD,XRP-USD,DOGE-USD"], clock)
        self.assertEqual(code, 0, err)
        (bad,) = self.rows(out, "XRP-USD")
        self.assertEqual(set(bad), {"tick_id", "ts_rx", "product", "ok", "error"})
        self.assertIs(bad["ok"], False)
        self.assertEqual(bad["error"], "FeedError: http-503 /product_book")
        self.assertIs(self.rows(out, "ETH-USD")[0]["ok"], True)
        self.assertIs(self.rows(out, "DOGE-USD")[0]["ok"], True)
        self.assertNotIn("Traceback", err)
        self.assertIn("XRP-USD ok 0 error 1", err)
        gaps = [b - a for (a, _), (b, _) in zip(self.calls, self.calls[1:])]
        self.assertEqual(len(self.calls), 7)                 # the failed book stops XRP's snapshot: 3 + 1 + 3
        self.assertTrue(all(g >= 1.0 for g in gaps), gaps)

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
        self.fail = lambda url: "http-503 /product_book"
        code, err = self.main(["run", "--day", DAY, "--out", out, "--candidates", "ETH-USD,XRP-USD"], clock)
        self.assertEqual(code, 0, err)
        self.assertEqual([r["tick_id"] for r in self.rows(out, "ETH-USD")], ["20260924T235800Z", "20260924T235900Z"])
        self.assertEqual([r["ts_rx"] for r in self.rows(out, "ETH-USD")],
                         ["2026-09-24T23:58:30.000Z", "2026-09-24T23:59:30.000Z"])
        self.assertIn("done (the day is over), 2 cycles; ETH-USD ok 0 error 2; XRP-USD ok 0 error 2", err)
        self.assertTrue(all(s <= 1.0 for s in clock.sleeps))  # naps of a second at most: SIGTERM is seen quickly

    def test_waits_for_its_day_and_refuses_one_that_is_over(self):
        clock, out = Clock(D0 - 15), os.path.join(self.tmp, "early")               # 2026-09-23T23:59:45Z
        self.fail = lambda url: "http-503 /product_book"
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
        self.fail = lambda url: "http-503 /product_book"
        code, err = self.main(["run", "--day", DAY, "--out", out, "--candidates", "ETH-USD,XRP-USD",
                               "--max-minutes", "3"], clock)
        self.assertEqual(code, 0, err)
        lines = err.splitlines()
        self.assertEqual(len(lines), 3, err)                # the start, one hourly line, the end
        self.assertEqual(lines[1], "2026-09-24T01:00:30.000Z probe: 2 cycles; ETH-USD ok 0 error 2; XRP-USD ok 0 error 2")

    def test_a_directory_of_another_run_is_refused(self):
        out = os.path.join(self.tmp, "out")
        self.fail = lambda url: "http-503 /product_book"
        self.assertEqual(self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1"], Clock(T_FIX))[0], 0)
        code, err = self.main(["run", "--day", "2026-09-25", "--out", out, "--max-minutes", "1"], Clock(T_FIX))
        self.assertEqual(code, 2)
        self.assertIn("another day", err)
        code, err = self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1", "--candidates", "ETH-USD"],
                              Clock(T_FIX))
        self.assertEqual(code, 2)
        self.assertEqual(self.main(["run", "--day", DAY, "--out", out, "--max-minutes", "1"], Clock(T_FIX))[0], 0)
        self.assertEqual(len(self.rows(out, "ETH-USD")), 2)  # the same day resumes, appending


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
        for cmd in (["run", "--day", DAY, "--max-minutes", "1"], ["volume"]):
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
        os.symlink(self.target, os.path.join(vol, "volume.json"))
        c = Clock(T_FIX)
        with mock.patch.object(feed, "_get", lambda url: {"candles": []}):
            code = probe.main(["volume", "--out", vol, "--candidates", "ETH-USD"], wall=c.now, mono=c.now,
                              sleep=c.sleep, err=io.StringIO())
        self.assertEqual(code, 3)
        self.assertTargetUntouched()


class Volume(Offline):
    def test_thirty_closed_days_per_candidate(self):
        clock, out = Clock(T_FIX), os.path.join(self.tmp, "out")
        days = [{"start": str(D0 - 86400 * k), "low": "1", "high": "3", "open": "2", "close": "2000",
                 "volume": "1000"} for k in range(0, 32)]  # k = 0 is the open day, k = 31 is before the window

        def get(url):
            self.calls.append((clock.now(), url))
            if "XRP-USD" in url:
                raise feed.FeedError("http-404 /products/XRP-USD/candles")
            return {"candles": days}
        err = io.StringIO()
        with mock.patch.object(feed, "_get", get):
            code = probe.main(["volume", "--out", out, "--candidates", "ETH-USD,XRP-USD"], wall=clock.now,
                              mono=clock.now, sleep=clock.sleep, err=err)
        self.assertEqual(code, 0, err.getvalue())
        with open(os.path.join(out, "volume.json"), encoding="utf-8") as fh:
            v = json.load(fh)
        self.assertEqual(v["products"]["ETH-USD"]["usd_per_day"], 2e6)       # 30 x 1000 x 2000 / 30
        self.assertEqual(v["products"]["ETH-USD"]["rows"], 30)
        self.assertEqual(v["products"]["ETH-USD"]["candles"], days)          # the raw candles, as sent
        self.assertEqual(v["products"]["XRP-USD"], {"error": "FeedError: http-404 /products/XRP-USD/candles"})
        self.assertEqual((v["start"], v["end"], v["days"]), ("2026-08-25T00:00:00.000Z", "2026-09-24T00:00:00.000Z", 30))
        self.assertEqual([u for _, u in self.calls], [
            f"{feed.BASE}/products/{p}/candles?start={D0 - 30 * 86400}&end={D0}&granularity=ONE_DAY"
            for p in ("ETH-USD", "XRP-USD")])
        self.assertEqual(self.calls[1][0] - self.calls[0][0], 1.0)


def _prow(m, fill, ok=True, day="20260924", tick=0.0001):
    t = f"{day}T{m // 60:02d}{m % 60:02d}00Z"
    if not ok:
        return {"tick_id": t, "ts_rx": "x", "product": "P", "ok": False, "error": "FeedError: http-503 /product_book"}
    return {"tick_id": t, "ts_rx": "x", "product": "P", "ok": True, "mid": 0.5, "spread_bps": 1.0, "fill1k_bps": fill,
            "fill1k_short": False, "vol5_usd": 1.0, "trades_5m": 10, "feed_age_s": 5.0,
            "tick_est": {"ask": tick, "bid": tick}}


# h = fill * 0.5 / (1e4 * 0.0001 / 2) = fill: 3 x 1, 13 x 2, 3 x 3, 1 x 4
PASSING = [1.0] * 3 + [2.0] * 13 + [3.0] * 3 + [4.0]


def _write_product(d, product, fills, extra=True):
    rows = [_prow(m, f) for m, f in enumerate(fills)]
    if extra:
        rows[5]["tick_est"] = {"ask": 0.0002, "bid": 0.0002}        # the mode still wins
        rows.append(_prow(30, None, ok=False))                       # an error row: 20/21 GETs answered
        rows.append(_prow(0, 9.0, day="20260925"))                   # the next day: not read
    with open(os.path.join(d, f"{product}.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
        if extra:
            fh.write('{"tick_id": "20260924T0031')                      # torn


def _write_dir(d, products, volumes):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "run.json"), "w", encoding="utf-8") as fh:
        json.dump({"day": DAY, "candidates": list(products), "every": 60, "start_second": 30}, fh)
    for p, fills in products.items():
        _write_product(d, p, fills)
    with open(os.path.join(d, "volume.json"), "w", encoding="utf-8") as fh:
        json.dump({"products": {p: {"usd_per_day": v, "rows": 30, "candles": []} for p, v in volumes.items()}}, fh)


def _summarize(d, *extra):
    out, err = io.StringIO(), io.StringIO()
    code = probe.main(["summarize", d, *extra], out=out, err=err)
    return code, out.getvalue(), err.getvalue()


class Summarize(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())

    def test_one_passing_one_failing_volume_one_failing_occupancy(self):
        d = os.path.join(self.tmp, "probe")
        _write_dir(d, {"ETH-USD": PASSING, "XRP-USD": PASSING, "DOGE-USD": [2.0] * 20},
                   {"ETH-USD": 40e6, "XRP-USD": 60e6, "DOGE-USD": 80e6})
        code, out, err = _summarize(d)
        self.assertEqual(code, 0, err)
        tail = ["h_p10: 1.0000", "h_p50: 2.0000", "h_p90: 3.0000", "h_p99: 4.0000", "h_max: 4.0000",
                "a10: 1", "a90: 3", "rule: deep iff h < 1.5; thin iff h > 3.5 or fill1k_short; normal otherwise",
                "thin_fallback: no", "deep: 3/20 15.00%", "normal: 16/20 80.00%", "thin: 1/20 5.00%"]
        head = ["rows: 21 (ok 20, error 1; unparsable lines 1, rows outside the day 1)",
                "get_success: 20/21 95.24%",
                "tick: 0.0001 (mode of 40 per-side minimum steps, 38 at the mode)",
                "fill1k_bps_median: 2.0000"]
        self.assertEqual(out.splitlines(), [
            f"dir: {d}",
            "day: 2026-09-24",
            "candidates: ETH-USD XRP-USD DOGE-USD",
            "criteria: get_success >= 95% of the day's rows; volume >= 50000000 USD/day over 30 days;"
            " each liq word in [3%, 90%] under the h-rule; not a stablecoin",
            "== ETH-USD", *head, *tail,
            "volume_usd_per_day: 40000000 (30 daily rows / 30)",
            "criterion_gets: PASS", "criterion_volume: FAIL 40000000 < 50000000", "criterion_occupancy: PASS",
            "criterion_stablecoin: PASS", "result: FAIL",
            "== XRP-USD", *head, *tail,
            "volume_usd_per_day: 60000000 (30 daily rows / 30)",
            "criterion_gets: PASS", "criterion_volume: PASS", "criterion_occupancy: PASS",
            "criterion_stablecoin: PASS", "result: PASS",
            "== DOGE-USD", *head[:3], "fill1k_bps_median: 2.0000",
            "h_p10: 2.0000", "h_p50: 2.0000", "h_p90: 2.0000", "h_p99: 2.0000", "h_max: 2.0000",
            "a10: 2", "a90: 2", "rule: deep iff h < 2.5; thin iff h > 1.5 or fill1k_short; normal otherwise",
            "thin_fallback: yes (thin held 0/20 0.00% under h > 2.5)",
            "deep: 20/20 100.00%", "normal: 0/20 0.00%", "thin: 0/20 0.00%",
            "volume_usd_per_day: 80000000 (30 daily rows / 30)",
            "criterion_gets: PASS", "criterion_volume: PASS",
            "criterion_occupancy: FAIL deep 100.00%, normal 0.00%, thin 0.00% outside [3%, 90%]",
            "criterion_stablecoin: PASS", "result: FAIL",
            "chosen: XRP-USD (only 1 of 3 passed; v2 runs on what passed)",
        ])

    def test_the_first_two_passing_in_candidate_order(self):
        d = os.path.join(self.tmp, "probe")
        order = {"ETH-USD": PASSING, "XRP-USD": PASSING, "DOGE-USD": [2.0] * 20, "AVAX-USD": PASSING, "LINK-USD": PASSING}
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
        self.assertIn("rows: 0 (ok 0, error 0; unparsable lines 0, rows outside the day 0)", lines)
        self.assertIn("criterion_gets: FAIL 0/0 < 95%", lines)
        self.assertIn("criterion_occupancy: FAIL no usable fill1k_bps row", lines)
        self.assertIn("criterion_volume: FAIL not in volume.json", lines)
        os.remove(os.path.join(d, "volume.json"))
        self.assertIn("criterion_volume: FAIL no volume.json", _summarize(d)[1].splitlines())
        self.assertEqual(_summarize(os.path.join(self.tmp, "absent"))[0], 2)

    def test_a_stablecoin_fails(self):
        rows = [_prow(m, f) for m, f in enumerate(PASSING)]
        lines, passed = probe.summarize_product("USDT-USD", rows, 0, 0, None, {"USDT-USD": {"usd_per_day": 1e9}})
        self.assertFalse(passed)
        self.assertIn("criterion_stablecoin: FAIL USDT is a stablecoin", lines)
        lines, passed = probe.summarize_product("ETH-USD", rows, 0, 0, None, {"ETH-USD": {"usd_per_day": 1e9}})
        self.assertTrue(passed, lines)

    def test_criteria_constants_are_the_prereg_revision(self):
        self.assertEqual(probe.DEFAULT_CANDIDATES, ("ETH-USD", "XRP-USD", "DOGE-USD", "AVAX-USD", "LINK-USD", "ADA-USD"))
        self.assertEqual((probe.MIN_USD_PER_DAY, probe.VOLUME_DAYS, probe.CHOOSE), (50e6, 30, 2))
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

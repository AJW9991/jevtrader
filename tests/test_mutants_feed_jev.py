"""loop.feed and loop.jev, offline: rules the rest of the suite left unchecked, found by a
stdlib mutation run over both modules at 0f1d0dc (2026-09-28). Each test holds one documented
rule, named in the comment above it.

The same walls as test_feed and test_jev: urllib.request.urlopen is mocked wherever a request
could start, config.JEV_URL points at 127.0.0.1:9 (discard), config.SENDS and config.PROTOCOL
point into a temp dir, the key is a made-up string in the environment, time.sleep is mocked.
Nothing here reads prompts/ or data/."""
import email.message, hashlib, http.client, importlib.util, io, json, os, tempfile, unittest
import urllib.error, urllib.request
from unittest import mock

from loop import config, feed, jev

FIX = os.path.join(config.REPO, "fixtures")


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return json.load(fh)


META = _load("meta.json")
NOW = float(META["ts_rx_epoch"])                 # 2026-09-24T02:28:49Z; the newest closed minute is 49 s old
BOOK, CANDLES, TRADES = _load("book.json"), _load("candles.json"), _load("trades.json")
RAW = CANDLES["candles"]                         # newest first: RAW[0] open, RAW[1..300] the window, RAW[301..] spare
BIDS = [{"price": "100", "size": "1"}]
ASKS = [{"price": "100.01", "size": "1"}]


def _book(bids=BIDS, asks=ASKS, **extra):
    pb = {"product_id": "SOL-USD", "time": "t", "bids": bids, "asks": asks}
    pb.update(extra)
    return {"pricebook": pb}


def _assemble(candles=RAW, trades=TRADES, now=NOW):
    return feed.assemble("SOL-USD", now, BOOK, {"candles": candles}, trades, {"calls": 3, "ms": 0})


def _venue(req, timeout=None):
    """urlopen stand-in for the three public GETs: the recorded fixture per endpoint."""
    url = req.full_url
    body = BOOK if "/product_book" in url else CANDLES if "/candles" in url else TRADES
    return io.BytesIO(json.dumps(body).encode())


class FeedTest(unittest.TestCase):

    # SPEC §3 "10 s timeout each" and §14 TIMEOUT_S = 10: every GET is bounded by the frozen 10 s
    def test_every_venue_get_waits_ten_seconds_at_most(self):
        seen = []
        def fake(req, timeout=None):
            seen.append(timeout)
            return _venue(req)
        with mock.patch("urllib.request.urlopen", fake):
            feed.snapshot(config.PRODUCT, now=NOW)
        self.assertEqual(seen, [10, 10, 10])

    # CONTRACT §2 Snapshot `http: {"calls", "ms"}`: ms is the time the three GETs took
    def test_http_ms_is_the_time_spent_in_the_gets(self):
        clock = [500.0]
        def fake(req, timeout=None):
            clock[0] += 0.125                                          # exact in binary: 3 x 125 ms
            return _venue(req)
        with mock.patch("urllib.request.urlopen", fake), \
                mock.patch("time.monotonic", side_effect=lambda: clock[0]):
            s = feed.snapshot(config.PRODUCT, now=NOW)
        self.assertEqual(s["http"], {"calls": 3, "ms": 375})

    # module docstring and CONTRACT §2: any parse failure is FeedError (absence "feed"), never a bare TypeError
    def test_a_null_or_array_level_is_a_feed_error(self):
        for bad in ([{"price": None, "size": "1"}], [{"price": "100", "size": None}], [["100", "1"]]):
            with self.subTest(level=bad), self.assertRaises(feed.FeedError):
                feed.parse_levels(_book(bids=bad), "SOL-USD")
        closed = int(NOW) // 60 * 60 - 60
        with self.assertRaises(feed.FeedError):
            feed.parse_candles({"candles": [{"start": str(closed), "open": None, "high": "2", "low": "1",
                                             "close": "2", "volume": "0"}]}, NOW)

    # SPEC §3: a level that is not a finite positive price AND size refuses the book
    def test_an_infinite_level_size_refuses_the_book(self):
        for bids, asks in (([{"price": "100", "size": "inf"}], ASKS),
                           (BIDS, ASKS + [{"price": "100.02", "size": "inf"}])):
            with self.subTest(bids=bids, asks=asks), self.assertRaises(feed.FeedError):
                feed.parse_levels(_book(bids, asks), "SOL-USD")

    # SPEC §3: "finite positive price and size" is the whole rule, so a price under $1 is a level
    def test_a_positive_price_under_one_dollar_is_a_valid_level(self):
        got = feed.parse_levels(_book([{"price": "0.5", "size": "1"}], [{"price": "0.6", "size": "2"}]), "SOL-USD")
        self.assertEqual(got, ([[0.5, 1.0]], [[0.6, 2.0]], "t"))

    # CONTRACT §2: any parse failure is FeedError; a null or non-object book body is one
    def test_a_null_or_non_object_book_body_is_a_feed_error(self):
        for bad in (None, 5, "book", {"pricebook": None}, {"pricebook": []},
                    _book(bids=None), _book(asks=None)):
            with self.subTest(body=bad), self.assertRaises(feed.FeedError):
                feed.parse_levels(bad, "SOL-USD")

    # CONTRACT §2 `FeedError(str)`, feed.FeedError docstring ("what failed and on which endpoint")
    def test_a_book_side_that_is_not_a_list_is_refused_as_such(self):
        for bids, asks in (("x", ASKS), (BIDS, "x")):
            with self.subTest(bids=bids, asks=asks):
                with self.assertRaisesRegex(feed.FeedError, "levels are not lists"):
                    feed.parse_levels(_book(bids, asks), "SOL-USD")

    # CONTRACT §2 / SPEC §2: book_time is the venue's ISO time or null, never an empty or numeric value
    def test_a_falsy_venue_book_time_is_null(self):
        for t in ("", 0, False):
            with self.subTest(time=t):
                self.assertIsNone(feed.parse_levels(_book(time=t), "SOL-USD")[2])

    # CONTRACT §2: any parse failure is FeedError; a null start or an array candle is one
    def test_a_null_or_array_candle_is_a_feed_error(self):
        for bad in ([{"start": None}], [["1790216820", "1", "2", "1", "2", "0"]], [None]):
            with self.subTest(candles=bad), self.assertRaises(feed.FeedError):
                feed.parse_candles({"candles": bad}, NOW)

    # SPEC §3: a candle is CLOSED iff start + 60 <= ts_rx, so the open minute stays out at :59.5
    def test_the_open_minute_is_dropped_late_in_its_minute(self):
        b = 1790216880                                                  # a minute boundary
        row = {"low": "1", "high": "2", "open": "1", "close": "2", "volume": "0"}
        raw = [dict(row, start=str(b - 60 * i)) for i in range(302)]    # i=0 opened 59.5 s ago
        rows = feed.parse_candles({"candles": raw}, b + 59.5)
        self.assertEqual(len(rows), 301)
        self.assertEqual(rows[-1]["start"], b - 60)

    # CONTRACT §2: only a WINDOW candle that is not finite and positive refuses the set
    def test_garbage_in_the_spare_candle_just_before_the_window_costs_nothing(self):
        bad = [dict(c) for c in RAW]
        bad[config.WINDOW_MIN + 1]["close"] = "0"                      # RAW[301]: the newest spare row
        s = _assemble(bad)
        self.assertEqual(len(s["candles"]), META["expect"]["candles_closed"])
        self.assertEqual(s["feed_age_s"], META["expect"]["feed_age_s"])

    # SPEC §3 contiguity: ALL of the last WINDOW_MIN closed candles are 60 s apart, the oldest pair too
    def test_a_missing_minute_at_the_windows_oldest_edge_is_refused(self):
        i = config.WINDOW_MIN                                           # RAW[300]: the window's oldest minute
        with self.assertRaisesRegex(feed.FeedError, "not contiguous"):
            _assemble(RAW[:i] + RAW[i + 1:])

    # SPEC §3: "A gap in the 49 spare rows before the window is never read and costs nothing"
    def test_a_gap_just_before_the_window_costs_nothing(self):
        i = config.WINDOW_MIN + 1                                       # RAW[301]: the newest spare minute
        s = _assemble(RAW[:i] + RAW[i + 1:])
        self.assertEqual(len(s["candles"]), META["expect"]["candles_closed"] - 1)
        self.assertEqual(s["feed_age_s"], META["expect"]["feed_age_s"])

    # SPEC §3: an unparseable ticker yields trades_5m = -1 "and the tick goes on"
    def test_a_trade_with_a_null_or_numeric_time_leaves_the_tick_whole(self):
        for trades in ({"trades": [{"time": None}]}, {"trades": [{"time": NOW}]}, {"trades": [None]}):
            with self.subTest(trades=trades):
                s = _assemble(trades=trades)
                self.assertEqual(s["trades_5m"], -1)
                self.assertEqual(len(s["candles"]), META["expect"]["candles_closed"])

    # SPEC §2 (ts_rx in ms) and §3 (feed_age_s = ts_rx - (newest start + 60)): kept to the millisecond
    def test_feed_age_is_kept_to_the_millisecond(self):
        s = _assemble(now=NOW + 0.1234)
        self.assertEqual(s["ts_rx"], "2026-09-24T02:28:49.123Z")
        self.assertEqual(s["feed_age_s"], 49.123)


KEY = "unit-test-key-not-real-0000"
URL = "http://127.0.0.1:9/v1/systemone"
STATE = "SOL: liquidity thin, flow quiet, trend flat, vol calm"
Q = {"a_action": {"type": "choice", "instructions": "Decide.",
                  "criteria": {"buy": "b", "sell": "s", "hold": "h"}},
     "skip": {"type": "noul", "instructions": "Hostile.", "criteria": {"yes": "y", "no": "n"}}}
GOOD = {"model": config.MODEL, "usage": {"input_tokens": 123, "output_tokens": 7},
        "answers": {"a_action": {"choice": "hold", "probabilities": {"buy": 0.1, "sell": 0.1, "hold": 0.8},
                                 "confidence": 0.8},
                    "skip": {"noul": 0.02}}}
KPATH = "env:TYPESAFE_API_KEY_LOOP"


class _Resp:
    """What urlopen yields: a context manager whose read() returns the body or raises."""
    def __init__(self, doc=None, raw=None, exc=None):
        self._b = raw if raw is not None else json.dumps(doc).encode()
        self._exc = exc
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def read(self):
        if self._exc is not None:
            raise self._exc
        return self._b


def _with(**changes):
    d = json.loads(json.dumps(GOOD))
    for path, v in changes.items():
        *head, last = path.split("__")
        tgt = d
        for k in head:
            tgt = tgt[k]
        tgt[last] = v
    return _Resp(d)


class JevTest(unittest.TestCase):

    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.sends = os.path.join(self.tmp, "data", "sends.tsv")
        self.enterContext(mock.patch.object(config, "SENDS", self.sends))
        self.enterContext(mock.patch.object(config, "JEV_URL", URL))
        self.enterContext(mock.patch.dict(os.environ, {"TYPESAFE_API_KEY_LOOP": KEY}))
        self.protocol = os.path.join(self.tmp, "PROTOCOL.md")
        with open(self.protocol, "w", encoding="utf-8") as fh:
            fh.write("# PROTOCOL\n\nIn force from: `2026-09-24`  Signed: `test`\n")
        self.enterContext(mock.patch.object(config, "PROTOCOL", self.protocol))
        self.sleeps = []
        self.enterContext(mock.patch("time.sleep", side_effect=self.sleeps.append))
        self.urlopen = self.enterContext(mock.patch("urllib.request.urlopen"))
        self.urlopen.return_value = _Resp(GOOD)
        self.errors = []

    def tearDown(self):
        for e in self.errors:
            e.close()

    def _http(self, code):
        e = urllib.error.HTTPError(URL, code, "status text", email.message.Message(), io.BytesIO(b""))
        self.errors.append(e)
        return e

    def _parse_error(self, resp):
        self.urlopen.return_value = resp
        with self.assertRaises(jev.JevError) as cm:
            jev.ask(STATE, Q)
        self.assertEqual((cm.exception.kind, cm.exception.key_path), ("parse", KPATH))
        self.assertEqual(self.urlopen.call_count, 1)
        self.urlopen.reset_mock()
        return cm.exception

    # SPEC §12: ONE retry after RETRY_S on a transport failure; JevError: a non-timeout transport failure is `timeout`
    def test_a_reply_cut_off_mid_body_is_a_transport_failure_retried_once(self):
        cut = http.client.IncompleteRead(b'{"answers": {', 400)
        self.urlopen.side_effect = [_Resp(exc=cut), _Resp(GOOD)]
        self.assertEqual(jev.ask(STATE, Q)["answers"], GOOD["answers"])
        self.assertEqual(self.sleeps, [1.0])
        self.assertEqual(self.urlopen.call_count, 2)
        self.urlopen.reset_mock(); self.sleeps.clear()
        self.urlopen.side_effect = [_Resp(exc=cut), http.client.BadStatusLine("garbage")]
        with self.assertRaises(jev.JevError) as cm:
            jev.ask(STATE, Q)
        self.assertEqual((cm.exception.kind, cm.exception.key_path), ("timeout", KPATH))
        self.assertIn("BadStatusLine", cm.exception.detail)

    # CONTRACT §2 `raises JevError(kind, detail)`; cycle prints `jev: {e}` as "kind and detail"
    def test_a_jev_error_reads_as_its_kind_and_detail(self):
        self.assertEqual(str(jev.JevError("http-4xx", "401 Unauthorized", 401, KPATH)), "http-4xx: 401 Unauthorized")
        self.assertEqual(str(jev.JevError("parse")), "parse")

    # CONTRACT §2 (a 3xx is never followed): jev installs its redirect-refusing opener at import
    def test_importing_jev_installs_its_redirect_refusing_opener(self):
        self.addCleanup(urllib.request.install_opener, urllib.request._opener)
        urllib.request.install_opener(None)                             # the stock state before any import
        spec = importlib.util.spec_from_file_location("loop._jev_fresh_import", jev.__file__)
        fresh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fresh)                                  # a fresh import, loop.jev left as it is
        self.assertIs(urllib.request._opener, fresh._OPENER)
        redirects = [h for h in fresh._OPENER.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
        self.assertEqual([type(h) for h in redirects], [fresh._NoAuthRedirect])

    # SPEC §12 / CONTRACT §2: one row per attempt fsync'd to sends.tsv before the request
    def test_the_ledger_fsync_finds_the_row_already_in_the_file(self):
        at_fsync, real = [], os.fsync
        def fsync(fd):
            with open(self.sends, encoding="utf-8") as fh:
                at_fsync.append(fh.read())
            return real(fd)
        with mock.patch("os.fsync", side_effect=fsync):
            sha12 = jev.ledger(STATE, Q)
        self.assertEqual(sha12, hashlib.sha256(STATE.encode()).hexdigest()[:12])
        self.assertEqual(len(at_fsync), 1)
        self.assertTrue(at_fsync[0].startswith(jev.HEADER), at_fsync[0])
        self.assertTrue(at_fsync[0].endswith("\t" + sha12 + "\t-\n"), at_fsync[0])

    # SPEC §12 answer shape: `answers` is an object keyed by qid; the parse detail names what was wrong
    def test_a_non_object_answers_field_is_parse_naming_it(self):
        e = self._parse_error(_with(answers=[GOOD["answers"]["a_action"], GOOD["answers"]["skip"]]))
        self.assertIn("answers is list", e.detail)

    # SPEC §12 answer shape: choice -> {"choice","probabilities","confidence"}, noul -> {"noul"}, as objects
    def test_a_list_or_string_answer_is_parse_even_holding_the_field_names(self):
        self._parse_error(_with(answers__a_action=["choice", "probabilities", "confidence"]))
        self._parse_error(_with(answers__skip="noul"))

    # CONTRACT §2 kinds, jev._parse docstring: a malformed reply is JevError("parse"), never "unexpected"
    def test_a_non_object_usage_is_parse(self):
        for usage in ("n/a", [1], 5):
            with self.subTest(usage=usage):
                self._parse_error(_with(usage=usage))

    # CONTRACT §2 kinds, jev._parse docstring and comment: a pathologically nested body is "parse"
    def test_a_pathologically_nested_reply_is_parse(self):
        self._parse_error(_Resp(raw=b'{"answers": ' + b"[" * 100000 + b"]" * 100000 + b"}"))

    # jev.signed docstring ("True only when ..."; an unreadable file is unsigned): a plain False
    def test_an_unreadable_protocol_is_a_plain_false(self):
        with mock.patch.object(config, "PROTOCOL", os.path.join(self.tmp, "absent.md")):
            self.assertIs(jev.signed(), False)

    # CONTRACT §2 / SPEC §12: never a retry on a 4xx other than 429; 499 is a 4xx
    def test_a_499_is_http_4xx_without_retry(self):
        self.urlopen.side_effect = [self._http(499), _Resp(GOOD)]
        with self.assertRaises(jev.JevError) as cm:
            jev.ask(STATE, Q)
        self.assertEqual((cm.exception.kind, cm.exception.status), ("http-4xx", 499))
        self.assertEqual(self.urlopen.call_count, 1)
        self.assertEqual(self.sleeps, [])

    # SPEC §2 jev.latency_ms, jev.ask docstring: "the answering request alone; the wait ... is ours"
    def test_latency_ms_is_the_answering_request_alone(self):
        clock = [1000.0]
        def after(secs, result):
            def call(req, timeout=None):
                clock[0] += secs                                        # binary-exact steps: no rounding
                if isinstance(result, Exception):
                    raise result
                return result
            return call
        def sleep(s):
            self.sleeps.append(s)
            clock[0] += s
        calls = []
        self.urlopen.side_effect = lambda req, timeout=None: calls.pop(0)(req, timeout)
        with mock.patch("time.monotonic", side_effect=lambda: clock[0]), mock.patch("time.sleep", side_effect=sleep):
            calls[:] = [after(0.25, _Resp(GOOD))]
            self.assertEqual(jev.ask(STATE, Q)["latency_ms"], 250)
            calls[:] = [after(0.5, self._http(503)), after(0.125, _Resp(GOOD))]
            self.assertEqual(jev.ask(STATE, Q)["latency_ms"], 125)
        self.assertEqual(self.sleeps, [1.0])


if __name__ == "__main__":
    unittest.main()

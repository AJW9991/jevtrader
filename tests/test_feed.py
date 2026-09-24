"""Offline tests for loop.feed against fixtures/ (one real set, 2026-09-24T02:28:49Z).

urllib.request.urlopen is mocked in every path that reaches snapshot(); a test that
opens a socket is a failing test. Numbers are pinned in fixtures/meta.json `expect`.
"""
import datetime as dt
import io
import json
import os
import re
import time
import unittest
import urllib.error
from unittest import mock

from loop import config, feed

FIX = os.path.join(config.REPO, "fixtures")


def load(name):
    with open(os.path.join(FIX, name)) as fh:
        return json.load(fh)


META = load("meta.json")
NOW = float(META["ts_rx_epoch"])
EXP = META["expect"]
BOOK, CANDLES, TRADES = load("book.json"), load("candles.json"), load("trades.json")
KEYS = {"ts_rx", "product", "bid", "bid_size", "ask", "ask_size", "book_time",
        "candles", "trades_5m", "feed_age_s", "http"}                    # CONTRACT §2, exactly


def http_error(code):
    # an explicit empty body: fp=None makes 3.14 allocate a tempfile and warn on cleanup
    return urllib.error.HTTPError("https://api.coinbase.com/x", code, "boom", {}, io.BytesIO(b""))


class Fake:
    """urlopen stand-in: one payload per endpoint (dict -> JSON, bytes raw, Exception
    raised), and every URL asked, in order."""

    def __init__(self, book=BOOK, candles=CANDLES, trades=TRADES):
        self.by = {"/product_book": book, "/candles": candles, "/ticker": trades}
        self.urls = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.urls.append(url)
        for k, v in self.by.items():
            if k in url:
                if isinstance(v, Exception):
                    raise v
                return io.BytesIO(v if isinstance(v, bytes) else json.dumps(v).encode())
        raise AssertionError("unexpected URL " + url)


def snap(fake=None, now=NOW):
    fake = fake or Fake()
    with mock.patch("urllib.request.urlopen", fake):
        return feed.snapshot(config.PRODUCT, now=now), fake


class TestSnapshot(unittest.TestCase):

    def test_exact_keys_and_types(self):
        s, _ = snap()
        self.assertEqual(set(s), KEYS)
        self.assertEqual(s["product"], "SOL-USD")
        for k in ("bid", "bid_size", "ask", "ask_size", "feed_age_s"):
            self.assertIsInstance(s[k], float, k)
        self.assertIsInstance(s["trades_5m"], int)
        self.assertEqual(set(s["http"]), {"calls", "ms"})
        self.assertEqual(s["http"]["calls"], 3)
        self.assertIsInstance(s["http"]["ms"], int)
        self.assertGreaterEqual(s["http"]["ms"], 0)
        self.assertEqual((s["bid"], s["bid_size"], s["ask"], s["ask_size"], s["book_time"]),
                         (EXP["bid"], EXP["bid_size"], EXP["ask"], EXP["ask_size"], EXP["book_time"]))
        self.assertLess(s["bid"], s["ask"])

    def test_ts_rx_is_iso_utc_ms(self):
        s, _ = snap()
        self.assertRegex(s["ts_rx"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertEqual(s["ts_rx"], "2026-09-24T02:28:49.000Z")
        s2, _ = snap(now=NOW + 0.1234)
        self.assertEqual(s2["ts_rx"], "2026-09-24T02:28:49.123Z")

    def test_ts_rx_defaults_to_this_clock(self):
        # now=None is the live path: ts_rx is the wall clock at ENTRY (the decision timestamp).
        # Against the live clock the recorded fixture is stale by construction, so the
        # staleness bound is lifted HERE only; test_a_lagging_candle_set_is_refused pins it.
        t0 = time.time()
        with mock.patch.object(feed, "MAX_FEED_AGE_S", float("inf")):
            s, _ = snap(now=None)
        got = dt.datetime.strptime(s["ts_rx"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.timezone.utc)
        self.assertLess(abs(got.timestamp() - t0), 5.0)
        self.assertEqual(len(s["candles"]), EXP["candles_raw"])       # all 350 are closed by now

    def test_candles_oldest_first_closed_and_enough(self):
        s, _ = snap()
        c = s["candles"]
        self.assertEqual(len(c), EXP["candles_closed"])
        self.assertGreaterEqual(len(c), config.WINDOW_MIN)
        starts = [r["start"] for r in c]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual({b - a for a, b in zip(starts, starts[1:])}, {60})     # this set has no gap
        self.assertEqual(starts[0], EXP["oldest_start"])
        self.assertEqual(starts[-1], EXP["newest_closed_start"])
        self.assertNotIn(EXP["open_minute_start"], starts)                       # open minute dropped
        self.assertTrue(all(r["start"] + 60 <= NOW for r in c))
        for r in c:
            self.assertEqual(set(r), {"start", "open", "high", "low", "close", "volume"})
            self.assertIsInstance(r["start"], int)
            for k in ("open", "high", "low", "close", "volume"):
                self.assertIsInstance(r[k], float, k)
            self.assertLessEqual(r["low"], min(r["open"], r["close"]))
            self.assertGreaterEqual(r["high"], max(r["open"], r["close"]))

    def test_closed_boundary(self):
        # closed iff start + 60 <= now: equality is closed; one second short is open
        now = 1790216880.0                                              # a minute boundary
        row = {"low": "1", "high": "2", "open": "1", "close": "2", "volume": "0"}
        raw = [dict(row, start=str(int(now) - 60 * i)) for i in range(302)]   # i=0 is the open minute
        raw.append(dict(row, start=str(int(now) - 30)))                        # misaligned, still open
        raw.append(dict(row, start=str(int(now) - 61)))                        # closed 1 s ago
        rows = feed.parse_candles({"candles": raw}, now)
        self.assertEqual(len(rows), 302)
        self.assertEqual(rows[-1]["start"], int(now) - 60)
        self.assertEqual(rows[-2]["start"], int(now) - 61)
        self.assertEqual(rows[0]["start"], int(now) - 60 * 301)

    def test_too_few_candles_raises(self):
        # 300 raw rows include the open minute -> 299 closed -> below WINDOW_MIN
        f = Fake(candles={"candles": CANDLES["candles"][:config.WINDOW_MIN]})
        with mock.patch("urllib.request.urlopen", f):
            with self.assertRaises(feed.FeedError) as cm:
                feed.snapshot(config.PRODUCT, now=NOW)
        self.assertIn(str(config.WINDOW_MIN - 1), str(cm.exception))
        s, _ = snap(Fake(candles={"candles": CANDLES["candles"][:config.WINDOW_MIN + 1]}))
        self.assertEqual(len(s["candles"]), config.WINDOW_MIN)

    def test_gap_inside_the_window_is_a_feed_error(self):
        # Coinbase omits a minute with no trades. One missing minute inside the last
        # WINDOW_MIN closed rows would make "15 candles ago" 16 minutes ago: refused, not
        # computed. raw[0] is the open minute, so raw[1..300] are the window.
        raw = CANDLES["candles"]
        for i in (1, 2, 150, config.WINDOW_MIN - 1):                   # the newest closed row is not a gap
            gapped = {"candles": raw[:i] + raw[i + 1:]}
            if i == 1:                                                  # a contiguous window ending a minute early
                s = feed.assemble("SOL-USD", NOW, BOOK, gapped, TRADES, {"calls": 3, "ms": 0})
                self.assertEqual(s["feed_age_s"], EXP["feed_age_s"] + 60)
                continue
            with self.assertRaises(feed.FeedError) as cm:
                feed.assemble("SOL-USD", NOW, BOOK, gapped, TRADES, {"calls": 3, "ms": 0})
            self.assertIn("not contiguous", str(cm.exception))
        # a gap in the spare rows before the window is never read, so it costs nothing
        s = feed.assemble("SOL-USD", NOW, BOOK, {"candles": raw[:340] + raw[341:]}, TRADES, {"calls": 3, "ms": 0})
        self.assertEqual(len(s["candles"]), EXP["candles_closed"] - 1)
        # a duplicated minute is not contiguous either (0 s apart)
        dup = {"candles": raw[:10] + [raw[10]] + raw[10:]}
        with self.assertRaises(feed.FeedError):
            feed.assemble("SOL-USD", NOW, BOOK, dup, TRADES, {"calls": 3, "ms": 0})
        # and through snapshot() it is the same FeedError, which cycle.py logs as absence "feed"
        f = Fake(candles={"candles": raw[:150] + raw[151:]})
        with mock.patch("urllib.request.urlopen", f):
            with self.assertRaises(feed.FeedError):
                feed.snapshot(config.PRODUCT, now=NOW)

    def test_trades_5m_matches_hand_count(self):
        s, _ = snap()
        hand = sum(1 for t in TRADES["trades"]
                   if dt.datetime.fromisoformat(t["time"]).timestamp() >= NOW - 300)
        self.assertEqual(s["trades_5m"], hand)
        self.assertEqual(hand, EXP["trades_5m"])

    def test_trades_window_edge_and_shapes(self):
        def one(ts):
            iso = dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat().replace("+00:00", "Z")
            return {"trades": [{"time": iso}]}
        self.assertEqual(feed.parse_trades(one(NOW - 300), NOW), 1)        # exactly 300 s old counts
        self.assertEqual(feed.parse_trades(one(NOW - 300.001), NOW), 0)
        self.assertEqual(feed.parse_trades(one(NOW + 1), NOW), 1)          # later than ts_rx still counts
        self.assertEqual(feed.parse_trades({"trades": []}, NOW), 0)
        self.assertEqual(feed.parse_trades({"best_bid": "1"}, NOW), -1)    # no list -> -1
        self.assertEqual(feed.parse_trades([], NOW), -1)
        with self.assertRaises(feed.FeedError):
            feed.parse_trades({"trades": [{"time": "yesterday"}]}, NOW)
        # a bare ISO string is UTC, not this Mac's zone; 7 fractional digits parse too
        self.assertEqual(feed._ep("2026-09-24T02:28:49"), NOW)
        self.assertEqual(feed._ep("2026-09-24T02:28:49Z"), NOW)
        self.assertAlmostEqual(feed._ep("2026-09-24T02:28:49.1234567Z"), NOW + 0.123457, places=5)

    def test_feed_age(self):
        s, _ = snap()
        self.assertEqual(s["feed_age_s"], EXP["feed_age_s"])
        self.assertAlmostEqual(s["feed_age_s"], NOW - (s["candles"][-1]["start"] + 60), places=3)
        s2, _ = snap(now=NOW + 7.5)
        self.assertEqual(s2["feed_age_s"], EXP["feed_age_s"] + 7.5)

    def test_a_lagging_candle_set_is_refused(self):
        # The venue lagging the newest k closed minutes would leave a contiguous window that
        # describes [t-k-15, t-k] while the mid is at t. One omitted minute (60-120 s) is
        # allowed (SPEC §3); two or more is a FeedError, which the tick logs as absence feed.
        raw = CANDLES["candles"]                                        # raw[0] is the open minute
        s = feed.assemble("SOL-USD", NOW, BOOK, {"candles": raw[:1] + raw[2:]}, TRADES, {"calls": 3, "ms": 0})
        self.assertLessEqual(s["feed_age_s"], feed.MAX_FEED_AGE_S)
        for k in (2, 3, 8):
            with self.subTest(k=k), self.assertRaises(feed.FeedError) as cm:
                feed.assemble("SOL-USD", NOW, BOOK, {"candles": raw[:1] + raw[1 + k:]}, TRADES, {"calls": 3, "ms": 0})
            self.assertIn("MAX_FEED_AGE_S", str(cm.exception))
        self.assertEqual(feed.MAX_FEED_AGE_S, 120)

    def test_urls_three_calls_no_retry(self):
        _, f = snap()
        end = int(NOW)
        self.assertEqual(f.urls, [
            feed.BASE + "/product_book?product_id=SOL-USD&limit=1",
            feed.BASE + f"/products/SOL-USD/candles?start={end - 350 * 60}&end={end}&granularity=ONE_MINUTE",
            feed.BASE + f"/products/SOL-USD/ticker?limit=1000&start={end - 300}&end={end}",
        ])
        self.assertEqual(f.urls, [META["book_url"], META["candles_url"], META["trades_url"]])
        for u in f.urls:
            self.assertTrue(u.startswith("https://api.coinbase.com/api/v3/brokerage/market/"), u)

    def test_book_http_error_raises_once(self):
        f = Fake(book=http_error(500))
        with mock.patch("urllib.request.urlopen", f):
            with self.assertRaises(feed.FeedError) as cm:
                feed.snapshot(config.PRODUCT, now=NOW)
        self.assertIn("http-500", str(cm.exception))
        self.assertEqual(len(f.urls), 1)                                # no retry, nothing after

    def test_network_error_raises(self):
        for exc, word in ((TimeoutError("slow"), "TimeoutError"),
                          (urllib.error.URLError("dns"), "URLError")):
            f = Fake(book=exc)
            with mock.patch("urllib.request.urlopen", f):
                with self.assertRaises(feed.FeedError) as cm:
                    feed.snapshot(config.PRODUCT, now=NOW)
            self.assertIn(word, str(cm.exception))
            self.assertEqual(len(f.urls), 1)

    def test_candles_bad_payloads_raise(self):
        # transport or JSON failure: raised in the GET, so the ticker is never asked (2 calls);
        # wrong shape in valid JSON: raised in assemble(), after all three GETs (3 calls)
        for bad, calls in ((http_error(429), 2), (b"<html>not json", 2), ({"candles": None}, 3),
                           ({}, 3), ([], 3), ({"candles": [{"start": "x"}]}, 3),
                           ({"candles": [{"nostart": 1}]}, 3),
                           ({"candles": [{"start": "1790216820", "open": "x"}]}, 3)):
            f = Fake(candles=bad)
            with mock.patch("urllib.request.urlopen", f):
                with self.assertRaises(feed.FeedError):
                    feed.snapshot(config.PRODUCT, now=NOW)
            self.assertEqual(len(f.urls), calls, bad)

    def test_trades_unavailable_is_minus_one_not_a_raise(self):
        for bad in (http_error(503), TimeoutError("slow"), b"garbage",
                    {"trades": [{"time": "nope"}]}, {"nope": 1}, {"trades": [{}]}):
            s, f = snap(Fake(trades=bad))
            self.assertEqual(s["trades_5m"], -1, bad)
            self.assertEqual(s["http"]["calls"], 3)                     # the failed call is counted
            self.assertEqual(set(s), KEYS)
            self.assertEqual(len(s["candles"]), EXP["candles_closed"])

    def test_book_sanity(self):
        def book(bid="114.8", bs="1", ask="114.82", az="1", product="SOL-USD"):
            return {"pricebook": {"product_id": product, "bids": [{"price": bid, "size": bs}],
                                  "asks": [{"price": ask, "size": az}], "time": "t"}}
        for bad in (book(bid="115", ask="114"), book(bs="0"), book(az="0"), book(bid="0"),
                    book(product="BTC-USD"), book(bid="abc"), {"pricebook": {"bids": [], "asks": []}},
                    {"pricebook": {}}, {}, {"pricebook": {"product_id": "SOL-USD", "bids": [{}], "asks": [{}]}}):
            with self.assertRaises(feed.FeedError, msg=bad):
                feed.parse_book(bad, "SOL-USD")
        bid, bs, ask, az, t = feed.parse_book(book(bid="114.8", ask="114.8"), "SOL-USD")   # locked: allowed
        self.assertEqual((bid, ask, t), (114.8, 114.8, "t"))
        nob = book()
        del nob["pricebook"]["time"]
        self.assertIsNone(feed.parse_book(nob, "SOL-USD")[4])            # book_time null when absent

    def test_assemble_equals_snapshot_and_is_the_cli_fixture_path(self):
        s, _ = snap()
        a = feed.assemble("SOL-USD", NOW, BOOK, CANDLES, TRADES, {"calls": 3, "ms": s["http"]["ms"]})
        self.assertEqual(a, s)
        self.assertEqual(json.loads(json.dumps(a)), a)                  # JSON-clean for the row

    def test_fixture_files_are_the_raw_venue_shapes(self):
        # guards the README's claims about the recorded set
        raw = CANDLES["candles"]
        self.assertEqual(len(raw), EXP["candles_raw"])
        self.assertEqual(int(raw[0]["start"]), EXP["open_minute_start"])
        self.assertEqual(int(raw[0]["start"]), int(NOW) // 60 * 60)     # open minute on top
        self.assertIsInstance(raw[0]["close"], str)                      # every number is a string
        self.assertEqual(len(TRADES["trades"]), EXP["trades_raw"])
        self.assertIn("best_bid", TRADES)
        self.assertRegex(TRADES["trades"][0]["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")
        self.assertEqual(BOOK["pricebook"]["product_id"], "SOL-USD")
        self.assertEqual(len(BOOK["pricebook"]["bids"]), 1)

    def test_feed_never_sleeps_retries_or_sees_jev(self):
        with open(feed.__file__) as fh:
            src = fh.read()
        self.assertNotIn("sleep(", src)
        self.assertIsNone(re.search(r"^\s*(from|import)\s+[\w.]*jev", src, re.M))
        self.assertNotIn("typesafe", src.lower())
        self.assertNotIn("Authorization", src)
        self.assertEqual(src.count("urlopen("), 1)


if __name__ == "__main__":
    unittest.main()

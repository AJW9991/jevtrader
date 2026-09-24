"""book: open / close / no-op with exact fee arithmetic at two constants,
equity marks, forced holds, and paired d_t == 0.0 wherever positions match.
Offline; no module other than loop.book and loop.config is imported."""
import unittest

from loop import book, config

N = config.NOTIONAL_USD
# the primary by NAME and the cheapest non-zero column: two real constants for the fee arithmetic
# (the last column is 0, gross, where the arithmetic would be trivially 0)
FEES = (config.FEE_BPS_PRIMARY, min(f for f in config.FEE_BPS_COLUMNS if f > 0))
COLS = ("argmax", "c50", "c70", "c85", "c99", "c50v", "c70v", "c85v", "c99v", "pbuy60", "noultail")


def _cols(intent):
    return {k: intent for k in COLS}


def _row(i, bid, ask, a=None, b=None, c="hold", absence=None, dry=False):
    """A full CONTRACT row. a/b are the intent every column of that arm carries
    (None = the arm's columns are null); prices None = unpriced (failed before feed)."""
    priced = bid is not None and ask is not None
    return {"v": 1, "tick_id": f"20260923T10{i:02d}00Z", "ts_rx": f"2026-09-23T10:{i:02d}:00.100Z",
            "mode": "dry" if dry else "live", "venue": "coinbase", "product": "SOL-USD",
            "cadence_s": 60, "horizon_s": 900,
            "bid": bid, "bid_size": 5.0 if priced else None, "ask": ask, "ask_size": 5.0 if priced else None,
            "mid": (bid + ask) / 2 if priced else None, "book_time": None, "feed_age_s": 1.0 if priced else None,
            "features": {} if priced else None, "adj": {} if priced else None,
            "state": "SOL: liquidity normal, flow organic, trend flat, vol normal" if priced else None,
            "spec_sha": "x", "prompt_a": "v1", "prompt_a_sha": "x", "prompt_b": "v1", "prompt_b_sha": "x",
            "model_requested": config.MODEL, "model_answered": None, "drift": False,
            "jev": {"latency_ms": None, "input_tokens": None, "error": None, "key_path": None},
            "answers": None, "rule_c": c if priced else None,
            "columns": {"a": _cols(a) if a else None, "b": _cols(b) if b else None},
            "absence": absence}


class Apply(unittest.TestCase):
    def test_open_when_flat(self):
        for fee in FEES:
            pos, fill = book.apply(None, "buy", 99.0, 101.0, fee)
            self.assertEqual(pos, {"qty": N / 101.0, "entry": 101.0})
            self.assertEqual(fill, {"side": "buy", "price": 101.0, "qty": N / 101.0, "fee": N * fee / 1e4})
        self.assertEqual(book.apply(None, "buy", 99.0, 101.0, 60.0)[1]["fee"], 6.0)
        self.assertEqual(book.apply(None, "buy", 99.0, 101.0, 2.0)[1]["fee"], 0.2)

    def test_close_when_long(self):
        long = {"qty": N / 101.0, "entry": 101.0}
        for fee in FEES:
            pos, fill = book.apply(long, "sell", 103.0, 105.0, fee)
            self.assertIsNone(pos)
            self.assertEqual(fill, {"side": "sell", "price": 103.0, "qty": N / 101.0,
                                    "fee": (N / 101.0) * 103.0 * fee / 1e4})
        self.assertNotEqual(book.apply(long, "sell", 103.0, 105.0, 60.0)[1]["fee"], 6.0)   # on filled value, not on N

    def test_noops(self):
        long = {"qty": 10.0, "entry": 100.0}
        self.assertEqual(book.apply(long, "buy", 99.0, 101.0, 60.0), (long, None))
        self.assertEqual(book.apply(None, "sell", 99.0, 101.0, 60.0), (None, None))
        self.assertEqual(book.apply(long, "hold", 99.0, 101.0, 60.0), (long, None))
        self.assertEqual(book.apply(None, "hold", 99.0, 101.0, 60.0), (None, None))
        self.assertEqual(book.apply(None, "hold", None, None, 60.0), (None, None))   # no price needed to do nothing

    def test_bad_inputs_raise(self):
        with self.assertRaises(ValueError):
            book.apply(None, "flat", 99.0, 101.0, 60.0)
        with self.assertRaises(ValueError):
            book.apply(None, None, 99.0, 101.0, 60.0)
        with self.assertRaises(ValueError):
            book.apply(None, "buy", 99.0, None, 60.0)
        with self.assertRaises(ValueError):
            book.apply({"qty": 1.0, "entry": 1.0}, "sell", 0.0, 1.0, 60.0)


class Replay(unittest.TestCase):
    ROWS = [_row(1, 99.0, 101.0, a="hold"), _row(2, 99.0, 101.0, a="buy"), _row(3, 101.0, 103.0, a="hold"),
            _row(4, 103.0, 105.0, a="sell"), _row(5, 103.0, 105.0, a="hold")]

    def test_open_hold_close_marks(self):
        for fee in FEES:
            r = book.replay(self.ROWS, None, "a", "argmax", fee)
            q = N / 101.0
            want = {"20260923T100100Z": 0.0,
                    "20260923T100200Z": (q * (100.0 - 101.0) - N * fee / 1e4) * 1e4 / N,
                    "20260923T100300Z": (q * (102.0 - 100.0)) * 1e4 / N,
                    "20260923T100400Z": (q * (103.0 - 102.0) - q * 103.0 * fee / 1e4) * 1e4 / N,
                    "20260923T100500Z": 0.0}
            self.assertEqual(r["pnl_bps_per_tick"], want)
            self.assertEqual([t for t, _ in r["equity"]], list(want))
            run = 0.0
            for (t, e), (_, p) in zip(r["equity"], want.items()):
                run += p
                self.assertEqual(e, run)
            self.assertEqual(r["trades"], [
                {"tick_id": "20260923T100200Z", "side": "buy", "price": 101.0, "qty": q, "fee": N * fee / 1e4},
                {"tick_id": "20260923T100400Z", "side": "sell", "price": 103.0, "qty": q, "fee": q * 103.0 * fee / 1e4}])
            self.assertEqual(r["position"], {"20260923T100100Z": 0.0, "20260923T100200Z": q, "20260923T100300Z": q,
                                             "20260923T100400Z": 0.0, "20260923T100500Z": 0.0})
            self.assertEqual(r["forced_hold"], 0)
            self.assertEqual(sorted(r), ["equity", "forced_hold", "pnl_bps_per_tick", "position", "trades"])

    def test_fee_constant_moves_only_trade_ticks(self):
        hi = book.replay(self.ROWS, None, "a", "argmax", 60.0)["pnl_bps_per_tick"]
        lo = book.replay(self.ROWS, None, "a", "argmax", 2.0)["pnl_bps_per_tick"]
        q = N / 101.0
        self.assertEqual(hi["20260923T100100Z"], lo["20260923T100100Z"])
        self.assertEqual(hi["20260923T100300Z"], lo["20260923T100300Z"])
        self.assertAlmostEqual(lo["20260923T100200Z"] - hi["20260923T100200Z"], 58.0, places=9)
        self.assertAlmostEqual(lo["20260923T100400Z"] - hi["20260923T100400Z"],
                               q * 103.0 * 58.0 / 1e4 * 1e4 / N, places=9)

    def test_forced_holds_and_gap_carry(self):
        rows = [_row(1, 99.0, 101.0, a="buy"),
                _row(2, None, None, absence="feed"),                # unpriced: hold, pnl 0, position carried
                _row(3, 99.0, 101.0, dry=True),                     # columns null: hold
                _row(4, 101.0, 103.0, absence="jev", c="sell"),     # absence: hold for EVERY arm, even c
                _row(5, 105.0, 107.0, a="sell", c="sell")]
        r = book.replay(rows, None, "a", "argmax", 60.0)
        q = N / 101.0
        self.assertEqual(r["forced_hold"], 3)
        self.assertEqual(r["pnl_bps_per_tick"]["20260923T100200Z"], 0.0)
        self.assertEqual(r["pnl_bps_per_tick"]["20260923T100300Z"], 0.0)       # mid 100 -> 100
        self.assertEqual(r["pnl_bps_per_tick"]["20260923T100400Z"], q * 2.0 * 1e4 / N)   # 100 -> 102 lands here
        self.assertEqual(r["position"]["20260923T100200Z"], q)
        self.assertEqual(r["position"]["20260923T100500Z"], 0.0)
        c = book.replay(rows, None, "c", "argmax", 60.0)
        self.assertEqual(c["trades"], [])                                        # c's sell on the jev-absence row is held
        self.assertEqual(c["forced_hold"], 3)                                    # the dry row is forced for c too
        self.assertEqual(sum(c["pnl_bps_per_tick"].values()), 0.0)

    def test_dry_row_is_a_forced_hold_for_c_too(self):
        # A dry row carries rule_c and no model columns. If C acted on it, B-C would carry a
        # C trade B could never make: a `make dry` between two live ticks would manufacture
        # a disagreement. Here rule_c says buy on the dry row and hold everywhere else.
        rows = [_row(1, 99.0, 101.0, a="hold", b="hold", c="hold"),
                _row(2, 104.0, 106.0, c="buy", dry=True),
                _row(3, 109.0, 111.0, a="hold", b="hold", c="hold"),
                _row(4, 114.0, 116.0, a="hold", b="hold", c="hold")]
        for fee in FEES:
            c = book.replay(rows, None, "c", "argmax", fee)
            self.assertEqual(c["trades"], [])
            self.assertEqual(c["forced_hold"], 1)
            self.assertEqual(book.paired(rows, None, "b", "c", "argmax", fee), [(r["tick_id"], 0.0) for r in rows])

    def test_arm_c_reads_rule_c_and_ignores_column(self):
        rows = [_row(1, 99.0, 101.0, a="hold", c="buy"), _row(2, 99.0, 101.0, a="hold", c="sell")]
        r = book.replay(rows, None, "c", "does-not-exist", 60.0)
        self.assertEqual([t["side"] for t in r["trades"]], ["buy", "sell"])
        self.assertEqual(book.replay(rows, None, "a", "argmax", 60.0)["trades"], [])

    def test_bad_column_or_arm_is_loud(self):
        with self.assertRaises(KeyError):
            book.replay(self.ROWS, None, "a", "argmaxx", 60.0)
        with self.assertRaises(ValueError):
            book.replay(self.ROWS, None, "d", "argmax", 60.0)
        with self.assertRaises(TypeError):
            book.replay(self.ROWS, [], "a", "argmax", 60.0)

    def test_duplicate_tick_folds_and_order_is_by_tick(self):
        dup = dict(_row(2, None, None, absence="lock")); dup["ts_rx"] = "2026-09-23T10:02:30.000Z"
        rows = [self.ROWS[3], self.ROWS[1], dup, self.ROWS[0], self.ROWS[2], self.ROWS[4]]
        r = book.replay(rows, None, "a", "argmax", 60.0)
        base = book.replay(self.ROWS, None, "a", "argmax", 60.0)
        self.assertEqual(r["pnl_bps_per_tick"], base["pnl_bps_per_tick"])
        self.assertEqual(r["equity"], base["equity"])
        self.assertEqual(r["forced_hold"], 1)

    def test_empty(self):
        self.assertEqual(book.replay([], None, "a", "argmax", 60.0),
                         {"equity": [], "trades": [], "pnl_bps_per_tick": {}, "position": {}, "forced_hold": 0})


class Paired(unittest.TestCase):
    # a and c agree on 1-3 and 7; on 4 a sells and c stays long; on 5 they differ (a flat, c long);
    # on 6 c sells while a is already flat; the mid moves on every tick so a carried long is never 0 by luck.
    ROWS = [_row(1, 99.0, 101.0, a="hold", c="hold"), _row(2, 99.5, 101.5, a="buy", c="buy"),
            _row(3, 100.0, 102.0, a="hold", c="hold"), _row(4, 100.5, 102.5, a="sell", c="hold"),
            _row(5, 101.0, 103.0, a="hold", c="hold"), _row(6, 101.5, 103.5, a="hold", c="sell"),
            _row(7, 102.0, 104.0, a="hold", c="hold")]

    def test_zero_exactly_where_positions_match(self):
        d = dict(book.paired(self.ROWS, None, "a", "c", "argmax", 60.0))
        pa = book.replay(self.ROWS, None, "a", "argmax", 60.0)["position"]
        pc = book.replay(self.ROWS, None, "c", "argmax", 60.0)["position"]
        ticks = list(pa)
        before = {t: (pa[ticks[i - 1]] if i else 0.0, pc[ticks[i - 1]] if i else 0.0) for i, t in enumerate(ticks)}
        for t in ticks:
            same = before[t][0] == before[t][1] and pa[t] == pc[t]
            if same:
                self.assertEqual(d[t], 0.0, t)
            else:
                self.assertNotEqual(d[t], 0.0, t)
        self.assertEqual([t for t in ticks if d[t] != 0.0],
                         ["20260923T100400Z", "20260923T100500Z", "20260923T100600Z"])
        self.assertEqual([t for t, _ in book.paired(self.ROWS, None, "a", "c", "argmax", 60.0)], ticks)

    def test_same_arm_is_all_zero_and_antisymmetric(self):
        self.assertTrue(all(v == 0.0 for _, v in book.paired(self.ROWS, None, "c", "c", "argmax", 60.0)))
        ac = book.paired(self.ROWS, None, "a", "c", "argmax", 2.0)
        ca = book.paired(self.ROWS, None, "c", "a", "argmax", 2.0)
        self.assertEqual([(t, -v) for t, v in ca], ac)

    def test_b_null_columns_is_all_hold(self):
        self.assertEqual(book.paired(self.ROWS, None, "b", "b", "c50v", 60.0),
                         [(r["tick_id"], 0.0) for r in self.ROWS])
        self.assertEqual(book.replay(self.ROWS, None, "b", "c50v", 60.0)["forced_hold"], len(self.ROWS))


if __name__ == "__main__":
    unittest.main()

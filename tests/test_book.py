"""book: open / close / no-op with exact fee arithmetic at two constants,
equity marks, forced holds, and paired d_t == 0.0 wherever positions match.
Offline; no module other than loop.book and loop.config is imported."""
import unittest

from loop import book, config

N = config.NOTIONAL_USD
# the venue's fee by NAME and the cheapest non-zero column: two real constants for the fee
# arithmetic. (This read FEE_BPS_PRIMARY until 2026-09-24, when Alex moved the primary to 0 bps,
# gross, where the arithmetic would be trivially 0; the venue's 120 bps is the constant it meant.)
FEES = (config.FEE_BPS_VENUE, min(f for f in config.FEE_BPS_COLUMNS if f > 0))
COLS = ("argmax", "c50", "c70", "c85", "c99", "c50v", "c70v", "c85v", "c99v", "pbuy60", "noultail")


def _cols(intent):
    return {k: intent for k in COLS}


def _row(i, bid, ask, a=None, b=None, c="hold", absence=None, dry=False, d="absent"):
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
            "columns": {"a": _cols(a) if a else None, "b": _cols(b) if b else None, **({} if d == "absent" else {"d": d})},
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

    def test_round_trip_at_the_primary_fee_still_pays_the_spread(self):
        # PREREG §4 / SPEC §10 (review, 2026-09-24): at FEE_BPS_PRIMARY = 0 the H1 cell is gross of
        # FEES, not of the spread. On a flat book one extra round trip costs exactly
        # q * (bid - ask) = -1e4 * spread / ask bps: 0.87 at a 1c spread on ~$115, 1.74 at 2c --
        # the order of the 1.78 bps per-block MDE, so turnover still moves the cell.
        self.assertEqual(config.FEE_BPS_PRIMARY, 0.0)
        for bid, ask, want in ((114.95, 114.96, 0.8699), (114.94, 114.96, 1.7397)):
            rows = [_row(1, bid, ask, a="buy", c="hold"), _row(2, bid, ask, a="sell", c="hold")]
            d = sum(v for _, v in book.paired(rows, None, "a", "c", "argmax", config.FEE_BPS_PRIMARY))
            self.assertAlmostEqual(d, -1e4 * (ask - bid) / ask, places=9)
            self.assertAlmostEqual(-d, want, places=4)

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
            book.replay(self.ROWS, None, "e", "argmax", 60.0)
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

    def test_null_columns_hold_every_arm_c_included(self):
        # SPEC §10: "null columns ... is a forced hold for EVERY arm, C included". A live, absence-null
        # row with null model columns cannot come from cycle.py, but if one ever did, C trading on it
        # would manufacture a B-C and an A-C disagreement A and B could never answer.
        from loop import rules
        rows = [_row(1, 99.0, 101.0, a="hold", b="hold", c="hold"), _row(2, 99.0, 101.0, a="hold", b="hold", c="buy"),
                _row(3, 104.0, 106.0, a="hold", b="hold", c="hold")]
        for cols in ({"a": rules.null_columns(), "b": rules.null_columns()}, {"a": None, "b": None}, {}):
            rows[1]["columns"] = cols
            self.assertEqual([d for _, d in book.paired(rows, None, "b", "c", "argmax", 0.0)], [0.0, 0.0, 0.0], cols)
            rep = book.replay(rows, None, "c", "argmax", 0.0)
            self.assertEqual(rep["trades"], [])
            self.assertEqual(rep["forced_hold"], 1)
        # one arm's columns null with the other's present is not a shape the tick writes: only that arm
        # holds (the fixtures above lean on it), and C reads rule_c as before
        for cols in ({"a": _cols("hold"), "b": None}, {"a": None, "b": _cols("hold")}, {"a": _cols("hold"), "b": _cols("hold")}):
            rows[1]["columns"] = cols
            self.assertEqual(len(book.replay(rows, None, "c", "argmax", 0.0)["trades"]), 1, cols)

    def test_two_priced_rows_in_one_tick_and_a_locked_book(self):
        # two priced rows share a minute (a dry row between two live ticks): the dry one is a forced
        # hold, its mark folds into the minute, and the pnl dict has one entry per tick; a locked book
        # (bid == ask) opens and closes at the same price, so the spread costs nothing there
        rows = [_row(1, 99.0, 101.0, a="buy", b="buy", c="buy"), _row(1, 99.5, 100.5, dry=True),
                _row(2, 100.0, 100.0, a="hold", b="hold", c="hold"), _row(3, 100.0, 100.0, a="sell", b="sell", c="sell")]
        rep = book.replay(rows, None, "c", "argmax", 0.0)
        self.assertEqual(list(rep["pnl_bps_per_tick"]), ["20260923T100100Z", "20260923T100200Z", "20260923T100300Z"])
        self.assertEqual(len(rep["trades"]), 2)
        self.assertEqual(rep["forced_hold"], 1)
        self.assertEqual(rep["trades"][1]["price"], 100.0)              # closed at the locked bid
        for d in (d for _, d in book.paired(rows, None, "b", "c", "argmax", 0.0)):
            self.assertEqual(d, 0.0)

    def test_b_null_columns_is_all_hold(self):
        self.assertEqual(book.paired(self.ROWS, None, "b", "b", "c50v", 60.0),
                         [(r["tick_id"], 0.0) for r in self.ROWS])
        self.assertEqual(book.replay(self.ROWS, None, "b", "c50v", 60.0)["forced_hold"], len(self.ROWS))


class ArmD(unittest.TestCase):
    """PREREG-v2 §10's book bullet: ARMS gains d; D reads columns.d (the CURRENT table's answer, no call) at
    argmax and raises on any other column; the every-arm forced hold applies to D; a null columns.d on an
    otherwise answered row is a hold for D only, counted in D's forced holds."""

    def test_d_is_an_arm_and_reads_columns_d(self):
        self.assertEqual(book.ARMS, ("a", "b", "c", "d"))
        rows = [_row(1, 99.0, 101.0, a="hold", b="hold", d="buy"), _row(2, 101.0, 103.0, a="hold", b="hold", d="hold"),
                _row(3, 103.0, 105.0, a="hold", b="buy", d="sell")]
        r = book.replay(rows, None, "d", "argmax", 0.0)
        self.assertEqual([(t["tick_id"], t["side"]) for t in r["trades"]], [("20260923T100100Z", "buy"), ("20260923T100300Z", "sell")])
        self.assertEqual(r["forced_hold"], 0)
        # D and B differ only where their intents do: B buys at :03, D sold there
        d = dict(book.paired(rows, None, "d", "b", "argmax", 0.0))
        self.assertEqual(d["20260923T100100Z"], r["pnl_bps_per_tick"]["20260923T100100Z"])

    def test_d_has_no_column_but_argmax(self):
        rows = [_row(1, 99.0, 101.0, a="hold", b="hold", d="buy")]
        for col in ("c50", "noultail", "argmaxx"):
            with self.assertRaises(ValueError):
                book.replay(rows, None, "d", col, 0.0)
            with self.assertRaises(ValueError):
                book.replay([], None, "d", col, 0.0)                          # loud on an empty log too
            with self.assertRaises(ValueError):
                book._intent(_row(2, None, None, absence="feed"), "d", col)    # and on a forced-hold row

    def test_the_every_arm_forced_hold_applies_to_d(self):
        rows = [_row(1, 99.0, 101.0, a="hold", b="hold", d="hold"),
                _row(2, 99.0, 101.0, d="buy", dry=True),                          # dry: forced for D
                _row(3, 99.0, 101.0, a="hold", b="hold", d="buy", absence="jev"), # absence: forced for D
                _row(4, 99.0, 101.0, d="buy"),                                    # live, a and b null: forced for D
                _row(5, None, None, a="hold", b="hold", d="buy"),                 # unpriced: forced for D
                _row(6, 99.0, 101.0, a="hold", b="hold", d="hold")]
        r = book.replay(rows, None, "d", "argmax", 0.0)
        self.assertEqual(r["trades"], [])
        self.assertEqual(r["forced_hold"], 4)

    def test_a_null_d_on_an_answered_row_holds_d_only(self):
        rows = [_row(1, 99.0, 101.0, a="buy", b="buy", c="buy", d=None),            # no table: D alone holds
                _row(2, 104.0, 106.0, a="hold", b="hold", c="hold", d="hold"),
                _row(3, 109.0, 111.0, a="sell", b="sell", c="sell")]               # a v1 row: no d key at all
        dr = book.replay(rows, None, "d", "argmax", 0.0)
        self.assertEqual(dr["trades"], [])
        self.assertEqual(dr["forced_hold"], 2)                                     # the null and the absent d
        for arm in ("a", "b", "c"):
            rep = book.replay(rows, None, arm, "argmax", 0.0)
            self.assertEqual(len(rep["trades"]), 2, arm)
            self.assertEqual(rep["forced_hold"], 0, arm)


class AtCadence(unittest.TestCase):
    """PREREG-v2 §4: at_cadence(rows, c, t0) acts once per c-block on the block's decision row (the first row in
    _order on which replay would not force a hold), every arm from that one row, and holds on every other row of
    the block; a block with no decision row holds throughout. Hand-built rows, the intents per row written out."""
    T0 = "20260923T100000Z"

    @staticmethod
    def _r(minute, a=None, b=None, c="hold", d="absent", priced=True, absence=None, dry=False, ts=100):
        r = _row(0, 99.0 + minute if priced else None, 101.0 + minute if priced else None, a=a, b=b, c=c, absence=absence, dry=dry, d=d)
        h, m = divmod(minute, 60)
        r["tick_id"] = f"20260923T{10 + h:02d}{m:02d}00Z"
        r["ts_rx"] = f"2026-09-23T{10 + h:02d}:{m:02d}:00.{ts:03d}Z"
        return r

    def _intents(self, rows, arm):
        return [book._intent(r, arm, "argmax") if all(book._px(r.get(k)) for k in ("bid", "ask", "mid")) else None for r in rows]

    def test_per_block_intents_on_a_hand_built_log(self):
        t0 = book._epoch(self.T0)
        R = self._r
        rows = [
            # block 0, [10:00, 10:15): an unpriced row, a dry row, then the decision row at :02; :03 is held; :07 an absence
            R(0, priced=False, absence="feed"), R(1, dry=True, c="buy"), R(2, a="buy", b="sell", c="buy", d="buy"),
            R(3, a="sell", b="buy", c="sell", d="sell"), R(7, a="buy", b="buy", c="buy", d="buy", absence="jev"),
            # block 1, [10:15, 10:30): absences and a dry row only: every arm holds throughout
            R(15, absence="halt", c="sell"), R(16, dry=True, c="sell"), R(29, absence="guard"),
            # block 2, [10:30, 10:45): both model columns null (forced), an unpriced answered row (forced), then the
            # decision row at :33 with a null D (D alone holds), then answered rows that are held
            R(30, c="sell"), R(31, a="sell", b="sell", c="sell", d="sell", priced=False), R(33, a="sell", b="hold", c="sell", d=None),
            R(40, a="buy", b="buy", c="buy", d="buy"),
            # block 3, [10:45, 11:00): one row, a v1 row with no d key: D holds, the rest act
            R(50, a="hold", b="buy", c="hold"),
        ]
        out = book.at_cadence(rows, 900, t0)
        self.assertEqual([r["tick_id"] for r in out], [r["tick_id"] for r in rows])
        self.assertEqual(sorted(book.decision_rows(rows, 900, t0)), [0, 2, 3])
        want = {                       # per row, in order: the intent replay reads (None: a forced hold for that arm)
            "a": [None, None, "buy", "hold", None, None, None, None, None, None, "sell", "hold", "hold"],
            "b": [None, None, "sell", "hold", None, None, None, None, None, None, "hold", "hold", "buy"],
            "c": [None, None, "buy", "hold", None, None, None, None, None, None, "sell", "hold", "hold"],
            "d": [None, None, "buy", "hold", None, None, None, None, None, None, None, "hold", None],
        }
        for arm, w in want.items():
            self.assertEqual(self._intents(out, arm), w, arm)
        # the transformed intents feed replay: trades only on decision rows, the book's own forced-hold count
        for arm, sides in (("a", [("20260923T100200Z", "buy"), ("20260923T103300Z", "sell")]), ("b", [("20260923T105000Z", "buy")]),
                           ("c", [("20260923T100200Z", "buy"), ("20260923T103300Z", "sell")]), ("d", [("20260923T100200Z", "buy")])):
            rep = book.replay(out, None, arm, "argmax", 0.0)
            self.assertEqual([(t["tick_id"], t["side"]) for t in rep["trades"]], sides, arm)
        self.assertEqual(book.replay(out, None, "d", "argmax", 0.0)["forced_hold"], 10)   # 8 forced for all, D null at :33, no d at :50
        self.assertEqual(book.replay(out, None, "a", "argmax", 0.0)["forced_hold"], 8)
        # the raw minute replay trades on more rows: the cadence changed the policy, not the book
        self.assertGreater(len(book.replay(rows, None, "a", "argmax", 0.0)["trades"]), 2)

    def test_the_input_rows_are_not_changed(self):
        import copy
        t0 = book._epoch(self.T0)
        rows = [self._r(m, a="buy", b="sell", c="buy", d="sell") for m in range(0, 40, 3)]
        before = copy.deepcopy(rows)
        out = book.at_cadence(rows, 900, t0)
        self.assertEqual(rows, before)
        self.assertIs(out[0], rows[0])                                         # the decision row is the row itself
        self.assertIsNot(out[1], rows[1])

    def test_t0_not_aligned_to_c_and_a_row_before_t0(self):
        # T0_v2 is a minute boundary, not a multiple of c: the blocks run from it. A row before it is block -1.
        t0 = book._epoch("20260923T100700Z")
        rows = [self._r(m, a="buy", b="buy", c="buy", d="buy") for m in (5, 6, 7, 8, 21, 22, 23)]
        self.assertEqual({j: r["tick_id"] for j, r in book.decision_rows(rows, 900, t0).items()},
                         {-1: "20260923T100500Z", 0: "20260923T100700Z", 1: "20260923T102200Z"})
        out = book.at_cadence(rows, 900, t0)
        self.assertEqual(self._intents(out, "a"), ["buy", "hold", "buy", "hold", "hold", "buy", "hold"])

    def test_two_rows_in_one_minute_the_first_by_ts_rx_decides(self):
        t0 = book._epoch(self.T0)
        lock = self._r(2, absence="lock", priced=False, ts=50)
        first = self._r(2, a="buy", b="buy", c="buy", d="buy", ts=200)
        second = self._r(2, a="sell", b="sell", c="sell", d="sell", ts=900)
        out = book.at_cadence([second, first, lock], 900, t0)
        self.assertEqual([r["ts_rx"][-7:] for r in out], ["00.050Z", "00.200Z", "00.900Z"])
        self.assertEqual(self._intents(out, "b"), [None, "buy", "hold"])

    def test_every_answered_minute_its_own_block_at_c_60(self):
        # at c = 60 on a log of one row a minute, every answered priced row is its own decision row: the minute replay
        t0 = book._epoch(self.T0)
        rows = [self._r(0, a="buy", b="hold", c="buy", d="buy"), self._r(1, absence="feed", priced=False),
                self._r(2, a="sell", b="buy", c="hold", d="sell"), self._r(3, a="buy", b="sell", c="sell", d=None)]
        for arm in book.ARMS:
            self.assertEqual(book.replay(book.at_cadence(rows, 60, t0), None, arm, "argmax", 10.0),
                             book.replay(rows, None, arm, "argmax", 10.0), arm)

    def test_an_argmax_null_arm_with_a_stray_column_holds_off_the_decision_row(self):
        # an arm whose argmax is null but which carries a non-null column (a shape rules.columns never writes, all null
        # or all filled) acts at that column on the decision row as the raw replay would, and holds on every held row:
        # _held turns each non-null column of it into hold too (2026-09-29 refuter: it kept the stray "buy")
        t0 = book._epoch(self.T0)
        rows = [self._r(m, b="hold", c="hold", d="hold") for m in (2, 5, 8)]
        for r in rows:
            r["columns"]["a"] = {"argmax": None, "c50": "buy", "c70": None}
        rows[0]["columns"]["a"] = {"argmax": None, "c50": "hold", "c70": None}          # the decision row: A holds at c50
        out = book.at_cadence(rows, 900, t0)
        self.assertEqual([book._intent(r, "a", "c50") for r in out], ["hold", "hold", "hold"])
        self.assertEqual([book._intent(r, "a", "argmax") for r in out], [None, None, None])
        self.assertEqual([book._intent(r, "a", "c70") for r in out], [None, None, None])
        self.assertEqual(book.replay(out, None, "a", "c50", 0.0)["trades"], [])
        self.assertEqual(out[1]["columns"]["a"], {"argmax": None, "c50": "hold", "c70": None})
        self.assertEqual(rows[1]["columns"]["a"], {"argmax": None, "c50": "buy", "c70": None})   # the input is not changed

    def test_bad_cadence_or_t0_is_loud(self):
        t0 = book._epoch(self.T0)
        for c in (0, -900, 900.0, True, None):
            with self.assertRaises(ValueError, msg=repr(c)):
                book.at_cadence([], c, t0)
        for t in (None, float("nan"), "20260923T100000Z", True):
            with self.assertRaises(ValueError, msg=repr(t)):
                book.at_cadence([], 900, t)
        with self.assertRaises(ValueError):
            book.at_cadence([dict(self._r(2, a="buy", b="buy"), tick_id="2026-09-23T10:02")], 900, t0)
        self.assertEqual(book.at_cadence([], 900, t0), [])


if __name__ == "__main__":
    unittest.main()

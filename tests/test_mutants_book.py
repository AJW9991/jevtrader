"""book: the rules of SPEC §10 that the older book tests left unpinned, found by mutating
loop/book.py (2026-09-28). Each test names the documented rule it holds the code to: a close on a
locked book, the equity point of a folded minute, the carry's reference mid, the absence and mode
clauses on their own, a null or malformed columns field, a null rule_c, what counts as a price, a
book missing one side, the ts_rx tiebreak and the tick_id order.
Offline and pure: only loop.book, loop.config and loop.rules are imported; nothing is read or written."""
import math
import unittest

from loop import book, config, rules

N = config.NOTIONAL_USD
FEE = 60.0                                   # any non-zero constant: the rules below hold at every fee


def _cols(intent, **over):
    d = {k: intent for k in rules.COLUMNS}
    d.update(over)
    return d


def _row(minute, bid, ask, mid="avg", a=None, b=None, c="hold", absence=None, mode="live", ts=None):
    """A CONTRACT row reduced to what book reads. a/b: the intent every column of that arm carries
    (None = the arm's columns are null). mid defaults to (bid + ask) / 2 when both are floats."""
    if mid == "avg":
        both = all(isinstance(x, float) and math.isfinite(x) for x in (bid, ask))
        mid = (bid + ask) / 2 if both else None
    return {"v": 1, "tick_id": f"20260923T10{minute:02d}00Z",
            "ts_rx": ts if ts is not None else f"2026-09-23T10:{minute:02d}:00.100Z",
            "mode": mode, "bid": bid, "ask": ask, "mid": mid, "rule_c": c,
            "columns": {"a": _cols(a) if a else None, "b": _cols(b) if b else None},
            "absence": absence}


def _t(minute):
    return f"20260923T10{minute:02d}00Z"


def _bps(usd):
    return usd * 1e4 / N


class Marks(unittest.TestCase):
    def test_close_on_a_locked_book_is_marked_from_the_previous_mid(self):
        # SPEC §10: a close books qty·(bid − mid_prev) − fee, even when the bid equals the ask
        rows = [_row(1, 99.0, 101.0, a="buy"), _row(2, 102.0, 104.0, a="hold"), _row(3, 100.0, 100.0, a="sell")]
        q = N / 101.0
        for fee in (0.0, FEE):
            r = book.replay(rows, None, "a", "argmax", fee)
            self.assertEqual(r["pnl_bps_per_tick"][_t(3)], _bps(q * (100.0 - 103.0) - q * 100.0 * fee / 1e4))
            self.assertEqual([t["side"] for t in r["trades"]], ["buy", "sell"])

    def test_equity_at_a_folded_minute_counts_every_row_of_it(self):
        # SPEC §10: equity is cumulative bps, and two rows with one tick_id fold (+=) into that minute
        rows = [_row(1, 99.0, 101.0, a="buy"), _row(2, 101.0, 103.0, a="hold"),
                _row(2, 104.0, 106.0, mode="dry", ts="2026-09-23T10:02:30.000Z")]   # the dry row's mark moves
        r = book.replay(rows, None, "a", "argmax", FEE)
        pnl = r["pnl_bps_per_tick"]
        self.assertEqual(list(pnl), [_t(1), _t(2)])
        self.assertNotEqual(pnl[_t(2)], book.replay(rows[:2], None, "a", "argmax", FEE)["pnl_bps_per_tick"][_t(2)])
        self.assertEqual([t for t, _ in r["equity"]], [_t(1), _t(2)])
        self.assertEqual(r["equity"][0][1], pnl[_t(1)])
        self.assertAlmostEqual(r["equity"][1][1], pnl[_t(1)] + pnl[_t(2)], places=9)   # the running sum rounds once more

    def test_the_carry_is_marked_from_the_previous_rows_logged_mid(self):
        # SPEC §10 / module docstring: a carried position books qty·(mid_t − mid_prev), each mid the row's own
        rows = [_row(1, 99.0, 101.0, mid=100.5, a="buy"), _row(2, 99.25, 101.25, mid=100.75, a="hold")]
        q = N / 101.0
        r = book.replay(rows, None, "a", "argmax", FEE)
        self.assertEqual(r["pnl_bps_per_tick"][_t(2)], _bps(q * (100.75 - 100.5)))


class ForcedHolds(unittest.TestCase):
    def _held_by_every_arm(self, middle, arms=("a", "b", "c"), column="argmax"):
        rows = [_row(1, 99.0, 101.0, a="hold", b="hold"), middle, _row(3, 109.0, 111.0, a="hold", b="hold")]
        for arm in arms:
            r = book.replay(rows, None, arm, column, FEE)
            self.assertEqual(r["trades"], [], (arm, middle))
            self.assertEqual(r["forced_hold"], 1, (arm, middle))
            self.assertEqual(r["pnl_bps_per_tick"][_t(2)], 0.0, (arm, middle))

    def test_absence_or_a_non_live_mode_holds_every_arm_even_with_columns_present(self):
        # SPEC §10: a row with absence set, or whose mode is not live, is a forced hold for EVERY arm
        for absence in ("jev", "halt", ""):                      # any non-null absence, even one outside the alphabet
            with self.subTest(absence=absence):
                self._held_by_every_arm(_row(2, 104.0, 106.0, a="buy", b="buy", c="buy", absence=absence))
        for mode in ("dry", None, "paper"):
            with self.subTest(mode=mode):
                self._held_by_every_arm(_row(2, 104.0, 106.0, a="buy", b="buy", c="buy", mode=mode))
        no_mode = _row(2, 104.0, 106.0, a="buy", b="buy", c="buy")
        del no_mode["mode"]
        self._held_by_every_arm(no_mode)

    def test_a_null_or_missing_columns_field_holds_every_arm(self):
        # SPEC §10: null columns are a forced hold for EVERY arm, C included
        null = _row(2, 104.0, 106.0, c="buy")
        null["columns"] = None
        self._held_by_every_arm(null)
        missing = _row(2, 104.0, 106.0, c="buy")
        del missing["columns"]
        self._held_by_every_arm(missing)

    def test_argmax_null_on_both_arms_is_null_columns_whatever_else_they_hold(self):
        # SPEC §9: argmax is action.choice and every other column derives from it; with no choice the
        # dict is null, so argmax null on both arms is SPEC §10's null columns, a hold for every arm
        row = _row(2, 104.0, 106.0, c="buy")
        row["columns"] = {"a": _cols(None, c85v="buy"), "b": _cols(None, c85v="buy")}
        self._held_by_every_arm(row, column="c85v")

    def test_a_null_rule_c_on_a_decided_row_is_a_counted_forced_hold_for_c(self):
        # _intent docstring / SPEC §2: a null rule_c carries no decision for C, which is a forced hold
        self._held_by_every_arm(_row(2, 104.0, 106.0, a="hold", b="hold", c=None), arms=("c",))

    def test_arm_b_reads_its_own_columns_when_the_a_slot_is_not_a_dict(self):
        # SPEC §10: arm a/b reads columns[arm][column] and arm c rule_c; only null columns on BOTH arms hold all
        rows = [_row(1, 99.0, 101.0, a="hold", b="hold"), _row(2, 104.0, 106.0, b="buy", c="buy")]
        rows[1]["columns"]["a"] = "buy"
        for arm in ("b", "c"):
            r = book.replay(rows, None, arm, "argmax", FEE)
            self.assertEqual([(t["tick_id"], t["side"]) for t in r["trades"]], [(_t(2), "buy")], arm)
            self.assertEqual(r["forced_hold"], 0, arm)


class Prices(unittest.TestCase):
    def test_a_bool_non_finite_negative_or_string_price_is_an_unpriced_forced_hold(self):
        # CONTRACT §2 (a level is a finite positive price) and SPEC §10: anything else is an unpriced
        # book, a forced hold for every arm; book._px: a bool never becomes a fill
        for bad in (True, math.inf, math.nan, -101.0, "101.0"):
            with self.subTest(ask=bad):
                row = _row(1, 99.0, 101.0, a="buy", b="buy", c="buy")
                row["ask"] = bad
                for arm in ("a", "b", "c"):
                    r = book.replay([row], None, arm, "argmax", FEE)
                    self.assertEqual((r["trades"], r["forced_hold"], r["pnl_bps_per_tick"]), ([], 1, {_t(1): 0.0}))

    def test_a_price_below_one_dollar_is_still_a_price(self):
        # CONTRACT §2 / SPEC §10: a usable price is any finite positive number
        rows = [_row(1, 0.25, 0.5, a="buy"), _row(2, 0.5, 0.75, a="sell")]
        r = book.replay(rows, None, "a", "argmax", FEE)
        self.assertEqual([(t["side"], t["price"]) for t in r["trades"]], [("buy", 0.5), ("sell", 0.5)])
        self.assertEqual(r["forced_hold"], 0)

    def test_a_book_missing_its_bid_or_ask_is_unpriced_even_with_a_mid(self):
        # SPEC §10: an unpriced book is a forced hold for every arm and counted in forced_hold;
        # priced means bid, ask AND mid usable (book.replay; inference's gap count reads the same test)
        for side in ("bid", "ask"):
            with self.subTest(missing=side):
                row = _row(1, 99.0, 101.0, a="buy", b="buy", c="buy")
                row[side] = None
                for arm in ("a", "b", "c"):
                    r = book.replay([row], None, arm, "argmax", FEE)
                    self.assertEqual((r["trades"], r["forced_hold"]), ([], 1), arm)


class Order(unittest.TestCase):
    def test_rows_of_one_minute_replay_in_ts_rx_order_whatever_order_they_arrive(self):
        # module docstring (the mark at t uses t's mid only, never a later one) and SPEC §2 (ts_rx is the
        # decision time; two rows can share a tick_id): within a minute rows walk in ts_rx order
        first = _row(1, 99.0, 101.0, a="buy")
        later = _row(1, 103.0, 105.0, mode="dry", ts="2026-09-23T10:01:30.000Z")
        after = _row(2, 103.0, 105.0, a="hold")
        want = book.replay([first, later, after], None, "a", "argmax", FEE)
        self.assertEqual(book.replay([later, first, after], None, "a", "argmax", FEE), want)
        self.assertEqual(book.replay([after, later, first], None, "a", "argmax", FEE), want)

    def test_rows_walk_in_tick_id_order_even_where_ts_rx_disagrees(self):
        # SPEC §10: replay walks rows in tick_id order
        rows = [_row(1, 99.0, 101.0, a="buy", ts="2026-09-23T10:09:00.000Z"), _row(2, 103.0, 105.0, a="sell")]
        r = book.replay(rows, None, "a", "argmax", FEE)
        self.assertEqual([t for t, _ in r["equity"]], [_t(1), _t(2)])
        self.assertEqual([(t["tick_id"], t["side"]) for t in r["trades"]], [(_t(1), "buy"), (_t(2), "sell")])

    def test_a_row_without_ts_rx_still_folds_into_its_minute(self):
        # SPEC §10: rows walk in tick_id order and one minute's rows fold; ts_rx only breaks the tie
        rows = [_row(1, 99.0, 101.0, a="buy"), _row(1, 103.0, 105.0, mode="dry")]
        rows[1]["ts_rx"] = None
        r = book.replay(rows, None, "a", "argmax", FEE)
        self.assertEqual((list(r["pnl_bps_per_tick"]), len(r["trades"]), r["forced_hold"]), ([_t(1)], 1, 1))


if __name__ == "__main__":
    unittest.main()

"""PREREG-v2's report (loop/report.py without --log): every product's store, per product and pooled, the cadences
through book.at_cadence, the recomputed stop rule 3, arm D's agreement, gap_blocks, and the withholding of §9.5,
which reads T0_v2 from PREREG-v2.md §12 whatever the flags say. Offline: synthetic logs (tests/synth.py) and
hand-built rows in temp directories; the live data/, HALT and looks.tsv are never touched."""
import contextlib, datetime, io, json, os, tempfile, unittest
from unittest import mock

import synth
from fixture_prereg import pin_prereg, pin_prereg_v2
from fixture_products import add_products
from loop import book, config, outcomes, report, rules

T0S = "20261024T220000Z"                             # a stand-in T0_v2 (§12 is filled at sealing)
T0 = report.tick_epoch(T0S)
END = T0 + 28 * 86400
UTC = datetime.timezone.utc


def _iso(epoch, ms=100):
    return datetime.datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def _row(epoch, mid, b="hold", c="hold", a="hold", d="same", absence=None, product="SOL-USD"):
    """A v2-era row reduced to what the readers read: B, A and C's intents on every column, D the table's (by
    default B's own argmax), priced 1c either side of `mid` unless mid is None; an absence row carries no columns."""
    cols = {"a": {k: a for k in rules.COLUMNS}, "b": {k: b for k in rules.COLUMNS}, "d": b if d == "same" else d}
    if absence is not None:
        cols = {"a": None, "b": None, "d": None}
    return {"v": 1, "tick_id": report._tick_of(epoch), "ts_rx": _iso(epoch), "mode": "live", "product": product,
            "bid": None if mid is None else mid - 0.01, "ask": None if mid is None else mid + 0.01, "mid": mid,
            "spec_sha": "spec-v2-fixture", "prompt_a": "v2", "prompt_a_sha": "A", "prompt_b": "v2", "prompt_b_sha": "A",
            "table_sha": "T", "model_answered": config.MODEL, "drift": False,
            "jev": {"latency_ms": 500, "input_tokens": 100, "error": "timeout" if absence == "jev" else None, "key_path": "loop"},
            "answers": None, "rule_c": None if mid is None else c, "columns": cols, "absence": absence}


def _store(product, rows):
    last = max((report.tick_epoch(r["tick_id"]) for r in rows), default=None)
    return {"product": product, "log": f"<{product}>", "missing": False, "rows": [r for r in rows if T0 <= report.tick_epoch(r["tick_id"]) < END],
            "bad": [], "outs": outcomes.join(rows), "last": last, "reached": last}


def _day_rows(day, mid_of, product="SOL-USD", every=900, **kw):
    """Rows of T0-anchored day `day` (1 = d01), one every `every` s; mid_of(i) the mid of the i-th."""
    a = T0 + 86400 * (day - 1)
    return [_row(a + every * i, mid_of(i), product=product, **kw) for i in range(86400 // every)]


class ExcludedDayBetweenKeptDays(unittest.TestCase):
    """PREREG-v2 §4: the replay runs from flat at T0 over every row, excluded days included; an excluded product-
    day's blocks are dropped afterwards; a position carried into an excluded day is marked on its priced rows, and
    where it has none the move lands on the first priced tick after it, in a kept block that stays kept (gap_blocks).
    B buys on d01's first row and holds; C never trades: the arms' positions differ across d02, and d02's price jump
    (100 -> 150) is the whole of what dropping it removes."""

    def setUp(self):
        self.enterContext(mock.patch.object(config, "HALT", os.path.join(self.enterContext(tempfile.TemporaryDirectory()), "no-HALT")))

    def _log(self, d02):
        rows = [dict(_row(T0, 100.0, b="buy"))] + _day_rows(1, lambda i: 100.0 + 0.01 * (i % 3))[1:]
        rows += d02
        rows += _day_rows(3, lambda i: 150.0 + 0.01 * (i % 3)) + _day_rows(4, lambda i: 150.0)[:8]   # d03 closes on d04's rows
        return rows

    def _cell(self, rows, c=900):
        out = report.render_v2([_store("SOL-USD", rows)], t0=T0, now=END + 86400)
        return out, out["cadence"]["cells"][(c, "b", "c", "argmax", 0.0)]

    def test_a_bad_day_with_priced_rows_takes_its_marks_with_it(self):
        # d02: every row priced at 150 (the jump lands on its first row), 10 of 96 rows a jev absence: BAD (> 5 %)
        d02 = _day_rows(2, lambda i: 150.0)
        for i in range(0, 96, 10):
            d02[i] = _row(report.tick_epoch(d02[i]["tick_id"]), 150.0, absence="jev")
        rows = self._log(d02)
        out, cell = self._cell(rows)
        self.assertEqual(out["recomputed"], {(2, "SOL-USD")})
        pnl = book.replay(book.at_cadence(rows, 900, T0), None, "b", "argmax", 0.0)["pnl_bps_per_tick"]
        kept = sum(v for t, v in pnl.items() if not T0 + 86400 <= report.tick_epoch(t) < T0 + 2 * 86400)
        jump = pnl[report._tick_of(T0 + 86400)]
        prev = rows[95]["mid"]                                                           # d01's last mid
        self.assertAlmostEqual(jump, (1000.0 / 100.01) * (150.0 - prev) * 1e4 / 1000.0, places=6)   # d02's first row carries the move
        self.assertEqual(cell["per"]["SOL-USD"]["n"], 2 * 96 + 8)                        # d01, d03 and d04's 8 blocks to the last tick
        self.assertEqual(len([k for k, _ in cell["S"] if 96 <= k < 192]), 0)            # no d02 block
        self.assertAlmostEqual(sum(v for _, v in cell["S"]), kept, places=9)             # C is flat: S is B's pnl
        # replaying without d02's rows would land the jump on d03's first tick, inside a kept block
        naive = book.replay(book.at_cadence([r for r in rows if not T0 + 86400 <= report.tick_epoch(r["tick_id"]) < T0 + 2 * 86400], 900, T0),
                            None, "b", "argmax", 0.0)["pnl_bps_per_tick"]
        self.assertGreater(abs(sum(naive.values()) - kept), 40.0)
        self.assertEqual(out["cadence"]["gap_blocks"][900]["SOL-USD"], [])              # d02 was priced: no gap
        # the position really differs across d02, at every cadence
        for c in config.CADENCES:
            pos = book.replay(book.at_cadence(rows, c, T0), None, "b", "argmax", 0.0)["position"]
            self.assertGreater(pos[report._tick_of(T0 + 86400 + 3600)], 0.0, c)
            self.assertEqual(book.replay(book.at_cadence(rows, c, T0), None, "c", "argmax", 0.0)["trades"], [], c)

    def test_a_day_with_no_row_lands_its_move_on_the_first_tick_after_it(self):
        rows = self._log([])                                                             # d02: no row at all
        out, cell = self._cell(rows)
        self.assertEqual(out["recomputed"], {(2, "SOL-USD")})                              # NO LIVE ROWS: excluded whole
        first = T0 + 2 * 86400
        pnl = book.replay(book.at_cadence(rows, 900, T0), None, "b", "argmax", 0.0)["pnl_bps_per_tick"]
        self.assertAlmostEqual(pnl[report._tick_of(first)], (1000.0 / 100.01) * (150.0 - rows[95]["mid"]) * 1e4 / 1000.0, places=6)
        self.assertAlmostEqual(dict(cell["S"])[192], pnl[report._tick_of(first)], places=9)   # in d03's first block, kept
        self.assertAlmostEqual(sum(v for _, v in cell["S"]), sum(pnl.values()), places=9)
        for c in config.CADENCES:
            self.assertEqual(out["cadence"]["gap_blocks"][c]["SOL-USD"], [int(2 * 86400 // c)], c)
        self.assertIn("gap_blocks (kept blocks holding the first priced tick after > 900 s without one): SOL-USD 1", out["text"])

    def test_pooled_blocks_take_the_kept_products_only(self):
        # two products, the same prices; ETH's d02 is excluded (no row), SOL's is kept: S-bar_k on d02 is SOL's alone
        add_products(self, 2)
        p2 = config.PRODUCTS[1]
        sol = self._log(_day_rows(2, lambda i: 150.0))
        eth = [dict(r, product=p2) for r in self._log([])]
        out = report.render_v2([_store("SOL-USD", sol), _store(p2, eth)], t0=T0, now=END + 86400)
        self.assertEqual(out["recomputed"], {(2, p2)})
        cell = out["cadence"]["cells"][(900, "b", "c", "argmax", 0.0)]
        S = dict(cell["S"])
        s_sol, s_eth = cell["S_p"]["SOL-USD"], cell["S_p"][p2]
        for k in (0, 50, 96, 150, 192, 250):
            want = s_sol.get(k, 0.0) if 96 <= k < 192 else (s_sol.get(k, 0.0) + s_eth.get(k, 0.0)) / 2
            self.assertAlmostEqual(S[k], want, places=12, msg=k)
        self.assertEqual(cell["per"][p2]["n"], cell["per"]["SOL-USD"]["n"] - 96)
        self.assertEqual(cell["n"], cell["per"]["SOL-USD"]["n"])                         # every block has a kept product


class SinceWithT0(unittest.TestCase):
    """--since cuts rows before the replay (its help: rows whose tick_id date is on or after the day), so with --t0
    the replay starts flat at the first row on or after --since, not at T0. The blocks that start before the cut
    hold no row, or only part of theirs, and are left out of n and every mean rather than counted as S_k = 0; the
    header says where the replay starts. 2026-09-29 refuter: --since 2026-10-26 kept n = 296 with 104 empty blocks."""

    def setUp(self):
        self.enterContext(mock.patch.object(config, "HALT", os.path.join(self.enterContext(tempfile.TemporaryDirectory()), "no-HALT")))

    def test_blocks_before_the_since_cut_leave_every_mean(self):
        rows = [r for day in (1, 2, 3) for r in _day_rows(day, lambda i: 100.0 + (i % 2), b="buy")]
        rows += _day_rows(4, lambda i: 100.0)[:8]
        full = _store("SOL-USD", rows)
        since = "2026-10-26"
        since_ep = report.tick_epoch("20261026T000000Z")                              # T0 + 26 h
        cut = dict(full, rows=[r for r in full["rows"] if r["tick_id"][:8] >= "20261026"])
        out = report.render_v2([cut], t0=T0, since=since, now=END + 86400)
        for c in config.CADENCES:
            first = -(-int(since_ep - T0) // c)                                          # the first block starting at or after the cut
            cell = out["cadence"]["cells"][(c, "b", "c", "argmax", 0.0)]
            ks = [k for k, _ in cell["S"]]
            self.assertEqual(ks[0], first, c)
            n_all = int((report.tick_epoch(rows[-1]["tick_id"]) - T0) // c) + 1
            self.assertEqual(cell["n"], n_all - first, c)
            self.assertEqual(cell["per"]["SOL-USD"]["n"], n_all - first, c)
            self.assertAlmostEqual(cell["mean"], sum(v for _, v in cell["S"]) / len(ks), places=12)
        self.assertEqual([k for k, _ in out["cadence"]["cells"][(900, "b", "c", "argmax", 0.0)]["S"]][0], 104)
        self.assertEqual([k for k, _ in out["cadence"]["cells"][(14400, "b", "c", "argmax", 0.0)]["S"]][0], 7)   # block 6 straddles
        head = out["text"].splitlines()[0]
        self.assertIn("each product replayed from flat at its first row on or after --since 2026-10-26", head)
        self.assertNotIn("replayed from flat at T0)", head)
        # without --since the header is unchanged and every block from 0 counts
        whole = report.render_v2([full], t0=T0, now=END + 86400)
        self.assertIn("each product replayed from flat at T0)", whole["text"].splitlines()[0])
        self.assertEqual(whole["cadence"]["cells"][(900, "b", "c", "argmax", 0.0)]["S"][0][0], 0)


class AStoppedLoop(unittest.TestCase):
    """The calendar does not stop with one product's loop: its days close on the latest tick any product's log has
    reached, so the days after its last row are NO LIVE ROWS, excluded whole (§9.3), and its blocks there dropped
    from the pool, not counted as S_k = 0 (report, status and dash alike)."""

    def test_the_days_after_a_stopped_logs_last_row_are_excluded(self):
        add_products(self, 2)
        p2 = config.PRODUCTS[1]
        self.enterContext(mock.patch.object(config, "HALT", os.path.join(self.enterContext(tempfile.TemporaryDirectory()), "no-HALT")))
        sol = [r for d in range(1, 6) for r in _day_rows(d, lambda i: 100.0)]
        eth = [dict(r, product=p2) for d in range(1, 3) for r in _day_rows(d, lambda i: 100.0)]   # stopped at d02's end
        out = report.render_v2([_store("SOL-USD", sol), _store(p2, eth)], t0=T0, now=END + 86400)
        self.assertEqual(out["recomputed"], {(3, p2), (4, p2)})                  # d05 is still open on SOL's log
        cell = out["cadence"]["cells"][(900, "b", "c", "argmax", 0.0)]
        self.assertEqual(cell["per"][p2]["n"], 2 * 96 + 96)                      # d01, d02 and open d05, not d03-d04
        from loop import status
        now = datetime.datetime.fromtimestamp(T0 + 6 * 86400, UTC)
        _, days = status._days(eth, outcomes.join(eth), T0, now, report.tick_epoch(sol[-1]["tick_id"]))
        self.assertEqual([x["day"] for x in days if x["empty"]], ["d03", "d04"])


class Void(unittest.TestCase):
    """§9.4: a product with fewer than 21 kept days leaves the pool, judged once every product's d28 has closed."""

    def test_a_product_with_twenty_kept_days_is_void_and_leaves_the_pool(self):
        add_products(self, 2)
        p2 = config.PRODUCTS[1]
        self.enterContext(mock.patch.object(config, "HALT", os.path.join(self.enterContext(tempfile.TemporaryDirectory()), "no-HALT")))

        def days(product, which):
            rows = []
            for d in which:                                   # a live row a day and a priced HALT row at its t + h (not live,
                a = T0 + 86400 * (d - 1) + 3600               # so the day's fill is 1/1)
                rows += [_row(a, 100.0, b="buy" if d == 1 else "hold", product=product),
                         _row(a + 900, 100.5, product=product, absence="halt")]
            return rows + [_row(END + 3600, 100.0, product=product)]
        stores = [_store("SOL-USD", days("SOL-USD", range(1, 29))), _store(p2, days(p2, range(1, 21)))]
        out = report.render_v2(stores, t0=T0, now=END + 86400)
        self.assertEqual(out["void"], {p2})
        self.assertEqual({n for n, p in out["recomputed"] if p == p2}, set(range(21, 29)))
        self.assertIn(f"{p2} 20 kept VOID", out["text"])
        cell = out["cadence"]["cells"][(900, "b", "c", "argmax", 0.0)]
        self.assertEqual(cell["per"][p2]["n"], 0)
        self.assertEqual(cell["n"], 28 * 96)
        self.assertEqual(dict(cell["S"]), {k: v for k, v in cell["S_p"]["SOL-USD"].items() if k < 28 * 96} | {
            k: 0.0 for k in range(28 * 96) if k not in cell["S_p"]["SOL-USD"]})
        # before d28 closes nothing is void
        early = report.render_v2([_store("SOL-USD", days("SOL-USD", range(1, 10))), _store(p2, days(p2, range(1, 5)))], t0=T0,
                                 now=T0 + 10 * 86400)
        self.assertEqual(early["void"], set())
        self.assertIn("not judged until every product's d28 has closed", early["text"])


class RowLevelDescriptivesTakeKeptRowsOnly(unittest.TestCase):
    """PREREG-v2 §2: an excluded product-day removes that product's blocks "(and its rows, for row-level
    descriptives) from every statistic"; §9.4: a void product leaves the pool. So A's agreement with C, arm D's
    Agreement(p, v) and its reading, §6's direction probabilities, §7's confidence table and trades/day read the
    rows of kept product-days of non-void products only. The replay still runs over every row (§4). 2026-09-29
    refuter: an excluded d02 on which D says sell while B holds turned D's LOOKUP into DRIFT (200/286)."""

    def setUp(self):
        self.enterContext(mock.patch.object(config, "HALT", os.path.join(self.enterContext(tempfile.TemporaryDirectory()), "no-HALT")))

    def _log(self, product="SOL-USD"):
        d02 = _day_rows(2, lambda i: 100.0, d="sell", a="buy", c="sell", product=product)   # D and B, A and C differ all day
        for i in range(0, 96, 10):                                                            # 10 of 96 jev errors: BAD
            d02[i] = _row(report.tick_epoch(d02[i]["tick_id"]), 100.0, absence="jev", product=product)
        return (_day_rows(1, lambda i: 100.0, product=product) + d02 + _day_rows(3, lambda i: 100.0, product=product)
                + _day_rows(4, lambda i: 100.0, product=product)[:8])

    def test_an_excluded_day_leaves_every_row_level_descriptive(self):
        rows = self._log()
        seen = {}

        def spy(name, fn):
            def wrapped(rs, *a, **k):
                seen.setdefault(name, []).append(sorted({int((report.tick_epoch(r["tick_id"]) - T0) // 86400) + 1 for r in rs}))
                return fn(rs, *a, **k)
            return wrapped
        for name in ("h2", "calibration", "agreement"):
            self.enterContext(mock.patch.object(report, name, spy(name, getattr(report, name))))
        out = report.render_v2([_store("SOL-USD", rows)], t0=T0, now=END + 86400)
        self.assertEqual(out["recomputed"], {(2, "SOL-USD")})
        da = out["d_agreement"]
        self.assertEqual(da["cells"][("SOL-USD", "v2")], {"n": 200, "agree": 200, "null": 0, "share": 1.0, "readable": True})
        self.assertTrue(da["reading"].startswith("LOOKUP"), da["reading"])
        sec4 = out["text"].split(report.TITLES_V2[3])[1].split(report.TITLES_V2[4])[0]
        self.assertIn("a.argmax == rule_c on 200/200 (100.0%)", sec4)
        self.assertNotIn("/286", sec4)
        for name in ("h2", "calibration", "agreement"):
            self.assertTrue(seen[name], name)
            for days in seen[name]:
                self.assertNotIn(2, days, name)                                         # no d02 row reaches it
        self.assertIn("left out of every row-level descriptive", sec4)
        # trades/day counts the kept days only: A's one buy is on d02 (excluded), so A trades 0 a day on kept ones
        tpd = out["cadence"]["trades_per_day"]
        for label in ("minute",) + tuple(config.CADENCES):
            self.assertEqual(tpd[label]["SOL-USD"]["a"], 0.0, label)
        # the replay itself still reads d02: A is long from d02's first decision row on
        pos = book.replay(book.at_cadence(rows, 900, T0), None, "a", "argmax", 0.0)["position"]
        self.assertGreater(pos[report._tick_of(T0 + 2 * 86400)], 0.0)

    def test_a_void_product_leaves_the_pooled_and_its_own_row_level_lines(self):
        add_products(self, 2)
        p2 = config.PRODUCTS[1]

        def days(product, which, a="hold"):
            rows = []
            for d in which:
                t = T0 + 86400 * (d - 1) + 3600
                rows += [_row(t, 100.0, product=product, a=a), _row(t + 900, 100.5, product=product, absence="halt")]
            return rows + [_row(END + 3600, 100.0, product=product)]
        stores = [_store("SOL-USD", days("SOL-USD", range(1, 29))), _store(p2, days(p2, range(1, 21), a="buy"))]
        out = report.render_v2(stores, t0=T0, now=END + 86400)
        self.assertEqual(out["void"], {p2})
        sec4 = out["text"].split(report.TITLES_V2[3])[1].split(report.TITLES_V2[4])[0]
        pooled = sec4.split(f"-- ")[0]
        self.assertIn("a.argmax == rule_c on 28/28 (100.0%)", pooled)                  # SOL's 28 rows, not p2's 20 buys
        self.assertIn(f"-- {p2}: void (PREREG-v2 §9.4, fewer than 21 kept days): its rows enter no statistic", sec4)
        self.assertNotIn(p2, "\n".join(l for l in out["d_agreement"]["lines"] if l.startswith("    ") and "product" not in l))
        for title in report.TITLES_V2[5:]:
            sec = out["text"].split(title)[1]
            self.assertIn(f"-- {p2}: void (PREREG-v2 §9.4, fewer than 21 kept days): its rows enter no statistic", sec)


class FeeArithmetic(unittest.TestCase):
    """PREREG-v2 §6's fee arithmetic, per product and cadence on the at_cadence replay, by hand at c = 900 (rows every
    900 s, so every row decides): E_X,p(f) = the sum of book.replay's pnl over the ticks of kept days, a fill counted
    when its tick is on a kept day; f*_X = 90 E(0) / (E(0) - E(90)); "never pays" at E(0) <= 0, undefined with no fill;
    a buy-and-hold line over the same span; the 30-day volume; tiers named when their taker is below f*; pairs
    Delta = E_X - E_Y = the sum of S_k over kept blocks, with f*_XY and its wording, never "pays".
    B (and D, its table) buys d01's first row at ask 100.01 and sells at row 50 at bid 104.99; on d02 (BAD, excluded)
    B buys and sells again, fills that do not count; A and C hold throughout."""
    N = config.NOTIONAL_USD

    def setUp(self):
        self.enterContext(mock.patch.object(config, "HALT", os.path.join(self.enterContext(tempfile.TemporaryDirectory()), "no-HALT")))
        d01 = _day_rows(1, lambda i: 100.0 if i < 50 else 105.0)
        d01[0] = _row(T0, 100.0, b="buy")
        d01[50] = _row(T0 + 50 * 900, 105.0, b="sell")
        d02 = _day_rows(2, lambda i: 150.0)
        for i in range(0, 96, 10):
            d02[i] = _row(report.tick_epoch(d02[i]["tick_id"]), 150.0, absence="jev")
        d02[1] = _row(report.tick_epoch(d02[1]["tick_id"]), 150.0, b="buy")
        d02[95] = _row(report.tick_epoch(d02[95]["tick_id"]), 150.0, b="sell")
        self.rows = d01 + d02 + _day_rows(3, lambda i: 150.0) + _day_rows(4, lambda i: 150.0)[:8]

    def _render(self, tiers=None):
        return report.render_v2([_store("SOL-USD", self.rows)], t0=T0, now=END + 86400, tiers=tiers)

    def test_each_arms_break_even_and_the_buy_and_hold_line_by_hand(self):
        out = self._render()
        self.assertEqual(out["recomputed"], {(2, "SOL-USD")})
        fa = out["cadence"]["fee_arithmetic"][900]
        qty = self.N / 100.01
        e0 = qty * (104.99 - 100.01) * 1e4 / self.N                                   # the round trip on d01, spread included
        slope = 1.0 + qty * 104.99 / self.N                                             # one buy (fee on NOTIONAL) + one sell (on qty x bid)
        for arm in ("b", "d"):
            x = fa["pooled"][arm]
            self.assertAlmostEqual(x["e0"], e0, places=9, msg=arm)
            self.assertAlmostEqual(x["e90"], e0 - 90.0 * slope, places=9, msg=arm)
            self.assertEqual(x["fills"], 2, arm)                                         # d02's two fills do not count
            self.assertAlmostEqual(x["fstar"], 90.0 * e0 / (90.0 * slope), places=9, msg=arm)
            self.assertEqual(fa["per"]["SOL-USD"][arm], x, arm)
        for arm in ("a", "c"):
            self.assertEqual((fa["pooled"][arm]["fills"], fa["pooled"][arm]["fstar"]), (0, None), arm)
            self.assertEqual(fa["pooled"][arm]["reading"], "undefined: no fill on a kept day", arm)
        self.assertAlmostEqual(fa["pooled"]["b"]["volume_30d"], (self.N + qty * 104.99) * 30 / (200 * 900 / 86400), places=6)
        # buy-and-hold: bought at T0's ask, marked to d01's last mid; d02's jump (105 -> 150) is on an excluded day
        bh = fa["pooled"]["buy-and-hold"]
        self.assertAlmostEqual(bh["e0"], qty * (105.0 - 100.01) * 1e4 / self.N, places=9)
        self.assertAlmostEqual(bh["e90"], bh["e0"] - 90.0, places=9)
        self.assertEqual(bh["fills"], 1)
        self.assertAlmostEqual(bh["fstar"], bh["e0"], places=9)
        text = out["text"]
        self.assertIn("fee arithmetic at 900 s (PREREG-v2 §6", text)
        self.assertIn(f"B  pooled: E(0) {e0:.3f}, E(90) {e0 - 90.0 * slope:.3f}, fills 2: f* {90.0 * e0 / (90.0 * slope):.2f} bps per fill", text)
        self.assertIn("C  pooled: E(0) 0.000, E(90) 0.000, fills 0: undefined: no fill on a kept day", text)
        for c in config.CADENCES:
            self.assertIn(f"fee arithmetic at {c} s (PREREG-v2 §6", text)
        # E(0) <= 0 with a fill: never pays (a round trip at an unchanged mid pays the spread)
        flat = [dict(r, mid=100.0, bid=99.99, ask=100.01) if r["mid"] is not None else r for r in self.rows]
        got = report.render_v2([_store("SOL-USD", flat)], t0=T0, now=END + 86400)["cadence"]["fee_arithmetic"][900]["pooled"]["b"]
        self.assertLess(got["e0"], 0.0)
        self.assertEqual((got["fstar"], got["reading"]), (None, "never pays: E(0) <= 0"))

    def test_pairs_are_sums_of_kept_blocks_and_read_by_f_star(self):
        out = self._render()
        fa = out["cadence"]["fee_arithmetic"]
        for c in config.CADENCES:
            for x, y in report.PAIRS:
                for f, key in ((0.0, "d0"), (90.0, "d90")):
                    pr = fa[c]["pairs"][(x, y)]
                    e = fa[c]["pooled"]
                    self.assertAlmostEqual(pr[key], e[x]["e" + key[1:]] - e[y]["e" + key[1:]], places=9, msg=(c, x, y))
                    cell = out["cadence"]["cells"].get((c, x, y, "argmax", f))
                    if cell is not None:                                               # 90 is a printed fee column once config has it
                        s = sum(v for k, v in cell["S_p"]["SOL-USD"].items() if not 96 * 900 // c <= k < 192 * 900 // c)
                        self.assertAlmostEqual(pr[key], s, places=9, msg=(c, x, y, f))
        bc = fa[900]["pairs"][("b", "c")]
        fs = 90.0 * bc["d0"] / (bc["d0"] - bc["d90"])
        self.assertAlmostEqual(bc["fstar"], fs, places=9)
        self.assertEqual(bc["reading"], f"B stops beating C above {fs:.2f} bps per fill")
        self.assertEqual(fa[900]["pairs"][("d", "b")]["reading"], "fees cancel: D and B tie at every fee")
        self.assertEqual(fa[900]["pairs"][("a", "c")]["reading"], "fees cancel: A and C tie at every fee")
        cb = report._pair_reading("c", "b", -bc["d0"], -bc["d90"])
        self.assertEqual(cb, (fs, f"C starts beating B above {fs:.2f} bps per fill"))
        self.assertEqual(report._pair_reading("b", "c", 0.0, -5.0), (0.0, "the sign of Delta(90) holds at every fee > 0: B trails C"))
        self.assertEqual(report._pair_reading("b", "c", 3.0, 3.0)[1], "fees cancel: B beats C at every fee")
        self.assertNotIn(" pays", "\n".join(l for l in out["text"].splitlines() if "Delta" in l))

    def test_cadence_table_prints_the_fee_columns_it_is_given(self):
        # PREREG-v2 §6's columns are (0, 2, 10, 25, 50, 90); config.FEE_BPS_COLUMNS stays v1's until the SPEC/config stage,
        # so loop.inference_v2 hands the table §6's columns, and the table prints those and no other
        per = {"SOL-USD": [r for r in self.rows if T0 <= report.tick_epoch(r["tick_id"]) < END]}
        kept = lambda p, k, c: (int(c * k // 86400) + 1, p) != (2, "SOL-USD")
        n_of = lambda c: int((report.tick_epoch(self.rows[-1]["tick_id"]) - T0) // c) + 1
        ct = report.cadence_table(per, T0, n_of, kept, ["SOL-USD"], True, fees=(0.0, 50.0, 90.0))
        self.assertEqual(ct["fees"], (0.0, 50.0, 90.0))
        self.assertEqual({key[4] for key in ct["cells"]}, {0.0, 50.0, 90.0})
        text = "\n".join(ct["lines"])
        self.assertIn("pair B-C  fee 90 bps", text)
        self.assertNotIn("fee 120 bps", text)
        default = report.cadence_table(per, T0, n_of, kept, ["SOL-USD"], True)
        self.assertEqual(default["fees"], report._fee_list())
        for key in ((900, "b", "c", "argmax", 0.0), (3600, "b", "a", "argmax", 0.0), ("minute", "b", "c", "argmax", 0.0)):
            self.assertEqual(ct["cells"][key]["S"], default["cells"][key]["S"], key)   # a column adds cells, changes none

    def test_tiers_from_section_12_or_errata_and_those_named(self):
        text = self._render()["text"]
        self.assertIn("fee tiers (PREREG-v2 §6.2): §12's table is blank until sealing; ERRATA.md's 2026-09-27 reading stands in", text)
        self.assertIn("maker 50 bps / taker 90 bps; round trip 2 x taker 180 bps; 2 x maker 100 bps needs a passive-fill model"
                      " not measured here", text)
        tiers = {"read": "2026-10-24T21:00Z", "tiers": [
            {"name": "Intro 1", "band": "$0-$10K", "low": 0.0, "high": 1e4, "maker": 60.0, "taker": 120.0},
            {"name": "Intro 2", "band": "$10K-$50K", "low": 1e4, "high": 5e4, "maker": 25.0, "taker": 40.0},
            {"name": None, "band": "$50K+", "low": 5e4, "high": None, "maker": 15.0, "taker": 300.0}]}
        out = self._render(tiers)
        fa = out["cadence"]["fee_arithmetic"][900]
        self.assertEqual([t["band"] for t in fa["named"]["b"]], ["$0-$10K", "$10K-$50K"])      # 120 and 40 < f*_B ~ 242.9
        self.assertEqual(fa["named"]["c"], [])                                                # f*_C undefined
        self.assertEqual([t["band"] for t in fa["named"]["buy-and-hold"]], ["$0-$10K", "$10K-$50K", "$50K+"])   # 300 < f*_BH ~ 499
        self.assertIn("§12's table, read UTC 2026-10-24T21:00Z", out["text"])
        self.assertIn("it differs from ERRATA.md's 2026-09-27 reading", out["text"])        # Intro 1 is 60/120 here, not 50/90
        self.assertIn("Intro 1 $0-$10K", out["text"])
        err = self._render({"error": "PREREG-v2 §12's fee-tier row 'x' is not ..."})["text"]
        self.assertIn("fee tiers (PREREG-v2 §6.2): §12's table REFUSED, fix before day 28: PREREG-v2 §12's fee-tier row 'x'", err)


class DAgreement(unittest.TestCase):
    """§6: Agreement(p, v), its denominator and null count; a null marks the cell a defect; the three readings."""

    def _rows(self, spec, product="SOL-USD"):
        out = []
        for i, (v, b, d) in enumerate(spec):
            r = _row(T0 + 60 * i, 100.0, b=b, d=d, product=product)
            r["prompt_b"], r["state"] = v, f"S{i % 2}"
            out.append(r)
        return out

    def test_cells_and_readings(self):
        agree = [("v2", "buy", "buy")] * 199 + [("v2", "buy", "sell")]                   # 0.995
        got = report.d_agreement({"SOL-USD": self._rows(agree)})
        self.assertEqual(got["cells"][("SOL-USD", "v2")], {"n": 200, "agree": 199, "null": 0, "share": 0.995, "readable": True})
        self.assertTrue(got["reading"].startswith("LOOKUP"))
        drift = self._rows([("v3", "buy", "buy")] * 9 + [("v3", "sell", "buy")], "X-USD")      # 0.9
        got = report.d_agreement({"SOL-USD": self._rows(agree), "X-USD": drift})
        self.assertTrue(got["reading"].startswith("DRIFT"))
        between = self._rows([("v2", "buy", "buy")] * 97 + [("v2", "buy", "hold")] * 3)          # 0.97
        self.assertTrue(report.d_agreement({"SOL-USD": between})["reading"].startswith("between"))
        # a null columns.d on a live row: the cell is a table defect and is not read (so the drift cell is not either)
        defect = self._rows([("v3", "buy", "buy")] * 9 + [("v3", "sell", None)], "X-USD")
        got = report.d_agreement({"SOL-USD": self._rows(agree), "X-USD": defect})
        self.assertEqual(got["cells"][("X-USD", "v3")], {"n": 9, "agree": 9, "null": 1, "share": 1.0, "readable": False})
        self.assertTrue(got["reading"].startswith("LOOKUP"))
        self.assertIn("TABLE DEFECT", "\n".join(got["lines"]))
        self.assertTrue(report.d_agreement({"X-USD": defect})["reading"].startswith("D NOT READ: table defect"))
        # absences and v1-era rows (no columns.d key) are not in any cell; v1 rows are counted as left out
        v1 = [dict(r, columns={"a": r["columns"]["a"], "b": r["columns"]["b"]}) for r in self._rows(agree[:5])]
        absent = [_row(T0, 100.0, absence="jev")]
        got = report.d_agreement({"SOL-USD": v1 + absent})
        self.assertEqual((got["cells"], got["v1_rows"]), ({}, 5))
        self.assertIn("live rows without columns.d (v1-era rows, not v2's) left out: 5", "\n".join(got["lines"]))

    def test_within_state_consistency_and_the_modal_answer(self):
        rows = self._rows([("v2", "buy", "buy")] * 12 + [("v2", "sell", "buy")] * 12)   # S0 and S1 alternate
        for r in rows[:12]:
            r["state"] = "S0"                                                          # S0: 12 buys, table buy
        for r in rows[12:]:
            r["state"] = "S1"                                                          # S1: 12 sells, table buy: differs
        got = report.d_agreement({"SOL-USD": rows})
        self.assertEqual((got["consistency"], got["seen"], got["differ"]), (1.0, 2, 1))


class Withheld(unittest.TestCase):
    """PREREG-v2 §9.5 and §10's tests bullet: over tests/synth.py's three-product log the report withholds §4-§7 with
    no flags, with --t0 T0_v2 and with --since; T0_v2 is read from PREREG-v2.md §12 whatever the flags; blank, it
    withholds every row carrying the v2 spec_sha; v1's withholding is kept beside it; --unblind is a look, appended
    to data/looks.tsv."""
    DAY1 = T0 + 86400 + 3600

    @classmethod
    def setUpClass(cls):
        cls.products = add_products(cls)
        pin_prereg(cls)                                                   # v1's §11 (its sample ended 2026-10-23)
        cls.data = cls.enterClassContext(tempfile.TemporaryDirectory())
        cls.enterClassContext(mock.patch.object(config, "DATA", cls.data))
        cls.enterClassContext(mock.patch.object(config, "DECISIONS", os.path.join(cls.data, "decisions.jsonl")))
        cls.enterClassContext(mock.patch.object(config, "HALT", os.path.join(cls.data, "HALT")))
        logs = synth.generate_products(5, cls.products, t0=T0S, days=1.0, pre_hours=2.0, cadence_s=300, era="v2",
                                       promotions_h=(6.0,))
        cls.paths = synth.write_products(cls.data, logs)
        cls.sha = synth._spec_sha()                                       # what every v2-era synthetic row carries

    def _run(self, argv, now, t0_v2=T0S, sha=None):
        with contextlib.ExitStack() as st:
            pin_prereg_v2(st, t0_v2, self.sha if sha is None else sha)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = report.main(argv, now=now)
        return code, out.getvalue(), err.getvalue()

    def _blind(self, out):
        for t in report.TITLES_V2[:3]:
            self.assertIn(t, out)
        for t in report.TITLES_V2[3:]:
            self.assertNotIn(t, out)
        for word in ("pair B-C", "H1 cell", "Agreement(p, v)", "a.argmax == rule_c", "mean_S", "Pearson", "Brier", "P(correct)", "cadence 900"):
            self.assertNotIn(word, out)

    def test_no_flags_t0_and_since_all_withhold_on_three_products(self):
        for argv in ([], ["--t0", T0S], ["--since", "2026-10-25"], ["--t0", "2026-10-24T22:00", "--since", "2026-10-24"],
                     ["--prereg", "/nonexistent/PREREG.md"], ["--sample"]):
            with self.subTest(argv=argv):
                code, out, err = self._run(argv, self.DAY1)
                self.assertEqual(code, 0)
                self.assertIn("sections 4-7 WITHHELD until 2026-11-21T22:00Z", out)
                self.assertIn("(T0_v2 from PREREG-v2.md §12, whatever --t0, --since or --log say, §9.5)", out)
                for p in self.products:
                    self.assertIn(f"-- {p}", out)
                self.assertIn("pooled over 3 products", out)
                self._blind(out)
                self.assertEqual(err, "")
        # --log on one product's store is v1's report, and PREREG-v2's withholding holds there too
        code, out, err = self._run(["--log", self.paths[self.products[2]]], self.DAY1)
        self.assertIn("WITHHELD until 2026-11-21T22:00Z", out)
        for t in report.TITLES[3:]:
            self.assertNotIn(t, out)
        self.assertNotIn("pair B-C", out)
        # --health is the look that needs no notice
        code, out, err = self._run(["--health"], self.DAY1)
        self.assertNotIn("WITHHELD", out)
        self.assertIn("health only", out)
        self._blind(out)

    def test_a_blank_t0_v2_withholds_every_row_carrying_the_v2_spec_sha(self):
        for argv in ([], ["--t0", T0S], ["--since", "2026-10-25"]):
            code, out, err = self._run(argv, END + 86400, t0_v2=None)           # no clock lifts it
            self.assertIn("WITHHELD: PREREG-v2.md §12's T0_v2 is blank and", out)
            self.assertIn(f"carry the v2 spec_sha ({self.sha[:12]}...)", out)
            self._blind(out)
        code, out, err = self._run([], END + 86400, t0_v2=None, sha="some-other-spec")   # no row carries it
        self.assertNotIn("WITHHELD", out)
        self.assertIn("pair B-C", out)
        with self.assertRaises(SystemExit) as cm:                              # --sample needs §12's T0_v2
            self._run(["--sample"], self.DAY1, t0_v2=None)
        self.assertEqual(cm.exception.code, 2)

    def test_a_malformed_seal_withholds_as_blank_and_says_so(self):
        code, out, err = self._run([], self.DAY1, t0_v2="2026-10-24T22:00Z")
        self.assertIn("T0_v2 is blank", out)
        self.assertIn("is not a tick_id on a minute boundary", err)
        self._blind(out)

    def test_main_reads_the_fee_tiers_from_section_12(self):
        # PREREG-v2 §10: report reads the fee-tier table from PREREG-v2.md §12 (dash.read_fee_tiers), whatever the flags
        def run(field):
            with contextlib.ExitStack() as st:
                path = pin_prereg_v2(st, T0S, self.sha)
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text.replace("\n## 13.", f"\nFee tiers (30-day band / maker / taker, read UTC {field}\n## 13."))
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(report.main(["--t0", T0S], now=END), 0)
            return out.getvalue()
        out = run("`2026-10-24T21:00Z`): `Intro 1: $0-$10K / 0.60% / 1.20%; $10K+ / 0.25% / 0.40%`")
        self.assertIn("fee tiers (PREREG-v2 §6.2): §12's table, read UTC 2026-10-24T21:00Z", out)
        self.assertIn("Intro 1 $0-$10K: maker 60 bps / taker 120 bps", out)
        self.assertIn("fee arithmetic at 900 s (PREREG-v2 §6", out)
        out = run("`________`): `________`")
        self.assertIn("§12's table is blank until sealing", out)
        out = run("`2026-10-24T21:00Z`): `Intro 1: $0-$10K / 0.60 / 1.20`")
        self.assertIn("§12's table REFUSED, fix before day 28: PREREG-v2 §12's fee-tier row 'Intro 1: $0-$10K / 0.60 / 1.20'", out)
        # health only computes none of it
        with contextlib.ExitStack() as st:
            pin_prereg_v2(st, T0S, self.sha)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                report.main(["--health", "--t0", T0S], now=END)
        self.assertNotIn("fee tiers", out.getvalue())
        self.assertNotIn("fee arithmetic", out.getvalue())

    def test_after_the_sample_it_prints_and_before_t0_v2_shakedown_rows_print(self):
        code, out, err = self._run(["--t0", T0S], END)
        self.assertNotIn("WITHHELD", out)
        for t in report.TITLES_V2:
            self.assertIn(t, out)
        self.assertIn("pair B-C  fee 0 bps  [* H1 cell, PREREG-v2 §5]", out)
        self.assertIn("pair D-B  fee 0 bps", out)
        self.assertIn("[F4, PREREG-v2 §6]", out)
        self.assertIn("the H1 and family-F bounds are loop.inference_v2's (make results), at day 28", out)
        self.assertIn("Agreement(p, v)", out)
        # the shakedown before T0_v2: a --since that keeps no sample row, on a clock inside the sample, is not withheld
        code, out, err = self._run(["--since", "2026-11-30"], self.DAY1)
        self.assertNotIn("WITHHELD", out)

    def test_unblind_is_a_look_appended_to_looks_tsv(self):
        looks = os.path.join(self.data, "looks.tsv")
        if os.path.exists(looks):
            os.remove(looks)
        code, out, err = self._run(["--unblind", "--t0", T0S], self.DAY1)
        self.assertEqual(code, 0)
        self.assertNotIn("WITHHELD", out)
        self.assertIn("Agreement(p, v)", out)
        self.assertIn("report: --unblind: sections 4-7 printed on PREREG-v2's withheld rows; this is a look (PREREG-v2 §9.5)", err)
        with open(looks, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(lines[0], "utc\targv\thead")
        utc, argv, head = lines[1].split("\t")
        self.assertEqual((utc, argv), ("2026-10-25T23:00:00Z", f"python3 -m loop.report --unblind --t0 {T0S}"))
        self.assertTrue(head == "unknown" or len(head) in (40, 64))
        self._run(["--unblind"], self.DAY1)                                    # a second look is a second line
        with open(looks, encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().splitlines()), 3)

    def test_unblind_is_a_look_whatever_it_lifts(self):
        # §9.5: "`report --unblind` is a look: it appends (UTC, argv, HEAD) to data/looks.tsv", with no condition. It is
        # recorded when nothing was withheld too (2026-09-29 refuter: with §12 blank and SPEC still v1's, --unblind
        # printed everything and recorded nothing), and a look that cannot be recorded is still refused.
        looks = os.path.join(self.data, "looks.tsv")
        if os.path.exists(looks):
            os.remove(looks)

        def n_lines():
            with open(looks, encoding="utf-8") as fh:
                return len(fh.read().splitlines())
        code, out, err = self._run(["--unblind", "--t0", T0S], END)           # the sample has ended: nothing is withheld
        self.assertEqual(code, 0)
        self.assertIn("pair B-C", out)
        self.assertEqual(n_lines(), 2)
        self.assertIn("report: --unblind: nothing read here was withheld; the look is recorded all the same (PREREG-v2 §9.5)", err)
        self.assertIn(f"report: --unblind: recorded in {looks}: ", err)
        self._run(["--unblind"], END + 86400, t0_v2=None, sha="some-other-spec")   # §12 blank, no row carries the v2 sha
        self.assertEqual(n_lines(), 3)
        code, out, err = self._run(["--unblind", "--health"], self.DAY1)      # health only: still a look
        self.assertEqual(code, 0)
        self.assertIn("health only", out)
        self.assertEqual(n_lines(), 4)
        with mock.patch.object(config, "DATA", os.path.join(self.data, "no-such-dir")):
            code, out, err = self._run(["--unblind", "--t0", T0S], END)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("the look cannot be recorded", err)
        self.assertEqual(n_lines(), 4)


class V1InferenceWithholdsV2(unittest.TestCase):
    """PREREG-v2 §10 ("no reader prints §4-§7 over a v2 sample row before T0_v2 + 28 d") and §9.5 ("whatever --t0 ...
    or --log say"; "No bootstrap runs before day 28"): v1's loop.inference, which stays in this tree, refuses (exit 3)
    before any bootstrap when the rows it would read hold one PREREG-v2 withholds, whatever its own --t0 and --log say.
    2026-09-29 lens-2 review: a copy of the live log and a --t0 28 days before T0_v2 printed B - C's bound over v2 sample
    rows. v1's rows (before T0_v2, v1's spec_sha) are unaffected."""

    @classmethod
    def setUpClass(cls):
        cls.products = add_products(cls)
        pin_prereg(cls)                                                   # v1's §11: its sample ended 2026-10-23
        cls.data = cls.enterClassContext(tempfile.TemporaryDirectory())
        cls.enterClassContext(mock.patch.object(config, "DATA", cls.data))
        cls.enterClassContext(mock.patch.object(config, "DECISIONS", os.path.join(cls.data, "decisions.jsonl")))
        logs = synth.generate_products(5, cls.products, t0=T0S, days=1.0, pre_hours=2.0, cadence_s=300, era="v2")
        paths = synth.write_products(cls.data, logs)
        cls.copy = os.path.join(cls.enterClassContext(tempfile.TemporaryDirectory()), "copy.jsonl")
        with open(paths["SOL-USD"], encoding="utf-8") as src, open(cls.copy, "w", encoding="utf-8") as dst:
            dst.write(src.read())                                         # a copy of the live log is not the live log
        cls.sha = synth._spec_sha()

    def _run(self, t0, t0_v2, now):
        from loop import inference
        with contextlib.ExitStack() as st:
            pin_prereg_v2(st, t0_v2, self.sha)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = inference.main(["--sample", "--log", self.copy, "--t0", t0, "--resamples", "20", "--accept-pending"],
                                      now=datetime.datetime.fromtimestamp(now, UTC))
        return code, out.getvalue(), err.getvalue()

    def test_a_window_holding_v2_sample_rows_is_refused_sealed_or_blank(self):
        # v1's window [2026-09-27T22:00, 2026-10-25T22:00) holds the first sample day of T0_v2 2026-10-24T22:00Z
        for t0_v2 in (T0S, None):
            with self.subTest(t0_v2=t0_v2):
                code, out, err = self._run("2026-09-27T22:00", t0_v2, T0 + 2 * 86400)
                self.assertEqual(code, 3, err)
                self.assertEqual(out, "")
                self.assertIn("inference: refusing to look:", err)
                self.assertIn("PREREG-v2 §9.5", err)

    def test_v1_rows_and_v2_shakedown_rows_before_a_sealed_t0_v2_still_run(self):
        # a window ending at T0_v2 holds only the shakedown's two hours: not PREREG-v2's sample once §12 is sealed
        code, out, err = self._run("2026-09-26T22:00", T0S, T0 + 2 * 86400)
        self.assertEqual(code, 0, err)
        self.assertIn("B - C", out)
        # after the v2 sample has ended nothing is withheld
        code, out, err = self._run("2026-09-27T22:00", T0S, END)
        self.assertEqual(code, 0, err)


class MakeHealth(unittest.TestCase):
    """PREREG-v2 §2: the v1 stream's rows between v1's end (2026-10-23 21:40Z) and T0_v2 "are logged and reported by
    `make health`", which §9.5 also makes the day-14 look (report §1-§3 per product and pooled over the sample).
    `make health` is `loop.report --health --pre-sample --sample`: the rows before the sample first, [v1's T0 + 28 d,
    T0_v2), then the sample's; while §12 is blank, every row from v1's end and a line that there is no sample yet, exit 0
    (2026-09-29 lens-3 review: `report --health --sample` dropped every row before T0_v2 and exited 2 while blank)."""

    @classmethod
    def setUpClass(cls):
        cls.products = add_products(cls)
        pin_prereg(cls)                                                   # v1's §11: its sample ended 2026-10-23T21:40Z
        cls.data = cls.enterClassContext(tempfile.TemporaryDirectory())
        cls.enterClassContext(mock.patch.object(config, "DATA", cls.data))
        cls.enterClassContext(mock.patch.object(config, "DECISIONS", os.path.join(cls.data, "decisions.jsonl")))
        cls.enterClassContext(mock.patch.object(config, "HALT", os.path.join(cls.data, "HALT")))
        logs = synth.generate_products(3, cls.products, t0=T0S, days=1.0, pre_hours=26.5, cadence_s=300, era="v2")
        paths = synth.write_products(cls.data, logs)
        cls.ticks = {}
        for p, path in paths.items():
            with open(path, encoding="utf-8") as fh:
                cls.ticks[p] = [report.tick_epoch(json.loads(l)["tick_id"]) for l in fh if l.strip()]
        cls.v1_end = report.tick_epoch("20261023T214000Z")

    def _run(self, argv, t0_v2):
        with contextlib.ExitStack() as st:
            pin_prereg_v2(st, t0_v2, synth._spec_sha())
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = report.main(argv, now=T0 + 86400 + 3600)
        return code, out.getvalue(), err.getvalue()

    def _n(self, p, lo, hi=None):
        return sum(1 for t in self.ticks[p] if t >= lo and (hi is None or t < hi))

    def test_the_makefile_target(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Makefile"), encoding="utf-8") as fh:
            make = fh.read()
        recipe = make.split("\nhealth:\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(recipe.strip(), "$(PY) -m loop.report --health --pre-sample --sample")

    def test_the_rows_before_the_sample_then_the_sample(self):
        self.assertTrue(min(self.ticks["SOL-USD"]) < self.v1_end)              # the log starts inside v1's sample
        code, out, err = self._run(["--health", "--pre-sample", "--sample"], T0S)
        self.assertEqual((code, err), (0, ""))
        pre, _, samp = out.partition("== PREREG-v2's sample [T0_v2 2026-10-24T22:00Z, T0_v2 + 28 d)")
        self.assertTrue(pre.startswith("== the rows before PREREG-v2's sample (PREREG-v2 §2: the v1 stream after v1's sample, the"
                                       " switch and the shakedown): tick_id from 2026-10-23T21:40Z (v1: PREREG.md §11 T0 + 28 d)"
                                       " up to T0_v2 2026-10-24T22:00Z (PREREG-v2.md §12)\n"), pre[:300])
        for p in self.products:
            self.assertIn(f"  {p}: {config.store(p).decisions}, {self._n(p, self.v1_end, T0)} rows,", pre)
            self.assertIn(f"  {p}: {config.store(p).decisions}, {self._n(p, T0)} rows,", samp)
        for part in (pre, samp):
            self.assertIn("health only", part)
            self.assertNotIn(report.TITLES_V2[3], part)

    def test_while_section_12_is_blank_every_row_from_v1s_end_and_no_sample_yet(self):
        code, out, err = self._run(["--health", "--pre-sample", "--sample"], None)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("up to the last row (PREREG-v2.md §12 T0_v2 blank)", out)
        for p in self.products:
            self.assertIn(f"  {p}: {config.store(p).decisions}, {self._n(p, self.v1_end)} rows,", out)
        self.assertTrue(out.endswith("== PREREG-v2's sample: none yet: PREREG-v2.md §12's T0_v2 is blank (not sealed)\n"), out[-300:])
        with self.assertRaises(SystemExit) as cm:                              # --sample alone still needs §12
            self._run(["--health", "--sample"], None)
        self.assertEqual(cm.exception.code, 2)
        with self.assertRaises(SystemExit):
            self._run(["--pre-sample", "--t0", T0S], T0S)

    def test_without_health_the_withholding_holds_on_each_part(self):
        code, out, err = self._run(["--pre-sample", "--sample"], T0S)
        self.assertEqual(code, 0)
        pre, _, samp = out.partition("== PREREG-v2's sample")
        self.assertNotIn("WITHHELD", pre)                                      # shakedown rows are not the sample
        self.assertIn("sections 4-7 WITHHELD until 2026-11-21T22:00Z", samp)
        self.assertNotIn(report.TITLES_V2[3], out)


if __name__ == "__main__":
    unittest.main()

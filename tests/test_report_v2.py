"""PREREG-v2's report (loop/report.py without --log): every product's store, per product and pooled, the cadences
through book.at_cadence, the recomputed stop rule 3, arm D's agreement, gap_blocks, and the withholding of §9.5,
which reads T0_v2 from PREREG-v2.md §12 whatever the flags say. Offline: synthetic logs (tests/synth.py) and
hand-built rows in temp directories; the live data/, HALT and looks.tsv are never touched."""
import contextlib, datetime, io, os, tempfile, unittest
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

    def test_after_the_sample_it_prints_and_before_t0_v2_shakedown_rows_print(self):
        code, out, err = self._run(["--t0", T0S], END)
        self.assertNotIn("WITHHELD", out)
        for t in report.TITLES_V2:
            self.assertIn(t, out)
        self.assertIn("pair B-C  fee 0 bps  [* H1 cell, PREREG-v2 §5]", out)
        self.assertIn("pair D-B  fee 0 bps", out)
        self.assertIn("[F4, PREREG-v2 §6]", out)
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


if __name__ == "__main__":
    unittest.main()

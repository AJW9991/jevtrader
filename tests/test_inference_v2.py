"""loop/inference_v2.py, PREREG-v2's day-28 inference: its refusals, stop rules 1-4 (an excluded day between kept days,
NO PROMOTION, void), RESULTS-v2 §0, the fee arithmetic on a hand-built book, and a run end to end through main. The draw,
the bound and the pooled statistic are held to transcriptions of the text in tests/test_invariants.py; this module holds
the behaviour. Offline: hand-built rows every 900 s (so each row's t + h is the next row) in memory or in temp
directories; the live data/, HALT and looks.tsv are never touched."""
import contextlib, datetime, hashlib, io, json, os, subprocess, sys, tempfile, unittest
from unittest import mock

from fixture_prereg import pin_prereg_v2
from fixture_products import add_products
from loop import book, config, dash, inference, inference_v2, report, rules

T0S = "20261024T220000Z"                 # a stand-in T0_v2 (§12 is filled at sealing)
T0 = report.tick_epoch(T0S)
END = T0 + 28 * 86400
AFTER = END + 86400                      # a clock a day after the sample
UTC = datetime.timezone.utc
SHA = "spec-v2-fixture"
R = 80                                   # resamples in these tests (the bootstrap is most of a run): sorted[1] at 1/40, [0] at 1/160
R_MAIN = 200                             # main's: sorted[4] at 1/40, sorted[1] at 1/160
QTY = 1000.0 / 100.01                    # a buy at mid 100 fills at the ask 100.01
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _iso(epoch, ms=100):
    return datetime.datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def _row(epoch, mid, b="hold", c="hold", a="hold", d="same", absence=None, product="SOL-USD", promoted=False, spec=SHA):
    """A v2-era row reduced to what the readers read: A, B and C's intents on every column, D the table's (by default B's
    own argmax), priced 1c either side of `mid`; `promoted`: B asks v3 (prompt_b_sha != prompt_a_sha); an absence row
    carries no columns."""
    cols = {"a": {k: a for k in rules.COLUMNS}, "b": {k: b for k in rules.COLUMNS}, "d": b if d == "same" else d}
    if absence is not None:
        cols = {"a": None, "b": None, "d": None}
    return {"v": 1, "tick_id": report._tick_of(epoch), "ts_rx": _iso(epoch), "mode": "live", "product": product,
            "bid": mid - 0.01, "ask": mid + 0.01, "mid": mid, "spec_sha": spec, "prompt_a": "v2", "prompt_a_sha": "A",
            "prompt_b": "v3" if promoted else "v2", "prompt_b_sha": "B3" if promoted else "A", "table_sha": "T",
            "model_answered": config.MODEL, "drift": False,
            "jev": {"latency_ms": 500, "input_tokens": 100, "error": "timeout" if absence == "jev" else None, "key_path": "loop"},
            "answers": None, "rule_c": c, "columns": cols, "absence": absence}


def _log(product="SOL-USD", days=range(1, 29), mid=lambda n: 100.0, row=None, post=3):
    """Rows every 900 s over the T0_v2-anchored days `days` (1 = d01), then `post` rows after the sample (3 close d28: its
    last row's t + h, and a tick past T0_v2 + 28 d + 930 s). Row n sits at T0 + 900 n with mid(n); row(n) gives _row's
    other arguments, or None for no row at all."""
    ns = [n for d in days for n in range(96 * (d - 1), 96 * d)] + list(range(96 * 28, 96 * 28 + post))
    out = []
    for n in ns:
        kw = (row or (lambda n: {}))(n)
        if kw is not None:
            out.append(_row(T0 + 900 * n, mid(n), product=product, **kw))
    return out


def _store(product, rows):
    return {"product": product, "log": f"<{product}>", "missing": False, "rows": rows, "bad": [], "sha": "x", "bytes": 0}


def _run(*stores, **kw):
    kw.setdefault("descriptive", False)
    return inference_v2.run(list(stores), T0, AFTER, resamples=R, **kw)


def _rising(n):
    return 100.0 + 0.05 * n                 # B long from the first row earns ~5 bps a block


def _b_buys(n):
    return {"b": "buy" if n == 0 else "hold", "promoted": True}


class ExcludedDayBetweenKeptDays(unittest.TestCase):
    """PREREG-v2 §4, §10's test: the replay runs from flat at T0_v2 over every sample row, excluded days included; an
    excluded product-day's blocks are dropped afterwards; a position carried into it is marked on its priced rows, and
    where it has none the move lands on the first priced tick after it, in a kept block that stays kept (gap_blocks).
    B buys on d01's first row and holds, A and C never trade: the arms' positions differ across d02, and d02's jump
    (100 -> 150) is the whole of what dropping it removes."""

    @staticmethod
    def mid(n):
        return 100.0 if n < 96 else 150.0

    def test_a_day_with_no_row_is_excluded_and_its_move_lands_on_the_next_kept_block(self):
        rows = _log(days=[1] + list(range(3, 29)), mid=self.mid, row=_b_buys)
        out = _run(_store("SOL-USD", rows))
        self.assertEqual(out["excluded"], {(2, "SOL-USD")})                              # NO LIVE ROWS: excluded whole
        self.assertEqual(out["kept_days"]["SOL-USD"], 27)
        jump = QTY * (150.0 - 100.0) * 1e4 / 1000.0                                      # B's move across d02, in bps of NOTIONAL
        for name, c in (("H1", 900), ("F1", 3600), ("F2", 14400)):
            S = dict(out["cells"][name]["series"])
            k = 2 * 86400 // c                                                           # d03's first block
            self.assertEqual(len(S), 27 * 86400 // c, name)
            self.assertFalse([j for j in S if 86400 // c <= j < k], name)                # no d02 block
            self.assertAlmostEqual(S[k], jump, places=6, msg=name)                        # the move, in d03's first block
            self.assertAlmostEqual(sum(S.values()), jump - QTY * 0.01 * 1e4 / 1000.0, places=6, msg=name)   # less the spread paid
            self.assertEqual(out["gaps"][c]["SOL-USD"], [k], name)
            pos = book.replay(book.at_cadence(report.in_sample(rows, T0), c, T0), None, "b", "argmax", 0.0)["position"]
            self.assertGreater(pos[report._tick_of(T0 + 2 * 86400)], 0.0, name)          # B carried long across d02; C flat
        self.assertIn("    900 s: SOL-USD 1; pooled blocks holding one 1",
                      "\n".join(inference_v2.power_lines(out["cells"], out["pool"], out["excluded"], out["gaps"])))

    def test_a_bad_day_with_priced_rows_takes_its_marks_with_it(self):
        # d02 priced at 150 (the jump lands on its first row), 10 of its 96 rows a jev absence: BAD (> 5 %), excluded
        def row(n):
            if 96 <= n < 192 and (n - 96) % 10 == 5:
                return {"absence": "jev"}
            return _b_buys(n)
        rows = _log(mid=self.mid, row=row)
        out = _run(_store("SOL-USD", rows))
        self.assertEqual(out["excluded"], {(2, "SOL-USD")})
        S = dict(out["cells"]["H1"]["series"])
        self.assertFalse([k for k in S if 96 <= k < 192])
        self.assertAlmostEqual(sum(S.values()), -QTY * 0.01 * 1e4 / 1000.0, places=6)    # the jump went with d02; the spread stays
        self.assertEqual(out["gaps"][900]["SOL-USD"], [])                                 # d02 was priced: no gap
        # replaying without d02's rows (the reading §4 rules out) would land the jump on d03, inside a kept block
        naive = [r for r in report.in_sample(rows, T0) if not T0 + 86400 <= report.tick_epoch(r["tick_id"]) < T0 + 2 * 86400]
        pnl = book.replay(book.at_cadence(naive, 900, T0), None, "b", "argmax", 0.0)["pnl_bps_per_tick"]
        self.assertGreater(sum(pnl.values()), 4000.0)


class NoPromotion(unittest.TestCase):
    """§9.2: when no live row on a kept product-day of a non-void product has prompt_b_sha != prompt_a_sha, stop rule 2
    reads NO PROMOTION, F4 is withdrawn (neither bootstrapped nor read) and B - A is test-retest; §11: an H1 rejection then
    reads as the frozen v2 wording, never as the rewrite. The row set is exactly that: a promotion on an excluded day, on a
    void product or on a row that is not live does not count."""

    def setUp(self):
        self.products = add_products(self, 2)

    def _sol(self, promote=None):
        """B buys on the first row, the price rises: H1 rejects. promote(n): the rows that carry a promoted B."""
        return _log(mid=_rising, row=lambda n: {"b": "buy" if n == 0 else "hold", "promoted": bool(promote and promote(n))})

    def test_no_promoted_row_reads_no_promotion(self):
        out = _run(_store("SOL-USD", self._sol()))
        self.assertEqual(out["promoted"], 0)
        self.assertEqual(out["rules"]["rule2"], "NO PROMOTION")
        f4 = out["cells"]["F4"]
        self.assertEqual((f4["withdrawn"], f4["lower"], f4["reject"]), (True, None, None))
        self.assertGreater(f4["mean"], 0.0)                                               # printed, as test-retest
        self.assertTrue(out["cells"]["H1"]["reject"])
        text = out["text"]
        self.assertIn("-> NO PROMOTION (CURRENT never left v2): F4 is withdrawn, B - A is test-retest", text)
        self.assertIn("WITHDRAWN: NO PROMOTION (§9.2): not bootstrapped and not read", text)
        self.assertIn("stop rule 2 (§9.2): NO PROMOTION: no live row on a kept product-day of a pooled product has prompt_b_sha", text)
        self.assertIn("never as the rewrite", text)
        self.assertNotIn("F4 rejected", text)

    def test_the_withdrawn_cell_draws_nothing(self):
        seeds = []
        real = inference_v2.random.Random
        with mock.patch.object(inference_v2.random, "Random", side_effect=lambda s: seeds.append(s) or real(s)):
            _run(_store("SOL-USD", self._sol()))
        self.assertEqual(seeds, [20261023, 20261024, 20261025, 20261026])                # F4's 20261027 never drawn
        seeds.clear()
        with mock.patch.object(inference_v2.random, "Random", side_effect=lambda s: seeds.append(s) or real(s)):
            _run(_store("SOL-USD", self._sol(lambda n: n == 500)))
        self.assertEqual(seeds, [20261023, 20261024, 20261025, 20261026, 20261027])      # one cell, one generator, §6's order

    def test_a_promotion_only_on_an_excluded_day_or_a_void_product_or_a_non_live_row_is_none(self):
        # on d02, which is BAD (jev errors): the promoted rows leave with the day
        def row(n):
            if 96 <= n < 192 and (n - 96) % 10 == 5:
                return {"absence": "jev"}
            return {"b": "buy" if n == 0 else "hold", "promoted": 96 <= n < 192}
        out = _run(_store("SOL-USD", _log(mid=_rising, row=row)))
        self.assertEqual((out["excluded"], out["promoted"], out["rules"]["rule2"]), ({(2, "SOL-USD")}, 0, "NO PROMOTION"))
        # on a void product (20 kept days) with every row promoted
        p2 = self.products[1]
        void = _log(p2, days=range(1, 21), mid=_rising, row=lambda n: {"promoted": True})
        out = _run(_store("SOL-USD", self._sol()), _store(p2, void))
        self.assertEqual((out["void_products"], out["promoted"], out["rules"]["rule2"]), ({p2}, 0, "NO PROMOTION"))
        # on a kept day, but only on absence rows (not live rows, §2)
        rows = self._sol()
        for i in (400, 401):
            rows[i] = _row(report.tick_epoch(rows[i]["tick_id"]), rows[i]["mid"], absence="halt", promoted=True)
        out = _run(_store("SOL-USD", rows))
        self.assertEqual((out["promoted"], out["rules"]["rule2"]), (0, "NO PROMOTION"))

    def test_one_live_promoted_row_on_a_kept_day_reads_f4(self):
        out = _run(_store("SOL-USD", self._sol(lambda n: n == 1000)))
        self.assertEqual(out["promoted"], 1)
        f4 = out["cells"]["F4"]
        self.assertFalse(f4["withdrawn"])
        self.assertIsNotNone(f4["lower"])
        self.assertIs(out["rules"]["rule2"], False)                                      # B - A > 0: does not fire
        self.assertIn("a promotion took effect: F4 is read", out["text"])
        self.assertIn("-> does not fire (> 0)", out["text"])


class StopRules(unittest.TestCase):
    """§9.1: rule 1 fires when neither H1 (B - C at 1/40) nor F3 (A - C at 1/160) rejects; §9.2: rule 2 fires when the
    point estimate of B - A at 900 s is <= 0; §11's reading of each outcome."""

    def _out(self, a, b):
        return _run(_store("SOL-USD", _log(mid=_rising, row=lambda n: {"a": a if n == 0 else "hold", "b": b if n == 0 else "hold",
                                                                       "promoted": True})))

    def test_neither_arm_beats_c_fires_rule_1(self):
        out = self._out("hold", "hold")                                                  # nobody trades: every S-bar_k is 0.0
        self.assertEqual({n: c["lower"] for n, c in out["cells"].items()}, dict.fromkeys(("H1", "F1", "F2", "F3", "F4"), 0.0))
        self.assertEqual(out["rules"], {"rule1": True, "rule2": True})                   # ties stay in; B - A = 0 <= 0
        self.assertIn("-> FIRES: neither A nor B beats C on H1's cell", out["text"])
        self.assertIn("-> FIRES (<= 0): the nightly is stopped (its plist booted out); A is kept", out["text"])
        self.assertIn("§11: H1 not rejected: no B - C difference detectable", out["text"])

    def test_b_beats_c_and_a_holds(self):
        out = self._out("hold", "buy")
        self.assertTrue(all(out["cells"][n]["reject"] for n in ("H1", "F1", "F2", "F4")))
        self.assertFalse(out["cells"]["F3"]["reject"])
        self.assertEqual(out["rules"], {"rule1": False, "rule2": False})
        self.assertIn("§11: H1 rejected: B's wording", out["text"])
        self.assertIn("with F4 also rejected: the rewrite added to the frozen prompt", out["text"])
        self.assertIn("F1 rejected (§6): B's decisions, acted on once an hour, beat C's", out["text"])

    def test_a_beats_c_alone_keeps_the_arms_and_stops_the_nightly(self):
        out = self._out("buy", "hold")
        self.assertFalse(out["cells"]["H1"]["reject"])
        self.assertTrue(out["cells"]["F3"]["reject"])
        self.assertLess(out["cells"]["F4"]["mean"], 0.0)
        self.assertEqual(out["rules"], {"rule1": False, "rule2": True})
        self.assertIn("F3 rejected (§6): a fixed non-rule prompt beats the rule", out["text"])
        self.assertNotIn("§11: F1 rejected without H1", out["text"])


class Void(unittest.TestCase):
    """§9.4: a product with fewer than 21 kept days is void and leaves the pool; rules 1-2 are read on the rest; with no
    product at 21 the block is void and reads neither."""

    def setUp(self):
        self.products = add_products(self, 2)

    def test_a_product_with_twenty_kept_days_leaves_the_pool_and_twenty_one_stays(self):
        p2 = self.products[1]
        sol = _log(mid=_rising, row=_b_buys)
        for kept, void in ((20, {p2}), (21, set())):
            with self.subTest(kept=kept):
                out = _run(_store("SOL-USD", sol), _store(p2, _log(p2, days=range(1, kept + 1), mid=_rising, row=_b_buys)))
                self.assertEqual(out["void_products"], void)
                self.assertEqual(out["pool"], ["SOL-USD"] + ([] if void else [p2]))
                self.assertFalse(out["void"])
                if void:
                    alone = _run(_store("SOL-USD", sol))
                    self.assertEqual(out["cells"]["H1"]["series"], alone["cells"]["H1"]["series"])   # SOL's S alone
                    self.assertIn(f"{p2} 20 VOID: leaves the pool", out["text"])
                    self.assertEqual(out["rules"], alone["rules"])
                else:                                                                    # both pooled on d01-d21, SOL alone after
                    S, s_sol, s_p2 = dict(out["cells"]["H1"]["series"]), out["cells"]["H1"]["S_p"]["SOL-USD"], out["cells"]["H1"]["S_p"][p2]
                    self.assertAlmostEqual(S[5], (s_sol[5] + s_p2[5]) / 2, places=12)
                    self.assertAlmostEqual(S[96 * 21 + 5], s_sol[96 * 21 + 5], places=12)

    def test_no_product_with_twenty_one_kept_days_is_a_void_block(self):
        self.enterContext(mock.patch.object(inference_v2, "FEE_COLUMNS", (0.0, 90.0)))   # two columns: a third of the replays
        out = _run(_store("SOL-USD", _log(days=range(1, 21), mid=_rising, row=_b_buys)), descriptive=True)
        self.assertTrue(out["void"])
        self.assertEqual(out["rules"], {"rule1": None, "rule2": None})
        self.assertEqual({c["n"] for c in out["cells"].values()}, {0})
        text = out["text"]
        self.assertIn("VOID (§9.4): no product has 21 kept days; every verdict is prefixed VOID and stop rules 1 and 2 are not read", text)
        self.assertIn("VOID (§9.4): no product has 21 kept days: the block is void and reported as void; it reads neither stop rule", text)
        self.assertNotIn("stop rule 1 (§9.1)", text)
        self.assertNotIn("stop rule 2 (§9.2)", text)
        self.assertIn("-> not read: the block is void", text)
        self.assertIn("no blocks: nothing to test", text)
        self.assertIn("§8. Descriptive", text)                                           # the descriptive sections still print


class Rule3AndTheFile(unittest.TestCase):
    """§9.3: the rule recomputed from the log governs; data/exclusions-v2.tsv is printed verbatim beside it and every
    disagreement is named; a listed day the rule judges fine is not excluded."""

    def test_the_recomputed_set_governs_and_every_disagreement_is_named(self):
        def row(n):                                                                      # d02 BAD: 10 of 96 rows jev errors
            return {"absence": "jev"} if 96 <= n < 192 and (n - 96) % 10 == 5 else _b_buys(n)
        verbatim = ["day\tproduct\tfill%\tjev-err%\treason", "d05\tSOL-USD\t100\t0\tlooked thin"]
        listed = {"set": {(5, "SOL-USD")}, "lines": verbatim[1:], "path": "<exclusions-v2.tsv>", "error": None}
        out = _run(_store("SOL-USD", _log(mid=_rising, row=row)), listed=listed)
        self.assertEqual(out["excluded"], {(2, "SOL-USD")})                              # d05 stays in, d02 goes
        self.assertIn(96 * 4 + 1, dict(out["cells"]["H1"]["series"]))
        text = out["text"]
        self.assertIn("    | d05\tSOL-USD\t100\t0\tlooked thin", text)
        self.assertIn("DISAGREE: listed, but the rule does not exclude them (fine or not yet closed), so NOT excluded: d05 SOL-USD", text)
        self.assertIn("DISAGREE: the rule excludes them and the file does not list them (excluded anyway): d02 SOL-USD", text)
        self.assertIn("kept days (of 28; void below 21, §9.4): SOL-USD 27", text)
        refused = _run(_store("SOL-USD", _log(mid=_rising, row=row)),
                       listed={"set": set(), "lines": [], "path": "<x>", "error": "<x>:2: day 'd40' is not d01..d28"})
        self.assertIn("<x>: REFUSED, so not read: <x>:2: day 'd40' is not d01..d28 (the recomputed rule governs regardless)", refused["text"])
        self.assertEqual(refused["excluded"], {(2, "SOL-USD")})


class AcceptPending(unittest.TestCase):
    """A log that stopped for good inside d27: without --accept-pending d27 is open (not judged) and d28 is not reached, so
    neither is excluded and main refuses; with it every sample day is closed at T0_v2 + 28 d + h + 30 s, d28 has no live
    row and is excluded whole, and d27's last rows, whose t + h never came, count as gaps."""

    def test_the_flag_closes_every_sample_day(self):
        rows = _log(days=range(1, 28), mid=_rising, row=_b_buys, post=0)[:-40]       # d27 ends at its 56th row
        waiting = _run(_store("SOL-USD", rows))
        self.assertTrue(waiting["pending"])
        self.assertEqual(waiting["excluded"], set())
        self.assertIn("d28 OPEN: the logs have not reached its closing tick, so the open days are not judged", waiting["text"])
        closed = _run(_store("SOL-USD", rows), accept=True)
        self.assertEqual(closed["excluded"], {(28, "SOL-USD")})
        self.assertEqual(closed["kept_days"]["SOL-USD"], 27)
        d27 = next(x for x in closed["days"]["SOL-USD"]["days"] if x["day"] == "d27")
        self.assertEqual((d27["open"], d27["pending"], d27["live"], d27["filled"]), (False, 0, 56, 55))   # the last row's t + h: a gap
        self.assertIn("--accept-pending given and the sample's last day was open: every sample day is judged closed", closed["text"])
        self.assertNotIn(96 * 27, dict(closed["cells"]["H1"]["series"]))


class Section0(unittest.TestCase):
    """RESULTS-v2 §0 (§9.5, §13): the seal placeholder, data/looks.tsv verbatim, the spec_sha set of the sample's rows."""

    def test_looks_and_the_spec_sha_set(self):
        rows = _log(mid=_rising, row=_b_buys)
        looks = {"path": "<looks.tsv>", "lines": ["utc\targv\thead", "2026-11-01T09:00:00Z\tpython3 -m loop.report --unblind\tabc"],
                 "error": None}
        text = _run(_store("SOL-USD", rows), looks=looks, tree_sha=SHA)["text"]
        self.assertIn("§0. The seal, the looks and the sample's spec_sha (PREREG-v2 §9.5, §13)", text)
        self.assertIn("seal: PLACEHOLDER. bin/seal-check is not built in this tree yet", text)
        self.assertIn("<looks.tsv>: 1 look(s), each `report --unblind` as (UTC, argv, HEAD) (§9.5), verbatim:", text)
        self.assertIn("    | 2026-11-01T09:00:00Z\tpython3 -m loop.report --unblind\tabc", text)
        self.assertIn(f"    {SHA} {96 * 28} rows\n  one value, as §13 requires\n", text)    # the post rows are not the sample's
        text = _run(_store("SOL-USD", rows), tree_sha="another")["text"]
        self.assertIn("looks.tsv: absent: no `report --unblind` look was recorded (§9.5)", text)
        self.assertIn("one value, as §13 requires; it is NOT this tree's SPEC.md sha another", text)
        rows[700] = dict(rows[700], spec_sha="old")
        text = _run(_store("SOL-USD", rows), looks={"path": "<l>", "lines": None, "error": "Permission denied"})["text"]
        self.assertIn("    old 1 rows", text)
        self.assertIn("NOT ONE VALUE: 2 values over the sample's rows; §13 requires exactly one", text)
        self.assertIn("<l>: cannot be read: Permission denied", text)


class FeeArithmeticOnAHandBuiltBook(unittest.TestCase):
    """§6's fee arithmetic through the day-28 run, two products, by hand at c = 900 (rows every 900 s: every row decides).
    SOL: B (and D, its table) buys d01's first row at ask 100.01 and sells row 50 at bid 104.99. P2: B buys d03's first row
    at 50.01 and sells its 11th at 51.99. A and C never trade. Pooled figures are sums over kept product-days (§6.4)."""

    @classmethod
    def setUpClass(cls):
        cls.products = add_products(cls, 2)
        cls.p2 = cls.products[1]
        sol = _log(mid=lambda n: 105.0 if 50 <= n < 96 * 28 else 100.0,
                   row=lambda n: {"b": "buy" if n == 0 else "sell" if n == 50 else "hold"})
        p2 = _log(cls.p2, mid=lambda n: 52.0 if 192 + 10 <= n else 50.0,
                  row=lambda n: {"b": "buy" if n == 192 else "sell" if n == 202 else "hold"})
        cls.tiers = {"read": "2026-11-21T21:00Z", "tiers": [
            {"name": "Intro 1", "band": "$0-$10K", "low": 0.0, "high": 1e4, "maker": 60.0, "taker": 120.0},
            {"name": "Intro 2", "band": "$10K-$50K", "low": 1e4, "high": 5e4, "maker": 25.0, "taker": 40.0},
            {"name": None, "band": "$50K+", "low": 5e4, "high": None, "maker": 0.0, "taker": 5.0}]}
        # two fee columns, a third of the descriptive table's replays: the arithmetic reads 0 and 90 bps whatever the columns
        # (Main prints §6's six)
        with mock.patch.object(inference_v2, "FEE_COLUMNS", (0.0, 90.0)):
            cls.out = _run(_store("SOL-USD", sol), _store(cls.p2, p2), descriptive=True, tiers=cls.tiers)

    def test_each_arm_pooled_is_the_sum_of_the_products_and_f_star_by_hand(self):
        fa = self.out["ct"]["fee_arithmetic"][900]
        q1, q2 = 1000.0 / 100.01, 1000.0 / 50.01
        e1, e2 = q1 * (104.99 - 100.01) * 10.0, q2 * (51.99 - 50.01) * 10.0              # bps of NOTIONAL: USD x 1e4 / 1000
        slope = (1.0 + q1 * 104.99 / 1000.0) + (1.0 + q2 * 51.99 / 1000.0)              # per bps of fee: two buys at NOTIONAL, two sells at qty x bid
        for arm in ("b", "d"):
            x = fa["pooled"][arm]
            self.assertAlmostEqual(fa["per"]["SOL-USD"][arm]["e0"], e1, places=9)
            self.assertAlmostEqual(fa["per"][self.p2][arm]["e0"], e2, places=9)
            self.assertAlmostEqual(x["e0"], e1 + e2, places=9)
            self.assertAlmostEqual(x["e90"], e1 + e2 - 90.0 * slope, places=9)
            self.assertEqual(x["fills"], 4)
            self.assertAlmostEqual(x["fstar"], 90.0 * (e1 + e2) / (90.0 * slope), places=9)
            self.assertAlmostEqual(x["volume_30d"], ((1000.0 + q1 * 104.99) + (1000.0 + q2 * 51.99)) * 30 / 28, places=6)
        for arm in ("a", "c"):
            self.assertEqual((fa["pooled"][arm]["fills"], fa["pooled"][arm]["reading"]), (0, "undefined: no fill on a kept day"))
        bh = fa["pooled"]["buy-and-hold"]                                                # bought at T0's ask, marked to the last sample mid
        self.assertAlmostEqual(bh["e0"], q1 * (105.0 - 100.01) * 10.0 + q2 * (52.0 - 50.01) * 10.0, places=9)
        self.assertEqual(bh["fills"], 2)
        for c in (3600, 14400):                                                          # pooled = the sum at every cadence
            f = self.out["ct"]["fee_arithmetic"][c]
            for arm in ("a", "b", "c", "d", "buy-and-hold"):
                for k in ("e0", "e90", "fills", "volume_30d"):
                    self.assertAlmostEqual(f["pooled"][arm][k], sum(f["per"][p][arm][k] for p in ("SOL-USD", self.p2)), places=9)

    def test_tiers_pairs_and_the_reading(self):
        fa = self.out["ct"]["fee_arithmetic"][900]
        fs = fa["pooled"]["b"]["fstar"]
        self.assertTrue(120.0 < fs)
        self.assertEqual([t["band"] for t in fa["named"]["b"]], ["$0-$10K", "$10K-$50K", "$50K+"])   # every taker below f*_B
        bc = fa["pairs"][("b", "c")]
        self.assertAlmostEqual(bc["d0"], fa["pooled"]["b"]["e0"], places=9)             # C has no fill: Delta = E_B
        self.assertEqual(bc["reading"], f"B stops beating C above {bc['fstar']:.2f} bps per fill")
        text = self.out["text"]
        self.assertIn("fee arithmetic at 900 s (PREREG-v2 §6", text)
        self.assertIn("§12's table, read UTC 2026-11-21T21:00Z", text)
        # §11: B's 30-day volume (~$4,400) reaches Intro 1 only; f*_B (~219 bps) exceeds its taker 120 at 900 s
        self.assertIn("§11 (fees, descriptive): an arm's pooled break-even fee exceeds the taker of a tier its own volume reaches:", text)
        self.assertIn(f"B at 900 s: f* {fs:.2f} bps per fill exceeds the taker 120 bps of Intro 1 $0-$10K, which its 30-day volume", text)
        self.assertNotIn("of Intro 2", text)
        self.assertIn("beside it: the H1 cell at every fee column (mean S-bar_k, bps): 0 bps", text)
        self.assertEqual(self.out["ct"]["cells"][(900, "b", "c", "argmax", 0.0)]["S"], self.out["cells"]["H1"]["series"])
        for name, c, x, y in (("F1", 3600, "b", "c"), ("F2", 14400, "b", "c"), ("F3", 900, "a", "c"), ("F4", 900, "b", "a")):
            self.assertEqual(self.out["ct"]["cells"][(c, x, y, "argmax", 0.0)]["S"], self.out["cells"][name]["series"], name)

    def test_no_arm_that_pays_reads_nothing_paid(self):
        lines = inference_v2.fee_reading({900: {"pooled": {a: {"fstar": None, "volume_30d": 0.0} for a in book.ARMS}}}, self.tiers["tiers"])
        self.assertEqual(lines, ["  §11 (fees, descriptive): no arm's pooled break-even fee f*_X, at any cadence, exceeds the taker"
                                 " fee of a tier its own account-level volume reaches: nothing measured here paid at the venue at $1,000"])


def _write(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")


class Main(unittest.TestCase):
    """main: T0_v2 from PREREG-v2.md §12 only; refusals before any log is opened (blank or malformed T0_v2, before T0_v2 +
    28 d) and after (d28 open without --accept-pending); --out written once; the whole text end to end, and again in a
    fresh interpreter under another hash seed, byte for byte. SOL's log only: d28 open (two rows after the sample)."""
    ARGV = ["--sample", "--accept-pending"]

    @classmethod
    def setUpClass(cls):
        cls.data = cls.enterClassContext(tempfile.TemporaryDirectory())
        cls.enterClassContext(mock.patch.object(config, "DATA", cls.data))
        cls.enterClassContext(mock.patch.object(config, "DECISIONS", os.path.join(cls.data, "decisions.jsonl")))
        cls.enterClassContext(mock.patch.object(config, "HALT", os.path.join(cls.data, "HALT")))
        pin_prereg_v2(cls, T0S, SHA)
        _write(config.DECISIONS, _log(mid=_rising, row=lambda n: {"b": "buy" if n == 0 else "hold", "promoted": n > 500}, post=2))
        with open(config.DECISIONS, "rb") as fh:
            cls.sha = hashlib.sha256(fh.read()).hexdigest()
        cls.outpath = os.path.join(cls.data, "RESULTS-v2.md")
        cls.code, cls.text, cls.err = cls._main(cls.ARGV + ["--out", cls.outpath])

    @staticmethod
    def _main(argv, now=AFTER):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = inference_v2.main(argv, now=now, resamples=R_MAIN)
        return code, out.getvalue(), err.getvalue()

    def test_the_run_end_to_end(self):
        self.assertEqual(self.code, 0, self.err)
        with open(self.outpath, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), self.text)
        for head in ("§0. The seal", "§1. Stop rule 3 and void", "§2. H1, the one primary", "§3. Family F", "§4. Stop rules 1-2",
                     "§5. Power as measured", "§6. Descriptive, never tested", "§7. Descriptive: A's argmax", "§8. Descriptive: the direction"):
            self.assertIn("\n" + head, self.text)
        self.assertIn(f"SOL-USD: log {config.DECISIONS}: ", self.text)
        self.assertIn(f"sha256 {self.sha}", self.text)
        self.assertIn("T0_v2 2026-10-24T22:00Z (PREREG-v2.md §12)", self.text)
        self.assertIn(f"NOT the pre-registered run (R = {R_MAIN}, not 10000)", self.text)
        self.assertIn("--accept-pending given and the sample's last day was open", self.text)
        self.assertIn(f"looks.tsv: absent", self.text)
        self.assertIn("one value, as §13 requires\n", self.text)                         # SHA is also this tree's (pinned)
        self.assertIn("H1 B - C, argmax, 0 bps, c = 900 s, seed 20261023, one-sided alpha 1/40, bound sorted[4]", self.text)
        self.assertIn("F4 B - A, argmax, 0 bps, c = 900 s, seed 20261027, one-sided alpha 1/160, bound sorted[1]", self.text)
        self.assertIn("fee columns 0, 2, 10, 25, 50, 90 bps (§6)", self.text)                  # PREREG-v2 §6's, whatever config's are
        for fee in (2, 10, 25, 50, 90):
            self.assertIn(f"pair B-C  fee {fee} bps", self.text)
        self.assertNotIn("fee 60 bps", self.text)
        self.assertNotIn("fee 120 bps", self.text)
        code, _, err = self._main(self.ARGV + ["--out", self.outpath])                   # written once
        self.assertEqual(code, 2)
        self.assertIn("exists; the result is written once", err)

    def test_it_waits_for_d28_to_close_unless_the_logs_really_stopped(self):
        code, out, err = self._main(["--sample"])
        self.assertEqual((code, out), (3, ""))
        self.assertIn("the sample's last day d28 is open: stop rule 3 judges it once a product's log has reached a tick at or after"
                      " 2026-11-21T22:16Z (T0_v2 + 28 d + h + 30 s), and the latest any log has reached is 2026-11-21T22:15Z", err)

    def test_refusals_before_any_log_is_opened(self):
        with mock.patch.object(inference, "read_log", side_effect=AssertionError("a log was opened")):
            code, out, err = self._main(["--sample"], now=END - 60)
            self.assertEqual((code, out), (3, ""))
            self.assertIn("refusing: the sample ends 2026-11-21T22:00Z and it is 2026-11-21T21:59Z", err)
            for t0, why in ((None, "T0_v2 is blank: the block is not sealed"), ("2026-10-24T22:00Z", "is not a tick_id on a minute boundary")):
                with contextlib.ExitStack() as st:
                    pin_prereg_v2(st, t0, SHA)
                    code, out, err = self._main(["--sample"])
                self.assertEqual((code, out), (3, ""), t0)
                self.assertIn(why, err)
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
            inference_v2.main([], now=AFTER)                                             # --sample is the one mode
        self.assertEqual(cm.exception.code, 2)
        with mock.patch.object(config, "DATA", os.path.join(self.data, "none")), \
                mock.patch.object(config, "DECISIONS", os.path.join(self.data, "none", "decisions.jsonl")):
            code, out, err = self._main(["--sample"])
        self.assertEqual(code, 2)
        self.assertIn("no log at any product's store", err)

    def test_a_fresh_interpreter_under_another_hash_seed_prints_the_same_bytes(self):
        boot = ("import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]]\n"
                "from unittest import mock\n"
                "from loop import config, dash, inference_v2\n"
                "data, prereg = sys.argv[3], sys.argv[4]\n"
                "config.DATA, config.DECISIONS, config.HALT = data, data + '/decisions.jsonl', data + '/HALT'\n"
                "config.PRODUCTS = tuple(sys.argv[5].split(','))\n"
                "dash.PREREG_V2_PATH, dash.v2_spec_sha = prereg, (lambda spec=None: sys.argv[6])\n"
                "sys.exit(inference_v2.main(sys.argv[8:], now=float(sys.argv[7]), resamples=%d))\n" % R_MAIN)
        p = subprocess.run([sys.executable, "-c", boot, os.path.join(REPO, "tests"), REPO, self.data,
                            dash.PREREG_V2_PATH, ",".join(config.PRODUCTS), SHA, str(AFTER)] + self.ARGV,
                           cwd=REPO, env=dict(os.environ, PYTHONHASHSEED="4242", PYTHONIOENCODING="utf-8"), capture_output=True, timeout=300)
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(p.stdout.decode(), self.text)


if __name__ == "__main__":
    unittest.main()

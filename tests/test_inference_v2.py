"""loop/inference_v2.py, PREREG-v2's day-28 inference: its refusals, stop rules 1-4 (an excluded day between kept days,
NO PROMOTION, void), RESULTS-v2 §0, the fee arithmetic on a hand-built book, and a run end to end through main. The draw,
the bound and the pooled statistic are held to transcriptions of the text in tests/test_invariants.py; this module holds
the behaviour. Offline: hand-built rows every 900 s (so each row's t + h is the next row) in memory or in temp
directories; the live data/, HALT and looks.tsv are never touched."""
import contextlib, datetime, hashlib, io, json, math, os, random, re, shutil, subprocess, sys, tempfile, unittest
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


def _power_line(text, name):
    """§5's one line for cell `name` (power_lines)."""
    (line,) = [l for l in text.splitlines() if re.match(rf"  {name} [A-D] - [A-D] at \d+ s: ", l)]
    return line


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
        self.assertIn("    F4's B - A is test-retest, descriptive only: before any promotion A and B ask the same wording", text)
        # §5: a withdrawn cell is not tested, so it has no power figure (§7: cell 4 gets no all-block figure either way)
        f4 = _power_line(text, "F4")
        self.assertIn("F4 B - A at 900 s: withdrawn (NO PROMOTION, §9.2): not tested, no z and no MDE; n 2688;", f4)
        self.assertNotIn("MDE ", f4.replace("no MDE", ""))
        self.assertIn(" bps/day", _power_line(text, "F3"))                                # F3, a tested cell, keeps its figures

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
        self.assertNotIn("F4's B - A is test-retest", out["text"])
        # §7: "Cell 4 (B - A) gets no all-block figure"; its MDE on the disagreement blocks alone is printed
        f4 = _power_line(out["text"], "F4")
        self.assertIn("no all-block MDE (§7: cell 4 gets none; before the first promotion B - A is test-retest)", f4)
        self.assertNotIn("bps/day", f4)
        self.assertIn("MDE on the disagreement blocks ", f4)


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
        # the header says "every verdict is prefixed VOID": the five cells' verdicts, H1 and F1-F4, all are
        self.assertEqual(text.count("-> VOID: no blocks: nothing to test"), 5)
        self.assertNotIn("-> no blocks", text)
        self.assertIn("§8. Descriptive", text)                                           # the descriptive sections still print
        # a void block has no §9.2 row set (§1 says "not read: the block is void"), so F4 is not withdrawn and §3 does not
        # call B - A test-retest "before any promotion": that reading is NO PROMOTION's alone
        self.assertFalse(out["cells"]["F4"]["withdrawn"])
        self.assertNotIn("F4's B - A is test-retest", text)


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
    """RESULTS-v2 §0 (§9.5, §13): run() without main's seal check says so, data/looks.tsv verbatim, the spec_sha set of the sample's rows."""

    def test_looks_and_the_spec_sha_set(self):
        rows = _log(mid=_rising, row=_b_buys)
        looks = {"path": "<looks.tsv>", "lines": ["utc\targv\thead", "2026-11-01T09:00:00Z\tpython3 -m loop.report --unblind\tabc"],
                 "error": None}
        text = _run(_store("SOL-USD", rows), looks=looks, tree_sha=SHA)["text"]
        self.assertIn("§0. The seal, the looks, the sample's spec_sha and prompt_b (PREREG-v2 §8, §9.5, §13)", text)
        self.assertIn("seal: NOT CHECKED: run() was called without main's seal check (a test, never the result)", text)
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


class Section0PromptB(unittest.TestCase):
    """PREREG-v2 §8: "RESULTS-v2 §0 prints each product-day's `prompt_b` set and names any day with two values". A
    promotion takes effect at a day's first tick (activation_tick = T0_v2 + 86,400 (E - 1)), so every row of a
    product-day carries one prompt_b; two on one day is a hand edit of CURRENT or a version activated off its boundary.
    A row stopped before the prompts step carries a null prompt_b and no version."""

    def setUp(self):
        self.p2 = add_products(self, 2)[1]

    def test_each_product_day_and_the_days_with_two_values(self):
        def row(n):
            if n == 96 * 2 + 7:
                return {"absence": "feed"}                                               # null prompt_b below: not a value
            return {"b": "buy" if n == 0 else "hold", "promoted": 96 * 4 + 48 <= n < 96 * 5 or n >= 96 * 7}
        sol = _log(mid=_rising, row=row)
        i = next(j for j, r in enumerate(sol) if r["absence"] == "feed")
        sol[i] = dict(sol[i], prompt_a=None, prompt_a_sha=None, prompt_b=None, prompt_b_sha=None)
        p2 = _log(self.p2, days=[d for d in range(1, 29) if d != 10], mid=_rising, row=_b_buys)
        out = _run(_store("SOL-USD", sol), _store(self.p2, p2))
        s0 = out["text"].split("\n§0.")[1].split("\n§1.")[0]
        self.assertIn("  prompt_b per product-day (PREREG-v2 §8: every row of a product-day carries one; over the sample's rows"
                      " that reached the prompts step, a null prompt_b carrying none):", s0)
        self.assertIn("\n    SOL-USD: d01-d04 {v2}; d05 {v2, v3} TWO VALUES; d06-d07 {v2}; d08-d28 {v3}\n", s0)
        self.assertIn(f"\n    {self.p2}: d01-d09 {{v3}}; d10 {{}}; d11-d28 {{v3}}\n", s0)
        self.assertIn("  product-days with two or more prompt_b values (§8): SOL-USD d05\n", s0)
        clean = _run(_store("SOL-USD", _log(mid=_rising, row=_b_buys)))["text"]
        self.assertIn("\n    SOL-USD: d01-d28 {v3}\n", clean)
        self.assertIn("  product-days with two or more prompt_b values (§8): none\n", clean)


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


class FeeArithmeticKeptDaysThroughTheRun(unittest.TestCase):
    """§6.1-§6.2 through run(): what run() hands report.cadence_table as the kept blocks and the kept days, held to the
    text by hand. SOL's d02 is BAD (10 of 96 rows jev errors) and B buys on it (row 100, ask 100.01) and sells on d04
    (row 300, bid 109.99; the mid is 110 from d03's first row): "a fill counts when its tick is on a kept day", so one
    fill, the sell; E sums the pnl over kept days' ticks, so the buy tick's spread (on d02) is out and the jump (d03's
    first row) is in; the 30-day volume is the kept fill value x 30 / 27 kept days. P2 has 20 kept days (void, §9.4) and
    trades: it is in no pooled sum. Both switches sit on decision rows at 900 and 3,600 s."""

    @classmethod
    def setUpClass(cls):
        cls.p2 = add_products(cls, 2)[1]

        def row(n):
            if 96 <= n < 192 and (n - 96) % 10 == 5:
                return {"absence": "jev"}
            return {"b": "buy" if n == 100 else "sell" if n == 300 else "hold"}
        sol = _log(mid=lambda n: 100.0 if n < 192 else 110.0, row=row)
        p2 = _log(cls.p2, days=range(1, 21), mid=lambda n: 50.0 if n < 20 else 60.0,
                  row=lambda n: {"b": "buy" if n == 0 else "sell" if n == 40 else "hold"})
        with mock.patch.object(inference_v2, "FEE_COLUMNS", (0.0, 90.0)):
            cls.out = _run(_store("SOL-USD", sol), _store(cls.p2, p2), descriptive=True)

    def test_a_fill_on_an_excluded_day_and_a_void_product_are_out(self):
        self.assertEqual(self.out["excluded"] & {(2, "SOL-USD")}, {(2, "SOL-USD")})
        self.assertEqual((self.out["kept_days"]["SOL-USD"], self.out["void_products"]), (27, {self.p2}))
        q = 1000.0 / 100.01
        e0 = q * (110.0 - 100.0 - 0.01) * 10.0                                           # bps of NOTIONAL; the buy's 0.01 is on d02
        value = q * 109.99                                                               # the one kept fill, the sell
        for c in (900, 3600):
            with self.subTest(c=c):
                fa = self.out["ct"]["fee_arithmetic"][c]
                self.assertEqual(fa["days"]["SOL-USD"], 27.0)
                sol, b = fa["per"]["SOL-USD"]["b"], fa["pooled"]["b"]
                self.assertEqual(sol["fills"], 1)
                self.assertAlmostEqual(sol["e0"], e0, places=9)
                self.assertAlmostEqual(sol["e90"], e0 - 90.0 * value / 1000.0, places=9)
                self.assertAlmostEqual(sol["volume_30d"], value * 30 / 27, places=9)
                for k in ("e0", "e90", "fills", "value", "volume_30d"):                     # P2, void, is in no pooled sum
                    self.assertEqual(b[k], sol[k], k)
                self.assertAlmostEqual(b["fstar"], 90.0 * e0 / (90.0 * value / 1000.0), places=9)
        self.assertIn(f"      {self.p2}: void (PREREG-v2 §9.4): not pooled", self.out["text"])


class PowerAsMeasured(unittest.TestCase):
    """RESULTS-v2 §5, PREREG-v2 §7's figures as measured, each held to a transcription of the text: z = the one-sided
    alpha's normal quantile + power 0.80's (§7: 1.95996 + 0.84162 = 2.80159 at 1/40, 2.4977 + 0.8416 = 3.3393 at 1/160);
    sd = the sample sd of S-bar_k; MDE = z sd / sqrt(n) per block, x 86,400 / c per day; n_eff = f n = the pooled
    disagreement blocks (a kept product's SIDES differ into or out of a tick in them), counted here from the positions the
    fixture sets; the MDE on them z sd_dis / sqrt(n_eff); rho = Pearson's r of two pooled products' S_k,p over the blocks
    both keep. Two products on correlated random walks, every row promoted (F4 read); P2 has no row on d05 (excluded).
    B is long on rows [0, 1008] and [1504, 2208], A on [304, 704], C never: every switch sits on a decision row at every
    cadence (multiples of 16), so the sides are known by hand at 900, 3,600 and 14,400 s."""
    Z_H1, Z_F = 1.95996 + 0.84162, 2.49771 + 0.84162                                    # §7's, to the text's digits

    @classmethod
    def setUpClass(cls):
        cls.p2 = add_products(cls, 2)[1]
        rng = random.Random(20261029)
        common = [rng.gauss(0.0, 0.05) for _ in range(96 * 28 + 3)]
        own = [[rng.gauss(0.0, 0.04) for _ in range(96 * 28 + 3)] for _ in range(2)]
        walks = []
        for j, (base, beta) in enumerate(((100.0, 1.0), (50.0, 0.5))):
            w, x = [], base
            for n in range(96 * 28 + 3):
                x += beta * common[n] + own[j][n]
                w.append(round(x, 2))
            walks.append(w)

        def row(n):
            b = "buy" if n in (0, 1504) else "sell" if n in (1008, 2208) else "hold"
            a = "buy" if n == 304 else "sell" if n == 704 else "hold"
            return {"b": b, "a": a, "promoted": True}
        sol = _log(mid=lambda n: walks[0][n], row=row)
        p2 = _log(cls.p2, days=[d for d in range(1, 29) if d != 5], mid=lambda n: walks[1][n], row=row)
        cls.out = _run(_store("SOL-USD", sol), _store(cls.p2, p2))
        cls.long = {"b": [(0, 1008), (1504, 2208)], "a": [(304, 704)], "c": []}

    @staticmethod
    def sd(xs):
        m = sum(xs) / len(xs)
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))

    @staticmethod
    def r(xs, ys):
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        return (sum((x - mx) * (y - my) for x, y in zip(xs, ys))
                / math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)))

    def side(self, arm, n):
        return any(a <= n < b for a, b in self.long[arm])                               # long out of row n: its buy's row to the sell's

    def hot(self, x, y, c):
        """The disagreement blocks by hand: a row whose sides differ into it (after the row before) or out of it."""
        per, out = c // 900, set()
        for n in range(96 * 28):
            into = n > 0 and self.side(x, n - 1) != self.side(y, n - 1)
            if into or self.side(x, n) != self.side(y, n):
                out.add(n // per)
        return out

    def figures(self, name):
        line = _power_line(self.out["text"], name)
        m = re.search(r": n (\d+); disagreement blocks (\d+) \(f ([\d.]+)%, n_eff (\d+); product-blocks (\d+)\); sd ([\d.]+),"
                      r" sd_dis ([\d.]+) bps; z ([\d.]+); (?:MDE ([\d.]+) bps/block = ([\d.]+) bps/day|no all-block MDE \([^)]*\));"
                      r" MDE on the disagreement blocks ([\d.]+) bps/block$", line)
        self.assertIsNotNone(m, line)
        return m.groups()

    def test_z_sd_mde_and_n_eff_per_cell(self):
        for name, x, y, c, z in (("H1", "b", "c", 900, self.Z_H1), ("F1", "b", "c", 3600, self.Z_F), ("F2", "b", "c", 14400, self.Z_F),
                                 ("F3", "a", "c", 900, self.Z_F), ("F4", "b", "a", 900, self.Z_F)):
            with self.subTest(cell=name):
                n, dis, f, n_eff, pdis, sd, sdd, zz, mde, mday, mdd = self.figures(name)
                series = dict(self.out["cells"][name]["series"])
                self.assertEqual(int(n), 28 * 86400 // c)                                  # SOL keeps every day
                hot = self.hot(x, y, c)
                self.assertEqual((int(dis), int(n_eff)), (len(hot), len(hot)))
                d05 = range(4 * 86400 // c, 5 * 86400 // c)                                # P2's excluded day: SOL alone
                self.assertEqual(int(pdis), sum(1 if k in d05 else 2 for k in hot))         # both products' sides are B's and A's
                self.assertAlmostEqual(float(f), 100.0 * len(hot) / int(n), delta=0.05)
                self.assertEqual(zz, f"{z:.4f}")                                           # 2.8016 at 1/40, 3.3393 at 1/160
                vals, dv = list(series.values()), [series[k] for k in sorted(hot)]
                self.assertAlmostEqual(float(sd), self.sd(vals), delta=0.0005)
                self.assertAlmostEqual(float(sdd), self.sd(dv), delta=0.0005)
                self.assertAlmostEqual(float(mdd), z * self.sd(dv) / math.sqrt(len(dv)), delta=0.0006)
                if name == "F4":
                    self.assertIsNone(mde)                                                 # §7: no all-block figure for cell 4
                else:
                    self.assertAlmostEqual(float(mde), z * self.sd(vals) / math.sqrt(len(vals)), delta=0.0006)
                    self.assertAlmostEqual(float(mday), z * self.sd(vals) / math.sqrt(len(vals)) * 86400 / c, delta=0.06)

    def test_rho_between_the_pooled_products_over_the_blocks_both_keep(self):
        text = self.out["text"]
        for name in ("H1", "F1", "F2", "F3", "F4"):
            with self.subTest(cell=name):
                x = self.out["cells"][name]
                c = x["cell"].c
                ks = [k for k in range(28 * 86400 // c) if not 4 * 86400 // c <= k < 5 * 86400 // c]   # P2's d05 is excluded
                want = self.r([x["S_p"]["SOL-USD"].get(k, 0.0) for k in ks], [x["S_p"][self.p2].get(k, 0.0) for k in ks])
                self.assertTrue(0.2 < abs(want) < 0.99, want)                              # a rho that means something
                m = re.search(rf"\n    {name}: SOL-USD~{self.p2} (-?[\d.]+) over (\d+)\n", text)
                self.assertIsNotNone(m, name)
                self.assertEqual(int(m.group(2)), len(ks))
                self.assertAlmostEqual(float(m.group(1)), want, delta=0.0005)


class MakeResults(unittest.TestCase):
    def test_make_results_is_the_v2_run(self):
        # PREREG-v2 §10: "v2's own `results` target, in the build"; v1's run is made from main before the switch; §13:
        # NO_SEAL=1 is the one override of the seal check, passed as --no-seal, which RESULTS-v2 §0 records
        env = {k: v for k, v in os.environ.items() if not k.startswith("MAKE") and k != "NO_SEAL"}   # not the outer make's
        for extra, tail in (([], ""), (["NO_SEAL=1"], " --no-seal"), (["NO_SEAL=0"], ""), (["NO_SEAL=yes"], "")):
            with self.subTest(extra=extra):
                r = subprocess.run(["make", "-n", "-s", "-C", REPO, "results", f"PY={sys.executable}"] + extra, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", env=env, timeout=60)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout.strip(), f"{sys.executable} -m loop.inference_v2 --sample --out RESULTS-v2.md{tail}")


class SealCheck(unittest.TestCase):
    """PREREG-v2 §10 (the inference bullet) and §13: v2's make results "checks prereg-v2-seal and runs bin/seal-check
    --since prereg-v2-seal", refusing on any other hunk unless NO_SEAL=1, which it records; RESULTS-v2 §0 prints
    `git diff -U0 prereg-v2-seal HEAD`. inference_v2.seal on a real temporary repository: the annotated tag, its ancestry
    to HEAD, bin/seal-check's exit and output, the diff."""

    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git not on PATH")
        self.repo = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.dict(os.environ, {                      # no user or system git config leaks in
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}))
        self.git("init", "-q")
        self.commit("a.txt", "one\n")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, name, text):
        with open(os.path.join(self.repo, name), "w", encoding="utf-8") as fh:
            fh.write(text)
        self.git("add", name)
        self.git("commit", "-q", "-m", name)

    def tool(self, code, say="seal-check: since prereg-v2-seal: every hunk is on the allowlist"):
        os.makedirs(os.path.join(self.repo, "bin"), exist_ok=True)
        path = os.path.join(self.repo, "bin", "seal-check")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"#!/bin/sh\necho \"$0 $*\" >> \"$(dirname \"$0\")/../argv.txt\"\nprintf '%s (%s)\\n' '{say}' \"$1\"\nexit {code}\n")
        os.chmod(path, 0o755)

    def test_no_annotated_tag_fails(self):
        x = inference_v2.seal(self.repo)
        self.assertEqual((x["ok"], x["why"]), (False, "no annotated tag prereg-v2-seal"))
        self.git("tag", "prereg-v2-seal")                                                # a lightweight tag is not the seal
        self.assertEqual(inference_v2.seal(self.repo)["why"], "no annotated tag prereg-v2-seal")

    def test_a_tag_off_the_branch_fails(self):
        self.git("checkout", "-q", "-b", "side")
        self.commit("b.txt", "side\n")
        self.git("tag", "-a", "prereg-v2-seal", "-m", "sealed")
        self.git("checkout", "-q", "-")
        self.tool(0)
        x = inference_v2.seal(self.repo)
        self.assertFalse(x["ok"])
        self.assertEqual(x["why"], "prereg-v2-seal is not an ancestor of HEAD")

    def test_bin_seal_check_absent_or_failing_fails_and_passing_passes(self):
        self.git("tag", "-a", "prereg-v2-seal", "-m", "sealed")
        tag, commit = self.git("rev-parse", "prereg-v2-seal"), self.git("rev-parse", "HEAD")
        self.commit("a.txt", "one\ntwo\n")
        head = self.git("rev-parse", "HEAD")
        x = inference_v2.seal(self.repo)
        self.assertEqual((x["ok"], x["why"]), (False, "bin/seal-check is not in this tree (PREREG-v2 §10 builds it in the draft tree)"))
        self.commit("stray.txt", "x\n")                                                  # committed so the tool's file is the only new one
        self.tool(1, "seal-check: 1 hunk outside the allowlist: stray.txt")
        x = inference_v2.seal(self.repo)
        self.assertEqual((x["ok"], x["why"]), (False, "bin/seal-check --since prereg-v2-seal exited 1"))
        self.assertIn("    | seal-check: 1 hunk outside the allowlist: stray.txt (--since)", x["lines"])
        self.assertIn("  the seal's verdict, replayed: FAIL (exit 1)", x["lines"])       # printed, not a gate: --since is
        os.remove(os.path.join(self.repo, "argv.txt"))
        self.tool(0)
        x = inference_v2.seal(self.repo)
        self.assertEqual((x["ok"], x["why"]), (True, None))
        with open(os.path.join(self.repo, "argv.txt"), encoding="utf-8") as fh:
            self.assertEqual([l.split()[1:] for l in fh.read().splitlines()], [["--at", "prereg-v2-seal"], ["--since", "prereg-v2-seal"]])
        text = "\n".join(x["lines"])
        head2 = self.git("rev-parse", "HEAD")
        self.assertIn(f"  seal: annotated tag prereg-v2-seal {tag} (commit {commit}), an ancestor of HEAD {head2}", text)
        # §13: RESULTS-v2 §0 prints the seal's -U0 diff from the draft tag, seal-check's verdict, the --stat of the excluded
        # paths, the listed deviations' diffs and the T0_v2 re-derivations: bin/seal-check --at prints them (2026-09-29
        # lens-5 review: §0 said "not printed here yet")
        self.assertIn("  bin/seal-check --at prereg-v2-seal (the seal's verdict replayed on the sealed commit, PREREG-v2 §13;"
                      " printed, not a gate): exit 0, its output verbatim:\n"
                      "    | seal-check: since prereg-v2-seal: every hunk is on the allowlist (--at)\n"
                      "  the seal's verdict, replayed: PASS (exit 0)", text)
        self.assertIn("  bin/seal-check --since prereg-v2-seal: exit 0, its output verbatim:\n"
                      "    | seal-check: since prereg-v2-seal: every hunk is on the allowlist (--since)", text)
        self.assertNotIn("not printed here yet", "\n".join(inference_v2.seal_lines(x, False)))
        self.assertIn("  git diff -U0 prereg-v2-seal HEAD (PREREG-v2 §13), verbatim:\n", text)
        self.assertIn("\n    | +two\n", text)
        self.assertIn("\n    | +++ b/stray.txt\n", text)
        self.assertNotEqual(head, head2)

    def test_git_missing_fails_and_says_so(self):
        with mock.patch.object(inference_v2.subprocess, "run", side_effect=FileNotFoundError(2, "No such file", "git")):
            x = inference_v2.seal(self.repo)
        self.assertFalse(x["ok"])
        self.assertTrue(x["why"].startswith("git could not be run: "), x["why"])


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
    SEAL = {"ok": True, "why": None, "lines": ["  seal: <a passing seal check, the fixture's>"]}

    @classmethod
    def setUpClass(cls):
        cls.seal = cls.enterClassContext(mock.patch.object(inference_v2, "seal", return_value=cls.SEAL))
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
        self.assertIn("\n  seal: <a passing seal check, the fixture's>\n", self.text)
        self.assertNotIn("NO_SEAL", self.text)

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
        # "the logs really stopped" cannot be said before a running loop could have written d28's closing tick: the minute
        # it falls in (22:16) and that minute's own write (to 22:17); before then --accept-pending would turn the last
        # rows' pending outcomes into gaps (stop rule 3) at T0_v2 + 28 d + 1 min
        with mock.patch.object(inference, "read_log", side_effect=AssertionError("a log was opened")):
            for now in (END + 60, END + 1019):
                code, out, err = self._main(["--sample", "--accept-pending"], now=now)
                self.assertEqual((code, out), (3, ""), now)
                self.assertIn("refusing: --accept-pending is for logs that really stopped, and before 2026-11-21T22:17Z no running loop"
                              " could have written d28's closing tick (a tick at or after 2026-11-21T22:16Z, T0_v2 + 28 d + h + 30 s):"
                              " run without it once the logs reach that tick (PREREG-v2 §9.3: a row whose t + h has not come would"
                              " count as a gap)", err)
        code, out, err = self._main(["--sample", "--accept-pending"], now=END + 1020)
        self.assertEqual(code, 0, err)
        self.assertIn("--accept-pending given and the sample's last day was open", out)

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
            failed = {"ok": False, "why": "no annotated tag prereg-v2-seal", "lines": ["  seal: no annotated tag prereg-v2-seal"]}
            with mock.patch.object(inference_v2, "seal", return_value=failed):
                code, out, err = self._main(["--sample"])
            self.assertEqual((code, out), (3, ""))
            self.assertIn("refusing: the seal check failed: no annotated tag prereg-v2-seal. PREREG-v2 §10, §13: make results"
                          " checks prereg-v2-seal and runs bin/seal-check --since prereg-v2-seal, and refuses unless NO_SEAL=1"
                          " (make results NO_SEAL=1, --no-seal), which RESULTS-v2 §0 records", err)
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
            inference_v2.main([], now=AFTER)                                             # --sample is the one mode
        self.assertEqual(cm.exception.code, 2)
        with mock.patch.object(config, "DATA", os.path.join(self.data, "none")), \
                mock.patch.object(config, "DECISIONS", os.path.join(self.data, "none", "decisions.jsonl")):
            code, out, err = self._main(["--sample"])
        self.assertEqual(code, 2)
        self.assertIn("no log at any product's store", err)

    def test_no_seal_runs_on_a_failed_check_and_records_it(self):
        failed = {"ok": False, "why": "no annotated tag prereg-v2-seal", "lines": ["  seal: no annotated tag prereg-v2-seal"]}
        with mock.patch.object(inference_v2, "seal", return_value=failed):
            code, text, err = self._main(self.ARGV + ["--no-seal"])
        self.assertEqual(code, 0, err)
        self.assertIn("  NO_SEAL=1 (§13): the seal check FAILED and this run was made anyway: no annotated tag prereg-v2-seal\n", text)
        self.assertIn("\n§0. The seal", text)
        self.assertIn("\n  seal: no annotated tag prereg-v2-seal\n  NO_SEAL=1 given (make results NO_SEAL=1, --no-seal): the seal"
                      " check FAILED and was overridden: no annotated tag prereg-v2-seal\n", text)
        code, text, err = self._main(self.ARGV + ["--no-seal"])                          # given, though the check passes
        self.assertEqual(code, 0, err)
        self.assertIn("  NO_SEAL=1 given (make results NO_SEAL=1, --no-seal): the seal check passed; nothing was overridden\n", text)

    def test_a_sample_with_two_spec_shas_is_refused_unless_no_seal(self):
        # §13: "the set of spec_sha over sample rows, which must hold exactly one value"; NO_SEAL=1 is §13's one override
        d = self.enterContext(tempfile.TemporaryDirectory())
        rows = _log(mid=_rising, row=_b_buys, post=2)
        rows[700] = dict(rows[700], spec_sha="old")
        rows[-1] = dict(rows[-1], spec_sha="after")                                      # after the sample: not a sample row
        _write(os.path.join(d, "decisions.jsonl"), rows)
        with mock.patch.object(config, "DATA", d), mock.patch.object(config, "DECISIONS", os.path.join(d, "decisions.jsonl")):
            code, out, err = self._main(self.ARGV)
            self.assertEqual((code, out), (3, ""))
            self.assertIn("refusing: the sample's rows carry 2 spec_sha values (old 1 rows, spec-v2-fixture 2687 rows); PREREG-v2"
                          " §13 requires exactly one (a row whose sha is not SPEC v2's does not mean what SPEC v2 says); NO_SEAL=1"
                          " (make results NO_SEAL=1, --no-seal) runs anyway and RESULTS-v2 records it", err)
            code, out, err = self._main(self.ARGV + ["--no-seal"])
        self.assertEqual(code, 0, err)
        self.assertIn("\n  NO_SEAL=1 (§13): the sample's spec_sha set is NOT ONE VALUE (2 values) and this run was made anyway\n", out)
        self.assertIn("  NOT ONE VALUE: 2 values over the sample's rows; §13 requires exactly one (a sample row whose sha is not"
                      " SPEC v2's does not mean what SPEC v2 says); this run was made under NO_SEAL=1, recorded here\n", out)

    def test_a_fresh_interpreter_under_another_hash_seed_prints_the_same_bytes(self):
        boot = ("import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]]\n"
                "from unittest import mock\n"
                "from loop import config, dash, inference_v2\n"
                "data, prereg = sys.argv[3], sys.argv[4]\n"
                "config.DATA, config.DECISIONS, config.HALT = data, data + '/decisions.jsonl', data + '/HALT'\n"
                "config.PRODUCTS = tuple(sys.argv[5].split(','))\n"
                "dash.PREREG_V2_PATH, dash.v2_spec_sha = prereg, (lambda spec=None: sys.argv[6])\n"
                "inference_v2.seal = lambda repo=None: %r\n"
                "sys.exit(inference_v2.main(sys.argv[8:], now=float(sys.argv[7]), resamples=%d))\n" % (self.SEAL, R_MAIN))
        p = subprocess.run([sys.executable, "-c", boot, os.path.join(REPO, "tests"), REPO, self.data,
                            dash.PREREG_V2_PATH, ",".join(config.PRODUCTS), SHA, str(AFTER)] + self.ARGV,
                           cwd=REPO, env=dict(os.environ, PYTHONHASHSEED="4242", PYTHONIOENCODING="utf-8"), capture_output=True, timeout=300)
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(p.stdout.decode(), self.text)


if __name__ == "__main__":
    unittest.main()

"""report: every CONTRACT §4 section renders from a synthetic 40-row log (5 dry, one
absence, 34 answered, a two-minute hole, one truncated line) and the key numbers are
the ones worked out by hand below. Offline; temp files only; nothing is sent.

The log, minute m of 10:00 UTC on 2026-09-23, m in 0..19 and 22..41 (20 and 21 missing):
  prices   m 10..19 bid/ask 100.99/101.01 mid 101; every other minute 99.99/100.01 mid 100
  adj      liq deep always; flow quiet on m 0,1 else organic (38/40 = 95.0%, NOT > 95%);
           trend pumping 10..19, dumping 22..31, flat else; vol violent 38..41 else normal
  rule_c   buy 10..19; sell 22..31 and 38..41; hold else (CONTRACT §2 by hand)
  mode     dry 0..4 (no answers); m 15 absence "jev" (priced, no answers); else answered
  A        choice = rule_c except hold on 24,25 and buy on 34,35; confidence 0.6 (m<10),
           0.9 (m<20), 0.75 (m<32), 0.99 (m>=32)
  B        = A except sell on 24,25 and hold on 30; confidence = A's minus 0.2 on those three
  prompts  a sha "shaA" always; b "v1"/"shaA" for m < 32, "v2"/"shaB" from 32 (a promote)
  jev      latency 100+m ms and 1000 input tokens on answered rows; m 41 answered by
           "jev-1.14.0" with drift true
Outcomes at h = 15 min, nearest row within +-30 s: m 0..4 up (100 -> 101); m 5 and m 6 GAP (t+h
lands on minute 20 or 21, the hole; the join's first form took minute 22 for m 6, a 16-minute
horizon, and this fixture used to pin that); m 7..9 flat; m 10..19 down; m 22..26 flat; m 27..41
gap (past the log). Blocks (no --t0) are anchored at 10:00: k0 = m 0..14, k1 = m 15..29,
k2 = m 30..41.
"""
import contextlib, io, json, os, tempfile, unittest

from loop import book, config, outcomes, report, rules, state

MINUTES = tuple(range(0, 20)) + tuple(range(22, 42))       # 40 ticks, minutes 20 and 21 missing
N = config.NOTIONAL_USD
FEE = config.FEE_BPS_PRIMARY


def _adj(m):
    return {"liq": "deep", "flow": "quiet" if m < 2 else "organic",
            "trend": "pumping" if 10 <= m <= 19 else "dumping" if 22 <= m <= 31 else "flat",
            "vol": "violent" if m >= 38 else "normal"}


def _rule(m):
    if 10 <= m <= 19:
        return "buy"
    if 22 <= m <= 31 or m >= 38:
        return "sell"
    return "hold"


def _a_choice(m):
    return "hold" if m in (24, 25) else "buy" if m in (34, 35) else _rule(m)


def _b_choice(m):
    return "sell" if m in (24, 25) else "hold" if m == 30 else _a_choice(m)


def _conf(m):
    return 0.6 if m < 10 else 0.9 if m < 20 else 0.75 if m < 32 else 0.99


def _choice(choice, conf):
    rest = (1.0 - conf) / 2
    return {"choice": choice, "confidence": conf,
            "probabilities": {k: conf if k == choice else rest for k in ("buy", "sell", "hold")}}


def _answers(m):
    ca = _conf(m)
    cb = ca - 0.2 if m in (24, 25, 30) else ca
    return {"a_action": _choice(_a_choice(m), ca), "b_action": _choice(_b_choice(m), cb),
            "skip": {"noul": 0.9 if m >= 38 else 0.1},
            "up15": {"noul": 0.995 if 10 <= m <= 12 else 0.2}, "down15": {"noul": 0.3}}


def _row(m):
    bid, ask, mid = (100.99, 101.01, 101.0) if 10 <= m <= 19 else (99.99, 100.01, 100.0)
    dry, absence = m < 5, "jev" if m == 15 else None
    answered = not dry and absence is None
    ans, adj = _answers(m) if answered else None, _adj(m)
    return {"v": 1, "tick_id": f"20260923T10{m:02d}00Z", "ts_rx": f"2026-09-23T10:{m:02d}:00.100Z",
            "mode": "dry" if dry else "live", "venue": "coinbase", "product": "SOL-USD",
            "cadence_s": 60, "horizon_s": 900,
            "bid": bid, "bid_size": 100.0, "ask": ask, "ask_size": 100.0, "mid": mid, "book_time": None,
            "feed_age_s": 5.0, "features": {"mid": mid}, "adj": adj, "state": state.state_string(adj),
            "spec_sha": "spec", "prompt_a": "v1", "prompt_a_sha": "shaA",
            "prompt_b": "v1" if m < 32 else "v2", "prompt_b_sha": "shaA" if m < 32 else "shaB",
            "model_requested": config.MODEL,
            "model_answered": ("jev-1.14.0" if m == 41 else config.MODEL) if answered else None,
            "drift": answered and m == 41,
            "jev": {"latency_ms": 100 + m if answered else None, "input_tokens": 1000 if answered else None,
                    "error": "http-5xx" if absence == "jev" else None,
                    "key_path": None if dry else "env:TYPESAFE_API_KEY_LOOP"},
            "answers": ans, "rule_c": _rule(m),
            "columns": {"a": rules.for_arm(ans, "a") if ans else None, "b": rules.for_arm(ans, "b") if ans else None},
            "absence": absence}


def _write(path, rows, garbage=True):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
        if garbage:
            fh.write('{"v": 1, "tick_id": "20260923T104200Z", "ts_rx": "2026-09-23T10:4')   # a crash mid-write


def _main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = report.main(argv)
    return code, out.getvalue()


class Synthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.log = os.path.join(cls.tmp.name, "decisions.jsonl")
        _write(cls.log, [_row(m) for m in MINUTES])
        cls.bad = []
        cls.rows = outcomes.load(cls.log, cls.bad)
        cls.outs = outcomes.join(cls.rows)
        cls.text = report.render(cls.rows, cls.bad, cls.log)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_fixture_is_what_the_docstring_says(self):
        self.assertEqual(len(self.rows), 40)
        self.assertEqual(len(self.bad), 1)
        self.assertEqual(self.bad[0][0], 41)                            # the truncated 41st line, and only it
        for r in self.rows:                                            # the hand rule matches state.rule_c
            self.assertEqual(r["rule_c"], state.rule_c(r["adj"]))
        labels = {r["tick_id"][11:13]: self.outs[r["tick_id"]]["label"] for r in self.rows}   # YYYYMMDDTHHMM00Z
        self.assertEqual([labels[f"{m:02d}"] for m in range(0, 5)], ["up"] * 5)
        self.assertIsNone(labels["05"])                                # t+h fell in the two-minute hole
        self.assertEqual(self.outs["20260923T100500Z"]["absence"], "gap")
        self.assertIsNone(labels["06"])                                # t+15 = minute 21, also the hole: never minute 22
        self.assertEqual(self.outs["20260923T100600Z"]["absence"], "gap")
        self.assertEqual([labels[f"{m:02d}"] for m in range(7, 10)], ["flat"] * 3)
        self.assertEqual([labels[f"{m:02d}"] for m in range(10, 20)], ["down"] * 10)
        self.assertEqual([labels[f"{m:02d}"] for m in range(22, 27)], ["flat"] * 5)
        self.assertTrue(all(labels[f"{m:02d}"] is None for m in range(27, 42)))

    def test_sections_render_in_order(self):
        pos = [self.text.index(t) for t in report.TITLES]
        self.assertEqual(pos, sorted(pos))
        self.assertEqual(len(report.TITLES), 6)
        self.assertNotIn("p-value", self.text.lower())
        self.assertNotIn("p=", self.text)
        self.assertTrue(self.text.startswith("jev-paper-loop report: coinbase SOL-USD, cadence 60 s, horizon 900 s, log "))

    def test_health(self):
        h = report.health(self.rows, self.outs, self.bad)
        self.assertEqual((h["rows"], h["ticks"], h["live"], h["dry"], h["skipped"]), (40, 40, 34, 5, 1))
        self.assertEqual(h["absence"], {"jev": 1})
        self.assertEqual((h["priced"], h["filled"]), (40, 23))          # 5 up + 3 flat + 10 down + 5 flat
        self.assertEqual(h["fill"], 23 / 40)
        self.assertEqual((h["attempted"], h["errors"]), (35, {"http-5xx": 1}))
        self.assertEqual(h["error_rate"], 1 / 35)
        # latencies 105..114, 116..119, 122..141: sum 1095 + 470 + 2630; rank ceil(0.95*34) = 33 -> 140
        self.assertAlmostEqual(h["latency_mean"], 4195 / 34, places=12)
        self.assertEqual(h["latency_p95"], 140)
        self.assertEqual(h["tokens"], 34000)
        self.assertAlmostEqual(h["usd"], 34000 * 0.042 / 1e6, places=15)
        self.assertEqual(h["models"], {"jev-1.13.0": 33, "jev-1.14.0": 1})
        self.assertEqual(h["drift"], 1)
        self.assertEqual(h["versions"], {"v1": 30, "v2": 10})
        text = "\n".join(h["lines"])
        self.assertIn("rows 40 (40 ticks, 1 day, 20260923T100000Z..20260923T104100Z); skipped lines 1", text)
        self.assertIn("live answered 34; dry 5; absence: jev 1", text)
        self.assertIn("outcome fill 23/40 (57.5%) of priced ticks", text)
        self.assertIn("jev errors 1/35 (2.9%) of attempted sends: http-5xx 1", text)
        self.assertIn("latency ms: mean 123.4, p95 140 (n 34)", text)
        self.assertIn("input tokens 34000 = $0.001428 to date", text)
        self.assertIn("model_answered: jev-1.13.0 33, jev-1.14.0 1 (2 distinct); drift 1", text)
        self.assertIn("prompt_b versions: v1 30, v2 10", text)

    def test_occupancy_and_the_95_percent_flag(self):
        o = report.occupancy(self.rows)
        self.assertEqual(o["n"], 40)                                   # dry and absence rows carry adjectives too
        self.assertEqual(o["share"][("liq", "deep")], 1.0)
        self.assertEqual(o["share"][("flow", "organic")], 38 / 40)     # exactly 95%: not above, not flagged
        self.assertEqual(o["share"][("trend", "pumping")], 10 / 40)
        self.assertEqual(o["share"][("vol", "violent")], 4 / 40)
        self.assertEqual(o["flags"], [("liq", "deep")])
        self.assertEqual(o["states"], 5)
        text = "\n".join(o["lines"])
        self.assertIn("liq   thin 0/40 (0.0%)  normal 0/40 (0.0%)  deep 40/40 (100.0%)", text)
        self.assertIn("flow  quiet 2/40 (5.0%)  organic 38/40 (95.0%)  bot_war 0/40 (0.0%)", text)
        self.assertIn("FLAG liq is deep on 100.0% > 95%", text)
        self.assertEqual(text.count("FLAG"), 1)
        self.assertIn("distinct states 5 of 81 over 40 rows", text)

    def test_retest(self):
        t = report.retest(self.rows)
        self.assertEqual((t["n"], t["agree"]), (24, 21))                # m 5..14, 16..19, 22..31; B differs on 24, 25, 30
        self.assertEqual(t["agree_rate"], 21 / 24)
        self.assertAlmostEqual(t["dconf"], 3 * 0.2 / 24, places=9)      # 0.025
        self.assertIn("choice agreement 21/24 (87.5%); mean |dconfidence| 0.0250 (n 24)", "\n".join(t["lines"]))

    def test_argmax_vs_rule_c(self):
        a = report.agreement(self.rows)
        self.assertEqual((a["n"], a["agree"]), (34, 30))
        self.assertEqual(a["confusion"][("hold", "sell")], 2)          # m 24, 25
        self.assertEqual(a["confusion"][("buy", "hold")], 2)           # m 34, 35
        self.assertEqual(a["confusion"][("buy", "buy")], 9)
        self.assertEqual(a["confusion"][("sell", "sell")], 12)
        self.assertEqual(a["confusion"][("hold", "hold")], 9)
        self.assertIn("a.argmax == rule_c on 30/34 (88.2%)", "\n".join(a["lines"]))

    def test_pair_table_primary_cell_by_hand(self):
        t = report.table(self.rows, self.outs)
        self.assertEqual(t["fees"], config.FEE_BPS_COLUMNS)
        self.assertEqual(len(t["cells"]), 3 * len(rules.COLUMNS) * len(config.FEE_BPS_COLUMNS))
        cell = t["cells"][report.PRIMARY]
        # B and C hold the same position through minute 33 (both open at 10, close at 22). B alone
        # opens at 34 (ask 100.01, mid 100) and closes at 38 (bid 99.99): two ticks with a fee.
        d34 = ((N / 100.01) * (100.0 - 100.01) - N * FEE / 1e4) * 1e4 / N
        d38 = ((N / 100.01) * (99.99 - 100.0) - (N / 100.01) * 99.99 * FEE / 1e4) * 1e4 / N
        d = dict(cell["all"]["d"])
        self.assertAlmostEqual(d["20260923T103400Z"], d34, places=9)
        self.assertAlmostEqual(d["20260923T103800Z"], d38, places=9)
        # the half-spread (0.01 / 100.01 = 0.9999 bps) plus the primary fee, read by name: the
        # primary moved from 60 to 120 bps and a literal here would pin the old one
        self.assertAlmostEqual(d34, -0.9999 - config.FEE_BPS_PRIMARY, places=3)
        for m in MINUTES:
            if m not in (34, 38):
                self.assertEqual(d[f"20260923T10{m:02d}00Z"], 0.0)     # exactly, not almost
        self.assertEqual(cell["all"]["n"], 40)
        self.assertEqual(cell["all"]["dis"], 5)                        # 34 (out), 35, 36, 37 (in and out), 38 (in)
        self.assertAlmostEqual(cell["all"]["mean"], (d34 + d38) / 40, places=9)
        self.assertAlmostEqual(cell["all"]["mean_dis"], (d34 + d38) / 5, places=9)
        self.assertEqual(cell["all"]["hit"], 0.0)
        self.assertEqual(cell["trades_per_day"], (4 * 1440 / 40, 2 * 1440 / 40))   # 144 and 72
        # PREREG §3 blocks, anchored at the first tick (no --t0): d34 and d38 both fall in k2
        blk = cell["blocks"]
        self.assertEqual([k for k, _ in blk["S"]], [0, 1, 2])
        self.assertEqual(blk["S"][:2], [(0, 0.0), (1, 0.0)])
        self.assertAlmostEqual(blk["S"][2][1], d34 + d38, places=9)
        self.assertEqual((blk["n"], blk["dis"], blk["share"]), (3, 1, 1 / 3))
        self.assertAlmostEqual(blk["mean"], (d34 + d38) / 3, places=9)
        self.assertAlmostEqual(blk["mean_dis"], d34 + d38, places=9)
        self.assertEqual(t["anchor"], report.tick_epoch("20260923T100000Z"))
        # the report's d_t is book.paired's, tick for tick
        self.assertEqual(cell["all"]["d"], book.paired(self.rows, self.outs, "b", "c", "argmax", FEE))
        # B-A: B's extra hold on 30 while flat is a no-op, so the positions never differ
        ba = t["cells"][("b", "a", "argmax", FEE)]["all"]
        self.assertEqual((ba["dis"], ba["mean"], ba["mean_dis"], ba["hit"]), (0, 0.0, None, None))
        self.assertEqual(t["per_arm"]["c"]["trades"], 2)
        self.assertEqual(t["per_arm"]["c"]["forced_hold"], 6)          # 5 dry + 1 absence: a dry row is forced for C too
        self.assertEqual(t["per_arm"]["a"]["forced_hold"], 6)          # 5 dry + 1 absence
        self.assertEqual(t["per_arm"]["a"]["trades"], 4)
        c10 = ((N / 101.01) * (101.0 - 101.01) - N * FEE / 1e4) * 1e4 / N
        c22 = ((N / 101.01) * (99.99 - 101.0) - (N / 101.01) * 99.99 * FEE / 1e4) * 1e4 / N
        self.assertAlmostEqual(t["per_arm"]["c"]["equity"], c10 + c22, places=9)

    def test_pair_table_renders_every_cell_once_with_one_primary(self):
        lines = report.table(self.rows, self.outs)["lines"]
        cells = [l for l in lines if l.startswith("  * ") or l.startswith("    ")]
        cells = [l for l in cells if l.split()[1 if l.startswith("  * ") else 0] in rules.COLUMNS]
        self.assertEqual(len(cells), len(report.PAIRS) * len(rules.COLUMNS) * len(config.FEE_BPS_COLUMNS))
        self.assertEqual(sum(l.startswith("  * argmax") for l in cells), 1)
        self.assertEqual(sum("[* primary]" in l for l in lines), 1)
        self.assertIn(f"pair B-C  fee {config.FEE_BPS_PRIMARY:g} bps  [* primary]", "\n".join(lines))
        self.assertIn(0.0, config.FEE_BPS_COLUMNS)                      # the gross, direction-only control
        self.assertIn("pair B-C  fee 0 bps\n", "\n".join(lines) + "\n")  # is a column, and never the primary
        for x, y in report.PAIRS:
            for fee in config.FEE_BPS_COLUMNS:
                self.assertIn(f"pair {x.upper()}-{y.upper()}  fee {fee:g} bps", "\n".join(lines))
        star = next(l for l in cells if l.startswith("  * "))
        self.assertEqual(star.split()[:4], ["*", "argmax", "40", "5"])
        self.assertIn("144.0", star)
        self.assertIn("72.0", star)

    def test_calibration_bins(self):
        c = report.calibration(self.rows, self.outs)
        self.assertEqual((c["n"], c["below"]), (17, 0))
        want = [(0.5, 0.7, 3, 3, 1.0),          # m 7..9: hold and flat (m 5, 6: gap)
                (0.7, 0.85, 5, 2, 2 / 5),       # m 22..26: sell/flat wrong x3, hold/flat right x2
                (0.85, 0.99, 9, 0, 0.0),        # m 10..14, 16..19: buy into a down move
                (0.99, 1.0, 0, 0, None)]        # m 32..41: no outcome yet
        self.assertEqual([(b["lo"], b["hi"], b["n"], b["correct"], b["p"]) for b in c["bins"]], want)
        text = "\n".join(c["lines"])
        self.assertIn("[0.50, 0.70)", text)
        self.assertIn("[0.99, 1.00]", text)
        self.assertRegex(text, r"\[0\.70, 0\.85\)\s+5\s+2\s+40\.0%")

    def test_bin_edges(self):
        self.assertEqual([report._bin(x) for x in (0.49, 0.5, 0.69, 0.7, 0.85, 0.99, 1.0)], [None, 0, 0, 1, 2, 3, 3])
        self.assertEqual(report._p95([1]), 1)
        self.assertEqual(report._p95(list(range(1, 21))), 19)            # ceil(19) = 19th of 20
        self.assertIsNone(report._p95([]))

    def test_main_matches_render_and_since(self):
        code, out = _main(["--log", self.log])
        self.assertEqual(code, 0)
        self.assertEqual(out, self.text)
        code, out = _main(["--log", self.log, "--since", "2026-09-23"])
        self.assertIn("since 2026-09-23", out.splitlines()[0])
        self.assertIn("rows 40 (40 ticks", out)
        code, out = _main(["--log", self.log, "--since", "2026-09-24"])
        self.assertEqual(code, 0)
        self.assertIn("empty log since 2026-09-24: no rows", out)
        self.assertIn("rows 0 (0 ticks, 0 days, -)", out)
        for t in report.TITLES:
            self.assertIn(t, out)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                report.main(["--log", self.log, "--since", "yesterday"])
        self.assertEqual(cm.exception.code, 2)


class SampleAndSides(unittest.TestCase):
    """PREREG §2-§4 as the report prints them: --t0 cuts to [T0, T0 + 28 d) before any replay
    and anchors the 900 s blocks at T0; disagreement is on the side, not the quantity."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.log = os.path.join(cls.tmp.name, "decisions.jsonl")
        cls.rows = [_row(m) for m in MINUTES]
        _write(cls.log, cls.rows, garbage=False)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_t0_cuts_the_sample_and_anchors_the_blocks(self):
        t0 = report._t0("2026-09-23T10:25")
        self.assertEqual(t0, report._t0("20260923T102500Z"))           # PREREG §11 records a tick_id
        cut = report.in_sample(self.rows, t0)
        self.assertEqual([r["tick_id"] for r in cut][0], "20260923T102500Z")
        self.assertEqual(len(cut), 17)                                  # m 25..41
        t = report.table(cut, outcomes.join(self.rows), t0)
        self.assertEqual(t["anchor"], t0)
        self.assertEqual(t["per_arm"]["c"]["trades"], 0)               # flat at T0: C's pre-T0 long never enters
        blk = t["cells"][report.PRIMARY]["blocks"]
        self.assertEqual([k for k, _ in blk["S"]], [0, 1])              # k0 = m 25..39, k1 = m 40..41
        self.assertEqual((blk["n"], blk["dis"]), (2, 1))
        self.assertEqual(blk["S"][1], (1, 0.0))
        code, out = _main(["--log", self.log, "--t0", "2026-09-23T10:25"])
        self.assertEqual(code, 0)
        self.assertIn("T0 2026-09-23T10:25Z (sample [T0, T0 + 28 d), replayed from flat at T0)", out.splitlines()[0])
        self.assertIn("rows 17 (17 ticks", out)
        self.assertIn("H1 statistic (PREREG §4), mean S_k at the primary cell:", out)
        self.assertIn("anchored at T0 2026-09-23T10:25Z (--t0)", out)
        self.assertEqual(out, _main(["--log", self.log, "--t0", "20260923T102500Z"])[1])

    def test_sample_ends_before_t0_plus_28_days(self):
        t0 = report._t0("2026-08-26T10:20")                             # T0 + 28 d = 2026-09-23T10:20
        cut = report.in_sample(self.rows, t0)
        self.assertEqual((len(cut), cut[-1]["tick_id"]), (20, "20260923T101900Z"))

    def test_bad_t0_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                report.main(["--log", self.log, "--t0", "2026-09-23"])
        self.assertEqual(cm.exception.code, 2)

    def test_two_longs_on_different_entries_are_not_a_disagreement(self):
        # A buys at 10:00 (ask 100.01), C at 10:01 (ask 105.01); both long into and out of
        # 10:02. Their qty differ, so d_t at 10:02 is (qa - qc) * dmid, not 0.0 -- but the
        # sides agree, and a disagreement is a difference of side.
        def r(m, bid, ask, a, c):
            x = _row(22 + m)                                            # a live, answered row to start from
            x.update(tick_id=f"20260923T10{m:02d}00Z", ts_rx=f"2026-09-23T10:{m:02d}:00.100Z",
                     bid=bid, ask=ask, mid=(bid + ask) / 2, rule_c=c, absence=None, mode="live")
            x["columns"] = {"a": {k: a for k in rules.COLUMNS}, "b": {k: a for k in rules.COLUMNS}}
            return x
        rows = [r(0, 99.99, 100.01, "buy", "hold"), r(1, 104.99, 105.01, "hold", "buy"),
                r(2, 109.99, 110.01, "hold", "hold")]
        pa, pc = (book.replay(rows, None, arm, "argmax", 0.0) for arm in ("a", "c"))
        self.assertEqual(report._disagreement(pa, pc), {"20260923T100000Z", "20260923T100100Z"})
        qa, qc = N / 100.01, N / 105.01
        d2 = dict(book.paired(rows, None, "a", "c", "argmax", 0.0))["20260923T100200Z"]
        self.assertAlmostEqual(d2, (qa - qc) * (110.0 - 105.0) * 1e4 / N, places=9)
        self.assertNotEqual(d2, 0.0)


class Degenerate(unittest.TestCase):
    def test_missing_log(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = _main(["--log", os.path.join(d, "none.jsonl")])
        self.assertEqual(code, 0)
        self.assertIn("no log at", out)
        self.assertIn("rows 0 (0 ticks", out)
        self.assertIn("no rows with adjectives", out)
        self.assertIn("nothing to compare", out)
        self.assertIn("no row carries both", out)
        self.assertIn("no answered rows", out)
        self.assertIn("nothing to calibrate", out)
        for t in report.TITLES:
            self.assertIn(t, out)

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "decisions.jsonl")
            open(p, "w").close()
            code, out = _main(["--log", p])
        self.assertEqual(code, 0)
        self.assertIn("empty log: no rows", out)
        self.assertIn("outcome fill 0/0 (n/a)", out)

    def test_dry_only_log(self):
        rows = [_row(m) for m in range(5)]                              # the five dry rows: adjectives, no answers
        text = report.render(rows, [], "x")
        self.assertIn("dry-only log: 5 rows and none answered", text)
        self.assertIn("live answered 0; dry 5; absence: none", text)
        self.assertIn("deep 5/5 (100.0%)", text)
        self.assertIn("FLAG liq is deep", text)
        self.assertIn("no answered rows: arms A and B replay as forced holds", text)
        self.assertNotIn("pair B-C", text)
        self.assertIn("C equity 0.00 bps, trades 0, forced holds 5", text)   # a dry row is a forced hold for every arm
        self.assertIn("A equity 0.00 bps, trades 0, forced holds 5", text)
        self.assertIn("nothing to calibrate", text)

    def test_no_network_no_key_no_write(self):
        import inspect
        src = inspect.getsource(report)
        for word in ("urllib", "socket", "http.client", "subprocess", "KEY_PATHS", "open("):
            self.assertNotIn(word, src)


if __name__ == "__main__":
    unittest.main()

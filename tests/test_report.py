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
import contextlib, datetime, io, json, math, os, tempfile, unittest
from unittest import mock

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
        # 2026-09-24, decided by Alex: H2 moved to the direction probabilities (§6); the old
        # arm-A confidence table stays as a descriptive §7, so there are seven sections, not six.
        self.assertEqual(len(report.TITLES), 7)
        self.assertTrue(report.TITLES[5].startswith("6. H2: "))
        self.assertIn("rule-matching, not outcomes (descriptive)", report.TITLES[6])
        self.assertNotIn("p-value", self.text.lower())
        self.assertNotIn("p=", self.text)
        self.assertTrue(self.text.startswith("jev-paper-loop report: coinbase SOL-USD, cadence 60 s, horizon 900 s, log "))

    def test_health(self):
        halt = os.path.join(tempfile.mkdtemp(), "HALT")                 # never the repo's data/HALT: a live HALT on the
        with mock.patch.object(config, "HALT", halt):                   # Mac must not turn the commit gate red
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
        self.assertIn("key answering: env:TYPESAFE_API_KEY_LOOP 35", text)        # 34 answered + the jev-error row
        self.assertNotIn("SHARED KEY", text)
        self.assertEqual(h["shared_key_rows"], 0)
        # the fixture ticks every 60 s exactly: the join lands on t + 900 with no offset
        self.assertIn("realised horizon, ts_rx to ts_rx of the row the join picked: mean 900.0 s, |offset from 900| p95 0 s, max 0 s (n 23); isolated skipped minutes 0", text)
        self.assertEqual((h["horizon"]["n"], h["horizon"]["mean"], h["horizon"]["max"], h["horizon"]["skips"]), (23, 900.0, 0.0, 0))
        self.assertIn("HALT: absent", text)
        self.assertFalse(h["halt"])
        with open(halt, "w") as fh:
            fh.write("spend: $0.2513 of input tokens today\n")
        with mock.patch.object(config, "HALT", halt):
            h = report.health(self.rows, self.outs, self.bad)
        self.assertTrue(h["halt"])
        self.assertIn("HALT: PRESENT since 20", "\n".join(h["lines"]))
        self.assertIn("clearing it is a person's act", "\n".join(h["lines"]))

    def test_shared_key_skipped_minutes_and_the_receive_time_horizon_are_named(self):
        rows = [dict(_row(m)) for m in range(5, 40) if m != 20]                # minute 20 has no row: one isolated skip
        for r in rows:
            r["jev"] = dict(r["jev"], key_path="file:~/.secondbrain-secrets/typesafe-api-key")   # the brain's key, not the loop's
        rows[1]["ts_rx"] = "2026-09-23T10:06:40.000Z"                            # received 40 s into its minute: the join
        outs = outcomes.join(rows)                                               # takes the 10:22 row (+20.1 s), not 10:21
        h = report.health(rows, outs)                                            # (-39.9 s, outside the +-30 s window)
        text = "\n".join(h["lines"])
        self.assertIn("SHARED KEY on 34 rows", text)
        self.assertEqual(h["horizon"]["skips"], 1)
        self.assertIn("isolated skipped minutes 1 (a missed :00 fire; until 2026-09-27 05:18Z launchd's 60 s StartInterval ran a ~61 s grid", text)
        self.assertEqual(outs[rows[1]["tick_id"]]["mid_h"], rows[16]["mid"])      # minute 22's row (minute 20 is missing)
        self.assertAlmostEqual(h["horizon"]["max"], 20.1, places=6)                # the fixture rows carry .100 ms
        self.assertLessEqual(h["horizon"]["max"], outcomes.JOIN_TOL_S)             # never a row the join did not take
        self.assertEqual(h["horizon"]["n"], sum(1 for r in rows if outs[r["tick_id"]]["absence"] is None))
        self.assertEqual(h["days"][0]["skips"], 1)
        self.assertIn("    20260923     34   2.4%", text)

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
        # 2026-09-24, decided by Alex: the primary is 0 bps, gross. The same hand arithmetic is
        # run at the venue's 120 bps too, so the fee terms below are still exercised with a
        # non-zero constant now that the primary's own fee term is 0.
        self.assertEqual(report.PRIMARY, ("b", "c", "argmax", 0.0))
        for fee in (FEE, config.FEE_BPS_VENUE):
            with self.subTest(fee=fee):
                cell = t["cells"][("b", "c", "argmax", fee)]
                # B and C hold the same position through minute 33 (both open at 10, close at 22). B alone
                # opens at 34 (ask 100.01, mid 100) and closes at 38 (bid 99.99): two ticks with a fee.
                d34 = ((N / 100.01) * (100.0 - 100.01) - N * fee / 1e4) * 1e4 / N
                d38 = ((N / 100.01) * (99.99 - 100.0) - (N / 100.01) * 99.99 * fee / 1e4) * 1e4 / N
                d = dict(cell["all"]["d"])
                self.assertAlmostEqual(d["20260923T103400Z"], d34, places=9)
                self.assertAlmostEqual(d["20260923T103800Z"], d38, places=9)
                # the half-spread (0.01 / 100.01 = 0.9999 bps) plus the fee, read by name
                self.assertAlmostEqual(d34, -0.9999 - fee, places=3)
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
                # the report's d_t is book.paired's, tick for tick
                self.assertEqual(cell["all"]["d"], book.paired(self.rows, self.outs, "b", "c", "argmax", fee))
        self.assertEqual(t["anchor"], report.tick_epoch("20260923T100000Z"))
        # B-A: B's extra hold on 30 while flat is a no-op, so the positions never differ
        ba = t["cells"][("b", "a", "argmax", FEE)]["all"]
        self.assertEqual((ba["dis"], ba["mean"], ba["mean_dis"], ba["hit"]), (0, 0.0, None, None))
        self.assertEqual(t["per_arm"]["c"]["trades"], 2)
        self.assertEqual(t["per_arm"]["c"]["forced_hold"], 6)          # 5 dry + 1 absence: a dry row is forced for C too
        self.assertEqual(t["per_arm"]["a"]["forced_hold"], 6)          # 5 dry + 1 absence
        self.assertEqual(t["per_arm"]["a"]["trades"], 4)
        for fee, per in ((FEE, t["per_arm"]), (config.FEE_BPS_VENUE, t["per_arm_venue"])):
            c10 = ((N / 101.01) * (101.0 - 101.01) - N * fee / 1e4) * 1e4 / N
            c22 = ((N / 101.01) * (99.99 - 101.0) - (N / 101.01) * 99.99 * fee / 1e4) * 1e4 / N
            self.assertAlmostEqual(per["c"]["equity"], c10 + c22, places=9)
            self.assertEqual(per["c"]["trades"], 2)                    # a fee never changes a decision

    def test_pair_table_renders_every_cell_once_with_one_primary(self):
        lines = report.table(self.rows, self.outs)["lines"]
        cells = [l for l in lines if l.startswith("  * ") or l.startswith("    ")]
        cells = [l for l in cells if l.split()[1 if l.startswith("  * ") else 0] in rules.COLUMNS]
        self.assertEqual(len(cells), len(report.PAIRS) * len(rules.COLUMNS) * len(config.FEE_BPS_COLUMNS))
        self.assertEqual(sum(l.startswith("  * argmax") for l in cells), 1)
        self.assertEqual(sum("[* primary]" in l for l in lines), 1)
        # 2026-09-24, decided by Alex: the primary IS the 0 bps gross column (it used to be the
        # control and never the primary); the venue's own taker fee is now a column that is never
        # the primary, printed with its source as the realistic cost.
        self.assertEqual(config.FEE_BPS_PRIMARY, 0.0)
        self.assertIn("pair B-C  fee 0 bps  [* primary]\n", "\n".join(lines) + "\n")
        self.assertEqual(config.FEE_BPS_COLUMNS, tuple(sorted(config.FEE_BPS_COLUMNS)))   # ascending, 0 first
        self.assertEqual(config.FEE_BPS_COLUMNS[0], config.FEE_BPS_PRIMARY)
        self.assertIn(config.FEE_BPS_VENUE, config.FEE_BPS_COLUMNS)
        self.assertIn(f"pair B-C  fee {config.FEE_BPS_VENUE:g} bps  [venue fee]\n", "\n".join(lines) + "\n")
        self.assertEqual(sum("[venue fee]" in l for l in lines), len(report.PAIRS))
        text = "\n".join(lines)
        self.assertIn(f"primary fee 0 bps (config.FEE_BPS_PRIMARY): gross of fees", text)
        # review, 2026-09-24: gross of fees is NOT free of turnover -- a round trip still pays the
        # spread (tests/test_book.py pins 0.87 / 1.74 bps), so the header must not say otherwise.
        self.assertIn("direction net of the spread", text)
        self.assertNotIn("not turnover", text)
        self.assertIn(f"venue fee {config.FEE_BPS_VENUE:g} bps (config.FEE_BPS_VENUE)", text)
        self.assertIn(config.FEE_BPS_VENUE_SOURCE, text)                 # UNVERIFIED, beside the table
        self.assertTrue(config.FEE_BPS_VENUE_SOURCE.startswith("UNVERIFIED"))
        self.assertFalse(hasattr(config, "FEE_BPS_PRIMARY_SOURCE"))      # moved: the primary has no source, it is 0
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
        # descriptive since 2026-09-24: beside P(correct), how often a.argmax IS rule_c per bin
        # (m 7..9 hold = rule 3/3; m 22..26 A holds on 24, 25 against the rule's sell: 3/5; m 10..19 buy 9/9)
        self.assertEqual([(b["rule"], b["p_rule"]) for b in c["bins"]], [(3, 1.0), (3, 3 / 5), (9, 1.0), (0, None)])
        self.assertRegex(text, r"\[0\.70, 0\.85\)\s+5\s+2\s+40\.0%\s+60\.0%")
        self.assertTrue(c["lines"][0].startswith("  not H2 (PREREG §5, 2026-09-24): "))

    def test_h2_on_the_fixture(self):
        # Blocks anchored at 10:00. k0's first live row is m 5 (gap), k1's is m 16 (m 15 is the
        # jev absence), k2's is m 30 (gap): one unit, so r is undefined and the report says so.
        h = report.h2(self.rows, self.outs)
        a = 1e4 * math.log(100.0 / 101.0)                               # m 10..19 at 101 -> 100 at t+15
        self.assertEqual((h["blocks"], h["dropped"]), (3, {"gap": 2}))
        u = h["units"]
        self.assertEqual([(p["tick"], p["lean"]) for p in u["pairs"]], [("20260923T101600Z", -0.1)])
        self.assertAlmostEqual(u["pairs"][0]["ret"], a, places=9)
        self.assertEqual((u["n"], u["r"], u["rho"], u["why"]), (1, None, None, "fewer than 2 pairs (n 1)"))
        # every live tick with a pair: m 7..9 (lean -0.1, ret 0), m 10..12 (0.695, a), m 13, 14, 16..19
        # (-0.1, a), m 22..26 (-0.1, 0) = 17; dropped as gaps: m 5, 6, 27..41 = 17
        e = h["every"]
        self.assertEqual((e["n"], h["dropped_every"]), (17, {"gap": 17}))
        # r by hand, a factored out (r is sign(a) times a function of the leans alone):
        # sxy/a = 3(0.695) + 6(-0.1) - 17 mx my/a, mx = 0.685/17, my/a = 9/17; syy/a^2 = 9 - 81/17
        sxy = 3 * 0.695 - 0.6 - 0.685 * 9 / 17
        sxx = 3 * 0.695 ** 2 + 14 * 0.01 - 0.685 ** 2 / 17
        self.assertAlmostEqual(e["r"], -sxy / math.sqrt(sxx * (9 - 81 / 17)), places=12)
        text = "\n".join(h["lines"])
        self.assertIn("Pearson r(lean, ret_h_bps) over 1 units: undefined (fewer than 2 pairs (n 1))", text)
        self.assertIn("3 blocks with a live row, dropped: gap 2, missing noul 0; 1 units", text)
        self.assertIn("anchored at the log's first tick 20260923T100000Z; no --t0, so descriptive only", text)
        self.assertIn("measured tails (>= 0.99 / < 0.15): units up15 0/0, down15 0/0; every tick up15 3/0, down15 0/0", text)
        self.assertIn(report.TITLES[5] + "\n" + text + "\n", self.text)

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

    def test_health_only_is_sections_1_to_3_and_nothing_else(self):
        # PREREG §8.4: the day-14 look reads report §1-§3 only. Without --health every run prints
        # H1's and H2's headline numbers; --health neither computes nor prints sections 4-7.
        code, out = _main(["--log", self.log, "--health"])
        self.assertEqual(code, 0)
        note = ("health only (--health, PREREG §8.4's day-14 look): sections 1-3; sections 4-7 are neither"
                " computed nor printed\n")
        self.assertEqual(out.splitlines()[1] + "\n", note)
        cut = self.text.index("\n\n" + report.TITLES[3])
        self.assertEqual(out.replace(note, "", 1), self.text[:cut] + "\n")   # sections 1-3 exactly as the full report
        for t in report.TITLES[:3]:
            self.assertIn(t, out)
        for t in report.TITLES[3:]:
            self.assertNotIn(t, out)
        for word in ("H1 cell", "H2 statistic", "Pearson", "Spearman", "Brier", "P(correct)", "pair B-C"):
            self.assertIn(word, self.text)                              # the full report prints each of them ...
            self.assertNotIn(word, out)                                 # ... and the blind look none
        self.assertEqual(report.render(self.rows, self.bad, self.log, health_only=True), out)
        with tempfile.TemporaryDirectory() as d:
            code, out = _main(["--log", os.path.join(d, "none.jsonl"), "--health"])
        self.assertEqual(code, 0)
        self.assertIn("no log at", out)
        self.assertNotIn(report.TITLES[5], out)


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
        self.assertIn("H1 cell (PREREG §4), mean S_k at the primary cell, descriptive here (the statistic is loop.inference's", out)
        self.assertIn("anchored at T0 2026-09-23T10:25Z (--t0)", out)
        self.assertEqual(out, _main(["--log", self.log, "--t0", "20260923T102500Z"])[1])

    def test_blocks_run_to_the_logs_last_tick_and_the_cell_is_labelled_descriptive(self):
        # 2026-09-28 (review): the table's block count stopped at the last tick in the cut, so with
        # --t0 the "H1 statistic" line averaged over fewer blocks than PREREG's 2,688 and could
        # differ from loop.inference's number; it is now labelled descriptive and, given the whole
        # log's last tick, runs to the end of the log (capped at the sample's 2,688 blocks)
        from loop import outcomes
        rows = [_row(m) for m in MINUTES]
        outs = outcomes.join(rows)
        t0 = report.tick_epoch("20260923T100000Z")
        tb = report.table(rows, outs, t0)                               # no `last`: k0 .. the last tick's block
        self.assertEqual(tb["cells"][report.PRIMARY]["blocks"]["n"], 3)
        tb = report.table(rows, outs, t0, last=t0 + 5 * 900)              # a log that runs 75 min past the cut
        self.assertEqual(tb["cells"][report.PRIMARY]["blocks"]["n"], 6)
        self.assertEqual([v for _, v in tb["cells"][report.PRIMARY]["blocks"]["S"][3:]], [0.0, 0.0, 0.0])
        tb = report.table(rows, outs, t0, last=t0 + 40 * 86400)            # never past the sample's 2,688
        self.assertEqual(tb["cells"][report.PRIMARY]["blocks"]["n"], 96 * 28)
        self.assertEqual(tb["cells"][report.PRIMARY]["blocks"]["pre"], 0)
        blk = report._blocks([("20260923T095900Z", 5.0), ("20260923T100000Z", 1.0)], set(), t0)
        self.assertEqual((blk["pre"], blk["n"], blk["S"]), (1, 1, [(0, 1.0)]))   # a tick before the anchor is counted out loud
        # the block index map computed once per table equals the per-tick arithmetic
        kof = {t: int((report.tick_epoch(t) - t0) // report.BLOCK_S) for t in {r["tick_id"] for r in rows}}
        a = report._blocks(tb["cells"][report.PRIMARY]["all"]["d"], set(), t0, kof, 4)
        b = report._blocks(tb["cells"][report.PRIMARY]["all"]["d"], set(), t0, None, 4)
        self.assertEqual(a["S"], b["S"])

    def test_tick_epoch_is_strptime_exactly_and_refuses_what_it_refused(self):
        import calendar, random
        rng = random.Random(3)
        for _ in range(2000):
            e = 946684800 + 60 * rng.randrange(0, 60 * 24 * 366 * 40)
            tid = datetime.datetime.fromtimestamp(e, datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self.assertEqual(report.tick_epoch(tid), float(e))
            self.assertEqual(report.tick_epoch(tid), datetime.datetime.strptime(tid, "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc).timestamp())
        self.assertEqual(report.tick_epoch("20240229T235900Z"), calendar.timegm((2024, 2, 29, 23, 59, 0)))
        for bad in ("20261399T000000Z", "20260230T000000Z", "2026092T2140000Z", "20260925T214000", "20260925T2140x0Z", "20260925 214000Z"):
            with self.assertRaises(ValueError, msg=bad):
                report.tick_epoch(bad)

    def test_a_skipped_minute_is_its_own_days_and_dNN_sorts_by_number(self):
        from loop import outcomes
        t0 = report.tick_epoch("20260923T100000Z")
        rows = [dict(_row(m)) for m in range(5, 40) if m != 20]
        # T0 at 10:20: minute 20 is the first minute of d01, so its skip is d01's, not d00's (the row before it)
        h = report.health(rows, outcomes.join(rows), t0=report.tick_epoch("20260923T102000Z"))
        self.assertEqual({d["day"]: d["skips"] for d in h["days"]}, {"d00": 0, "d01": 1})
        self.assertEqual([report._day_key(x) for x in ("d-1", "d00", "d01", "d10")], [(0, -1), (0, 0), (0, 1), (0, 10)])
        self.assertEqual(sorted(["d10", "d2", "d-1", "d00"], key=report._day_key), ["d-1", "d00", "d2", "d10"])
        self.assertEqual(report._day_key("20260923"), (1, "20260923"))

    def test_sample_ends_before_t0_plus_28_days(self):
        t0 = report._t0("2026-08-26T10:20")                             # T0 + 28 d = 2026-09-23T10:20
        cut = report.in_sample(self.rows, t0)
        self.assertEqual((len(cut), cut[-1]["tick_id"]), (20, "20260923T101900Z"))

    def test_a_row_exactly_at_t0_plus_28_days_is_out(self):
        # the fixture has no rows at 10:20 and 10:21, so end = 10:22 lands on a real row: it is excluded (<)
        cut = report.in_sample(self.rows, report._t0("2026-08-26T10:22"))
        self.assertEqual(cut[-1]["tick_id"], "20260923T101900Z")
        self.assertNotIn("20260923T102200Z", [r["tick_id"] for r in cut])
        cut = report.in_sample(self.rows, report._t0("2026-08-26T10:23"))
        self.assertEqual(cut[-1]["tick_id"], "20260923T102200Z")

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


def _h2_row(m, mid, up, down, mode="live"):
    """A live, answered row at minute m after 10:00 (m may pass 59) with the two direction
    nouls set; up None drops the up15 noul (rules read it as 0.0, the report as missing)."""
    x = _row(22)
    x.update(tick_id=f"20260923T{10 + m // 60:02d}{m % 60:02d}00Z", ts_rx=f"2026-09-23T{10 + m // 60:02d}:{m % 60:02d}:00.100Z",
             mid=mid, bid=mid - 0.01, ask=mid + 0.01, mode=mode, absence=None)
    if mode == "dry":
        x.update(answers=None, columns={"a": None, "b": None})
        return x
    x["answers"]["up15"] = {"type": "noul"} if up is None else {"type": "noul", "noul": up}
    x["answers"]["down15"] = {"type": "noul", "noul": down}
    x["columns"] = {"a": rules.for_arm(x["answers"], "a"), "b": rules.for_arm(x["answers"], "b")}
    return x


def _h2_log(rets, nouls, dry=(), missing=(), other=(0.995, 0.05)):
    """Blocks of 15 minutes from 10:00, one more than len(rets); every row of block k has mid
    M_k and M_{k+1} = M_k exp(rets[k] / 1e4), so every tick of block k has ret_h_bps = rets[k]
    (the last block's t+h is past the log: gap). nouls: {minute: (up, down)}, else `other`."""
    mids = [100.0]
    for y in rets:
        mids.append(mids[-1] * math.exp(y / 1e4))
    return [_h2_row(m, mids[m // 15], *nouls.get(m, other), mode="dry" if m in dry else "live")
            for m in range(15 * len(mids)) if m not in missing]


class H2(unittest.TestCase):
    """PREREG §5 (2026-09-24, decided by Alex): Pearson r between lean = up15 - down15 and
    ret_h_bps on the first live row of each 900 s block, rho, Brier vs the base rate, tails.

    The log: 90 minutes, six blocks, ret by block (-10, 0, 0, +10, 0, gap). Minute 15 is dry
    and minute 30 is missing, so the first live rows are m 0, 16, 31, 45, 60, 75. Their nouls
    (up, down): (0.3, 0.2), (0.4, 0.3), (0.5, 0.2), (0.6, 0.1), (missing, 0.4), default; every
    other row is (0.995, 0.05), a tail on each side. 0.3 - 0.2 and 0.4 - 0.3 differ in binary
    and are both 0.1 after the report's rounding, a tie."""

    @classmethod
    def setUpClass(cls):
        cls.rows = _h2_log([-10, 0, 0, 10, 0], {0: (0.3, 0.2), 16: (0.4, 0.3), 31: (0.5, 0.2), 45: (0.6, 0.1),
                                                60: (None, 0.4)}, dry={15}, missing={30})
        cls.outs = outcomes.join(cls.rows)
        cls.h = report.h2(cls.rows, cls.outs)

    def test_pearson_and_spearman_by_hand(self):
        # x = (1, 2, 3, 4), y = (1, 3, 2, 4): dx = dy up to order = (-1.5, -.5, .5, 1.5); sxy 4, sxx = syy = 5
        self.assertAlmostEqual(report.pearson([1, 2, 3, 4], [1, 3, 2, 4]), 0.8, places=15)
        self.assertAlmostEqual(report.spearman([1, 2, 3, 4], [1, 3, 2, 4]), 0.8, places=15)
        # ties take the mean rank: (0.1, 0.1, 0.3, 0.5) -> (1.5, 1.5, 3, 4); (-10, 0, 0, 10) -> (1, 2.5, 2.5, 4)
        self.assertEqual(report.ranks([0.1, 0.1, 0.3, 0.5]), [1.5, 1.5, 3.0, 4.0])
        self.assertEqual(report.ranks([0.0, -10.0, 10.0, 0.0]), [2.5, 1.0, 4.0, 2.5])
        # r: dx = (-.15, -.15, .05, .25), dy = (-10, 0, 0, 10): sxy 4, sxx .11, syy 200 -> 4 / sqrt(22)
        self.assertAlmostEqual(report.pearson([0.1, 0.1, 0.3, 0.5], [-10, 0, 0, 10]), 4 / math.sqrt(22), places=12)
        # rho: rank dx = (-1, -1, .5, 1.5), dy = (-1.5, 0, 0, 1.5): 3.75 / 4.5 = 5/6
        self.assertAlmostEqual(report.spearman([0.1, 0.1, 0.3, 0.5], [-10, 0, 0, 10]), 5 / 6, places=12)

    def test_units_are_the_first_live_row_of_each_block(self):
        u = self.h["units"]
        self.assertEqual([p["tick"][9:13] for p in u["pairs"]], ["1000", "1016", "1031", "1045"])
        self.assertEqual([p["lean"] for p in u["pairs"]], [0.1, 0.1, 0.3, 0.5])
        for p, y in zip(u["pairs"], (-10.0, 0.0, 0.0, 10.0)):
            self.assertAlmostEqual(p["ret"], y, places=9)
        self.assertEqual([p["label"] for p in u["pairs"]], ["down", "flat", "flat", "up"])
        self.assertEqual((self.h["blocks"], self.h["dropped"]), (6, {"noul": 1, "gap": 1}))   # m 60, m 75
        self.assertAlmostEqual(u["r"], 4 / math.sqrt(22), places=9)                      # the pair above, by hand
        self.assertAlmostEqual(u["rho"], 5 / 6, places=12)
        self.assertIsNone(u["why"])
        text = "\n".join(self.h["lines"])
        self.assertIn(f"H2 statistic (PREREG §5), Pearson r(lean, ret_h_bps) over 4 units: {4 / math.sqrt(22):.4f};"
                      f" Spearman rho {5 / 6:.4f} (descriptive)", text)
        self.assertIn("6 blocks with a live row, dropped: gap 1, missing noul 1; 4 units", text)

    def test_every_tick_is_beside_the_statistic_not_it(self):
        # live rows with a pair: m 0..74 less m 15 (dry), 30 (missing), 60 (no up15) = 72; m 75..89: gap
        e = self.h["every"]
        self.assertEqual((e["n"], self.h["dropped_every"]), (72, {"gap": 15, "noul": 1}))
        want = [m for m in range(75) if m not in (15, 30, 60)]
        self.assertEqual([p["tick"] for p in e["pairs"]], [f"20260923T{10 + m // 60:02d}{m % 60:02d}00Z" for m in want])
        firsts = {0: 0.1, 16: 0.1, 31: 0.3, 45: 0.5}
        xs = [firsts.get(m, 0.945) for m in want]
        ys = [(-10.0, 0.0, 0.0, 10.0, 0.0)[m // 15] for m in want]
        self.assertAlmostEqual(e["r"], report.pearson(xs, ys), places=9)
        self.assertNotAlmostEqual(e["r"], self.h["units"]["r"], places=2)

    def test_perfectly_informative_lean_is_r_1(self):
        # ret_h_bps = 100 x lean at every unit: a straight line through the units
        leans = {0: (0.4, 0.6), 15: (0.55, 0.45), 30: (0.65, 0.35), 45: (0.57, 0.5)}      # -0.2, 0.1, 0.3, 0.07
        rows = _h2_log([-20, 10, 30, 7], leans)
        u = report.h2(rows, outcomes.join(rows))["units"]
        self.assertEqual([p["lean"] for p in u["pairs"]], [-0.2, 0.1, 0.3, 0.07])
        self.assertAlmostEqual(u["r"], 1.0, places=9)
        self.assertEqual(u["rho"], 1.0)
        self.assertEqual(report.pearson([-0.5, -0.1, 0.2, 0.7], [3 * x + 2 for x in (-0.5, -0.1, 0.2, 0.7)]), 1.0)
        self.assertLessEqual(report.pearson([0.1, 0.2, 0.3], [0.1, 0.2, 0.3]), 1.0)          # clamped, never 1 + eps

    def test_constant_lean_is_undefined_and_said_so(self):
        # every lean is 0.2 once rounded, though 0.5 - 0.3, 0.6 - 0.4 and 0.7 - 0.5 differ in binary
        rows = _h2_log([-10, 5, 20], {0: (0.5, 0.3), 15: (0.6, 0.4), 30: (0.3, 0.1)}, other=(0.7, 0.5))
        h = report.h2(rows, outcomes.join(rows))
        for s in (h["units"], h["every"]):
            self.assertEqual((s["r"], s["rho"], s["why"]), (None, None, "no variance in lean"))
        self.assertEqual(h["units"]["n"], 3)
        self.assertIsNone(report.pearson([0.1] * 3, [1.0, 2.0, 3.0]))    # 0.1 * 3 / 3 != 0.1: the residue is not r
        self.assertIsNone(report.pearson([1.0, 2.0], [5.0, 5.0]))
        self.assertIsNone(report.pearson([1.0], [2.0]))
        text = report.render(rows, [], "x")                            # the whole report, not a crash
        self.assertIn("Pearson r(lean, ret_h_bps) over 3 units: undefined (no variance in lean);"
                      " Spearman rho undefined (no variance in lean)", text)
        self.assertIn("every live tick (overlapping horizons, descriptive, never the statistic): r undefined"
                      " (no variance in lean)", text)

    def test_brier_against_the_base_rate_by_hand(self):
        # units: up15 (.3, .4, .5, .6) vs up (0, 0, 0, 1): (.09 + .16 + .25 + .16) / 4 = .165; p = .25,
        # base .25 * .75 = .1875. down15 (.2, .3, .2, .1) vs down (1, 0, 0, 0): (.64 + .09 + .04 + .01) / 4 = .195
        bu, bd = self.h["units"]["brier_up"], self.h["units"]["brier_down"]
        for got, want in ((bu, (0.165, 0.1875, 0.25)), (bd, (0.195, 0.1875, 0.25))):
            for g, w in zip(got, want):
                self.assertAlmostEqual(g, w, places=12)
        self.assertEqual(report.brier([], []), (None, None, None))
        b, base, p = report.brier([0.9, 0.9, 0.9], [1.0, 1.0, 1.0])     # all up: the base rate is perfect
        self.assertAlmostEqual(b, 0.01, places=12)
        self.assertEqual((base, p), (0.0, 1.0))
        self.assertRegex("\n".join(self.h["lines"]), r"units\s+4\s+0\.1650\s+0\.1875\s+0\.250\s+0\.1950\s+0\.1875\s+0\.250")

    def test_tail_counts(self):
        # units: only m 45's down15 0.1 is in a tail (< 0.15); every tick adds the 68 other rows at (0.995, 0.05)
        self.assertEqual(self.h["units"]["tails"], {"up": (0, 0), "down": (0, 1)})
        self.assertEqual(self.h["every"]["tails"], {"up": (68, 0), "down": (0, 69)})
        # the edges: >= 0.99 is the high tail, < 0.15 the low; 0.989 and 0.15 are the band
        ps = [{"up": u, "down": 0.5, "lean": 0.0, "ret": 0.0, "label": "flat"} for u in (0.99, 0.989, 0.15, 0.149)]
        self.assertEqual(report._h2_stats(ps)["tails"], {"up": (1, 1), "down": (0, 0)})
        self.assertIn("measured tails (>= 0.99 / < 0.15): units up15 0/0, down15 0/1; every tick up15 68/0, down15 0/69",
                      "\n".join(self.h["lines"]))

    def test_the_trend_word_beside_the_statistic_by_hand(self):
        # PREREG §5: Jev sees only the four words and rule_c acts on `trend`, so the report puts
        # the word (dumping -1, flat 0, pumping +1) beside lean. Blocks: ret (-10, 6, 6, 10, -12, gap),
        # trend (dumping, flat, flat, pumping, flat, flat), first-row leans (-0.3, 0, 0.1, 0.3, -0.1).
        trends = ("dumping", "flat", "flat", "pumping", "flat", "flat")
        rows = _h2_log([-10, 6, 6, 10, -12], {0: (0.2, 0.5), 15: (0.4, 0.4), 30: (0.5, 0.4), 45: (0.6, 0.3),
                                               60: (0.4, 0.5)})
        for m, r in enumerate(rows):
            r["adj"] = dict(r["adj"], trend=trends[m // 15])
            r["state"], r["rule_c"] = state.state_string(r["adj"]), state.rule_c(r["adj"])
        h = report.h2(rows, outcomes.join(rows))
        u = h["units"]
        self.assertEqual([(p["lean"], p["trend"]) for p in u["pairs"]], [(-0.3, -1), (0.0, 0), (0.1, 0), (0.3, 1), (-0.1, 0)])
        w = u["word"]
        # x = (-.3, 0, .1, .3, -.1), t = (-1, 0, 0, 1, 0), y = (-10, 6, 6, 10, -12); every mean is 0
        # r(x, t): sxt .6, sxx .2, stt 2 -> .6 / sqrt(.4) = 3 / sqrt(10)
        self.assertAlmostEqual(w["lean_trend"]["r"], 3 / math.sqrt(10), places=9)
        # r(t, y): sty 20, syy 100 + 36 + 36 + 100 + 144 = 416 -> 20 / sqrt(832) = 5 / (2 sqrt(13))
        self.assertAlmostEqual(w["trend_ret"]["r"], 5 / (2 * math.sqrt(13)), places=9)
        # within flat: x = (0, .1, -.1), y = (6, 6, -12), mean 0: sxy 1.8, sxx .02, syy 216 -> sqrt(3)/2
        self.assertAlmostEqual(w["flat"]["r"], math.sqrt(3) / 2, places=9)
        self.assertEqual((w["lean_trend"]["n"], w["trend_ret"]["n"], w["flat"]["n"]), (5, 5, 3))
        # every tick: m 0..74 (m 75..89 is the gap block); the first rows as above, every other 0.945
        firsts = {0: -0.3, 15: 0.0, 30: 0.1, 45: 0.3, 60: -0.1}
        xs = [firsts.get(m, 0.945) for m in range(75)]
        ts = [report.TREND_SIGN[trends[m // 15]] for m in range(75)]
        ys = [(-10.0, 6.0, 6.0, 10.0, -12.0)[m // 15] for m in range(75)]
        we = h["every"]["word"]
        self.assertAlmostEqual(we["lean_trend"]["r"], report.pearson(xs, ts), places=9)
        self.assertAlmostEqual(we["trend_ret"]["r"], report.pearson(ts, ys), places=9)
        fl = [m for m in range(75) if ts[m] == 0]
        self.assertAlmostEqual(we["flat"]["r"], report.pearson([xs[m] for m in fl], [ys[m] for m in fl]), places=9)
        self.assertEqual(we["flat"]["n"], 45)
        text = "\n".join(h["lines"])
        self.assertIn(f"    units       r(lean, trend) {3 / math.sqrt(10):.4f};"
                      f" r(trend, ret_h_bps) {5 / (2 * math.sqrt(13)):.4f};"
                      f" r(lean, ret_h_bps | trend flat) {math.sqrt(3) / 2:.4f} over 3", text)
        # the statistic itself is unchanged by the comparator: sxy = 3 + 0 + .6 + 3 + 1.2 = 7.8 -> 7.8 / sqrt(.2 * 416)
        self.assertAlmostEqual(u["r"], 7.8 / math.sqrt(0.2 * 416), places=9)

    def test_the_trend_word_undefined_is_said_so(self):
        # the class fixture is `dumping` on every row: no variance in the word, and no flat pair
        for s in (self.h["units"], self.h["every"]):
            w = s["word"]
            self.assertEqual((w["lean_trend"]["r"], w["lean_trend"]["why"]), (None, "no variance in trend"))
            self.assertEqual((w["trend_ret"]["r"], w["trend_ret"]["why"]), (None, "no variance in trend"))
            self.assertEqual((w["flat"]["r"], w["flat"]["why"], w["flat"]["n"]), (None, "fewer than 2 pairs (n 0)", 0))
        self.assertIn("    units       r(lean, trend) undefined (no variance in trend); r(trend, ret_h_bps) undefined"
                      " (no variance in trend); r(lean, ret_h_bps | trend flat) undefined (fewer than 2 pairs (n 0)) over 0",
                      "\n".join(self.h["lines"]))
        self.assertEqual(report.TREND_SIGN, {"dumping": -1, "flat": 0, "pumping": 1})
        self.assertEqual(set(report.TREND_SIGN), set(state.TREND))

    def test_t0_restricts_h2_to_the_sample(self):
        # T0 10:15: the sample is m 15..89, blocks re-anchored there; units m 16, 31, 45 (m 60 no
        # up15, m 75 gap): x (0.1, 0.3, 0.5), y (0, 0, 10). dx (-.2, 0, .2), dy (-10/3, -10/3, 20/3):
        # sxy 2, sxx .08, syy 600/9 -> r = 2 / sqrt(16/3) = sqrt(3)/2; rho: ranks (1, 2, 3), (1.5, 1.5, 3)
        # -> 1.5 / sqrt(2 * 1.5) = sqrt(3)/2
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "decisions.jsonl")
            _write(log, self.rows, garbage=False)
            code, out = _main(["--log", log, "--t0", "2026-09-23T10:15"])
            cut = report.in_sample(self.rows, report._t0("2026-09-23T10:15"))
        self.assertEqual(code, 0)
        h = report.h2(cut, self.outs, report._t0("2026-09-23T10:15"))
        self.assertEqual([p["tick"][9:13] for p in h["units"]["pairs"]], ["1016", "1031", "1045"])
        self.assertAlmostEqual(h["units"]["r"], math.sqrt(3) / 2, places=9)
        self.assertAlmostEqual(h["units"]["rho"], math.sqrt(3) / 2, places=12)
        self.assertEqual(h["every"]["n"], 72 - 15)                        # m 0..14 are before T0
        self.assertIn("anchored at T0 2026-09-23T10:15Z (--t0); 5 blocks with a live row, dropped: gap 1,"
                      " missing noul 1; 3 units", out)
        self.assertIn(f"over 3 units: {math.sqrt(3) / 2:.4f}; Spearman rho {math.sqrt(3) / 2:.4f} (descriptive)", out)
        with tempfile.TemporaryDirectory() as d:                     # PREREG §8.4: the blind look, on the sample
            log = os.path.join(d, "decisions.jsonl")
            _write(log, self.rows, garbage=False)
            code, blind = _main(["--log", log, "--t0", "2026-09-23T10:15", "--health"])
        self.assertEqual(code, 0)
        self.assertIn("T0 2026-09-23T10:15Z", blind.splitlines()[0])
        self.assertIn("H2 statistic", out)
        self.assertNotIn("H2 statistic", blind)
        self.assertNotIn(report.TITLES[5], blind)


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
        self.assertIn("no unit yet: no block's first live row has both nouls and an outcome", out)
        self.assertIn("over 0 units: undefined (fewer than 2 pairs (n 0))", out)
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
        self.assertIn("no answered rows: 5 rows (5 dry, 0 absences)", text)
        self.assertIn("live answered 0; dry 5; absence: none", text)
        self.assertIn("deep 5/5 (100.0%)", text)
        self.assertIn("FLAG liq is deep", text)
        self.assertIn("no answered rows: arms A and B replay as forced holds", text)
        self.assertNotIn("pair B-C", text)
        self.assertIn("C equity 0.00 bps, trades 0, forced holds 5", text)   # a dry row is a forced hold for every arm
        self.assertIn("A equity 0.00 bps, trades 0, forced holds 5", text)
        self.assertIn("nothing to calibrate", text)
        self.assertIn("no unit yet", text)                               # dry rows are never H2 units
        self.assertIn("no answered rows: 5 rows (5 dry, 0 absences); sections 3-7 need live rows", text)
        halted = [dict(_row(m), mode="live", absence="halt", answers=None, columns={"a": None, "b": None}) for m in range(5, 8)]
        self.assertIn("no answered rows: 3 rows (0 dry, 3 absences)", report.render(halted, [], "x"))

    def test_no_network_no_key_no_write(self):
        import inspect
        src = inspect.getsource(report)
        for word in ("urllib", "socket", "http.client", "subprocess", "KEY_PATHS", "open("):
            self.assertNotIn(word, src)



class Withheld(unittest.TestCase):
    """CLAUDE.md: nobody reads report §4-§7 before day 28; the day-14 look is --health. `make report`
    on rows of the sealed sample therefore prints sections 1-3 and says the rest is withheld until
    the sample ends; --unblind prints them and says so on stderr; shakedown rows before T0, or any
    log after the sample has ended, print in full. --sample reads T0 from PREREG.md §11."""
    T0 = report.tick_epoch("20260925T214000Z")                       # the sealed T0 (PREREG §11)
    END = T0 + report.SAMPLE_DAYS * 86400

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        rows = []
        for m in MINUTES:                                               # the synthetic log moved into day 2 of the sample
            r = dict(_row(m))
            e = cls.T0 + 86400 + 60 * m
            r["tick_id"], r["ts_rx"] = report._tick_of(e), datetime.datetime.fromtimestamp(e, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.100Z")
            rows.append(r)
        cls.log = os.path.join(cls.tmp, "sample.jsonl")
        _write(cls.log, rows, garbage=False)
        cls.pre = os.path.join(cls.tmp, "pre.jsonl")                    # the same rows before T0: shakedown
        _write(cls.pre, [_row(m) for m in MINUTES], garbage=False)
        cls.rows = outcomes.load(cls.log, [])
        cls.unsealed = os.path.join(cls.tmp, "PREREG-unsealed.md")
        with open(cls.unsealed, "w") as fh:
            fh.write("# PREREG\n\nT0 (first tick_id of day 1): `________`\n")

    def _run(self, argv, now):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = report.main(argv, now=now)
        return code, out.getvalue(), err.getvalue()

    def test_withheld_until(self):
        day10 = self.T0 + 10 * 86400
        self.assertEqual(report.withheld_until(self.rows, self.T0, day10), self.END)
        self.assertIsNone(report.withheld_until(self.rows, self.T0, self.END))                  # the sample has ended
        self.assertIsNone(report.withheld_until(self.rows, None, day10))                         # unsealed
        self.assertIsNone(report.withheld_until(outcomes.load(self.pre, []), self.T0, day10))    # shakedown rows only
        self.assertIsNone(report.withheld_until([], self.T0, day10))

    def test_full_report_on_sample_rows_is_health_only_until_day_28(self):
        day10 = self.T0 + 10 * 86400
        code, out, err = self._run(["--log", self.log], day10)
        self.assertEqual(code, 0)
        self.assertIn("sections 4-7 WITHHELD until 2026-10-23T21:40Z", out)
        for t in report.TITLES[:3]:
            self.assertIn(t, out)
        for t in report.TITLES[3:]:
            self.assertNotIn(t, out)
        for word in ("H1 cell", "H2 statistic", "Pearson", "Brier", "pair B-C", "P(correct)"):
            self.assertNotIn(word, out)
        self.assertEqual(err, "")
        # --t0 and --since do not lift it; --health is the look and needs no notice
        self.assertIn("WITHHELD", self._run(["--log", self.log, "--t0", "20260925T214000Z"], day10)[1])
        self.assertIn("WITHHELD", self._run(["--log", self.log, "--since", "2026-09-26"], day10)[1])
        code, out, err = self._run(["--log", self.log, "--health"], day10)
        self.assertNotIn("WITHHELD", out)
        self.assertIn("health only (--health", out)

    def test_unblind_prints_them_and_says_so(self):
        day10 = self.T0 + 10 * 86400
        code, out, err = self._run(["--log", self.log, "--unblind"], day10)
        self.assertEqual(code, 0)
        self.assertNotIn("WITHHELD", out)
        for t in report.TITLES:
            self.assertIn(t, out)
        self.assertIn("report: --unblind: sections 4-7 printed on sample rows before 2026-10-23T21:40Z; this is a look (PREREG §8.4)", err)

    def test_after_the_sample_and_before_t0_print_in_full(self):
        code, out, err = self._run(["--log", self.log], self.END)
        self.assertNotIn("WITHHELD", out)
        self.assertIn("pair B-C", out)
        code, out, err = self._run(["--log", self.pre], self.T0 + 10 * 86400)
        self.assertNotIn("WITHHELD", out)
        self.assertIn("pair B-C", out)
        self.assertEqual(err, "")

    def test_sample_flag_reads_the_sealed_t0(self):
        code, out, err = self._run(["--log", self.log, "--health", "--sample"], self.T0 + 10 * 86400)
        self.assertEqual(code, 0)
        self.assertIn("T0 2026-09-25T21:40Z (sample [T0, T0 + 28 d), replayed from flat at T0)", out.splitlines()[0])
        self.assertEqual(out, self._run(["--log", self.log, "--health", "--t0", "20260925T214000Z"], self.T0 + 10 * 86400)[1])
        with self.assertRaises(SystemExit) as cm:
            self._run(["--log", self.log, "--health", "--sample", "--t0", "20260925T214000Z"], None)
        self.assertEqual(cm.exception.code, 2)
        with self.assertRaises(SystemExit) as cm:
            self._run(["--log", self.log, "--health", "--sample", "--prereg", self.unsealed], None)
        self.assertEqual(cm.exception.code, 2)
        # unsealed PREREG: nothing is withheld (there is no sample yet)
        code, out, err = self._run(["--log", self.log, "--prereg", self.unsealed], self.T0 + 10 * 86400)
        self.assertNotIn("WITHHELD", out)
        self.assertIn("pair B-C", out)


class PerDay(unittest.TestCase):
    """§1's per-day table: PREREG §8 stop rule 3, per UTC day, on the join over the whole log."""

    @staticmethod
    def _day(rows_m, day, hour, minute0):
        out = []
        for i, m in enumerate(rows_m):
            r = dict(_row(m))
            mm = minute0 + i
            r["tick_id"] = f"{day}T{hour:02d}{mm:02d}00Z"
            r["ts_rx"] = f"{day[:4]}-{day[4:6]}-{day[6:]}T{hour:02d}:{mm:02d}:00.100Z"
            r["mode"], r["absence"] = "live", r["absence"]
            out.append(r)
        return out

    def test_fill_is_per_live_row_and_a_day_ends_into_the_next(self):
        from loop import outcomes
        # day B: 23:30..23:59, every row's t+15 exists (in B or in C) -> fill 100%, ok
        # day C: 00:00..00:29, rows from 00:15 on have no t+15 -> fill under 95%, BAD (fill)
        ms = list(range(5, 35))                                  # 30 live rows; m == 15 is absence "jev"
        b = self._day(ms, "20260923", 23, 30)
        c = self._day(ms, "20260924", 0, 0)
        sentinel = self._day([0], "20260925", 12, 0)               # a dry row two days on: both days are closed
        sentinel[0]["mode"] = "dry"
        rows = b + c + sentinel
        outs = outcomes.join(rows)
        h = report.health(rows, outs)
        self.assertEqual([d["day"] for d in h["days"]], ["20260923", "20260924", "20260925"])
        db, dc, ds = h["days"]
        self.assertEqual((ds["live"], ds["pending"], ds["open"], ds["bad"]), (0, 0, True, False))
        self.assertEqual((db["ticks"], db["live"], db["filled"], db["attempted"], db["errors"]), (30, 29, 29, 30, 1))
        self.assertEqual(db["fill"], 1.0)
        self.assertAlmostEqual(db["jev_err"], 1 / 30)
        self.assertFalse(db["bad"])
        # C: minutes 0..14 have an outcome; minute 10 (m == 15) is the jev absence, so 14 filled of 29 live
        self.assertEqual((dc["ticks"], dc["live"], dc["filled"]), (30, 29, 14))
        self.assertAlmostEqual(dc["fill"], 14 / 29)
        self.assertTrue(dc["bad"])
        self.assertEqual(dc["why"], ["fill"])
        self.assertEqual(h["bad_days"], ["20260924"])
        self.assertAlmostEqual(dc["cov"], 30 / 1440)
        text = "\n".join(h["lines"])
        self.assertIn("per UTC calendar day (no --t0; the sample's days are counted from T0) (stop rule 3: BAD when fill < 95% of live rows or jev errors > 5% of attempted; 3 BAD days pause the run", text)
        self.assertIn("20260923     30   2.1%    29 100.0%     0     0     3.3%", text)
        self.assertIn("20260924     30   2.1%    29  48.3%     0     0     3.3%  BAD (fill)", text)
        self.assertIn("20260925      1   0.1%     0    n/a     0     0      n/a  open", text)
        self.assertIn("BAD days 1: 20260924; the exclusion is a line in data/exclusions.tsv, written by hand, never here.", text)

    def test_an_open_day_is_pending_not_bad(self):
        from loop import outcomes
        rows = self._day(list(range(5, 35)), "20260924", 0, 0)      # the log ends at 00:29: rows from 00:15 cannot fill yet
        h = report.health(rows, outcomes.join(rows))
        d = h["days"][0]
        self.assertEqual((d["live"], d["filled"], d["pending"]), (14, 14, 15))   # m == 15 (minute 10) is the jev absence
        self.assertEqual(d["fill"], 1.0)
        self.assertTrue(d["open"])
        self.assertFalse(d["bad"])
        self.assertEqual(h["bad_days"], [])
        self.assertIn("20260924     30   2.1%    14 100.0%    15     0     3.3%  open", "\n".join(h["lines"]))

    def test_t0_anchored_days_are_labelled_dNN_with_their_span(self):
        from loop import outcomes
        b = self._day(list(range(5, 35)), "20260923", 23, 30)
        c = self._day(list(range(5, 35)), "20260924", 0, 0)
        sentinel = self._day([0], "20260925", 12, 0)
        sentinel[0]["mode"] = "dry"
        rows = b + c + sentinel
        t0 = report.tick_epoch("20260923T233000Z")
        h = report.health(rows, outcomes.join(rows), t0=t0)
        self.assertEqual([d["day"] for d in h["days"]], ["d01", "d02"])
        d1, d2 = h["days"]
        self.assertEqual(d1["span"], ("20260923T233000Z", "20260924T233000Z"))
        self.assertEqual((d1["live"], d1["filled"]), (58, 43))       # B all filled, C 14 of 29
        self.assertTrue(d1["bad"])
        self.assertEqual(d2["day"], "d02")
        self.assertTrue(d2["open"])
        text = "\n".join(h["lines"])
        self.assertIn("per day from T0 (dNN = [T0 + 86400(N-1), T0 + 86400 N), 96 blocks; d00 is before T0)", text)
        self.assertIn("d01          60   4.2%    58  74.1%     0     0     3.3%  20260923T233000Z..20260924T233000Z  BAD (fill)", text)
        # a row before T0 is d00
        self.assertEqual(report.day_of("20260923T100000Z", t0), "d00")
        self.assertEqual(report.day_of("20260923T100000Z", None), "20260923")
        self.assertIsNone(report.day_span("20260923", None))

    def test_jev_errors_flag_a_day_too(self):
        from loop import outcomes
        rows = self._day([10, 15, 20], "20260923", 12, 0)         # one of three reached-the-ask rows is a jev error
        h = report.health(rows, outcomes.join(rows))
        d = h["days"][0]
        rows += self._day([0], "20260925", 12, 0)                    # closed by a later dry row
        rows[-1]["mode"] = "dry"
        h = report.health(rows, outcomes.join(rows))
        d = h["days"][0]
        self.assertEqual((d["attempted"], d["errors"], d["live"], d["filled"]), (3, 1, 2, 0))
        self.assertEqual(d["why"], ["fill", "jev-err"])
        self.assertIn("BAD (fill, jev-err)", "\n".join(h["lines"]))

    def test_the_last_sample_day_closes_on_rows_after_the_cut(self):
        # 2026-09-28: with --t0 the rows are cut to the sample, so days_table saw no row after d28's end
        # and d28 stayed "open" for ever, never judged, never BAD: exactly the day whose exclusions.tsv
        # line is decided after the sample. `last` (the whole log's last tick) closes it.
        from loop import outcomes
        t0 = report.tick_epoch("20260925T214000Z")
        end = t0 + report.SAMPLE_DAYS * 86400
        rows = []
        for m in range(27 * 1440, 28 * 1440 + 120):                  # d28 and two hours past the end
            if m < 28 * 1440 and m % 10 == 0:
                continue                                          # d28 loses every tenth minute: fill under 95%
            r = dict(_row(7))
            e = t0 + 60 * m
            r["tick_id"] = report._tick_of(e)
            r["ts_rx"] = datetime.datetime.fromtimestamp(e, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.100Z")
            rows.append(r)
        outs = outcomes.join(rows)
        cut = report.in_sample(rows, t0)
        self.assertTrue(all(report.tick_epoch(r["tick_id"]) < end for r in cut))
        stale = report.health(cut, outs, t0=t0)["days"][-1]           # no `last`: what the cut alone can tell
        self.assertEqual((stale["day"], stale["open"], stale["bad"]), ("d28", True, False))
        last = max(report.tick_epoch(r["tick_id"]) for r in rows)
        h = report.health(cut, outs, t0=t0, last=last)
        d = h["days"][-1]
        self.assertEqual((d["day"], d["open"], d["bad"], d["why"]), ("d28", False, True, ["fill"]))
        self.assertLess(d["fill"], report.BAD_FILL)
        self.assertEqual(h["bad_days"], ["d28"])
        self.assertEqual(h["empty_days"], [f"d{j:02d}" for j in range(1, 28)])   # every day before d28 is listed, with no row
        self.assertIn("BAD (fill)", [l for l in h["lines"] if l.startswith("    d28 ")][0])
        # render() and main() hand the whole log's last tick through
        text = report.render(cut, [], t0=t0, outs=outs, health_only=True, last=last)
        self.assertIn("  d28 ", text)
        self.assertIn("BAD days 1: d28", text)
        log = os.path.join(tempfile.mkdtemp(), "past-end.jsonl")
        _write(log, rows, garbage=False)
        code, out = _main(["--log", log, "--health", "--t0", "20260925T214000Z"])
        self.assertEqual(code, 0)
        self.assertIn("BAD days 1: d28", out)
        self.assertNotIn("d29", out)                                  # the two hours after the sample are not a sample day

    def test_every_t0_day_is_listed_and_a_day_without_live_rows_is_flagged(self):
        # 2026-09-28: a day the log has no row for (the Mac off) never appeared in the table, and a day
        # of absences only (HALT all day) read "n/a": the worst health events were the ones the stop-rule
        # table could not show. Fill is 0/0 there, which PREREG §8.3 does not define, so they are
        # flagged NO LIVE ROWS and counted, never marked BAD by code: the exclusion is Alex's call.
        from loop import outcomes
        t0 = report.tick_epoch("20260925T214000Z")
        rows = []
        for m in range(5 * 1440):
            day = m // 1440 + 1
            if day == 2:
                continue                                          # d02: no rows at all
            r = dict(_row(7))
            e = t0 + 60 * m
            r["tick_id"], r["ts_rx"] = report._tick_of(e), datetime.datetime.fromtimestamp(e, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.100Z")
            if day == 4:                                          # d04: every row a HALT absence
                r["absence"], r["answers"], r["columns"] = "halt", None, {"a": None, "b": None}
            rows.append(r)
        h = report.health(rows, outcomes.join(rows), t0=t0)
        self.assertEqual([d["day"] for d in h["days"]], ["d01", "d02", "d03", "d04", "d05"])
        by = {d["day"]: d for d in h["days"]}
        self.assertEqual((by["d02"]["ticks"], by["d02"]["live"], by["d02"]["fill"], by["d02"]["empty"], by["d02"]["bad"]), (0, 0, None, True, False))
        self.assertEqual((by["d04"]["ticks"], by["d04"]["live"], by["d04"]["empty"], by["d04"]["bad"]), (1440, 0, True, False))
        self.assertFalse(by["d01"]["empty"])
        self.assertTrue(by["d05"]["open"] and not by["d05"]["empty"])   # an open day is not judged, empty or not
        self.assertEqual(h["empty_days"], ["d02", "d04"])
        text = "\n".join(h["lines"])
        self.assertIn("    d02           0   0.0%     0    n/a     0     0      n/a  20260926T214000Z..20260927T214000Z  NO LIVE ROWS", text)
        self.assertIn("  NO LIVE ROWS", [l for l in text.splitlines() if l.startswith("    d04 ")][0])
        self.assertIn("NO LIVE ROWS on 2 closed days: d02, d04: fill is 0/0, which PREREG §8.3 does not define", text)
        # without T0 the calendar table lists only days with rows, as before (six UTC days touched, d02's gone)
        cal = report.health(rows, outcomes.join(rows))
        self.assertEqual(len(cal["days"]), 6)
        self.assertEqual(cal["empty_days"], [])                          # d04 straddles two calendar days, each with live rows

    def test_dry_rows_and_absences_are_not_live(self):
        from loop import outcomes
        rows = [dict(_row(m)) for m in range(0, 5)]                # all dry
        h = report.health(rows, outcomes.join(rows))
        d = h["days"][0]
        self.assertEqual((d["ticks"], d["live"], d["attempted"]), (5, 0, 0))
        self.assertIsNone(d["fill"])
        self.assertFalse(d["bad"])
        self.assertIn("20260923      5   0.3%     0    n/a     0     0      n/a  open", "\n".join(h["lines"]))
        self.assertEqual(report.health([], {})["days"], [])
        self.assertIn("    no rows", report.health([], {})["lines"])

if __name__ == "__main__":
    unittest.main()

"""bin/fill1k-quantiles: the counts, the nearest-rank quantiles of fill1k_bps and of h (half-ticks),
the atoms and the liq-word occupancy of the h-rule, every printed number pinned on a log this test
writes; and a scan of the tool's source for the fields it must never read (the sample is blind)."""
import json, os, re, shutil, subprocess, sys, tempfile, unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS)
TOOL = os.path.join(REPO, "bin", "fill1k-quantiles")
T0, UNTIL = "20260925T214000Z", "20260925T222000Z"          # 40 minutes, half-open


def _tid(m):
    """tick_id of minute m after 21:40 on 2026-09-25 (negative: before it)."""
    t = 21 * 60 + 40 + m
    return f"20260925T{t // 60:02d}{t % 60:02d}00Z"


def _row(m, fill, mid=100.0, short=False, mode="live", absence=None, product="SOL-USD"):
    # the blinded fields are present, as in the live log, and a top-level mid that is not the feature's:
    # the tool must read features.mid and nothing the model wrote
    return {"v": 1, "tick_id": _tid(m), "mode": mode, "absence": absence, "product": product, "mid": 999.0,
            "features": {"mid": mid, "fill1k_bps": fill, "fill1k_short": short, "spread_bps": 0.1},
            "answers": {"action": {"buy": 1.0}}, "rule_c": "hold"}


# (fill1k_bps, mid) of the 24 usable rows; h = fill * mid / 50 at tick 0.01
USABLE = ([(0.25, 200.0), (0.5, 200.0)]                         # h 1.0 and 2.0: bps order is not h order
          + [(0.25, 100.0)] * 2 + [(0.5, 100.0)] * 5            # h 0.5 x2, 1.0 x5
          + [(0.75, 100.0)]                                     # h 1.5: ON the deep cut, so normal
          + [(1.0, 100.0)] * 7 + [(1.5, 100.0)] * 5             # h 2.0 x7, 3.0 x5
          + [(1.75, 100.0)] + [(5.0, 100.0)])                   # h 3.5: ON the thin cut, so normal; h 10


def _main_log(path):
    rows = [_row(i, f, m) for i, (f, m) in enumerate(USABLE)]   # minute 0 is tick_id == t0: kept
    rows.append(_row(24, None, short=True))                     # short: out of the quantiles, thin
    rows.append(_row(25, None))                                 # no fill, not short: unusable
    rows.append(_row(26, 100.0, mode="dry"))                    # not live
    rows.append(_row(27, 100.0, absence="jev"))                 # not live
    rows.append(_row(28, 100.0, product="ETH-USD"))             # another product
    rows += [_row(m, 100.0) for m in (-2, -1, 40, 41)]          # outside; minute 40 is tick_id == until
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
        fh.write('{"v": 1, "tick_id": "20260925T2229')           # torn: a crash mid-write


def _run(*argv):
    p = subprocess.run([sys.executable, TOOL, *argv], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=REPO)
    return p.returncode, p.stdout, p.stderr


class Quantiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.log = os.path.join(cls.tmp, "decisions.jsonl")
        _main_log(cls.log)

    def test_every_printed_number(self):
        code, out, err = _run("--log", self.log, "--t0", T0, "--until", UNTIL)
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines(), [
            f"log: {self.log}",
            "window: 20260925T214000Z <= tick_id < 20260925T222000Z",
            "product_base: SOL",
            "tick: 0.01",
            "lines_unparsable: 1",
            "rows_parsed: 33",
            "rows_not_live: 2",
            "live_rows_outside_window: 4",
            "live_rows_other_product: 1",
            "live_rows: 26",
            "short_rows_excluded: 1",
            "unusable_rows_excluded: 1",
            "quantile_rows: 24",
            "fill1k_bps_p10: 0.2500",
            "fill1k_bps_p50: 1.0000",
            "fill1k_bps_p90: 1.5000",
            "fill1k_bps_p99: 5.0000",
            "fill1k_bps_max: 5.0000",
            "h_p10: 1.0000",
            "h_p50: 2.0000",
            "h_p90: 3.0000",
            "h_p99: 10.0000",
            "h_max: 10.0000",
            "a10: 1",
            "a90: 3",
            "rule: deep iff h < 1.5; thin iff h > 3.5 or fill1k_short; normal otherwise",
            "thin_fallback: no",
            "deep: 8/25 32.00%",
            "normal: 15/25 60.00%",
            "thin: 2/25 8.00%",
            "every_word_within_3_90: yes",
        ])
        self.assertEqual(err, "")

    def test_deterministic(self):
        self.assertEqual(_run("--log", self.log, "--t0", T0, "--until", UNTIL),
                         _run("--log", self.log, "--t0", T0, "--until", UNTIL))

    def test_tick_scales_h_and_atoms_round_halves_up(self):
        # at tick 0.02 every h halves: p10 0.5 -> a10 1 (a banker's round would give 0), p90 1.5 -> 2
        code, out, err = _run("--log", self.log, "--t0", T0, "--until", UNTIL, "--tick", "0.02")
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        for want in ("tick: 0.02", "h_p10: 0.5000", "h_p90: 1.5000", "h_max: 5.0000", "fill1k_bps_p10: 0.2500",
                     "a10: 1", "a90: 2", "rule: deep iff h < 1.5; thin iff h > 2.5 or fill1k_short; normal otherwise"):
            self.assertIn(want, lines)

    def test_thin_fallback_applied_once_and_said(self):
        # 40 rows, no short: h 1.0 x4, 2.0 x30, 3.0 x5, 4.0 x1. p10 = sorted[3] = 1, p90 = sorted[35] = 3;
        # thin under h > 3.5 holds 1/40 = 2.5 % < 3 %, so thin becomes h > 2.5 (6 rows), and says so
        path = os.path.join(self.tmp, "fallback.jsonl")
        hs = [1.0] * 4 + [2.0] * 30 + [3.0] * 5 + [4.0]
        with open(path, "w", encoding="utf-8") as fh:
            for m, h in enumerate(reversed(hs)):
                fh.write(json.dumps(_row(m, h / 2)) + "\n")
        code, out, err = _run("--log", path, "--t0", T0, "--until", UNTIL)
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines()[12:], [
            "quantile_rows: 40",
            "fill1k_bps_p10: 0.5000",
            "fill1k_bps_p50: 1.0000",
            "fill1k_bps_p90: 1.5000",
            "fill1k_bps_p99: 2.0000",
            "fill1k_bps_max: 2.0000",
            "h_p10: 1.0000",
            "h_p50: 2.0000",
            "h_p90: 3.0000",
            "h_p99: 4.0000",
            "h_max: 4.0000",
            "a10: 1",
            "a90: 3",
            "rule: deep iff h < 1.5; thin iff h > 2.5 or fill1k_short; normal otherwise",
            "thin_fallback: yes (thin held 1/40 2.50% < 3% under h > 3.5; applied once: thin iff h > 2.5)",
            "deep: 4/40 10.00%",
            "normal: 30/40 75.00%",
            "thin: 6/40 15.00%",
            "every_word_within_3_90: yes",
        ])

    def test_a_word_outside_the_band_says_no(self):
        # every row at h 2: a10 = a90 = 2, all deep (h < 2.5; 100 % > 90 %), thin 0 even after the fallback's
        # h > 1.5 because deep (h < 2.5) is tested first
        path = os.path.join(self.tmp, "flat.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for m in range(30):
                fh.write(json.dumps(_row(m, 1.0)) + "\n")
        code, out, _ = _run("--log", path, "--t0", T0, "--until", UNTIL)
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-5:], [
            "thin_fallback: yes (thin held 0/30 0.00% < 3% under h > 2.5; applied once: thin iff h > 1.5)",
            "deep: 30/30 100.00%", "normal: 0/30 0.00%", "thin: 0/30 0.00%", "every_word_within_3_90: no"])

    def test_a_row_that_names_no_product_is_left_out(self):
        # mode, absence, tick_id and product select the rows: a live row in the window without a product
        # string is not a SOL row, so it is counted with the other products and read no further
        path = os.path.join(self.tmp, "noproduct.jsonl")
        rows = [_row(m, 1.0) for m in range(3)]
        rows.append({k: v for k, v in _row(3, 9.0).items() if k != "product"})
        rows += [_row(4, 9.0, product=None), _row(5, 9.0, product=7), _row(6, 9.0, product="SOLUSD-ETH")]
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        code, out, err = _run("--log", path, "--t0", T0, "--until", UNTIL)
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        for want in ("rows_parsed: 7", "live_rows_other_product: 4", "live_rows: 3", "quantile_rows: 3",
                     "fill1k_bps_max: 1.0000"):
            self.assertIn(want, lines)

    def test_usage_errors_and_an_empty_window_exit_2(self):
        self.assertEqual(_run("--log", self.log, "--t0", "2026-09-25", "--until", UNTIL)[0], 2)
        self.assertEqual(_run("--log", self.log, "--t0", UNTIL, "--until", T0)[0], 2)
        self.assertEqual(_run("--log", self.log, "--t0", T0, "--until", UNTIL, "--tick", "0")[0], 2)
        self.assertEqual(_run("--log", os.path.join(self.tmp, "absent"), "--t0", T0, "--until", UNTIL)[0], 2)
        code, out, err = _run("--log", self.log, "--t0", "20270101T000000Z", "--until", "20270102T000000Z")
        self.assertEqual(code, 2)
        self.assertIn("live_rows: 0", out.splitlines())
        self.assertIn("no live row", err)

    def test_source_never_names_a_blinded_field(self):
        with open(TOOL, encoding="utf-8") as fh:
            src = fh.read()
        for word in ("answers", "columns", "rule_c", "outcome", "ret_h", "label", "pnl"):
            self.assertIsNone(re.search(word, src, re.IGNORECASE), word)
        self.assertIsNone(re.search(r"^\s*(from|import)\s+loop\b", src, re.MULTILINE))   # nothing from loop/


if __name__ == "__main__":
    unittest.main()

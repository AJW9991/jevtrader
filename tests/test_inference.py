"""loop/inference.py: the pre-registered draw, the guard that refuses the sample before day 28,
exclusions by T0-anchored day, and an end-to-end run on a synthetic log and on --pre-t0."""
import contextlib, io, os, random, tempfile, unittest
from unittest import mock

from loop import inference, outcomes, report
from test_report import _row, _write

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = inference.main(argv)
    return code, out.getvalue(), err.getvalue()


class Draw(unittest.TestCase):
    def test_resample_is_prereg_section_5_steps_1_to_2(self):
        # n = 10, L = 4: ceil(10/4) = 3 starts, 4 wrapped indices each, first 10 kept
        rng = random.Random(7)
        idx = inference.resample_indices(rng, 10)
        self.assertEqual(len(idx), 10)
        starts = [idx[0], idx[4], idx[8]]
        for s, chunk in zip(starts, (idx[0:4], idx[4:8], idx[8:10])):
            self.assertEqual(chunk, [(s + i) % 10 for i in range(len(chunk))])
        # the same seed draws the same starts, in order, from one generator
        rng2 = random.Random(7)
        self.assertEqual(starts, [rng2.randrange(10) for _ in range(3)])

    def test_bootstrap_lower_bound_is_the_250th_sorted_value_and_seeded(self):
        series = [1.0] * 40                                          # every resample's mean is 1
        b = inference.bootstrap(series, inference.mean, resamples=300)
        self.assertEqual((b["n"], b["lower"], b["reject"]), (40, 1.0, True))
        z = inference.bootstrap([0.0] * 40, inference.mean, resamples=300)
        self.assertEqual((z["lower"], z["reject"]), (0.0, False))       # a tie never rejects
        a = inference.bootstrap([0.5, -0.5] * 20, inference.mean, resamples=500)
        a2 = inference.bootstrap([0.5, -0.5] * 20, inference.mean, resamples=500)
        self.assertEqual(a["sorted"], a2["sorted"])                        # seeded: reproducible
        self.assertIs(a["sorted"][inference.ALPHA_RANK], a["lower"])
        self.assertFalse(a["reject"])
        self.assertEqual(inference.bootstrap([], inference.mean)["reject"], False)

    def test_undefined_statistic_counts_as_zero(self):
        ps = [(1.0, 5.0)] * 8                                        # every resample has no variance in x
        b = inference.bootstrap(ps, inference.pearson_pairs, resamples=50)
        self.assertEqual(b["sorted"], [0.0] * 50)
        self.assertFalse(b["reject"])


class DaysAndExclusions(unittest.TestCase):
    def test_block_to_day(self):
        self.assertEqual([inference.day_of_block(k) for k in (0, 95, 96, 2687)], [1, 1, 2, 28])

    def test_exclusions_parse_dNN_or_NN_and_refuse_junk(self):
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, "exclusions.tsv")
        with open(p, "w") as fh:
            fh.write("day\tfill%\tjev-err%\treason\nd03\t90.0%\t0.0%\tasleep\n\n7\t80.0%\t0.0%\tfeed down\n")
        days, lines = inference.read_exclusions(p)
        self.assertEqual(days, {3, 7})
        self.assertEqual(len(lines), 2)
        self.assertEqual(inference.read_exclusions(os.path.join(tmp, "none.tsv")), (set(), []))
        with open(p, "w") as fh:
            fh.write("day\tfill%\tjev-err%\treason\n20260926\t90.0%\t0.0%\ta calendar day is not a T0 day\n")
        with self.assertRaises(ValueError):
            inference.read_exclusions(p)
        with open(p, "w") as fh:
            fh.write("d29\t90.0%\t0.0%\tout of range\n")
        with self.assertRaises(ValueError):
            inference.read_exclusions(p)


class Guard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.log = os.path.join(cls.tmp, "decisions.jsonl")
        _write(cls.log, [_row(m) for m in range(42)])                # 2026-09-23 10:00 .. 10:41
        cls.t0 = "2026-09-23T10:00"

    def test_sample_is_refused_before_day_28_without_opening_the_log(self):
        with mock.patch.object(outcomes, "load", side_effect=AssertionError("the log was opened")):
            code, out, err = _main(["--sample", "--log", self.log, "--t0", self.t0, "--now", "2026-10-20T00:00"])
        self.assertEqual(code, inference.EXIT_NOT_YET)
        self.assertEqual(out, "")
        self.assertIn("refusing to look", err)
        self.assertIn("2026-10-21T10:00Z", err)                       # T0 + 28 d

    def test_sample_runs_at_day_28_and_says_the_clock_was_overridden(self):
        code, out, err = _main(["--sample", "--log", self.log, "--t0", self.t0, "--now", "2026-10-21T10:00", "--resamples", "200",
                                "--exclusions", os.path.join(self.tmp, "none.tsv")])
        self.assertEqual(code, 0, err)
        self.assertIn("mode sample", out)
        self.assertIn("(clock overridden with --now 2026-10-21T10:00)", out.splitlines()[0])
        self.assertIn("n blocks 2688", out)                           # every block kept, empty ones as 0
        self.assertIn("days kept 28 of 28", out)
        self.assertIn("H2 -- Pearson", out)
        self.assertIn("exclusions.tsv: absent or empty", out)

    def test_exclusions_drop_96_blocks_per_day_and_void_under_21(self):
        p = os.path.join(self.tmp, "ex.tsv")
        with open(p, "w") as fh:
            fh.write("day\tfill%\tjev-err%\treason\n" + "".join(f"d{d:02d}\t50%\t0%\tx\n" for d in range(1, 9)))
        code, out, _ = _main(["--sample", "--log", self.log, "--t0", self.t0, "--now", "2026-10-21T10:00", "--resamples", "50", "--exclusions", p])
        self.assertEqual(code, 0)
        self.assertIn("n blocks 1920", out)                           # 20 days x 96
        self.assertIn("VOID (PREREG §8.3)", out)
        self.assertIn("  d01\t50%\t0%\tx", out)                        # reproduced verbatim
        with open(p, "w") as fh:
            fh.write("d99\t50%\t0%\tx\n")
        code, out, err = _main(["--sample", "--log", self.log, "--t0", self.t0, "--now", "2026-10-21T10:00", "--exclusions", p])
        self.assertEqual(code, 2)
        self.assertIn("not d01..d28", err)

    def test_pre_t0_runs_any_time_on_rows_before_t0_only(self):
        code, out, err = _main(["--pre-t0", "--log", self.log, "--t0", "2026-09-23T10:20", "--resamples", "100",
                                "--exclusions", os.path.join(self.tmp, "none.tsv")])
        self.assertEqual(code, 0, err)
        self.assertIn("mode pre-t0", out)
        self.assertIn("rows in scope 20", out)                        # 10:00 .. 10:19
        self.assertIn("PRE-T0: shakedown rows only", out)
        self.assertIn("n blocks 2;", out)                             # the shakedown's own span: 10:00 and 10:15
        self.assertIn("days and exclusions: not applicable before T0", out)
        self.assertNotIn("VOID", out)

    def test_h1_series_keeps_every_block_and_excludes_whole_days(self):
        bad = []
        rows = outcomes.load(self.log, bad)
        outs = outcomes.join(rows)
        t0 = report.tick_epoch("20260923T100000Z")
        s = inference.h1_series(rows, outs, "b", "c", t0)
        self.assertEqual(len(s["S"]), 2688)
        self.assertEqual([k for k, _ in s["series"]][:3], [0, 1, 2])
        e = inference.h1_series(rows, outs, "b", "c", t0, excluded={1})
        self.assertEqual(len(e["S"]), 2688 - 96)
        self.assertTrue(all(inference.day_of_block(k) != 1 for k, _ in e["series"]))
        self.assertEqual(sum(v for _, v in e["series"]), 0.0)         # the only rows were in day 1


if __name__ == "__main__":
    unittest.main()

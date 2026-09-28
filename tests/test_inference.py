"""loop/inference.py: the pre-registered draw, the guard that refuses the sample before day 28,
exclusions by T0-anchored day, and an end-to-end run on a synthetic log and on --pre-t0."""
import contextlib, datetime, io, os, random, tempfile, unittest
from unittest import mock

from loop import inference, outcomes, report, rules
from test_report import _row, _write

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0S = "2026-09-23T10:00"                                             # the synthetic logs' T0 (--t0), not PREREG's
T0 = report._t0(T0S)
END = T0 + 28 * 86400                                                # 2026-10-21T10:00Z


def _main(argv, now=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = inference.main(argv, now=now)
    return code, out.getvalue(), err.getvalue()


def _choice(choice, conf):
    rest = (1.0 - conf) / 2
    return {"choice": choice, "confidence": conf,
            "probabilities": {k: conf if k == choice else rest for k in ("buy", "sell", "hold")}}


def _at(epoch, mid=100.0, up=0.6, down=0.4, a="hold", b="hold", c="hold", conf=0.9, mode="live", absence=None, ts=0.1):
    """A live answered row at `epoch` (a minute boundary) with ts_rx `ts` seconds after it; a, b the
    arms' action choices (confidence conf), c rule_c, up/down the direction nouls (None: missing)."""
    x = _row(22)
    d = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
    ans = {"a_action": _choice(a, conf), "b_action": _choice(b, conf), "skip": {"type": "noul", "noul": 0.1},
           "up15": {"type": "noul"} if up is None else {"type": "noul", "noul": up}, "down15": {"type": "noul", "noul": down}}
    x.update(tick_id=d.strftime("%Y%m%dT%H%M00Z"), ts_rx=d.strftime("%Y-%m-%dT%H:%M:") + f"{ts:06.3f}Z", mode=mode,
             absence=absence, bid=round(mid - 0.01, 6), ask=round(mid + 0.01, 6), mid=mid, answers=ans, rule_c=c,
             columns={"a": rules.for_arm(ans, "a"), "b": rules.for_arm(ans, "b")})
    return x


def _minutes(a, b, **kw):
    """Rows every minute on [a, b) (epochs); kw as _at, a callable value is called with the epoch."""
    return [_at(e, **{k: (v(e) if callable(v) else v) for k, v in kw.items()}) for e in range(int(a), int(b), 60)]


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
        # the log stopped at 10:41: block 2's first live row (10:30) will never see its t + h
        code, out, err = _main(["--sample", "--log", self.log, "--t0", self.t0, "--now", "2026-10-21T10:00", "--resamples", "200",
                                "--exclusions", os.path.join(self.tmp, "none.tsv"), "--accept-pending"])
        self.assertEqual(code, 0, err)
        self.assertIn("--accept-pending given: 1 H2 unit(s)", out)
        self.assertIn("mode sample", out)
        self.assertIn("(clock overridden with --now 2026-10-21T10:00)", out.splitlines()[0])
        self.assertIn("n blocks 2688", out)                           # every block kept, empty ones as 0
        self.assertIn("blocks on which a gap longer than the horizon lands 0 of 2688", out)
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


class Pending(unittest.TestCase):
    """The clock lifts at T0 + 28 d, but the last block's unit needs the row at t + 900 s +- 30 s:
    a run in between would count that outcome as a gap and drop the unit for good."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.ex = os.path.join(cls.tmp, "exclusions.tsv")
        with open(cls.ex, "w") as fh:
            fh.write("day\tfill%\tjev-err%\treason\n")
        lean = lambda e: 0.5 + 0.1 * ((e // 60) % 4)                  # a varying up15, so r is defined
        cls.rows = _minutes(END - 30 * 60, END + 16 * 60, up=lean, mid=lambda e: 100.0 + ((e // 60) % 7) * 0.01)
        cls.stopped = os.path.join(cls.tmp, "stopped.jsonl")              # the log as it stands at 10:00:00: last row 09:59
        _write(cls.stopped, [r for r in cls.rows if report.tick_epoch(r["tick_id"]) < END], garbage=False)
        cls.full = os.path.join(cls.tmp, "full.jsonl")                    # every t + h written (the last row 10:15)
        _write(cls.full, cls.rows, garbage=False)

    def _run(self, log, *extra):
        return _main(["--sample", "--log", log, "--t0", T0S, "--now", "2026-10-21T10:00", "--resamples", "40",
                      "--exclusions", self.ex, *extra])

    def test_units_whose_t_plus_h_the_log_has_not_reached_refuse_the_run(self):
        code, out, err = self._run(self.stopped)
        self.assertEqual(code, 3)
        self.assertEqual(out, "")                                          # no number printed
        self.assertIn("refusing to run: 1 H2 unit(s) wait for a t + h the log has not reached", err)
        self.assertIn("first live row 20261021T094500Z", err)             # block 2687's first row; its t + h is 10:00
        self.assertIn("ts_rx at or after 2026-10-21T10:00:31Z", err)     # 09:45:00.1 + 900 + 30, rounded up
        self.assertIn("--accept-pending", err)

    def test_accept_pending_runs_and_says_so_in_the_header(self):
        code, out, err = self._run(self.stopped, "--accept-pending")
        self.assertEqual(code, 0, err)
        self.assertIn("--accept-pending given: 1 H2 unit(s) whose t + h the log has not reached are counted as gaps", out)
        self.assertIn("20261021T094500Z", out)
        self.assertIn("dropped {'gap': 1}", out)                          # the pending unit, dropped as the flag says

    def test_a_log_that_has_the_t_plus_h_rows_runs_without_the_flag(self):
        code, out, err = self._run(self.full)
        self.assertEqual(code, 0, err)
        self.assertNotIn("--accept-pending", out)
        self.assertIn("blocks with a live row 2; dropped none", out)     # blocks 2686 and 2687, both units

    def test_pending_units_counts_only_first_live_rows_with_both_nouls(self):
        rows = outcomes.load(self.stopped, [])
        outs = outcomes.join(rows)
        scope = report.in_sample(rows, T0)
        self.assertEqual([t for t, _ in inference.pending_units(rows, scope, outs, T0)], ["20261021T094500Z"])
        self.assertEqual(inference.pending_units(rows, scope, outs, T0, excluded={28}), [])   # an excluded day waits for nothing
        nonoul = [dict(r) for r in rows]
        for r in nonoul:
            if r["tick_id"] == "20261021T094500Z":
                r["answers"] = dict(r["answers"], up15={"type": "noul"})    # dropped as "noul" whatever comes
        self.assertEqual(inference.pending_units(nonoul, report.in_sample(nonoul, T0), outs, T0), [])


if __name__ == "__main__":
    unittest.main()

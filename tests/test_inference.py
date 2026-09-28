"""loop/inference.py: the pre-registered draw, the guard that refuses the sample before day 28,
exclusions by T0-anchored day, and an end-to-end run on a synthetic log and on --pre-t0."""
import contextlib, datetime, hashlib, io, json, math, os, random, re, shutil, sys, tempfile, unittest
from unittest import mock

from fixture_prereg import pin_prereg
from loop import book, exclusions, inference, outcomes, report, rules
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


def _at(epoch, mid=100.0, up=0.6, down=0.4, a="hold", b="hold", c="hold", conf=0.9, conf_b=None, mode="live", absence=None, ts=0.1):
    """A live answered row at `epoch` (a minute boundary) with ts_rx `ts` seconds after it; a, b the
    arms' action choices (confidence conf, B's conf_b when given), c rule_c, up/down the direction
    nouls (None: missing)."""
    x = _row(22)
    d = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
    ans = {"a_action": _choice(a, conf), "b_action": _choice(b, conf if conf_b is None else conf_b), "skip": {"type": "noul", "noul": 0.1},
           "up15": {"type": "noul"} if up is None else {"type": "noul", "noul": up}, "down15": {"type": "noul", "noul": down}}
    x.update(tick_id=d.strftime("%Y%m%dT%H%M00Z"), ts_rx=d.strftime("%Y-%m-%dT%H:%M:") + f"{ts:06.3f}Z", mode=mode,
             absence=absence, bid=round(mid - 0.01, 6), ask=round(mid + 0.01, 6), mid=mid, answers=ans, rule_c=c,
             columns={"a": rules.for_arm(ans, "a"), "b": rules.for_arm(ans, "b")})
    return x


def _minutes(a, b, **kw):
    """Rows every minute on [a, b) (epochs); kw as _at, a callable value is called with the epoch."""
    return [_at(e, **{k: (v(e) if callable(v) else v) for k, v in kw.items()}) for e in range(int(a), int(b), 60)]


def _edge_rows(blocks=16, b_trades=True, a_sell=None, b_conf=0.9, lean0=0.3, lean_step=-0.01, day=1):
    """`blocks` whole blocks from the start of T0-day `day`: in block j the mid climbs 0.1 a minute from
    100 + 0.5 j; B buys on the block's first minute and sells on its 15th (b_trades), C holds, A holds
    or buys with B and sells on minute a_sell. lean = lean0 + lean_step x j, so with the falling
    15-minute return (the base climbs 0.5 a block) a negative step makes r(lean, ret) > 0. Two dry
    rows open the next block: the last unit's t + h, and nothing pending."""
    rows, start = [], T0 + (day - 1) * 86400
    for j in range(blocks):
        lean = lean0 + lean_step * j
        for m in range(15):
            b = ("buy" if m == 0 else "sell" if m == 14 else "hold") if b_trades else "hold"
            a = "hold" if a_sell is None else "buy" if m == 0 else "sell" if m == a_sell else "hold"
            rows.append(_at(start + 900 * j + 60 * m, mid=round(100.0 + 0.5 * j + 0.1 * m, 6), up=round(0.5 + lean / 2, 6),
                            down=round(0.5 - lean / 2, 6), a=a, b=b, conf_b=b_conf))
    rows += [_at(start + 900 * blocks + 60 * m, mid=100.0 + 0.5 * blocks, mode="dry") for m in (0, 1)]
    return rows


def _same(tc, got, want):
    """assertEqual for a 2,688-long series without difflib's quadratic diff: the first index that differs."""
    if got != want:
        i = next((i for i, (g, w) in enumerate(zip(got, want)) if g != w), min(len(got), len(want)))
        tc.fail(f"lengths {len(got)} vs {len(want)}; first difference at [{i}]: "
                f"{got[i] if i < len(got) else '-'!r} vs {want[i] if i < len(want) else '-'!r}")


def _exclusions(path, days=()):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("day\tfill%\tjev-err%\treason\n" + "".join(f"d{d:02d}\t50.0%\t0.0%\tx\n" for d in days))
    return path


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
        self.assertEqual(inference.alpha_rank(500), 12)                    # ceil(12.5) = 13th value
        self.assertIs(a["sorted"][inference.alpha_rank(500)], a["lower"])
        self.assertFalse(a["reject"])
        self.assertEqual(inference.bootstrap([], inference.mean)["reject"], False)

    def test_the_rank_is_the_nearest_rank_percentile_at_any_resample_count(self):
        # ceil(0.025 R) - 1 in integer arithmetic: 249 at the pre-registered 10,000, never a fixed 249
        self.assertEqual(inference.alpha_rank(inference.RESAMPLES), 249)
        self.assertEqual(inference.ALPHA_RANK, 249)
        self.assertEqual([inference.alpha_rank(r) for r in (1, 40, 41, 200, 1000, 9999, 10000, 10001)],
                         [0, 0, 1, 4, 24, 249, 249, 250])
        with self.assertRaises(ValueError):
            inference.alpha_rank(0)
        b = inference.bootstrap([float(i) for i in range(40)], inference.mean, resamples=1000)
        self.assertIs(b["lower"], b["sorted"][24])                          # the 25th of 1,000, not the 250th

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
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "exclusions.tsv")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("day\tfill%\tjev-err%\treason\nd03\t90.0%\t0.0%\tasleep\n\n7\t80.0%\t0.0%\tfeed down\n")
        days, lines = inference.read_exclusions(p)
        self.assertEqual(days, {3, 7})
        self.assertEqual(len(lines), 2)
        self.assertEqual(inference.read_exclusions(os.path.join(tmp, "none.tsv")), (set(), []))
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("day\tfill%\tjev-err%\treason\n20260926\t90.0%\t0.0%\ta calendar day is not a T0 day\n")
        with self.assertRaises(ValueError):
            inference.read_exclusions(p)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("d29\t90.0%\t0.0%\tout of range\n")
        with self.assertRaises(ValueError):
            inference.read_exclusions(p)

    def test_exclusions_take_the_space_separated_line_prereg_prints(self):
        # PREREG §8.3 prints the line as `day  fill%  jev-err%  reason`; the parser split on tabs only,
        # so a line written as printed failed `make results` on day 28, and nothing read it before
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = os.path.join(tmp, "exclusions.tsv")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("day  fill%  jev-err%  reason\nd06  91.0  0.1  Mac asleep\n12\t80.0\t0.0\ta tab\n")
        days, lines = inference.read_exclusions(p)
        self.assertEqual(days, {6, 12})
        self.assertEqual(lines, ["d06  91.0  0.1  Mac asleep", "12\t80.0\t0.0\ta tab"])       # verbatim
        self.assertEqual(exclusions.status_line(p), f"exclusions: 2 day(s) excluded: d06 d12 ({p})")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("day  fill%  jev-err%  reason\nd6x  91.0  0.1  typo\n")
        self.assertTrue(exclusions.status_line(p).startswith("exclusions: REFUSED, fix before day 28: "))
        # a typo must never become a different day, or part of one (2026-09-28, pre-merge verifier):
        # the day is taken by the line's own separator, and anything left over is refused with path:line
        for bad in ("d1 6\t80.0\t0.0\tMac asleep", "\t20\t0.0\tday field left empty", "d06 d07\t80.0\t0.0\ttwo nights",
                    "d1\t6\t80.0\t0.0\ta tab typed inside the day", "0" * 5000 + "6\t80.0\t0.0\tvery long",
                    "d1 6 80.0 0.0 one-space typo", "d٣\t80.0\t0.0\ta non-ASCII digit"):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("day\tfill%\tjev-err%\treason\n" + bad + "\n")
            with self.assertRaisesRegex(ValueError, rf"^{re.escape(p)}:2: day "):
                exclusions.read_exclusions(p)
        for first in ("day06\t80.0\t0.0\tno header, a typo", "day 16  80.0  0.0  no header"):   # not the header: refused
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(first + "\n")
            with self.assertRaisesRegex(ValueError, rf"^{re.escape(p)}:1: line 1 is neither the header "):
                exclusions.read_exclusions(p)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("DAY  Fill%  jev-err%  reason\nd02  90  0  ok\n")                  # the header in PREREG's form is skipped
        self.assertEqual(exclusions.read_exclusions(p)[0], {2})
        with open(p, "wb") as fh:
            fh.write(b"day\tfill%\tjev-err%\treason\nd03\t90\t0\t\xff\n")
        self.assertTrue(exclusions.status_line(p).startswith(f"exclusions: REFUSED, fix before day 28: {p}: not UTF-8"))
        self.assertTrue(exclusions.status_line(os.path.join(tmp, "none.tsv")).startswith("exclusions: none ("))

    def test_a_header_typed_with_single_spaces_or_reworded_is_still_the_header(self):
        # 52fe1a6 skipped only the exact tab or two-space header, so a header typed with single spaces (as a
        # rendered PREREG §8.3 shows it) or with its columns reworded, accepted before, was refused as a bad
        # day on line 1 and stopped the day-28 run (2026-09-28, round-4 verifier). Line 1 is the header when
        # its first word is 'day' and it holds no digit: a day line always has a digit in its day
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        p = os.path.join(tmp, "exclusions.tsv")
        for header in ("day fill% jev-err% reason", "day\tfill\tjev-err\treason", "Day   Fill %   Jev-err %   Reason",
                       "day\tfill%\tjev-err%\treason\t", "day"):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(header + "\nd06\t91.0\t0.1\tasleep\n")
            self.assertEqual(exclusions.read_exclusions(p), ({6}, ["d06\t91.0\t0.1\tasleep"]), header)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(header + "\n")
            self.assertEqual(exclusions.status_line(p), f"exclusions: none ({p} has no day line)", header)
        # a first line with a digit is a data line whatever its first word, and one that is not a day says so
        for first, bad in (("day 16  80.0  0.0  no header", "'day 16'"), ("day06\t80.0\t0.0\ttypo", "'day06'"),
                           ("day fill% jev-err% reason 2", "'day fill% jev-err% reason 2'"),
                           ("day\tfill%\tjev-err%\treason (PREREG \u00a78.3)", "'day\\tfill%\\tjev-err%\\treason (PREREG \u00a78.3)'"),
                           ("d29\t90.0\t0.0\tout of range", "'d29'"), ("day ٣\t80.0\t0.0\tx", "'day ٣'")):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(first + "\nd06\t91.0\t0.1\tasleep\n")
            with self.assertRaises(ValueError, msg=first) as cm:
                exclusions.read_exclusions(p)
            why = f"; {exclusions.TAB_FORM}" if first.startswith("day\tfill%") else ""   # a tab line whose fill% is not a number
            self.assertEqual(str(cm.exception), f"{p}:1: line 1 is neither the header (day<TAB>fill%<TAB>jev-err%<TAB>reason) "
                                                f"nor a day line: day {bad} is not d01..d28{why} (the line: {first!r})")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("d06\t91.0\t0.1\tno header at all\n")                    # a day line on line 1 is read as one
        self.assertEqual(exclusions.read_exclusions(p)[0], {6})
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("day fill% jev-err% reason\nday fill% jev-err% reason\n")    # only line 1 can be the header
        with self.assertRaisesRegex(ValueError, rf"^{re.escape(p)}:2: day "):
            exclusions.read_exclusions(p)

    def test_a_tab_typed_inside_the_day_is_refused_when_the_reason_is_left_out_or_follows_a_space(self):
        # a tab typed inside the day shifts every column right: with the reason tab-separated it makes five
        # fields (refused), but with the reason left out or typed after a space it made exactly four, and
        # 'd1<TAB>6<TAB>80.0<TAB>0.0' was read as d01 while the line meant, 'd16<TAB>80.0<TAB>0.0', was
        # refused (2026-09-28, round-4 verifier). A tab line's fill% and jev-err% are numbers (or n/a, as the
        # report prints an undefined share), and its reason does not begin with one
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        p = os.path.join(tmp, "exclusions.tsv")
        for bad in ("d1\t6\t80.0\t0.0", "d1\t6\t90.0%\t0.0%", "d1\t6\t80.0\t0.0 Mac asleep", "d1\t6\t80.0\t0.0 ",
                    "d1\t6\t80.0\t0.0\t", "d1\t6\t80.0\t0.0, Mac asleep", "d1\t6\t80.0\t0.0 % asleep", "d1\t6\tn/a\tn/a",
                    "d1\t6 80.0\t0.0\tasleep", "d1\t6\t80.0 0.0\tasleep", "d16\t\t0.0\tfill left empty",
                    "d16\tMac asleep\t0.0\tx", "d16\t80.0\t0.0\t3 h asleep", "d16\t80.0\t0.0\t\t", "d1\t6\t80.0\t\t"):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("day\tfill%\tjev-err%\treason\n" + bad + "\n")
            with self.assertRaisesRegex(ValueError, rf"^{re.escape(p)}:2: day .* is not d01..d28; a tab line is "
                                                    r"day<TAB>fill%<TAB>jev-err%<TAB>reason, ", msg=bad):
                exclusions.read_exclusions(p)
            self.assertTrue(exclusions.status_line(p).startswith(f"exclusions: REFUSED, fix before day 28: {p}:2: day "), bad)
        for good in ("d16\t80.0\t0.0\tMac asleep", "d16\t80.0\t0.0\t", "d16\t80.0\t0.0\t ",    # the reason may be empty
                     "d16\t80.0\t0.0\tMac asleep\t", "d16\t80.0\t0.0\tMac asleep\t\t ",          # tabs after the reason
                     "d16\tn/a\tN/A\tMac asleep all day", "d16\t0/0\tn/a\tNO LIVE ROWS", "16\t94.2%\t0.0%\t3h asleep",
                     "d16\t80,0 %\t0.1;\tx", " d16 \t 80.0 \t 0.0 \t x "):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("day\tfill%\tjev-err%\treason\n" + good + "\n")
            self.assertEqual(exclusions.read_exclusions(p), ({16}, [good]), repr(good))
            self.assertEqual(exclusions.status_line(p), f"exclusions: 1 day(s) excluded: d16 ({p})", repr(good))
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("d1\t6\t80.0\t0.0\n")                                      # on line 1 as well, with both messages
        with self.assertRaisesRegex(ValueError, rf"^{re.escape(p)}:1: line 1 is neither the header .* is not d01..d28; a tab line is "):
            exclusions.read_exclusions(p)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("day  fill%  jev-err%  reason\nd1  6  80.0  0.0  two spaces\n")   # the two-space typo it cannot catch
        self.assertEqual(exclusions.read_exclusions(p)[0], {1})


class Guard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.log = os.path.join(cls.tmp, "decisions.jsonl")
        _write(cls.log, [_row(m) for m in range(42)])                # 2026-09-23 10:00 .. 10:41
        cls.t0 = "2026-09-23T10:00"
        cls.ex = _exclusions(os.path.join(cls.tmp, "exclusions.tsv"))   # header only: no exclusions

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
                                "--exclusions", self.ex, "--accept-pending"])
        self.assertEqual(code, 0, err)
        self.assertIn("--accept-pending given: 1 H2 unit(s)", out)
        self.assertIn("mode sample", out)
        self.assertIn("(clock overridden with --now 2026-10-21T10:00)", out.splitlines()[0])
        self.assertIn("lower bound = sorted[4] (nearest-rank 2.5th percentile)", out)     # ceil(0.025 x 200) - 1
        self.assertIn("NOT the pre-registered run (resamples R != 10000)", out)
        self.assertIn("n blocks 2688", out)                           # every block kept, empty ones as 0
        self.assertIn("blocks on which a gap longer than the horizon lands 0 of 2688", out)
        self.assertIn("days kept 28 of 28", out)
        self.assertIn("H2 -- Pearson", out)
        self.assertIn("exclusions.tsv: absent or empty", out)

    def test_exclusions_drop_96_blocks_per_day_and_void_under_21(self):
        p = os.path.join(self.tmp, "ex.tsv")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("day\tfill%\tjev-err%\treason\n" + "".join(f"d{d:02d}\t50%\t0%\tx\n" for d in range(1, 9)))
        code, out, _ = _main(["--sample", "--log", self.log, "--t0", self.t0, "--now", "2026-10-21T10:00", "--resamples", "50", "--exclusions", p])
        self.assertEqual(code, 0)
        self.assertIn("n blocks 1920", out)                           # 20 days x 96
        self.assertIn("VOID (PREREG §8.3)", out)
        self.assertIn("  d01\t50%\t0%\tx", out)                        # reproduced verbatim
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("d99\t50%\t0%\tx\n")
        code, out, err = _main(["--sample", "--log", self.log, "--t0", self.t0, "--now", "2026-10-21T10:00", "--exclusions", p])
        self.assertEqual(code, 2)
        self.assertIn("not d01..d28", err)

    def test_pre_t0_runs_any_time_on_rows_before_t0_only(self):
        code, out, err = _main(["--pre-t0", "--log", self.log, "--t0", "2026-09-23T10:20", "--resamples", "100",
                                "--exclusions", self.ex])
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


AFTER_SEALED_END = datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc)   # PREREG §11's T0 + 28 d has passed


def _fake_bootstrap(series, stat, seed=inference.SEED, resamples=inference.RESAMPLES, L=inference.BLOCK_LEN):
    """A stand-in with bootstrap's shape, so a test can reach the 10,000-resample path in no time."""
    return {"n": len(series), "lower": 0.0, "reject": False, "sorted": []}


class LiveLog(unittest.TestCase):
    """--log resolving to config.DECISIONS is the launchd log: the pre-registered run only."""

    @classmethod
    def setUpClass(cls):
        pin_prereg(cls)                                               # the repository's PREREG, pinned: T0 2026-09-25T21:40Z
        cls.tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.log = os.path.join(cls.tmp, "decisions.jsonl")
        _write(cls.log, [_row(m) for m in range(42)])                # 2026-09-23, before PREREG's T0: no sample row
        cls.ex = os.path.join(cls.tmp, "exclusions.tsv")
        with open(cls.ex, "w", encoding="utf-8") as fh:
            fh.write("day\tfill%\tjev-err%\treason\n")

    def _run(self, argv, now=AFTER_SEALED_END):
        with mock.patch.object(inference.config, "DECISIONS", self.log):
            return _main(argv + ["--exclusions", self.ex], now=now)

    def test_sample_on_the_live_log_refuses_any_other_resample_count(self):
        with mock.patch.object(outcomes, "load", side_effect=AssertionError("the log was opened")):
            code, out, err = self._run(["--sample", "--resamples", "1000"])
        self.assertEqual((code, out), (3, ""))
        self.assertIn("runs the pre-registered 10000 resamples only, got --resamples 1000", err)
        # the same log by another spelling of its path is still the live log
        with mock.patch.object(outcomes, "load", side_effect=AssertionError("the log was opened")):
            code, _, err = self._run(["--sample", "--resamples", "1000", "--log", os.path.join(self.tmp, ".", "decisions.jsonl")])
        self.assertEqual(code, 3, err)

    def test_sample_on_the_live_log_at_10000_is_the_pre_registered_run(self):
        with mock.patch.object(inference, "bootstrap", _fake_bootstrap):
            code, out, err = self._run(["--sample"])
        self.assertEqual(code, 0, err)
        self.assertIn("10000 resamples", out)
        self.assertIn("lower bound = sorted[249]", out)
        self.assertNotIn("NOT the pre-registered run", out)

    def test_pre_t0_on_the_live_log_may_use_fewer_resamples_and_says_so(self):
        code, out, err = self._run(["--pre-t0", "--resamples", "50"])
        self.assertEqual(code, 0, err)
        self.assertIn("NOT the pre-registered run (resamples R != 10000)", out)

    def test_a_hard_link_to_the_live_log_is_the_live_log(self):
        link = os.path.join(self.tmp, "linked.jsonl")
        os.link(self.log, link)
        with mock.patch.object(outcomes, "load", side_effect=AssertionError("the log was opened")):
            code, out, err = self._run(["--sample", "--resamples", "1000", "--log", link])
        self.assertEqual((code, out), (3, ""))
        self.assertIn("runs the pre-registered 10000 resamples only", err)

    def test_a_copy_of_the_log_is_not_the_live_log(self):
        code, out, err = _main(["--sample", "--log", self.log, "--resamples", "50", "--exclusions", self.ex], now=AFTER_SEALED_END)
        self.assertEqual(code, 0, err)
        self.assertIn("NOT the pre-registered run", out)

    def test_now_is_refused_on_the_live_log_in_both_modes(self):
        for mode in ("--sample", "--pre-t0"):
            with mock.patch.object(outcomes, "load", side_effect=AssertionError("the log was opened")):
                code, out, err = self._run([mode, "--now", "2026-10-24T00:00"], now=None)
            self.assertEqual((code, out), (3, ""), mode)
            self.assertIn("refusing: --now 2026-10-24T00:00 overrides the clock, and the live log is read on the real clock only", err)

    def test_a_t0_other_than_prereg_section_11_is_refused_on_the_live_log_in_both_modes(self):
        for mode, t0 in (("--sample", "2026-09-23T10:00"), ("--pre-t0", "2026-09-26T00:00"), ("--pre-t0", "2026-09-25T21:39")):
            with mock.patch.object(outcomes, "load", side_effect=AssertionError("the log was opened")):
                code, out, err = self._run([mode, "--t0", t0])
            self.assertEqual((code, out), (3, ""), (mode, t0))
            self.assertIn(f"refusing: --t0 {t0} is not PREREG §11's T0 2026-09-25T21:40Z", err)
        with mock.patch.object(inference, "bootstrap", _fake_bootstrap):   # the sealed T0 itself, either spelling, is fine
            for t0 in ("20260925T214000Z", "2026-09-25T21:40"):
                code, out, err = self._run(["--sample", "--t0", t0])
                self.assertEqual(code, 0, err)
                self.assertIn("T0 2026-09-25T21:40Z", out)

    def test_another_prereg_is_refused_on_the_live_log(self):
        p = os.path.join(self.tmp, "PREREG.md")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("T0 (first tick_id of day 1): `20260901T000000Z`\n")
        code, out, err = self._run(["--pre-t0", "--prereg", p])
        self.assertEqual((code, out), (3, ""))
        self.assertIn(f"--prereg {p} is not the repository's PREREG.md", err)

    def test_the_real_clock_still_refuses_the_live_sample_before_day_28(self):
        code, out, err = self._run(["--sample"], now=datetime.datetime(2026, 10, 23, 21, 39, tzinfo=datetime.timezone.utc))
        self.assertEqual((code, out), (3, ""))
        self.assertIn("refusing to look: the sample ends 2026-10-23T21:40Z", err)


class PreT0Cut(unittest.TestCase):
    """--pre-t0 takes the rows before the EARLIER of --t0 and PREREG §11's T0 (2026-09-25T21:40Z)."""

    @classmethod
    def setUpClass(cls):
        pin_prereg(cls)
        cls.tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.log = os.path.join(cls.tmp, "copy.jsonl")                 # not the live log: --t0 is accepted
        sealed = report._t0("2026-09-25T21:40")
        _write(cls.log, _minutes(sealed - 10 * 60, sealed + 10 * 60), garbage=False)   # 21:30 .. 21:49, ten each side
        cls.ex = os.path.join(cls.tmp, "exclusions.tsv")
        with open(cls.ex, "w", encoding="utf-8") as fh:
            fh.write("day\tfill%\tjev-err%\treason\n")

    def test_a_later_t0_still_cuts_at_the_sealed_t0(self):
        code, out, err = _main(["--pre-t0", "--log", self.log, "--t0", "2026-09-26T00:00", "--resamples", "20", "--exclusions", self.ex])
        self.assertEqual(code, 0, err)
        self.assertIn("rows in scope 10\n", out)                      # 21:30 .. 21:39, never a sample row
        self.assertIn("rows before 2026-09-25T21:40Z (the earlier of --t0 and PREREG §11's T0)", out)

    def test_an_earlier_t0_cuts_there(self):
        code, out, err = _main(["--pre-t0", "--log", self.log, "--t0", "2026-09-25T21:35", "--resamples", "20", "--exclusions", self.ex])
        self.assertEqual(code, 0, err)
        self.assertIn("rows in scope 5\n", out)
        self.assertIn("rows before 2026-09-25T21:35Z", out)


class SealedCopy(unittest.TestCase):
    """A log holding rows of the repository's sealed sample (PREREG §11: 2026-09-25 21:40Z + 28 d) is read on
    the real clock wherever it lives: a copy of the live log with --now, another --t0 or another --prereg
    is not a way to look before day 28, and --pre-t0 cuts at the repository's seal whatever --prereg says."""
    SEALED = report._t0("2026-09-25T21:40")
    BEFORE_END = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)

    @classmethod
    def setUpClass(cls):
        pin_prereg(cls)                                               # "the repository's" seal: the pinned fixture's
        cls.tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.log = os.path.join(cls.tmp, "copy.jsonl")
        _write(cls.log, _minutes(cls.SEALED - 600, cls.SEALED + 42 * 60, mid=lambda e: 100.0 + (e % 3600) / 600.0), garbage=False)
        cls.none = _exclusions(os.path.join(cls.tmp, "none.tsv"))     # 10 rows before the seal, 42 inside the sample
        cls.unsealed = os.path.join(cls.tmp, "PREREG.md")
        with open(cls.unsealed, "w", encoding="utf-8") as fh:
            fh.write("# a PREREG with no T0 line\n")

    def test_sample_with_now_is_refused_before_the_real_end(self):
        with mock.patch.object(inference, "bootstrap", side_effect=AssertionError("the draw ran")):
            code, out, err = _main(["--sample", "--log", self.log, "--t0", "2026-09-25T21:40", "--now", "2026-10-24T00:00",
                                    "--resamples", "20", "--exclusions", self.none], now=self.BEFORE_END)
        self.assertEqual(code, 3, err)
        self.assertIn(f"refusing to look: {self.log} holds 42 rows of the sealed sample [2026-09-25T21:40Z, 2026-10-23T21:40Z)"
                      " and it is 2026-10-01T00:00Z: a copy of the live log is read on the real clock", err)
        self.assertEqual(out, "")

    def test_another_t0_or_prereg_does_not_help(self):
        with mock.patch.object(inference, "bootstrap", side_effect=AssertionError("the draw ran")):
            code, _, err = _main(["--sample", "--log", self.log, "--t0", "2026-09-25T21:30", "--prereg", self.unsealed, "--now",
                                  "2026-10-24T00:00", "--resamples", "20", "--exclusions", self.none], now=self.BEFORE_END)
        self.assertEqual(code, 3, err)
        self.assertIn("holds 42 rows of the sealed sample", err)

    def test_runs_after_the_real_end(self):
        code, out, err = _main(["--sample", "--log", self.log, "--t0", "2026-09-25T21:40", "--resamples", "20",
                                "--exclusions", self.none, "--accept-pending"], now=AFTER_SEALED_END)
        self.assertEqual(code, 0, err)
        self.assertIn("T0 2026-09-25T21:40Z", out)

    def test_pre_t0_cuts_at_the_repository_seal_whatever_prereg_says(self):
        code, out, err = _main(["--pre-t0", "--log", self.log, "--t0", "2026-09-26T00:00", "--prereg", self.unsealed,
                                "--resamples", "20", "--exclusions", self.none], now=self.BEFORE_END)
        self.assertEqual(code, 0, err)
        self.assertIn("rows before 2026-09-25T21:40Z (the earlier of --t0 and PREREG §11's T0)", out)


class RuleThree(unittest.TestCase):
    """PREREG §8.3 recomputed beside the exclusions file: descriptive lines that change no number."""

    @staticmethod
    def _day(d, bad=False, empty=False, open_=False):
        return {"day": d, "bad": bad, "empty": empty, "open": open_}

    def _lines(self, days, excluded):
        return inference.rule3_lines({"days": days}, excluded, n_days=6)

    def test_every_sample_day_is_placed_once(self):
        # d01 BAD, d02 fine, d03 no live rows, d04 BAD on jev errors alone (empty too: BAD wins), d05
        # open; d06 has no row at all (after the log's last row): no live rows, never "judged fine"
        days = [self._day("d01", bad=True), self._day("d02"), self._day("d03", empty=True),
                self._day("d04", bad=True, empty=True), self._day("d05", open_=True)]
        lines = self._lines(days, {2, 3, 5, 6})
        self.assertEqual(lines[1], "  BAD by the rule, recomputed from the log: d01 d04 (2; the rule pauses the run at 3)")
        self.assertEqual(lines[2], "  listed and BAD: none; listed but judged fine by the rule: d02; BAD but NOT listed: d01 d04")
        self.assertEqual(lines[3], "  open, not yet judged (a day's last t + h is not in the log): d05, listed: d05")
        self.assertEqual(lines[4], "  no live rows (0/0, the rule undefined; Alex's call; includes any day after the log's last row):"
                                   " d03 d06, listed: d03 d06")

    def test_agreement_reads_none_everywhere(self):
        lines = self._lines([self._day(f"d0{k}", bad=k == 2) for k in range(1, 7)], {2})
        self.assertEqual(lines[2], "  listed and BAD: d02; listed but judged fine by the rule: none; BAD but NOT listed: none")
        self.assertEqual(lines[3], "  open, not yet judged (a day's last t + h is not in the log): none")
        self.assertTrue(lines[4].endswith(": none"))

    def test_a_sample_run_prints_them_and_a_pre_t0_run_does_not(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        log, ex = os.path.join(tmp, "edge.jsonl"), _exclusions(os.path.join(tmp, "ex.tsv"), [1, 2])
        _write(log, _edge_rows(), garbage=False)
        code, out, err = _main(["--sample", "--log", log, "--t0", T0S, "--now", "2026-10-21T10:00", "--resamples", "20",
                                "--exclusions", ex, "--accept-pending"])
        self.assertEqual(code, 0, err)
        self.assertIn("stop rule 3 cross-check (PREREG §8.3, descriptive; the exclusions file above decides, this changes no number):", out)
        self.assertIn("  open, not yet judged (a day's last t + h is not in the log): d01, listed: d01", out)   # a 4-hour log
        self.assertIn("includes any day after the log's last row): d02 d03", out)                          # d02..d28 have no row
        self.assertRegex(out, r"includes any day after the log's last row\): d02 .* d27 d28, listed: d02\n")   # d28, the last day, too
        self.assertIn(", listed: d02\n", out)
        code, out, err = _main(["--pre-t0", "--log", log, "--t0", "2026-09-23T12:00", "--resamples", "20", "--exclusions", ex])
        self.assertEqual(code, 0, err)
        self.assertNotIn("stop rule 3 cross-check", out)


class EveryRow(unittest.TestCase):
    def test_the_every_row_side_numbers_count_rows_and_say_so(self):
        # a second live decision in a minute shares the minute's outcome (the join is per tick); the
        # side numbers count every kept live row, as report §5 does, and the line says rows, not ticks
        rows = _edge_rows(blocks=4)
        extra = dict(rows[5], ts_rx=rows[5]["ts_rx"][:17] + "30.000Z")
        both = rows + [extra]
        one = inference.h2(rows, outcomes.join(rows), T0, resamples=20)["side_every"]
        two = inference.h2(both, outcomes.join(both), T0, resamples=20)["side_every"]
        self.assertEqual(two["n"], one["n"] + 1)
        lines = inference.side_lines(inference.h2(both, outcomes.join(both), T0, resamples=20))
        self.assertTrue(any("every kept live row (overlapping horizons; a second decision in a minute shares its outcome)" in l
                            and f"over {two['n']} rows" in l for l in lines), lines)


class LiveClock(unittest.TestCase):
    """On the live log the real clock caps 'the log's last row': a row stamped after it (a clock that
    stepped forward) must not satisfy the pending refusal, nor close d28 in the stop-rule-3 lines."""

    def test_a_row_stamped_after_the_clock_does_not_lift_the_pending_refusal(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        sealed = report._t0("2026-09-25T21:40")
        end = sealed + 28 * 86400
        rows = _minutes(end - 30 * 60, end, up=0.6, down=0.4)          # the last two blocks; the log stops at 21:39
        stray = dict(rows[-1], tick_id="20261101T000000Z", ts_rx="2026-11-01T00:00:00.100Z")   # a clock stepped forward
        log = os.path.join(tmp, "decisions.jsonl")
        _write(log, rows + [stray], garbage=False)
        ex = _exclusions(os.path.join(tmp, "none.tsv"))
        run_at = datetime.datetime.fromtimestamp(end + 10, datetime.timezone.utc)   # 21:40:10, the 21:40 row not yet written
        with mock.patch.object(inference.config, "DECISIONS", log), \
                mock.patch.object(inference, "bootstrap", side_effect=AssertionError("the draw ran")):
            code, out, err = _main(["--sample", "--exclusions", ex], now=run_at)
        self.assertEqual((code, out), (3, ""), err)
        self.assertIn("refusing to run: 1 H2 unit(s) wait for a t + h the log has not reached", err)


class Reading(unittest.TestCase):
    """PREREG §8.1-§8.2's stop rules and §5/§9's reading, each on a line of its own, from the verdicts."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.edge = os.path.join(cls.tmp, "edge.jsonl")              # B beats C on 16 blocks, lean tracks the return
        _write(cls.edge, _edge_rows(), garbage=False)
        cls.flat = os.path.join(cls.tmp, "flat.jsonl")              # every arm holds; lean runs against the return
        _write(cls.flat, _edge_rows(b_trades=False, lean_step=0.01), garbage=False)
        cls.none = _exclusions(os.path.join(cls.tmp, "none.tsv"))
        cls.seven = _exclusions(os.path.join(cls.tmp, "seven.tsv"), range(2, 9))    # 21 kept: not void
        cls.eight = _exclusions(os.path.join(cls.tmp, "eight.tsv"), range(2, 10))   # 20 kept: void

    def _run(self, log, ex):
        code, out, err = _main(["--sample", "--log", log, "--t0", T0S, "--now", "2026-10-21T10:00", "--resamples", "100", "--exclusions", ex])
        self.assertEqual(code, 0, err)
        return out.splitlines()

    def _line(self, lines, start):
        hit = [l for l in lines if l.startswith(start)]
        self.assertEqual(len(hit), 1, (start, lines))
        return hit[0]

    def test_b_beats_c_and_lean_tracks_the_return_the_loop_works_as_described(self):
        lines = self._run(self.edge, self.none)
        i = lines.index(self._line(lines, "  B - A: "))
        ba = lines[i + 1].split("mean S_k ")[1].split(" bps")[0]           # the point estimate printed under B - A
        self.assertIn("  stop rule 1: B-C reject=True, A-C reject=False -> does not fire", lines)
        self.assertIn(f"  stop rule 2: mean S_k(B-A) = {ba} -> does not fire", lines)
        self.assertIn("  primaries: H1 (B - C) reject=True, H2 reject=True -> both primaries hold: 'the loop works as described' (§5),"
                      " which does not say it earns anything at a retail fee (§4)", lines)
        self.assertIn("  H1 (§9): H1 rejected for B and not for A: the rewrite earned its keep over the rule", lines)
        self.assertTrue(self._line(lines, "  H2 (§9): ").startswith("  H2 (§9): H2 supported: "))
        self.assertFalse(any("VOID" in l for l in lines))

    def test_no_arm_beats_c_stop_rules_1_and_2_fire_whatever_h2_shows(self):
        lines = self._run(self.flat, self.none)
        self.assertIn("  stop rule 1: B-C reject=False, A-C reject=False -> fires", lines)
        self.assertIn("  stop rule 2: mean S_k(B-A) = 0.0000 -> fires", lines)      # <= 0 fires, 0 included
        self.assertIn("  primaries: H1 (B - C) reject=False, H2 reject=False -> neither primary holds", lines)
        self.assertTrue(self._line(lines, "  H1 (§9): ").startswith("  H1 (§9): neither A nor B beats C on H1: "))
        self.assertTrue(self._line(lines, "  H1 (§9): ").endswith("(stop rule 1)"))
        self.assertTrue(self._line(lines, "  H2 (§9): ").startswith("  H2 (§9): H2 not supported: "))

    def test_21_kept_days_read_the_stop_rules_20_are_void_and_say_so_on_every_verdict(self):
        kept21 = self._run(self.edge, self.seven)
        self.assertIn("  days kept 21 of 28; excluded [2, 3, 4, 5, 6, 7, 8] (" + self.seven + ", reproduced below)", kept21)
        self.assertFalse(any("VOID" in l for l in kept21))
        self.assertIn("  stop rule 1: B-C reject=True, A-C reject=False -> does not fire", kept21)
        void = self._run(self.edge, self.eight)
        self.assertIn("  stop rule 1: B-C reject=True, A-C reject=False -> does not fire", [l.replace("VOID: ", "") for l in void])
        self.assertIn("  VOID: stop rule 1: B-C reject=True, A-C reject=False -> does not fire", void)
        self.assertIn("  VOID (PREREG §8.3): fewer than 21 days kept: the block is void and the stop rules are not read", void)
        for start in ("  VOID: stop rule 2: ", "  VOID: primaries: ", "  VOID: H1 (§9): ", "  VOID: H2 (§9): "):
            self._line(void, start)
        verdicts = [l for l in void if " -> " in l and not l.startswith("  VOID: ")]
        self.assertEqual(len(verdicts), 4, verdicts)                        # B - C, A - C, B - A and H2
        self.assertTrue(all(" -> VOID: " in l for l in verdicts), verdicts)

    def test_every_combination_of_verdicts(self):
        def h1s(b, a, ba):
            return [{"pair": "B - C", "reject": b}, {"pair": "A - C", "reject": a}, {"pair": "B - A", "reject": None, "mean": ba}]
        cases = {  # (B - C, A - C, H2) -> (stop rule 1, primaries, H1 reading, H2 reading)
            (True, True, True): ("does not fire", "both primaries hold", "H1 rejected for B and for A", "H2 supported: "),
            (True, False, False): ("does not fire", "H1 alone", "H1 rejected for B and not for A", "H2 not supported"),
            (False, True, False): ("does not fire", "neither primary holds", "H1 rejected for A and not for B", "H2 not supported"),
            (False, True, True): ("does not fire", "H2 alone", "H1 rejected for A and not for B", "H2 supported and H1 not"),
            (False, False, True): ("fires", "H2 alone", "neither A nor B beats C", "H2 supported and H1 not"),
            (False, False, False): ("fires", "neither primary holds", "neither A nor B beats C", "H2 not supported"),
        }
        for (b, a, h2), (sr1, prim, r1, r2) in cases.items():
            lines = inference.reading(h1s(b, a, 0.5), {"reject": h2, "n": 10})
            self.assertIn(f"  stop rule 1: B-C reject={b}, A-C reject={a} -> {sr1}", lines)
            self.assertIn(f"H2 reject={h2} -> {prim}", self._line(lines, "  primaries: "))
            self.assertTrue(self._line(lines, "  H1 (§9): ").startswith(f"  H1 (§9): {r1}"), (b, a, h2))
            self.assertTrue(self._line(lines, "  H2 (§9): ").startswith(f"  H2 (§9): {r2}"), (b, a, h2))
        for ba, sr2 in ((0.5, "does not fire"), (0.0, "fires"), (-0.25, "fires"), (-1e-9, "fires"), (None, "not read (no blocks)")):
            self.assertIn(f"  stop rule 2: mean S_k(B-A) = {inference._f(ba)} -> {sr2}", inference.reading(h1s(True, True, ba), {"reject": True, "n": 10}))
        self.assertIn("  PRE-T0: a smoke of the procedure; no stop rule and no reading applies before T0",
                      inference.reading(h1s(False, False, 0.0), {"reject": False, "n": 10}, pre_t0=True))


class ExcludedDays(unittest.TestCase):
    """An excluded day leaves every number, not only S_k and the units: the log is day 1 (16 blocks of
    B trading) plus day 2 (4 more, a live row missing a noul, an outage row); excluding d02 must
    read exactly as the log of day 1 alone."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        d2 = T0 + 86400
        outage = _at(d2 + 900 * 11, absence="feed")
        outage.update(bid=None, ask=None, mid=None, answers=None, columns={"a": None, "b": None})
        cls.day1 = _edge_rows()
        cls.both = cls.day1 + _edge_rows(blocks=4, day=2) + [_at(d2 + 900 * 10, up=None), outage]
        cls.log = os.path.join(cls.tmp, "two-days.jsonl")
        _write(cls.log, cls.both, garbage=False)
        cls.ex = _exclusions(os.path.join(cls.tmp, "ex.tsv"), [2])

    def _load(self, rows):
        path = os.path.join(self.tmp, "x.jsonl")
        _write(path, rows, garbage=False)
        rows = outcomes.load(path, [])
        return rows, outcomes.join(rows)

    def test_h1_descriptive_numbers_read_the_kept_days_only(self):
        both, ob = self._load(self.both)
        one, o1 = self._load(self.day1)
        for x, y in (("b", "c"), ("a", "c"), ("b", "a")):
            e = inference.h1_series(both, ob, x, y, T0, excluded={2})
            s = inference.h1_series(one, o1, x, y, T0)
            for key in ("ticks", "mean_tick", "trades_x", "trades_y", "forced_x", "forced_y", "dis_blocks", "mean_dis", "gap_blocks"):
                self.assertEqual(e[key], s[key], (x, y, key))
            _same(self, e["series"], [(k, v) for k, v in s["series"] if inference.day_of_block(k) != 2])
            self.assertEqual(e["days"], 27)
        full = inference.h1_series(both, ob, "b", "c", T0)                  # the same log with nothing excluded counts day 2
        self.assertEqual((full["trades_x"], full["forced_x"]), (32 + 8, 2 + 2 + 1))
        self.assertEqual((e["trades_x"], e["forced_x"]), (32, 2))

    def test_h2_units_and_side_numbers_read_the_kept_days_only(self):
        both, ob = self._load(self.both)
        one, o1 = self._load(self.day1)
        e = inference.h2(both, ob, T0, excluded={2}, resamples=20)
        s = inference.h2(one, o1, T0, resamples=20)
        for key in ("n", "blocks_with_row", "dropped", "r", "rho", "lower", "units", "side_units", "side_every", "dropped_every"):
            self.assertEqual(e[key], s[key], key)
        full = inference.h2(both, ob, T0, resamples=20)
        self.assertEqual((full["blocks_with_row"], full["dropped"]), (16 + 4 + 1, {"noul": 1}))
        self.assertEqual((e["blocks_with_row"], e["dropped"]), (16, {}))

    def test_units_of_the_kept_rows_are_the_units_of_every_row_less_the_excluded_days(self):
        both, ob = self._load(self.both)
        live = sorted((r for r in both if report._live(r)), key=lambda r: r["tick_id"])
        kept = [r for r in live if inference.kept_tick(r["tick_id"], T0, {2})]
        all_units, _, _ = report.h2_units(live, ob, T0)
        kept_units, _, _ = report.h2_units(kept, ob, T0)
        self.assertEqual(kept_units, [u for u in all_units if inference.day_of_block(u["k"]) != 2])   # blocks nest in days
        self.assertLess(len(kept_units), len(all_units))

    def test_trades_per_day_and_the_side_numbers_are_printed(self):
        code, out, err = _main(["--sample", "--log", self.log, "--t0", T0S, "--now", "2026-10-21T10:00", "--resamples", "40",
                                "--exclusions", self.ex])
        self.assertEqual(code, 0, err)
        self.assertIn("trades 32 vs 0 (1.19 vs 0.00 per day over 27 kept days)", out)       # PREREG §4: trades/day each side
        self.assertIn("every tick mean d_t 8.7977 over 242", out)                          # day 1's 242 rows, not day 2's
        one, o1 = self._load(self.day1)
        s = inference.h2(one, o1, T0, resamples=20)["side_units"]
        self.assertIn(f"  descriptive (PREREG §5, never claimed): Spearman rho {inference._f(s['rho'])} over the 16 units;", out)
        bu = s["brier_up"]
        self.assertIn(f"  descriptive: Brier on the units up15 {inference._f(bu[0])} vs base {inference._f(bu[1])}", out)
        self.assertIn("  descriptive: measured tails (>= 0.99 / < 0.15) on the units up15 0/0, down15 0/0;", out)
        self.assertIn("  descriptive: the trend word (no model): units r(lean, trend) undefined (no variance in trend)", out)


class PerDay(unittest.TestCase):
    """Each kept day's live blocks and units, and a kept day with no live row flagged, rows or not."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.log = os.path.join(cls.tmp, "no-day-2.jsonl")        # 16 blocks on d01, none on d02 (no row at all), 4 on d03
        _write(cls.log, _edge_rows() + _edge_rows(blocks=4, day=3), garbage=False)
        cls.ex = _exclusions(os.path.join(cls.tmp, "ex.tsv"), [4])

    def test_every_kept_day_is_listed_and_a_day_without_live_rows_is_flagged(self):
        code, out, err = _main(["--sample", "--log", self.log, "--t0", T0S, "--now", "2026-10-21T10:00", "--resamples", "40",
                                "--exclusions", self.ex])
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertIn("per kept day (descriptive): blocks holding a live row, of 96, and the H2 units the day gave", lines)
        self.assertIn("  d01  16/96 blocks  16 units", lines)
        self.assertIn("  d02   0/96 blocks   0 units  no live rows: stop rule 3 is undefined (fill 0/0);"
                      " the exclusion is Alex's call (PREREG §8.3)", lines)
        self.assertIn("  d03   4/96 blocks   4 units", lines)
        self.assertFalse(any(l.startswith("  d04 ") for l in lines))     # excluded: not a kept day
        days = [l for l in lines if l[:3] == "  d" and l[3:5].isdigit() and "/96 blocks" in l]
        self.assertEqual(len(days), 27)
        self.assertEqual(sum(1 for l in days if inference.NO_LIVE_ROWS in l), 25)   # d02 and d05 .. d28

    def test_per_day_counts_blocks_with_a_live_row_and_units_apart(self):
        rows = outcomes.load(self.log, [])
        outs = outcomes.join(rows)
        extra = _at(T0 + 900 * 20, up=None)                           # d01 block 20: a live row, no unit (a noul missing)
        h = inference.h2(report.in_sample(rows + [extra], T0), outs, T0, resamples=20)
        self.assertEqual((h["per_day"][1], h["per_day"][2], h["per_day"][3]), ([17, 16], [0, 0], [4, 4]))
        self.assertEqual(sorted(h["per_day"]), list(range(1, 29)))
        self.assertNotIn(4, inference.h2(report.in_sample(rows, T0), outs, T0, excluded={4}, resamples=20)["per_day"])


def _end_rows():
    """Live rows every minute from 09:30 to 10:15 on the sample's last day (T0 + 28 d = 10:00): the
    last two blocks' first rows (09:30, 09:45) and every t + h they need, the last one past the end."""
    lean = lambda e: 0.5 + 0.1 * ((e // 60) % 4)                      # a varying up15, so r is defined
    return _minutes(END - 30 * 60, END + 16 * 60, up=lean, mid=lambda e: 100.0 + ((e // 60) % 7) * 0.01)


class Pending(unittest.TestCase):
    """The clock lifts at T0 + 28 d, but the last block's unit needs the row at t + 900 s +- 30 s:
    a run in between would count that outcome as a gap and drop the unit for good."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.ex = os.path.join(cls.tmp, "exclusions.tsv")
        with open(cls.ex, "w", encoding="utf-8") as fh:
            fh.write("day\tfill%\tjev-err%\treason\n")
        cls.rows = _end_rows()
        cls.stopped = os.path.join(cls.tmp, "stopped.jsonl")              # the log as it stands at 10:00:00: last row 09:59
        _write(cls.stopped, [r for r in cls.rows if report.tick_epoch(r["tick_id"]) < END], garbage=False)
        cls.full = os.path.join(cls.tmp, "full.jsonl")                    # every t + h written (the last row 10:15)
        _write(cls.full, cls.rows, garbage=False)

    def _run(self, log, *extra):
        return _main(["--sample", "--log", log, "--t0", T0S, "--now", "2026-10-21T10:00", "--resamples", "40",
                      "--exclusions", self.ex, *extra], now=AFTER_SEALED_END)

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


def _block_sums(d, anchor=T0, n_blocks=2688):
    """PREREG §3 from book.paired's own output: S_k = the sum of d_t over block k, 0.0 where empty."""
    S = [0.0] * n_blocks
    for t, v in d:
        S[int((report.tick_epoch(t) - anchor) // 900)] += v
    return S


class Pinned(unittest.TestCase):
    """What each statistic IS, not only its length and label: the H1 series against book.paired at
    the primary cell, B - A's sign and value, H2's units, its Pearson on 12-decimal leans, the
    degenerate case, void, the join past the sample's end, and the clock at the end."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)

        def load(rows):
            path = os.path.join(cls.tmp, f"{len(os.listdir(cls.tmp))}.jsonl")
            _write(path, rows, garbage=False)
            rows = outcomes.load(path, [])
            return path, report.in_sample(rows, T0), outcomes.join(rows)

        # B trades at confidence 0.45: argmax buys and sells, c50 would hold; A sells at minute 5
        cls.log, cls.rows, cls.outs = load(_edge_rows(b_conf=0.45, a_sell=5))
        cls.ex = _exclusions(os.path.join(cls.tmp, "none.tsv"))

    def test_h1_series_is_book_paired_b_minus_c_at_argmax_and_0_bps_summed_per_block(self):
        self.assertEqual(inference.config.FEE_BPS_PRIMARY, 0.0)
        want = _block_sums(book.paired(self.rows, self.outs, "b", "c", "argmax", 0.0))
        got = inference.h1_series(self.rows, self.outs, "b", "c", T0)
        _same(self, got["series"], list(enumerate(want)))
        self.assertGreater(sum(want), 0.0)                                  # B minus C: B wins these blocks
        self.assertNotEqual(want, _block_sums(book.paired(self.rows, self.outs, "c", "b", "argmax", 0.0)))
        self.assertNotEqual(want, _block_sums(book.paired(self.rows, self.outs, "b", "c", "c50", 0.0)))    # the column matters here
        self.assertNotEqual(want, _block_sums(book.paired(self.rows, self.outs, "b", "c", "argmax", 120.0)))  # and so does the fee
        a = inference.h1_series(self.rows, self.outs, "a", "c", T0)
        _same(self, a["series"], list(enumerate(_block_sums(book.paired(self.rows, self.outs, "a", "c", "argmax", 0.0)))))

    def test_b_minus_a_is_b_minus_a_and_its_mean_is_pinned(self):
        # per block B makes 1.38 q and A 0.48 q USD on the same entry (q = 1000 / ask), so B - A is
        # 0.9 q USD = 9000 / (100.01 + 0.5 j) bps of the 1,000 USD notional, over 16 of 2,688 blocks
        closed = sum(9000.0 / (100.01 + 0.5 * j) for j in range(16)) / 2688
        ba = inference.h1(self.rows, self.outs, T0, resamples=20)[2]
        self.assertEqual((ba["pair"], ba["lower"], ba["reject"]), ("B - A", None, None))   # a point estimate, never tested
        self.assertAlmostEqual(ba["mean"], closed, places=9)
        self.assertAlmostEqual(ba["mean"], 0.5165563466, places=9)          # the same number, pasted
        self.assertEqual(ba["mean"], sum(_block_sums(book.paired(self.rows, self.outs, "b", "a", "argmax", 0.0))) / 2688)
        code, out, err = _main(["--sample", "--log", self.log, "--t0", T0S, "--now", "2026-10-21T10:00", "--resamples", "20",
                                "--exclusions", self.ex], now=AFTER_SEALED_END)
        self.assertEqual(code, 0, err)
        self.assertIn("  stop rule 2: mean S_k(B-A) = 0.5166 -> does not fire", out)

    def test_h2_units_are_report_h2_units_on_the_kept_days(self):
        live = sorted((r for r in self.rows if report._live(r)), key=lambda r: r["tick_id"])
        units, _, _ = report.h2_units(live, self.outs, T0)
        self.assertEqual(inference.h2(self.rows, self.outs, T0, resamples=20)["units"], [(u["k"], u["lean"], u["ret"]) for u in units])
        self.assertEqual(len(units), 16)
        self.assertEqual(inference.h2(self.rows, self.outs, T0, excluded={1}, resamples=20)["units"], [])

    def test_h2_is_pearson_on_the_units_and_its_bootstrap_is_pearsons(self):
        h = inference.h2(self.rows, self.outs, T0, resamples=200)
        xs, ys = [x for _, x, _ in h["units"]], [y for _, _, y in h["units"]]
        self.assertEqual(h["r"], report.pearson(xs, ys))
        self.assertNotEqual(report.pearson(xs, ys), report.spearman(xs, ys))   # so a Spearman in its place shows
        ps = list(zip(xs, ys))
        self.assertEqual(h["lower"], inference.bootstrap(ps, inference.pearson_pairs, resamples=200)["lower"])
        spear = inference.bootstrap(ps, lambda q: report.spearman([x for x, _ in q], [y for _, y in q]), resamples=200)
        self.assertNotEqual(h["lower"], spear["lower"])

    def test_leans_are_rounded_to_12_decimals_before_anything(self):
        # four units whose leans differ only in the 13th decimal: one lean at 12 decimals, so
        # "no variance in lean" (a 15-decimal rounding would see four and compute an r)
        rows = []
        for j in range(4):
            rows += _minutes(T0 + 900 * j, T0 + 900 * (j + 1), mid=100.0 + j * j, up=0.55 + j * 1e-13, down=0.45)
        rows += [_at(T0 + 3600 + 60 * m, mid=110.0, mode="dry") for m in (0, 1)]
        loaded = outcomes.load(self._write(rows), [])
        h = inference.h2(report.in_sample(loaded, T0), outcomes.join(loaded), T0, resamples=20)
        self.assertEqual({x for _, x, _ in h["units"]}, {0.1})
        self.assertEqual(len(h["units"]), 4)
        self.assertEqual((h["degenerate"], h["lower"], h["reject"]), ("no variance in lean", None, False))

    def _write(self, rows):
        path = os.path.join(self.tmp, f"w{len(os.listdir(self.tmp))}.jsonl")
        _write(path, rows, garbage=False)
        return path

    def test_the_degenerate_cases_are_recorded_not_bootstrapped(self):
        flat_ret = []
        for j in range(4):                                                   # the mid never moves: every ret is 0
            flat_ret += _minutes(T0 + 900 * j, T0 + 900 * (j + 1), up=0.5 + 0.05 * j, down=0.4)
        flat_ret += [_at(T0 + 3600 + 60 * m, mode="dry") for m in (0, 1)]
        path = self._write(flat_ret)
        with mock.patch.object(inference, "bootstrap", side_effect=AssertionError("a degenerate H2 is not bootstrapped")):
            h = inference.h2(report.in_sample(outcomes.load(path, []), T0), outcomes.join(outcomes.load(path, [])), T0, resamples=20)
        self.assertEqual((h["n"], h["degenerate"], h["lower"], h["reject"]), (4, "no variance in ret", None, False))
        code, out, err = _main(["--sample", "--log", path, "--t0", T0S, "--now", "2026-10-21T10:00", "--resamples", "20",
                                "--exclusions", self.ex], now=AFTER_SEALED_END)
        self.assertEqual(code, 0, err)
        self.assertIn("n units 4 (blocks with a live row 4; dropped none): not supported: no variance in ret (PREREG §5 degenerate case)", out)

    def test_a_unit_whose_t_plus_h_is_after_the_sample_end_gets_its_outcome(self):
        rows = _minutes(END - 15 * 60, END + 2 * 60, mid=lambda e: 100.0 + (e - END) / 6000.0)   # 09:45 .. 10:01; 10:00 is past the end
        path = self._write(rows)
        all_rows = outcomes.load(path, [])
        scope = report.in_sample(all_rows, T0)
        self.assertEqual(max(r["tick_id"] for r in scope), "20261021T095900Z")
        h = inference.h2(scope, outcomes.join(all_rows), T0, resamples=20)
        self.assertEqual([(k, round(y, 9)) for k, _, y in h["units"]], [(2687, round(1e4 * math.log(100.0 / 99.85), 9))])
        code, out, err = _main(["--sample", "--log", path, "--t0", T0S, "--now", "2026-10-21T10:02", "--resamples", "20",
                                "--exclusions", self.ex], now=AFTER_SEALED_END)                    # and the run itself joins over the whole log
        self.assertEqual(code, 0, err)
        self.assertIn("  n units 1 (blocks with a live row 1; dropped none)", out)

    def test_the_clock_refuses_at_end_minus_one_minute_and_lifts_at_the_end(self):
        stopped = self._write([r for r in _end_rows() if report.tick_epoch(r["tick_id"]) < END])
        full = self._write(_end_rows())
        args = ["--sample", "--t0", T0S, "--resamples", "20", "--exclusions", self.ex]
        with mock.patch.object(outcomes, "load", side_effect=AssertionError("the log was opened")):
            code, out, err = _main(args + ["--log", full, "--now", "2026-10-21T09:59"], now=AFTER_SEALED_END)
        self.assertEqual((code, out), (3, ""))
        self.assertIn("refusing to look: the sample ends 2026-10-21T10:00Z and it is 2026-10-21T09:59Z", err)
        code, out, err = _main(args + ["--log", full, "--now", "2026-10-21T10:00"], now=AFTER_SEALED_END)                    # the log has the t + h rows
        self.assertEqual(code, 0, err)
        code, out, err = _main(args + ["--log", stopped, "--now", "2026-10-21T10:00"], now=AFTER_SEALED_END)                 # it does not: refused ...
        self.assertEqual(code, 3, err)
        code, out, err = _main(args + ["--log", stopped, "--now", "2026-10-21T10:00", "--accept-pending"], now=AFTER_SEALED_END)   # ... unless it stopped
        self.assertEqual(code, 0, err)


class Robustness(unittest.TestCase):
    """What the run prints about its own inputs, and the inputs that must stop it cleanly."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.log = os.path.join(cls.tmp, "edge.jsonl")
        _write(cls.log, _edge_rows(blocks=4))                        # with a torn last line, as a crash leaves it
        cls.ex = _exclusions(os.path.join(cls.tmp, "ex.tsv"), [9])

    def _run(self, *extra, log=None, ex=None):
        argv = ["--sample", "--log", log or self.log, "--t0", T0S, "--now", "2026-10-21T10:00", "--resamples", "20"]
        return _main(argv + (["--exclusions", ex] if ex else []) + list(extra))

    def test_the_exclusions_path_read_is_printed_and_a_missing_one_given_explicitly_stops_the_run(self):
        code, out, err = self._run(ex=self.ex)
        self.assertEqual(code, 0, err)
        self.assertIn(f"excluded [9] ({self.ex}, reproduced below)", out)
        self.assertIn(f"{self.ex}, verbatim:\n  d09\t50.0%\t0.0%\tx\n", out)
        missing = os.path.join(self.tmp, "no-such.tsv")
        code, out, err = self._run(ex=missing)
        self.assertEqual((code, out), (2, ""))
        self.assertIn(f"no exclusions file at {missing}", err)
        data = tempfile.mkdtemp()                                    # the default may be absent: that is no exclusions
        self.addCleanup(shutil.rmtree, data, ignore_errors=True)
        with mock.patch.object(inference.config, "DATA", data):
            code, out, err = self._run()
        self.assertEqual(code, 0, err)
        self.assertIn(f"excluded none ({os.path.join(data, 'exclusions.tsv')}, reproduced below)", out)
        self.assertIn(f"{os.path.join(data, 'exclusions.tsv')}: absent or empty", out)

    def test_the_sha_is_of_the_bytes_the_rows_came_from_and_a_later_copy_can_be_checked(self):
        with open(self.log, "rb") as fh:
            before = fh.read()
        path = os.path.join(self.tmp, "growing.jsonl")
        with open(path, "wb") as fh:
            fh.write(before)
        real = outcomes.load

        def appending(p, bad=None):                                  # launchd writes a row between the read and the parse
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("\n" + json.dumps(_at(T0 + 3 * 86400)) + "\n")
            return real(p, bad)

        with mock.patch.object(outcomes, "load", appending):
            code, out, err = self._run(log=path, ex=self.ex)
        self.assertEqual(code, 0, err)
        sha = hashlib.sha256(before).hexdigest()
        self.assertIn(f"  log {path}: {len(before)} bytes, sha256 {sha}, last tick_id 20260923T110100Z"
                      f" (a later copy: head -c {len(before)} FILE | shasum -a 256); skipped lines 1; rows in scope 62\n", out)
        with open(path, "rb") as fh:
            later = fh.read()
        self.assertGreater(len(later), len(before))
        self.assertEqual(hashlib.sha256(later[:len(before)]).hexdigest(), sha)       # head -c N of the later copy
        rows, bad, sha2, n = inference.read_log(self.log)
        self.assertEqual((sha2, n), (sha, len(before)))
        want_bad = []
        self.assertEqual(rows, outcomes.load(self.log, want_bad))   # skipped exactly as outcomes.load skips
        self.assertEqual(bad, want_bad)
        self.assertEqual(len(bad), 1)

    def test_the_header_says_which_python_ran(self):
        code, out, err = self._run(ex=self.ex)
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines()[1], f"  python {' '.join(sys.version.split())}")

    def test_out_is_a_new_file_and_an_existing_one_is_never_overwritten(self):
        new = os.path.join(self.tmp, "RESULTS-new.md")
        code, out, err = self._run("--out", new, ex=self.ex)
        self.assertEqual(code, 0, err)
        with open(new, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), out)
        old = os.path.join(self.tmp, "RESULTS-old.md")
        with open(old, "w", encoding="utf-8") as fh:
            fh.write("the committed result\n")
        with mock.patch.object(inference, "h1", side_effect=AssertionError("computed before refusing")):
            code, out, err = self._run("--out", old, ex=self.ex)
        self.assertEqual((code, out), (2, ""))
        self.assertIn(f"--out {old} exists; refusing to overwrite it", err)
        with open(old, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "the committed result\n")
        late = os.path.join(self.tmp, "RESULTS-late.md")               # a file that appears while the bootstrap runs
        real = inference.render

        def render_then_appear(*a, **k):
            with open(late, "w", encoding="utf-8") as fh:
                fh.write("written meanwhile\n")
            return real(*a, **k)

        with mock.patch.object(inference, "render", render_then_appear):
            code, out, err = self._run("--out", late, ex=self.ex)
        self.assertEqual(code, 2)
        self.assertIn(f"--out {late} appeared during the run; refusing to overwrite it", err)
        with open(late, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "written meanwhile\n")

    def test_a_missing_log_is_said_so_not_a_traceback(self):
        missing = os.path.join(self.tmp, "no-such.jsonl")
        for mode in (["--sample"], ["--pre-t0"]):
            code, out, err = _main(mode + ["--log", missing, "--t0", T0S, "--now", "2026-10-21T10:00", "--exclusions", self.ex])
            self.assertEqual((code, out, err), (2, "", f"inference: no log at {missing}\n"), mode)

    def test_pre_t0_with_no_row_before_the_cut_prints_no_blocks_and_no_units(self):
        code, out, err = _main(["--pre-t0", "--log", self.log, "--t0", T0S, "--resamples", "20", "--exclusions", self.ex])   # every row is at or after T0
        self.assertEqual(code, 0, err)
        self.assertIn("rows in scope 0\n", out)
        self.assertIn("    n blocks 0; mean S_k n/a bps; lower bound n/a bps -> no blocks: nothing to test", out)
        self.assertIn("disagreement blocks 0 (n/a)", out)
        self.assertIn("  n units 0 (blocks with a live row 0; dropped none): no units:", out)
        self.assertNotIn("not rejected", out)
        self.assertIn("  H2 (§9): no units:", out)

    def test_one_unit_is_fewer_than_two_not_no_variance(self):
        rows = _minutes(T0, T0 + 900, up=0.6, down=0.4) + [_at(T0 + 900 + 60 * m, mode="dry", mid=101.0) for m in (0, 1)]
        path = os.path.join(self.tmp, "one-unit.jsonl")
        _write(path, rows, garbage=False)
        code, out, err = self._run(log=path, ex=self.ex)
        self.assertEqual(code, 0, err)
        self.assertIn("  n units 1 (blocks with a live row 1; dropped none): not supported: fewer than 2 units (n 1): r is undefined", out)
        self.assertNotIn("no variance", [l for l in out.splitlines() if l.startswith("  n units ")][0])

    def test_a_run_of_unpriced_rows_longer_than_the_horizon_is_a_gap_block(self):
        def unpriced(e):
            r = _at(e, absence="feed")
            r.update(bid=None, ask=None, mid=None, answers=None, columns={"a": None, "b": None})
            return r

        for hole, want in ((21, 1), (15, 1), (14, 0)):               # minutes without a price after minute 9: > 900 s is 15 or more
            rows = ([_at(T0 + 60 * m, mid=100.0 + m / 10, b="buy" if m == 0 else "hold") for m in range(10)]
                    + [unpriced(T0 + 60 * m) for m in range(10, 10 + hole)]
                    + [_at(T0 + 60 * m, mid=101.0) for m in range(10 + hole, 45)])
            path = os.path.join(self.tmp, f"hole{hole}.jsonl")
            _write(path, rows, garbage=False)
            loaded = outcomes.load(path, [])
            s = inference.h1_series(report.in_sample(loaded, T0), outcomes.join(loaded), "b", "c", T0)
            self.assertEqual(s["gap_blocks"], want, hole)            # every minute has a row, so only the price shows the gap


if __name__ == "__main__":
    unittest.main()

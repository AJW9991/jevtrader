"""loop/inference.py: behaviours a mutation run of the module showed no other test holding. Each
test pins one documented rule (the comment above it names where it is written) on the smallest
synthetic log that shows it: the empty series, the day bounds of data/exclusions.tsv, the block of
a block's last minute, H1's and H2's descriptive counts, the pending-unit guard at its edges, the
printed verdicts, and main's argument and clock guards at their boundaries. Every run reads a
temporary log with config.DATA and config.DECISIONS pointed into a temporary directory."""
import contextlib, datetime, io, os, tempfile, unittest
from unittest import mock

from loop import inference, outcomes, report
from test_inference import AFTER_SEALED_END, END, T0, T0S, _at, _edge_rows, _end_rows, _exclusions, _minutes
from test_report import _write

NOW = "2026-10-21T10:00"                                             # the synthetic sample's end (T0S + 28 d)
SEALED = report._t0("2026-09-25T21:40")                               # PREREG §11's T0, the repository's seal


def setUpModule():
    global TMP, _tmpdir
    _tmpdir = tempfile.TemporaryDirectory()
    TMP = _tmpdir.name


def tearDownModule():
    _tmpdir.cleanup()


def _path(name):
    return os.path.join(TMP, name)


def _log(name, rows):
    path = _path(name)
    _write(path, rows, garbage=False)
    return path


def _load(rows):
    """rows written and read back as the run reads them: (rows, outcomes over the whole log)."""
    path = _log(f"load-{len(os.listdir(TMP))}.jsonl", rows)
    loaded = outcomes.load(path, [])
    return loaded, outcomes.join(loaded)


def _tick(epoch):
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _unpriced(epoch, **kw):
    """A feed-outage row at `epoch`: logged, no bid, ask or mid, no answers (not live)."""
    r = _at(epoch, absence="feed", **kw)
    r.update(bid=None, ask=None, mid=None, answers=None, columns={"a": None, "b": None})
    return r


def _run(argv, now=AFTER_SEALED_END, decisions=None):
    """inference.main with its output captured and config.DATA / config.DECISIONS in a temporary
    directory, so no run reads or stats the live data/."""
    data = tempfile.mkdtemp(dir=TMP)
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(inference.config, "DATA", data), \
            mock.patch.object(inference.config, "DECISIONS", decisions or os.path.join(data, "decisions.jsonl")), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = inference.main(argv, now=now)
        except SystemExit as e:                                      # argparse's ap.error: exit 2 with a usage line
            code = e.code
    return code, out.getvalue(), err.getvalue()


def _verdicts(out):
    """{pair: the printed line under its title} for H1's three pairs, and "H2": H2's statistic line."""
    lines = out.splitlines()
    got = {}
    for pair in ("B - C", "A - C", "B - A"):
        i = next(i for i, l in enumerate(lines) if l.startswith(f"  {pair}: "))
        got[pair] = lines[i + 1]
    got["H2"] = next(l for l in lines if l.startswith("  n units "))
    return got


class EmptyAndOneBlockSeries(unittest.TestCase):
    # bootstrap's docstring and PREREG §4: the lower bound is a sorted resample; with no block there is no resample and no bound
    def test_an_empty_series_is_not_bootstrapped_and_has_no_lower_bound(self):
        self.assertEqual(inference.bootstrap([], inference.mean, resamples=20), {"n": 0, "lower": None, "reject": False, "sorted": []})

    # PREREG §4: the circular block bootstrap of the block series, whatever its length; one block resamples to itself
    def test_a_one_block_series_is_bootstrapped(self):
        b = inference.bootstrap([2.5], inference.mean, resamples=20)
        self.assertEqual((b["n"], b["lower"], b["reject"], b["sorted"]), (1, 2.5, True, [2.5] * 20))

    # bootstrap's docstring and PREREG §4: no block, no resample, so every pair prints its lower bound as n/a, never 0.0000
    def test_every_day_excluded_prints_no_lower_bound_for_any_pair(self):
        log = _log("edge-all-excluded.jsonl", _edge_rows(blocks=2))
        ex = _exclusions(_path("all28.tsv"), range(1, 29))
        code, out, err = _run(["--sample", "--log", log, "--t0", T0S, "--now", NOW, "--resamples", "20", "--exclusions", ex])
        self.assertEqual(code, 0, err)
        want = "    n blocks 0; mean S_k n/a bps; lower bound n/a bps -> VOID: no blocks: nothing to test"
        self.assertEqual(sorted(_verdicts(out)[p] for p in ("B - C", "A - C", "B - A")), [want] * 3)


class Exclusions(unittest.TestCase):
    def _read(self, day):
        p = _path(f"ex-{day}.tsv")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(f"day\tfill%\tjev-err%\treason\n{day}\t50.0%\t0.0%\tx\n")
        return inference.read_exclusions(p)

    # read_exclusions' docstring and PREREG §8.3: a day is d01 .. d28, so the sample's last day can be excluded
    def test_day_28_can_be_excluded(self):
        self.assertEqual(self._read("d28")[0], {28})
        self.assertEqual(self._read("28")[0], {28})

    # read_exclusions' docstring: a day outside 1..28 is an error; d00 names no T0-anchored day
    def test_day_zero_is_refused(self):
        for day in ("d00", "0", "00"):
            with self.assertRaises(ValueError, msg=day):
                self._read(day)

    # read_exclusions' docstring: the day is dNN or NN; the d is read in either case (D02 is day 2)
    def test_an_uppercase_d_names_the_same_day(self):
        self.assertEqual(self._read("D02"), ({2}, ["D02\t50.0%\t0.0%\tx"]))


class KeptTick(unittest.TestCase):
    # PREREG §3: block k holds T0 + 900k <= tick_id < T0 + 900(k + 1), so a block's last minute stays in its block and day
    def test_the_last_minute_of_a_day_and_of_the_sample_are_kept(self):
        self.assertTrue(inference.kept_tick(_tick(T0 + 86400 - 60), T0, {2}))    # d01's last minute, d02 excluded
        self.assertFalse(inference.kept_tick(_tick(T0 + 86400), T0, {2}))        # d02's first minute
        self.assertTrue(inference.kept_tick(_tick(END - 60), T0))                 # the sample's last minute
        self.assertFalse(inference.kept_tick(_tick(END), T0))


class H1Descriptive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # block 0: B buys at minute 0 and sells at minute 14 while C holds (B and C on different sides
        # all block); block 1: every arm holds (they agree on every row); block 2: two dry rows
        rows = [_at(T0 + 60 * m, mid=round(100.0 + 0.1 * m, 6), b="buy" if m == 0 else "sell" if m == 14 else "hold") for m in range(15)]
        rows += [_at(T0 + 60 * m, mid=round(101.0 + 0.05 * (m - 15), 6)) for m in range(15, 30)]
        rows += [_at(T0 + 1800 + 60 * m, mid=102.0, mode="dry") for m in (0, 1)]
        cls.rows, cls.outs = _load(rows)

    # PREREG §4: disagreement blocks are the blocks holding a tick where B and C are on different sides, and the mean is over those blocks only
    def test_disagreement_blocks_are_the_blocks_where_the_arms_are_on_different_sides(self):
        s = inference.h1_series(self.rows, self.outs, "b", "c", T0, n_blocks=3)
        self.assertGreater(s["series"][0][1], 0.0)
        self.assertEqual([v for _, v in s["series"][1:]], [0.0, 0.0])
        self.assertEqual((s["dis_blocks"], s["mean_dis"]), (1, s["series"][0][1]))

    # PREREG §4 (trades/day each side) and h1_series' docstring: days = blocks / 96, a fraction of a day on --pre-t0's short span
    def test_days_is_the_blocks_over_96_even_on_a_span_shorter_than_a_day(self):
        self.assertEqual(inference.h1_series(self.rows, self.outs, "b", "c", T0, n_blocks=3)["days"], 3 / 96)

    # PREREG §4: reject iff the 2.5th percentile of the resampled means is > 0; h1 reports that bound for B - C and A - C
    def test_h1_lower_bound_is_the_bootstrap_of_its_block_series(self):
        got = {h["pair"]: h for h in inference.h1(self.rows, self.outs, T0, resamples=50, n_blocks=3)}
        for x, y in (("b", "c"), ("a", "c")):
            s = inference.h1_series(self.rows, self.outs, x, y, T0, n_blocks=3)["S"]
            want = inference.bootstrap(s, inference.mean, resamples=50)
            h = got[f"{x.upper()} - {y.upper()}"]
            self.assertIsNotNone(h["lower"])
            self.assertEqual((h["lower"], h["reject"]), (want["lower"], want["reject"]), (x, y))
        self.assertGreater(got["B - C"]["lower"], 0.0)

    # h1_series' comment: "priced" is book.replay's own test, bid, ask and mid all usable; a mid alone is an unpriced row
    def test_a_row_with_a_mid_but_no_bid_or_ask_is_part_of_a_gap(self):
        def mid_only(e):
            r = _at(e, absence="feed")
            r.update(bid=None, ask=None, answers=None, columns={"a": None, "b": None})
            return r

        rows = ([_at(T0 + 60 * m, mid=100.0 + m / 10) for m in range(5)] + [mid_only(T0 + 60 * m) for m in range(5, 26)]
                + [_at(T0 + 60 * m, mid=101.0) for m in range(26, 40)])      # 22 minutes between priced rows 4 and 26
        loaded, outs = _load(rows)
        self.assertEqual(inference.h1_series(loaded, outs, "b", "c", T0)["gap_blocks"], 1)


class H2Descriptive(unittest.TestCase):
    # PREREG §5 (reported beside it): r and rho on every live tick; h2's docstring: every kept live tick with an outcome, the rest counted by reason
    def test_every_tick_numbers_count_each_live_tick_once_by_what_it_gave(self):
        # 30 live minutes: minute 3 misses up15 (noul), minutes 15 .. 29 have no t + h in the log (gap), 14 pairs
        rows = _minutes(T0, T0 + 30 * 60, up=lambda e: None if e == T0 + 180 else 0.5 + 0.01 * ((e // 60) % 5),
                        mid=lambda e: 100.0 + ((e // 60) % 7) * 0.03)
        loaded, outs = _load(rows)
        h = inference.h2(loaded, outs, T0, resamples=20, n_blocks=2)
        self.assertEqual(h["side_every"]["n"], 14)
        self.assertEqual(h["dropped_every"], {"gap": 15, "noul": 1})

    # PREREG §5 degenerate cases: only EVERY lean equal (or every return equal) is "no variance"; two distinct leans are tested
    def test_two_distinct_leans_are_bootstrapped_not_degenerate(self):
        rows = []
        for j in range(8):
            rows += _minutes(T0 + 900 * j, T0 + 900 * (j + 1), mid=100.0 + (j % 3) * 0.2 + j * 0.01, up=0.6 if j % 2 else 0.5, down=0.4)
        rows += [_at(T0 + 900 * 8 + 60 * m, mid=101.0, mode="dry") for m in (0, 1)]
        loaded, outs = _load(rows)
        h = inference.h2(report.in_sample(loaded, T0), outs, T0, resamples=20)
        self.assertEqual(len({x for _, x, _ in h["units"]}), 2)
        self.assertIsNone(h["degenerate"])
        ps = [(x, y) for _, x, y in h["units"]]
        self.assertEqual(h["lower"], inference.bootstrap(ps, inference.pearson_pairs, resamples=20)["lower"])
        self.assertIsNotNone(h["lower"])


class PendingUnits(unittest.TestCase):
    def _pending(self, rows):
        loaded, outs = _load(rows)
        return inference.pending_units(loaded, report.in_sample(loaded, T0), outs, T0)

    # pending_units' docstring: it returns a list of (tick_id, epoch); a log with no row has none
    def test_an_empty_log_has_an_empty_list_of_pending_units(self):
        self.assertEqual(inference.pending_units([], [], {}, T0), [])

    # module docstring: --sample refuses while ANY kept block's first live row has a gap outcome whose t + h the log has not reached, block 0 included
    def test_block_0_waits_for_its_t_plus_h_like_any_block(self):
        got = self._pending(_minutes(T0, T0 + 600))                      # the log stopped 10 minutes after T0
        self.assertEqual([t for t, _ in got], [_tick(T0)])
        self.assertAlmostEqual(got[0][1], T0 + 930.1, places=4)          # ts_rx 10:00:00.1 + 900 + 30

    # pending_units' docstring: pending while t + h + JOIN_TOL_S is LATER than the log's last ts_rx (SPEC §11: the window's edges are inclusive)
    def test_a_log_whose_last_row_is_at_the_window_end_has_reached_it(self):
        rows = [_at(T0 + 60 * m, ts=0.5) for m in range(10)] + [_unpriced(T0 + 900, ts=30.5)]   # 10:00:00.5 + 930 s = 10:15:30.5
        loaded, outs = _load(rows)
        self.assertEqual(outcomes.ts_epoch(loaded[0]["ts_rx"]) + 900 + outcomes.JOIN_TOL_S, outcomes.ts_epoch(loaded[-1]["ts_rx"]))
        self.assertEqual(report._h2_pair(loaded[0], outs), "gap")
        self.assertEqual(inference.pending_units(loaded, report.in_sample(loaded, T0), outs, T0), [])

    # pending_units' docstring: compared with the LAST ts_rx of the whole log, so a gap the log has long passed is a gap, not pending
    def test_a_gap_the_log_has_moved_past_is_not_pending(self):
        live = [_at(T0 + 60 * m, mid=100.0 + m / 100) for m in range(45) if m != 15]   # block 0's t + h (minute 15) is missing
        dry = [_at(T0 + 60 * m, mid=100.5, mode="dry") for m in range(45, 62)]
        loaded, outs = _load(live + dry)
        self.assertEqual(report._h2_pair(loaded[0], outs), "gap")
        self.assertEqual(inference.pending_units(loaded, report.in_sample(loaded, T0), outs, T0), [])

    # pending_units' docstring: only a first row whose pair is "gap" can wait; one that has its outcome is final (SPEC §11: one row in the window)
    def test_a_unit_that_has_its_outcome_is_not_pending(self):
        rows = [_at(T0 + 60 * m, mid=100.0 + m / 100) for m in range(15)] + [_at(T0 + 900, mid=100.5, mode="dry")]
        loaded, outs = _load(rows)
        self.assertIsInstance(report._h2_pair(loaded[0], outs), dict)
        self.assertEqual(inference.pending_units(loaded, report.in_sample(loaded, T0), outs, T0), [])

    # module docstring and PREREG §5: the join is over the whole log, so the last ts_rx is the whole log's, rows after the sample's end included
    def test_the_run_reads_the_last_row_of_the_whole_log_not_of_the_sample(self):
        log = _log("end-no-1000.jsonl", [r for r in _end_rows() if r["tick_id"] != _tick(END)])   # block 2687's t + h row missing
        ex = _exclusions(_path("none-pending.tsv"))
        code, out, err = _run(["--sample", "--log", log, "--t0", T0S, "--now", NOW, "--resamples", "20", "--exclusions", ex])
        self.assertEqual(code, 0, err)
        self.assertIn("dropped {'gap': 1}", out)
        self.assertNotIn("--accept-pending", out)


class ReadLog(unittest.TestCase):
    # read_log's docstring: the rows are parsed from a private copy of the bytes read; the copy is the run's scratch and does not outlive it
    def test_the_private_copy_of_the_log_is_removed(self):
        log = _log("tiny.jsonl", _minutes(T0, T0 + 180))
        scratch = tempfile.mkdtemp(dir=TMP)
        with mock.patch.object(tempfile, "tempdir", scratch):
            rows, bad, _, _ = inference.read_log(log)
        self.assertEqual((len(rows), bad), (3, []))
        self.assertEqual(os.listdir(scratch), [])


class DayLines(unittest.TestCase):
    # day_lines: "no kept day" is said when no day is kept, and only then
    def test_no_kept_day_is_said_only_when_there_is_none(self):
        self.assertEqual(inference.day_lines({})[1:], ["  no kept day"])
        self.assertNotIn("  no kept day", inference.day_lines({1: [3, 3], 2: [0, 0]}))

    # day_lines' docstring: the flag is for a kept day with no live row at all (fill 0/0); a day with live rows and no unit has a fill
    def test_a_day_with_live_rows_and_no_unit_is_not_flagged(self):
        lines = inference.day_lines({1: [2, 0], 2: [0, 0]})
        self.assertIn("  d01   2/96 blocks   0 units", lines)
        self.assertIn(f"  d02   0/96 blocks   0 units  {inference.NO_LIVE_ROWS}", lines)


class PrintedVerdicts(unittest.TestCase):
    """The day-28 text: each pair's verdict as its bootstrap decided it, H2's too, and what a void or a
    pre-T0 run says about itself."""

    @classmethod
    def setUpClass(cls):
        cls.none = _exclusions(_path("none-verdicts.tsv"))
        cls.edge = _log("edge.jsonl", _edge_rows())                          # B beats C, lean tracks the return
        cls.flat = _log("flat.jsonl", _edge_rows(b_trades=False, lean_step=0.01))   # every arm holds, lean runs against it
        cls.runs = {name: _run(["--sample", "--log", log, "--t0", T0S, "--now", NOW, "--resamples", "40", "--exclusions", cls.none])
                    for name, log in (("edge", cls.edge), ("flat", cls.flat))}

    def setUp(self):
        self.out = {}
        for name, (code, out, err) in self.runs.items():
            self.assertEqual(code, 0, err)
            self.out[name] = out

    # PREREG §4 and §8.2: B - C and A - C print the bootstrap's verdict, B - A is a point estimate and never tested
    def test_h1_pairs_print_reject_not_rejected_or_point_estimate_as_computed(self):
        edge, flat = _verdicts(self.out["edge"]), _verdicts(self.out["flat"])
        self.assertIn("  stop rule 1: B-C reject=True, A-C reject=False -> does not fire", self.out["edge"].splitlines())
        self.assertTrue(edge["B - C"].endswith(" bps -> REJECT H0: the arm beats the other"), edge["B - C"])
        self.assertTrue(edge["A - C"].endswith(" bps -> not rejected"), edge["A - C"])
        self.assertTrue(edge["B - A"].endswith("lower bound n/a bps -> no test (point estimate)"), edge["B - A"])
        self.assertTrue(flat["B - C"].endswith(" bps -> not rejected"), flat["B - C"])

    # PREREG §5: H0 r <= 0 is rejected iff the 2.5th percentile of the resampled r is > 0, and the printed verdict says which
    def test_h2_prints_the_verdict_its_bootstrap_gave(self):
        edge, flat = _verdicts(self.out["edge"])["H2"], _verdicts(self.out["flat"])["H2"]
        self.assertTrue(edge.endswith(" -> REJECT H0: r > 0"), edge)
        self.assertTrue(flat.endswith(" -> not rejected"), flat)
        self.assertIn("H2 reject=True", self.out["edge"])
        self.assertIn("H2 reject=False", self.out["flat"])

    # reading's docstring and PREREG §2: the PRE-T0 disclaimer belongs to the smoke; the sample's reading does not carry it
    def test_the_pre_t0_disclaimer_is_in_the_smoke_and_not_in_the_sample(self):
        line = "  PRE-T0: a smoke of the procedure; no stop rule and no reading applies before T0"
        self.assertNotIn(line, self.out["edge"].splitlines())
        code, out, err = _run(["--pre-t0", "--log", self.edge, "--t0", "2026-09-24T10:00", "--resamples", "20", "--exclusions", self.none])
        self.assertEqual(code, 0, err)
        self.assertIn(line, out.splitlines())

    # PREREG §8.3: fewer than 21 kept days is void and reported as void, in the header before any number
    def test_a_void_block_says_so_in_the_header(self):
        eight = _exclusions(_path("eight.tsv"), range(2, 10))                 # 20 days kept
        code, out, err = _run(["--sample", "--log", self.edge, "--t0", T0S, "--now", NOW, "--resamples", "20", "--exclusions", eight])
        self.assertEqual(code, 0, err)
        header = out.split("\n\n")[0].splitlines()
        self.assertIn("  VOID (PREREG §8.3): fewer than 21 days kept; reported as void, a second block is a new pre-registration;"
                      " every verdict below is prefixed VOID and the stop rules are not read", header)


class EmptyLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.log = _path("empty.jsonl")
        open(cls.log, "w", encoding="utf-8").close()
        cls.none = _exclusions(_path("none-empty.tsv"))

    def _run(self):
        code, out, err = _run(["--sample", "--log", self.log, "--t0", T0S, "--now", NOW, "--resamples", "20",
                               "--exclusions", self.none, "--accept-pending"])
        self.assertEqual(code, 0, err)
        return out

    # module docstring: the header carries the last tick_id of the bytes read; a log with no row has none ("-") and still runs
    def test_an_empty_log_runs_and_its_last_tick_is_a_dash(self):
        out = self._run()
        self.assertIn(f"  log {self.log}: 0 bytes, sha256 ", out)
        self.assertIn(", last tick_id - (a later copy: head -c 0 FILE", out)

    # module docstring: --accept-pending is said in the header, with the units it overrode listed, none when there are none
    def test_accept_pending_with_nothing_pending_says_zero_and_lists_nothing(self):
        self.assertIn("  --accept-pending given: 0 H2 unit(s) whose t + h the log has not reached are counted as gaps"
                      " (for a log that really stopped; without the flag the run is refused)", self._run().splitlines())


class MainGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.none = _exclusions(_path("none-main.tsv"))
        cls.small = _log("small.jsonl", _edge_rows(blocks=4))

    # --resamples' help and alpha_rank: a positive count; zero is refused as an argument error, before the log is read
    def test_zero_resamples_is_an_argument_error_before_the_log_is_read(self):
        with mock.patch.object(inference, "read_log", side_effect=AssertionError("the log was read")):
            code, out, err = _run(["--sample", "--log", self.small, "--t0", T0S, "--now", NOW, "--resamples", "0", "--exclusions", self.none])
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--resamples wants a positive count, got 0", err)

    # alpha_rank's docstring: ceil(0.025 R) - 1 at any R >= 1, so one resample is a valid (test) run reading sorted[0]
    def test_one_resample_is_accepted(self):
        code, out, err = _run(["--pre-t0", "--log", self.small, "--t0", "2026-09-24T10:00", "--resamples", "1", "--exclusions", self.none])
        self.assertEqual(code, 0, err)
        self.assertIn("1 resamples, seed 20260923", out)
        self.assertIn("lower bound = sorted[0]", out)

    # main: with PREREG §11 unsealed and no --t0 there is no T0, and that is an argument error, not a traceback
    def test_an_unsealed_prereg_and_no_t0_is_an_argument_error(self):
        unsealed = _path("PREREG-unsealed.md")
        with open(unsealed, "w", encoding="utf-8") as fh:
            fh.write("# a PREREG with no T0 line\n")
        code, out, err = _run(["--pre-t0", "--log", self.small, "--prereg", unsealed, "--resamples", "20", "--exclusions", self.none])
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no T0: PREREG.md §11 is unsealed and no --t0 given", err)

    # module docstring: a log holding sealed-sample rows refuses --sample until the sample's end, [T0, T0 + 28 d), on the real clock
    def test_the_sealed_copy_guard_holds_to_the_last_second_and_lifts_at_the_end(self):
        log = _log("sealed-copy.jsonl", _minutes(SEALED, SEALED + 20 * 60))
        argv = ["--sample", "--log", log, "--t0", "2026-09-25T21:40", "--now", "2026-10-24T00:00", "--resamples", "20",
                "--exclusions", self.none, "--accept-pending"]
        end = datetime.datetime.fromtimestamp(SEALED + 28 * 86400, datetime.timezone.utc)
        code, out, err = _run(argv, now=end - datetime.timedelta(seconds=1))
        self.assertEqual((code, out), (3, ""), err)
        self.assertIn("holds 20 rows of the sealed sample", err)
        code, out, err = _run(argv, now=end)
        self.assertEqual(code, 0, err)
        self.assertIn("mode sample", out)

    # module docstring: --log RESOLVING to config.DECISIONS is the live log, however it is spelled, even before the file exists
    def test_another_spelling_of_the_live_log_path_is_the_live_log(self):
        nodata = tempfile.mkdtemp(dir=TMP)
        decisions = os.path.join(nodata, "decisions.jsonl")                  # not written yet
        code, out, err = _run(["--sample", "--log", os.path.join(nodata, ".", "decisions.jsonl"), "--now", "2026-10-24T00:00",
                               "--exclusions", self.none], decisions=decisions)
        self.assertEqual((code, out), (3, ""), err)
        self.assertIn("refusing: --now 2026-10-24T00:00 overrides the clock", err)

    # render and main: exclusions name sample days; none apply before T0, so --pre-t0 keeps every block of the shakedown's span
    def test_pre_t0_does_not_apply_the_exclusions_file(self):
        d01 = _exclusions(_path("d01.tsv"), [1])
        code, out, err = _run(["--pre-t0", "--log", self.small, "--t0", "2026-09-24T10:00", "--resamples", "20", "--exclusions", d01])
        self.assertEqual(code, 0, err)
        self.assertIn(f"{d01}: not applied before T0 (exclusions name sample days)", out)
        v = _verdicts(out)
        self.assertEqual({v[p].split(";")[0] for p in ("B - C", "A - C", "B - A")}, {"    n blocks 5"})   # 4 blocks and the dry rows' block
        self.assertTrue(v["H2"].startswith("  n units 4 (blocks with a live row 4;"), v["H2"])

    # module docstring and PREREG §2: --pre-t0 reads the rows before the cut only; no sample row enters the smoke's numbers
    def test_pre_t0_h2_reads_no_row_at_or_after_the_cut(self):
        # 50 rows before T0S and 20 after; the anchor is T0S - 50 min, so the smoke's last block [T0S - 5, T0S + 10) straddles the cut
        log = _log("across-cut.jsonl", _minutes(T0 - 50 * 60, T0 + 20 * 60, up=lambda e: 0.5 + 0.02 * ((e // 60) % 7),
                                                mid=lambda e: 100.0 + ((e // 60) % 11) * 0.03))
        code, out, err = _run(["--pre-t0", "--log", log, "--t0", T0S, "--resamples", "20", "--exclusions", self.none])
        self.assertEqual(code, 0, err)
        self.assertIn("rows in scope 50\n", out)
        self.assertIn(" over 50 rows (dropped: gap 0, missing noul 0)", out)


if __name__ == "__main__":
    unittest.main()

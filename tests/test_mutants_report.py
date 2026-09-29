"""report: boundaries and small rules of loop/report.py that the section tests leave loose, each
held to the document that states it (PREREG §2, §3, §5, §8.3; CONTRACT §4; the module's and the
functions' docstrings). Written against the survivors of a mutation run over loop/report.py
(2026-09-28): each test is the smallest input on which the documented rule and a plausible slip
of the code part. Hand-built rows and outcome dicts, plus test_report's 40-row fixture for the
pair table; offline; config.HALT is patched, so nothing under the live data/ is read."""
import datetime, math, os, statistics, tempfile, unittest
from unittest import mock

from loop import book, config, outcomes, report, rules
from test_report import MINUTES, _row as _fixture_row

T0S = "20260925T214000Z"
T0 = report.tick_epoch(T0S)
DAY = 86400
FILLED = {"mid_h": 100.0, "ret_h_bps": 0.0, "label": "flat", "absence": None}


def _tk(e):
    return report._tick_of(e)


def _at(e, **kw):
    """A live row at epoch e (priced, answered by nothing unless kw says so)."""
    r = {"tick_id": _tk(e), "ts_rx": datetime.datetime.fromtimestamp(e, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.200Z"),
         "mode": "live", "absence": None, "mid": 100.0,
         "jev": {"error": None, "latency_ms": 100, "input_tokens": 1000, "key_path": "file:loop"}}
    r.update(kw)
    return r


def _day(j, n_live, n_filled, n_err=0):
    """n_live live rows on T0-day dNN j, the first n_filled with a non-gap outcome, then n_err jev errors."""
    rows, outs = [], {}
    base = T0 + DAY * (j - 1)
    for i in range(n_live):
        r = _at(base + 60 * i)
        rows.append(r)
        outs[r["tick_id"]] = dict(FILLED) if i < n_filled else dict(outcomes.GAP)
    for i in range(n_err):
        rows.append(_at(base + 60 * (n_live + i), absence="jev", jev={"error": "timeout"}))
    return rows, outs


class StopRule3(unittest.TestCase):
    """report §1's per-day table (days_table)."""

    def test_a_closed_day_at_exactly_95_percent_fill_is_not_bad(self):
        # PREREG §8.3: a day is bad when its fill is < 95 % (19/20 is 95.0 %, not under it)
        rows, outs = _day(1, 20, 19)
        t = report.days_table(rows, outs, T0, T0 + 40 * DAY)
        d = t["days"][0]
        self.assertEqual((d["day"], d["live"], d["filled"], d["fill"]), ("d01", 20, 19, 0.95))
        self.assertEqual((d["open"], d["bad"], d["why"]), (False, False, []))
        self.assertNotIn("d01", t["bad"])

    def test_a_closed_day_at_exactly_5_percent_jev_errors_is_not_bad(self):
        # PREREG §8.3: a day is bad when its Jev error share is > 5 % (1/20 is 5.0 %, not over it)
        rows, outs = _day(1, 19, 19, n_err=1)
        d = report.days_table(rows, outs, T0, T0 + 40 * DAY)["days"][0]
        self.assertEqual((d["day"], d["attempted"], d["errors"], d["jev_err"]), ("d01", 20, 1, 0.05))
        self.assertEqual((d["open"], d["bad"], d["why"]), (False, False, []))

    def test_a_day_with_a_row_still_pending_is_open(self):
        # days_table: a day is open while its last row can still fill, and pend counts the live rows whose
        # t + h the log has not reached; a row in d01's last second (readers keep a tick_id's seconds) is one
        end = T0 + DAY
        r = _at(end - 1)
        d = report.days_table([r], {r["tick_id"]: dict(outcomes.GAP)}, T0, end + 900)["days"][0]
        self.assertEqual((d["day"], d["live"], d["pending"], d["open"], d["bad"]), ("d01", 0, 1, True, False))

    def test_every_day_from_d01_to_the_day_of_last_is_listed(self):
        # days_table docstring: with T0, every day from d01 to the day of `last` is listed, rows or not
        # (day_of: day j = [T0 + 86400(j-1), T0 + 86400 j), so the last second of d01 is still d01)
        def listed(last):
            return [d["day"] for d in report.days_table([], {}, T0, last)["days"]]
        self.assertEqual(listed(T0 + DAY - 1), ["d01"])
        self.assertEqual(listed(T0 + DAY), ["d01", "d02"])
        self.assertEqual(listed(T0 + 2 * DAY + 120), ["d01", "d02", "d03"])

    def test_after_the_sample_a_d28_without_rows_is_listed_and_flagged(self):
        # days_table docstring and CONTRACT §4.1: every day from d01 to the log's last tick (at most d28)
        # is listed, and a closed one with no live row is flagged NO LIVE ROWS and counted in `empty`
        rows, outs = _day(27, 10, 10)
        t = report.days_table(rows, outs, T0, T0 + 28 * DAY + 3600)       # the Mac off on the last day
        self.assertEqual([d["day"] for d in t["days"]], [f"d{j:02d}" for j in range(1, 29)])
        d28 = t["days"][-1]
        self.assertEqual((d28["ticks"], d28["open"], d28["empty"], d28["bad"]), (0, False, True, False))
        self.assertFalse(t["days"][-2]["empty"])                            # d27 has its ten live rows
        self.assertEqual(t["empty"][-1], "d28")
        self.assertIn("d28: fill is 0/0", [l for l in t["lines"] if l.startswith("  NO LIVE ROWS on ")][0])

    def test_days_outside_the_sample_are_never_flagged_no_live_rows(self):
        # days_table: NO LIVE ROWS is for "only a day the exclusions file could name", d01..d28 (PREREG §2, §8.3)
        rows = [_at(T0 - 3600, absence="feed", mid=None), _at(T0 + 28 * DAY + 60, absence="feed", mid=None)]
        t = report.days_table(rows, {}, T0, T0 + 40 * DAY)
        by = {d["day"]: d for d in t["days"]}
        self.assertEqual((by["d00"]["open"], by["d00"]["live"], by["d00"]["empty"]), (False, 0, False))
        self.assertEqual((by["d29"]["open"], by["d29"]["live"], by["d29"]["empty"]), (False, 0, False))
        self.assertEqual(t["empty"], [f"d{j:02d}" for j in range(1, 29)])


class DayLabels(unittest.TestCase):
    def test_the_first_minute_of_the_day_before_t0_is_d00(self):
        # day_of docstring: day j = [T0 + 86400(j-1), T0 + 86400 j); d00 is the day before T0
        self.assertEqual(report.day_of(_tk(T0 - DAY), T0), "d00")
        self.assertEqual(report.day_of(_tk(T0 - DAY - 60), T0), "d-1")
        self.assertEqual(report.day_of(_tk(T0 - 2 * DAY), T0), "d-1")

    def test_a_calendar_label_has_no_span_even_beside_a_t0(self):
        # day_span docstring: the [from, to) of a T0-anchored 'dNN' label; None for a calendar label
        self.assertIsNone(report.day_span("20260925", T0))
        self.assertEqual(report.day_span("d01", T0), (T0S, _tk(T0 + DAY)))


class Health(unittest.TestCase):
    def test_the_first_line_counts_utc_calendar_days(self):
        # day_of docstring: without T0 a day is the UTC calendar day, the first 8 chars of tick_id (CONTRACT §4.1)
        rows = [_at(T0 + DAY * k, mode="dry") for k in range(3)]            # 2026-09-25, -26, -27
        with mock.patch.object(config, "HALT", os.path.join(self.enterContext(tempfile.TemporaryDirectory()), "HALT")):
            h = report.health(rows, outcomes.join(rows))
        self.assertIn("(3 ticks, 3 days, ", h["lines"][0])
        self.assertEqual(len(h["days"]), 3)


class Occupancy(unittest.TestCase):
    def test_alphabet_words_never_count_as_outside_the_alphabet(self):
        # CONTRACT §4.2 and occupancy(): OUTSIDE-ALPHABET counts words the SPEC does not have, loud, never folded
        adj = {"liq": "deep", "flow": "organic", "trend": "flat", "vol": "normal"}   # thin, quiet, ... never occur
        rows = [_at(T0 + 60 * i, adj=dict(adj)) for i in range(4)]
        self.assertEqual([l for l in report.occupancy(rows)["lines"] if "OUTSIDE" in l], [])
        rows.append(_at(T0 + 300, adj=dict(adj, liq="soggy")))
        self.assertIn("OUTSIDE-ALPHABET 1", report.occupancy(rows)["lines"][0])


class Retest(unittest.TestCase):
    def test_a_row_with_one_answer_is_not_a_pair(self):
        # retest docstring and CONTRACT §4.3: a pair is two answers to one question in one request
        one_a = _at(T0, prompt_a_sha="s", prompt_b_sha="s", answers={"a_action": {"choice": "hold", "confidence": 0.9}})
        one_b = _at(T0 + 60, prompt_a_sha="s", prompt_b_sha="s", answers={"b_action": {"choice": "hold", "confidence": 0.9}})
        t = report.retest([one_a, one_b])
        self.assertEqual((t["n"], t["agree"], t["agree_rate"]), (0, 0, None))

    def test_a_pair_missing_one_confidence_still_counts_for_agreement(self):
        # CONTRACT §4.3 agreement of the two choices; a missing confidence is a legal answer (rules.py: read as no signal)
        r = _at(T0, prompt_a_sha="s", prompt_b_sha="s",
                answers={"a_action": {"choice": "hold", "confidence": 0.9}, "b_action": {"choice": "hold"}})
        t = report.retest([r])
        self.assertEqual((t["n"], t["agree"]), (1, 1))


class Answered(unittest.TestCase):
    def test_a_row_with_either_arms_column_is_answered(self):
        # answered() docstring: the rows that carry a model column
        ra = _at(T0, columns={"a": {"argmax": "buy"}, "b": None})
        rb = _at(T0 + 60, columns={"a": None, "b": {"argmax": "hold"}})
        rn = _at(T0 + 120, columns={"a": None, "b": None})
        self.assertEqual(report.answered([ra, rb, rn]), [ra, rb])


class PairTable(unittest.TestCase):
    """report §5 on test_report's 40-row fixture (2026-09-23 10:00..10:41, no --t0)."""

    @classmethod
    def setUpClass(cls):
        cls.rows = [_fixture_row(m) for m in MINUTES]
        cls.outs = outcomes.join(cls.rows)
        cls.tb = report.table(cls.rows, cls.outs)

    def test_every_cell_is_book_paired_on_its_own_column(self):
        # module docstring: d_t is book.paired's own expression, one replay per (arm, column, fee) (CONTRACT §4.5);
        # the v1 fixture prints A, B and C's pairs, and the same rows with a columns.d (A's argmax) add D's two
        v2 = [dict(r, columns=dict(r["columns"], d=(r["columns"].get("a") or {}).get("argmax"))) for r in self.rows]
        for rows, tb, pairs in ((self.rows, self.tb, report.PAIRS[:3]), (v2, report.table(v2, outcomes.join(v2)), report.PAIRS)):
            self.assertEqual(tb["pairs"], pairs)
            for x, y in pairs:
                for fee in (config.FEE_BPS_PRIMARY, config.FEE_BPS_VENUE):
                    for col in report.pair_columns(x, y):
                        self.assertEqual(dict(tb["cells"][(x, y, col, fee)]["all"]["d"]),
                                         dict(book.paired(rows, outcomes.join(rows), x, y, col, fee)), (x, y, col, fee))

    def test_the_legend_counts_trades_per_1440_ticks(self):
        # CONTRACT §4.5 trades/day each side; TICKS_PER_DAY: trades/day is per 1440 ticks
        self.assertIn("tr/d = trades per 1440 ticks", "\n".join(self.tb["lines"]))

    def test_the_per_arm_equity_is_the_replays_last_mark(self):
        # CONTRACT §4.5: the per-arm line at the primary and at the venue fee is each arm's replayed equity
        rows = [_fixture_row(m) for m in range(5, 20)]                      # every arm long from m 10 on
        for r in rows:                                                      # D (PREREG-v2) reads A's argmax as its table
            r["columns"] = dict(r["columns"], d=(r["columns"]["a"] or {}).get("argmax"))
        rows[-1].update(bid=101.99, ask=102.01, mid=102.0)                 # and the last tick moves the mark
        outs = outcomes.join(rows)
        tb = report.table(rows, outs)
        for fee, per in ((config.FEE_BPS_PRIMARY, tb["per_arm"]), (config.FEE_BPS_VENUE, tb["per_arm_venue"])):
            for arm in report.ARMS:
                eq = book.replay(rows, outs, arm, "argmax", fee)["equity"]
                self.assertNotEqual(eq[-1][1], eq[-2][1], (arm, fee))        # the witness: the last tick carries pnl
                self.assertEqual(per[arm]["equity"], eq[-1][1], (arm, fee))

    def test_with_no_rows_every_arm_is_flat_at_zero(self):
        # module docstring: an empty log still prints; every arm starts flat (PREREG §3: nothing held is 0.0)
        tb = report.table([], {})
        for per in (tb["per_arm"], tb["per_arm_venue"]):
            self.assertEqual({a: (per[a]["equity"], per[a]["trades"]) for a in tb["arms"]},
                             {a: (0.0, 0) for a in ("a", "b", "c")})

    def test_ticks_before_the_anchor_are_counted_out_and_fill_no_block(self):
        # _blocks docstring: a tick before the anchor is counted in `pre` and left out; n = the block of
        # the log's last tick + 1, and a last tick one minute before the anchor is in block -1
        t0 = report.tick_epoch("20260923T104200Z")
        tb = report.table(self.rows, self.outs, t0, t0 - 60)
        blk = tb["cells"][report.PRIMARY]["blocks"]
        self.assertEqual((blk["n"], blk["pre"], blk["S"], blk["mean"]), (0, len(MINUTES), [], None))


class Blocks(unittest.TestCase):
    def test_no_ticks_make_no_blocks(self):
        # _blocks docstring: n is the block of the last tick in d + 1 (none here); rates of 0 are None, never a crash
        self.assertEqual(report._blocks([], set(), T0),
                         {"n": 0, "dis": 0, "share": None, "mean": None, "mean_dis": None, "S": [], "pre": 0})

    def test_ticks_only_before_the_anchor_make_no_block(self):
        # _blocks docstring: a tick before the anchor is counted in `pre` and left out
        b = report._blocks([(_tk(T0 - 60), 1.0)], set(), T0)
        self.assertEqual((b["n"], b["pre"], b["S"], b["mean"]), (0, 1, [], None))


class Cell(unittest.TestCase):
    def test_hit_is_the_share_of_disagreement_ticks_with_d_above_zero(self):
        # CONTRACT §4.5 hit rate on disagreement ticks; the legend: d_t > 0, a zero is not a hit
        ticks = ["t1", "t2", "t3", "t4", "t5"]
        px = {"equity": [(t, 0.0) for t in ticks], "pnl_bps_per_tick": {"t1": 0.5, "t2": 3.0, "t3": -1.0, "t4": 0.0, "t5": 7.0}}
        py = {"equity": [(t, 0.0) for t in ticks], "pnl_bps_per_tick": {t: 0.0 for t in ticks}}
        c = report._cell(px, py, {"t1", "t2", "t3", "t4"})                  # t5 is not a disagreement tick
        self.assertEqual((c["dis"], c["hit"]), (4, 0.5))


class Sides(unittest.TestCase):
    def test_a_long_of_less_than_one_unit_is_a_side(self):
        # _disagreement docstring and SPEC §10: sides are long vs flat; qty = NOTIONAL / ask is under 1 above $1,000
        long_ = {"equity": [("t1", 0.0), ("t2", 0.0)], "position": {"t1": 0.0, "t2": 0.8}}
        flat = {"equity": [("t1", 0.0), ("t2", 0.0)], "position": {"t1": 0.0, "t2": 0.0}}
        self.assertEqual(report._disagreement(long_, flat), {"t2"})
        self.assertEqual(report._disagreement(flat, long_), {"t2"})


class Pearson(unittest.TestCase):
    def test_two_distinct_pairs_define_r(self):
        # pearson docstring and CONTRACT §4.6: undefined only with fewer than two pairs or a constant side
        self.assertAlmostEqual(report.pearson([0.1, 0.3], [5.0, -2.0]), -1.0, places=12)
        self.assertAlmostEqual(report.pearson([0.1, 0.3], [-2.0, 5.0]), 1.0, places=12)

    def test_a_constant_side_is_undefined_even_when_its_float_mean_is_off(self):
        # pearson docstring: constancy is tested on the values; the mean of three 0.1 is not 0.1 in binary
        self.assertIsNone(report.pearson([1.0, 2.0, 3.0], [0.1, 0.1, 0.1]))
        self.assertIsNone(report.pearson([0.1, 0.1, 0.1], [1.0, 2.0, 3.0]))

    def test_r_is_the_centred_two_pass_formula_to_the_last_bit(self):
        # PREREG §5 step 3: every bootstrap r* is "Pearson r ... as loop/report.py::pearson", so its arithmetic is
        # part of the sealed procedure: sum((x - mx)(y - my)) / sqrt(sum((x - mx)^2) sum((y - my)^2))
        for xs, ys in (([0.11, 0.37, 0.52, 0.93, 0.05], [3.3, -1.7, 12.9, 0.4, -8.8]),
                       ([0.03, -0.12, 0.25, 0.31, -0.07, 0.18], [4.25, -9.5, 1.75, 22.0, -3.125, 0.5])):
            n = len(xs)
            mx, my = sum(xs) / n, sum(ys) / n
            sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            sxx = sum((x - mx) ** 2 for x in xs)
            syy = sum((y - my) ** 2 for y in ys)
            self.assertEqual(report.pearson(xs, ys), sxy / math.sqrt(sxx * syy), xs)

    def test_a_variance_lost_to_underflow_is_undefined_not_a_crash(self):
        # CONTRACT §4.6: an r that cannot be computed prints undefined, never a number and never a crash
        self.assertIsNone(report.pearson([0.0, 1e-170], [1.0, 2.0]))        # (x - mx)^2 underflows to 0.0
        self.assertIsNone(report.pearson([1.0, 2.0], [0.0, 1e-170]))

    def test_r_stays_within_minus_one_and_one_and_is_not_clipped_inside(self):
        # pearson docstring: the clamp takes only the last-bit overshoot of a perfect fit; r is Pearson's r
        # perfect fits whose unclamped r lands one bit past +-1 on CPython 3.11 (plain sum) and 3.12+ (compensated)
        for xs, a in (([0.3, 0.6, 0.43], 0.3), ([0.5, 0.17, 0.35], 1.1), ([0.8, 0.1, -0.11], 0.9)):
            for k in (a, -a):
                r = report.pearson(xs, [k * x for x in xs])
                self.assertTrue(-1.0 <= r <= 1.0, (xs, k, r))
                self.assertAlmostEqual(r, math.copysign(1.0, k), places=12)
        xs, ys = [1.0, 2.0, 3.0, 4.0, 5.0], [-1.0, -2.1, -2.9, -4.2, -4.8]     # r = -0.995..., a fit short of perfect
        self.assertAlmostEqual(report.pearson(xs, ys), statistics.correlation(xs, ys), places=12)


class WhyUndefined(unittest.TestCase):
    def test_the_reason_names_the_side_that_is_constant(self):
        # PREREG §5 degenerate cases ("no variance in {lean|ret}") and CONTRACT §4.6: undefined (<reason>)
        self.assertEqual(report._why_undefined([0.1], [5.0]), "fewer than 2 pairs (n 1)")
        self.assertEqual(report._why_undefined([0.1, 0.1], [5.0, -2.0]), "no variance in lean")
        self.assertEqual(report._why_undefined([0.1, 0.2, 0.1], [5.0, 5.0, 5.0]), "no variance in ret_h_bps")

    def test_a_defined_r_has_no_reason(self):
        # CONTRACT §4.6: a reason is printed only where r is undefined
        xs, ys = [0.1, 0.2, 0.3], [5.0, -5.0, 5.0]                          # each side two-valued, r defined
        self.assertIsNotNone(report.pearson(xs, ys))
        self.assertIsNone(report._why_undefined(xs, ys))
        self.assertIsNone(report._corr(xs, ys, "lean", "trend")["why"])


class Lean(unittest.TestCase):
    @staticmethod
    def _lean(up, down):
        r = _at(T0, answers={"up15": {"noul": up}, "down15": {"noul": down}})
        return report._h2_pair(r, {r["tick_id"]: {"absence": None, "ret_h_bps": 5.0, "label": "up", "mid_h": 100.05}})["lean"]

    def test_lean_keeps_12_decimals_and_drops_the_13th(self):
        # PREREG §5: x_k = up15.noul - down15.noul, rounded to 12 decimals
        self.assertEqual(self._lean(0.600000000003, 0.1), 0.500000000003)
        self.assertEqual(self._lean(0.6000000000003, 0.1), 0.5)
        self.assertEqual(self._lean(0.4, 0.3), self._lean(0.3, 0.2))        # PREREG §5's own example


class H2Lines(unittest.TestCase):
    def test_section_6_states_the_lean_range_over_the_units(self):
        # module docstring: each section returns its numbers and its rendered lines from one computation
        nouls = ((0.2, 0.3), (0.4, 0.3), (0.6, 0.3))                        # leans -0.1, 0.1, 0.3, one per block
        rows, outs = [], {}
        for k, (u, d) in enumerate(nouls):
            r = _at(T0 + 900 * k, adj={"trend": "flat"}, answers={"up15": {"noul": u}, "down15": {"noul": d}})
            rows.append(r)
            outs[r["tick_id"]] = {"absence": None, "ret_h_bps": float(k), "label": "flat", "mid_h": 100.0}
        h = report.h2(rows, outs, T0)
        self.assertEqual([p["lean"] for p in h["units"]["pairs"]], [-0.1, 0.1, 0.3])
        self.assertIn("  over the units: lean min -0.10, mean 0.1000, max 0.30; up15 0.20..0.60, down15 0.30..0.30", h["lines"])


class Calibration(unittest.TestCase):
    LABEL = {"absence": None, "label": "flat", "ret_h_bps": 1.0, "mid_h": 100.01}

    def test_a_confidence_under_one_half_is_counted_outside_the_bins(self):
        # CONTRACT §4.7's bins start at 0.5; calibration(): an answer outside them is counted, never hidden
        r = _at(T0, answers={"a_action": {"choice": "hold", "confidence": 0.4}}, columns={"a": {"argmax": "hold"}, "b": None},
                rule_c="hold")
        c = report.calibration([r], {r["tick_id"]: dict(self.LABEL)})
        self.assertEqual((c["n"], c["below"]), (0, 1))
        self.assertIn("0 in bins, 1 outside [0.5, 1.0]", "\n".join(c["lines"]))

    def test_an_answer_without_an_argmax_is_not_scored(self):
        # CONTRACT §4.7 scores a.argmax against the label; a parse refusal logs the answer and no column (cycle.py)
        r = _at(T0, absence="jev", answers={"a_action": {"choice": "short", "confidence": 0.9}},
                columns={"a": None, "b": None}, rule_c="hold")
        c = report.calibration([r], {r["tick_id"]: dict(self.LABEL)})
        self.assertEqual((c["n"], c["below"]), (0, 0))


class SampleBounds(unittest.TestCase):
    def test_a_row_exactly_at_t0_is_a_sample_row_and_is_withheld(self):
        # PREREG §2: the sample is T0 <= tick_id < T0 + 28 d; withheld_until: a sample row withholds §4-§7
        self.assertEqual(report.withheld_until([{"tick_id": T0S}], T0, now=T0 + 30), T0 + 28 * DAY)

    def test_a_row_exactly_at_the_sample_end_is_not_a_sample_row(self):
        # PREREG §2: T0 + 28 d itself is after the sample, so it withholds nothing
        self.assertIsNone(report.withheld_until([{"tick_id": _tk(T0 + 28 * DAY)}], T0, now=T0 + 30))

    def test_the_sample_is_half_open_to_the_second(self):
        # PREREG §2 and in_sample docstring: T0 <= tick_id < T0 + 28 * 86,400 s
        rows = [{"tick_id": _tk(e)} for e in (T0 - 1, T0, T0 + 28 * DAY - 1, T0 + 28 * DAY)]
        self.assertEqual([r["tick_id"] for r in report.in_sample(rows, T0)], [T0S, _tk(T0 + 28 * DAY - 1)])


class TickEpoch(unittest.TestCase):
    def test_a_sign_or_a_space_in_a_digit_field_is_refused(self):
        # tick_epoch docstring: a string of the wrong shape raises ValueError; the shape is outcomes._TICK's,
        # eight digits, T, six digits, Z (int() alone would read '+9', ' 1' or '0 ' as a number)
        for bad in ("2026+925T214000Z", "2026092 T214000Z", "20260925T 14000Z", "20260925T21400 Z"):
            self.assertIsNone(outcomes._TICK.match(bad), bad)
            with self.assertRaises(ValueError, msg=bad):
                report.tick_epoch(bad)


if __name__ == "__main__":
    unittest.main()

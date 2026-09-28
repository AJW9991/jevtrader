"""outcomes, the edges the other tests leave open: which strings a reader's clock can use, which
mids are prices, a naive clock under a zone that is not UTC, whole-millisecond ties, the row that
speaks for a tick, forward-only at a short horizon, and a log reader that survives bytes, values and
glued lines the writer never makes. Each test holds the code to a sentence of SPEC.md, CONTRACT.md or
loop/outcomes.py's docstrings (named in its comment), and was written against a mutant of
loop/outcomes.py that the rest of the suite let through. Offline; temp files only."""
import datetime, json, math, os, tempfile, time, unittest

from loop import config, outcomes, report

T0 = datetime.datetime(2026, 9, 23, 10, 0, 0, tzinfo=datetime.timezone.utc)
H = config.HORIZON_S


def _iso(s):
    d = T0 + datetime.timedelta(seconds=s)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _iso_ms(ms, base=T0):
    d = base + datetime.timedelta(milliseconds=ms)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _row(s, mid, absence=None, mode="live"):
    """A row at T0+s seconds, tick_id its minute."""
    d = T0 + datetime.timedelta(seconds=s)
    return {"v": 1, "tick_id": d.strftime("%Y%m%dT%H%M00Z"), "ts_rx": _iso(s), "mode": mode,
            "venue": "coinbase", "product": "SOL-USD", "cadence_s": 60, "horizon_s": 900,   # outcomes.WRITER_KEYS: every row has them
            "mid": mid, "absence": absence}


def _at(ts_rx, mid):
    """A priced live row at an exact ts_rx string."""
    d = datetime.datetime.fromisoformat(ts_rx)
    return {"v": 1, "tick_id": d.strftime("%Y%m%dT%H%M00Z"), "ts_rx": ts_rx, "mode": "live", "mid": mid, "absence": None}


def _j(r):
    return json.dumps(r, separators=(",", ":"))            # what cycle.write_row writes


class _Log(unittest.TestCase):
    def _log(self, data):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "decisions.jsonl")
        with open(p, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else data.encode())
        self.addCleanup(lambda: (os.remove(p), os.rmdir(d)))
        return p


class ReadersClock(_Log):
    def _read(self, tick_ids):
        good = [_row(0, 100.0), _row(60, 101.0)]
        lines = [_j(good[0])] + [_j(dict(_row(30, 100.5), tick_id=t)) for t in tick_ids] + [_j(good[1])]
        bad = []
        return outcomes.load(self._log("\n".join(lines) + "\n"), bad), bad, good

    def test_a_tick_id_strptime_would_stretch_to_a_minute_is_not_a_row(self):
        # SPEC §2 (tick_id is YYYYMMDDTHHMM00Z) and _not_row: a string that is not a minute would crash every reader's clock
        stretched = ["20260923T10000Z", "20260923T1000Z", "2026923T100000Z"]     # strptime reads each as 10:00:00
        rows, bad, good = self._read(stretched)
        self.assertEqual(rows, good)
        self.assertEqual([report.tick_epoch(r["tick_id"]) for r in rows], [T0.timestamp(), T0.timestamp() + 60])   # the reader's clock reads what is kept
        self.assertEqual([n for n, _ in bad], [2, 3, 4])
        self.assertTrue(all(why.startswith("not a row") for _, why in bad))

    def test_a_tick_id_of_the_right_shape_that_is_no_date_is_not_a_row(self):
        # _tick_ok: the same parse report.tick_epoch does, None when the digits are not a date
        rows, bad, good = self._read(["20261399T000000Z", "20260230T100000Z", "20260923T246000Z", "20260923T100000Z\n"])
        self.assertEqual(rows, good)
        self.assertEqual([n for n, _ in bad], [2, 3, 4, 5])


class Mids(unittest.TestCase):
    def test_a_mid_that_is_not_a_finite_positive_number_is_no_price(self):
        # _num: a mid is a finite positive number; SPEC §11: no mid at t, or no priced row in the window, is a gap
        for bad in (math.inf, -math.inf, math.nan, 0.0, -0.0, 0, -1.0, -0.5, True, False, "101.0", [101.0], None):
            with self.subTest(mid=bad):
                base = _row(0, 100.0)
                self.assertEqual(outcomes.join([base, _row(H, bad)])[base["tick_id"]], outcomes.GAP)      # never a candidate
                self.assertEqual(outcomes.priced_points([base, _row(H, bad)]), ([outcomes.ts_epoch(base["ts_rx"])], [100.0]))
                t = _row(0, bad)
                self.assertEqual(outcomes.join([t, _row(H, 101.0)])[t["tick_id"]], outcomes.GAP)         # never a mid_t

    def test_a_price_below_one_dollar_is_still_a_price(self):
        # _num: any finite positive number is a mid; SPEC §11: ret_h_bps = 1e4 ln(mid_h / mid_t)
        rows = [_row(0, 0.5), _row(H, 0.75)]
        o = outcomes.join(rows)[rows[0]["tick_id"]]
        self.assertEqual((o["mid_h"], o["ret_h_bps"], o["label"], o["absence"]), (0.75, 1e4 * math.log(1.5), "up", None))


@unittest.skipUnless(hasattr(time, "tzset"), "needs time.tzset")
class NaiveClock(unittest.TestCase):
    def test_a_naive_ts_rx_is_utc_whatever_the_machine_zone(self):
        # ts_epoch: a naive string is treated as UTC, never as local time
        old = os.environ.get("TZ")

        def restore():
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()
        self.addCleanup(restore)
        os.environ["TZ"] = "ZZZ+07"                          # a POSIX zone 7 h west of UTC, no tz database needed
        time.tzset()
        self.assertEqual(time.timezone, 7 * 3600)            # the zone took, so the test is not vacuous
        self.assertEqual(outcomes.ts_epoch("2026-09-23T10:00:00"), T0.timestamp())
        self.assertEqual(outcomes.ts_epoch("2026-09-23T10:00:00.250"), outcomes.ts_epoch("2026-09-23T10:00:00.250Z"))


class Ties(unittest.TestCase):
    def test_an_exact_whole_millisecond_tie_goes_to_the_earlier_row(self):
        # SPEC §11: a tie goes to the earlier row; CONTRACT §2: ties are judged in whole milliseconds
        b = _at("2026-09-23T11:08:25.718Z", 100.0)
        e, l = _at("2026-09-23T11:23:24.986Z", 101.0), _at("2026-09-23T11:23:26.450Z", 102.0)   # both 732 ms from t+900
        self.assertEqual(outcomes.join([b, e, l])[b["tick_id"]]["mid_h"], 101.0)
        # and for every ms clock, also past 2**31 s (2038-01-19), where epoch * 1000 can land a hair below the whole
        # millisecond: t anywhere in its minute, two rows the same whole ms either side of t+900
        for base in (T0, datetime.datetime(2038, 2, 1, tzinfo=datetime.timezone.utc)):
            at = lambda ms: outcomes.ts_epoch(_iso_ms(ms, base))
            for t_ms in range(0, 60_000, 997):
                for d_ms in (1, 7, 499, 732, 18_652, 29_999, 30_000):
                    times = [at(t_ms + 900_000 - d_ms), at(t_ms + 900_000 + d_ms)]
                    self.assertEqual(outcomes.pick(times, at(t_ms)), 0, (base, t_ms, d_ms))

    def test_rows_sharing_one_ts_rx_resolve_to_the_first_written(self):
        # CONTRACT §2: ties go to the earlier row; priced_points sorts by time only, so one ts_rx keeps file order
        base = _row(0, 100.0)
        self.assertEqual(outcomes.join([base, _row(H, 103.0), _row(H, 101.0)])[base["tick_id"]]["mid_h"], 103.0)
        self.assertEqual(outcomes.join([base, _row(H, 101.0), _row(H, 103.0)])[base["tick_id"]]["mid_h"], 101.0)


class ForwardOnly(unittest.TestCase):
    def test_the_join_never_takes_the_row_at_t_itself(self):
        # pick and CONTRACT §2: the picked row is strictly after t (module docstring: t sees t+h, never the reverse)
        t = _row(0, 100.0)
        self.assertEqual(outcomes.join([t], 0)[t["tick_id"]], outcomes.GAP)
        self.assertEqual(outcomes.join([t], 20)[t["tick_id"]], outcomes.GAP)          # t lies inside [t+20-30, t+20+30]
        self.assertEqual(outcomes.join([t, _row(10, 101.0)], 0)[t["tick_id"]]["mid_h"], 101.0)
        times, _ = outcomes.priced_points([t])
        self.assertIsNone(outcomes.pick(times, times[0], 0))


class WhoSpeaks(unittest.TestCase):
    def test_only_a_live_row_with_a_null_absence_outranks_the_rest(self):
        # CONTRACT §2 and rank: the live decision (mode live, absence null) speaks for the tick, then any other priced row
        later = [_row(60 * m + 0.2, 100.0 + m) for m in range(1, 21)]
        decision = _row(40.0, 100.5)                              # its t+15 window holds only minute 16's row
        first = {"jev": _row(0.2, 100.0, absence="jev"), "halt": _row(0.2, 100.0, absence="halt"),
                 "guard": _row(0.2, 100.0, absence="guard"), "empty absence": _row(0.2, 100.0, absence=""),
                 "no mode": {k: v for k, v in _row(0.2, 100.0).items() if k != "mode"},
                 "other mode": _row(0.2, 100.0, mode="replay")}
        for name, r in first.items():                             # each written first in the minute, priced, its window on minute 15
            with self.subTest(first=name):
                self.assertEqual((outcomes.rank(r), outcomes.rank(decision)), (1, 0))
                self.assertEqual(outcomes.join([r, decision] + later)[decision["tick_id"]]["mid_h"], 116.0)


class JoinGuards(unittest.TestCase):
    def test_a_priced_row_whose_clock_does_not_parse_is_a_gap_not_a_crash(self):
        # ts_epoch: a bad clock string becomes a gap and never a candidate; join: anything else is the GAP outcome
        later = _row(H, 101.0)
        for ts in ("not a time", None, 1758621600):
            with self.subTest(ts_rx=ts):
                r = {"tick_id": "20260923T100000Z", "ts_rx": ts, "mid": 100.0, "mode": "live", "absence": None}
                self.assertEqual(outcomes.join([r, later])["20260923T100000Z"], outcomes.GAP)


class LoadSurvives(_Log):
    def test_a_line_of_bytes_that_are_not_utf8_costs_that_line_only(self):
        # load: a line that is not a row is skipped and must cost one row, not the report
        a, b = _row(0, 100.0), _row(60, 101.0)
        bad = []
        rows = outcomes.load(self._log(_j(a).encode() + b"\n\xff\xfe\x80 not text\n" + _j(b).encode() + b"\n"), bad)
        self.assertEqual(rows, [a, b])
        self.assertEqual([n for n, _ in bad], [2])

    def test_a_line_json_refuses_with_a_plain_value_error_costs_that_line_only(self):
        # load: a line that is not a row is skipped; json.loads refuses an over-long integer with ValueError, not JSONDecodeError
        a, b = _row(0, 100.0), _row(60, 101.0)
        bad = []
        rows = outcomes.load(self._log(_j(a) + "\n" + '{"v":1,"n":' + "9" * 10_000 + "}\n" + _j(b) + "\n"), bad)
        self.assertEqual(rows, [a, b])
        self.assertEqual([n for n, _ in bad], [2])

    def test_an_object_with_a_tick_id_and_no_ts_rx_is_skipped_not_crashed(self):
        # SPEC §2 and load: a line without string tick_id and ts_rx is dropped
        a = _row(0, 100.0)
        bad = []
        rows = outcomes.load(self._log('{"v":1,"tick_id":"20260923T100000Z","mid":100.0}\n' + _j(a) + "\n"), bad)
        self.assertEqual(rows, [a])
        self.assertEqual(bad, [(1, "not a row: needs tick_id and ts_rx")])


class GluedLines(_Log):
    def test_a_whole_row_after_a_one_byte_torn_head_is_kept(self):
        # load: a torn line with the next whole row appended onto it keeps that row (it was written in full)
        b = _row(60, 101.0)
        bad = []
        self.assertEqual(outcomes.load(self._log("{" + _j(b) + "\n"), bad), [b])
        self.assertIn("the whole row appended onto the torn line is kept", bad[0][1])

    def test_many_whole_rows_on_one_line_are_read_in_file_order(self):
        # load: rows in file order; _glued: the JSON values on the line, in order
        rs = [_row(60 * k, 100.0 + k) for k in range(8)]
        p = self._log("".join(_j(r) for r in rs[:4]) + "\n" + _j(rs[4])[:25] + "".join(_j(r) for r in rs[5:]) + "\n")
        self.assertEqual(outcomes.load(p), rs[:4] + rs[5:])

    def test_a_whole_row_after_a_torn_row_on_one_line_is_kept(self):
        # load: the tail from the last row start parses on its own and is kept; only what does not parse is the skip
        a, b, c, d = (_row(60 * k, 100.0 + k) for k in range(4))
        bad = []
        rows = outcomes.load(self._log(_j(a) + _j(b)[:30] + _j(c) + "\n" + _j(d) + "\n"), bad)
        self.assertIn(c, rows)
        self.assertEqual(rows[-1], d)
        self.assertEqual([n for n, _ in bad], [1])
        self.assertIn("kept", bad[0][1])

    def test_a_line_without_a_row_start_yields_no_pieces(self):
        # _glued: pieces are split at row starts, so a line with none has no parsed object to name
        a = _row(0, 100.0)
        bad = []
        self.assertEqual(outcomes.load(self._log(_j(a) + "\nxx 12"), bad), [a])      # the last line, no newline
        self.assertEqual([n for n, _ in bad], [2])
        self.assertNotIn("parsed object", bad[0][1])
        self.assertNotIn("kept", bad[0][1])


if __name__ == "__main__":
    unittest.main()

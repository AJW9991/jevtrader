"""loop/status.py: the one-screen morning check renders from the log, the heartbeat, HALT, proposals/
and logs/propose.log, says STOPPED/HALT/MISSING when they apply, and can carry no H1/H2/pair/
confidence number because it never imports or calls the code that computes one (PREREG §8.4)."""
import contextlib, datetime, io, os, shutil, tempfile, unittest
from unittest import mock

from loop import config, dash, outcomes, report, status
from test_dash import ALLOWED_IMPORTS, ALLOWED_REPORT, assert_health_only, runtime_health_only
from test_report import _row, _write

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UTC = datetime.timezone.utc


def _now(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M").replace(tzinfo=UTC)


class Status(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.log = os.path.join(cls.tmp, "decisions.jsonl")
        _write(cls.log, [_row(m) for m in range(42)])                 # 2026-09-23 10:00 .. 10:41, one torn line
        cls.rows = outcomes.load(cls.log, [])
        cls.outs = outcomes.join(cls.rows)
        cls.props = os.path.join(cls.tmp, "proposals")
        os.makedirs(cls.props)
        for name in ("2026-09-21.md", "2026-09-21.json", "2026-09-22.md"):
            with open(os.path.join(cls.props, name), "w", encoding="utf-8") as fh:
                fh.write("x\n")
        cls.plog = os.path.join(cls.tmp, "propose.log")
        with open(cls.plog, "w", encoding="utf-8") as fh:
            fh.write("".join(f"line {i}\n" for i in range(6)))
        cls.halt = os.path.join(cls.tmp, "HALT")

    def _render(self, now, hb="2026-09-23T10:41:00.100Z", t0=report.tick_epoch("20260923T100000Z"), halt=None):
        return status.render(self.rows, self.outs, t0, _now(now), hb, halt or self.halt, self.log, self.props, self.plog, "v1")

    def test_ticking_stopped_and_halt_lines(self):
        text = self._render("2026-09-23T10:42")
        self.assertIn("ticking: last tick 60 s ago (2026-09-23T10:41:00.100Z)", text)
        self.assertIn("HALT absent: sends allowed", text)
        self.assertIn("STOPPED? last tick 19 min ago", self._render("2026-09-23T11:00"))
        self.assertIn("STOPPED? no heartbeat", self._render("2026-09-23T11:00", hb=None))
        self.assertIn("STOPPED? heartbeat unreadable", self._render("2026-09-23T11:00", hb="junk"))
        with open(self.halt, "w", encoding="utf-8") as fh:
            fh.write("spend: $0.2513 of input tokens today\n")
        try:
            text = self._render("2026-09-23T10:42")
            self.assertIn("HALT PRESENT since", text)
            self.assertIn("spend: $0.2513 of input tokens today -- nothing is sent until a person clears it", text)
        finally:
            os.remove(self.halt)

    def test_a_heartbeat_is_stale_one_second_past_three_ticks(self):
        # STALE_S is three cadences: 180 s old is a slow loop, 181 s a stopped one
        self.assertIn("ticking: last tick 180 s ago", self._render("2026-09-23T10:44", hb="2026-09-23T10:41:00.000Z"))
        self.assertIn("STOPPED? last tick 3 min ago (2026-09-23T10:40:59.000Z); a healthy loop is under 180 s",
                      self._render("2026-09-23T10:44", hb="2026-09-23T10:40:59.000Z"))

    def test_the_sample_day_turns_at_t0_each_day_and_ends_at_t0_plus_28_days(self):
        # T0 10:00Z: a day is [T0 + 86400 (N - 1), T0 + 86400 N), so d01 runs to 09:59 the next morning
        # and the last minute of d28 is 2026-10-21T09:59; at T0 + 28 d exactly the sample has ended
        for now, want in (("2026-09-23T09:59", "sample: not started (T0 2026-09-23T10:00Z)"),
                          ("2026-09-23T10:00", "sample: day d01 of 28"),
                          ("2026-09-24T09:59", "sample: day d01 of 28"),
                          ("2026-09-24T10:00", "sample: day d02 of 28"),
                          ("2026-10-21T09:59", "sample: day d28 of 28 (T0 2026-09-23T10:00Z, ends 2026-10-21T10:00Z)"),
                          ("2026-10-21T10:00", "sample: ended 2026-10-21T10:00Z")):
            with self.subTest(now=now):
                self.assertIn(want, self._render(now))

    def test_last_row_today_sample_and_per_day(self):
        text = self._render("2026-09-23T10:42")
        self.assertIn("last row: 20260923T104100Z live ok state=deep organic flat violent c=sell prompt_b=v2 jev=141ms/1000tok err=None key=env:TYPESAFE_API_KEY_LOOP DRIFT", text)
        # today: 42 distinct minutes elapsed at 10:42, 42 rows (the torn line is not one); 36 live answered
        # (5 dry, 1 jev absence); spend as the guard counts it: 36 x 1000 + 2000 for the failed send
        self.assertIn("today 2026-09-23Z: 42 rows in 642 min (7%), live answered 36, absence jev 1; spend $0.0016 of the $0.25 tripwire", text)
        self.assertIn("sample: day d01 of 28 (T0 2026-09-23T10:00Z, ends 2026-10-21T10:00Z)", text)
        self.assertIn("prompt_b CURRENT: v1; rows 42 in the log", text)
        self.assertIn("per day (last 1 of 1; BAD days so far 0):", text)
        # the per-day table's live = rows whose t + h the log has reached (fill counts those), pend = not yet
        self.assertIn("  d01       ticks    42 (  2.9%)  live    21  fill 100.0%  pend   15  skip   0  jev-err   2.7%  open", text)
        self.assertIn("sample: not started", self._render("2026-09-22T10:42"))
        self.assertIn("sample: ended 2026-10-21T10:00Z", self._render("2026-10-22T10:42"))
        self.assertIn("sample: no T0", self._render("2026-09-23T10:42", t0=None))

    def test_the_per_day_table_is_the_samples_and_names_a_day_without_live_rows(self):
        # 2026-09-28 (verifier): `make status` ran days_table on the whole uncut log, so a pre-T0 day
        # with poor fill counted as BAD and a closed sample day with no row at all read "ok"
        t0 = report.tick_epoch("20260925T214000Z")
        rows = []
        for m in range(-1440, 4 * 1440, 1):
            day = m // 1440 + 1
            if day == 2 or (day == 0 and m % 20):                       # d02: no rows; d00: a row every 20 min
                continue
            r = dict(_row(7))
            e = t0 + 60 * m
            r["tick_id"], r["ts_rx"] = report._tick_of(e), datetime.datetime.fromtimestamp(e, UTC).strftime("%Y-%m-%dT%H:%M:%S.100Z")
            rows.append(r)
        outs = outcomes.join(rows)
        text = status.render(rows, outs, t0, _now("2026-09-29T22:00"), "2026-09-29T21:39:00.100Z", self.halt, self.log, self.props, self.plog, "v2")
        self.assertIn("per day (last 3 of 4; BAD days so far 0; NO LIVE ROWS 1: d02 (fill 0/0; the exclusion is Alex's call)):", text)
        self.assertIn("  d02       ticks     0 (  0.0%)  live     0  fill    n/a  pend    0  skip   0  jev-err    n/a  NO LIVE ROWS", text)
        self.assertNotIn("d00", text)                                    # the day before T0 is not the sample's
        self.assertIn("STOPPED? no heartbeat (data/heartbeat absent or empty", status.render(rows, outs, t0, _now("2026-09-29T22:00"), None, self.halt, self.log, self.props, self.plog, "v2"))

    def test_nightly_lines_and_the_missing_slot(self):
        # at 12Z yesterday's (09-22) table exists: nothing missing; at 12Z on 09-24 the 09-23 one is missing
        text = self._render("2026-09-23T12:00")
        self.assertIn("nightly: 2 tables, 1 proposal files in proposals/; latest 2026-09-22", text)
        self.assertNotIn("MISSING", text)
        self.assertIn("  line 3\n  line 4\n  line 5\n", text)
        text = self._render("2026-09-24T12:00")
        self.assertIn("MISSING: no proposal for 2026-09-23 yet", text)
        self.assertNotIn("MISSING", self._render("2026-09-24T05:00"))    # before 11Z the slot has not come round yet
        self.assertIn("MISSING: no proposal for 2026-09-23 yet", self._render("2026-09-25T05:00"))

    def test_missing_waits_until_11z_for_a_slow_winter_night(self):
        # under CST (from 2026-11-01) 03:30 America/Chicago is 09:30Z and the call is capped at 45 min
        # awake, so a night can still be running at 10:15Z: MISSING at 10Z would flag a night in progress
        self.assertEqual(status.NIGHTLY_DONE_UTC_H, 11)
        self.assertNotIn("MISSING", self._render("2026-09-24T10:59"))
        self.assertIn("MISSING: no proposal for 2026-09-23 yet", self._render("2026-09-24T11:00"))

    def test_empty_log_and_main(self):
        text = status.render([], {}, None, _now("2026-09-28T01:00"), None, self.halt, os.path.join(self.tmp, "none.jsonl"),
                             os.path.join(self.tmp, "no-proposals"), os.path.join(self.tmp, "no.log"), None)
        for needle in ("STOPPED? no heartbeat", "last row: none", "0 rows in 60 min (0%)", "sample: no T0", "per day: no rows",
                       "nightly: 0 tables, 0 proposal files in proposals/; latest none -- MISSING", f"no {self.tmp}/no.log yet"):
            self.assertIn(needle, text)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), mock.patch.object(config, "HALT", self.halt), mock.patch.object(config, "DATA", self.tmp), \
                mock.patch.object(dash, "heartbeat", return_value="2026-09-23T10:41:00.100Z"), \
                mock.patch.object(dash, "current_version", return_value="v9"):
            code = status.main(["--log", self.log, "--t0", "2026-09-23T10:00", "--now", "2026-09-23T10:42"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("status at 2026-09-23T10:42Z", out)
        self.assertIn("ticking: last tick 60 s ago", out)
        self.assertIn("prompt_b CURRENT: v9", out)
        self.assertIn("sample: day d01 of 28", out)

    def test_a_row_stamped_after_the_clock_closes_no_day_on_the_status_screen(self):
        t0 = report._t0("2026-09-23T10:00")
        stray = dict(self.rows[-1], tick_id="20260927T100000Z", ts_rx="2026-09-27T10:00:00.100Z")
        rows = self.rows + [stray]
        lines = status._days_lines(rows, outcomes.join(rows), t0, _now("2026-09-23T10:42"))
        text = "\n".join(lines)
        self.assertNotIn("NO LIVE ROWS", text.split("\n", 1)[1])
        self.assertNotIn("BAD (", text)
        without = status._days_lines(rows, outcomes.join(rows), t0)                  # no clock: the stray row closes d01..d04
        self.assertIn("NO LIVE ROWS", "\n".join(without))
        text = status.render(rows, outcomes.join(rows), t0, _now("2026-09-23T10:42"), None, self.halt, self.log,
                             os.path.join(self.tmp, "no-proposals"), os.path.join(self.tmp, "no.log"), None)   # render passes its clock
        self.assertNotIn("NO LIVE ROWS", text.split("per day", 1)[1].split("\n", 1)[1])
        self.assertNotIn("BAD (", text)

    def test_the_screen_shows_the_exclusions_file_the_day_28_run_will_apply(self):
        # a line the parser refuses must be seen the morning after it is written, not on day 28
        data = os.path.join(self.tmp, "excl-data")
        os.makedirs(data, exist_ok=True)
        ex = os.path.join(data, "exclusions.tsv")
        for body, want in (("day\tfill%\tjev-err%\treason\nd03\t90.0%\t0.0%\tasleep\n", f"exclusions: 1 day(s) excluded: d03 ({ex})"),
                           ("day\tfill%\tjev-err%\treason\nd1 6\t90.0%\t0.0%\ttypo\n", "exclusions: REFUSED, fix before day 28: " + ex + ":2: day "),
                           (None, f"exclusions: none ({ex} absent)")):
            if body is None:
                os.remove(ex)
            else:
                with open(ex, "w", encoding="utf-8") as fh:
                    fh.write(body)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), mock.patch.object(config, "HALT", self.halt), mock.patch.object(config, "DATA", data), \
                    mock.patch.object(dash, "heartbeat", return_value=None), mock.patch.object(dash, "current_version", return_value="v9"):
                self.assertEqual(status.main(["--log", self.log, "--t0", "2026-09-23T10:00", "--now", "2026-09-23T10:42"]), 0)
            self.assertIn(want, buf.getvalue())

    def test_a_data_dir_this_user_cannot_enter_is_named_not_counted_as_zero(self):
        # os.path.exists is False on a path under a directory the user cannot enter, so status read
        # "no log" and printed $0 "as the guard counts it" while the guard counted inf and tripped
        log = os.path.join(self.tmp, "locked", "decisions.jsonl")
        real_open = open

        def no_entry(path, *a, **k):
            if os.path.abspath(str(path)) == log:
                raise PermissionError(13, "Permission denied", path)
            return real_open(path, *a, **k)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), mock.patch("builtins.open", side_effect=no_entry), \
                mock.patch.object(config, "HALT", self.halt), mock.patch.object(config, "DATA", self.tmp), \
                mock.patch.object(dash, "heartbeat", return_value=None), mock.patch.object(dash, "current_version", return_value="v9"):
            self.assertEqual(status.main(["--log", log, "--t0", "2026-09-23T10:00", "--now", "2026-09-23T10:42"]), 0)
        out = buf.getvalue()
        self.assertTrue(out.startswith(f"LOG UNREADABLE: {log}: "), out[:120])
        self.assertIn("spend UNREADABLE", out)

    def test_an_unreadable_log_is_named_not_a_traceback(self):
        # a 0200 log (write_row still appends to it) or a directory: the spend guard trips on it, and
        # the morning screen says why instead of dying in outcomes.load
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), mock.patch.object(config, "HALT", self.halt), mock.patch.object(config, "DATA", self.tmp), \
                mock.patch.object(dash, "heartbeat", return_value=None), mock.patch.object(dash, "current_version", return_value="v9"):
            code = status.main(["--log", self.tmp, "--t0", "2026-09-23T10:00", "--now", "2026-09-23T10:42"])   # a directory
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertTrue(out.startswith(f"LOG UNREADABLE: {self.tmp}: "), out[:200])
        self.assertIn("spend UNREADABLE: the log cannot be read, so the guard trips (HALT) rather than count it", out)

    def test_no_h1_h2_pair_or_confidence_number(self):
        text = self._render("2026-09-23T10:42")
        for banned in ("H1 statistic", "H2 statistic", "pair B-C", "mean_S", "Pearson", "Brier", "calibration", "c99", "noultail", "pbuy", "confidence"):
            self.assertNotIn(banned, text)
        # the same static guard as the dash (plus cycle for the spend guard and dash for its readers),
        # and the screen renders on an answered log with every measurement function tripwired
        assert_health_only(self, os.path.join(REPO, "loop", "status.py"), ALLOWED_REPORT | {"days_table", "_pc", "SAMPLE_DAYS"},
                           ALLOWED_IMPORTS | {"cycle", "dash", "exclusions"})
        text2 = runtime_health_only(self, lambda: self._render("2026-09-23T10:42"))
        self.assertEqual(text2, text)


if __name__ == "__main__":
    unittest.main()

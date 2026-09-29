"""loop/status.py: the one-screen morning check renders from the log, the heartbeat, HALT, proposals/
and logs/propose.log, says STOPPED/HALT/MISSING when they apply, and can carry no H1/H2/pair/
confidence number because it never imports or calls the code that computes one (PREREG §8.4)."""
import contextlib, datetime, io, json, os, shutil, tempfile, unittest
from unittest import mock

import synth
from fixture_prereg import pin_prereg_v2
from fixture_products import add_products
from loop import config, cycle, dash, outcomes, report, status
from test_dash import ALLOWED_IMPORTS, ALLOWED_REPORT, AGREEMENT_WORDS, assert_health_only, runtime_health_only
from test_prompts import _v3
from test_report import _row, _stopped_with_a_stray, _write

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
        self.assertIn("today 2026-09-23Z: 42 rows in 642 min (7%), live answered 36, absence jev 1; spend $0.0016 of the "
                      f"${config.DAILY_SPEND_HALT_USD:g} tripwire", text)                     # $0.25 a product
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

    def test_a_row_stamped_after_the_clock_leaves_a_stopped_logs_open_day_open(self):
        # _days_lines passed the whole log's last tick and days_table capped it with min(last, now): one row stamped
        # after the clock made the clock the log's last tick, so on a log that stopped at 21:49, read at 21:57, d01
        # closed on rows the log has not reached and read BAD (fill 25/30). The screen reads the same with or without
        # the stray row: d01 open, 5 pending, no BAD day.
        t0, rows, stray, now = _stopped_with_a_stray()
        at = datetime.datetime.fromtimestamp(now, UTC)
        got = []
        for rs in (rows, rows + [stray]):
            text = status.render(rs, outcomes.join(rs), t0, at, None, self.halt, os.path.join(self.tmp, "no-such.jsonl"),
                                 os.path.join(self.tmp, "no-proposals"), os.path.join(self.tmp, "no.log"), None)
            self.assertIn("; BAD days so far 0", text)
            d01 = [l for l in text.splitlines() if l.startswith("  d01 ")]
            self.assertEqual(len(d01), 1, text)
            self.assertIn("live    25  fill 100.0%  pend    5", d01[0])
            self.assertTrue(d01[0].endswith("  open"), d01[0])
            got.append(d01[0])
        self.assertEqual(got[1], got[0])

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

    def test_a_missing_log_is_zero_spend_and_no_unreadable_line(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), mock.patch.object(config, "HALT", self.halt), mock.patch.object(config, "DATA", self.tmp), \
                mock.patch.object(dash, "heartbeat", return_value=None), mock.patch.object(dash, "current_version", return_value="v9"):
            self.assertEqual(status.main(["--log", os.path.join(self.tmp, "never.jsonl"), "--t0", "2026-09-23T10:00",
                                          "--now", "2026-09-23T10:42"]), 0)
        out = buf.getvalue()
        self.assertNotIn("UNREADABLE", out)
        self.assertIn(f"spend $0.0000 of the ${config.DAILY_SPEND_HALT_USD:g} tripwire (as the guard counts it)", out)

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
        self.assertIn("spend UNREADABLE: the log cannot be read, so the next tick's guard trips (HALT) rather than count it", out)

    def _today(self, tokens):
        """status.render's today line on a log of three of today's rows, the middle one carrying `tokens`."""
        log = os.path.join(self.tmp, "uncounted.jsonl")
        rows = [dict(_row(m)) for m in range(5, 8)]                       # 2026-09-23 10:05 .. 10:07, live answered
        for i, t in enumerate(tokens):
            rows[1 + i] = dict(rows[1 + i], jev=dict(rows[1 + i]["jev"], input_tokens=t))
        _write(log, rows, garbage=False)
        rows = outcomes.load(log, [])
        text = status.render(rows, outcomes.join(rows), None, _now("2026-09-23T10:42"), None, self.halt, log,
                             os.path.join(self.tmp, "no-proposals"), os.path.join(self.tmp, "no.log"), None)
        self.assertIn("HALT absent: sends allowed", text)                  # status writes no HALT; the next tick's guard does
        today = [l for l in text.splitlines() if l.startswith("today ")]
        self.assertEqual(len(today), 1, text)
        return today[0]

    def test_a_token_count_past_a_floats_range_is_named_on_the_today_line(self):
        # the spend UNCOUNTED branch had no test: without it the line printed float max as a 309-digit
        # dollar figure "of the $0.25 tripwire"; and it said "the guard trips (HALT)" under "HALT absent",
        # where its UNREADABLE sibling says the next tick's guard trips (status itself writes no HALT)
        line = self._today([10 ** 400])
        self.assertIn("; spend UNCOUNTED: ", line)
        self.assertTrue(line.endswith(" past a float's range, so the next tick's guard trips (HALT)"), line)
        self.assertNotIn("spend $", line)
        self.assertIn(f"; spend $0.0001 of the ${config.DAILY_SPEND_HALT_USD:g} tripwire", self._today([1000]))   # still priced

    def test_counts_that_fit_a_float_but_sum_past_one_are_named_as_the_sum(self):
        # two server replies of 1e308 (jev._parse int()s them): each fits a float, today's sum does not; the
        # line said "a token count today is past a float's range" and sent Alex to look for a row not there
        line = self._today([10 ** 308, 10 ** 308])
        self.assertIn("; spend UNCOUNTED: a token count today, or today's sum of them, is past a float's range,"
                      " so the next tick's guard trips (HALT)", line)
        self.assertNotIn("spend $", line)

    def test_float_counts_that_sum_to_inf_are_uncounted_not_an_unreadable_log(self):
        # float counts (a foreign row's; jev._parse int()s the count) that sum past a float's range made
        # cycle.spend_today return math.inf, which this line reads as a log that cannot be read
        line = self._today([1e308, 1e308])
        self.assertIn("; spend UNCOUNTED: a token count today, or today's sum of them, is past a float's range,"
                      " so the next tick's guard trips (HALT)", line)
        self.assertNotIn("UNREADABLE", line)

    def test_no_h1_h2_pair_or_confidence_number(self):
        text = self._render("2026-09-23T10:42")
        for banned in ("H1 statistic", "H2 statistic", "pair B-C", "mean_S", "Pearson", "Brier", "calibration", "c99", "noultail", "pbuy", "confidence"):
            self.assertNotIn(banned, text)
        # the same static guard as the dash (plus cycle for the spend guard and dash for its readers),
        # and the screen renders on an answered log with every measurement function tripwired
        assert_health_only(self, os.path.join(REPO, "loop", "status.py"), ALLOWED_REPORT | {"days_table", "_pc", "SAMPLE_DAYS", "last_reached"},
                           ALLOWED_IMPORTS | {"cycle", "dash", "exclusions", "exclusions_v2"})
        text2 = runtime_health_only(self, lambda: self._render("2026-09-23T10:42"))
        self.assertEqual(text2, text)


class StatusV2(unittest.TestCase):
    """PREREG-v2 §2, §10: without --log the screen covers every product's store: data/HALT once (REPO/data, never
    --data), each PAUSE with its reason, CURRENT and a pending prompt version on its own line, today's spend over
    every product's log as the guard sums it, T0_v2 from §12, each product's heartbeat, last row, today and days,
    and the exclusions-v2 file beside the recomputed rule. Health only: no agreement, A's or D's."""
    T0S = "20261024T220000Z"
    NOW = datetime.datetime(2026, 10, 26, 3, 7, tzinfo=datetime.timezone.utc)

    def setUp(self):
        self.products = add_products(self)
        self.data = self.enterContext(tempfile.TemporaryDirectory())
        for k, v in (("DATA", self.data), ("DECISIONS", os.path.join(self.data, "decisions.jsonl")),
                     ("HEARTBEAT", os.path.join(self.data, "heartbeat")), ("HALT", os.path.join(self.data, "HALT")),
                     ("PROPOSALS", os.path.join(self.data, "proposals")), ("REPO", self.data)):
            self.enterContext(mock.patch.object(config, k, v))
        os.makedirs(config.PROPOSALS)
        pin_prereg_v2(self, self.T0S)
        self.prompts = os.path.join(self.data, "prompts")
        os.makedirs(self.prompts)
        for v in ("v1", "v2"):
            shutil.copy(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts", v + ".json"), self.prompts)
        with open(os.path.join(self.prompts, "v3.json"), "w", encoding="utf-8") as fh:
            json.dump(_v3(activation_tick="20261027T220000Z", replaces="v2"), fh)
        with open(os.path.join(self.prompts, "CURRENT"), "w", encoding="utf-8") as fh:
            fh.write("v3\n")
        self.enterContext(mock.patch.object(config, "PROMPTS", self.prompts))
        logs = synth.generate_products(8, self.products, t0=self.T0S, days=1.2, pre_hours=1.0, era="v2", cadence_s=300)
        synth.write_products(self.data, logs)
        for p in self.products:
            with open(dash.store_paths(p)[1], "w", encoding="utf-8") as fh:
                fh.write("2026-10-26T03:06:00.100Z\n" if p != self.products[2] else "2026-10-26T02:00:00.100Z\n")
        with open(config.pause(self.products[1]), "w", encoding="utf-8") as fh:
            fh.write("prereg: 3 bad days\n")

    def _main(self, argv=()):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(status.main(list(argv), now=self.NOW), 0)
        return buf.getvalue()

    def test_every_store_halt_each_pause_and_the_pending_version(self):
        text = self._main()
        lines = text.splitlines()
        self.assertIn("HALT absent: sends allowed", lines)
        self.assertIn(f"PAUSE.{self.products[0]}: absent", lines)
        self.assertTrue(any(l.startswith(f"PAUSE.{self.products[1]} PRESENT since ") and "prereg: 3 bad days" in l for l in lines))
        self.assertIn("prompt_b CURRENT: v3", lines)
        self.assertIn("prompt_b pending: v3 (CURRENT) activates at 2026-10-27T22:00Z, replacing v2; until then B asks v2", lines)
        self.assertIn("sample: day d02 of 28 (T0_v2 2026-10-24T22:00Z, ends 2026-11-21T22:00Z)", lines)
        for p in self.products:
            self.assertIn(f"-- {p} ({status._short(dash.store_paths(p)[0])}): rows", text)
        self.assertEqual(sum(1 for l in lines if l.startswith("  ticking: last tick 60 s ago")), 2)
        self.assertEqual(sum(1 for l in lines if l.startswith("  STOPPED? last tick 67 min ago")), 1)
        usd = sum(cycle.spend_today(self.NOW.timestamp(), dash.store_paths(p)[0]) for p in self.products)
        self.assertGreater(usd, 0.0)
        self.assertIn(f"spend today ${usd:.4f} over every product's log, of the ${config.DAILY_SPEND_HALT_USD:g} tripwire"
                      " (as the guard counts it)", lines)
        self.assertIn(f"exclusions-v2: none ({config.EXCLUSIONS_V2} absent)", lines)
        self.assertTrue(any(l.startswith("  stop rule 3 (PREREG-v2 §9.3), recomputed from the log, which governs") for l in lines))
        # HALT is REPO/data's whatever the stores are, and shows first
        with open(config.HALT, "w", encoding="utf-8") as fh:
            fh.write("spend: $0.80 of input tokens today\n")
        self.assertTrue(self._main().splitlines()[1].startswith("HALT PRESENT since "))
        # after the activation there is nothing pending
        self.assertIn("prompt_b pending: none (B asks v3 this minute)",
                      self._main_at(datetime.datetime(2026, 10, 28, 0, 0, tzinfo=datetime.timezone.utc)))

    def test_after_the_sample_the_line_names_v2s_run(self):
        # v1's screen names v1's command (python3 -m loop.inference ... RESULTS.md); v2's names its own (PREREG-v2 §10)
        t0 = report.tick_epoch(self.T0S)
        end = datetime.datetime.fromtimestamp(t0 + 28 * 86400, datetime.timezone.utc)
        self.assertEqual(status._sample_line_v2(t0, end), "sample: ended 2026-11-21T22:00Z; day 28's inference is `make results`"
                         " (python3 -m loop.inference_v2 --sample --out RESULTS-v2.md), once d28 has closed")
        self.assertEqual(status._sample_line_v2(t0, end - datetime.timedelta(seconds=1)),
                         "sample: day d28 of 28 (T0_v2 2026-10-24T22:00Z, ends 2026-11-21T22:00Z)")

    def _main_at(self, now):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status.main([], now=now)
        return buf.getvalue()

    def test_a_listed_day_the_rule_judges_fine_is_named(self):
        with open(config.EXCLUSIONS_V2, "w", encoding="utf-8") as fh:
            fh.write(f"day\tproduct\tfill%\tjev-err%\treason\nd01\t{self.products[2]}\t90.0%\t0.0%\tlooked bad\n")
        text = self._main()
        self.assertIn(f"exclusions-v2: 1 product-day(s) listed: d01 {self.products[2]}", text)
        self.assertIn(f"DISAGREE: listed, but the rule does not exclude them (fine or not yet closed), so NOT excluded: d01 {self.products[2]}", text)
        with open(config.EXCLUSIONS_V2, "w", encoding="utf-8") as fh:
            fh.write("day\tproduct\tfill%\tjev-err%\treason\nd01\tBTC-USD\t90.0%\t0.0%\tx\n")
        self.assertIn("exclusions-v2: REFUSED, fix before day 28:", self._main())

    def test_health_only_neither_agreement(self):
        text = self._main()
        for word in AGREEMENT_WORDS + ("H1 statistic", "pair B-C", "mean_S", "Pearson", "Brier", "calibration", "confidence"):
            self.assertNotIn(word, text)
        self.assertEqual(runtime_health_only(self, self._main), text)       # renders with every measurement tripwired
        # --log is v1's screen on that one log, as before
        self.assertIn("jev-paper-loop status at", self._main(["--log", dash.store_paths(self.products[1])[0], "--t0", self.T0S]))


if __name__ == "__main__":
    unittest.main()

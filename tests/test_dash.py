"""loop/dash.py: the health page renders from a log, and can carry no H1/H2/pair/confidence number
because every report.<name> it uses is on an allowlist of section 1-3 functions (PREREG §8.4)."""
import ast, contextlib, datetime, io, os, re, shutil, tempfile, unittest
from unittest import mock

from fixture_prereg import pin_prereg, text as prereg_text
from fixture_prompts import pin_v1
from loop import config, dash, inference, outcomes, report, status
from test_report import _row, _write, no_live_halt

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# what a health page may call on report: section 1-3 functions and their constants, nothing that
# replays a book, joins a return to an answer, or bins a confidence
ALLOWED_REPORT = {"health", "days_table", "occupancy", "retest", "in_sample", "tick_epoch", "day_of", "_iso_minute", "_t0", "_tick_of",
                  "_num", "_mean", "_p95", "DAY_TICKS", "SAMPLE_DAYS", "BAD_FILL", "BAD_JEV_ERR", "BAD_DAYS_PAUSE", "OCCUPANCY_FLAG"}
ALLOWED_IMPORTS = {"config", "outcomes", "report", "state"}


BANNED_CALLS = {"getattr", "vars", "__import__", "eval", "exec", "globals", "locals", "setattr", "delattr"}


def assert_health_only(tc, path, allowed_report, allowed_imports):
    """The static guard both health-only modules pass: every `report.<name>` and every name imported
    from loop.report is on the allowlist and never aliased; no other loop module is imported by any
    spelling (relative, absolute, `import loop.x`, `from loop import x as y`); no getattr/vars/
    __import__/eval/importlib or __dict__/__globals__ that could reach a name the scan cannot see."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "report"}
    tc.assertLessEqual(used, allowed_report, used - allowed_report)
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            mod = n.module or ""
            if n.level or mod == "loop" or mod.startswith("loop."):
                tc.assertTrue(all(a.asname is None for a in n.names), ast.dump(n))
                if n.level and not mod or mod == "loop":                  # from . import x / from loop import x
                    tc.assertLessEqual({a.name for a in n.names}, allowed_imports, ast.dump(n))
                elif mod in ("report", "loop.report") or mod.endswith(".report"):
                    tc.assertLessEqual({a.name for a in n.names}, allowed_report, ast.dump(n))
                else:
                    tc.fail(f"{path}: imports {ast.dump(n)}")
        if isinstance(n, ast.Import):
            tc.assertFalse(any(a.name == "loop" or a.name.startswith("loop.") or a.name == "importlib" for a in n.names), ast.dump(n))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            tc.assertNotIn(n.func.id, BANNED_CALLS, f"{path}: {n.func.id}() could reach a banned name")
        if isinstance(n, ast.Attribute):
            tc.assertNotIn(n.attr, {"__dict__", "__globals__", "__builtins__", "import_module"}, f"{path}: {n.attr}")
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    tc.assertFalse(names & {"book", "inference", "rules", "jev", "importlib"})


class _Tripwire(Exception):
    pass


def _trip(*a, **k):
    raise _Tripwire("a health page reached the measurement")


def runtime_health_only(tc, fn):
    """Runs `fn` with every function that computes an H1, H2, pair or calibration number replaced by a
    tripwire: the page or screen must render without touching one, whatever the static scan missed."""
    from loop import book
    with mock.patch.object(report, "table", _trip), mock.patch.object(report, "h2", _trip), \
            mock.patch.object(report, "calibration", _trip), mock.patch.object(report, "agreement", _trip), \
            mock.patch.object(report, "_h2_pair", _trip), mock.patch.object(report, "h2_units", _trip), \
            mock.patch.object(report, "_cell", _trip), mock.patch.object(report, "_blocks", _trip), \
            mock.patch.object(book, "replay", _trip), mock.patch.object(book, "paired", _trip):
        return fn()


class Dash(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        no_live_halt(cls, cls.tmp)                                       # a page is compared with a page
        cls.log = os.path.join(cls.tmp, "decisions.jsonl")
        _write(cls.log, [_row(m) for m in range(42)])
        cls.rows = outcomes.load(cls.log, [])
        cls.outs = outcomes.join(cls.rows)

    def test_renders_sections_1_to_3_and_the_strip(self):
        import datetime
        now = datetime.datetime(2026, 9, 23, 10, 42, tzinfo=datetime.timezone.utc)
        page = dash.render(self.rows, self.outs, t0=None, now=now, hb="2026-09-23T10:41:00.000Z", log=self.log)
        for needle in ("priced ticks per hour (UTC)", "PREREG §8 stop rule 3", "adjective occupancy", "the 81 states",
                       "test-retest", "the nightly", "Health only (PREREG §8.4)", "2026-09-23", "class='cell b",
                       "<div class='lab'>2026-09-23 &middot; <b>42</b>/643</div>",    # 42 priced ticks of the 643 minutes begun by 10:42
                       "absence in the sample: jev 1", "spend per day", "jev latency p95 per day", "holes &middot;",
                       "realised horizon", "key answering", "prompt_b versions", "stop-rule fill"):
            self.assertIn(needle, page)
        self.assertNotIn("rationale</th>", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("http://", page.split("</style>", 1)[1])
        self.assertNotIn("https://", page.split("</style>", 1)[1])
        self.assertIn("at render 10:", page)                            # the badge says when it was true

    def test_hourly_counts_priced_ticks_only_and_bins_by_shortfall(self):
        # a two-hour feed outage writes absence rows with no mid: they must draw as the gap they are
        rows = [dict(_row(m)) for m in range(42)]
        for r in rows[10:20]:
            r["absence"], r["mid"], r["bid"], r["ask"] = "feed", None, None, None
        self.assertEqual(dash.hourly(rows)[("20260923", 10)], 32)
        self.assertEqual(dash.absent(rows)[("20260923", 10)]["feed"], 10)
        page = dash.render(rows, outcomes.join(rows), now=datetime.datetime(2026, 9, 23, 12, 0, tzinfo=datetime.timezone.utc))   # the strip's window ends today
        self.assertIn("32/60 priced ticks; absent feed 10", page)
        self.assertIn("absence in the sample: feed 10", page)
        self.assertEqual([dash._bin_hour(n) for n in (0, 1, 29, 30, 44, 45, 54, 55, 59, 60)], [-1, 0, 0, 1, 1, 2, 2, 3, 3, 4])
        self.assertEqual(dash._bin(0, 60), -1)
        self.assertEqual(dash._bin(5, 0), 4)
        self.assertEqual([dash._bin_state(n, 1000) for n in (0, 1, 9, 10, 49, 50, 199, 200, 499, 500, 1000)], [-1, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4])
        self.assertEqual(dash._bin_state(3, 0), 4)

    def test_hours_after_the_render_are_not_yet_and_today_counts_the_minutes_begun(self):
        # 2026-09-28 (round 4): the strip drew every hour of today as a full hour, so a page rebuilt at 09:44Z
        # drew 10:00-23:00 as empty 0/60 cells, the class and title of a real outage; today's label read
        # 105/1440, and the hour in progress read 45/60, a 45-54 shortfall
        def at(ticks):
            out = []
            for t in ticks:
                r = dict(_row(20))
                r["tick_id"], r["ts_rx"] = t, f"{t[:4]}-{t[4:6]}-{t[6:8]}T{t[9:11]}:{t[11:13]}:00.100Z"
                out.append(r)
            return out
        yday = [f"20260922T{h:02d}{m:02d}00Z" for h in (12, 14) for m in range(60)]          # 13:00 is a real hole
        today = [f"20260923T{h:02d}{m:02d}00Z" for h in (8, 9) for m in range(60) if h * 60 + m <= 9 * 60 + 44]   # 08:00 .. 09:44
        now = datetime.datetime(2026, 9, 23, 9, 44, 30, tzinfo=datetime.timezone.utc)
        rows = at(yday + today)
        strip = _strip(dash.render(rows, outcomes.join(rows), now=now))
        for hh in range(10, 24):
            self.assertIn(f"<div class='cell future' title='2026-09-23 {hh:02d}:00Z: not yet'></div>", strip)
        self.assertEqual(strip.count("cell future"), 14)
        self.assertIn("<div class='cell' title='2026-09-22 13:00Z: 0/60 priced ticks'></div>", strip)   # the real hole reads as one
        self.assertIn("<div class='cell' title='2026-09-23 07:00Z: 0/60 priced ticks'></div>", strip)   # and so does an hour of today that is over
        self.assertIn("<div class='cell b4' title='2026-09-23 09:00Z: 45/45 priced ticks so far, the hour in progress'></div>", strip)
        self.assertIn("<div class='lab'>2026-09-23 &middot; <b>105</b>/585</div>", strip)
        self.assertIn("<div class='lab'>2026-09-22 &middot; <b>120</b>/1440</div>", strip)
        # the minute under way may not have its row yet: no shortfall; ten missing minutes are one
        strip = _strip(dash.render(rows[:-1], outcomes.join(rows[:-1]), now=now))
        self.assertIn("<div class='cell b4' title='2026-09-23 09:00Z: 44/45 priced ticks so far, the hour in progress'></div>", strip)
        short = [r for r in rows if not r["tick_id"].startswith("20260923T091")]            # 09:10 .. 09:19
        strip = _strip(dash.render(short, outcomes.join(short), now=now))
        self.assertIn("<div class='cell b2' title='2026-09-23 09:00Z: 35/45 priced ticks so far, the hour in progress'></div>", strip)
        # no row in the hour in progress is a gap once a minute of it is over; before that it is not yet
        early = [r for r in rows if not r["tick_id"].startswith("20260923T09")]
        strip = _strip(dash.render(early, outcomes.join(early), now=now))
        self.assertIn("<div class='cell' title='2026-09-23 09:00Z: 0/45 priced ticks so far, the hour in progress'></div>", strip)
        self.assertEqual(dash._hour_cell(0, 3600, 3600 + 30), ("cell future", "not yet"))
        self.assertEqual(dash._hour_cell(1, 3600, 3600 + 30), ("cell b4", "1/1 priced ticks so far, the hour in progress"))
        self.assertEqual(dash._hour_cell(0, 3600, 3600 + 60), ("cell", "0/2 priced ticks so far, the hour in progress"))
        # a row stamped after the clock is drawn as logged, beside the not-yet hours of its day
        stray = at(["20260925T030000Z"])
        strip = _strip(dash.render(rows + stray, outcomes.join(rows + stray), now=now))
        self.assertIn("<div class='cell b0' title='2026-09-25 03:00Z: 1/60 priced ticks'></div>", strip)
        self.assertIn("<div class='cell future' title='2026-09-25 04:00Z: not yet'></div>", strip)

    def test_a_days_tokens_summed_past_a_floats_range_are_not_charted_and_the_page_says_so(self):
        # 2026-09-28 (round 4): each count passes report._num, but two of int(1e308) on one day sum past a
        # float's range, and `t * rate` raised OverflowError: spend_by_day, and with it the page, died
        rows = [dict(_row(m)) for m in range(20, 30)]
        for i in (3, 4):
            rows[i] = dict(rows[i], jev=dict(rows[i]["jev"], input_tokens=int(1e308)))
        self.assertTrue(report._num(int(1e308)))
        self.assertEqual(dash.spend_by_day(rows), {})                      # the day is left out, never a crash
        nxt = dict(_row(20), tick_id="20260924T100000Z", ts_rx="2026-09-24T10:00:00.100Z")   # a day with an ordinary count
        over = []
        self.assertEqual(dash.spend_by_day(rows + [nxt], None, over), {"20260924": 1000 * config.USD_PER_MTOK / 1e6})
        self.assertEqual(over, ["20260923"])
        # the page. report.health's own whole-log sum is report's to guard; here a stand-in leaves the two
        # counts out of it and answers usd None, so what is tested is the dash's own spend sections
        real = report.health

        def health(rs, *a, **k):
            rs = [dict(r, jev=dict(r["jev"], input_tokens=None)) if r["jev"]["input_tokens"] == int(1e308) else r for r in rs]
            return dict(real(rs, *a, **k), usd=None)
        with mock.patch.object(report, "health", health):
            page = dash.render(rows + [nxt], outcomes.join(rows + [nxt]), now=datetime.datetime(2026, 9, 24, 12, 0, tzinfo=datetime.timezone.utc))
        self.assertIn("<span class='badge crit'>1 day(s) not charted</span> 20260923: the input tokens logged that day sum past a float's range.", page)
        self.assertIn("title='20260923: input tokens summed past a float&#x27;s range, not charted'><div class='vbar' style='height:0%'>", page)
        self.assertIn("title='20260924: $0.0000 of the $0.25 tripwire'", page)                # the other day keeps its bar
        self.assertIn("<td>past range</td>", page)                                            # the per-day table
        self.assertIn('<div class="tile crit"><div class="k">spend, whole log</div><div class="v">past range</div>', page)

    def test_skipped_log_lines_show_on_the_page_as_in_report_health(self):
        # the dash never passed the log's skipped lines to report.health, so its "skipped log lines"
        # text could not render: the one count of rows lost to torn lines was missing from the page
        now = datetime.datetime(2026, 9, 23, 10, 42, tzinfo=datetime.timezone.utc)
        self.assertIn("skipped log lines 3", dash.render(self.rows, self.outs, now=now, bad=[(1, "x"), (5, "y"), (9, "z")]))
        self.assertNotIn("skipped log lines", dash.render(self.rows, self.outs, now=now))

    def test_a_calendar_day_without_a_row_is_drawn_empty_in_the_strip(self):
        # the strip looped over days that HAVE rows, so a day the Mac was off vanished instead of
        # showing as 24 empty cells; days after the clock are shown only if a row names them
        rows = []
        for day in ("20260923", "20260925"):                               # 2026-09-24 has no row at all
            for m in range(3):
                r = dict(_row(m))
                r["tick_id"] = f"{day}T10{m:02d}00Z"
                r["ts_rx"] = f"{day[:4]}-{day[4:6]}-{day[6:]}T10:{m:02d}:00.100Z"
                rows.append(r)
        now = datetime.datetime(2026, 9, 25, 12, 0, tzinfo=datetime.timezone.utc)
        page = dash.render(rows, outcomes.join(rows), now=now)
        self.assertIn("2026-09-24 &middot; <b>0</b>/1440", page)
        self.assertEqual(dash._calendar_run(["20260923", "20260925", "20270101"], now), (["20260923", "20260924", "20260925", "20270101"], []))
        self.assertEqual(dash._calendar_run([], now), ([], []))

    def test_a_clock_stepped_back_or_a_stopped_loop_keeps_the_strip_bounded_and_current(self):
        # 2026-09-28 (pre-merge verifier): one row stamped 1970 filled the strip from 1970 (40 MB); and
        # the strip ended at the last logged day, so an outage still under way was not drawn
        now = datetime.datetime(2026, 9, 30, 12, 0, tzinfo=datetime.timezone.utc)
        run, older = dash._calendar_run(["19700101", "20260923", "20260925"], now)
        self.assertEqual((len(run), run[-1], older), (8, "20260930", ["19700101"]))           # 09-23 .. 09-30, today included
        logged = ["19700101"] + [f"202608{d:02d}" for d in range(1, 32)] + [f"202609{d:02d}" for d in range(1, 29)]
        run, older = dash._calendar_run(logged, now)                    # the cap: 35 days ending today
        self.assertEqual((len(run), run[0], run[-1]), (dash.STRIP_DAYS, "20260827", "20260930"))
        self.assertEqual((len(older), older[0], older[-1]), (1 + 26, "19700101", "20260826"))
        # the log ran until 08-26 and then stopped: the whole window is empty cells, not today alone
        run, older = dash._calendar_run([f"202608{d:02d}" for d in range(1, 27)], now)
        self.assertEqual((len(run), run[0], run[-1]), (dash.STRIP_DAYS, "20260827", "20260930"))
        # it ran until 08-26, stopped, and came back on 09-20: the empty in-window days before 09-20 show
        run, _ = dash._calendar_run([f"202608{d:02d}" for d in range(1, 27)] + ["20260920"], now)
        self.assertEqual((len(run), run[0]), (dash.STRIP_DAYS, "20260827"))
        rows = []
        for tick in ("19700101T000000Z", "20260929T100000Z", "20260929T100100Z"):
            r = dict(_row(0))
            r["tick_id"], r["ts_rx"] = tick, f"{tick[:4]}-{tick[4:6]}-{tick[6:8]}T{tick[9:11]}:{tick[11:13]}:00.100Z"
            rows.append(r)
        page = dash.render(rows, outcomes.join(rows), now=now)
        self.assertLess(len(page), 200_000)
        self.assertIn("1 earlier logged day(s), the last 1970-01-01: not drawn", page)
        self.assertIn("2026-09-30 &middot; <b>0</b>/721", page)                                  # today, the loop stopped (12:00: 721 minutes begun)

    def test_the_strip_starts_at_its_floor_when_the_log_ran_within_a_year_before_it(self):
        # 2026-09-28 (round 4): the lookback was 7 days. A loop that ran until 08-18 drew the whole window
        # while it was down, and today alone the moment it came back: 34 empty days vanished with one row.
        # A year still keeps a row from a clock stepped back to 1970 or 2001 from padding the window.
        now = datetime.datetime(2026, 9, 30, 12, 0, tzinfo=datetime.timezone.utc)
        floor = datetime.date(2026, 8, 27)                                  # 35 days ending 09-30
        ymd = lambda d: d.strftime("%Y%m%d")
        whole = [ymd(floor + datetime.timedelta(days=i)) for i in range(dash.STRIP_DAYS)]
        run = lambda days: dash._calendar_run(days, now)[0]
        ran = [f"202607{d:02d}" for d in range(1, 32)] + [f"202608{d:02d}" for d in range(1, 19)]   # 07-01 .. 08-18
        self.assertEqual(run(ran), whole)                                   # still down
        self.assertEqual(run(ran + ["20260930"]), whole)                    # back today: the outage stays drawn
        self.assertEqual(run(ran + ["20260920"]), whole)                    # back on 09-20
        self.assertEqual(run(["19700101"] + ran + ["20260930"]), whole)     # the LAST row before the window decides
        # the boundary: a last row exactly a year before the floor counts, one day more does not
        edge = floor - datetime.timedelta(days=dash.STRIP_LOOKBACK_DAYS)
        self.assertEqual(run([ymd(edge), "20260920"]), whole)
        beyond = ymd(edge - datetime.timedelta(days=1))
        self.assertEqual(run([beyond, "20260920"]), [f"202609{d}" for d in range(20, 31)])
        # no row inside the window: the whole window, whatever the age of the last row, never today alone
        self.assertEqual(run([beyond]), whole)
        self.assertEqual(run(["20260628"]), whole)                          # ended 60 days before the floor
        self.assertEqual(run(["19700101"]), whole)
        # a clock stepped back to 1970 or 2001 is counted, not filled up to
        self.assertEqual(dash._calendar_run(["19700101", "20010101", "20260923"], now),
                         ([f"202609{d}" for d in range(23, 31)], ["19700101", "20010101"]))
        self.assertIn(f"within {dash.STRIP_LOOKBACK_DAYS} days", dash._calendar_run.__doc__)   # the docstring states the rule
        # the page: one row a day 07-01 .. 08-18, then one today
        rows = []
        for d in ran + ["20260930"]:
            r = dict(_row(0))
            r["tick_id"], r["ts_rx"] = f"{d}T100000Z", f"{d[:4]}-{d[4:6]}-{d[6:]}T10:00:00.100Z"
            rows.append(r)
        strip = dash.render(rows, outcomes.join(rows), now=now).split("<div class='strip'>", 1)[1].split("<div class='legend'>", 1)[0]
        self.assertIn("49 earlier logged day(s), the last 2026-08-18: not drawn", strip)
        self.assertIn("<div class='lab'>2026-08-27 &middot; <b>0</b>/1440</div>", strip)
        self.assertEqual(len(re.findall(r"<div class='lab'>\d{4}-\d\d-\d\d ", strip)), dash.STRIP_DAYS)

    def test_no_h1_h2_pair_or_confidence_number(self):
        page = dash.render(self.rows, self.outs, t0=report.tick_epoch("20260923T100000Z"))
        body = page.split("<div class='foot'>")[0]                 # the footer NAMES what the page cannot carry
        for banned in ("H1", "H2", "pair B-C", "mean_S", "Pearson", "Brier", "calibration", "c99", "noultail", "pbuy", "confidence table"):
            self.assertNotIn(banned, body)
        # statically: every report.<name> and every import is on the allowlist, by any spelling; and at
        # run time: the page renders on an answered log with every measurement function tripwired
        assert_health_only(self, os.path.join(REPO, "loop", "dash.py"), ALLOWED_REPORT, ALLOWED_IMPORTS)
        import datetime
        now = datetime.datetime(2026, 9, 23, 10, 42, tzinfo=datetime.timezone.utc)
        props = dash.proposals(os.path.join(REPO, "proposals"))
        args = dict(t0=report.tick_epoch("20260923T100000Z"), now=now, props=props, hb="2026-09-23T10:41:00.000Z")
        page2 = runtime_health_only(self, lambda: dash.render(self.rows, self.outs, **args))
        self.assertEqual(page2, dash.render(self.rows, self.outs, **args))         # the same page, tripwired or not
        # the guard itself catches the spellings a substring scan missed
        for src in ("from . import report as _rp\n", "from loop.report import table\n", "from loop import inference\n",
                    "import loop.report as r\n", "x = getattr(report, 'tab' + 'le')\n", "import importlib\n",
                    "y = vars(report)['h2']\n", "z = report.__dict__\n"):
            p = os.path.join(self.tmp, "mutant.py")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("from . import config, outcomes, report, state\n" + src)
            with self.assertRaises(AssertionError, msg=src):
                assert_health_only(self, p, ALLOWED_REPORT, ALLOWED_IMPORTS)

    def test_t0_from_prereg_and_the_sample_cut(self):
        pin_prereg(self)                                                 # prereg-v1's §11, not the repository's (to be re-sealed for v2)
        self.assertEqual(dash.read_t0(), report.tick_epoch("20260925T214000Z"))
        self.assertIsNone(dash.read_t0(os.path.join(self.tmp, "nope.md")))
        import datetime
        now = datetime.datetime(2026, 9, 23, 10, 42, tzinfo=datetime.timezone.utc)   # never the calendar: the day tile reads it
        page = dash.render(self.rows, self.outs, t0=report.tick_epoch("20260923T102000Z"), now=now)
        self.assertIn("T0 2026-09-23T10:20Z", page)
        self.assertIn('<div class="v">22</div><div class="n">42 in the whole log</div>', page)   # the cut: 10:20 .. 10:41
        self.assertNotIn("(pre-T0)", page)                        # the one UTC day holds T0 itself: not before it
        self.assertIn("<h2>the 28 days</h2>", page)
        self.assertEqual(page.count("<div class='d "), 28)
        self.assertIn("title='d01: 22 ticks", page)
        self.assertIn("title='d02: not yet'", page)
        self.assertIn('<div class="v">1 of 28</div>', page)
        page = dash.render(self.rows, self.outs, t0=report.tick_epoch("20260924T000000Z"), now=now)
        self.assertIn("(pre-T0)", page)
        self.assertIn('<div class="v">not started</div>', page)                     # T0 is 13 h after the clock
        self.assertIn('<div class="v">not started</div>', dash.render(self.rows, self.outs, t0=report.tick_epoch("20991231T000000Z"), now=now))
        self.assertIn('<div class="v">28 of 28 (ended)</div>', dash.render(self.rows, self.outs, t0=report.tick_epoch("20200101T000000Z"), now=now))

    def test_the_last_day_closes_and_a_day_without_live_rows_is_flagged(self):
        t0 = report.tick_epoch("20260925T214000Z")
        rows = []
        for m in range(3 * 1440 + 120):                                 # d01, d02 (no rows), d03, and two hours of d04
            day = m // 1440 + 1
            if day == 2:
                continue
            r = dict(_row(7))
            e = t0 + 60 * m
            r["tick_id"], r["ts_rx"] = report._tick_of(e), f"{report._iso_minute(e)[:16]}:00.100Z"
            rows.append(r)
        now = datetime.datetime.fromtimestamp(t0 + 3 * 86400 + 125 * 60, datetime.timezone.utc)   # just after the log: d03 closed
        page = dash.render(rows, outcomes.join(rows), t0=t0, now=now)
        self.assertIn("<span class='badge crit'>NO LIVE ROWS</span>", page)
        self.assertIn("title='d02: 0 ticks, fill n/a, jev-err n/a, NO LIVE ROWS'", page)
        self.assertIn("<div class='d empty'", page)
        self.assertIn("1 with no live rows", page)
        self.assertIn("<div class='d ok'", page)                       # d01 and d03 closed and fine
        self.assertIn(".map .c.b4 { background: var(--s5)", page)         # the map's bins outrank .map .c (they never showed before)
        self.assertIn("<div class='d open'", page)                     # d04

    def test_a_row_stamped_after_the_clock_closes_no_day_on_the_page(self):
        # dash.render passes its clock to report.health: one row from a forward clock step must not
        # close today (BAD on its pending rows) or list the days before it NO LIVE ROWS
        t0 = report.tick_epoch("20260925T214000Z")
        rows = []
        for m in range(1440 + 20):
            r = dict(_row(7))
            e = t0 + 60 * m
            r["tick_id"], r["ts_rx"] = report._tick_of(e), f"{report._iso_minute(e)[:16]}:00.100Z"
            rows.append(r)
        stray = dict(rows[100], tick_id=report._tick_of(t0 + 4 * 86400), ts_rx="2026-09-29T21:40:00.100Z")
        now = datetime.datetime.fromtimestamp(t0 + 60 * (1440 + 20) + 30, datetime.timezone.utc)
        page = dash.render(rows + [stray], outcomes.join(rows + [stray]), t0=t0, now=now)
        self.assertNotIn("<span class='badge crit'>NO LIVE ROWS</span>", page)
        self.assertNotIn("<div class='d empty'", page)
        self.assertNotIn("<div class='d bad'", page)
        self.assertIn("<div class='d open'", page)                           # d02, still pending

    def test_badge_is_at_render_time_and_never_negative(self):
        import datetime
        now = datetime.datetime(2026, 9, 23, 10, 42, tzinfo=datetime.timezone.utc)
        self.assertEqual(dash._age("2026-09-23T10:41:00.000Z", now), 60.0)
        self.assertEqual(dash._age("2026-09-23T10:43:30.000Z", now), 0.0)   # a heartbeat ahead of the clock
        self.assertIsNone(dash._age("junk", now))
        page = dash.render(self.rows, self.outs, now=now, hb="2026-09-23T10:41:00.000Z")
        self.assertIn('<span class="badge ok">at render 10:42Z: last tick 60 s before</span>', page)
        self.assertIn("heartbeat 2026-09-23T10:41:00.000Z", page)
        page = dash.render(self.rows, self.outs, now=now + datetime.timedelta(hours=5), hb="2026-09-23T10:41:00.000Z")
        self.assertIn('<span class="badge crit">at render 15:42Z: last tick 301 min before</span>', page)
        self.assertIn("no heartbeat", dash.render(self.rows, self.outs, now=now, hb=None))
        self.assertIn("HALT present", dash.render(self.rows, self.outs, now=now, hb="x", halt=True))

    def test_the_badge_goes_crit_one_second_past_three_ticks(self):
        import datetime
        now = datetime.datetime(2026, 9, 23, 10, 44, tzinfo=datetime.timezone.utc)
        self.assertIn('<span class="badge ok">at render 10:44Z: last tick 180 s before</span>',
                      dash.render(self.rows, self.outs, now=now, hb="2026-09-23T10:41:00.000Z"))
        self.assertIn('<span class="badge crit">at render 10:44Z: last tick 3 min before</span>',
                      dash.render(self.rows, self.outs, now=now, hb="2026-09-23T10:40:59.000Z"))

    def test_the_day_tile_turns_at_t0_each_day_and_ends_at_t0_plus_28_days(self):
        import datetime
        t0 = report.tick_epoch("20260923T100000Z")
        at = lambda s: datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M").replace(tzinfo=datetime.timezone.utc)
        for now, want in (("2026-09-23T09:59", "not started"), ("2026-09-23T10:00", "1 of 28"), ("2026-09-24T09:59", "1 of 28"),
                          ("2026-09-24T10:00", "2 of 28"), ("2026-10-21T09:59", "28 of 28"), ("2026-10-21T10:00", "28 of 28 (ended)")):
            with self.subTest(now=now):
                self.assertIn(f'<div class="k">sample day</div><div class="v">{want}</div>',
                              dash.render(self.rows, self.outs, t0=t0, now=at(now)))

    def test_outside_alphabet_words_are_loud(self):
        rows = [dict(_row(m)) for m in range(10)]
        for r in rows[:4]:
            r["adj"] = dict(r["adj"], vol="wild")
        page = dash.render(rows, outcomes.join(rows))
        self.assertIn("OUTSIDE-ALPHABET 40.0%", page)
        self.assertIn("<span class='badge crit'>OUTSIDE-ALPHABET</span> vol", page)
        rows[0]["adj"] = {"liq": "deep"}                                 # a missing key is outside too, and never a crash
        rows[1]["jev"] = "oops"                                          # a foreign row's jev is not a dict
        rows[2]["adj"]["liq"] = ["x"]                                    # unhashable
        page = dash.render(rows, outcomes.join(rows))
        self.assertIn("OUTSIDE-ALPHABET", page)

    def test_main_writes_the_file_and_reports_rows(self):
        pin_v1(self)                                                     # never the live prompts/, heartbeat or HALT
        out = os.path.join(self.tmp, "d", "dash.html")
        with mock.patch.object(config, "HEARTBEAT", os.path.join(self.tmp, "heartbeat")), \
                mock.patch.object(config, "HALT", os.path.join(self.tmp, "HALT")), \
                mock.patch.object(config, "PROPOSALS", os.path.join(self.tmp, "no-proposals")):
            with open(config.HEARTBEAT, "w", encoding="utf-8") as fh:
                fh.write("2026-09-23T10:41:00.100Z\n")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = dash.main(["--log", self.log, "--out", out, "--no-t0"])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(out))
            self.assertIn("42 rows, 1 skipped", buf.getvalue())
            with open(out, encoding="utf-8") as fh:
                page = fh.read()
            self.assertIn("skipped log lines 1", page)                     # main hands the log's skipped lines to the page
            self.assertIn("no T0: whole log", page)
            self.assertIn("prompt_b v1", page)                           # the pinned root, not the live CURRENT
            self.assertIn("heartbeat 2026-09-23T10:41:00.100Z", page)
            self.assertIn("no proposals yet", page)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(dash.main(["--log", os.path.join(self.tmp, "none.jsonl"), "--out", out, "--no-t0"]), 0)

    def test_main_takes_its_roots_from_the_arguments(self):
        # propose.sh --root passes its own data/, proposals/ and (under test) a pinned prompts root,
        # so the nightly's rebuild never reads the repo's heartbeat, HALT or CURRENT (2026-09-28)
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        os.makedirs(os.path.join(root, "data"))
        os.makedirs(os.path.join(root, "proposals"))
        os.makedirs(os.path.join(root, "prompts"))
        with open(os.path.join(root, "data", "heartbeat"), "w", encoding="utf-8") as fh:
            fh.write("2026-09-23T10:41:00.100Z\n")
        with open(os.path.join(root, "data", "HALT"), "w", encoding="utf-8") as fh:
            fh.write("test\n")
        with open(os.path.join(root, "prompts", "CURRENT"), "w", encoding="utf-8") as fh:
            fh.write("v7\n")
        out = os.path.join(root, "dash.html")
        with contextlib.redirect_stdout(io.StringIO()):
            code = dash.main(["--log", self.log, "--out", out, "--no-t0", "--data", os.path.join(root, "data"),
                              "--proposals", os.path.join(root, "proposals"), "--prompts", os.path.join(root, "prompts")])
        self.assertEqual(code, 0)
        with open(out, encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("HALT present", page)
        self.assertIn("heartbeat 2026-09-23T10:41:00.100Z", page)
        self.assertIn("prompt_b v7", page)
        self.assertIn("no proposals yet", page)

    def test_gaps_latency_and_absence_by_day(self):
        rows = [dict(_row(m)) for m in range(42) if m not in (20, 21, 22, 30)]   # a 3-minute hole and an isolated skip
        g = dash.gaps(rows)
        self.assertEqual(g, [{"from": "20260923T102000Z", "to": "20260923T102300Z", "minutes": 3, "day": "20260923"}])
        self.assertEqual(dash.gaps(rows, min_minutes=1)[1]["minutes"], 1)
        t0 = report.tick_epoch("20260923T102000Z")
        self.assertEqual(dash.gaps(rows, t0)[0]["day"], "d01")             # the hole's first minute is d01's
        lat = dash.latency_by_day(rows)
        self.assertEqual(lat["20260923"][2], 38 - 5 - 1)                   # 38 rows, 5 dry, one jev absence
        self.assertEqual(dash.absence_by_day(rows)["20260923"], {"jev": 1})
        page = dash.render(rows, outcomes.join(rows))
        self.assertIn("holes &middot; 1 of 3+ missing minutes, 3 minutes in all", page)
        self.assertIn("<td class='l mono'>20260923T102000Z</td>", page)

    def test_proposals_parse_the_committed_tables_and_a_long_rationale(self):
        props = dash.proposals(os.path.join(REPO, "proposals"))
        for p in props:
            for c in p["candidates"]:
                self.assertNotIn("rationale", c)                  # never on the health page: it quotes the digest's outcomes
        dates = [p["date"] for p in props]
        self.assertTrue(all(re.match(r"^\d{4}-\d{2}-\d{2}$", d) for d in dates))
        if "2026-09-25" in dates:
            p = props[dates.index("2026-09-25")]
            self.assertEqual((p["requests"], p["answered"], p["errors"], p["current"], p["current_vs_rule"], p["current_of"]), (81, 81, 0, "v1", 0, 81))
            self.assertEqual([(c["name"], c["vs_current"], c["vs_rule"]) for c in p["candidates"]],
                             [("cand_0", 0, 0), ("cand_1", 27, 27), ("cand_2", 27, 27)])
        root = os.path.join(self.tmp, "props")
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, "2026-09-30.md"), "w", encoding="utf-8") as fh:
            fh.write("# policy table 2026-09-30\n\nrequests: 81, answered: 79, errors: 2 -- INCOMPLETE  \n\n"
                     "## current (v2)\n\ndiffers from rule_c on 27 of 79 answered states\n\n"
                     "## cand_0\n\nrationale: a first line\nand a second line of it\n\n"
                     "differs from CURRENT on 5 of 79 answered states; from rule_c on 30 of 79\n\n```diff\n```\n")
        p = dash.proposals(root)[0]
        self.assertEqual(p["candidates"], [{"name": "cand_0", "vs_current": 5, "of": 79, "vs_rule": 30}])
        self.assertEqual((p["current"], p["current_vs_rule"], p["current_of"]), ("v2", 27, 79))
        page = dash.render(self.rows, self.outs, props=dash.proposals(root))
        self.assertIn("current v2: 27/79 vs rule_c", page)


class PinnedPrereg(unittest.TestCase):
    """tests/fixture_prereg.pin_prereg: every program reads the repository's PREREG through
    dash.PREREG_PATH, so the pin is the one place a test names a T0, and the repository's own
    PREREG.md (to be re-sealed for prereg-v2 after 2026-10-23) is never opened while it holds."""
    LATER = "20261101T000000Z"                                          # a T0 no real PREREG has had: seen, it came from the pin

    def test_the_default_is_the_repositorys_prereg(self):
        self.assertEqual(dash.PREREG_PATH, os.path.join(config.REPO, "PREREG.md"))

    def test_every_program_reads_the_pin_and_never_the_repositorys_prereg(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        repo_prereg = os.path.realpath(os.path.join(config.REPO, "PREREG.md"))
        real_open = open

        def guarded(file, *a, **k):
            if isinstance(file, (str, bytes, os.PathLike)) and os.path.realpath(file) == repo_prereg:
                raise AssertionError(f"{file} was opened while a PREREG was pinned")
            return real_open(file, *a, **k)
        path = pin_prereg(self, self.LATER)
        pin_v1(self)
        log = os.path.join(tmp, "decisions.jsonl")
        _write(log, [_row(m) for m in range(20)], garbage=False)       # 2026-09-23 10:00 .. 10:19, before any T0 here
        ex = os.path.join(tmp, "exclusions.tsv")
        with open(ex, "w", encoding="utf-8") as fh:
            fh.write("day\tfill%\tjev-err%\treason\n")
        for k, v in (("HALT", "HALT"), ("HEARTBEAT", "heartbeat"), ("PROPOSALS", "proposals"), ("DATA", "data")):
            self.enterContext(mock.patch.object(config, k, os.path.join(tmp, v)))
        self.enterContext(mock.patch("builtins.open", guarded))
        run = _capture                                                  # (main, argv) -> (exit code, stdout)
        self.assertEqual(dash.read_t0(), report.tick_epoch(self.LATER))
        code, out = run(report.main, ["--log", log, "--health", "--sample"])
        self.assertEqual(code, 0)
        self.assertIn("T0 2026-11-01T00:00Z (sample [T0, T0 + 28 d)", out.splitlines()[0])
        code, out = run(status.main, ["--log", log, "--now", "2026-09-28T12:00"])
        self.assertIn("sample: not started (T0 2026-11-01T00:00Z)", out)
        code, out = run(dash.main, ["--log", log, "--out", os.path.join(tmp, "dash.html")])
        with open(os.path.join(tmp, "dash.html"), encoding="utf-8") as fh:
            self.assertIn("T0 2026-11-01T00:00Z", fh.read())
        code, out = run(inference.main, ["--pre-t0", "--log", log, "--resamples", "20", "--exclusions", ex])
        self.assertEqual(code, 0)
        self.assertIn("rows before 2026-11-01T00:00Z (the earlier of --t0 and PREREG §11's T0)", out)
        # blank the pinned §11 and every reader sees an unsealed PREREG
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(prereg_text(None))
        self.assertIsNone(dash.read_t0())
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
            run(report.main, ["--log", log, "--health", "--sample"])
        self.assertEqual(cm.exception.code, 2)
        code, out = run(status.main, ["--log", log, "--now", "2026-09-28T12:00"])
        self.assertIn("sample: no T0", out)


def _strip(page):
    """The hourly strip of a rendered page, its header row to its last cell."""
    return page.split("<div class='strip'>", 1)[1].split("<div class='legend'>", 1)[0]


def _capture(main, argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(argv)
    return code, buf.getvalue()


if __name__ == "__main__":
    unittest.main()

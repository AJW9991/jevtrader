"""loop/dash.py: the health page renders from a log, and can carry no H1/H2/pair/confidence number
because every report.<name> it uses is on an allowlist of section 1-3 functions (PREREG §8.4)."""
import ast, contextlib, io, os, re, shutil, tempfile, unittest
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
                       "<div class='lab'>2026-09-23 &middot; <b>42</b>/1440</div>",   # every fixture row has a mid: 42 priced ticks
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
        page = dash.render(rows, outcomes.join(rows))
        self.assertIn("32/60 priced ticks; absent feed 10", page)
        self.assertIn("absence in the sample: feed 10", page)
        self.assertEqual([dash._bin_hour(n) for n in (0, 1, 29, 30, 44, 45, 54, 55, 59, 60)], [-1, 0, 0, 1, 1, 2, 2, 3, 3, 4])
        self.assertEqual(dash._bin(0, 60), -1)
        self.assertEqual(dash._bin(5, 0), 4)
        self.assertEqual([dash._bin_state(n, 1000) for n in (0, 1, 9, 10, 49, 50, 199, 200, 499, 500, 1000)], [-1, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4])
        self.assertEqual(dash._bin_state(3, 0), 4)

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
        page = dash.render(rows, outcomes.join(rows), t0=t0, now=None)
        self.assertIn("<span class='badge crit'>NO LIVE ROWS</span>", page)
        self.assertIn("title='d02: 0 ticks, fill n/a, jev-err n/a, NO LIVE ROWS'", page)
        self.assertIn("<div class='d empty'", page)
        self.assertIn("1 with no live rows", page)
        self.assertIn("<div class='d ok'", page)                       # d01 and d03 closed and fine
        self.assertIn(".map .c.b4 { background: var(--s5)", page)         # the map's bins outrank .map .c (they never showed before)
        self.assertIn("<div class='d open'", page)                     # d04

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
        for k, v in (("HALT", "HALT"), ("HEARTBEAT", "heartbeat"), ("PROPOSALS", "proposals")):
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


def _capture(main, argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(argv)
    return code, buf.getvalue()


if __name__ == "__main__":
    unittest.main()

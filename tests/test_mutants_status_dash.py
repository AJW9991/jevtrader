"""loop/status.py and loop/dash.py, the rules the other suites left open: the clock boundaries
(a stale heartbeat, the nightly's slot, the T0-anchored sample day and the sample's end), the
sample's last day closing on rows after the cut, and the dash's numbers, not only its headings
(spend, latency, coverage, holes, the state map, occupancy, the nightly table). Offline; every
config path a render or a main can reach points into a temp dir, and no test reads prompts/."""
import contextlib, datetime, html, io, os, re, tempfile, unittest
from unittest import mock

from fixture_prompts import pin_v1
from loop import config, dash, outcomes, report, state, status
from test_report import _row

UTC = datetime.timezone.utc
T0 = report.tick_epoch("20260923T100000Z")          # the first fixture row
FIX = [_row(m) for m in range(42)]                   # 2026-09-23 10:00 .. 10:41 (test_report._row)
TILE = re.compile(r'<div class="tile( crit)?"><div class="k">([^<]*)</div><div class="v">([^<]*)</div><div class="n">([^<]*)</div></div>')


def _dt(s):
    fmt = "%Y-%m-%dT%H:%M:%S" if s.count(":") == 2 else "%Y-%m-%dT%H:%M"
    return datetime.datetime.strptime(s, fmt).replace(tzinfo=UTC)


def _ep(e):
    return datetime.datetime.fromtimestamp(e, UTC)


def _at(epoch, m=7, **over):
    """_row(m) (m = 7: live, answered, priced, 1000 tokens) moved to the tick at `epoch`."""
    r = _row(m)
    r["tick_id"], r["ts_rx"] = report._tick_of(epoch), _ep(epoch).strftime("%Y-%m-%dT%H:%M:%S.100Z")
    r.update(over)
    return r


def _tiles(page):
    return {k: (bool(c), v, n) for c, k, v, n in TILE.findall(page)}


def _between(page, start, end):
    return page.split(start, 1)[1].split(end, 1)[0]


class _Isolated(unittest.TestCase):
    """report.health checks config.HALT, render's footer names config.DECISIONS, and main reads
    config.HEARTBEAT / PROPOSALS / REPO: all of them point into a temp dir for every test."""

    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        for name in ("HALT", "HEARTBEAT", "DECISIONS", "PROPOSALS"):
            self.enterContext(mock.patch.object(config, name, os.path.join(self.tmp, name.lower())))

    def _render(self, rows, **kw):
        return dash.render(rows, outcomes.join(rows), **kw)

    def _props(self, name, files):
        root = os.path.join(self.tmp, name)
        os.makedirs(root)
        for f, text in files.items():
            with open(os.path.join(root, f), "w", encoding="utf-8") as fh:
                fh.write(text)
        return root


class StatusClocks(_Isolated):
    def test_a_heartbeat_is_stale_only_past_three_ticks(self):
        # status.py STALE_S: a heartbeat older than three ticks (3 x CADENCE_S = 180 s) is a stopped loop, not a slow one
        hb = "2026-09-23T10:41:00.100Z"
        self.assertEqual(status._age_line(hb, _dt("2026-09-23T10:44")), f"ticking: last tick 180 s ago ({hb})")
        self.assertEqual(status._age_line(hb, _dt("2026-09-23T10:44:01")),
                         f"STOPPED? last tick 3 min ago ({hb}); a healthy loop is under 180 s")
        self.assertIn("STOPPED? last tick 31 min ago", status._age_line(hb, _dt("2026-09-23T11:12")))

    def test_the_nightly_slot_turns_at_11z(self):
        # status.py NIGHTLY_DONE_UTC_H: the nightly starts 08:30Z (CDT) or 09:30Z (CST) and its call may run 45 min,
        # so by 11Z yesterday's proposal exists; before that the day before's is the latest one expected
        props = self._props("p", {"2026-09-22.md": "x\n"})
        no_log = os.path.join(self.tmp, "no.log")
        self.assertNotIn("MISSING", status._nightly_lines(props, no_log, _dt("2026-09-24T10:59"))[0])
        self.assertIn("MISSING: no proposal for 2026-09-23 yet", status._nightly_lines(props, no_log, _dt("2026-09-24T11:00"))[0])

    def test_the_latest_proposal_is_a_bare_date_from_tables_or_json_alone(self):
        # HANDOFF "Tooling": make status names the newest proposal; *.json is gitignored, so tables alone (or a json alone) count
        now, no_log = _dt("2026-09-23T12:00"), os.path.join(self.tmp, "no.log")
        tables = self._props("md", {"2026-09-21.md": "x\n", "2026-09-22.md": "x\n"})
        jsons = self._props("js", {"2026-09-23.json": "{}\n"})
        mixed = self._props("mix", {"2026-09-22.md": "x\n", "2026-09-23.json": "{}\n"})
        self.assertEqual(status._nightly_lines(tables, no_log, now)[0], "nightly: 2 tables, 0 proposal files in proposals/; latest 2026-09-22")
        self.assertEqual(status._nightly_lines(jsons, no_log, now)[0], "nightly: 0 tables, 1 proposal files in proposals/; latest 2026-09-23")
        self.assertEqual(status._nightly_lines(mixed, no_log, now)[0], "nightly: 1 tables, 1 proposal files in proposals/; latest 2026-09-23")

    def test_only_the_last_three_lines_of_propose_log_are_shown(self):
        # HANDOFF "Tooling": make status shows the tail of propose.log (status.LOG_TAIL = 3 lines), not the whole file
        plog = os.path.join(self.tmp, "propose.log")
        with open(plog, "w", encoding="utf-8") as fh:
            fh.write("".join(f"line {i}\n" for i in range(6)))
        out = status._nightly_lines(self._props("p", {"2026-09-22.md": "x\n"}), plog, _dt("2026-09-23T12:00"))
        self.assertEqual(out[1:], ["  line 3", "  line 4", "  line 5"])

    def test_the_sample_day_turns_on_t0_anchored_boundaries_and_d28_is_still_the_sample(self):
        # PREREG §2: day j = [T0 + 86400(j-1), T0 + 86400 j); the sample is days 1-28 and ends at T0 + 28 days, not a day earlier
        t0 = report.tick_epoch("20260925T214000Z")
        tail = "of 28 (T0 2026-09-25T21:40Z, ends 2026-10-23T21:40Z)"
        self.assertEqual(status._sample_line(t0, _ep(t0 + 86400 - 1)), f"sample: day d01 {tail}")
        self.assertEqual(status._sample_line(t0, _ep(t0 + 86400)), f"sample: day d02 {tail}")
        self.assertEqual(status._sample_line(t0, _ep(t0 + 27 * 86400)), f"sample: day d28 {tail}")
        self.assertEqual(status._sample_line(t0, _ep(t0 + 28 * 86400 - 1)), f"sample: day d28 {tail}")
        self.assertTrue(status._sample_line(t0, _ep(t0 + 28 * 86400)).startswith("sample: ended 2026-10-23T21:40Z;"))

    def test_today_counts_rows_against_the_minutes_since_midnight(self):
        # HANDOFF "Tooling": make status shows today's rows against the minutes elapsed, one tick a minute (config.CADENCE_S)
        line = status._today_line([_at(report.tick_epoch("20260923T000000Z"))], _dt("2026-09-23T00:01"), os.path.join(self.tmp, "none.jsonl"))
        self.assertTrue(line.startswith("today 2026-09-23Z: 1 rows in 1 min (100%), live answered 1, absence none;"), line)

    def test_halt_line_reads_config_halt_when_called(self):
        # status.py docstring: the screen reads data/HALT (config.HALT, resolved at call time, as dash.heartbeat resolves config.HEARTBEAT)
        self.assertEqual(status._halt_line(), "HALT absent: sends allowed")
        with open(config.HALT, "w", encoding="utf-8") as fh:
            fh.write("prereg: 3 bad days\n")
        self.assertIn(": prereg: 3 bad days -- nothing is sent", status._halt_line())

    def test_main_without_now_reads_the_clock_and_an_absent_heartbeat(self):
        # status.py usage line: `python3 -m loop.status` with no --now is the Mac's `make status`; an absent data/heartbeat reads "no heartbeat"
        pin_v1(self)
        self.assertIsNone(dash.heartbeat(os.path.join(self.tmp, "absent")))
        buf = io.StringIO()
        with mock.patch.object(config, "REPO", self.tmp), contextlib.redirect_stdout(buf):
            before = datetime.datetime.now(UTC)
            code = status.main(["--log", os.path.join(self.tmp, "none.jsonl"), "--t0", "2026-09-25T21:40"])
            after = datetime.datetime.now(UTC)
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn(re.search(r"status at (\S+) ", out).group(1), {before.strftime("%Y-%m-%dT%H:%MZ"), after.strftime("%Y-%m-%dT%H:%MZ")})
        self.assertIn("STOPPED? no heartbeat (data/heartbeat absent or empty", out)
        self.assertIn("prompt_b CURRENT: v1;", out)


class LastDayCloses(_Isolated):
    def test_the_samples_last_day_closes_on_rows_after_the_cut(self):
        # report.days_table / status._days_lines docstrings: the sample's rows with the WHOLE log's last tick, so d28 can close (HANDOFF "Watch")
        t0 = report.tick_epoch("20260925T214000Z")
        end = t0 + 28 * 86400
        rows = [_at(end + 60 * k) for k in range(-30, 30)]             # d28's last 30 minutes and 30 after the sample
        outs = outcomes.join(rows)
        d28 = [l for l in status._days_lines(rows, outs, t0) if l.startswith("  d28")]
        self.assertEqual(len(d28), 1)
        self.assertTrue(d28[0].endswith("  ok"), d28[0])
        page = dash.render(rows, outs, t0=t0, now=_ep(end + 1800))
        self.assertIn("<div class='d ok' title='d28: 30 ticks, fill 100.0%, jev-err 0.0%, ok'>28</div>", page)


class DashHelpers(_Isolated):
    def test_bin_reads_fifths_of_top_closed_above(self):
        # dash._bin docstring: 0 -> -1 (empty); else 0..4 by share of `top`, so a full hour and a full cell read darkest
        self.assertEqual([dash._bin(n, 60) for n in (1, 12, 13, 24, 25, 36, 37, 48, 49, 60, 120)], [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4])

    def test_vbars_heights_are_shares_of_top_and_every_bar_is_labelled(self):
        # dash._vbars docstring: items = [(label, value, title, crit)], heights as a share of `top`; CSS only
        items = [("07", 0.125, "a", False), ("08", None, "b", True), ("09", 0.001, "c", False)]
        self.assertEqual(dash._vbars(items, 0.25),
                         "<div class='vb'>"
                         "<div class='vbc' title='a'><div class='vbar' style='height:50%'></div><div class='vbl'>07</div></div>"
                         "<div class='vbc' title='b'><div class='vbar crit' style='height:0%'></div><div class='vbl'>08</div></div>"
                         "<div class='vbc' title='c'><div class='vbar' style='height:2%'></div><div class='vbl'>09</div></div>"
                         "</div>")
        self.assertEqual(re.findall(r"<div class='vbl'>([^<]*)</div>", dash._vbars(items, 0.25, 2)), ["07", "", "09"])

    def test_short_bar_labels(self):
        # dash._short docstring: 'd07' -> '07', '20260927' -> '27'
        self.assertEqual([dash._short(d) for d in ("d07", "d28", "20260927")], ["07", "28", "27"])

    def test_mini_bar_is_crit_only_below_its_threshold(self):
        # PREREG §8.3: a day is BAD when fill is < 95% (dash._mbar: "crit (red) below a threshold"), so a share AT it is not
        self.assertEqual(dash._mbar(None), "")
        self.assertEqual(dash._mbar(0.95, report.BAD_FILL), "<span class='mb'><i style='width:95.0%'></i></span>")
        self.assertEqual(dash._mbar(0.9, report.BAD_FILL), "<span class='mb crit'><i style='width:90.0%'></i></span>")
        self.assertEqual(dash._mbar(0.97, None, 0.97), "<span class='mb'><i style='width:97.0%'></i></span>")
        self.assertEqual(dash._mbar(0.96, None, 0.97), "<span class='mb warn'><i style='width:96.0%'></i></span>")

    def test_absent_heartbeat_and_current_read_none(self):
        # dash.heartbeat / current_version: an absent file is None ("no heartbeat", "?"), never a value
        self.assertIsNone(dash.heartbeat(os.path.join(self.tmp, "absent")))
        self.assertIsNone(dash.current_version(os.path.join(self.tmp, "no-prompts")))

    def test_the_heartbeat_age_counts_its_seconds(self):
        # cycle._heartbeat: data/heartbeat is the row's ts_rx, so its age is taken to the second
        self.assertEqual(dash._age("2026-09-23T10:41:07.100Z", _dt("2026-09-23T10:42")), 53.0)
        self.assertEqual(status._age_line("2026-09-23T10:41:07.100Z", _dt("2026-09-23T10:42")), "ticking: last tick 53 s ago (2026-09-23T10:41:07.100Z)")


class DashPage(_Isolated):
    def test_the_badge_turns_crit_only_past_three_ticks(self):
        # status.STALE_S and the dash badge agree: a heartbeat older than 3 x CADENCE_S = 180 s is a stopped loop
        now = _dt("2026-09-23T10:44")
        self.assertIn('<span class="badge ok">at render 10:44Z: last tick 180 s before</span>',
                      self._render(FIX, now=now, hb="2026-09-23T10:41:00.000Z"))
        self.assertIn('<span class="badge crit">at render 10:44Z: last tick 3 min before</span>',
                      self._render(FIX, now=now, hb="2026-09-23T10:40:59.000Z"))

    def test_the_hourly_strip_has_24_hours_and_a_short_hour_is_pale_not_empty(self):
        # dash._bin_hour docstring: 1-29 priced ticks is bin 0 (a pale cell), 0 is empty; the strip is one cell per UTC hour
        strip = _between(self._render(FIX[:10], now=_dt("2026-09-23T12:00")), "<div class='strip'>", "<div class='legend'>")   # the day itself: one line
        self.assertEqual(re.findall(r"<div class='hr'>(\d+)</div>", strip), [f"{h:02d}" for h in range(24)])
        self.assertEqual(strip.count("<div class='cell"), 24)
        self.assertIn("<div class='cell b0' title='2026-09-23 10:00Z: 10/60 priced ticks'></div>", strip)

    def test_sample_day_tile_counts_t0_anchored_days(self):
        # PREREG §2: day j = [T0 + 86400(j-1), T0 + 86400 j); the sample is days 1-28
        def tile(s):
            return _tiles(self._render(FIX, t0=T0, now=_ep(T0 + s)))["sample day"]
        self.assertEqual(tile(12 * 3600), (False, "1 of 28", "days from T0"))
        self.assertEqual(tile(86400)[1], "2 of 28")
        self.assertEqual(tile(28 * 86400 - 1)[1], "28 of 28")
        self.assertEqual(tile(28 * 86400)[1], "28 of 28 (ended)")
        self.assertEqual(_tiles(self._render(FIX))["sample day"], (False, "-", "no T0"))

    def test_coverage_since_t0_is_priced_ticks_per_minute_elapsed_capped_at_100(self):
        # dash tile "coverage since T0": priced ticks per minute elapsed since T0, to the sample's end (PREREG §2), never above 100%
        def cov(rows, t0, now):
            return _tiles(self._render(rows, t0=t0, now=now))["coverage since T0"][1]
        self.assertEqual(cov(FIX, T0, _dt("2026-09-23T11:00")), "70.0%")             # 42 priced ticks in 60 minutes
        self.assertEqual(cov(FIX, T0, _dt("2026-09-23T10:41:30")), "100.0%")          # 42 in 41.5 minutes: capped
        self.assertEqual(cov(FIX, T0, _ep(T0)), "n/a")                                # at T0 nothing has elapsed
        self.assertEqual(cov(FIX, report.tick_epoch("20260923T104100Z"), _dt("2026-09-23T10:42")), "100.0%")   # 1 tick, 1 minute
        base = _at(T0)
        rows = [dict(base, tick_id=report._tick_of(T0 + 60 * k), ts_rx=_ep(T0 + 60 * k).strftime("%Y-%m-%dT%H:%M:%S.100Z")) for k in range(3649)]
        self.assertEqual(cov(rows, T0, _ep(T0 + 30 * 86400)), "9.1%")                 # after the sample: 3649 / (28 x 1440)

    def test_key_drift_version_and_fill_tiles_carry_their_numbers(self):
        # CONTRACT §4.1: health names the key that answered (SHARED KEY, PROTOCOL §3.6), model_answered and drift, prompt_b versions, fill
        tiles = _tiles(self._render(FIX, t0=T0, now=_dt("2026-09-23T11:00")))
        self.assertEqual(tiles["key answering"], (False, "loop key", "TYPESAFE_API_KEY_LOOP 37"))
        self.assertEqual(tiles["drift"], (True, "1", f"{config.MODEL} 35, jev-1.14.0 1"))
        self.assertEqual(tiles["prompt_b versions"], (False, "v1 32, v2 10", "rows per wording in the sample"))
        self.assertEqual(tiles["stop-rule fill"][:2], (False, "100.0%"))
        shared = [dict(r, jev=dict(r["jev"], key_path="env:TYPESAFE_API_KEY" if r["jev"]["key_path"] else None)) for r in FIX]
        self.assertEqual(_tiles(self._render(shared))["key answering"], (True, "SHARED KEY", "TYPESAFE_API_KEY 37"))
        self.assertEqual(_tiles(self._render(FIX[:5]))["key answering"], (False, "-", "none"))   # dry rows only: no key answered

    def test_stop_rule_tiles_turn_crit_only_past_the_thresholds(self):
        # PREREG §8.3: BAD when fill is < 95% or the jev error share is > 5%; exactly 95% and exactly 5% are neither
        t = report.tick_epoch("20260923T100000Z")
        fill95 = [_at(t + 60 * k) for k in range(36) if k != 16]      # row 1's t + 15 is the missing minute: 19 of 20 decided rows fill
        page = self._render(fill95)
        self.assertEqual(_tiles(page)["stop-rule fill"][:2], (False, "95.0%"))
        self.assertIn("<td><span class='mb'><i style='width:95.0%'></i></span>95.0%</td>", page)
        err5 = [_at(t + 60 * k, m=15 if k == 10 else 7) for k in range(20)]     # 1 jev absence in 20 attempted sends
        self.assertEqual(_tiles(self._render(err5))["jev errors"][:2], (False, "5.0%"))

    def test_spend_per_day_is_the_logged_input_tokens_at_the_configured_rate(self):
        # the dash's spend section: "input tokens the rows logged, at the configured rate" (config.USD_PER_MTOK per million)
        d1, d2 = report.tick_epoch("20260923T100000Z"), report.tick_epoch("20260924T100000Z")
        rows = [_at(d1 + 60 * k) for k in range(36)] + [_at(d2 + 60 * k) for k in range(5)]
        rows.append(_at(d2 + 300, jev=dict(rows[-1]["jev"], input_tokens=1)))
        self.assertEqual(dash.spend_by_day(rows), {"20260923": 36000 * config.USD_PER_MTOK / 1e6, "20260924": 5001 * config.USD_PER_MTOK / 1e6})
        page = self._render(rows, now=_dt("2026-09-24T11:00"))
        limit = f"{config.DAILY_SPEND_HALT_USD:g}"                                           # $0.25 a product
        self.assertIn(f"<h2>spend per day &middot; max $0.0015, tripwire ${limit}</h2>", page)
        self.assertEqual(_tiles(page)["spend, whole log"], (False, "$0.0017", f"$0.0009 per logged day; tripwire ${limit}/day"))

    def test_latency_chart_and_column_show_each_days_p95(self):
        # CONTRACT §4.1 latency p95, per day (dash.latency_by_day: day -> (mean, p95, n)); the chart's heading names the tallest bar
        d2 = report.tick_epoch("20260924T100000Z")
        rows = FIX + [_at(d2 + 60 * k, jev=dict(_row(7)["jev"], latency_ms=50)) for k in range(5)]
        page = self._render(rows, now=_dt("2026-09-24T11:00"))
        self.assertIn("<h2>jev latency p95 per day &middot; tallest bar 140 ms</h2>", page)
        table = _between(page, "PREREG §8 stop rule 3</h2>", "<h2>spend per day")
        self.assertEqual(re.findall(r"<td>(\d+) ms</td>", table), ["140", "50"])

    def test_holes_are_listed_longest_first_ten_shown_and_the_rest_counted(self):
        # dash.gaps docstring: holes longest first; the page lists GAPS_SHOWN = 10 of them and counts the shorter rest
        def log(lengths):
            rows, e = [], T0
            for n in lengths + [0]:
                rows.append(_at(e))
                e += 60 * (n + 1)
            return rows
        rows = log(list(range(3, 15)))                                  # twelve holes, 3..14 minutes, shortest first in time
        self.assertEqual([g["minutes"] for g in dash.gaps(rows)], list(range(14, 2, -1)))
        holes = _between(self._render(rows), "<h2>holes", "<h2>adjective occupancy")
        self.assertEqual(re.findall(r"<td>(\d+)</td></tr>", holes), [str(n) for n in range(14, 4, -1)])
        self.assertIn("<tr><td colspan='4' class='l'>and 2 shorter ones</td></tr>", holes)
        holes = _between(self._render(log(list(range(3, 13)))), "<h2>holes", "<h2>adjective occupancy")
        self.assertEqual(len(re.findall(r"<td>(\d+)</td></tr>", holes)), 10)
        self.assertNotIn("shorter ones", holes)

    def test_the_state_map_counts_rows_per_state_and_shades_by_the_busiest(self):
        # dash docstring and the map's legend: the number is rows seen per state, the shade its share of the busiest (_bin_state: > 0 is bin 0)
        busy = {"liq": "deep", "flow": "organic", "trend": "flat", "vol": "normal"}
        rare = {"liq": "thin", "flow": "quiet", "trend": "dumping", "vol": "calm"}
        rows = [_at(T0 + 60 * k, adj=dict(busy), state=state.state_string(busy)) for k in range(101)]
        rows.append(_at(T0 + 60 * 101, adj=dict(rare), state=state.state_string(rare)))
        wild = _at(T0 + 60 * 102, adj=dict(busy, vol="wild"))
        self.assertEqual(dash.state_counts(rows + [wild]), {tuple(busy[d] for d in state.DIMS): 101, tuple(rare[d] for d in state.DIMS): 1})
        page = self._render(rows)
        self.assertIn(f"<div class='c b4' title='{html.escape(state.state_string(busy))}: 101 rows (99.0%), rule_c hold'><i>H</i><b>101</b></div>", page)
        self.assertIn(f"<div class='c b0' title='{html.escape(state.state_string(rare))}: 1 rows (1.0%), rule_c sell'><i>S</i><b>1</b></div>", page)

    def test_occupancy_bars_and_legend_carry_every_share_and_the_flag(self):
        # CONTRACT §4.2: adjective occupancy per dimension, any word > 95% flagged; a word outside the alphabet is loud (report §2)
        rows = [_row(m) for m in range(10)]
        for r in rows[:4]:
            r["adj"] = dict(r["adj"], vol="wild")
        page = self._render(rows)
        for needle in ("<span class='b2' style='width:60.00%' title='vol normal: 60.0%'></span>",
                       "<span><i class='sw b2'></i>normal 60.0%</span>",
                       "<span class='out' style='width:40.00%' title='vol: OUTSIDE-ALPHABET 40.0%'></span>",
                       "<span><i class='sw out'></i>OUTSIDE-ALPHABET 40.0%</span>",
                       "<p class='sub'><span class='badge warn'>FLAG</span> liq is deep above 95%: a constant</p>"):
            self.assertIn(needle, page)

    def test_the_per_day_table_says_when_the_sample_has_no_rows(self):
        # PREREG §8 stop rule 3's per-day table: an empty sample says so, a sample with days does not
        empty = "<tr><td colspan='12'>no rows in the sample yet</td></tr>"
        self.assertIn(empty, self._render(FIX, t0=report.tick_epoch("20991231T000000Z")))
        self.assertNotIn(empty, self._render(FIX))

    def test_the_test_retest_line_reaches_the_page(self):
        # CONTRACT §4.3 / dash docstring: the page is report §1-§3, test-retest's agreement included
        retest = _between(self._render(FIX), "<h2>test-retest", "<h2>the nightly")
        self.assertIn("rows with prompt_a_sha == prompt_b_sha and both answers: 26 &middot;", retest)
        self.assertIn("choice agreement 23/26 (88.5%)", retest)

    def test_headings_and_footer_follow_t0_and_the_log(self):
        # report.day_of: T0-anchored days with a T0, UTC calendar days without; the footer names the log the page was built from
        with_t0 = self._render(FIX, t0=T0, log="/x/decisions.jsonl")
        self.assertIn("<h2>per day from T0 &middot; PREREG §8 stop rule 3</h2>", with_t0)
        self.assertIn("Log: /x/decisions.jsonl. ", with_t0)
        no_t0 = self._render(FIX)
        self.assertIn("<h2>per UTC day &middot; PREREG §8 stop rule 3</h2>", no_t0)
        self.assertIn(f"Log: {html.escape(config.DECISIONS)}. ", no_t0)


class DashNightly(_Isolated):
    CUR = "# policy table {d}\n\nrequests: 81, answered: {a}, errors: {e}  \n\n## current (v2)\n\ndiffers from rule_c on 27 of {a} answered states\n"

    def _cand(self, name, vs_cur, vs_rule):
        return (f"\n## {name}\n\nrationale: a line\n\ndiffers from CURRENT on {vs_cur} of 81 answered states; from rule_c on {vs_rule} of 81\n\n"
                "```diff\n```\n")

    def test_the_nightly_table_shows_sends_current_and_no_op_candidates(self):
        # CONTRACT (nightly): per candidate, the count of states where it differs from CURRENT and from rule_c; the header's requests/answered/errors
        root = self._props("props", {
            "2026-09-28.md": "# policy table 2026-09-28\n\nnothing parsed here\n",
            "2026-09-29.md": self.CUR.format(d="2026-09-29", a=79, e=2),
            "2026-09-30.md": self.CUR.format(d="2026-09-30", a=81, e=0) + self._cand("cand_0", 0, 27) + self._cand("cand_1", 5, 30)})
        page = self._render(FIX, props=dash.proposals(root))
        for needle in ("<tr><td class='l'>2026-09-28</td><td>-</td><td class='l' colspan='3'>no candidates parsed</td></tr>",
                       "<tr><td class='l'>2026-09-29</td><td>79/81, 2 err</td><td class='l' colspan='3'>current v2: 27/79 vs rule_c</td></tr>",
                       "<tr><td class='l'>2026-09-30<br><span class='mono'>current v2: 27/81 vs rule_c</span></td><td>81/81</td>"
                       "<td class='l'>cand_0 <span class='badge warn'>no-op</span></td><td>0/81</td><td>27/81</td></tr>",
                       "<tr><td></td><td></td><td class='l'>cand_1</td><td>5/81</td><td>30/81</td></tr>"):
            self.assertIn(needle, page)
        self.assertEqual(page.count("no-op</span>"), 1)

    def test_proposals_skip_an_unreadable_file_and_a_section_without_counts(self):
        # CONTRACT (nightly): loop.dash rebuilds data/dash.html every night whatever happened, so a bad table is skipped, never a crash
        root = self._props("props", {"2026-09-30.md": self.CUR.format(d="2026-09-30", a=81, e=0) + "\n## cand_0\n\nrationale: cut short\n"
                                     + self._cand("cand_1", 5, 30)})
        os.makedirs(os.path.join(root, "2026-09-29.md"))                    # sorts first and cannot be read as a file
        props = dash.proposals(root)
        self.assertEqual([p["date"] for p in props], ["2026-09-30"])
        self.assertEqual(props[0]["candidates"], [{"name": "cand_1", "vs_current": 5, "of": 81, "vs_rule": 30}])


if __name__ == "__main__":
    unittest.main()

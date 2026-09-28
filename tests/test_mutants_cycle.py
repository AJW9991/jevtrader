"""loop.cycle: behaviours a mutation run of cycle.py showed that no test held.

Each test is the smallest one that holds the code to a written rule, named in the comment
above it. Offline like test_cycle: urllib.request.urlopen raises unless a test hands it a
reply, config.JEV_URL points at 127.0.0.1:9, every data path in config points into a temp
dir, feed.snapshot returns the fixture snapshot, the prompts are pinned to v1
(fixture_prompts.pin_v1), and time.time / time.sleep are pinned. Signals are raised
in-process at the moment a mock is reached, so main()'s handlers run exactly where a real
alarm or SIGTERM would land; nothing waits on a real clock."""
import io, json, os, signal, tempfile, time, unittest
from unittest import mock
from fixture_prompts import pin_v1
from loop import config, cycle, feed, jev, outcomes, prompts, state

FIX = os.path.join(config.REPO, "fixtures")


def _load(n):
    with open(os.path.join(FIX, n), encoding="utf-8") as fh:
        return json.load(fh)


META = _load("meta.json")
NOW = float(META["ts_rx_epoch"])                     # 2026-09-24T02:28:49Z
TS_RX = "2026-09-24T02:28:49.000Z"
TICK = "20260924T022800Z"
NEXT_TICK = "20260924T022900Z"
DAY = "20260924"
STATE = "SOL: liquidity deep, flow quiet, trend pumping, vol normal"
SNAP = feed.assemble(META["product"], NOW, _load("book.json"), _load("candles.json"),
                     _load("trades.json"), {"calls": 3, "ms": 600})
KEY = "unit-test-key-not-real-0000"
URL = "http://127.0.0.1:9/v1/systemone"
ANSWERS = {"a_action": {"choice": "buy", "probabilities": {"buy": 0.7, "sell": 0.1, "hold": 0.2},
                        "confidence": 0.72},
           "b_action": {"choice": "hold", "probabilities": {"buy": 0.3, "sell": 0.1, "hold": 0.6},
                        "confidence": 0.55},
           "skip": {"noul": 0.1}, "up15": {"noul": 0.6}, "down15": {"noul": 0.05}}
OVER = 3_000_000                                     # x2 rows = $0.252, over the $0.25 tripwire


def _usd(tokens):
    return tokens * config.USD_PER_MTOK / 1e6


def _row(tick_id, tokens, mode="live", absence=None, error=None):
    """A minimal earlier row for the spend guard: what it reads is tick_id, mode, absence and jev."""
    return {"v": 1, "tick_id": tick_id, "ts_rx": TS_RX, "mode": mode, "absence": absence,
            "jev": {"latency_ms": 500, "input_tokens": tokens, "error": error, "key_path": "env:X"}}


class _Resp:
    def __init__(self, doc):
        self._b = json.dumps(doc).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


class CycleMutantsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.data = os.path.join(self.tmp, "data")            # absent, like a fresh clone
        paths = {"DECISIONS": "decisions.jsonl", "SENDS": "sends.tsv", "HALT": "HALT",
                 "LOCK": "loop.lock", "HEARTBEAT": "heartbeat"}
        self.enterContext(mock.patch.object(config, "DATA", self.data))
        for k, v in paths.items():
            self.enterContext(mock.patch.object(config, k, os.path.join(self.data, v)))
        self.spec = os.path.join(self.tmp, "SPEC.md")         # absent unless a test makes it
        self.enterContext(mock.patch.object(config, "SPEC", self.spec))
        self.enterContext(mock.patch.object(config, "JEV_URL", URL))
        self.enterContext(mock.patch.dict(os.environ, {"TYPESAFE_API_KEY_LOOP": KEY}))
        protocol = os.path.join(self.tmp, "PROTOCOL.md")
        with open(protocol, "w", encoding="utf-8") as fh:
            fh.write("In force from: `2026-09-24`  Signed: `test`\n")
        self.enterContext(mock.patch.object(config, "PROTOCOL", protocol))
        self.prompts_root = pin_v1(self)                      # never the live prompts/
        self.urlopen = self.enterContext(mock.patch("urllib.request.urlopen",
                                                    side_effect=AssertionError("urlopen was reached")))
        self.snapshot = self.enterContext(mock.patch.object(feed, "snapshot", return_value=SNAP))
        self.enterContext(mock.patch("time.time", return_value=NOW))
        self.sleeps = []
        self.enterContext(mock.patch("time.sleep", side_effect=self.sleeps.append))
        self.err = self.enterContext(mock.patch("sys.stderr", new_callable=io.StringIO))
        self.out = self.enterContext(mock.patch("sys.stdout", new_callable=io.StringIO))
        cycle._SIG.update(term=False, critical=False)          # main() resets it; the write_row tests do not call main()
        self.addCleanup(cycle._SIG.update, term=False, critical=False)

    # ---- helpers ------------------------------------------------------------------------
    def rows(self):
        if not os.path.exists(config.DECISIONS):
            return []
        bad = []
        rows = outcomes.load(config.DECISIONS, bad)
        self.assertEqual(bad, [])
        return rows

    def only_row(self):
        rows = self.rows()
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def assert_nothing_sent(self):
        self.urlopen.assert_not_called()
        self.assertFalse(os.path.exists(config.SENDS))

    def write_log(self, rows):
        os.makedirs(self.data, exist_ok=True)
        with open(config.DECISIONS, "w", encoding="utf-8") as fh:
            fh.writelines(json.dumps(r) + "\n" for r in rows)

    def forever(self, argv, on_sleep=None, stop_at=2):
        """main(argv) with --forever's clock advanced by each sleep; SIGTERM lands in sleep
        number `stop_at` (a stop for a mutant that would otherwise loop). Returns the exit."""
        clock = [NOW]

        def sleep(s):
            self.sleeps.append(s)
            if on_sleep:
                on_sleep()
            clock[0] += s
            if len(self.sleeps) >= stop_at:
                signal.raise_signal(signal.SIGTERM)
        self.snapshot.side_effect = lambda: dict(SNAP, ts_rx=cycle.iso_ms(clock[0]))
        with mock.patch("time.time", side_effect=lambda: clock[0]), mock.patch("time.sleep", side_effect=sleep):
            return cycle.main(argv)

    def once_at(self, second, heartbeat):
        """--dry --once started `second` s into 02:28 with data/heartbeat = `heartbeat`;
        returns (sleeps, the row's tick_id)."""
        os.makedirs(self.data, exist_ok=True)
        with open(config.HEARTBEAT, "w", encoding="utf-8") as fh:
            fh.write(heartbeat + "\n")
        clock = [NOW - 49 + second]

        def sleep(s):
            self.sleeps.append(s)
            clock[0] += s
        self.snapshot.side_effect = lambda: dict(SNAP, ts_rx=cycle.iso_ms(clock[0]))
        with mock.patch("time.time", side_effect=lambda: clock[0]), mock.patch("time.sleep", side_effect=sleep):
            self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        return [round(s, 6) for s in self.sleeps], self.rows()[-1]["tick_id"]

    def _symlinked(self):
        real = os.path.join(self.tmp, "forbidden-real")
        os.makedirs(os.path.join(real, "sub"))
        link = os.path.join(self.tmp, "forbidden-link")
        os.symlink(real, link)
        return real, link

    # ---- the watchdog --------------------------------------------------------------------
    # SPEC §13.6 and §14: a 50 s signal.alarm watchdog per tick (WATCHDOG_S = 50, under CADENCE_S).
    def test_each_tick_arms_a_50_s_watchdog(self):
        real, armed = signal.alarm, []

        def alarm(n):
            armed.append(n)
            return real(n)
        with mock.patch.object(signal, "alarm", new=alarm):
            self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        self.assertEqual([n for n in armed if n], [50])
        self.assertLess(50, config.CADENCE_S)

    # CONTRACT §3: a watchdog AROUND each tick -- none is left armed into --forever's wait.
    def test_no_alarm_is_left_armed_between_forever_ticks(self):
        for name, data in (("a row-writing tick", None), ("a tick that cannot create data/", "file")):
            with self.subTest(name):
                self.sleeps[:] = []
                armed = []
                with mock.patch.object(config, "DATA", self.data if data is None else os.path.join(self.tmp, "a-file")):
                    if data:
                        open(config.DATA, "w", encoding="utf-8").close()        # a FILE where data/ goes: makedirs raises
                    code = self.forever(["--dry", "--forever"], on_sleep=lambda: armed.append(signal.alarm(0)))
                self.assertEqual(code, 0)
                self.assertEqual(armed, [0, 0])                # the wait before the tick, and the one after it

    # module docstring: past the lock the row is written wherever the alarm lands.
    def test_an_alarm_after_the_row_is_complete_never_costs_it(self):
        real = cycle._finish

        def finish(row):
            signal.raise_signal(signal.SIGALRM)               # after _run returned, before write_row begins
            return real(row)
        with mock.patch.object(cycle, "_finish", side_effect=finish):
            self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        row = self.only_row()
        self.assertEqual((row["absence"], row["state"]), (None, STATE))
        self.assertNotIn("no row", self.err.getvalue())

    # ---- the spend guard -----------------------------------------------------------------
    # SPEC §13.3: today's spend is the sum over today's rows, so a log whose only row is today's counts it.
    def test_a_log_of_one_row_counts_that_row(self):
        self.write_log([_row(DAY + "T010000Z", 1000)])
        self.assertAlmostEqual(cycle.spend_today(NOW), _usd(1000))

    # SPEC §13.3: every one of today's rows is counted wherever the tail is cut, even when it holds one row.
    def test_a_tail_holding_one_row_of_today_still_counts_all_of_today(self):
        yesterday = json.dumps(_row("20260923T235900Z", 50_000_000)) + "\n"
        first = json.dumps(_row(DAY + "T000000Z", 1000)) + "\n"
        last = json.dumps(_row(DAY + "T000100Z", 1000)) + "\n"
        os.makedirs(self.data)
        with open(config.DECISIONS, "w", encoding="utf-8") as fh:
            fh.write(yesterday + first + last)
        with mock.patch.object(cycle, "TAIL_BYTES", len(last) + 10):   # the cut lands inside today's first row
            self.assertEqual(cycle._tail(config.DECISIONS, cycle.TAIL_BYTES), (last.encode(), True))
            self.assertAlmostEqual(cycle.spend_today(NOW), _usd(2000))

    # SPEC §13.3: today's rows by tick_id UTC date -- a row dated after today is not today's.
    def test_rows_dated_after_today_are_not_charged_today(self):
        self.write_log([_row("20260925T000000Z", 50_000_000), _row(DAY + "T010000Z", 1000)])
        self.assertAlmostEqual(cycle.spend_today(NOW), _usd(1000))

    # SPEC §13.3: the day is the tick_id's UTC date, whatever zone the Mac runs in.
    def test_the_spend_day_is_the_utc_date_whatever_the_local_zone(self):
        self.write_log([_row(DAY + "T010000Z", 1000)])
        self.addCleanup(time.tzset)                            # runs after the environ below is restored
        self.enterContext(mock.patch.dict(os.environ, {"TZ": "ABC+10"}))   # 02:28Z is 16:28 the day before
        time.tzset()
        self.assertEqual(time.strftime("%Y%m%d", time.localtime(NOW)), "20260923")
        self.assertAlmostEqual(cycle.spend_today(NOW), _usd(1000))

    # SPEC §13.3: the spend is summed over the day of the tick it guards (tick(now) pins that tick's clock).
    def test_the_spend_guard_counts_the_ticks_own_day(self):
        self.write_log([_row(DAY + "T010000Z", OVER), _row(DAY + "T010100Z", OVER)])
        with mock.patch("time.time", return_value=NOW + 86400):   # any other clock read is a day later
            self.assertEqual(cycle.tick(dry=True, now=NOW), 0)
        self.assertTrue(os.path.exists(config.HALT))
        self.assertEqual((self.rows()[-1]["absence"], self.rows()[-1]["tick_id"]), ("halt", TICK))
        self.assertEqual(self.out.getvalue(), "")

    # SPEC §13.3: billed tokens are the logged jev.input_tokens when positive -- 1 included.
    def test_a_logged_count_of_one_token_is_billed_as_one(self):
        self.assertEqual(cycle.billed_tokens(_row(DAY + "T010000Z", 1)), 1)

    # SPEC §13.3: halt/lock/feed/guard rows are billed 0, a live guard row with no count included.
    def test_a_live_guard_row_is_billed_nothing(self):
        self.assertEqual(cycle.billed_tokens(_row(DAY + "T010000Z", None, absence="guard")), 0)

    # SPEC §13.3: a trip writes data/HALT with the reason; when that write fails, stderr says so.
    def test_a_halt_that_cannot_be_written_is_reported(self):
        self.write_log([_row(DAY + "T010000Z", OVER), _row(DAY + "T010100Z", OVER)])
        halt = os.path.join(self.tmp, "no-such-dir", "HALT")
        with mock.patch.object(config, "HALT", halt):
            self.assertEqual(cycle.main(["--once"]), 0)
        self.assertEqual(self.rows()[-1]["absence"], "halt")   # the trip still halts this tick
        self.assertIn(f"cannot write {halt}", self.err.getvalue())
        self.assert_nothing_sent()

    # ---- HALT and the path guard ---------------------------------------------------------
    # SPEC §13.2: data/HALT EXISTS -> the tick is halted; a directory there exists too.
    def test_a_halt_that_is_a_directory_still_stops_sends(self):
        os.makedirs(config.HALT)
        self.assertEqual(cycle.main(["--once"]), 0)
        self.assertEqual(self.only_row()["absence"], "halt")
        self.assert_nothing_sent()

    # SPEC §13.1: the resolved repo path under a forbidden prefix is refused -- the tree a symlinked prefix names too.
    def test_the_path_guard_resolves_a_symlinked_prefix(self):
        real, link = self._symlinked()
        with mock.patch.object(config, "FORBIDDEN_PREFIXES", (link,)):
            self.assertEqual(cycle.forbidden(os.path.join(real, "sub")), link)

    # SPEC §13.1: the RESOLVED repo path -- a checkout reached through a symlink into the tree exits 3.
    def test_the_path_guard_resolves_a_symlinked_repo(self):
        real, link = self._symlinked()
        with mock.patch.object(config, "FORBIDDEN_PREFIXES", (real,)), \
                mock.patch.object(config, "REPO", os.path.join(link, "sub")):
            self.assertEqual(cycle.main(["--once"]), 3)
        self.assertFalse(os.path.exists(self.data))

    # SPEC §13.1 / CONTRACT §3: the path guard exits 3 -- in --forever too, when it trips mid-run.
    def test_the_path_guard_ends_forever_with_exit_3_when_it_trips_mid_run(self):
        tree = os.path.join(self.tmp, "forbidden")             # a stand-in prefix: the real tree is never statted
        self.enterContext(mock.patch.object(config, "FORBIDDEN_PREFIXES", (tree,)))
        self.enterContext(mock.patch.object(config, "REPO", config.REPO))

        def move_under_the_tree():
            config.REPO = os.path.join(tree, "jev-paper-loop")
        self.assertEqual(self.forever(["--dry", "--forever"], on_sleep=move_under_the_tree, stop_at=3), 3)
        self.assertEqual(len(self.sleeps), 1)
        self.assertFalse(os.path.exists(self.data))

    # ---- absences ------------------------------------------------------------------------
    # SPEC §13.5: a prompt that does not load is absence "guard" (the state before it is kept).
    def test_an_undecodable_current_is_guard_not_feed(self):
        with open(os.path.join(self.prompts_root, "CURRENT"), "wb") as fh:
            fh.write(b"\xff\xfev1\n")                          # prompts.current() lets UnicodeDecodeError through
        self.assertEqual(cycle.main(["--once"]), 0)
        row = self.only_row()
        self.assertEqual((row["absence"], row["state"], row["rule_c"]), ("guard", STATE, "buy"))
        self.assert_nothing_sent()

    # module docstring: guard is anything else that stopped the tick before the send, an unexpected exception included.
    def test_an_unexpected_exception_before_the_send_is_guard_and_billed_nothing(self):
        for i, (mod, name, exc) in enumerate(((state, "features", KeyError("mid")),
                                               (prompts, "build", TypeError("bad question")))):
            with self.subTest(name), mock.patch.object(mod, name, side_effect=exc), \
                    mock.patch("time.time", return_value=NOW + 60 * i):
                self.assertEqual(cycle.main(["--once"]), 0)
            row = self.rows()[-1]
            self.assertEqual((row["absence"], row["jev"]["error"], row["answers"]), ("guard", None, None))
            self.assertEqual(cycle.billed_tokens(row), 0)
        self.assertEqual(len(self.rows()), 2)
        self.assert_nothing_sent()

    # SPEC §2: drift is model_answered != model_requested, and model_answered is null when none was reported.
    def test_a_reply_that_names_no_model_is_drift(self):
        self.urlopen.side_effect = None
        self.urlopen.return_value = _Resp({"usage": {"input_tokens": 480}, "answers": ANSWERS})
        self.assertEqual(cycle.main(["--once"]), 0)
        row = self.only_row()
        self.assertEqual((row["model_answered"], row["drift"], row["absence"]), (None, True, None))

    # ---- rows owed, and exit 0 -----------------------------------------------------------
    # module docstring: every tick past the path guard and data/ writes exactly one row; SPEC §13.6: exit 0.
    def test_a_lock_file_that_cannot_be_opened_still_costs_one_row_and_exit_0(self):
        os.makedirs(config.LOCK)                               # a directory where the lock file goes
        self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        self.assertIsNotNone(self.only_row()["absence"])
        self.assert_nothing_sent()

    # SPEC §13.5: every path after the path guard writes one row; SPEC.md unreadable costs no row.
    def test_an_unreadable_spec_still_leaves_the_tick_its_row(self):
        os.makedirs(self.spec)                                 # SPEC.md present but not a readable file
        self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        self.assertEqual(self.only_row()["state"], STATE)

    # SPEC §13.6: every exit is 0 but 3 and 2 -- a late --once fire whose heartbeat cannot be read included.
    def test_an_unreadable_heartbeat_never_crashes_a_late_once_fire(self):
        os.makedirs(config.HEARTBEAT)                          # read in the minute's last 2 s: it cannot be
        clock = [NOW - 49 + 59.5]
        with mock.patch("time.time", side_effect=lambda: clock[0]):
            self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        self.assertEqual(len(self.rows()), 1)

    # SPEC §13.6: exit 0 but 3 and 2 -- dry or live; module docstring: no row is owed before data/ exists.
    def test_an_uncreatable_data_dir_exits_0_and_reports_only_that(self):
        open(self.data, "w", encoding="utf-8").close()                           # a FILE where data/ goes
        for argv in (["--dry", "--once"], ["--once"]):
            with self.subTest(argv=argv):
                self.assertEqual(cycle.main(argv), 0)
        err = self.err.getvalue()
        self.assertIn(f"cannot create {self.data}", err)
        self.assertNotIn("row NOT written", err)               # no row was owed, so none is reported lost
        self.snapshot.assert_not_called()
        self.assert_nothing_sent()

    # module docstring: the append itself failing is logged and the exit stays 0.
    def test_a_row_that_cannot_be_appended_is_reported_lost_and_exits_0(self):
        with mock.patch("os.write", side_effect=OSError(28, "No space left on device")):
            self.assertEqual(cycle.main(["--dry", "--once"]), 0)
        self.assertEqual(self.rows(), [])
        self.assertIn("row NOT written", self.err.getvalue())

    # ---- the write -----------------------------------------------------------------------
    # SPEC §13.6: an atomic append -- a short os.write is carried on until the whole line is down.
    def test_a_short_write_still_lands_the_whole_row(self):
        os.makedirs(self.data)
        real, calls = os.write, []
        row = cycle.new_row(TS_RX, "dry")

        def short(fd, b):
            calls.append(len(b))
            if len(calls) > 2000:
                raise OSError(28, "the write loop ran away")
            return real(fd, bytes(b[:7]))
        with mock.patch("os.write", side_effect=short):
            cycle.write_row(row)
        with open(config.DECISIONS, "rb") as fh:
            raw = fh.read()
        self.assertEqual(raw.count(b"\n"), 1)
        self.assertEqual(json.loads(raw), row)
        self.assertGreater(len(calls), 1)                      # it was short

    # SPEC §2: the log is append-only -- a log the tick can write but not read keeps every earlier row.
    def test_a_write_only_log_gets_its_row_after_the_rows_already_there(self):
        real_open = os.open

        def no_read(path, flags, *a):
            if flags & os.O_RDWR:
                raise PermissionError(13, "Permission denied", path)
            return real_open(path, flags, *a)
        old = b"".join(json.dumps(dict(_row(DAY + "T01%02d00Z" % i, 480), pad="x" * 2500)).encode() + b"\n"
                       for i in range(3))
        os.makedirs(self.data)
        with open(config.DECISIONS, "wb") as fh:
            fh.write(old)
        with mock.patch("os.open", side_effect=no_read):
            cycle.write_row(cycle.new_row(TS_RX, "dry"))
        with open(config.DECISIONS, "rb") as fh:
            raw = fh.read()
        self.assertTrue(raw.startswith(old))
        self.assertEqual([r["tick_id"] for r in self.rows()], [DAY + "T010000Z", DAY + "T010100Z", DAY + "T010200Z", TICK])

    # CONTRACT §3: --forever writes a row a minute until SIGTERM, so each write closes the descriptor it opened.
    def test_write_row_leaves_no_descriptor_open(self):
        os.makedirs(self.data)
        real_open, opened = os.open, []

        def rec(path, flags, *a):
            fd = real_open(path, flags, *a)
            opened.append(fd)
            return fd
        with mock.patch("os.open", side_effect=rec):
            cycle.write_row(cycle.new_row(TS_RX, "dry"))
        self.assertEqual(len(opened), 1)
        with self.assertRaises(OSError):
            os.fstat(opened[0])

    # module docstring: SIGTERM once the write has begun lets it complete, and then the tick stops.
    def test_a_sigterm_deferred_by_the_write_stops_the_tick_once_the_row_is_down(self):
        os.makedirs(self.data)
        old = signal.signal(signal.SIGTERM, cycle._on_term)
        self.addCleanup(signal.signal, signal.SIGTERM, old)
        real = os.fsync

        def fsync(fd):
            signal.raise_signal(signal.SIGTERM)                # inside the critical section: deferred
            real(fd)
        with mock.patch("os.fsync", side_effect=fsync), self.assertRaises(cycle._Stop):
            cycle.write_row(cycle.new_row(TS_RX, "dry"))
        self.assertEqual(self.only_row()["tick_id"], TICK)
        with open(config.HEARTBEAT, encoding="utf-8") as fh:
            self.assertEqual(fh.read().strip(), TS_RX)

    # CONTRACT §3: --forever runs until SIGTERM -- one landing inside a write that then fails ends it too.
    def test_sigterm_inside_a_failing_write_still_ends_forever(self):
        def write(fd, b):
            signal.raise_signal(signal.SIGTERM)                # deferred: the write is critical
            raise OSError(28, "No space left on device")
        with mock.patch("os.write", side_effect=write):
            self.assertEqual(self.forever(["--dry", "--forever"], stop_at=3), 0)
        self.assertEqual(len(self.sleeps), 1)                  # the wait before the one tick, and no other
        self.assertIn("row NOT written", self.err.getvalue())

    # ---- --once near the minute's end ----------------------------------------------------
    # module docstring: --once pre-sleeps in a minute's last 2 s when the heartbeat shows this minute has its row.
    def test_once_in_the_last_two_seconds_with_this_minutes_row_waits_for_the_boundary(self):
        self.assertEqual(self.once_at(58.5, "2026-09-24T02:28:00.100Z"), ([1.5], NEXT_TICK))

    # module docstring: a heartbeat that names this minute shows it has its row, however it ends after the minute.
    def test_a_heartbeat_naming_only_the_minute_still_shows_the_minute_has_its_row(self):
        self.assertEqual(self.once_at(59.5, "2026-09-24T02:28"), ([0.5], NEXT_TICK))


if __name__ == "__main__":
    unittest.main()

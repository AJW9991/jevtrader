"""PREREG-v2 §8: "the report counts failed nights with their reasons" (loop/nights.py), from logs/propose.log as
nightly/propose.sh writes it. Offline: hand-written log lines in the form propose.sh's log() prints (checked against
the script's own printf here), in temp files; the live logs/ is never read."""
import datetime, os, re, tempfile, unittest

from loop import nights, report

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = report.tick_epoch("20261024T220000Z")          # a stand-in T0_v2


def log(*events):
    return [f"{ts} propose {what}" for ts, what in events]


class Nights(unittest.TestCase):

    def test_the_log_line_is_propose_shs(self):
        with open(os.path.join(REPO, "nightly", "propose.sh"), encoding="utf-8") as fh:
            sh = fh.read()
        self.assertIn("log()  { printf '%s propose %s\\n' \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"$*\"", sh)
        self.assertIn('fail() { log "FAIL $*"; exit 0; }', sh)
        self.assertIn('log "start date=$DATE dry=$DRY root=$ROOT"', sh)
        self.assertIn('log "OK proposals/$DATE.json"', sh)

    def test_the_sample_nights_are_the_days_that_close_in_it(self):
        ds = nights.sample_nights(T0)
        self.assertEqual(len(ds), 28)
        self.assertEqual((ds[0], ds[-1]), (datetime.date(2026, 10, 24), datetime.date(2026, 11, 20)))
        on = report.tick_epoch("20261025T000000Z")      # a T0_v2 at 00:00Z: its own date closes a day later
        self.assertEqual(nights.sample_nights(on)[0], datetime.date(2026, 10, 25))
        self.assertEqual(nights.sample_nights(on)[-1], datetime.date(2026, 11, 21))

    def test_ok_failed_and_not_run_with_their_reasons(self):
        lines = log(("2026-10-25T08:30:01Z", "start date=2026-10-24 dry=0 root=/r"),
                    ("2026-10-25T08:31:00Z", "claude model claude-sonnet-5"),
                    ("2026-10-25T08:40:00Z", "OK proposals/2026-10-24.json"),
                    ("2026-10-25T09:00:00Z", "start date=2026-10-24 dry=0 root=/r"),            # a second run is refused
                    ("2026-10-25T09:00:00Z", "FAIL proposals/2026-10-24.json exists: one run per day"),
                    ("2026-10-26T08:30:00Z", "start date=2026-10-25 dry=0 root=/r"),
                    ("2026-10-26T09:15:00Z", "FAIL claude capped at 2700 s awake (see logs/claude-2026-10-25.err)"),
                    ("2026-10-27T08:30:00Z", "FAIL bad --date 2026-1026"),                          # before its start line
                    ("2026-10-28T08:30:00Z", "start date=2026-10-27 dry=1 root=/tmp/x"),            # dry: not a night
                    ("2026-10-28T08:31:00Z", "OK proposals/2026-10-27.json"),
                    ("2026-10-29T08:30:00Z", "start date=2026-10-28 dry=0 root=/r"))               # never finished
        c = nights.count({"path": "p", "lines": lines, "error": None}, T0)
        st = {d.isoformat(): (s, w) for d, s, w in c["nights"]}
        self.assertEqual(st["2026-10-24"], ("OK", []))
        self.assertEqual(st["2026-10-25"], ("FAILED", ["claude capped at 2700 s awake (see logs/claude-2026-10-25.err)"]))
        self.assertEqual(st["2026-10-26"], ("FAILED", ["bad --date 2026-1026"]))
        self.assertEqual(st["2026-10-27"], ("NOT RUN", []))
        self.assertEqual(st["2026-10-28"], ("FAILED", ["the run logged no OK and no FAIL line (it did not finish)"]))
        self.assertEqual(c["failed"], 27)                                                    # 28 nights, one OK
        text = "\n".join(nights.lines(c, "logs/propose.log"))
        self.assertIn("  failed nights (PREREG-v2 §8; logs/propose.log, the nights digesting the UTC days that close in the"
                      " sample): 27 of 28", text)
        self.assertIn("    2026-10-25: FAILED: claude capped at 2700 s awake", text)
        self.assertIn("    2026-10-27: NOT RUN: no run logged for this date (no proposal)", text)
        self.assertNotIn("2026-10-24:", text)

    def test_an_absent_or_unreadable_log(self):
        with tempfile.TemporaryDirectory() as d:
            got = nights.read(os.path.join(d, "propose.log"))
            self.assertEqual((got["lines"], got["error"]), (None, None))
            c = nights.count(got, T0)
            self.assertEqual(c["failed"], 28)
            self.assertIn("(the log is absent: no night was logged)", nights.lines(c, got["path"])[0])
            os.mkdir(os.path.join(d, "dir.log"))
            got = nights.read(os.path.join(d, "dir.log"))
            self.assertIsNotNone(got["error"])
            self.assertRegex(nights.lines(nights.count(got, T0), got["path"])[0], re.escape("cannot be read"))


if __name__ == "__main__":
    unittest.main()

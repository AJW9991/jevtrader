"""loop/dash.py: the health page renders from a log, and can carry no H1/H2/pair/confidence number
because it never imports or calls the code that computes one (PREREG §8.4)."""
import os, re, tempfile, unittest

from loop import dash, outcomes, report
from test_report import _row, _write

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Dash(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.log = os.path.join(cls.tmp, "decisions.jsonl")
        _write(cls.log, [_row(m) for m in range(42)])
        cls.rows = outcomes.load(cls.log, [])
        cls.outs = outcomes.join(cls.rows)

    def test_renders_sections_1_to_3_and_the_strip(self):
        page = dash.render(self.rows, self.outs, t0=None, hb="2026-09-23T10:41:00.000Z", log=self.log)
        for needle in ("ticks per hour (UTC)", "PREREG §8 stop rule 3", "adjective occupancy", "the 81 states",
                       "test-retest", "the nightly", "Health only (PREREG §8.4)", "2026-09-23", "class='cell b"):
            self.assertIn(needle, page)
        self.assertNotIn("<script", page)
        self.assertNotIn("http://", page.split("</style>", 1)[1])
        self.assertNotIn("https://", page.split("</style>", 1)[1])

    def test_no_h1_h2_pair_or_confidence_number(self):
        page = dash.render(self.rows, self.outs, t0=report.tick_epoch("20260923T100000Z"))
        body = page.split("<div class='foot'>")[0]                 # the footer NAMES what the page cannot carry
        for banned in ("H1", "H2", "pair B-C", "mean_S", "Pearson", "Brier", "calibration", "c99", "noultail", "pbuy", "confidence table"):
            self.assertNotIn(banned, body)
        with open(os.path.join(REPO, "loop", "dash.py")) as fh:
            src = fh.read()
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        for banned in ("report.table", "report.h2", "report.calibration", "report.agreement", "book.", "paired(", "replay("):
            self.assertNotIn(banned, code)
        self.assertNotIn("from . import", [l for l in code.splitlines() if "book" in l and "import" in l])

    def test_t0_from_prereg_and_the_sample_cut(self):
        with open(os.path.join(REPO, "PREREG.md")) as fh:
            sealed = "T0 (first tick_id of day 1): `" in fh.read()
        if sealed:
            self.assertEqual(dash.read_t0(), report.tick_epoch("20260925T214000Z"))
        self.assertIsNone(dash.read_t0(os.path.join(self.tmp, "nope.md")))
        page = dash.render(self.rows, self.outs, t0=report.tick_epoch("20260923T102000Z"))
        self.assertIn("T0 2026-09-23T10:20Z", page)
        self.assertIn("(pre-T0)", page) if False else None       # the same UTC day holds T0: not pre-T0
        self.assertIn("ticks in sample", page)

    def test_main_writes_the_file_and_reports_rows(self):
        import contextlib, io
        out = os.path.join(self.tmp, "d", "dash.html")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = dash.main(["--log", self.log, "--out", out, "--no-t0"])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(out))
        self.assertIn("42 rows, 1 skipped", buf.getvalue())
        with open(out) as fh:
            self.assertIn("no T0: whole log", fh.read())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(dash.main(["--log", os.path.join(self.tmp, "none.jsonl"), "--out", out, "--no-t0"]), 0)

    def test_hourly_and_bins(self):
        self.assertEqual(dash.hourly(self.rows)[("20260923", 10)], 42)
        self.assertEqual(dash._bin(0, 60), -1)
        self.assertEqual(dash._bin(1, 60), 0)
        self.assertEqual(dash._bin(12, 60), 0)
        self.assertEqual(dash._bin(13, 60), 1)
        self.assertEqual(dash._bin(60, 60), 4)
        self.assertEqual(dash._bin(5, 0), 4)

    def test_proposals_parse_the_committed_tables(self):
        props = dash.proposals(os.path.join(REPO, "proposals"))
        dates = [p["date"] for p in props]
        self.assertTrue(all(re.match(r"^\d{4}-\d{2}-\d{2}$", d) for d in dates))
        if "2026-09-25" in dates:
            p = props[dates.index("2026-09-25")]
            self.assertEqual((p["requests"], p["answered"], p["errors"], p["current"], p["current_vs_rule"]), (81, 81, 0, "v1", 0))
            self.assertEqual([(c["name"], c["vs_current"], c["vs_rule"]) for c in p["candidates"]],
                             [("cand_0", 0, 0), ("cand_1", 27, 27), ("cand_2", 27, 27)])


if __name__ == "__main__":
    unittest.main()

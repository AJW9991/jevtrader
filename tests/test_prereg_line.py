"""The repository's own PREREG.md §11 line parses whenever it is sealed. Every other test pins a
fixture PREREG (tests/fixture_prereg.py), so this is the one test that reads the real line: a seal
written in a form dash.T0_RE does not parse (a minute instead of a tick_id, say) would make read_t0
return None, which silently lifts report's §4-§7 withholding and makes status say 'no T0'. It
accepts ANY T0, so the prereg-v2 re-seal after 2026-10-23 passes; only a malformed seal fails."""
import hashlib, os, re, subprocess, tempfile, unittest

from fixture_prereg import text_v2
from loop import config, dash

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX = "T0 (first tick_id of day 1):"


class PreregLine(unittest.TestCase):
    def test_the_sealed_t0_line_parses(self):
        path = os.path.join(REPO, "PREREG.md")
        with open(path, encoding="utf-8") as fh:
            lines = [l for l in fh.read().splitlines() if l.startswith(PREFIX)]
        self.assertEqual(len(lines), 1, lines)
        unsealed = re.match(re.escape(PREFIX) + r" `_+`", lines[0]) is not None
        if not unsealed:
            self.assertIsNotNone(dash.read_t0(path), lines[0])

    def test_a_malformed_seal_is_what_this_test_would_catch(self):
        # the reading the test above relies on: a minute-form seal does not parse, a tick_id seal does
        self.assertIsNone(dash.T0_RE.search(PREFIX + " `2026-10-25T21:40Z`   Sealed by: `x`"))
        self.assertIsNotNone(dash.T0_RE.search(PREFIX + " `20261025T214000Z`   Sealed by: `x`"))


class PreregV2Line(unittest.TestCase):
    """PREREG-v2 §12's T0_v2 field (dash.read_t0_v2): blank is None (and the v2 withholding then covers every row
    carrying the v2 spec_sha), a tick_id is T0_v2, anything else filled in is loud. The repository's own line is
    read here and nowhere else (tests pin tests/fixture_prereg.pin_prereg_v2)."""

    def test_the_repositorys_section_12_line_reads(self):
        path = os.path.join(REPO, "PREREG-v2.md")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        sec = text[text.index("\n## 12."):text.index("\n## 13.")]
        self.assertEqual(len(dash.T0_V2_RE.findall(sec)), 1)
        dash.read_t0_v2(path)                                          # blank (None) or a tick_id; never a raise

    def _read(self, t0_field):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "PREREG-v2.md")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text_v2().replace("T0_v2: `________`", f"T0_v2: `{t0_field}`"))
            return dash.read_t0_v2(p)

    def test_blank_sealed_and_malformed(self):
        self.assertIsNone(self._read("________"))
        self.assertIsNone(self._read(""))
        self.assertEqual(self._read("20261024T220000Z"), dash.report.tick_epoch("20261024T220000Z"))
        for bad in ("2026-10-24T22:00Z", "20261024T220030Z", "20261024T2200Z", "tomorrow", "20261324T220000Z"):
            with self.assertRaises(ValueError, msg=bad):
                self._read(bad)
        self.assertIsNone(dash.read_t0_v2(os.path.join(REPO, "no-such-PREREG-v2.md")))
        # only §12's field is read: the fixture carries a filled T0_v2 in §13, which must not count
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "PREREG-v2.md")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text_v2())
            self.assertIsNone(dash.read_t0_v2(p))

    def _read_line(self, field_line):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "PREREG-v2.md")
            text = text_v2()
            start = text.index("T_first_v2:")
            end = text.index("\n", start)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text[:start] + field_line + text[end:])
            return dash.read_t0_v2(p)

    def test_a_filled_field_in_a_near_form_is_read_or_loud_never_blank(self):
        # "a malformed seal must be loud": a filled T0_v2 written a little differently from `T0_v2: `...`` must never
        # read as blank (None), which keeps everything withheld with no clock to lift it, makes --sample say "blank"
        # and the dash fall back to v1's T0. Spaces around the backticked value are only spacing and read; a value
        # without its backticks, or a second T0_v2 field in §12, is a ValueError (2026-09-29 refuter: p5.md, p6.md).
        tick = dash.report.tick_epoch("20261025T220000Z")
        for line in ("T_first_v2: `________`   T0_v2:  `20261025T220000Z`   Sealed by: `________`   on: `________`",
                     "T_first_v2: `________`   T0_v2:\t`20261025T220000Z`   Sealed by: `________`   on: `________`",
                     "T_first_v2: `________`   T0_v2 : `20261025T220000Z`   Sealed by: `________`   on: `________`",
                     "T_first_v2: `________`   T0_v2: ` 20261025T220000Z `   Sealed by: `________`   on: `________`"):
            self.assertEqual(self._read_line(line), tick, line)
        self.assertIsNone(self._read_line("T_first_v2: `________`   T0_v2:  `________`   Sealed by: `________`   on: `________`"))
        for line in ("T_first_v2: `________`   T0_v2: 20261025T220000Z   Sealed by: `________`   on: `________`",
                     "T_first_v2: `________`   T0_v2: ________   Sealed by: `________`   on: `________`",
                     "T_first_v2: `________`   T0_v2: '20261025T220000Z'   Sealed by: `________`   on: `________`",
                     "T0_v2: `20261025T220000Z`\nT0_v2: `20261026T220000Z`"):
            with self.assertRaises(ValueError, msg=line):
                self._read_line(line)
        # the §12 table row that names the field ("T_first_v2, T0_v2, sealed-by, ...") is not a field line
        self.assertIsNone(self._read_line("| T_first_v2, T0_v2, sealed-by, sealed-on | at sealing | the logs |\n"
                                          "T_first_v2: `________`   T0_v2: `________`   Sealed by: `________`   on: `________`"))

    def _tiers(self, read, table, extra=""):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "PREREG-v2.md")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text_v2().replace("\n## 13.", f"\nFee tiers (30-day band / maker / taker, read UTC `{read}`): `{table}`\n{extra}\n## 13.")
                         + "Fee tiers (30-day band / maker / taker, read UTC `x`): `$0+ / 1% / 1%`\n")   # §13: never read
            return dash.read_fee_tiers(p)

    def test_the_fee_tier_table(self):
        # PREREG-v2 §6.2 and §12: the venue's spot schedule, every row, read in-account at sealing with the read time. Blank
        # (underscores) is None: the report then prints ERRATA's 2026-09-27 reading alone. The form a filled field takes
        # (this reader's, for §14): rows `[name:] $LOW-$HIGH / maker / taker` or `$LOW+ / ...` joined by `;`, amounts with
        # an optional K, M or B, each fee with its unit, % or bps. Anything else filled in is a ValueError, never blank.
        path = os.path.join(REPO, "PREREG-v2.md")
        dash.read_fee_tiers(path)                                          # the repository's own line: blank or a table, never a raise
        self.assertIsNone(self._tiers("________", "________"))
        self.assertIsNone(dash.read_fee_tiers(os.path.join(REPO, "no-such-PREREG-v2.md")))
        got = self._tiers("2026-10-24T21:00Z", "Intro 1: $0-$10K / 0.50% / 0.90%; Intro 2: $10K-$50K / 0.25% / 0.40%;"
                                               " $50K-$1.5M / 15 bps / 25 bps; Advanced: $1B+ / 0% / 0.07%")
        self.assertEqual(got["read"], "2026-10-24T21:00Z")
        self.assertEqual([(t["name"], t["low"], t["high"], t["maker"], t["taker"]) for t in got["tiers"]],
                         [("Intro 1", 0.0, 10_000.0, 50.0, 90.0), ("Intro 2", 10_000.0, 50_000.0, 25.0, 40.0),
                          (None, 50_000.0, 1_500_000.0, 15.0, 25.0), ("Advanced", 1e9, None, 0.0, 7.0)])
        self.assertEqual(got["tiers"][0]["band"], "$0-$10K")
        for read, table in (("________", "$0+ / 0.5% / 0.9%"),               # a table without its read time
                            ("2026-10-24T21:00Z", "________"),               # a read time without its table
                            ("2026-10-24T21:00Z", "$0+ / 0.5 / 0.9"),        # a fee without its unit
                            ("2026-10-24T21:00Z", "$0+ / 0.5% / 0.9%, $10K+ / 0.2% / 0.4%"),
                            ("2026-10-24T21:00Z", "Intro / 0.5% / 0.9%"),    # no band
                            ("2026-10-24T21:00Z", "$0-$10K / 0.5% / 0.9%;")):
            with self.assertRaises(ValueError, msg=table):
                self._tiers(read, table)
        with self.assertRaises(ValueError):                                 # the field line without its backticks
            self._tiers("________", "________", extra="Fee tiers (30-day band / maker / taker): $0+ / 0.5% / 0.9%")

    def test_the_v2_spec_sha(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "SPEC.md")
            with open(p, "wb") as fh:
                fh.write(b"SPEC v2\n")
            self.assertEqual(dash.v2_spec_sha(p), hashlib.sha256(b"SPEC v2\n").hexdigest())
            self.assertIsNone(dash.v2_spec_sha(os.path.join(d, "absent.md")))
        with open(config.SPEC, "rb") as fh:
            tree = hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual(dash.v2_spec_sha(), None if tree == dash.V1_SPEC_SHA else tree)   # v1's SPEC: no row is v2 by sha

    def test_v1_spec_sha_is_prereg_v1s_spec(self):
        try:
            blob = subprocess.run(["git", "show", "prereg-v1:SPEC.md"], cwd=REPO, capture_output=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            blob = b""
        if not blob:
            self.skipTest("no prereg-v1 tag in this checkout (a shallow clone)")
        self.assertEqual(hashlib.sha256(blob).hexdigest(), dash.V1_SPEC_SHA)


if __name__ == "__main__":
    unittest.main()

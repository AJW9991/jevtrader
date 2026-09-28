"""The repository's own PREREG.md §11 line parses whenever it is sealed. Every other test pins a
fixture PREREG (tests/fixture_prereg.py), so this is the one test that reads the real line: a seal
written in a form dash.T0_RE does not parse (a minute instead of a tick_id, say) would make read_t0
return None, which silently lifts report's §4-§7 withholding and makes status say 'no T0'. It
accepts ANY T0, so the prereg-v2 re-seal after 2026-10-23 passes; only a malformed seal fails."""
import os, re, unittest

from loop import dash

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


if __name__ == "__main__":
    unittest.main()

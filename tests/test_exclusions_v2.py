"""loop/exclusions_v2.py: data/exclusions-v2.tsv (PREREG-v2 §9.3) parses to {(N, product)}, refuses a line whose
product is missing or not in config.PRODUCTS, and sits beside v1's reader, which is not changed; the recomputed
rule governs and every disagreement with the file is named."""
import os, tempfile, unittest
from unittest import mock

from loop import config, exclusions, exclusions_v2, report

HEAD = "day\tproduct\tfill%\tjev-err%\treason\n"


class Read(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.path = os.path.join(self.tmp, "exclusions-v2.tsv")
        p2 = [p for p in config.PROBE_CANDIDATES if p not in config.PRODUCTS][0]
        self.enterContext(mock.patch.object(config, "PRODUCTS", tuple(config.PRODUCTS) + (p2,)))
        self.p2 = p2

    def _put(self, body):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return self.path

    def test_product_days_and_the_lines_verbatim(self):
        body = HEAD + f"d03\tSOL-USD\t90.0%\t0.0%\tasleep\n5\t{self.p2}\t99.1\t6.2%\t429s\n\nd03\t{self.p2}\t0/0\tn/a\tno live row\n"
        got, lines = exclusions_v2.read(self._put(body))
        self.assertEqual(got, {(3, "SOL-USD"), (5, self.p2), (3, self.p2)})
        self.assertEqual(lines, [l for l in body.split("\n")[1:] if l])
        self.assertEqual(exclusions_v2.read(os.path.join(self.tmp, "absent.tsv")), (set(), []))
        # the header may be left out; tabs typed after the reason are ignored
        self.assertEqual(exclusions_v2.read(self._put("d28\tSOL-USD\t90%\t0%\tx\t\t\n"))[0], {(28, "SOL-USD")})
        # the default path is config.EXCLUSIONS_V2, under DATA as it is now
        with mock.patch.object(config, "DATA", self.tmp):
            self._put(HEAD + "d01\tSOL-USD\t94.0%\t0.0%\tfill\n")
            self.assertEqual(exclusions_v2.read()[0], {(1, "SOL-USD")})

    def test_a_missing_or_unknown_product_is_refused(self):
        for line, why in (("d03\t\t90.0%\t0.0%\tasleep", "the product is missing"),
                          ("d03\tBTC-USD\t90.0%\t0.0%\tasleep", "'BTC-USD' is not in config.PRODUCTS"),
                          ("d03\tsol-usd\t90.0%\t0.0%\tasleep", "'sol-usd' is not in config.PRODUCTS"),
                          ("d03\t90.0%\t0.0%\tasleep", "4 fields, not 5"),                      # v1's shape: no product column
                          ("d03  SOL-USD  90.0%  0.0%  asleep", "no tab"),                      # two spaces: v1 took them, v2 does not
                          ("d29\tSOL-USD\t90.0%\t0.0%\tasleep", "day 'd29' is not d01..d28"),
                          ("d1 6\tSOL-USD\t90.0%\t0.0%\ttypo", "day 'd1 6'"),
                          ("d03\tSOL-USD\t90.0%\tasleep\t", "fill% and jev-err%"),             # jev-err% left out
                          ("d03\tSOL-USD\t90.0%\t0.0%\t401 from Jev", "fill% and jev-err%")):  # a reason that begins with a number
            with self.subTest(line=line):
                with self.assertRaises(ValueError) as cm:
                    exclusions_v2.read(self._put(HEAD + "d01\tSOL-USD\t94%\t0%\tok\n" + line + "\n"))
                self.assertIn(why, str(cm.exception))
                self.assertIn(":3:", str(cm.exception))                                          # the line number
        with self.assertRaises(ValueError) as cm:                                                 # v1's header is not v2's
            exclusions_v2.read(self._put("day\tfill%\tjev-err%\treason\nd03\tSOL-USD\t90.0%\t0.0%\tasleep\n"))
        self.assertIn("the header is not v2's", str(cm.exception))
        with open(self.path, "wb") as fh:
            fh.write(HEAD.encode() + b"d03\tSOL-USD\t90\t0\t\xff\n")
        with self.assertRaises(ValueError):
            exclusions_v2.read(self.path)

    def test_v1s_reader_and_file_are_untouched(self):
        self.assertEqual(os.path.basename(config.EXCLUSIONS_V2), "exclusions-v2.tsv")
        self.assertNotEqual(config.EXCLUSIONS_V2, os.path.join(config.DATA, "exclusions.tsv"))
        v1 = os.path.join(self.tmp, "exclusions.tsv")
        with open(v1, "w", encoding="utf-8") as fh:
            fh.write("day\tfill%\tjev-err%\treason\nd03\t90.0%\t0.0%\tasleep\n")
        self.assertEqual(exclusions.read_exclusions(v1), ({3}, ["d03\t90.0%\t0.0%\tasleep"]))

    def test_the_file_is_versioned_when_it_exists(self):
        # PREREG-v2 §10: `!data/exclusions-v2.tsv` in .gitignore, after the `data/*` it overrides
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".gitignore"), encoding="utf-8") as fh:
            rules = fh.read().split("\n")
        self.assertGreater(rules.index("!data/exclusions-v2.tsv"), rules.index("data/*"))

    def test_status_line(self):
        self.assertEqual(exclusions_v2.status_line(self._put(HEAD + "d03\tSOL-USD\t90.0%\t0.0%\tasleep\n")),
                         f"exclusions-v2: 1 product-day(s) listed: d03 SOL-USD ({self.path})")
        self.assertTrue(exclusions_v2.status_line(self._put(HEAD + "d03\tBTC-USD\t9\t0\tx\n")).startswith(
            f"exclusions-v2: REFUSED, fix before day 28: {self.path}:2: product 'BTC-USD'"))
        self.assertEqual(exclusions_v2.status_line(os.path.join(self.tmp, "no.tsv")),
                         f"exclusions-v2: none ({os.path.join(self.tmp, 'no.tsv')} absent)")
        self.assertIn("cannot be read", exclusions_v2.status_line(self.tmp))                  # a directory


class Recompute(unittest.TestCase):
    """The rule recomputed per product governs: BAD and NO LIVE ROWS days are excluded, an open day is not judged."""

    @staticmethod
    def _day(n, bad=False, empty=False, open_=False):
        return {"day": f"d{n:02d}", "bad": bad, "empty": empty, "open": open_}

    def test_bad_and_empty_days_are_excluded_open_ones_are_not(self):
        days = {"SOL-USD": [self._day(0, bad=True), self._day(1), self._day(2, bad=True), self._day(3, empty=True), self._day(4, open_=True)],
                "X-USD": [self._day(2), self._day(29, bad=True), self._day(5, bad=True)]}
        self.assertEqual(exclusions_v2.recompute(days), {(2, "SOL-USD"), (3, "SOL-USD"), (5, "X-USD")})   # d00 and d29 are not sample days

    def test_every_disagreement_is_named(self):
        listed, rule = {(2, "SOL-USD"), (4, "SOL-USD")}, {(2, "SOL-USD"), (3, "X-USD")}
        self.assertEqual(exclusions_v2.disagreements(listed, rule), ([(4, "SOL-USD")], [(3, "X-USD")]))
        text = "\n".join(exclusions_v2.lines(listed, rule, ["d02\tSOL-USD\t90%\t0%\tx", "d04\tSOL-USD\t99%\t0%\ty"], "F"))
        self.assertIn("recomputed from the log, which governs: 2 product-day(s) excluded: d02 SOL-USD, d03 X-USD", text)
        self.assertIn("F: 2 product-day(s) listed: d02 SOL-USD, d04 SOL-USD", text)
        self.assertIn("    | d04\tSOL-USD\t99%\t0%\ty", text)
        self.assertIn("DISAGREE: listed, but the rule does not exclude them (fine or not yet closed), so NOT excluded: d04 SOL-USD", text)
        self.assertIn("DISAGREE: the rule excludes them and the file does not list them (excluded anyway): d03 X-USD", text)
        self.assertIn("the file and the rule agree", "\n".join(exclusions_v2.lines(rule, rule, [], "F")))

    def test_on_days_table_itself(self):
        # a closed sample day with no row at all is NO LIVE ROWS in days_table and so excluded; the day after it is open
        t0 = report.tick_epoch("20260923T000000Z")
        rows = [{"tick_id": report._tick_of(t0 + 86400 * 2 + 3600 + 60 * m), "ts_rx": None, "mode": "live", "absence": None, "mid": 100.0}
                for m in range(3)]
        d = report.days_table(rows, {}, t0)
        self.assertEqual(exclusions_v2.recompute({"SOL-USD": d["days"]}), {(1, "SOL-USD"), (2, "SOL-USD")})


if __name__ == "__main__":
    unittest.main()

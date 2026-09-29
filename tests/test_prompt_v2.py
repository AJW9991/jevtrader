"""nightly/PROMPT.md, v2 (PREREG-v2 §8): the v1 rules, plus the product as the first word of the state with one
wording for every product up to the base token {BASE}, and the measured fact that Jev reads "volatility is calm" as
"not violent", so a candidate whose only lever is calm against normal changes nothing. The text is the treatment:
tests/test_frozen.py pins its bytes; this module holds what the bytes must say."""
import os, re, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _text():
    with open(os.path.join(REPO, "nightly", "PROMPT.md"), encoding="utf-8") as fh:
        return fh.read()


def _flat(text):
    return re.sub(r"\s+", " ", text)


class PromptV2(unittest.TestCase):
    def test_the_v1_rules_stand(self):
        # the eight rules of v1's PROMPT.md, each by its opening words, in v1's order: none dropped, none reordered
        flat = _flat(_text())
        v1 = ["1. Full text, never a diff.", "2. One to three candidates.", "3. `rationale` is one line and is not sent to the fast model.",
              "4. No numbers. No digit, percentage, threshold, count, time or price anywhere in `instructions` or `criteria`.",
              "5. Keep the semantics. `buy` means want to be long; `sell` means want to be flat;",
              "6. Only the `action` question.",
              "7. The fast model can see only these words: liquidity `thin`, `normal`, `deep`; flow `quiet`, `organic`, `bot_war`;"
              " trend `dumping`, `flat`, `pumping`; vol `calm`, `normal`, `violent`.",
              "8. Your candidates are scored on the eighty-one synthetic states the alphabet can produce,"]
        at = [flat.find(r) for r in v1]
        self.assertNotIn(-1, at, [r for r, i in zip(v1, at) if i < 0])
        self.assertEqual(at, sorted(at))
        self.assertIn("Exactly ONE fenced code block tagged `json`", flat)

    def test_the_product_is_the_first_word_and_one_wording_serves_every_product(self):
        flat = _flat(_text())
        self.assertIn("The first word of the state is the product.", flat)
        self.assertIn("9. One wording for every product.", flat)
        self.assertIn("write the token `{BASE}`", flat)
        self.assertIn("a candidate must read identically for every product apart from `{BASE}`", flat)
        self.assertIn("The CURRENT wording of the `action` question, verbatim, with the product written `{BASE}`.", flat)

    def test_calm_reads_as_not_violent(self):
        flat = _flat(_text())
        self.assertIn('10. A measured fact about the fast model: it reads "volatility is calm" as "volatility is not violent"', flat)
        self.assertIn("A candidate whose only lever is calm against normal changes nothing", flat)
        self.assertIn("a fact of the synthetic table, not of any market data", flat)

    def test_the_digest_it_describes_is_v2s(self):
        # PREREG-v2 §8's digest: per product and pooled, 0 bps and the verified maker and taker, B from the minutes that
        # asked the wording CURRENT then, up to 25 disagreement rows, the per-state table
        flat = _flat(_text())
        for s in ("One summary line per product and one pooled over the products",
                  "at zero fee (direction, gross of fees), at the venue's retail maker fee and at its retail taker fee",
                  "Arm B's figures come only from the minutes that asked the wording that was CURRENT at that minute.",
                  "Up to twenty-five rows, over all the products,", "For each product, a table of the eighty-one states:"):
            self.assertIn(s, flat)

    def test_no_digit_but_the_rule_numbers(self):
        # PROMPT.md forbids the model numbers; the text itself spells its own ("eighty-one", "twenty-five")
        for n, line in enumerate(_text().splitlines(), 1):
            rest = re.sub(r"^\d{1,2}\. ", "", line)
            self.assertFalse(any(ch.isdigit() for ch in rest), f"line {n}: {line}")


if __name__ == "__main__":
    unittest.main()

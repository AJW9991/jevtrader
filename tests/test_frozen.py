"""The sample's frozen inputs, pinned (CLAUDE.md: nothing on this list changes until 2026-10-23
21:40Z): SPEC.md (every row carries its sha), PREREG.md (the H1/H2 definitions), nightly/PROMPT.md
(the treatment), the prompt files bin/promote has written so far, every threshold in
loop/config.py, the state alphabet and arm C's rule. An edit to any of them fails `make test` on
the Mac and in CI the day it is made, not at day 28. A deliberate change (an erratum Alex applies,
prereg-v2 after the sample) updates the pin here in the same commit, and its message says why.

Not pinned: prompts/CURRENT and any prompt file after v2 (bin/promote writes those, and no test
depends on what CURRENT names); the digest's content (its own golden test, tests/test_digest_v2.py);
PROTOCOL.md (Alex's signed carve-out, not an input of the measurement); the spend guard's dollar
figures, the venue fee and the fee columns FEE_BPS_COLUMNS beside the 0 bps primary (a spending
decision and descriptive report columns, none in a row's meaning; FEE_BPS_PRIMARY, the H1 cell,
is pinned). The pins were taken 2026-09-28 from bytes identical to the sealed prereg-v1 commit
(cfaa3f9) for SPEC, PREREG, PROMPT.md and v1.json, and to the promote commit (d155042) for v2.json;
PROMPT.md's was moved to its v2 text (PREREG-v2 §8) on 2026-09-29, in the commit that wrote it.

PREREG-v2's inference constants (§10: "the seeds, L, R, the ranks") are pinned by value as loop/inference_v2.py holds
them (2026-09-29): H1's and family F's cells in §6's order with their pair, cadence, seed and exact alpha, L, R, the
ranks the alphas give at R, the void threshold, the sample's days and §7's power.
"""
import hashlib, json, os, unittest
from fractions import Fraction

from loop import config, inference_v2, state

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = {                                            # sha256 of the bytes on disk
    "SPEC.md": "d246febca5dad492d8e561642bf9a5221d82791b3302df7527cc82aa85a2299a",   # SPEC v2 (PREREG-v2 §10), 2026-09-29;
                                                 # v1's 5d4f355e... stays in prereg-v1
    "PREREG.md": "28dab0a9cba8bb21a596fe06f3a19302476f42e3efbbe40b41480898266b7882",
    "nightly/PROMPT.md": "7ebcd64071700b6da578078e5eec10a846a56852a3c6de54bfd7ce8d786a1e50",   # v2 text (PREREG-v2 §8), 2026-09-29;
                                                 # v1's d20cc08e... stays in prereg-v1
    "prompts/v1.json": "207ed69be0ce6cb8d22ac81519a4db6845ab92d643c2772f150cabfe9efe57a0",
    "prompts/v2.json": "dcc848e5ad1452bede8631cf0d2f9801175070746ced883857e86366ec4a8ab4",
}

THRESHOLDS = {                                       # what a row's words, columns and label are computed from
    "VENUE": "coinbase", "PRODUCT": "SOL-USD", "CADENCE_S": 60, "HORIZON_S": 900, "MODEL": "jev-1.13.0",
    "JEV_TIMEOUT_S": 20,                             # SPEC: which slow answers become absence "jev" rows
    "NOTIONAL_USD": 1000.0, "BOOK_LEVELS": 100, "LIQ_THIN_BPS": 5.0, "LIQ_DEEP_BPS": 1.0,
    "FLOW_P_LO": 10, "FLOW_P_HI": 90, "TREND_Z": 1.0, "VOL_RATIO_LO": 0.5, "VOL_RATIO_HI": 2.0,
    "WINDOW_MIN": 300, "DEAD_BAND_BPS": 5.0, "FEE_BPS_PRIMARY": 0.0,
    "CONF_THRESHOLDS": (0.50, 0.70, 0.85, 0.99), "VETO_NOUL": 0.5, "PBUY": 0.60, "NOUL_TAIL": 0.99,
    # PREREG-v2 §2-§4, §10 (pinned 2026-09-29 with the constants themselves; the two probe products, their TICK_P
    # and atoms join PRODUCTS here in the commit that adds them to loop/config.py, before the draft tag)
    "PRODUCTS": ("SOL-USD",), "TICK_P": {"SOL-USD": 0.01}, "LIQ_ATOMS": {"SOL-USD": (1, 4)},
    "LIQ_THIN_FALLBACK": {"SOL-USD": False}, "CADENCES": (900, 3600, 14400), "FROZEN_A": "v2",
}

ALPHABET = {"liq": ("thin", "normal", "deep"), "flow": ("quiet", "organic", "bot_war"),
            "trend": ("dumping", "flat", "pumping"), "vol": ("calm", "normal", "violent")}
# per product, sha256 of json.dumps([[state_string(adj, base), rule_c(adj)], ...]) over state.all_states(): arm C's
# answer on all 81 states, the product's base first in each string (PREREG-v2 §3: one pin per product, SOL-USD's the
# v1 pin unchanged; an added product's pin is set in the commit that adds it to config.PRODUCTS)
RULE_C = {"SOL-USD": "289e53281bde0399848a5911e236396a0269936ec5f5608498f1786e1d578bb6"}


def _rule_c_digest(product):
    pairs = [[state.state_string(a, config.base(product)), state.rule_c(a)] for a in state.all_states()]
    return hashlib.sha256(json.dumps(pairs).encode()).hexdigest(), pairs

INFERENCE_V2 = {"SEED_H1": 20261023, "RESAMPLES": 10000, "BLOCK_LEN": 4, "ALPHA_H1": Fraction(1, 40),
                "ALPHA_F": Fraction(1, 160), "MIN_KEPT_DAYS": 21, "N_DAYS": 28, "POWER": 0.8}
CELLS_V2 = (("H1", "b", "c", 900, 20261023, Fraction(1, 40)),       # §5
            ("F1", "b", "c", 3600, 20261024, Fraction(1, 160)),     # §6, i = 1..4, seed 20261023 + i
            ("F2", "b", "c", 14400, 20261025, Fraction(1, 160)),
            ("F3", "a", "c", 900, 20261026, Fraction(1, 160)),
            ("F4", "b", "a", 900, 20261027, Fraction(1, 160)))
RANKS_V2 = {"H1": 249, "F1": 62, "F2": 62, "F3": 62, "F4": 62}   # sorted[ceil(alpha R) - 1]

HOW = ("a frozen input changed during the sample (CLAUDE.md, 'What must not change'). If the change is"
       " Alex's and deliberate (an erratum, or prereg-v2 after 2026-10-23 21:40Z), update the pin in"
       " tests/test_frozen.py in the same commit and say why; otherwise revert it.")


class Frozen(unittest.TestCase):
    def test_the_frozen_files_are_byte_for_byte_the_pinned_ones(self):
        for rel, want in FILES.items():
            with self.subTest(file=rel):
                with open(os.path.join(REPO, rel), "rb") as fh:
                    got = hashlib.sha256(fh.read()).hexdigest()
                self.assertEqual(got, want, f"{rel}: {HOW}")

    def test_every_threshold_of_a_row_is_the_pinned_value(self):
        got = {k: getattr(config, k) for k in THRESHOLDS}
        self.assertEqual(got, THRESHOLDS, HOW)

    def test_the_state_alphabet_and_arm_c_on_every_state_are_the_pinned_ones(self):
        self.assertEqual(state.DIMS, ("liq", "flow", "trend", "vol"), HOW)
        self.assertEqual(state.ALPHABET, ALPHABET, HOW)
        self.assertEqual(sorted(RULE_C), sorted(config.PRODUCTS), "one RULE_C pin per product: " + HOW)
        for product, want in RULE_C.items():
            with self.subTest(product=product):
                got, pairs = _rule_c_digest(product)
                self.assertEqual(len(pairs), 81)
                self.assertTrue(all(s.startswith(config.base(product) + ": liquidity ") for s, _ in pairs))
                self.assertEqual(got, want, HOW)
        pairs = [[state.state_string(a), state.rule_c(a)] for a in state.all_states()]      # v1's form, no base given
        self.assertEqual(hashlib.sha256(json.dumps(pairs).encode()).hexdigest(), RULE_C["SOL-USD"], HOW)

    def test_the_v2_inference_constants_are_the_pinned_ones(self):
        self.assertEqual({k: getattr(inference_v2, k) for k in INFERENCE_V2}, INFERENCE_V2, HOW)
        self.assertEqual(tuple((c.name, c.x, c.y, c.c, c.seed, c.alpha) for c in inference_v2.CELLS), CELLS_V2, HOW)
        self.assertEqual({c.name: inference_v2.alpha_rank(c.alpha, inference_v2.RESAMPLES) for c in inference_v2.CELLS}, RANKS_V2, HOW)
        for c in inference_v2.CELLS:                                                     # exact, never a float that equals it
            self.assertIs(type(c.alpha), Fraction, c.name)
        self.assertNotEqual(Fraction(1, 160), 0.00625)                                   # the pin itself tells them apart

    def test_the_pins_catch_an_edit(self):
        # the check itself, not only its inputs: one changed byte, one changed threshold, one changed state
        # answer each give a different digest or value than the pinned one
        with open(os.path.join(REPO, "SPEC.md"), "rb") as fh:
            spec = fh.read()
        self.assertNotEqual(hashlib.sha256(spec + b" ").hexdigest(), FILES["SPEC.md"])
        self.assertNotEqual(dict(THRESHOLDS, PBUY=0.61), THRESHOLDS)
        pairs = [[state.state_string(a), state.rule_c(a)] for a in state.all_states()]
        pairs[0][1] = {"buy": "hold", "hold": "sell", "sell": "buy"}[pairs[0][1]]
        self.assertNotEqual(hashlib.sha256(json.dumps(pairs).encode()).hexdigest(), RULE_C["SOL-USD"])
        other = [[state.state_string(a, "ETH"), state.rule_c(a)] for a in state.all_states()]   # the base is in the pin
        self.assertNotEqual(hashlib.sha256(json.dumps(other).encode()).hexdigest(), RULE_C["SOL-USD"])


if __name__ == "__main__":
    unittest.main()

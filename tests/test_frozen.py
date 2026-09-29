"""The sample's frozen inputs, pinned (CLAUDE.md: nothing on this list changes until 2026-10-23
21:40Z): SPEC.md (every row carries its sha), PREREG.md (the H1/H2 definitions), nightly/PROMPT.md
(the treatment), the prompt files bin/promote has written so far, every threshold in
loop/config.py, the state alphabet and arm C's rule. An edit to any of them fails `make test` on
the Mac and in CI the day it is made, not at day 28. A deliberate change (an erratum Alex applies,
prereg-v2 after the sample) updates the pin here in the same commit, and its message says why.

Not pinned: prompts/CURRENT and any prompt file after v2 (bin/promote writes those, and no test
depends on what CURRENT names); the digest's content (its own golden test in test_nightly);
PROTOCOL.md (Alex's signed carve-out, not an input of the measurement); the spend guard's dollar
figures, the venue fee and the fee columns FEE_BPS_COLUMNS beside the 0 bps primary (a spending
decision and descriptive report columns, none in a row's meaning; FEE_BPS_PRIMARY, the H1 cell,
is pinned). The pins were taken 2026-09-28 from bytes identical to the sealed prereg-v1 commit
(cfaa3f9) for SPEC, PREREG, PROMPT.md and v1.json, and to the promote commit (d155042) for v2.json.
"""
import hashlib, json, os, unittest

from loop import config, state

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = {                                            # sha256 of the bytes on disk
    "SPEC.md": "5d4f355e181739ae2a65a6496ecddf195d9dde7c7668c7606c19d795c5254ca7",
    "PREREG.md": "28dab0a9cba8bb21a596fe06f3a19302476f42e3efbbe40b41480898266b7882",
    "nightly/PROMPT.md": "d20cc08e3c757bb7e37f0638037bf3e29b7c4176d371bd8a94233ba7adfdfb6b",
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
# sha256 of json.dumps([[state_string, rule_c], ...]) over state.all_states(): arm C's answer on all 81 states
RULE_C = "289e53281bde0399848a5911e236396a0269936ec5f5608498f1786e1d578bb6"

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
        pairs = [[state.state_string(a), state.rule_c(a)] for a in state.all_states()]
        self.assertEqual(len(pairs), 81)
        self.assertEqual(hashlib.sha256(json.dumps(pairs).encode()).hexdigest(), RULE_C, HOW)

    def test_the_pins_catch_an_edit(self):
        # the check itself, not only its inputs: one changed byte, one changed threshold, one changed state
        # answer each give a different digest or value than the pinned one
        with open(os.path.join(REPO, "SPEC.md"), "rb") as fh:
            spec = fh.read()
        self.assertNotEqual(hashlib.sha256(spec + b" ").hexdigest(), FILES["SPEC.md"])
        self.assertNotEqual(dict(THRESHOLDS, PBUY=0.61), THRESHOLDS)
        pairs = [[state.state_string(a), state.rule_c(a)] for a in state.all_states()]
        pairs[0][1] = {"buy": "hold", "hold": "sell", "sell": "buy"}[pairs[0][1]]
        self.assertNotEqual(hashlib.sha256(json.dumps(pairs).encode()).hexdigest(), RULE_C)


if __name__ == "__main__":
    unittest.main()

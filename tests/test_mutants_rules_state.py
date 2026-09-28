"""loop/rules.py behaviour a mutation run found no existing test holding. Offline, hand-built
answers: no Jev, no fixture, no prompts/, no data/. Each test names the documented rule it
holds the code to; an expected value is written out, never recomputed through rules itself.
Whether a numeric string ("0.99") is a reading is deliberately pinned neither way here: the
documents refuse a wrong-typed field, rules._real coerces this one, and that is Alex's call.
"""
import unittest
from loop import config, rules


def noul(x):
    return {"noul": x}


def action(choice, conf):
    return {"choice": choice, "probabilities": {choice: conf}, "confidence": conf}


class ForArmSharedNouls(unittest.TestCase):
    def test_down15_alone_in_the_tail_is_a_sell_on_both_arms(self):
        # CONTRACT §2 / SPEC §9 noultail: sell if down15.noul >= NOUL_TAIL; for_arm: down15 is shared by both arms.
        answers = {"a_action": action("buy", 0.9), "b_action": action("sell", 0.9),
                   "skip": noul(0.3), "up15": noul(0.02), "down15": noul(config.NOUL_TAIL)}
        for arm in ("a", "b"):
            with self.subTest(arm=arm):
                self.assertEqual(rules.for_arm(answers, arm)["noultail"], "sell")


if __name__ == "__main__":
    unittest.main()

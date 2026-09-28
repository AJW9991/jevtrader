"""loop/rules.py against CONTRACT §2 Rule columns, on hand-built answers. Offline; no
Jev, no fixture. Every threshold is read back from config so a changed constant fails
here before it changes what a column means in the log.
"""
import math, unittest
from loop import config, rules

KEYS = ("argmax", "c50", "c70", "c85", "c99", "c50v", "c70v", "c85v", "c99v", "pbuy60", "noultail")


def below(x):
    return math.nextafter(x, -math.inf)


def action(choice, conf, buy=None, sell=None, hold=None):
    p = {"buy": buy, "sell": sell, "hold": hold}
    if buy is None and sell is None and hold is None:         # a plausible mass on the choice
        p = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
        p[choice] = conf
        rest = (1.0 - conf) / 2.0
        for k in p:
            if k != choice:
                p[k] = rest
    return {"choice": choice, "probabilities": p, "confidence": conf}


def noul(x):
    return {"noul": x}


QUIET = noul(0.10)        # skip: no veto
NO_UP, NO_DOWN = noul(0.20), noul(0.15)


class Shape(unittest.TestCase):
    def test_keys_exactly_in_contract_order(self):
        self.assertEqual(rules.COLUMNS, KEYS)
        out = rules.columns(action("buy", 0.9), QUIET, NO_UP, NO_DOWN)
        self.assertEqual(tuple(out), KEYS)

    def test_names_are_the_constants(self):
        self.assertEqual(config.CONF_THRESHOLDS, (0.50, 0.70, 0.85, 0.99))
        self.assertEqual(rules.CONF_COLUMNS, ("c50", "c70", "c85", "c99"))
        self.assertEqual(rules.PBUY_COLUMN, "pbuy60")
        self.assertEqual((config.VETO_NOUL, config.PBUY, config.NOUL_TAIL), (0.5, 0.60, 0.99))

    def test_null_answers_give_every_column_null(self):
        for args in ((None, None, None, None),
                     (None, QUIET, NO_UP, NO_DOWN),
                     (action("buy", 0.9), None, NO_UP, NO_DOWN),
                     (action("buy", 0.9), QUIET, None, NO_DOWN),
                     (action("buy", 0.9), QUIET, NO_UP, None)):
            out = rules.columns(*args)
            self.assertEqual(tuple(out), KEYS)
            self.assertTrue(all(v is None for v in out.values()), args)
        self.assertEqual(rules.null_columns(), {k: None for k in KEYS})

    def test_bad_choice_is_refused(self):
        with self.assertRaises(ValueError):
            rules.columns({"choice": "long", "probabilities": {}, "confidence": 0.9}, QUIET, NO_UP, NO_DOWN)

    def test_a_bool_or_non_finite_reading_is_refused(self):
        # float(True) is 1.0 (it would pass c99); NaN fails every cut (a silent hold); inf passes
        # every cut. None of them is a reading: ValueError, which cycle.py logs as jev/parse.
        for bad in (True, False, math.nan, math.inf, -math.inf, "nan", "inf", 10 ** 400):
            with self.subTest(bad=bad):
                a = action("buy", 0.9)
                a["confidence"] = bad
                with self.assertRaises(ValueError):
                    rules.columns(a, QUIET, NO_UP, NO_DOWN)
                for side in ("buy", "sell"):
                    a = action("buy", 0.9)
                    a["probabilities"][side] = bad
                    with self.assertRaises(ValueError):
                        rules.columns(a, QUIET, NO_UP, NO_DOWN)
                for i in range(1, 4):                                     # skip, up15, down15
                    args = [action("buy", 0.9), QUIET, NO_UP, NO_DOWN]
                    args[i] = noul(bad)
                    with self.assertRaises(ValueError):
                        rules.columns(*args)

    def test_a_wrong_typed_field_raises_and_a_missing_one_is_no_signal(self):
        a = action("buy", 0.9)
        a["confidence"] = None
        with self.assertRaises(TypeError):
            rules.columns(a, QUIET, NO_UP, NO_DOWN)
        a = action("buy", 0.9)
        a["probabilities"] = "x"
        with self.assertRaises(AttributeError):
            rules.columns(a, QUIET, NO_UP, NO_DOWN)
        with self.assertRaises(TypeError):
            rules.columns(action("buy", 0.9), noul(None), NO_UP, NO_DOWN)
        # missing, as before: no signal
        out = rules.columns({"choice": "buy"}, {}, {}, {})
        self.assertEqual(out, {"argmax": "buy", **{k: "hold" for k in KEYS[1:]}})
        # an int is a number, and 1 passes every cut, as 1.0 does
        out = rules.columns({"choice": "sell", "probabilities": {"sell": 1}, "confidence": 1}, noul(0), noul(0), noul(1))
        self.assertEqual((out["c99"], out["pbuy60"], out["noultail"]), ("sell", "sell", "sell"))


class HandBuilt(unittest.TestCase):
    def test_buy_at_072(self):
        a = {"choice": "buy", "probabilities": {"buy": 0.72, "sell": 0.08, "hold": 0.20}, "confidence": 0.72}
        out = rules.columns(a, noul(0.20), noul(0.30), noul(0.05))
        self.assertEqual(out, {"argmax": "buy",
                               "c50": "buy", "c70": "buy", "c85": "hold", "c99": "hold",
                               "c50v": "buy", "c70v": "buy", "c85v": "hold", "c99v": "hold",
                               "pbuy60": "buy", "noultail": "hold"})

    def test_sell_at_099_vetoed(self):
        a = {"choice": "sell", "probabilities": {"buy": 0.005, "sell": 0.99, "hold": 0.005}, "confidence": 0.99}
        out = rules.columns(a, noul(0.80), noul(0.01), noul(0.995))
        self.assertEqual(out, {"argmax": "sell",
                               "c50": "sell", "c70": "sell", "c85": "sell", "c99": "sell",
                               "c50v": "hold", "c70v": "hold", "c85v": "hold", "c99v": "hold",
                               "pbuy60": "sell", "noultail": "sell"})

    def test_hold_is_hold_everywhere(self):
        a = {"choice": "hold", "probabilities": {"buy": 0.3, "sell": 0.1, "hold": 0.6}, "confidence": 0.6}
        out = rules.columns(a, QUIET, NO_UP, NO_DOWN)
        self.assertEqual(out, {k: "hold" for k in KEYS})

    def test_low_confidence_buy_gates_out_but_argmax_keeps_it(self):
        a = {"choice": "buy", "probabilities": {"buy": 0.45, "sell": 0.15, "hold": 0.40}, "confidence": 0.45}
        out = rules.columns(a, QUIET, NO_UP, NO_DOWN)
        self.assertEqual(out["argmax"], "buy")
        for k in ("c50", "c70", "c85", "c99", "c50v", "c70v", "c85v", "c99v"):
            self.assertEqual(out[k], "hold", k)
        self.assertEqual(out["pbuy60"], "hold")


class ConfidenceCuts(unittest.TestCase):
    def test_at_and_just_below_each_threshold(self):
        for choice in ("buy", "sell"):
            for k, name in zip(config.CONF_THRESHOLDS, rules.CONF_COLUMNS):
                on = rules.columns(action(choice, k), QUIET, NO_UP, NO_DOWN)
                self.assertEqual(on[name], choice, (choice, name, "on"))          # >= : on the cut passes
                self.assertEqual(on[name + "v"], choice)
                off = rules.columns(action(choice, below(k)), QUIET, NO_UP, NO_DOWN)
                self.assertEqual(off[name], "hold", (choice, name, "below"))
                self.assertEqual(off[name + "v"], "hold")
                self.assertEqual(off["argmax"], choice)                            # argmax is never gated

    def test_monotone_across_columns(self):
        # Passing c85 implies passing c70 and c50; a confidence between cuts fills a prefix.
        for conf, expect in ((0.49, 0), (0.50, 1), (0.69, 1), (0.70, 2), (0.84, 2), (0.85, 3), (0.98, 3), (0.99, 4), (1.0, 4)):
            out = rules.columns(action("sell", conf), QUIET, NO_UP, NO_DOWN)
            passed = [out[c] == "sell" for c in rules.CONF_COLUMNS]
            self.assertEqual(passed, [True] * expect + [False] * (4 - expect), conf)


class Veto(unittest.TestCase):
    def test_skip_at_and_below_the_cut(self):
        a = action("buy", 1.0)
        on = rules.columns(a, noul(config.VETO_NOUL), NO_UP, NO_DOWN)             # 0.5 vetoes
        off = rules.columns(a, noul(below(config.VETO_NOUL)), NO_UP, NO_DOWN)     # just under does not
        for name in rules.CONF_COLUMNS:
            self.assertEqual(on[name], "buy")                                     # plain columns untouched
            self.assertEqual(on[name + "v"], "hold")
            self.assertEqual(off[name + "v"], "buy")
        self.assertEqual(on["argmax"], "buy")                                     # the veto never touches argmax
        self.assertEqual(on["pbuy60"], "buy")                                     # nor pbuy, nor noultail
        self.assertEqual(on["noultail"], "hold")

    def test_veto_is_a_hold_not_a_sell(self):
        out = rules.columns(action("buy", 0.9), noul(1.0), NO_UP, NO_DOWN)
        self.assertEqual([out[n + "v"] for n in rules.CONF_COLUMNS], ["hold"] * 4)
        out = rules.columns(action("sell", 0.9), noul(1.0), NO_UP, NO_DOWN)
        self.assertEqual([out[n + "v"] for n in rules.CONF_COLUMNS], ["hold"] * 4)


class PBuy(unittest.TestCase):
    def col(self, buy, sell, choice="hold"):
        a = {"choice": choice, "probabilities": {"buy": buy, "sell": sell, "hold": 1.0 - buy - sell}, "confidence": 0.4}
        return rules.columns(a, QUIET, NO_UP, NO_DOWN)["pbuy60"]

    def test_cut_is_inclusive_and_independent_of_the_choice(self):
        self.assertEqual(self.col(config.PBUY, 0.1), "buy")                      # 0.60 → buy
        self.assertEqual(self.col(below(config.PBUY), 0.1), "hold")
        self.assertEqual(self.col(0.1, config.PBUY), "sell")
        self.assertEqual(self.col(0.1, below(config.PBUY)), "hold")
        self.assertEqual(self.col(0.59, 0.41), "hold")
        self.assertEqual(self.col(0.9, 0.05, choice="hold"), "buy")             # reads p, not the choice

    def test_missing_probabilities_hold(self):
        a = {"choice": "buy", "probabilities": {}, "confidence": 0.9}
        self.assertEqual(rules.columns(a, QUIET, NO_UP, NO_DOWN)["pbuy60"], "hold")


class NoulTail(unittest.TestCase):
    def col(self, up, down):
        return rules.columns(action("hold", 0.5), QUIET, noul(up), noul(down))["noultail"]

    def test_tail_at_and_below_099(self):
        t = config.NOUL_TAIL
        self.assertEqual(self.col(t, 0.0), "buy")
        self.assertEqual(self.col(below(t), 0.0), "hold")
        self.assertEqual(self.col(0.0, t), "sell")
        self.assertEqual(self.col(0.0, below(t)), "hold")
        self.assertEqual(self.col(0.98, 0.98), "hold")
        self.assertEqual(self.col(1.0, 0.0), "buy")
        self.assertEqual(self.col(0.0, 1.0), "sell")

    def test_both_in_tail_reads_up_first(self):
        self.assertEqual(self.col(0.995, 0.995), "buy")

    def test_independent_of_the_action_answer(self):
        out = rules.columns(action("sell", 1.0), noul(1.0), noul(1.0), noul(0.0))
        self.assertEqual(out["noultail"], "buy")
        self.assertEqual(out["c99"], "sell")


class ForArm(unittest.TestCase):
    def test_reads_the_arm_action_and_the_shared_nouls(self):
        answers = {"a_action": action("buy", 0.9), "b_action": action("sell", 0.6),
                   "skip": noul(0.1), "up15": noul(0.995), "down15": noul(0.0)}
        a, b = rules.for_arm(answers, "a"), rules.for_arm(answers, "b")
        self.assertEqual((a["argmax"], a["c85"], a["c99"]), ("buy", "buy", "hold"))
        self.assertEqual((b["argmax"], b["c50"], b["c70"]), ("sell", "sell", "hold"))
        self.assertEqual((a["noultail"], b["noultail"]), ("buy", "buy"))

    def test_none_answers_is_the_null_shape(self):
        self.assertEqual(rules.for_arm(None, "a"), rules.null_columns())
        self.assertEqual(rules.for_arm({"skip": noul(0.1)}, "b"), rules.null_columns())


if __name__ == "__main__":
    unittest.main()

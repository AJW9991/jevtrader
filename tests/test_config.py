"""loop/config.py's v2 accessors (PREREG-v2 §2, §3, §4, §10): the product set, the per-product tables, the
stores, the global HALT and the per-product PAUSE, JEVLOOP_PRODUCT and the liq cuts. Offline, no file written."""
import os, re, unittest
from unittest import mock
from loop import config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TWO = ("SOL-USD", "ETH-USD")                         # a stand-in second product; the probe names the real ones
OUTSIDE = "BTC-USD"                                  # never in PRODUCTS: neither SOL-USD nor a probe candidate


class Products(unittest.TestCase):
    def test_sol_is_first_and_every_per_product_table_holds_exactly_the_products(self):
        self.assertIsInstance(config.PRODUCTS, tuple)
        self.assertEqual(config.PRODUCTS[0], "SOL-USD")
        self.assertEqual(config.PRODUCT, "SOL-USD")
        self.assertEqual(len(set(config.PRODUCTS)), len(config.PRODUCTS))
        self.assertLessEqual(len(config.PRODUCTS), 3)
        for table in (config.TICK_P, config.LIQ_ATOMS, config.LIQ_THIN_FALLBACK):
            self.assertEqual(sorted(table), sorted(config.PRODUCTS))
        for p in config.PRODUCTS:
            self.assertRegex(p, r"^[A-Z]+-USD$")
            self.assertGreater(config.TICK_P[p], 0.0)
            a10, a90 = config.LIQ_ATOMS[p]
            self.assertIsInstance(a10, int)
            self.assertIsInstance(a90, int)
            self.assertLessEqual(a10, a90)
            self.assertIsInstance(config.LIQ_THIN_FALLBACK[p], bool)

    def test_sol_values_are_the_prereg_ones(self):
        # PREREG-v2 §3: TICK_p 0.01; a10 1, a90 4, thin_fallback no -> deep iff h < 1.5, thin iff h > 4.5
        self.assertEqual(config.TICK_P["SOL-USD"], 0.01)
        self.assertEqual(config.LIQ_ATOMS["SOL-USD"], (1, 4))
        self.assertIs(config.LIQ_THIN_FALLBACK["SOL-USD"], False)
        self.assertEqual(config.liq_cuts("SOL-USD"), (1.5, 4.5))

    def test_the_thin_fallback_moves_only_the_thin_cut(self):
        with mock.patch.dict(config.LIQ_THIN_FALLBACK, {"SOL-USD": True}):
            self.assertEqual(config.liq_cuts("SOL-USD"), (1.5, 3.5))

    def test_the_other_constants(self):
        self.assertEqual(config.CADENCES, (900, 3600, 14400))
        self.assertEqual(config.FROZEN_A, "v2")
        self.assertEqual(config.DAILY_SPEND_HALT_USD, 0.25 * len(config.PRODUCTS))
        self.assertEqual(config.base("SOL-USD"), "SOL")
        self.assertEqual(config.base("DOGE-USD"), "DOGE")

    def test_the_probe_candidates_are_bin_probes_own_list(self):
        # read as text, never imported: a probe run holds bin/probe's lock on D
        with open(os.path.join(REPO, "bin", "probe"), encoding="utf-8") as fh:
            m = re.search(r"^DEFAULT_CANDIDATES = (\([^)]*\))", fh.read(), re.M)
        self.assertIsNotNone(m)
        self.assertEqual(config.PROBE_CANDIDATES, eval(m.group(1), {}))
        for p in config.PRODUCTS[1:]:
            self.assertIn(p, config.PROBE_CANDIDATES)
        self.assertNotIn(OUTSIDE, ("SOL-USD",) + config.PROBE_CANDIDATES)   # so the tests' example outside PRODUCTS stays outside


class Stores(unittest.TestCase):
    def test_sol_keeps_every_v1_path(self):
        self.assertEqual(config.store("SOL-USD"), (config.DECISIONS, config.SENDS, config.LOCK, config.HEARTBEAT))
        data = os.path.join(REPO, "data")
        self.assertEqual(config.store("SOL-USD"), (os.path.join(data, "decisions.jsonl"), os.path.join(data, "sends.tsv"),
                                                   os.path.join(data, "loop.lock"), os.path.join(data, "heartbeat")))
        s = config.store("SOL-USD")
        self.assertEqual((s.decisions, s.sends, s.lock, s.heartbeat), tuple(s))

    def test_sol_follows_a_patched_v1_path(self):
        with mock.patch.object(config, "DECISIONS", "/elsewhere/d.jsonl"):
            self.assertEqual(config.store("SOL-USD").decisions, "/elsewhere/d.jsonl")

    def test_another_product_has_its_own_directory_under_data(self):
        with mock.patch.object(config, "PRODUCTS", TWO), mock.patch.object(config, "DATA", "/d"):
            self.assertEqual(config.store("ETH-USD"), ("/d/ETH-USD/decisions.jsonl", "/d/ETH-USD/sends.tsv",
                                                      "/d/ETH-USD/loop.lock", "/d/ETH-USD/heartbeat"))
            self.assertEqual(config.pause("ETH-USD"), "/d/PAUSE.ETH-USD")
            self.assertEqual(config.pause("SOL-USD"), "/d/PAUSE.SOL-USD")

    def test_a_product_outside_products_is_refused_not_made_a_path(self):
        unchosen = tuple(p for p in config.PROBE_CANDIDATES if p not in config.PRODUCTS)   # a candidate the probe did not pick
        for bad in (OUTSIDE, "../x", "", "SOL-USD/..", None) + unchosen:
            with self.assertRaises(ValueError, msg=bad):
                config.store(bad)
            with self.assertRaises(ValueError, msg=bad):
                config.pause(bad)

    def test_the_global_files_sit_at_repo_data(self):
        data = os.path.join(REPO, "data")
        self.assertEqual(config.HALT, os.path.join(data, "HALT"))
        self.assertEqual(config.EXCLUSIONS_V2, os.path.join(data, "exclusions-v2.tsv"))
        self.assertEqual(config.LOOKS, os.path.join(data, "looks.tsv"))
        self.assertEqual(config.pause("SOL-USD"), os.path.join(data, "PAUSE.SOL-USD"))


    def test_the_v2_global_files_follow_a_patched_data(self):
        # like store() and pause(): a test that points DATA at a temp dir moves exclusions-v2.tsv and looks.tsv
        # with it, so no test can append a "look" to the live data/looks.tsv that RESULTS-v2 §0 reproduces
        with mock.patch.object(config, "DATA", "/d"):
            self.assertEqual((config.EXCLUSIONS_V2, config.LOOKS), ("/d/exclusions-v2.tsv", "/d/looks.tsv"))
            with mock.patch.object(config, "LOOKS", "/elsewhere/looks.tsv"):                  # a patch of its own wins
                self.assertEqual(config.LOOKS, "/elsewhere/looks.tsv")
            self.assertEqual(config.LOOKS, "/d/looks.tsv")                                     # and is undone
        self.assertEqual(config.LOOKS, os.path.join(REPO, "data", "looks.tsv"))
        with self.assertRaises(AttributeError):
            config.NO_SUCH_CONSTANT


class LoopProduct(unittest.TestCase):
    def test_unset_is_sol(self):
        self.assertEqual(config.loop_product({}), "SOL-USD")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JEVLOOP_PRODUCT", None)
            self.assertEqual(config.loop_product(), "SOL-USD")

    def test_a_product_in_products_is_taken(self):
        self.assertEqual(config.loop_product({"JEVLOOP_PRODUCT": "SOL-USD"}), "SOL-USD")
        with mock.patch.object(config, "PRODUCTS", TWO):
            self.assertEqual(config.loop_product({"JEVLOOP_PRODUCT": "ETH-USD"}), "ETH-USD")

    def test_anything_else_is_refused(self):
        unchosen = tuple(p for p in config.PROBE_CANDIDATES if p not in config.PRODUCTS)
        for bad in (OUTSIDE, "sol-usd", "", "SOL", "SOL-USD ", "../data") + unchosen:
            with self.assertRaises(ValueError, msg=bad):
                config.loop_product({"JEVLOOP_PRODUCT": bad})


if __name__ == "__main__":
    unittest.main()

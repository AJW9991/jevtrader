"""The suite holds once the probe's products are in config.PRODUCTS (PREREG-v2 §2). The commit that adds them
writes loop/config.py (PRODUCTS, TICK_P, LIQ_ATOMS, LIQ_THIN_FALLBACK, and with them DAILY_SPEND_HALT_USD,
0.25 x the products) and the pins in tests/test_frozen.py, and nothing else. So no other test may assume one
product: not the $0.25 tripwire (it is $0.25 a product), not a probe candidate as the example of a product
outside PRODUCTS (the tests use BTC-USD, neither SOL-USD nor a candidate: test_config checks it). At S1 of the
v2 build 18 tests outside the pins failed with ETH-USD and XRP-USD added (the refuter's three-product run).

Checked here by running the suite's modules in a fresh interpreter with config set as that commit will set it:
PRODUCTS filled to three with the first candidates bin/probe tries that are not in it yet (ETH-USD and XRP-USD,
the likeliest two, until the real ones are in), each with a tick, atoms and a thin fallback (illustrative
values: the probe's run on 2026-09-30 names the real ones), and the tripwire scaled as config.py computes it.
Skipped once PRODUCTS holds three: the suite itself runs them then. Not run in that interpreter, each for its
reason in LEFT_OUT. Subprocesses a test starts import the committed config: they are not covered."""
import json, os, subprocess, sys, unittest
from loop import config

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS)
SELF = os.path.splitext(os.path.basename(__file__))[0]
LEFT_OUT = {
    SELF: "this module",
    "test_frozen": "its pins are the committed PRODUCTS' (THRESHOLDS with TICK_P and the atoms, RULE_C per product);"
                   " by rule they change in the commit that adds the products",
    "test_probe": "bin/probe is finished and reads no PRODUCTS; a real probe run holds its lock on D, which the"
                  " module's own one-at-a-time test meets",
    "test_nightly": "22 s of shell runs; what it reads of PRODUCTS today (bin/promote builds every product) passed"
                    " with three by hand at S1; the stage that makes the nightly per product takes it in or says why not",
}
from fixture_products import STAND_IN          # per candidate: (TICK_P, (a10, a90), thin fallback) -- illustrative
BOOT = r"""
import json, sys, unittest
tests, repo, spec = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
sys.path[:0] = [tests, repo]
from loop import config
n = len(config.PRODUCTS)
for p, (tick, atoms, fallback) in spec.items():
    config.TICK_P[p], config.LIQ_ATOMS[p], config.LIQ_THIN_FALLBACK[p] = tick, tuple(atoms), fallback
config.PRODUCTS = tuple(config.PRODUCTS) + tuple(spec)
config.DAILY_SPEND_HALT_USD = config.DAILY_SPEND_HALT_USD / n * len(config.PRODUCTS)   # 0.25 x products, as config.py
unittest.main(module=None, argv=["products-added"] + sys.argv[4:])
"""


def modules():
    names = sorted(os.path.splitext(f)[0] for f in os.listdir(TESTS) if f.startswith("test") and f.endswith(".py"))
    return [m for m in names if m not in LEFT_OUT]


class ProductsAdded(unittest.TestCase):
    def test_every_left_out_module_exists(self):
        names = {os.path.splitext(f)[0] for f in os.listdir(TESTS)}
        self.assertLessEqual(set(LEFT_OUT), names)

    def test_the_suite_holds_with_three_products(self):
        add = [p for p in config.PROBE_CANDIDATES if p not in config.PRODUCTS][:3 - len(config.PRODUCTS)]
        if not add:
            self.skipTest("PRODUCTS holds three: the suite runs them itself")
        self.assertEqual(sorted(STAND_IN), sorted(config.PROBE_CANDIDATES))
        spec = {p: STAND_IN[p] for p in add}
        mods = modules()
        self.assertIn("test_cycle", mods)
        argv = [sys.executable] + [f"-W{w}" for w in sys.warnoptions] + ["-c", BOOT, TESTS, REPO, json.dumps(spec)] + mods
        r = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=600)
        self.assertEqual(r.returncode, 0, f"with {', '.join(add)} added:\n" + "\n".join(
            l for l in r.stderr.splitlines() if l.startswith(("FAIL:", "ERROR:", "Ran ", "FAILED")))
            + "\n" + r.stderr[-3000:])
        self.assertRegex(r.stderr, r"Ran \d+ tests")


if __name__ == "__main__":
    unittest.main()

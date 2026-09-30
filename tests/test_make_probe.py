"""The Makefile's PREREG-v2 tool targets: `quantiles` and `probe` print usage and run nothing, and
`probe-summarize` needs DIR and reads it offline. None of them is the default goal, which stays `test`. And the
morning targets (health, status, dash) read every product's store."""
import json, os, re, subprocess, sys, tempfile, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _make(*args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("MAKE")}   # not the outer `make test`'s flags
    return subprocess.run(["make", "-s", "-C", REPO, *args, f"PY={sys.executable}"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=60)


class MakeTargets(unittest.TestCase):
    def test_quantiles_and_probe_print_usage(self):
        r = _make("quantiles")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("usage: bin/fill1k-quantiles"), r.stdout)
        r = _make("probe")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("usage: bin/probe"), r.stdout)

    def test_probe_summarize_needs_dir_and_reads_it(self):
        r = _make("probe-summarize")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("make probe-summarize DIR=", r.stderr)
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "run.json"), "w", encoding="utf-8") as fh:
                json.dump({"day": "2026-09-24", "candidates": ["ETH-USD"]}, fh)
            r = _make("probe-summarize", f"DIR={d}")
            self.assertEqual(r.returncode, 2, r.stderr)                  # summarize exits 1: a day with no row is void
            self.assertIn("day_valid: no (rows in 0/1440 0.00% of D's minutes < 95%)", r.stdout.splitlines())
            self.assertEqual(r.stdout.splitlines()[-1],
                             "chosen: none (D is void; PREREG-v2 section 2: D becomes the next UTC day, once, named in"
                             " section 14)")
            self.assertEqual(sorted(os.listdir(d)), ["run.json"])          # offline and read-only
            self.assertNotIn("tick: 0.0002 (--tick-override)", r.stdout.splitlines())
            r = _make("probe-summarize", f"DIR={d}", "TICK_OVERRIDE=ETH-USD=0.0002")   # builder's open issue 5
            self.assertIn("tick: 0.0002 (--tick-override)", r.stdout.splitlines(), r.stderr)
            self.assertEqual(r.returncode, 2, r.stderr)

    def test_phony_and_the_default_goal(self):
        with open(os.path.join(REPO, "Makefile"), encoding="utf-8") as fh:
            text = fh.read()
        phony = re.search(r"^\.PHONY:(.*)$", text, re.MULTILINE).group(1).split()
        for t in ("quantiles", "probe", "probe-summarize"):
            self.assertIn(t, phony)
        first = re.search(r"^([A-Za-z][\w-]*):", text, re.MULTILINE).group(1)
        self.assertEqual(first, "test")

    def test_the_morning_targets_read_every_store(self):
        # PREREG-v2 §2, §10: health, status and dash pass no --log, so each reader takes its default, every product's
        # store in config.PRODUCTS (v2's results target is held in tests/test_inference_v2.py)
        for target, want in (("health", "-m loop.report --health --pre-sample --sample"), ("status", "-m loop.status"),
                             ("dash", "-m loop.dash")):
            r = _make("-n", target)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), f"{sys.executable} {want}", target)


if __name__ == "__main__":
    unittest.main()

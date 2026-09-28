"""bin/readers-diff: one log read by two code trees, reported as counts and tick_ids only."""
import json, os, shutil, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_report import _row

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "bin", "readers-diff")


def _run(*argv):
    p = subprocess.run([sys.executable, TOOL, *argv], capture_output=True, text=True, cwd=REPO)
    return p.returncode, p.stdout, p.stderr


class ReadersDiff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        rows = [_row(m) for m in range(40)]
        dry_first = dict(rows[7]); dry_first["mode"], dry_first["ts_rx"] = "dry", "2026-09-23T10:07:00.050Z"
        dry_first.update(bid=100.49, ask=100.51, mid=100.5)  # a different mid, so which row speaks changes the return
        rows.insert(7, dry_first)                              # a priced dry row before the live one, same tick_id
        cls.log = os.path.join(cls.tmp, "decisions.jsonl")
        with open(cls.log, "w", encoding="utf-8") as fh:
            for r in rows[:30]:
                fh.write(json.dumps(r) + "\n")
            fh.write('{"v": 1, "tick_id": "20260923T103000Z", "ts_rx": "2026-09-23T10:3')   # torn, then a whole row glued on
            for r in rows[30:]:
                fh.write(json.dumps(r) + "\n")
        cls.old = os.path.join(cls.tmp, "old")                  # this tree, with the join's first-wins rule of main
        os.makedirs(cls.old)
        shutil.copytree(os.path.join(REPO, "loop"), os.path.join(cls.old, "loop"), ignore=shutil.ignore_patterns("__pycache__"))
        with open(os.path.join(cls.old, "loop", "outcomes.py"), "a", encoding="utf-8") as fh:
            fh.write("\n\ndef rank(r):\n    return 0\n")      # every row ranks alike: the first row with a tick_id speaks for it

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_same_tree_twice_differs_nowhere_and_counts_the_shapes(self):
        code, out, err = _run(REPO, REPO, "--log", self.log)
        self.assertEqual(code, 0, err)
        self.assertIn("rows read: old 41 / new 41\n", out)
        self.assertIn("lines skipped: old 1 / new 1; lines from which the new tree recovered a whole row: 1\n", out)
        self.assertIn("priced tick_ids with more than one row: 1 20260923T100700Z\n", out)
        self.assertIn("live answered rows with both columns null (book._intent): 0\n", out)
        self.assertIn("ticks whose joined outcome differs old vs new: 0\n", out)

    def test_a_tree_with_the_first_wins_join_differs_on_the_shared_tick_only(self):
        code, out, err = _run(self.old, REPO, "--log", self.log)
        self.assertEqual(code, 0, err)
        self.assertIn("ticks whose joined outcome differs old vs new: 1 20260923T100700Z\n", out)
        self.assertIn("rows read: old 41 / new 41\n", out)

    def test_no_number_of_the_outcome_is_printed(self):
        code, out, _ = _run(self.old, REPO, "--log", self.log)
        self.assertEqual(code, 0)
        head, body = out.split("\n", 1)                                     # the first line is paths, by design
        self.assertTrue(head.startswith(f"log {self.log}: read by old "), head)
        for token in ("mid_h", "ret_h", "bps", "101.0", "100.0", "up", "down", "flat", "S_k", "H1", "H2", "r("):
            self.assertNotIn(token, body.replace("H2 unit", ""), token)

    def test_an_empty_loop_is_refused_even_run_from_the_checkout(self):
        # run from the repository root (the documented use: --log defaults to a relative path), an old
        # tree whose loop/ is empty or has no __init__.py must not silently import the checkout's loop/
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(os.path.join(empty, "loop"), exist_ok=True)
        code, out, err = _run(empty, REPO, "--log", self.log)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("holds no outcomes.py", err)
        bare = os.path.join(self.tmp, "bare")                       # a namespace package: outcomes.py, no __init__.py,
        shutil.copytree(os.path.join(REPO, "loop"), os.path.join(bare, "loop"),         # and main's first-wins join, so its
                        ignore=shutil.ignore_patterns("__pycache__", "__init__.py"))    # reading differs from the checkout's
        with open(os.path.join(bare, "loop", "outcomes.py"), "a", encoding="utf-8") as fh:
            fh.write("\n\ndef rank(r):\n    return 0\n")
        code, out, err = _run(bare, REPO, "--log", self.log)
        self.assertEqual(code, 0, err)                               # it read with the tree's own code, not the checkout's
        self.assertIn("ticks whose joined outcome differs old vs new: 1 20260923T100700Z\n", out)

    def test_the_probe_refuses_a_loop_that_is_not_the_trees(self):
        # the realpath check behind -I: run the probe without -I from a cwd whose loop/ is the checkout,
        # for a tree that holds none, and it must refuse rather than read the checkout's code
        import importlib.machinery, importlib.util
        spec = importlib.util.spec_from_loader("readers_diff", importlib.machinery.SourceFileLoader("readers_diff", TOOL))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        empty = os.path.join(self.tmp, "nothing")
        os.makedirs(empty, exist_ok=True)
        p = subprocess.run([sys.executable, "-B", "-c", mod.PROBE, empty, self.log], capture_output=True, text=True, cwd=REPO)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("loop.outcomes came from", p.stderr)
        self.assertIn("not the tree's", p.stderr)

    def test_skips_and_recoveries_are_counted_by_line(self):
        # one line of two non-row objects is ONE skipped line (load writes one entry a line), and a
        # row whose mid is not a finite positive number is not priced
        log = os.path.join(self.tmp, "counting.jsonl")
        with open(self.log, encoding="utf-8") as fh:
            good = [l for l in fh.read().splitlines() if l.startswith("{") and l.endswith("}")][:3]
        nan_row = json.loads(good[0])
        nan_row["mid"] = float("nan")
        with open(log, "w", encoding="utf-8") as fh:
            fh.write("\n".join(good) + "\n" + '{"v":1}{"v":1}' + "\n" + json.dumps(nan_row) + "\n")
        code, out, err = _run(REPO, REPO, "--log", log)
        self.assertEqual(code, 0, err)
        self.assertIn("lines skipped: old 1 / new 1;", out)
        self.assertIn("priced tick_ids with more than one row: 0\n", out)

    def test_it_writes_no_bytecode_into_either_tree(self):
        pyc = os.path.join(self.old, "loop", "__pycache__")
        shutil.rmtree(pyc, ignore_errors=True)
        code, _, err = _run(self.old, REPO, "--log", self.log)
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(pyc))

    def test_a_tree_without_loop_or_a_missing_log_is_said_so(self):
        code, out, err = _run(self.tmp, REPO, "--log", self.log)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("holds no loop/ directory", err)
        code, out, err = _run(REPO, REPO, "--log", os.path.join(self.tmp, "none.jsonl"))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no log at", err)

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
        with open(cls.log, "w") as fh:
            for r in rows[:30]:
                fh.write(json.dumps(r) + "\n")
            fh.write('{"v": 1, "tick_id": "20260923T103000Z", "ts_rx": "2026-09-23T10:3')   # torn, then a whole row glued on
            for r in rows[30:]:
                fh.write(json.dumps(r) + "\n")
        cls.old = os.path.join(cls.tmp, "old")                  # this tree, with the join's first-wins rule of main
        os.makedirs(cls.old)
        shutil.copytree(os.path.join(REPO, "loop"), os.path.join(cls.old, "loop"), ignore=shutil.ignore_patterns("__pycache__"))
        with open(os.path.join(cls.old, "loop", "outcomes.py"), "a") as fh:
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
        for token in ("mid_h", "ret_h", "bps", "101.0", "100.0", "up", "down", "flat", "S_k", "H1", "H2", "r("):
            self.assertNotIn(token, out.replace("H2 unit", ""), token)

    def test_an_empty_loop_is_refused_even_run_from_the_checkout(self):
        # run from the repository root (the documented use: --log defaults to a relative path), an old
        # tree whose loop/ is empty or has no __init__.py must not silently import the checkout's loop/
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(os.path.join(empty, "loop"), exist_ok=True)
        code, out, err = _run(empty, REPO, "--log", self.log)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("holds no outcomes.py", err)
        bare = os.path.join(self.tmp, "bare")                       # a namespace package: outcomes.py, no __init__.py
        shutil.copytree(os.path.join(REPO, "loop"), os.path.join(bare, "loop"), ignore=shutil.ignore_patterns("__pycache__", "__init__.py"))
        code, out, err = _run(bare, REPO, "--log", self.log)
        self.assertIn(code, (0, 2), err)
        if code == 0:                                                # it read with the tree's own code
            self.assertIn(f"read by old {bare}", out)

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

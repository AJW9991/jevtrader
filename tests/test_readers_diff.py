"""bin/readers-diff: one log read by two code trees, reported as counts and tick_ids only."""
import contextlib, io, json, os, shutil, signal, subprocess, sys, tempfile, unittest
from unittest import mock

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
        self.assertTrue(head.startswith(f"log {self.log} ("), head)
        self.assertIn(" bytes, one copy read by both): read by old ", head)
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
        inf_row = dict(json.loads(good[1]), mid=float("inf"))                # shares good[1]'s tick: not a second PRICED row
        with open(log, "w", encoding="utf-8") as fh:
            fh.write("\n".join(good) + "\n" + '{"v":1}{"v":1}' + "\n" + json.dumps(nan_row) + "\n" + json.dumps(inf_row) + "\n")
        code, out, err = _run(REPO, REPO, "--log", log)
        self.assertEqual(code, 0, err)
        self.assertIn("lines skipped: old 1 / new 1;", out)
        self.assertIn("priced tick_ids with more than one row: 0\n", out)

    def test_both_trees_read_one_copy_and_it_is_removed(self):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        p = subprocess.run([sys.executable, TOOL, REPO, REPO, "--log", self.log], capture_output=True, text=True, cwd=REPO,
                           env=dict(os.environ, TMPDIR=tmpdir))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(f"({os.path.getsize(self.log)} bytes, one copy read by both)", p.stdout)
        self.assertEqual(os.listdir(tmpdir), [])                         # the copy is gone

    def _module(self):
        import importlib.machinery, importlib.util
        spec = importlib.util.spec_from_loader("readers_diff", importlib.machinery.SourceFileLoader("readers_diff", TOOL))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_both_probes_are_given_the_same_copy_never_the_live_log(self):
        # the point of reading once: a probe given the live log path would see rows the other did not
        mod, seen = self._module(), []
        real = mod.read_with

        def spy(tree, log):
            seen.append((log, os.path.exists(log)))
            return real(tree, log)
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        with mock.patch.object(mod, "read_with", spy), mock.patch.object(mod.tempfile, "tempdir", tmpdir), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.main([REPO, REPO, "--log", self.log]), 0)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0][0], seen[1][0])                         # the same copy for both trees
        self.assertNotEqual(os.path.realpath(seen[0][0]), os.path.realpath(self.log))
        self.assertTrue(seen[0][1])
        self.assertEqual(os.listdir(tmpdir), [])                          # and it is gone afterwards

    def test_a_sigterm_or_sighup_mid_probe_still_removes_the_copy(self):
        for sig in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=sig.name):
                mod = self._module()
                tmpdir = tempfile.mkdtemp()
                self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)

                def unguarded(signum, frame, name=sig.name):              # in place of the default action, which would end
                    raise AssertionError(f"readers-diff installed no {name} handler")   # the whole test run, not fail this test
                self.addCleanup(signal.signal, sig, signal.signal(sig, unguarded))

                def killed(tree, log, sig=sig):
                    os.kill(os.getpid(), sig)                             # delivered at once to this process
                    return {}, None
                with mock.patch.object(mod, "read_with", killed), mock.patch.object(mod.tempfile, "tempdir", tmpdir):
                    with self.assertRaises(SystemExit) as cm:
                        mod.main([REPO, REPO, "--log", self.log])
                self.assertEqual(cm.exception.code, 128 + sig)
                self.assertEqual(os.listdir(tmpdir), [])
                self.assertIs(signal.getsignal(sig), unguarded)          # the handler is put back, whatever it was

    def test_a_copy_that_cannot_be_written_is_a_message(self):
        mod = self._module()
        real_open = open

        def full(path, mode="r", *a, **k):
            if "wb" == mode and str(path).endswith("decisions.jsonl") and "readers-diff-" in str(path):
                raise OSError(28, "No space left on device")
            return real_open(path, mode, *a, **k)
        err = io.StringIO()
        with mock.patch("builtins.open", side_effect=full), contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.main([REPO, REPO, "--log", self.log]), 2)
        self.assertIn("cannot write a temporary copy", err.getvalue())

    def test_no_temporary_directory_is_a_message(self):
        # a volume so full that mkdtemp fails too (on the Mac TMPDIR, /tmp and /var/tmp are one volume):
        # exit 2 and a message, not a traceback and exit 1. Once where the directory cannot be made, once
        # where gettempdir finds nowhere to write at all
        mod = self._module()
        missing = os.path.join(self.tmp, "no-such-dir")
        nowhere = FileNotFoundError(2, "No usable temporary directory found in ['/tmp', '/var/tmp']")
        for patch, says in ((mock.patch.object(mod.tempfile, "tempdir", missing),
                             f"readers-diff: cannot make a temporary directory in {missing}: "),
                            (mock.patch.object(mod.tempfile, "gettempdir", side_effect=nowhere),
                             "readers-diff: cannot make a temporary directory: No usable temporary directory found in ")):
            err = io.StringIO()
            with patch, contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(mod.main([REPO, REPO, "--log", self.log]), 2)
            self.assertIn(says, err.getvalue())
            self.assertTrue(err.getvalue().endswith(" (set TMPDIR elsewhere)\n"), err.getvalue())
            self.assertEqual(out.getvalue(), "")
        self.assertFalse(os.path.exists(missing))

    def test_a_non_ascii_failure_reads_under_a_c_locale(self):
        # the probes' output is decoded as UTF-8 whatever the locale: a tree whose code fails with a
        # non-ASCII message is exit 2 and the message, not a UnicodeDecodeError traceback
        bad = os.path.join(self.tmp, "accented-failure")                   # an ASCII path: the runner may itself be in a C locale
        os.makedirs(os.path.join(bad, "loop"), exist_ok=True)
        with open(os.path.join(bad, "loop", "__init__.py"), "w", encoding="utf-8") as fh:
            fh.write("")
        with open(os.path.join(bad, "loop", "outcomes.py"), "w", encoding="utf-8") as fh:
            fh.write("raise RuntimeError('d\u00e9j\u00e0 cass\u00e9')\n")
        env = dict(os.environ, LC_ALL="C", LANG="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0")
        p = subprocess.run([sys.executable, TOOL, bad, REPO, "--log", self.log], capture_output=True, cwd=REPO, env=env)
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertNotIn(b"UnicodeDecodeError", p.stderr)

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

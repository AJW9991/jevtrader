"""The suite cleans up after itself: a test module run in a fresh interpreter, with TMPDIR pointed at an
empty directory, leaves that directory empty. A run used to leave ~22 temp dirs (6 MB) behind:
tempfile.mkdtemp() in a setUpClass or a test with nothing to remove it. Checked here on two fast
modules end to end (every class and test cleanup has to run for the directory to come back empty),
in a subprocess, so this module's own temp files cannot be mistaken for theirs. And the suite runs
under any locale: every text-mode open() on the test side names its encoding."""
import ast, glob, os, subprocess, sys, tempfile, unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS)


class TempDirs(unittest.TestCase):
    def test_status_and_dash_leave_tmpdir_empty(self):
        tmpdir = self.enterContext(tempfile.TemporaryDirectory())
        env = {**os.environ, "TMPDIR": tmpdir, "PYTHONPATH": REPO, "PYTHONDONTWRITEBYTECODE": "1"}
        r = subprocess.run([sys.executable, "-m", "unittest", "test_status", "test_dash"], cwd=TESTS, env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertRegex(r.stderr, r"Ran \d+ tests")
        self.assertEqual(os.listdir(tmpdir), [])


class Encodings(unittest.TestCase):
    ELSEWHERE = set()

    def test_every_text_open_on_the_test_side_names_its_encoding(self):
        # under LC_ALL=C with PYTHONUTF8=0 an open() without one reads and writes ASCII, and 14 tests
        # errored on the section signs, em dashes and accents the repository's files hold
        missing = []
        for path in sorted(glob.glob(os.path.join(TESTS, "*.py"))):
            if os.path.basename(path) in self.ELSEWHERE:
                continue
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for n in ast.walk(tree):
                if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open"):
                    continue
                mode = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "mode"), None)
                binary = isinstance(mode, ast.Constant) and "b" in str(mode.value)
                if not binary and not any(k.arg == "encoding" for k in n.keywords):
                    missing.append(f"{os.path.basename(path)}:{n.lineno}")
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()

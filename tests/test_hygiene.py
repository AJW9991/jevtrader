"""The suite cleans up after itself: a test module run in a fresh interpreter, with TMPDIR pointed at an
empty directory, leaves that directory empty. A run used to leave ~22 temp dirs (6 MB) behind:
tempfile.mkdtemp() in a setUpClass or a test with nothing to remove it. Checked here on two fast
modules end to end (every class and test cleanup has to run for the directory to come back empty),
in a subprocess, so this module's own temp files cannot be mistaken for theirs."""
import os, subprocess, sys, tempfile, unittest

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


if __name__ == "__main__":
    unittest.main()

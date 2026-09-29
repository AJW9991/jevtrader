"""bin/backup-data copies data/ and logs/ to DEST byte for byte and logs one line per run in
logs/backup.log. It refuses, with exit 2 and nothing written or created, a DEST inside the root or
the repo, one that is an ancestor of the root, one under the crypto repo's path, or one holding a
newline. A second run over the same DEST is a no-op that still logs. Nothing here opens a socket."""
import os, subprocess, tempfile, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "bin", "backup-data")
ROWS = b'{"tick_id": "20260925T214000Z", "mode": "live"}\n{"tick_id": "20260925T2141'   # a torn last line


def run(*args, home=None):
    env = dict(os.environ)
    if home is not None:
        env["HOME"] = home
    return subprocess.run(["/bin/bash", SCRIPT, *args], capture_output=True, text=True, timeout=60, env=env)


class BackupData(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(self.enterContext(tempfile.TemporaryDirectory()))
        self.root = os.path.join(self.tmp, "root")
        os.makedirs(os.path.join(self.root, "data"))
        os.makedirs(os.path.join(self.root, "logs"))
        with open(os.path.join(self.root, "data", "decisions.jsonl"), "wb") as fh:
            fh.write(ROWS)
        with open(os.path.join(self.root, "data", "heartbeat"), "w", encoding="utf-8") as fh:
            fh.write("2026-09-25T21:40:00.000Z\n")
        with open(os.path.join(self.root, "logs", "propose.log"), "w", encoding="utf-8") as fh:
            fh.write("2026-09-25T08:30:03Z propose start\n")
        self.dest = os.path.join(self.tmp, "dest")

    def _log_lines(self):
        path = os.path.join(self.root, "logs", "backup.log")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return fh.read().splitlines()

    def test_copies_byte_for_byte_and_logs_one_line_per_run(self):
        r = run("--root", self.root, self.dest)
        self.assertEqual(r.returncode, 0, r.stderr)
        for rel in ("data/decisions.jsonl", "data/heartbeat", "logs/propose.log"):
            with open(os.path.join(self.root, rel), "rb") as a, open(os.path.join(self.dest, rel), "rb") as b:
                self.assertEqual(a.read(), b.read(), rel)
        lines = self._log_lines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(f"backup OK decisions.jsonl {len(ROWS)} bytes -> {self.dest}", lines[0])
        self.assertEqual(r.stdout.strip(), lines[0])
        r = run("--root", self.root, self.dest)                     # idempotent; still logs
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self._log_lines()), 2)
        with open(os.path.join(self.dest, "data", "decisions.jsonl"), "rb") as fh:
            self.assertEqual(fh.read(), ROWS)

    def test_refuses_a_dest_inside_the_root_the_repo_or_above_the_root(self):
        cases = {
            "inside root": os.path.join(self.root, "backup"),
            "inside repo": os.path.join(REPO, "data", "backup-test-never-created"),
            "ancestor of root": self.tmp,
            "newline": os.path.join(self.tmp, "de\nst"),
        }
        for label, dest in cases.items():
            with self.subTest(label):
                r = run("--root", self.root, dest)
                self.assertEqual(r.returncode, 2, (label, r.stderr))
                self.assertIn("nothing written", r.stderr)
                self.assertFalse(os.path.exists(os.path.join(dest, "data", "decisions.jsonl")), label)
        self.assertFalse(os.path.exists(cases["inside repo"]))
        self.assertFalse(os.path.exists(cases["inside root"]))
        self.assertEqual(self._log_lines(), [])

    def test_refuses_a_dest_under_the_crypto_repo_path(self):
        forbidden = os.path.join(self.tmp, "Projects", "crypto-trading-system")   # the guard's path under a fake HOME
        os.makedirs(forbidden)
        dest = os.path.join(forbidden, "jevtrader-backup")
        r = run("--root", self.root, dest, home=self.tmp)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("crypto repo", r.stderr)
        self.assertFalse(os.path.exists(dest))
        self.assertEqual(self._log_lines(), [])

    def test_usage_without_data_or_with_a_flag_it_does_not_know(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        self.assertEqual(run("--root", empty, self.dest).returncode, 2)
        self.assertEqual(run("--root", self.root, "--delete", self.dest).returncode, 2)
        self.assertFalse(os.path.exists(self.dest))


if __name__ == "__main__":
    unittest.main()

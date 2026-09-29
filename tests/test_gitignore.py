""".gitignore as git reads it (PREREG-v2 §2, §8, §10): the stores, HALT, PAUSE.* and logs stay out of git; v1's and v2's
exclusion logs, the looks log, the probe's output, the per-product plists and v2's tables are versioned; a proposal's
json and .table.json stay out and its .md is in. Asked of `git check-ignore --no-index`, so the answer is git's, whatever
the order or form of the lines; the paths need not exist."""
import os, shutil, subprocess, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IGNORED = ("data/decisions.jsonl", "data/sends.tsv", "data/heartbeat", "data/loop.lock", "data/HALT", "data/PAUSE.ETH-USD",
           "data/ETH-USD/decisions.jsonl", "data/ETH-USD/heartbeat", "data/dash.html", "data/digest-2026-10-24.md",
           "logs/loop-launchd.log", "logs/loop-launchd-ETH-USD.log", "logs/loop-launchd-every-product.log",
           "proposals/2026-10-24.json", "proposals/2026-10-24.table.json", "PREREG-v2.md.bak-20261001-120000")
VERSIONED = ("data/exclusions.tsv", "data/exclusions-v2.tsv", "data/looks.tsv", "probe/2026-09-30/run.json",
             "probe/2026-09-30/volume.json", "probe/2026-09-30/ETH-USD.jsonl", "proposals/2026-10-24.md",
             "launchd/com.alexward.jevloop.loop.ETH-USD.plist", "launchd/one-process/com.alexward.jevloop.loop.every-product.plist",
             "launchd/loop-product.plist.in", "prompts/v2.table.ETH-USD.json", "prompts/v3.table.ETH-USD.json",
             "RESULTS.md", "RESULTS-v2.md", "ERRATA.md")


class GitIgnore(unittest.TestCase):
    def ignored(self, path):
        r = subprocess.run(["git", "-c", "core.excludesFile=" + os.devnull, "check-ignore", "-q", "--no-index", path],
                           cwd=REPO, capture_output=True, text=True, timeout=30,
                           env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1"))
        self.assertIn(r.returncode, (0, 1), f"git check-ignore {path}: {r.stderr}")
        return r.returncode == 0

    def setUp(self):
        if not shutil.which("git") or not os.path.exists(os.path.join(REPO, ".git")):
            self.skipTest("git, or this checkout's .git, is not here")

    def test_what_stays_out_of_git(self):
        self.assertEqual([p for p in IGNORED if not self.ignored(p)], [])

    def test_what_is_versioned(self):
        self.assertEqual([p for p in VERSIONED if self.ignored(p)], [])


if __name__ == "__main__":
    unittest.main()

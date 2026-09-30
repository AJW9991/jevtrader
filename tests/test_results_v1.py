"""bin/results-v1: v1's `make results` behind PREREG-v2 §10's guard, on real temporary git repositories holding a copy of
it (the copy checks its own tree), offline. The run it wraps is a stand-in that writes the file; v1's inference is never
run here. And the Makefile: no target runs v1's sample inference except through the guard."""
import os, re, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "bin", "results-v1")
SENTENCE = ("v2 draft tag absent: v2 as drafted is not run; a second block is a new pre-registration written after v1 "
            "was read")
WRITE = "open('RESULTS.md', 'x').write('jev-paper-loop inference, mode sample\\nthe body\\n'); open('ran', 'w').close()"


class Guard(unittest.TestCase):
    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git not on PATH")
        self.repo = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}))
        os.makedirs(os.path.join(self.repo, "bin"))
        shutil.copy2(TOOL, os.path.join(self.repo, "bin", "results-v1"))
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "main")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def build_branch(self, tag=True, annotated=True, on_branch=True):
        self.git("checkout", "-q", "-b", "prereg-v2")
        self.git("commit", "-q", "--allow-empty", "-m", "the build")
        if tag and not on_branch:
            self.git("checkout", "-q", "-b", "elsewhere")
            self.git("commit", "-q", "--allow-empty", "-m", "off the build")
        if tag:
            self.git("tag", *(["-a", "-m", "frozen before make results (v1)"] if annotated else []), "prereg-v2-draft")
        self.git("checkout", "-q", "main")

    def run_it(self, *flags, code=WRITE):
        return subprocess.run([sys.executable, os.path.join(self.repo, "bin", "results-v1"), *flags, "--out", "RESULTS.md",
                               "--", sys.executable, "-c", code], cwd=self.repo, capture_output=True, text=True,
                              encoding="utf-8", timeout=60)

    def results(self):
        with open(os.path.join(self.repo, "RESULTS.md"), encoding="utf-8") as fh:
            return fh.read()

    def assertRefused(self, why):
        r = self.run_it()
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn(f"results: refused before the run (PREREG-v2 section 10): {why}", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "ran")))           # the run never started
        self.assertFalse(os.path.exists(os.path.join(self.repo, "RESULTS.md")))

    def test_no_draft_tag_refuses_before_the_run(self):
        self.assertRefused("no annotated tag prereg-v2-draft")
        self.build_branch(tag=False)
        self.assertRefused("no annotated tag prereg-v2-draft")

    def test_a_lightweight_tag_is_not_the_draft_tag(self):
        self.build_branch(annotated=False)
        self.assertRefused("no annotated tag prereg-v2-draft")

    def test_a_tag_off_the_build_branch_refuses(self):
        self.build_branch(on_branch=False)
        tag = self.git("rev-parse", "refs/tags/prereg-v2-draft")
        self.assertRefused(f"the annotated tag prereg-v2-draft {tag} (commit ")

    def test_the_draft_tag_on_the_build_branch_runs_and_its_sha_heads_the_file(self):
        self.build_branch()
        tag, commit, head = (self.git("rev-parse", r) for r in ("refs/tags/prereg-v2-draft", "prereg-v2-draft^{commit}",
                                                                 "prereg-v2"))
        r = self.run_it()
        self.assertEqual(r.returncode, 0, r.stderr)
        line = (f"v2 draft tag: prereg-v2-draft {tag} (commit {commit}), an ancestor of prereg-v2 {head}; checked before"
                " this run (PREREG-v2 §10)")
        self.assertEqual(self.results(), f"jev-paper-loop inference, mode sample\n{line}\nthe body\n")
        self.assertTrue(r.stdout.startswith(f"v2 draft tag: prereg-v2-draft {tag} (commit {commit})"), r.stdout)
        r = self.run_it("--no-v2", code=WRITE.replace("'x'", "'w'"))
        self.assertEqual(self.results(), f"jev-paper-loop inference, mode sample\n{line}\nNO_V2=1 was given; the draft tag"
                         " was there, so it overrode nothing\nthe body\n")

    def test_no_v2_runs_without_the_tag_and_writes_the_sentence(self):
        r = self.run_it("--no-v2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.results(), f"jev-paper-loop inference, mode sample\n{SENTENCE}\n(NO_V2=1 given; the guard"
                         " found: no annotated tag prereg-v2-draft)\nthe body\n")

    def test_a_failed_run_keeps_its_exit_and_nothing_is_written(self):
        self.build_branch()
        r = self.run_it(code="import sys; sys.exit(3)")
        self.assertEqual(r.returncode, 3)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "RESULTS.md")))
        r = self.run_it(code="pass")                                                  # exit 0, no file
        self.assertEqual(r.returncode, 2)
        self.assertIn("results: the run exited 0 but RESULTS.md cannot be read", r.stderr)


class Makefile(unittest.TestCase):
    """PREREG-v2 §10: on main, `make results` is v1's run behind the guard; in the build it is v2's own (its seal check).
    Either way no Makefile line runs v1's sample inference except through bin/results-v1."""

    def test_v1s_sample_run_goes_through_the_guard(self):
        with open(os.path.join(REPO, "Makefile"), encoding="utf-8") as fh:
            recipes = [l for l in fh.read().splitlines() if l.startswith("\t")]
        v1 = [l for l in recipes if re.search(r"-m loop\.inference\b(?!_)", l) and "--sample" in l]
        for line in v1:
            self.assertIn("bin/results-v1", line)
            self.assertLess(line.index("bin/results-v1"), line.index("-m loop.inference"))
        env = {k: v for k, v in os.environ.items() if not k.startswith("MAKE")}
        dry = subprocess.run(["make", "-s", "-n", "-C", REPO, "results", "NO_V2=1", f"PY={sys.executable}"],
                             capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        if re.search(r"-m loop\.inference\b(?!_)", dry.stdout):                    # main's results: v1's run
            self.assertIn(f"{sys.executable} bin/results-v1 --out RESULTS.md --no-v2 -- {sys.executable} -m loop.inference"
                          " --sample --out RESULTS.md", dry.stdout)


if __name__ == "__main__":
    unittest.main()

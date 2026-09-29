"""STEPS.md §10 (PREREG-v2's tags and switch), the commands the author runs by hand: the python snippets run here on
scratch stores, the shell steps that only touch git run on a scratch repository, and what needs launchd or the network
is read. Where STEPS.md and PREREG-v2.md differ, PREREG-v2.md wins; these tests hold STEPS to it."""
import os, re, subprocess, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEVIATIONS_HEAD = "\n## v2 deviations (PREREG-v2 §13"


def steps():
    with open(os.path.join(REPO, "STEPS.md"), encoding="utf-8") as fh:
        return fh.read()


def subsection(number):
    """STEPS.md's `### <number> ...` to the next heading or rule."""
    m = re.search(rf"^### {re.escape(number)} .*?(?=^### |^## |^---|\Z)", steps(), re.M | re.S)
    if m is None:
        raise AssertionError(f"STEPS.md has no ### {number}")
    return m.group(0)


def bash_blocks(text):
    return re.findall(r"^```bash\n(.*?)^```\n", text, re.M | re.S)


def git(*args):
    """git in this repository, bytes decoded as UTF-8 (any locale)."""
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True)
    return r.returncode, r.stdout.decode("utf-8", "replace")


class DraftTag(unittest.TestCase):
    """10.4: what main takes before the draft tag."""

    def test_main_takes_the_deviations_table_before_the_draft_tag(self):
        # §13: from the draft tag main adds at the end of ERRATA.md, and the build's ERRATA.md ends with the v2
        # deviations table; unless main has the table before the tag, switch step (4)'s merge meets both sides adding at
        # the same end and stops (the S5 refuter's defect 4). The commit 10.4 merges into main carries the table as this
        # tree has it, and the v1 results guard with it.
        merges = re.findall(r"git merge --no-ff --no-edit ([0-9a-f]{7,40})", "".join(bash_blocks(subsection("10.4"))))
        self.assertEqual(len(merges), 1, merges)
        sha = merges[0]
        if git("cat-file", "-e", f"{sha}^{{commit}}")[0] != 0:
            self.skipTest(f"{sha} is not in this clone's history (a shallow checkout)")
        code, theirs = git("show", f"{sha}:ERRATA.md")
        self.assertEqual(code, 0)
        with open(os.path.join(REPO, "ERRATA.md"), encoding="utf-8") as fh:
            ours = fh.read()
        self.assertIn(DEVIATIONS_HEAD, theirs)
        self.assertTrue(ours[ours.index(DEVIATIONS_HEAD):].startswith(theirs[theirs.index(DEVIATIONS_HEAD):]))
        self.assertEqual(git("merge-base", "--is-ancestor", "097edc0", sha)[0], 0, "the v1 results guard comes with it")

    def test_a_row_after_mains_additions_goes_under_a_continued_heading(self):
        for number in ("10.4", "10.6"):
            self.assertIn("## v2 deviations (continued)", subsection(number), number)


if __name__ == "__main__":
    unittest.main()

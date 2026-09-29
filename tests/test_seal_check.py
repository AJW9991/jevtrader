"""bin/seal-check (PREREG-v2 §13) on real temporary git repositories, offline: the seal's (a)-(e), --draft before the
draft tag and --since after the seal, each check passing and failing on its own. The tool is loaded in process so a
test's three products (fixture_products) apply; a few runs go through its command line and through inference_v2.seal,
which runs it the way v2's make results does. No test runs it on this repository (its (e) runs `make test`)."""
import importlib.machinery, importlib.util, io, json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

from loop import config, inference_v2, prompts, state
from fixture_products import add_products

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "bin", "seal-check")
BLANK = "________"


def _load():
    loader = importlib.machinery.SourceFileLoader("seal_check", TOOL)
    spec = importlib.util.spec_from_file_location("seal_check", TOOL, loader=loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


SC = _load()

PREREG = f"""# PREREG-v2 (a test's copy)

**Status: DRAFT.** Nothing in the header is a field.

## 0. What changes

Nothing here is a field.

## 2. Products

- over the UTC day **D = 2026-09-30**, named here before it runs.
  Written before the draft tag: Products: `SOL-USD`, `ETH-USD`, `XRP-USD`.

## 8. The treatment

- id `claude-test-1` (night `2026-09-29`).

## 12. Fields filled after the draft tag (and nothing else)

| field | filled when | from |
|---|---|---|

Fee tiers (30-day band / maker / taker, read UTC `{BLANK}`): `{BLANK}`
Tables rebuilt at the switch: `{BLANK}`
T_first_v2: `{BLANK}`   T0_v2: `{BLANK}`   Sealed by: `{BLANK}`   on: `{BLANK}`

## 13. The tags

`bin/seal-check --draft` refuses if any `{BLANK}` remains outside §12.

## 14. Amendments between `prereg-v2-doc` and `prereg-v2-draft`

- 2026-09-29, Claude: an entry.
"""
FEE_LINE = f"Fee tiers (30-day band / maker / taker, read UTC `{BLANK}`): `{BLANK}`"
REBUILD = f"Tables rebuilt at the switch: `{BLANK}`"
SEAL_LINE = f"T_first_v2: `{BLANK}`   T0_v2: `{BLANK}`   Sealed by: `{BLANK}`   on: `{BLANK}`"
ERRATA = """# ERRATA (a test's copy)

## PREREG.md

| § | The document says | The code does | Kind |
|---|---|---|---|
| §2 | "UTC day" | T0-anchored days | stale |

## v2 deviations (PREREG-v2 §13)

| Commit | What it fixes | Why outside §13 (c) |
|---|---|---|
"""
PIN = "a" * 64


def frozen(prereg=PIN, table=PIN, spec="b" * 64):
    return ('FILES = {\n'
            f'    "SPEC.md": "{spec}",\n'
            f'    "PREREG-v2.md": "{prereg}",   # this file\n'
            f'    "prompts/v2.table.SOL-USD.json": "{table}",\n'
            '}\n')


class Scratch(unittest.TestCase):
    """A repository in the shape §13 reads: PREREG-v2.md, ERRATA.md, tests/test_frozen.py, prompts/ (the real v2.json,
    CURRENT v2, one v2 table per product), probe/2026-09-30/, loop/code.py, and a Makefile whose `test` exits
    $SEALTEST_EXIT; tagged prereg-v2-doc, then prereg-v2-draft on the same commit."""

    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git not on PATH")
        self.products = add_products(self, 3)
        self.repo = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.dict(os.environ, {                      # no user or system git config leaks in
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid", "SEALTEST_EXIT": "0"}))
        self.git("init", "-q", "-b", "main")
        self.write("PREREG-v2.md", PREREG)
        self.write("ERRATA.md", ERRATA)
        self.write("tests/test_frozen.py", frozen())
        with open(os.path.join(REPO, "prompts", "v2.json"), encoding="utf-8") as fh:
            self.write("prompts/v2.json", fh.read())
        self.write("prompts/CURRENT", "v2\n")
        for p in self.products:
            self.table(p, "jev-1.13.0")
        self.write("probe/2026-09-30/run.json", json.dumps({"day": "2026-09-30"}) + "\n")
        self.write("probe/2026-09-30/volume.json", "{}\n")
        for p in self.products[1:]:
            self.write(f"probe/2026-09-30/{p}.jsonl", "{}\n")
        self.write("loop/code.py", "X = 1\nY = 2\nZ = 3\n")
        self.write("loop/book.py", "def at_cadence():\n    return 1\n")
        self.write("Makefile", "test:\n\t@exit $${SEALTEST_EXIT:-0}\n")
        self.commit("base")
        self.git("tag", "-a", "prereg-v2-doc", "-m", "doc")
        self.git("tag", "-a", "prereg-v2-draft", "-m", "draft")

    # ---- the repository ----
    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def path(self, name):
        return os.path.join(self.repo, name)

    def write(self, name, text):
        os.makedirs(os.path.dirname(self.path(name)), exist_ok=True)
        with open(self.path(name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def read(self, name):
        with open(self.path(name), encoding="utf-8") as fh:
            return fh.read()

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def table(self, p, model, answer="hold", drop=0):
        answers = {state.state_string(a, config.base(p)): answer for a in state.all_states()}
        for s in sorted(answers)[:drop]:
            del answers[s]
        doc = {"version": "v2", "product": p, "prompt_sha": prompts.sha("v2", self.path("prompts")),
               "model_answered": model, "answers": answers}
        self.write(f"prompts/v2.table.{p}.json", json.dumps(doc, indent=2) + "\n")
        return prompts.sha_of(doc)

    def replace(self, name, old, new):
        text = self.read(name)
        self.assertEqual(text.count(old), 1, old)
        self.write(name, text.replace(old, new))

    def filled(self):
        """§12 filled and committed: the seal's own precondition, before a test's changes."""
        self.fill()
        return self.commit("§12 filled")

    def fill(self, fee=None, rebuild="no", seal=("20261024T213000Z", "20261025T213100Z", "Alex", "2026-10-25")):
        fee = fee or ("2026-10-24T09:00Z", "$0-$10K / 0.60 % / 1.20 %; $10K+ / 0.40 % / 0.80 %")
        self.replace("PREREG-v2.md", FEE_LINE, f"Fee tiers (30-day band / maker / taker, read UTC `{fee[0]}`): `{fee[1]}`")
        if rebuild is not None:
            self.replace("PREREG-v2.md", REBUILD, f"Tables rebuilt at the switch: `{rebuild}`")
        a, b, c, d = seal
        self.replace("PREREG-v2.md", SEAL_LINE, f"T_first_v2: `{a}`   T0_v2: `{b}`   Sealed by: `{c}`   on: `{d}`")

    # ---- the tool ----
    def check(self, *argv):
        buf = io.StringIO()
        code = SC.main(list(argv), repo=self.repo, out=buf)
        return code, buf.getvalue()

    def assertPasses(self, *argv):
        code, text = self.check(*argv)
        self.assertEqual(code, 0, text)
        self.assertIn("seal-check: PASS", text.splitlines()[-1])
        return text

    def assertFails(self, *argv, says=(), failed=None):
        code, text = self.check(*argv)
        self.assertEqual(code, 1, text)
        self.assertIn("seal-check: FAIL", text.splitlines()[-1])
        for s in says:
            self.assertIn(s, text)
        if failed is not None:
            self.assertTrue(text.splitlines()[-1].endswith(f": {failed} failed"), text.splitlines()[-1])
        return text


class Seal(Scratch):
    """§13's seal: (a)-(e), each failing alone; what (c) lets through."""

    def switch(self):
        """What main takes from the draft tag to the switch and at it: every path (c) excludes or allows."""
        self.write("RESULTS.md", "v1's result\n")
        self.write("HANDOFF.md", "notes\n")
        self.write("proposals/2026-10-01.md", "a proposal\n")
        self.write("data/exclusions.tsv", "day\tfill%\n")
        self.write("prompts/v3.json", "{}\n")                              # v1's bin/promote, before the switch
        self.write("prompts/CURRENT", "v3\n")
        self.commit("v1's month")
        self.write("prompts/CURRENT", "v2\n")                              # switch step 8
        self.write("ERRATA.md", ERRATA + "\n## Later\nan addition at the end\n")
        self.fill()
        self.commit("the switch and §12")

    def test_the_switch_and_a_filled_section_12_pass_every_check(self):
        self.switch()
        text = self.assertPasses()
        for tag in "abcde":
            self.assertIn(f"({tag}) PASS", text)
        self.assertIn("(c) `git diff -U0 refs/tags/prereg-v2-draft HEAD -- . ':(exclude)RESULTS.md' ':(exclude)HANDOFF.md'"
                      " ':(exclude)proposals' ':(exclude)data/exclusions.tsv'` (renames off), verbatim:", text)
        self.assertIn("    | +T_first_v2: `20261024T213000Z`   T0_v2: `20261025T213100Z`   Sealed by: `Alex`   on: `2026-10-25`", text)
        self.assertIn("    | +++ b/prompts/v3.json", text)
        for excluded in ("RESULTS.md", "HANDOFF.md", "proposals/2026-10-01.md", "data/exclusions.tsv"):
            self.assertNotIn(f"+++ b/{excluded}", text)
        self.assertIn("(§12) PASS: PREREG-v2.md §12 is filled: no ________ left, T0_v2 20261025T213100Z and 2 fee tier(s)"
                      " read as loop.dash reads them", text)
        self.assertIn("(e) PASS: `make test` exited 0", text)
        self.assertNotIn("NOTE", text)

    def test_a_blank_left_in_section_12_fails(self):
        # the header: prereg-v2-seal is made "once §12's fields are filled, tagged only after bin/seal-check exits 0";
        # after the tag --since refuses any edit of PREREG-v2.md, so a blank left then stays blank (the S5 refuter's
        # defect 2: T0_v2 blank for good, bin/promote refusing for the whole block)
        self.fill(rebuild=None)
        self.commit("§12 but the rebuild line")
        self.assertFails(says=["(§12) FAIL: PREREG-v2.md §12 still holds 1 ________ (the seal is made once §12 is filled;"
                               " after it, --since refuses any edit of PREREG-v2.md)", "(e) NOT RUN: (§12) failed already"],
                         failed="§12")
        self.write("PREREG-v2.md", PREREG)
        self.commit("§12 blank again")
        self.assertFails(says=["still holds 7 ________", "T0_v2 is blank"], failed="§12")

    def test_a_section_12_its_readers_cannot_read_fails(self):
        # T0_v2 and the fee tiers are read by bin/promote, the report, the dash and v2's make results (loop.dash): a
        # field filled in a form they refuse is as unfillable after the tag as a blank
        self.fill(seal=("20261024T213000Z", "20261025T2130Z", "Alex", "2026-10-25"))
        self.commit("T0_v2 not a tick_id")
        self.assertFails(says=["(§12) FAIL:", "T0_v2 '20261025T2130Z' is not a tick_id on a minute boundary"], failed="§12")
        self.write("PREREG-v2.md", PREREG)
        self.commit("back")
        self.fill(fee=("2026-10-24T09:00Z", "$0-$10K / 0.60 / 1.20"))
        self.commit("fees without their unit")
        self.assertFails(says=["(§12) FAIL:", "fee-tier row '$0-$10K / 0.60 / 1.20'"], failed="§12")

    def test_a_no_draft_tag_on_head_fails_a_and_nothing_is_judged(self):
        self.filled()
        self.git("tag", "-d", "prereg-v2-draft")
        text = self.assertFails(says=["(a) FAIL", "(c) NOT RUN: there is no draft tag", "(e) NOT RUN: (a) failed already"],
                                 failed="a")
        self.assertNotIn("verbatim", text)
        self.git("checkout", "-q", "-b", "side")
        self.commit("off the branch")
        self.git("tag", "-a", "prereg-v2-draft", "-m", "draft")
        self.git("checkout", "-q", "main")
        self.assertFails(says=["(a) FAIL: `git merge-base --is-ancestor refs/tags/prereg-v2-draft HEAD` exited 1"])

    def test_b_a_dirty_tree_fails(self):
        self.filled()
        self.write("stray.txt", "x\n")
        self.assertFails(says=["(b) FAIL: `git status --porcelain` lists 1: ?? stray.txt", "(c) PASS"], failed="b")

    def test_d_current_not_v2_fails(self):
        self.write("prompts/v3.json", "{}\n")
        self.write("prompts/CURRENT", "v3\n")
        self.commit("promoted")
        self.assertFails(says=["(d) FAIL: prompts/CURRENT names 'v3', not v2",
                               "prompts/v3.json: added after prereg-v2-draft and named by prompts/CURRENT"])

    def test_e_a_failing_suite_fails(self):
        self.filled()
        os.environ["SEALTEST_EXIT"] = "1"
        self.assertFails(says=["(e) FAIL: `make test` exited 2"], failed="e")

    def test_c_refuses_code_a_changed_version_and_a_moved_file(self):
        self.filled()
        self.replace("loop/code.py", "Y = 2", "Y = 3")
        self.commit("a code change")
        self.assertFails(says=["loop/code.py: changed after prereg-v2-draft, which §13 (c) does not allow"], failed="c")
        self.write("prompts/v2.json", self.read("prompts/v2.json") + "\n")
        self.commit("v2.json edited")
        self.assertFails(says=["prompts/v2.json: changed after prereg-v2-draft"])
        self.git("mv", "loop/book.py", "loop/book2.py")
        self.commit("a move")
        self.assertFails(says=["loop/book.py: removed after", "loop/book2.py: added after"])

    def test_c_prereg_only_section_12_blanks_filled(self):
        self.replace("PREREG-v2.md", "Nothing here is a field.", "Nothing here is a field, now.")
        self.commit("§0 edited")
        self.assertFails(says=["PREREG-v2.md @@ -7,1 +7,1 @@: line 7 'Nothing here is a field.' is not a blank field of §12"])

    def test_c_prereg_a_fill_that_changes_the_line_around_it_fails(self):
        self.replace("PREREG-v2.md", SEAL_LINE, SEAL_LINE.replace("Sealed by:", "Sealed:").replace(BLANK, "x"))
        self.commit("the line reworded")
        self.assertFails(says=["changes beyond its blanks"])

    def test_c_prereg_a_line_added_to_section_12_fails(self):
        self.replace("PREREG-v2.md", REBUILD, REBUILD + "\nA new line.")
        self.commit("an added line")
        self.assertFails(says=["not a one-for-one replacement of lines"])

    def test_c_prereg_the_section_13_mention_of_the_blank_is_not_a_field(self):
        self.replace("PREREG-v2.md", f"refuses if any `{BLANK}` remains", "refuses if any `x` remains")
        self.commit("§13 edited")
        self.assertFails(says=["is not a blank field of §12"])

    def test_c_errata_only_additions_at_the_end(self):
        self.filled()
        self.write("ERRATA.md", ERRATA + "| more |\n")
        self.commit("a row under the deviations heading")
        self.assertFails(says=["ERRATA.md's v2 deviations row '| more |' names no commit in its first cell"])
        self.write("ERRATA.md", ERRATA + "\n## Later\n\n| more |\n")
        self.commit("added under a heading of its own")
        self.assertPasses()
        self.replace("ERRATA.md", "T0-anchored days", "days of 24 h")
        self.commit("edited")
        self.assertFails(says=["ERRATA.md: a hunk that is not a pure addition at the end"])

    def test_c_test_frozen_only_the_pins_of_prereg_v2_and_the_tables(self):
        self.filled()
        self.write("tests/test_frozen.py", frozen(prereg="c" * 64, table="d" * 64))
        self.commit("re-pinned")
        self.assertPasses()
        self.write("tests/test_frozen.py", frozen(prereg="c" * 64, table="d" * 64, spec="e" * 64))
        self.commit("SPEC re-pinned")
        self.assertFails(says=["tests/test_frozen.py @@ -2,3 +2,3 @@: a change beyond the sha of a pin"])
        self.write("tests/test_frozen.py", frozen(prereg="c" * 64, table="d" * 64).replace("# this file", "# edited"))
        self.commit("a comment on the pin line")
        self.assertFails(says=["tests/test_frozen.py @@ -3,2 +3,2 @@: a change beyond the sha of a pin"])

    def test_c_a_version_file_v1_added_and_not_current_passes_and_v2s_own_does_not(self):
        self.filled()
        self.write("prompts/v4.json", "{}\n")
        self.commit("v1's promote")
        self.assertPasses()
        self.write("prompts/v2.table.BTC-USD.json", "{}\n")
        self.commit("a table of no product")
        self.assertFails(says=["prompts/v2.table.BTC-USD.json: added after prereg-v2-draft"])


class Rebuild(Scratch):
    """§8's once-only rebuild at the switch: every product's table, one commit, another Jev version, §12's line."""

    def rebuild(self, model="jev-1.14.0", products=None):
        return {p: self.table(p, model, answer="buy") for p in (products or self.products)}

    def test_a_rebuild_recorded_in_section_12_passes(self):
        shas = self.rebuild()
        self.commit("tables rebuilt")
        self.fill(rebuild="jev-1.14.0; " + ", ".join(f"{p} {s[:12]}" for p, s in shas.items()))
        self.commit("§12")
        self.assertPasses()

    def test_a_rebuild_the_line_does_not_name_fails(self):
        shas = self.rebuild()
        self.commit("tables rebuilt")
        self.fill(rebuild="jev-1.14.0; " + ", ".join(f"{p} {s[:12]}" for p, s in list(shas.items())[:2]))
        self.commit("§12")
        p = self.products[2]
        self.assertFails(says=[f"does not name {p}'s table sha {shas[p][:12]}"])

    def test_a_rebuild_with_the_line_blank_or_no_fails(self):
        self.rebuild()
        self.commit("tables rebuilt")
        self.assertFails(says=["v2's tables were rebuilt and §12's rebuild line does not record it"])
        self.fill(rebuild="no")
        self.commit("§12 says no")
        self.assertFails(says=["does not name jev-1.14.0"])

    def test_no_rebuild_the_line_may_read_only_no(self):
        self.fill(rebuild="jev-1.14.0")
        self.commit("§12 names a rebuild that did not happen")
        self.assertFails(says=["reads 'jev-1.14.0' while no v2 table differs from the draft tag's"])

    def test_a_rebuild_by_the_same_model_fails(self):
        shas = self.rebuild(model="jev-1.13.0")
        self.commit("rebuilt by the same model")
        self.fill(rebuild="jev-1.13.0 " + " ".join(shas.values()))
        self.commit("§12")
        self.assertFails(says=["answered by 'jev-1.13.0', the model the draft tag's table names"])

    def test_one_product_rebuilt_fails(self):
        shas = self.rebuild(products=self.products[:1])
        self.commit("one table")
        self.fill(rebuild="jev-1.14.0 " + " ".join(shas.values()))
        self.commit("§12")
        self.assertFails(says=[f"{self.products[0]} rebuilt and {', '.join(self.products[1:])} not"])

    def test_two_rebuild_commits_fail(self):
        self.rebuild(products=self.products[:1])
        self.commit("first")
        shas = self.rebuild()
        self.commit("second")
        self.fill(rebuild="jev-1.14.0 " + " ".join(shas.values()))
        self.commit("§12")
        self.assertFails(says=["prompts/v2.table.*.json: changed by 2 commits after prereg-v2-draft"])

    def test_a_table_that_is_not_a_table_fails(self):
        self.rebuild()
        self.table(self.products[1], "jev-1.14.0", drop=1)
        self.commit("80 states")
        self.fill(rebuild="jev-1.14.0")
        self.commit("§12")
        self.assertFails(says=[f"prompts/v2.table.{self.products[1]}.json: not a v2 table as prompts.table reads one"])


class Deviations(Scratch):
    """ERRATA.md's "v2 deviations" table: a listed commit's diff is taken out before (c) judges the rest."""

    def test_a_listed_fix_passes_and_is_printed_an_unlisted_one_fails(self):
        self.filled()
        self.replace("loop/code.py", "Y = 2", "Y = 3")
        fix = self.commit("a fix")
        self.assertFails(says=["loop/code.py: changed after prereg-v2-draft"])
        self.write("ERRATA.md", ERRATA + f"| `{fix[:9]}` | Y | a fix outside (c) |\n")
        self.commit("listed")
        text = self.assertPasses()
        self.assertIn(f"(c) listed deviation {fix} (ERRATA.md's v2 deviations table), taken out before the judgement:", text)
        self.assertIn("    | +Y = 3", text)
        self.assertIn("(1 listed deviation(s) taken out)", text)
        self.assertNotIn("READ", text)

    def test_a_listed_deviation_in_a_voiding_file_is_named(self):
        self.filled()
        self.replace("loop/book.py", "return 1", "return 2")
        fix = self.commit("at_cadence changed")
        self.write("ERRATA.md", ERRATA + f"| {fix} | at_cadence | a fix |\n")
        self.commit("listed")
        text = self.assertPasses()
        self.assertIn(f"(c) READ: the listed deviation {fix[:12]} touches loop/book.py, which holds at_cadence, replay,"
                      " paired: a deviation touching those voids the draft tag (§13)", text)

    def test_a_listed_fix_main_made_after_the_draft_tag_passes(self):
        # §13: from the draft tag until switch step (6) main takes a fix only as a listed deviation. Merged into the
        # build at switch step (4) and into main at step (6), that commit is one HEAD reaches and the draft tag does
        # not, without descending from the tag (the S5 refuter's defect 1)
        self.git("tag", "-d", "prereg-v2-draft")
        self.git("checkout", "-q", "-b", "prereg-v2")
        self.write("loop/v2only.py", "V2 = True\n")
        self.commit("the build")
        self.git("tag", "-a", "prereg-v2-draft", "-m", "draft")
        self.git("checkout", "-q", "main")
        self.replace("loop/code.py", "Y = 2", "Y = 3")
        fix = self.commit("a fix main needed after the draft tag")
        self.write("ERRATA.md", ERRATA + f"| {fix[:10]} | Y | outside (c) |\n")
        self.commit("its row, an addition at the end")
        self.git("checkout", "-q", "prereg-v2")
        self.git("merge", "-q", "--no-edit", "main")                     # switch step (4)
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--ff-only", "prereg-v2")                # switch step (6)
        self.filled()
        text = self.assertPasses()
        self.assertIn(f"(c) listed deviation {fix} (ERRATA.md's v2 deviations table), taken out before the judgement:", text)
        self.assertIn("(1 listed deviation(s) taken out)", text)

    def test_a_listed_commit_head_does_not_reach_fails(self):
        self.git("checkout", "-q", "-b", "side")
        self.replace("loop/code.py", "Y = 2", "Y = 3")
        side = self.commit("a fix on a branch never merged")
        self.git("checkout", "-q", "main")
        self.write("ERRATA.md", ERRATA + f"| {side[:12]} | Y | a fix |\n")
        self.commit("listed")
        self.assertFails(says=[f"names {side[:12]}, which is not in prereg-v2-draft..HEAD"])

    def test_a_listed_deviation_in_the_text_the_schedule_or_the_readers_is_named(self):
        # §13 voids the draft tag on a deviation touching the alphabet or its cuts, inference, the exclusion readers or
        # promote's schedule: PREREG-v2.md and SPEC.md define them, loop/prompts.py enforces the schedule, days_table
        # feeds the exclusion recompute, and outcomes.join feeds replay and paired (the S5 refuter's defect 5)
        self.filled()
        self.replace("PREREG-v2.md", "Nothing here is a field.", "Nothing here is a field. H1 alpha is now 1/10.")
        self.write("SPEC.md", "a changed spec\n")
        self.write("loop/prompts.py", "def current(tick_id):\n    return 'v3'\n")
        self.write("loop/report.py", "def days_table():\n    return {}\n")
        self.write("loop/outcomes.py", "def join():\n    return []\n")
        fix = self.commit("a deviation in the text, the schedule and the readers")
        self.write("ERRATA.md", ERRATA + f"| {fix[:10]} | x | y |\n")
        self.commit("listed")
        text = self.assertPasses()
        for path, holds in (("PREREG-v2.md", "the text that defines every one of them"), ("SPEC.md", "the alphabet and its cuts"),
                            ("loop/prompts.py", "current and activation"), ("loop/report.py", "days_table"),
                            ("loop/outcomes.py", "the t + h join")):
            self.assertIn(f"(c) READ: the listed deviation {fix[:12]} touches {path}, which holds {holds}", text)

    def test_every_file_defining_what_section_13_names_is_on_a_read_line(self):
        # where this tree defines what §13's voiding sentence names: each file is on a READ line
        holders = {"at_cadence": "loop/book.py", "replay": "loop/book.py", "paired": "loop/book.py",
                   "join": "loop/outcomes.py", "days_table": "loop/report.py", "pooled": "loop/inference_v2.py",
                   "recompute": "loop/exclusions_v2.py", "rule_c": "loop/state.py", "adjectives": "loop/state.py",
                   "current": "loop/prompts.py", "activation": "loop/prompts.py"}
        for name, path in holders.items():
            with open(os.path.join(REPO, path), encoding="utf-8") as fh:
                self.assertRegex(fh.read(), rf"(?m)^def {name}\(", path)
            self.assertIn(path, SC.VOIDING, f"{name} is defined in {path}")

    def test_a_later_commit_over_a_listed_one_cannot_be_taken_out(self):
        self.replace("loop/code.py", "Y = 2", "Y = 3")
        fix = self.commit("a fix")
        self.replace("loop/code.py", "Y = 3", "Y = 4")
        self.commit("over it, unlisted")
        self.write("ERRATA.md", ERRATA + f"| {fix[:12]} | Y | a fix |\n")
        self.commit("listed")
        self.assertFails(says=[f"the listed deviation {fix[:12]} cannot be taken out of HEAD"])

    def test_a_row_that_names_no_commit_after_the_tag_fails(self):
        draft = self.git("rev-parse", "HEAD")
        self.write("ERRATA.md", ERRATA + "| see above | x | y |\n")
        self.commit("a row without a commit")
        self.assertFails(says=["names no commit in its first cell"])
        self.write("ERRATA.md", ERRATA + f"| {draft} | x | y |\n")
        self.commit("the draft commit itself")
        self.assertFails(says=[f"names {draft[:12]}, which is not in prereg-v2-draft..HEAD"])
        self.write("ERRATA.md", ERRATA + "| 0123456789abc | x | y |\n")
        self.commit("no such commit")
        self.assertFails(says=["names 0123456789abc, which is not a commit here"])

    def test_rows_under_another_heading_are_not_listed(self):
        self.replace("loop/code.py", "Y = 2", "Y = 3")
        fix = self.commit("a fix")
        self.write("ERRATA.md", ERRATA + f"\n## Something else\n\n| {fix} | Y | not a deviation row |\n")
        self.commit("a row elsewhere")
        self.assertFails(says=["loop/code.py: changed after prereg-v2-draft"])


class Draft(Scratch):
    """--draft: §13's three refusals, and §2's D."""

    def test_the_draft_tree_passes(self):
        text = self.assertPasses("--draft")
        for tag in ("blanks", "probe", "tables", "§14"):
            self.assertIn(f"{tag}: PASS", text)
        self.assertIn(f"probe/2026-09-30/ is in HEAD with run.json, volume.json, {self.products[1]}.jsonl, "
                      f"{self.products[2]}.jsonl", text)

    def test_a_blank_outside_section_12_fails_and_names_its_line(self):
        self.replace("PREREG-v2.md", "id `claude-test-1`", f"id `{BLANK}`")
        self.replace("PREREG-v2.md", "Nothing in the header", f"`{BLANK}` in the header")
        self.commit("blanks")
        self.assertFails("--draft", says=[f"{BLANK} remains outside §12 at line 3 (the header), line 16 (§8)"], failed="blanks")

    def test_a_missing_probe_file_or_another_day_fails(self):
        self.git("rm", "-q", f"probe/2026-09-30/{self.products[2]}.jsonl")
        self.commit("one product's rows gone")
        self.assertFails("--draft", says=[f"probe/2026-09-30/ lacks {self.products[2]}.jsonl in HEAD"], failed="probe")
        self.write(f"probe/2026-09-30/{self.products[2]}.jsonl", "{}\n")
        self.write("probe/2026-09-30/run.json", json.dumps({"day": "2026-10-01"}) + "\n")
        self.commit("another day's run")
        self.assertFails("--draft", says=["probe/2026-09-30/run.json names day '2026-10-01', not 2026-09-30"])
        self.write("probe/2026-09-30/run.json", json.dumps({"day": "2026-09-30"}) + "\n")
        self.commit("back")
        self.write("probe/2026-09-30/volume.json", "{}\n")
        os.remove(self.path("probe/2026-09-30/volume.json"))
        self.assertPasses("--draft")                                     # HEAD is read, not the files on disk
        self.replace("PREREG-v2.md", "**D = 2026-09-30**", "D = 2026-09-30")
        self.commit("D unnamed")
        self.assertFails("--draft", says=["§2 of PREREG-v2.md names no day as **D = YYYY-MM-DD**"])

    def test_a_missing_or_malformed_table_fails(self):
        self.git("rm", "-q", f"prompts/v2.table.{self.products[1]}.json")
        self.commit("a table gone")
        self.assertFails("--draft", says=[f"prompts/v2.table.{self.products[1]}.json is not in HEAD"], failed="tables")
        self.table(self.products[1], "jev-1.13.0", drop=1)
        self.commit("80 states")
        self.assertFails("--draft", says=[f"prompts/v2.table.{self.products[1]}.json:", "not exactly the 81 states"])

    def test_section_14_none_yet_with_a_changed_text_fails(self):
        self.replace("PREREG-v2.md", "- 2026-09-29, Claude: an entry.", "(none yet)")
        self.commit("§14 emptied")
        self.git("tag", "-f", "-a", "prereg-v2-doc", "-m", "doc")
        self.assertPasses("--draft")                                     # unchanged since the doc tag
        self.replace("PREREG-v2.md", "Nothing here is a field.", "Nothing here is a field, still.")
        self.commit("an unlogged edit")
        self.assertFails("--draft", says=["PREREG-v2.md changed since the doc tag while §14 reads \"(none yet)\""],
                         failed="§14")
        self.git("tag", "-d", "prereg-v2-doc")
        self.assertFails("--draft", says=["no tag refs/tags/prereg-v2-doc"])

    def test_the_real_document_passes_once_its_pre_tag_fields_are_written(self):
        # PREREG-v2.md as it stands: every blank outside §12, §13 and §14 filled, and §12's real field lines filled
        with open(os.path.join(REPO, "PREREG-v2.md"), encoding="utf-8") as fh:
            text = fh.read()
        lines = text.split("\n")
        labels = SC.section_labels(lines)
        self.assertTrue(any(BLANK in l for l, s in zip(lines, labels) if s == "13"))   # §13 names the token
        blank12 = {FEE_LINE.split("`")[0]: FEE_LINE, REBUILD.split("`")[0]: REBUILD, SEAL_LINE.split("`")[0]: SEAL_LINE}
        pre = "\n".join(l.replace(BLANK, "X") if s not in ("12", "13", "14") else    # §12 blank again once it is filled
                        next((v for k, v in blank12.items() if s == "12" and l.startswith(k)), l) for l, s in zip(lines, labels))
        self.write("PREREG-v2.md", pre)
        self.commit("the real text, pre-tag fields written")
        self.git("tag", "-f", "-a", "prereg-v2-doc", "-m", "doc")
        self.git("tag", "-f", "-a", "prereg-v2-draft", "-m", "draft")
        self.assertPasses("--draft")
        self.fill()
        self.commit("§12 at the seal")
        self.assertPasses()


class Since(Scratch):
    """--since TAG: §13's post-seal allowlist, over the files on disk."""

    def setUp(self):
        super().setUp()
        self.git("tag", "-a", "prereg-v2-seal", "-m", "sealed")

    def test_the_allowlist_passes(self):
        self.write("prompts/v3.json", "{}\n")
        for p in self.products:
            self.write(f"prompts/v3.table.{p}.json", "{}\n")
        self.write("prompts/CURRENT", "v3\n")
        self.write("HANDOFF.md", "notes\n")
        self.write("proposals/2026-11-02.md", "a proposal\n")
        self.write("data/exclusions-v2.tsv", "day\tproduct\n")
        self.write("data/looks.tsv", "utc\targv\thead\n")
        self.commit("the block's commits")
        self.write("data/looks.tsv", "utc\targv\thead\nx\ty\tz\n")          # not yet committed: judged too
        self.write("RESULTS-v2.md", "written by the run\n")                  # untracked: named, not judged
        text = self.assertPasses("--since", "prereg-v2-seal")
        self.assertIn("allowlist: PASS", text)
        self.assertIn("    | +x\ty\tz", text)
        self.assertIn("NOTE: untracked, not judged: RESULTS-v2.md", text)

    def test_a_change_off_the_allowlist_fails_committed_or_not(self):
        self.replace("loop/code.py", "Y = 2", "Y = 3")
        self.assertFails("--since", "prereg-v2-seal", says=["loop/code.py: changed since prereg-v2-seal"], failed="allowlist")
        self.commit("committed")
        self.assertFails("--since", "prereg-v2-seal", says=["loop/code.py: changed since prereg-v2-seal"])

    def test_v2s_tables_errata_and_another_products_table_are_off_it(self):
        self.table(self.products[0], "jev-1.14.0", answer="sell")
        self.write("prompts/v3.table.BTC-USD.json", "{}\n")
        self.write("ERRATA.md", ERRATA + "more\n")
        self.commit("off the list")
        self.assertFails("--since", "prereg-v2-seal", says=[
            "3 path(s) off §13's post-seal allowlist:", "ERRATA.md: changed since",
            "prompts/v3.table.BTC-USD.json: added since", f"prompts/v2.table.{self.products[0]}.json: changed since"])

    def test_a_tag_that_is_missing_or_off_the_branch_fails(self):
        self.assertFails("--since", "prereg-v2-nothing", says=["tag: FAIL: prereg-v2-nothing names no commit here"])
        self.git("checkout", "-q", "-b", "side")
        self.commit("elsewhere")
        self.git("tag", "-a", "elsewhere", "-m", "x")
        self.git("checkout", "-q", "main")
        self.assertFails("--since", "elsewhere", says=["is NOT an ancestor of HEAD"], failed="tag")


class CommandLine(unittest.TestCase):
    """The tool as a person and v2's make results run it: its usage, and inference_v2.seal on a repository holding a
    copy of it (the copy checks its own tree)."""

    def test_usage_and_the_modes_exclude_each_other(self):
        r = subprocess.run([sys.executable, TOOL, "--help"], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("usage: seal-check"), r.stdout)
        r = subprocess.run([sys.executable, TOOL, "--draft", "--since", "x"], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not allowed with argument", r.stderr)

    def test_v2s_make_results_runs_it_since_the_seal(self):
        if not shutil.which("git"):
            self.skipTest("git not on PATH")
        repo = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}))

        def git(*args):
            return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

        shutil.copytree(os.path.join(REPO, "loop"), os.path.join(repo, "loop"), ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(os.path.join(REPO, "prompts"), os.path.join(repo, "prompts"))
        os.makedirs(os.path.join(repo, "bin"))
        shutil.copy2(TOOL, os.path.join(repo, "bin", "seal-check"))
        with open(os.path.join(repo, ".gitignore"), "w", encoding="utf-8") as fh:
            fh.write("__pycache__/\n")
        git("init", "-q", "-b", "main")
        git("add", "-A")
        git("commit", "-q", "-m", "sealed tree")
        git("tag", "-a", "prereg-v2-seal", "-m", "sealed")
        with open(os.path.join(repo, "HANDOFF.md"), "w", encoding="utf-8") as fh:
            fh.write("notes\n")
        git("add", "-A")
        git("commit", "-q", "-m", "a handoff")
        x = inference_v2.seal(repo)
        self.assertEqual((x["ok"], x["why"]), (True, None), "\n".join(x["lines"]))
        self.assertIn("    | seal-check: PASS (--since prereg-v2-seal)", x["lines"])
        with open(os.path.join(repo, "loop", "config.py"), "a", encoding="utf-8") as fh:
            fh.write("# an edit\n")
        x = inference_v2.seal(repo)
        self.assertEqual((x["ok"], x["why"]), (False, "bin/seal-check --since prereg-v2-seal exited 1"))
        self.assertIn("    |     loop/config.py: changed since prereg-v2-seal", x["lines"])


if __name__ == "__main__":
    unittest.main()

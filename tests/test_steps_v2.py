"""STEPS.md §10 (PREREG-v2's tags and switch), the commands the author runs by hand: the python snippets run here on
scratch stores, the shell steps that only touch git run on a scratch repository, and what needs launchd or the network
is read. Where STEPS.md and PREREG-v2.md differ, PREREG-v2.md wins; these tests hold STEPS to it."""
import contextlib, datetime, hashlib, io, json, os, re, subprocess, tempfile, unittest
from unittest import mock

from loop import config
from fixture_products import add_products

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


def heredoc(block):
    """The python a block feeds to `python3 - <<'EOF'`."""
    m = re.search(r"python3 - <<'EOF'[^\n]*\n(.*?)^EOF\n", block, re.M | re.S)
    if m is None:
        raise AssertionError(f"no python3 heredoc in {block[:200]!r}")
    return m.group(1)


def git(*args):
    """git in this repository, bytes decoded as UTF-8 (any locale)."""
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True)
    return r.returncode, r.stdout.decode("utf-8", "replace")


class ProductsCommit(unittest.TestCase):
    """10.1: the probe's volume and the products' commit."""

    def test_main_is_merged_into_the_build_before_prereg_v2_is_edited_there(self):
        # PREREG-v2 §13 (0): "Before any further edit of PREREG-v2.md on the build branch, main is merged into
        # prereg-v2". 10.1 is the build's first edit of it (a void D's §14 entry, §2's products and their §14 entry), and
        # it had no merge (the S5 refuter's defect 9)
        text = subsection("10.1")
        first = bash_blocks(text)[0]
        self.assertEqual(first.strip(), "cd ~/Projects/jev-paper-loop-v2 && git merge --no-edit main && make test")
        self.assertIn("§13 (0)", text[:text.index(first)])


    def test_a_merge_that_changes_prereg_v2_moves_its_pin_in_the_merge_commit(self):
        # tests/test_frozen.py pins PREREG-v2.md (PREREG-v2 §10), and main has edited PREREG-v2.md since the build last
        # took it, so 10.1's merge fails make test on that pin; the pin moves in the commit that changes the file
        text = " ".join(subsection("10.1").split())
        self.assertIn("`tests/test_frozen.py` pins PREREG-v2.md's bytes", text)
        self.assertIn("git add tests/test_frozen.py && git commit --amend --no-edit && make test", text)
        self.assertIn("Every later edit of PREREG-v2.md before the draft tag (each a §14 entry) moves the pin in its own"
                      " commit the same way", text)

    def test_the_products_commit_writes_specs_rows_and_its_pin(self):
        # SPEC v2 §5 gives each product's TICK_P and atoms, and tests/test_spec.py holds that table to config.PRODUCTS
        text = " ".join(subsection("10.1").split())
        self.assertIn("SPEC.md §5's per-product table", text)
        self.assertIn("and SPEC.md's sha", text)


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


class Stores(unittest.TestCase):
    """A snippet of STEPS §10 run as the author runs it from the checkout: `from loop import config`, three products'
    stores (config.store) and SPEC.md and prompts/ in the working directory, all in a temporary root."""

    def setUp(self):
        self.products = add_products(self, 3)
        self.root = self.enterContext(tempfile.TemporaryDirectory())
        data = os.path.join(self.root, "data")
        os.makedirs(data)
        self.enterContext(mock.patch.multiple(config, DATA=data, DECISIONS=os.path.join(data, "decisions.jsonl"),
                                              SENDS=os.path.join(data, "sends.tsv"), LOCK=os.path.join(data, "loop.lock"),
                                              HEARTBEAT=os.path.join(data, "heartbeat")))
        with open(os.path.join(self.root, "SPEC.md"), "w", encoding="utf-8") as fh:
            fh.write("SPEC v2 (a test's copy)\n")
        with open(os.path.join(self.root, "SPEC.md"), "rb") as fh:
            self.sha = hashlib.sha256(fh.read()).hexdigest()

    def row(self, tick, ts_rx, v2=True, absence=None, model="jev-1.13.0"):
        return {"v": 1, "tick_id": tick, "ts_rx": ts_rx, "mode": "live", "absence": absence,
                "spec_sha": self.sha if v2 else "5d4f355e" + "0" * 56, "model_answered": None if absence else model}

    def log(self, product, rows):
        path = config.store(product).decisions
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(r) + "\n" for r in rows))

    def run_snippet(self, code):
        """(stdout, the SystemExit it raised or None), run with the root as the working directory."""
        out, cwd = io.StringIO(), os.getcwd()
        os.chdir(self.root)
        try:
            with contextlib.redirect_stdout(out):
                try:
                    exec(compile(code, "STEPS.md", "exec"), {"__name__": "__main__"})
                except SystemExit as e:
                    return out.getvalue(), e
        finally:
            os.chdir(cwd)
        return out.getvalue(), None


class SwitchGit(unittest.TestCase):
    """10.5: a switch step that only touches git, run in a scratch repository by each shell the author may paste it into."""

    def step(self, label):
        text = subsection("10.5")
        block = bash_blocks(text[text.index(label):])[0]
        prefix = "cd ~/Projects/jev-paper-loop && "
        self.assertTrue(block.startswith(prefix), block)
        return block[len(prefix):]

    def scratch(self, current):
        d = self.enterContext(tempfile.TemporaryDirectory())
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
                   GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")

        def run(*argv):
            r = subprocess.run(argv, cwd=d, env=env, capture_output=True)
            return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
        os.makedirs(os.path.join(d, "prompts"))
        for name, text in (("prompts/CURRENT", current + "\n"), ("HANDOFF.md", "notes\n")):
            with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        for argv in (("git", "init", "-q", "-b", "main"), ("git", "add", "-A"), ("git", "commit", "-q", "-m", "switched")):
            self.assertEqual(run(*argv)[0], 0)
        return d, run

    def test_step_8_leaves_a_clean_tree_either_way(self):
        # (8) records "CURRENT already v2" in HANDOFF.md, and bin/seal-check (b) wants a clean tree: the line is
        # committed with the step, as its other branch commits CURRENT (the S5 refuter's defect 10: left uncommitted,
        # the seal failed on " M HANDOFF.md")
        shells = [s for s in ("/bin/bash", "/bin/zsh") if os.path.exists(s)]
        self.assertTrue(shells)
        for shell in shells:
            for current in ("v2", "v3"):
                d, run = self.scratch(current)
                code, out = run(shell, "-c", self.step("(8) CURRENT"))
                self.assertEqual(code, 0, (shell, current, out))
                self.assertEqual(run("git", "status", "--porcelain"), (0, ""), (shell, current))
                with open(os.path.join(d, "prompts", "CURRENT"), encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), "v2\n")
                with open(os.path.join(d, "HANDOFF.md"), encoding="utf-8") as fh:
                    last = fh.read().splitlines()[-1]
                self.assertEqual(last.endswith("switch step 8: CURRENT already v2"), current == "v2", (shell, last))
                self.assertEqual(run("git", "log", "-1", "--format=%s")[1].split(":")[0],
                                 "HANDOFF.md" if current == "v2" else "prompts/CURRENT", (shell, current))

    def test_every_handoff_line_is_committed_before_the_seal(self):
        text = subsection("10.5")
        self.assertIn("committed", text[text.index("(8a)"):text.index("(8b)")])
        self.assertIn("HANDOFF.md lines of switch steps (8) and (8a) are committed", subsection("10.6"))


class ShakedownModel(Stores):
    """10.5 (11a): the Jev version that answered the first shakedown rows against the pinned tables'."""

    def snippet(self):
        text = subsection("10.5")
        return heredoc(bash_blocks(text[text.index("(11a)"):])[0])

    def tables(self, model):
        os.makedirs(os.path.join(self.root, "prompts"))
        for p in self.products:
            with open(os.path.join(self.root, "prompts", f"v2.table.{p}.json"), "w", encoding="utf-8") as fh:
                json.dump({"version": "v2", "product": p, "model_answered": model}, fh)

    def rows(self, minutes, **kw):
        return [self.row(f"20261023T22{m:02d}00Z", f"2026-10-23T22:{m:02d}:00.400Z", **kw) for m in minutes]

    def test_the_first_v2_rows_are_read_and_a_product_without_one_waits(self):
        # §10 (11a): "model_answered of the first shakedown rows". The snippet took the last three live rows of each
        # log's last 64 KB with no spec_sha filter, so SOL's v1 rows counted, a product whose first rows had no answer
        # read "DIFFERENT", and a product with no log yet raised (the S5 refuter's defect 8)
        self.tables("jev-1.14.0")
        self.log("SOL-USD", [self.row(f"20261023T21{m:02d}00Z", "2026-10-23T21:00:00.500Z", v2=False) for m in range(10)]
                 + self.rows([5], model="jev-1.14.0"))
        self.log(self.products[1], self.rows([6], absence="jev"))
        out, stop = self.run_snippet(self.snippet())
        self.assertIsNone(stop, out)
        self.assertEqual(out.splitlines(), [
            "SOL-USD first v2 rows: ['jev-1.14.0'] tables: jev-1.14.0 same",
            f"{self.products[1]} no answered v2 row yet (tables: jev-1.14.0): run this again in a minute",
            f"{self.products[2]} no answered v2 row yet (tables: jev-1.14.0): run this again in a minute"])

    def test_another_version_on_the_first_rows_says_rebuild_whatever_answers_later(self):
        self.tables("jev-1.13.0")
        for p in self.products:
            self.log(p, self.rows(range(5, 8), model="jev-1.14.0") + self.rows(range(8, 20), model="jev-1.13.0"))
        out, stop = self.run_snippet(self.snippet())
        self.assertIsNone(stop, out)
        for p, line in zip(self.products, out.splitlines()):
            self.assertEqual(line, f"{p} first v2 rows: ['jev-1.14.0'] tables: jev-1.13.0 DIFFERENT: rebuild the tables"
                                   " once (PREREG-v2 §8, §12)")


class OneProcess(Stores):
    """10.8: the swap to the one-process plist."""

    def test_the_loops_go_once_every_heartbeat_names_this_minute_and_it_comes_a_minute_later(self):
        # the one-process plist loads with RunAtLoad true: bootstrapped in the minute the per-product loops were booted
        # out, it ticks that minute again and writes each product a second row for it (switch step (9) waits for a
        # later minute for exactly this); and a bootout that lands mid-tick costs the minute its row (the S5 refuter's
        # defect 11). The loops now go once every product's heartbeat names the current minute, and the plist comes in
        # a later minute than their bootout.
        blocks = bash_blocks(subsection("10.8"))
        out_block = next(b for b in blocks if "launchctl bootout" in b)
        in_block = next(b for b in blocks if "launchctl bootstrap" in b)
        self.assertLess(out_block.index("python3 - <<'EOF'"), out_block.index("launchctl bootout"))
        self.assertIn('OUT=$(date -u +%H%M)', out_block[out_block.index("launchctl bootout"):])
        self.assertLess(in_block.index('until [ "$(date -u +%H%M)" != "$OUT" ]; do sleep 1; done'),
                        in_block.index("launchctl bootstrap"))
        wait = heredoc(out_block)

        def minute():
            return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M")

        def beat(p, m):
            path = config.store(p).heartbeat
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"{m}:04.321Z\n")
        for p in self.products[:2]:
            beat(p, minute())
        beat(self.products[2], "2026-10-23T22:04")                      # its tick of this minute has not written yet
        slept = []

        def sleep(s):
            slept.append(s)
            if len(slept) > 5:
                raise AssertionError("the wait never ended")
            for p in self.products:                                   # every loop's tick lands
                beat(p, minute())
        with mock.patch("time.sleep", sleep):
            out, stop = self.run_snippet(wait)
        self.assertIsNone(stop, out)
        self.assertTrue(slept, "it booted the loops out while a product's tick was owed")
        self.assertIn("every heartbeat names", out)


class SealFields(Stores):
    """10.6: T_first_v2 and T0_v2 from the logs."""

    def snippet(self):
        return heredoc(bash_blocks(subsection("10.6"))[0])

    def test_t_first_v2_is_the_first_live_rows_tick_id(self):
        # PREREG-v2 §2 names each product's first live row carrying the v2 spec sha; the sealed PREREG.md reads a row's
        # time as its tick_id (§2: "T_first = tick_id of the first row ..."), and the sample window is by tick_id. Read
        # by ts_rx, T0_v2 came out a minute late whenever the latest first row was received after its minute's :00 (the
        # S5 refuter's defect 3; its hand-computed fixture)
        self.log("SOL-USD", [self.row("20261023T210000Z", "2026-10-23T21:00:00.500Z", v2=False),
                             self.row("20261023T220500Z", "2026-10-23T22:05:00.812Z")])
        self.log(self.products[1], [self.row("20261023T220600Z", "2026-10-23T22:06:00.300Z", absence="jev"),
                                    self.row("20261023T220700Z", "2026-10-23T22:07:01.100Z")])
        self.log(self.products[2], [self.row("20261023T220700Z", "2026-10-23T22:07:00.000Z")])
        out, stop = self.run_snippet(self.snippet())
        self.assertIsNone(stop, out)
        self.assertIn("T_first_v2: 20261023T220700Z   T0_v2: 20261024T220700Z", out)

    def test_a_product_without_a_v2_live_row_or_a_log_stops_it(self):
        self.log("SOL-USD", [self.row("20261023T220500Z", "2026-10-23T22:05:00.812Z")])
        self.log(self.products[1], [self.row("20261023T220600Z", "2026-10-23T22:06:00.300Z", absence="jev")])
        out, stop = self.run_snippet(self.snippet())
        self.assertIsNotNone(stop)
        self.assertEqual(str(stop.code), f"no v2 live row yet for {list(self.products[1:])}")


if __name__ == "__main__":
    unittest.main()

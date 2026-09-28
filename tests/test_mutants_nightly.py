"""nightly/policy_table.py, nightly/capped.py and bin/promote held to what their docstrings,
CONTRACT.md §5, SPEC.md §14 and nightly/PROMPT.md say, on the cases test_nightly.py leaves
open: the literal constants SPEC pins, a proposal of exactly three candidates, a 403, runs of
failures broken by answers, the default --out, a confidence that is not a number, the tty and
git checks run for real, a SIGTERM that is honoured or ignored. Each test here was written to
fail on a mutant of the code that the older tests let through.
Offline: loop.jev.ask and urlopen are mocked wherever the table runs, git is either faked or a
throwaway repository in a temp dir, config.HALT / PROMPTS / PROPOSALS point at temp dirs, and
nothing here opens a socket or reads the live prompts/ or data/."""
import datetime, hashlib, importlib.machinery, importlib.util, io, json, os, shutil, signal, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout
from unittest import mock

from fixture_prompts import pin_v1
from loop import config, jev, prompts
from nightly import capped, policy_table

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAND = {"rationale": "test", "instructions": "Decide whether to be long for the next quarter of an hour.",
        "criteria": {"buy": "the trend is pumping and liquidity is deep", "sell": "the trend is dumping",
                     "hold": "anything else"}}


def _answer(choice, conf):
    p = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
    p[choice] = conf
    return {"choice": choice, "probabilities": p, "confidence": conf}


def _wording(q, **over):
    """A candidate carrying question q's instructions and criteria, with `over` replacing either."""
    return {"instructions": q["instructions"], "criteria": dict(q["criteria"]), **over}


class PolicyTableHeld(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.ask = self.enterContext(mock.patch("loop.jev.ask"))
        self.urlopen = self.enterContext(mock.patch("urllib.request.urlopen"))
        self.halt = os.path.join(self.tmp, "HALT")                           # never the repo's data/HALT
        self.enterContext(mock.patch.object(config, "HALT", self.halt))
        self.proposals = os.path.join(self.tmp, "proposals")                 # never the repo's proposals/; not made yet
        self.enterContext(mock.patch.object(config, "PROPOSALS", self.proposals))
        pin_v1(self)
        self.indir = os.path.join(self.tmp, "in")                            # the json lives apart from PROPOSALS
        os.makedirs(self.indir)
        self.prop = self._proposal("2026-09-22.json", [CAND])
        self.cands = policy_table.load_candidates(self.prop)
        self.cur_name, self.cur_q, self.cur_sha = policy_table.current_action()
        self.qs = policy_table.questions(self.cands, self.cur_q)
        self.rule = dict(policy_table.states())

    def _proposal(self, name, cands):
        p = os.path.join(self.indir, name)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"candidates": cands}, fh)
        return p

    def _reply(self, s, cur=None, cand="hold"):
        return {"answers": {"cand_0": _answer(cand, 0.8), "current": _answer(cur or self.rule[s], 0.9)},
                "model": config.MODEL}

    def _night(self, fail_at):
        """run() with ask() raising fail_at[n] on the n-th ask (from 1) and answering every other."""
        def fake(s, qs, **kw):
            e = fail_at.get(self.ask.call_count)
            if e is not None:
                raise e
            return self._reply(s)
        self.ask.reset_mock()
        self.ask.side_effect = fake
        return policy_table.run(self.qs)

    def _main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), mock.patch("sys.stderr", err):
            rc = policy_table.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_the_night_sends_up_to_900_s_and_nothing_after(self):
        # SPEC §14: DEADLINE_S = 900.0; docstring: nothing new is sent AFTER the deadline
        ticks = iter([0.0, 900.0, 900.5])
        self.ask.side_effect = lambda s, qs, **kw: self._reply(s)
        results = policy_table.run(self.qs, clock=lambda: next(ticks, 900.5))
        self.assertEqual(self.ask.call_count, 1)                             # sent at 900.0, stopped at 900.5
        self.assertIsNotNone(results[0]["answers"])
        self.assertEqual([r["error"] for r in results[1:]], ["deadline"] * 80)

    def test_three_candidates_is_a_whole_proposal(self):
        # CONTRACT §5: 1-3 entries (SPEC §14: MAX_CANDIDATES = 3)
        three = [{**CAND, "instructions": f"Decide whether to be long, wording {w}."} for w in ("one", "two", "three")]
        cands = policy_table.parse_candidates(json.dumps({"candidates": three}).encode(), "p.json")
        self.assertEqual([c["qid"] for c in cands], ["cand_0", "cand_1", "cand_2"])
        self.assertEqual(list(policy_table.questions(cands, self.cur_q)), ["cand_0", "cand_1", "cand_2", "current"])

    def test_a_refusal_raised_before_any_send_ends_the_night_after_one_ask(self):
        # run() docstring: a fatal kind (no key, no ledger, ...) stops the sending; FATAL_KINDS: more would repeat the refusal
        for kind in ("unsigned", "no-key", "ledger"):
            with self.subTest(kind=kind):
                results = self._night({n: jev.JevError(kind, "x") for n in range(1, 82)})
                self.assertEqual(self.ask.call_count, 1)
                self.assertEqual({r["error"] for r in results}, {kind})
                self.assertFalse(os.path.exists(self.halt))

    def test_transient_failures_end_the_night_only_three_in_a_row(self):
        # CONTRACT §5 / SPEC §14: MAX_TRANSIENT_RUN = 3 transient failures IN A ROW end the night
        t = jev.JevError("timeout", "x")
        results = self._night({1: t, 2: t, 30: t, 50: t})                   # two in a row, then isolated ones
        self.assertEqual(self.ask.call_count, 81)
        self.assertEqual(sum(1 for r in results if r["answers"]), 77)
        self._night({20: t, 21: t, 22: t})
        self.assertEqual(self.ask.call_count, 22)

    def test_other_failures_end_the_night_only_three_in_a_row(self):
        # docstring: MAX_OTHER_RUN other failures IN A ROW end the night; an answer breaks the run
        e = jev.JevError("http-4xx", "404 Not Found", 404, "env:X")
        results = self._night({1: e, 2: e, 30: e, 50: e})                   # two opening the night, then isolated ones
        self.assertEqual(self.ask.call_count, 81)
        self.assertEqual(sum(1 for r in results if r["answers"]), 77)

    def test_a_403_is_a_rejected_key_like_a_401(self):
        # CONTRACT §5: a 401/403 writes data/HALT; run() docstring: the remaining rows carry the kind that stopped it
        self.ask.side_effect = jev.JevError("http-4xx", "403 Forbidden", 403, "env:X")
        results = policy_table.run(self.qs)
        self.assertEqual(self.ask.call_count, 1)
        self.assertEqual({r["error"] for r in results}, {"http-4xx"})
        with open(self.halt, encoding="utf-8") as fh:
            reason = fh.read()
        self.assertIn("key rejected", reason)
        self.assertIn("403", reason)

    def test_a_rejected_key_ends_the_night_even_when_halt_cannot_be_written(self):
        # run() docstring: key rejected is a fatal kind by itself, not because the HALT it writes is found next state
        self.enterContext(mock.patch.object(config, "HALT", os.path.join(self.tmp, "no-such-dir", "HALT")))
        self.ask.side_effect = jev.JevError("http-4xx", "401 Unauthorized", 401, "env:X")
        with mock.patch("sys.stderr", io.StringIO()) as err:
            results = policy_table.run(self.qs)
        self.assertEqual(self.ask.call_count, 1)
        self.assertEqual({r["error"] for r in results}, {"http-4xx"})
        self.assertIn("cannot write", err.getvalue())

    def test_every_shape_fault_is_a_refusal_before_any_send(self):
        # parse_candidates docstring: ValueError on ANY shape fault; module docstring: exit 1 bad input
        for i, doc in enumerate(({"candidates": None}, {"candidates": 5}, {"candidates": ["abc"]},
                                 {"candidates": [None]}, {"candidates": [5]}, [CAND])):
            with self.subTest(doc=doc):
                p = os.path.join(self.indir, f"bad{i}.json")
                with open(p, "w", encoding="utf-8") as fh:
                    json.dump(doc, fh)
                rc, _, err = self._main(p)
                self.assertEqual(rc, 1)
                self.assertTrue(err.startswith("policy_table: "), err)
        self.ask.assert_not_called()

    def test_a_digit_in_a_criterion_is_refused_before_any_send(self):
        # PROMPT.md rule 4: no digit anywhere in instructions OR criteria
        p = self._proposal("2026-09-23.json", [{**CAND, "criteria": {**CAND["criteria"], "buy": "the trend pumped for 3 bars"}}])
        rc, _, err = self._main(p)
        self.assertEqual(rc, 1)
        self.assertIn("digit", err)
        self.ask.assert_not_called()

    def test_the_diff_shows_the_whole_wording_in_wire_order(self):
        # _lines docstring: instructions, then the criteria in wire order; the diff is of all four lines
        cand = prompts.question({"type": "choice", **_wording(self.cur_q, instructions="Decide whether to be long.")}, "choice")
        lines = policy_table.diff(self.cur_q, cand, "cand_0").splitlines()
        c = self.cur_q["criteria"]
        self.assertEqual(lines[:2], ["--- current", "+++ cand_0"])
        self.assertEqual(lines[3:], ["-instructions: " + self.cur_q["instructions"], "+instructions: Decide whether to be long.",
                                     " buy: " + c["buy"], " sell: " + c["sell"], " hold: " + c["hold"]])

    def test_a_candidate_worded_as_current_says_identical(self):
        # module docstring: per wording, the diff against CURRENT; an empty block would read as a missing one
        cands = policy_table.parse_candidates(json.dumps({"candidates": [_wording(self.cur_q)]}).encode(), "p.json")
        text = policy_table.render("2026-09-22", self.cur_name, self.cur_sha, cands, self.cur_q, [])
        self.assertIn("```diff\n(identical wording)\n```", text)

    def test_the_header_counts_the_candidates_and_current(self):
        # module docstring: each request carries every candidate AND the current question (K+1 wordings)
        text = policy_table.render("2026-09-22", self.cur_name, self.cur_sha, self.cands, self.cur_q, [])
        self.assertIn("one request each, carrying 2 questions.", text)

    def test_each_count_is_against_its_own_reference(self):
        # CONTRACT §5 / module docstring: counts of states where a wording differs from CURRENT and from rule_c
        results = policy_table.run(self.qs, ask=lambda s, qs: self._reply(s, cur="hold", cand=self.rule[s]))
        text = policy_table.render("2026-09-22", self.cur_name, self.cur_sha, self.cands, self.cur_q, results)
        moves = sum(rc != "hold" for rc in self.rule.values())
        self.assertGreater(moves, 0)
        current, cand = text.split("\n## cand_0\n")
        self.assertIn(f"differs from rule_c on {moves} of 81 answered states", current)
        self.assertIn(f"differs from CURRENT on {moves} of 81 answered states; from rule_c on 0 of 81", cand)

    def test_the_current_table_shows_currents_answers(self):
        # module docstring: per wording (CURRENT included) the 81-row table of state, choice, confidence
        results = policy_table.run(self.qs, ask=lambda s, qs: self._reply(s, cur="hold"))
        text = policy_table.render("2026-09-22", self.cur_name, self.cur_sha, self.cands, self.cur_q, results)
        s0, rc0 = policy_table.states()[0]
        self.assertIn(f"| {s0} | hold | 0.90 | {rc0} |\n", text.split("\n## cand_0\n")[0])

    def test_a_confidence_that_is_not_a_number_renders_as_a_dash(self):
        # module docstring: the 81-row table (state, choice, confidence); jev._parse checks confidence is present, not its type
        confs = [0.5, True, None, "high"]
        results = [{"state": s, "rule_c": rc, "answers": {"cand_0": ("buy", c), "current": ("hold", c)}, "error": None,
                    "model": config.MODEL} for (s, rc), c in zip(policy_table.states(), confs)]
        text = policy_table.render("2026-09-22", self.cur_name, self.cur_sha, self.cands, self.cur_q, results)
        want = ["0.50", "-", "-", "-"]
        for (s, rc), cf in zip(policy_table.states(), want):
            self.assertIn(f"| {s} | hold | {cf} | {rc} |\n", text)
            self.assertIn(f"| {s} | buy | {cf} | {rc} | hold |", text)

    def test_without_out_the_table_goes_under_proposals_named_for_the_json(self):
        # module docstring: --out defaults to <date>.md under config.PROPOSALS, not beside the json (CONTRACT §5 invocation)
        self.ask.side_effect = lambda s, qs, **kw: self._reply(s)
        rc, out, _ = self._main(self.prop)
        self.assertEqual(rc, 0)
        md = os.path.join(self.proposals, "2026-09-22.md")
        with open(md, encoding="utf-8") as fh:
            self.assertEqual(fh.readline(), "# policy table 2026-09-22\n")
        self.assertEqual(os.listdir(self.indir), ["2026-09-22.json"])
        self.assertTrue(out.startswith(md + "\t81/81 answered"), out)

    def test_a_json_not_named_for_a_date_gets_a_table_of_its_own_stem(self):
        # CONTRACT §5 / bin/promote vouched(): the table is found by the json's own stem, so no two proposals share one
        self.ask.side_effect = lambda s, qs, **kw: self._reply(s)
        rc, _, _ = self._main(self._proposal("2026-09-22-rerun.json", [CAND]))
        self.assertEqual(rc, 0)
        self.assertEqual(os.listdir(self.proposals), ["2026-09-22-rerun.md"])

    def test_an_incomplete_table_exits_4_and_says_how_many_answered(self):
        # module docstring: exit 4 INCOMPLETE (written, some states unanswered)
        def fake(s, qs, **kw):
            if self.ask.call_count == 5:
                raise jev.JevError("timeout", "x")
            return self._reply(s)
        self.ask.side_effect = fake
        out = os.path.join(self.tmp, "t.md")
        rc, stdout, _ = self._main(self.prop, "--out", out)
        self.assertEqual(rc, 4)
        self.assertEqual(stdout, f"{out}\t80/81 answered INCOMPLETE\n")
        with open(out, encoding="utf-8") as fh:
            self.assertIn("requests: 81, answered: 80, errors: 1 -- INCOMPLETE", fh.read())


class CappedHeld(unittest.TestCase):
    """nightly/capped.py in-process where nothing can hang; in a child process where a mutant could."""

    def _main(self, *argv):
        with mock.patch("sys.stderr", io.StringIO()) as err:
            return capped.main(list(argv)), err.getvalue()

    def test_usage_errors_exit_2(self):
        # module docstring: SECONDS -- CMD [ARG ...]; 2 on a usage error
        for argv in ([], ["5"], ["5", "--"], ["5", "x", "true"]):
            with self.subTest(argv=argv):
                rc, err = self._main(*argv)
                self.assertEqual(rc, 2)
                self.assertIn("usage", err)

    def test_a_fractional_cap_is_a_number(self):
        # module docstring: SECONDS is a number of awake seconds, not a whole one
        self.assertEqual(self._main("0.5", "--", "true")[0], 0)
        self.assertEqual(self._main("2700.0", "--", "true")[0], 0)

    def test_a_command_that_exists_but_cannot_be_executed_exits_127(self):
        # module docstring: 127 when the command cannot be started
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        path = os.path.join(tmp, "not-executable")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(path, 0o644)
        rc, err = self._main("5", "--", path)
        self.assertEqual(rc, 127)
        self.assertIn("cannot start", err)

    def test_a_capped_child_gets_its_sigterm_before_the_kill(self):
        # module docstring: when the cap fires the child is terminated, THEN killed (GRACE_S: SIGTERM, then this long)
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        flag = os.path.join(tmp, "flag")
        script = "trap 'sleep 0.1; echo terminated > \"$0\"; exit 0' TERM; while :; do sleep 0.05; done"
        rc, err = self._main("0.4", "--", "sh", "-c", script, flag)
        self.assertEqual(rc, capped.EXIT_CAPPED)
        with open(flag, encoding="utf-8") as fh:                                               # its SIGTERM cleanup ran to the end
            self.assertEqual(fh.read(), "terminated\n")

    def test_a_child_that_ignores_sigterm_is_killed_after_the_grace(self):
        # module docstring: 124 when the cap fired (the child is terminated, then killed); a child left running would hold the night
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        pidfile = os.path.join(tmp, "pid")
        script = "trap '' TERM; echo $$ > \"$0\"; while :; do sleep 0.05; done"
        code = "import sys; from nightly import capped; capped.GRACE_S = 0.2; sys.exit(capped.main(sys.argv[1:]))"

        def reap():
            try:
                with open(pidfile, encoding="utf-8") as fh:
                    os.kill(int(fh.read()), signal.SIGKILL)
            except (OSError, ValueError):
                pass
        self.addCleanup(reap)
        r = subprocess.run([sys.executable, "-c", code, "0.4", "--", "sh", "-c", script, pidfile],
                           cwd=REPO, capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, capped.EXIT_CAPPED, r.stderr)
        with open(pidfile, encoding="utf-8") as fh:                                            # the child was up, ignoring TERM, when the cap fired
            pid = int(fh.read())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)


def _load_promote():
    path = os.path.join(REPO, "bin", "promote")
    spec = importlib.util.spec_from_file_location("promote", path, loader=importlib.machinery.SourceFileLoader("promote", path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PromoteHeld(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = os.path.join(self.tmp, "prompts")
        os.makedirs(self.root)
        shutil.copy(os.path.join(REPO, "prompts", "v1.json"), self.root)     # the frozen v1, never the live CURRENT
        with open(os.path.join(self.root, "CURRENT"), "w", encoding="utf-8") as fh:
            fh.write("v1\n")
        self.v1 = prompts.load("v1", self.root)
        self.prop = os.path.join(self.tmp, "2026-09-22.json")
        self._write_prop([CAND])
        self.promote = _load_promote()
        self.git = self.enterContext(mock.patch.object(self.promote.subprocess, "run"))
        self.status, self.tags = ("", 0), ("prereg-v1\n", 0)               # (stdout, returncode): clean, sealed

        def git(argv, **kw):
            got = self.status if argv[:2] == ["git", "status"] else self.tags if argv[:2] == ["git", "tag"] else None
            if got is None:
                raise AssertionError(f"unexpected command {argv}")
            return subprocess.CompletedProcess(argv, got[1], stdout=got[0] if got[1] == 0 else "",
                                               stderr="" if got[1] == 0 else got[0])
        self.git.side_effect = git
        self.enterContext(mock.patch.object(self.promote, "_attended", return_value=True))

    def _write_prop(self, cands):
        with open(self.prop, "w", encoding="utf-8") as fh:
            json.dump({"candidates": cands}, fh)

    def _table(self, body):
        with open(self.prop[:-5] + ".md", "w", encoding="utf-8") as fh:
            fh.write(body)

    def _sha_line(self):
        with open(self.prop, "rb") as fh:
            return "proposal sha256: " + hashlib.sha256(fh.read()).hexdigest() + "  \n"

    def _run(self, *argv):
        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), mock.patch("sys.stderr", err):
            rc = self.promote.main(list(argv))
        return rc, buf.getvalue(), err.getvalue()

    def _untouched(self):
        self.assertEqual(sorted(os.listdir(self.root)), ["CURRENT", "v1.json"])
        self.assertEqual(prompts.current(self.root), "v1")

    def test_a_git_command_that_fails_refuses_and_says_which(self):
        # docstring: refuses on a dirty tree or a missing PREREG_TAG; a git that cannot answer vouches for neither
        self.status = ("fatal: index file corrupt", 128)
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("git status failed: fatal: index file corrupt", err)
        self._untouched()
        self.status, self.tags = ("", 0), ("fatal: not a git repository", 128)
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("git tag failed: fatal: not a git repository", err)
        self._untouched()

    def test_numbering_goes_past_a_gap(self):
        # docstring: N is the highest vN.json present
        shutil.copy(os.path.join(self.root, "v1.json"), os.path.join(self.root, "v3.json"))
        self.assertEqual(self.promote.next_version(self.root), "v4")

    def test_the_printed_diff_shows_the_whole_action_question(self):
        # docstring: prints the unified diff of the action question; a wording no one read must not go live
        self._write_prop([_wording(self.v1["action"], instructions="Decide whether to be long SOL.")])
        rc, out, _ = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        c = self.v1["action"]["criteria"]
        self.assertIn("\n".join([" buy: " + c["buy"], " sell: " + c["sell"], " hold: " + c["hold"]]), out)

    def test_only_the_incomplete_marker_warns(self):
        # CONTRACT §5: a table MARKED INCOMPLETE is a warning (policy_table's " -- INCOMPLETE"), not one that says the word
        self._table("# policy table 2026-09-22\n\n" + self._sha_line() + "requests: 81, answered: 81, errors: 0  \n\n"
                    "## cand_0\n\nrationale: yesterday's table was INCOMPLETE\n")
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        self.assertNotIn("WARNING", err)

    def test_a_table_without_the_sha_line_warns_and_proceeds(self):
        # CONTRACT §5: a table without the `proposal sha256` line is a warning, not a refusal
        self._table("# policy table 2026-09-22\n\nrequests: 81, answered: 81, errors: 0  \n")
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        self.assertIn("carries no 'proposal sha256' line", err)
        self.assertEqual(prompts.current(self.root), "v2")

    def test_a_digit_in_a_criterion_is_refused(self):
        # PROMPT.md rule 4: no digit anywhere in instructions OR criteria; nothing reaches prompts/
        self._write_prop([{**CAND, "criteria": {**CAND["criteria"], "buy": "the trend pumped for 3 bars"}}])
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("digit", err)
        self._untouched()

    def test_the_note_carries_the_rationale_on_one_line_or_none(self):
        # PROMPT.md rule 3: the rationale is one line, for the person; v2.json's note carries it as "Rationale: ..."
        self._write_prop([{**CAND, "rationale": "  sharper buy side \n"}, {k: v for k, v in CAND.items() if k != "rationale"}])
        self.assertEqual(self._run(self.prop, "0", "--prompts", self.root)[0], 0)
        self.assertEqual(self._run(self.prop, "1", "--prompts", self.root)[0], 0)
        with_why, without = (prompts.load(v, self.root)["note"] for v in ("v2", "v3"))
        self.assertTrue(with_why.endswith("candidate 0. Rationale: sharper buy side skip/up15/down15 carried from v1 unchanged."),
                        with_why)
        self.assertTrue(without.endswith("candidate 1. skip/up15/down15 carried from v1 unchanged."), without)

    def test_frozen_is_the_full_utc_date(self):
        # build() docstring: the document is shaped as v1.json, whose "frozen" is a whole date (2026-09-23)
        before = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        self.assertEqual(self._run(self.prop, "0", "--prompts", self.root)[0], 0)
        after = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        frozen = prompts.load("v2", self.root)["frozen"]
        self.assertRegex(self.v1["frozen"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn(frozen, {before, after})

    def test_without_prompts_flag_it_writes_the_configured_prompts_root(self):
        # docstring: --prompts exists for tests and a person never passes it; without it, prompts/ is config.PROMPTS
        root = pin_v1(self)                                                  # config.PROMPTS -> a temp v1 root
        rc, _, err = self._run(self.prop, "0")
        self.assertEqual(rc, 0, err)
        self.assertEqual(prompts.current(root), "v2")
        self.assertTrue(os.path.exists(os.path.join(root, "v2.json")))

    def test_the_promoted_candidate_is_from_the_bytes_the_table_vouched_for(self):
        # vouched() docstring: the sha checked and the candidates parsed are of the same bytes, read once
        self._table("# policy table 2026-09-22\n\n" + self._sha_line())
        real = self.promote.vouched

        def vouched_then_rewritten(proposal, raw):
            real(proposal, raw)
            self._write_prop([{**CAND, "instructions": "Rewritten after the check."}])
        with mock.patch.object(self.promote, "vouched", side_effect=vouched_then_rewritten):
            rc, _, _ = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        self.assertEqual(prompts.load("v2", self.root)["action"]["instructions"], CAND["instructions"])

    def test_a_proposal_without_a_candidate_list_is_refused_in_one_line(self):
        # CONTRACT §5: promote copies candidate k; a proposal with no list has none, and nothing is written
        for doc in ({}, {"candidates": None}, {"candidates": {"0": CAND}}, {"candidates": "abc"}, {"candidates": 5}):
            with self.subTest(doc=doc):
                with open(self.prop, "w", encoding="utf-8") as fh:
                    json.dump(doc, fh)
                rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
                self.assertEqual(rc, 1)
                self.assertIn("no candidate 0", err)
                self._untouched()

    def test_a_proposal_that_is_not_a_json_object_is_refused_in_one_line(self):
        # an array (or a bare value) escaped main() as an AttributeError traceback; it is refused like
        # every other bad proposal, exit 1, one line, nothing written
        for doc in ([{"instructions": "x"}], 5, "abc", None):
            with self.subTest(doc=doc):
                with open(self.prop, "w", encoding="utf-8") as fh:
                    json.dump(doc, fh)
                rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
                self.assertEqual(rc, 1)
                self.assertIn("not a JSON object with a candidates list", err)
                self.assertNotIn("Traceback", err)
                self._untouched()

    def test_a_version_file_that_appears_meanwhile_is_never_overwritten(self):
        # docstring: May not edit any existing prompt file (a second promote racing this one wrote v2 first)
        real = self.promote.next_version

        def racing(root):
            v = real(root)
            with open(os.path.join(root, v + ".json"), "w", encoding="utf-8") as fh:
                fh.write("written by another promote\n")
            return v
        with mock.patch.object(self.promote, "next_version", side_effect=racing):
            rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("exists", err)
        with open(os.path.join(self.root, "v2.json"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "written by another promote\n")
        self.assertEqual(prompts.current(self.root), "v1")


class PromoteUnfaked(unittest.TestCase):
    """bin/promote with nothing patched: run by path, _attended() on a real terminal, and
    clean_tree() / sealed() on a real throwaway repository. Every PromoteHeld test replaces
    _attended and subprocess.run, so what these read is seen only here."""

    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = os.path.join(self.tmp, "prompts")
        os.makedirs(self.root)
        shutil.copy(os.path.join(REPO, "prompts", "v1.json"), self.root)     # the frozen v1, never the live CURRENT
        with open(os.path.join(self.root, "CURRENT"), "w", encoding="utf-8") as fh:
            fh.write("v1\n")
        self.prop = os.path.join(self.tmp, "2026-09-22.json")
        with open(self.prop, "w", encoding="utf-8") as fh:
            json.dump({"candidates": [CAND]}, fh)
        self.promote = _load_promote()

    def test_run_by_path_from_a_script_it_refuses_for_want_of_a_tty(self):
        # CONTRACT §5 runs `bin/promote proposals/<date>.json <k>` by path; docstring: it refuses without a tty
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}   # `from loop import` must resolve on its own
        r = subprocess.run([sys.executable, os.path.join(REPO, "bin", "promote"), self.prop, "0", "--prompts", self.root],
                           cwd=self.tmp, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertTrue(r.stderr.startswith("promote: no tty"), r.stderr)
        self.assertEqual(sorted(os.listdir(self.root)), ["CURRENT", "v1.json"])

    def test_a_terminal_is_attended_and_anything_else_is_not(self):
        # docstring: a person runs this at a terminal; it refuses without a tty
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        with open(slave, closefd=True, encoding="utf-8") as tty, mock.patch.object(self.promote.sys, "stdin", tty):
            self.assertIs(self.promote._attended(), True)
        with open(os.devnull, encoding="utf-8") as fh, mock.patch.object(self.promote.sys, "stdin", fh):
            self.assertIs(self.promote._attended(), False)

    def test_clean_tree_and_sealed_read_a_real_repository(self):
        # docstring: refuses on a dirty git tree, and while the git tag prereg-v1 is missing
        if not shutil.which("git"):
            self.skipTest("git not on PATH")
        repo = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.dict(os.environ, {                      # no user or system git config leaks in
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}))

        def git(*args):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
        git("init", "-q")
        git("commit", "-q", "--allow-empty", "-m", "empty")
        self.assertIs(self.promote.clean_tree(repo), True)
        self.assertIs(self.promote.sealed(repo), False)
        git("tag", "prereg-v1-draft")
        self.assertIs(self.promote.sealed(repo), False)
        git("tag", "prereg-v1")
        self.assertIs(self.promote.sealed(repo), True)
        with open(os.path.join(repo, "stray"), "w", encoding="utf-8") as fh:
            fh.write("x\n")
        self.assertIs(self.promote.clean_tree(repo), False)


if __name__ == "__main__":
    unittest.main()

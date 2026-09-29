"""nightly/policy_table.py and nightly/capped.py held to what their docstrings, CONTRACT.md §5,
SPEC.md §14 and nightly/PROMPT.md say, on the cases test_nightly.py leaves open: the literal
constants SPEC pins, a proposal of exactly three candidates, a 403, runs of failures broken by
answers, the default --out, a confidence that is not a number, a SIGTERM that is honoured or
ignored. Each test here was written to fail on a mutant of the code that the older tests let
through. (bin/promote's, v1's here until PREREG-v2, are tests/test_promote_v2.py.)
Offline: loop.jev.ask and urlopen are mocked wherever the table runs, config.HALT / PROMPTS /
PROPOSALS point at temp dirs, and nothing here opens a socket or reads the live prompts/ or data/."""
import io, json, os, signal, subprocess, sys, tempfile, unittest
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
        self.rule = {s: rc for p in config.PRODUCTS for s, rc in policy_table.states(p)}   # every product's: main() asks all
        self.n = 81 * len(config.PRODUCTS)                                   # main()'s requests: 81 a product

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
        same = {"instructions": self.cur_q["instructions"].replace("SOL", "{BASE}"),       # a candidate names the product
                "criteria": {k: v.replace("SOL", "{BASE}") for k, v in self.cur_q["criteria"].items()}}   # as {BASE}
        cands = policy_table.parse_candidates(json.dumps({"candidates": [same]}).encode(), "p.json")
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
        moves = sum(rc != "hold" for _, rc in policy_table.states())
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
        self.assertTrue(out.startswith(md + f"\t{self.n}/{self.n} answered"), out)

    def test_a_json_not_named_for_a_date_gets_a_table_of_its_own_stem(self):
        # CONTRACT §5 / bin/promote vouched(): the table is found by the json's own stem, so no two proposals share one
        self.ask.side_effect = lambda s, qs, **kw: self._reply(s)
        rc, _, _ = self._main(self._proposal("2026-09-22-rerun.json", [CAND]))
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(os.listdir(self.proposals)), ["2026-09-22-rerun.md", "2026-09-22-rerun.table.json"])

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
        self.assertEqual(stdout, f"{out}\t{self.n - 1}/{self.n} answered INCOMPLETE\n")
        with open(out, encoding="utf-8") as fh:
            self.assertIn(f"requests: {self.n}, answered: {self.n - 1}, errors: 1 -- INCOMPLETE", fh.read())


class CappedHeld(unittest.TestCase):
    """nightly/capped.py in-process where nothing can hang; in a child process where a mutant could."""

    def setUp(self):
        # capped.main installs its forwarding handler on SIGTERM, SIGINT, SIGHUP and SIGQUIT in THIS
        # process; put the runner's own back after each test
        for s in capped.FORWARDED:
            self.addCleanup(signal.signal, s, signal.getsignal(s))

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


if __name__ == "__main__":
    unittest.main()

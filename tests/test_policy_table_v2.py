"""nightly/policy_table.py, v2 (PREREG-v2 §8 "Scoring a candidate", §10): state_string(adj, base) per product; one
request per state per product carrying the candidates and CURRENT, each rendered for the product's base; beside
proposals/<date>.md a proposals/<date>.table.json holding every wording's 81 answers per product, whose sha the .md
names; the deadline scaled by the product count; a pending version invisible (CURRENT is what current() names now);
a CURRENT-only table from a proposal with no candidates; and --fill, attended, re-sending only unanswered states.
Offline: loop.jev.ask is mocked and urlopen raises; config.HALT, PROPOSALS and PROMPTS point at temp dirs."""
import fnmatch, hashlib, io, json, os, tempfile, unittest
from contextlib import redirect_stdout
from unittest import mock

from fixture_products import exactly
from fixture_prompts import pin_versions, version_doc
from loop import config, jev, prompts, state
from nightly import policy_table

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCTS3 = ("SOL-USD", "ETH-USD", "XRP-USD")
CAND = {"rationale": "test", "instructions": "Decide whether to be long {BASE} for the next quarter of an hour.",
        "criteria": {"buy": "the trend is pumping and liquidity is deep", "sell": "the trend is dumping",
                     "hold": "anything else"}}


class Reached(BaseException):
    pass


def _answer(choice, conf):
    return {"choice": choice, "probabilities": {"buy": 0.0, "sell": 0.0, "hold": 0.0, choice: conf}, "confidence": conf}


class PolicyTableV2(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        exactly(self, PRODUCTS3)
        self.ask = self.enterContext(mock.patch("loop.jev.ask"))
        self.enterContext(mock.patch("urllib.request.urlopen", side_effect=Reached("urlopen was reached")))
        self.halt = os.path.join(self.tmp, "HALT")
        self.enterContext(mock.patch.object(config, "HALT", self.halt))
        self.proposals = os.path.join(self.tmp, "proposals")
        self.enterContext(mock.patch.object(config, "PROPOSALS", self.proposals))
        self.root = pin_versions(self, "v2")
        self.prop = self._proposal([CAND])
        self.rule = {p: {s: rc for s, rc in policy_table.states(p)} for p in PRODUCTS3}
        self.ask.side_effect = self._reply

    def _proposal(self, cands, name="2026-10-30.json"):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"candidates": cands}, fh)
        return p

    def _reply(self, s, qs, **kw):
        """CURRENT follows rule_c; every candidate holds."""
        p = next(p for p in PRODUCTS3 if s.startswith(config.base(p) + ":"))
        return {"answers": {q: _answer(self.rule[p][s] if q == "current" else "hold", 0.9 if q == "current" else 0.7) for q in qs},
                "model": config.MODEL}

    def _main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), mock.patch("sys.stderr", err):
            rc = policy_table.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def _night(self):
        md = os.path.join(self.proposals, "2026-10-30.md")
        rc, out, err = self._main(self.prop, "--out", md)
        return rc, md, policy_table.table_path(md)

    def test_every_products_state_strings_begin_with_its_own_base(self):
        # PREREG-v2 §10: "every added product's table strings begin with its own base"
        for p in PRODUCTS3:
            st = policy_table.states(p)
            self.assertEqual(len(st), 81)
            self.assertEqual([s for s, _ in st], [state.state_string(a, config.base(p)) for a in state.all_states()])
            self.assertTrue(all(s.startswith(config.base(p) + ": liquidity ") for s, _ in st), p)
            self.assertEqual([rc for _, rc in st], [state.rule_c(a) for a in state.all_states()])
        self.assertEqual(policy_table.states(), policy_table.states("SOL-USD"))

    def test_one_request_per_state_per_product_carrying_every_wording_rendered_for_it(self):
        rc, md, tj = self._night()
        self.assertEqual(rc, 0)
        self.assertEqual(self.ask.call_count, 81 * 3)
        v2 = prompts.load("v2", self.root)["action"]
        for i, call in enumerate(self.ask.call_args_list):
            p = PRODUCTS3[i // 81]
            s, qs = call.args
            self.assertEqual(s, policy_table.states(p)[i % 81][0])
            self.assertEqual(list(qs), ["cand_0", "current"])
            base = config.base(p)
            self.assertEqual(qs["cand_0"]["instructions"], CAND["instructions"].replace("{BASE}", base))
            self.assertEqual(qs["current"], prompts.render(prompts.question(v2, "choice"), "v2", base))
            self.assertIn(f"long {base} ", qs["current"]["instructions"])
        with open(md, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("for 3 products (SOL-USD, ETH-USD, XRP-USD), one request each, carrying 2 questions.", text)
        self.assertIn("requests: 243, answered: 243, errors: 0  \n", text)

    def test_the_table_json_holds_every_wordings_answers_per_product_and_the_md_names_its_sha(self):
        rc, md, tj = self._night()
        with open(tj, "rb") as fh:
            raw = fh.read()
        doc = json.loads(raw)
        self.assertEqual(os.path.basename(tj), "2026-10-30.table.json")
        self.assertEqual(list(doc["products"]), list(PRODUCTS3))
        with open(self.prop, "rb") as fh:
            self.assertEqual(doc["proposal_sha256"], hashlib.sha256(fh.read()).hexdigest())
        self.assertEqual(doc["current"], {"version": "v2", "sha": prompts.sha("v2", self.root),
                                          "question": prompts.question(prompts.load("v2", self.root)["action"], "choice")})
        self.assertEqual([c["qid"] for c in doc["candidates"]], ["cand_0"])
        for p in PRODUCTS3:
            rows = doc["products"][p]["rows"]
            self.assertEqual([r["state"] for r in rows], [s for s, _ in policy_table.states(p)])
            for r in rows:
                self.assertEqual(r["answers"]["current"][0], self.rule[p][r["state"]])
                self.assertEqual(r["answers"]["cand_0"], ["hold", 0.7])
        with open(md, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(f"table sha256: {hashlib.sha256(raw).hexdigest()} (2026-10-30.table.json)  \n", text)
        self.assertEqual(policy_table.vouched_sha(md), hashlib.sha256(raw).hexdigest())
        # pooled counts first (what loop.dash reads), then per product, each candidate's moved states marked
        moves = sum(rc != "hold" for rc in self.rule["SOL-USD"].values())
        self.assertIn(f"## cand_0\n\nrationale: test\n\ndiffers from CURRENT on {3 * moves} of 243 answered states;", text)
        for p in PRODUCTS3:
            self.assertIn(f"### {p}\n\ndiffers from CURRENT on {moves} of 81 answered states;", text)
        sol = policy_table.states("SOL-USD")
        s, rc = next((s, rc) for s, rc in sol if rc == "buy")
        self.assertIn(f"| {s} | hold | 0.70 | buy | buy | yes |", text)
        s, rc = next((s, rc) for s, rc in sol if rc == "hold")
        self.assertIn(f"| {s} | hold | 0.70 | hold | hold |  |", text)
        from loop import dash
        self.assertEqual(dash.PROPOSAL_COUNTS.search(text).groups(), (str(3 * moves), "243", str(3 * moves), "243"))
        self.assertEqual(dash.CURRENT_CAND.search(text).groups(), ("v2", "0", "243"))

    def test_the_deadline_scales_with_the_product_count(self):
        # DEADLINE_S per product: three products get 2,700 s. A clock that moves 100 s a send reaches 900 s after nine
        # sends, 2,700 s after 27; one product alone stops at nine.
        t = [0.0]

        def clock():
            t[0] += 50.0                       # two reads a send: the check and the next check
            return t[0]
        jobs = [(p, {"current": {}}, policy_table.states(p)) for p in PRODUCTS3]
        self.ask.side_effect = lambda s, qs, **kw: {"answers": {"current": _answer("hold", 0.5)}, "model": config.MODEL}
        per = policy_table.run_night(jobs, clock=clock)
        sent = self.ask.call_count
        self.assertEqual(sum(1 for p in PRODUCTS3 for r in per[p] if r["error"] == "deadline"), 243 - sent)
        self.assertEqual(sent, 54)             # clock after send k is 50 (k + 1): 50 (k + 1) - 50 <= 2,700
        t[0] = 0.0
        self.ask.reset_mock()
        policy_table.run_night(jobs[:1], clock=clock)
        self.assertEqual(self.ask.call_count, 18)

    def test_a_stop_carries_over_to_every_later_product(self):
        self.ask.side_effect = jev.JevError("http-429", "429 Too Many Requests", 429, "env:X")
        rc, md, tj = self._night()
        self.assertEqual(rc, policy_table.EXIT_INCOMPLETE)
        self.assertEqual(self.ask.call_count, 1)
        with open(tj, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual({r["error"] for p in PRODUCTS3 for r in doc["products"][p]["rows"]}, {"http-429"})

    def test_a_pending_version_is_invisible_to_the_table(self):
        # CURRENT names v3, activating in the future: the night scores against v2, what arm B asks now (PREREG-v2 §10)
        v3 = version_doc("v3", {"instructions": "A pending wording for {BASE}.", "criteria": CAND["criteria"]},
                         activation_tick="20991231T000000Z", replaces="v2")
        root = pin_versions(self, "v3", {"v3": v3})
        self.assertEqual(prompts.pending(root=root), "v3")
        name, q, sha = policy_table.current_action(root)
        self.assertEqual((name, sha), ("v2", prompts.sha("v2", root)))
        rc, md, tj = self._night()
        self.assertEqual(rc, 0)
        with open(md, encoding="utf-8") as fh:
            text = fh.read()
        with open(tj, encoding="utf-8") as fh:
            blob = fh.read()
        for t in (text, blob):
            self.assertNotIn("pending wording", t)
            self.assertNotIn(prompts.sha("v3", root), t)
        self.assertIn(f"CURRENT: v2 sha {prompts.sha('v2', root)}", text)
        for call in self.ask.call_args_list:
            self.assertNotIn("pending", call.args[1]["current"]["instructions"])

    def test_a_proposal_with_no_candidates_is_a_current_only_table(self):
        # PREREG-v2 §8: v2's own tables come from a policy_table run on a proposal with no candidates
        prop = self._proposal([], "2026-10-31.json")
        md = os.path.join(self.proposals, "2026-10-31.md")
        rc, _, _ = self._main(prop, "--out", md)
        self.assertEqual(rc, 0)
        self.assertEqual(self.ask.call_count, 243)
        self.assertEqual({tuple(c.args[1]) for c in self.ask.call_args_list}, {("current",)})
        doc, sha = policy_table.read_table(policy_table.table_path(md))
        self.assertEqual(doc["candidates"], [])
        with open(md, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("carrying 1 questions.", text)
        self.assertNotIn("## cand_", text)

    def test_a_candidate_naming_a_product_is_refused_before_any_send(self):
        for bad in ("Decide whether to be long SOL.", "Decide whether to be long ETH now.", "Be long XRP."):
            rc, _, err = self._main(self._proposal([{**CAND, "instructions": bad}]), "--out", os.path.join(self.tmp, "x.md"))
            self.assertEqual(rc, 1, bad)
            self.assertIn("product word", err)
        self.ask.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "x.table.json")))

    def test_the_table_json_stays_gitignored(self):
        # PREREG-v2 §8: the .table.json stays gitignored, vouched for by its sha in the committed .md
        with open(os.path.join(REPO, ".gitignore"), encoding="utf-8") as fh:
            lines = [l.strip() for l in fh.read().splitlines() if l.strip() and not l.startswith("#")]
        name = "proposals/2026-10-30.table.json"
        self.assertTrue(any(fnmatch.fnmatch(name, l) for l in lines if not l.startswith("!")))
        self.assertFalse(any(fnmatch.fnmatch(name, l[1:]) for l in lines if l.startswith("!")))

    def test_dry_counts_every_products_payloads(self):
        rc, out, _ = self._main("--dry", self.prop)
        self.assertEqual(rc, 0)
        first, body = out.split("\n", 1)
        self.assertEqual(first, "dry: 243 payloads, 0 sent")
        self.assertEqual(json.loads(body)["state"], policy_table.states("SOL-USD")[0][0])
        self.ask.assert_not_called()


class Fill(unittest.TestCase):
    """--fill proposals/<date>.table.json: attended; asks only unanswered states, with the questions the night sent;
    writes their answers into the same file and its new sha into the .md; never re-sends an answered state."""

    def setUp(self):
        t = PolicyTableV2("test_dry_counts_every_products_payloads")
        t.setUp()
        self.addCleanup(t.doCleanups)
        self.t = t
        self.attended = self.enterContext(mock.patch.object(policy_table, "_attended", return_value=True))
        # the night: three of ETH's sends time out, never two in a row (three in a row would end the night)
        n = [0]

        def night(s, qs, **kw):
            n[0] += 1
            if n[0] - 82 in (4, 6, 68):
                raise jev.JevError("timeout", "slow")
            return t._reply(s, qs)
        t.ask.side_effect = night
        rc, self.md, self.tj = t._night()
        self.assertEqual(rc, policy_table.EXIT_INCOMPLETE)
        self.missed = [policy_table.states("ETH-USD")[i][0] for i in (4, 6, 68)]
        t.ask.reset_mock()
        t.ask.side_effect = t._reply

    def _fill(self):
        return self.t._main("--fill", self.tj)

    def test_only_the_unanswered_states_are_sent_and_the_md_names_the_new_sha(self):
        with open(self.tj, "rb") as fh:
            before = json.loads(fh.read())
        rc, out, _ = self._fill()
        self.assertEqual(rc, 0, out)
        self.assertEqual([c.args[0] for c in self.t.ask.call_args_list], self.missed)
        for c in self.t.ask.call_args_list:
            self.assertEqual(c.args[1], before["products"]["ETH-USD"]["questions"])      # the night's questions, as sent
        with open(self.tj, "rb") as fh:
            raw = fh.read()
        after = json.loads(raw)
        for p in PRODUCTS3:
            for b, a in zip(before["products"][p]["rows"], after["products"][p]["rows"]):
                if b["answers"]:
                    self.assertEqual(a, b)                                                 # an answered state is untouched
                else:
                    self.assertEqual(a["answers"]["cand_0"], ["hold", 0.7])
                    self.assertIsNone(a["error"])
        self.assertEqual(policy_table.vouched_sha(self.md), hashlib.sha256(raw).hexdigest())
        with open(self.md, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("requests: 243, answered: 243, errors: 0  \n", text)
        self.assertNotIn("INCOMPLETE", text)
        self.assertEqual(out, f"{self.tj}\tfilled 3, unanswered 0\n")
        rc, out, _ = self._fill()                                                           # nothing left: no send
        self.assertEqual((rc, out), (0, f"{self.tj}\tfilled 0, unanswered 0\n"))
        self.assertEqual(self.t.ask.call_count, 3)

    def test_a_table_json_the_md_does_not_vouch_for_is_refused(self):
        with open(self.tj, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["products"]["SOL-USD"]["rows"][0]["answers"]["cand_0"] = ["buy", 0.99]           # edited after the night
        with open(self.tj, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        rc, _, err = self._fill()
        self.assertEqual(rc, 1)
        self.assertIn("is not the one", err)
        self.t.ask.assert_not_called()

    def test_fill_is_attended_and_stops_on_halt(self):
        self.attended.return_value = False
        rc, _, err = self._fill()
        self.assertEqual(rc, 1)
        self.assertIn("attended", err)
        self.attended.return_value = True
        with open(self.t.halt, "w", encoding="utf-8") as fh:
            fh.write("by hand\n")
        rc, out, _ = self._fill()
        self.assertEqual(rc, 0)
        self.assertIn("HALT present", out)
        self.t.ask.assert_not_called()

    def test_a_fill_that_leaves_states_unanswered_says_so(self):
        self.t.ask.side_effect = [self.t._reply(self.missed[0], {"cand_0": None, "current": None}),
                                  jev.JevError("timeout", "slow"), self.t._reply(self.missed[2], {"cand_0": None, "current": None})]
        rc, out, _ = self._fill()
        self.assertEqual(rc, policy_table.EXIT_INCOMPLETE)
        self.assertEqual(out, f"{self.tj}\tfilled 2, unanswered 1 INCOMPLETE\n")
        with open(self.md, encoding="utf-8") as fh:
            self.assertIn("requests: 243, answered: 242, errors: 1 -- INCOMPLETE", fh.read())
        doc, sha = policy_table.read_table(self.tj)
        self.assertEqual(policy_table.vouched_sha(self.md), sha)

    def test_a_choice_outside_the_alphabet_is_unanswered_and_filled(self):
        # PREREG-v2 §8: "An unanswered state is re-sent only by --fill". A null (or any other) choice that jev._parse
        # passed was stored as answered: the night said 243/243 with errors 0, --fill sent nothing, and bin/promote then
        # refused the candidate at 80 of 81 (2026-09-29 lens-4 review)
        t = PolicyTableV2("test_dry_counts_every_products_payloads")
        t.setUp()
        self.addCleanup(t.doCleanups)
        bad = policy_table.states("ETH-USD")[10][0]

        def night(s, qs, **kw):
            r = t._reply(s, qs)
            if s == bad:
                r["answers"]["cand_0"] = {"choice": None, "probabilities": None, "confidence": None}
            return r
        t.ask.side_effect = night
        rc, md, tj = t._night()
        self.assertEqual(rc, policy_table.EXIT_INCOMPLETE)
        with open(md, encoding="utf-8") as fh:
            self.assertIn("requests: 243, answered: 242, errors: 1 -- INCOMPLETE", fh.read())
        doc, _ = policy_table.read_table(tj)
        row = next(r for r in doc["products"]["ETH-USD"]["rows"] if r["state"] == bad)
        self.assertEqual((row["answers"], row["error"]), (None, "parse"))
        t.ask.reset_mock()
        t.ask.side_effect = t._reply
        with mock.patch.object(policy_table, "_attended", return_value=True):
            rc, out, _ = t._main("--fill", tj)
        self.assertEqual((rc, out), (0, f"{tj}\tfilled 1, unanswered 0\n"))
        self.assertEqual([c.args[0] for c in t.ask.call_args_list], [bad])

    def test_fill_and_a_proposal_are_one_or_the_other(self):
        with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as cm:
            policy_table.main([self.t.prop, "--fill", self.tj])
        self.assertEqual(cm.exception.code, 2)
        with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            policy_table.main([])


if __name__ == "__main__":
    unittest.main()

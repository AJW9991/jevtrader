"""nightly: the digest lists the right arm-B disagreements in the right order and
leaks no feature; the policy table enumerates 81 digit-free states and sends nothing
in --dry; promote refuses on a dirty tree and carries v1's three nouls byte for byte;
propose.sh --dry turns the fixture reply into a proposals json. Offline: loop.jev.ask
is mocked wherever the table is run, subprocess.run is mocked for git, and every
write lands in a temp dir. Nothing here opens a socket."""
import datetime, importlib.util, io, json, os, shutil, subprocess, tempfile, unittest
from contextlib import redirect_stdout
from unittest import mock

from loop import config, jev, prompts, rules, state
from nightly import digest, policy_table

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = datetime.date(2026, 9, 22)
T0 = datetime.datetime(2026, 9, 22, 10, 0, 0, tzinfo=datetime.timezone.utc)
ADJ = {"liq": "deep", "flow": "quiet", "trend": "pumping", "vol": "normal"}
STATE = state.state_string(ADJ)
NOUL = {"noul": 0.0}


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _answer(choice, conf):
    p = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
    p[choice] = conf
    return {"choice": choice, "probabilities": p, "confidence": conf}


def _row(minute, mid, b=None, absence=None):
    """A CONTRACT §2 row at T0 + minute. b = (choice, confidence) for b_action; a_action
    is always hold. absence rows carry null answers and a null mid."""
    d = T0 + datetime.timedelta(minutes=minute)
    answers = None if absence or b is None else {
        "a_action": _answer("hold", 0.9), "b_action": _answer(*b), "skip": NOUL, "up15": NOUL, "down15": NOUL}
    return {"v": 1, "tick_id": d.strftime("%Y%m%dT%H%M00Z"), "ts_rx": _iso(d), "mode": "live",
            "venue": "coinbase", "product": "SOL-USD", "cadence_s": 60, "horizon_s": 900,
            "bid": None if mid is None else mid - 0.01, "ask": None if mid is None else mid + 0.01,
            "mid": mid, "features": {"ret15_z": 1.7, "rv_ratio": 0.9}, "adj": ADJ, "state": STATE,
            "answers": answers, "rule_c": "buy",
            "columns": {"a": rules.for_arm(answers, "a"), "b": rules.for_arm(answers, "b")},
            "absence": absence}


def synthetic_log():
    """41 minutes. Mids are 100 except at the six t+15 rows that resolve minutes 0..5:
      0 buy 0.95 -> down   listed (1st)      3 buy 0.80 -> down  below the cut
      1 sell 0.90 -> up    listed (2nd)      4 hold 0.99 -> down hold is never listed
      2 buy 0.99 -> up     correct           5 sell 0.86 -> up   listed (3rd)
    plus an absence row at minute 6 (null answers, null mid) and a sell at 0.97 at
    minute 30 whose t+15 is past the log (gap: never listed)."""
    mids = {15: 99.85, 16: 100.15, 17: 100.20, 18: 99.80, 19: 99.80, 20: 100.10}
    b = {0: ("buy", 0.95), 1: ("sell", 0.90), 2: ("buy", 0.99), 3: ("buy", 0.80), 4: ("hold", 0.99),
         5: ("sell", 0.86), 30: ("sell", 0.97)}
    rows = []
    for m in range(41):
        if m == 6:
            rows.append(_row(m, None, absence="feed"))
        else:
            rows.append(_row(m, mids.get(m, 100.0), b.get(m, ("hold", 0.6))))
    return rows


def _write_log(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _table_rows(text):
    """[(choice, confidence, label)] of the disagreement table, file order."""
    out = []
    for line in text.splitlines():
        if line.startswith("| SOL:"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            out.append((cells[1], float(cells[2]), cells[4]))
    return out


class DigestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.log = os.path.join(self.tmp, "data", "decisions.jsonl")
        _write_log(self.log, synthetic_log())

    def test_disagreement_rows_and_order(self):
        text, n = digest.build(DAY, self.log)
        self.assertEqual(n, 41)
        self.assertEqual(_table_rows(text), [("buy", 0.95, "down"), ("sell", 0.90, "up"), ("sell", 0.86, "up")])
        self.assertIn("B disagreements 3", text)
        self.assertIn("3 of 3 shown", text)

    def test_never_features_never_the_log(self):
        text, _ = digest.build(DAY, self.log)
        self.assertNotIn("features", text)
        self.assertNotIn("ret15_z", text)
        self.assertNotIn("1.7", text)                     # the feature value planted in every row
        self.assertNotIn("tick_id", text)                 # no raw row
        self.assertNotIn("Bearer", text)

    def test_current_question_verbatim_and_both_shas(self):
        text, _ = digest.build(DAY, self.log)
        v1 = prompts.load("v1")
        self.assertIn(v1["action"]["instructions"], text)
        for k in ("buy", "sell", "hold"):
            self.assertIn(v1["action"]["criteria"][k], text)
        self.assertIn(f"prompt_a v1 {prompts.sha('v1')}", text)
        self.assertIn(f"prompt_b {prompts.current()} {prompts.sha(prompts.current())}", text)

    def test_summary_line_counts(self):
        text, _ = digest.build(DAY, self.log)
        line = text.splitlines()[2]
        self.assertTrue(line.startswith("2026-09-22 | ticks 41, answered 40, absence feed:1"))
        self.assertIn("outcomes joined 25/40", line)      # minutes 0..24 resolve inside the 41-row log (6 is unpriced)
        self.assertIn("trend dumping 0% flat 0% pumping 100%", line)
        self.assertIn(f"fee {config.FEE_BPS_PRIMARY:g} bps, column argmax: A 0 trades +0.0 bps", line)
        self.assertIn("B 2 trades", line)                 # buy at minute 0, sell at minute 1
        self.assertIn("C 1 trades", line)                 # rule_c buy at minute 0, then held long
        self.assertIn("B disagreements 3", line)

    def test_cap_at_25(self):
        rows = synthetic_log()
        # forty buys at 0.9 whose t+15 all read 99.0: forty disagreements, 25 listed
        for m in range(25, 40):
            rows[m]["answers"]["b_action"] = _answer("buy", 0.9)
        for m in range(15, 41):
            if rows[m]["mid"] is not None:
                rows[m]["mid"] = 99.0
        rows += [_row(m, 99.0, ("hold", 0.6)) for m in range(41, 60)]
        _write_log(self.log, rows)
        text, _ = digest.build(DAY, self.log)
        n_listed = len(_table_rows(text))
        self.assertEqual(n_listed, 25)
        self.assertIn("25 of ", text)

    def test_other_days_are_excluded_but_join_across_midnight(self):
        rows = synthetic_log()
        late = datetime.datetime(2026, 9, 22, 23, 50, 0, tzinfo=datetime.timezone.utc)
        for i in range(20):                               # 23:50 .. 00:09 next day; the 23:50 buy resolves at 00:05
            d = late + datetime.timedelta(minutes=i)
            r = _row(0, 100.0 if i < 15 else 99.5, ("buy", 0.93) if i == 0 else ("hold", 0.6))
            r["tick_id"], r["ts_rx"] = d.strftime("%Y%m%dT%H%M00Z"), _iso(d)
            rows.append(r)
        _write_log(self.log, rows)
        text, n = digest.build(DAY, self.log)
        self.assertEqual(n, 41 + 10)                      # the 10 next-day rows are not the day's
        self.assertEqual(_table_rows(text)[0], ("buy", 0.95, "down"))
        self.assertIn(("buy", 0.93, "down"), _table_rows(text))

    def test_main_writes_file_and_day_zero_exits_4(self):
        out = os.path.join(self.tmp, "digest.md")
        with redirect_stdout(io.StringIO()):
            rc = digest.main(["--date", "2026-09-22", "--log", self.log, "--out", out])
        self.assertEqual(rc, 0)
        with open(out) as fh:
            self.assertIn("B disagreements 3", fh.read())
        with redirect_stdout(io.StringIO()):
            rc = digest.main(["--date", "2026-09-22", "--log", os.path.join(self.tmp, "none.jsonl"), "--out", out])
        self.assertEqual(rc, digest.EXIT_EMPTY)
        with open(out) as fh:
            text = fh.read()
        self.assertIn("ticks 0", text)
        self.assertIn("(none)", text)
        self.assertNotIn("features", text)

    def test_yesterday_is_the_previous_utc_day(self):
        now = datetime.datetime(2026, 9, 23, 0, 5, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(digest.yesterday(now), "2026-09-22")


CAND = {"rationale": "test", "instructions": "Decide whether to be long for the next quarter of an hour.",
        "criteria": {"buy": "the trend is pumping and liquidity is deep", "sell": "the trend is dumping",
                     "hold": "anything else"}}


def _by_state():
    return {state.state_string(a): a for a in state.all_states()}


class PolicyTableTest(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.ask = self.enterContext(mock.patch("loop.jev.ask"))
        self.urlopen = self.enterContext(mock.patch("urllib.request.urlopen"))
        self.prop = os.path.join(self.tmp, "2026-09-22.json")
        with open(self.prop, "w") as fh:
            json.dump({"candidates": [CAND]}, fh)

    def test_81_distinct_digit_free_states(self):
        st = policy_table.states()
        self.assertEqual(len(st), 81)
        strings = [s for s, _ in st]
        self.assertEqual(len(set(strings)), 81)
        for s in strings:
            self.assertFalse(any(ch.isdigit() for ch in s), s)
            self.assertTrue(s.startswith("SOL: liquidity "), s)
        self.assertEqual(sorted({rc for _, rc in st}), ["buy", "hold", "sell"])
        self.assertEqual(sum(rc == "buy" for _, rc in st), 12)

    def test_dry_prints_81_and_sends_nothing(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = policy_table.main(["--dry", self.prop])
        self.assertEqual(rc, 0)
        first, body = buf.getvalue().split("\n", 1)
        self.assertEqual(first, "dry: 81 payloads, 0 sent")
        p = json.loads(body)
        self.assertEqual(p["model"], config.MODEL)
        self.assertEqual(p["state"], policy_table.states()[0][0])
        self.assertEqual(list(p["questions"]), ["cand_0", "current"])
        self.assertEqual(p["questions"]["cand_0"], {"type": "choice", **{k: CAND[k] for k in ("instructions", "criteria")}})
        self.assertEqual(p["questions"]["current"]["instructions"], prompts.load("v1")["action"]["instructions"])
        self.ask.assert_not_called()
        self.urlopen.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "2026-09-22.md")))

    def test_payloads_are_81_one_per_state_all_candidates_in_each(self):
        cands = policy_table.load_candidates(self.prop)
        _, cur_q, _ = policy_table.current_action()
        ps = policy_table.payloads(policy_table.questions(cands, cur_q))
        self.assertEqual(len(ps), 81)
        self.assertEqual(len({p["state"] for p in ps}), 81)
        for p in ps:
            self.assertEqual(list(p["questions"]), ["cand_0", "current"])
            self.assertFalse(any(ch.isdigit() for ch in p["state"]))

    def test_run_writes_table_with_counts(self):
        by = _by_state()

        def fake(s, qs):                                  # current follows rule_c exactly; cand_0 always holds
            rc = state.rule_c(by[s])
            return {"answers": {"cand_0": _answer("hold", 0.7), "current": _answer(rc, 0.9)},
                    "model": config.MODEL, "input_tokens": 100, "latency_ms": 5, "key_path": "env:X"}
        self.ask.side_effect = fake
        out = os.path.join(self.tmp, "2026-09-22.md")
        with redirect_stdout(io.StringIO()):
            rc = policy_table.main([self.prop, "--out", out])
        self.assertEqual(rc, 0)
        self.assertEqual(self.ask.call_count, 81)
        for call in self.ask.call_args_list:
            self.assertEqual(list(call.args[1]), ["cand_0", "current"])
        with open(out) as fh:
            text = fh.read()
        self.assertIn("differs from rule_c on 0 of 81 answered states", text)          # current
        self.assertIn("differs from CURRENT on 57 of 81 answered states; from rule_c on 57 of 81", text)
        self.assertIn("-buy: the trend is pumping, volatility is not violent, and liquidity is not thin", text)
        self.assertIn("+buy: the trend is pumping and liquidity is deep", text)
        self.assertIn("rationale: test", text)
        self.assertIn("requests: 81, answered: 81, errors: 0", text)
        self.assertNotIn("INCOMPLETE", text)
        self.assertNotIn("DRIFT", text)
        self.assertEqual(text.count("| SOL: liquidity "), 162)                            # 81 rows x 2 tables
        self.assertIn("| SOL: liquidity deep, flow quiet, trend pumping, vol normal | hold | 0.70 | buy | buy |", text)
        self.assertIn("scored against a logged outcome", text)

    def test_key_rejected_stops_after_one_and_marks_incomplete(self):
        self.ask.side_effect = jev.JevError("http-4xx", "401", 401, "env:X")
        out = os.path.join(self.tmp, "t.md")
        with redirect_stdout(io.StringIO()):
            rc = policy_table.main([self.prop, "--out", out])
        self.assertEqual(rc, policy_table.EXIT_INCOMPLETE)
        self.assertEqual(self.ask.call_count, 1)
        with open(out) as fh:
            text = fh.read()
        self.assertIn("INCOMPLETE", text)
        self.assertIn("errors: 81", text)

    def test_transient_error_continues(self):
        by = _by_state()
        calls = []

        def fake(s, qs):
            calls.append(s)
            if len(calls) == 3:
                raise jev.JevError("timeout", "x", None, "env:X")
            return {"answers": {"cand_0": _answer("hold", 0.5), "current": _answer(state.rule_c(by[s]), 0.9)},
                    "model": config.MODEL}
        self.ask.side_effect = fake
        results = policy_table.run(policy_table.questions(policy_table.load_candidates(self.prop),
                                                          policy_table.current_action()[1]))
        self.assertEqual(len(calls), 81)
        self.assertEqual(sum(1 for r in results if r["error"]), 1)
        self.assertEqual(policy_table.counts(results, "cand_0")[2], 80)

    def test_deadline_stops_sending(self):
        t = [0.0]

        def clock():
            t[0] += 100.0
            return t[0]
        self.ask.return_value = {"answers": {"cand_0": _answer("hold", 0.5), "current": _answer("hold", 0.5)}}
        results = policy_table.run(policy_table.questions(policy_table.load_candidates(self.prop),
                                                          policy_table.current_action()[1]),
                                   deadline_s=250.0, clock=clock)
        self.assertLess(self.ask.call_count, 81)
        self.assertEqual(sum(1 for r in results if r["error"] == "deadline"), 81 - self.ask.call_count)

    def test_bad_candidates_refused_before_any_send(self):
        for bad in ({"candidates": []}, {"candidates": [CAND] * 4},
                    {"candidates": [{**CAND, "criteria": {"yes": "a", "no": "b"}}]},
                    {"candidates": [{**CAND, "instructions": "wait 15 minutes"}]}):
            with open(self.prop, "w") as fh:
                json.dump(bad, fh)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(policy_table.main([self.prop]), 1)
        self.ask.assert_not_called()


def _load_promote():
    path = os.path.join(REPO, "bin", "promote")
    spec = importlib.util.spec_from_file_location("promote", path, loader=importlib.machinery.SourceFileLoader("promote", path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _block(text, name):
    """The raw text of the top-level `"name": {...}` block in a 2-space-indented file."""
    start = text.index(f'  "{name}": {{')
    end = text.index("\n  }", start) + len("\n  }")
    return text[start:end]


class PromoteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = os.path.join(self.tmp, "prompts")
        os.makedirs(self.root)
        for f in ("v1.json", "CURRENT"):
            shutil.copy(os.path.join(REPO, "prompts", f), self.root)
        self.prop = os.path.join(self.tmp, "2026-09-22.json")
        with open(self.prop, "w") as fh:
            json.dump({"candidates": [CAND, {**CAND, "instructions": "Second candidate."}]}, fh)
        self.promote = _load_promote()
        self.git = self.enterContext(mock.patch.object(self.promote.subprocess, "run"))
        self.git.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        self.enterContext(mock.patch.object(self.promote, "_attended", return_value=True))

    def _run(self, *argv):
        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), mock.patch("sys.stderr", err):
            rc = self.promote.main(list(argv))
        return rc, buf.getvalue(), err.getvalue()

    def test_dirty_tree_refuses_and_writes_nothing(self):
        self.git.return_value = subprocess.CompletedProcess([], 0, stdout=" M loop/x.py\n", stderr="")
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("dirty", err)
        self.assertEqual(sorted(os.listdir(self.root)), ["CURRENT", "v1.json"])
        self.assertEqual(prompts.current(self.root), "v1")
        self.git.assert_called_once()
        self.assertEqual(self.git.call_args.args[0], ["git", "status", "--porcelain"])

    def test_no_tty_refuses(self):
        with mock.patch.object(self.promote, "_attended", return_value=False):
            rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("tty", err)
        self.assertEqual(sorted(os.listdir(self.root)), ["CURRENT", "v1.json"])

    def test_v2_carries_v1_nouls_byte_identical(self):
        rc, out, _ = self._run(self.prop, "1", "--prompts", self.root)
        self.assertEqual(rc, 0, out)
        self.assertEqual(prompts.current(self.root), "v2")
        with open(os.path.join(self.root, "v1.json")) as fh:
            t1 = fh.read()
        with open(os.path.join(self.root, "v2.json")) as fh:
            t2 = fh.read()
        for q in ("skip", "up15", "down15"):
            self.assertEqual(_block(t1, q), _block(t2, q))
        v1, v2 = json.loads(t1), json.loads(t2)
        self.assertEqual(list(v2), list(v1))                                  # same key order
        self.assertEqual(v2["version"], "v2")
        self.assertEqual(v2["action"], {"type": "choice", "instructions": "Second candidate.", "criteria": CAND["criteria"]})
        self.assertIn("candidate 1", v2["note"])
        self.assertEqual(t1, open(os.path.join(REPO, "prompts", "v1.json")).read())   # v1 untouched
        qs = prompts.build(v1, v2)                                             # and the loop can build from it
        self.assertEqual(qs["b_action"]["instructions"], "Second candidate.")
        self.assertEqual(qs["a_action"], prompts.question(v1["action"], "choice"))
        self.assertIn("+++ v2.action", out)
        self.assertIn("-instructions: " + v1["action"]["instructions"], out)
        self.assertIn("+instructions: Second candidate.", out)

    def test_numbers_from_highest_file_not_current(self):
        self._run(self.prop, "0", "--prompts", self.root)                     # v2
        with open(os.path.join(self.root, "CURRENT"), "w") as fh:
            fh.write("v1\n")                                                    # rolled back by hand
        rc, out, _ = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        self.assertEqual(prompts.current(self.root), "v3")
        self.assertIn("--- v1.action", out)

    def test_bad_k_and_digit_refused(self):
        rc, _, err = self._run(self.prop, "2", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("no candidate 2", err)
        with open(self.prop, "w") as fh:
            json.dump({"candidates": [{**CAND, "instructions": "wait 15 minutes"}]}, fh)
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("digit", err)
        self.assertEqual(sorted(os.listdir(self.root)), ["CURRENT", "v1.json"])


class ProposeDryTest(unittest.TestCase):
    def test_dry_writes_proposal_from_fixture_and_sends_nothing(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        _write_log(os.path.join(tmp, "data", "decisions.jsonl"), synthetic_log())
        sends_before = os.path.getsize(config.SENDS) if os.path.exists(config.SENDS) else None
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry",
                            "--date", "2026-09-22", "--root", tmp],
                           cwd=tmp, capture_output=True, text=True, timeout=120,
                           env={**os.environ, "TYPESAFE_API_KEY_LOOP": "", "TYPESAFE_API_KEY": ""})
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(tmp, "proposals", "2026-09-22.json")) as fh:
            doc = json.load(fh)
        self.assertEqual(list(doc), ["candidates"])
        self.assertEqual(len(doc["candidates"]), 1)
        c = doc["candidates"][0]
        self.assertEqual(sorted(c), ["criteria", "instructions", "rationale"])
        self.assertEqual(list(c["criteria"]), ["buy", "sell", "hold"])
        self.assertIn("liquidity is deep", c["criteria"]["buy"])
        self.assertFalse(any(ch.isdigit() for ch in c["instructions"] + "".join(c["criteria"].values())))
        policy_table.load_candidates(os.path.join(tmp, "proposals", "2026-09-22.json"))   # the table accepts it
        with open(os.path.join(tmp, "logs", "propose.log")) as fh:
            log = fh.read()
        self.assertIn("OK proposals/2026-09-22.json", log)
        self.assertIn("dry: 81 payloads, 0 sent", log)
        self.assertTrue(os.path.exists(os.path.join(tmp, "data", "digest-2026-09-22.md")))
        self.assertFalse(os.path.exists(os.path.join(tmp, "proposals", "2026-09-22.md")))   # dry writes no table
        self.assertFalse(os.path.exists(os.path.join(tmp, "data", "sends.tsv")))
        sends_after = os.path.getsize(config.SENDS) if os.path.exists(config.SENDS) else None
        self.assertEqual(sends_before, sends_after)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", log + r.stdout + r.stderr)

    def test_usage_error_is_2_and_dry_needs_no_claude(self):
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--bogus"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2)
        with open(os.path.join(REPO, "nightly", "propose.sh")) as fh:
            src = fh.read()
        self.assertIn('--tools ""', src)
        self.assertNotIn("echo $CLAUDE_CODE_OAUTH_TOKEN", src)
        self.assertNotIn("prompts/", src.split("# May not")[1].split("\n")[0])   # the header says it never writes there


if __name__ == "__main__":
    unittest.main()

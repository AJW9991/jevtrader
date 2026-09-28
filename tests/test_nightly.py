"""nightly: the digest lists the right arm-B disagreements in the right order and
leaks no feature; the policy table enumerates 81 digit-free states and sends nothing
in --dry; promote refuses on a dirty tree and carries v1's three nouls byte for byte;
propose.sh --dry turns the fixture reply into a proposals json. Offline: loop.jev.ask
is mocked wherever the table is run, subprocess.run is mocked for git, and every
write lands in a temp dir. Nothing here opens a socket."""
import datetime, hashlib, importlib.util, io, json, os, shutil, subprocess, sys, tempfile, time, unittest
from contextlib import redirect_stdout
from unittest import mock

from fixture_prompts import pin_v1
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


def _sh_env(tmp=None, **extra):
    """propose.sh's environment for a test. JEVLOOP_PY is the interpreter running the suite
    (under `make test` on the Mac that is /opt/homebrew/bin/python3, the script's default); on a
    host with no /usr/bin/caffeinate (a Linux checkout, CI) JEVLOOP_CAFFEINATE is a stub in `tmp`
    that drops `-i` and runs the command, so the live branch can be driven there too. Both keys
    are blank so nothing here could ever find one."""
    env = {**os.environ, "TYPESAFE_API_KEY_LOOP": "", "TYPESAFE_API_KEY": "", "JEVLOOP_PY": sys.executable, **extra}
    if tmp is not None and not os.access("/usr/bin/caffeinate", os.X_OK):
        stub = os.path.join(tmp, "caffeinate")
        with open(stub, "w") as fh:
            fh.write('#!/bin/bash\n[ "$1" = "-i" ] && shift\nexec "$@"\n')
        os.chmod(stub, 0o755)
        env["JEVLOOP_CAFFEINATE"] = stub
    return env


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
        pin_v1(self)                                                 # the digest quotes CURRENT: pin it to v1

    def test_disagreement_rows_and_order(self):
        text, n = digest.build(DAY, self.log)
        self.assertEqual(n, 41)
        self.assertEqual(_table_rows(text), [("buy", 0.95, "down"), ("sell", 0.90, "up"), ("sell", 0.86, "up")])
        self.assertIn("B disagreements 3", text)
        self.assertIn("3 of 3 shown", text)

    def test_rows_of_a_superseded_wording_are_not_arm_b_on_current(self):
        rows = synthetic_log()
        rows[0]["prompt_b"], rows[1]["prompt_b"] = "v2", "v2"            # the two most confident listed rows answered v2
        rows[5]["prompt_b"] = "v1"                                       # CURRENT is pinned to v1: this one stays
        _write_log(self.log, rows)
        text, n = digest.build(DAY, self.log)
        self.assertEqual(n, 41)
        self.assertEqual(_table_rows(text), [("sell", 0.86, "up")])
        self.assertIn("B disagreements 1 | prompt_b v1 1, v2 2 (arm B is read from the v1 rows only; the other rows answered a superseded wording)", text)
        self.assertEqual(digest.versions(rows), {"v1": 1, "v2": 2})
        self.assertEqual(len(digest.on_current(rows, "v1")), 39)

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
        # 2026-09-24, decided by Alex: PnL per arm twice, labelled -- at 0 bps (H1, direction)
        # and at the venue's own taker fee (the realistic cost)
        self.assertIn(f"column argmax, paper PnL at {config.FEE_BPS_PRIMARY:g} bps (direction) / at "
                      f"{config.FEE_BPS_VENUE:g} bps (venue fee): A 0 trades +0.0 / +0.0 bps", line)
        self.assertIn("paper PnL at 0 bps (direction) / at 120 bps (venue fee)", line)
        # a trade is a FILL (book.replay "trades"), not a round trip: B opens at 0, closes at 1,
        # opens again at 2 (buy 0.99), holds through 3-4 and closes at 5 (sell 0.86); the
        # sell at 30 finds it flat and is a no-op. Four fills, two round trips.
        self.assertIn("B 4 trades", line)
        self.assertIn("C 1 trades", line)                 # rule_c buy at minute 0, then held long
        self.assertIn("B disagreements 3", line)

    def test_summary_pnl_at_both_fees(self):
        # the trade count is the same at both fees (a fee never changes a decision); the net
        # figure is the gross one minus each fill's fee. C: one fill, the open at minute 0 at
        # ask 100.01 on $1,000, fee exactly FEE_BPS_VENUE bps of notional.
        day = [r for r in digest.outcomes.load(self.log, []) if r["tick_id"].startswith("20260922")]
        gross, net = digest.arms(day, config.FEE_BPS_PRIMARY), digest.arms(day, config.FEE_BPS_VENUE)
        for arm in ("a", "b", "c"):
            self.assertEqual(gross[arm][0], net[arm][0], arm)
        self.assertEqual(gross["c"][0], 1)
        self.assertAlmostEqual(gross["c"][1] - net["c"][1], config.FEE_BPS_VENUE, places=9)
        self.assertEqual(gross["b"][0], 4)
        self.assertGreater(gross["b"][1] - net["b"][1], 3.9 * config.FEE_BPS_VENUE)   # four fills, ~120 each
        line = digest.build(DAY, self.log)[0].splitlines()[2]
        self.assertIn(f"C 1 trades {gross['c'][1]:+.1f} / {net['c'][1]:+.1f} bps", line)
        self.assertIn(f"B 4 trades {gross['b'][1]:+.1f} / {net['b'][1]:+.1f} bps", line)

    def test_cap_at_25(self):
        # forty buys at 0.9 on a mid that falls 0.1 a minute: every t+15 is ~-150 bps, so
        # all forty are disagreements and exactly DISAGREE_MAX = 25 are listed. (The earlier
        # form set the mid at t AND at t+15 to 99.0, so those buys were flat, not wrong,
        # and only 2 rows could ever be listed: the fixture, not the cap, was under test.)
        rows = [_row(m, 100.0 - 0.1 * m, ("buy", 0.9) if m < 40 else ("hold", 0.6)) for m in range(60)]
        _write_log(self.log, rows)
        text, _ = digest.build(DAY, self.log)
        self.assertEqual(len(_table_rows(text)), digest.DISAGREE_MAX)
        self.assertEqual(digest.DISAGREE_MAX, 25)
        self.assertIn("25 of 40 shown", text)
        self.assertIn("B disagreements 40", text)

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
        self.halt = os.path.join(self.tmp, "HALT")                  # never the repo's data/HALT
        self.enterContext(mock.patch.object(config, "HALT", self.halt))
        pin_v1(self)                                                 # current_action() reads CURRENT: pin it to v1
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

    def test_runs_by_path_as_the_contract_names_it(self):
        # CONTRACT §5 says `policy_table.py proposals/<date>.json` and `nightly/digest.py`:
        # run by path, sys.path[0] is nightly/ and `from loop import` must still resolve.
        env = {**os.environ, "TYPESAFE_API_KEY_LOOP": "", "TYPESAFE_API_KEY": ""}
        r = subprocess.run([sys.executable, os.path.join(REPO, "nightly", "policy_table.py"), "--dry", self.prop],
                           cwd=self.tmp, capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split("\n", 1)[0], "dry: 81 payloads, 0 sent")
        r = subprocess.run([sys.executable, os.path.join(REPO, "nightly", "digest.py"), "--help"],
                           cwd=self.tmp, capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)

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

        def fake(s, qs, **kw):                                  # current follows rule_c exactly; cand_0 always holds
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
        with open(self.halt) as fh:                                   # the caller writes HALT (CONTRACT §2)
            reason = fh.read()
        self.assertIn("key rejected", reason)
        self.assertIn("401", reason)

    def test_halt_present_sends_nothing(self):
        # PROTOCOL §3.8: HALT stops sends. These never reach decisions.jsonl, so the spend
        # guard cannot see them; without this check the nightly sent 81 after a HALT.
        with open(self.halt, "w") as fh:
            fh.write("spend: by hand\n")
        out = os.path.join(self.tmp, "t.md")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = policy_table.main([self.prop, "--out", out])
        self.assertEqual(rc, 0)
        self.assertIn("HALT present", buf.getvalue())
        self.ask.assert_not_called()
        self.urlopen.assert_not_called()
        self.assertFalse(os.path.exists(out))

    def test_persistent_429_ends_the_night_after_one_ask(self):
        self.ask.side_effect = jev.JevError("http-429", "429 Too Many Requests", 429, "env:X")
        results = policy_table.run(policy_table.questions(policy_table.load_candidates(self.prop),
                                                          policy_table.current_action()[1]))
        self.assertEqual(self.ask.call_count, 1)                     # jev.ask's own retry is its only one
        self.assertEqual({r["error"] for r in results}, {"http-429"})
        self.assertFalse(os.path.exists(self.halt))                  # a limit is not a rejected key

    def test_transient_failures_in_a_row_end_the_night(self):
        self.ask.side_effect = jev.JevError("http-5xx", "503", 503, "env:X")
        results = policy_table.run(policy_table.questions(policy_table.load_candidates(self.prop),
                                                          policy_table.current_action()[1]))
        self.assertEqual(self.ask.call_count, policy_table.MAX_TRANSIENT_RUN)
        self.assertEqual(sum(1 for r in results if r["error"]), 81)

    def test_three_other_errors_in_a_row_end_the_night(self):
        by = _by_state()
        calls = []

        def fake(s, qs, **kw):
            calls.append(s)
            if len(calls) >= 3:
                raise jev.JevError("http-4xx", "x", 404, "env:X")        # not 401/403: not a HALT, not fatal alone
            return {"answers": {"cand_0": _answer("hold", 0.5), "current": _answer(state.rule_c(by[s]), 0.9)},
                    "model": config.MODEL}
        self.ask.side_effect = fake
        results = policy_table.run(policy_table.questions(policy_table.load_candidates(self.prop),
                                                          policy_table.current_action()[1]))
        self.assertEqual(len(calls), 5)                                  # 2 answers, then 3 in a row end it
        self.assertEqual(sum(1 for r in results if r["error"] == "http-4xx"), 79)
        self.assertEqual(policy_table.counts(results, "cand_0")[2], 2)

    def test_table_names_the_proposal_sha(self):
        by = _by_state()
        self.ask.side_effect = lambda s, qs, **kw: {"answers": {"cand_0": _answer("hold", 0.5), "current": _answer(state.rule_c(by[s]), 0.9)},
                                                    "model": config.MODEL}
        out = os.path.join(self.tmp, "t.md")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(policy_table.main([self.prop, "--out", out]), 0)
        with open(self.prop, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        with open(out) as fh:
            self.assertIn(f"proposal sha256: {sha}", fh.read())

    def test_transient_error_continues(self):
        by = _by_state()
        calls = []

        def fake(s, qs, **kw):
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

    def _answers(self, s, model=config.MODEL):
        r = {"answers": {"cand_0": _answer("hold", 0.5), "current": _answer(state.rule_c(_by_state()[s]), 0.9)}}
        if model is not None:
            r["model"] = model
        return r

    def test_a_halt_written_mid_table_stops_the_rest(self):
        # PROTOCOL §3.8: HALT stops sends. main() checks it once before the first send; a HALT a
        # person or the loop writes while the table runs must stop every send after it too.
        calls = []

        def fake(s, qs, **kw):
            calls.append(s)
            if len(calls) == 3:
                with open(self.halt, "w") as fh:
                    fh.write("spend: by hand, mid-table\n")
            return self._answers(s)
        self.ask.side_effect = fake
        out = os.path.join(self.tmp, "t.md")
        with redirect_stdout(io.StringIO()):
            rc = policy_table.main([self.prop, "--out", out])
        self.assertEqual(rc, policy_table.EXIT_INCOMPLETE)
        self.assertEqual(len(calls), 3)                                  # the fourth state found HALT: no send
        with open(out) as fh:
            text = fh.read()
        self.assertIn("requests: 81, answered: 3, errors: 78 -- INCOMPLETE", text)
        self.assertIn("error kinds: halt", text)
        self.urlopen.assert_not_called()

    def test_alternating_error_kinds_end_the_night(self):
        # timeout resets the "other" run and a 404 resets the transient run, so each per-kind
        # counter alone never reaches 3; the any-kind counter does.
        kinds = [("timeout", None), ("http-4xx", 404)]
        calls = []

        def fake(s, qs, **kw):
            k, st = kinds[len(calls) % 2]
            calls.append(s)
            raise jev.JevError(k, "x", st, "env:X")
        self.ask.side_effect = fake
        results = policy_table.run(policy_table.questions(policy_table.load_candidates(self.prop),
                                                          policy_table.current_action()[1]))
        self.assertEqual(len(calls), policy_table.MAX_ERROR_RUN)
        self.assertEqual(policy_table.MAX_ERROR_RUN, 3)
        self.assertEqual(sum(1 for r in results if r["error"]), 81)
        self.assertFalse(os.path.exists(self.halt))                      # neither kind is a rejected key

    def test_an_answer_between_errors_resets_the_any_kind_run(self):
        seq = ["timeout", "http-4xx", "ok"] * 27                          # never three errors in a row

        def fake(s, qs, **kw):
            k = seq[self.ask.call_count - 1]
            if k == "ok":
                return self._answers(s)
            raise jev.JevError(k, "x", 404 if k == "http-4xx" else None, "env:X")
        self.ask.side_effect = fake
        results = policy_table.run(policy_table.questions(policy_table.load_candidates(self.prop),
                                                          policy_table.current_action()[1]))
        self.assertEqual(self.ask.call_count, 81)
        self.assertEqual(sum(1 for r in results if r["answers"]), 27)

    def test_the_sha_is_of_the_bytes_the_candidates_were_read_from(self):
        # the json is read once: a rewrite while the 81 sends run must not give the table a sha
        # of bytes it never described (bin/promote trusts that line)
        with open(self.prop, "rb") as fh:
            original = fh.read()

        def fake(s, qs, **kw):
            if self.ask.call_count == 1:
                with open(self.prop, "w") as fh:
                    json.dump({"candidates": [{**CAND, "rationale": "rewritten mid-table"}]}, fh)
            return self._answers(s)
        self.ask.side_effect = fake
        out = os.path.join(self.tmp, "t.md")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(policy_table.main([self.prop, "--out", out]), 0)
        with open(out) as fh:
            text = fh.read()
        self.assertIn(f"proposal sha256: {hashlib.sha256(original).hexdigest()}", text)
        self.assertIn("rationale: test", text)
        self.assertNotIn("rewritten mid-table", text)

    def test_an_answer_naming_no_model_is_drift(self):
        # cycle.py logs drift when the reply's model is not config.MODEL, None included
        self.ask.side_effect = lambda s, qs, **kw: self._answers(s, model=None)
        out = os.path.join(self.tmp, "t.md")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(policy_table.main([self.prop, "--out", out]), 0)
        with open(out) as fh:
            text = fh.read()
        self.assertIn(f"model answered: no model named on 81 -- DRIFT, requested {config.MODEL}", text)
        self.ask.side_effect = lambda s, qs, **kw: self._answers(s, model=None if s.endswith("calm") else config.MODEL)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(policy_table.main([self.prop, "--out", out]), 0)
        with open(out) as fh:
            text = fh.read()
        self.assertIn(f"model answered: {config.MODEL}, no model named on 27 -- DRIFT", text)


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
        shutil.copy(os.path.join(REPO, "prompts", "v1.json"), self.root)
        with open(os.path.join(self.root, "CURRENT"), "w") as fh:  # v1, not the live CURRENT (v2 since 2026-09-26)
            fh.write("v1\n")
        self.prop = os.path.join(self.tmp, "2026-09-22.json")
        with open(self.prop, "w") as fh:
            json.dump({"candidates": [CAND, {**CAND, "instructions": "Second candidate."}]}, fh)
        self.promote = _load_promote()
        self.git = self.enterContext(mock.patch.object(self.promote.subprocess, "run"))
        self.status, self.tags = "", "prereg-v1\n"                   # a clean tree, PREREG sealed

        def git(argv, **kw):
            out = self.status if argv[:2] == ["git", "status"] else self.tags if argv[:2] == ["git", "tag"] else None
            if out is None:
                raise AssertionError(f"unexpected command {argv}")
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
        self.git.side_effect = git
        self.enterContext(mock.patch.object(self.promote, "_attended", return_value=True))

    def _run(self, *argv):
        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), mock.patch("sys.stderr", err):
            rc = self.promote.main(list(argv))
        return rc, buf.getvalue(), err.getvalue()

    def test_the_committed_table_vouches_for_the_json(self):
        md = self.prop[:-5] + ".md"
        with open(md, "w") as fh:
            fh.write("# policy table\n\nproposal sha256: " + "0" * 64 + "  \n")
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("changed after its table was made", err)
        self.assertFalse(os.path.exists(os.path.join(self.root, "v2.json")))
        with open(self.prop, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        with open(md, "w") as fh:
            fh.write("# policy table\n\nproposal sha256: " + sha + "  \n")
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        self.assertNotIn("WARNING", err)

    def test_no_table_warns_and_proceeds(self):
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        self.assertIn("WARNING no policy table", err)

    def test_an_incomplete_table_warns(self):
        # a table that answered 2 of 81 states vouches for the json's bytes but not for the
        # candidate's behaviour: the person at the terminal is told before CURRENT moves
        with open(self.prop, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        md = self.prop[:-5] + ".md"
        with open(md, "w") as fh:
            fh.write("# policy table\n\nproposal sha256: " + sha + "  \n"
                     "requests: 81, answered: 2, errors: 79 -- INCOMPLETE  \n")
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        self.assertIn(f"WARNING {md} is INCOMPLETE (answered 2 of 81 states)", err)
        self.assertEqual(prompts.current(self.root), "v2")

    def test_current_is_replaced_whole_never_truncated_in_place(self):
        # the loop reads CURRENT every minute: it is written beside and renamed over, so no tick
        # can read an empty file between a truncate and a write
        current, tmp = os.path.join(self.root, "CURRENT"), os.path.join(self.root, "CURRENT.tmp")
        with mock.patch.object(self.promote.os, "replace", wraps=os.replace) as rep:
            rc, _, _ = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        rep.assert_called_once_with(tmp, current)
        with open(current) as fh:
            self.assertEqual(fh.read(), "v2\n")
        self.assertFalse(os.path.exists(tmp))
        # a rename that fails leaves CURRENT exactly as it was, and no CURRENT.tmp behind
        with mock.patch.object(self.promote.os, "replace", side_effect=OSError("disk full")):
            rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("could not switch CURRENT (disk full); CURRENT still names v2", err)
        with open(current) as fh:
            self.assertEqual(fh.read(), "v2\n")
        self.assertFalse(os.path.exists(tmp))
        self.assertTrue(os.path.exists(os.path.join(self.root, "v3.json")))

    def test_dirty_tree_refuses_and_writes_nothing(self):
        self.status = " M loop/x.py\n"
        rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("dirty", err)
        self.assertEqual(sorted(os.listdir(self.root)), ["CURRENT", "v1.json"])
        self.assertEqual(prompts.current(self.root), "v1")
        self.git.assert_called_once()
        self.assertEqual(self.git.call_args.args[0], ["git", "status", "--porcelain"])

    def test_unsealed_prereg_refuses_and_writes_nothing(self):
        # PREREG §10: the tag must exist before the first row whose prompt_b is not v1.
        for tags in ("", "prereg-v1-draft\n", "other\n"):
            self.tags = tags
            rc, _, err = self._run(self.prop, "0", "--prompts", self.root)
            self.assertEqual(rc, 1, tags)
            self.assertIn("prereg-v1", err)
            self.assertEqual(sorted(os.listdir(self.root)), ["CURRENT", "v1.json"])
            self.assertEqual(prompts.current(self.root), "v1")
        self.assertEqual(self.git.call_args.args[0], ["git", "tag", "-l", "prereg-v1"])

    def test_promote_is_executable_as_the_contract_runs_it(self):
        # CONTRACT §5 and STEPS.md run `bin/promote proposals/<date>.json <k>` by path
        self.assertTrue(os.access(os.path.join(REPO, "bin", "promote"), os.X_OK))

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

    def test_promoted_action_has_type_choice_so_the_next_tick_builds(self):
        # nightly candidates carry only instructions + criteria (+ rationale); prompts.build()
        # refuses a question without "type", so a promote that copied the candidate verbatim
        # would make the first tick after it raise PromptError. Replayed with exactly the
        # calls cycle._run makes: load v1, current(), load(current), build.
        self.assertNotIn("type", CAND)
        rc, _, _ = self._run(self.prop, "0", "--prompts", self.root)
        self.assertEqual(rc, 0)
        cur = prompts.current(self.root)
        doc = prompts.load(cur, self.root)
        self.assertEqual(doc["action"]["type"], "choice")
        qs = prompts.build(prompts.load("v1", self.root), doc)
        self.assertEqual(list(qs), ["a_action", "b_action", "skip", "up15", "down15"])
        self.assertEqual(qs["b_action"], {"type": "choice", "instructions": CAND["instructions"],
                                          "criteria": CAND["criteria"]})

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
                           cwd=tmp, capture_output=True, text=True, timeout=120, env=_sh_env())
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

    def test_halt_present_skips_the_table(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        _write_log(os.path.join(tmp, "data", "decisions.jsonl"), synthetic_log())
        with open(os.path.join(tmp, "data", "HALT"), "w") as fh:
            fh.write("by hand\n")
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry",
                            "--date", "2026-09-22", "--root", tmp],
                           cwd=tmp, capture_output=True, text=True, timeout=120, env=_sh_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(tmp, "logs", "propose.log")) as fh:
            log = fh.read()
        self.assertIn("HALT present", log)
        self.assertNotIn("dry: 81 payloads", log)                    # policy_table.py never ran
        self.assertNotIn("OK proposals/", log)
        self.assertTrue(os.path.exists(os.path.join(tmp, "proposals", "2026-09-22.json")))

    def test_usage_error_is_2_and_dry_needs_no_claude(self):
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--bogus"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2)
        with open(os.path.join(REPO, "nightly", "propose.sh")) as fh:
            src = fh.read()
        self.assertIn('--tools ""', src)
        self.assertNotIn("echo $CLAUDE_CODE_OAUTH_TOKEN", src)
        # The header's "May not" line NAMES prompts/ -- it is the promise never to write there
        # (CONTRACT §5) -- so the promise is asserted as present, and kept by checking that no
        # line of code (comments excluded) mentions prompts/ at all.
        self.assertIn("write under prompts/", src.split("# May not")[1].split("\n")[0])
        code = [l for l in src.splitlines() if not l.lstrip().startswith("#")]
        self.assertEqual([l for l in code if "prompts/" in l or "/prompts" in l], [])



class LiveBranch(unittest.TestCase):
    """propose.sh's live branch, driven end to end with a stub claude (JEVLOOP_CLAUDE), a temp token
    file (JEVLOOP_TOKEN_FILE) and a short cap (JEVLOOP_CLAUDE_CAP_S). data/HALT in the temp root
    keeps policy_table from sending (PROTOCOL §3.8), so nothing here reaches api.typesafe.ai."""
    TOKEN = "sekrit-token-value-never-printed"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _write_log(os.path.join(self.tmp, "data", "decisions.jsonl"), synthetic_log())
        with open(os.path.join(self.tmp, "data", "HALT"), "w") as fh:
            fh.write("test: no sends\n")
        self.token = os.path.join(self.tmp, "token")
        with open(self.token, "w") as fh:
            fh.write(self.TOKEN + "\n")
        self.saw = os.path.join(self.tmp, "saw")                         # what the stub saw: argv, cwd, token
        os.makedirs(self.saw)
        pin_v1(self)

    def _stub(self, body):
        p = os.path.join(self.tmp, "claude")
        with open(p, "w") as fh:
            fh.write("#!/bin/bash\n" + body)
        os.chmod(p, 0o755)
        return p

    def _run(self, stub, cap="2700", **extra):
        env = _sh_env(self.tmp, JEVLOOP_CLAUDE=stub, JEVLOOP_TOKEN_FILE=self.token, JEVLOOP_CLAUDE_CAP_S=cap, **extra)
        return subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--date", DAY.isoformat(), "--root", self.tmp],
                              capture_output=True, text=True, timeout=120, env=env, cwd=REPO)

    def _home(self, memory=None):
        """A HOME for the run: empty, or with ~/.claude/CLAUDE.md holding `memory`."""
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, ".claude"), exist_ok=True)
        if memory is not None:
            with open(os.path.join(home, ".claude", "CLAUDE.md"), "w") as fh:
                fh.write(memory)
        return home

    def _everything_written(self):
        out = []
        for d in ("logs", "proposals", "data"):
            for f in os.listdir(os.path.join(self.tmp, d)):
                with open(os.path.join(self.tmp, d, f), errors="replace") as fh:
                    out.append(fh.read())
        return "\n".join(out)

    def test_live_branch_end_to_end_token_set_never_printed(self):
        # the stub answers --version (propose.sh logs it), then records what the real call gets:
        # its argv NUL-separated (the prompt spans lines, and --tools takes an EMPTY argument), its
        # working directory and that directory's listing, and whether the token reached it
        stub = self._stub('[ "$1" = --version ] && {{ echo "9.9.9 (stub claude)"; exit 0; }}\n'
                          '[ -n "$CLAUDE_CODE_OAUTH_TOKEN" ] && echo TOKEN_SET >"{saw}/token"\n'
                          'printf "%s\\0" "$@" >"{saw}/argv"\n'
                          'pwd -P >"{saw}/cwd"\n'
                          'ls -A >"{saw}/ls"\n'
                          'cat <<"EOF"\nreply\n\n```json\n{{"candidates": [{{"rationale": "t", "instructions": "Decide.",'
                          ' "criteria": {{"buy": "pumping", "sell": "dumping", "hold": "else"}}}}]}}\n```\nEOF\n'.format(saw=self.saw))
        memory = "user memory the CLI loads\n"
        r = self._run(stub, HOME=self._home(memory))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.saw, "token")), "the stub never saw the token in its environment")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "proposals", f"{DAY.isoformat()}.json")))
        with open(os.path.join(self.tmp, "logs", "propose.log")) as fh:
            log = fh.read()
        self.assertIn("claude exit 0 after", log)
        self.assertIn("(cap 2700 s awake)", log)
        self.assertIn("HALT present", log)                                    # policy_table never ran: no send
        self.assertNotIn("OK proposals/", log)
        for blob in (r.stdout, r.stderr, self._everything_written()):
            self.assertNotIn(self.TOKEN, blob)
        # the flags, exactly: no tool, no MCP, no settings file but ours, text out
        with open(os.path.join(self.saw, "argv"), "rb") as fh:
            argv = fh.read().decode("utf-8").split("\0")[:-1]
        repo = os.path.realpath(REPO)
        self.assertEqual(argv[0], "-p")
        with open(os.path.join(REPO, "nightly", "PROMPT.md"), encoding="utf-8") as fh:
            self.assertTrue(argv[1].startswith(fh.read().rstrip("\n") + "\n\n"))   # PROMPT.md, then the digest
        self.assertIn("B disagreements", argv[1])
        self.assertEqual(argv[2:], ["--tools", "", "--restricted", "--strict-mcp-config",
                                    "--settings", os.path.join(repo, "nightly", "settings.json"), "--output-format", "text"])
        for a in argv:
            self.assertNotIn(self.TOKEN, a)
        # the working directory: not the repo, not under it, empty, no CLAUDE.md above it, gone after
        with open(os.path.join(self.saw, "cwd")) as fh:
            cwd = fh.read().strip()
        self.assertNotEqual(cwd, repo)
        self.assertFalse(cwd.startswith(repo + os.sep), cwd)
        with open(os.path.join(self.saw, "ls")) as fh:
            self.assertEqual(fh.read(), "")
        d = os.path.dirname(cwd)
        while True:
            self.assertFalse(os.path.exists(os.path.join(d, "CLAUDE.md")), d)
            if d == os.path.dirname(d):
                break
            d = os.path.dirname(d)
        self.assertFalse(os.path.exists(cwd), "the empty cwd was not removed")
        # and the night's record: that cwd, the user memory's sha, the CLI's version
        self.assertIn("(empty); user memory ", log)
        self.assertIn("CLAUDE.md sha256 " + hashlib.sha256(memory.encode()).hexdigest()[:12] + "; cli 9.9.9 (stub claude)", log)

    def test_a_hung_claude_is_one_fail_line_and_the_night_ends_clean(self):
        stub = self._stub('[ "$1" = --version ] && { echo "9.9.9 (stub claude)"; exit 0; }\nsleep 30\n')
        t = time.monotonic()
        r = self._run(stub, cap="1")
        self.assertEqual(r.returncode, 0)
        self.assertLess(time.monotonic() - t, 25)
        with open(os.path.join(self.tmp, "logs", "propose.log")) as fh:
            log = fh.read()
        self.assertIn("claude exit 124 after", log)
        self.assertIn("FAIL claude capped at 1 s awake", log)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "proposals", f"{DAY.isoformat()}.json")))

    def test_a_failing_claude_is_one_fail_line(self):
        stub = self._stub('pwd -P >"%s/cwd"; echo boom >&2; exit 7\n' % self.saw)
        r = self._run(stub, HOME=self._home())
        self.assertEqual(r.returncode, 0)
        with open(os.path.join(self.tmp, "logs", "propose.log")) as fh:
            log = fh.read()
        self.assertIn("FAIL claude exit 7", log)
        self.assertIn("CLAUDE.md absent; cli unknown", log)                  # no user memory; --version failed too
        with open(os.path.join(self.saw, "cwd")) as fh:
            self.assertFalse(os.path.exists(fh.read().strip()), "a failed night left its empty cwd behind")
        with open(os.path.join(self.tmp, "logs", f"claude-{DAY.isoformat()}.err")) as fh:
            self.assertIn("boom", fh.read())

    def test_a_reply_without_one_json_block_is_invalid(self):
        stub = self._stub('echo "no block here"\n')
        r = self._run(stub)
        self.assertEqual(r.returncode, 0)
        with open(os.path.join(self.tmp, "logs", "propose.log")) as fh:
            self.assertIn("FAIL invalid proposal", fh.read())


class Capped(unittest.TestCase):
    """nightly/capped.py: the claude call's cap on awake seconds (propose.sh wires it in)."""
    PY = sys.executable                       # /opt/homebrew/bin/python3 under `make test` on the Mac; whatever runs the suite elsewhere

    def _run(self, *args):
        return subprocess.run([self.PY, "-m", "nightly.capped", *args], cwd=REPO, capture_output=True, text=True, timeout=30)

    def test_exit_is_the_commands_own(self):
        self.assertEqual(self._run("5", "--", "true").returncode, 0)
        self.assertEqual(self._run("5", "--", "sh", "-c", "exit 7").returncode, 7)

    def test_a_hang_exits_124_and_kills_the_child(self):
        t = time.monotonic()
        r = self._run("1", "--", "sleep", "20")
        self.assertEqual(r.returncode, 124)
        self.assertLess(time.monotonic() - t, 10)
        self.assertIn("exceeded 1 s awake", r.stderr)

    def test_usage_is_2_and_a_missing_command_is_127(self):
        self.assertEqual(self._run("x", "--", "true").returncode, 2)
        self.assertEqual(self._run("5", "true").returncode, 2)
        self.assertEqual(self._run("0", "--", "true").returncode, 2)
        self.assertEqual(self._run("5", "--", "/nonexistent-cmd").returncode, 127)

    def test_a_child_killed_by_a_signal_exits_128_plus_the_signal(self):
        # subprocess reports -15 for SIGTERM; sys.exit(-15) would exit 241, which reads as the
        # command's own code. A shell says 143, and so does capped.
        r = subprocess.run([sys.executable, "-m", "nightly.capped", "5", "--", "sh", "-c", "kill -TERM $$"],
                           cwd=REPO, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 128 + 15)

    def test_propose_sh_rebuilds_the_dash_after_the_table_non_fatally(self):
        with open(os.path.join(REPO, "nightly", "propose.sh")) as fh:
            src = fh.read()
        code = [l for l in src.splitlines() if not l.lstrip().startswith("#")]
        dash = [l for l in code if "-m loop.dash" in l]
        self.assertEqual(len(dash), 1)
        self.assertIn('--log "$ROOT/data/decisions.jsonl" --out "$ROOT/data/dash.html"', dash[0])
        self.assertIn('|| log "dash:', code[code.index(dash[0]) + 1])
        # the table's OK line comes BEFORE the dash, so a dash failure can never hide a good night
        self.assertLess(code.index([l for l in code if 'log "OK proposals/$DATE.json"' in l][0]), code.index(dash[0]))
        # and a --dry run against a temp root writes the page there, never into the repo's data/
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "decisions.jsonl"), "w") as fh:
            pass
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22", "--root", tmp],
                           capture_output=True, text=True, timeout=120, env=_sh_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(tmp, "data", "dash.html")))
        with open(os.path.join(tmp, "logs", "propose.log")) as fh:
            self.assertIn("note: no proposal exists for 2026-09-21 (a missed slot?); this run is for 2026-09-22 only", fh.read())

    def test_propose_sh_guards_repo_root_and_cwd(self):
        with open(os.path.join(REPO, "nightly", "propose.sh")) as fh:
            code = [l for l in fh.read().splitlines() if not l.lstrip().startswith("#")]
        self.assertEqual([l for l in code if l.startswith("guard_path ")],
                         ['guard_path "$REPO" repo', 'guard_path "$(cd "$ROOT" 2>/dev/null && pwd -P || echo "$ROOT")" root', 'guard_path "$(pwd -P)" cwd'])
        forbidden = os.path.expanduser("~/Projects/crypto-trading-system")
        r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--root", os.path.join(forbidden, "x")],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 3)
        self.assertIn("forbidden prefix (root)", r.stderr)

    def test_propose_sh_defaults_are_the_mac_paths_and_launchd_sets_no_knob(self):
        # The JEVLOOP_* variables are for the suite (here, and on a host without Homebrew or
        # caffeinate). Under launchd the plist sets only PATH, so every one of them is its default,
        # and the defaults must stay the paths STEPS.md installs against.
        with open(os.path.join(REPO, "nightly", "propose.sh")) as fh:
            src = fh.read()
        for line in ('PY="${JEVLOOP_PY:-/opt/homebrew/bin/python3}"',
                     'CLAUDE="${JEVLOOP_CLAUDE:-/opt/homebrew/bin/claude}"',
                     'CAFFEINATE="${JEVLOOP_CAFFEINATE:-/usr/bin/caffeinate}"',
                     'TOKEN_FILE="${JEVLOOP_TOKEN_FILE:-$HOME/.secondbrain-secrets/oauth_token}"'):
            self.assertIn(line, src)
        for plist in ("com.alexward.jevloop.loop.plist", "com.alexward.jevloop.nightly.plist"):
            with open(os.path.join(REPO, "launchd", plist)) as fh:
                self.assertNotIn("JEVLOOP", fh.read(), plist)
        # and a --dry run with no knob at all still refuses, in one FAIL line, when the Mac's
        # python is absent, rather than falling back to whatever python3 is on PATH
        if not os.path.exists("/opt/homebrew/bin/python3"):
            tmp = tempfile.mkdtemp()
            r = subprocess.run(["/bin/bash", os.path.join(REPO, "nightly", "propose.sh"), "--dry", "--date", "2026-09-22", "--root", tmp],
                               capture_output=True, text=True, timeout=30, env={**os.environ, "JEVLOOP_PY": ""})
            self.assertEqual(r.returncode, 0)
            self.assertIn("FAIL no python at /opt/homebrew/bin/python3", r.stderr)

    def test_propose_sh_wires_the_cap_around_claude_under_caffeinate(self):
        with open(os.path.join(REPO, "nightly", "propose.sh")) as fh:
            src = fh.read()
        code = [l for l in src.splitlines() if not l.lstrip().startswith("#")]
        call = [l for l in code if '"$CAFFEINATE" -i' in l]
        self.assertEqual(len(call), 1)
        # caffeinate outermost, then capped BY PATH: the call runs in an empty temp dir, where
        # `-m nightly.capped` would not resolve
        self.assertIn('cd "$WORK"', call[0])
        self.assertIn('"$CAFFEINATE" -i "$PY" "$REPO/nightly/capped.py" "$CLAUDE_CAP_S" --', call[0])
        self.assertEqual([l for l in code if "-m nightly.capped" in l], [])
        self.assertIn('CLAUDE_CAP_S="${JEVLOOP_CLAUDE_CAP_S:-2700}"', src)
        self.assertIn('[ $rc -eq 124 ] && fail "claude capped', src)

if __name__ == "__main__":
    unittest.main()

"""nightly/digest.py, v2 (PREREG-v2 §8): the UTC day just closed, only rows carrying this tree's SPEC sha, per product
and pooled, the summary at 0 bps and at the verified maker (50) and taker (90), every arm-B figure from rows whose
prompt_b is the version prompts.current() names for that row's tick, the disagreement rows as before (now over the
products), and the per-state table of 81 rows per product. A golden file holds every byte of the digest of a fixed
three-product day (tests/golden/digest-v2.md); the other tests say by hand what the golden bytes must contain.

Offline and hermetic: config.PRODUCTS is patched to SOL-USD, ETH-USD and XRP-USD with the stand-in ticks of
tests/fixture_products (so the golden does not move when the probe's real products are added), config.SPEC to a temp
file (so the tree's spec sha does not move with SPEC.md), and the prompts root is a temp dir holding copies of the
frozen v1.json and v2.json and a v3 written here."""
import datetime, io, json, os, shutil, tempfile, unittest
from contextlib import redirect_stdout
from unittest import mock

from fixture_products import STAND_IN
from loop import config, cycle, dash, inference_v2, prompts, report, rules, state
from nightly import digest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(REPO, "tests", "golden", "digest-v2.md")
DAY = datetime.date(2026, 10, 30)
T0 = datetime.datetime(2026, 10, 30, 10, 0, 0, tzinfo=datetime.timezone.utc)
PRODUCTS3 = ("SOL-USD", "ETH-USD", "XRP-USD")
ACT = "20261030T102000Z"                    # v3's activation: minute 20 of the fixture, inside the UTC day
NOW = "20261031T083000Z"                    # the nightly's minute: v3 is active
SCALE = {"SOL-USD": 1.0, "ETH-USD": 40.0, "XRP-USD": 0.025}
ADJ = {"SOL-USD": {"liq": "deep", "flow": "quiet", "trend": "pumping", "vol": "normal"},      # rule_c buy
       "ETH-USD": {"liq": "normal", "flow": "organic", "trend": "flat", "vol": "calm"},       # rule_c hold
       "XRP-USD": {"liq": "thin", "flow": "bot_war", "trend": "dumping", "vol": "violent"}}   # rule_c sell
FOREIGN = {"liq": "wild", "flow": "bot_war", "trend": "dumping", "vol": "violent"}
NOUL = {"noul": 0.0}
V3_ACTION = {"type": "choice", "instructions": "Decide whether to be long {BASE} for the next quarter of an hour.",
             "criteria": {"buy": "the trend is pumping and volatility is not violent", "sell": "the trend is dumping",
                          "hold": "anything else"}}


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _answer(choice, conf):
    p = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
    p[choice] = conf
    return {"choice": choice, "probabilities": p, "confidence": conf}


def _row(product, minute, mid, spec, b=None, absence=None, prompt_b=None, adj=None):
    """A CONTRACT §2 row of `product` at T0 + minute. b = (choice, confidence) for b_action; a_action always holds.
    prompt_b: v2 before ACT and v3 from it unless given. An absence row carries null answers."""
    d = T0 + datetime.timedelta(minutes=minute)
    adj = adj or ADJ[product]
    base = config.base(product)
    st = (state.state_string(adj, base) if adj is not FOREIGN
          else f"{base}: liquidity {adj['liq']}, flow {adj['flow']}, trend {adj['trend']}, vol {adj['vol']}")
    answers = None if absence or b is None else {
        "a_action": _answer("hold", 0.9), "b_action": _answer(*b), "skip": NOUL, "up15": NOUL, "down15": NOUL}
    tick = d.strftime("%Y%m%dT%H%M00Z")
    pb = prompt_b or ("v2" if tick < ACT else "v3")
    half = 0.01 * SCALE[product]
    return {"v": 1, "tick_id": tick, "ts_rx": _iso(d), "mode": "live", "venue": "coinbase", "product": product,
            "cadence_s": 60, "horizon_s": 900, "bid": None if mid is None else mid - half,
            "ask": None if mid is None else mid + half, "mid": mid, "features": {"ret15_z": 1.7, "rv_ratio": 0.9},
            "adj": adj, "state": st, "spec_sha": spec, "prompt_a": "v2", "prompt_b": None if absence == "feed" else pb,
            "answers": answers, "rule_c": state.rule_c(adj) if adj is not FOREIGN else "hold",
            "columns": {"a": rules.for_arm(answers, "a"), "b": rules.for_arm(answers, "b"), "d": None},
            "absence": absence}


def fixture_logs(spec):
    """{product: rows}: 41 minutes each from T0.
    SOL-USD, v1's digest fixture: mids 100 except at the six t+15 rows that resolve minutes 0..5; B buy 0.95 at 0
      (then down), sell 0.90 at 1 (up), buy 0.99 at 2 (up), buy 0.80 at 3 (below the cut), hold 0.99 at 4, sell 0.86
      at 5 (up), sell 0.97 at 30 (t+15 past the log); a feed absence at 6.
    ETH-USD, the same mids x 40: sell 0.97 at 0 (then down: right), buy 0.92 at 1 (up: right), buy 0.88 at 3 (down:
      wrong), sell 0.99 at 5 (up: wrong); a jev absence at 7.
    XRP-USD, mids 2.5 but 2.49 at 25 and 37, 2.51 at 26: minutes 0-9 carry prereg-v1's SPEC sha (not read); buy 0.90
      at 10 (then down: wrong); sell 0.95 at 11 asking v3 BEFORE v3's activation (not arm B's: not listed); a word
      outside the alphabet at 12; buy 0.86 at 22 asking v3 after it (down: wrong); a halt absence at 30."""
    mids = {15: 99.85, 16: 100.15, 17: 100.20, 18: 99.80, 19: 99.80, 20: 100.10}
    out = {}
    sol_b = {0: ("buy", 0.95), 1: ("sell", 0.90), 2: ("buy", 0.99), 3: ("buy", 0.80), 4: ("hold", 0.99),
             5: ("sell", 0.86), 30: ("sell", 0.97)}
    out["SOL-USD"] = [_row("SOL-USD", m, None, spec, absence="feed") if m == 6 else
                      _row("SOL-USD", m, mids.get(m, 100.0), spec, sol_b.get(m, ("hold", 0.6))) for m in range(41)]
    eth_b = {0: ("sell", 0.97), 1: ("buy", 0.92), 3: ("buy", 0.88), 5: ("sell", 0.99)}
    out["ETH-USD"] = [_row("ETH-USD", m, 40 * mids.get(m, 100.0), spec, absence="jev") if m == 7 else
                      _row("ETH-USD", m, 40 * mids.get(m, 100.0), spec, eth_b.get(m, ("hold", 0.6))) for m in range(41)]
    xmid = {25: 2.49, 26: 2.51, 37: 2.49}
    xrp = []
    for m in range(41):
        mid = xmid.get(m, 2.5)
        if m < 10:
            xrp.append(_row("XRP-USD", m, mid, dash.V1_SPEC_SHA, ("hold", 0.6)))
        elif m == 11:
            xrp.append(_row("XRP-USD", m, mid, spec, ("sell", 0.95), prompt_b="v3"))
        elif m == 12:
            xrp.append(_row("XRP-USD", m, mid, spec, ("hold", 0.6), adj=FOREIGN))
        elif m == 30:
            xrp.append(_row("XRP-USD", m, mid, spec, absence="halt"))
        else:
            xrp.append(_row("XRP-USD", m, mid, spec, {10: ("buy", 0.90), 22: ("buy", 0.86)}.get(m, ("hold", 0.6))))
    out["XRP-USD"] = xrp
    return out


def _write(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def three_products(tc):
    """config.PRODUCTS exactly PRODUCTS3, with tests/fixture_products' stand-in ticks, for the test's lifetime."""
    add = {p: STAND_IN[p] for p in PRODUCTS3[1:]}
    tc.enterContext(mock.patch.dict(config.TICK_P, {p: v[0] for p, v in add.items()}))
    tc.enterContext(mock.patch.dict(config.LIQ_ATOMS, {p: v[1] for p, v in add.items()}))
    tc.enterContext(mock.patch.dict(config.LIQ_THIN_FALLBACK, {p: v[2] for p, v in add.items()}))
    tc.enterContext(mock.patch.object(config, "PRODUCTS", PRODUCTS3))


def prompts_root(tc, current="v3", v3=True, extra=None):
    """A prompts root: the frozen v1.json and v2.json, a v3.json activating at ACT and replacing v2, CURRENT."""
    root = os.path.join(tc.enterContext(tempfile.TemporaryDirectory()), "prompts")
    os.makedirs(root)
    for v in ("v1", "v2"):
        shutil.copy(os.path.join(REPO, "prompts", v + ".json"), root)
    docs = {}
    if v3:
        v2 = prompts.load("v2", root)
        docs["v3"] = {"version": "v3", "frozen": "2026-10-29", "activation_tick": ACT, "replaces": "v2",
                      "note": "test", "action": V3_ACTION, **{q: v2[q] for q in prompts.CARRIED}}
    docs.update(extra or {})
    for v, doc in docs.items():
        with open(os.path.join(root, v + ".json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
    with open(os.path.join(root, "CURRENT"), "w", encoding="utf-8") as fh:
        fh.write(current + "\n")
    return root


def _table(text, product=None):
    """[(state, choice, confidence, ret, label)] of the disagreement table, file order."""
    sec = text.split("## arm B disagreements")[1].split("\n## ")[0]
    out = []
    for line in sec.splitlines():
        if line.startswith("| ") and ":" in line.split("|")[1]:
            c = [x.strip() for x in line.strip("|").split("|")]
            out.append((c[0], c[1], float(c[2]), float(c[3]), c[4]))
    return out


def _line(text, label):
    return next(l for l in text.splitlines() if l.startswith(label + " | "))


class DigestV2(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        three_products(self)
        spec = os.path.join(self.tmp, "SPEC.md")
        with open(spec, "w", encoding="utf-8") as fh:
            fh.write("# SPEC v2 (test)\n")
        self.enterContext(mock.patch.object(config, "SPEC", spec))
        self.spec = digest.tree_spec_sha()
        self.data = os.path.join(self.tmp, "data")
        self.logs = fixture_logs(self.spec)
        for p, rows in self.logs.items():
            _write(dash.store_paths(p, self.data)[0], rows)
        self.root = prompts_root(self)

    def _build(self, now=NOW, root=None):
        return digest.build(DAY, self.data, root or self.root, now)

    def test_the_digest_of_the_fixture_day_is_the_golden_file(self):
        # the digest's content is the treatment (PREREG-v2 §8), pinned by its source's sha at the draft tag: every
        # byte of it on this day is held here. Regenerate only with a change the author means, and read the diff.
        text, n = self._build()
        self.assertEqual(n, 41 + 41 + 31)
        with open(GOLDEN, encoding="utf-8") as fh:
            self.assertEqual(text, fh.read())

    def test_only_rows_of_this_trees_spec_are_read(self):
        text, n = self._build()
        self.assertIn("2026-10-30 UTC, the rows of this tree's SPEC; XRP-USD 10 row(s) of another spec_sha not read\n", text)
        self.assertTrue(_line(text, "XRP-USD").startswith("XRP-USD | ticks 31, answered 30, absence halt:1,"))
        self.assertNotIn(dash.V1_SPEC_SHA[:12], text)
        # a day whose rows all carry another SPEC is day zero for the digest: exit 4, nothing for the model
        other = digest.build(DAY, self.data, self.root, NOW, spec="f" * 64)
        self.assertEqual(other[1], 0)
        self.assertIn("SOL-USD 41 row(s) of another spec_sha not read; ETH-USD 41 row(s)", other[0])

    def test_arm_b_is_read_from_rows_asking_the_version_current_at_their_tick(self):
        text, _ = self._build()
        ticks = sorted({r["tick_id"] for r in self.logs["XRP-USD"]})
        vers = digest.versions_at(ticks, self.root)
        self.assertEqual({t for t, v in vers.items() if v == "v3"}, {t for t in ticks if t >= ACT})
        self.assertEqual({t for t, v in vers.items() if v == "v2"}, {t for t in ticks if t < ACT})
        self.assertEqual(vers, {t: prompts.current(t, self.root) for t in ticks})      # the halving reads what current() reads
        # XRP's sell 0.95 at minute 11 asked v3 before v3 was active: not B's, so not a disagreement, counted instead
        self.assertNotIn(0.95, [c for s, _, c, _, _ in _table(text) if s.startswith("XRP:")])
        self.assertIn("arm B read from prompt_b v2 9, v3 21 (rows asking another wording: 1)", _line(text, "XRP-USD"))
        self.assertIn("arm B read from prompt_b v2 19, v3 21 (rows asking another wording: 0)", _line(text, "SOL-USD"))
        # and v1's reading of the same rows (B = every row of the day) would have listed it
        day = [r for r in self.logs["XRP-USD"] if r["spec_sha"] == self.spec]
        joined = digest.outcomes.join(day)
        self.assertIn(0.95, [x["confidence"] for x in digest.disagreements(day, joined)])

    def test_a_pending_version_is_invisible_to_the_digest(self):
        # CURRENT names v4, activating after the day and after the nightly's minute: every tick of the day and "now"
        # ask v3; v4's words, name and sha appear nowhere, and a row that asked v4 is not arm B's
        v4 = dict(prompts.load("v3", self.root), version="v4", activation_tick="20261031T214000Z", replaces="v3",
                  action=dict(V3_ACTION, instructions="A pending wording nobody has asked yet for {BASE}."))
        root = prompts_root(self, current="v4", extra={"v4": v4})
        rows = self.logs["SOL-USD"]
        rows[40] = dict(rows[40], prompt_b="v4")
        _write(dash.store_paths("SOL-USD", self.data)[0], rows)
        text, _ = digest.build(DAY, self.data, root, NOW)
        self.assertNotIn("v4", text)
        self.assertNotIn("pending wording", text)
        self.assertNotIn(prompts.sha("v4", root), text)
        self.assertIn("## CURRENT action question (v3, the version arm B asks now)", text)
        self.assertIn("(rows asking another wording: 1)", _line(text, "SOL-USD"))
        self.assertEqual(set(digest.versions_at(sorted({r["tick_id"] for r in rows}), root).values()), {"v2", "v3"})

    def test_per_product_and_pooled_at_zero_and_the_verified_maker_and_taker(self):
        text, _ = self._build()
        fees = "paper PnL at 0 bps (direction) / 50 bps (venue maker) / 90 bps (venue taker): "
        for label in PRODUCTS3 + ("pooled over 3 products (sums)",):
            self.assertIn(fees, _line(text, label))
        # SOL is v1's fixture: B opens at 0, closes at 1, opens at 2, closes at 5 (four fills); C buys at 0 and holds
        sol = _line(text, "SOL-USD")
        self.assertTrue(sol.startswith("SOL-USD | ticks 41, answered 40, absence feed:1, outcomes joined 25/40 |"), sol)
        self.assertIn("B 4 trades", sol)
        self.assertIn("C 1 trades", sol)
        s = {p: digest.summarise(p, *self._parts(p)) for p in PRODUCTS3}
        c = s["SOL-USD"]["pnl"]
        self.assertAlmostEqual(c[0]["c"][1] - c[1]["c"][1], 50.0, places=9)             # one fill: the maker exactly
        self.assertAlmostEqual(c[0]["c"][1] - c[2]["c"][1], 90.0, places=9)             # and the taker exactly
        pool = digest.pooled(list(s.values()))
        for i in range(3):
            for arm in digest.ARMS:
                self.assertEqual(pool["pnl"][i][arm][0], sum(s[p]["pnl"][i][arm][0] for p in PRODUCTS3))
                self.assertAlmostEqual(pool["pnl"][i][arm][1], sum(s[p]["pnl"][i][arm][1] for p in PRODUCTS3), places=9)
        line = _line(text, "pooled over 3 products (sums)")
        self.assertTrue(line.startswith("pooled over 3 products (sums) | ticks 113, answered 110, absence feed:1 halt:1 jev:1,"), line)
        self.assertIn(f"B {pool['pnl'][0]['b'][0]} trades " + " / ".join(f"{pool['pnl'][i]['b'][1]:+.1f}" for i in range(3)), line)
        self.assertTrue(line.endswith("| B disagreements 7"), line)

    def _parts(self, p):
        day = [r for r in self.logs[p] if r["spec_sha"] == self.spec]
        joined = digest.outcomes.join(day)
        vers = digest.versions_at(sorted({r["tick_id"] for r in day}), self.root)
        return day, digest.b_rows(day, vers), joined, vers

    def test_the_disagreement_rows_over_the_products(self):
        text, _ = self._build()
        got = [(s.split(":")[0], ch, c, lab) for s, ch, c, _, lab in _table(text)]
        self.assertEqual(got, [("ETH", "sell", 0.99, "up"), ("SOL", "buy", 0.95, "down"), ("SOL", "sell", 0.90, "up"),
                               ("XRP", "buy", 0.90, "down"), ("ETH", "buy", 0.88, "down"), ("SOL", "sell", 0.86, "up"),
                               ("XRP", "buy", 0.86, "down")])
        self.assertIn("7 of 7 shown over the products, highest confidence first", text)

    def test_at_most_25_rows_most_confident_first(self):
        rows = [_row("SOL-USD", m, 100.0 - 0.1 * m, self.spec, ("buy", 0.9) if m < 40 else ("hold", 0.6)) for m in range(60)]
        _write(dash.store_paths("SOL-USD", self.data)[0], rows)
        text, _ = self._build()
        self.assertEqual(len(_table(text)), digest.DISAGREE_MAX)
        self.assertEqual(digest.DISAGREE_MAX, 25)
        self.assertIn("25 of 44 shown", text)                      # SOL's 40, ETH's 2 and XRP's 2
        self.assertEqual(_table(text)[0][:3], ("ETH: liquidity normal, flow organic, trend flat, vol calm", "sell", 0.99))

    def test_the_per_state_table_has_81_rows_per_product(self):
        text, _ = self._build()
        for p in PRODUCTS3:
            sec = text.split(f"## {p}: the 81 states that day")[1].split("\n## ")[0]
            rows = [l for l in sec.splitlines() if l.startswith(f"| {config.base(p)}: ")]
            self.assertEqual(len(rows), 81, p)
            self.assertEqual([r.split(" | ")[0][2:] for r in rows],
                             [state.state_string(a, config.base(p)) for a in state.all_states()])
        sol = state.state_string(ADJ["SOL-USD"], "SOL")
        # SOL: 40 live rows (the feed absence is not live); B buy 0, 2, 3, sell 1, 5, 30, hold the other 34; the 25 rows
        # with an outcome: 0..25 but 6
        table = text.split("## SOL-USD: the 81 states that day")[1]
        row = next(l for l in table.splitlines() if l.startswith(f"| {sol} |"))
        cells = [c.strip() for c in row.strip("|").split("|")]
        self.assertEqual(cells[1:3], ["40", "3 / 3 / 34"])
        rets = [digest.outcomes.join(self.logs["SOL-USD"])[r["tick_id"]] for r in self.logs["SOL-USD"] if r["mid"] is not None]
        rets = [o for o in rets if o["label"] is not None]
        self.assertEqual(len(rets), 25)
        self.assertEqual(cells[3], f"{sum(o['ret_h_bps'] for o in rets) / 25:+.1f}")
        up, down = sum(o["label"] == "up" for o in rets), sum(o["label"] == "down" for o in rets)
        self.assertEqual(cells[4], f"{100 * up / 25:.0f}% / {100 * down / 25:.0f}% / {100 * (25 - up - down) / 25:.0f}%")
        # XRP: the stale v3 row (minute 11) is seen but its choice is not B's; the foreign word is in no state; the halt
        # absence is not live
        xrp = state.state_string(ADJ["XRP-USD"], "XRP")
        row = next(l for l in text.split("## XRP-USD: the 81 states that day")[1].splitlines() if l.startswith(f"| {xrp} |"))
        self.assertEqual([c.strip() for c in row.strip("|").split("|")][1:3], ["29", "2 / 0 / 26"])
        self.assertIn("(1 live row(s) showed a word outside the alphabet: in no state above)", text)
        empty = state.state_string({"liq": "thin", "flow": "quiet", "trend": "dumping", "vol": "calm"}, "ETH")
        self.assertIn(f"| {empty} | 0 | - | - | - |", text)

    def test_the_current_question_is_shown_with_its_base_token(self):
        # v2's placeholder is the word SOL: shown as {BASE}, one wording for every product (PROMPT.md rule 9)
        text, _ = digest.build(DAY, self.data, prompts_root(self, current="v2", v3=False), NOW)
        q = json.loads(text.split("## CURRENT action question (v2, the version arm B asks now), verbatim, its product "
                                  "written {BASE}\n\n```json\n")[1].split("\n```")[0])
        v2 = prompts.load("v2", self.root)["action"]
        self.assertIn(" SOL", v2["instructions"])
        self.assertEqual(q["instructions"], v2["instructions"].replace("SOL", "{BASE}"))
        self.assertNotIn("SOL", json.dumps(q))
        text, _ = self._build()                                             # v3 carries {BASE} itself: shown as written
        self.assertIn(json.dumps(V3_ACTION, indent=2), text)
        self.assertIn(f"prompt_a v2 {prompts.sha('v2', self.root)}  \nprompt_b v2 {prompts.sha('v2', self.root)}  \n"
                      f"prompt_b v3 {prompts.sha('v3', self.root)}  \n", text)

    def test_never_features_never_the_log(self):
        text, _ = self._build()
        for s in ("features", "ret15_z", "1.7", "rv_ratio", "tick_id", "Bearer", "spec_sha\":", self.spec[:12]):
            self.assertNotIn(s, text)

    def test_a_parse_row_with_an_odd_answer_neither_crashes_nor_changes_the_digest(self):
        # cycle keeps the answers of a jev/parse row; a list or dict choice, or an integer confidence past a float's
        # range, lost v1 a night. Such a row is no disagreement and no B choice; the other bytes stay.
        base, _ = self._build()
        for bad in ({"choice": ["buy"], "confidence": 0.95}, {"choice": {"x": "buy"}, "confidence": 0.95},
                    {"choice": "buy", "confidence": 10 ** 400}):
            rows = [dict(r) for r in self.logs["SOL-USD"]]
            odd = dict(rows[8], absence="jev", columns={"a": None, "b": None, "d": None})
            odd["answers"] = dict(odd["answers"], b_action=dict(bad, probabilities={"buy": 1.0, "sell": 0.0, "hold": 0.0}))
            rows[8] = odd
            _write(dash.store_paths("SOL-USD", self.data)[0], rows)
            text, _ = self._build()
            self.assertEqual(_table(text), _table(base), bad)
        out = os.path.join(self.tmp, "d.md")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(digest.main(["--date", DAY.isoformat(), "--data", self.data, "--out", out, "--prompts", self.root]), 0)

    def test_other_days_are_excluded_but_join_across_midnight(self):
        rows = self.logs["SOL-USD"]
        late = datetime.datetime(2026, 10, 30, 23, 50, 0, tzinfo=datetime.timezone.utc)
        for i in range(20):                               # 23:50 .. 00:09 next day; the 23:50 buy resolves at 00:05
            d = late + datetime.timedelta(minutes=i)
            r = _row("SOL-USD", 0, 100.0 if i < 15 else 99.5, self.spec, ("buy", 0.93) if i == 0 else ("hold", 0.6))
            r["tick_id"], r["ts_rx"], r["prompt_b"] = d.strftime("%Y%m%dT%H%M00Z"), _iso(d), "v3"
            rows.append(r)
        _write(dash.store_paths("SOL-USD", self.data)[0], rows)
        text, n = self._build()
        self.assertEqual(n, 41 + 10 + 41 + 31)                             # the 10 next-day rows are not the day's
        self.assertIn(("SOL: liquidity deep, flow quiet, trend pumping, vol normal", "buy", 0.93, -50.1, "down"), _table(text))

    def test_main_writes_the_file_and_a_day_with_no_row_exits_4(self):
        out = os.path.join(self.tmp, "digest.md")
        with redirect_stdout(io.StringIO()) as buf:
            rc = digest.main(["--date", DAY.isoformat(), "--data", self.data, "--out", out, "--prompts", self.root])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), f"{out}\t113 ticks\n")
        with open(out, encoding="utf-8") as fh:
            self.assertIn("B disagreements 7", fh.read())
        empty = os.path.join(self.tmp, "empty")
        with redirect_stdout(io.StringIO()):
            rc = digest.main(["--date", DAY.isoformat(), "--data", empty, "--out", out, "--prompts", self.root])
        self.assertEqual(rc, digest.EXIT_EMPTY)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("SOL-USD | ticks 0, answered 0, absence none, outcomes joined 0/0", text)
        self.assertIn("| (none) | | | | |", text)
        # without --out the file goes beside the stores it read
        with redirect_stdout(io.StringIO()):
            digest.main(["--date", DAY.isoformat(), "--data", self.data, "--prompts", self.root])
        self.assertTrue(os.path.exists(os.path.join(self.data, f"digest-{DAY.isoformat()}.md")))

    def test_yesterday_is_the_previous_utc_day(self):
        self.assertEqual(digest.yesterday(datetime.datetime(2026, 10, 31, 0, 5, tzinfo=datetime.timezone.utc)), "2026-10-30")


class Constants(unittest.TestCase):
    def test_the_fees_are_the_verified_maker_and_taker(self):
        # PREREG-v2 §6: 50 = the venue's retail maker, 90 = its retail taker, read in-account 2026-09-27
        self.assertEqual([f for f, _ in digest.FEES], [0.0, 50.0, 90.0])
        self.assertEqual((digest.MAKER_BPS, digest.TAKER_BPS), (report.ERRATA_TIER["maker"], report.ERRATA_TIER["taker"]))
        self.assertLessEqual({f for f, _ in digest.FEES}, set(inference_v2.FEE_COLUMNS))

    def test_the_trees_spec_sha_is_the_one_the_loop_writes(self):
        self.assertEqual(digest.tree_spec_sha(), cycle.spec_sha())
        with mock.patch.object(config, "SPEC", os.path.join(REPO, "no-such-SPEC.md")):
            self.assertEqual(digest.tree_spec_sha(), cycle.spec_sha())

    def test_every_products_store_is_read_where_the_loop_writes_it(self):
        three_products(self)
        self.assertEqual(digest.logs(), [(p, config.store(p).decisions) for p in PRODUCTS3])
        self.assertEqual(digest.logs("/x/data"), [("SOL-USD", "/x/data/decisions.jsonl"), ("ETH-USD", "/x/data/ETH-USD/decisions.jsonl"),
                                                  ("XRP-USD", "/x/data/XRP-USD/decisions.jsonl")])

    def test_propose_passes_the_data_dir_holding_every_store(self):
        with open(os.path.join(REPO, "nightly", "propose.sh"), encoding="utf-8") as fh:
            code = [l for l in fh.read().splitlines() if not l.lstrip().startswith("#")]
        call = [i for i, l in enumerate(code) if "-m nightly.digest" in l]
        self.assertEqual(len(call), 1)
        self.assertIn('--data "$ROOT/data" --out "$DIGEST"', code[call[0] + 1])


def write_golden():
    """Regenerate tests/golden/digest-v2.md (by hand, after a change the author means): runs the golden test's setUp."""
    t = DigestV2("test_the_digest_of_the_fixture_day_is_the_golden_file")
    t.setUp()
    try:
        text, _ = t._build()
    finally:
        t.doCleanups()
    with open(GOLDEN, "w", encoding="utf-8") as fh:
        fh.write(text)


if __name__ == "__main__":
    unittest.main()

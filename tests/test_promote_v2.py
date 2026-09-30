"""bin/promote, v2 (PREREG-v2 §8, §10): the schedule (8 <= E <= 22, spacing >= 7, none in the shakedown, at most three;
run on day E - 1, refused when now >= activation - 600 s); T0_v2 read from PREREG-v2.md §12 and refused while blank;
the prereg-v2-seal tag; a second pending version refused; prompts/v<N>.json with activation_tick and replaces, then
the per-product tables copied from the proposal night's .table.json under an 81/81 refusal and a CURRENT-sha match,
then CURRENT; a candidate moving 0 of 81 states on every product refused; the base-token refusal; the reason line with
the states moved; and --table-only, which copies a version's own tables and sends nothing. Promote never sends.

Offline: the proposal night's .md and .table.json are made here by nightly.policy_table with loop.jev.ask mocked;
git is faked (subprocess.run in the loaded promote) except in PromoteUnfaked, which uses a throwaway repository;
config.PRODUCTS is exactly three stand-ins, config.PROMPTS and HALT point at temp dirs, PREREG-v2.md is a temp file."""
import datetime, hashlib, importlib.machinery, importlib.util, io, json, os, shutil, subprocess, sys, tempfile, time, unittest
from contextlib import redirect_stdout
from unittest import mock

from fixture_products import exactly
from fixture_prompts import pin_versions, version_doc
from loop import config, jev, prompts, state
from nightly import policy_table

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCTS3 = ("SOL-USD", "ETH-USD", "XRP-USD")
T0 = "20261024T220000Z"
T0_S = datetime.datetime(2026, 10, 24, 22, 0, tzinfo=datetime.timezone.utc).timestamp()
DAY = 86400
HOLDER = {"rationale": "hold everywhere", "instructions": "Decide whether to be long {BASE}; hold every state.",
          "criteria": {"buy": "never", "sell": "never", "hold": "always"}}
SAME = {"rationale": "the rule", "instructions": "Decide whether to be long {BASE} as the rule says.",
        "criteria": {"buy": "the trend is pumping", "sell": "the trend is dumping", "hold": "anything else"}}


class Reached(BaseException):
    pass


def _answer(choice, conf):
    return {"choice": choice, "probabilities": {"buy": 0.0, "sell": 0.0, "hold": 0.0, choice: conf}, "confidence": conf}


def _load_promote():
    path = os.path.join(REPO, "bin", "promote")
    spec = importlib.util.spec_from_file_location("promote", path, loader=importlib.machinery.SourceFileLoader("promote", path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def prereg(path, t0=T0):
    """A PREREG-v2.md whose §12 carries T0_v2 (underscores: blank)."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# PREREG-v2 (test)\n\n## 12. Fields filled after the draft tag\n\n"
                 f"T_first_v2: `________`   T0_v2: `{t0}`   Sealed by: `________`   on: `________`\n\n## 13. Tags\n")
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        exactly(self, PRODUCTS3)
        self.enterContext(mock.patch.object(sys, "path", list(sys.path)))   # bin/promote inserts REPO at import
        self.promote = _load_promote()
        self.root = pin_versions(self, "v2")
        self.props = os.path.join(self.tmp, "proposals")
        os.makedirs(self.props)
        self.halt = os.path.join(self.tmp, "HALT")
        self.enterContext(mock.patch.object(config, "HALT", self.halt))
        self.prereg = prereg(os.path.join(self.tmp, "PREREG-v2.md"))
        self.git = {"status": ("", 0), "rev-parse": ("abc\n", 0), "merge-base": ("", 0),   # clean, sealed, an ancestor,
                    "diff": ("", 0)}                                                       # nothing changed since a tag
        self.calls = []

        def git(argv, **kw):                                  # a key naming the whole command wins over its subcommand
            self.calls.append(argv)
            out, rc = self.git.get(" ".join(argv[1:])) or self.git[argv[1]]
            return subprocess.CompletedProcess(argv, rc, stdout=out if rc == 0 else "", stderr="" if rc == 0 else out)
        self.enterContext(mock.patch.object(self.promote.subprocess, "run", side_effect=git))
        self.attended = self.enterContext(mock.patch.object(self.promote, "_attended", return_value=True))
        self.rule = {s: rc for p in PRODUCTS3 for s, rc in policy_table.states(p)}
        self.sends = self.enterContext(mock.patch("loop.jev.ask", side_effect=Reached("promote sent something")))
        self.enterContext(mock.patch("urllib.request.urlopen", side_effect=Reached("urlopen was reached")))

    def night(self, cands, date="2026-10-31", fail=(), root=None, policy=None, now=None, model=None):
        """proposals/<date>.json and, as the nightly makes them, its .md and .table.json: CURRENT answers rule_c; a
        candidate whose rationale is "hold everywhere" holds on every state, any other answers rule_c too. `fail`: the
        states whose sends time out (never two in a row). `now`: the clock prompts.current() reads (default day 7).
        `model`: the Jev version the answers name (default config.MODEL)."""
        prop = os.path.join(self.props, f"{date}.json")
        with open(prop, "w", encoding="utf-8") as fh:
            json.dump({"candidates": cands}, fh)
        pol = {f"cand_{i}": (lambda rc: "hold") if c.get("rationale") == "hold everywhere" else (lambda rc: rc)
               for i, c in enumerate(cands)}
        pol.update(policy or {})

        def ask(s, qs, **kw):
            if s in fail:
                raise jev.JevError("timeout", "slow")
            rc = self.rule[s]
            return {"answers": {q: _answer(rc if q == "current" else pol[q](rc), 0.9) for q in qs},
                    "model": model or config.MODEL}
        md = os.path.join(self.props, f"{date}.md")
        with mock.patch("loop.jev.ask", side_effect=ask), redirect_stdout(io.StringIO()), \
                mock.patch.object(prompts.time, "time", return_value=day(7) if now is None else now):
            policy_table.main([prop, "--out", md, "--prompts", root or self.root])
        return prop

    def run_promote(self, *argv, now=None):
        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), mock.patch("sys.stderr", err):
            rc = self.promote.main(list(argv) + ["--prompts", self.root, "--prereg", self.prereg], now=now)
        return rc, buf.getvalue(), err.getvalue()

    def listing(self):
        return sorted(os.listdir(self.root))

    def untouched(self):
        self.assertEqual(self.listing(), ["CURRENT", "v1.json", "v2.json"])
        self.assertEqual(prompts.named(self.root), "v2")


def day(n, hours=1.0):
    """An epoch `hours` into T0-anchored day n."""
    return T0_S + DAY * (n - 1) + 3600 * hours


class Promote(Base):
    def test_writes_the_version_with_activation_and_replaces_then_its_tables_then_current(self):
        prop = self.night([HOLDER, SAME])
        order = []
        real_open, real_replace = open, os.replace

        def spy_replace(a, b):
            order.append(("replace", os.path.basename(b), sorted(os.listdir(self.root))))
            return real_replace(a, b)
        with mock.patch.object(self.promote.os, "replace", side_effect=spy_replace):
            rc, out, err = self.run_promote(prop, "0", "--reason", "holds on every trending state", now=day(7))
        self.assertEqual(rc, 0, err)
        doc = prompts.load("v3", self.root)
        self.assertEqual(doc["activation_tick"], "20261031T220000Z")               # T0_v2 + 86,400 x (8 - 1)
        self.assertEqual(doc["replaces"], "v2")
        self.assertEqual(list(doc)[:4], ["version", "frozen", "activation_tick", "replaces"])
        self.assertEqual(doc["action"], prompts.question({**HOLDER, "type": "choice"}, "choice"))
        v1 = prompts.load("v1", self.root)
        for q in prompts.CARRIED:
            self.assertEqual(doc[q], v1[q])
        # the tables: candidate 0's column per product, the new file's sha, read back as the loop reads them
        for p in PRODUCTS3:
            t = prompts.table("v3", p, self.root)
            self.assertEqual(set(t["answers"].values()), {"hold"})
            with open(prompts.table_path("v3", p, self.root), encoding="utf-8") as fh:
                raw = json.load(fh)
            self.assertEqual((raw["version"], raw["product"], raw["prompt_sha"], raw["model_answered"]),
                             ("v3", p, prompts.sha("v3", self.root), config.MODEL))
            self.assertEqual(list(raw["answers"]), [s for s, _ in policy_table.states(p)])
        # CURRENT last, and every table was on disk before it moved
        self.assertEqual([o[:2] for o in order], [("replace", "CURRENT")])
        self.assertEqual(order[0][2], sorted(["CURRENT", "CURRENT.tmp", "v1.json", "v2.json", "v3.json"]
                                             + [f"v3.table.{p}.json" for p in PRODUCTS3]))
        self.assertEqual(prompts.named(self.root), "v3")
        # pending until day 8: the loop, the digest and the table keep asking v2 until the activation tick
        tick = self.promote.minute_of(day(7))
        self.assertEqual(prompts.pending(tick, self.root), "v3")
        self.assertEqual(prompts.current(tick, self.root), "v2")
        self.assertEqual(prompts.current("20261031T215900Z", self.root), "v2")
        self.assertEqual(prompts.current("20261031T220000Z", self.root), "v3")
        # the commit line: the reason and the states moved per product
        moved = sum(rc != "hold" for _, rc in policy_table.states())
        self.assertIn(f"promote v3 (day 8, activates 2026-10-31T22:00Z) from {os.path.relpath(prop, REPO)} cand_0: "
                      f"holds on every trending state -- states moved: SOL-USD {moved}/81, ETH-USD {moved}/81, "
                      f"XRP-USD {moved}/81\n", out)
        self.assertIn("+++ v3.action", out)
        self.sends.assert_not_called()

    def test_t0_v2_blank_or_malformed_is_refused(self):
        prop = self.night([HOLDER])
        for t0, why in (("________", "T0_v2 is blank"), ("2026-10-24 22:00", "is not a tick_id")):
            prereg(self.prereg, t0)
            rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7))
            self.assertEqual(rc, 1, t0)
            self.assertIn(why, err)
            self.untouched()

    def test_the_schedule(self):
        # effective day E = the day promote runs + 1; 8 <= E <= 22; none before T0_v2 (the shakedown)
        prop = self.night([HOLDER])
        for now, why in ((T0_S - 3600, "before T0_v2"), (day(1), "effective day would be 2 < 8"),
                         (day(6, 23.9), "effective day would be 7 < 8"), (day(22), "effective day would be 23 > 22"),
                         (day(27), "effective day would be 28 > 22"),
                         (T0_S + 7 * DAY - 600, "within 600 s of the activation 20261031T220000Z (day 8): too late on day 7"),
                         (T0_S + 7 * DAY - 1, "within 600 s")):
            rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=now)
            self.assertEqual(rc, 1, why)
            self.assertIn(why, err)
            self.untouched()
        self.assertEqual(self.run_promote(prop, "0", "--reason", "r", now=T0_S + 7 * DAY - 601)[0], 0)   # 601 s before: in time
        self.assertEqual(prompts.load("v3", self.root)["activation_tick"], "20261031T220000Z")

    def test_the_last_effective_day_is_22(self):
        prop = self.night([HOLDER])
        rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(21, 12))
        self.assertEqual(rc, 0, err)
        self.assertEqual(prompts.load("v3", self.root)["activation_tick"], self.promote.tick_of(T0_S + 21 * DAY))

    def test_spacing_of_at_least_seven_days(self):
        prop = self.night([HOLDER])
        self.assertEqual(self.run_promote(prop, "0", "--reason", "first", now=day(7))[0], 0)       # E = 8, v3
        prop = self.night([HOLDER], date="2026-11-06", now=day(13))                              # scored against v3
        for n in (8, 12, 13):                                                                     # E = 9 .. 14
            rc, _, err = self.run_promote(prop, "0", "--reason", "second", now=day(n))
            self.assertEqual(rc, 1, n)
            self.assertIn(f"day {n + 1} is {n + 1 - 8} day(s) after v3's day 8: the spacing is at least 7", err)
        rc, _, err = self.run_promote(prop, "0", "--reason", "second", now=day(14))               # E = 15
        self.assertEqual(rc, 0, err)
        self.assertEqual((prompts.load("v4", self.root)["replaces"], prompts.load("v4", self.root)["activation_tick"]),
                         ("v3", self.promote.tick_of(T0_S + 14 * DAY)))

    def test_at_most_three_promotions(self):
        # promotions the schedule itself could not have made (days 8, 9, 10), so the count alone refuses a fourth
        docs = {}
        for i, (v, rep) in enumerate((("v3", "v2"), ("v4", "v3"), ("v5", "v4"))):
            docs[v] = version_doc(v, {"instructions": "Be long {BASE}.", "criteria": HOLDER["criteria"]},
                                  activation_tick=self.promote.tick_of(T0_S + (7 + i) * DAY), replaces=rep)
        self.root = pin_versions(self, "v5", docs)
        prop = self.night([HOLDER], now=day(20))
        rc, _, err = self.run_promote(prop, "0", "--reason", "fourth", now=day(20))
        self.assertEqual(rc, 1)
        self.assertIn("3 promotions already (v3, v4, v5): at most 3", err)
        self.assertEqual(self.promote.promotions(self.root, T0_S), {"v3": 8, "v4": 9, "v5": 10})

    def test_a_second_pending_version_is_refused(self):
        prop = self.night([HOLDER, {**HOLDER, "instructions": "Another holder for {BASE}."}])
        self.assertEqual(self.run_promote(prop, "0", "--reason", "first", now=day(7))[0], 0)
        rc, _, err = self.run_promote(prop, "1", "--reason", "second", now=day(7, 2))
        self.assertEqual(rc, 1)
        self.assertIn("v3 is pending (activates 20261031T220000Z): a second pending version is refused", err)
        self.assertFalse(os.path.exists(os.path.join(self.root, "v4.json")))
        self.assertEqual(prompts.named(self.root), "v3")

    def test_without_the_seal_tag_it_is_refused(self):
        prop = self.night([HOLDER])
        for key, res, why in (("rev-parse", ("", 1), "no annotated git tag prereg-v2-seal at or before HEAD"),
                              ("merge-base", ("", 1), "no annotated git tag prereg-v2-seal at or before HEAD"),
                              ("rev-parse", ("fatal: not a git repository", 128), "git rev-parse failed: fatal: not a git repository"),
                              ("merge-base", ("fatal: bad object", 128), "git merge-base failed: fatal: bad object")):
            saved = self.git[key]
            self.git[key] = res
            rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7))
            self.git[key] = saved
            self.assertEqual(rc, 1, (key, res))
            self.assertIn(why, err)
            self.untouched()
        self.assertEqual(self.promote.PREREG_TAG, "prereg-v2-seal")
        self.assertIn(["git", "rev-parse", "-q", "--verify", "refs/tags/prereg-v2-seal^{tag}"], self.calls)
        self.assertIn(["git", "merge-base", "--is-ancestor", "prereg-v2-seal", "HEAD"], self.calls)

    def test_a_candidate_that_moves_no_state_on_any_product_is_refused(self):
        prop = self.night([SAME])
        rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7))
        self.assertEqual(rc, 1)
        self.assertIn("cand_0 moves 0 of 81 states from v2's answer on every product: nothing to promote", err)
        self.untouched()

    def test_one_state_moved_on_one_product_is_a_promotion(self):
        eth = policy_table.states("ETH-USD")[5][0]
        prop = os.path.join(self.props, "2026-11-01.json")
        with open(prop, "w", encoding="utf-8") as fh:
            json.dump({"candidates": [SAME]}, fh)

        def ask(s, qs, **kw):
            rc = self.rule[s]
            other = "buy" if rc != "buy" else "sell"
            return {"answers": {"current": _answer(rc, 0.9), "cand_0": _answer(other if s == eth else rc, 0.9)},
                    "model": config.MODEL}
        with mock.patch("loop.jev.ask", side_effect=ask), redirect_stdout(io.StringIO()):
            policy_table.main([prop, "--out", prop[:-5] + ".md", "--prompts", self.root])
        rc, out, err = self.run_promote(prop, "0", "--reason", "one state", now=day(7))
        self.assertEqual(rc, 0, err)
        self.assertIn("states moved: SOL-USD 0/81, ETH-USD 1/81, XRP-USD 0/81", out)

    def test_the_column_is_copied_only_at_81_of_81_on_every_product(self):
        miss = policy_table.states("XRP-USD")[40][0]
        prop = self.night([HOLDER], fail=(miss,))
        rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7))
        self.assertEqual(rc, 1)
        self.assertIn("cand_0 answered 80 of 81 states on XRP-USD: a table is copied only at 81/81", err)
        self.untouched()
        # --fill asks the one state; then the promote goes through
        with mock.patch.object(policy_table, "_attended", return_value=True), \
                mock.patch("loop.jev.ask", side_effect=lambda s, qs, **kw: {"answers": {q: _answer("hold", 0.9) for q in qs},
                                                                          "model": config.MODEL}), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(policy_table.main(["--fill", policy_table.table_path(prop[:-5] + ".md")]), 0)
        self.assertEqual(self.run_promote(prop, "0", "--reason", "r", now=day(7))[0], 0)

    def test_the_tables_current_must_be_the_version_current_names(self):
        # scored while CURRENT was v1 (the table's CURRENT sha is v1.json's): refused now that CURRENT names v2
        v1root = pin_versions(self, "v1")
        prop = self.night([HOLDER], root=v1root)
        self.root = pin_versions(self, "v2")
        rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7))
        self.assertEqual(rc, 1)
        self.assertIn(f"the table's CURRENT sha {prompts.sha('v1', self.root)[:12]} is not v2.json's", err)
        self.untouched()

    def test_the_md_vouches_for_the_json_and_the_table(self):
        prop = self.night([HOLDER])
        md, tj = prop[:-5] + ".md", policy_table.table_path(prop[:-5] + ".md")
        with open(prop, "rb") as fh:
            raw = fh.read()
        with open(prop, "wb") as fh:                                                  # the json edited after its night
            fh.write(raw.replace(b"hold every state", b"hold each state"))
        rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7))
        self.assertEqual(rc, 1)
        self.assertIn("the file changed after its table was made", err)
        with open(prop, "wb") as fh:
            fh.write(raw)
        with open(tj, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["products"]["SOL-USD"]["rows"][0]["answers"]["cand_0"][0] = "buy"          # the table edited after it
        with open(tj, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7))
        self.assertEqual(rc, 1)
        self.assertIn("the table changed after it was made", err)
        os.unlink(md)
        rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7))
        self.assertEqual(rc, 1)
        self.assertIn("no policy table beside", err)
        self.untouched()

    def test_a_product_word_other_than_base_is_refused_before_anything_is_written(self):
        # policy_table refuses such a candidate too, so this table is made with its word check off: promote's own
        # base-token refusal (prompts.build for every product) must still hold
        for word, date in (("SOL", "2026-11-01"), ("ETH", "2026-11-02")):
            with mock.patch.object(policy_table.prompts, "check_words"):
                prop = self.night([{**HOLDER, "instructions": f"Decide whether to be long {word}."}], date=date)
            rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7))
            self.assertEqual(rc, 1, word)
            self.assertIn(f"product word '{word}' in v3", err)
            self.untouched()

    def test_the_reason_is_one_line(self):
        prop = self.night([HOLDER])
        for argv in ([], ["--reason", ""], ["--reason", "  "], ["--reason", "two\nlines"], ["--reason", "cr\r"]):
            rc, _, err = self.run_promote(prop, "0", *argv, now=day(7))
            self.assertEqual(rc, 1, argv)
            self.assertIn("--reason must be one non-empty line", err)
        self.untouched()

    def test_no_tty_and_a_dirty_tree_are_refused(self):
        prop = self.night([HOLDER])
        self.attended.return_value = False
        rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7))
        self.assertIn("no tty", err)
        self.attended.return_value = True
        self.git["status"] = (" M loop/x.py\n", 0)
        rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7))
        self.assertEqual(rc, 1)
        self.assertIn("dirty", err)
        self.git["status"] = ("fatal: index file corrupt", 128)
        rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7))
        self.assertIn("git status failed: fatal: index file corrupt", err)
        self.untouched()

    def test_a_bad_proposal_or_k_is_refused_in_one_line(self):
        prop = self.night([HOLDER])
        rc, _, err = self.run_promote(prop, "1", "--reason", "r", now=day(7))
        self.assertEqual(rc, 1)
        self.assertIn("no candidate 1 (has 1)", err)
        self.untouched()

    def test_numbering_goes_from_the_highest_file_and_an_existing_file_is_never_overwritten(self):
        shutil.copy(os.path.join(self.root, "v1.json"), os.path.join(self.root, "v6.json"))
        self.assertEqual(self.promote.next_version(self.root), "v7")
        os.unlink(os.path.join(self.root, "v6.json"))
        prop = self.night([HOLDER])
        real = self.promote.next_version

        def racing(root):
            v = real(root)
            with open(os.path.join(root, v + ".json"), "w", encoding="utf-8") as fh:
                fh.write("written by another promote\n")
            return v
        with mock.patch.object(self.promote, "next_version", side_effect=racing):
            rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7))
        self.assertEqual(rc, 1)
        self.assertIn("exists", err)
        with open(os.path.join(self.root, "v3.json"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "written by another promote\n")
        self.assertEqual(prompts.named(self.root), "v2")

    def test_current_is_replaced_whole_and_a_failed_switch_leaves_it(self):
        prop = self.night([HOLDER])
        with mock.patch.object(self.promote.os, "replace", side_effect=OSError("disk full")):
            rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7))
        self.assertEqual(rc, 1)
        self.assertIn("could not switch CURRENT (disk full): removed v3.json, v3.table.SOL-USD.json, "
                      "v3.table.ETH-USD.json, v3.table.XRP-USD.json; prompts/ is as it was, CURRENT still names v2", err)
        self.untouched()                                                        # CURRENT.tmp gone too
        self.assertEqual(self.run_promote(prop, "0", "--reason", "r", now=day(7, 2))[0], 0)   # the day's slot is kept

    def test_a_failed_promote_leaves_prompts_as_it_was_and_costs_no_slot(self):
        # the S4 refuter's defect 2: a version file left by a failed promote counted as a promotion, so the same day's
        # rerun was refused on spacing ("0 day(s) after") and the slot was lost
        prop = self.night([HOLDER])
        stray = os.path.join(self.root, "v3.table.ETH-USD.json")               # a table of the version to be written
        with open(stray, "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7))
        self.assertEqual(rc, 1)
        self.assertIn(f"{stray} exists with no v3.json beside it: a stray file, never overwritten; remove it and rerun", err)
        self.assertEqual(self.listing(), ["CURRENT", "v1.json", "v2.json", "v3.table.ETH-USD.json"])   # nothing written
        os.unlink(stray)
        real, wrote = self.promote._write_new, []

        def failing(path, doc):                                                 # the second table cannot be written
            if ".table." in path and wrote:
                raise OSError("disk full")
            real(path, doc)
            if ".table." in path:
                wrote.append(path)
        with mock.patch.object(self.promote, "_write_new", side_effect=failing):
            rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7, 2))
        self.assertEqual(rc, 1)
        self.assertIn("could not write v3's tables (disk full): removed v3.json, v3.table.SOL-USD.json; prompts/ is as it "
                      "was, CURRENT still names v2", err)
        self.untouched()
        self.assertEqual(self.promote.promotions(self.root, T0_S), {})
        rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7, 3))   # the same day, the same slot
        self.assertEqual(rc, 0, err)
        self.assertEqual((prompts.named(self.root), prompts.load("v3", self.root)["activation_tick"]),
                         ("v3", "20261031T220000Z"))

    def test_a_version_file_never_current_and_never_active_is_no_promotion(self):
        # a promote killed mid-write (power lost) can still leave vN.json, and a person may commit it to clean the tree:
        # a version CURRENT's `replaces` chain does not reach and whose activation has not come was never live and costs
        # no slot; one whose activation has passed may have been live (CURRENT edited by hand) and still counts
        orphan = version_doc("v3", {"instructions": "Be long {BASE}.", "criteria": HOLDER["criteria"]},
                             activation_tick=self.promote.tick_of(T0_S + 7 * DAY), replaces="v2")
        self.root = pin_versions(self, "v2", {"v3": orphan})
        self.assertEqual(self.promote.promotions(self.root, T0_S, day(7)), {})
        prop = self.night([HOLDER])
        rc, _, err = self.run_promote(prop, "0", "--reason", "r", now=day(7, 2))
        self.assertEqual(rc, 0, err)
        self.assertEqual((prompts.named(self.root), prompts.load("v4", self.root)["replaces"]), ("v4", "v2"))
        self.assertEqual(self.promote.promotions(self.root, T0_S, day(7, 3)), {"v4": 8})
        self.assertEqual(self.promote.promotions(self.root, T0_S, day(9)), {"v3": 8, "v4": 8})
        self.assertEqual(self.promote.promotions(self.root, T0_S), {"v3": 8, "v4": 8})   # no clock: every file counts

    def test_a_version_file_cut_short_is_removed(self):
        # _write_new creates the file (never over another's) and removes it if the write then fails
        path = os.path.join(self.tmp, "v9.json")
        real_open = open

        class Short:                                                            # the file is made, its write fails
            def __init__(self, fh):
                self.fh = fh

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.fh.close()

            def write(self, text):
                raise OSError("disk full")
        with mock.patch.object(self.promote, "open", create=True, side_effect=lambda *a, **k: Short(real_open(*a, **k))), \
                self.assertRaisesRegex(OSError, "disk full"):
            self.promote._write_new(path, {})
        self.assertFalse(os.path.exists(path))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("another promote's\n")
        with self.assertRaises(FileExistsError):
            self.promote._write_new(path, {})
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "another promote's\n")

    def test_the_note_carries_the_rationale_and_frozen_is_the_utc_date(self):
        prop = self.night([HOLDER])
        self.assertEqual(self.run_promote(prop, "0", "--reason", "r", now=day(7))[0], 0)
        doc = prompts.load("v3", self.root)
        self.assertTrue(doc["note"].endswith("candidate 0. Rationale: hold everywhere skip/up15/down15 carried from v1 unchanged."))
        self.assertEqual(doc["frozen"], "2026-10-30")

    def test_loading_promote_leaves_sys_path_as_it_was(self):
        # bin/promote does sys.path.insert(0, REPO) at import, and setUp loads it for every test: run two tests as the
        # runner would and the suite's sys.path is what it was
        before = list(sys.path)
        suite = unittest.TestSuite([Promote("test_the_reason_is_one_line"), Promote("test_promote_never_sends")])
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        self.assertEqual((result.testsRun, result.errors, result.failures), (2, [], []))
        self.assertEqual(sys.path, before)

    def test_promote_never_sends(self):
        # jev.ask and urlopen raise if reached (setUp); a static read: no send path is named in bin/promote
        with open(os.path.join(REPO, "bin", "promote"), encoding="utf-8") as fh:
            code = [l for l in fh.read().splitlines() if not l.lstrip().startswith("#")]
        for name in ("jev.ask", "urlopen", "run_night", "policy_table.run(", "policy_table.main", "policy_table.fill"):
            self.assertEqual([l for l in code if name in l], [], name)


SEAL_Q = "rev-parse -q --verify refs/tags/prereg-v2-seal"
DRAFT_Q = "rev-parse -q --verify refs/tags/prereg-v2-draft^{tag}"
DIFF_Q = "diff --quiet prereg-v2-draft HEAD -- prompts/v2.table.*.json"


class TableOnly(Base):
    """--table-only <proposal.json>: the CURRENT version's per-product tables, copied from a proposal night's
    .table.json (PREREG-v2 §8: v2's own tables before the draft tag); attended, sends nothing, no schedule, no seal.
    By default here no tag exists (before the draft tag)."""

    def setUp(self):
        super().setUp()
        self.git["rev-parse"] = ("", 1)

    def test_refused_once_the_seal_tag_exists(self):
        # §8 and §12 allow v2's tables before the draft tag and one rebuild at the switch, both before the seal (§13);
        # a tag of that name of any kind is the seal here, and a git that fails is a refusal, never "not sealed"
        prop = self.night([])
        for res, why in ((("abc\n", 0), "the tag prereg-v2-seal exists: v2's tables are built before the draft tag and "
                                        "rebuilt at most once at the switch, both before the seal"),
                         (("fatal: not a git repository", 128), "git rev-parse failed: fatal: not a git repository")):
            self.git[SEAL_Q] = res
            rc, _, err = self.run_promote("--table-only", prop)
            self.assertEqual(rc, 1, res)
            self.assertIn(why, err)
            self.untouched()
        self.assertIn(["git", "rev-parse", "-q", "--verify", "refs/tags/prereg-v2-seal"], self.calls)

    def test_after_the_draft_tag_one_rebuild_and_only_for_another_jev_version(self):
        # §8: "If a different Jev version answers at the switch, the tables are rebuilt once under the same rule"
        self.assertEqual(self.run_promote("--table-only", self.night([]))[0], 0)          # before the draft tag
        pinned = {p: prompts.table("v2", p, self.root)["sha"] for p in PRODUCTS3}
        self.git[DRAFT_Q] = ("abc\n", 0)                                                   # the draft tag, tables as pinned
        rc, _, err = self.run_promote("--table-only", self.night([], date="2026-10-24"))
        self.assertEqual(rc, 1)
        self.assertIn(f"the table was answered by {config.MODEL}, the Jev version the pinned v2 tables name: after "
                      "prereg-v2-draft they are rebuilt only when a different Jev version answers", err)
        self.assertEqual({p: prompts.table("v2", p, self.root)["sha"] for p in PRODUCTS3}, pinned)
        rc, out, err = self.run_promote("--table-only", self.night([], date="2026-10-25", model="jev-9.9.9"))
        self.assertEqual(rc, 0, err)                                                        # the one rebuild
        self.assertIn("REPLACED", out)
        self.assertIn("model answered jev-9.9.9", out)
        self.git[DIFF_Q] = ("", 1)                                                          # committed: changed since the tag
        rebuilt = {p: prompts.table("v2", p, self.root)["sha"] for p in PRODUCTS3}
        rc, _, err = self.run_promote("--table-only", self.night([], date="2026-10-26", model="jev-9.9.10"))
        self.assertEqual(rc, 1)
        self.assertIn("prompts/v2.table.*.json changed since prereg-v2-draft: v2's tables are rebuilt at most once "
                      "after the draft tag", err)
        self.assertEqual({p: prompts.table("v2", p, self.root)["sha"] for p in PRODUCTS3}, rebuilt)
        self.assertIn(["git", "diff", "--quiet", "prereg-v2-draft", "HEAD", "--", "prompts/v2.table.*.json"], self.calls)

    def test_copies_currents_column_for_every_product(self):
        prop = self.night([])                                                   # a proposal with no candidates
        prereg(self.prereg, "________")                                         # no T0_v2, no tag (setUp)
        rc, out, err = self.run_promote("--table-only", prop)
        self.assertEqual(rc, 0, err)
        for p in PRODUCTS3:
            t = prompts.table("v2", p, self.root)
            self.assertEqual(t["answers"], dict(policy_table.states(p)))       # CURRENT answered rule_c everywhere
            with open(prompts.table_path("v2", p, self.root), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["prompt_sha"], prompts.sha("v2", self.root))
        self.assertEqual(prompts.named(self.root), "v2")
        self.assertIn("Nothing sent, CURRENT untouched", out)
        self.assertNotIn("REPLACED", out)
        self.sends.assert_not_called()
        rc, out, _ = self.run_promote("--table-only", prop)                    # the once-only rebuild shows what it replaced
        self.assertEqual(rc, 0)
        self.assertIn("REPLACED", out)

    def test_refuses_a_table_whose_current_is_not_the_version_file(self):
        v1root = pin_versions(self, "v1")
        prop = self.night([], root=v1root)
        self.root = pin_versions(self, "v2")
        rc, _, err = self.run_promote("--table-only", prop)
        self.assertEqual(rc, 1)
        self.assertIn(f"the table's CURRENT is v1 sha {prompts.sha('v1', self.root)[:12]}, not v2.json's", err)
        self.untouched()

    def test_writes_v2s_tables_alone_whatever_current_names(self):
        # PREREG-v2 §8 and §10: --table-only "refuses unless the table's CURRENT sha equals prompts/v2.json's". A
        # promoted version's tables are its promotion's; --table-only never writes or replaces them, active or pending.
        v3 = version_doc("v3", {"instructions": "Be long {BASE}.", "criteria": HOLDER["criteria"]},
                         activation_tick=self.promote.tick_of(T0_S + 7 * DAY), replaces="v2")
        self.root = pin_versions(self, "v3", {"v3": v3})
        prop = self.night([], date="2026-11-02", now=day(9))                   # v3 active: the table's CURRENT is v3
        rc, _, err = self.run_promote("--table-only", prop)
        self.assertEqual(rc, 1)
        self.assertIn(f"the table's CURRENT is v3 sha {prompts.sha('v3', self.root)[:12]}, not v2.json's "
                      f"{prompts.sha('v2', self.root)[:12]}", err)
        self.assertEqual(self.listing(), ["CURRENT", "v1.json", "v2.json", "v3.json"])
        prop = self.night([], date="2026-10-30", now=day(7))                   # v3 pending: the table's CURRENT is v2
        rc, out, err = self.run_promote("--table-only", prop)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.listing(), sorted(["CURRENT", "v1.json", "v2.json", "v3.json"]
                                                + [f"v2.table.{p}.json" for p in PRODUCTS3]))
        self.assertEqual(prompts.named(self.root), "v3")
        self.assertEqual(self.promote.TABLE_ONLY_VERSION, "v2")

    def test_refuses_a_table_scored_with_candidates(self):
        # PREREG-v2 §8: v2's tables come "from a policy_table.py (v2) run on a proposal with no candidates (CURRENT = v2
        # only)", and the switch's rebuild follows "the same rule". A night with candidates answered CURRENT in requests
        # that also carried them, and --table-only copied it (2026-09-29 lens-4 review)
        prop = self.night([HOLDER, SAME], date="2026-10-29")
        rc, _, err = self.run_promote("--table-only", prop)
        self.assertEqual(rc, 1)
        self.assertIn("the table was scored with 2 candidate(s) (questions cand_0, cand_1, current): v2's own tables come"
                      " from a policy_table.py run on a proposal with no candidates", err)
        self.untouched()

    def test_refuses_short_of_81_of_81(self):
        prop = self.night([], fail=(policy_table.states("ETH-USD")[3][0],))
        rc, _, err = self.run_promote("--table-only", prop)
        self.assertEqual(rc, 1)
        self.assertIn("current answered 80 of 81 states on ETH-USD", err)
        self.untouched()

    def test_is_attended_on_a_clean_tree_and_takes_nothing_else(self):
        prop = self.night([])
        self.attended.return_value = False
        rc, _, err = self.run_promote("--table-only", prop)
        self.assertEqual(rc, 1)
        self.assertIn("no tty", err)
        self.attended.return_value = True
        self.git["status"] = ("?? stray\n", 0)
        rc, _, err = self.run_promote("--table-only", prop)
        self.assertIn("dirty", err)
        self.untouched()
        with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            self.promote.main(["--table-only", prop, "--reason", "r"])


class PromoteUnfaked(unittest.TestCase):
    """bin/promote with nothing patched: run by path, _attended() on a real terminal, and clean_tree() / sealed() on a
    real throwaway repository."""

    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.object(sys, "path", list(sys.path)))
        self.promote = _load_promote()

    def test_run_by_path_from_a_script_it_refuses_for_want_of_a_tty(self):
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}      # `from loop import` must resolve on its own
        root = os.path.join(self.tmp, "prompts")
        os.makedirs(root)
        r = subprocess.run([sys.executable, os.path.join(REPO, "bin", "promote"), os.path.join(self.tmp, "p.json"), "0",
                            "--reason", "r", "--prompts", root], cwd=self.tmp, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertTrue(r.stderr.startswith("promote: no tty"), r.stderr)
        self.assertEqual(os.listdir(root), [])
        self.assertTrue(os.access(os.path.join(REPO, "bin", "promote"), os.X_OK))

    def test_a_terminal_is_attended_and_anything_else_is_not(self):
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        with open(slave, closefd=True, encoding="utf-8") as tty, mock.patch.object(self.promote.sys, "stdin", tty):
            self.assertIs(self.promote._attended(), True)
        with open(os.devnull, encoding="utf-8") as fh, mock.patch.object(self.promote.sys, "stdin", fh):
            self.assertIs(self.promote._attended(), False)

    def test_clean_tree_and_sealed_read_a_real_repository(self):
        # sealed: the ANNOTATED tag prereg-v2-seal, an ancestor of HEAD; a lightweight tag of that name, a tag of another
        # name, or a tag on a side branch is not a seal
        if not shutil.which("git"):
            self.skipTest("git not on PATH")
        repo = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}))

        def git(*args):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        git("commit", "-q", "--allow-empty", "-m", "empty")
        self.assertIs(self.promote.clean_tree(repo), True)
        self.assertIs(self.promote.sealed(repo), False)
        git("tag", "prereg-v2-seal")                                          # lightweight
        self.assertIs(self.promote.sealed(repo), False)
        git("tag", "-d", "prereg-v2-seal")
        git("tag", "-a", "prereg-v2-draft", "-m", "d")
        self.assertIs(self.promote.sealed(repo), False)
        git("checkout", "-q", "-b", "side")
        git("commit", "-q", "--allow-empty", "-m", "side")
        git("tag", "-a", "prereg-v2-seal", "-m", "s")                         # on a commit HEAD will not contain
        git("checkout", "-q", "main")
        self.assertIs(self.promote.sealed(repo), False)
        git("merge", "-q", "--ff-only", "side")
        self.assertIs(self.promote.sealed(repo), True)
        with open(os.path.join(repo, "stray"), "w", encoding="utf-8") as fh:
            fh.write("x\n")
        self.assertIs(self.promote.clean_tree(repo), False)

    def test_tag_exists_and_tables_changed_since_read_a_real_repository(self):
        # --table-only's guards: any tag named prereg-v2-seal (a lightweight one too), the annotated draft tag, and a
        # committed change to prompts/v2.table.*.json between the draft tag and HEAD (the pathspec's glob as git reads it)
        if not shutil.which("git"):
            self.skipTest("git not on PATH")
        repo = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}))

        def git(*args):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

        def put(name, text):
            os.makedirs(os.path.join(repo, "prompts"), exist_ok=True)
            with open(os.path.join(repo, "prompts", name), "w", encoding="utf-8") as fh:
                fh.write(text)
            git("add", "-A")
            git("commit", "-q", "-m", name)
        git("init", "-q", "-b", "main")
        put("v2.table.SOL-USD.json", "a\n")
        self.assertIs(self.promote.tag_exists(repo, "prereg-v2-seal"), False)
        git("tag", "prereg-v2-seal")                                          # lightweight: still the seal's name
        self.assertIs(self.promote.tag_exists(repo, "prereg-v2-seal"), True)
        self.assertIs(self.promote.tag_exists(repo, "prereg-v2-seal", annotated=True), False)
        git("tag", "-a", "prereg-v2-draft", "-m", "d")
        self.assertIs(self.promote.tag_exists(repo, "prereg-v2-draft", annotated=True), True)
        put("v3.table.SOL-USD.json", "b\n")                                  # another version's table: not v2's
        put("v2.json", "c\n")
        self.assertIs(self.promote.tables_changed_since(repo, "prereg-v2-draft", "v2"), False)
        put("v2.table.SOL-USD.json", "d\n")
        self.assertIs(self.promote.tables_changed_since(repo, "prereg-v2-draft", "v2"), True)
        with self.assertRaisesRegex(RuntimeError, "git diff failed"):
            self.promote.tables_changed_since(repo, "no-such-tag", "v2")


if __name__ == "__main__":
    unittest.main()

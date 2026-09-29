"""loop.prompts, offline: the committed prompts/ tree plus temp copies of it.
Nothing here writes under prompts/ -- bin/promote is the only writer."""
import json, os, re, shutil, subprocess, sys, tempfile, unittest
from unittest import mock
from fixture_prompts import pin_v1
from loop import config, prompts, state
from test_nightly import _sh_env

ORDER = ["a_action", "b_action", "skip", "up15", "down15"]


def _copy(doc):
    return json.loads(json.dumps(doc))          # deep copy; tests mutate freely


class PromptsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.v1 = prompts.load("v1")

    def _save(self, name, doc, **dump):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, **dump)
            fh.write("\n")

    # --- CONTRACT §6: CURRENT = v1 gives identical a/b questions ---------------
    def test_current_is_v1_and_a_equals_b(self):
        root = pin_v1(self)                                          # a v1-only root, not the live prompts/
        self.assertEqual(prompts.current(root=root), "v1")
        cur = prompts.load(prompts.current(root=root), root)
        q = prompts.build(self.v1, cur, "SOL", v1=self.v1)
        self.assertEqual(q["a_action"], q["b_action"])
        self.assertEqual(prompts.sha("v1", root), prompts.sha(prompts.current(root=root), root))

    def test_live_current_loads_and_builds_whatever_it_is(self):
        # the repo's own prompts/: CURRENT names one version that exists and builds four wire
        # questions with v1's skip/up15/down15 byte-identical (bin/promote's promise), whatever N is
        cur = prompts.current()
        live = prompts.load(cur)
        q = prompts.build(prompts.load("v1"), live, "SOL", v1=self.v1)
        self.assertEqual(sorted(q), ["a_action", "b_action", "down15", "skip", "up15"])
        for k in prompts.CARRIED:
            self.assertEqual(live[k], self.v1[k])
        if cur == "v1":
            self.assertEqual(q["a_action"], q["b_action"])
        else:
            self.assertNotEqual(q["a_action"], q["b_action"])

    # --- CONTRACT §6: sha is stable ---------------------------------------------
    def test_sha_stable_across_reserialisation(self):
        shuffled = {k: self.v1[k] for k in reversed(list(self.v1))}      # other key order
        self._save("v1.json", shuffled, indent=4)                        # other indent, trailing newline
        self.assertEqual(prompts.sha("v1", root=self.tmp), prompts.sha("v1"))
        self.assertEqual(len(prompts.sha("v1")), 64)
        self.assertEqual(prompts.sha_of(self.v1), prompts.sha("v1"))
        changed = _copy(self.v1)
        changed["action"]["instructions"] += "."                         # one character
        self._save("v2.json", changed)
        self.assertNotEqual(prompts.sha("v2", root=self.tmp), prompts.sha("v1"))

    def test_a_non_ascii_prompt_loads_to_the_same_sha_under_a_c_locale(self):
        # v2.json holds an em dash. Read with the locale's encoding, a C locale refused it (and a
        # Latin-1 one would read other characters, so another sha): load() and current() read UTF-8.
        doc = _copy(self.v1)
        doc["version"] = "v9"
        doc["action"]["instructions"] = doc["action"]["instructions"].replace("SOL", "{BASE}") + " — and flat otherwise."
        with open(os.path.join(self.tmp, "v9.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
        with open(os.path.join(self.tmp, "CURRENT"), "w", encoding="utf-8") as fh:
            fh.write("v9\n")
        want = [prompts.current(root=self.tmp), prompts.sha("v9", self.tmp)]
        self.assertEqual(want[1], prompts.sha_of(doc))
        code = ("import locale, sys\nfrom loop import prompts\nprint(locale.getpreferredencoding(False))\n"
                "print(prompts.current(root=sys.argv[1]))\nprint(prompts.sha('v9', sys.argv[1]))\n")
        env = _sh_env(self, JEVLOOP_PROMPTS=self.tmp, LC_ALL="C", LANG="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0",
                      PYTHONIOENCODING="utf-8")                   # no key, no proxy, no token, a temp HOME: as the nightly's
        r = subprocess.run([sys.executable, "-c", code, self.tmp], cwd=config.REPO, env=env,
                           capture_output=True, text=True, timeout=60)
        enc = (r.stdout.splitlines() or [""])[0].lower().replace("-", "").replace("_", "")
        if enc in ("utf8", ""):
            self.skipTest(f"this interpreter reads UTF-8 under LC_ALL=C anyway ({r.stdout!r} {r.stderr[-200:]!r})")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[1:], want)

    # --- CONTRACT §2 wire shapes ------------------------------------------------
    def test_wire_shapes(self):
        q = prompts.build(self.v1, self.v1, "SOL", v1=self.v1)
        self.assertEqual(list(q), ORDER)
        for qid in ORDER:
            self.assertEqual(tuple(q[qid]), prompts.WIRE, qid)
        self.assertEqual(q["a_action"]["type"], "choice")
        self.assertEqual(list(q["a_action"]["criteria"]), ["buy", "sell", "hold"])
        for qid in ("skip", "up15", "down15"):
            self.assertEqual(q[qid]["type"], "noul", qid)
            self.assertEqual(list(q[qid]["criteria"]), ["yes", "no"], qid)
        json.dumps(q)                                                    # serialisable as-is

    def test_build_takes_action_from_current_and_the_rest_from_v1(self):
        cur = _copy(self.v1)
        cur["action"]["instructions"] = "Rewritten by the night shift."
        cur["skip"]["instructions"] = "This must NOT reach the wire."
        q = prompts.build(self.v1, cur, "SOL", v1=self.v1)
        self.assertEqual(q["b_action"]["instructions"], "Rewritten by the night shift.")
        self.assertEqual(q["a_action"]["instructions"], self.v1["action"]["instructions"])
        self.assertEqual(q["skip"]["instructions"], self.v1["skip"]["instructions"])
        self.assertNotEqual(q["a_action"], q["b_action"])

    def test_build_projects_extra_keys_away(self):
        cur = _copy(self.v1)
        cur["action"]["note"] = "candidate 2 of 3"
        cur["action"]["confidence"] = 0.9
        q = prompts.build(self.v1, cur, "SOL", v1=self.v1)
        self.assertEqual(tuple(q["b_action"]), prompts.WIRE)

    def test_build_rejects_true_false_noul_keys(self):
        v1 = _copy(self.v1)
        v1["skip"]["criteria"] = {"true": "x", "false": "y"}
        with self.assertRaises(prompts.PromptError):
            prompts.build(self.v1, self.v1, "SOL", v1=v1)

    def test_build_rejects_wrong_choice_keys_and_types(self):
        cur = _copy(self.v1)
        cur["action"]["criteria"] = {"buy": "b", "sell": "s"}           # hold missing
        with self.assertRaises(prompts.PromptError):
            prompts.build(self.v1, cur, "SOL", v1=self.v1)
        cur = _copy(self.v1)
        cur["action"]["criteria"]["long"] = "extra"                     # a fourth key
        with self.assertRaises(prompts.PromptError):
            prompts.build(self.v1, cur, "SOL", v1=self.v1)
        cur = _copy(self.v1)
        cur["action"]["type"] = "noul"                                  # a choice slot cannot be a noul
        with self.assertRaises(prompts.PromptError):
            prompts.build(self.v1, cur, "SOL", v1=self.v1)
        cur = _copy(self.v1)
        del cur["action"]
        with self.assertRaises(prompts.PromptError):
            prompts.build(self.v1, cur, "SOL", v1=self.v1)
        cur = _copy(self.v1)
        cur["action"]["instructions"] = "   "
        with self.assertRaises(prompts.PromptError):
            prompts.build(self.v1, cur, "SOL", v1=self.v1)
        cur = _copy(self.v1)
        cur["action"]["criteria"]["buy"] = ""
        with self.assertRaises(prompts.PromptError):
            prompts.build(self.v1, cur, "SOL", v1=self.v1)

    # --- names and files ---------------------------------------------------------
    def test_load_and_current_reject_bad_names(self):
        for bad in ("../v1", "v1.json", "CURRENT", "", None, "v", "1"):
            with self.assertRaises(prompts.PromptError, msg=repr(bad)):
                prompts.load(bad)
        with self.assertRaises(prompts.PromptError):
            prompts.load("v999", root=self.tmp)                          # absent file
        with open(os.path.join(self.tmp, "v3.json"), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        with self.assertRaises(prompts.PromptError):
            prompts.load("v3", root=self.tmp)
        with open(os.path.join(self.tmp, "CURRENT"), "w", encoding="utf-8") as fh:
            fh.write("v1\nv2\n")
        with self.assertRaises(prompts.PromptError):
            prompts.current(root=self.tmp)
        with self.assertRaises(prompts.PromptError):
            prompts.named(root=self.tmp)
        with open(os.path.join(self.tmp, "CURRENT"), "w", encoding="utf-8") as fh:
            fh.write("\n  v7  \n\n")                                     # blank lines tolerated
        self.assertEqual(prompts.named(root=self.tmp), "v7")
        with self.assertRaises(prompts.PromptError):
            prompts.current(root=self.tmp)                               # CURRENT names a file that is not there
        self._save("v7.json", self.v1)                                   # v1's text names SOL: refused in a v7
        with self.assertRaises(prompts.PromptError):
            prompts.current(root=self.tmp)
        v7 = _copy(self.v1)
        v7["action"]["instructions"] = v7["action"]["instructions"].replace("SOL", "{BASE}")
        self._save("v7.json", v7)
        self.assertEqual(prompts.current(root=self.tmp), "v7")
        with self.assertRaises(prompts.PromptError):
            prompts.current(root=os.path.join(self.tmp, "nowhere"))

    def test_committed_v1_is_frozen_and_wire_clean(self):
        self.assertEqual(self.v1["version"], "v1")
        self.assertEqual(sorted(self.v1), ["action", "down15", "frozen", "note", "skip", "up15", "version"])
        q = prompts.build(self.v1, self.v1, "SOL", v1=self.v1)                              # the committed file passes its own gate
        self.assertNotIn("\t", json.dumps(q))                            # a tab would split a sends.tsv column
        self.assertNotIn("\n", json.dumps(q))


def _v3(text="Decide whether to be long {BASE} for the next stretch.", **extra):
    """A v3 document as bin/promote writes one: v1's nouls, an action naming the base by {BASE}."""
    v1 = prompts.load("v1")
    doc = {"version": "v3", "frozen": "2026-11-01", "note": "Promoted from SOL's night (a note may name SOL).",
           "action": {"type": "choice", "instructions": text,
                      "criteria": {"buy": "the trend is pumping and {BASE} liquidity is not thin",
                                   "sell": "the trend is dumping", "hold": "anything else"}},
           **{q: v1[q] for q in prompts.CARRIED}}
    doc.update(extra)
    return doc


class BaseToken(unittest.TestCase):
    """PREREG-v2 §1: v2.json's SOL is the base placeholder; v3+ use {BASE}; any other product word is refused."""

    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.v1, self.v2 = prompts.load("v1"), prompts.load("v2")

    def _save(self, name, doc):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)

    def test_each_products_rendered_a_differs_from_sols_only_in_the_base_token(self):
        sol = prompts.build(self.v2, self.v2, "SOL", v1=self.v1)["a_action"]
        self.assertEqual(sol, prompts.question(self.v2["action"], "choice"))       # SOL-USD: byte-identical to v1's A request
        self.assertIn("SOL", sol["instructions"])
        bases = sorted({config.base(p) for p in config.PRODUCTS + config.PROBE_CANDIDATES} - {"SOL"})
        self.assertGreaterEqual(len(bases), 2)
        split = lambda q: re.split(r"(\W+)", json.dumps(q, ensure_ascii=False))
        for b in bases:
            with self.subTest(base=b):
                got = prompts.build(self.v2, self.v2, b, v1=self.v1)["a_action"]
                s, g = split(sol), split(got)
                self.assertEqual(len(s), len(g))
                diff = {(x, y) for x, y in zip(s, g) if x != y}
                self.assertEqual(diff, {("SOL", b)})
                self.assertEqual(got["instructions"].count(b), sol["instructions"].count("SOL"))

    def test_a_v3_wording_renders_the_literal_base(self):
        doc = _v3()
        for b in ("SOL", "ETH"):
            q = prompts.build(self.v2, doc, b, v1=self.v1)["b_action"]
            self.assertEqual(q["instructions"], f"Decide whether to be long {b} for the next stretch.")
            self.assertEqual(q["criteria"]["buy"], f"the trend is pumping and {b} liquidity is not thin")
            self.assertNotIn("{BASE}", json.dumps(q))

    def test_the_nouls_come_from_v1_and_are_never_rendered(self):
        fa, cur = json.loads(json.dumps(self.v2)), _v3()
        fa["skip"]["instructions"] = cur["skip"]["instructions"] = "not v1's"
        q = prompts.build(fa, cur, "ETH", v1=self.v1)
        for k in prompts.CARRIED:
            self.assertEqual(q[k], prompts.question(self.v1[k], "noul"))
        with mock.patch.object(config, "PROMPTS", pin_v1(self)):                  # v1 read from the root when not passed
            self.assertEqual(prompts.build(fa, cur, "ETH")["skip"], prompts.question(self.v1["skip"], "noul"))

    def test_another_product_word_is_refused_by_the_loader_and_by_build(self):
        cases = []
        eth_in_v2 = json.loads(json.dumps(self.v2))
        eth_in_v2["action"]["criteria"]["sell"] += " on ETH"
        cases.append(("v2", eth_in_v2))
        token_in_v2 = json.loads(json.dumps(self.v2))
        token_in_v2["action"]["instructions"] = token_in_v2["action"]["instructions"].replace("SOL", "{BASE}")
        cases.append(("v2", token_in_v2))
        cases.append(("v3", _v3("Decide whether to be long SOL.")))
        cases.append(("v3", _v3("Be long {BASE} when DOGE pumps.")))
        sol_noul = _v3()
        sol_noul["up15"] = {**sol_noul["up15"], "instructions": "SOL will be higher."}
        cases.append(("v3", sol_noul))
        for name, doc in cases:
            with self.subTest(name=name, doc=doc["action"]["instructions"][:40]):
                self._save(name + ".json", doc)
                with self.assertRaises(prompts.PromptError):
                    prompts.load(name, self.tmp)
                with self.assertRaises(prompts.PromptError):
                    prompts.build(self.v2, doc, "SOL", v1=self.v1)

    def test_what_is_not_a_product_word_passes(self):
        doc = _v3("Be long {BASE} on a solid book; link the size to depth; Sol is not a base word.")
        self._save("v3.json", doc)
        self.assertEqual(prompts.load("v3", self.tmp), doc)                        # the note names SOL: not wire text
        prompts.build(self.v2, doc, "SOL", v1=self.v1)

    def test_the_product_words_are_every_products_base_and_every_candidates(self):
        self.assertEqual(prompts.product_words(), ["ADA", "AVAX", "DOGE", "ETH", "LINK", "SOL", "XRP"])
        with mock.patch.object(config, "PRODUCTS", ("SOL-USD", "FOO-USD")):
            self.assertIn("FOO", prompts.product_words())
            with self.assertRaises(prompts.PromptError):
                prompts.build(self.v2, _v3("Be long {BASE}, not FOO."), "SOL", v1=self.v1)

    def test_build_refuses_a_bad_base_or_a_document_without_a_version(self):
        for bad in ("sol", "S0L", "", None, "SOL-USD", "{BASE}"):
            with self.assertRaises(prompts.PromptError, msg=repr(bad)):
                prompts.build(self.v2, self.v2, bad, v1=self.v1)
        for v in (None, "2", "v", "../v2"):
            doc = json.loads(json.dumps(self.v2))
            doc["version"] = v
            with self.assertRaises(prompts.PromptError, msg=repr(v)):
                prompts.build(self.v2, doc, "SOL", v1=self.v1)
        self.assertEqual(prompts.placeholder("v1"), "SOL")
        self.assertEqual(prompts.placeholder("v2"), "SOL")
        self.assertEqual(prompts.placeholder("v3"), "{BASE}")
        self.assertEqual(prompts.placeholder("v12"), "{BASE}")


class Activation(unittest.TestCase):
    """PREREG-v2 §8: current(tick_id) follows `replaces` while tick_id < activation_tick; one pending version."""
    ACT3, ACT4 = "20261101T214000Z", "20261108T214000Z"

    def setUp(self):
        self.root = self.enterContext(tempfile.TemporaryDirectory())
        for v in ("v1", "v2"):
            shutil.copy(os.path.join(config.REPO, "prompts", v + ".json"), self.root)
        self._save("v3", _v3(activation_tick=self.ACT3, replaces="v2"))
        self._current("v3")

    def _save(self, name, doc):
        with open(os.path.join(self.root, name + ".json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

    def _current(self, name):
        with open(os.path.join(self.root, "CURRENT"), "w", encoding="utf-8") as fh:
            fh.write(name + "\n")

    def test_a_pending_version_answers_only_from_its_activation_tick(self):
        cur = lambda t: prompts.current(t, self.root)
        self.assertEqual(cur("20261101T213900Z"), "v2")
        self.assertEqual(cur("20261101T214000Z"), "v3")
        self.assertEqual(cur("20261120T000000Z"), "v3")
        self.assertEqual(prompts.named(self.root), "v3")
        self.assertEqual(prompts.pending("20261101T213900Z", self.root), "v3")
        self.assertIsNone(prompts.pending("20261101T214000Z", self.root))
        self._current("v2")
        self.assertEqual(cur("20261101T213900Z"), "v2")
        self.assertIsNone(prompts.pending("20261101T213900Z", self.root))

    def test_no_tick_means_this_minute(self):
        with mock.patch("time.time", return_value=1793569140.0):                  # 2026-11-01T21:39:00Z
            self.assertEqual(prompts.current(root=self.root), "v2")
            self.assertEqual(prompts.pending(root=self.root), "v3")
        with mock.patch("time.time", return_value=1793569200.0):                  # 21:40:00Z
            self.assertEqual(prompts.current(root=self.root), "v3")
            self.assertIsNone(prompts.pending(root=self.root))

    def test_a_second_pending_version_is_refused(self):
        self._save("v4", _v3(version="v4", activation_tick=self.ACT4, replaces="v3"))
        self._current("v4")
        self.assertEqual(prompts.current("20261105T000000Z", self.root), "v3")     # v3 active, v4 pending: one
        self.assertEqual(prompts.pending("20261105T000000Z", self.root), "v4")
        self.assertEqual(prompts.current(self.ACT4, self.root), "v4")
        for t in ("20261031T000000Z", "20261101T213900Z"):                          # before v3 too: two pending
            with self.assertRaises(prompts.PromptError, msg=t):
                prompts.current(t, self.root)
            with self.assertRaises(prompts.PromptError, msg=t):
                prompts.pending(t, self.root)
        self._save("v4", _v3(version="v4", activation_tick="20261101T214000Z", replaces="v3"))   # no later than v3's
        with self.assertRaises(prompts.PromptError):
            prompts.current("20261101T213900Z", self.root)

    def test_a_malformed_activation_is_refused(self):
        for extra in ({"activation_tick": self.ACT3}, {"replaces": "v2"},
                      {"activation_tick": "2026-11-01T21:40Z", "replaces": "v2"},
                      {"activation_tick": "20261101T214030Z", "replaces": "v2"},
                      {"activation_tick": 1793655600, "replaces": "v2"},
                      {"activation_tick": self.ACT3, "replaces": "v3"},
                      {"activation_tick": self.ACT3, "replaces": "../v2"},
                      {"activation_tick": self.ACT3, "replaces": "v9"}):                # names no file
            with self.subTest(extra=extra):
                self._save("v3", _v3(**extra))
                with self.assertRaises(prompts.PromptError):
                    prompts.current("20261101T213900Z", self.root)

    def test_the_tick_is_a_row_tick_id_and_a_root_goes_by_keyword(self):
        for bad in (self.root, 1793655600, "2026-11-01", "20261101T2140Z"):
            with self.assertRaises(prompts.PromptError, msg=repr(bad)):
                prompts.current(bad)

    def test_v1_and_v2_carry_no_activation(self):
        for v in ("v1", "v2"):
            self.assertIsNone(prompts.activation(prompts.load(v), v))


class Tables(unittest.TestCase):
    """prompts/<version>.table.<product>.json: arm D's lookup (PREREG-v2 §1, §8)."""

    def setUp(self):
        self.root = self.enterContext(tempfile.TemporaryDirectory())
        shutil.copy(os.path.join(config.REPO, "prompts", "v2.json"), self.root)

    def _table(self, product="SOL-USD", base=None, **over):
        b = base or config.base(product)
        doc = {"version": "v2", "product": product, "prompt_sha": prompts.sha("v2", self.root),
               "model_answered": "jev-1.13.0",
               "answers": {state.state_string(a, b): state.rule_c(a) for a in state.all_states()}}
        doc.update(over)
        with open(os.path.join(self.root, f"v2.table.{product}.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1)
        return doc

    def test_absent_is_none_and_a_good_table_is_its_answers_and_canonical_sha(self):
        self.assertIsNone(prompts.table("v2", "SOL-USD", self.root))
        doc = self._table()
        got = prompts.table("v2", "SOL-USD", self.root)
        self.assertEqual(got["answers"], doc["answers"])
        self.assertEqual(got["sha"], prompts.sha_of(doc))
        self.assertEqual(len(got["answers"]), 81)
        self.assertEqual(prompts.table_path("v2", "SOL-USD", self.root), os.path.join(self.root, "v2.table.SOL-USD.json"))

    def test_another_product_reads_its_own_file_and_its_own_base(self):
        with mock.patch.object(config, "PRODUCTS", ("SOL-USD", "ETH-USD")):
            self._table("ETH-USD")
            got = prompts.table("v2", "ETH-USD", self.root)
            self.assertTrue(all(s.startswith("ETH: liquidity ") for s in got["answers"]))
            self.assertIsNone(prompts.table("v2", "SOL-USD", self.root))
            self._table("ETH-USD", base="SOL")                                      # SOL's strings in ETH's file
            with self.assertRaises(prompts.PromptError):
                prompts.table("v2", "ETH-USD", self.root)

    def test_every_other_shape_is_refused(self):
        full = {state.state_string(a): state.rule_c(a) for a in state.all_states()}
        first = next(iter(full))
        bad = [{"version": "v1"}, {"product": "ETH-USD"}, {"prompt_sha": "0" * 64}, {"prompt_sha": None},
               {"answers": dict(list(full.items())[:80])}, {"answers": {**full, "SOL: extra": "buy"}},
               {"answers": {**full, first: "long"}}, {"answers": {**full, first: None}}, {"answers": list(full)}]
        for over in bad:
            with self.subTest(over=str(over)[:60]):
                self._table(**over)
                with self.assertRaises(prompts.PromptError):
                    prompts.table("v2", "SOL-USD", self.root)
        with open(os.path.join(self.root, "v2.table.SOL-USD.json"), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        with self.assertRaises(prompts.PromptError):
            prompts.table("v2", "SOL-USD", self.root)
        for version, product in (("v2", "ETH-USD"), ("../v2", "SOL-USD"), ("v2", "../SOL-USD")):
            with self.assertRaises(prompts.PromptError):
                prompts.table(version, product, self.root)

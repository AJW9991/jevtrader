"""loop.prompts, offline: the committed prompts/ tree plus temp copies of it.
Nothing here writes under prompts/ -- bin/promote is the only writer."""
import json, os, subprocess, sys, tempfile, unittest
from fixture_prompts import pin_v1
from loop import config, prompts
from test_nightly import _sh_env

ORDER = ["a_action", "b_action", "skip", "up15", "down15"]


def _copy(doc):
    return json.loads(json.dumps(doc))          # deep copy; tests mutate freely


class PromptsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.v1 = prompts.load("v1")

    def _save(self, name, doc, **dump):
        with open(os.path.join(self.tmp, name), "w") as fh:
            json.dump(doc, fh, **dump)
            fh.write("\n")

    # --- CONTRACT §6: CURRENT = v1 gives identical a/b questions ---------------
    def test_current_is_v1_and_a_equals_b(self):
        root = pin_v1(self)                                          # a v1-only root, not the live prompts/
        self.assertEqual(prompts.current(root), "v1")
        cur = prompts.load(prompts.current(root), root)
        q = prompts.build(self.v1, cur)
        self.assertEqual(q["a_action"], q["b_action"])
        self.assertEqual(prompts.sha("v1", root), prompts.sha(prompts.current(root), root))

    def test_live_current_loads_and_builds_whatever_it_is(self):
        # the repo's own prompts/: CURRENT names one version that exists and builds four wire
        # questions with v1's skip/up15/down15 byte-identical (bin/promote's promise), whatever N is
        cur = prompts.current()
        live = prompts.load(cur)
        q = prompts.build(prompts.load("v1"), live)
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
        doc["action"]["instructions"] += " — and flat otherwise."
        with open(os.path.join(self.tmp, "v9.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
        with open(os.path.join(self.tmp, "CURRENT"), "w", encoding="utf-8") as fh:
            fh.write("v9\n")
        want = [prompts.current(self.tmp), prompts.sha("v9", self.tmp)]
        self.assertEqual(want[1], prompts.sha_of(doc))
        code = ("import locale, sys\nfrom loop import prompts\nprint(locale.getpreferredencoding(False))\n"
                "print(prompts.current(sys.argv[1]))\nprint(prompts.sha('v9', sys.argv[1]))\n")
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
        q = prompts.build(self.v1, self.v1)
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
        q = prompts.build(self.v1, cur)
        self.assertEqual(q["b_action"]["instructions"], "Rewritten by the night shift.")
        self.assertEqual(q["a_action"]["instructions"], self.v1["action"]["instructions"])
        self.assertEqual(q["skip"]["instructions"], self.v1["skip"]["instructions"])
        self.assertNotEqual(q["a_action"], q["b_action"])

    def test_build_projects_extra_keys_away(self):
        cur = _copy(self.v1)
        cur["action"]["note"] = "candidate 2 of 3"
        cur["action"]["confidence"] = 0.9
        q = prompts.build(self.v1, cur)
        self.assertEqual(tuple(q["b_action"]), prompts.WIRE)

    def test_build_rejects_true_false_noul_keys(self):
        v1 = _copy(self.v1)
        v1["skip"]["criteria"] = {"true": "x", "false": "y"}
        with self.assertRaises(prompts.PromptError):
            prompts.build(v1, self.v1)

    def test_build_rejects_wrong_choice_keys_and_types(self):
        cur = _copy(self.v1)
        cur["action"]["criteria"] = {"buy": "b", "sell": "s"}           # hold missing
        with self.assertRaises(prompts.PromptError):
            prompts.build(self.v1, cur)
        cur = _copy(self.v1)
        cur["action"]["criteria"]["long"] = "extra"                     # a fourth key
        with self.assertRaises(prompts.PromptError):
            prompts.build(self.v1, cur)
        cur = _copy(self.v1)
        cur["action"]["type"] = "noul"                                  # a choice slot cannot be a noul
        with self.assertRaises(prompts.PromptError):
            prompts.build(self.v1, cur)
        cur = _copy(self.v1)
        del cur["action"]
        with self.assertRaises(prompts.PromptError):
            prompts.build(self.v1, cur)
        cur = _copy(self.v1)
        cur["action"]["instructions"] = "   "
        with self.assertRaises(prompts.PromptError):
            prompts.build(self.v1, cur)
        cur = _copy(self.v1)
        cur["action"]["criteria"]["buy"] = ""
        with self.assertRaises(prompts.PromptError):
            prompts.build(self.v1, cur)

    # --- names and files ---------------------------------------------------------
    def test_load_and_current_reject_bad_names(self):
        for bad in ("../v1", "v1.json", "CURRENT", "", None, "v", "1"):
            with self.assertRaises(prompts.PromptError, msg=repr(bad)):
                prompts.load(bad)
        with self.assertRaises(prompts.PromptError):
            prompts.load("v999", root=self.tmp)                          # absent file
        with open(os.path.join(self.tmp, "v3.json"), "w") as fh:
            fh.write("{not json")
        with self.assertRaises(prompts.PromptError):
            prompts.load("v3", root=self.tmp)
        with open(os.path.join(self.tmp, "CURRENT"), "w") as fh:
            fh.write("v1\nv2\n")
        with self.assertRaises(prompts.PromptError):
            prompts.current(root=self.tmp)
        with open(os.path.join(self.tmp, "CURRENT"), "w") as fh:
            fh.write("\n  v7  \n\n")                                     # blank lines tolerated
        self.assertEqual(prompts.current(root=self.tmp), "v7")
        with self.assertRaises(prompts.PromptError):
            prompts.current(root=os.path.join(self.tmp, "nowhere"))

    def test_committed_v1_is_frozen_and_wire_clean(self):
        self.assertEqual(self.v1["version"], "v1")
        self.assertEqual(sorted(self.v1), ["action", "down15", "frozen", "note", "skip", "up15", "version"])
        q = prompts.build(self.v1, self.v1)                              # the committed file passes its own gate
        self.assertNotIn("\t", json.dumps(q))                            # a tab would split a sends.tsv column
        self.assertNotIn("\n", json.dumps(q))

"""loop.prompts, offline: the committed prompts/ tree plus temp copies of it.
Nothing here writes under prompts/ -- bin/promote is the only writer."""
import json, os, tempfile, unittest
from loop import config, prompts

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
        self.assertEqual(prompts.current(), "v1")
        cur = prompts.load(prompts.current())
        q = prompts.build(self.v1, cur)
        self.assertEqual(q["a_action"], q["b_action"])
        self.assertEqual(prompts.sha("v1"), prompts.sha(prompts.current()))

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

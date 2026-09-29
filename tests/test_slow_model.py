"""nightly/slow_model.py: the slow model's id, pinned in ONE place (PREREG-v2 §8), and PREREG-v2.md §8's line naming it
agree: both blank (underscores there, "" here) until §8 is filled before the draft tag, then the same id and night.
§8's line is read in both forms it has had: the blank one, **id `________` (night `________`).**, and the one main
filled on 2026-09-29, **id `claude-sonnet-5` (night 2026-09-29 08:30Z; the log's line reads `...`).**, whose night is
bare and ends at the `;` (the S6 refuter's defect 1: this test required the night in backticks, so after STEPS §10.1's
merge of main no value here could pass). propose.sh passes it as `--model` and reads it from nowhere else. The live
night's refusal of a blank or malformed id is driven end to end in tests/test_nightly.py (LiveBranch)."""
import os, re, unittest

from nightly import answered_model, slow_model

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# §8 wraps it across lines; the night in backticks (the blank form) or bare up to the `;` or `)` that ends it
LINE = re.compile(r"\*\*id\s+`([^`\n]*)`\s+\(night\s+(?:`([^`\n]*)`|([^`;()]+?))\s*[;)]")
# main's §8 as it was filled on 2026-09-29 (95454c8), the line that STEPS §10.1's merge brings into this tree
MAIN_FILLED = ("**id `claude-sonnet-5` (night\n  2026-09-29 08:30Z; the log's line reads `claude model claude-sonnet-5"
               " (read from the CLI's transcript of\n  this call, which names no model)`).**")


def _prereg_v2():
    with open(os.path.join(REPO, "PREREG-v2.md"), encoding="utf-8") as fh:
        return fh.read()


def _section_8(text=None):
    m = re.search(r"^## 8\..*?(?=^## )", _prereg_v2() if text is None else text, re.M | re.S)
    return m.group(0) if m else ""


def id_and_night(text=None):
    """[(id, night)] of every "id `...` (night ...)" line in PREREG-v2 §8 (`text`: a whole PREREG-v2.md), each value
    stripped and its whitespace (§8 wraps lines) collapsed to one space."""
    return [(pid.strip(), " ".join((a or b).split())) for pid, a, b in LINE.findall(_section_8(text))]


class SlowModel(unittest.TestCase):
    def test_the_constant_is_prereg_v2_section_8s(self):
        found = id_and_night()
        self.assertEqual(len(found), 1, "PREREG-v2 §8 must carry exactly one 'id `...` (night ...).' line")
        pid, night = found[0]
        blank = lambda v: re.fullmatch(r"_*", v) is not None
        self.assertEqual(slow_model.MODEL_ID, "" if blank(pid) else pid)
        self.assertEqual(slow_model.NIGHT, "" if blank(night) else night)
        self.assertEqual(slow_model.MODEL_ID == "", slow_model.NIGHT == "", "the id and its night are filled together")

    def test_mains_filled_line_is_read_as_its_id_and_night(self):
        # STEPS §10.1 merges main into the build; main's §8 carries the id with a bare night, and this tree's line must
        # then read as that id and night (the S6 refuter's defect 1: the old pattern found no line at all)
        text = _prereg_v2()
        blank = re.search(r"\*\*id `_+` \(night\s+`_+`\)\.\*\*", text)
        if blank is None:
            self.skipTest("§8 is filled in this tree: test_the_constant_is_prereg_v2_section_8s reads it")
        merged = text[:blank.start()] + MAIN_FILLED + text[blank.end():]
        self.assertEqual(id_and_night(merged), [("claude-sonnet-5", "2026-09-29 08:30Z")])
        self.assertEqual(id_and_night(text), [("________", "________")])
        self.assertRegex("claude-sonnet-5", "^" + slow_model.ID_FORM + "$")

    def test_a_filled_id_has_the_form_a_claude_model_line_holds(self):
        self.assertEqual(slow_model.ID_FORM, answered_model.MODEL_ID.pattern)
        if slow_model.MODEL_ID:
            self.assertRegex(slow_model.MODEL_ID, "^" + slow_model.ID_FORM + "$")

    def test_propose_sh_passes_it_as_model_and_takes_no_other(self):
        with open(os.path.join(REPO, "nightly", "propose.sh"), encoding="utf-8") as fh:
            src = fh.read()
        code = [l for l in src.splitlines() if not l.lstrip().startswith("#")]
        model = [l for l in code if "--model \"" in l]                    # the call's argument, not the log line
        self.assertEqual(len(model), 1, model)
        self.assertIn('--model "$MODEL_ID"', model[0])
        reads = [l for l in code if "import slow_model" in l or "slow_model import" in l]
        self.assertEqual(len(reads), 1, reads)                             # the one read, of the module in the repo
        self.assertIn("from nightly import slow_model", reads[0])
        self.assertEqual([l for l in code if re.search(r"\bJEVLOOP_[A-Z_]*MODEL", l)], [])   # no environment knob for it


if __name__ == "__main__":
    unittest.main()

"""nightly/slow_model.py: the slow model's id, pinned in ONE place (PREREG-v2 §8), and PREREG-v2.md §8's line naming it
agree: both blank (underscores there, "" here) until §8 is filled before the draft tag, then the same id and night.
propose.sh passes it as `--model` and reads it from nowhere else. The live night's refusal of a blank or malformed id
is driven end to end in tests/test_nightly.py (LiveBranch)."""
import os, re, unittest

from nightly import answered_model, slow_model

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINE = re.compile(r"\*\*id\s+`([^`\n]*)`\s+\(night\s+`([^`\n]*)`\)\.\*\*")   # §8 wraps it across lines


def _section_8():
    with open(os.path.join(REPO, "PREREG-v2.md"), encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"^## 8\..*?(?=^## )", text, re.M | re.S)
    return m.group(0) if m else ""


class SlowModel(unittest.TestCase):
    def test_the_constant_is_prereg_v2_section_8s(self):
        found = LINE.findall(_section_8())
        self.assertEqual(len(found), 1, "PREREG-v2 §8 must carry exactly one 'id `...` (night `...`).' line")
        pid, night = (v.strip() for v in found[0])
        blank = lambda v: re.fullmatch(r"_*", v) is not None
        self.assertEqual(slow_model.MODEL_ID, "" if blank(pid) else pid)
        self.assertEqual(slow_model.NIGHT, "" if blank(night) else night)
        self.assertEqual(slow_model.MODEL_ID == "", slow_model.NIGHT == "", "the id and its night are filled together")

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

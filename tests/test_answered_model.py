"""nightly/answered_model.py: the model that answered the nightly's call, read from the CLI's own
transcript of that session (in a fake config dir here; no test reads a real ~/.claude)."""
import io, json, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout

from nightly import answered_model

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _assistant(model):
    return {"type": "assistant", "message": {"model": model, "role": "assistant", "content": [{"type": "text", "text": "x"}]}}


class AnsweredModel(unittest.TestCase):
    def setUp(self):
        self.cfg = self.enterContext(tempfile.TemporaryDirectory())
        self.work = "/private/var/folders/ab/xyz_12/T/jevloop-claude.AbC123"      # a macOS TMPDIR, as mktemp names it

    def _session(self, dirname, lines, name="0b9d.jsonl"):
        d = os.path.join(self.cfg, "projects", dirname)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
            for x in lines:
                fh.write((x if isinstance(x, str) else json.dumps(x)) + "\n")

    def test_the_slug_is_the_clis_every_non_alphanumeric_a_dash(self):
        self.assertEqual(answered_model.slug(self.work), "-private-var-folders-ab-xyz-12-T-jevloop-claude-AbC123")

    def test_the_models_of_that_nights_session_only(self):
        self._session(answered_model.slug(self.work), [
            {"type": "user", "message": {"role": "user", "content": "PROMPT.md + digest"}},
            _assistant("model-alpha-1"),
            _assistant("<synthetic>"),                                   # the CLI's own filler, not a model
            "{not json",
            _assistant("two words"),                                     # not an id: never printed
            {"type": "assistant", "message": "a string, not an object"},
            _assistant("model-beta-2"),
            _assistant("model-alpha-1"),
        ])
        self._session("-private-var-folders-ab-xyz-12-T-jevloop-claude-ZZZ999", [_assistant("another-night")])
        self._session("-private-var-folders-ab-xyz-12-T-jevloop-claude-AbC123-old", [_assistant("a-longer-name")])
        self.assertEqual(answered_model.models(self.cfg, self.work), ["model-alpha-1", "model-beta-2"])
        self.assertEqual(answered_model.models(self.cfg, self.work + "/"), ["model-alpha-1", "model-beta-2"])

    def test_the_cwd_as_the_cli_resolved_it_matches_too(self):
        # /var is a symlink to /private/var on macOS: whichever form the CLI kept, the suffix is the same
        self._session(answered_model.slug(self.work.replace("/private", "", 1)), [_assistant("model-alpha-1")])
        self.assertEqual(answered_model.models(self.cfg, self.work), ["model-alpha-1"])

    def test_a_name_the_cli_cut_and_hashed_is_not_found_rather_than_misread(self):
        # past 200 characters the CLI keeps the first 200 of the slug and a hash of the path: the unique
        # suffix is gone, so the night logs "unrecorded" -- and another night's session is never taken for it
        work = "/private/var/folders/" + "x" * 200 + "/T/jevloop-claude.AbC123"
        cut = answered_model.slug(work)[:200] + "-1q2w3e"
        self._session(cut, [_assistant("model-alpha-1")])
        self.assertEqual(answered_model.models(self.cfg, work), [])

    def test_nothing_found_is_an_empty_answer_never_an_error(self):
        self.assertEqual(answered_model.models(os.path.join(self.cfg, "absent"), self.work), [])
        self.assertEqual(answered_model.models(self.cfg, "/"), [])
        self._session(answered_model.slug(self.work), [{"type": "user"}])
        self.assertEqual(answered_model.models(self.cfg, self.work), [])

    def test_main_prints_the_ids_and_exits_0_whatever_happens(self):
        self._session(answered_model.slug(self.work), [_assistant("model-alpha-1")])
        for argv, want in (([self.cfg, self.work], "model-alpha-1\n"), ([self.cfg], ""), ([], "")):
            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(io.StringIO()):
                self.assertEqual(answered_model.main(argv), 0)
            self.assertEqual(buf.getvalue(), want)

    def test_run_by_path_isolated_as_propose_sh_runs_it(self):
        self._session(answered_model.slug(self.work), [_assistant("model-alpha-1"), _assistant("model-gamma-3")])
        r = subprocess.run([sys.executable, "-I", "-B", os.path.join(REPO, "nightly", "answered_model.py"), self.cfg, self.work],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "model-alpha-1,model-gamma-3\n", ""))


if __name__ == "__main__":
    unittest.main()

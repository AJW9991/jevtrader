"""A PREREG.md for tests. No test may depend on what the repository's PREREG.md §11 says: its T0 line is
to be re-sealed for prereg-v2 after 2026-10-23 (or blanked in between), and a test that pins the
literal 2026-09-25T21:40Z there would go red for a reason that is not a bug. pin_prereg(tc)
writes a temp PREREG.md whose §11 line has exactly the shape dash.T0_RE parses (the real line's,
with the fixture named as the sealer), patches dash.PREREG_PATH to it for the test's lifetime
(or the class's, when `tc` is the class in setUpClass), and returns the path. Every program
reads the repository's PREREG through dash.PREREG_PATH (report, status, dash, inference), so
this is the one pin (tests/test_prereg_line.py is the one test that reads the real line, and accepts any
T0: it checks only that a sealed line parses). t0=None writes an unsealed line. Not a test module: unittest discovers
test*.py only."""
import os, tempfile
from unittest import mock

from loop import dash

SEALED_T0 = "20260925T214000Z"                         # prereg-v1's §11, the T0 the tests are written against
LINE = "T0 (first tick_id of day 1): `{t0}`   Sealed by: `{by}`   on: `2026-09-24T21:40:33Z`\n"


def text(t0=SEALED_T0):
    """A PREREG.md body: a title, a §11 heading and the T0 line (underscores when t0 is None)."""
    return ("# PREREG (test fixture, tests/fixture_prereg.py)\n\n## 11. Sealing\n\n"
            + LINE.format(t0=t0 or "________________", by="tests/fixture_prereg.py" if t0 else "________"))


LINE_V2 = "T_first_v2: `{tf}`   T0_v2: `{t0}`   Sealed by: `{by}`   on: `{on}`\n"


def text_v2(t0=None):
    """A PREREG-v2.md body: a title, a §12 heading and its field line, T0_v2 underscores when t0 is None (blank)."""
    return ("# PREREG-v2 (test fixture, tests/fixture_prereg.py)\n\n## 12. Fields filled after the draft tag\n\n"
            + LINE_V2.format(tf="________" if t0 is None else "20261023T220000Z", t0=t0 or "________",
                             by="________" if t0 is None else "tests/fixture_prereg.py", on="________")
            + "\n## 13. The tags\n\nT0_v2: `20990101T000000Z` (outside §12: never read)\n")


def pin_prereg_v2(tc, t0=None, spec_sha="spec-v2-fixture"):
    """The v2 twin of pin_prereg: a temp PREREG-v2.md whose §12 carries `t0` (a tick_id, or None: blank), patched
    in as dash.PREREG_V2_PATH, and dash.v2_spec_sha patched to return `spec_sha`, so no test depends on the
    repository's §12 (filled at sealing) or on whether this tree's SPEC.md is v1's or v2's. `tc` may also be a
    contextlib.ExitStack, for one run. Returns the path."""
    enter = getattr(tc, "enter_context", None) or (tc.enterClassContext if isinstance(tc, type) else tc.enterContext)
    path = os.path.join(enter(tempfile.TemporaryDirectory()), "PREREG-v2.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text_v2(t0))
    enter(mock.patch.object(dash, "PREREG_V2_PATH", path))
    enter(mock.patch.object(dash, "v2_spec_sha", lambda spec=None: spec_sha))
    return path


def pin_prereg(tc, t0=SEALED_T0):
    enter = tc.enterClassContext if isinstance(tc, type) else tc.enterContext
    path = os.path.join(enter(tempfile.TemporaryDirectory()), "PREREG.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text(t0))
    enter(mock.patch.object(dash, "PREREG_PATH", path))
    return path

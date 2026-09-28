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


def pin_prereg(tc, t0=SEALED_T0):
    enter = tc.enterClassContext if isinstance(tc, type) else tc.enterContext
    path = os.path.join(enter(tempfile.TemporaryDirectory()), "PREREG.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text(t0))
    enter(mock.patch.object(dash, "PREREG_PATH", path))
    return path

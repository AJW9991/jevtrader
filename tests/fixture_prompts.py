"""A v1-only prompts root for tests. The suite must not read the repo's live prompts/: CURRENT
changes whenever a person runs bin/promote (v2 on 2026-09-26), and a test that assumes v1
there goes red for a reason that is not a bug. pin_v1(testcase) copies the frozen v1.json,
writes CURRENT = v1, patches config.PROMPTS to that directory for the test's lifetime, and
returns the path. Not a test module: unittest discovers test*.py only."""
import os, shutil, tempfile
from unittest import mock

from loop import config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V1 = os.path.join(REPO, "prompts", "v1.json")      # frozen 2026-09-23; the one prompt file that never changes


def pin_v1(testcase):
    root = os.path.join(testcase.enterContext(tempfile.TemporaryDirectory()), "prompts")
    os.makedirs(root)
    shutil.copy(V1, root)
    with open(os.path.join(root, "CURRENT"), "w") as fh:
        fh.write("v1\n")
    testcase.enterContext(mock.patch.object(config, "PROMPTS", root))
    return root

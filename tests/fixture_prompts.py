"""A v1-only prompts root for tests. The suite must not read the repo's live prompts/: CURRENT
changes whenever a person runs bin/promote (v2 on 2026-09-26), and a test that assumes v1
there goes red for a reason that is not a bug. pin_v1(testcase) copies the frozen v1.json,
writes CURRENT = v1, patches config.PROMPTS to that directory for the test's lifetime, and
returns the path. pin_v1(testcase, frozen_a=True) also copies config.FROZEN_A's file (v2.json,
pinned by tests/test_frozen.py), which every v2 tick loads for arm A (PREREG-v2 §1); CURRENT
still names v1. Not a test module: unittest discovers test*.py only."""
import json, os, shutil, tempfile
from unittest import mock

from loop import config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V1 = os.path.join(REPO, "prompts", "v1.json")      # frozen 2026-09-23; the one prompt file that never changes
FROZEN_A = os.path.join(REPO, "prompts", config.FROZEN_A + ".json")   # frozen 2026-09-26 (v2), arm A from v2 on


def pin_v1(testcase, frozen_a=False):
    root = os.path.join(testcase.enterContext(tempfile.TemporaryDirectory()), "prompts")
    os.makedirs(root)
    shutil.copy(V1, root)
    if frozen_a:
        shutil.copy(FROZEN_A, root)
    with open(os.path.join(root, "CURRENT"), "w", encoding="utf-8") as fh:
        fh.write("v1\n")
    testcase.enterContext(mock.patch.object(config, "PROMPTS", root))
    return root


def pin_versions(testcase, current, docs=None):
    """A prompts root holding the frozen v1.json and v2.json, each of `docs` ({version: document}) written beside them,
    and CURRENT naming `current`; config.PROMPTS patched to it for the test's lifetime. Returns the path."""
    root = os.path.join(testcase.enterContext(tempfile.TemporaryDirectory()), "prompts")
    os.makedirs(root)
    shutil.copy(V1, root)
    shutil.copy(FROZEN_A, root)
    for v, doc in (docs or {}).items():
        with open(os.path.join(root, v + ".json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    with open(os.path.join(root, "CURRENT"), "w", encoding="utf-8") as fh:
        fh.write(current + "\n")
    testcase.enterContext(mock.patch.object(config, "PROMPTS", root))
    return root


def version_doc(version, action, activation_tick=None, replaces=None, note="test"):
    """A version document as bin/promote writes it: v1's three nouls carried, the action given, and the activation
    keys when given."""
    with open(V1, encoding="utf-8") as fh:
        v1 = json.load(fh)
    doc = {"version": version, "frozen": "2026-10-29"}
    if activation_tick is not None:
        doc.update(activation_tick=activation_tick, replaces=replaces)
    doc.update(note=note, action=dict(action, type="choice"), **{q: v1[q] for q in ("skip", "up15", "down15")})
    return doc

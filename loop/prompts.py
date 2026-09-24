"""Prompt versions: load one, name the current one, sha it, build the wire questions.

May: read prompts/<version>.json and prompts/CURRENT. May not: write anything under
prompts/ (only bin/promote does, by hand), read data/, the key or the network, or
change a question's text in any way -- build() projects each question onto the three
wire keys and refuses a wrong shape; it never rewrites one. Nothing here knows what
an answer means.
"""
import hashlib, json, os, re
from loop import config

_VERSION = re.compile(r"^v\d+$")          # bin/promote writes v<N+1>; anything else is a path, not a version
WIRE = ("type", "instructions", "criteria")
# yes/no is what the brain's live inject-screen sends and it works; true/false is not
# tested against this model (CONTRACT §2), so the keys are fixed here, not left to the file.
CRITERIA = {"choice": ("buy", "sell", "hold"), "noul": ("yes", "no")}
CARRIED = ("skip", "up15", "down15")      # always from v1: only `action` is ever rewritten (v1.json note)


class PromptError(ValueError):
    pass


def _root(root):
    return root or config.PROMPTS


def load(version, root=None):
    """prompts/<version>.json as a dict. `root` exists for tests and bin/promote's dry run."""
    if not isinstance(version, str) or not _VERSION.match(version):
        raise PromptError(f"not a version name: {version!r}")
    p = os.path.join(_root(root), version + ".json")
    try:
        with open(p) as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        raise PromptError(f"{p}: {e}") from None
    if not isinstance(doc, dict):
        raise PromptError(f"{p}: top level is {type(doc).__name__}, not an object")
    return doc


def current(root=None):
    """The one version name in prompts/CURRENT. Blank lines are tolerated; a second
    name is not -- two names would make prompt_b ambiguous in every row after."""
    p = os.path.join(_root(root), "CURRENT")
    try:
        with open(p) as fh:
            names = [l.strip() for l in fh.read().splitlines() if l.strip()]
    except OSError as e:
        raise PromptError(f"{p}: {e}") from None
    if len(names) != 1 or not _VERSION.match(names[0]):
        raise PromptError(f"{p}: expected exactly one version name, got {names!r}")
    return names[0]


def canon(doc):
    """Canonical bytes: sorted keys, no whitespace. A re-save with another indent or
    key order (a hand edit, `python -m json.tool`) leaves the sha alone; a changed
    character anywhere in the text does not."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


def sha_of(doc):
    return hashlib.sha256(canon(doc)).hexdigest()


def sha(version, root=None):
    return sha_of(load(version, root))


def question(q, want, where="?"):
    """One question projected onto the wire shape {type, instructions, criteria},
    or PromptError. `want` is the type this slot must have: the action slot is a
    choice, the three carried slots are nouls, and a promoted file that swapped
    one would silently change what a column means."""
    if not isinstance(q, dict):
        raise PromptError(f"{where}: missing or not an object")
    if q.get("type") != want:
        raise PromptError(f"{where}: type {q.get('type')!r}, expected {want!r}")
    text, crit = q.get("instructions"), q.get("criteria")
    if not isinstance(text, str) or not text.strip():
        raise PromptError(f"{where}: instructions must be non-empty text")
    keys = CRITERIA[want]
    if not isinstance(crit, dict) or sorted(crit) != sorted(keys):
        raise PromptError(f"{where}: criteria keys {sorted(crit) if isinstance(crit, dict) else crit!r}, expected {sorted(keys)}")
    for k in keys:
        if not isinstance(crit[k], str) or not crit[k].strip():
            raise PromptError(f"{where}: criteria.{k} must be non-empty text")
    return {"type": want, "instructions": text, "criteria": {k: crit[k] for k in keys}}


def build(v1, current):
    """The five questions of CONTRACT §2, in row order. a_action is v1's action, b_action
    the current version's; the three nouls always come from v1 so arms A and B differ
    in one question's wording and nothing else."""
    out = {"a_action": question(v1.get("action"), "choice", "v1.action"),
           "b_action": question(current.get("action"), "choice", "current.action")}
    for qid in CARRIED:
        out[qid] = question(v1.get(qid), "noul", "v1." + qid)
    return out

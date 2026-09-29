"""Prompt versions: load one, name the one a tick asks, sha it, build the wire questions,
and read a version's per-product answer table.

May: read prompts/<version>.json, prompts/CURRENT and prompts/<version>.table.<product>.json.
May not: write anything under prompts/ (only bin/promote does, by hand), read data/, the key
or the network, or change a question's text in any way but one -- build() projects each
question onto the three wire keys, refuses a wrong shape, and renders the product's base into
the action text (PREREG-v2 §1); it never rewrites anything else. Nothing here knows what an
answer means.

The base token (PREREG-v2 §1). prompts/v1.json and v2.json were written for SOL-USD alone:
in them the word `SOL` IS the base placeholder, replaced by the row's base (ETH, ...), so
SOL-USD's requests stay byte-identical to v1's. v3 and later name no product and may use the
literal `{BASE}`. Every other product word -- the base of any product in config.PRODUCTS or
config.PROBE_CANDIDATES, as a whole capitalised word, and `{BASE}` in v1/v2 -- is refused
by load() (by the file's name) and by build() (by the document's "version"), so bin/promote,
which builds before it writes, refuses it too.

Activation (PREREG-v2 §8). A version bin/promote writes during v2 carries `activation_tick`
(a minute tick_id, T0_v2 + 86,400 (E - 1)) and `replaces` (the version active when it ran).
current(tick_id) answers for one tick: CURRENT's version from its activation_tick on, the
version it replaces before that. At most one version is pending for any tick: a replaced
version that is itself pending at the tick asked (or activates no earlier than its successor)
is refused. v1.json and v2.json carry neither key and are active whenever CURRENT names them.

Tables (PREREG-v2 §1 arm D, §8). prompts/<version>.table.<product>.json holds that wording's
answer on each of the 81 synthetic states rendered for the product:
    {"version": "v2", "product": "SOL-USD", "prompt_sha": <sha of prompts/v2.json>,
     "model_answered": "jev-...", "answers": {"SOL: liquidity thin, flow quiet, ...": "sell", ...}}
exactly the 81 state strings of state.all_states() with the product's base, each answer one of
buy/sell/hold. table() returns None when the file is absent and refuses any other shape.
"""
import hashlib, json, os, re, time
from loop import config, state

_VERSION = re.compile(r"^v\d+$")          # bin/promote writes v<N+1>; anything else is a path, not a version
_TICK_ID = re.compile(r"^\d{8}T\d{6}Z$")   # a row's tick_id, fixed width, so string order is time order
_ACTIVATION = re.compile(r"^\d{8}T\d{4}00Z$")   # a minute boundary (T0_v2 is one)
LEGACY_TOKEN = "SOL"                      # v1.json / v2.json: the base placeholder (PREREG-v2 §1)
BASE_TOKEN = "{BASE}"                     # v3 and later: the literal a wording may use for the base
LEGACY_LAST = 2                           # the last version whose placeholder is LEGACY_TOKEN
TABLE_ANSWERS = ("buy", "sell", "hold")
WIRE = ("type", "instructions", "criteria")
# yes/no is what the brain's live inject-screen sends and it works; true/false is not
# tested against this model (CONTRACT §2), so the keys are fixed here, not left to the file.
CRITERIA = {"choice": ("buy", "sell", "hold"), "noul": ("yes", "no")}
CARRIED = ("skip", "up15", "down15")      # always from v1: only `action` is ever rewritten (v1.json note)


class PromptError(ValueError):
    pass


def _root(root):
    return root or config.PROMPTS


def product_words():
    """The capitalised product words a prompt file may carry only as its placeholder: the base of
    every product in config.PRODUCTS and config.PROBE_CANDIDATES (read now, so a patch applies)."""
    return sorted({config.base(p) for p in tuple(config.PRODUCTS) + tuple(config.PROBE_CANDIDATES)})


def placeholder(version):
    """"SOL" for v1 and v2, "{BASE}" for v3 and later; PromptError for a name that is not a version."""
    if not isinstance(version, str) or not _VERSION.match(version):
        raise PromptError(f"not a version name: {version!r}")
    return LEGACY_TOKEN if int(version[1:]) <= LEGACY_LAST else BASE_TOKEN


def _texts(q):
    """The wire text of one question slot: its instructions and its criteria values (strings only)."""
    if not isinstance(q, dict):
        return []
    crit = q.get("criteria")
    out = [q.get("instructions")] + (list(crit.values()) if isinstance(crit, dict) else [])
    return [t for t in out if isinstance(t, str)]


def check_words(doc, version, where="?"):
    """Refuse any product word in the doc's question slots (action, skip, up15, down15) other than
    the version's own placeholder: in v1/v2 any base but SOL, or the literal {BASE}; in v3 and later
    any base at all. Free text outside the questions (note, rationale) is not wire text and is not read."""
    ph = placeholder(version)
    word = re.compile(r"\b(" + "|".join(re.escape(w) for w in product_words()) + r")\b")
    for qid in ("action",) + CARRIED:
        for t in _texts(doc.get(qid) if isinstance(doc, dict) else None):
            bad = [m.group(1) for m in word.finditer(t) if m.group(1) != ph]
            if ph == LEGACY_TOKEN and BASE_TOKEN in t:
                bad.append(BASE_TOKEN)
            if bad:
                raise PromptError(f"{where}.{qid}: product word {bad[0]!r} in {version}, whose only base token is "
                                  f"{ph!r} (PREREG-v2 §1)")


def load(version, root=None):
    """prompts/<version>.json as a dict. `root` exists for the tests and the --prompts flag of bin/promote,
    nightly.digest, nightly.policy_table and loop.dash."""
    if not isinstance(version, str) or not _VERSION.match(version):
        raise PromptError(f"not a version name: {version!r}")
    p = os.path.join(_root(root), version + ".json")
    try:
        with open(p, encoding="utf-8") as fh:        # not the locale's: v2 holds an em dash, and under LC_ALL=C
            doc = json.load(fh)                      # the file was refused (or, elsewhere, read to another sha)
    except (OSError, ValueError) as e:
        raise PromptError(f"{p}: {e}") from None
    if not isinstance(doc, dict):
        raise PromptError(f"{p}: top level is {type(doc).__name__}, not an object")
    check_words(doc, version, p)
    return doc


def named(root=None):
    """The one version name in prompts/CURRENT, as written. Blank lines are tolerated; a second
    name is not -- two names would make prompt_b ambiguous in every row after. Readers want
    current(tick_id), which honours a pending version's activation_tick; this is its input."""
    p = os.path.join(_root(root), "CURRENT")
    try:
        with open(p, encoding="utf-8") as fh:
            names = [l.strip() for l in fh.read().splitlines() if l.strip()]
    except OSError as e:
        raise PromptError(f"{p}: {e}") from None
    if len(names) != 1 or not _VERSION.match(names[0]):
        raise PromptError(f"{p}: expected exactly one version name, got {names!r}")
    return names[0]


def _tick(tick_id):
    """A row's tick_id as given, or this minute's (UTC, from time.time(), which tests pin) for None."""
    if tick_id is None:
        return time.strftime("%Y%m%dT%H%M00Z", time.gmtime(time.time()))
    if not isinstance(tick_id, str) or not _TICK_ID.match(tick_id):
        raise PromptError(f"not a tick_id (YYYYMMDDTHHMMSSZ): {tick_id!r}; a prompts root is passed as root=")
    return tick_id


def activation(doc, name):
    """(activation_tick, replaces) of a version document, or None when it carries neither key (v1,
    v2: active whenever CURRENT names it). One key without the other, a tick that is not a minute
    boundary, or a `replaces` that is not another version's name is refused."""
    has = [k in doc for k in ("activation_tick", "replaces")]
    if not any(has):
        return None
    if not all(has):
        raise PromptError(f"{name}: activation_tick and replaces come together, got only "
                          f"{'activation_tick' if has[0] else 'replaces'}")
    act, rep = doc["activation_tick"], doc["replaces"]
    if not isinstance(act, str) or not _ACTIVATION.match(act):
        raise PromptError(f"{name}: activation_tick {act!r} is not a minute tick_id (YYYYMMDDTHHMM00Z)")
    if not isinstance(rep, str) or not _VERSION.match(rep) or rep == name:
        raise PromptError(f"{name}: replaces {rep!r} is not another version's name")
    return act, rep


def current(tick_id=None, root=None):
    """The version arm B asks at `tick_id` (a row's tick_id; None: this minute), PREREG-v2 §8:
    the one CURRENT names from its activation_tick on (or always, when it carries none), the one it
    replaces before that. A replaced version still pending at that tick, or one that activates no
    earlier than its successor, is a second pending version and is refused: bin/promote allows one."""
    tick = _tick(tick_id)
    name = named(root)
    act = activation(load(name, root), name)
    if act is None or tick >= act[0]:
        return name
    prev = act[1]
    before = activation(load(prev, root), prev)
    if before is not None and (tick < before[0] or before[0] >= act[0]):
        raise PromptError(f"{name} (activation {act[0]}) replaces {prev} (activation {before[0]}), pending at {tick}"
                          f" too: a second pending version")
    return prev


def pending(tick_id=None, root=None):
    """The version CURRENT names when it is not yet active at `tick_id` (None: this minute), else None:
    what dash and status show on its own line and what bin/promote refuses to stack a second on."""
    tick = _tick(tick_id)
    name = named(root)
    act = activation(load(name, root), name)
    if act is None or tick >= act[0]:
        return None
    current(tick, root)                              # the replaced version must itself be active: else refused
    return name


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


def _check_base(base):
    if not isinstance(base, str) or not base.isascii() or not base.isalpha() or not base.isupper():
        raise PromptError(f"base {base!r} is not a product's capital-letter base")
    return base


def render(q, version, base):
    """A projected question with the version's placeholder replaced by `base`: the whole word SOL
    in v1/v2 (so SOL renders byte-identical), the literal {BASE} in v3 and later."""
    ph, base = placeholder(version), _check_base(base)
    if ph == LEGACY_TOKEN:
        word = re.compile(r"\b" + re.escape(LEGACY_TOKEN) + r"\b")
        sub = lambda t: word.sub(base, t)
    else:
        sub = lambda t: t.replace(BASE_TOKEN, base)
    return {"type": q["type"], "instructions": sub(q["instructions"]),
            "criteria": {k: sub(v) for k, v in q["criteria"].items()}}


def _action(doc, which, base):
    where = f"{which}.action"
    if not isinstance(doc, dict):
        raise PromptError(f"{which}: not a prompt document")
    version = doc.get("version")
    placeholder(version)                              # a document without a version name cannot be rendered
    check_words(doc, version, which)
    return render(question(doc.get("action"), "choice", where), version, base)


def build(frozen_a, current, base, v1=None, root=None):
    """The five questions of CONTRACT §2, in row order, for the product whose base is `base`
    (PREREG-v2 §1). a_action is the frozen A wording's action (config.FROZEN_A's document),
    b_action the current version's, each rendered for the base; the three nouls always come from
    v1 (the document passed, or prompts/v1.json under root), never rendered, so arms A and B
    differ in one question's wording and nothing else."""
    v1 = load("v1", root) if v1 is None else v1
    out = {"a_action": _action(frozen_a, "frozen_a", base),
           "b_action": _action(current, "current", base)}
    for qid in CARRIED:
        out[qid] = question(v1.get(qid), "noul", "v1." + qid)
    return out


def table_path(version, product, root=None):
    placeholder(version)
    if product not in config.PRODUCTS:
        raise PromptError(f"product {product!r} is not in config.PRODUCTS")
    return os.path.join(_root(root), f"{version}.table.{product}.json")


def table(version, product, root=None):
    """{"answers": {state string: choice}, "sha": canonical sha} of prompts/<version>.table.<product>.json,
    or None when the file does not exist. Refused (PromptError): a file that does not parse, names another
    version or product, carries a prompt_sha that is not the version file's own, or answers anything but
    exactly the 81 states rendered with the product's base, each buy, sell or hold."""
    p = table_path(version, product, root)
    try:
        with open(p, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise PromptError(f"{p}: {e}") from None
    if not isinstance(doc, dict):
        raise PromptError(f"{p}: top level is not an object")
    if doc.get("version") != version or doc.get("product") != product:
        raise PromptError(f"{p}: names {doc.get('version')!r} / {doc.get('product')!r}")
    if doc.get("prompt_sha") != sha(version, root):
        raise PromptError(f"{p}: prompt_sha {str(doc.get('prompt_sha'))[:12]} is not {version}.json's own")
    answers = doc.get("answers")
    want = {state.state_string(a, config.base(product)) for a in state.all_states()}
    if not isinstance(answers, dict) or set(answers) != want:
        raise PromptError(f"{p}: answers are not exactly the 81 states of {product}")
    bad = sorted(s for s, c in answers.items() if c not in TABLE_ANSWERS)
    if bad:
        raise PromptError(f"{p}: {bad[0]!r} answers {answers[bad[0]]!r}, not one of {TABLE_ANSWERS}")
    return {"answers": dict(answers), "sha": sha_of(doc)}

"""81 synthetic states per product per candidate wording: what each rewrite of the `action` question would answer on
every state the alphabet can produce, for every product (PREREG-v2 §8, "Scoring a candidate").

It scores NOTHING against any logged outcome. The table is a description of a wording, not a backtest of it: this
file never opens a decision log, never sees a feature, a price or a label, and never picks a candidate. A person reads
the table and runs bin/promote, or does not.

May: enumerate loop.state.all_states() (3^4 = 81 adjective dicts in one fixed order) for each product in
config.PRODUCTS, render each with state_string(adj, base) (the product's base first; no digit, no position); read
proposals/<date>.json (0-3 candidates: none is a CURRENT-only table, the form a version's own table is built from, §8)
and the CURRENT `action` question as prompts.current() names it NOW (a pending version is invisible here, §10);
render every wording for the product's base (prompts.render: CURRENT by its own version's placeholder, a candidate as a
version after v2, whose base token is {BASE}); send ONE request per state per product through loop.jev.ask carrying
every candidate and the current question as separate choice questions (cand_0 .. cand_{K-1}, current: 81 requests per
product for K+1 wordings, not 81 x (K+1)); and write two files beside each other:
  proposals/<date>.table.json  every wording's 81 answers per product, the questions exactly as sent, the proposal's
                               sha and CURRENT's version and sha: what bin/promote copies a column of (gitignored like
                               the proposal json, and vouched for by its sha in the .md);
  proposals/<date>.md          rendered from it: per wording, pooled counts and, per product, the 81-row table (state,
                               choice, confidence, rule_c; a candidate's also CURRENT's answer and whether it moved),
                               the unified diff of its instructions+criteria against CURRENT, the counts of states where
                               it differs from CURRENT and from rule_c, and where those changes land (landing(): per
                               adjective, and the CURRENT -> wording moves); its "table sha256" line is the json's sha.
May not: read a log, the key (jev.py holds it), or anything under the crypto repo; write under prompts/ or data/
(jev.py appends its own ledger row per send; the one exception is data/HALT on a rejected key, CONTRACT §2 "the caller
writes HALT", the same rule as cycle.py); send anything while data/HALT exists (PROTOCOL §3.8: HALT stops sends, and
these sends never reach a decision log, so the spend guard cannot see them; checked before EVERY send, so a HALT a
person or the loop writes mid-table stops the rest); retry beyond jev.py's one, or keep sending into a limiter (a 429
ends the night; so do MAX_TRANSIENT_RUN transient failures in a row, MAX_OTHER_RUN other failures in a row, and
MAX_ERROR_RUN failures of any kind in a row, so alternating kinds cannot run to the deadline; a stop carries over to
every later product: 81 states x jev.py's two attempts would be 162 requests on the loop's own key, the key PROTOCOL
§3.6 isolates because a limit or a suspension is the risk); run a candidate whose criteria are not exactly
buy/sell/hold (prompts.question refuses it) or that names a product (prompts.check_words: one CURRENT for every
product, up to {BASE}), so a malformed proposal sends nothing.
The proposal's bytes are read ONCE: the candidates are parsed from them and the table's "proposal sha256" line is their
hash, so the committed .md vouches for exactly the json it was built from (bin/promote checks it).
--dry prints the number of would-be payloads and the first one, and sends nothing.

Cost: 81 states x (K+1) questions of ~50 words + a 10-word state, per product; at K=3 that is ~30k input tokens =
~$0.0013 a product at config.USD_PER_MTOK. Sends are sequential: typical 81 x ~0.5 s = 40 s a product, and the
deadline, DEADLINE_S per product (so DEADLINE_S x the product count for the night), bounds the night when the API is
slow -- nothing new is sent after it and the table says INCOMPLETE.
Exit 0 complete or HALT present at the start (nothing sent, no table), 4 INCOMPLETE (written, some states unanswered: a
HALT that appears mid-table is one way), 1 bad input, 2 usage. --out defaults to <date>.md under the repo's proposals/
(config.PROPOSALS), not beside the json; propose.sh always passes it. The .table.json goes beside the .md.
"""
import argparse, collections, difflib, hashlib, json, os, re, sys, time

if __package__ in (None, ""):      # run as a script (CONTRACT §5 names `nightly/<file>.py`), not -m: sys.path[0]
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # is nightly/, so add the repo

from loop import config, jev, prompts, state

DEADLINE_S = 900.0         # per product: 81 x jev.py's worst case (45 s) is an hour; 15 min is 81 x 11 s, ample for
                           # a working API and short enough that a dead one costs one launchd slot; the night's
                           # deadline is DEADLINE_S x the number of products (PREREG-v2 §8)
MAX_CANDIDATES = 3         # CONTRACT §5: 1-3 entries from the nightly; 0 is a CURRENT-only table (PREREG-v2 §8)
CURRENT = "current"
CANDIDATE_VERSION = f"v{prompts.LEGACY_LAST + 1}"   # a candidate becomes v3 or later: its base token is {BASE}
FATAL_KINDS = ("unsigned", "no-key", "ledger", "http-429")   # 80 more sends would repeat the refusal; a 429 is the
                                                 # limiter saying stop, and jev.py already retried it once
TRANSIENT_KINDS = ("timeout", "http-5xx")
MAX_OTHER_RUN = 3                         # ... and this many non-transient, non-fatal errors in a row (a 4xx other than
                                          # 401/403/429, a parse): 78 more sends would repeat them
MAX_TRANSIENT_RUN = 3                     # this many transient failures in a row end the night: one is
                                          # noise and the table goes on; three is an outage, not a blip
MAX_ERROR_RUN = 3                         # ... and this many failures of ANY kind in a row: the two counters above
                                          # each reset on the other's kind, so timeout, 404, timeout, 404 ... would
                                          # otherwise run to the deadline
HALT_STATUS = (401, 403)                  # the key is rejected: same rule as cycle.py's HALT
EXIT_INCOMPLETE = 4
TABLE_SUFFIX = ".table.json"
KIND = "policy-table-v2"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TABLE_SHA_LINE = re.compile(r"^table sha256: ([0-9a-f]{64})", re.M)


def _product(product):
    return product or config.PRODUCT


def states(product=None):
    """[(state string, rule_c)] in loop.state.all_states() order for `product` (default SOL-USD): 81 rows, each string
    beginning with the product's base, every string digit-free by construction (state_string raises otherwise)."""
    base = config.base(_product(product))
    return [(state.state_string(adj, base), state.rule_c(adj)) for adj in state.all_states()]


def load_candidates(path):
    """The proposal's 0-3 candidates, read from the file at `path` (see parse_candidates)."""
    with open(path, "rb") as fh:
        return parse_candidates(fh.read(), path)


def parse_candidates(raw, path):
    """The 0-3 candidates in `raw` (the proposal's bytes; `path` names it in errors), each projected onto the wire shape
    with type 'choice' added (proposals carry none, CONTRACT §5); rationale kept for the table. Raises ValueError on any
    shape fault (a byte that is not UTF-8 is one too), a digit, or a product word (a candidate may name the product only
    as {BASE}, PREREG-v2 §1, §8): a half-valid proposal would send half a table."""
    doc = json.loads(raw.decode("utf-8"))
    c = doc.get("candidates") if isinstance(doc, dict) else None
    if not isinstance(c, list) or len(c) > MAX_CANDIDATES:
        raise ValueError(f"{path}: candidates must be a list of 0-{MAX_CANDIDATES}")
    out = []
    for i, cand in enumerate(c):
        if not isinstance(cand, dict):
            raise ValueError(f"{path}: candidate {i} is not an object")
        q = prompts.question({**cand, "type": "choice"}, "choice", f"cand_{i}")
        text = q["instructions"] + "".join(q["criteria"].values())
        if any(ch.isdigit() for ch in text):
            raise ValueError(f"{path}: cand_{i} carries a digit; PROMPT.md forbids numbers")
        prompts.check_words({"action": q}, CANDIDATE_VERSION, f"{path} cand_{i}")
        out.append({"qid": f"cand_{i}", "q": q, "rationale": str(cand.get("rationale", ""))})
    return out


def current_action(root=None, now_tick=None):
    """(version name, wire question as the file holds it, sha of the whole version file) of the version
    prompts.current() names at `now_tick` (None: this minute): a pending version is invisible here (PREREG-v2 §10)."""
    name = prompts.current(now_tick, root)
    doc = prompts.load(name, root)
    return name, prompts.question(doc.get("action"), "choice", f"{name}.action"), prompts.sha_of(doc)


def questions(cands, cur_q, cur_name=None, product=None):
    """One dict, sent whole on every state of `product` (default SOL-USD): cand_0..cand_{K-1} then current, each
    rendered for the product's base: a candidate as a version after v2 ({BASE}), CURRENT by its own version's
    placeholder (cur_name; None leaves it as given)."""
    base = config.base(_product(product))
    qs = {c["qid"]: prompts.render(c["q"], CANDIDATE_VERSION, base) for c in cands}
    qs[CURRENT] = cur_q if cur_name is None else prompts.render(cur_q, cur_name, base)
    return qs


def payloads(qs, product=None):
    return [jev.dry_payload(s, qs) for s, _ in states(product)]


def _halt(reason):
    """data/HALT, as cycle._halt writes it: a person reads the reason and deletes it."""
    try:
        with open(config.HALT, "w") as fh:
            fh.write(reason + "\n")
    except OSError as e:
        print(f"policy_table: cannot write {config.HALT}: {e}", file=sys.stderr)


def run_night(jobs, ask=None, deadline_s=None, clock=time.monotonic):
    """{product: [row]} for `jobs`, [(product, qs, [(state, rule_c)])] sent in order, one request per state carrying
    every question of qs. A row: {"state", "rule_c", "answers": {qid: (choice, confidence)}|None, "error": kind|None,
    "model": str|None}. One clock for the night: the deadline (default DEADLINE_S x the number of jobs) is checked before
    each send, never mid-send (jev.py's own timeout bounds a send). A fatal kind (no key, no ledger, a 429, key rejected
    -- which also writes data/HALT), MAX_TRANSIENT_RUN transient failures in a row, MAX_OTHER_RUN other failures in a
    row, or MAX_ERROR_RUN failures of any kind in a row stop the sending; so does data/HALT, checked before every send
    (error kind "halt"). A stop carries over to every later product; the remaining rows carry the kind that stopped it."""
    ask = ask or jev.ask                 # resolved at call time so tests can patch loop.jev.ask
    deadline_s = DEADLINE_S * len(jobs) if deadline_s is None else deadline_s
    t0, stop, streak, other, errors = clock(), None, 0, 0, 0
    out = {}
    for product, qs, sts in jobs:
        rows = out.setdefault(product, [])
        for s, rc in sts:
            row = {"state": s, "rule_c": rc, "answers": None, "error": None, "model": None}
            if stop:
                row["error"] = stop
            elif os.path.exists(config.HALT):          # PROTOCOL §3.8, per send: a HALT written mid-table stops the rest
                stop = row["error"] = "halt"
            elif clock() - t0 > deadline_s:
                stop = row["error"] = "deadline"
            else:
                try:
                    r = ask(s, qs)
                    row["answers"] = {qid: (r["answers"][qid].get("choice"), r["answers"][qid].get("confidence"))
                                      for qid in qs}
                    row["model"] = r.get("model")
                    streak = other = errors = 0
                except jev.JevError as e:
                    row["error"] = e.kind
                    streak = streak + 1 if e.kind in TRANSIENT_KINDS else 0
                    other = other + 1 if e.kind not in TRANSIENT_KINDS else 0     # a 4xx or parse that repeats is not going to clear
                    errors += 1                                                   # any kind: alternating kinds reset the two above
                    if e.status in HALT_STATUS:
                        _halt(f"key rejected: {e.kind} {e.status} via {e.key_path} (nightly policy table)")
                    if (e.kind in FATAL_KINDS or e.status in HALT_STATUS or streak >= MAX_TRANSIENT_RUN
                            or other >= MAX_OTHER_RUN or errors >= MAX_ERROR_RUN):
                        stop = e.kind
            rows.append(row)
    return out


def run(qs, ask=None, deadline_s=DEADLINE_S, clock=time.monotonic, product=None):
    """One product's 81 rows (run_night for one job; default SOL-USD)."""
    p = _product(product)
    return run_night([(p, qs, states(p))], ask, deadline_s, clock)[p]


def _lines(q):
    """The four lines a wording is diffed on: instructions, then the criteria in wire order."""
    return [f"instructions: {q['instructions']}"] + [f"{k}: {q['criteria'][k]}" for k in prompts.CRITERIA["choice"]]


def diff(cur_q, cand_q, name):
    return "\n".join(difflib.unified_diff(_lines(cur_q), _lines(cand_q), fromfile=CURRENT, tofile=name,
                                          lineterm="", n=4))


def counts(results, qid):
    """(differs from current, differs from rule_c, n answered) over states where the
    wording answered; an errored state counts in none of them."""
    cur = rule = n = 0
    for r in results:
        a = r["answers"]
        if not a or qid not in a:
            continue
        n += 1
        cur += a[qid][0] != a[CURRENT][0]
        rule += a[qid][0] != r["rule_c"]
    return cur, rule, n


def landing(results, qid, product=None):
    """Where a wording changes CURRENT's answer, over the states where both answered: for each
    adjective, the states it changed out of the answered states that carry that adjective, and the
    CURRENT -> wording moves. For the person who promotes (the digest never carries a table). It
    says which states moved, not whether a move follows the wording's own criteria: that stays a
    person's read, as proposals/2026-09-25.review.md did by hand (cand_0 moved none of the 81
    states; cand_1 moved the 27 vol-violent states, not the vol-normal ones its wording named)."""
    base = config.base(_product(product))
    by = {state.state_string(adj, base): adj for adj in state.all_states()}
    seen = {d: dict.fromkeys(state.ALPHABET[d], 0) for d in state.DIMS}
    changed = {d: dict.fromkeys(state.ALPHABET[d], 0) for d in state.DIMS}
    moves = collections.Counter()
    for r in results:
        a, adj = r["answers"], by.get(r["state"])
        if not a or qid not in a or CURRENT not in a or adj is None:
            continue
        moved = a[qid][0] != a[CURRENT][0]
        for d in state.DIMS:
            seen[d][adj[d]] += 1
            changed[d][adj[d]] += moved
        if moved:
            moves[(str(a[CURRENT][0]), str(a[qid][0]))] += 1
    n, total = sum(seen[state.DIMS[0]].values()), sum(moves.values())
    if not total:
        return [f"where it changes CURRENT's answer: nowhere (0 of {n} answered states)"]
    out = [f"where it changes CURRENT's answer ({total} of {n} answered states; per adjective, changed / answered):"]
    for d in state.DIMS:
        out.append(f"- {d}: " + ", ".join(f"{w} {changed[d][w]}/{seen[d][w]}" for w in state.ALPHABET[d]))
    out.append("- moves: " + ", ".join(f"{c} -> {w} {k}" for (c, w), k in sorted(moves.items(), key=lambda x: (-x[1], x[0]))))
    return out


def _cell(a):
    if a is None:
        return "-", "-"
    choice, conf = a
    if not isinstance(conf, (int, float)) or isinstance(conf, bool):
        return str(choice), "-"
    try:
        return str(choice), f"{conf:.2f}"
    except OverflowError:                      # an int past a float's range: it raised after all 81 sends, and the
        return str(choice), "?"                # table was left empty


def table_doc(date, cur_name, cur_sha, cands, cur_q, per, per_qs=None, proposal_sha=None, writer=None):
    """The .table.json document: every wording's 81 answers per product ({product: [row]} in `per`), the questions as
    sent to each product (`per_qs`; default: rendered here), CURRENT's version, sha and question, the candidates as
    proposed, the proposal's sha and its writer. Answers are [choice, confidence] (JSON has no tuple)."""
    products = {}
    for p, rows in per.items():
        qs = (per_qs or {}).get(p) or questions(cands, cur_q, cur_name, p)
        products[p] = {"questions": qs, "rows": [{"state": r["state"], "rule_c": r["rule_c"], "error": r["error"],
                                                  "model": r["model"],
                                                  "answers": None if not r["answers"] else {q: list(v) for q, v in r["answers"].items()}}
                                                 for r in rows]}
    return {"kind": KIND, "date": date, "proposal_sha256": proposal_sha, "writer": writer,
            "current": {"version": cur_name, "sha": cur_sha, "question": cur_q},
            "candidates": [{"qid": c["qid"], "question": c["q"], "rationale": c["rationale"]} for c in cands],
            "products": products}


def dump(doc):
    """The .table.json bytes: one fixed serialisation, so its sha is a function of the document."""
    return (json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=False) + "\n").encode("utf-8")


def _rows(doc, p):
    """A product's rows with answers as tuples, as run_night gives them."""
    return [{**r, "answers": None if not r["answers"] else {q: tuple(v) for q, v in r["answers"].items()}}
            for r in doc["products"][p]["rows"]]


def render_doc(doc, table_sha=None, table_name=None):
    """The .md of a .table.json document: pooled counts first (what loop.dash reads), then per product."""
    per = {p: _rows(doc, p) for p in doc["products"]}
    allrows = [r for rows in per.values() for r in rows]
    n_err = sum(1 for r in allrows if r["error"] or not r["answers"])
    answered = [r for r in allrows if r["answers"]]
    models = sorted({str(r["model"]) for r in answered if r["model"]})
    unnamed = sum(1 for r in answered if not r["model"])
    if unnamed:
        models.append(f"no model named on {unnamed}")
    # cycle.py's rule for the same reply (row "drift": model != config.MODEL): an answer that names
    # no model is drift too, not a pass
    drift = " -- DRIFT, requested " + config.MODEL if any(r["model"] != config.MODEL for r in answered) else ""
    cur = doc["current"]
    cands = doc["candidates"]
    prods = list(per)
    first = prods[0] if prods else config.PRODUCT
    out = [f"# policy table {doc['date']}", "",
           f"Eighty-one synthetic states per product for {len(prods)} product{'s' if len(prods) != 1 else ''} "
           f"({', '.join(prods)}), one request each, carrying {len(cands) + 1} questions. "
           "Nothing here is scored against a logged outcome: the table describes a wording, it does not backtest it.",
           "", f"CURRENT: {cur['version']} sha {cur['sha']}  ",
           f"proposal sha256: {doc['proposal_sha256'] or '-'}  ",   # the json is not committed; this line, in the committed table, vouches for it
           f"proposal written by: {doc['writer'] or 'not given'}  ",  # propose.sh reads it from the CLI's transcript; the call names it too
           f"table sha256: {table_sha or '-'}{f' ({table_name})' if table_name else ''}  ",   # bin/promote copies from the json it vouches for
           f"requests: {len(allrows)}, answered: {len(allrows) - n_err}, errors: {n_err}"
           + (" -- INCOMPLETE" if n_err else "") + "  ",
           f"model answered: {', '.join(models) or 'none'}{drift}", ""]
    if n_err:
        kinds = sorted({str(r["error"]) for r in allrows if r["error"]})
        out += [f"error kinds: {', '.join(kinds)}", ""]
    _, rule, n = counts(allrows, CURRENT)
    out += [f"## {CURRENT} ({cur['version']})", "", f"differs from rule_c on {rule} of {n} answered states"]
    for p in prods:
        _, rule, n = counts(per[p], CURRENT)
        out += ["", f"### {p}", "", f"differs from rule_c on {rule} of {n} answered states", "",
                "| state | choice | confidence | rule_c |", "|---|---|---|---|"]
        for r in per[p]:
            ch, cf = _cell((r["answers"] or {}).get(CURRENT))
            out.append(f"| {r['state']} | {ch if r['answers'] else 'error:' + str(r['error'])} | {cf} | {r['rule_c']} |")
    for c in cands:
        qid = c["qid"]
        dcur, rule, n = counts(allrows, qid)
        shown = doc["products"][first]["questions"] if prods else None
        cq = shown[qid] if shown else c["question"]
        kq = shown[CURRENT] if shown else cur["question"]
        out += ["", f"## {qid}", "", f"rationale: {c['rationale'] or '(none given)'}", "",
                f"differs from CURRENT on {dcur} of {n} answered states; from rule_c on {rule} of {n}", "",
                f"the wording against CURRENT, as sent for {first}:", "",
                "```diff", diff(kq, cq, qid) or "(identical wording)", "```"]
        for p in prods:
            dcur, rule, n = counts(per[p], qid)
            out += ["", f"### {p}", "", f"differs from CURRENT on {dcur} of {n} answered states; from rule_c on {rule} of {n}", "",
                    *landing(per[p], qid, p), "",
                    "| state | choice | confidence | rule_c | current | moved |", "|---|---|---|---|---|---|"]
            for r in per[p]:
                a = r["answers"] or {}
                ch, cf = _cell(a.get(qid))
                cc, _ = _cell(a.get(CURRENT))
                moved = "yes" if a and qid in a and CURRENT in a and a[qid][0] != a[CURRENT][0] else ""
                out.append(f"| {r['state']} | {ch if r['answers'] else 'error:' + str(r['error'])} | {cf} | {r['rule_c']} | {cc} | {moved} |")
    return "\n".join(out) + "\n"


def render(date, cur_name, cur_sha, cands, cur_q, results, proposal_sha=None, writer=None, table_sha=None):
    """The .md for `results` ({product: [row]}, or one product's rows for SOL-USD)."""
    per = results if isinstance(results, dict) else {config.PRODUCT: results}
    return render_doc(table_doc(date, cur_name, cur_sha, cands, cur_q, per, None, proposal_sha, writer), table_sha)


def table_path(md):
    """proposals/<date>.table.json beside proposals/<date>.md."""
    return (md[:-3] if md.endswith(".md") else md) + TABLE_SUFFIX


def md_path(table):
    """proposals/<date>.md beside proposals/<date>.table.json."""
    return (table[:-len(TABLE_SUFFIX)] if table.endswith(TABLE_SUFFIX) else table) + ".md"


def _write(path, data):
    """Written whole beside the target, then renamed over it: a reader never sees half a table."""
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def write(out, doc):
    """proposals/<date>.table.json, then the .md that names its sha. Returns the sha."""
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    raw = dump(doc)
    sha = hashlib.sha256(raw).hexdigest()
    tpath = table_path(out)
    _write(tpath, raw)
    _write(out, render_doc(doc, sha, os.path.basename(tpath)).encode("utf-8"))
    return sha


def read_table(path):
    """(document, sha256 of its bytes) of a .table.json, the bytes read once. ValueError when it does not parse or is
    not this module's document (kind, products, rows)."""
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError) as e:
        raise ValueError(f"{path}: {e}") from None
    if not isinstance(doc, dict) or doc.get("kind") != KIND or not isinstance(doc.get("products"), dict):
        raise ValueError(f"{path}: not a {KIND} document")
    for p, pd in doc["products"].items():
        if (not isinstance(pd, dict) or not isinstance(pd.get("rows"), list) or not isinstance(pd.get("questions"), dict)
                or any(not isinstance(r, dict) or not isinstance(r.get("state"), str) for r in pd["rows"])):
            raise ValueError(f"{path}: product {p!r} has no rows and questions of the documented shape")
    return doc, hashlib.sha256(raw).hexdigest()


def vouched_sha(md):
    """The "table sha256" line of the .md, or None."""
    try:
        with open(md, encoding="utf-8") as fh:
            m = TABLE_SHA_LINE.search(fh.read())
    except OSError:
        return None
    return m.group(1) if m else None


def _date_of(path):
    base = os.path.splitext(os.path.basename(path))[0]
    return base if _DATE.match(base) else base


def main(argv=None):
    ap = argparse.ArgumentParser(prog="policy_table",
                                 description="81 synthetic states per product per candidate; scores nothing against outcomes")
    ap.add_argument("proposal", help="proposals/<date>.json")
    ap.add_argument("--dry", action="store_true", help="print payload count and the first payload; send nothing")
    ap.add_argument("--out", default=None,
                    help="default: <date>.md under the repo's proposals/ (config.PROPOSALS), wherever the json is; "
                         "propose.sh passes --out beside it; the .table.json goes beside the .md")
    ap.add_argument("--prompts", default=None, help="prompts root (tests)")
    ap.add_argument("--writer-model", default=None,
                    help="the model that wrote the proposal, for the table's header (propose.sh passes it)")
    a = ap.parse_args(argv)
    try:
        with open(a.proposal, "rb") as fh:          # read ONCE: the candidates and the sha are of the same bytes
            raw = fh.read()
        cands = parse_candidates(raw, a.proposal)
        cur_name, cur_q, cur_sha = current_action(a.prompts)
        per_qs = {p: questions(cands, cur_q, cur_name, p) for p in config.PRODUCTS}
    except (OSError, ValueError) as e:              # PromptError is a ValueError
        print(f"policy_table: {e}", file=sys.stderr)
        return 1
    if a.dry:
        ps = [pl for p in config.PRODUCTS for pl in payloads(per_qs[p], p)]
        print(f"dry: {len(ps)} payloads, 0 sent")
        print(json.dumps(ps[0], indent=2))
        return 0
    if os.path.exists(config.HALT):                 # PROTOCOL §3.8: HALT stops sends, the nightly's too
        print(f"policy_table: HALT present at {config.HALT}; no sends, no table")
        return 0
    per = run_night([(p, per_qs[p], states(p)) for p in config.PRODUCTS])
    date = _date_of(a.proposal)
    out = a.out or os.path.join(config.PROPOSALS, f"{date}.md")
    doc = table_doc(date, cur_name, cur_sha, cands, cur_q, per, per_qs, hashlib.sha256(raw).hexdigest(), a.writer_model)
    write(out, doc)
    rows = [r for p in per for r in per[p]]
    n_err = sum(1 for r in rows if r["error"])
    print(f"{out}\t{len(rows) - n_err}/{len(rows)} answered" + (" INCOMPLETE" if n_err else ""))
    return EXIT_INCOMPLETE if n_err else 0


if __name__ == "__main__":
    sys.exit(main())

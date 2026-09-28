"""81 synthetic states per candidate wording: what each rewrite of the `action`
question would answer on every state the alphabet can produce.

It scores NOTHING against any logged outcome. The table is a description of a
wording, not a backtest of it: this file never opens data/decisions.jsonl, never
sees a feature, a price or a label, and never picks a candidate. A person reads
the table and runs bin/promote, or does not.

May: enumerate loop.state.all_states() (3^4 = 81 adjective dicts in one fixed order),
render each with state_string (no digit, no position), read proposals/<date>.json and
the CURRENT `action` question, send ONE request per state through loop.jev.ask
carrying every candidate and the current question as separate choice questions
(cand_0 .. cand_{K-1}, current: 81 requests for K+1 wordings, not 81 x (K+1)), and
write proposals/<date>.md: per wording the 81-row table (state, choice, confidence),
the unified diff of its instructions+criteria against CURRENT, the counts of
states where it differs from CURRENT and from rule_c, and where those changes land
(landing(): per adjective, and the CURRENT -> wording moves; which states moved, not
whether a move follows the wording's criteria).
May not: read the log, the key (jev.py holds it), or anything under the crypto
repo; write under prompts/ or data/ (jev.py appends its own ledger row per send;
the one exception is data/HALT on a rejected key, CONTRACT §2 "the caller writes
HALT", the same rule as cycle.py); send anything while data/HALT exists (PROTOCOL
§3.8: HALT stops sends, and these sends never reach decisions.jsonl, so the spend
guard cannot see them; checked before EVERY send, so a HALT a person or the loop
writes mid-table stops the rest); retry beyond jev.py's one, or keep sending into a
limiter (a 429 ends the night; so do MAX_TRANSIENT_RUN transient failures in a row,
MAX_OTHER_RUN other failures in a row, and MAX_ERROR_RUN failures of any kind in a
row, so alternating kinds cannot run to the deadline: 81 states x jev.py's two
attempts would be 162 requests on the loop's own key, the key PROTOCOL §3.6
isolates because a limit or a suspension is the risk); run a candidate whose
criteria are not exactly buy/sell/hold (prompts.question refuses it, so a malformed
proposal sends nothing).
The proposal's bytes are read ONCE: the candidates are parsed from them and the
table's "proposal sha256" line is their hash, so the committed .md vouches for
exactly the json it was built from (bin/promote checks it).
--dry prints the number of would-be payloads and the first one, and sends nothing.

Cost: 81 states x (K+1) questions of ~50 words + a 10-word state; at K=3 that is
~30k input tokens = ~$0.0013 at config.USD_PER_MTOK, under CONTRACT §5's ~$0.005.
Sends are sequential: typical 81 x ~0.5 s = 40 s, and DEADLINE_S bounds the night
when the API is slow -- nothing new is sent after it and the table says INCOMPLETE.
Exit 0 complete or HALT present at the start (nothing sent, no table), 4 INCOMPLETE
(written, some states unanswered: a HALT that appears mid-table is one way), 1 bad
input, 2 usage. --out defaults to <date>.md under the repo's proposals/
(config.PROPOSALS), not beside the json; propose.sh always passes it.
"""
import argparse, collections, difflib, hashlib, json, os, re, sys, time

if __package__ in (None, ""):      # run as a script (CONTRACT §5 names `nightly/<file>.py`), not -m: sys.path[0]
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # is nightly/, so add the repo

from loop import config, jev, prompts, state

DEADLINE_S = 900.0         # 81 x jev.py's worst case (45 s) is an hour; 15 min is 81 x 11 s, ample for
                           # a working API and short enough that a dead one costs one launchd slot
MAX_CANDIDATES = 3         # CONTRACT §5: 1-3 entries
CURRENT = "current"
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
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def states():
    """[(state string, rule_c)] in loop.state.all_states() order: 81 rows, every string
    digit-free by construction (state_string raises otherwise)."""
    return [(state.state_string(adj), state.rule_c(adj)) for adj in state.all_states()]


def load_candidates(path):
    """The proposal's 1-3 candidates, read from the file at `path` (see parse_candidates)."""
    with open(path, "rb") as fh:
        return parse_candidates(fh.read(), path)


def parse_candidates(raw, path):
    """The 1-3 candidates in `raw` (the proposal's bytes; `path` names it in errors), each
    projected onto the wire shape with type 'choice' added (proposals carry none, CONTRACT
    §5); rationale kept for the table. Raises ValueError on any shape fault (a byte that is
    not UTF-8 is one too): a half-valid proposal would send half a table."""
    doc = json.loads(raw.decode("utf-8"))
    c = doc.get("candidates") if isinstance(doc, dict) else None
    if not isinstance(c, list) or not 1 <= len(c) <= MAX_CANDIDATES:
        raise ValueError(f"{path}: candidates must be a list of 1-{MAX_CANDIDATES}")
    out = []
    for i, cand in enumerate(c):
        if not isinstance(cand, dict):
            raise ValueError(f"{path}: candidate {i} is not an object")
        q = prompts.question({**cand, "type": "choice"}, "choice", f"cand_{i}")
        text = q["instructions"] + "".join(q["criteria"].values())
        if any(ch.isdigit() for ch in text):
            raise ValueError(f"{path}: cand_{i} carries a digit; PROMPT.md forbids numbers")
        out.append({"qid": f"cand_{i}", "q": q, "rationale": str(cand.get("rationale", ""))})
    return out


def current_action(root=None):
    """(version name, wire question, sha of the whole version file)."""
    name = prompts.current(root)
    doc = prompts.load(name, root)
    return name, prompts.question(doc.get("action"), "choice", f"{name}.action"), prompts.sha_of(doc)


def questions(cands, cur_q):
    """One dict, sent whole on every state: cand_0..cand_{K-1} then current."""
    qs = {c["qid"]: c["q"] for c in cands}
    qs[CURRENT] = cur_q
    return qs


def payloads(qs):
    return [jev.dry_payload(s, qs) for s, _ in states()]


def _halt(reason):
    """data/HALT, as cycle._halt writes it: a person reads the reason and deletes it."""
    try:
        with open(config.HALT, "w") as fh:
            fh.write(reason + "\n")
    except OSError as e:
        print(f"policy_table: cannot write {config.HALT}: {e}", file=sys.stderr)


def run(qs, ask=None, deadline_s=DEADLINE_S, clock=time.monotonic):
    """One row per state: {"state", "rule_c", "answers": {qid: (choice, confidence)}|None,
    "error": kind|None, "model": str|None}. A fatal kind (no key, no ledger, a 429, key
    rejected -- which also writes data/HALT), MAX_TRANSIENT_RUN transient failures in a
    row, MAX_OTHER_RUN other failures in a row, or MAX_ERROR_RUN failures of any kind in a
    row stop the sending; so does data/HALT, checked before every send (error kind
    "halt"). The remaining rows carry that kind as their error. The deadline is checked
    before each send, never mid-send: jev.py's own timeout bounds a send."""
    ask = ask or jev.ask                 # resolved at call time so tests can patch loop.jev.ask
    t0, stop, out, streak, other, errors = clock(), None, [], 0, 0, 0
    for s, rc in states():
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
        out.append(row)
    return out


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


def landing(results, qid):
    """Where a wording changes CURRENT's answer, over the states where both answered: for each
    adjective, the states it changed out of the answered states that carry that adjective, and the
    CURRENT -> wording moves. For the person who promotes (the digest never carries a table). It
    says which states moved, not whether a move follows the wording's own criteria: that stays a
    person's read, as proposals/2026-09-25.review.md did by hand (cand_0 moved none of the 81
    states; cand_1 moved the 27 vol-violent states, not the vol-normal ones its wording named)."""
    by = {state.state_string(adj): adj for adj in state.all_states()}
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


def render(date, cur_name, cur_sha, cands, cur_q, results, proposal_sha=None):
    n_err = sum(1 for r in results if r["error"])
    answered = [r for r in results if r["answers"]]
    models = sorted({str(r["model"]) for r in answered if r["model"]})
    unnamed = sum(1 for r in answered if not r["model"])
    if unnamed:
        models.append(f"no model named on {unnamed}")
    # cycle.py's rule for the same reply (row "drift": model != config.MODEL): an answer that names
    # no model is drift too, not a pass
    drift = " -- DRIFT, requested " + config.MODEL if any(r["model"] != config.MODEL for r in answered) else ""
    out = [f"# policy table {date}", "",
           f"Eighty-one synthetic states, one request each, carrying {len(cands) + 1} questions. "
           "Nothing here is scored against a logged outcome: the table describes a wording, it does not backtest it.",
           "", f"CURRENT: {cur_name} sha {cur_sha}  ",
           f"proposal sha256: {proposal_sha or '-'}  ",      # the json is not committed; this line, in the committed table, vouches for it
           f"requests: {len(results)}, answered: {len(results) - n_err}, errors: {n_err}"
           + (" -- INCOMPLETE" if n_err else "") + "  ",
           f"model answered: {', '.join(models) or 'none'}{drift}", ""]
    if n_err:
        kinds = sorted({r["error"] for r in results if r["error"]})
        out += [f"error kinds: {', '.join(kinds)}", ""]
    _, rule, n = counts(results, CURRENT)
    out += [f"## {CURRENT} ({cur_name})", "", f"differs from rule_c on {rule} of {n} answered states", "",
            "| state | choice | confidence | rule_c |", "|---|---|---|---|"]
    for r in results:
        ch, cf = _cell((r["answers"] or {}).get(CURRENT))
        out.append(f"| {r['state']} | {ch if r['answers'] else 'error:' + str(r['error'])} | {cf} | {r['rule_c']} |")
    for c in cands:
        qid = c["qid"]
        cur, rule, n = counts(results, qid)
        out += ["", f"## {qid}", "", f"rationale: {c['rationale'] or '(none given)'}", "",
                f"differs from CURRENT on {cur} of {n} answered states; from rule_c on {rule} of {n}", "",
                *landing(results, qid), "",
                "```diff", diff(cur_q, c["q"], qid) or "(identical wording)", "```", "",
                "| state | choice | confidence | rule_c | current |", "|---|---|---|---|---|"]
        for r in results:
            ch, cf = _cell((r["answers"] or {}).get(qid))
            cc, _ = _cell((r["answers"] or {}).get(CURRENT))
            out.append(f"| {r['state']} | {ch if r['answers'] else 'error:' + str(r['error'])} | {cf} | {r['rule_c']} | {cc} |")
    return "\n".join(out) + "\n"


def _date_of(path):
    base = os.path.splitext(os.path.basename(path))[0]
    return base if _DATE.match(base) else base


def main(argv=None):
    ap = argparse.ArgumentParser(prog="policy_table",
                                 description="81 synthetic states per candidate; scores nothing against outcomes")
    ap.add_argument("proposal", help="proposals/<date>.json")
    ap.add_argument("--dry", action="store_true", help="print payload count and the first payload; send nothing")
    ap.add_argument("--out", default=None,
                    help="default: <date>.md under the repo's proposals/ (config.PROPOSALS), wherever the json is; "
                         "propose.sh passes --out beside it")
    ap.add_argument("--prompts", default=None, help="prompts root (tests)")
    a = ap.parse_args(argv)
    try:
        with open(a.proposal, "rb") as fh:          # read ONCE: the candidates and the sha are of the same bytes
            raw = fh.read()
        cands = parse_candidates(raw, a.proposal)
        cur_name, cur_q, cur_sha = current_action(a.prompts)
    except (OSError, ValueError) as e:              # PromptError is a ValueError
        print(f"policy_table: {e}", file=sys.stderr)
        return 1
    qs = questions(cands, cur_q)
    if a.dry:
        ps = payloads(qs)
        print(f"dry: {len(ps)} payloads, 0 sent")
        print(json.dumps(ps[0], indent=2))
        return 0
    if os.path.exists(config.HALT):                 # PROTOCOL §3.8: HALT stops sends, the nightly's too
        print(f"policy_table: HALT present at {config.HALT}; no sends, no table")
        return 0
    results = run(qs)
    date = _date_of(a.proposal)
    out = a.out or os.path.join(config.PROPOSALS, f"{date}.md")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render(date, cur_name, cur_sha, cands, cur_q, results, hashlib.sha256(raw).hexdigest()))
    n_err = sum(1 for r in results if r["error"])
    print(f"{out}\t{len(results) - n_err}/{len(results)} answered" + (" INCOMPLETE" if n_err else ""))
    return EXIT_INCOMPLETE if n_err else 0


if __name__ == "__main__":
    sys.exit(main())

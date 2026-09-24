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
the unified diff of its instructions+criteria against CURRENT, and the counts of
states where it differs from CURRENT and from rule_c.
May not: read the log, the key (jev.py holds it), or anything under the crypto
repo; write under prompts/ or data/ (jev.py appends its own ledger row per send);
retry beyond jev.py's one; run a candidate whose criteria are not exactly
buy/sell/hold (prompts.question refuses it, so a malformed proposal sends nothing).
--dry prints the number of would-be payloads and the first one, and sends nothing.

Cost: 81 states x (K+1) questions of ~50 words + a 10-word state; at K=3 that is
~30k input tokens = ~$0.0013 at config.USD_PER_MTOK, under CONTRACT §5's ~$0.005.
Sends are sequential: typical 81 x ~0.5 s = 40 s, and DEADLINE_S bounds the night
when the API is slow -- nothing new is sent after it and the table says INCOMPLETE.
Exit 0 complete, 4 INCOMPLETE (written, some states unanswered), 1 bad input, 2 usage.
"""
import argparse, difflib, json, os, re, sys, time

from loop import config, jev, prompts, state

DEADLINE_S = 900.0         # 81 x jev.py's worst case (45 s) is an hour; 15 min is 81 x 11 s, ample for
                           # a working API and short enough that a dead one costs one launchd slot
MAX_CANDIDATES = 3         # CONTRACT §5: 1-3 entries
CURRENT = "current"
FATAL_KINDS = ("no-key", "ledger")        # 80 more sends would repeat the same refusal
HALT_STATUS = (401, 403)                  # the key is rejected: same rule as cycle.py's HALT
EXIT_INCOMPLETE = 4
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def states():
    """[(state string, rule_c)] in loop.state.all_states() order: 81 rows, every string
    digit-free by construction (state_string raises otherwise)."""
    return [(state.state_string(adj), state.rule_c(adj)) for adj in state.all_states()]


def load_candidates(path):
    """The proposal's 1-3 candidates, each projected onto the wire shape with type
    'choice' added (proposals carry none, CONTRACT §5); rationale kept for the table.
    Raises ValueError on any shape fault: a half-valid proposal would send half a table."""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
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


def run(qs, ask=None, deadline_s=DEADLINE_S, clock=time.monotonic):
    """One row per state: {"state", "rule_c", "answers": {qid: (choice, confidence)}|None,
    "error": kind|None, "model": str|None}. A fatal kind (no key, no ledger, key rejected)
    stops the sending; the remaining rows carry that kind as their error. The deadline
    is checked before each send, never mid-send: jev.py's own timeout bounds a send."""
    ask = ask or jev.ask                 # resolved at call time so tests can patch loop.jev.ask
    t0, stop, out = clock(), None, []
    for s, rc in states():
        row = {"state": s, "rule_c": rc, "answers": None, "error": None, "model": None}
        if stop:
            row["error"] = stop
        elif clock() - t0 > deadline_s:
            stop = row["error"] = "deadline"
        else:
            try:
                r = ask(s, qs)
                row["answers"] = {qid: (r["answers"][qid].get("choice"), r["answers"][qid].get("confidence"))
                                  for qid in qs}
                row["model"] = r.get("model")
            except jev.JevError as e:
                row["error"] = e.kind
                if e.kind in FATAL_KINDS or e.status in HALT_STATUS:
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


def _cell(a):
    if a is None:
        return "-", "-"
    choice, conf = a
    return str(choice), f"{conf:.2f}" if isinstance(conf, (int, float)) and not isinstance(conf, bool) else "-"


def render(date, cur_name, cur_sha, cands, cur_q, results):
    n_err = sum(1 for r in results if r["error"])
    models = sorted({r["model"] for r in results if r["answers"] and r["model"]})
    drift = " -- DRIFT, requested " + config.MODEL if models and models != [config.MODEL] else ""
    out = [f"# policy table {date}", "",
           f"Eighty-one synthetic states, one request each, carrying {len(cands) + 1} questions. "
           "Nothing here is scored against a logged outcome: the table describes a wording, it does not backtest it.",
           "", f"CURRENT: {cur_name} sha {cur_sha}  ",
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
    ap.add_argument("--out", default=None, help="default: proposals/<date>.md beside the json")
    ap.add_argument("--prompts", default=None, help="prompts root (tests)")
    a = ap.parse_args(argv)
    try:
        cands = load_candidates(a.proposal)
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
    results = run(qs)
    date = _date_of(a.proposal)
    out = a.out or os.path.join(config.PROPOSALS, f"{date}.md")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render(date, cur_name, cur_sha, cands, cur_q, results))
    n_err = sum(1 for r in results if r["error"])
    print(f"{out}\t{len(results) - n_err}/{len(results)} answered" + (" INCOMPLETE" if n_err else ""))
    return EXIT_INCOMPLETE if n_err else 0


if __name__ == "__main__":
    sys.exit(main())

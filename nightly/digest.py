"""What the slow model may read: one UTC day of every product's loop, reduced to words and outcomes (PREREG-v2 §8).

May: read each product's decision log (config.PRODUCTS, each where config.store puts it, under --data when given)
through loop.outcomes.load; keep only the rows carrying this tree's SPEC sha (the v2 SPEC's spec_sha on the tree that
runs the v2 loop), so the switch-day digests never mix v1-code rows in; join every row to its t+h outcome within its
own product (loop.outcomes.join, the 15-minute join); replay arms A, B and C (loop.book) at 0 bps (direction, gross
of fees, the H1 cell) and at the venue's verified retail maker and taker (MAKER_BPS, TAKER_BPS); and write
data/digest-<date>.md: one summary line per product and one pooled over the products, up to DISAGREE_MAX arm-B
disagreement rows over the products, a per-state table of the 81 states per product, the CURRENT `action` question
verbatim with its base token written {BASE}, and the prompt shas.
May not: read the key or name its value, copy a raw log line, or print a single feature value. The model that reads
this file rewrites wording, and PROMPT.md forbids it numbers, so the digest carries none of the numbers the tick
computed; the outcome return, its label and the confidence are the figures it is allowed to reason from. Nothing here
sends anything, and nothing here writes under prompts/. Nothing in the digest is a test.

Arm B. Every B figure -- its replay, its disagreements, its choices in the per-state table -- is read from the rows
whose prompt_b is the version prompts.current(tick_id) names for that row's own tick (PREREG-v2 §8). v1's summary
replayed B over a promotion day's mixed rows; here a promotion that activates inside the UTC day splits B's rows at its
activation tick, and a row that asked any other wording (a hand edit of CURRENT, a stale read) is not B's and is
counted on the summary line instead. A version CURRENT names but that is still pending is invisible: no tick of a
closed day reaches its activation, and the CURRENT question shown is the one current() names now, as the policy table
scores against. A and C are read from every row of the day.

"Disagreement" is with the market, not with arm A: a b_action answer at confidence >= DISAGREE_CONF whose label at
t+h contradicts it, buy then down or sell then up. Those are the rows a rewrite could have changed; a hold, a flat, or
a low-confidence answer says nothing about the wording. Highest confidence first over every product (the state's first
word names the product): the most sure and most wrong is the most informative. Each product's arms are replayed over
its day alone (flat at 00:00Z), so a PnL figure is that day's; the pooled figure is the sum over products (bps of each
product's $1,000 notional).

The per-state table (new in v2): per product, the 81 states in state.all_states() order, each with the live rows
(mode live, absence null) that showed it that day, B's buy / sell / hold on those of them that asked the wording
CURRENT at their tick, the mean ret_h_bps over those with an outcome at the 15-minute join, and the up / down / flat
shares of those outcomes.

Exit 0 when the file was written and the day had rows; 4 when it was written for a day with no row of this tree's
SPEC in any product's log (day zero, an outage, or the day before the switch): propose.sh then has nothing to
propose from and stops before the model is called.
"""
import argparse, collections, datetime, hashlib, json, os, re, sys

if __package__ in (None, ""):      # run as a script (CONTRACT §5 names `nightly/<file>.py`), not -m: sys.path[0]
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # is nightly/, so add the repo

from loop import book, config, dash, outcomes, prompts, state

DISAGREE_CONF = 0.85       # the c85 column's cut (config.CONF_THRESHOLDS[2]); a lower cut would list
                           # answers no column ever acts on
DISAGREE_MAX = 25          # CONTRACT §5: "up to 25"; over every product, enough to read, not a log
ARMS = ("a", "b", "c")     # the arms the summary replays; D (the CURRENT table) is not in §8's digest
COLUMN = "argmax"          # the A/B column the summary replays: the model's bare answer
# PREREG-v2 §6, §8: the summary at 0 bps (direction, gross: the H1 cell) and at the venue's retail maker and taker,
# both read in-account by Alex on 2026-09-27 (ERRATA.md; report.ERRATA_TIER holds the same pair). A round trip at the
# taker is 180 bps against a ~33 bps 15-minute sd, so those two figures mostly count trades; the trade count is the
# same at every fee, since a fee never changes a decision.
MAKER_BPS = 50.0
TAKER_BPS = 90.0
FEES = ((0.0, "direction"), (MAKER_BPS, "venue maker"), (TAKER_BPS, "venue taker"))
CONTRADICTS = {("buy", "down"), ("sell", "up")}
LABELS = ("up", "down", "flat")
EXIT_EMPTY = 4


def yesterday(now=None):
    """The previous UTC day: the nightly runs after midnight UTC over the day just closed."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d")


def _date(s):
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not YYYY-MM-DD: {s!r}") from None


def _prefix(d):
    return d.strftime("%Y%m%d")                     # tick_id is YYYYMMDDTHHMM00Z


def tree_spec_sha():
    """sha256 of this tree's SPEC.md (config.SPEC), as loop.cycle.spec_sha writes it on every row the tree's loop
    makes: after the switch, the v2 SPEC's. "unsealed" when it is absent, as cycle says it."""
    try:
        with open(config.SPEC, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return "unsealed"


def logs(data=None):
    """[(product, decision log path)] for every product in config.PRODUCTS, in its order: where config.store puts it,
    or under `data` (propose.sh's --root) as the dash reads it (dash.store_paths)."""
    return [(p, dash.store_paths(p, data)[0]) for p in config.PRODUCTS]


def split(rows, d):
    """(day rows, join rows). The join needs the rows AFTER the day too: a decision at
    23:59 resolves at 00:14 next day. The whole next day is taken rather than 16
    minutes of it: one string compare per row, and the join is a bisect either way."""
    p, nxt = _prefix(d), _prefix(d + datetime.timedelta(days=1))
    day = [r for r in rows if r["tick_id"].startswith(p)]
    return day, [r for r in rows if r["tick_id"][:8] in (p, nxt)]


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def versions_at(ticks, root=None):
    """{tick_id: prompts.current(tick_id)} for the sorted, distinct `ticks`. current() is monotone in the tick along
    the `replaces` walk (each activation earlier than its successor's), so it is asked at the two ends of a span and the
    span is halved only where they differ: a handful of reads for a day instead of one per tick."""
    out = {}
    if not ticks:
        return out
    stack = [(0, len(ticks) - 1, prompts.current(ticks[0], root), prompts.current(ticks[-1], root))]
    while stack:
        lo, hi, vlo, vhi = stack.pop()
        if vlo == vhi or hi - lo <= 1:
            for i in range(lo, hi + 1):
                out[ticks[i]] = vlo if vlo == vhi or i == lo else vhi
            continue
        mid = (lo + hi) // 2
        vm = prompts.current(ticks[mid], root)
        stack += [(lo, mid, vlo, vm), (mid, hi, vm, vhi)]
    return out


def b_rows(day, vers):
    """The day's rows whose prompt_b is the version current() names for their tick: arm B's rows (PREREG-v2 §8)."""
    return [r for r in day if isinstance(r.get("prompt_b"), str) and r["prompt_b"] == vers.get(r["tick_id"])]


def disagreements(rows, joined):
    """Every arm-B disagreement in `rows` (arm B's rows), most confident first (tick_id, then the state, break ties so
    two runs over one log list the same rows in the same order). The caller cuts to DISAGREE_MAX; the full count goes
    on the summary line."""
    out = []
    for r in rows:
        a = (r.get("answers") or {}).get("b_action")
        if not isinstance(a, dict) or not _num(a.get("confidence")) or a["confidence"] < DISAGREE_CONF:
            continue
        o = joined.get(r["tick_id"]) or outcomes.GAP
        if not isinstance(a.get("choice"), str) or (a["choice"], o["label"]) not in CONTRADICTS:
            continue                                # a list or dict choice (a jev/parse row keeps the answer) is unhashable
        try:
            conf = float(a["confidence"])
        except OverflowError:                       # an integer past a float's range (a jev/parse row keeps it): not a row
            continue                                # the table can show; it raised and lost the night
        out.append({"state": r.get("state") if isinstance(r.get("state"), str) else "?", "choice": a["choice"],
                    "confidence": conf, "ret_h_bps": o["ret_h_bps"], "label": o["label"], "tick_id": r["tick_id"]})
    out.sort(key=lambda x: (-x["confidence"], x["tick_id"], x["state"]))
    return out


def occupancy(day):
    """Per dimension, the share of each word over the rows that carry adjectives."""
    adjs = [r["adj"] for r in day if isinstance(r.get("adj"), dict)]
    parts = []
    for dim in state.DIMS:
        c = collections.Counter(a.get(dim) for a in adjs)
        words = " ".join(f"{w} {100 * c[w] / len(adjs):.0f}%" if adjs else f"{w} -" for w in state.ALPHABET[dim])
        parts.append(f"{dim} {words}")
    return "; ".join(parts)


def arms(day, brows, fee):
    """{arm: (fills, pnl_bps)} at `fee`, the day replayed from flat: A and C over every row of the day, B over its
    own rows."""
    out = {}
    for arm in ARMS:
        rep = book.replay(brows if arm == "b" else day, None, arm, COLUMN, fee)
        out[arm] = (len(rep["trades"]), rep["equity"][-1][1] if rep["equity"] else 0.0)
    return out


def _live(r):
    return r.get("mode") == "live" and r.get("absence") is None


def per_state(day, brows, joined, product):
    """([(state string, rows seen, (B buy, sell, hold) or None, mean ret_h_bps or None, {label: share} or None)] over
    the 81 states rendered with the product's base, in state.all_states() order; the count of live rows whose state is
    none of them, a word outside the alphabet)."""
    names = [state.state_string(a, config.base(product)) for a in state.all_states()]
    seen = {s: [] for s in names}
    other = 0
    bids = {id(r) for r in brows}
    for r in day:
        if not _live(r):
            continue
        s = r.get("state")
        if isinstance(s, str) and s in seen:
            seen[s].append(r)
        else:
            other += 1
    out = []
    for s in names:
        rs = seen[s]
        ch = collections.Counter()
        for r in rs:
            a = (r.get("answers") or {}).get("b_action") if id(r) in bids else None
            if isinstance(a, dict) and isinstance(a.get("choice"), str) and a["choice"] in book.INTENTS:
                ch[a["choice"]] += 1
        outs = [o for o in ((joined.get(r["tick_id"]) or outcomes.GAP) for r in rs) if o["label"] in LABELS]
        mean = sum(o["ret_h_bps"] for o in outs) / len(outs) if outs else None
        rates = {k: sum(o["label"] == k for o in outs) / len(outs) for k in LABELS} if outs else None
        out.append((s, len(rs), tuple(ch[k] for k in book.INTENTS) if sum(ch.values()) else None, mean, rates))
    return out, other


def _fees_s():
    return " / ".join(f"{f:g} bps ({w})" for f, w in FEES)


def _arms_s(pnl):
    """'A 3 trades +1.0 / -149.0 / -269.0 bps, B ...': per arm the fills and the PnL at each fee of FEES."""
    return ", ".join(f"{arm.upper()} {pnl[0][arm][0]} trades " + " / ".join(f"{p[arm][1]:+.1f}" for p in pnl) + " bps"
                     for arm in ARMS)


def summarise(product, day, brows, joined, vers):
    """One product's figures: the counts, the replays at every fee, the disagreements, B's versions."""
    answered = sum(1 for r in day if isinstance(r.get("answers"), dict))
    absent = collections.Counter(r["absence"] for r in day if r.get("absence"))
    priced = [r for r in day if _num(r.get("mid"))]
    filled = sum(1 for r in priced if (joined.get(r["tick_id"]) or outcomes.GAP)["absence"] is None)
    other = sum(1 for r in day if isinstance(r.get("prompt_b"), str) and r["prompt_b"] != vers.get(r["tick_id"]))
    return {"product": product, "day": day, "ticks": len(day), "answered": answered, "absent": absent,
            "priced": len(priced), "filled": filled, "pnl": [arms(day, brows, f) for f, _ in FEES],
            "dis": disagreements(brows, joined), "b_vers": collections.Counter(r["prompt_b"] for r in brows),
            "b_other": other}


def summary_line(label, s):
    b = ", ".join(f"{k} {v}" for k, v in sorted(s["b_vers"].items())) or "none"
    return (f"{label} | ticks {s['ticks']}, answered {s['answered']}, absence "
            f"{' '.join(f'{k}:{v}' for k, v in sorted(s['absent'].items())) or 'none'}, "
            f"outcomes joined {s['filled']}/{s['priced']} | occupancy {occupancy(s['day'])} | "
            f"column {COLUMN}, paper PnL at {_fees_s()}: {_arms_s(s['pnl'])} | "
            f"arm B read from prompt_b {b} (rows asking another wording: {s['b_other']}) | B disagreements {len(s['dis'])}")


def pooled(sums):
    """The products' figures added up: counts, fills and PnL summed (each product replayed on its own), occupancy over
    every product's rows."""
    pnl = []
    for i in range(len(FEES)):
        pnl.append({arm: (sum(s["pnl"][i][arm][0] for s in sums), sum(s["pnl"][i][arm][1] for s in sums)) for arm in ARMS})
    return {"day": [r for s in sums for r in s["day"]], "ticks": sum(s["ticks"] for s in sums),
            "answered": sum(s["answered"] for s in sums), "absent": sum((s["absent"] for s in sums), collections.Counter()),
            "priced": sum(s["priced"] for s in sums), "filled": sum(s["filled"] for s in sums), "pnl": pnl,
            "dis": [x for s in sums for x in s["dis"]], "b_vers": sum((s["b_vers"] for s in sums), collections.Counter()),
            "b_other": sum(s["b_other"] for s in sums)}


def _cell3(t):
    return " / ".join(str(x) for x in t) if t else "-"


def _pct(x):
    return f"{100 * x:.0f}%"


def state_table(product, rows, other):
    out = [f"## {product}: the 81 states that day", "",
           "rows: live rows showing the state; B: buy / sell / hold on those that asked the wording CURRENT at their tick; "
           "mean ret_h_bps and up / down / flat: over those with an outcome at the 15-minute join", "",
           "| state | rows | B buy / sell / hold | mean ret_h_bps | up / down / flat |", "|---|---|---|---|---|"]
    for s, n, ch, mean, rates in rows:
        out.append(f"| {s} | {n} | {_cell3(ch)} | {'-' if mean is None else f'{mean:+.1f}'} | "
                   f"{'-' if rates is None else ' / '.join(_pct(rates[k]) for k in LABELS)} |")
    if other:
        out += ["", f"({other} live row(s) showed a word outside the alphabet: in no state above)"]
    return out


def _base_token(action, version):
    """The action question as the file holds it, its product written {BASE}: in v1/v2 the whole word SOL is the base
    placeholder (prompts.py); v3 and later already carry the literal {BASE}."""
    if prompts.placeholder(version) != prompts.LEGACY_TOKEN:
        return action
    word = re.compile(r"\b" + re.escape(prompts.LEGACY_TOKEN) + r"\b")
    sub = lambda t: word.sub(prompts.BASE_TOKEN, t) if isinstance(t, str) else t
    out = dict(action)
    out["instructions"] = sub(action.get("instructions"))
    if isinstance(action.get("criteria"), dict):
        out["criteria"] = {k: sub(v) for k, v in action["criteria"].items()}
    return out


def render(d, sums, cur_name, cur_doc, sha_a, shas_b, skipped):
    pool = pooled(sums)
    dis = sorted(pool["dis"], key=lambda x: (-x["confidence"], x["tick_id"], x["state"]))
    shown = dis[:DISAGREE_MAX]
    note = "; ".join(f"{s['product']} {n} row(s) of another spec_sha not read" for s, n in zip(sums, skipped) if n)
    out = [f"# digest {d.isoformat()}", "", f"{d.isoformat()} UTC, the rows of this tree's SPEC" + (f"; {note}" if note else ""),
           ""]
    out += [summary_line(s["product"], s) for s in sums]
    out += [summary_line(f"pooled over {len(sums)} product{'s' if len(sums) != 1 else ''} (sums)", pool), "",
            f"## arm B disagreements (confidence >= {DISAGREE_CONF:g}, label at t+h contradicts the "
            f"choice; {len(shown)} of {len(dis)} shown over the products, highest confidence first)", "",
            "| state | choice | confidence | ret_h_bps | label |", "|---|---|---|---|---|"]
    out += [f"| {x['state']} | {x['choice']} | {x['confidence']:.2f} | {x['ret_h_bps']:+.1f} | {x['label']} |"
            for x in shown]
    if not shown:
        out.append("| (none) | | | | |")
    for s in sums:
        rows, other = s["states"]
        out += [""] + state_table(s["product"], rows, other)
    out += ["", f"## CURRENT action question ({cur_name}, the version arm B asks now), verbatim, its product written "
            f"{prompts.BASE_TOKEN}", "", "```json",
            json.dumps(_base_token(cur_doc["action"], cur_name), indent=2, ensure_ascii=False), "```", "", "## shas", "",
            f"prompt_a {config.FROZEN_A} {sha_a}  "]
    out += [f"prompt_b {v} {h}  " for v, h in shas_b]
    return "\n".join(out) + "\n"


def build(d, data=None, prompts_root=None, now_tick=None, spec=None):
    """(text, n_rows): n_rows the day's rows of this tree's SPEC over every product. A missing log is that product's
    day zero: no rows, not an error. `now_tick` (a tick_id; None: this minute) is the tick the CURRENT question is read
    at; `spec` the spec_sha kept (None: this tree's)."""
    spec = spec or tree_spec_sha()
    sums, skipped, bad_n = [], [], 0
    for product, path in logs(data):
        bad = []
        rows = outcomes.load(path, bad) if os.path.exists(path) else []
        bad_n += len(bad)
        kept = [r for r in rows if r.get("spec_sha") == spec]
        day, joinrows = split(kept, d)
        skipped.append(len(split(rows, d)[0]) - len(day))
        joined = outcomes.join(joinrows, config.HORIZON_S)
        vers = versions_at(sorted({r["tick_id"] for r in day}), prompts_root)
        brows = b_rows(day, vers)
        s = summarise(product, day, brows, joined, vers)
        s["states"] = per_state(day, brows, joined, product)
        sums.append(s)
    cur_name = prompts.current(now_tick, prompts_root)
    cur_doc = prompts.load(cur_name, prompts_root)
    names = sorted({v for s in sums for v in s["b_vers"]} | {cur_name}, key=lambda v: int(v[1:]))
    shas_b = [(v, prompts.sha(v, prompts_root)) for v in names]
    text = render(d, sums, cur_name, cur_doc, prompts.sha(config.FROZEN_A, prompts_root), shas_b, skipped)
    if bad_n:
        text += f"\n({bad_n} malformed log line(s) skipped)\n"
    return text, sum(s["ticks"] for s in sums)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="digest", description="data/digest-<date>.md for the slow model (PREREG-v2 §8)")
    ap.add_argument("--date", type=_date, default=None, help="UTC day, default: yesterday")
    ap.add_argument("--data", default=None, help="the data/ holding every product's store (default: the repo's; "
                    "propose.sh --root passes its own)")
    ap.add_argument("--out", default=None, help="default: data/digest-<date>.md")
    ap.add_argument("--prompts", default=None, help="prompts root (tests)")
    a = ap.parse_args(argv)
    d = a.date or datetime.date.fromisoformat(yesterday())
    out = a.out or os.path.join(a.data or config.DATA, f"digest-{d.isoformat()}.md")
    text, n = build(d, a.data, a.prompts)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"{out}\t{n} ticks")
    return EXIT_EMPTY if n == 0 else 0


if __name__ == "__main__":
    sys.exit(main())

"""What the slow model may read: one UTC day of the loop, reduced to words and outcomes.

May: read data/decisions.jsonl through loop.outcomes.load, join every row to its t+h
outcome (loop.outcomes.join), replay the three arms (loop.book) at 0 bps (the H1 fee,
gross: direction) and at the venue's own taker fee (the realistic cost), and write
data/digest-<date>.md: ONE summary line, up to DISAGREE_MAX arm-B disagreement rows,
the CURRENT `action` question verbatim, and both prompt shas.
May not: read the key or name its value, copy a raw log line, or print a single
feature value. The model that reads this file rewrites wording, and PROMPT.md forbids
it numbers, so the digest carries none of the numbers the tick computed; the
outcome return and the confidence are the two figures it is allowed to reason from.
Nothing here sends anything, and nothing here writes under prompts/.

"Disagreement" is with the market, not with arm A: a b_action answer at confidence
>= DISAGREE_CONF whose label at t+h contradicts it, buy then down or sell then up.
Those are the rows a rewrite could have changed; a hold, a flat, or a low-confidence
answer says nothing about the wording. Highest confidence first: the most sure and
most wrong is the most informative. The arms are replayed over the day alone
(flat at 00:00), so the PnL figure is that day's, not the cumulative curve.

Exit 0 when the file was written and the day had rows; 4 when it was written for a
day with no rows at all (day zero, or an outage): propose.sh then has nothing to
propose from and stops before the model is called.
"""
import argparse, collections, datetime, json, os, sys

if __package__ in (None, ""):      # run as a script (CONTRACT §5 names `nightly/<file>.py`), not -m: sys.path[0]
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # is nightly/, so add the repo

from loop import book, config, outcomes, prompts, state

DISAGREE_CONF = 0.85       # the c85 column's cut (config.CONF_THRESHOLDS[2]); a lower cut would list
                           # answers no column ever acts on
DISAGREE_MAX = 25          # CONTRACT §5: "up to 25"; ~1.7% of a full day, enough to read, not a log
COLUMN = "argmax"          # the A/B column the summary replays: the model's bare answer. PREREG names
                           # the primary cell; until it does the digest shows the column every other
                           # column is derived from
# The summary shows each arm's paper PnL twice, labelled (2026-09-24, decided by Alex): at
# FEE_BPS_PRIMARY = 0 bps, the H1 cell, where a difference is direction net of the spread (a
# round trip still pays one spread, ~0.9-1.7 bps, so the trade count is printed beside it); and at the venue's
# FEE_BPS_VENUE = 120 bps taker, where a round trip is 240 bps against a ~33 bps 15-min sd and
# the figure mostly counts trades. The trade count is the same at both: fees never change a decision.
FEES = ((config.FEE_BPS_PRIMARY, "direction"), (config.FEE_BPS_VENUE, "venue fee"))
CONTRADICTS = {("buy", "down"), ("sell", "up")}
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


def split(rows, d):
    """(day rows, join rows). The join needs the rows AFTER the day too: a decision at
    23:59 resolves at 00:14 next day. The whole next day is taken rather than 16
    minutes of it: one string compare per row, and the join is a bisect either way."""
    p, nxt = _prefix(d), _prefix(d + datetime.timedelta(days=1))
    day = [r for r in rows if r["tick_id"].startswith(p)]
    return day, [r for r in rows if r["tick_id"][:8] in (p, nxt)]


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def on_current(day, cur_name):
    """The day's rows whose arm B answered the CURRENT wording. A promotion mid-day (v2 on
    2026-09-26 at 22:21Z) leaves rows of the superseded wording before it; those are not arm B
    on CURRENT and are never shown to the slow model as if they were. A row without a prompt_b
    name (a fixture) is kept."""
    return [r for r in day if not isinstance(r.get("prompt_b"), str) or r["prompt_b"] == cur_name]


def versions(day):
    return collections.Counter(str(r.get("prompt_b")) for r in day if isinstance(r.get("prompt_b"), str))


def disagreements(day, joined, cur_name=None):
    """Every arm-B disagreement of the day, most confident first (tick_id breaks ties so
    two runs over one log list the same rows in the same order), over the CURRENT wording's
    rows only when cur_name is given. The caller cuts to DISAGREE_MAX; the full count goes on
    the summary line."""
    out = []
    for r in (on_current(day, cur_name) if cur_name else day):
        a = (r.get("answers") or {}).get("b_action")
        if not isinstance(a, dict) or not _num(a.get("confidence")) or a["confidence"] < DISAGREE_CONF:
            continue
        o = joined.get(r["tick_id"]) or outcomes.GAP
        if not isinstance(a.get("choice"), str) or (a["choice"], o["label"]) not in CONTRADICTS:
            continue                                # a list or dict choice (a jev/parse row keeps the answer) is unhashable
        out.append({"state": r.get("state") or "?", "choice": a["choice"], "confidence": float(a["confidence"]),
                    "ret_h_bps": o["ret_h_bps"], "label": o["label"], "tick_id": r["tick_id"]})
    out.sort(key=lambda x: (-x["confidence"], x["tick_id"]))
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


def arms(day, fee):
    """{arm: (trades, pnl_bps)} at `fee`, the day replayed from flat."""
    out = {}
    for arm in book.ARMS:
        rep = book.replay(day, None, arm, COLUMN, fee)
        out[arm] = (len(rep["trades"]), rep["equity"][-1][1] if rep["equity"] else 0.0)
    return out


def summary(d, day, joined, dis, cur_name=None):
    answered = sum(1 for r in day if isinstance(r.get("answers"), dict))
    vers = versions(day)
    ver_s = ""
    if cur_name and any(k != cur_name for k in vers):
        ver_s = (" | prompt_b " + ", ".join(f"{k} {v}" for k, v in sorted(vers.items()))
                 + f" (arm B is read from the {cur_name} rows only; the other rows answered a superseded wording)")
    absent = collections.Counter(r["absence"] for r in day if r.get("absence"))
    priced = [r for r in day if _num(r.get("mid"))]
    filled = sum(1 for r in priced if (joined.get(r["tick_id"]) or outcomes.GAP)["absence"] is None)
    (f0, w0), (fv, wv) = FEES
    gross, net = arms(day, f0), arms(day, fv)
    arm_s = ", ".join(f"{arm.upper()} {gross[arm][0]} trades {gross[arm][1]:+.1f} / {net[arm][1]:+.1f} bps"
                      for arm in gross)
    return (f"{d.isoformat()} | ticks {len(day)}, answered {answered}, absence "
            f"{' '.join(f'{k}:{v}' for k, v in sorted(absent.items())) or 'none'}, "
            f"outcomes joined {filled}/{len(priced)} | occupancy {occupancy(day)} | "
            f"column {COLUMN}, paper PnL at {f0:g} bps ({w0}) / at {fv:g} bps ({wv}): {arm_s}"
            f" | B disagreements {len(dis)}{ver_s}")


def render(d, day, joined, cur_name, cur_doc, sha_a, sha_b):
    dis = disagreements(day, joined, cur_name)
    shown = dis[:DISAGREE_MAX]
    out = [f"# digest {d.isoformat()}", "", summary(d, day, joined, dis, cur_name), "",
           f"## arm B disagreements (confidence >= {DISAGREE_CONF:g}, label at t+h contradicts the "
           f"choice; {len(shown)} of {len(dis)} shown, highest confidence first)", "",
           "| state | choice | confidence | ret_h_bps | label |", "|---|---|---|---|---|"]
    out += [f"| {x['state']} | {x['choice']} | {x['confidence']:.2f} | {x['ret_h_bps']:+.1f} | {x['label']} |"
            for x in shown]
    if not shown:
        out.append("| (none) | | | | |")
    out += ["", f"## CURRENT action question ({cur_name}), verbatim", "", "```json",
            json.dumps(cur_doc["action"], indent=2, ensure_ascii=False), "```", "", "## shas", "",
            f"prompt_a v1 {sha_a}  ", f"prompt_b {cur_name} {sha_b}", ""]
    return "\n".join(out)


def build(d, log_path, prompts_root=None):
    """(text, n_rows). A missing log is day zero: an empty digest, not an error."""
    bad = []
    rows = outcomes.load(log_path, bad) if os.path.exists(log_path) else []
    day, joinrows = split(rows, d)
    joined = outcomes.join(joinrows, config.HORIZON_S)
    cur_name = prompts.current(prompts_root)
    cur_doc = prompts.load(cur_name, prompts_root)
    text = render(d, day, joined, cur_name, cur_doc, prompts.sha("v1", prompts_root), prompts.sha_of(cur_doc))
    if bad:
        text += f"\n({len(bad)} malformed log line(s) skipped)\n"
    return text, len(day)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="digest", description="data/digest-<date>.md for the slow model")
    ap.add_argument("--date", type=_date, default=None, help="UTC day, default: yesterday")
    ap.add_argument("--log", default=config.DECISIONS, help="decisions.jsonl (default: data/)")
    ap.add_argument("--out", default=None, help="default: data/digest-<date>.md")
    ap.add_argument("--prompts", default=None, help="prompts root (tests)")
    a = ap.parse_args(argv)
    d = a.date or datetime.date.fromisoformat(yesterday())
    out = a.out or os.path.join(config.DATA, f"digest-{d.isoformat()}.md")
    text, n = build(d, a.log, a.prompts)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"{out}\t{n} ticks")
    return EXIT_EMPTY if n == 0 else 0


if __name__ == "__main__":
    sys.exit(main())

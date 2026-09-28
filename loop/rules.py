"""Action-rule columns from ONE logged answer set. Pure; the measurement, not a decision.

May: turn the four answers of one tick (action, skip, up15, down15) into the column
dict of CONTRACT §2, one entry per rule, every rule a function of that answer alone.
May not: read or write anything, call anything, know a position, or act on a value
it computes — a column is something the report compares, never something the tick
obeys. Every cut is imported from config.py: 0.99 is the one measured tail (JEV
PROTOCOL 2.2); 0.50/0.70/0.85 are the unmeasured band this project exists to measure.

Null answers → null_columns(): every column None, keys intact, for a caller that asks. The
tick's dry, HALT and absence rows keep new_row's `columns: {a: null, b: null}` (SPEC §2) and
book._intent reads both shapes; the report joins on keys, never on presence.
Missing optional fields read as no signal: confidence → 0.0 (every c* holds),
probabilities → {} (pbuy holds), noul → 0.0 (no veto, no tail). A choice outside
buy/sell/hold is refused: an intent the book cannot map must not reach the log. So is a
field present with a value no cut can read (ValueError, or TypeError/AttributeError for a
wrong type): a bool (float(True) is 1.0, which passes c99), NaN (fails every cut, a silent
hold) or an infinity. cycle.py logs every refusal as jev/parse with the answer kept.
"""
import math

from loop import config

BUY, SELL, HOLD = "buy", "sell", "hold"
CHOICES = (BUY, SELL, HOLD)


def _cname(k):
    return "c%d" % round(k * 100)                        # 0.50 → "c50"; the name IS the constant


CONF_COLUMNS = tuple(_cname(k) for k in config.CONF_THRESHOLDS)   # c50 c70 c85 c99
VETO_COLUMNS = tuple(c + "v" for c in CONF_COLUMNS)                # c50v c70v c85v c99v
PBUY_COLUMN = "pbuy%d" % round(config.PBUY * 100)                  # pbuy60
COLUMNS = ("argmax",) + CONF_COLUMNS + VETO_COLUMNS + (PBUY_COLUMN, "noultail")


def null_columns():
    """The shape with nothing in it: what a dry or absent tick logs for each arm."""
    return {c: None for c in COLUMNS}


def _real(v, what):
    """float(v) for a cut to compare, or ValueError: a bool or a non-finite number is not
    a reading. A missing field arrives here as the caller's default, 0.0."""
    if isinstance(v, bool):
        raise ValueError("%s is a bool (%r)" % (what, v))
    try:
        x = float(v)                                       # None, a list: TypeError; "x": ValueError
    except OverflowError:                                  # an integer past float range: not finite either
        raise ValueError("%s is past float range" % what) from None
    if not math.isfinite(x):
        raise ValueError("%s is not finite (%r)" % (what, v))
    return x


def columns(action_answer, skip_answer, up15, down15):
    """CONTRACT §2 Rule columns, in its key order. Every comparison is `>=`: a confidence
    exactly on a cut passes it, a skip exactly at VETO_NOUL vetoes, a noul exactly at
    NOUL_TAIL is in the tail — the same reading the JEV CLI gives its 0.99."""
    if action_answer is None or skip_answer is None or up15 is None or down15 is None:
        return null_columns()
    choice = action_answer["choice"]
    if choice not in CHOICES:
        raise ValueError("choice %r not in %s" % (choice, CHOICES))
    conf = _real(action_answer.get("confidence", 0.0), "confidence")
    probs = action_answer.get("probabilities") or {}
    veto = _real(skip_answer.get("noul", 0.0), "skip.noul") >= config.VETO_NOUL
    up, down = _real(up15.get("noul", 0.0), "up15.noul"), _real(down15.get("noul", 0.0), "down15.noul")
    out = {"argmax": choice}
    for k, name in zip(config.CONF_THRESHOLDS, CONF_COLUMNS):
        gated = choice if conf >= k else HOLD
        out[name] = gated
        out[name + "v"] = HOLD if veto else gated          # the veto is a hold, never a sell
    p_buy, p_sell = _real(probs.get(BUY, 0.0), "probabilities.buy"), _real(probs.get(SELL, 0.0), "probabilities.sell")
    out[PBUY_COLUMN] = BUY if p_buy >= config.PBUY else SELL if p_sell >= config.PBUY else HOLD
    # up15 is tested first, as CONTRACT §2 lists it; both ≥ 0.99 at once is a contradiction
    # the model should not produce, and the contract's order settles it rather than a coin.
    out["noultail"] = BUY if up >= config.NOUL_TAIL else SELL if down >= config.NOUL_TAIL else HOLD
    return {c: out[c] for c in COLUMNS}


def for_arm(answers, arm):
    """The row's `columns[arm]`: arm "a" reads a_action, "b" reads b_action; skip, up15
    and down15 are one answer shared by both arms (one request, one state). None in →
    null_columns() out (the tick itself never calls this on its dry or absence paths)."""
    if answers is None:
        return null_columns()
    return columns(answers.get(arm + "_action"), answers.get("skip"),
                   answers.get("up15"), answers.get("down15"))

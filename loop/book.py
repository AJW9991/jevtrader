"""Paper execution, replayed from the decision log. Pure: no I/O, no clock, no
network, no randomness. The same rows and the same fee constant give the same
numbers, which is what lets `make report` re-run one log at every fee in
config.FEE_BPS_COLUMNS.

May: map one logged intent onto the current position at that row's bid/ask,
mark the position to that row's mid, and difference two arms tick by tick.
May not: read a file, look at a confidence, choose a column, or see a row's
future — the mark at t uses t's mid only; the t+h join is outcomes.py's job.

Units: qty in SOL, prices and fees in USD, every pnl figure in bps of
config.NOTIONAL_USD so that a cell in the report compares arms on the same
1000 USD paper order whatever the entry price was.

pnl on a tick is computed DIRECTLY, not as equity_t - equity_{t-1}:
  carried position     qty * (mid_t - mid_prev)
  open at ask          qty * (mid_t - ask) - fee
  close at bid         qty * (bid - mid_prev) - fee
The equity difference would be identical in exact arithmetic, but two arms with
the same position and different cash histories round differently, and the
paired test needs d_t == 0.0 exactly wherever the arms carry the same position
through a tick.
"""
import math

from loop import config

NOTIONAL = config.NOTIONAL_USD
INTENTS = ("buy", "sell", "hold")      # buy = want long, sell = want flat, hold = no change
ARMS = ("a", "b", "c", "d")            # a/b read row["columns"][arm][column]; c reads row["rule_c"];
                                       # d reads row["columns"]["d"], the CURRENT table's answer, at argmax only
D_COLUMN = "argmax"                    # arm D's table holds the action choice alone (PREREG-v2 §6, §10)


def _px(x):
    """A usable price: a finite positive number. bool is an int in Python and
    a null field arrives as None; neither may become a fill."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def apply(pos, intent, bid, ask, fee_bps):
    """(pos', fill|None). pos is None (flat) or {"qty", "entry"}; fill is
    {"side", "price", "qty", "fee"}. Only two of the six (pos, intent)
    combinations trade; the rest return pos unchanged and None."""
    if intent not in INTENTS:
        raise ValueError(f"intent {intent!r} not in {INTENTS}")
    if intent == "buy" and pos is None:
        if not _px(ask):
            raise ValueError(f"cannot open at ask {ask!r}")
        qty = NOTIONAL / ask                   # buy exactly NOTIONAL worth at the offer
        fee = NOTIONAL * fee_bps / 1e4         # taker fee on the filled value, which IS the notional here
        return {"qty": qty, "entry": ask}, {"side": "buy", "price": ask, "qty": qty, "fee": fee}
    if intent == "sell" and pos is not None:
        if not _px(bid):
            raise ValueError(f"cannot close at bid {bid!r}")
        qty = pos["qty"]
        # The venue charges on the filled value qty*bid, not on the 1000 USD
        # opened: at a 1c spread on ~$200 SOL the two differ by 0.5 bps of the
        # fee, ~0.006 bps at the 120 bps venue fee. Immaterial, but the exact one is free.
        fee = qty * bid * fee_bps / 1e4
        return None, {"side": "sell", "price": bid, "qty": qty, "fee": fee}
    return pos, None


def _null(x):
    """An arm's model columns absent, or the null_columns() shape (argmax null)."""
    return x is None or (isinstance(x, dict) and x.get("argmax") is None)


def _answered(row):
    """Whether the row carries a decision at all: a live row with no absence whose columns.a and
    columns.b are not both null. On any other row every arm, C and D included, is a forced hold."""
    if row.get("absence") is not None or row.get("mode") != "live":
        return False
    cols = row.get("columns") or {}
    return not (_null(cols.get("a")) and _null(cols.get("b")))


def _intent(row, arm, column):
    """The logged intent for this arm on this row, or None when the row
    carries no decision for it (absence set, not a live row, columns null).
    A dry row is a forced hold for EVERY arm, C included: it carries rule_c but
    no model columns, so letting C act on it would hand C a trade A and B could
    never make (a `make dry` between two live ticks would manufacture a B-C
    disagreement). Same rule as an outage.
    Arm D (PREREG-v2 §10) reads columns.d, the CURRENT table's answer for the state, and has no
    column but argmax: any other column raises, on every row. The every-arm forced hold applies
    to D; a null columns.d on an otherwise answered row (no table, a refused table, a state the
    table lacks) is a hold for D only, counted in D's forced holds."""
    if arm == "d" and column != D_COLUMN:
        raise ValueError(f"arm d has only the {D_COLUMN!r} column (its table holds the action choice alone), not {column!r}")
    if not _answered(row):
        return None                            # SPEC §10: null columns are a forced hold for EVERY arm, C included.
                                               # cycle.py writes that shape only with absence set or in dry mode, so
                                               # on a live row it is a writer bug, and C must not get a trade A and
                                               # B could never make (2026-09-28, review). One arm's columns null with
                                               # the other's present is not a shape the tick writes; only that arm holds.
    if arm == "c":
        return row.get("rule_c")
    cols = row.get("columns") or {}
    if arm == "d":
        return cols.get("d")                   # null (or a v1 row with no d key): D alone holds
    cols = cols.get(arm)
    if cols is None:
        return None
    if column not in cols:                     # a typo'd column would replay as all-hold; make it loud
        raise KeyError(f"column {column!r} not in row {row.get('tick_id')!r} arm {arm!r}")
    return cols[column]


def _order(row):
    return (row.get("tick_id") or "", row.get("ts_rx") or "")


def replay(rows, outcomes, arm, column, fee_bps):
    """Walk rows in tick order applying the arm's intent at each row's bid/ask
    and marking to its mid. Returns
      {"equity": [(tick_id, equity_bps)], "trades": [{"tick_id","side","price","qty","fee"}],
       "pnl_bps_per_tick": {tick_id: bps}, "position": {tick_id: qty after the tick},
       "forced_hold": n}
    A row with absence set, a dry row, null columns, or an unpriced book is a
    "hold" for every arm (so neither an outage nor a dry run ever manufactures a
    disagreement) and is counted
    in forced_hold. The position is carried through it: a priced forced hold marks
    that position to its mid (SPEC §10; so d_t is not 0 there when the arms hold
    different positions), an unpriced one adds 0.0, and the move across a gap lands
    on the first priced tick after it.
    `outcomes` is accepted for the contract's signature; a mark-to-mid book
    needs no t+h join, and using one here would let t see t+h."""
    if arm not in ARMS:
        raise ValueError(f"arm {arm!r} not in {ARMS}")
    if arm == "d" and column != D_COLUMN:      # loud on an empty log too, as _intent is on every row
        raise ValueError(f"arm d has only the {D_COLUMN!r} column, not {column!r}")
    if outcomes is not None and not isinstance(outcomes, dict):
        raise TypeError("outcomes must be the dict from outcomes.join() or None")
    pos, last_mid, equity, forced = None, None, 0.0, 0
    pnl, position, eq, trades = {}, {}, [], []
    for row in sorted(rows, key=_order):
        tid = row.get("tick_id")
        priced = all(_px(row.get(k)) for k in ("bid", "ask", "mid"))
        intent = _intent(row, arm, column) if priced else None
        if intent is None:
            intent, forced = "hold", forced + 1
        if not priced:
            usd = 0.0
        else:
            bid, ask, mid = row["bid"], row["ask"], row["mid"]
            pos2, fill = apply(pos, intent, bid, ask, fee_bps)
            if fill is None:
                usd = pos["qty"] * (mid - last_mid) if pos else 0.0   # literal 0.0: 0*negative is -0.0
            elif fill["side"] == "buy":
                usd = fill["qty"] * (mid - ask) - fill["fee"]
            else:
                usd = fill["qty"] * (bid - last_mid) - fill["fee"]
            if fill is not None:
                trades.append({"tick_id": tid, **fill})
            pos, last_mid = pos2, mid
        bps = usd * 1e4 / NOTIONAL
        equity += bps
        if tid in pnl:                         # two rows one minute (launchd double-fire: the second is
            pnl[tid] += bps                    # an absence "lock" row, pnl 0.0); fold, never overwrite
            eq[-1] = (tid, equity)
        else:
            pnl[tid] = bps
            eq.append((tid, equity))
        position[tid] = pos["qty"] if pos else 0.0
    return {"equity": eq, "trades": trades, "pnl_bps_per_tick": pnl,
            "position": position, "forced_hold": forced}


def paired(rows, outcomes, x, y, column, fee_bps):
    """[(tick_id, d_t)] with d_t = pnl_x - pnl_y in bps, tick order. Both arms
    see the same rows, so the key sets are identical; d_t is exactly 0.0 on any
    tick both arms carry the same position into and out of."""
    px = replay(rows, outcomes, x, column, fee_bps)["pnl_bps_per_tick"]
    py = replay(rows, outcomes, y, column, fee_bps)["pnl_bps_per_tick"]
    return [(t, px[t] - py[t]) for t in px]

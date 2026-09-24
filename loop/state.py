"""features → adjectives → state string → the arm-C rule. Pure functions, nothing else.

May: turn one feed snapshot into the numbers of CONTRACT §2 (`features`), the numbers
into four words (`adjectives`), the words into the one string the model sees
(`state_string`), and the words into arm C's intent (`rule_c`). May not: read or
write a file, touch the network or the clock, see the key, know a position, or act
on anything it computes. Every threshold is imported from config.py; nothing here
decides a cut, it only applies one. Anything that changes a word here changes what
arm C IS (SPEC.md), so the definitions below are written out and pinned by tests.

Definitions (the window is the LAST config.WINDOW_MIN = 300 closed 1-min candles;
index 0 is the oldest, -1 the newest closed minute, which is "now"):
  fill1k_bps  the cost of ONE paper order walked through the book (2026-09-24, decided by
              Alex): buy = 1e4·(VWAP of the asks for NOTIONAL_USD of quote − mid)/mid, sell
              = 1e4·(mid − VWAP of the bids for NOTIONAL_USD)/mid, fill1k_bps = max(buy,
              sell). A side the snapshot's levels cannot fill costs inf: logged as null with
              fill1k_short = true, and liq reads thin. l1_min_usd (the smaller level-1 side in
              USD) stays a logged feature; it no longer sets a word.
  vol5_usd    sum over the last 5 candles of base volume × close (the candle carries
              no notional; close is the only price the venue closes the minute on).
  vol5_p10/90 nearest-rank percentiles of the window's 60 NON-overlapping 5-min sums,
              blocked from the end so the newest block is vol5_usd itself.
  ret15_bps   1e4·ln(close[-1] / close[-16]); ret15_sd_bps is the sample sd of all
              285 OVERLAPPING 15-min returns in the window; ret15_z = ret / sd.
  rv15        sum of squared 1-min log returns over the last 15 candles (closes -16..-1);
              rv15_med is the median over the window's 19 NON-overlapping 15-return
              blocks from the end (299 returns; the 14 oldest are dropped); rv_ratio =
              rv15 / rv15_med.
  A window with no scale (sd == 0, or rv15_med == 0) reads z = 0.0 and rv_ratio = 1.0:
  the neutral words, so a stuck feed (300 equal closes) is flat/normal and rule_c holds.
  Cuts are strict (<, >) exactly as CONTRACT §2 writes them; equality is the middle word.
"""
import itertools, math, statistics
from loop import config

# ---- the alphabet: the ONLY words the model ever sees ----------------------------
# Order within a tuple is (below the low cut, between, above the high cut). "bot_war"
# keeps the underscore: one token, no digit, and the same spelling in prompts/v1.json.
LIQ = ("thin", "normal", "deep")
FLOW = ("quiet", "organic", "bot_war")
TREND = ("dumping", "flat", "pumping")
VOL = ("calm", "normal", "violent")
DIMS = ("liq", "flow", "trend", "vol")
ALPHABET = {"liq": LIQ, "flow": FLOW, "trend": TREND, "vol": VOL}
BUY, SELL, HOLD = "buy", "sell", "hold"
BASE = config.PRODUCT.split("-")[0]                     # "SOL": the word in front of the colon
FLOW_BLOCK_MIN = 5                                      # the 5 in vol5: CONTRACT §2 names the feature
RET_BLOCK_MIN = config.HORIZON_S // config.CADENCE_S    # 15: the return block IS the horizon
FEATURE_KEYS = ("mid", "spread_bps", "l1_min_usd", "fill1k_bps", "fill1k_short",
                "vol5_usd", "vol5_p10", "vol5_p90",
                "ret15_bps", "ret15_sd_bps", "ret15_z", "rv15", "rv15_med", "rv_ratio",
                "window_min")


def _blocks(seq, size):
    """Non-overlapping blocks of `size`, aligned to the END so the last block is the
    live one; a leading remainder shorter than `size` is dropped (299 returns / 15 →
    19 blocks, 14 oldest returns unused)."""
    n = len(seq) // size
    lead = len(seq) - n * size
    return [seq[lead + i * size: lead + (i + 1) * size] for i in range(n)]


def _nearest_rank(values, p):
    """Nearest-rank percentile: sorted[ceil(p·N/100) − 1], the smallest sample value
    with at least p% of the sample at or below it. Integer arithmetic on purpose:
    0.1 * 60 is 6.000000000000001 in binary floats and a float ceil would skip a rank."""
    s = sorted(values)
    return s[(p * len(s) + 99) // 100 - 1]


def fill_cost_bps(levels, mid, side, notional=config.NOTIONAL_USD):
    """The cost, in bps of mid, of one market order for `notional` USD of quote walked
    through `levels` ([[price, size], ...], best first): buy walks the asks, sell the bids.
    Whole levels are taken as `size` base units; the level that finishes the order gives
    remaining_usd / price. VWAP = notional / base. buy → 1e4·(VWAP − mid)/mid, sell →
    1e4·(mid − VWAP)/mid; both ≥ 0 on an uncrossed book. Levels that cannot absorb
    `notional` → inf (the order does not fill on what the venue showed). No literal is
    compared here (tests/test_state.py's AST test): the stop is `level usd >= what remains`."""
    if side not in (BUY, SELL):
        raise ValueError("side %r is not buy or sell" % (side,))
    rem, base = float(notional), 0.0
    for price, size in levels:
        usd = price * size
        if usd >= rem:                                  # this level finishes the order
            vwap = notional / (base + rem / price)
            return 1e4 * ((vwap - mid) if side == BUY else (mid - vwap)) / mid
        base += size
        rem -= usd
    return math.inf


def features(snap):
    """Snapshot → the numbers of CONTRACT §2 (fill1k_short is the one flag). Logged, never
    sent. Raises ValueError if the feed handed fewer than WINDOW_MIN candles (a shorter
    window silently changes every percentile and median, so it is refused rather than
    approximated) or a side of the book with no levels (nothing to walk)."""
    candles = snap["candles"]
    if len(candles) < config.WINDOW_MIN:
        raise ValueError("window: %d candles < WINDOW_MIN %d" % (len(candles), config.WINDOW_MIN))
    w = candles[-config.WINDOW_MIN:]
    closes = [float(c["close"]) for c in w]
    usd = [float(c["volume"]) * float(c["close"]) for c in w]
    bid, ask = float(snap["bid"]), float(snap["ask"])
    mid = (bid + ask) / 2.0
    spread_bps = 1e4 * (ask - bid) / mid
    l1_min_usd = min(bid * float(snap["bid_size"]), ask * float(snap["ask_size"]))
    bids, asks = snap.get("bids"), snap.get("asks")
    if not bids or not asks:
        raise ValueError("book: a side with no levels")
    fill = max(fill_cost_bps(asks, mid, BUY), fill_cost_bps(bids, mid, SELL))
    short = math.isinf(fill)                            # JSON has no inf: null plus the flag
    # flow: the live 5-min notional against the window's own distribution of 5-min notionals.
    sums5 = [sum(b) for b in _blocks(usd, FLOW_BLOCK_MIN)]
    vol5 = sums5[-1]
    p_lo, p_hi = _nearest_rank(sums5, config.FLOW_P_LO), _nearest_rank(sums5, config.FLOW_P_HI)
    # trend: the live 15-min log return z-scored by the window's overlapping 15-min returns.
    # Sample sd (n−1): at 285 returns it differs from the population sd by 0.18%, and it is
    # the conventional estimator; the choice is pinned here so the report never has to guess.
    h = RET_BLOCK_MIN
    r15 = [1e4 * math.log(closes[i] / closes[i - h]) for i in range(h, len(closes))]
    ret15 = r15[-1]
    sd = statistics.stdev(r15)
    z = ret15 / sd if sd > 0.0 else 0.0
    # vol: realised variance of the last 15 one-minute returns against the median block.
    sq = [math.log(closes[i] / closes[i - 1]) ** 2 for i in range(1, len(closes))]
    blocks = _blocks(sq, h)
    rv15 = sum(blocks[-1])
    rv_med = statistics.median(sum(b) for b in blocks)
    ratio = rv15 / rv_med if rv_med > 0.0 else 1.0
    return {"mid": mid, "spread_bps": spread_bps, "l1_min_usd": l1_min_usd,
            "fill1k_bps": None if short else fill, "fill1k_short": short,
            "vol5_usd": vol5, "vol5_p10": p_lo, "vol5_p90": p_hi,
            "ret15_bps": ret15, "ret15_sd_bps": sd, "ret15_z": z,
            "rv15": rv15, "rv15_med": rv_med, "rv_ratio": ratio,
            "window_min": len(w)}


def _band(x, lo, hi, words):
    """Three words from two strict cuts, exactly CONTRACT §2's `<` and `>`: a value ON
    a cut is not evidence of either extreme, so it takes the middle word."""
    return words[0] if x < lo else words[2] if x > hi else words[1]


def adjectives(feat):
    """Numbers → four words. Every cut comes from config.py; flow's cuts come from the
    window itself (the p10/p90 in feat), which is why they are features, not constants.
    liq runs the other way round from the other three: a LOW cost is deep, so the cuts
    are (LIQ_DEEP_BPS, LIQ_THIN_BPS) and the words reversed; a short side is inf → thin."""
    fill = math.inf if feat["fill1k_short"] or feat["fill1k_bps"] is None else feat["fill1k_bps"]
    return {"liq": _band(fill, config.LIQ_DEEP_BPS, config.LIQ_THIN_BPS, LIQ[::-1]),
            "flow": _band(feat["vol5_usd"], feat["vol5_p10"], feat["vol5_p90"], FLOW),
            "trend": _band(feat["ret15_z"], -config.TREND_Z, config.TREND_Z, TREND),
            "vol": _band(feat["rv_ratio"], config.VOL_RATIO_LO, config.VOL_RATIO_HI, VOL)}


def _check(adj):
    """A word outside the alphabet would change the state the model sees (and what arm C
    holds on) without any test noticing; refuse it here, loudly."""
    for d in DIMS:
        if adj.get(d) not in ALPHABET[d]:
            raise ValueError("adj[%r]=%r not in %s" % (d, adj.get(d), ALPHABET[d]))


def state_string(adj):
    """The ~10 words arms A and B both ride. No number, no position: the two arms share
    one request on one state, and a digit would be a number the SPEC says they never see."""
    _check(adj)
    s = "%s: liquidity %s, flow %s, trend %s, vol %s" % (
        BASE, adj["liq"], adj["flow"], adj["trend"], adj["vol"])
    if any(ch.isdigit() for ch in s):
        raise ValueError("state string carries a digit: %r" % s)
    return s


def rule_c(adj):
    """Arm C, the three lines of CONTRACT §2, position-free: buy = want to be long,
    sell = want to be flat, hold = no change. buy and sell cannot both fire (pumping ≠
    dumping, and buy excludes violent), so the order of the two tests is immaterial."""
    _check(adj)
    t, v, l = adj["trend"], adj["vol"], adj["liq"]
    if t == "pumping" and v != "violent" and l != "thin":
        return BUY
    if t == "dumping" or v == "violent":
        return SELL
    return HOLD


def all_states():
    """The 81 = 3⁴ adjective dicts in one fixed order (liq, flow, trend, vol; each in
    alphabet order): the nightly's synthetic policy table and the truth-table test walk
    this list, so the order is part of the interface."""
    return [dict(zip(DIMS, combo)) for combo in itertools.product(*(ALPHABET[d] for d in DIMS))]

"""A seeded synthetic decision log in the shape loop/cycle.py writes, for tests and benchmarks.

    python3 tests/synth.py --days 28 --seed 1 --out FILE [--t0 20260925T214000Z] [--stress] [--era v2] [--cadence-s 60]
    python3 tests/synth.py --products all --era v2 --out DATA_DIR ...    (one log per product, where config.store puts it)

Not a test module (unittest discovers test*.py only). Tests import it as the suite imports
fixture_prompts (`from synth import generate, write`, tests/ being on sys.path under
`unittest discover -s tests`); run as a script it puts the repo root on sys.path itself.

One row a minute from T0 - pre_hours to T0 + days + post_minutes, every key of CONTRACT §2's Row
in cycle.new_row's order, written compact (`json.dumps(row, separators=(",", ":"))`, so every line
starts with outcomes.ROW_START) with the absences, duplicates and damaged lines a real log carries.
The rows are built the way the tick builds them: a feed part (bid/ask/sizes/book_time/feed_age_s),
a state part (mid, the 15 features, the four words from state.adjectives, the state string,
rule_c), a prompts part (v1 and the CURRENT name with their shas), and an answer part (jev, the
five answers, columns from rules.for_arm). An absence row carries exactly the parts the tick had
reached (SPEC §2, §13): lock and a feed that failed to fetch carry none, a feed the state refused
carries the feed part only (bid/ask set, mid null), guard has feed and state, halt and jev have
feed, state and prompts, a jev/parse refused at the columns keeps its answer and no columns.
The features are consistent with the words (adj = state.adjectives(features)) and computed from
a random-walk price path with a 300-minute pre-roll by the definitions of SPEC §4 (rolling sums,
not candles; nothing reads them back but the adjectives). The prompt shas are sha256 of
"synthetic prompt vN" (never the live prompts/); spec_sha is prereg-v1's SPEC sha on a v1-era row and
this repo's SPEC.md on a v2-era row (knob era). generate_products(seed, products) gives one Log per
product on one shared tick grid; write_products(data, logs) puts each where config.store would.

Knobs (generate(seed, **knobs); KNOBS holds the defaults, which make a 28-day log look like the
live one; STRESS turns every oddity up so a 1-day log carries several of each):
  t0                tick_id of T0 (default PREREG §11's 20260925T214000Z)
  days              span after T0 in days (float); pre_hours before T0 (the shakedown), post_minutes
                    after T0 + days (so the last blocks' t + h rows exist)
  pre_dry_hours     the first hours of the shakedown are attended `make dry` runs (mode dry), each
                    minute kept with probability pre_dry_keep
  mid0, vol_bps     start price (USD) and the per-minute log-return sd in bps (log-AR(1) around it)
  trend_rate        per-minute chance a trend episode starts (drift +-1.5..4 bps/min for 8..40 min:
                    the pumping/dumping words); burst_rate the chance of a volatility burst (x3 for
                    10..30 min: violent)
  spread_cents      ((cents, weight), ...) of the book's spread; p_thin, p_short: liq thin by cost,
                    or a side that cannot fill NOTIONAL_USD (fill1k_bps null, fill1k_short true)
  phase             "calendar" (launchd at :00, ts_rx jitter_ms after the minute), "wild" (any
                    point of the minute: stresses the +-30 s join window, its edges and ties);
                    quantum_ms rounds the in-minute offset down to a multiple (1 = real ms);
                    p_late: a fire late by 1..20 s
  interval_hours    the first hours of the log run on launchd's old ~61 s StartInterval grid (the
                    phase walks round the minute and a minute is skipped about once an hour)
  holes_per_day     Mac asleep or logged out: holes start at this rate, length lognormal around
                    hole_median minutes, at most hole_max; p_skip drops one isolated minute
  empty_days        T0-day numbers (1 = [T0, T0 + 1 d)) with no row at all (the Mac off all day)
  absence_days      T0-day numbers where every row is an absence of kind absence_day_kind
  p_feed            isolated feed absences; feed_bursts_per_day: outages of 2..15 minutes; a feed
                    absence is a fetch failure (no parts) or, with p_state_refused, a window the
                    state refused (feed part only)
  halts_per_day     data/HALT stretches of halt_minutes (lo, hi): absence halt, sends stopped
  p_guard           a prompts failure (absence guard)
  p_jev             a Jev failure on a live tick; jev_kinds ((kind, weight), ...); a parse can be a
                    half answer (no answer kept) or a refused choice at the columns (answer kept)
  p_lock_dup        a launchd double-fire: an absence "lock" row sharing the tick_id, written first
  p_dry_dup         a `make dry` between two live ticks: a dry row 15..45 s into the same minute
  p_live_dup        a second live answered row in the same minute (a manual --once), 15..45 s in
  p_torn            a row torn mid-write (no newline); the next row closes it with "\\n" first, as
                    cycle.write_row does since 2026-09-28: one skipped line, the row lost
  p_glued           a torn row with the next whole row appended onto it (the writer before
                    2026-09-28): outcomes.load keeps the whole row and skips the torn head
  torn_tail         the file ends in a torn row (a crash during the last write)
  p_foreign         a live row with a word outside the alphabet in one dimension (a value from
                    foreign_words, None included: never written by the tick, which refuses it)
  promotions_h      hours after T0 at which bin/promote moves prompt_b to v2, v3, ...; B answers
                    the v1 question until the first (test-retest: retest_noise) and a per-version
                    policy after it (policy_change: the share of the 81 states it moves off the rule)
  a_noise           arm A's answer differs from rule_c with this probability (v1 restates it)
  p_tail            a direction noul in the measured tail (>= 0.99)
  p_drift           model_answered is not MODEL (drift); p_shared_key: the brain's key answered
  product           the row's product (default SOL-USD, the v1 stream): its base leads the state string,
                    its liq words are read in its own half-ticks (config.TICK_P), its book sits on its
                    tick grid; a product other than SOL-USD draws its own price path (mid0 from MIDS
                    unless given) and consumes SOL's market draws first, so its fires, holes, HALT
                    stretches and feed bursts are SOL's for the same seed (generate_products)
  era               "v1" (default): the rows v1's loop wrote (A = v1, no table_sha, columns a and b);
                    "v2": the rows the v2 tree writes (PREREG-v2 §10): A asks the frozen v2 wording,
                    CURRENT starts at v2 and promotions_h move it to v3, v4, ...; the row carries
                    table_sha and columns.d, the CURRENT version's table answer for the state (the
                    version's policy, which B's live answer follows up to retest_noise)
  p_d_null          (v2) a tick whose table read failed: table_sha and columns.d null on that row
  no_table          (v2) versions with no table: table_sha and columns.d null on every row asking them
  cadence_s         seconds between the synthetic loop's fires (a multiple of 60 dividing 86,400;
                    default 60): the grid is T0-anchored, the rows carry it as cadence_s, and a
                    28-day multi-product log at 900 s is small enough for a test
The v1 era's rows carry prereg-v1's SPEC sha (dash.V1_SPEC_SHA), the v2 era's this tree's SPEC.md.
Every probability is per row (or per minute for the *_per_day rates). The same seed and knobs
give the same bytes. generate(..., encode=False) skips the bytes (Log.data is None) and gives the
same rows about twice as fast; tests that do not read the file use it.

Speed: ~0.1 ms a row with the bytes (a 28-day log, ~41k rows and ~80 MB, in about 6 s).
"""
import argparse, bisect, calendar, hashlib, json, math, os, random, sys, time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:                     # run as a script: tests/ is sys.path[0], loop/ is not
    sys.path.insert(0, REPO)

from loop import config, dash, rules, state  # noqa: E402

CHOICES = rules.CHOICES
WINDOW = config.WINDOW_MIN                   # 300
FOREIGN = ("wild", "sideways", "frozen", None)
LOOP_KEY = "file:~/.secondbrain-secrets/typesafe-api-key-loop"
SHARED_KEY = "file:~/.secondbrain-secrets/typesafe-api-key"

KNOBS = {
    "t0": "20260925T214000Z", "days": 28.0, "pre_hours": 24.0, "post_minutes": 20,
    "pre_dry_hours": 1.0, "pre_dry_keep": 0.3,
    "mid0": 200.0, "vol_bps": 8.0, "trend_rate": 0.004, "burst_rate": 0.001,
    "spread_cents": ((1, 80), (2, 15), (3, 4), (5, 1)), "p_thin": 0.01, "p_short": 0.001,
    "phase": "calendar", "jitter_ms": (40, 400), "quantum_ms": 1, "p_late": 0.002,
    "interval_hours": 0.0,
    "holes_per_day": 0.3, "hole_median": 45, "hole_max": 600, "p_skip": 0.0005,
    "empty_days": (), "absence_days": (), "absence_day_kind": "halt",
    "p_feed": 0.002, "feed_bursts_per_day": 0.3, "p_state_refused": 0.2,
    "halts_per_day": 0.04, "halt_minutes": (60, 360),
    "p_guard": 0.0002,
    "p_jev": 0.002, "jev_kinds": (("timeout", 40), ("http-5xx", 30), ("http-429", 8), ("parse", 12), ("watchdog", 4),
                                  ("unexpected", 3), ("http-4xx", 1), ("no-key", 1), ("ledger", 1)),
    "p_lock_dup": 0.0003, "p_dry_dup": 0.0002, "p_live_dup": 0.0001,
    "p_torn": 0.00005, "p_glued": 0.00003, "torn_tail": False,
    "p_foreign": 0.0, "foreign_words": FOREIGN,
    "promotions_h": (24.7, 302.0), "retest_noise": 0.02, "policy_change": 0.3,
    "a_noise": 0.005, "p_tail": 0.001, "p_drift": 0.0, "p_shared_key": 0.0,
    "product": config.PRODUCT, "era": "v1", "p_d_null": 0.0, "no_table": (), "cadence_s": config.CADENCE_S,
}
MIDS = {"SOL-USD": 200.0, "ETH-USD": 4000.0, "XRP-USD": 2.5, "DOGE-USD": 0.25, "AVAX-USD": 30.0, "LINK-USD": 20.0,
        "ADA-USD": 0.8}                        # a product's mid0 when none is given (MID_ELSE for any other)
MID_ELSE = 100.0
ERAS = ("v1", "v2")
# the knobs drawn before the first row (the market, the fires, the holes, HALT and the feed bursts): one set for
# every product of generate_products, so the products share one tick grid and one Mac
GRID_KNOBS = ("t0", "days", "pre_hours", "post_minutes", "cadence_s", "interval_hours", "phase", "jitter_ms",
              "quantum_ms", "p_late", "trend_rate", "burst_rate", "holes_per_day", "hole_median", "hole_max",
              "halts_per_day", "halt_minutes", "feed_bursts_per_day")

STRESS = {
    "pre_hours": 2.0, "pre_dry_hours": 0.5, "pre_dry_keep": 0.5, "trend_rate": 0.01, "burst_rate": 0.004,
    "p_thin": 0.03, "p_short": 0.01, "p_late": 0.01,
    "holes_per_day": 3.0, "hole_median": 15, "hole_max": 240, "p_skip": 0.005,
    "p_feed": 0.01, "feed_bursts_per_day": 2.0, "p_state_refused": 0.4, "halts_per_day": 1.0, "halt_minutes": (20, 120),
    "p_guard": 0.003, "p_jev": 0.01, "p_lock_dup": 0.005, "p_dry_dup": 0.005, "p_live_dup": 0.004,
    "p_torn": 0.002, "p_glued": 0.002, "p_foreign": 0.003, "promotions_h": (8.0,), "retest_noise": 0.05,
    "a_noise": 0.02, "p_tail": 0.01, "p_drift": 0.002, "p_shared_key": 0.002,
}


class Log:
    """What generate() made. rows: the rows outcomes.load returns from `data`, in file order (the torn
    rows gone, the glued ones kept); lost: the torn rows' dicts; bad: the lines load skips (one per
    torn row, glued head and torn tail); glued: tick_ids of the rows written onto a torn line;
    t0: T0 in epoch seconds; knobs: the knobs used; events: counts of what was injected."""

    def __init__(self, rows, lost, data, bad, glued, t0, knobs, events):
        self.rows, self.lost, self.data, self.bad, self.glued = rows, lost, data, bad, glued
        self.t0, self.knobs, self.events = t0, knobs, events


def _epoch_of_tick(tid):
    return calendar.timegm(time.strptime(tid, "%Y%m%dT%H%M%SZ"))


def _iso_ms(ms):
    """The row's ts_rx: '2026-09-25T21:40:00.123Z' (cycle.iso_ms, from integer milliseconds)."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms // 1000)) + ".%03dZ" % (ms % 1000)


def _tick(ts):
    return ts[:4] + ts[5:7] + ts[8:10] + "T" + ts[11:13] + ts[14:16] + "00Z"


def _spec_sha():
    try:
        with open(os.path.join(REPO, "SPEC.md"), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return "unsealed"


def prompt_sha(version):
    return hashlib.sha256(f"synthetic prompt {version}".encode()).hexdigest()


def table_sha(version, product):
    return hashlib.sha256(f"synthetic table {version} {product}".encode()).hexdigest()


def new_row(ts_ms, mode, spec, era="v1", product=config.PRODUCT, cadence_s=config.CADENCE_S):
    """cycle.new_row: every key present, in its order, everything not filled null. A v1-era row has v1's
    shape (no table_sha, columns a and b); a v2-era row the v2 tree's (table_sha after prompt_b_sha, columns.d)."""
    ts = _iso_ms(ts_ms)
    row = {"v": 1, "tick_id": _tick(ts), "ts_rx": ts, "mode": mode,
           "venue": config.VENUE, "product": product,
           "cadence_s": cadence_s, "horizon_s": config.HORIZON_S,
           "bid": None, "bid_size": None, "ask": None, "ask_size": None, "mid": None,
           "book_time": None, "feed_age_s": None,
           "features": None, "adj": None, "state": None, "spec_sha": spec,
           "prompt_a": None, "prompt_a_sha": None, "prompt_b": None, "prompt_b_sha": None,
           "model_requested": config.MODEL, "model_answered": None, "drift": False,
           "jev": {"latency_ms": None, "input_tokens": None, "error": None, "key_path": None},
           "answers": None, "rule_c": None, "columns": {"a": None, "b": None}, "absence": None}
    if era == "v1":
        return row
    out = {}
    for k, v in row.items():
        out[k] = v
        if k == "prompt_b_sha":
            out["table_sha"] = None
    out["columns"] = {"a": None, "b": None, "d": None}
    return out


# ---- the market: a price path and the SPEC §4 features on it, per minute --------------------------
class _Market:
    """closes[i] for every minute i of [start - WINDOW - 16, end), and the rolling features at i."""

    def __init__(self, rng, k, n):
        self.rng, self.k = rng, k
        lp, h, trend, left, burst = math.log(k["mid0"]), 0.0, 0.0, 0, 0
        self.lp, self.usd = [], []
        for _ in range(n):
            h = 0.98 * h + rng.gauss(0.0, 0.03)
            if left == 0 and rng.random() < k["trend_rate"]:
                trend, left = rng.choice((-1, 1)) * rng.uniform(1.5, 4.0), rng.randint(8, 40)
            if burst == 0 and rng.random() < k["burst_rate"]:
                burst = rng.randint(10, 30)
            sig = k["vol_bps"] * math.exp(h) * (3.0 if burst else 1.0)
            lp += (rng.gauss(trend if left else 0.0, sig)) / 1e4
            left, burst = max(0, left - 1), max(0, burst - 1)
            self.lp.append(lp)
            self.usd.append(math.exp(rng.gauss(math.log(800.0), 0.6)) * (3.0 if burst else 1.0) * math.exp(lp))
        # rb[j]: the 15-minute realised variance ending at minute j (squared 1-min log returns, natural
        # units); b5[j]: the 5-minute notional ending at j. Each block series is then a strided slice.
        sq = [0.0] + [(self.lp[i] - self.lp[i - 1]) ** 2 for i in range(1, n)]
        self.rb, acc = [0.0] * n, 0.0
        for j in range(n):
            acc += sq[j] - (sq[j - 15] if j >= 15 else 0.0)
            self.rb[j] = acc
        self.b5, acc = [0.0] * n, 0.0
        for j in range(n):
            acc += self.usd[j] - (self.usd[j - 5] if j >= 5 else 0.0)
            self.b5[j] = acc
        # overlapping 15-minute returns in bps and their rolling sums over the window's 285
        self.r15 = [None] * n
        for i in range(15, n):
            self.r15[i] = 1e4 * (self.lp[i] - self.lp[i - 15])
        self.s1, self.s2 = [None] * n, [None] * n
        m = WINDOW - 15                                              # 285
        a1 = a2 = 0.0
        for i in range(15, n):
            a1 += self.r15[i]
            a2 += self.r15[i] ** 2
            if i - m >= 15:
                a1 -= self.r15[i - m]
                a2 -= self.r15[i - m] ** 2
            if i >= m + 14:
                self.s1[i], self.s2[i] = a1, a2

    def close(self, i):
        return math.exp(self.lp[i])

    def features(self, i, bid, ask, bid_size, ask_size, halftick_k=1.0):
        """halftick_k: the product's half-tick over SOL's, in bps at mid0, so the fill noise past the half-spread
        (and a thin draw) is the same number of the product's half-ticks as SOL's (1.0 for SOL, left out)."""
        rng, k = self.rng, self.k
        mid = (bid + ask) / 2.0                                         # state.features' own expression
        spread_bps = 1e4 * (ask - bid) / mid
        short = rng.random() < k["p_short"]
        extra = rng.expovariate(2.0)
        fill = 1e4 * (ask - mid) / mid + (extra if halftick_k == 1.0 else extra * halftick_k)
        if rng.random() < k["p_thin"]:
            thin = rng.uniform(4.0, 10.0)
            fill += thin if halftick_k == 1.0 else thin * halftick_k
        n = WINDOW - 15
        s1, s2 = self.s1[i], self.s2[i]
        sd = math.sqrt(max(0.0, (s2 - s1 * s1 / n) / (n - 1)))
        ret15 = self.r15[i]
        z = ret15 / sd if sd > 0.0 else 0.0
        rv15 = self.rb[i]
        rv_med = sorted(self.rb[i - 270:i + 1:15])[9]                  # the median of the 19 blocks from the end
        vol5 = self.b5[i]
        s5 = sorted(self.b5[i - 295:i + 1:5])                           # the window's 60 blocks; the newest is vol5
        return {"mid": mid, "spread_bps": spread_bps, "l1_min_usd": min(bid * bid_size, ask * ask_size),
                "fill1k_bps": None if short else fill, "fill1k_short": short,
                "vol5_usd": vol5, "vol5_p10": s5[(config.FLOW_P_LO * 60 + 99) // 100 - 1], "vol5_p90": s5[(config.FLOW_P_HI * 60 + 99) // 100 - 1],
                "ret15_bps": ret15, "ret15_sd_bps": sd, "ret15_z": z,
                "rv15": rv15, "rv15_med": rv_med, "rv_ratio": rv15 / rv_med if rv_med > 0.0 else 1.0,
                "window_min": WINDOW}


def _weighted(rng, pairs):
    total = sum(w for _, w in pairs)
    x = rng.uniform(0, total)
    for v, w in pairs:
        x -= w
        if x <= 0:
            return v
    return pairs[-1][0]


def _intervals(rng, start_min, n_min, per_day, lo_hi=None, median=None, hi=None):
    """[a, b) minute intervals starting at `per_day` / 1440 per minute; lengths uniform in lo_hi or
    lognormal around median capped at hi."""
    out, m = [], 0
    p = per_day / 1440.0
    while m < n_min:
        if p and rng.random() < p:
            if lo_hi:
                L = rng.randint(*lo_hi)
            else:
                L = int(min(hi, max(2, round(median * math.exp(rng.gauss(0.0, 1.0))))))
            out.append((start_min + m, start_min + m + L))
            m += L
        else:
            m += 1
    return out


def _inside(ivs, minute):
    i = bisect.bisect_right(ivs, (minute, math.inf)) - 1
    return i >= 0 and ivs[i][0] <= minute < ivs[i][1]


def _choice(choice, conf):
    rest = round((1.0 - conf) / 2, 3)
    return {"choice": choice, "probabilities": {c: (conf if c == choice else rest) for c in CHOICES}, "confidence": conf}


def _key(adj):
    return tuple(adj.get(d) for d in state.DIMS)


_STATES, _COLS = {}, {}
_ENC = json.JSONEncoder(separators=(",", ":"))


def _columns(ans, arm):
    """rules.for_arm(ans, arm), computed once per reading of the cuts it applies (the choice, its
    confidence, and which side of PBUY, VETO_NOUL and NOUL_TAIL each other field is on): half the
    generator's time otherwise. tests/test_invariants.py checks every row against rules.for_arm."""
    a, skip, up, down = ans[arm + "_action"], ans["skip"], ans["up15"], ans["down15"]
    p = a["probabilities"]
    key = (a["choice"], a["confidence"], p.get("buy", 0.0) >= config.PBUY, p.get("sell", 0.0) >= config.PBUY,
           skip["noul"] >= config.VETO_NOUL, up["noul"] >= config.NOUL_TAIL, down["noul"] >= config.NOUL_TAIL)
    if key not in _COLS:
        _COLS[key] = rules.columns(a, skip, up, down)
    return dict(_COLS[key])


def _state_string(adj, base=state.BASE):
    """state.state_string, once per state and base (its digit scan was a fifth of the generator's time)."""
    key = (base,) + _key(adj)
    if key not in _STATES:
        _STATES[key] = state.state_string(adj, base)
    return _STATES[key]


def generate(seed=1, encode=True, **over):
    """A Log for `seed` and the knobs `over` (on top of KNOBS). encode=False skips the bytes (data is
    None): the rows, the torn ones and the counts are the same, and the generator runs twice as fast."""
    unknown = set(over) - set(KNOBS)
    if unknown:
        raise TypeError(f"unknown knobs: {sorted(unknown)}")
    k = dict(KNOBS, **over)
    product, era, cad = k["product"], k["era"], k["cadence_s"]
    if era not in ERAS:
        raise ValueError(f"era {era!r} not in {ERAS}")
    if isinstance(cad, bool) or not isinstance(cad, int) or cad <= 0 or cad % 60 or 86400 % cad:
        raise ValueError(f"cadence_s {cad!r} is not a multiple of 60 s dividing a day")
    if cad != 60 and k["interval_hours"]:
        raise ValueError("cadence_s other than 60 with interval_hours: the old ~61 s grid is a one-minute loop's")
    sol = product == config.PRODUCT
    if not sol and "mid0" not in over:
        k["mid0"] = MIDS.get(product, MID_ELSE)
    tick = config.TICK_P[product]                            # a product must have its tick (tests add products to config)
    base = config.base(product)
    rng = random.Random(seed)
    t0 = _epoch_of_tick(k["t0"])
    start = (t0 - int(round(k["pre_hours"] * 3600))) // 60 * 60
    end = t0 + int(round(k["days"] * 86400)) + 60 * int(k["post_minutes"])
    n_min = max(0, (end - start) // 60)
    start_min, pre = start // 60, WINDOW + 16
    mk = _Market(rng, k, n_min + pre + 1)
    if not sol:                                             # SOL's market draws are taken (so the fires, holes and HALT
        mk = _Market(random.Random(f"{seed}/{product}"), k, n_min + pre + 1)   # stretches below are SOL's) and the
                                                                               # product walks its own path on its own rng
    spec = dash.V1_SPEC_SHA if era == "v1" else _spec_sha()
    size_k = 1.0 if sol else MIDS["SOL-USD"] / k["mid0"]   # a side's size in base units: SOL's USD depth at this price
    halftick_k = 1.0 if sol else (tick / 2 / k["mid0"]) / (0.005 / MIDS["SOL-USD"])   # SOL's fill noise, in this
                                                                                     # product's half-ticks
    events = {"rows": 0, "absence": {}, "lock_dup": 0, "dry_dup": 0, "live_dup": 0, "torn": 0, "glued": 0, "tail": 0,
              "foreign": 0, "drift": 0, "shared_key": 0, "holes": 0, "skips": 0, "late": 0}

    # -- when the tick fired: one fire per minute (calendar / wild), or the old ~61 s grid
    fires, q = [], max(1, int(k["quantum_ms"]))
    grid_end = start + int(round(k["interval_hours"] * 3600))
    ms = start * 1000 + rng.randint(*k["jitter_ms"])
    while ms < grid_end * 1000 and ms < end * 1000:
        fires.append(ms)
        ms += 61000 + rng.randint(-60, 60)
    first = -(-max(ms, grid_end * 1000) // 60000) if fires else start_min
    for m in range(first, end // 60):
        if cad != 60 and (m * 60 - t0) % cad:
            continue                                        # the cadence knob: one fire every cad s from T0
        if k["phase"] == "wild":
            off = rng.randrange(0, 60000)
        else:
            off = rng.randint(*k["jitter_ms"])
            if rng.random() < k["p_late"]:
                off += rng.randint(1000, 20000)
                events["late"] += 1
        fires.append(m * 60000 + off // q * q)

    holes = _intervals(rng, start_min, n_min, k["holes_per_day"], median=k["hole_median"], hi=k["hole_max"])
    halts = _intervals(rng, start_min, n_min, k["halts_per_day"], lo_hi=k["halt_minutes"])
    bursts = _intervals(rng, start_min, n_min, k["feed_bursts_per_day"], lo_hi=(2, 15))
    events["holes"] = len(holes)

    def t0_day(minute):
        return (minute * 60 - t0) // 86400 + 1

    first_v = 1 if era == "v1" else 2                       # v2: CURRENT is v2 at T0_v2 (PREREG-v2 §1), A's own wording
    versions = [(f"v{first_v}", -math.inf)] + [(f"v{j + first_v + 1}", t0 + h * 3600) for j, h in enumerate(sorted(k["promotions_h"]))]
    policies = {}
    for j, (v, _) in enumerate(versions[1:] if era == "v1" else versions, 2):   # vN's policy is the same in both eras
        prng = random.Random(seed * 1009 + j)
        pol = {}
        for adj in state.all_states():
            r = state.rule_c(adj)
            pol[_key(adj)] = r if prng.random() >= k["policy_change"] else prng.choice([c for c in CHOICES if c != r])
        policies[v] = pol

    def version_at(sec):
        v = versions[0][0]
        for name, since in versions:
            if sec >= since:
                v = name
        return v

    def feed_part(row, i, sec_ms):
        c = mk.close(i)
        s = _weighted(rng, k["spread_cents"])               # the spread in ticks (cents on SOL's 1c grid)
        if sol:
            bid = round(c - s / 200.0, 2)
            ask = round(bid + s / 100.0, 2)
        else:
            nd = max(0, -math.floor(math.log10(tick) + 1e-9))
            bid = round(round((c - s * tick / 2) / tick) * tick, nd)
            ask = round(bid + s * tick, nd)
        bs, az = round(rng.uniform(0.5, 300.0) * size_k, 3), round(rng.uniform(0.5, 300.0) * size_k, 3)
        age = (sec_ms % 60000) / 1000.0 + (60.0 if rng.random() < 0.01 else 0.0)
        row.update(bid=bid, bid_size=bs, ask=ask, ask_size=az,             # the venue's clock: microseconds, a hair before ours
                   book_time=row["ts_rx"][:20] + "%06dZ" % rng.randrange(1 + 1000 * (sec_ms % 1000)),
                   feed_age_s=round(age, 3))
        return bid, ask, bs, az

    def state_part(row, i, bid, ask, bs, az, foreign=False):
        feat = mk.features(i, bid, ask, bs, az, halftick_k)
        adj = state.adjectives(feat, product)
        rule = state.rule_c(adj)
        s = _state_string(adj, base)
        if foreign:                                         # never written by the tick: state.py refuses the word
            d = rng.choice(state.DIMS)
            adj = dict(adj, **{d: rng.choice(k["foreign_words"])})
            s = "%s: liquidity %s, flow %s, trend %s, vol %s" % (base, adj["liq"], adj["flow"], adj["trend"], adj["vol"])
            events["foreign"] += 1
        row.update(mid=feat["mid"], features=feat, adj=adj, state=s, rule_c=rule)
        return adj, rule

    def prompts_part(row, sec):
        v = version_at(sec)
        a = "v1" if era == "v1" else config.FROZEN_A
        row.update(prompt_a=a, prompt_a_sha=prompt_sha(a), prompt_b=v, prompt_b_sha=prompt_sha(v))
        if era == "v2":                                     # cycle reads the table at the prompts step, before HALT
            row["table_sha"] = None if v in k["no_table"] else table_sha(v, product)
        return v

    def answer(adj, rule, bver):
        amean = rule if era == "v1" else policies[config.FROZEN_A].get(_key(adj), rule)   # v1's A restates rule_c
        a = amean if rng.random() >= k["a_noise"] else rng.choice([c for c in CHOICES if c != amean])
        ca = round(rng.uniform(0.86, 0.99), 2)
        if bver == versions[0][0]:                          # the same question twice: the model's own noise
            b = a if rng.random() >= k["retest_noise"] else rng.choice([c for c in CHOICES if c != a])
            cb = round(min(0.99, max(0.5, ca + rng.uniform(-0.02, 0.02))), 2)
        else:
            b = policies[bver].get(_key(adj), rule)
            if rng.random() < k["retest_noise"]:
                b = rng.choice(CHOICES)
            cb = round(rng.uniform(0.55, 0.99), 2)
        lean = {"pumping": 0.3, "dumping": -0.3}.get(adj.get("trend"), 0.02) + rng.gauss(0.0, 0.04)
        up = round(min(0.95, max(0.02, 0.45 + lean / 2 + rng.gauss(0.0, 0.02))), 2)
        down = round(min(0.95, max(0.02, 0.45 - lean / 2 + rng.gauss(0.0, 0.02))), 2)
        if rng.random() < k["p_tail"]:
            if rng.random() < 0.5:
                up = 0.99 if rng.random() < 0.5 else 1.0
            else:
                down = 0.99
        skip = round(rng.uniform(0.01, 0.12), 2) if rng.random() >= 0.02 else round(rng.uniform(0.5, 0.9), 2)
        return {"a_action": _choice(a, ca), "b_action": _choice(b, cb), "skip": {"noul": skip},
                "up15": {"noul": up}, "down15": {"noul": down}}

    def jev_meta(bver):
        key = SHARED_KEY if rng.random() < k["p_shared_key"] else LOOP_KEY
        model = "jev-1.14.0" if rng.random() < k["p_drift"] else config.MODEL
        events["shared_key"] += key == SHARED_KEY
        events["drift"] += model != config.MODEL
        lat = int(min(20000, math.exp(rng.gauss(math.log(700.0), 0.35))))
        tok = (540 if bver == "v1" else 600) + rng.randint(-20, 20)
        return key, model, lat, tok

    def build(ms_, minute, mode, kind, foreign=False):
        """One row at ts_rx = ms_ of `kind`: ok | feed | feed-state | guard | halt | jev | lock."""
        row = new_row(ms_, mode, spec, era, product, cad)
        i = minute - start_min + pre
        sec = ms_ / 1000.0
        if kind == "lock" or kind == "feed":
            row["absence"] = kind
            return row
        bid, ask, bs, az = feed_part(row, i, ms_)
        if kind == "feed-state":
            row["absence"] = "feed"
            return row
        adj, rule = state_part(row, i, bid, ask, bs, az, foreign)
        if kind == "guard":
            row["absence"] = "guard"
            return row
        bver = prompts_part(row, sec)
        if kind == "halt":
            row["absence"] = "halt"
            return row
        if mode == "dry":
            return row
        if kind == "jev":
            err = _weighted(rng, k["jev_kinds"])
            row["absence"] = "jev"
            row["jev"]["error"] = err
            key, model, lat, tok = jev_meta(bver)
            # a JevError names the key it used (none for no-key); the tick's own kinds (watchdog, unexpected)
            # are not JevErrors and leave key_path null (cycle._run)
            row["jev"]["key_path"] = None if err in ("no-key", "unsigned", "watchdog", "unexpected") else key
            if err == "parse" and rng.random() < 0.5:        # refused at the columns: the answer is logged, no column
                ans = answer(adj, rule, bver)
                ans["b_action"]["choice"] = rng.choice(("short", "long", "BUY"))
                row["jev"].update(latency_ms=lat, input_tokens=tok)
                row.update(answers=ans, model_answered=model, drift=model != config.MODEL)
            return row
        key, model, lat, tok = jev_meta(bver)
        ans = answer(adj, rule, bver)
        row["jev"].update(latency_ms=lat, input_tokens=tok, key_path=key)
        row.update(answers=ans, model_answered=model, drift=model != config.MODEL)
        row["columns"] = {"a": _columns(ans, "a"), "b": _columns(ans, "b")}
        if era == "v2":                                     # arm D: the CURRENT version's table, looked up by the state
            if k["p_d_null"] and rng.random() < k["p_d_null"]:
                row["table_sha"] = None                     # the table read failed on this tick: D alone holds
            d = None if row["table_sha"] is None else policies[bver].get(_key(adj), rule)
            row["columns"]["d"] = d
        return row

    records = []                                            # (row, fate) in file order
    dry_end = start + int(round(k["pre_dry_hours"] * 3600))
    for ms_ in fires:
        minute = ms_ // 60000
        if _inside(holes, minute) or t0_day(minute) in k["empty_days"]:
            continue
        if rng.random() < k["p_skip"]:
            events["skips"] += 1
            continue
        mode = "dry" if ms_ < dry_end * 1000 else "live"
        if mode == "dry" and rng.random() >= k["pre_dry_keep"]:
            continue
        foreign = False
        if t0_day(minute) in k["absence_days"]:
            kind = k["absence_day_kind"]
        elif _inside(bursts, minute) or rng.random() < k["p_feed"]:
            kind = "feed-state" if rng.random() < k["p_state_refused"] else "feed"
        elif _inside(halts, minute):
            kind = "halt"
        elif rng.random() < k["p_guard"]:
            kind = "guard"
        elif mode == "live" and rng.random() < k["p_jev"]:
            kind = "jev"
        else:
            kind = "ok"
            foreign = rng.random() < k["p_foreign"]
        lo, hi = minute * 60000, minute * 60000 + 59999
        if rng.random() < k["p_lock_dup"]:                  # the second process finds the lock held: written first
            records.append([build(min(hi, max(lo, ms_ + rng.randint(-30, 30))), minute, mode, "lock"), "whole"])
            events["lock_dup"] += 1
        records.append([build(ms_, minute, mode, kind, foreign), "whole"])
        if mode == "live" and rng.random() < k["p_dry_dup"]:
            records.append([build(min(hi, ms_ + rng.randint(15000, 45000)), minute, "dry", "ok"), "whole"])
            events["dry_dup"] += 1
        elif mode == "live" and kind == "ok" and rng.random() < k["p_live_dup"]:
            records.append([build(min(hi, ms_ + rng.randint(15000, 45000)), minute, "live", "ok"), "whole"])
            events["live_dup"] += 1

    # -- damage: torn rows (closed by the next write), glued rows (the old writer), a torn tail
    for j in range(len(records) - 1):
        if records[j][1] != "whole" or (j and records[j - 1][1] != "whole"):
            continue                                        # the row after a torn one is always whole
        x = rng.random()
        if x < k["p_torn"]:
            records[j][1] = "torn"
        elif x < k["p_torn"] + k["p_glued"]:
            records[j][1] = "glued"
    if records and k["torn_tail"]:
        records[-1][1] = "tail"

    rows, lost, glued = [], [], []
    for j, (row, fate) in enumerate(records):
        if fate == "whole":
            rows.append(row)
            if j and records[j - 1][1] == "glued":
                glued.append(row["tick_id"])
        else:
            lost.append(row)
            events[fate] += 1
    out = bytearray() if encode else None
    for j, (row, fate) in enumerate(records if encode else ()):
        line = _ENC.encode(row).encode()                     # json.dumps(row, separators=(",", ":")), as cycle.write_row
        if fate == "whole":
            if out and out[-1:] != b"\n" and records[j - 1][1] != "glued":
                out += b"\n"                                # cycle.write_row closes a torn line first
            out += line + b"\n"
        else:
            out += line[:rng.randint(1, len(line) - 1)]     # a short write: never the whole object
    for r in rows:
        if r["absence"]:
            events["absence"][r["absence"]] = events["absence"].get(r["absence"], 0) + 1
    events["rows"] = len(rows)
    return Log(rows, lost, bytes(out) if encode else None, len(lost), glued, t0, k, events)


def rows(seed=1, **knobs):
    """generate(seed, **knobs).rows: the rows a reader of the written file gets back."""
    return generate(seed, encode=False, **knobs).rows


def write(path, log):
    """The bytes as the loop would have left them (torn and glued lines included)."""
    with open(path, "wb") as fh:
        fh.write(log.data)
    return path


def generate_products(seed=1, products=None, encode=True, per_product=None, **knobs):
    """{product: Log} for `products` (default config.PRODUCTS), one generate() each with the same seed and `knobs`,
    so they share one tick grid: the fires, holes (the Mac asleep), HALT stretches and feed bursts are drawn
    before any product-specific draw. Each walks its own price path and draws its own row-level noise. SOL-USD's
    Log is byte for byte generate(seed, **knobs). per_product: {product: knobs} on top of `knobs` for that product
    alone (empty_days, absence_days, p_jev, ...); a knob in GRID_KNOBS there is refused, it would move the grid."""
    products = tuple(config.PRODUCTS if products is None else products)
    per_product = per_product or {}
    for p, kn in per_product.items():
        if p not in products:
            raise ValueError(f"per_product names {p!r}, not one of {products}")
        grid = sorted(set(kn) & set(GRID_KNOBS))
        if grid:
            raise ValueError(f"per_product[{p!r}] sets {grid}: the grid is shared, set them for every product")
    if "product" in knobs:
        raise TypeError("product is set per Log by generate_products")
    return {p: generate(seed, encode, **dict(knobs, product=p, **per_product.get(p, {}))) for p in products}


def store_path(data, product):
    """Where config.store(product).decisions sits under the data dir `data`: data/decisions.jsonl for SOL-USD,
    data/<PRODUCT>/decisions.jsonl otherwise (tests/test_invariants holds the two to each other)."""
    return os.path.join(data, "decisions.jsonl") if product == config.PRODUCT else os.path.join(data, product, "decisions.jsonl")


def write_products(data, logs):
    """Each Log of generate_products written where the loop would: {product: path}."""
    out = {}
    for p, log in logs.items():
        path = store_path(data, p)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        out[p] = write(path, log)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 tests/synth.py", description="a seeded synthetic decision log (JSONL)")
    ap.add_argument("--days", type=float, default=KNOBS["days"])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--t0", default=KNOBS["t0"], help="T0 as a tick_id (default PREREG §11's)")
    ap.add_argument("--pre-hours", type=float, default=KNOBS["pre_hours"])
    ap.add_argument("--post-minutes", type=int, default=KNOBS["post_minutes"])
    ap.add_argument("--stress", action="store_true", help="the STRESS knobs: every oddity turned up")
    ap.add_argument("--era", choices=ERAS, default=KNOBS["era"], help="v1's rows (default) or the v2 tree's (table_sha, columns.d)")
    ap.add_argument("--cadence-s", type=int, default=KNOBS["cadence_s"], help="seconds between fires (a multiple of 60)")
    ap.add_argument("--products", default=None, help="comma-separated products of config.PRODUCTS (or 'all'): with --out a DATA"
                    " directory, each log written where config.store would put it under it")
    a = ap.parse_args(argv)
    knobs = dict(STRESS) if a.stress else {}
    knobs.update(days=a.days, t0=a.t0, pre_hours=a.pre_hours, post_minutes=a.post_minutes, era=a.era, cadence_s=a.cadence_s)
    if a.products:
        products = tuple(config.PRODUCTS) if a.products == "all" else tuple(a.products.split(","))
        bad = [p for p in products if p not in config.PRODUCTS]
        if bad:
            ap.error(f"--products: {bad} not in config.PRODUCTS {tuple(config.PRODUCTS)}")
        logs = generate_products(a.seed, products, **knobs)
        paths = write_products(a.out, logs)
        for p in products:
            sys.stdout.write(f"{paths[p]}\t{len(logs[p].rows)} rows, {len(logs[p].data)} bytes\n")
        return 0
    log = generate(a.seed, **knobs)
    write(a.out, log)
    e = log.events
    sys.stdout.write(f"{a.out}\t{len(log.rows)} rows, {len(log.data)} bytes, {log.bad} damaged lines; absence {e['absence']};"
                     f" duplicates lock {e['lock_dup']} dry {e['dry_dup']} live {e['live_dup']}; holes {e['holes']}, skips {e['skips']};"
                     f" torn {e['torn']} glued {e['glued']} tail {e['tail']}; foreign {e['foreign']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

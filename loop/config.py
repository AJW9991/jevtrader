"""Constants. Frozen once SPEC.md is written; changing any value below after row 1
changes what arm C IS, so it is a new experiment, not a tweak.

Everything a module might be tempted to hard-code lives here so the report, the
tests and SPEC.md all read one source. Nothing in this file reads the network
or the key.
"""
import collections, os

# ---- what and where ---------------------------------------------------------
VENUE = "coinbase"                 # Coinbase Advanced Trade, public market-data endpoints, no key
PRODUCT = "SOL-USD"                # decided 2026-09-23: ~$131M/day, 1c-wide book in the probe;
                                   # api.binance.com is HTTP 451 from this Mac, Binance.US SOLUSDT
                                   # is 2.7 trades/min and the adjectives degenerate on it
CADENCE_S = 60                     # one decision a minute; launchd StartInterval drifts, so
HORIZON_S = 900                    # tick_id is floored to the minute and the join is windowed

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")
DECISIONS = os.path.join(DATA, "decisions.jsonl")
SENDS = os.path.join(DATA, "sends.tsv")       # ledger-before-send, same columns as JEV's DISCLOSURE.tsv
HALT = os.path.join(DATA, "HALT")
LOCK = os.path.join(DATA, "loop.lock")
HEARTBEAT = os.path.join(DATA, "heartbeat")
PROMPTS = os.path.join(REPO, "prompts")
PROPOSALS = os.path.join(REPO, "proposals")
SPEC = os.path.join(REPO, "SPEC.md")
PROTOCOL = os.path.join(REPO, "PROTOCOL.md")   # jev.ask refuses to send until its signature line is filled

# ---- v2: products, per-product stores, the global stop and the per-product pause (PREREG-v2 §2, §10) ----
# PRODUCTS is fixed at the prereg-v2-draft tag. One loop process per product, chosen by the environment
# variable JEVLOOP_PRODUCT (unset: SOL-USD, the v1 stream, unbroken); a value not in PRODUCTS is refused
# before any directory is made (loop.cycle.main exits 2). Every per-product table below (TICK_P, LIQ_ATOMS,
# LIQ_THIN_FALLBACK) holds exactly the products in PRODUCTS (tests/test_config.py).
PRODUCTS = (
    "SOL-USD",
    # >>> THE TWO PROBE PRODUCTS GO HERE (PREREG-v2 §2): the first two candidates that pass every criterion of
    # >>> `bin/probe summarize probe/2026-09-30`, in its order, each with its TICK_P and atoms below and a RULE_C
    # >>> pin in tests/test_frozen.py. Fewer than two passing: SOL-USD and what passed (§2).
)
PROBE_CANDIDATES = ("ETH-USD", "XRP-USD", "DOGE-USD", "AVAX-USD", "LINK-USD", "ADA-USD")   # PREREG-v2 §2, bin/probe's
                                   # order: their bases are product words a prompt file may not carry (loop/prompts.py)
ENV_PRODUCT = "JEVLOOP_PRODUCT"
EXCLUSIONS_V2 = os.path.join(DATA, "exclusions-v2.tsv")   # stop rule 3's log, Alex's (PREREG-v2 §9.3); REPO/data, global
LOOKS = os.path.join(DATA, "looks.tsv")                   # `report --unblind` appends one line per look (§9.5)

# The two trees this project must never run under. Resolved with realpath at
# startup; a match is exit 3 before anything else happens.
FORBIDDEN_PREFIXES = (
    os.path.expanduser("~/Projects/crypto-trading-system"),
    os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/crypto-trading-system-backup"),
)

# ---- Jev ----------------------------------------------------------------------
JEV_URL = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai") + "/v1/systemone"
MODEL = "jev-1.13.0"               # pinned: every JEV threshold was calibrated on it; the server
                                   # reports the model that answered and a mismatch is logged as drift
JEV_TIMEOUT_S = 20
USD_PER_MTOK = 0.042               # $0.042 per million INPUT tokens; output is free (docs, 2026-09-23)
DAILY_SPEND_HALT_USD = 0.25 * len(PRODUCTS)   # $0.25 a product (PREREG-v2 §2): one tripwire over every product's
                                   # decision log, ~5x the estimate; a runaway writes data/HALT and stops SENDING only
JEV_TOKENS_IF_UNKNOWN = 2000       # the spend guard's charge for a send whose row carries input_tokens 0 or
                                   # null (a reply with no `usage`, or a send that failed after it left):
                                   # counting it as 0 would blind the tripwire. The body is ~1.8 KB (~450
                                   # tokens at 4 chars/token; ~600 billed is the estimate), so 2000 is a
                                   # ceiling, >3x. At 2000 the guard trips at ~2,976 such sends in a UTC
                                   # day, 2x the cadence: a runaway (double-firing, a loop bug), not a day
KEY_PATHS = (                      # first hit wins; the loop's own key is preferred so a loop-triggered
    ("env", "TYPESAFE_API_KEY_LOOP"),                                   # limit never touches the
    ("file", os.path.expanduser("~/.secondbrain-secrets/typesafe-api-key-loop")),  # brain's live screen
    ("env", "TYPESAFE_API_KEY"),
    ("file", os.path.expanduser("~/.secondbrain-secrets/typesafe-api-key")),
)

# ---- the alphabet: code computes numbers, the model sees words ------------------
NOTIONAL_USD = 1000.0              # paper order size; also the liquidity yardstick
# liq, 2026-09-24, decided by Alex: the word is the cost of WALKING THE BOOK for one NOTIONAL_USD
# market order, not the size of level 1. Twelve product_book samples over 60 s: top-of-book
# min-side USD swung $1 to $11,580 and read "thin" 7/12 under the old l1_min_usd < $1000 rule,
# while a $1,000 order's VWAP-vs-mid cost was 0.44-2.02 bps (median 0.87) on both sides and ask
# depth within 5 bps was $91k-$191k: the old word was a coin flip that randomly blocked arm C's
# buys. fill1k_bps = max(buy, sell) of 1e4 * |VWAP - mid| / mid over the first BOOK_LEVELS levels.
BOOK_LEVELS = 100                  # product_book limit; 100 levels at a 1c tick is ~$1.3 of price
                                   # (8.4 KB, 0.22 s in the recording), orders of magnitude past $1,000
LIQ_THIN_BPS = 5.0                 # v1's cut (SPEC v1 §5), kept because every v1 row was read by it: fill1k_bps above
LIQ_DEEP_BPS = 1.0                 # 5.0 (or a short side) -> thin, below 1.0 -> deep. v2 reads liq in h (below):
                                   # thin held 0 of 3,467 v1 rows, the cuts sat outside where the cost lives
                                   # (PREREG-v2 §0.2, §3). Nothing in loop/ reads these two any more.
# liq, v2 (PREREG-v2 §3): h = fill1k_bps * mid / (1e4 * TICK_P / 2), the fill cost in half-tick units (at a
# level-1 fill, the spread in ticks); deep iff h < a10 + 0.5, thin iff h > a90 + 0.5 (or a90 - 0.5 where the
# window's thin fallback ran) or fill1k_short, normal otherwise, deep read first. a10/a90 are the integer atoms
# nearest the nearest-rank p10/p90 of h over the product's window, printed by bin/fill1k-quantiles (SOL-USD,
# 2026-09-29 06:30Z: a10 1, a90 4, thin_fallback no) and bin/probe summarize (the probe products).
TICK_P = {"SOL-USD": 0.01}         # the product's price tick in USD (§2: the mode of the book's level step)
LIQ_ATOMS = {"SOL-USD": (1, 4)}    # (a10, a90): SOL deep iff h < 1.5 (a one-tick spread), thin iff h > 4.5
LIQ_THIN_FALLBACK = {"SOL-USD": False}   # True only where the window's thin held < 3 % at a90 + 0.5
FLOW_P_LO, FLOW_P_HI = 10, 90      # 5-min traded volume vs percentiles of the window's 5-min sums
TREND_Z = 1.0                      # 15-min log return, z-scored by the window's sd of 15-min returns
VOL_RATIO_LO, VOL_RATIO_HI = 0.5, 2.0   # realised 15-min variance vs the window's median
WINDOW_MIN = 300                   # minutes of 1m candles required (Coinbase serves <= 350 per call)
DEAD_BAND_BPS = 5.0                # |ret_h| below this is "flat" for the outcome label
CADENCES = (900, 3600, 14400)      # PREREG-v2 §4: the decision-held replay cadences (s); the loop still ticks at CADENCE_S
FROZEN_A = "v2"                    # PREREG-v2 §1: arm A's frozen wording, prompts/v2.json, rendered per product

# ---- paper execution --------------------------------------------------------------
# 2026-09-24, decided by Alex: H1 is measured at 0 bps, GROSS (PREREG §4). Coinbase Advanced
# retail tier 0 ("Intro 1", < $1K 30-day volume) is 0.60% maker / 1.20% TAKER per two sources
# updated April 2026 (tokenecho.io, cryptofeediscount.com; fetched 2026-09-24); the official table
# (coinbase.com/advanced-fees) is behind sign-in. A round trip at 120 bps is 240 bps against a
# 15-minute sd of ~33 bps, so profitability at retail fees is settled by arithmetic, and a NET H1
# would mostly rank which arm trades least. At 0 bps, gross of fees, a difference between arms is
# direction NET OF THE SPREAD, which is the question: turnover still costs one spread per round trip
# (open at the ask, close at the bid, marked to mid: 0.87 bps at 1c, 1.74 at 2c on ~$115, the order
# of PREREG §7's 1.78 bps per-block MDE), so trades/day is read beside the cell. Every net-of-fee
# column is descriptive.
FEE_BPS_PRIMARY = 0.0              # the H1 cell (PREREG §4): gross of fees, not of the spread
FEE_BPS_VENUE = 120.0              # the venue's own retail taker: the realistic-cost column, descriptive
FEE_BPS_VENUE_SOURCE = ("UNVERIFIED — Coinbase Advanced Intro 1 taker per secondary sources "
                        "(April 2026); confirm at https://www.coinbase.com/advanced-fees signed in")
FEE_BPS_COLUMNS = (0.0, 2.0, 10.0, 25.0, 60.0, 120.0)   # ascending, the same decisions at six constants:
                                                        # 0 = gross, the H1 cell; 2 = Binance.US; 10 = the
                                                        # article's; 25; 60 = venue maker; 120 = venue taker

# ---- rule columns ----------------------------------------------------------------
CONF_THRESHOLDS = (0.50, 0.70, 0.85, 0.99)  # 0.99 is the only measured tail (JEV PROTOCOL 2.2); the
VETO_NOUL = 0.5                             # rest are the unmeasured band this project measures
PBUY = 0.60
NOUL_TAIL = 0.99


# ---- v2 accessors: every per-product path and cut is computed here, at call time (tests patch DATA etc.) --------
def base(product):
    """"SOL" for "SOL-USD": the word in front of the state string's colon, and the token prompts/v2.json renders."""
    return product.split("-")[0]


def _known(product):
    if product not in PRODUCTS:
        raise ValueError(f"product {product!r} is not in config.PRODUCTS {PRODUCTS}")
    return product


Store = collections.namedtuple("Store", "decisions sends lock heartbeat")   # one product's own four files


def store(product):
    """The decision log, sends ledger, lock and heartbeat of one product (PREREG-v2 §2): under data/ for SOL-USD,
    the v1 paths exactly (DECISIONS, SENDS, LOCK, HEARTBEAT, read now so a test's patch applies), and under
    data/<PRODUCT>/ for any other product in PRODUCTS. HALT, PAUSE.*, EXCLUSIONS_V2 and LOOKS are not in a store:
    they sit at REPO/data/ whatever the product. A product not in PRODUCTS raises ValueError (it would be a path)."""
    _known(product)
    if product == PRODUCT:
        return Store(DECISIONS, SENDS, LOCK, HEARTBEAT)
    d = os.path.join(DATA, product)
    return Store(os.path.join(d, "decisions.jsonl"), os.path.join(d, "sends.tsv"),
                 os.path.join(d, "loop.lock"), os.path.join(d, "heartbeat"))


def pause(product):
    """data/PAUSE.<PRODUCT>: that product's loop skips its send (absence "halt") while observation goes on.
    The nightly and the spend guard ignore it; data/HALT stays the one global stop (PREREG-v2 §2)."""
    return os.path.join(DATA, "PAUSE." + _known(product))


def loop_product(environ=None):
    """The product this loop process ticks: JEVLOOP_PRODUCT, or SOL-USD when it is unset. A value not in PRODUCTS
    (an empty string included) raises ValueError; loop.cycle.main turns that into exit 2 before any directory."""
    env = os.environ if environ is None else environ
    if ENV_PRODUCT not in env:
        return PRODUCT
    p = env[ENV_PRODUCT]
    if p not in PRODUCTS:
        raise ValueError(f"{ENV_PRODUCT}={p!r} is not in config.PRODUCTS {PRODUCTS}")
    return p


def liq_cuts(product):
    """(deep_below, thin_above) in h for one product: a10 + 0.5 and a90 + 0.5 (a90 - 0.5 after the window's
    thin fallback), PREREG-v2 §3, the rule bin/fill1k-quantiles prints."""
    a10, a90 = LIQ_ATOMS[_known(product)]
    return a10 + 0.5, (a90 - 0.5 if LIQ_THIN_FALLBACK[product] else a90 + 0.5)

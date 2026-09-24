"""Constants. Frozen once SPEC.md is written; changing any value below after row 1
changes what arm C IS, so it is a new experiment, not a tweak.

Everything a module might be tempted to hard-code lives here so the report, the
tests and SPEC.md all read one source. Nothing in this file reads the network
or the key.
"""
import os

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
DAILY_SPEND_HALT_USD = 0.25        # ~5x the estimate; a runaway writes data/HALT and stops SENDING only
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
LIQ_THIN_BPS = 5.0                 # fill1k_bps above this (or a side the levels cannot fill) -> thin
LIQ_DEEP_BPS = 1.0                 # fill1k_bps below this -> deep. The half-spread alone is ~0.44 bps
                                   # at a 1c tick on ~$115, so deep and normal are both common and
                                   # thin is a real dislocation; the report's > 95% flag is the check
FLOW_P_LO, FLOW_P_HI = 10, 90      # 5-min traded volume vs percentiles of the window's 5-min sums
TREND_Z = 1.0                      # 15-min log return, z-scored by the window's sd of 15-min returns
VOL_RATIO_LO, VOL_RATIO_HI = 0.5, 2.0   # realised 15-min variance vs the window's median
WINDOW_MIN = 300                   # minutes of 1m candles required (Coinbase serves <= 350 per call)
DEAD_BAND_BPS = 5.0                # |ret_h| below this is "flat" for the outcome label

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

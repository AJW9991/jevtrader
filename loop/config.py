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
LIQ_THIN_USD = NOTIONAL_USD        # l1_min_usd below this: the top of book cannot absorb one order
LIQ_DEEP_USD = 10 * NOTIONAL_USD
FLOW_P_LO, FLOW_P_HI = 10, 90      # 5-min traded volume vs percentiles of the window's 5-min sums
TREND_Z = 1.0                      # 15-min log return, z-scored by the window's sd of 15-min returns
VOL_RATIO_LO, VOL_RATIO_HI = 0.5, 2.0   # realised 15-min variance vs the window's median
WINDOW_MIN = 300                   # minutes of 1m candles required (Coinbase serves <= 350 per call)
DEAD_BAND_BPS = 5.0                # |ret_h| below this is "flat" for the outcome label

# ---- paper execution --------------------------------------------------------------
# The venue's own taker fee is the PRIMARY. Coinbase Advanced retail tier 0
# ("Intro 1", < $1K 30-day volume) is 0.60% maker / 1.20% TAKER per two sources
# updated April 2026 (tokenecho.io, cryptofeediscount.com; fetched 2026-09-24).
# An earlier placeholder here said 60 bps was the taker rate — that is the maker
# rate. The official table (coinbase.com/advanced-fees) is behind sign-in, so
# this stays UNVERIFIED until Alex reads it in-account, before PREREG.md is sealed.
#
# Consequence worth knowing before sealing: a round trip at 120 bps is 240 bps
# against a 15-minute sd of ~33 bps, so any NET comparison mostly ranks which
# arm trades least. The 0 bps column is the only one that measures direction.
FEE_BPS_PRIMARY = 120.0
FEE_BPS_PRIMARY_SOURCE = ("UNVERIFIED — Coinbase Advanced Intro 1 taker per secondary sources "
                          "(April 2026); confirm at https://www.coinbase.com/advanced-fees signed in")
FEE_BPS_COLUMNS = (120.0, 60.0, 25.0, 10.0, 2.0, 0.0)   # same decision, different constant: venue taker,
                                                        # venue maker, 10 = the article's, 2 = Binance.US,
                                                        # 0 = gross, the direction-only control

# ---- rule columns ----------------------------------------------------------------
CONF_THRESHOLDS = (0.50, 0.70, 0.85, 0.99)  # 0.99 is the only measured tail (JEV PROTOCOL 2.2); the
VETO_NOUL = 0.5                             # rest are the unmeasured band this project measures
PBUY = 0.60
NOUL_TAIL = 0.99

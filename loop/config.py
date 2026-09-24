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
# The venue's own taker fee is the PRIMARY. It is UNVERIFIED as of this file: the
# fixtures builder must fetch the Coinbase Advanced fee page, record the tier-0
# taker rate and the URL here, and the value must be confirmed before PREREG.md
# is sealed. 60 bps is the widely quoted retail tier-0 taker rate and is the
# conservative placeholder.
FEE_BPS_PRIMARY = 60.0
FEE_BPS_PRIMARY_SOURCE = "UNVERIFIED — placeholder; see CONTRACT.md §2 Book"
FEE_BPS_COLUMNS = (60.0, 25.0, 10.0, 2.0)   # same decision, different constant; 10 = the article's, 2 = Binance.US

# ---- rule columns ----------------------------------------------------------------
CONF_THRESHOLDS = (0.50, 0.70, 0.85, 0.99)  # 0.99 is the only measured tail (JEV PROTOCOL 2.2); the
VETO_NOUL = 0.5                             # rest are the unmeasured band this project measures
PBUY = 0.60
NOUL_TAIL = 0.99

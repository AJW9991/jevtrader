"""The frozen inputs, pinned. An edit to any of them fails `make test` on the Mac and in CI the day it is made, not at
day 28. A deliberate change updates its pin here IN THE SAME COMMIT as the file it pins, and the message says why.

v2 (PREREG-v2 §10, "tests/test_frozen.py at the draft tag pins by sha"): SPEC v2 (every v2 row carries its sha),
CONTRACT.md, PREREG-v2.md (its CURRENT bytes: the author re-pins it in the same commit as each §14 amendment, and after
the draft tag bin/seal-check lets only that line and the v2 tables' lines of this file change, §13 (c)),
nightly/PROMPT.md v2 (the treatment), the sources of nightly/digest.py and nightly/policy_table.py (the treatment's
inputs), the call's shape (§8: "an empty temp cwd; tools off; nightly/settings.json; the 45-min cap; no user memory",
all in nightly/propose.sh, nightly/settings.json and nightly/capped.py; beyond §10's list), prompts/v2.json (arm A)
and one v2 table per product (arm D; pinned in V2_TABLES as STEPS §10.3 commits each, before the draft tag); by value
THRESHOLDS with TICK_P and the per-product atoms, every constant SPEC §14 names (SPEC14: the set is SPEC's own,
tests/test_spec.py's spec14), the inference constants (the seeds, L, R, the ranks), and RULE_C per product. The pins
of PREREG-v2.md and of the v2 tables stay one per line, `"<path>": "<sha256>",`, the form bin/seal-check's PIN_LINE
reads.

v1 (CLAUDE.md: nothing on v1's list changes until 2026-10-23 21:40Z): PREREG.md and prompts/v1.json are read by v1's
readers from this tree and keep their pins in FILES; SPEC.md and nightly/PROMPT.md moved to their v2 text in this
build, so v1's bytes are resolved where v1 froze them, `git show prereg-v1:<path>` (V1_FILES; skipped in a clone with
no tags, as CI's is), and a v1 row's spec_sha is dash.V1_SPEC_SHA. The v1 pins were taken 2026-09-28 from bytes
identical to the sealed prereg-v1 commit (cfaa3f9), and v2.json's from its promote commit (d155042).

Not pinned: prompts/CURRENT and any prompt file after v2 (bin/promote writes those, and no test depends on what CURRENT
names); PROTOCOL.md (Alex's signed carve-out, not an input of the measurement); the digest's bytes on a fixed day (its
own golden test, tests/test_digest_v2.py).
"""
import hashlib, json, os, re, subprocess, unittest
from fractions import Fraction

from loop import config, dash, inference_v2, state
from test_slow_model import id_and_night
from test_spec import load, spec14

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = {                                            # sha256 of the bytes on disk
    "SPEC.md": "c13ee48706c58a5d2403c4b7de11c6c74b99960adef95ffaf3677cefd0bb707a",   # SPEC v2 (PREREG-v2 §10), 2026-09-29;
                                                 # v1's 5d4f355e... stays in prereg-v1 (V1_FILES)
    "CONTRACT.md": "42c79efa62d10ba4663b1c0a3a7b5634a9501a378c037a33a7343d1e720c44bb",   # v2's interfaces, 2026-09-29
    "PREREG-v2.md": "0b417be4cc2f4555ab004f2187bb6eab3f487c33785aa26c3c05d6a451e602e6",
    "PREREG.md": "28dab0a9cba8bb21a596fe06f3a19302476f42e3efbbe40b41480898266b7882",
    "nightly/PROMPT.md": "7ebcd64071700b6da578078e5eec10a846a56852a3c6de54bfd7ce8d786a1e50",   # v2 text (PREREG-v2 §8), 2026-09-29;
                                                 # v1's d20cc08e... stays in prereg-v1 (V1_FILES)
    "nightly/digest.py": "323f657c990490bee55e39ddb21887f544f4bbe587e93f920bca9ae5b18e5af6",   # the digest's content (§8)
    "nightly/propose.sh": "c5ed12b465da5fa5ae53f96e0cc3f83c50ee918487e0ac76a7c11de41ec334c6",   # the call's shape (§8): empty cwd, tools off,
                                                 # --settings, the 45-min cap, CLAUDE_CONFIG_DIR, --model
    "nightly/settings.json": "0a6ed21f0bad3058900388daca799fa0b49bb6c10ddfc34d9f6c7111d7f0cfe5",   # the call's permissions (§8)
    "nightly/capped.py": "9bf29eaed255592606ae96a79f50234a7795eba83d1bca7bd7c7347141b34bbc",   # the cap on awake time (§8)
    "nightly/policy_table.py": "d54fa8bdbfc9d3f8005703ee934c9c3b4562330c8a058898e68564357c0a84d2",   # candidate scoring (§8)
    "prompts/v1.json": "207ed69be0ce6cb8d22ac81519a4db6845ab92d643c2772f150cabfe9efe57a0",
    "prompts/v2.json": "dcc848e5ad1452bede8631cf0d2f9801175070746ced883857e86366ec4a8ab4",
}

V1_TAG = "prereg-v1"
V1_FILES = {                                         # sha256 of `git show prereg-v1:<path>`: what v1's sample is read by
    "SPEC.md": "5d4f355e181739ae2a65a6496ecddf195d9dde7c7668c7606c19d795c5254ca7",
    "PREREG.md": "28dab0a9cba8bb21a596fe06f3a19302476f42e3efbbe40b41480898266b7882",
    "nightly/PROMPT.md": "d20cc08e3c757bb7e37f0638037bf3e29b7c4176d371bd8a94233ba7adfdfb6b",
    "prompts/v1.json": "207ed69be0ce6cb8d22ac81519a4db6845ab92d643c2772f150cabfe9efe57a0",
}

# >>> v2's own tables (PREREG-v2 §8, §10; STEPS §10.3): one line per product, `"prompts/v2.table.<PRODUCT>.json":
# >>> "<sha256 of the file>",`, added in the commit that commits the table (bin/promote --table-only writes them), before
# >>> the draft tag; after it only §8's once-only rebuild at the switch changes a line here (bin/seal-check (c)).
V2_TABLES = {
}

THRESHOLDS = {                                       # what a row's words, columns and label are computed from
    "VENUE": "coinbase", "PRODUCT": "SOL-USD", "CADENCE_S": 60, "HORIZON_S": 900, "MODEL": "jev-1.13.0",
    "JEV_TIMEOUT_S": 20,                             # SPEC: which slow answers become absence "jev" rows
    "NOTIONAL_USD": 1000.0, "BOOK_LEVELS": 100, "LIQ_THIN_BPS": 5.0, "LIQ_DEEP_BPS": 1.0,
    "FLOW_P_LO": 10, "FLOW_P_HI": 90, "TREND_Z": 1.0, "VOL_RATIO_LO": 0.5, "VOL_RATIO_HI": 2.0,
    "WINDOW_MIN": 300, "DEAD_BAND_BPS": 5.0, "FEE_BPS_PRIMARY": 0.0,
    "CONF_THRESHOLDS": (0.50, 0.70, 0.85, 0.99), "VETO_NOUL": 0.5, "PBUY": 0.60, "NOUL_TAIL": 0.99,
    # PREREG-v2 §2-§4, §10 (pinned 2026-09-29 with the constants themselves; the two probe products, their TICK_P
    # and atoms join PRODUCTS here in the commit that adds them to loop/config.py, before the draft tag)
    "PRODUCTS": ("SOL-USD",), "TICK_P": {"SOL-USD": 0.01}, "LIQ_ATOMS": {"SOL-USD": (1, 4)},
    "LIQ_THIN_FALLBACK": {"SOL-USD": False}, "CADENCES": (900, 3600, 14400), "FROZEN_A": "v2",
}

# Every constant SPEC.md §14 names, by value (PREREG-v2 §10: "every §14 constant"); the key set is SPEC §14's own.
SPEC14 = {
    ("loop.config", "VENUE"): 'coinbase',
    ("loop.config", "PRODUCT"): 'SOL-USD',
    ("loop.config", "PRODUCTS"): ('SOL-USD',),
    ("loop.config", "PROBE_CANDIDATES"): ('ETH-USD', 'XRP-USD', 'DOGE-USD', 'AVAX-USD', 'LINK-USD', 'ADA-USD'),
    ("loop.config", "ENV_PRODUCT"): 'JEVLOOP_PRODUCT',
    ("loop.config", "CADENCE_S"): 60,
    ("loop.config", "HORIZON_S"): 900,
    ("loop.config", "CADENCES"): (900, 3600, 14400),
    ("loop.config", "FROZEN_A"): 'v2',
    ("loop.config", "MODEL"): 'jev-1.13.0',
    ("loop.config", "JEV_TIMEOUT_S"): 20,
    ("loop.config", "USD_PER_MTOK"): 0.042,
    ("loop.config", "DAILY_SPEND_HALT_USD"): 0.25,
    ("loop.config", "NOTIONAL_USD"): 1000.0,
    ("loop.config", "BOOK_LEVELS"): 100,
    ("loop.config", "TICK_P"): {'SOL-USD': 0.01},
    ("loop.config", "LIQ_ATOMS"): {'SOL-USD': (1, 4)},
    ("loop.config", "LIQ_THIN_FALLBACK"): {'SOL-USD': False},
    ("loop.config", "LIQ_THIN_BPS"): 5.0,
    ("loop.config", "LIQ_DEEP_BPS"): 1.0,
    ("loop.config", "FLOW_P_LO"): 10,
    ("loop.config", "FLOW_P_HI"): 90,
    ("loop.config", "TREND_Z"): 1.0,
    ("loop.config", "VOL_RATIO_LO"): 0.5,
    ("loop.config", "VOL_RATIO_HI"): 2.0,
    ("loop.config", "WINDOW_MIN"): 300,
    ("loop.config", "DEAD_BAND_BPS"): 5.0,
    ("loop.config", "JEV_TOKENS_IF_UNKNOWN"): 2000,
    ("loop.config", "FEE_BPS_PRIMARY"): 0.0,
    ("loop.config", "FEE_BPS_VENUE"): 90.0,
    ("loop.config", "FEE_BPS_VENUE_SOURCE"): ("verified: Coinbase Advanced spot taker, tier Intro (30-day volume $0), 0.90 %, maker 0.50 %;"
                                              " read in-account by Alex at https://www.coinbase.com/advanced-fees on"
                                              " 2026-09-27 ~22:55Z (ERRATA.md; SPEC.md's verified tier-0 taker row)"),
    ("loop.config", "FEE_BPS_COLUMNS"): (0.0, 2.0, 10.0, 25.0, 50.0, 90.0),
    ("loop.config", "CONF_THRESHOLDS"): (0.5, 0.7, 0.85, 0.99),
    ("loop.config", "VETO_NOUL"): 0.5,
    ("loop.config", "PBUY"): 0.6,
    ("loop.config", "NOUL_TAIL"): 0.99,
    ("loop.state", "LIQ"): ('thin', 'normal', 'deep'),
    ("loop.state", "FLOW"): ('quiet', 'organic', 'bot_war'),
    ("loop.state", "TREND"): ('dumping', 'flat', 'pumping'),
    ("loop.state", "VOL"): ('calm', 'normal', 'violent'),
    ("loop.state", "DIMS"): ('liq', 'flow', 'trend', 'vol'),
    ("loop.state", "FLOW_BLOCK_MIN"): 5,
    ("loop.state", "RET_BLOCK_MIN"): 15,
    ("loop.state", "BASE"): 'SOL',
    ("loop.feed", "CANDLES_REQ"): 350,
    ("loop.feed", "TRADES_WINDOW_S"): 300,
    ("loop.feed", "TRADES_LIMIT"): 1000,
    ("loop.feed", "TIMEOUT_S"): 10,
    ("loop.feed", "MAX_FEED_AGE_S"): 120,
    ("loop.feed", "START_MAX"): 1 << 40,
    ("loop.outcomes", "JOIN_TOL_S"): 30.0,
    ("loop.jev", "RETRY_S"): 1.0,
    ("loop.jev", "RETRY_AFTER_CAP_S"): 5.0,
    ("loop.rules", "COLUMNS"): ("argmax", "c50", "c70", "c85", "c99", "c50v", "c70v", "c85v", "c99v", "pbuy60",
                                "noultail"),
    ("loop.cycle", "WATCHDOG_S"): 50,
    ("loop.cycle", "TAIL_BYTES"): 8 << 20,
    ("loop.cycle", "ROW_V"): 1,
    ("loop.cycle", "UNSENT_KINDS"): ('unsigned', 'no-key', 'ledger'),
    ("loop.cycle", "SPEND_UNCOUNTED"): 1.7976931348623157e+308,
    ("loop.book", "ARMS"): ('a', 'b', 'c', 'd'),
    ("loop.book", "D_COLUMN"): 'argmax',
    ("loop.prompts", "LEGACY_TOKEN"): 'SOL',
    ("loop.prompts", "BASE_TOKEN"): '{BASE}',
    ("loop.prompts", "LEGACY_LAST"): 2,
    ("loop.prompts", "TABLE_ANSWERS"): ('buy', 'sell', 'hold'),
    ("loop.report", "PRIMARY"): ('b', 'c', 'argmax', 0.0),
    ("loop.report", "VENUE_FEE"): 90.0,
    ("loop.report", "BLOCK_S"): 900,
    ("loop.report", "SAMPLE_DAYS"): 28,
    ("loop.report", "PAIRS"): (('b', 'c'), ('a', 'c'), ('b', 'a'), ('d', 'b'), ('d', 'c')),
    ("loop.report", "OCCUPANCY_FLAG"): 0.95,
    ("loop.report", "HEALTH_N"): 3,
    ("loop.report", "BAD_FILL"): 0.95,
    ("loop.report", "BAD_JEV_ERR"): 0.05,
    ("loop.report", "BAD_DAYS_PAUSE"): 3,
    ("loop.report", "NOUL_HIGH"): 0.99,
    ("loop.report", "NOUL_LOW"): 0.15,
    ("loop.report", "LEAN_DP"): 12,
    ("loop.report", "VOID_KEPT_DAYS"): 21,
    ("loop.report", "LOOKUP_AT"): 0.99,
    ("loop.report", "DRIFT_BELOW"): 0.95,
    ("loop.report", "MODAL_MIN"): 10,
    ("loop.report", "GAP_S"): 900,
    ("loop.report", "BREAK_EVEN_FEE"): 90.0,
    ("loop.report", "FEE_EPS"): 1e-09,
    ("loop.report", "F_CELLS"): {(3600, 'b', 'c'): 'F1', (14400, 'b', 'c'): 'F2', (900, 'a', 'c'): 'F3', (900, 'b', 'a'): 'F4'},
    ("loop.report", "ERRATA_TIER"): {'name': 'Intro', 'band': 'at 30-day volume $0', 'low': 0.0, 'high': None, 'maker': 50.0,
                                     'taker': 90.0},
    ("loop.report", "ERRATA_TIER_WHERE"): "ERRATA.md's 2026-09-27 reading (Alex, in-account, ~22:55Z)",
    ("loop.inference_v2", "SEED_H1"): 20261023,
    ("loop.inference_v2", "RESAMPLES"): 10000,
    ("loop.inference_v2", "BLOCK_LEN"): 4,
    ("loop.inference_v2", "ALPHA_H1"): Fraction(1, 40),
    ("loop.inference_v2", "ALPHA_F"): Fraction(1, 160),
    ("loop.inference_v2", "MIN_KEPT_DAYS"): 21,
    ("loop.inference_v2", "N_DAYS"): 28,
    ("loop.inference_v2", "POWER"): 0.8,
    ("loop.inference_v2", "FEE_COLUMNS"): (0.0, 2.0, 10.0, 25.0, 50.0, 90.0),
    ("loop.inference_v2", "SEAL_TAG"): 'prereg-v2-seal',
    ("loop.inference_v2", "SEAL_CHECK_TIMEOUT_S"): 3600,
    ("loop.exclusions_v2", "N_DAYS"): 28,
    ("nightly.digest", "FEES"): ((0.0, 'direction'), (50.0, 'venue maker'), (90.0, 'venue taker')),
    ("nightly.digest", "MAKER_BPS"): 50.0,
    ("nightly.digest", "TAKER_BPS"): 90.0,
    ("nightly.digest", "DISAGREE_CONF"): 0.85,
    ("nightly.digest", "DISAGREE_MAX"): 25,
    ("nightly.policy_table", "DEADLINE_S"): 900.0,
    ("nightly.policy_table", "MAX_CANDIDATES"): 3,
    ("nightly.policy_table", "MAX_TRANSIENT_RUN"): 3,
    ("nightly.policy_table", "MAX_OTHER_RUN"): 3,
    ("nightly.policy_table", "MAX_ERROR_RUN"): 3,
    ("nightly.policy_table", "CANDIDATE_VERSION"): 'v3',
    ("nightly.policy_table", "TABLE_SUFFIX"): '.table.json',
    # the slow model's id and night are PREREG-v2 §8's (blank underscores there are "" here): pinned through
    # PREREG-v2.md's sha above, so filling §8 moves that one pin and nightly/slow_model.py, not a line here
    ("nightly.slow_model", "MODEL_ID"): "" if set(id_and_night()[0][0]) <= {"_"} else id_and_night()[0][0],
    ("nightly.slow_model", "NIGHT"): "" if set(id_and_night()[0][1]) <= {"_"} else id_and_night()[0][1],
    ("bin/promote", "E_MIN"): 8,                     # PREREG-v2 §8's schedule (a deviation touching it voids the draft
    ("bin/promote", "E_MAX"): 22,                    # tag, §13)
    ("bin/promote", "E_SPACING"): 7,
    ("bin/promote", "MAX_PROMOTIONS"): 3,
    ("bin/promote", "LEAD_S"): 600,
    ("bin/promote", "DAY_S"): 86400,
    ("bin/promote", "PREREG_TAG"): 'prereg-v2-seal',
    ("bin/promote", "DRAFT_TAG"): 'prereg-v2-draft',
    ("bin/promote", "TABLE_ONLY_VERSION"): 'v2',
}


ALPHABET = {"liq": ("thin", "normal", "deep"), "flow": ("quiet", "organic", "bot_war"),
            "trend": ("dumping", "flat", "pumping"), "vol": ("calm", "normal", "violent")}
# per product, sha256 of json.dumps([[state_string(adj, base), rule_c(adj)], ...]) over state.all_states(): arm C's
# answer on all 81 states, the product's base first in each string (PREREG-v2 §3: one pin per product, SOL-USD's the
# v1 pin unchanged; an added product's pin is set in the commit that adds it to config.PRODUCTS)
RULE_C = {"SOL-USD": "289e53281bde0399848a5911e236396a0269936ec5f5608498f1786e1d578bb6"}


def _rule_c_digest(product):
    pairs = [[state.state_string(a, config.base(product)), state.rule_c(a)] for a in state.all_states()]
    return hashlib.sha256(json.dumps(pairs).encode()).hexdigest(), pairs

INFERENCE_V2 = {"SEED_H1": 20261023, "RESAMPLES": 10000, "BLOCK_LEN": 4, "ALPHA_H1": Fraction(1, 40),
                "ALPHA_F": Fraction(1, 160), "MIN_KEPT_DAYS": 21, "N_DAYS": 28, "POWER": 0.8}
CELLS_V2 = (("H1", "b", "c", 900, 20261023, Fraction(1, 40)),       # §5
            ("F1", "b", "c", 3600, 20261024, Fraction(1, 160)),     # §6, i = 1..4, seed 20261023 + i
            ("F2", "b", "c", 14400, 20261025, Fraction(1, 160)),
            ("F3", "a", "c", 900, 20261026, Fraction(1, 160)),
            ("F4", "b", "a", 900, 20261027, Fraction(1, 160)))
RANKS_V2 = {"H1": 249, "F1": 62, "F2": 62, "F3": 62, "F4": 62}   # sorted[ceil(alpha R) - 1]

HOW = ("a frozen input changed. Before prereg-v2-draft a deliberate change updates its pin here in the same commit as"
       " the file, and says why (a PREREG-v2.md edit is also a dated §14 entry); after the tag only §13 (c)'s lines may"
       " change (bin/seal-check); v1's files do not change during v1's sample (CLAUDE.md). Otherwise revert it.")
PIN_FORM = re.compile(r'^    "(PREREG-v2\.md|prompts/v2\.table\.[A-Z0-9]+-[A-Z]+\.json)": "([0-9a-f]{64})",')   # bin/seal-check's PIN_LINE


def _sha(rel):
    with open(os.path.join(REPO, rel), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _at_tag(tag, rel):
    """The bytes of `rel` at `tag` (git show), or None where the tag is not in this clone (CI checks out one commit)."""
    try:
        r = subprocess.run(["git", "show", f"{tag}:{rel}"], cwd=REPO, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


class Frozen(unittest.TestCase):
    def test_the_frozen_files_are_byte_for_byte_the_pinned_ones(self):
        for rel, want in FILES.items():
            with self.subTest(file=rel):
                with open(os.path.join(REPO, rel), "rb") as fh:
                    got = hashlib.sha256(fh.read()).hexdigest()
                self.assertEqual(got, want, f"{rel}: {HOW}")

    def test_the_calls_shape_is_pinned(self):
        # PREREG-v2 §8 fixes before the draft tag, unchanged through the block, "the call's shape (an empty temp cwd;
        # tools off; nightly/settings.json; the 45-min cap; no user memory ...)": propose.sh makes the call, settings.json
        # is its --settings, capped.py holds the cap. None was pinned (the S6 refuter's defect 4)
        for rel in ("nightly/propose.sh", "nightly/settings.json", "nightly/capped.py"):
            self.assertIn(rel, FILES, rel)
        with open(os.path.join(REPO, "nightly", "propose.sh"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertRegex(src, r'(?m)^CLAUDE_CAP_S="\$\{JEVLOOP_CLAUDE_CAP_S:-2700\}"')          # 45 min awake
        self.assertIn('--settings "$REPO/nightly/settings.json"', src)
        self.assertIn("\"$REPO/nightly/capped.py\" \"$CLAUDE_CAP_S\"", src)
        with open(os.path.join(REPO, "CONTRACT.md"), encoding="utf-8") as fh:
            contract = " ".join(fh.read().split())
        self.assertIn("the call's shape (`nightly/propose.sh`, `nightly/settings.json`, `nightly/capped.py`; PREREG-v2 §8)",
                      contract)

    def test_v1s_files_are_the_ones_prereg_v1_froze(self):
        # PREREG-v2 §10: "a v1 row's spec_sha resolves with git show prereg-v1:SPEC.md"; PREREG.md and v1.json are still
        # read from this tree by v1's readers, so their pins here are prereg-v1's own bytes
        self.assertEqual(dash.V1_SPEC_SHA, V1_FILES["SPEC.md"])
        for rel in ("PREREG.md", "prompts/v1.json"):
            self.assertEqual(FILES[rel], V1_FILES[rel], rel)
        self.assertNotEqual(FILES["SPEC.md"], V1_FILES["SPEC.md"])            # SPEC v2 is not v1's SPEC
        blobs = {rel: _at_tag(V1_TAG, rel) for rel in V1_FILES}
        if any(b is None for b in blobs.values()):
            self.skipTest(f"no {V1_TAG} tag in this checkout (a shallow clone, as CI's): v1's bytes are checked on the Mac")
        for rel, blob in blobs.items():
            self.assertEqual(hashlib.sha256(blob).hexdigest(), V1_FILES[rel], f"{rel} at {V1_TAG}")

    def test_each_products_v2_table_is_pinned_once_it_exists(self):
        # PREREG-v2 §10: "one v2 table per product" pinned at the draft tag. The tables are built attended (STEPS §10.3)
        # after the probe names the products; until a product's table exists this test says so and skips, and
        # bin/seal-check --draft refuses the tag while any is missing (§13)
        for rel, want in V2_TABLES.items():
            with self.subTest(table=rel):
                self.assertTrue(os.path.exists(os.path.join(REPO, rel)), f"{rel} is pinned and absent: {HOW}")
                self.assertEqual(_sha(rel), want, f"{rel}: {HOW}")
        missing = []
        for p in config.PRODUCTS:
            rel = f"prompts/v2.table.{p}.json"
            if not os.path.exists(os.path.join(REPO, rel)):
                missing.append(p)
                continue
            with self.subTest(table=rel):
                self.assertIn(rel, V2_TABLES, f"{rel} exists and is not pinned: pin it in V2_TABLES in the commit that adds it")
        self.assertLessEqual({r.split(".table.", 1)[1][:-len(".json")] for r in V2_TABLES}, set(config.PRODUCTS))
        if missing:
            self.skipTest(f"no v2 table yet for {', '.join(missing)}: STEPS §10.3 builds each (policy_table on a CURRENT-only"
                          f" proposal, then bin/promote --table-only) and pins it in V2_TABLES, one line a table, before the"
                          f" draft tag")

    def test_the_seal_checks_pin_lines_are_one_per_line(self):
        # after the draft tag bin/seal-check (c) lets this file change only on PREREG-v2.md's and the v2 tables' pin
        # lines, each read in exactly this form (bin/seal-check PIN_LINE, STEPS §10.4)
        with open(os.path.abspath(__file__), encoding="utf-8") as fh:
            lines = [PIN_FORM.match(l) for l in fh.read().splitlines()]
        got = {m.group(1): m.group(2) for m in lines if m}
        self.assertEqual(got, {"PREREG-v2.md": FILES["PREREG-v2.md"], **V2_TABLES})
        with open(os.path.join(REPO, "bin", "seal-check"), encoding="utf-8") as fh:
            src = fh.read()
        pin_line = re.compile(eval(re.search(r"^PIN_LINE = re\.compile\((r'[^']*')\)", src, re.M).group(1)))
        self.assertTrue(pin_line.match(f'    "PREREG-v2.md": "{FILES["PREREG-v2.md"]}",'))
        self.assertTrue(pin_line.match(f'    "prompts/v2.table.SOL-USD.json": "{"0" * 64}",'))

    def test_every_spec_14_constant_is_the_pinned_value(self):
        self.assertEqual(set(SPEC14), spec14(), "SPEC §14's names and SPEC14's keys differ: " + HOW)
        for (module, name), want in SPEC14.items():
            with self.subTest(constant=f"{module}.{name}"):
                got = getattr(load(module), name)
                self.assertEqual(got, want, HOW)
                self.assertEqual(repr(got), repr(want), HOW)                     # 90 is not 90.0, 1/40 not 0.025

    def test_every_threshold_of_a_row_is_the_pinned_value(self):
        got = {k: getattr(config, k) for k in THRESHOLDS}
        self.assertEqual(got, THRESHOLDS, HOW)

    def test_the_state_alphabet_and_arm_c_on_every_state_are_the_pinned_ones(self):
        self.assertEqual(state.DIMS, ("liq", "flow", "trend", "vol"), HOW)
        self.assertEqual(state.ALPHABET, ALPHABET, HOW)
        self.assertEqual(sorted(RULE_C), sorted(config.PRODUCTS), "one RULE_C pin per product: " + HOW)
        for product, want in RULE_C.items():
            with self.subTest(product=product):
                got, pairs = _rule_c_digest(product)
                self.assertEqual(len(pairs), 81)
                self.assertTrue(all(s.startswith(config.base(product) + ": liquidity ") for s, _ in pairs))
                self.assertEqual(got, want, HOW)
        pairs = [[state.state_string(a), state.rule_c(a)] for a in state.all_states()]      # v1's form, no base given
        self.assertEqual(hashlib.sha256(json.dumps(pairs).encode()).hexdigest(), RULE_C["SOL-USD"], HOW)

    def test_the_v2_inference_constants_are_the_pinned_ones(self):
        self.assertEqual({k: getattr(inference_v2, k) for k in INFERENCE_V2}, INFERENCE_V2, HOW)
        self.assertEqual(tuple((c.name, c.x, c.y, c.c, c.seed, c.alpha) for c in inference_v2.CELLS), CELLS_V2, HOW)
        self.assertEqual({c.name: inference_v2.alpha_rank(c.alpha, inference_v2.RESAMPLES) for c in inference_v2.CELLS}, RANKS_V2, HOW)
        for c in inference_v2.CELLS:                                                     # exact, never a float that equals it
            self.assertIs(type(c.alpha), Fraction, c.name)
        self.assertNotEqual(Fraction(1, 160), 0.00625)                                   # the pin itself tells them apart

    def test_the_pins_catch_an_edit(self):
        # the check itself, not only its inputs: one changed byte, one changed threshold, one changed state
        # answer each give a different digest or value than the pinned one
        with open(os.path.join(REPO, "SPEC.md"), "rb") as fh:
            spec = fh.read()
        self.assertNotEqual(hashlib.sha256(spec + b" ").hexdigest(), FILES["SPEC.md"])
        self.assertNotEqual(dict(THRESHOLDS, PBUY=0.61), THRESHOLDS)
        pairs = [[state.state_string(a), state.rule_c(a)] for a in state.all_states()]
        pairs[0][1] = {"buy": "hold", "hold": "sell", "sell": "buy"}[pairs[0][1]]
        self.assertNotEqual(hashlib.sha256(json.dumps(pairs).encode()).hexdigest(), RULE_C["SOL-USD"])
        other = [[state.state_string(a, "ETH"), state.rule_c(a)] for a in state.all_states()]   # the base is in the pin
        self.assertNotEqual(hashlib.sha256(json.dumps(other).encode()).hexdigest(), RULE_C["SOL-USD"])
        self.assertNotEqual(repr(90), repr(SPEC14[("loop.config", "FEE_BPS_VENUE")]))            # a type change is caught
        self.assertFalse(PIN_FORM.match('    "PREREG-v2.md": "' + "0" * 64 + '"'))                  # the form needs its comma


if __name__ == "__main__":
    unittest.main()

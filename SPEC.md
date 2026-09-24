# SPEC — what one row means, frozen

**Status: FROZEN 2026-09-23.** This file is the description a sceptic reads. It
says what the loop measures, exactly, with every threshold named by its
`loop/config.py` constant and value, so that no number in a row has to be
inferred from code. It is not the pre-registration (`PREREG.md` — the test,
the sample, the stop rules) and not the carve-out (`PROTOCOL.md` — why this
may run at all). Nothing here decides anything; the tick logs, the report
compares.

Checked 2026-09-23 against the modules on disk: `loop/feed.py`, `state.py`,
`rules.py`, `prompts.py`, `jev.py`, `book.py`, `outcomes.py`, `prompts/v1.json`.
`loop/cycle.py` (the writer of the row) was not yet on disk when this file was
frozen; the row in §2 is what `CONTRACT.md` §2 says it writes and what every
reader module indexes. A divergence found when `cycle.py` lands is a defect in
`cycle.py`, not a reason to edit this file.

## 1. The loop in one paragraph

Every 60 s (`CADENCE_S = 60`) on this Mac, one tick reads the Coinbase Advanced
Trade PUBLIC market data for `SOL-USD` (`VENUE = "coinbase"`, `PRODUCT =
"SOL-USD"`; no key, no signature, three GETs), computes 13 numbers, turns them
into four words from a closed alphabet, sends the ~10-word state string once to
`jev-1.13.0` (`MODEL`) with five typed questions, and appends one JSON row. The
model never sees a number, a position, or an outcome. Every action rule is a
column derived afterwards from one logged answer; the paper book is replayed
from the log at report time; the outcome of a decision at t is the log's own
mid at t + 900 s (`HORIZON_S = 900`). Paper only, forward only, nothing
back-filled.

## 2. The row — one line of `data/decisions.jsonl` per tick, append-only

```
{ "v": 1, "tick_id": "YYYYMMDDTHHMM00Z", "ts_rx": ISO ms, "mode": "live"|"dry",
  "venue": "coinbase", "product": "SOL-USD", "cadence_s": 60, "horizon_s": 900,
  "bid","bid_size","ask","ask_size","mid": float, "book_time": str|null, "feed_age_s": float,
  "features": {...}, "adj": {...}, "state": str, "spec_sha": str,
  "prompt_a": "v1", "prompt_a_sha": str, "prompt_b": "vN", "prompt_b_sha": str,
  "model_requested": str, "model_answered": str|null, "drift": bool,
  "jev": {"latency_ms": int|null, "input_tokens": int|null, "error": str|null, "key_path": str|null},
  "answers": null | {"a_action":{...},"b_action":{...},"skip":{...},"up15":{...},"down15":{...}},
  "rule_c": "buy"|"sell"|"hold",
  "columns": {"a": {...}|null, "b": {...}|null},
  "absence": null | "feed"|"jev"|"halt"|"lock"|"guard" }
```

- `ts_rx` is this machine's clock at the ENTRY of the feed call (before the
  three GETs), ISO 8601 UTC with milliseconds and a `Z`. `tick_id` is `ts_rx`
  floored to the minute. A fetch that straddles :00 therefore cannot move the
  tick (`feed.py::snapshot`).
- `mid = (bid + ask) / 2`. Prices are floats parsed from the venue's strings.
- `features` are the 13 numbers of §4, logged and never sent. `adj` is the four
  words of §5. `state` is the one string the model sees (§5).
- `spec_sha` is the SHA-256 of this file's bytes. `prompt_a_sha` /
  `prompt_b_sha` are SHA-256 of the canonical JSON (`sort_keys`, no whitespace)
  of the whole prompt file, so a re-indent leaves the sha alone and a changed
  character does not (`prompts.py::canon`). `prompt_a` is always `v1`;
  `prompt_b` is the one name in `prompts/CURRENT`.
- `model_requested` is `MODEL`; `model_answered` is what the server reported,
  `null` when it reported none; `drift` is `model_answered != model_requested`.
- `jev.key_path` NAMES the key that answered (`env:TYPESAFE_API_KEY_LOOP`,
  `file:~/.secondbrain-secrets/typesafe-api-key-loop`, `env:TYPESAFE_API_KEY`,
  `file:~/.secondbrain-secrets/typesafe-api-key`; first hit wins). No value is
  ever logged. `jev.error` is a `JevError` kind: `no-key`, `ledger`,
  `http-4xx`, `http-429`, `http-5xx`, `timeout` (which also covers connection
  refused/reset/DNS: the kind set has no other transient slot), `parse`.
- `answers` is `null` in dry mode and on any absence; then `columns.a` and
  `columns.b` are `null` too (every key present, every value `null`:
  `rules.null_columns()`). `rule_c` is present whenever the state was computed,
  absence or not.
- A tick that fails before the feed still writes a row: `absence` set,
  `tick_id` and `ts_rx` always strings (`outcomes.load` drops a line without
  them), everything it could not fill `null`.
- Two rows can share one `tick_id` (a launchd double-fire; the second is
  `absence: "lock"`). Readers fold, never overwrite (§10, §11).

## 3. The feed (`loop/feed.py`)

Three unauthenticated GETs against `https://api.coinbase.com/api/v3/brokerage/market`
per tick, 10 s timeout each, no retry, no sleep; 0.05 req/s against the venue's
documented 10 req/s per IP:

| call | what is kept |
|---|---|
| `product_book?product_id=SOL-USD&limit=1` | L1 `bid`, `bid_size`, `ask`, `ask_size`, venue `book_time` |
| `products/SOL-USD/candles?start=ts_rx-21000&end=ts_rx&granularity=ONE_MINUTE` | 350 rows requested (`CANDLES_REQ = 350`, the venue's cap); the open minute is dropped, so 349 CLOSED one-minute candles (`start + 60 <= ts_rx`), sorted oldest first, floats. Fewer than `WINDOW_MIN = 300` closed rows raises `FeedError` |
| `products/SOL-USD/ticker?limit=1000&start=ts_rx-300&end=ts_rx` | `trades_5m` = count of trades with `time >= ts_rx - 300` (`TRADES_WINDOW_S = 300`); `1000` means "≥ 1000" (the venue keeps the newest `TRADES_LIMIT = 1000`); a failed or unparseable ticker call yields `-1` and the tick goes on, because nothing in §5 reads it |

`feed_age_s = ts_rx − (newest closed candle start + 60)`: 0–60 s when the
venue is current. A book or candles failure raises `FeedError` → row with
`absence: "feed"`. The recorded fixture set (2026-09-24T02:28:49Z, `fixtures/`)
pins the parsers; live and fixture go through the same `assemble()`.

## 4. Features (`loop/state.py::features`) — logged, never sent

The window is the LAST `WINDOW_MIN = 300` closed candles of the 349 the feed
returns; index −1 is the newest closed minute, which is "now". `close` is the
only price the venue closes the minute on and is the price used throughout.

| key | definition |
|---|---|
| `mid` | `(bid + ask) / 2` |
| `spread_bps` | `1e4 · (ask − bid) / mid` |
| `l1_min_usd` | `min(bid · bid_size, ask · ask_size)` — the smaller side of the top of book, in USD |
| `vol5_usd` | Σ over the last 5 candles (`FLOW_BLOCK_MIN = 5`) of `volume · close` (the candle carries base units and no notional) |
| `vol5_p10`, `vol5_p90` | nearest-rank percentiles (`FLOW_P_LO = 10`, `FLOW_P_HI = 90`) of the window's 60 NON-overlapping 5-minute sums, blocked from the END so the newest block is `vol5_usd` itself. Nearest rank = `sorted[ceil(p·N/100) − 1]` in integer arithmetic (`0.1·60` is `6.000000000000001` in floats) → ranks 6 and 54 of 60 |
| `ret15_bps` | `1e4 · ln(close[−1] / close[−16])` — the 15-minute log return (`RET_BLOCK_MIN = HORIZON_S / CADENCE_S = 15`) |
| `ret15_sd_bps` | SAMPLE sd (n−1) of all 285 OVERLAPPING 15-minute returns in the window (0.18 % from the population sd at n = 285) |
| `ret15_z` | `ret15_bps / ret15_sd_bps`; `0.0` when the sd is 0 |
| `rv15` | Σ of squared one-minute log returns over the last 15 candles (closes −16..−1) |
| `rv15_med` | median of the same sum over the window's 19 NON-overlapping 15-return blocks from the end (299 returns; the 14 oldest unused) |
| `rv_ratio` | `rv15 / rv15_med`; `1.0` when the median is 0 |
| `window_min` | 300, always: a shorter window is refused (`ValueError`), never approximated |

A window with no scale (300 equal closes, a stuck feed) reads `z = 0.0`,
`rv_ratio = 1.0`: the neutral words, so arm C holds.

## 5. The alphabet — the only words the model ever sees

Cuts are STRICT (`<`, `>`) exactly as `CONTRACT.md` §2 writes them: a value ON
a cut is not evidence of either extreme and takes the middle word.

| dim | feature | low word | low cut | middle word | high cut | high word |
|---|---|---|---|---|---|---|
| `liq` | `l1_min_usd` | `thin` | `< LIQ_THIN_USD = 1000.0` (= `NOTIONAL_USD`) | `normal` | `> LIQ_DEEP_USD = 10000.0` (= 10 · `NOTIONAL_USD`) | `deep` |
| `flow` | `vol5_usd` | `quiet` | `< vol5_p10` (`FLOW_P_LO = 10`) | `organic` | `> vol5_p90` (`FLOW_P_HI = 90`) | `bot_war` |
| `trend` | `ret15_z` | `dumping` | `< −TREND_Z = −1.0` | `flat` | `> +TREND_Z = +1.0` | `pumping` |
| `vol` | `rv_ratio` | `calm` | `< VOL_RATIO_LO = 0.5` | `normal` | `> VOL_RATIO_HI = 2.0` | `violent` |

The words live in `loop/state.py` (`LIQ`, `FLOW`, `TREND`, `VOL`, `DIMS`,
`ALPHABET`); the cuts in `loop/config.py`. `bot_war` keeps its underscore: one
token, no digit, the same spelling as in `prompts/v1.json`.

**State string** (`state.py::state_string`), the one thing arms A and B ride:

```
SOL: liquidity {liq}, flow {flow}, trend {trend}, vol {vol}
```

`SOL` is `PRODUCT.split("-")[0]`. Ten words after the colon, no digit (a digit
raises), no position (the two arms share one request on one state, and a
position would differ per arm). The 81 = 3⁴ states are enumerated in one fixed
order (`state.all_states()`: `liq`, `flow`, `trend`, `vol`, each in alphabet
order, `vol` fastest); the nightly's policy tables and the truth-table test
walk that order.

## 6. Arm C — the rule, exactly (`state.py::rule_c`)

```
buy   iff trend == pumping  and  vol != violent  and  liq != thin
sell  iff trend == dumping  or   vol == violent
hold  otherwise
```

`buy` and `sell` are exclusive (pumping ≠ dumping, and buy excludes violent),
so the order of the two tests is immaterial. `flow` never changes `rule_c`.
Truth table over the 81 states: **12 buy, 45 sell, 24 hold** (pinned by
`tests/test_state.py`). Intents are position-free: `buy` = want to be long,
`sell` = want to be flat, `hold` = no change; the book (§10) maps intent onto
the current position.

## 7. The three arms

| arm | what decides | where it comes from | changes when |
|---|---|---|---|
| **A** | Jev's answer to the FROZEN `v1` action question | `answers.a_action` → `columns.a` | never; `prompt_a_sha` is constant for the whole experiment |
| **B** | Jev's answer to the CURRENT action question | `answers.b_action` → `columns.b` | only when a person runs `bin/promote` (writes `prompts/v<N+1>.json` and `prompts/CURRENT`); identical to A until the first promote, which is a free test-retest of the model |
| **C** | `rule_c` — no model | `rule_c` | never; §6 is the whole arm |

A and B ride ONE request on ONE state string with ONE shared set of `skip`,
`up15`, `down15` answers (`prompts.build`: the three nouls always come from
`v1`). The only thing that can differ between A and B is the wording of the
`action` question. C sees the same four words.

## 8. The questions (`prompts/v1.json`, `prompts.py::build`)

Wire shape per question: `{"type": "choice"|"noul", "instructions": str,
"criteria": {...}}`. Choice criteria keys are exactly `buy`, `sell`, `hold`;
noul criteria keys are exactly `yes`, `no`. Five questions per request, in row
order: `a_action` (v1 action, choice), `b_action` (CURRENT action, choice),
`skip`, `up15`, `down15` (v1 nouls). `v1.json` was frozen 2026-09-23; its
canonical sha begins `7a85308fd126`. Its `action` criteria restate §6 on
purpose: arm A measures how faithfully the model follows a rule it is given.
Only `action` is ever rewritten; a promoted file that changed a noul's type
is refused at load (`PromptError`).

## 9. The rule columns (`loop/rules.py::columns`)

One dict per arm, keys in this order (`rules.COLUMNS`); every comparison is
`>=` (a value exactly on a cut passes it):

| column | value | constant |
|---|---|---|
| `argmax` | `action.choice` | — |
| `c50`, `c70`, `c85`, `c99` | `choice` if `action.confidence >= k` else `hold` | `CONF_THRESHOLDS = (0.50, 0.70, 0.85, 0.99)`; 0.99 is the one measured tail (JEV PROTOCOL §2.2), the rest are the band this project measures |
| `c50v`, `c70v`, `c85v`, `c99v` | as above, but `hold` if `skip.noul >= VETO_NOUL` | `VETO_NOUL = 0.5` (the veto is a hold, never a sell) |
| `pbuy60` | `buy` if `p.buy >= PBUY`, else `sell` if `p.sell >= PBUY`, else `hold` | `PBUY = 0.60` |
| `noultail` | `buy` if `up15.noul >= NOUL_TAIL`, else `sell` if `down15.noul >= NOUL_TAIL`, else `hold` | `NOUL_TAIL = 0.99`; `up15` tested first, as the contract lists it |

If ANY of the four answers is missing the whole dict is `null` values. A
missing optional field reads as no signal (`confidence → 0.0`, `probabilities
→ {}`, `noul → 0.0`). A `choice` outside `buy/sell/hold` is refused before it
can reach the log. Nothing in the tick reads a column; `make report` compares
them.

## 10. Paper execution (`loop/book.py`) — pure, replayed from the log

- One paper order of `NOTIONAL_USD = 1000.0`. `pos` is `None` (flat) or
  `{"qty", "entry"}`. Only two of the six (position, intent) cases trade:
  - `buy` when flat → open: `qty = NOTIONAL / ask`, `fee = NOTIONAL · fee_bps / 1e4`;
  - `sell` when long → close at `bid`: `fee = qty · bid · fee_bps / 1e4` (the
    filled value, what the venue charges; at a 1c spread on ~$200 SOL this
    differs from "fee on notional" by ~0.003 bps at 60 bps);
  - `buy` when long, `sell` when flat, `hold` → no-op.
- Mark to `mid` every tick. Per-tick pnl, in bps of `NOTIONAL`, computed
  DIRECTLY (not as an equity difference, so two arms with the same position
  and different cash histories give `d_t == 0.0` exactly):
  - carried position: `qty · (mid_t − mid_prev)`
  - open at ask: `qty · (mid_t − ask) − fee`
  - close at bid: `qty · (bid − mid_prev) − fee`
- `replay(rows, outcomes, arm, column, fee_bps)` walks rows in `tick_id`
  order; arm `a`/`b` reads `columns[arm][column]`, arm `c` reads `rule_c`.
  Returns `equity` (cumulative bps), `trades`, `pnl_bps_per_tick`, and —
  additive to the contract — `position` (qty after each tick, `0.0` flat) and
  `forced_hold`. A row with `absence` set, `null` columns, or an unpriced
  book is a forced `hold` for EVERY arm (an outage never manufactures a
  disagreement), pnl `0.0`, position carried; the move across a gap lands on
  the first priced tick after it. A dry row is a real hold for C and a forced
  one for A/B. Two rows with one `tick_id` fold (`+=`). The `outcomes`
  argument is accepted and unused: a mark-to-mid book needs no t+h join, and
  using one would let t see t+h.
- `paired(rows, outcomes, x, y, column, fee_bps) → [(tick_id, d_t)]`,
  `d_t = pnl_x − pnl_y`; exactly `0.0` on any tick both arms carry the same
  position into and out of.

**Fees.** `FEE_BPS_COLUMNS = (60.0, 25.0, 10.0, 2.0)`: the same decisions
replayed at four constants (10 = the article's, 2 = Binance.US). The PRIMARY is
`FEE_BPS_PRIMARY = 60.0`, meant to be the venue's own taker fee, and it is
**UNVERIFIED**: `FEE_BPS_PRIMARY_SOURCE = "UNVERIFIED — placeholder"`. What was
gathered 2026-09-24 (feed builder): two third-party fee tables dated April 2026
put the retail Coinbase Advanced tier "Intro 1" (< $1K 30-day volume) at 0.60 %
MAKER / **1.20 % TAKER**; the institutional Coinbase Exchange page shows "Up to
$10k: taker 0.60 %". 60 bps therefore matches the Advanced maker or the
Exchange taker, not the retail Advanced taker. The official retail page
(`https://www.coinbase.com/advanced-fees`) is behind sign-in and must be read
in-account. A round trip costs 2 × fee: 120 bps at 60, 240 bps at 120.

```
Verified tier-0 taker fee: ________ bps   URL: ______________________________   read (UTC): ____________
```

Rows carry no fee, so the log is unaffected by the value; but this file's sha
and `PREREG.md`'s primary cell name it, so the verified value (and, if it is
not 60, a matching `config.FEE_BPS_PRIMARY` / `FEE_BPS_COLUMNS`) must be in
place before `PREREG.md` is sealed and before the sample's first row.

## 11. The outcome join (`loop/outcomes.py::join`)

For each row at t with a mid, `mid_h` is the mid of the FIRST row (by
`ts_rx`) that HAS a mid and whose `ts_rx ∈ [t + 900, t + 900 + 90]`
(`JOIN_SLACK_S = 90`: one cadence plus half, admitting the next tick when both
t and t+h slipped under the 50 s watchdog, never a 20-minute outage).
`ret_h_bps = 1e4 · ln(mid_h / mid_t)`; `label` is `up` if `ret_h_bps >=
DEAD_BAND_BPS = 5.0`, `down` if `<= −5.0`, `flat` between (exactly ±5 is a
move: config says |ret| BELOW the band is flat). Anything else — no row in the
window, no mid at t — is `{"absence": "gap"}`, never the nearest row. A
null-mid absence row landing in the window is skipped as a candidate, not
taken as a gap. Two rows with one `tick_id`: the priced one wins. Forward only:
t sees t+h, never the reverse.

## 12. The Jev call (`loop/jev.py`) — the only code that sees the key

- Body `{"model": "jev-1.13.0", "state": <state string>, "questions": <five>}`
  (this exact dict is what `--dry` prints); headers `Authorization: Bearer
  <key>`, `Content-Type: application/json`; `JEV_URL =
  https://api.typesafe.ai/v1/systemone`; timeout `JEV_TIMEOUT_S = 20`.
- **Ledger before send, failing closed.** One row per ATTEMPT is fsync'd to
  `data/sends.tsv` (`utc  source  state_chars  q_chars  sha12  paths`, source
  `jev-paper-loop`, `paths` always `-`, same columns as JEV's `DISCLOSURE.tsv`)
  before the request; an unwritable ledger means nothing is sent
  (`JevError("ledger")`). `sends.tsv` counts sends, not ticks.
- At most ONE retry, after `RETRY_S = 1.0` s on 5xx or a transport failure, or
  after `Retry-After` capped at `RETRY_AFTER_CAP_S = 5.0` s on 429 (20 + 5 + 20
  = 45 s fits the 50 s watchdog). Never on another 4xx: 401/403 raise and the
  tick writes `data/HALT` ("key rejected").
- Answer shape: choice → `{"choice", "probabilities", "confidence"}`; noul →
  `{"noul"}`. A missing field on any asked question is `parse` (a half answer
  must not become a wrong column). `input_tokens` from `usage.input_tokens`,
  `0` when absent. A `model` other than `MODEL` is returned and logged as drift.
- Spend: `USD_PER_MTOK = 0.042` on input tokens, output free. The
  ~1.8 KB body is ~$0.04/day at 1,440 ticks.

## 13. Guards and absences (`loop/cycle.py`, in order, every tick)

1. Path guard: the resolved repo path under either `FORBIDDEN_PREFIXES`
   (`~/Projects/crypto-trading-system`, its iCloud mirror) → exit 3, nothing
   written.
2. `data/HALT` exists → row `absence: "halt"`, exit 0. HALT stops SENDS only;
   the feed, arm C and the report keep running.
3. Today's spend (Σ `jev.input_tokens` over today's rows × `USD_PER_MTOK` /
   1e6) ≥ `DAILY_SPEND_HALT_USD = 0.25` → write `data/HALT`, exit 0.
4. `flock` on `data/loop.lock`, non-blocking; held → `absence: "lock"`.
5. Feed (§3) → `absence: "feed"` on `FeedError`; features/state (§4–6);
   prompts (§8); `--dry` writes the row with `mode: "dry"`, no ledger row, no
   send; else `jev.ask` → `absence: "jev"` with `jev.error` on `JevError`.
6. Columns (§9), atomic append (one `write`, `flush`, `fsync`), heartbeat
   `data/heartbeat` = `ts_rx`. 50 s `signal.alarm` watchdog per tick; SIGTERM
   finishes the write and releases the lock. Every exit is 0 except the path
   guard (3) and a usage error (2).

The nightly (`nightly/`) reads a digest of the log and scores candidate
wordings on the 81 synthetic states only, never on a logged outcome; it writes
`proposals/` and nothing else. The only thing it can change in a row, via a
person running `bin/promote`, is `prompt_b` / `prompt_b_sha` and what
`answers.b_action` is an answer to.

## 14. Every constant, in one place

| where | name | value |
|---|---|---|
| `config.py` | `VENUE` / `PRODUCT` | `coinbase` / `SOL-USD` |
| | `CADENCE_S` / `HORIZON_S` | 60 / 900 |
| | `MODEL` / `JEV_TIMEOUT_S` | `jev-1.13.0` / 20 |
| | `USD_PER_MTOK` / `DAILY_SPEND_HALT_USD` | 0.042 / 0.25 |
| | `NOTIONAL_USD` | 1000.0 |
| | `LIQ_THIN_USD` / `LIQ_DEEP_USD` | 1000.0 / 10000.0 |
| | `FLOW_P_LO` / `FLOW_P_HI` | 10 / 90 |
| | `TREND_Z` | 1.0 |
| | `VOL_RATIO_LO` / `VOL_RATIO_HI` | 0.5 / 2.0 |
| | `WINDOW_MIN` | 300 |
| | `DEAD_BAND_BPS` | 5.0 |
| | `FEE_BPS_PRIMARY` (UNVERIFIED, §10) | 60.0 |
| | `FEE_BPS_COLUMNS` | (60.0, 25.0, 10.0, 2.0) |
| | `CONF_THRESHOLDS` | (0.50, 0.70, 0.85, 0.99) |
| | `VETO_NOUL` / `PBUY` / `NOUL_TAIL` | 0.5 / 0.60 / 0.99 |
| `state.py` | `LIQ` / `FLOW` / `TREND` / `VOL` | thin normal deep / quiet organic bot_war / dumping flat pumping / calm normal violent |
| | `FLOW_BLOCK_MIN` / `RET_BLOCK_MIN` | 5 / 15 |
| `feed.py` | `CANDLES_REQ` / `TRADES_WINDOW_S` / `TRADES_LIMIT` / `TIMEOUT_S` | 350 / 300 / 1000 / 10 |
| `outcomes.py` | `JOIN_SLACK_S` | 90.0 |
| `jev.py` | `RETRY_S` / `RETRY_AFTER_CAP_S` | 1.0 / 5.0 |
| `rules.py` | `COLUMNS` | argmax c50 c70 c85 c99 c50v c70v c85v c99v pbuy60 noultail |

---

sha256 of this file is written into every row as spec_sha; changing this file starts a new experiment.

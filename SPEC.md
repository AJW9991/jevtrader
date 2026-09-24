# SPEC — what one row means, frozen

**Status: FROZEN 2026-09-23.** This file is the description a sceptic reads. It
says what the loop measures, exactly, with every threshold named by its
`loop/config.py` constant and value, so that no number in a row has to be
inferred from code. It is not the pre-registration (`PREREG.md` — the test,
the sample, the stop rules) and not the carve-out (`PROTOCOL.md` — why this
may run at all). Nothing here decides anything; the tick logs, the report
compares.

Checked 2026-09-23 against the leaf modules (`loop/feed.py`, `state.py`,
`rules.py`, `prompts.py`, `jev.py`, `book.py`, `outcomes.py`, `prompts/v1.json`)
and re-checked 2026-09-24 at integration against `loop/cycle.py` (the writer of
the row, including a real `--dry` row read field by field), `loop/report.py`,
`nightly/` and `bin/promote`, after `config.py` moved the primary fee to 120
bps (superseded the same day: H1 is at 0 bps gross; 120 bps is the venue's
descriptive cost column — see the dated lines below). Where this file and the code disagreed and the code followed
`CONTRACT.md`, this file was corrected. No row of the sample exists yet, so
the sha change is pre-registration, not a new experiment.

Two definitions changed on 2026-09-24, before any decision row existed, so
both are pre-registration changes (each dated where it lands):

- 2026-09-24, decided by Alex: `liq` is the cost of walking the book for one
  `NOTIONAL_USD` order (`fill1k_bps`, §4–§5), no longer the size of level 1;
  the feed asks for `BOOK_LEVELS = 100` levels (§3).
- 2026-09-24, decided by Alex: H1's cell is 0 bps, gross (`FEE_BPS_PRIMARY =
  0.0`); the venue's 120 bps taker is `FEE_BPS_VENUE`, a descriptive
  realistic-cost column (§10, PREREG §4).

One reading changed later the same day, after the first 181 live shakedown
rows and before T0 was set or any sample row existed; no field of the row and
no constant of the tick changed with it:

- 2026-09-24, decided by Alex: H2 moves to the direction probabilities.
  PREREG §5 reads lean = `up15.noul − down15.noul` against `ret_h_bps` (§8,
  §11), not arm A's choice confidence, which with `v1`'s criteria restating
  §6 measures rule-matching, not outcomes (CONTRACT §4.6–§4.7).

## 1. The loop in one paragraph

Every 60 s (`CADENCE_S = 60`) on this Mac, one tick reads the Coinbase Advanced
Trade PUBLIC market data for `SOL-USD` (`VENUE = "coinbase"`, `PRODUCT =
"SOL-USD"`; no key, no signature, three GETs), computes 15 features (14
numbers and one flag), turns them
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
  three GETs), ISO 8601 UTC with milliseconds and a `Z` (on a row that stopped
  before the feed, the tick's own start). `tick_id` is `ts_rx` floored to the
  minute. A fetch that straddles :00 therefore cannot move the
  tick (`feed.py::snapshot`).
- `mid = (bid + ask) / 2`. Prices are floats parsed from the venue's strings.
- `features` are the 15 values of §4 (14 numbers and the `fill1k_short`
  flag; `fill1k_bps` is `null` when a side is short), logged and never sent.
  The book's levels are not in the row: they feed the walk. `adj` is the four
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
  refused/reset/DNS: the kind set has no other transient slot), `parse`
  (which also covers a request `http.client` refused locally, its message
  withheld because it can quote the header), or one of two the tick writes
  itself: `watchdog` (the 50 s alarm fired inside the send) and `unexpected`
  (any other exception once the send had begun). All but `no-key` and
  `ledger` are billed by the spend guard (§13.3). A key value that is not
  printable ASCII without whitespace is refused as `no-key`, naming its path.
- `answers` is `null` in dry mode and on every absence but one: an answer the
  rules refuse (a `choice` outside `buy/sell/hold`) is logged as received with
  `absence: "jev"`, `jev.error: "parse"`. `columns` is `{"a": null, "b": null}`
  — each arm's value is `null` itself, not a dict of nulls (CONTRACT §3 step 5)
  — whenever the tick did not reach step 7 (dry, every absence, a refused
  answer); otherwise both are the full dict of §9. `rule_c` is present whenever
  the state was computed, absence or not, dry or live; `null` only when the
  tick stopped before the state was computed.
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
| `product_book?product_id=SOL-USD&limit=100` | up to `BOOK_LEVELS = 100` levels a side, kept in the Snapshot as `bids` / `asks` (`[[price, size], …]`, floats, best first: the feed sorts, bids down and asks up, and keeps the best 100); L1 `bid`, `bid_size`, `ask`, `ask_size` are level 1 of those; venue `book_time`. An empty side, a level that is not a finite positive price and size, or a crossed best (bid > ask) raises `FeedError`; locked (bid = ask) is kept. 2026-09-24, decided by Alex: `limit=100`, was `limit=1` (§4 walks the book) |
| `products/SOL-USD/candles?start=ts_rx-21000&end=ts_rx&granularity=ONE_MINUTE` | 350 rows requested (`CANDLES_REQ = 350`, the venue's cap); the open minute is dropped, so 349 CLOSED one-minute candles (`start + 60 <= ts_rx`), sorted oldest first, floats. Fewer than `WINDOW_MIN = 300` closed rows raises `FeedError` |
| `products/SOL-USD/ticker?limit=1000&start=ts_rx-300&end=ts_rx` | `trades_5m` = count of trades with `time >= ts_rx - 300` (`TRADES_WINDOW_S = 300`); `1000` means "≥ 1000" (the venue keeps the newest `TRADES_LIMIT = 1000`); a failed or unparseable ticker call yields `-1` and the tick goes on, because nothing in §5 reads it |

`feed_age_s = ts_rx − (newest closed candle start + 60)`: 0–60 s when the
venue is current. **Contiguity** (`feed.py::check_contiguous`): the last
`WINDOW_MIN` closed candles must be exactly 60 s apart. Coinbase OMITS a
minute with no trades rather than sending a zero-volume candle, and §4
indexes by position ("16 closes back" is 15 minutes only if no minute is
missing), so a missing or duplicated minute inside the window raises
`FeedError` — refused, never forward-filled. A gap in the 49 spare rows
before the window is never read and costs nothing; an omitted NEWEST minute is
not a gap (the window ends a minute earlier and `feed_age_s` reads 60–120).
**Staleness:** `feed_age_s > MAX_FEED_AGE_S = 120` raises `FeedError`: two or
more missing newest minutes, or a lagging venue, would leave a contiguous
window describing `[t−k−15, t−k]` while the mid and the fill are at t (the
fixture with its newest 8 closed candles removed read `feed_age_s` 529 and
flipped `vol` normal → violent, `rule_c` buy → sell). A
book or candles failure raises `FeedError` → row with `absence: "feed"`; so
does a window `state.py` refuses (`ValueError`, e.g. fewer than 300 rows,
or a book side with no levels to walk):
`cycle.py` logs both as `absence: "feed"`. The recorded fixture set (candles and trades 2026-09-24T02:28:49Z; the
100-level book re-recorded 2026-09-24T04:51:41Z, `fixtures/README.md`) pins
the parsers; live and fixture go through the same `assemble()`.

## 4. Features (`loop/state.py::features`) — logged, never sent

The window is the LAST `WINDOW_MIN = 300` closed candles of the 349 the feed
returns; index −1 is the newest closed minute, which is "now". `close` is the
only price the venue closes the minute on and is the price used throughout.

| key | definition |
|---|---|
| `mid` | `(bid + ask) / 2` |
| `spread_bps` | `1e4 · (ask − bid) / mid` |
| `l1_min_usd` | `min(bid · bid_size, ask · ask_size)` — the smaller side of the top of book, in USD. Logged because it is informative; since 2026-09-24 it sets no word |
| `fill1k_bps` | the cost of one `NOTIONAL_USD = 1000.0` market order walked through the book, `max(buy, sell)`: buy = `1e4 · (VWAP_ask − mid) / mid`, sell = `1e4 · (mid − VWAP_bid) / mid`, where VWAP is `NOTIONAL_USD / base` for `NOTIONAL_USD` of QUOTE taken level by level best first (whole levels give their `size`; the level that finishes the order gives `remaining_usd / price`; `state.py::fill_cost_bps`). Both sides are ≥ 0 on an uncrossed book; with the order filled at level 1 it is the half-spread (~0.44 bps at a 1c tick on ~$115). A side whose `BOOK_LEVELS` levels hold less than `NOTIONAL_USD` costs `inf`, logged as `null`. 2026-09-24, decided by Alex |
| `fill1k_short` | `true` iff a side could not fill `NOTIONAL_USD` (then `fill1k_bps` is `null` and `liq` is `thin`); else `false` |
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
| `liq` | `fill1k_bps` (reversed: a LOW cost is deep) | `deep` | `< LIQ_DEEP_BPS = 1.0` | `normal` | `> LIQ_THIN_BPS = 5.0`, or `fill1k_short` | `thin` |
| `flow` | `vol5_usd` | `quiet` | `< vol5_p10` (`FLOW_P_LO = 10`) | `organic` | `> vol5_p90` (`FLOW_P_HI = 90`) | `bot_war` |
| `trend` | `ret15_z` | `dumping` | `< −TREND_Z = −1.0` | `flat` | `> +TREND_Z = +1.0` | `pumping` |
| `vol` | `rv_ratio` | `calm` | `< VOL_RATIO_LO = 0.5` | `normal` | `> VOL_RATIO_HI = 2.0` | `violent` |

`liq`, 2026-09-24, decided by Alex: it was `l1_min_usd` `< LIQ_THIN_USD =
1000.0` → thin, `> LIQ_DEEP_USD = 10000.0` → deep. Twelve `product_book`
samples over 60 s (limit 100) showed level 1's smaller side swinging from $1
to $11,580 and reading thin 7/12, while a $1,000 order's VWAP-vs-mid cost was
0.44–2.02 bps (median 0.87) on both sides and ask depth within 5 bps was
$91k–$191k: the old word was a coin flip that randomly blocked arm C's buys.
The new cuts make `deep` and `normal` both common and `thin` a real
dislocation; the report's > 95 % occupancy flag (§4.2 of CONTRACT) is the
check. Both old constants are removed from `config.py`.

The words live in `loop/state.py` (`LIQ`, `FLOW`, `TREND`, `VOL`, `DIMS`,
`ALPHABET`); the cuts in `loop/config.py`. The order of `LIQ` (`thin`,
`normal`, `deep`) is unchanged, so `all_states()` and every policy table keep
their order; `adjectives` applies the liq cuts to the words reversed.
`bot_war` keeps its underscore: one token, no digit, the same spelling as in
`prompts/v1.json`.

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

Unchanged in form on 2026-09-24; what `liq != thin` means moved with §5: both
sides of the book fill `NOTIONAL_USD` within its 100 levels and the dearer
side costs at most `LIQ_THIN_BPS = 5.0` bps.
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

`up15` and `down15` are therefore the only questions in the request that ask
Jev about the price rather than about the rule. 2026-09-24, decided by Alex:
they are H2's predictor (PREREG §5). `make report` §6 (CONTRACT §4.6) prints
lean = `up15.noul − down15.noul` (in [−1, 1], rounded to 12 decimals so equal
decimal leans compare equal) against §11's `ret_h_bps`: Pearson r on the first
live row of each 900 s block, Spearman ρ, r and ρ on every tick, the Brier
score of `up15` vs `label = up` and of `down15` vs `label = down` beside the
base-rate Brier, the counts in the measured tails (≥ `NOUL_TAIL` = 0.99,
< 0.15), and the `trend` word (§5) beside it as a no-model comparator: the
model sees only the four words, and on the first run lean tracked `trend` at
r 0.99 (PREREG §5), so a supported H2 is about that word as Jev maps it.
Arm A's choice confidence is printed beside `a.argmax == rule_c`
and against the label in report §7, descriptive only.

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
    differs from "fee on notional" by ~0.006 bps at the 120 bps venue fee);
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
  `forced_hold`. A row with `absence` set (including `halt`, §13), a row
  whose `mode` is not `live`, `null` columns, or an unpriced book is a forced
  `hold` for EVERY arm, C included (neither an outage, a HALT nor a `--dry`
  run ever manufactures a disagreement: a dry row carries `rule_c` but no
  model columns, so letting C act on it would give C a trade A and B could
  never make); the position is carried and marked to the row's mid when it
  has one, so the move lands on the tick it happened on, and across an
  unpriced gap on the first priced tick after it. Two rows with one `tick_id`
  fold (`+=`). The `outcomes`
  argument is accepted and unused: a mark-to-mid book needs no t+h join, and
  using one would let t see t+h.
- `paired(rows, outcomes, x, y, column, fee_bps) → [(tick_id, d_t)]`,
  `d_t = pnl_x − pnl_y`; exactly `0.0` on any tick both arms carry the same
  position (the same `qty`) into and out of, which includes every tick both are
  flat. Two arms long on entries opened at DIFFERENT ticks hold different
  quantities (`NOTIONAL / ask` at each arm's own entry), so a tick both carry
  long gives `d_t = (q_x − q_y) · (mid_t − mid_prev)`: entry-price noise, a
  small fraction of a bp at ordinary price differences, and NOT a
  disagreement. A disagreement tick (the report, PREREG §4) is a tick where
  the two arms are on different SIDES, long vs flat, into or out of it.

**Fees.** `FEE_BPS_COLUMNS = (0.0, 2.0, 10.0, 25.0, 60.0, 120.0)`, ascending:
the same decisions replayed at six constants — **0 = gross, the H1 cell**
(the PRIMARY), 2 = Binance.US, 10 = the article's, 25, 60 = the venue's retail
maker, 120 = the venue's retail taker. A fee never changes a decision, only
the pnl of the fills.

2026-09-24, decided by Alex: the PRIMARY is `FEE_BPS_PRIMARY = 0.0`, gross
(it was 120.0, the venue taker; before that a 60 bps placeholder). Why: a
round trip at the venue's taker costs 2 × 120 = **240 bps** against a
15-minute return sd of ~26–33 bps (`ret15_sd_bps`: 28.9 in the fixture window,
26.6 in the first `--dry` row), so profitability at retail fees is settled by
arithmetic, and a NET primary would mostly rank which arm trades least. At 0
bps, gross of fees, a difference between the arms is direction net of the
spread, which is the question PREREG §4 asks. Turnover still costs one
spread per round trip (open at the ask, close at the bid, marked to mid:
0.87 bps at a 1c spread and 1.74 bps at 2c on ~$115, the same order as
PREREG §7's 1.78 bps per-block MDE), so trades/day is read beside the cell.
(Wording corrected 2026-09-24 in review, before sealing; it said "a
difference in DIRECTION … and not in turnover". The statistic is
unchanged.) Every net-of-fee column (2, 10, 25, 60, 120 bps) is
DESCRIPTIVE: printed, never tested.

The venue's own cost is `FEE_BPS_VENUE = 120.0`, the realistic-cost column,
and it is **UNVERIFIED**: `FEE_BPS_VENUE_SOURCE = "UNVERIFIED — Coinbase
Advanced Intro 1 taker per secondary sources (April 2026); confirm at
https://www.coinbase.com/advanced-fees signed in"` (moved from the old
`FEE_BPS_PRIMARY_SOURCE`, which is gone). Two third-party fee tables dated
April 2026 put the retail Coinbase Advanced tier "Intro 1" (< $1K 30-day
volume) at 0.60 % MAKER / **1.20 % TAKER**; the official retail page is behind
sign-in and must be read in-account. The report labels the primary cell from
`config.FEE_BPS_PRIMARY`, prints `FEE_BPS_VENUE` and `FEE_BPS_VENUE_SOURCE`
beside the table with a per-arm line at that fee, and tags its columns
`[venue fee]`; the nightly digest shows each arm's pnl at both, labelled;
nothing hard-codes a fee.

```
Verified tier-0 taker fee: ________ bps   URL: ______________________________   read (UTC): ____________
```

Rows carry no fee, so the log is unaffected by the value. The venue fee no
longer decides any test, so it does not block sealing `PREREG.md` on its own;
but `FEE_BPS_COLUMNS` is named here (this file's sha is in every row) and in
PREREG §6, so a verified value other than 120 changes `FEE_BPS_VENUE` and its
column before the sample's first row.

## 11. The outcome join (`loop/outcomes.py::join`)

For each row at t with a mid, `mid_h` is the mid of the row that HAS a mid
and whose `ts_rx` is NEAREST `t + 900`, within `[t + 900 − 30, t + 900 + 30]`
(`JOIN_TOL_S = CADENCE_S / 2 = 30.0`; both edges inclusive; a tie goes to the
earlier row). `ts_rx` is the feed-entry clock, the minute boundary plus timing
noise (sleep overshoot and the guards under `--forever`, the StartInterval
phase under launchd); rows 60 s apart always leave exactly one within 30 s of
any instant, so the realised horizon is 900 ± 30 s whatever the phase, and a
missing t+15 row is a gap because its neighbours are 60 s away. (The first
form, "the FIRST row in `[t + 900, t + 990]`", picked the t+16 row whenever the
t+15 row's noise was smaller than t's: a 15- or 16-minute label on a coin flip.
Replaced before any sample row.)
`ret_h_bps = 1e4 · ln(mid_h / mid_t)`; `label` is `up` if `ret_h_bps >=
DEAD_BAND_BPS = 5.0`, `down` if `<= −5.0`, `flat` between (exactly ±5 is a
move: config says |ret| BELOW the band is flat). Anything else — no row in the
window, no mid at t — is `{"absence": "gap"}`, never a row outside it. A
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
  ~1.8 KB body is ~$0.04/day at 1,440 ticks. Because a reply without `usage`
  logs `0` and a failed send logs `null`, the spend guard (§13) charges such a
  send `JEV_TOKENS_IF_UNKNOWN = 2000` tokens rather than nothing.

## 13. Guards and absences (`loop/cycle.py`, in order, every tick)

1. Path guard: the resolved repo path under either `FORBIDDEN_PREFIXES`
   (`~/Projects/crypto-trading-system`, its iCloud mirror) → exit 3, nothing
   written.
2. `data/HALT` exists → the tick is HALTED: it takes the lock and runs the
   feed, the state, `rule_c` and the prompts as usual (§3–§8), then writes the
   row with `absence: "halt"` where the send would begin: no ledger row, no
   request, no body printed (dry or live). HALT stops SENDS only; the feed,
   arm C's `rule_c`, the outcome join and the report keep running, so the 15
   minutes before a HALT keep their t+h outcomes and the day's outcome fill
   (PREREG §8.3) is not spent by it. A feed or prompts failure under HALT
   keeps its own absence (`absence` names the first step that did not
   happen). In the book a halt row is a forced hold for EVERY arm, like any
   absence (§10): `rule_c` is logged but not traded, so a HALT never
   manufactures a B−C or A−C disagreement; its mid carries the marks.
3. Today's spend (Σ billed tokens over today's rows, by `tick_id` UTC date,
   × `USD_PER_MTOK` / 1e6) ≥ `DAILY_SPEND_HALT_USD = 0.25` → write `data/HALT`
   with the reason; the tick is then HALTED exactly as in 2. Billed tokens
   (`cycle.py::billed_tokens`): the logged `jev.input_tokens` when positive;
   else `JEV_TOKENS_IF_UNKNOWN = 2000` for a live row that reached the model
   (`absence` null, or `"jev"` with any kind but `no-key`/`ledger`, which are
   raised before a request leaves); else 0 (dry rows, halt/lock/feed/guard).
   At 2000 per unknown send the guard trips at ~2,976 such sends in a day, 2×
   the cadence: a runaway, never a normal day.
4. `flock` on `data/loop.lock`, non-blocking; held → `absence: "lock"`.
5. Feed (§3) → `absence: "feed"` on `FeedError` or a window `state.py`
   refuses; features/state (§4–6); prompts (§8; a prompt that does not load is
   `absence: "guard"`); `--dry` writes the row with `mode: "dry"`, `answers`
   and both columns `null`, no ledger row, no send, and prints the exact body
   to stdout; else `jev.ask` → `absence: "jev"` with `jev.error` on `JevError`
   (401/403 also write `data/HALT`, "key rejected"). Every path after the path
   guard writes exactly one row with string `tick_id` and `ts_rx`, including
   the lock row written before the feed. A post-send exception that is not a
   `JevError` is `absence: "jev"`, `jev.error: "unexpected"` (§2), billed.
6. Columns (§9), atomic append (one `write`, `flush`, `fsync`), heartbeat
   `data/heartbeat` = `ts_rx`. 50 s `signal.alarm` watchdog per tick; SIGTERM
   finishes the write and releases the lock. Every exit is 0 except the path
   guard (3) and a usage error (2).

The nightly (`nightly/`) reads a digest of the log and scores candidate
wordings on the 81 synthetic states only, never on a logged outcome; it writes
`proposals/`, its ledger rows, and `data/HALT` on a rejected key (the caller
writes HALT, as in §12), and nothing else. It sends nothing while `data/HALT`
exists, and a 429 or `MAX_TRANSIENT_RUN = 3` transient failures in a row end
its night. The only thing it can change in a row, via a
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
| | `BOOK_LEVELS` (2026-09-24) | 100 |
| | `LIQ_THIN_BPS` / `LIQ_DEEP_BPS` (2026-09-24; replaced `LIQ_THIN_USD` / `LIQ_DEEP_USD` = 1000.0 / 10000.0) | 5.0 / 1.0 |
| | `FLOW_P_LO` / `FLOW_P_HI` | 10 / 90 |
| | `TREND_Z` | 1.0 |
| | `VOL_RATIO_LO` / `VOL_RATIO_HI` | 0.5 / 2.0 |
| | `WINDOW_MIN` | 300 |
| | `DEAD_BAND_BPS` | 5.0 |
| | `JEV_TOKENS_IF_UNKNOWN` | 2000 |
| | `FEE_BPS_PRIMARY` (the H1 cell, gross; 2026-09-24, was 120.0) | 0.0 |
| | `FEE_BPS_VENUE` (UNVERIFIED, §10; `FEE_BPS_VENUE_SOURCE`) | 120.0 |
| | `FEE_BPS_COLUMNS` (ascending since 2026-09-24) | (0.0, 2.0, 10.0, 25.0, 60.0, 120.0) |
| | `CONF_THRESHOLDS` | (0.50, 0.70, 0.85, 0.99) |
| | `VETO_NOUL` / `PBUY` / `NOUL_TAIL` | 0.5 / 0.60 / 0.99 |
| `state.py` | `LIQ` / `FLOW` / `TREND` / `VOL` | thin normal deep / quiet organic bot_war / dumping flat pumping / calm normal violent |
| | `FLOW_BLOCK_MIN` / `RET_BLOCK_MIN` | 5 / 15 |
| `feed.py` | `CANDLES_REQ` / `TRADES_WINDOW_S` / `TRADES_LIMIT` / `TIMEOUT_S` / `MAX_FEED_AGE_S` | 350 / 300 / 1000 / 10 / 120 |
| `outcomes.py` | `JOIN_TOL_S` | 30.0 (`CADENCE_S / 2`, either side of t+h) |
| `jev.py` | `RETRY_S` / `RETRY_AFTER_CAP_S` | 1.0 / 5.0 |
| `rules.py` | `COLUMNS` | argmax c50 c70 c85 c99 c50v c70v c85v c99v pbuy60 noultail |
| `cycle.py` | `WATCHDOG_S` / `TAIL_BYTES` | 50 / 8 MiB (the spend guard reads the log's tail) |
| `report.py` | `PRIMARY` cell / `VENUE_FEE` / `BLOCK_S` / `SAMPLE_DAYS` | (B, C, `argmax`, `FEE_BPS_PRIMARY` = 0) / `FEE_BPS_VENUE` / 900 (`HORIZON_S`, blocks from T0, `--t0`) / 28 |
| `report.py` (H2, 2026-09-24) | `NOUL_HIGH` / `NOUL_LOW` / `LEAN_DP` | `NOUL_TAIL` = 0.99 / 0.15 (the measured tails, counted, never acted on) / 12 (lean's rounding) |
| `nightly/digest.py` | `FEES` | (`FEE_BPS_PRIMARY`, "direction"), (`FEE_BPS_VENUE`, "venue fee") |
| `nightly/digest.py` | `DISAGREE_CONF` / `DISAGREE_MAX` | 0.85 / 25 |
| `nightly/policy_table.py` | `DEADLINE_S` / `MAX_CANDIDATES` / `MAX_TRANSIENT_RUN` | 900.0 / 3 / 3 |

---

sha256 of this file is written into every row as spec_sha; changing this file starts a new experiment.

# SPEC — what one row means, frozen (v2)

**Status: SPEC v2, frozen by the `prereg-v2-draft` tag.** **Every v2 row carries this file's
sha256 as its `spec_sha`**: every row any product's loop writes once the build is merged
(PREREG-v2 §10, switch step (6)), so the set of `spec_sha` over v2's sample holds exactly this
one value (PREREG-v2 §13). Changing a byte of this file after the draft tag starts a new
experiment. v1's rows carry v1's SPEC sha, `5d4f355e1817…` (`git show prereg-v1:SPEC.md`;
`dash.V1_SPEC_SHA`), and mean what that text says; nothing here changes what a v1 row means. v1's
committed result and its descriptive cells are reproduced from the tag `results-v1` (PREREG-v2
§10), not from this tree: `loop.report` here prints §10's fee columns (0, 2, 10, 25, 50, 90) and
the verified venue fee 90 over the v1 log too, where v1's reader printed (0, 2, 10, 25, 60, 120)
and 120 (rows carry no fee, so no row's meaning moves).

This file is the description a sceptic reads. It says what the loop measures, exactly, with
every threshold named by its `loop/config.py` constant and value, so that no number in a row has
to be inferred from code. It is not the pre-registration (`PREREG-v2.md`: the test, the sample,
the stop rules; `PREREG.md` for v1) and not the carve-out (`PROTOCOL.md`: why this may run at
all). Nothing here decides anything; the tick logs, the report compares.

**Named here, restated nowhere here:** T_first_v2 and T0_v2, and the venue's fee-tier table,
are PREREG-v2 §12's fields, filled at sealing. Every reader takes them from PREREG-v2.md §12
(`dash.read_t0_v2`, `dash.read_fee_tiers`); this file gives neither value.

**What v2 changed from SPEC v1** (v1: frozen 2026-09-23, re-checked 2026-09-24 at integration;
PREREG-v2 §10's SPEC bullet; written 2026-09-29, before any v2 row existed):

- §1–§2: one loop per product in `config.PRODUCTS`; the row's `product` is its loop's
  (`JEVLOOP_PRODUCT`); the row gains `table_sha` and `columns.d`; `prompt_a` is
  `config.FROZEN_A = "v2"` (was the literal `v1`); `prompt_b` is the version
  `prompts.current(tick_id)` names for the row's own tick.
- §5: `liq` is read in h, the fill cost in half-ticks, with a per-product `TICK_P` and atoms;
  v1's bps cuts are retired. The state string's first word is the product's base.
- §6: `rule_c` and its 81-state truth table are unchanged; which live ticks read `thin` moves
  with §5.
- §7: four arms; A asks the frozen `v2` wording; D is the CURRENT wording's own 81-state table,
  looked up, no call.
- §10: arm D in the book; `book.at_cadence`; the fee columns (0, 2, 10, 25, 50, 90);
  `FEE_BPS_VENUE = 90.0`, verified, and the verified tier-0 taker row filled.
- §13: `data/PAUSE.<PRODUCT>` in step 2; the spend guard sums every product's log, at $0.25 a
  product.
- §14: every new constant.
- ERRATA.md's SPEC rows that describe what the code already did are folded into §2, §3 and
  §9–§13, each marked "(folded from ERRATA.md)"; ERRATA.md keeps the rows, marked as folded.

The dated decisions of v1 (2026-09-24: `liq` as the cost of walking the book for $1,000;
`BOOK_LEVELS = 100`; H1 gross of fees; H2 on the direction probabilities) keep their lines below
where they still describe a definition.

## 1. The loop in one paragraph

Every 60 s (`CADENCE_S = 60`) on this Mac, one tick PER PRODUCT (`config.PRODUCTS`: `SOL-USD`,
the v1 stream unbroken, and PREREG-v2 §2's two probe products; one loop process each, named by
`JEVLOOP_PRODUCT`, unset meaning `SOL-USD`, or one process ticking them in sequence,
`--every-product`) reads the Coinbase Advanced Trade PUBLIC market data for its product
(`VENUE = "coinbase"`; no key, no signature, three GETs), computes 15 features (14 numbers and
one flag), turns them into four words from a closed alphabet, sends the ~10-word state string,
whose first word is the product's base, once to `jev-1.13.0` (`MODEL`) with five typed
questions, looks the same state up in the CURRENT wording's 81-state table (arm D; no call), and
appends one JSON row to the product's own decision log. The model never sees a number, a
position, or an outcome. Every action rule is a column derived afterwards from one logged
answer; the paper book is replayed from the log at report time, per product, every minute and
decision-held once per 15, 60 and 240 minutes (PREREG-v2 §4); the outcome of a decision at t is
the log's own mid at t + 900 s (`HORIZON_S = 900`). Paper only, forward only, nothing
back-filled.

## 2. The row — one line of the product's decision log per tick, append-only

Where (`config.store(product)`): `data/decisions.jsonl` for `SOL-USD` (v1's path, unbroken) and
`data/<PRODUCT>/decisions.jsonl` for every other product, each beside its own `sends.tsv`,
`loop.lock` and `heartbeat`. `data/HALT`, `data/PAUSE.<PRODUCT>`, `data/exclusions-v2.tsv` and
`data/looks.tsv` sit in `data/` whatever the product.

```
{ "v": 1, "tick_id": "YYYYMMDDTHHMM00Z", "ts_rx": ISO ms, "mode": "live"|"dry",
  "venue": "coinbase", "product": <a product in config.PRODUCTS>, "cadence_s": 60, "horizon_s": 900,
  "bid","bid_size","ask","ask_size","mid": float, "book_time": str|null, "feed_age_s": float,
  "features": {...}, "adj": {...}, "state": str, "spec_sha": str,
  "prompt_a": "v2", "prompt_a_sha": str, "prompt_b": "vN", "prompt_b_sha": str, "table_sha": str|null,
  "model_requested": str, "model_answered": str|null, "drift": bool,
  "jev": {"latency_ms": int|null, "input_tokens": int|null, "error": str|null, "key_path": str|null},
  "answers": null | {"a_action":{...},"b_action":{...},"skip":{...},"up15":{...},"down15":{...}},
  "rule_c": "buy"|"sell"|"hold",
  "columns": {"a": {...}|null, "b": {...}|null, "d": "buy"|"sell"|"hold"|null},
  "absence": null | "feed"|"jev"|"halt"|"lock"|"guard" }
```

- `v` stays 1: the shape grew by two keys (`table_sha`, `columns.d`) and lost none; which
  definitions a row was made under is its `spec_sha`.
- `product` is the loop's product: `JEVLOOP_PRODUCT` (`config.loop_product`), `SOL-USD` when it
  is unset; always `SOL-USD` in v1. A value not in `config.PRODUCTS` exits 2 before any
  directory is made, so no row carries one.
- `ts_rx` is this machine's clock at the ENTRY of the feed call (before the three GETs), ISO 8601
  UTC with milliseconds and a `Z` (on a row that stopped before the feed, the tick's own start).
  `tick_id` is `ts_rx` floored to the minute. A fetch that straddles :00 therefore cannot move the
  tick (`feed.py::snapshot`).
- `mid = (bid + ask) / 2`. Prices are floats parsed from the venue's strings.
- `features` are the 15 values of §4 (14 numbers and the `fill1k_short` flag; `fill1k_bps` is
  `null` when a side is short), logged and never sent. The book's levels are not in the row:
  they feed the walk. `adj` is the four words of §5, cut for the row's product. `state` is the
  one string the model sees (§5).
- `spec_sha` is the SHA-256 of this file's bytes, or `unsealed` when the file cannot be read
  (absent, or any `OSError`: `cycle.spec_sha`). SPEC.md is always readable on the Mac (folded
  from ERRATA.md).
- `prompt_a_sha` / `prompt_b_sha` are SHA-256 of the canonical JSON (`sort_keys`, no whitespace)
  of the whole prompt file, so a re-indent leaves the sha alone and a changed character does not
  (`prompts.py::canon`). `prompt_a` is `config.FROZEN_A` = `v2` on every row (PREREG-v2 §1; its
  canonical sha is `b3291ca4a550…`); `prompt_b` is the version `prompts.current(tick_id)` names
  for this row's own tick: the one name in `prompts/CURRENT`, or, while that version's
  `activation_tick` is later than the tick, the version it `replaces` (§8; PREREG-v2 §8), so
  every row of a product-day carries one `prompt_b`.
- `table_sha` is the canonical sha (`prompts.canon`, as above) of
  `prompts/<prompt_b>.table.<product>.json`, the `prompt_b` wording's 81-state table for the
  row's product (§7, arm D), set whenever the tick read it (dry and halt rows included); `null`
  when that file is absent or refused (`prompts.table`: another version or product, a
  `prompt_sha` that is not the version file's own, not exactly the product's 81 state strings,
  an answer other than `buy`/`sell`/`hold`). A refusal is said on stderr and costs D alone.
- `model_requested` is `MODEL`; `model_answered` is what the server reported, `null` when it
  reported none; `drift` is `model_answered != model_requested`.
- `jev.key_path` NAMES the key that answered (`env:TYPESAFE_API_KEY_LOOP`,
  `file:~/.secondbrain-secrets/typesafe-api-key-loop`, `env:TYPESAFE_API_KEY`,
  `file:~/.secondbrain-secrets/typesafe-api-key`; first hit wins). No value is ever logged.
  `jev.error` is a `JevError` kind: `unsigned` (PROTOCOL.md's signature line is unfilled: refused
  before the send, never billed; folded from ERRATA.md), `no-key`, `ledger`, `http-4xx`,
  `http-429`, `http-5xx`, `timeout` (which also covers connection refused/reset/DNS: the kind set
  has no other transient slot), `parse` (which also covers a request `http.client` refused
  locally, its message withheld because it can quote the header), or one of two the tick writes
  itself: `watchdog` (the 50 s alarm fired inside the send, or while its answer became columns:
  that row has `input_tokens > 0` and no answers; folded from ERRATA.md) and `unexpected` (any
  other exception once the send had begun). All but `unsigned`, `no-key` and `ledger` are billed
  by the spend guard (§13.3). A key value that is not printable ASCII without whitespace is
  refused as `no-key`, naming its path.
- `answers` is `null` in dry mode and on every absence but two: an answer the rules refuse (a
  `choice` outside `buy/sell/hold`, or a field that is a bool, NaN, infinite or of the wrong type)
  is logged as received with `absence: "jev"`, `jev.error: "parse"`; and an `unexpected`
  exception at the columns stage keeps the answer with `absence: "jev"`, `jev.error:
  "unexpected"` (folded from ERRATA.md). `columns` is `{"a": null, "b": null, "d": null}` —
  each arm's value is `null` itself, not a dict of nulls (CONTRACT §3 step 5) — whenever the tick
  did not reach step 7 (dry, every absence, a refused answer); otherwise `a` and `b` are the full
  dicts of §9 and `d` is the table's answer for `state` (§7), `null` when the tick has no table
  or the table lacks the state. `rule_c` is present whenever the state was computed, absence or
  not, dry or live; `null` only when the tick stopped before the state was computed.
- A tick that fails before the feed still writes a row: `absence` set, `tick_id` and `ts_rx`
  always strings (`outcomes.load` drops a line without them), everything it could not fill
  `null`.
- Two rows can share one `tick_id` (a launchd double-fire; the second is `absence: "lock"`).
  Readers fold, never overwrite (§10, §11).

## 3. The feed (`loop/feed.py`)

Three unauthenticated GETs against `https://api.coinbase.com/api/v3/brokerage/market` per tick
per product (`<P>` below is the row's product), 10 s timeout each, no retry, no sleep: 0.05 req/s
a product, 0.15 req/s for three, against the venue's documented 10 req/s per IP. Each loop fires
at :00; the one-process mode (§13) ticks the products one after another inside the minute:

| call | what is kept |
|---|---|
| `product_book?product_id=<P>&limit=100` | up to `BOOK_LEVELS = 100` levels a side, kept in the Snapshot as `bids` / `asks` (`[[price, size], …]`, floats, best first: the feed sorts, bids down and asks up, and keeps the best 100); L1 `bid`, `bid_size`, `ask`, `ask_size` are level 1 of those; venue `book_time`. A book naming another product, an empty side, a level that is not a finite positive price and size, or a crossed best (bid > ask) raises `FeedError`; locked (bid = ask) is kept. 2026-09-24, decided by Alex: `limit=100`, was `limit=1` (§4 walks the book) |
| `products/<P>/candles?start=ts_rx-21000&end=ts_rx&granularity=ONE_MINUTE` | 350 rows requested (`CANDLES_REQ = 350`, the venue's cap); the open minute is dropped, so 349 CLOSED one-minute candles (`start + 60 <= ts_rx`), sorted oldest first, floats. Fewer than `WINDOW_MIN = 300` closed rows raises `FeedError` |
| `products/<P>/ticker?limit=1000&start=ts_rx-300&end=ts_rx` | `trades_5m` = count of trades with `time >= ts_rx - 300` (`TRADES_WINDOW_S = 300`); `1000` means "≥ 1000" (the venue keeps the newest `TRADES_LIMIT = 1000`); a failed or unparseable ticker call yields `-1` and the tick goes on, because nothing in §5 reads it |

`feed_age_s = ts_rx − (newest closed candle start + 60)`: 0–60 s when the venue is current.
**Contiguity** (`feed.py::check_contiguous`): the last `WINDOW_MIN` closed candles must be
exactly 60 s apart. Coinbase OMITS a minute with no trades rather than sending a zero-volume
candle, and §4 indexes by position ("16 closes back" is 15 minutes only if no minute is missing),
so a missing or duplicated minute inside the window raises `FeedError` — refused, never
forward-filled. A gap in the 49 spare rows before the window is never read and costs nothing; an
omitted NEWEST minute is not a gap (the window ends a minute earlier and `feed_age_s` reads
60–120). **Staleness:** `feed_age_s > MAX_FEED_AGE_S = 120` raises `FeedError` (exactly
120.000 s is accepted, a `ts_rx` on a minute boundary that live ticks do not reach; folded from
ERRATA.md): two or more missing newest minutes, or a lagging venue, would leave a contiguous
window describing `[t−k−15, t−k]` while the mid and the fill are at t (the fixture with its
newest 8 closed candles removed read `feed_age_s` 529 and flipped `vol` normal → violent,
`rule_c` buy → sell). **Finiteness** (folded from ERRATA.md): the book's rule holds for the
window's candles too — an open, high, low or close that is not finite and positive, or a volume
that is not finite and non-negative, refuses the set, and so does a candle start below 0 or at
2^40 and past (`START_MAX`), or a body nested past the JSON parser's depth. A book or candles
failure raises `FeedError` → row with `absence: "feed"`; so does a window `state.py` refuses
(`ValueError`, e.g. fewer than 300 rows, or a book side with no levels to walk): `cycle.py` logs
both as `absence: "feed"`. The recorded fixture set (`SOL-USD`; candles and trades
2026-09-24T02:28:49Z; the 100-level book re-recorded 2026-09-24T04:51:41Z, `fixtures/README.md`)
pins the parsers; live and fixture go through the same `assemble()`, for every product.

## 4. Features (`loop/state.py::features`) — logged, never sent

The window is the LAST `WINDOW_MIN = 300` closed candles of the 349 the feed returns; index −1 is
the newest closed minute, which is "now". `close` is the only price the venue closes the minute
on and is the price used throughout. The features are the same for every product; no feature
depends on the product's tick.

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

A window with no scale (300 equal closes, a stuck feed) reads `z = 0.0`, `rv_ratio = 1.0`: the
neutral words, so arm C holds. h (§5) is not a feature: it is a function of two logged features
and a constant of the product, so the row does not carry it and any reader can recompute it.

## 5. The alphabet — the only words the model ever sees

Cuts are STRICT (`<`, `>`) exactly as `CONTRACT.md` §2 writes them: a value ON a cut is not
evidence of either extreme and takes the middle word.

| dim | feature | low word | low cut | middle word | high cut | high word |
|---|---|---|---|---|---|---|
| `liq` | h, `fill1k_bps` in half-ticks of the product (reversed: a LOW cost is deep) | `deep` | `< a10 + 0.5` | `normal` | `> a90 + 0.5` (`a90 − 0.5` under the window's thin fallback), or `fill1k_short` | `thin` |
| `flow` | `vol5_usd` | `quiet` | `< vol5_p10` (`FLOW_P_LO = 10`) | `organic` | `> vol5_p90` (`FLOW_P_HI = 90`) | `bot_war` |
| `trend` | `ret15_z` | `dumping` | `< −TREND_Z = −1.0` | `flat` | `> +TREND_Z = +1.0` | `pumping` |
| `vol` | `rv_ratio` | `calm` | `< VOL_RATIO_LO = 0.5` | `normal` | `> VOL_RATIO_HI = 2.0` | `violent` |

**`liq` in a price-free unit (PREREG-v2 §3).** `flow`, `trend` and `vol` are relative to their
own window already and occupied every word on v1's health look; `liq` was absolute and dead
(`thin` on 0 of 3,467 v1 rows with adjectives, PREREG-v2 §0.2). At a level-1 fill `fill1k_bps`
is the half-spread, 50 · k / P bps for a spread of k ticks at price P on a 1c tick, so a cut in
bps moved with the price. v2 counts spread ticks:

- **h = `fill1k_bps` · `mid` / (1e4 · `TICK_P[p]` / 2)** (`state.py::half_ticks`): the fill cost
  in half-tick units of the row's product p; at a level-1 fill, the spread in ticks.
- **`deep` ⇔ h < a10 + 0.5; `thin` ⇔ h > a90 + 0.5**, where a10 and a90 (`LIQ_ATOMS[p]`) are the
  integer atoms nearest the nearest-rank p10 and p90 of h over the product's window; where `thin`
  then held < 3 % of the window's rows, once, `thin` ⇔ h > a90 − 0.5 (`LIQ_THIN_FALLBACK[p]`;
  `config.liq_cuts`). `fill1k_short` (or no reading) stays `thin`. `normal` otherwise; where the
  cuts overlap, `deep` is read first (`state.py::liq`).
- Per product (every word held ≥ 3 % and ≤ 90 % of its window's rows, PREREG-v2 §2 (3), §3):

| product | `TICK_P` (USD) | `LIQ_ATOMS` (a10, a90) | `LIQ_THIN_FALLBACK` | `deep` ⇔ | `thin` ⇔ | window |
|---|---|---|---|---|---|---|
| `SOL-USD` | 0.01 | (1, 4) | no | h < 1.5 (a one-tick spread) | h > 4.5 (wider than four ticks), or short | v1's live rows in [2026-09-25T21:40Z, 2026-09-29T04:30Z), `bin/fill1k-quantiles`: deep 16.53 %, normal 77.12 %, thin 6.35 % of 3,877 |

  PREREG-v2 §2's two probe products get their rows here in the commit that adds them to
  `config.PRODUCTS` (STEPS §10.1), from `bin/probe summarize probe/<D>` over D's ok rows (the
  quantiles tool's own rule, imported), before the draft tag; `tests/test_spec.py` holds this
  table to `config.PRODUCTS`, `TICK_P`, `LIQ_ATOMS` and `LIQ_THIN_FALLBACK`.
- `liq` counts spread ticks, so its occupancy may still drift with the price over 28 days; the
  report's > 95 % occupancy flag (CONTRACT §4.2) says so, and nothing is re-cut mid-sample.

`liq`, 2026-09-24, decided by Alex: it is the cost of walking the book for one `NOTIONAL_USD`
order (`fill1k_bps`, §4), not the size of level 1 (`l1_min_usd` `< LIQ_THIN_USD = 1000.0` →
thin, `> LIQ_DEEP_USD = 10000.0` → deep, which read thin on 7 of 12 samples in a minute while a
$1,000 order cost 0.44–2.02 bps). v1 then cut `fill1k_bps` itself at `LIQ_DEEP_BPS = 1.0` and
`LIQ_THIN_BPS = 5.0`; both stay in `config.py` because every v1 row was read by them, and nothing
in `loop/` reads them any more.

The words live in `loop/state.py` (`LIQ`, `FLOW`, `TREND`, `VOL`, `DIMS`, `ALPHABET`); the cuts
in `loop/config.py`. The order of `LIQ` (`thin`, `normal`, `deep`) is unchanged, so
`all_states()` and every policy table keep their order; `liq` applies its cuts to the words
reversed. `bot_war` keeps its underscore: one token, no digit, the same spelling as in the prompt
files.

**State string** (`state.py::state_string(adj, base)`), the one thing arms A and B ride and D
looks up:

```
{BASE}: liquidity {liq}, flow {flow}, trend {trend}, vol {vol}
```

`{BASE}` is `config.base(product)` = `product.split("-")[0]`: `SOL` for `SOL-USD` (v1's string,
byte for byte), the probe products' bases for theirs; a base that is not capital ASCII letters is
refused. The product name is the first word (PREREG-v2 §8), so one wording reads identically for
every product up to that word. Ten words after the colon, no digit (a digit raises), no position
(the two arms share one request on one state, and a position would differ per arm). The 81 = 3⁴
states are enumerated in one fixed order (`state.all_states()`: `liq`, `flow`, `trend`, `vol`,
each in alphabet order, `vol` fastest); the nightly's policy tables, arm D's tables and the
truth-table test walk that order.

## 6. Arm C — the rule, exactly (`state.py::rule_c`)

```
buy   iff trend == pumping  and  vol != violent  and  liq != thin
sell  iff trend == dumping  or   vol == violent
hold  otherwise
```

Unchanged in form since 2026-09-23. What `liq != thin` means is §5's for the row's product: both
sides of the book fill `NOTIONAL_USD` within its 100 levels and h is at most the product's thin
cut (`SOL-USD`: a spread of at most four ticks, h ≤ 4.5). So v2's C holds on the `thin` pumping
ticks that v1's C bought (PREREG-v2 §0), and which live ticks fill each state of a row-built
table moves with §5; the synthetic 81-state tables (arm D, candidate scoring) do not depend on the
cuts. `buy` and `sell` are exclusive (pumping ≠ dumping, and buy excludes violent), so the order
of the two tests is immaterial. `flow` never changes `rule_c`. Truth table over the 81 states:
**12 buy, 45 sell, 24 hold** (pinned by `tests/test_state.py`, and per product, the product's base
first in each state string, by `RULE_C` in `tests/test_frozen.py`; `SOL-USD`'s pin is v1's).
Intents are position-free: `buy` = want to be long, `sell` = want to be flat, `hold` = no change;
the book (§10) maps intent onto the current position.

## 7. The four arms

| arm | what decides | where it comes from | changes when |
|---|---|---|---|
| **A** | Jev's answer to the FROZEN `v2` action question (`config.FROZEN_A`), rendered for the row's product | `answers.a_action` → `columns.a` | never; `prompt_a_sha` is constant for the whole of v2 |
| **B** | Jev's answer to the CURRENT action question (`prompts.current(tick_id)`), rendered for the row's product | `answers.b_action` → `columns.b` | only when a person runs `bin/promote` (PREREG-v2 §8: at most three promotions, effective at a T0-anchored day boundary, `activation_tick`); identical to A until the first promotion (both ask `v2`), which is a free test-retest of the model |
| **C** | `rule_c` — no model | `rule_c` | never; §6 is the whole arm |
| **D** | the CURRENT wording's own answer on the product's synthetic state string, looked up by the row's `state` in `prompts/<prompt_b>.table.<product>.json` — no call | `columns.d` | with B: `bin/promote` copies the promoted candidate's column of the proposal night's `.table.json` into the new version's tables; v2's own tables (`prompts/v2.table.<product>.json`) are built before the draft tag (PREREG-v2 §8) |

A and B ride ONE request on ONE state string with ONE shared set of `skip`, `up15`, `down15`
answers (`prompts.build`: the three nouls always come from `v1`). The only thing that can differ
between A and B is the wording of the `action` question. D rides no request: its table holds
what Jev answered, the night the table was scored, on the same synthetic string, in one request
per state carrying the candidates and CURRENT (PREREG-v2 §8), so D against B says whether the
per-minute call is a lookup of its own table (PREREG-v2 §6's D-agreement). D's table holds the
action choice alone, so D has one column, `argmax` (§10). C and D see the same four words. By its
own 81-state table `v2` differs from `rule_c` on 27 of 81 states for `SOL-USD` (PREREG-v2 §1
gives each product's count).

## 8. The questions (`prompts/v1.json`, `prompts/v2.json`, `prompts.py::build`)

Wire shape per question: `{"type": "choice"|"noul", "instructions": str, "criteria": {...}}`.
Choice criteria keys are exactly `buy`, `sell`, `hold`; noul criteria keys are exactly `yes`,
`no`. Five questions per request, in row order: `a_action` (the `FROZEN_A` wording's action,
choice), `b_action` (the CURRENT wording's action, choice), `skip`, `up15`, `down15` (`v1`'s
nouls, never rendered). `v1.json` was frozen 2026-09-23 (canonical sha `7a85308fd126…`); its
`action` criteria restate §6, so in v1 arm A measured how faithfully the model follows a rule it
is given and A − C was zero by construction (PREREG-v2 §0.1). v2 freezes A at `v2.json`, the
wording promoted 2026-09-26 in v1 (canonical sha `b3291ca4a55091bd…`, file sha
`dcc848e5ad1452be…`): it sells on a non-violent dump and holds a violent one. Only `action` is
ever rewritten; a promoted file that changed a noul's type is refused at load (`PromptError`).

**The base token (PREREG-v2 §1).** `v1.json` and `v2.json` were written for `SOL-USD` alone: in
them the whole word `SOL` (`prompts.LEGACY_TOKEN`) is the base placeholder, replaced by the row's
base (`prompts.render`), so `SOL-USD`'s requests are byte-identical to v1's for A. Files `v3` and
later (after `LEGACY_LAST = 2`) name no product and may use the literal `{BASE}`
(`prompts.BASE_TOKEN`). Every other product word — the base of any product in `config.PRODUCTS`
or `config.PROBE_CANDIDATES` as a whole capitalised word, and `{BASE}` in `v1`/`v2` — is refused
by `load()` and by `build()` (`PromptError`), and so by `bin/promote`, which builds before it
writes.

**Which version B asks (PREREG-v2 §8).** A version `bin/promote` writes during v2 carries
`activation_tick` (T0_v2 + 86,400 · (E − 1), a minute tick_id) and `replaces` (the version active
when it ran). `prompts.current(tick_id)` starts at the name in `prompts/CURRENT` and follows
`replaces` while `tick_id` is before that version's `activation_tick`; a version carrying neither
key (`v1`, `v2`) is active whenever the walk reaches it, and a replaced version that activates no
earlier than its successor is refused. So a pending version is invisible to every tick before its
activation, and every reader asks `current()` with the tick it describes: the loop its own tick,
the digest each row's tick, `policy_table` and `bin/promote` now.

`up15` and `down15` are the only questions in the request that ask Jev about the price rather
than about a rule. In v1 they were H2's predictor (2026-09-24, decided by Alex; PREREG §5); in v2
they are descriptive (PREREG-v2 §6: on the shakedown lean tracked the `trend` word at r 0.99 and
never reached a tail). `make report` §6 (CONTRACT §4.6) prints, per product, lean =
`up15.noul − down15.noul` (in [−1, 1], rounded to 12 decimals so equal decimal leans compare
equal) against §11's `ret_h_bps`: Pearson r on the first live row of each 900 s block, Spearman ρ,
r and ρ on every tick, the Brier score of `up15` vs `label = up` and of `down15` vs
`label = down` beside the base-rate Brier, the counts in the measured tails (≥ `NOUL_TAIL` =
0.99, < 0.15), and the `trend` word (§5) beside it as a no-model comparator. Arm A's choice
confidence is printed beside `a.argmax == rule_c` and against the label in report §7,
descriptive only.

## 9. The rule columns (`loop/rules.py::columns`)

One dict per model arm (A and B), keys in this order (`rules.COLUMNS`); every comparison is `>=`
(a value exactly on a cut passes it):

| column | value | constant |
|---|---|---|
| `argmax` | `action.choice` | — |
| `c50`, `c70`, `c85`, `c99` | `choice` if `action.confidence >= k` else `hold` | `CONF_THRESHOLDS = (0.50, 0.70, 0.85, 0.99)`; 0.99 is the one measured tail (JEV PROTOCOL §2.2), the rest are the band this project measures |
| `c50v`, `c70v`, `c85v`, `c99v` | as above, but `hold` if `skip.noul >= VETO_NOUL` | `VETO_NOUL = 0.5` (the veto is a hold, never a sell) |
| `pbuy60` | `buy` if `p.buy >= PBUY`, else `sell` if `p.sell >= PBUY`, else `hold` | `PBUY = 0.60` |
| `noultail` | `buy` if `up15.noul >= NOUL_TAIL`, else `sell` if `down15.noul >= NOUL_TAIL`, else `hold` | `NOUL_TAIL = 0.99`; `up15` tested first, as the contract lists it |

If ANY of the four answers is missing the whole dict is `null` values. A missing optional field
reads as no signal (`confidence → 0.0`, `probabilities → {}`, `noul → 0.0`). A `choice` outside
`buy/sell/hold`, and a number that is a bool, NaN or infinite, is refused before it can reach a
column (`rules._real`; the tick logs `jev`/`parse`); a numeric STRING (`"0.99"`) is read as the
number it spells and makes a column — Jev's typed output sends numbers, and no row is known to
carry one (both folded from ERRATA.md). Arm D has no rule columns: `columns.d` is one word, the
table's choice. Nothing in the tick reads a column; `make report` compares them.

## 10. Paper execution (`loop/book.py`) — pure, replayed from the log

- One paper order of `NOTIONAL_USD = 1000.0`, per product and arm. `pos` is `None` (flat) or
  `{"qty", "entry"}`. Only two of the six (position, intent) cases trade:
  - `buy` when flat → open: `qty = NOTIONAL / ask`, `fee = NOTIONAL · fee_bps / 1e4`;
  - `sell` when long → close at `bid`: `fee = qty · bid · fee_bps / 1e4` (the filled value, what
    the venue charges);
  - `buy` when long, `sell` when flat, `hold` → no-op.
- Mark to `mid` every tick. Per-tick pnl, in bps of `NOTIONAL`, computed DIRECTLY (not as an
  equity difference, so two arms with the same position and different cash histories give
  `d_t == 0.0` exactly):
  - carried position: `qty · (mid_t − mid_prev)`
  - open at ask: `qty · (mid_t − ask) − fee`
  - close at bid: `qty · (bid − mid_prev) − fee`
- `replay(rows, outcomes, arm, column, fee_bps)` walks one product's rows in `tick_id` order
  (`book._order`: `tick_id`, then `ts_rx`; folded from ERRATA.md); `book.ARMS = ("a", "b", "c",
  "d")`: arm `a`/`b` reads `columns[arm][column]`, arm `c` reads `rule_c`, arm `d` reads
  `columns.d` and has the one column `argmax` (`D_COLUMN`; any other column raises, on every
  row). Returns `equity` (cumulative bps), `trades`, `pnl_bps_per_tick`, and — additive to the
  contract — `position` (qty after each tick, `0.0` flat) and `forced_hold`. A row with `absence`
  set (including `halt`, §13), a row whose `mode` is not `live`, a row whose `columns.a` and
  `columns.b` are both null (or argmax-null), or an unpriced book is a forced `hold` for EVERY arm,
  C and D included (neither an outage, a HALT, a PAUSE nor a `--dry` run ever manufactures a
  disagreement: a dry row carries `rule_c` but no model columns, so letting C act on it would give
  C a trade A and B could never make); the position is carried and marked to the row's mid when it
  has one, so the move lands on the tick it happened on, and across an unpriced gap on the first
  priced tick after it. On an otherwise answered row a single null arm holds alone and the others
  trade: `columns.d` null (no table, a refused one, a state it lacks) is a hold for D only, counted
  in D's forced holds; one of `columns.a`/`columns.b` or `rule_c` null is a shape the writer never
  produces and, read, holds that arm alone (folded from ERRATA.md). Two rows with one `tick_id`
  fold (`+=`), in `ts_rx` order. The `outcomes` argument is accepted and unused: a mark-to-mid
  book needs no t+h join, and using one would let t see t+h.
- `paired(rows, outcomes, x, y, column, fee_bps) → [(tick_id, d_t)]`, `d_t = pnl_x − pnl_y`;
  exactly `0.0` on any tick both arms carry the same position (the same `qty`) into and out of,
  which includes every tick both are flat, with one exception (folded from ERRATA.md): two live
  decisions sharing a minute fold, so an arm that round-trips inside that minute pays a spread
  and `d_t ≠ 0` though both arms are flat in and out (the report's disagreement count does not
  count that tick; seen once in 28 synthetic days). Two arms long on entries opened at DIFFERENT
  ticks hold different quantities (`NOTIONAL / ask` at each arm's own entry), so a tick both carry
  long gives `d_t = (q_x − q_y) · (mid_t − mid_prev)`: entry-price noise, a small fraction of a bp
  at ordinary price differences, and NOT a disagreement. A disagreement tick (the report,
  PREREG-v2 §4) is a tick where the two arms are on different SIDES, long vs flat, into or out of
  it.
- **Decision-held replay** (PREREG-v2 §4), `at_cadence(rows, c, t0)` with c ∈ `CADENCES = (900,
  3600, 14400)` and t0 = T0_v2 (PREREG-v2 §12; the book has no T0 and T0_v2 is not aligned to c):
  within each c-block [t0 + c·j, t0 + c·(j + 1)), every arm's intent is its own on the block's
  **decision row** — the first row of the block in `book._order` on which `replay` would not
  force a hold: a live row with no absence, priced (`bid`, `ask` and `mid` all pass `book._px`),
  whose `columns.a` and `columns.b` are not both null or argmax-null — and `hold` on every other
  row of the block (`book._held`'s copy: every non-null intent of a, b, D and `rule_c` turned into
  `hold`); a block with no decision row holds throughout. The decision row is shared by every arm:
  A and B read their columns, C `rule_c`, D `columns.d` (null a hold for D only). The transformed
  rows feed `replay` and `paired` unchanged, so the position, the marks, the spread and the fee
  columns are this section's. The input rows are not modified.

**Fees.** `FEE_BPS_COLUMNS = (0.0, 2.0, 10.0, 25.0, 50.0, 90.0)`, ascending: the same decisions
replayed at six constants — **0 = gross, the H1 cell** (the PRIMARY), 2 = Binance.US, 10 = the
article's, 25, **50 = the venue's retail maker, 90 = the venue's retail taker, both read
in-account by Alex on 2026-09-27** (PREREG-v2 §6). v1's unverified 60 and 120 bps columns are
replaced by the verified 50 and 90. A fee never changes a decision, only the pnl of the fills:
positions do not depend on the fee, so an arm's summed pnl is affine in it, which PREREG-v2 §6's
break-even arithmetic reads from the 0 and 90 columns (`report.BREAK_EVEN_FEE = 90.0`).

2026-09-24, decided by Alex: the PRIMARY is `FEE_BPS_PRIMARY = 0.0`, gross (it was 120.0, the
venue taker as then assumed; before that a 60 bps placeholder). Why: a round trip at the venue's
verified taker costs 2 × 90 = **180 bps** against a 15-minute return sd of ~26–33 bps
(`ret15_sd_bps`: 28.9 in the fixture window, 26.6 in the first `--dry` row), so profitability at
retail fees is settled by arithmetic, and a NET primary would mostly rank which arm trades least.
At 0 bps, gross of fees, a difference between the arms is direction net of the spread, which is
the question PREREG-v2 §5 asks. Turnover still costs one spread per round trip (open at the ask,
close at the bid, marked to mid: 0.87 bps at a 1c spread and 1.74 bps at 2c on ~$115, the same
order as the 1.78 bps per-block MDE), so trades/day is read beside the cell. Every net-of-fee
column (2, 10, 25, 50, 90 bps) is DESCRIPTIVE: printed, never tested.

The venue's own cost is `FEE_BPS_VENUE = 90.0`, the realistic-cost column, **verified**:
`FEE_BPS_VENUE_SOURCE = "verified: Coinbase Advanced spot taker, tier Intro (30-day volume $0),
0.90 %, maker 0.50 %; read in-account by Alex at https://www.coinbase.com/advanced-fees on
2026-09-27 ~22:55Z (ERRATA.md; SPEC.md's verified tier-0 taker row)"` (v1 carried 120.0 from two
third-party tables dated April 2026, marked UNVERIFIED; its rows carry no fee, so the change moved
no row). The report prints `FEE_BPS_VENUE` and its source beside the pair table with a per-arm
line at that fee and tags its columns `[venue fee]`; the nightly digest shows each arm's pnl at
0 bps and at the verified maker (50) and taker (90), labelled; nothing hard-codes a fee but
the constants named in §14 (`report.ERRATA_TIER` among them: the 2026-09-27 reading, printed beside
§12's table and standing in while it is blank). The venue's whole spot schedule, the tiers a 30-day volume reaches,
is PREREG-v2 §12's field, read in-account at sealing; this file does not restate it.

```
Verified tier-0 taker fee: 90 bps   URL: https://www.coinbase.com/advanced-fees   read (UTC): 2026-09-27 ~22:55Z (Alex, in-account: tier Intro, 30-day volume $0, spot maker 0.50 % / taker 0.90 %)
```

Rows carry no fee, so the log is unaffected by the value; `FEE_BPS_COLUMNS` is named here (this
file's sha is in every v2 row) and in PREREG-v2 §6.

## 11. The outcome join (`loop/outcomes.py::join`)

Per product, over that product's own log. For each row at t with a mid, `mid_h` is the mid of the
row that HAS a mid and whose `ts_rx` is NEAREST `t + 900`, within `[t + 900 − 30, t + 900 + 30]`
(`JOIN_TOL_S = CADENCE_S / 2 = 30.0`; both edges inclusive; a tie goes to the earlier row, ties
judged in whole milliseconds, and the joined row is strictly after t; folded from ERRATA.md).
`ts_rx` is the feed-entry clock, the minute boundary plus timing noise (sleep overshoot and the
guards under `--forever`, the StartCalendarInterval phase under launchd since 2026-09-27; folded
from ERRATA.md); rows 60 s apart always leave exactly one within 30 s of any instant, so the
realised horizon is 900 ± 30 s whatever the phase, and a missing t+15 row is a gap because its
neighbours are 60 s away. (The first form, "the FIRST row in `[t + 900, t + 990]`", picked the
t+16 row whenever the t+15 row's noise was smaller than t's: a 15- or 16-minute label on a coin
flip. Replaced before any v1 sample row.) `ret_h_bps = 1e4 · ln(mid_h / mid_t)`; `label` is `up`
if `ret_h_bps >= DEAD_BAND_BPS = 5.0`, `down` if `<= −5.0`, `flat` between (exactly ±5 is a move:
config says |ret| BELOW the band is flat). Anything else — no row in the window, no mid at t — is
`{"absence": "gap"}`, never a row outside it. A null-mid absence row landing in the window is
skipped as a candidate, not taken as a gap. Two rows with one `tick_id` (`outcomes.rank`, folded
from ERRATA.md): the live decision speaks for its tick, then any other priced row, then an
unpriced one; equal ranks keep the first in file order. A line that is not one JSON value
(`outcomes.load`, folded from ERRATA.md): whole rows on it are read, forward from its start (rows
that lost only their newlines), then, after a torn row, each whole row that carries the writer's
keys and ends where the next one begins; an object nested inside a row is never read as a row;
the line counts as one skip. Forward only: t sees t+h, never the reverse. A pending outcome is
not yet a gap (folded from ERRATA.md): `loop.inference_v2 --sample` refuses (exit 3) while the
sample's last day is open, until some product's log has reached a tick at or after T0_v2 + 28 d +
h + 30 s, where `report.days_table` closes d28; `--accept-pending` says the logs stopped (itself
refused until a minute after the minute that tick falls in), judges every sample day closed, counts
a live row whose t + h never came as a gap, and the output's header says so (CONTRACT §4).

## 12. The Jev call (`loop/jev.py`) — the only code that sees the key

- Body `{"model": "jev-1.13.0", "state": <state string>, "questions": <five>}` (this exact dict
  is what `--dry` prints); headers `Authorization: Bearer <key>`, `Content-Type:
  application/json`; `JEV_URL = https://api.typesafe.ai/v1/systemone`; timeout `JEV_TIMEOUT_S =
  20`.
- **Ledger before send, failing closed.** One row per ATTEMPT is fsync'd to the product's
  `sends.tsv` (`config.store(p).sends`: `data/sends.tsv` for `SOL-USD`, `data/<PRODUCT>/sends.tsv`
  otherwise; the nightly's table sends go to `data/sends.tsv`) (`utc  source  state_chars  q_chars
  sha12  paths`, source `jev-paper-loop`, `paths` always `-`, same columns as JEV's
  `DISCLOSURE.tsv`) before the request; an unwritable ledger means nothing is sent
  (`JevError("ledger")`). A `sends.tsv` counts sends, not ticks.
- At most ONE retry, after `RETRY_S = 1.0` s on 5xx or a transport failure, or after
  `Retry-After` capped at `RETRY_AFTER_CAP_S = 5.0` s on 429 (20 + 5 + 20 = 45 s fits the 50 s
  watchdog). Never on another 4xx: 401/403 raise and the tick writes `data/HALT` ("key
  rejected"). A 3xx is never followed (the bearer key would go with it): it is raised as
  `http-4xx` with its status, no retry. A retry whose ledger append fails raises attempt 1's
  kind, not `ledger` (attempt 1 was billed). (Folded from ERRATA.md.)
- Answer shape: choice → `{"choice", "probabilities", "confidence"}`; noul → `{"noul"}`. A
  missing field on any asked question is `parse` (a half answer must not become a wrong column).
  `input_tokens` from `usage.input_tokens`, `0` when absent, and `0` for a null, `""`, `[]` or
  `{}` count, the answer kept (folded from ERRATA.md). A `model` other than `MODEL` is returned
  and logged as drift.
- Spend: `USD_PER_MTOK = 0.042` on input tokens, output free. The ~1.8 KB body is ~$0.04/day a
  product at 1,440 ticks. Because a reply without `usage` logs `0` and a failed send logs `null`,
  the spend guard (§13) charges such a send `JEV_TOKENS_IF_UNKNOWN = 2000` tokens rather than
  nothing.

## 13. Guards and absences (`loop/cycle.py`, in order, every tick of every product)

1. Path guard: the resolved repo path under either `FORBIDDEN_PREFIXES`
   (`~/Projects/crypto-trading-system`, its iCloud mirror) → exit 3, nothing written.
2. `data/HALT` exists, or `data/PAUSE.<PRODUCT>` exists for this tick's product → the tick is
   HALTED: it takes the lock and runs the feed, the state, `rule_c`, the prompts and the table
   lookup as usual (§3–§8), then writes the row with `absence: "halt"` where the send would begin:
   no ledger row, no request, no body printed (dry or live). **`data/HALT` is the one global
   stop**: the spend trip, a key rejection and the nightly write and read only it, and every loop
   and the nightly stop on its existence. **`data/PAUSE.<PRODUCT>` pauses that product's sends
   alone** (PREREG-v2 §2; written by hand, "prereg: 3 bad days" on a product's third BAD day,
   §9.3): the other products' loops, the nightly and the spend guard ignore it. HALT and PAUSE stop
   SENDS only; the feed, arm C's `rule_c`, the outcome join and the report keep running, so the 15
   minutes before a HALT keep their t+h outcomes and the day's outcome fill (PREREG-v2 §9.3) is not
   spent by it. A feed or prompts failure under HALT keeps its own absence (`absence` names the
   first step that did not happen). In the book a halt row is a forced hold for EVERY arm, like
   any absence (§10): `rule_c` is logged but not traded, so neither ever manufactures a
   disagreement; its mid carries the marks.
3. Today's spend — Σ billed tokens over today's rows (by `tick_id` UTC date) of EVERY product's
   decision log (`config.store(p).decisions` for p in `PRODUCTS`), × `USD_PER_MTOK` / 1e6 —
   ≥ `DAILY_SPEND_HALT_USD` = 0.25 × the number of products → write `data/HALT` with the reason;
   the tick is then HALTED exactly as in 2. A log that exists but cannot be read (a 0200 mode, a
   directory, EIO), or a count, or today's sum of them, past a float's range, counts as over the
   limit: the guard cannot count, so it trips; a missing log is $0 (folded from ERRATA.md). Billed
   tokens (`cycle.py::billed_tokens`): the logged `jev.input_tokens` when positive; else
   `JEV_TOKENS_IF_UNKNOWN = 2000` for a live row that reached the model (`absence` null, or
   `"jev"` with any kind but `unsigned`/`no-key`/`ledger`, which are raised before a request
   leaves); else 0 (dry rows, halt/lock/feed/guard). At 2000 per unknown send the guard trips at
   ~2,976 such sends a product in a day, 2× the cadence: a runaway, never a normal day.
4. `flock` on the product's `loop.lock`, non-blocking; held → `absence: "lock"`.
5. Feed (§3) → `absence: "feed"` on `FeedError` or a window `state.py` refuses; features/state
   (§4–§6); prompts and the table (§7–§8; a prompt that does not load is `absence: "guard"`, a
   table that does not load is `table_sha` and `columns.d` null and nothing else); `--dry` writes
   the row with `mode: "dry"`, `answers` and every column `null`, no ledger row, no send, and
   prints the exact body to stdout; else `jev.ask` → `absence: "jev"` with `jev.error` on
   `JevError` (401/403 also write `data/HALT`, "key rejected"). A post-send exception that is not
   a `JevError` is `absence: "jev"`, `jev.error: "unexpected"` (§2), billed.
6. Columns (§9, and `columns.d`), atomic append to the product's log (one `write`, `flush`,
   `fsync`; the line starts with a newline when the log's last byte is not one, so a torn line is
   closed first; folded from ERRATA.md), the product's heartbeat = `ts_rx`. 50 s `signal.alarm`
   watchdog per tick; SIGTERM finishes the write and releases the lock. Every exit is 0 except the
   path guard (3) and a usage error (2).

Every path after the path guard writes exactly one row with string `tick_id` and `ts_rx`,
including the lock row written before the feed, except when SIGTERM lands before the write
begins, the watchdog lands in the guards before the lock, the product's data directory cannot be
created, or the append itself fails (each logged on stderr, exit 0; folded from ERRATA.md).
**One-process mode** (`--every-product`, PREREG-v2 §2): one process ticks every product in
`PRODUCTS` in sequence, each into its own store, under one `WATCHDOG_S` budget a round (each
product's tick is armed with what is left of it; a product reached with less than a second left
is not ticked that minute, said on stderr, no row); `JEVLOOP_PRODUCT` beside it is a usage error.

The nightly (`nightly/`) reads a digest of every product's log (only rows carrying this file's
sha) and scores candidate wordings on each product's 81 synthetic states only, never on a logged
outcome; it writes `proposals/` (`<date>.json`, `.md`, and the gitignored `.table.json` the .md
vouches for by its sha), the digest `data/digest-<date>.md`, `logs/`, `data/dash.html`, its ledger
rows, and `data/HALT` on a rejected key (the caller writes HALT, as in §12), and nothing else
(folded from ERRATA.md). It sends nothing while `data/HALT` exists (checked before every send). A
429 or an `unsigned`, `no-key` or `ledger` error ends its night; so do `MAX_TRANSIENT_RUN = 3`
transient failures in a row, `MAX_OTHER_RUN = 3` other failures in a row, `MAX_ERROR_RUN = 3`
failures of any kind in a row, and the deadline, `DEADLINE_S = 900` s a product (folded from
ERRATA.md). The only thing it can change in a row, via a person running `bin/promote`, is, from
the promotion's `activation_tick` on, `prompt_b` / `prompt_b_sha` and what `answers.b_action` is an
answer to, and with them `table_sha` and `columns.d`.

## 14. Every constant, in one place

Every constant a row, a v2 reading, the treatment or `bin/promote`'s schedule depends on. A `where`
cell left blank is the row above's file. `tests/test_spec.py` holds every name here to the module
named and every value cell to the code's value, and holds every capitalised constant of
`loop/config.py` (but its paths) and of `book`, `cycle`, `prompts`, `report`, `inference_v2`,
`exclusions_v2`, `digest`, `policy_table`, `slow_model` and `bin/promote` to this table, but those it
lists as exit codes, file formats, printed words, aliases or parts of a constant named here;
`tests/test_frozen.py` pins each by value. v2's rows are marked (v2); a v1 constant that v2 left
alone keeps its v1 row.

| where | name | value |
|---|---|---|
| `loop/config.py` | `VENUE` / `PRODUCT` | `coinbase` / `SOL-USD` (the v1 product; `JEVLOOP_PRODUCT` unset) |
| | `PRODUCTS` (v2; fixed at the draft tag) | `("SOL-USD",)` and PREREG-v2 §2's two probe products, in `bin/probe summarize`'s order, each with a row in §5's table |
| | `PROBE_CANDIDATES` (v2) | `ETH-USD`, `XRP-USD`, `DOGE-USD`, `AVAX-USD`, `LINK-USD`, `ADA-USD` (`bin/probe`'s order; their bases are product words no prompt file may carry) |
| | `ENV_PRODUCT` (v2) | `JEVLOOP_PRODUCT` |
| | `CADENCE_S` / `HORIZON_S` | 60 / 900 |
| | `CADENCES` (v2) | (900, 3600, 14400): the decision-held replay cadences (s), §10 |
| | `FROZEN_A` (v2) | `v2`: arm A's wording, `prompts/v2.json` |
| | `MODEL` / `JEV_TIMEOUT_S` | `jev-1.13.0` / 20 |
| | `USD_PER_MTOK` / `DAILY_SPEND_HALT_USD` (v2: a product's share) | 0.042 / 0.25 × the number of products |
| | `NOTIONAL_USD` | 1000.0 |
| | `BOOK_LEVELS` (2026-09-24) | 100 |
| | `TICK_P` (v2) | per product, §5's table (`SOL-USD` 0.01) |
| | `LIQ_ATOMS` (v2) | per product (a10, a90), §5's table (`SOL-USD` (1, 4)) |
| | `LIQ_THIN_FALLBACK` (v2) | per product, §5's table (`SOL-USD` no) |
| | `LIQ_THIN_BPS` / `LIQ_DEEP_BPS` (v1's cuts, 2026-09-24; kept for v1's rows, read by nothing in `loop/`) | 5.0 / 1.0 |
| | `FLOW_P_LO` / `FLOW_P_HI` | 10 / 90 |
| | `TREND_Z` | 1.0 |
| | `VOL_RATIO_LO` / `VOL_RATIO_HI` | 0.5 / 2.0 |
| | `WINDOW_MIN` | 300 |
| | `DEAD_BAND_BPS` | 5.0 |
| | `JEV_TOKENS_IF_UNKNOWN` | 2000 |
| | `FEE_BPS_PRIMARY` (the H1 cell, gross; 2026-09-24, was 120.0) | 0.0 |
| | `FEE_BPS_VENUE` (v2: verified, §10; `FEE_BPS_VENUE_SOURCE`) | 90.0 (v1: 120.0, unverified) |
| | `FEE_BPS_COLUMNS` (v2) | (0.0, 2.0, 10.0, 25.0, 50.0, 90.0) (v1: …, 60.0, 120.0) |
| | `CONF_THRESHOLDS` | (0.50, 0.70, 0.85, 0.99) |
| | `VETO_NOUL` / `PBUY` / `NOUL_TAIL` | 0.5 / 0.60 / 0.99 |
| `loop/state.py` | `LIQ` / `FLOW` / `TREND` / `VOL` | thin normal deep / quiet organic bot_war / dumping flat pumping / calm normal violent |
| | `DIMS` | liq flow trend vol |
| | `FLOW_BLOCK_MIN` / `RET_BLOCK_MIN` | 5 / 15 |
| | `BASE` (v2) | `SOL`: `state_string`'s base when none is given (v1's string) |
| `loop/feed.py` | `CANDLES_REQ` / `TRADES_WINDOW_S` / `TRADES_LIMIT` / `TIMEOUT_S` / `MAX_FEED_AGE_S` | 350 / 300 / 1000 / 10 / 120 |
| | `START_MAX` | 2^40 (a candle start at or past it, or below 0, refuses the set) |
| `loop/outcomes.py` | `JOIN_TOL_S` | 30.0 (`CADENCE_S / 2`, either side of t+h) |
| `loop/jev.py` | `RETRY_S` / `RETRY_AFTER_CAP_S` | 1.0 / 5.0 |
| `loop/rules.py` | `COLUMNS` | argmax c50 c70 c85 c99 c50v c70v c85v c99v pbuy60 noultail |
| `loop/cycle.py` | `WATCHDOG_S` / `TAIL_BYTES` | 50 / 8 MiB (the spend guard reads each log's tail) |
| | `ROW_V` | 1 (the row's `v`, §2) |
| | `UNSENT_KINDS` | `unsigned`, `no-key`, `ledger`: raised before a request leaves, billed 0 |
| | `SPEND_UNCOUNTED` (v2) | 1.7976931348623157e+308 (`sys.float_info.max`: a token count, or today's sum of them, past a float's range; over any limit, never "unreadable") |
| `loop/book.py` | `ARMS` (v2) | a b c d |
| | `D_COLUMN` (v2) | `argmax`: arm D's one column |
| `loop/prompts.py` | `LEGACY_TOKEN` / `BASE_TOKEN` / `LEGACY_LAST` (v2) | `SOL` / `{BASE}` / 2 (§8: `v1`, `v2` use `SOL`; `v3` on use `{BASE}`) |
| | `TABLE_ANSWERS` (v2) | buy sell hold: the answers an arm-D table may hold (§7) |
| `loop/report.py` | `PRIMARY` cell / `VENUE_FEE` / `BLOCK_S` / `SAMPLE_DAYS` | (B, C, `argmax`, `FEE_BPS_PRIMARY` = 0) / `FEE_BPS_VENUE` / 900 (`HORIZON_S`) / 28 |
| | `PAIRS` (v2: D − B and D − C at argmax only) | B−C, A−C, B−A, D−B, D−C |
| | `OCCUPANCY_FLAG` / `HEALTH_N` | 0.95 / 3 (`--health`: sections 1–3) |
| | `BAD_FILL` / `BAD_JEV_ERR` / `BAD_DAYS_PAUSE` | 0.95 / 0.05 / 3 (stop rule 3, PREREG-v2 §9.3: v2's third BAD day is a `PAUSE.<PRODUCT>` by hand) |
| | `NOUL_HIGH` / `NOUL_LOW` / `LEAN_DP` (2026-09-24) | `NOUL_TAIL` = 0.99 / 0.15 (the measured tails, counted, never acted on) / 12 (lean's rounding) |
| | `VOID_KEPT_DAYS` (v2) | 21 (PREREG-v2 §9.4) |
| | `LOOKUP_AT` / `DRIFT_BELOW` / `MODAL_MIN` (v2) | 0.99 / 0.95 / 10 (PREREG-v2 §6's D readings) |
| | `GAP_S` (v2) | 900 (`gap_blocks`, PREREG-v2 §4) |
| | `BREAK_EVEN_FEE` / `FEE_EPS` (v2) | 90.0 / 1e-9 bps (PREREG-v2 §6's f*, and "fees cancel") |
| | `F_CELLS` (v2) | `{(3600, "b", "c"): "F1", (14400, "b", "c"): "F2", (900, "a", "c"): "F3", (900, "b", "a"): "F4"}`: family F by (cadence, x, y), PREREG-v2 §6's order |
| | `ERRATA_TIER` (v2) | `{"name": "Intro", "band": "at 30-day volume $0", "low": 0.0, "high": None, "maker": 50.0, "taker": 90.0}`: ERRATA.md's reading, printed beside §12's fee-tier table and standing in for it while §12 is blank (PREREG-v2 §6) |
| | `ERRATA_TIER_WHERE` (v2) | `ERRATA.md's 2026-09-27 reading (Alex, in-account, ~22:55Z)` |
| `loop/inference_v2.py` | `SEED_H1` / `RESAMPLES` / `BLOCK_LEN` (v2) | 20261023 (family F: + i) / 10,000 / 4 units of the cell's cadence (PREREG-v2 §5–§6) |
| | `ALPHA_H1` / `ALPHA_F` (v2) | 1/40 / 1/160, exact fractions (`sorted[249]` / `sorted[62]`) |
| | `MIN_KEPT_DAYS` / `N_DAYS` / `POWER` (v2) | 21 / 28 / 0.8 |
| | `FEE_COLUMNS` (v2) | `FEE_BPS_COLUMNS`, transcribed |
| | `SEAL_TAG` / `SEAL_CHECK_TIMEOUT_S` (v2) | `prereg-v2-seal` / 3600 (`make results` checks the tag and runs `bin/seal-check --since` it, PREREG-v2 §13) |
| `loop/exclusions_v2.py` | `N_DAYS` (v2) | 28 (`exclusions.N_DAYS`: the days d01–d28 a line may name) |
| `nightly/digest.py` | `FEES` (v2) | (0.0, "direction"), (`MAKER_BPS`, "venue maker"), (`TAKER_BPS`, "venue taker") |
| | `MAKER_BPS` / `TAKER_BPS` (v2) | 50.0 / 90.0 (read in-account 2026-09-27) |
| | `DISAGREE_CONF` / `DISAGREE_MAX` | 0.85 / 25 |
| `nightly/policy_table.py` | `DEADLINE_S` (v2: a product) / `MAX_CANDIDATES` | 900.0 / 3 |
| | `MAX_TRANSIENT_RUN` / `MAX_OTHER_RUN` / `MAX_ERROR_RUN` | 3 / 3 / 3 |
| | `CANDIDATE_VERSION` / `TABLE_SUFFIX` (v2) | `v3` (`LEGACY_LAST` + 1: a candidate's base token is `{BASE}`, §8) / `.table.json` (beside `proposals/<date>.md`) |
| `nightly/slow_model.py` | `MODEL_ID` / `NIGHT` (v2) | PREREG-v2 §8's id / PREREG-v2 §8's night (both blank here while §8's are; `tests/test_slow_model.py` holds them to §8's line) |
| `bin/promote` | `E_MIN` / `E_MAX` / `E_SPACING` / `MAX_PROMOTIONS` (v2) | 8 / 22 / 7 / 3 (PREREG-v2 §8: effective days 8 ≤ E ≤ 22, E_k − E_(k−1) ≥ 7, at most three) |
| | `LEAD_S` / `DAY_S` (v2) | 600 (refused when now ≥ activation − 600 s) / 86,400 |
| | `PREREG_TAG` / `DRAFT_TAG` / `TABLE_ONLY_VERSION` (v2) | `prereg-v2-seal` / `prereg-v2-draft` / `v2` (`--table-only` writes v2's tables and no other's) |

PREREG-v2 §12 holds T_first_v2, T0_v2 and the venue's fee-tier table; this file names them and
restates neither.

---

sha256 of this file is written into every v2 row as spec_sha; changing this file starts a new experiment.

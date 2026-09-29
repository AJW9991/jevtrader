# CONTRACT — interfaces every module is built to

Read this whole file before writing a line. It is the one place the modules
agree. If something here is wrong, say so in your return value; do not silently
build something else.

## 0. What this is, and is not

A paper-only, forward-only measurement of the "two models at two speeds" loop:
a fast typed model (Jev) answers a fixed set of typed questions once a minute
from a ~10-word adjective state; a slow model (Claude, nightly) proposes a
rewrite of one question's wording into a proposal file; a person applies it.

- **Paper only.** No wallet, no exchange keys, no orders. Positions exist only
  by replaying the decision log.
- **Forward only.** A decision is made at tick t from data available at t; the
  outcome is whatever the log recorded at t+h. Nothing is ever computed over
  data from before the loop started, and nothing is back-filled.
- **Separate.** This repo never reads, writes, imports from, or proposes
  changes to `~/Projects/crypto-trading-system` or its iCloud mirror. A path
  guard refuses to run under either prefix.
- **Human-applied.** The nightly writes `proposals/`. Only `bin/promote`, run
  by a person, changes `prompts/`. Nothing self-deploys.
- **Measurement, not decision.** Every action rule is a COLUMN derived from one
  logged answer. Nothing in the tick acts on a confidence. The report compares
  columns.

Decisions already made (do not reopen): venue Coinbase Advanced Trade public
API, product `SOL-USD`; cadence 60 s, horizon 15 min; three arms A/B/C; host is
this Mac (attended `--forever` first, launchd `--once` later); nightly scores
candidates on 81 synthetic states only, never on logged outcomes; PREREG is
H1+H2 co-primary over 28 days. 2026-09-24, decided by Alex: H1 is at 0 bps
gross (`FEE_BPS_PRIMARY = 0.0`), not at the venue's own taker fee (was
decided 2026-09-23); the venue's 120 bps taker is `FEE_BPS_VENUE`, a
descriptive realistic-cost column: profitability at retail fees is settled by
arithmetic (240 bps a round trip against a ~33 bps 15-min sd), not tested.
2026-09-24, decided by Alex: H2 moves to the direction probabilities — Pearson
r between `up15.noul − down15.noul` and `ret_h_bps` on one row per 900 s block
(PREREG §5) — not arm A's choice confidence, which with `v1`'s criteria
restating the rule measures rule-matching, not outcomes (report §4.7,
descriptive).

**PREREG-v2, the second block** (PREREG-v2.md, SPEC.md v2; frozen by the `prereg-v2-draft` tag,
built on branch `prereg-v2`). Where a v1 line above differs, these hold for the v2 build, and v1's
readers still read the v1 log's rows as before (the report's fee columns over it are v2's; SPEC's
header): products `config.PRODUCTS` (`SOL-USD` and PREREG-v2 §2's
two probe products), one loop process per product (`JEVLOOP_PRODUCT`; unset = `SOL-USD`, v1's
paths) or one process ticking them in sequence (`--every-product`); four arms, A frozen at `v2`
(`config.FROZEN_A`), B the CURRENT wording, C `rule_c`, D the CURRENT wording's 81-state table
looked up by the state (no call); `liq` read in half-ticks per product (SPEC §5); H1 is B − C at
900 s, gross, pooled over products by time block, decided once per 15-minute block
(`book.at_cadence`); family F is B − C at 3,600 s, B − C at 14,400 s, A − C at 900 s and B − A at
900 s (PREREG-v2 §6); the direction probabilities are descriptive; the venue fee
is the verified 90 bps (`FEE_BPS_VENUE`) and the fee columns are (0, 2, 10, 25, 50, 90);
promotion is on PREREG-v2 §8's schedule, enforced in `bin/promote`; `data/HALT` is the one global
stop and `data/PAUSE.<PRODUCT>` pauses one product's sends.

## 1. Toolchain and layout

- `/opt/homebrew/bin/python3` (3.14). **Standard library only.** No pip.
- Never `import` anything from `~/Projects/JEV/bin/jev` (it exits at import
  without a key). Copy the ~60 lines you need; cite the source lines.
- Files are owned by exactly one builder. Touch only your files.

```
jev-paper-loop/
  CONTRACT.md            this file
  PROTOCOL.md            the carve-out Alex signs (drafted; not a builder's file)
  SPEC.md                row schema, alphabet, thresholds, arms — frozen; its sha is in every row (v2 since the
                         build: every v2 row carries SPEC v2's sha; v1's rows prereg-v1's, `git show prereg-v1:SPEC.md`)
  PREREG.md              v1's 28-day test and stop rules — sealed by the prereg-v1 tag
  PREREG-v2.md           the second block's test, stop rules, build and switch; §12 holds T0_v2 and the fee tiers
  ERRATA.md              where the sealed documents and the code disagree; the v2 deviations table (PREREG-v2 §13)
  README.md  Makefile  STEPS.md  CLAUDE.md (working rules)  HANDOFF.md (the baton)
  .github/workflows/test.yml   CI: make test on every push (3.12, 3.13, 3.14)
  loop/__init__.py
  loop/config.py         constants (written; import, do not edit)
  loop/feed.py           Coinbase public snapshot
  loop/state.py          features → adjectives → state string; the arm-C rule
  loop/prompts.py        load v1 + CURRENT, sha them, build the questions dict
  loop/jev.py            ledger-first send; the only code that sees the key
  loop/rules.py          action-rule columns from one answer
  loop/book.py           paper execution, pure, replayed from the log
  loop/outcomes.py       the t+h join
  loop/cycle.py          one tick; --once / --forever / --dry
  loop/report.py         make report (sections 4-7 withheld on sample rows until day 28; --health, --sample, --unblind); without --log PREREG-v2's report over every product's store, per product and pooled, at each cadence; T0_v2 from PREREG-v2 §12
  loop/looks.py          data/looks.tsv: every report --unblind appended as (UTC, argv, HEAD) (PREREG-v2 §9.5)
  loop/dash.py           make dash: the health page, report §1-§3 only, data/dash.html
  loop/status.py         make status: the morning check in one screen, report §1 only
  loop/exclusions.py     data/exclusions.tsv read (stop rule 3's list; inference applies it, status shows it)
  loop/exclusions_v2.py  data/exclusions-v2.tsv read, {(N, product)}, beside the rule recomputed from the log, which governs (PREREG-v2 §9.3)
  loop/inference.py      PREREG §4-§5 once, at day 28: v1's RESULTS.md, made from main before the switch (results-v1 after it); refuses the sample before then
  loop/inference_v2.py   PREREG-v2 §4-§7 and §9 once, at day 28 (make results, RESULTS-v2.md), over every product's store; refuses before then and while d28 is open
  nightly/digest.py      what the slow model may read
  nightly/policy_table.py  81 synthetic states per candidate
  nightly/capped.py      the claude call under a cap on awake seconds
  nightly/answered_model.py  which model answered the call, read from the CLI's transcript
  nightly/propose.sh  nightly/PROMPT.md  nightly/settings.json
  bin/promote            the human apply step
  bin/readers-diff       two trees' readers on one log: counts and tick_ids only (before a pull)
  bin/seal-check         PREREG-v2 §13: the seal's (a)-(e); --draft before the draft tag; --since TAG at v2's make results
  bin/probe              PREREG-v2 §2: the added products' probe over D (run, volume, summarize); finished, never edited
  bin/fill1k-quantiles   PREREG-v2 §3: h's quantiles, atoms and occupancy over a log's live rows (features only)
  bin/plists             writes and checks the per-product loop plists from launchd/loop-product.plist.in
  bin/results-v1         v1's make results behind the prereg-v2-draft guard (ERRATA PREREG §8.1)
  bin/backup-data        the backup job's copy of every store (STEPS §9)
  nightly/slow_model.py  PREREG-v2 §8's pinned slow-model id, the one place it lives
  nightly/trial-night.sh PREREG-v2 §8's trial night before the draft tag
  launchd/com.alexward.jevloop.loop.plist  launchd/com.alexward.jevloop.nightly.plist  launchd/com.alexward.jevloop.backup.plist
  launchd/loop-product.plist.in  the per-product loop plist (PREREG-v2 §2): bin/plists writes launchd/com.alexward.jevloop.loop.<P>.plist from it
                         for each P in config.PRODUCTS but SOL-USD (JEVLOOP_PRODUCT=P, logs/loop-launchd-<P>.log); `bin/plists` checks them
  launchd/one-process/com.alexward.jevloop.loop.every-product.plist  §2's one-process mode (loop.cycle --once --every-product),
                         installed only instead of every loop plist, never beside them; outside launchd/*.plist on purpose
  prompts/v1.json        frozen (written)   prompts/v2.json (promoted 2026-09-26; arm A in v2)   prompts/CURRENT  → "v2" (one line)
  prompts/v<N>.table.<PRODUCT>.json  arm D: version N's answer on the product's 81 synthetic states (bin/promote writes them)
  probe/<D>/             bin/probe's rows over D, committed verbatim (PREREG-v2 §2)
  fixtures/              one recorded Coinbase snapshot set, committed
  tests/                 unittest, stdlib; tests/fixture_prompts.py pins a v1-only prompts root and tests/fixture_prereg.py a PREREG.md (dash.PREREG_PATH) (no test depends on what the live prompts/CURRENT names; one checks it builds, whatever it names)
  data/   logs/   proposals/   (gitignored except proposals/*.md, data/exclusions.tsv, data/exclusions-v2.tsv and data/looks.tsv, versioned when they exist)
```

## 2. Data types (plain dicts; keys exactly as written)

**Snapshot** — `loop/feed.py::snapshot(product=config.PRODUCT) -> dict`
```
{ "ts_rx": ISO8601 UTC ms (this machine's clock, the decision timestamp),
  "product": str (the product asked: a product in config.PRODUCTS; its id goes into the three URLs),
  "bid": float, "bid_size": float, "ask": float, "ask_size": float,   (level 1)
  "bids": [[price, size], ...], "asks": [[price, size], ...]
          floats, best first (bids down, asks up), at most config.BOOK_LEVELS = 100 a side,
          from product_book?limit=100; bids[0] == [bid, bid_size], asks[0] == [ask, ask_size],
  "book_time": ISO8601 or null (venue's book timestamp if given),
  "candles": [ {"start": epoch_s int, "open","high","low","close","volume": float}, ... ]
              oldest first, ONE_MINUTE, at least 300 rows, newest is the last CLOSED minute,
  "trades_5m": int  (count of trades with time >= ts_rx-300s; -1 if the endpoint gave none),
  "feed_age_s": float (ts_rx minus the newest candle's start+60, i.e. how stale),
  "http": {"calls": int, "ms": int} }
```
Raises `FeedError(str)` on any HTTP/parse failure, a book naming another product, fewer than 300 closed candles, a
window that is not contiguous, a window candle whose open/high/low/close is not finite
and positive (or whose volume is not finite and non-negative), a candle start outside [0, 2^40), `feed_age_s` over
`MAX_FEED_AGE_S` (120 s), an empty or crossed book, or a level that is not a finite
positive price and size. A failed trades call is `trades_5m = -1`, not an error. No
retries inside feed.
(2026-09-24, decided by Alex: `bids`/`asks` added and `limit=1` → `limit=100`, so
`state.features` can walk the book; the row keeps level 1 only.)

**Features** — `loop/state.py::features(snap) -> dict` (numbers; logged, never sent)
```
{ "mid": float, "spread_bps": float, "l1_min_usd": float,
  "fill1k_bps": float|null, "fill1k_short": bool,
  "vol5_usd": float, "vol5_p10": float, "vol5_p90": float,
  "ret15_bps": float, "ret15_sd_bps": float, "ret15_z": float,
  "rv15": float, "rv15_med": float, "rv_ratio": float,
  "window_min": int }
```
**Adjectives** — `loop/state.py::adjectives(feat, product=config.PRODUCT) -> dict`, each value one word:
```
liq   ∈ {thin, normal, deep}      h = fill1k_bps·mid/(1e4·TICK_P[product]/2) (half-ticks; state.half_ticks);
                                  h > thin cut or fill1k_short (or no reading) → thin; h < a10 + 0.5 → deep, read first
                                  (config.liq_cuts(product): a10 + 0.5, a90 + 0.5 or a90 − 0.5 under LIQ_THIN_FALLBACK;
                                  SOL-USD: deep h < 1.5, thin h > 4.5; SPEC §5; v2, PREREG-v2 §3)
flow  ∈ {quiet, organic, bot_war} vol5_usd < p10 → quiet; > p90 → bot_war   (percentiles over the window's 5-min sums)
trend ∈ {dumping, flat, pumping}  ret15_z < -1 → dumping; > +1 → pumping
vol   ∈ {calm, normal, violent}   rv_ratio < 0.5 → calm; > 2.0 → violent
```
`fill1k_bps` = max(buy, sell): buy = 1e4·(VWAP of walking the asks for NOTIONAL_USD of
quote − mid)/mid, sell = 1e4·(mid − VWAP of walking the bids for NOTIONAL_USD)/mid. A side
the levels cannot fill costs inf, logged as `fill1k_bps: null` with `fill1k_short: true`.
`l1_min_usd` stays a logged feature and sets no word. 2026-09-24, decided by Alex: liq
was `l1_min_usd < NOTIONAL → thin; > 10*NOTIONAL → deep`; level 1 swung $1–$11,580 within
a minute and read thin 7/12 while a $1,000 order cost 0.44–2.02 bps (SPEC §5). v1 then cut `fill1k_bps` itself at
`LIQ_THIN_BPS` (5.0) and `LIQ_DEEP_BPS` (1.0); v2 reads h (above), and nothing in `loop/` reads
those two any more.
Exact thresholds live in `loop/config.py` and are frozen into `SPEC.md`.
**No position in the state.** Arms A and B ride one request on one state, so
the state must be identical for both; a position would differ per arm.
`state_string(adj, base="SOL") -> str` = `"{base}: liquidity {liq}, flow {flow}, trend {trend}, vol {vol}"`,
`base` = `config.base(product)` (`SOL`, `ETH`, …; capital ASCII letters, else `ValueError`).
Must contain no digit. `rule_c(adj) -> "buy"|"sell"|"hold"`:
- buy  iff trend == pumping and vol != violent and liq != thin
- sell iff trend == dumping or vol == violent
- hold otherwise

Actions are position-free intents: **buy = want to be long, sell = want to be
flat, hold = no change.** The book maps intent onto the current position.

**Questions** — `loop/prompts.py::build(frozen_a, current, base, v1=None, root=None) -> dict`
```
{ "a_action": render(frozen_a["action"], base),   # choice — config.FROZEN_A's document (prompts/v2.json)
  "b_action": render(current["action"], base),    # choice — current(tick_id)'s; identical to a_action until the first promote
  "skip":  v1["skip"],                            # noul, never rendered
  "up15":  v1["up15"],                            # noul
  "down15": v1["down15"] }                        # noul
```
`render` replaces the version's base placeholder with `base`: the whole word `SOL` in v1/v2
(`LEGACY_TOKEN`; so SOL-USD's requests are byte-identical to v1's), the literal `{BASE}` in v3 and
later (`BASE_TOKEN`). Any other product word (a base of `config.PRODUCTS` or
`config.PROBE_CANDIDATES`, whole and capitalised, or `{BASE}` in v1/v2) raises `PromptError` in
`load()` and `build()` (PREREG-v2 §1).

**Prompt versions** — `loop/prompts.py` (PREREG-v2 §8):
```
named(root=None) -> "vN"                 the one name in prompts/CURRENT (a second name, or none, is PromptError)
current(tick_id=None, root=None) -> "vN" the version B asks at tick_id (None: this minute): from named(), follow
                                         `replaces` while tick_id < that version's `activation_tick`
pending(tick_id=None, root=None) -> "vN"|None  the version CURRENT names while it is not yet active, else None
activation_of(version, root=None) -> (activation_tick, replaces)|None
table(version, product, root=None) -> {"answers": {state string: "buy"|"sell"|"hold"}, "sha": canonical sha}|None
```
A version file written by `bin/promote` during v2 carries `"activation_tick": "YYYYMMDDTHHMM00Z"`
(T0_v2 + 86,400 (E − 1)) and `"replaces": "v<M>"` together, or neither (v1, v2: active whenever
reached). A table file, `prompts/<version>.table.<product>.json`:
```
{ "version": "v2", "product": "SOL-USD", "prompt_sha": <canonical sha of prompts/v2.json>,
  "model_answered": "jev-...", "answers": {"SOL: liquidity thin, flow quiet, trend dumping, vol calm": "sell", ...} }
```
exactly the product's 81 state strings, each `buy`, `sell` or `hold`; `table()` returns None when
the file is absent and raises `PromptError` on any other shape, another version or product, or a
`prompt_sha` that is not the version file's own.
Wire format per question: `{"type": "choice"|"noul", "instructions": str, "criteria": {...}}`.
For choice, criteria keys are exactly `buy`, `sell`, `hold`. For noul, criteria
keys are exactly `yes`, `no` (this is what the live inject-screen sends and it
works; do not use true/false).

**Jev call** — `loop/jev.py::ask(state: str, questions: dict) -> dict`
```
returns { "answers": {qid: {...}}, "model": str, "input_tokens": int, "latency_ms": int, "key_path": str }
raises JevError(kind, detail)   kind ∈ {"unsigned","no-key","ledger","http-4xx","http-429","http-5xx","timeout","parse"}
                                ("unsigned": PROTOCOL.md's signature line is unfilled, PROTOCOL §3.11; the tick adds
                                 "watchdog" and "unexpected" of its own, SPEC §2)
```
- `key()`: `$TYPESAFE_API_KEY_LOOP`, else `~/.secondbrain-secrets/typesafe-api-key-loop`,
  else `$TYPESAFE_API_KEY`, else `~/.secondbrain-secrets/typesafe-api-key`. Log
  WHICH path was used (name only), never the value.
- Body: `{"model": config.MODEL, "state": state, "questions": questions}`.
  Headers: `Authorization: Bearer`, `Content-Type: application/json`. Timeout 20 s.
- **Ledger before send, fail closed:** append one row to `data/sends.tsv`
  (`utc  source  state_chars  q_chars  sha12  paths`, source=`jev-paper-loop`)
  BEFORE the request; if the append fails, do not send, raise `JevError("ledger")`.
- Retry: at most ONE, only on 429 (honour `Retry-After`, cap 5 s) or 5xx/timeout,
  after 1.0 s. Never on 4xx other than 429. 401/403 → raise; the caller writes HALT. A 3xx is
  never followed (the bearer key would go with it) and is raised as `http-4xx` with its
  status, no retry. If the retry's ledger append fails, attempt 1's kind is raised, not
  `ledger` (attempt 1 was billed). (2026-09-28)
- Response: `answers[qid]` for choice is `{"choice","probabilities","confidence"}`;
  for noul is `{"noul"}`. If `resp["model"] != config.MODEL`, still return but the
  caller logs it as drift.

**Rule columns** — `loop/rules.py::columns(action_answer, skip_answer, up15, down15) -> dict`
```
{ "argmax": choice,
  "c50","c70","c85","c99": choice if confidence >= k else "hold",
  "c50v","c70v","c85v","c99v": same, but "hold" if skip.noul >= 0.5,
  "pbuy60": buy if p.buy>=0.6, sell if p.sell>=0.6, else hold,
  "noultail": buy if up15.noul >= 0.99, sell if down15.noul >= 0.99, else hold }
```
Arm C is the single column `rule_c`. When answers are null (dry mode, error), every
model column is `null`.

**Row** — one line of the product's decision log per tick (`config.store(product).decisions`:
`data/decisions.jsonl` for SOL-USD, `data/<PRODUCT>/decisions.jsonl` otherwise), append-only:
```
{ "v": 1, "tick_id": "YYYYMMDDTHHMM00Z", "ts_rx": ISO ms, "mode": "live"|"dry",
  "venue": "coinbase", "product": <config.PRODUCTS>, "cadence_s": 60, "horizon_s": 900,
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
`tick_id` is `ts_rx` floored to the minute. A tick that fails before the feed
still writes a row with `absence` set and everything else null it can't fill.
v2 (PREREG-v2 §10, SPEC §2): `product` is the loop's (`JEVLOOP_PRODUCT`); `prompt_a` is
`config.FROZEN_A` (`v2`; v1 rows carry `v1`); `prompt_b` is `prompts.current(tick_id)` for the
row's own tick; `table_sha` is `prompts.table(prompt_b, product)`'s sha whenever the tick read
it (dry and halt rows included), null when absent or refused; `columns.d` is that table's answer
for `state` on a row that reached step 7, null otherwise or when there is no table or no such
state. `v` stays 1; a v1 row has no `table_sha` and no `columns.d`, and every reader treats the
missing keys as null.

**Outcome** — `loop/outcomes.py::join(rows, horizon_s=900) -> dict[tick_id -> outcome]`
```
{ "mid_h": float|null, "ret_h_bps": float|null, "label": "up"|"down"|"flat"|null,
  "absence": null|"gap" }
```
mid_h from the priced row whose `ts_rx` is NEAREST t+h within ±30 s (half a cadence;
ties → the earlier row); `ret_h_bps = 1e4*ln(mid_h/mid_t)`; label with a ±5 bps dead
band. Anything else is `gap`, never the wrong row. Ties are judged in whole milliseconds
and the picked row is strictly after t. When two rows share a `tick_id` (a double fire, a
dry row beside a live one) the live decision speaks for the tick, then any other priced
row, then an unpriced one; equal ranks keep the first in file order (`outcomes.rank`,
2026-09-28). (Was "first row in [t+h, t+h+90 s]"
until 2026-09-24: ts_rx jitter made that pick the t+16 row whenever the t+15 row
landed a millisecond earlier in its minute than t did.)

**Book** — `loop/book.py`, pure functions:
```
apply(pos: dict|None, intent: str, bid, ask, fee_bps) -> (pos', fill|None)
   pos = None (flat) | {"qty": float, "entry": float}
   buy when flat  → open: qty = NOTIONAL/ask, fee = NOTIONAL*fee_bps/1e4
   sell when long → close at bid, fee = qty*bid*fee_bps/1e4 (the filled value; SPEC §10)
   buy when long, sell when flat, hold → no-op (fill None)
replay(rows, outcomes, arm: "a"|"b"|"c"|"d", column: str, fee_bps) -> {"equity": [...], "trades": [...], "pnl_bps_per_tick": {tick_id: float},
                                                                    "position": {tick_id: qty}, "forced_hold": int}
   mark-to-mid each tick; pnl per tick is computed DIRECTLY (carried qty*(mid_t - mid_prev); open qty*(mid_t - ask) - fee;
   close qty*(bid - mid_prev) - fee), in bps of NOTIONAL, so two arms with the same position give d_t == 0.0 exactly (SPEC §10)
paired(rows, outcomes, x, y, column, fee_bps) -> [ (tick_id, d_t) ]   d_t = pnl_x - pnl_y
at_cadence(rows, c: int, t0: epoch) -> rows   PREREG-v2 §4: each c-block's decision row as it is, every other answered
   row of the block a copy with every intent `hold` (book._held); feed the result to replay/paired unchanged
decision_rows(rows, c, t0) -> {block j: row}  the first row of each block (tick_id, then ts_rx) replay would not force a hold on
```
Arm `d` reads `columns.d` and has the one column `argmax` (`book.D_COLUMN`; any other raises); a
null `columns.d` on an otherwise answered row is a hold for D alone, counted in its
`forced_hold`; every forced hold of SPEC §10 applies to D too. Fee constants come from
`config.FEE_BPS_COLUMNS` = (0, 2, 10, 25, 50, 90), ascending; the primary is
`config.FEE_BPS_PRIMARY` = 0.0, gross, the H1 cell; the venue's own taker fee is
`config.FEE_BPS_VENUE` = 90.0, verified in-account 2026-09-27, its source in
`FEE_BPS_VENUE_SOURCE` (v1: 60/120 and 120.0, UNVERIFIED). (2026-09-24, decided by Alex: the
primary was the venue's taker fee.)

**Stores and switches** — `loop/config.py` (PREREG-v2 §2), each computed at call time:
```
store(product) -> Store(decisions, sends, lock, heartbeat)   data/... for SOL-USD (v1's paths), data/<PRODUCT>/... otherwise
pause(product) -> "data/PAUSE.<PRODUCT>"      loop_product(environ=None) -> JEVLOOP_PRODUCT, or "SOL-USD" unset
base(product) -> "SOL"                        liq_cuts(product) -> (deep_below, thin_above) in h
HALT, EXCLUSIONS_V2 ("data/exclusions-v2.tsv"), LOOKS ("data/looks.tsv"): at REPO/data whatever the product
```
A product outside `config.PRODUCTS` raises `ValueError` from `store`, `pause` and `liq_cuts` (never a
path), and a `JEVLOOP_PRODUCT` outside it from `loop_product`; `base` only splits the id.

## 3. The tick (`loop/cycle.py`)

One tick is one product's: `JEVLOOP_PRODUCT` names it (unset: `SOL-USD`; a value not in
`config.PRODUCTS` exits 2 before any directory is made), and every file below that is not
`data/HALT` or `data/PAUSE.*` is that product's (`config.store(product)`). `--every-product` ticks
every product in sequence in one process under one 50 s watchdog budget a round (a product
reached with less than a second left is not ticked that minute, no row); with `JEVLOOP_PRODUCT`
set it is a usage error (exit 2).

Order, every time:
1. **Guards.** Resolved repo path must not start with either prefix in
   `config.FORBIDDEN_PREFIXES` → exit 3. `data/HALT` exists (the one global stop) → this tick is
   HALTED. Today's spend (summed over EVERY product's decision log, PREREG-v2 §2; sum over today's rows of the billed tokens: the logged
   `jev.input_tokens` when positive, else `config.JEV_TOKENS_IF_UNKNOWN` = 2000 for a
   live row that reached the model, SPEC §13.3; × `config.USD_PER_MTOK` / 1e6) ≥
   `config.DAILY_SPEND_HALT_USD` → write
   `data/HALT` with the reason; this tick is HALTED. A log that exists but cannot be read (a
   0200 mode, a directory, EIO), or a count, or today's sum of them, past a float's range,
   counts as over the limit: the guard cannot count, so it trips (2026-09-28); a missing log
   is $0 (`config.DAILY_SPEND_HALT_USD` = 0.25 × the number of products). `data/PAUSE.<PRODUCT>`
   exists → this tick is HALTED too, for its product only (PREREG-v2 §2: written by hand, "prereg:
   3 bad days"; the spend guard and the nightly ignore it; observation and t+h outcomes go on).
   `fcntl.flock` on the product's `loop.lock` (`data/loop.lock` for SOL-USD) non-blocking; if held →
   `absence: "lock"`, exit 0.
   **HALT stops sends only** (PROTOCOL §3.8, SPEC §13.2): a HALTED tick runs
   steps 2–4 as usual and then writes its row with `absence: "halt"` in place
   of steps 5–7 — no ledger row, no send, no body printed — and exits 0. The
   feed, `rule_c`, the marks and the t+h join therefore survive a HALT. A
   failure in steps 2–4 keeps its own absence: `absence` names the first step
   that did not happen.
2. **Feed.** `snapshot()`. On `FeedError` → row with `absence: "feed"`, exit 0.
3. **State.** features → adjectives → state string → rule_c.
4. **Prompts.** `current(tick_id)` for this tick; load v1, `config.FROZEN_A` (v2) and it; shas;
   questions rendered for the product's base. Then arm D's table, `prompts.table(current,
   product)`: `table_sha`, and its answer for the state, kept for step 7. A table that does not load
   (absent, refused, or any other exception short of the watchdog and SIGTERM) leaves `table_sha`
   and `columns.d` null, is said on stderr, and costs nothing else.
5. **Dry?** `--dry` → write the row with `answers: null`, `columns: {a:null,b:null,d:null}`,
   `mode: "dry"`. No ledger row, no send. This is the free thing, run first.
6. **Ask.** `jev.ask()`. On `JevError` → row with `absence: "jev"`, `jev.error` set.
   On 401/403 also write `data/HALT` ("key rejected"). Any other exception once
   the send has begun → `absence: "jev"`, `jev.error: "unexpected"` (the request
   may have left, so the spend guard must charge it; `guard` rows cost $0).
7. **Columns.** `rules.columns()` for a and b; `d` the table's answer from step 4.
8. **Write** the row to the product's log (atomic append: build the line, one `write`, `flush`,
   `fsync`; a line that follows a torn one starts with a newline).
9. **Heartbeat.** touch the product's heartbeat (`data/heartbeat` for SOL-USD) with `ts_rx`.

`--once`: one tick, exit. `--forever`: loop, sleeping until the next wall-clock
minute boundary (compute from `time.time()`; do not accumulate drift). A 50 s
watchdog around each tick (`signal.alarm`; macOS has no `timeout`). SIGTERM →
finish the current write, release the lock, exit 0. Every exit path is exit 0
except the path guard (3) and a usage error (2).

The tick never computes a position. Positions are replayed from the log.

## 4. Report (`loop/report.py`, `make report`)

Print, plain text, in this order:
1. Health: rows, live rows, absence by reason, outcome fill %, jev error %,
   mean/p95 latency, input tokens and $ to date, distinct `model_answered`, drift count,
   `prompt_b` versions, the key that answered (and a SHARED KEY warning, PROTOCOL §3.6),
   the realised horizon and the isolated skipped minutes, HALT present or absent, and the
   per-day table of PREREG §8 stop rule 3 (T0-anchored `dNN` with `--t0`; every day from d01
   to the log's last tick, capped at the clock so a row stamped in the future closes no day, a closed day with no live row flagged NO LIVE ROWS, never BAD by
   code: its fill is 0/0 and the exclusion is Alex's call).
2. Adjective occupancy per dimension; flag any word > 95% (arms cannot disagree
   on a constant).
3. Test-retest: on rows where `prompt_a_sha == prompt_b_sha`, agreement rate of
   `a_action.choice` vs `b_action.choice`, and mean |Δconfidence|. This is Jev's
   determinism, measured for free.
4. Agreement of column `a.argmax` with `rule_c` (does the model follow the rule it was given).
5. For each pair (B−C, A−C, B−A) × each column × each fee: n ticks, n ticks where
   the arms are on different SIDES (long vs flat) into or out of the tick
   ("disagreement ticks"; a quantity difference between two longs is not one),
   mean d_t, mean d_t on disagreement ticks, hit rate on disagreement ticks,
   trades/day each side. Primary cell is marked; the venue fee (`FEE_BPS_VENUE`, 90 bps since
   the v2 build, verified; v1's 120 UNVERIFIED), its source and a per-arm line at it are printed
   beside the table as the realistic-cost column (2026-09-24, decided by Alex). PREREG-v2 adds D − B
   and D − C at argmax only (`report.PAIRS`, on rows that carry `columns.d`). Beside the all-ticks figure,
   PREREG §3's statistic: 900 s blocks anchored at T0 (`--t0`; else at the log's
   first tick), n blocks, mean S_k, disagreement blocks and their share, mean S_k
   on them. `--t0` cuts the rows to [T0, T0 + 28 d) before any replay, so every
   arm starts flat at T0. (This replaced an every-15th-tick d_t, which PREREG §3
   says is not the statistic.) Under the H1 cell, the same cell by arm B's prompt
   version (the rewrite's iterations; 2026-09-28, approved by Alex): per contiguous stretch
   of one version (a version that comes back after a rollback is '<version> #2'), its
   first and last tick, ticks, blocks from its first tick's to its last tick's, mean
   S_k, disagreement blocks and mean S_k on them. Descriptive and not in PREREG;
   withheld with the rest of §4-§7 on sample rows until day 28.
6. H2, the direction lean (PREREG §5; 2026-09-24, decided by Alex: H2 moves
   to the direction probabilities): lean_t = `up15.noul − down15.noul` (the
   `v1` nouls, shared by A and B) against `ret_h_bps` of the outcome join
   (SPEC §11). Units: the first live row (`mode` live, `absence` null) of each
   900 s block anchored as in §4.5 (`--t0`, else the log's first tick; `--t0`
   cuts to the sample first); a unit whose outcome is a gap or whose noul is
   missing drops its block, with the drops counted by reason. Printed: Pearson
   r over the units (PREREG §5's statistic) with Spearman ρ (average ranks)
   beside it; r and ρ over every live tick with a pair (overlapping horizons,
   descriptive); Brier of `up15.noul` vs 1[label = up] and of `down15.noul` vs
   1[label = down], each beside the base-rate Brier (predicting the sample
   frequency p, = p(1 − p)), for units and every tick; counts of `up15` and
   `down15` in each measured tail (≥ `NOUL_TAIL` 0.99, < 0.15); and the
   `trend` word as a no-model comparator (review, 2026-09-24: Jev sees only
   the four words and lean tracked this one at r 0.99 on the shakedown,
   PREREG §5), trend = +1 `pumping`, 0 `flat`, −1 `dumping` from the row's
   `adj.trend`, for units and every tick: r(lean, trend), r(trend,
   `ret_h_bps`), and r(lean, `ret_h_bps`) within `trend = flat` with its n.
   Any r or ρ with fewer than two pairs, or with no variance on either side,
   prints `undefined (<reason>)`, never a number and never a crash. Pearson,
   Spearman and Brier are written out in stdlib; no interval is computed.
7. Arm A's choice confidence vs rule-matching, not outcomes (descriptive; the
   old H2 table): for confidence bins [0.5,0.7,0.85,0.99,1], P(argmax correct)
   where correct = buy&up or sell&down or hold&flat, and beside it the share of
   the bin where `a.argmax == rule_c`, under one line saying why it is not H2
   (`v1`'s action criteria restate the rule, so the confidence reads how well
   the answer matched it; nearly every answer is hold, correct only when
   |ret_h| < 5 bps).
`--health` prints §1–§3 only and neither computes nor prints §4–§7: PREREG
§8.4's day-14 look is `python3 -m loop.report --health --t0 <T0>` (`make health` is
`--health --sample`, T0 read from PREREG §11). Since 2026-09-28 a run without
`--health` on rows of the sealed sample prints §1–§3 and a WITHHELD line until
T0 + 28 d (2026-10-23 21:40Z); the T0 for that is read from the repo's own PREREG.md
whatever `--prereg` says; `--unblind` prints §4–§7 and says so on stderr.
No p-values in `make report`. Inference lives in PREREG.md and is run once: `loop.inference
--sample` refuses (exit 3) before T0 + 28 d on any log holding a row of the repository's
sealed sample, whatever `--now`, `--t0` or `--prereg` say (a copy of the live log is the live
log), and `--pre-t0` cuts at the repository's seal too (2026-09-28).

**PREREG-v2 (without `--log`).** `loop.report` reads every product's store (`config.store(p)` for
`p` in `config.PRODUCTS`) and prints the same seven sections over them: §1–§3 per product and
pooled (HALT once, each `data/PAUSE.<PRODUCT>`, each product's T0_v2-anchored day table; stop rule 3
recomputed from the log, which governs, beside `data/exclusions-v2.tsv` verbatim with every
disagreement named; PREREG-v2 §9.4's void once every product's d28 has closed); §4 A's argmax vs
`rule_c` and arm D's Agreement(p, v) with denominators, null counts and PREREG-v2 §6's readings;
§5 the paired book at the minute cadence (B − C) and at each `config.CADENCES` through
`book.at_cadence(rows, c, T0)`, each product replayed from flat at T0 over every row, excluded
days included, its excluded days' blocks dropped after, per product and pooled over the time
block, `gap_blocks` per cadence, trades/day per arm and product, D − B and D − C at argmax only,
and after each replay cadence PREREG-v2 §6's fee arithmetic at argmax (E_X,p at 0 and 90 bps over
kept days, f*_X for A, B, C, D and buy-and-hold, pooled and per product, the 30-day volume, the
tiers of §12's table, read by `dash.read_fee_tiers`, whose taker is below f*_X, ERRATA's 2026-09-27
reading standing in while §12 is blank, and each pair's Δ and f*_XY);
§6–§7 per product. §4, §6, §7 and trades/day read only the rows of kept product-days of non-void
products (PREREG-v2 §2, §9.4); §1–§3 read every row, since they judge the days. `--since` cuts rows
before the replay, so with `--t0` each product is replayed from flat at its first row on or after
it, and the blocks that start before it are left out of n and every mean. Every product's
days close on the latest tick any product's log has reached.
PREREG-v2's withholding sits beside v1's in both forms: T0_v2 is read from the repository's
PREREG-v2.md §12 (`dash.read_t0_v2`) whatever the flags say, and §4–§7 are withheld while the
clock is before T0_v2 + 28 d and a row read is in [T0_v2, T0_v2 + 28 d); while §12's T0_v2 is blank
(or malformed) they are withheld over every row carrying the v2 `spec_sha` (`dash.v2_spec_sha`).
Every `--unblind` is a look, whether or not it lifts a withholding: `loop/looks.py` appends (UTC,
argv, HEAD) to `data/looks.tsv` before anything is printed, and a look it cannot record is refused
(exit 2). `--sample` without
`--log` reads T0_v2 from §12. `make status` and the dash show every store, HALT (REPO/data) and
each PAUSE, and the pending prompt version on its own line; still health only: neither A's
agreement with C nor arm D's agreement, both answer-level and withheld with §4–§7 until
T0_v2 + 28 d (PREREG-v2 §6; `HEALTH_N` stays 3).

**PREREG-v2's inference (`loop/inference_v2.py`, `make results`).** `python3 -m loop.inference_v2 --sample
[--out RESULTS-v2.md] [--accept-pending] [--no-seal]` reads every product's store once (each log's sha and byte length
printed) and runs once, at day 28. It refuses (exit 3) while PREREG-v2.md §12's T0_v2 is blank or malformed, before
T0_v2 + 28 d, and while the seal check fails (`inference_v2.seal`: the annotated tag `prereg-v2-seal` is an ancestor of
HEAD and `bin/seal-check --since prereg-v2-seal` exits 0; PREREG-v2 §10, §13) unless `--no-seal` (`make results
NO_SEAL=1`), which the header and §0 record, all before any log is opened; and while d28 is open (no log has reached T0_v2 + 28 d + h + 30 s, where
`report.days_table` closes the day) unless `--accept-pending` says the logs stopped, a flag itself refused before any
log is opened until a minute after the minute that closing tick falls in (before then no running loop could have
written it); after reading, it also refuses
(exit 3) when the sample's rows carry more than one `spec_sha` (PREREG-v2 §13: exactly one), unless `--no-seal`,
recorded likewise; no sample row at all is a void block, not a refusal; `--out` never overwrites. The
clock and R are `main`'s arguments for the tests, not flags, and T0_v2 is §12's and nothing else. It prints
RESULTS-v2: §0 (the seal check with bin/seal-check's output and `git diff -U0 prereg-v2-seal HEAD` verbatim,
`data/looks.tsv` verbatim, the set of `spec_sha` over
the sample's rows, each product-day's `prompt_b` set with every product-day holding two or more values named, PREREG-v2
§8); stop rule 3 recomputed per product, which governs, beside `data/exclusions-v2.tsv`, and void; H1
and family F on PREREG-v2 §4's pooled series (`pooled`: the same sums, in the same order, as
`report.cadence_table`'s cells), each cell with its own `random.Random(seed)`, v1's draw (`inference.resample_indices`)
and the bound `sorted[ceil(alpha R) - 1]` with alpha a `fractions.Fraction` (`alpha_rank` refuses a float); F4
withdrawn under §9.2's NO PROMOTION; stop rules 1–2 and PREREG-v2 §11's reading; §7's figures as measured; and,
descriptive, `report.cadence_table` at PREREG-v2 §6's fee columns (`inference_v2.FEE_COLUMNS`, passed as its
`fees`), arm D's and A's agreement and the direction probabilities per product. v1's `loop/inference.py` is unchanged.

## 5. Nightly

**Which version a reader asks (PREREG-v2 §8; this contract amended for v2).** Every reader calls
`prompts.current(tick_id)` with the tick it describes: the loop its own tick, the digest each
row's tick, `policy_table` and `bin/promote` now, dash and status now, with `pending(now)` shown on
a line of its own. So a promotion written on day E − 1 changes nothing before its
`activation_tick`, every row and every c-block of a product-day carries one `prompt_b`, and a
pending version is invisible to the digest and to `policy_table` (both test it). A hand edit of
CURRENT after T_first_v2 is a deviation.

`nightly/digest.py [--date YYYY-MM-DD] [--data DIR]` → `data/digest-<date>.md` (PREREG-v2 §8): the UTC day just
closed, over every product's log (where `config.store` puts it, under `--data` when given), only the rows carrying
this tree's SPEC sha (the v2 spec_sha: a switch-day digest mixes no v1-code rows in). One summary line per product
and one pooled (each arm's trades and PnL the mean over the products, as PREREG-v2 §4 pools; the counts summed):
ticks, absences, outcomes joined, occupancy, trades and paper PnL per arm (A, B, C) at 0 bps
(direction), at the venue's verified maker (50) and taker (90), the versions B was read from, and B's disagreement
count. Every arm-B figure comes from rows whose `prompt_b` is the version `prompts.current(tick_id)` names for that
row's tick (a promotion inside the day splits B's rows at its activation; a row asking any other wording is counted,
not read; a pending version is never reached). Up to 25 arm-B disagreement rows over the products (state, choice,
confidence, ret_h_bps, label), highest confidence first; per product the 81-state table (live rows seen, B's buy /
sell / hold, mean ret_h_bps and up / down / flat at the 15-minute join); the CURRENT `action` question (what
`current()` names now) verbatim with its base token written `{BASE}`; prompt_a's and each prompt_b's sha. Never the
key, never the raw log, never the features. Exit 4 when no product has a row of this SPEC that day. Its bytes on a
fixed three-product day are held by `tests/golden/digest-v2.md`.

`nightly/propose.sh` (as it runs; the header of the script is the authority): the slow model's id first, from
`nightly/slow_model.py`'s `MODEL_ID` alone (PREREG-v2 §8; blank until §8 names it, and then the night fails there,
no digest, no call, no send); the digest (`nightly.digest --date <date> --data <root>/data`; exit 4 = nothing to
read, the night ends with one log line and no Claude call); then the token read from
`~/.secondbrain-secrets/oauth_token` into `CLAUDE_CODE_OAUTH_TOKEN` for the ONE call and unset after, never on argv,
never logged; the call itself, in an empty temporary working directory (the CLI auto-loads no CLAUDE.md from the
repo; the night fails if a CLAUDE.md, CLAUDE.local.md or .claude sits in any ancestor of it) and with
`CLAUDE_CONFIG_DIR` a fresh `mktemp -d` outside the repo, made and removed each night, for `--version`, the call and
`answered_model.py`: the night fails, sending nothing, if that directory holds CLAUDE.md, CLAUDE.local.md, rules/,
skills/, agents/ or plugins/ when the call is due, and logs "user memory not loaded" (PREREG-v2 §8; v1 loaded
`~/.claude/CLAUDE.md` and logged its sha). After the call `nightly/answered_model.py` reads the model that answered
from the CLI's transcript in that directory and the night logs it beside the requested id (`claude model <id>`, or
`unrecorded`) and passes it to the table's header:
`caffeinate -i python3 nightly/capped.py 2700 -- claude -p "$(cat nightly/PROMPT.md)

$(cat data/digest-<date>.md)" --model <MODEL_ID> --tools "" --restricted --strict-mcp-config --settings
nightly/settings.json --output-format text` (`capped.py`: 45 min of AWAKE time, monotonic, exit 124 when it fires;
the command runs in a process group of its own, which the cap ends, which ends when the command exits, and to which
SIGTERM/SIGINT/SIGHUP/SIGQUIT are passed on; the CLI's version, the temp cwd and the config dir are logged); extract
exactly one fenced ```json block; validate it is `{"candidates": [ {"instructions": str, "criteria":
{"buy","sell","hold"}} , ... ]}` with 1–3 entries; discard, one log line each, a candidate with a digit (PROMPT.md rule
4) or a product word other than `{BASE}` (rule 9), `policy_table.refused`, keeping the rest (none left: the night
fails); write `proposals/<date>.json` (refused, before the
digest and any call, when `proposals/<date>.json` or `.md` exists; `--dry`, the tests' form, needs `--root DIR`
outside the repo, else a usage error, exit 2). Then `policy_table.py proposals/<date>.json` (PREREG-v2 §8) asks Jev,
for every product, each candidate AND the CURRENT action question on the product's 81 synthetic state strings
(`state_string(adj, base)`; one request per state carrying every wording, each rendered for the product's base:
81 a product, ~$0.005 each), CURRENT being what `prompts.current()` names now (a pending version is invisible), and
writes `proposals/<date>.table.json` (every wording's 81 answers per product, the questions as sent, the proposal's
sha, CURRENT's version and sha; gitignored) and `proposals/<date>.md` from it: its `table sha256` line (the json's),
pooled counts first, then per product the 81-row tables (a candidate's with CURRENT's answer and whether the state
moved), the diff of each wording vs CURRENT, the counts of states where it differs from CURRENT and from rule_c,
where those changes land, and the sha256 of the proposal json (`bin/promote` checks both shas). A candidate naming a
product other than `{BASE}` is refused before any send; a proposal with no candidates is a CURRENT-only table (the
run a version's own tables come from). `python3 -m nightly.policy_table --fill proposals/<date>.table.json`
(attended) re-sends only the unanswered states, with the questions the night sent, writes their answers into the
same file and its new sha into the re-rendered .md; a json the .md does not vouch for is refused. Last, on every
night whatever happened, `loop.dash` rebuilds `data/dash.html` from every product's store. Every failure is one line
in `logs/propose.log` and exit 0 (launchd throttles a failing job); the night also writes `data/digest-<date>.md` and
`logs/claude-<date>.{txt,err}`. **It scores nothing against any logged outcome.** The nightly never touches
`prompts/`. While `data/HALT` exists it sends nothing (propose.sh skips the table, and `policy_table.py` refuses
again, before every send); a 429, three transient failures in a row, or three failures of any kind in a row end its
night (and every later product's sends); a 401/403 writes `data/HALT`; the night's deadline is 900 s a product.
`nightly/trial-night.sh` is PREREG-v2 §8's trial night before the draft tag: a real call through propose.sh with
`--root` a temp dir outside every checkout holding a synthetic three-product log (and data/HALT: no Jev send), printing
only the exit code and the FAIL, claude exit, claude model and "user memory not loaded" lines, then PASS or FAIL. The
products are §2's (`dash.read_products_v2`, the Products line): until that line is filled and config.PRODUCTS is its
set the script prints FAIL and makes and calls nothing, and PASS needs the digest's summary line for every one of them
(its "digest products" line). Beside every verdict a NOT SHOWN line says it cannot show whether `--settings` still
applies under the fresh config dir (§8 asks it; with no tools the settings file's deny list changes nothing the run
records): the author settles that before the draft tag.

`bin/promote proposals/<date>.json <k> --reason "<one line>"` (PREREG-v2 §8): copies candidate k to
`prompts/v<N+1>.json` (the other three questions carried from v1 unchanged) with `activation_tick` = T0_v2 + 86,400
(E − 1) and `replaces` = the version active when it ran, then candidate k's column of the proposal's `.table.json` to
`prompts/v<N+1>.table.<product>.json` for every product, then the new name to `prompts/CURRENT` (CURRENT.tmp renamed
over); prints the diff and the commit line (the reason, the states moved per product). A promote that cannot finish
removes what it wrote (prompts/ as it was, no version file left to count as a promotion). It refuses without a tty, on
a dirty `git status`, without the annotated tag `prereg-v2-seal` at or before HEAD, while PREREG-v2.md §12's T0_v2 is
blank, while a version is pending, off the schedule (run on day E − 1 for an effective day 8 ≤ E ≤ 22, at least 7
days after the block's last promotion, at most three, and not within 600 s of the activation), unless the committed
.md vouches for the json and the .table.json and the table was scored against the version CURRENT names, unless
candidate k answered 81/81 on every product, for a candidate that moves 0 of 81 states on every product, and for a
product word other than `{BASE}`. `bin/promote --table-only proposals/<date>.json` (attended, clean tree, no schedule
or T0_v2) copies the CURRENT column into `prompts/v2.table.<product>.json` for every product, refusing unless the
table's CURRENT sha is `prompts/v2.json`'s, whatever CURRENT names (a promoted version's tables are its promotion's);
it replaces an existing table only saying so. It refuses once a `prereg-v2-seal` tag exists, and after the annotated
`prereg-v2-draft` tag it rebuilds once only, and only for a Jev version other than the one the pinned tables name
(PREREG-v2 §8's once-only rebuild at the switch). Neither form sends
anything. A person runs it. Nothing else writes `prompts/`.

## 6. Tests (`tests/`, `python3 -m unittest`)

Fixtures: ONE real Coinbase snapshot set (book + 350 candles +
trades), committed under `fixtures/`, with the fetch command in a README (the book
re-recorded with `limit=100` on 2026-09-24, decided by Alex; the README says when and
why). Tests must pass offline.
- state: the book walk (exact VWAP on a hand-built book, each side alone, the max, a side
  that cannot fill → null/short → thin); every adjective boundary (just below / at / just above); rule_c truth
  table over all 81 states; state string has no digit and exactly the format.
- rules: each column against hand-built answers, including the veto and noultail.
- book: open / close / no-op sequences; fee arithmetic at two constants;
  paired d_t is 0.0 when positions match.
- outcomes: a 20-minute gap yields `gap`, never the wrong row; the dead band.
- cycle: path guard exits 3 under a forbidden prefix (monkeypatch the resolved
  path); HALT file → absence halt; spend over limit writes HALT; `--dry` writes
  a row with answers null and no sends.tsv line (use a temp `data/`).
- jev: with a mocked `urlopen`, the ledger row exists BEFORE the request is
  made; an unwritable ledger raises and nothing is sent; 401 raises `http-4xx`.
- prompts: sha is stable; `CURRENT` = v1 gives identical a/b questions.
- report: every §4 section from a synthetic log, key numbers by hand. H2 (§4.6,
  2026-09-24): Pearson r and Spearman ρ by hand on a small log (ties at mean
  ranks); a perfectly informative lean gives r = 1; a constant lean gives
  `undefined (no variance in lean)` and the whole report still renders; Brier
  and base-rate Brier by hand; tail counts at their edges; `--t0` cuts the
  units to the sample.

v2 (PREREG-v2 §10's tests bullet and each change's own; `tests/synth.py` writes a synthetic
log per product, v1-era and v2-era rows, with a cadence knob):
- config and cycle: with `JEVLOOP_PRODUCT` unset every v1 path (`data/decisions.jsonl`,
  `sends.tsv`, `loop.lock`, `heartbeat`) and the `RULE_C` pin are unchanged; a product outside
  `PRODUCTS` exits 2 before any directory; each per-product table holds exactly `PRODUCTS`;
  `data/PAUSE.<X>` stops only X's sends while X's observation and t + h outcomes continue, and
  `data/HALT` stops every product and the nightly; the spend guard sums every product's log;
  `--every-product`'s budget; the row carries `table_sha` and `columns.d`, and a table that fails
  costs D alone.
- state and prompts: `liq` at and around each product's cuts in h, the thin fallback; the state
  string's base; each product's rendered A differs from SOL's only in the base token, SOL's is
  byte-identical to v1's; a product word is refused; `current(tick_id)` follows `replaces` for as
  many steps as the tick needs and refuses a loop; a pending version is invisible to the digest
  and to `policy_table`; every added product's table strings begin with its own base.
- book: `at_cadence`'s decision row and hold, shared by every arm; D's one column; a null
  `columns.d` a hold for D alone.
- report, dash, status: withholding of §4–§7 with no flags, with `--t0` T0_v2 and with
  `--since`, over a three-product synthetic log; every `--unblind` a line in `data/looks.tsv`;
  dash and status print health only, neither A-agreement nor D-agreement.
- inference: `tests/test_invariants.py` holds the readers to independent transcriptions of
  PREREG-v2 §4–§6 (H1's seed 20261023 at `sorted[249]`, F's 20261024–20261027 at `sorted[62]`, L = 4
  units, R = 10,000, each cell's bound on a fixed series hard-coded, a golden series on which
  `sorted[61] ≠ sorted[62]`); `tests/test_report_v2.py` replays an excluded day between two kept
  days with arm positions that differ across it; `test_inference_golden` stays at v1's seed for
  v1's readers.
- `bin/promote`: refuses with §12's T0_v2 blank, at E < 8, at E > 22, at spacing < 7, within
  600 s of the activation, on a second pending version and without the `prereg-v2-seal` tag;
  `--table-only` refuses a table whose CURRENT sha is not `prompts/v2.json`'s.
- nightly: the digest's bytes on a fixed three-product day (`tests/golden/digest-v2.md`);
  `policy_table` per product, its `.table.json` and `--fill`; `propose.sh`'s `--model` and fresh
  `CLAUDE_CONFIG_DIR`; the per-product loop plists and the one-process plist.
- documents: `tests/test_spec.py` holds SPEC v2 to the code (the row's keys, §5's per-product
  table, §10's fees and verified row, §14's names); `tests/test_contract.py` holds this file's v2
  interfaces to the code; `tests/test_errata.py` reads ERRATA.md as `bin/seal-check` does, and
  every SPEC and PREREG row folded; `tests/test_frozen.py` pins by sha SPEC v2, this file,
  PREREG-v2.md, `nightly/PROMPT.md` v2, the sources of `nightly/digest.py` and
  `nightly/policy_table.py`, the call's shape (`nightly/propose.sh`, `nightly/settings.json`,
  `nightly/capped.py`; PREREG-v2 §8), `prompts/v1.json` and `prompts/v2.json` (and one v2 table per
  product once they exist), and by value every SPEC §14 constant and the inference constants; v1's SPEC sha
  resolves with `git show prereg-v1:SPEC.md`. `tests/test_products_added.py` runs the suite with
  three products; `tests/test_seal_check.py` runs `bin/seal-check` on scratch repositories.

## 7. Style

Match `~/Projects/JEV/bin/jev`: dense, explains WHY in comments with the
measured number that justifies it, no framework, no cleverness. Module
docstring says what the file may and may not do. Every constant that defines
arm C or the alphabet is named and lives in `config.py`.

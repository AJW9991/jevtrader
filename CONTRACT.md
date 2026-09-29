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

## 1. Toolchain and layout

- `/opt/homebrew/bin/python3` (3.14). **Standard library only.** No pip.
- Never `import` anything from `~/Projects/JEV/bin/jev` (it exits at import
  without a key). Copy the ~60 lines you need; cite the source lines.
- Files are owned by exactly one builder. Touch only your files.

```
jev-paper-loop/
  CONTRACT.md            this file
  PROTOCOL.md            the carve-out Alex signs (drafted; not a builder's file)
  SPEC.md                row schema, alphabet, thresholds, arms — frozen; its sha is in every row
  PREREG.md              the 28-day test and stop rules — sealed by git tag before the first v2 tick
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
  launchd/com.alexward.jevloop.loop.plist  launchd/com.alexward.jevloop.nightly.plist
  prompts/v1.json        frozen (written)   prompts/v2.json (promoted 2026-09-26)   prompts/CURRENT  → "v2" (one line)
  fixtures/              one recorded Coinbase snapshot set, committed
  tests/                 unittest, stdlib; tests/fixture_prompts.py pins a v1-only prompts root and tests/fixture_prereg.py a PREREG.md (dash.PREREG_PATH) (no test depends on what the live prompts/CURRENT names; one checks it builds, whatever it names)
  data/   logs/   proposals/   (gitignored except proposals/*.md, data/exclusions.tsv, data/exclusions-v2.tsv and data/looks.tsv, versioned when they exist)
```

## 2. Data types (plain dicts; keys exactly as written)

**Snapshot** — `loop/feed.py::snapshot(product) -> dict`
```
{ "ts_rx": ISO8601 UTC ms (this machine's clock, the decision timestamp),
  "product": "SOL-USD",
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
Raises `FeedError(str)` on any HTTP/parse failure, fewer than 300 closed candles, a
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
**Adjectives** — `loop/state.py::adjectives(feat) -> dict`, each value one word:
```
liq   ∈ {thin, normal, deep}      fill1k_bps > LIQ_THIN_BPS (5.0) or fill1k_short → thin;
                                  fill1k_bps < LIQ_DEEP_BPS (1.0) → deep
flow  ∈ {quiet, organic, bot_war} vol5_usd < p10 → quiet; > p90 → bot_war   (percentiles over the window's 5-min sums)
trend ∈ {dumping, flat, pumping}  ret15_z < -1 → dumping; > +1 → pumping
vol   ∈ {calm, normal, violent}   rv_ratio < 0.5 → calm; > 2.0 → violent
```
`fill1k_bps` = max(buy, sell): buy = 1e4·(VWAP of walking the asks for NOTIONAL_USD of
quote − mid)/mid, sell = 1e4·(mid − VWAP of walking the bids for NOTIONAL_USD)/mid. A side
the levels cannot fill costs inf, logged as `fill1k_bps: null` with `fill1k_short: true`.
`l1_min_usd` stays a logged feature and sets no word. 2026-09-24, decided by Alex: liq
was `l1_min_usd < NOTIONAL → thin; > 10*NOTIONAL → deep`; level 1 swung $1–$11,580 within
a minute and read thin 7/12 while a $1,000 order cost 0.44–2.02 bps (SPEC §5).
Exact thresholds live in `loop/config.py` and are frozen into `SPEC.md`.
**No position in the state.** Arms A and B ride one request on one state, so
the state must be identical for both; a position would differ per arm.
`state_string(adj) -> str` = `"SOL: liquidity {liq}, flow {flow}, trend {trend}, vol {vol}"`.
Must contain no digit. `rule_c(adj) -> "buy"|"sell"|"hold"`:
- buy  iff trend == pumping and vol != violent and liq != thin
- sell iff trend == dumping or vol == violent
- hold otherwise

Actions are position-free intents: **buy = want to be long, sell = want to be
flat, hold = no change.** The book maps intent onto the current position.

**Questions** — `loop/prompts.py::build(v1, current) -> dict`
```
{ "a_action": v1["action"],          # choice
  "b_action": current["action"],     # choice — identical to a_action until the first promote
  "skip":  v1["skip"],               # noul
  "up15":  v1["up15"],               # noul
  "down15": v1["down15"] }           # noul
```
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

**Row** — one line of `data/decisions.jsonl` per tick, append-only:
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
`tick_id` is `ts_rx` floored to the minute. A tick that fails before the feed
still writes a row with `absence` set and everything else null it can't fill.

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
replay(rows, outcomes, arm: "a"|"b"|"c", column: str, fee_bps) -> {"equity": [...], "trades": [...], "pnl_bps_per_tick": {tick_id: float},
                                                                    "position": {tick_id: qty}, "forced_hold": int}
   mark-to-mid each tick; pnl per tick is computed DIRECTLY (carried qty*(mid_t - mid_prev); open qty*(mid_t - ask) - fee;
   close qty*(bid - mid_prev) - fee), in bps of NOTIONAL, so two arms with the same position give d_t == 0.0 exactly (SPEC §10)
paired(rows, outcomes, x, y, column, fee_bps) -> [ (tick_id, d_t) ]   d_t = pnl_x - pnl_y
```
Fee constants come from `config.FEE_BPS_COLUMNS` = (0, 2, 10, 25, 60, 120), ascending; the
primary is `config.FEE_BPS_PRIMARY` = 0.0, gross, the H1 cell; the venue's own taker fee
is `config.FEE_BPS_VENUE` = 120.0, with its UNVERIFIED source in `FEE_BPS_VENUE_SOURCE`.
(2026-09-24, decided by Alex: the primary was the venue's taker fee.)

## 3. The tick (`loop/cycle.py`)

Order, every time:
1. **Guards.** Resolved repo path must not start with either prefix in
   `config.FORBIDDEN_PREFIXES` → exit 3. `data/HALT` exists → this tick is
   HALTED. Today's spend (sum over today's rows of the billed tokens: the logged
   `jev.input_tokens` when positive, else `config.JEV_TOKENS_IF_UNKNOWN` = 2000 for a
   live row that reached the model, SPEC §13.3; × `config.USD_PER_MTOK` / 1e6) ≥
   `config.DAILY_SPEND_HALT_USD` → write
   `data/HALT` with the reason; this tick is HALTED. A log that exists but cannot be read (a
   0200 mode, a directory, EIO), or a count, or today's sum of them, past a float's range,
   counts as over the limit: the guard cannot count, so it trips (2026-09-28); a missing log
   is $0. `fcntl.flock` on
   `data/loop.lock` non-blocking; if held → `absence: "lock"`, exit 0.
   **HALT stops sends only** (PROTOCOL §3.8, SPEC §13.2): a HALTED tick runs
   steps 2–4 as usual and then writes its row with `absence: "halt"` in place
   of steps 5–7 — no ledger row, no send, no body printed — and exits 0. The
   feed, `rule_c`, the marks and the t+h join therefore survive a HALT. A
   failure in steps 2–4 keeps its own absence: `absence` names the first step
   that did not happen.
2. **Feed.** `snapshot()`. On `FeedError` → row with `absence: "feed"`, exit 0.
3. **State.** features → adjectives → state string → rule_c.
4. **Prompts.** load v1 and CURRENT; shas; questions.
5. **Dry?** `--dry` → write the row with `answers: null`, `columns: {a:null,b:null}`,
   `mode: "dry"`. No ledger row, no send. This is the free thing, run first.
6. **Ask.** `jev.ask()`. On `JevError` → row with `absence: "jev"`, `jev.error` set.
   On 401/403 also write `data/HALT` ("key rejected"). Any other exception once
   the send has begun → `absence: "jev"`, `jev.error: "unexpected"` (the request
   may have left, so the spend guard must charge it; `guard` rows cost $0).
7. **Columns.** `rules.columns()` for a and b.
8. **Write** the row (atomic append: build the line, one `write`, `flush`, `fsync`).
9. **Heartbeat.** touch `data/heartbeat` with `ts_rx`.

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
   trades/day each side. Primary cell is marked; the venue fee (`FEE_BPS_VENUE`), its
   UNVERIFIED source and a per-arm line at it are printed beside the table as the
   realistic-cost column (2026-09-24, decided by Alex). Beside the all-ticks figure,
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
each PAUSE, and the pending prompt version on its own line; still health only.

**PREREG-v2's inference (`loop/inference_v2.py`, `make results`).** `python3 -m loop.inference_v2 --sample
[--out RESULTS-v2.md] [--accept-pending]` reads every product's store once (each log's sha and byte length printed)
and runs once, at day 28. It refuses (exit 3) while PREREG-v2.md §12's T0_v2 is blank or malformed and before
T0_v2 + 28 d, both before any log is opened, and while d28 is open (no log has reached T0_v2 + 28 d + h + 30 s, where
`report.days_table` closes the day) unless `--accept-pending` says the logs stopped; `--out` never overwrites. The
clock and R are `main`'s arguments for the tests, not flags, and T0_v2 is §12's and nothing else. It prints
RESULTS-v2: §0 (a placeholder for `bin/seal-check`'s section, `data/looks.tsv` verbatim, the set of `spec_sha` over
the sample's rows, each product-day's `prompt_b` set with every product-day holding two or more values named, PREREG-v2
§8); stop rule 3 recomputed per product, which governs, beside `data/exclusions-v2.tsv`, and void; H1
and family F on PREREG-v2 §4's pooled series (`pooled`: the same sums, in the same order, as
`report.cadence_table`'s cells), each cell with its own `random.Random(seed)`, v1's draw (`inference.resample_indices`)
and the bound `sorted[ceil(alpha R) - 1]` with alpha a `fractions.Fraction` (`alpha_rank` refuses a float); F4
withdrawn under §9.2's NO PROMOTION; stop rules 1–2 and PREREG-v2 §11's reading; §7's figures as measured; and,
descriptive, `report.cadence_table` at PREREG-v2 §6's fee columns (`inference_v2.FEE_COLUMNS`, passed as its
`fees`), arm D's and A's agreement and the direction probabilities per product. v1's `loop/inference.py` is unchanged.

## 5. Nightly

`nightly/digest.py [--date YYYY-MM-DD]` → `data/digest-<date>.md`: one summary
line (ticks, occupancy, trades and paper PnL per arm at 0 bps, labelled direction, AND
at `FEE_BPS_VENUE`, labelled venue fee (2026-09-24, decided by Alex), disagreement count
for B), up to 25 arm-B disagreement rows (state, choice,
confidence, ret_h_bps, label) highest confidence first, the CURRENT `action`
question verbatim, both shas. Never the key, never the raw log, never the features.

`nightly/propose.sh` (as it runs; the header of the script is the authority): the digest
first (`nightly.digest --date <date>`; exit 4 = the day has no rows, so the night ends
there with one log line and no Claude call); then the token read from
`~/.secondbrain-secrets/oauth_token` into `CLAUDE_CODE_OAUTH_TOKEN` for the ONE call and
unset after, never on argv, never logged; the call itself, with the working directory an
empty temporary directory so the CLI auto-loads no CLAUDE.md from the repo (the slow
model sees PROMPT.md and the digest, nothing the repo's working rules say, and
`~/.claude/CLAUDE.md` user memory as it always has, whose sha256 is logged; the night
fails if a CLAUDE.md, CLAUDE.local.md or .claude sits in any ancestor of the temp
directory; 2026-09-28). The call names no model; after it, `nightly/answered_model.py` reads
the model that answered from the CLI's own transcript of that session and the night logs it
(`claude model <id>`, or `unrecorded`) and passes it to the table's header (recorded, not
pinned: HANDOFF decision 4, approved 2026-09-28):
`caffeinate -i python3 nightly/capped.py 2700 -- claude -p "$(cat nightly/PROMPT.md)

$(cat data/digest-<date>.md)" --tools "" --restricted --strict-mcp-config --settings
nightly/settings.json --output-format text` (`capped.py`: 45 min of AWAKE time, monotonic,
exit 124 when it fires; the command runs in a process group of its own, which the cap ends,
which ends when the command exits, and to which SIGTERM/SIGINT/SIGHUP/SIGQUIT are passed on; the CLI's version and the temp cwd are logged); extract exactly one
fenced ```json block; validate it is `{"candidates": [ {"instructions": str, "criteria":
{"buy","sell","hold"}} , ... ]}` with 1–3 entries and no digit; write `proposals/<date>.json`
(refused, before the digest and any call, when `proposals/<date>.json` or `.md` exists: a
missed slot that fires after 00:00Z plus the regular slot must not spend twice or overwrite
a json a table vouches for; `--dry`, the tests' form, needs `--root DIR` outside the repo,
else a usage error, exit 2). Then
`policy_table.py proposals/<date>.json` asks Jev each candidate AND the CURRENT action
question on the 81 synthetic state strings (3⁴ combinations of the alphabet; ~$0.005) and
writes `proposals/<date>.md`: per candidate, the 81-row table of choice/confidence, the diff
of its wording vs CURRENT, the count of states where it differs from CURRENT and from
rule_c, where those changes land (per adjective, changed / answered states, and the
CURRENT -> candidate moves; since 2026-09-28, for the person who promotes, never the digest),
and the sha256 of the json it was built from (`bin/promote` checks it). Last, on
every night whatever happened, `loop.dash` rebuilds `data/dash.html`. Every failure is one
line in `logs/propose.log` and exit 0 (launchd throttles a failing job); the night also
writes `data/digest-<date>.md` and `logs/claude-<date>.{txt,err}`.
**It scores nothing against any logged outcome.** The nightly never touches
`prompts/`. While `data/HALT` exists it sends nothing (propose.sh skips the
table, and `policy_table.py` refuses again, before every send); a 429, three transient
failures in a row, or three failures of any kind in a row end its night; a 401/403 writes
`data/HALT`.

`bin/promote proposals/<date>.json <k>`: copies candidate k to `prompts/v<N+1>.json`
(with the other three questions carried from v1 unchanged), writes the new
version name to `prompts/CURRENT`, prints the diff, and refuses without a tty, if `git status`
is dirty, if the `prereg-v1` tag does not exist (PREREG §10: sealed before the
first row with `prompt_b != "v1"`), or if the json's sha256 differs from the
`proposal sha256` line of the table beside it (no table, a table without the line, or
one marked INCOMPLETE is a warning). CURRENT is written as CURRENT.tmp and renamed
over. A person runs it. Nothing else writes `prompts/`.

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

## 7. Style

Match `~/Projects/JEV/bin/jev`: dense, explains WHY in comments with the
measured number that justifies it, no framework, no cleverness. Module
docstring says what the file may and may not do. Every constant that defines
arm C or the alphabet is named and lives in `config.py`.

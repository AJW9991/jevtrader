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
H1+H2 co-primary over 28 days at the venue's own taker fee.

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
  README.md  Makefile  STEPS.md
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
  loop/report.py         make report
  nightly/digest.py      what the slow model may read
  nightly/policy_table.py  81 synthetic states per candidate
  nightly/propose.sh  nightly/PROMPT.md  nightly/settings.json
  bin/promote            the human apply step
  launchd/com.alexward.jevloop.loop.plist  launchd/com.alexward.jevloop.nightly.plist
  prompts/v1.json        frozen (written)   prompts/CURRENT  → "v1" (one line)
  fixtures/              one recorded Coinbase snapshot set, committed
  tests/                 unittest, stdlib
  data/   logs/   proposals/   (gitignored except proposals/*.md)
```

## 2. Data types (plain dicts; keys exactly as written)

**Snapshot** — `loop/feed.py::snapshot(product) -> dict`
```
{ "ts_rx": ISO8601 UTC ms (this machine's clock, the decision timestamp),
  "product": "SOL-USD",
  "bid": float, "bid_size": float, "ask": float, "ask_size": float,
  "book_time": ISO8601 or null (venue's book timestamp if given),
  "candles": [ {"start": epoch_s int, "open","high","low","close","volume": float}, ... ]
              oldest first, ONE_MINUTE, at least 300 rows, newest is the last CLOSED minute,
  "trades_5m": int  (count of trades with time >= ts_rx-300s; -1 if the endpoint gave none),
  "feed_age_s": float (ts_rx minus the newest candle's start+60, i.e. how stale),
  "http": {"calls": int, "ms": int} }
```
Raises `FeedError(str)` on any HTTP/parse failure. No retries inside feed.

**Features** — `loop/state.py::features(snap) -> dict` (numbers; logged, never sent)
```
{ "mid": float, "spread_bps": float, "l1_min_usd": float,
  "vol5_usd": float, "vol5_p10": float, "vol5_p90": float,
  "ret15_bps": float, "ret15_sd_bps": float, "ret15_z": float,
  "rv15": float, "rv15_med": float, "rv_ratio": float,
  "window_min": int }
```
**Adjectives** — `loop/state.py::adjectives(feat) -> dict`, each value one word:
```
liq   ∈ {thin, normal, deep}      l1_min_usd < NOTIONAL → thin; > 10*NOTIONAL → deep
flow  ∈ {quiet, organic, bot_war} vol5_usd < p10 → quiet; > p90 → bot_war   (percentiles over the window's 5-min sums)
trend ∈ {dumping, flat, pumping}  ret15_z < -1 → dumping; > +1 → pumping
vol   ∈ {calm, normal, violent}   rv_ratio < 0.5 → calm; > 2.0 → violent
```
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
returns { "answers": {qid: {...}}, "model": str, "input_tokens": int, "latency_ms": int }
raises JevError(kind, detail)   kind ∈ {"no-key","ledger","http-4xx","http-429","http-5xx","timeout","parse"}
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
  after 1.0 s. Never on 4xx other than 429. 401/403 → raise; the caller writes HALT.
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
mid_h from the first row whose `ts_rx` ∈ [t+h, t+h+90 s]; `ret_h_bps = 1e4*ln(mid_h/mid_t)`;
label with a ±5 bps dead band. Anything else is `gap`, never the wrong row.

**Book** — `loop/book.py`, pure functions:
```
apply(pos: dict|None, intent: str, bid, ask, fee_bps) -> (pos', fill|None)
   pos = None (flat) | {"qty": float, "entry": float}
   buy when flat  → open: qty = NOTIONAL/ask, fee = NOTIONAL*fee_bps/1e4
   sell when long → close at bid, fee on notional
   buy when long, sell when flat, hold → no-op (fill None)
replay(rows, outcomes, arm: "a"|"b"|"c", column: str, fee_bps) -> {"equity": [...], "trades": [...], "pnl_bps_per_tick": {tick_id: float}}
   mark-to-mid each tick; pnl per tick is the change in equity in bps of NOTIONAL
paired(rows, outcomes, x, y, column, fee_bps) -> [ (tick_id, d_t) ]   d_t = pnl_x - pnl_y
```
Fee constants come from `config.FEE_BPS_COLUMNS`; the primary is
`config.FEE_BPS_PRIMARY` (the venue's own taker fee, with its source URL in config).

## 3. The tick (`loop/cycle.py`)

Order, every time:
1. **Guards.** Resolved repo path must not start with either prefix in
   `config.FORBIDDEN_PREFIXES` → exit 3. `data/HALT` exists → write a row with
   `absence: "halt"`, exit 0. Today's spend (sum of `jev.input_tokens` over today's
   rows × `config.USD_PER_MTOK` / 1e6) ≥ `config.DAILY_SPEND_HALT_USD` → write
   `data/HALT` with the reason and exit 0. `fcntl.flock` on `data/loop.lock`
   non-blocking; if held → `absence: "lock"`, exit 0.
2. **Feed.** `snapshot()`. On `FeedError` → row with `absence: "feed"`, exit 0.
3. **State.** features → adjectives → state string → rule_c.
4. **Prompts.** load v1 and CURRENT; shas; questions.
5. **Dry?** `--dry` → write the row with `answers: null`, `columns: {a:null,b:null}`,
   `mode: "dry"`. No ledger row, no send. This is the free thing, run first.
6. **Ask.** `jev.ask()`. On `JevError` → row with `absence: "jev"`, `jev.error` set.
   On 401/403 also write `data/HALT` ("key rejected").
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
   mean/p95 latency, input tokens and $ to date, distinct `model_answered`, drift count.
2. Adjective occupancy per dimension; flag any word > 95% (arms cannot disagree
   on a constant).
3. Test-retest: on rows where `prompt_a_sha == prompt_b_sha`, agreement rate of
   `a_action.choice` vs `b_action.choice`, and mean |Δconfidence|. This is Jev's
   determinism, measured for free.
4. Agreement of column `a.argmax` with `rule_c` (does the model follow the rule it was given).
5. For each pair (B−C, A−C, B−A) × each column × each fee: n ticks, n ticks with
   differing positions ("disagreement ticks"), mean d_t, mean d_t on disagreement
   ticks, hit rate on disagreement ticks, trades/day each side. Primary cell is
   marked. Every-15th-tick subsample reported beside the all-ticks figure.
6. Calibration (H2, frozen arm A): for confidence bins [0.5,0.7,0.85,0.99,1],
   P(argmax correct) where correct = buy&up or sell&down or hold&flat.
No p-values in `make report`. Inference lives in PREREG.md and is run once.

## 5. Nightly

`nightly/digest.py [--date YYYY-MM-DD]` → `data/digest-<date>.md`: one summary
line (ticks, occupancy, trades and paper PnL per arm at the primary fee,
disagreement count for B), up to 25 arm-B disagreement rows (state, choice,
confidence, ret_h_bps, label) highest confidence first, the CURRENT `action`
question verbatim, both shas. Never the key, never the raw log, never the features.

`nightly/propose.sh`: `export CLAUDE_CODE_OAUTH_TOKEN=$(cat ~/.secondbrain-secrets/oauth_token)`;
`caffeinate -i /opt/homebrew/bin/claude -p "$(cat nightly/PROMPT.md)

$(cat data/digest-<date>.md)" --tools "" --output-format text`; extract exactly
one fenced ```json block; validate it is `{"candidates": [ {"instructions": str,
"criteria": {"buy","sell","hold"}} , ... ]}` with 1–3 entries; write
`proposals/<date>.json`. Then `policy_table.py proposals/<date>.json` asks Jev
each candidate AND the CURRENT action question on the 81 synthetic state strings
(3⁴ combinations of the alphabet; ~$0.005) and writes `proposals/<date>.md`: per
candidate, the 81-row table of choice/confidence, the diff of its wording vs
CURRENT, and the count of states where it differs from CURRENT and from rule_c.
**It scores nothing against any logged outcome.** The nightly never touches
`prompts/`.

`bin/promote proposals/<date>.json <k>`: copies candidate k to `prompts/v<N+1>.json`
(with the other three questions carried from v1 unchanged), writes the new
version name to `prompts/CURRENT`, prints the diff, and refuses if `git status`
is dirty. A person runs it. Nothing else writes `prompts/`.

## 6. Tests (`tests/`, `python3 -m unittest`)

Fixtures: ONE real Coinbase snapshot set recorded once (book + 350 candles +
trades), committed under `fixtures/`, with the fetch command in a README. Tests
must pass offline.
- state: every adjective boundary (just below / at / just above); rule_c truth
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

## 7. Style

Match `~/Projects/JEV/bin/jev`: dense, explains WHY in comments with the
measured number that justifies it, no framework, no cleverness. Module
docstring says what the file may and may not do. Every constant that defines
arm C or the alphabet is named and lives in `config.py`.

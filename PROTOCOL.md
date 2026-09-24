# PROTOCOL — the carve-out, and what it does not cover

**Status: DRAFTED 2026-09-23 by Claude. Not in force until Alex signs the last
section and pastes the one line into `~/Projects/JEV/PROTOCOL.md` §7.** Nothing
in this repo sends a request to api.typesafe.ai before that, and nothing loads
into launchd before that. `--dry` runs (no model) are allowed now.

## 1. What this repo is

A paper-only, forward-only measurement of the "two models at two speeds" loop
described in a public X article of 2026-09-22: a fast typed model answers a
fixed set of typed questions once a minute from a ~10-word adjective state; a
slow model proposes a rewrite of one question's wording nightly; a person
applies it. The question this repo exists to answer is whether the nightly
rewrite does anything, measured against a frozen prompt and against the
no-model rule the thresholds already imply.

## 2. The rules of `~/Projects/JEV/PROTOCOL.md` this repo would otherwise break

§5 Never: *"Any always-on hook that makes a model call"* — the tick is one,
1,440 times a day. §5: *"`jev ask` as a decision instrument"* — the tick asks
Jev a buy/sell/hold question. §2.8 / rule 8: *"No hook makes a model call."*
`NEXT.md` keeps *"agent routing (decides at 0.5, silent in the dangerous
direction)"* rejected.

## 3. The exception, and its exact edges

Granted for **this repository only**, on these conditions, every one of which
is enforced in code and checked by `make test`:

1. **Paper only.** No wallet, no exchange credentials, no order of any kind.
   Positions exist only by replaying `data/decisions.jsonl`.
2. **Forward only.** Decisions at t from data available at t; outcomes are the
   log's own row at t+h. Nothing is computed over any data from before the
   loop's first row. The nightly scores candidates on 81 synthetic states,
   never on a logged outcome.
3. **Separate.** A path guard exits 3 under `~/Projects/crypto-trading-system`
   and its iCloud mirror. This repo never reads, imports, writes or proposes
   anything for that repo. The crypto repo's own exclusion of Jev (sealed at
   `03131fd`, OpenTimestamps `9195387`) is untouched by this.
4. **Nothing acts on a confidence.** The tick logs every answer; every action
   rule (argmax, c50, c70, c85, c99, veto, pbuy60, noultail) is a column
   derived afterwards from one logged answer. The 0.15–0.99 band that
   §2.2 calls unmeasured is what the columns measure. This is why the
   exception is a measurement, not a decision instrument.
5. **Own ledger, before every send, failing closed.** `data/sends.tsv`, same
   columns as `~/Projects/JEV/sandbox/DISCLOSURE.tsv`. An unwritable ledger
   means nothing is sent.
6. **Own key.** `~/.secondbrain-secrets/typesafe-api-key-loop`, so a
   loop-triggered limit or suspension (TypeSafe MCA §6) never reaches the
   brain's live injection screen or the weekly canary. Until it exists the
   loop falls back to the shared key and says so in every row's `jev.key_path`.
7. **Human-applied prompts.** The nightly writes `proposals/`. Only
   `bin/promote`, run by a person, changes `prompts/`. No plist, no script and
   no model writes there.
8. **Spend tripwire.** `data/HALT` is written at $0.25/day of input tokens
   (~5× the estimate). HALT stops *sends*; the feed, arm C, the outcome join
   and the report keep running, because observation outlives sending.
9. **Pinned model.** Every request names `jev-1.13.0`; the answering model is
   logged; a mismatch is `drift: true` in the row and counted in the report.
10. **Hand-installed.** The two plists are installed by Alex per `STEPS.md`,
    never by a script. Same as the canary.
11. **Enforced in code, not by habit.** `loop/jev.py::ask` refuses with kind
    `unsigned` until the signature line in §5 carries both fields — before the
    key is read, the ledger is written or a socket is opened. Every send in
    the tick and the nightly passes through it. An unsigned tick still records
    the feed, the state and arm C, and bills nothing.

Not exempted, and unchanged: the brain (`~/Projects/Claude`), the JEV CLI and
its protocol, the crypto repo, and every other §5 line ("retry loops": this
repo retries at most once, on 429/5xx only; "engineering around a ledger
failure": a ledger failure is a non-send).

## 4. The line for `~/Projects/JEV/PROTOCOL.md` §7 Open (paste verbatim)

```
9. 2026-09-23 — CARVE-OUT, side project only: ~/Projects/jev-paper-loop runs
   an always-on Jev caller (1/min) and a nightly rewrite of its own prompt, as
   a paper-only, forward-only MEASUREMENT of the 0.15–0.99 band (every rule is
   a column; nothing acts on a confidence). Own repo, own store, own ledger,
   own key, human-applied prompts, hand-installed plists. Its PROTOCOL.md has
   the eleven conditions. Nothing here re-opens the crypto-repo exclusion.
```

## 5. Signature

Written by Claude on 2026-09-23 from decisions Alex made the same day
(carve-out both repos; MVP-first; Coinbase SOL-USD; second key; Mac launchd;
60 s / 15 min; H1+H2 over 28 days at the venue's fee; policy tables only).
Amended 2026-09-24, before signing, by Alex: H1 is at 0 bps gross (the venue's
120 bps taker is a descriptive column; profitability at retail fees is settled
by arithmetic, not tested), and `liq` walks the book for a $1,000 order instead
of reading the top level, which was noise on this venue.

In force from: `____________`  Signed: `____________`

(The signature is the commit that fills these two fields in. The JEV §7 line
is pasted in the same sitting.)

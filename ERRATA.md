# ERRATA — where the sealed documents and the code disagree

Written 2026-09-28 from five independent reviews of the code against the documents (docs,
frozen-list audit, invariant tests, macOS review, verifiers). SPEC.md, PREREG.md, PROTOCOL.md
and nightly/PROMPT.md are frozen until the sample ends (2026-10-23 21:40Z; CLAUDE.md): nothing
here is applied to them before then. Each entry says what the document says, what the code
does, and which one the revision after the sample should keep. Nothing here is a reading of
report §4–§7.

Kinds: **stale** (the code moved on by a decision already made; update the sentence),
**gloss** (an informal sentence contradicts the document's own formal rule, which the code
follows; fix the sentence), **gap** (the document is silent where the code decides),
**choice** (the code's behaviour is a decision someone should confirm).

## PREREG.md

| § | The document says | The code does | Kind |
|---|---|---|---|
| §2, §8.3 | "UTC day" | Days of 24 h anchored at T0, labelled d01–d28 (report.py, inference.py, exclusions), per Alex's reading of 2026-09-26 | stale |
| §3 | "Forced holds contribute 0.0; a block with no live row has S_k = 0" | SPEC §10 carries each arm's position through a forced row (HALT, a jev or guard absence, a dry row) and marks it to that row's mid, so d_t ≠ 0 there whenever the arms hold different positions, and a HALT-only block's S_k is the arms' difference in marks. This is §3's own formal definition (S_k = the sum of book.paired's d_t). On a 28-day synthetic log, 58 of 72 blocks with rows but no live row had S_k ≠ 0; mean S_k(B−C) was −0.7772 bps as defined vs −0.7252 if the sentence held (tests/test_invariants.py pins the fold). | gloss |
| §3, §8.4 | `make report` / `--t0` print S_k and H1/H2 on lines of their own | Both withhold §4–§7 on sample rows until T0 + 28 d; `--unblind` prints them and says so; the day-14 look is `make health` | stale |
| §4 | The H1 bootstrap draw "as above" | Not pinned by §4; the code applies §5 steps 1–3 to H1 too (a fresh `random.Random(20260923)` per pair, circular blocks of 4, sorted[249] of 10,000) | gap |
| §4, §8.3 | Excluded days are dropped | The whole window is replayed from flat at T0 and the excluded days' blocks are then dropped (a position carried into an excluded day is marked there and the next kept day starts from it); the other reading, dropping the rows before the replay, gives different numbers | gap |
| §8.3 | Jev error share: rows with `absence: "jev"` over rows that "reached the ask" | Every `jev` row counts on both sides, `no-key`, `ledger` and `unsigned` included (raised inside `jev.ask`); the other reading (SPEC §13.3's "reached the model") would make a day of `no-key` 0/0 and never BAD | gap |
| §8.3 | Stop rule 3 marks days BAD | The exclusions file decides and is applied as written; since 2026-09-28 the day-28 output recomputes the rule from the log beside it and names any day listed but not BAD, or BAD but not listed | gap |
| §5 | The last block's H2 unit needs its t + h row | `loop.inference --sample` refuses (exit 3) until that row is in the log: ~30 s after the end normally, up to ~15.5 min at worst; `--accept-pending` counts the missing ones as gaps and says so | gap |

## SPEC.md

| § | The document says | The code does | Kind |
|---|---|---|---|
| §2 | The `jev.error` kinds | Also `unsigned` (a request refused before the send; not billed) | gap |
| §2 | `watchdog` is "inside the send" | Also written when the alarm lands while the answer becomes columns; that row has `input_tokens > 0` and no answers | gap |
| §2 | Answers are kept on "one" absence, the out-of-alphabet choice | Also kept for a bool, NaN, infinite or wrong-typed answer field (`jev`/`parse`, columns null) and for an `unexpected` exception at the columns stage | gap |
| §3 | The book's finiteness rule | The same rule for window candles: an open/high/low/close that is not finite and positive, or a volume not finite and non-negative, refuses the set (`feed` absence) | gap |
| §9 | Rule columns from the answer's numbers | A bool, NaN or infinite number is refused (`rules._real`), never a column | gap |
| §10 | "d_t is exactly 0.0 on any tick both arms carry the same qty into and out of" | Two live decisions sharing a minute fold together (§10's own rule), so an arm that round-trips inside the minute pays a spread: d_t ≠ 0 though both arms are flat in and out. report's disagreement count does not count that tick; H1 is unaffected. Seen once in 28 synthetic days. | gloss |
| §10 | Rows of one minute are folded together | In `ts_rx` order, not file order (they differ only when a lock row and a live row share a minute; lock rows are unpriced, so nothing moves) | gap |
| §10 | "null columns … forced hold for EVERY arm" | A live answered row with both columns null holds every arm; with only ONE arm's columns null (or `rule_c` null) only that arm holds and the others still trade. The writer cannot produce that shape (a missing answer is `jev`/`parse`), so no row is affected; the literal reading would hold every arm | choice |
| §11 | "the StartInterval phase" | launchd's StartCalendarInterval since 2026-09-27 05:18Z | stale |
| §11 | Two rows with one tick_id: "the priced one wins" | `outcomes.rank`: the live decision speaks for its tick, then any other priced row, then an unpriced one; equal ranks keep the first. Ties at t + h are judged in whole milliseconds, earlier row first; the joined row is strictly after t. | stale |
| §11 | A crash mid-write costs one row | A whole row glued onto a torn line, and every whole row on a line that lost its newlines, is read; the line is one skip | gap |
| §12 | Retry and redirect rules | A 3xx is never followed (the key would go with it) and is `http-4xx` with no retry; a retry whose ledger append fails keeps attempt 1's kind; a null, "", [] or {} `usage.input_tokens` reads 0 and the answer is kept | gap |
| §13.5 | "Every path after the path guard writes exactly one row" | Not when SIGTERM lands before the write begins, the watchdog lands in the guards before the lock, `data/` cannot be created, or the append itself fails (each logged, exit 0) | gloss |
| §13.6 | The append | Starts with a newline when the log's last byte is not one (a torn line is closed first) | gap |
| §13, §14 | What the nightly writes and when it stops | It also writes the digest, logs/ and data/dash.html; it ends on unsigned/no-key/ledger, `MAX_OTHER_RUN` = 3, `MAX_ERROR_RUN` = 3 and `DEADLINE_S`; §14 lists neither `MAX_*_RUN` | gap |

## PROTOCOL.md

| Where | The document says | The code does | Kind |
|---|---|---|---|
| §3 (retries) | "retries at most once, on 429/5xx only" | Also retries a timeout or transport failure, once | stale |
| §3 (conditions) | Every condition "enforced in code" | Condition 10, the hand-installed plists, is enforced by a person | gloss |
| §3 (spend) | "$0.25/day of input tokens" | Billed tokens, charging 2,000 for a send whose count is unknown | gloss |

## nightly/PROMPT.md (the treatment: its content stays fixed through the sample)

| Where | The document says | The code does | Kind |
|---|---|---|---|
| Opening | "one fixed question" | Five typed questions a tick, in one request; the nightly rewrites the one `action` question | gloss |
| Rules, 4 | A candidate with a digit "is discarded unread" | The whole reply fails (propose.sh), and policy_table.py would refuse it anyway | choice |
| Output | "no other fenced block" | Not enforced; only ```json blocks are counted | gap |

## The nightly's context (a decision, not an erratum)
From the night a merge of this branch is pulled onto the Mac, the one `claude -p` call runs
from an empty temporary directory, so the repo's CLAUDE.md and the CLI's per-project state no
longer reach the slow model; `~/.claude/CLAUDE.md` still loads and its sha is logged. That
date is a change of the treatment's context and belongs in the write-up (HANDOFF.md decision 1).

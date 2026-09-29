# ERRATA — where the sealed documents and the code disagree

Written 2026-09-28 from five independent reviews of the code against the documents (docs,
frozen-list audit, invariant tests, macOS review, verifiers). SPEC.md, PREREG.md, PROTOCOL.md
and nightly/PROMPT.md are frozen until the sample ends (2026-10-23 21:40Z; CLAUDE.md): nothing
here is applied to them before then. Each entry says what the document says, what the code
does, and which one the revision after the sample should keep. Nothing here is a reading of
report §4–§7.

**Folded (2026-09-29, the prereg-v2 build).** Every SPEC.md and PREREG.md row below ends with where it went: SPEC v2
(PREREG-v2 §10: "ERRATA.md's SPEC and PREREG rows that describe what the code already does are folded into the text")
or PREREG-v2, which settled most of the PREREG rows when it was written. The rows stay: v1's sample is read by v1's
documents, which are not edited, and SPEC v2 reaches `main` only at the switch, after the sample.

Kinds: **stale** (the code moved on by a decision already made; update the sentence),
**gloss** (an informal sentence contradicts the document's own formal rule, which the code
follows; fix the sentence), **gap** (the document is silent where the code decides),
**choice** (the code's behaviour is a decision someone should confirm).

## PREREG.md

| § | The document says | The code does | Kind |
|---|---|---|---|
| §2, §8.3 | "UTC day" | Days of 24 h anchored at T0, labelled d01–d28 (report.py, inference.py, exclusions), per Alex's reading of 2026-09-26 **Folded into PREREG-v2 §2** (days are T0-anchored, d N = [T0_v2 + 86,400 (N − 1), …)). | stale |
| §3 | "Forced holds contribute 0.0; a block with no live row has S_k = 0" | SPEC §10 carries each arm's position through a forced row (HALT, a jev or guard absence, a dry row) and marks it to that row's mid, so d_t ≠ 0 there whenever the arms hold different positions, and a HALT-only block's S_k is the arms' difference in marks. This is §3's own formal definition (S_k = the sum of book.paired's d_t). On a 28-day synthetic log, 58 of 72 blocks with rows but no live row had S_k ≠ 0; mean S_k(B−C) was −0.7772 bps as defined vs −0.7252 if the sentence held (tests/test_invariants.py pins the fold). **Folded into PREREG-v2 §4** (S_k,p is the sum of `book.paired`'s d_t over the block; the sentence is not carried) and SPEC v2 §10. | gloss |
| §3, §8.4 | `make report` / `--t0` print S_k and H1/H2 on lines of their own | Both withhold §4–§7 on sample rows until T0 + 28 d; `--unblind` prints them and says so; the day-14 look is `make health` **Folded into PREREG-v2 §9.5** (withholding until T0_v2 + 28 d; the day-14 look is `make health`). | stale |
| §4 | The H1 bootstrap draw "as above" | Not pinned by §4; the code applies §5 steps 1–3 to H1 too (a fresh `random.Random(20260923)` per pair, circular blocks of 4, sorted[249] of 10,000) **Folded into PREREG-v2 §5** (the draw is `inference.resample_indices` under each cell's own `random.Random(seed)`). | gap |
| §4, §8.3 | Excluded days are dropped | The whole window is replayed from flat at T0 and the excluded days' blocks are then dropped (a position carried into an excluded day is marked there and the next kept day starts from it); the other reading, dropping the rows before the replay, gives different numbers **Folded into PREREG-v2 §4** ("Replay and exclusion": this reading, settled there). | gap |
| §8.3 | Jev error share: rows with `absence: "jev"` over rows that "reached the ask" | Every `jev` row counts on both sides, `no-key`, `ledger` and `unsigned` included (raised inside `jev.ask`); the other reading (SPEC §13.3's "reached the model") would make a day of `no-key` 0/0 and never BAD **Folded into PREREG-v2 §9.3** (every error kind, `report.py days_table`). | gap |
| §8.3 | Stop rule 3 marks days BAD | The exclusions file decides and is applied as written; since 2026-09-28 the day-28 output recomputes the rule from the log beside it and names any day listed but not BAD, or BAD but not listed **Folded into PREREG-v2 §9.3**, which settles it the other way for v2: the rule recomputed from the log governs, and `data/exclusions-v2.tsv` is printed beside it. | gap |
| §5 | The last block's H2 unit needs its t + h row | `loop.inference --sample` refuses (exit 3) until that row is in the log: ~30 s after the end normally, up to ~15.5 min at worst; `--accept-pending` counts the missing ones as gaps and says so **Not folded:** PREREG-v2 names only the refusal before T0_v2 + 28 d (§10); `loop.inference_v2` keeps the d28-open refusal and `--accept-pending`, written into CONTRACT §4. | gap |
| §8.1 | Stop rule 1's model arms kept "only if a second pre-registration wants them" | `make results` refuses (exit 3) before the run unless the annotated tag `prereg-v2-draft` exists and is an ancestor of `prereg-v2` (PREREG-v2 §0, §10: the second pre-registration is frozen before v1 is read); `make results NO_V2=1` runs it anyway and writes "v2 draft tag absent: v2 as drafted is not run; a second block is a new pre-registration written after v1 was read" into RESULTS.md, whose header otherwise carries the tag's sha (`bin/results-v1`). Tooling only: nothing of §4–§5 changes **Folded into PREREG-v2 §10** ("Makefile guard"). | gap |

## SPEC.md

| § | The document says | The code does | Kind |
|---|---|---|---|
| §2 | The `jev.error` kinds | Also `unsigned` (a request refused before the send; not billed) **Folded into SPEC v2 §2.** | gap |
| §2 | `watchdog` is "inside the send" | Also written when the alarm lands while the answer becomes columns; that row has `input_tokens > 0` and no answers **Folded into SPEC v2 §2.** | gap |
| §2 | Answers are kept on "one" absence, the out-of-alphabet choice | Also kept for a bool, NaN, infinite or wrong-typed answer field (`jev`/`parse`, columns null) and for an `unexpected` exception at the columns stage **Folded into SPEC v2 §2.** | gap |
| §2 | `spec_sha`: the SHA-256 of SPEC.md, or `unsealed` until it exists | `unsealed` also when SPEC.md exists but cannot be read (every OSError); during the sealed sample that would label rows with the pre-registration value. SPEC.md is always readable on the Mac **Folded into SPEC v2 §2.** | choice |
| §3 | A window whose two newest closed minutes are missing raises | The code follows §3's formula (`feed_age_s > 120` raises), so at exactly 120.000 s (ts_rx on a minute boundary) the window is accepted; the prose says it raises. Live ticks cannot reach exactly 120.000 **Folded into SPEC v2 §3.** | gloss |
| §3 | The book's finiteness rule | The same rule for window candles: an open/high/low/close that is not finite and positive, or a volume not finite and non-negative, refuses the set (`feed` absence); so does a candle start below 0 or at 2^40 and past, or a body nested past the parser's depth **Folded into SPEC v2 §3.** | gap |
| §9 | A wrong-typed answer field is a parse absence | A numeric STRING (`"0.99"`) is coerced to a float and makes a column (`rules._real`); only bool, NaN, inf and non-numbers are refused. Jev's typed output sends numbers, so no row is known to carry one **Folded into SPEC v2 §9.** | choice |
| §9 | Rule columns from the answer's numbers | A bool, NaN or infinite number is refused (`rules._real`), never a column **Folded into SPEC v2 §9.** | gap |
| §10 | "d_t is exactly 0.0 on any tick both arms carry the same qty into and out of" | Two live decisions sharing a minute fold together (§10's own rule), so an arm that round-trips inside the minute pays a spread: d_t ≠ 0 though both arms are flat in and out. report's disagreement count does not count that tick; H1 is unaffected. Seen once in 28 synthetic days. **Folded into SPEC v2 §10.** | gloss |
| §10 | Rows of one minute are folded together | In `ts_rx` order, not file order (they differ only when a lock row and a live row share a minute; lock rows are unpriced, so nothing moves) **Folded into SPEC v2 §10.** | gap |
| §10 | "null columns … forced hold for EVERY arm" | A live answered row with both columns null holds every arm; with only ONE arm's columns null (or `rule_c` null) only that arm holds and the others still trade. The writer cannot produce that shape (a missing answer is `jev`/`parse`), so no row is affected; the literal reading would hold every arm **Folded into SPEC v2 §10.** | choice |
| §10 | "Verified tier-0 taker fee: ________ bps" (the slot is blank; `FEE_BPS_VENUE = 120.0` is marked UNVERIFIED) | Alex read the fee page in-account on 2026-09-27 ~22:55Z (17:55 Chicago; https://www.coinbase.com/advanced-fees; transcribed in the crypto repo, docs/evidence/2026-09-28_coinbase_advanced_fee_tiers.md): tier Intro, spot maker 0.50 % / **taker 0.90 % = 90 bps**, 30-day volume $0. `FEE_BPS_VENUE` stays 120 through the sample: the digest prints each arm's pnl at it and the digest's content is the treatment, and the report's `[venue fee]` columns are descriptive (they overstate the cost by 30 bps a side). Set 90 and fill the slot for prereg-v2 **Folded into SPEC v2 §10** (`FEE_BPS_VENUE = 90.0`, the row filled, the columns 50 and 90). | choice |
| §11 | "the StartInterval phase" | launchd's StartCalendarInterval since 2026-09-27 05:18Z **Folded into SPEC v2 §11.** | stale |
| §11 | Two rows with one tick_id: "the priced one wins" | `outcomes.rank`: the live decision speaks for its tick, then any other priced row, then an unpriced one; equal ranks keep the first. Ties at t + h are judged in whole milliseconds, earlier row first; the joined row is strictly after t. **Folded into SPEC v2 §11.** | stale |
| §11 | A crash mid-write costs one row | Whole rows on a line that is not one JSON value are read: forward from its start (rows that lost only their newlines), then, after a torn row, each whole row that carries the writer's keys and ends where the next one begins; an object nested in a row is never read as a row; the line is one skip **Folded into SPEC v2 §11.** | gap |
| §12 | Retry and redirect rules | A 3xx is never followed (the key would go with it) and is `http-4xx` with no retry; a retry whose ledger append fails keeps attempt 1's kind; a null, "", [] or {} `usage.input_tokens` reads 0 and the answer is kept **Folded into SPEC v2 §12.** | gap |
| §13.3 | HALT at $0.25 of today's spend | Also when the decision log exists but cannot be read (a 0200 mode, a directory, EIO), or its token count overflows a float: the guard cannot count, so it trips; a missing log is $0 **Folded into SPEC v2 §13.** | gap |
| §13.5 | "Every path after the path guard writes exactly one row" | Not when SIGTERM lands before the write begins, the watchdog lands in the guards before the lock, `data/` cannot be created, or the append itself fails (each logged, exit 0) **Folded into SPEC v2 §13.** | gloss |
| §13.6 | The append | Starts with a newline when the log's last byte is not one (a torn line is closed first) **Folded into SPEC v2 §13.** | gap |
| §13, §14 | What the nightly writes and when it stops | It also writes the digest, logs/ and data/dash.html; it ends on unsigned/no-key/ledger, `MAX_OTHER_RUN` = 3, `MAX_ERROR_RUN` = 3 and `DEADLINE_S`; §14 lists neither `MAX_*_RUN` **Folded into SPEC v2 §13** (and `MAX_OTHER_RUN`, `MAX_ERROR_RUN` into §14). | gap |

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

## nightly/digest.py (the treatment's content: fixed through the sample)

| Where | The code does | What the revision should do | Kind |
|---|---|---|---|
| disagreements, the confidence filter | A b_action confidence that is NaN or +Infinity (kept on a `jev`/`parse` row) passes `< 0.85` as False, so it is counted in "B disagreements"; a NaN also breaks the "highest confidence first" sort, so real rows can be listed out of order and one can drop out of the 25 shown (an integer past a float's range raised and lost the night; since 2026-09-28 such a row is skipped) | Require a finite confidence (as report and outcomes do); no live row is known to carry one | choice |
| disagreements, the choice | A list or dict choice (also a `jev`/`parse` row) raised TypeError and lost the night; since 2026-09-28 such a row is skipped, and every digest that rendered before is byte-identical | Keep | gap |

## The nightly's context (a decision, not an erratum)
From the night a merge of this branch is pulled onto the Mac, the one `claude -p` call runs
from an empty temporary directory, so the repo's CLAUDE.md and the CLI's per-project state no
longer reach the slow model; `~/.claude/CLAUDE.md` still loads and its sha is logged. That
date is a change of the treatment's context and belongs in the write-up (HANDOFF.md decision 1).

## v2 deviations (PREREG-v2 §13: fixes between `prereg-v2-draft` and the seal that §13 (c) does not cover)

Each fix is its own commit and one row here, added at the end: the commit (7 to 40 hex digits), what it fixes, and why
§13 (c) does not cover it. `bin/seal-check` takes each listed commit's diff out of HEAD before it judges the rest, and
prints it; RESULTS-v2 §0 reproduces it. A deviation that touches `at_cadence`, `replay`/`paired`, inference, the pooling
or exclusion readers, `rule_c`, the alphabet or its cuts, PROMPT.md v2, the digest or promote's schedule voids the draft
tag. Rows under this heading are read as deviations until the next heading of its level; any other addition after the
draft tag goes under a heading of its own. Main adds at the end of this file after the draft tag (§13), so this table
stops being the end: a row added after such an addition goes at the end of the file under a new heading
`## v2 deviations (continued)` with this table's header row (§13 (c) allows only additions at the end, and
`bin/seal-check` reads every heading that holds "v2 deviations"). A fix main needs before switch step (6) is listed the
same way, from main.

| Commit | What it fixes | Why outside §13 (c) |
|---|---|---|

# HANDOFF — where the last session left off

Written 2026-09-28 by Claude (Fable 5.1) in a CLOUD session on branch `claude/cool-lamport-7sirtw`
(not merged; nothing here reaches the Mac until Alex merges to `main` and pulls). Supersedes the
2026-09-27 05:40Z handoff. Update this file at the end of every session that changes state.

## State
- The Mac's loop is untouched by this session (no `data/` here). Sample: `prereg-v1`, T0
  2026-09-25 21:40Z, ends 2026-10-23 21:40Z; day 3 of 28 on 2026-09-28. Arm B is v2 since
  2026-09-26 22:21Z. Spend ≈ $0.05 to date.
- This branch (`git log origin/main..`): 52 commits, `make test` green (402 tests) under 3.11-3.13 here and 3.12-3.14 in CI
  (`.github/workflows/test.yml`, every push). Five Opus reviews (tick/send, book+outcomes+report, inference, nightly,
  dash+docs) found no defect on the normal path; every fix below is a guard, a report line, a
  test or tooling. Nothing frozen changed: SPEC, PREREG, PROTOCOL, prompts/, PROMPT.md, the
  digest's content, config thresholds.

## Decisions for Alex (options, not done)
1. **The slow model's context.** `claude -p` run with cwd = the repo auto-loads `./CLAUDE.md`
   (the CLI's `--restricted` ignores settings files, not CLAUDE.md discovery; only `--bare` or
   `--safe-mode` do). CLAUDE.md was committed 2026-09-28 00:15Z (written ~05:40Z on 09-27), so
   the 09-27 08:30Z run may have seen it and tonight's will; it carries the "Jev reads calm as
   not violent" line the 09-25 review kept out of PROMPT.md. Commit 11a0b76 runs the one call from
   an empty temp directory (restoring nights 1-3's context; `~/.claude/CLAUDE.md` user memory
   still loads as it always has) and logs the CLI version and the user-memory sha each night.
   (a) merge and `git pull` on the Mac before 08:30Z (recommended); (b) leave it and record the
   deviation date here; (c) for prereg-v2, `--safe-mode` so the model sees PROMPT.md + digest only.
2. **A day with no live rows** (the Mac off all day, or all-HALT): stop rule 3's fill is 0/0,
   undefined. The report and dash now list every T0 day and flag such a day NO LIVE ROWS, never
   BAD by code. Decide before day 28: excluded whole, or kept (96 blocks of S_k = 0, no H2 unit).
3. **Duplicate priced ticks.** The join now lets the live decision speak for its tick (a later
   dry/double-fire row can no longer score it against a shifted window). Check the live log for
   any such duplicate: `python3 -c "from loop import outcomes;import collections;c=collections.Counter(r['tick_id'] for r in outcomes.load('data/decisions.jsonl') if r.get('mid'));print({t:n for t,n in c.items() if n>1})"`.
4. **Model pin for the nightly.** Nothing pins or records which Claude model writes the
   proposals; the CLI version is now logged per night. `--model` is a spending/treatment call.
5. **120 bps taker fee** still unverified in-account (`config.FEE_BPS_VENUE`).

## Day 28 (`make results`, after 2026-10-23 21:55Z)
`loop.inference --sample` now refuses while the last block's H2 unit still waits for its t + h
row (~15 min after the sample ends), refuses `--now`, another `--t0` or `--resamples` on the
live log, reads the log once and prints its sha/bytes/last tick, prints the stop rules and
§9's reading on lines of their own (VOID-prefixed under 21 kept days), and lists per kept day
the blocks with a live row. The draw is unchanged at 10,000 resamples (byte-identical output,
pinned by tests/test_inference_golden.py against an independent transcription of PREREG §5).
A full run on a 28-day synthetic log takes about a minute here.

## Tooling (all in the Makefile)
`make test` · `make status` (the morning check: heartbeat age, HALT, last row, today's spend vs
the tripwire, sample day, last days of the stop-rule table, newest proposal + MISSING flag, tail
of propose.log) · `make health` (report §1-§3 on the sample; `make report --health` never worked)
· `make report` (withholds §4-§7 on sample rows until 2026-10-23 21:40Z; `--unblind` is a look
and says so) · `make dash` · `make inference-smoke` · `make results` (day 28; refuses before).

## Watch
- Report §1 per-day table: d28 now closes; a NO LIVE ROWS day is a decision (above).
- Each morning: `make status`. The MISSING flag means the nightly's slot passed with no proposal.
- The Mac must stay on AC, lid open.

## What the branch changes on the tick and the send (guards only; no row's meaning changes)
- jev: a 3xx is never followed with the bearer key (a redirect would have re-sent it, as a GET,
  to any host); a null `usage.input_tokens` reads 0 instead of throwing the paid answer away; a
  key file that is not UTF-8 is `no-key`; a ledger failure on the retry keeps attempt 1's billed
  kind; the locally refused request keeps no key-quoting context.
- cycle: a torn last line is closed before the next row (it cost two rows); the watchdog can no
  longer lose a row past the lock, bill a send $0 or exit 1; `--once` started in a minute's last
  2 s sleeps to :00 first; the heartbeat failure has its own message and a per-pid temp name.
- rules/cycle: a bool, NaN or wrong-typed answer field is `jev`/`parse` (the answer kept, no
  column), never a column; feed: a candle that is not finite and positive refuses the set.
- outcomes: the live decision speaks for its tick when two rows share it; ties in whole ms; a
  whole row glued onto a torn line is kept. book: null columns hold C too (SPEC §10; latent).

## Not changed on purpose (prereg-v2 notes)
- The digest's summary line on a promotion day replays arm B over every row of the day, v1 and
  v2 alike, while saying B is read from the v2 rows only; the digest's content is the treatment.
  Avoid promoting between 00:00Z and ~08:30Z.
- digest exits 4 only on a day with zero rows; a day of absences only still gets a Claude call.
- The digest's 120 bps "venue fee" line; Jev's "calm" = "not violent"; blocks that absorb a gap.
- SPEC §2 does not list the `unsigned` error kind; SPEC §11 says "the priced one wins" and the
  join now ranks the live row first (the rank matters only when two priced rows share a tick).
- An `unexpected` exception at the columns stage (not a TypeError/ValueError) still keeps the
  answers on the row, against SPEC §2's letter; pre-existing, untouched.

## Working from a cloud checkout
No `data/` there. `make test` is the gate (python3 on PATH; the Makefile falls back). Subagent
worktrees land under `.claude/worktrees/` (ignored; never `git add -A`). For a benchmark, a
28-day synthetic log is a small script over `tests/test_report.py`'s `_row` shape (the one this
session used lived in its scratchpad only); `make health` on 40k rows takes ~5 s here.

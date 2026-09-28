# HANDOFF — where the last session left off

Written 2026-09-28 by Claude (Fable 5.1) in a CLOUD session on branch `claude/cool-lamport-7sirtw`
(not merged; nothing here reaches the Mac until Alex merges to `main` and pulls). Supersedes the
2026-09-27 05:40Z handoff. Update this file at the end of every session that changes state.

## State
- The Mac's loop is untouched by this session (no `data/` here). Sample: `prereg-v1`, T0
  2026-09-25 21:40Z, ends 2026-10-23 21:40Z; day 3 of 28 on 2026-09-28. Arm B is v2 since
  2026-09-26 22:21Z. Spend ≈ $0.05 to date.
- This branch (`git log origin/main..`): 76 commits, `make test` green (448 tests) under 3.11-3.13 here and 3.12-3.14 in CI
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
   an empty temp directory (no repo CLAUDE.md; `~/.claude/CLAUDE.md` user memory still loads as
   it always has), fails the night if a CLAUDE.md sits above that directory, and logs the CLI
   version and the user-memory sha each night. Note: the CLI's own per-machine context (cwd,
   git status, memory paths) differs between the repo and an empty non-git directory, so the
   night this is deployed is itself a change of the model's context; record the date. (a) merge
   and `git pull` on the Mac before 08:30Z (recommended; merging the branch IS this option, and
   the CLI's per-project state for the repo path no longer reaches the night either); (b) leave it
   and record the deviation date here; (c) for prereg-v2, `--safe-mode` so the model sees
   PROMPT.md + digest only.
2. **A day with no live rows** (the Mac off all day, or all-HALT): stop rule 3's fill is 0/0,
   undefined. The report and dash now list every T0 day and flag such a day NO LIVE ROWS, never
   BAD by code. Decide before day 28: excluded whole, or kept (96 blocks of S_k = 0, no H2 unit).
3. **Duplicate priced ticks.** The join now lets the live decision speak for its tick (a later
   dry/double-fire row can no longer score it against a shifted window). Check the live log for
   any such duplicate: `python3 -c "from loop import outcomes;import collections;c=collections.Counter(r['tick_id'] for r in outcomes.load('data/decisions.jsonl') if r.get('mid'));print({t:n for t,n in c.items() if n>1})"`.
4. **Model pin for the nightly.** Nothing pins or records which Claude model writes the
   proposals; the CLI version is now logged per night. `--model` is a spending/treatment call.
5. **120 bps taker fee** still unverified in-account (`config.FEE_BPS_VENUE`).
6. **Counts to take on the Mac BEFORE merging** (numbers, never a statistic; no §4-§7 look), with
   the branch's `bin/readers-diff`, which reads the log with two trees and prints counts and
   tick_ids only:
   ```bash
   cd ~/Projects/jev-paper-loop && git fetch origin && rm -rf /tmp/old /tmp/new && mkdir /tmp/old /tmp/new && git archive origin/main loop | tar -x -C /tmp/old && git archive origin/claude/cool-lamport-7sirtw loop | tar -x -C /tmp/new && git show origin/claude/cool-lamport-7sirtw:bin/readers-diff > /tmp/readers-diff && /opt/homebrew/bin/python3 /tmp/readers-diff /tmp/old /tmp/new --log data/decisions.jsonl
   ```
   It prints rows read by each tree (a difference = a whole row glued onto a torn line, now
   kept), lines skipped, priced tick_ids with more than one row (item 3), live answered rows
   with both columns null, and the ticks whose joined outcome differs. Also: dry rows inside
   [T0, ...) (`grep -c '"mode": "dry"' data/decisions.jsonl` against the pre-T0 rows), the
   `parse`/`unexpected` jev-error counts in `make health`, and that sample rows since
   2026-09-26 22:21Z carry `prompt_b_sha` b3291ca4a550 (v2 read as UTF-8; another sha would
   mean the Mac read the file in another encoding, and the merge would change the question
   sent). Record them here. If every count is 0, the merge changes no existing reading.

## Merging and pulling on the Mac (Alex; the loop keeps running)
Each tick is a fresh process, so a pull between ticks is safe; a tick that imports during the
sub-second checkout would traceback and lose its minute (one row, never a wrong one). Not while
the nightly runs (08:30Z plus ~15 min, or at wake after a slept-through 03:30 local). `--ff-only`:
a diverged `main` or a dirty tracked file stops it cleanly, never half-way. One line, BSD-safe,
which waits for the current minute's heartbeat first, pulls, and runs the suite on the Mac (bash
3.2, the real caffeinate, the real TMPDIR) before the next 03:30:
```bash
cd ~/Projects/jev-paper-loop && launchctl print gui/$(id -u)/com.alexward.jevloop.nightly | grep -q 'state = running' && echo "nightly running: wait" || { git fetch origin && git status --short --untracked-files=no && git log --oneline origin/main..main; until [ "$(cut -c1-16 data/heartbeat)" = "$(date -u +%Y-%m-%dT%H:%M)" ]; do sleep 1; done; git pull --ff-only origin main && make test; }
```
A red suite there is a `git reset --hard ORIG_HEAD` decision (safe on a clean tree). No plist
needs reinstalling: the nightly plist's diff is comments only.

## Day 28 (`make results`, after 2026-10-23 21:55Z)
`loop.inference --sample` now refuses while the last block's H2 unit still waits for its t + h
row (~30 s after the sample ends normally, up to ~15.5 min when the last block's first live
row is in its last minute), refuses `--now`, another `--t0` or `--resamples` on the
live log, reads the log once and prints its sha/bytes/last tick, prints the stop rules and
§9's reading on lines of their own (VOID-prefixed under 21 kept days), and lists per kept day
the blocks with a live row. The draw is unchanged at 10,000 resamples (a verifier found old and new output
byte-identical on a 28-day synthetic log; tests/test_inference_golden.py pins the resampled
sequence against an independent transcription of PREREG §5, the lower bounds to 9-12 places).
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

## What the branch changes on the tick, the send and the readers
- jev: a 3xx is never followed with the bearer key (a redirect would have re-sent it, as a GET,
  to any host); a null `usage.input_tokens` reads 0 instead of throwing the paid answer away; a
  key file that is not UTF-8 is `no-key`; a ledger failure on the retry keeps attempt 1's billed
  kind; the locally refused request keeps no key-quoting context.
- cycle: a torn last line is closed before the next row (it cost two rows); the watchdog can no
  longer lose a row past the lock, bill a send $0 or exit 1; a fire at :59.9999 whose boundary
  passed between two clock reads no longer sleeps a whole minute; `--once` started in a minute's last
  2 s sleeps to :00 first, and only when the heartbeat shows this minute already has its row
  (a late fire keeps its minute); the heartbeat failure has its own message and a per-pid temp name.
- rules/cycle: a bool, NaN or wrong-typed answer field is `jev`/`parse` (the answer kept, no
  column), never a column; feed: a candle that is not finite and positive refuses the set.
- outcomes: the live decision speaks for its tick when two rows share it; ties in whole ms; a
  whole row glued onto a torn line is kept, and so is every whole row on a line that lost its
  newlines (one skip entry per such line). book: null columns hold C too (SPEC §10; latent).
- **The outcomes and book changes are READERS** (an auditor of the whole diff, 2026-09-28): every
  report, digest and inference run re-reads the whole log with them. On a tick with two or more
  rows, on a torn line with a whole row glued to it, or on an exact-millisecond tie, `join`/`load`
  return a different outcome or row than main did, and that moves the digest (the treatment),
  report §1's stop-rule-3 fill and the day-28 H1/H2 inputs for those ticks only. Each moves toward
  SPEC §11 / PREREG §5's words; each is a no-op when the counts of decision 6 are 0. New-row
  changes for rare replies (a null token count is now an answered row; a bool or non-finite
  field is now jev/parse; a NaN or zero candle is now a feed absence; the watchdog at the
  columns stage is now jev/watchdog) are SPEC §2/§3/§9/§12 errata for after the sample.

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
- `jev.error: "watchdog"` is now also written when the alarm lands while the answer becomes
  columns (SPEC §2 defines it as "inside the send"); such a row has `input_tokens > 0` and no
  answers. A SPEC erratum for after the sample.
- `propose.sh --dry` now needs `--root DIR` outside the repo; a HALT night leaves the json
  without a table, and the log names the by-hand `policy_table` command for once HALT is cleared.
- **Two sentences of the sealed documents do not hold, and the code follows their formal
  definitions** (found by tests/test_invariants.py's independent references, 2026-09-28):
  PREREG §3's "Forced holds contribute 0.0; a block with no live row has S_k = 0" fails wherever
  the arms hold different positions across a priced forced row (HALT, a jev or guard absence, a
  dry row): SPEC §10 carries the position and marks it to that row's mid, so a HALT-only block
  has S_k = the arms' difference in marks, and H1 counts those marks (on a 28-day synthetic log,
  58 of 72 such blocks were non-zero; mean S_k(B−C) −0.7772 bps as defined vs −0.7252 if the
  sentence held). SPEC §10's "d_t is exactly 0.0 on any tick both arms carry the same qty into
  and out of" fails when two live decisions share a minute and an arm round-trips inside it (the
  fold §10 itself prescribes); report._disagreement does not count that tick, H1 is unaffected.
  Both are for the write-up or prereg-v2; nothing in code changes.

## Working from a cloud checkout
No `data/` there. `make test` is the gate (python3 on PATH; the Makefile falls back). Subagent
worktrees land under `.claude/worktrees/` (ignored; never `git add -A`). For a benchmark,
`python3 tests/synth.py --days 28 --seed 1 --out FILE` writes a 28-day synthetic log in the
writer's exact row shape (knobs in its docstring: holes, torn and glued lines, duplicate ticks,
an out-of-alphabet word, a promotion day; ~6 s, 41k rows, 81 MB); `make health` on it takes
~5 s here. tests/test_invariants.py holds the readers to independent transcriptions of SPEC
§10-§11 and PREREG §3-§5 on twelve seeded logs.

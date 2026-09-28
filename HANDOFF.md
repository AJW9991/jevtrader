# HANDOFF — where the last session left off

Written 2026-09-28 ~21:50Z by Claude (Fable 5.1) on Alex's Mac, the session that PULLED the cloud
merge onto the Mac. Supersedes the cloud session's handoff of 2026-09-28 (branch
`claude/cool-lamport-7sirtw`, merged to `main` by fast-forward at 183db6b); its record of what the
branch changed is kept below unchanged. Update this file at the end of every session that changes
state; whichever session ends last pushes.

## State
- **The Mac runs 183db6b since 2026-09-28 21:31:50Z.** `git pull --ff-only` between ticks (heartbeat
  21:31:06Z, next tick 21:32:00Z wrote its row; no traceback); `make test` on the Mac: 836 tests,
  OK (2 skipped), 36 s, python 3.14. No plist reinstalled (both diffs are comments only).
- Sample `prereg-v1`, T0 2026-09-25 21:40Z, ends 2026-10-23 21:40Z; **d03 of 28** open at 21:34Z.
  `make status`: d01 95.2 % fill (kept), d02 100 % (skip 9, all before the 05:18Z plist swap), d03
  100 % so far, skip 0, jev-err 0.6 % (7 http-5xx, 2 timeout); BAD days 0; no exclusions file;
  HALT absent; 5,066 rows; spend $0.034 today of the $0.25 tripwire, ≈ $0.09 since T0. Arm B is
  v2 (sha b3291ca4a550…) since 2026-09-26 22:21Z; every v2 row carries that sha. Mac on AC, 100 %.
- **Counts of the cloud's decision 6, taken on the Mac BEFORE the pull** (`bin/readers-diff`, old =
  09e867f, new = 183db6b, over data/decisions.jsonl at 5,062 rows): rows read 5062/5062; lines
  skipped 0/0; rows recovered from torn lines 0; live answered rows with both columns null 0;
  **ticks whose joined outcome differs 0**; dry rows in the sample 0; `prompt_b_sha` of the v2
  rows = exactly one, b3291ca4a550…. So the merge changed no existing reading. Priced tick_ids
  with two rows: 3 — `20260924T172000Z` and `20260924T181600Z` (shakedown, before T0) and
  `20260927T051800Z` (the minute the loop plist was swapped: both plists fired). Same outcome
  under both trees.
- **Nights.** 2026-09-27 08:30Z (digest of 09-26, 606 ticks): `claude -p` produced nothing and was
  killed at the 2700 s cap (logs/claude-2026-09-26.err: "exceeded 2700 s awake; killed";
  claude-2026-09-26.txt empty). No proposal exists for 2026-09-26. Cause narrowed, not found: the CLI's
  own transcript of that call (~/.claude/projects/-Users-alexanderward-Projects-jev-paper-loop/1cb1f730*.jsonl)
  shows the prompt dequeued at 08:30:07Z and the user turn assembled only at 09:15:06Z, when the cap's
  SIGTERM landed — a 45 min stall BEFORE prompt assembly; the repo was clean at 5d23fbb with no CLAUDE.md,
  so the repo CLAUDE.md is ruled out. Note for the write-up: every pre-pull night's call ran with cwd = the
  repo, so its context carried the CLI's git status and the five latest commit subjects; from 09-29 it does not. 2026-09-28 08:30Z (digest of
  09-27, 1435 ticks): exit 0 after 75 s; `proposals/2026-09-27.{json,md}` (committed): cand_0
  differs from CURRENT on 7 of 81 states, cand_1 on 9; both tighten `buy` on `trend pumping, vol
  normal` (the digest's top disagreements were 1.00-confidence buys there that went down). Not
  promoted: v2 keeps its 28 days (Do not). **Tonight, 2026-09-29 08:30Z, is the first night under
  the pulled code**: the call runs from an empty temp directory (no repo CLAUDE.md), logs the CLI
  version, the user-memory sha and `claude model <id>`. Record what it does.
- Added this session: ERRATA.md SPEC §10 row for the **verified venue fee: 90 bps taker** (Alex,
  in-account, 2026-09-27 ~22:55Z; tier Intro, maker 0.50 %); `config.FEE_BPS_VENUE` stays 120
  through the sample (the digest prints pnl at it; the treatment). `AGENTS.md -> CLAUDE.md`.

## Decisions for Alex
1. ~~The slow model's context~~ **done as (a)** by the pull; first night 2026-09-29 08:30Z.
2. **A day with no live rows** (Mac off all day, or all-HALT): stop rule 3's fill is 0/0. The
   report and dash flag such a day NO LIVE ROWS, never BAD by code. Decide before day 28: excluded
   whole, or kept (96 blocks of S_k = 0, no H2 unit). None has happened.
3. ~~Duplicate priced ticks~~ checked: the three above; the join's outcome is the same either way.
4. Nightly model **recorded, not pinned** — in force from the 09-29 night. Pinning with `--model`
   stays a prereg-v2 treatment/spending decision.
5. ~~120 bps taker fee~~ **verified 90 bps** (ERRATA.md §10). Whether prereg-v2 sets 90 is yours.
6. ~~Counts before pulling~~ taken; all zero (above).
7. ~~2026-09-26 likely BAD~~ Under the T0-anchored days you decided on 09-26, d01 (09-25 21:40Z →
   09-26 21:40Z) closed at 95.2 % and is kept; the UTC day 09-26 at 90.2 % is not a unit of the
   sample. No exclusions line is due. (`make status` shows the table each morning.)
8. **The missed 2026-09-26 proposal.** `nightly/propose.sh --date 2026-09-26` would digest that day
   (data/digest-2026-09-26.md exists, 606 ticks) and make one `claude -p` call (a spend, ~1-2 min
   on the 09-28 evidence, 45 min cap). Options: (a) run it by hand once, outside 00:00-08:30Z and
   never while the loop's tick is writing (it is a separate process; the nightly's 81 sends have
   their own HALT check); (b) leave the slot empty and let the write-up say one night of 28 produced
   no proposal. Nothing in PREREG requires a proposal every night; promote is yours either way.

## Approved 2026-09-28 ("approved for recommended on all")
- The nightly model is recorded, not pinned: decision 4.
- The 81-state table: under each candidate's counts, where it changes CURRENT's answer (per
  adjective, changed / answered states, and the CURRENT -> candidate moves), for the person who
  promotes; the digest never carries a table. Tables built before 2026-09-28 lack it (the 09-27
  table was built by the pre-pull code and lacks it too). It says which states moved, not whether
  the move follows the wording's criteria: that stays your read.
- Report §4.5: the H1 cell by arm B's prompt version, one row per contiguous stretch of a version
  (a rollback's return is `<version> #2`). Descriptive, not in PREREG, and withheld with §4-§7
  until day 28; read it beside, never instead of, the H1 statistic.

## Pulling on the Mac (done 2026-09-28; the procedure, for the next merge)
Take the counts of decision 6 first (`bin/readers-diff OLD NEW --log data/decisions.jsonl` with
`git archive` copies of `loop/`). Each tick is a fresh process, so a pull between ticks is safe;
a tick that imports during the sub-second checkout would traceback and lose its minute (one row,
never a wrong one). Not while the nightly runs (08:30Z plus ~15 min, or at wake after a
slept-through 03:30 local). `--ff-only`: a diverged `main` or a dirty tracked file stops it
cleanly, never half-way. One line, BSD-safe, which waits for the current minute's heartbeat,
pulls, and runs the suite on the Mac (bash 3.2, the real caffeinate, the real TMPDIR):
```bash
cd ~/Projects/jev-paper-loop && launchctl print gui/$(id -u)/com.alexward.jevloop.nightly | grep -q 'state = running' && echo "nightly running: wait" || { git fetch origin && git status --short --untracked-files=no && git log --oneline origin/main..main; until [ "$(cut -c1-16 data/heartbeat)" = "$(date -u +%Y-%m-%dT%H:%M)" ]; do sleep 1; done; git pull --ff-only origin main && make test; }
```
A red suite there is a `git reset --hard ORIG_HEAD` decision (safe on a clean tree).

## Day 28 (`make results`, once the log holds the 2026-10-23 21:56 tick, by ~21:58Z)
`loop.inference --sample` now refuses while the last block's H2 unit still waits for its t + h
row (~30 s after the sample ends normally, up to ~15.5 min when the last block's first live
row is in its last minute), refuses `--now`, another `--t0` or `--resamples` on the
live log, reads the log once and prints its sha/bytes/last tick, prints the stop rules and
§9's reading on lines of their own (VOID-prefixed under 21 kept days), and lists per kept day
the blocks with a live row, and recomputes stop rule 3 from the log beside the exclusions file
(BAD, open, no live rows, judged fine: a listed day the rule would not exclude, or a BAD day not listed,
is named; no number changes). d28 closes with the tick at 21:56Z; before it, d28 reads open. The draw is unchanged at 10,000 resamples (a verifier found old and new output
byte-identical on a 28-day synthetic log; tests/test_inference_golden.py pins the resampled
sequence against an independent transcription of PREREG §5, the lower bounds to 9-12 places).
A full run on a 28-day synthetic log takes about a minute here.

## Tooling (all in the Makefile)
`make test` · `make test-modes` (the six CI modes; one with `make test-mode MODE=...`) · `make status` (the morning check: heartbeat age, HALT, last row, today's spend vs
the tripwire, sample day, last days of the stop-rule table, the exclusions file as day 28 will
read it, newest proposal + MISSING flag, tail of propose.log) · `make health` (report §1-§3 on the sample; `make report --health` never worked)
· `make report` (withholds §4-§7 on sample rows until 2026-10-23 21:40Z; `--unblind` is a look
and says so) · `make dash` · `make inference-smoke` · `make results` (day 28; refuses before).

## Watch
- Report §1 per-day table: d28 now closes; a NO LIVE ROWS day is a decision (above).
- Each morning: `make status`. The MISSING flag means the nightly's slot passed with no proposal;
  it waits until 11Z, because from 2026-11-01 (CST) the night starts 09:30Z and its call may run
  45 min, to 10:15Z.
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
  whole row glued onto a torn line is kept, and so are whole rows that lost their newlines (read
  forward from the line's start; after a torn row only pieces with the writer's keys, so an object
  nested in a row is never a row; one skip entry per line; linear in the line however deeply a torn
  row nests objects, row-like or not: one parse per value read and at most two that fail). book: null columns hold C too (SPEC §10; latent).
- **The outcomes and book changes are READERS** (an auditor of the whole diff, 2026-09-28): every
  report, digest and inference run re-reads the whole log with them. On a tick with two or more
  rows, on a torn line with a whole row glued to it, or on an exact-millisecond tie, `join`/`load`
  return a different outcome or row than main did, and that moves the digest (the treatment),
  report §1's stop-rule-3 fill and the day-28 H1/H2 inputs for those ticks only. Each moves toward
  SPEC §11 / PREREG §5's words; each is a no-op when the counts of decision 6 are 0. New-row
  changes for rare replies (a null token count is now an answered row; a bool or non-finite
  field is now jev/parse; a NaN or zero candle is now a feed absence; the watchdog at the
  columns stage is now jev/watchdog) are SPEC §2/§3/§9/§12 errata for after the sample.

- nightly/capped.py: the capped claude call runs in its own process group, and the cap ends the
  whole group (a helper the CLI forked no longer outlives it); SIGTERM, SIGINT and SIGHUP sent to
  capped (and SIGQUIT) are passed on to that group, and whatever the command leaves running is
  ended when it exits (launchd's cleanup of the job's group no longer reaches it). The one cost:
  if capped itself were SIGKILLed (a bootout whose SIGTERM went unanswered for launchd's 20 s),
  the call would outlive it; ^Z at a terminal stops capped, not the call. Exit codes unchanged.

- Found by a six-lens bug hunt (66 agents, each finding refuted or confirmed by three skeptics),
  2026-09-28, each fixed with a test: the spend guard trips (HALT) on a log that exists but cannot
  be read, where it counted $0 and sent (a 0200 log keeps taking rows); venue garbage nested past
  the parser's depth or past a float's range is a `feed` absence, not `guard`; the digest skips a
  jev/parse row whose choice is a list or dict instead of losing the night (every digest that
  rendered before is byte-identical); a row stamped after the clock closes no day of the stop-rule
  table; the dash shows the skipped-lines count and draws a day without rows as empty cells;
  propose.sh's path guard sees the forbidden tree through a symlinked HOME; the exclusions parser
  takes the tab form or PREREG's two-space form (single spaces, a tab line without its four fields,
  a fill% or jev-err% that is not a value, a reason that begins with a number standing apart, and a
  first line that is neither the header nor a day are refused, with file:line; decision 7) and
  `make status` prints the parsed exclusions (or REFUSED) every morning. A NaN confidence in the
  digest's filter is an ERRATA entry (the treatment).

- Found by the fourth round and its two fix rounds (2026-09-28), each fixed with a test that failed
  before: the day-28 pending refusal waits for the last row stamped at or before the clock (a row
  stamped after it no longer lifts it), and so do the health readers; report §1 and the dash sum
  token counts without overflowing and name as uncounted only a count the spend guard trips on; `--since` in ISO week form
  works; the spend HALT and the status screen name an uncounted total; propose.sh knows the
  forbidden tree by identity (a case-only name, the firmlink, a bind mount), writes only under the
  --root it checked, refuses a newline in --root or the cwd, and runs every python before `cd` isolated;
  readers-diff survives a full disk, an ignored or repeated signal, and cleans up; the dash strip
  draws a long outage, hours not yet begun, and a HALT hour as what they are, and a sum past a
  float's range never stops the page; the loop plist is well-formed XML (comments only) and both
  plists are read strictly in the suite; the outcomes rescue is bounded.

## Not changed on purpose (prereg-v2 notes)
Every disagreement between the sealed documents and the code, in one table per document: ERRATA.md.
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
an out-of-alphabet word, a promotion day; ~6 s, 41k rows, 81 MB); `python3 -m loop.report --health --sample --log FILE`
on it takes ~5-7 s here (`make health` reads only data/decisions.jsonl). tests/test_invariants.py holds the readers to independent transcriptions of SPEC
§10-§11 and PREREG §3-§5 on twelve seeded logs.

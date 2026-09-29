# HANDOFF — the repo's dated record

**Mac only from 2026-09-29** (Alex). The baton — where the last session left off, what the next one does,
what waits on Alex — is the brain's block, `~/Projects/Claude/state/blocks/jev-paper-loop.md`, and
only that. This file is the record that outlives a block: decisions with their dates, the procedures
(pulling a merge, day 28), the treatment-context notes and the prereg-v2 notes for the write-up. It
changes when a decision or a procedure lands, not at every session end. The GitHub remote stays as
the off-machine copy of the code and for CI; push after a commit, expect no cloud session to read it.
The cloud session of 2026-09-28 (branch `claude/cool-lamport-7sirtw`) is fully merged at 183db6b and
nothing is pending there; its record of what the branch changed is kept below unchanged.

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
- **What tonight's log should show** (logs/propose.log; the cloud session's note): before the call,
  `claude cwd <TMPDIR>/jevloop-claude.XXXXXX (empty); user memory ~/.claude/CLAUDE.md sha256 <12 hex>
  (or absent); cli <version>`; after it, `claude model <id>`, read from the CLI's own transcript of the
  call, which now lands in `~/.claude/projects/<that temp cwd as a slug>/`: one small directory per
  night from now on (the pre-pull nights shared the repo's). `claude model unrecorded` means no
  transcript was found (CLAUDE_CODE_PROJECT_DIR_NAME set, or a cwd path past 200 characters, which the
  CLI cuts and hashes); the night goes on either way. The table gains `proposal written by: <id>` in
  its header and, per candidate, the "where it changes CURRENT's answer" block. On the 09-27 stall:
  tonight's call is the first without the repo as its cwd (no git status, no commit subjects, no repo
  CLAUDE.md in its context), so a stall tonight would rule the repo context out altogether.
- Added this session: ERRATA.md SPEC §10 row for the **verified venue fee: 90 bps taker** (Alex,
  in-account, 2026-09-27 ~22:55Z; tier Intro, maker 0.50 %); `config.FEE_BPS_VENUE` stays 120
  through the sample (the digest prints pnl at it; the treatment). `AGENTS.md -> CLAUDE.md`.
- Added 2026-09-29 ~04:15Z (Mac session): **backup tooling** — `bin/backup-data` (rsync of data/ and
  logs/ to the iCloud Drive folder jevtrader-backup; refuses the repo, the crypto repo, an ancestor, a
  newline), `launchd/com.alexward.jevloop.backup.plist` (hourly at :45; pinned in tests/test_nightly.py),
  `make backup`, tests/test_backup.py; 840 tests green on the Mac. **The first copy and the install are
  Alex's (STEPS §9); until then the sealed sample still exists once.** A `--dry --root <scratch>` run of
  `nightly/propose.sh --date 2026-09-26` over a copy of the log succeeded (digest 606 ticks, fixture
  proposal, dash; the repo untouched), so decision 8's by-hand rerun is proven up to the claude call and
  the 81 sends. A one-shot check of tonight's night is scheduled in the Mac session for 09:21Z (past the
  45 min cap); it records the comparison against the bullet above, here.

## Decisions for Alex
1. ~~The slow model's context~~ **done as (a)** by the pull; first night 2026-09-29 08:30Z.
2. ~~A day with no live rows~~ **decided by Alex 2026-09-29 ~04:25Z: excluded whole, like a BAD day.** The
   morning after such a day he writes its `dNN` line in data/exclusions.tsv (the report and dash flag it
   NO LIVE ROWS; kept days must still reach 21 or the block is VOID). None has happened. For the write-up
   and prereg-v2 §8.3.
3. ~~Duplicate priced ticks~~ checked: the three above; the join's outcome is the same either way.
4. Nightly model **recorded, not pinned** — in force from the 09-29 night. Pinning with `--model`
   stays a prereg-v2 treatment/spending decision.
5. ~~120 bps taker fee~~ **verified 90 bps** (ERRATA.md §10). Whether prereg-v2 sets 90 is yours.
6. ~~Counts before pulling~~ taken; all zero (above).
7. ~~2026-09-26 likely BAD~~ Under the T0-anchored days you decided on 09-26, d01 (09-25 21:40Z →
   09-26 21:40Z) closed at 95.2 % and is kept; the UTC day 09-26 at 90.2 % is not a unit of the
   sample. No exclusions line is due. (`make status` shows the table each morning.)
8. ~~The missed 2026-09-26 proposal~~ **decided by Alex 2026-09-29: the slot stays empty.** One night of
   28 produced no proposal (the 09-27 08:30Z call stalled and was capped); the write-up says so. The
   by-hand command stays in git history (a5c225e) should a later night need it.
9. **The backup under launchd.** First copy taken by Alex 2026-09-29 04:12Z (`make backup`: 11,255,319
   bytes to iCloud Drive `jevtrader-backup`). The plist is installed and its first run FAILED: TCC denies a
   launchd job the iCloud folder (`rsync: open: Operation not permitted`), the terminal has the grant. STEPS
   §9 has the two ways out: Full Disk Access for `/usr/bin/rsync` then `launchctl kickstart`, or a daily
   `make backup` beside `make status` and bootout the hourly job. Until one is done the job writes a FAIL
   line every hour and the iCloud copy is the 04:12Z one.

## Prereg-v2 (drafted 2026-09-29, blind by procedure; Alex: "approved for all recommended choices")
`PREREG-v2.md` is the second block's pre-registration; tag `prereg-v2-doc` (467cda4) marks the text
after a five-lens Opus review (114 findings, refuted one by one; 6 blockers, 14 majors, 18 minors) and
its recheck (15 partial items, 1 blocker, 9 majors, 14 minors), all applied. Design: one primary
(B − C pooled over products, decided once per 15-minute block, α 1/40), family F of four (60- and
240-minute holds, A − C, B − A; α 1/160 each, `sorted[62]`), arm A frozen at the v2 wording rendered
per product, arm D the wording's own table (no call), `liq` in spread ticks (SOL: deep < 1.5, thin
> 4.5 half-ticks; 16.5 / 77.1 / 6.4 %), direction nouls descriptive, fees 50/90, the nightly pinned to
a model id with no user memory, promotions on days 8/15/22 at most, activation at day boundaries,
`PAUSE.<product>` beside the global HALT, `exclusions-v2.tsv` with the recomputed rule governing,
each arm's break-even fee as the money arithmetic. Three tags: `prereg-v2-doc` (done) →
`prereg-v2-draft` (build complete and pinned on branch `prereg-v2`, BEFORE `make results` 10-23) →
`prereg-v2-seal` (after the switch, by `bin/seal-check`). §13 bounds what `main` may take between
tags; §14 logs every edit after the doc tag. The code is built in the worktree
`~/Projects/jev-paper-loop-v2` (no `data/`): `bin/fill1k-quantiles` and `bin/probe` exist (branch at
4437076+); the rest of §10 follows. **Probe day D = 2026-09-30 UTC** (starts 19:00 Chicago 09-29):
`bin/probe run` from the worktree under `caffeinate -i`, public GETs only, 1 req/s, nothing under
data/. **Alex's blanks before the draft tag:** the header's disclosure line (did he open a digest or
nightly transcript directly before 09-29), the probe approval date (§2). The model id fills §8 from
the 2026-09-29 08:30Z night's `claude model` line. **Probe armed 2026-09-29 ~07:40Z** (Alex approved
~07:00Z; Claude started it): `caffeinate -i python3 bin/probe run --day 2026-09-30 --out probe/2026-09-30` from
the worktree, sleeping until 00:00:30Z 09-30, then one row per candidate per minute until the day ends;
`bin/probe volume --day 2026-09-30` on 10-01, then `summarize`. **The §10 build runs as a seven-stage Opus
workflow in the worktree** (tick → readers → inference → nightly → tools → docs+pins → whole-branch verify),
each stage built, refuted and fixed; its choices land in §14 and its commits on branch `prereg-v2` (pushed by
the Mac session; CI runs on every push). Alex's disclosure and probe-approval blanks are filled (§14).

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

## Known residuals (the cloud session's, left by choice; none on the normal path)
Each is also written where it lives (docstring, test or commit message).
- Exclusions parser: five typos it cannot tell from a good line. The two-space `d1  6  80.0 ...`
  reads as d01; so does a tab typed inside the day of a line that also leaves out its fill% or
  jev-err%, a jev-err% without its % run straight into the reason (`0.0Mac`), a whole jev-err%
  joined by one point to a reason that begins with a number (`0` + `.3h`), and `n/a` run into a
  word. `make status` prints the parsed days each morning and day 28 recomputes rule 3 beside them.
  A byte-order mark or a blank line before the header is refused, loudly.
- Path guard: a second name with a device of its own (an overlay, an NFS or SMB loopback, a FUSE
  mirror such as bindfs) or a second name for a directory inside the forbidden tree is not
  recognised; none exists on the Mac as set up.
- Report: a NaN `input_tokens` is named nowhere in §1; §4.5's block count still counts a row
  stamped after the clock (withheld until day 28).
- Dash: a foreign log's 1e308 latencies print `mean inf ms` (cosmetic); a path that is not UTF-8
  prints as `?` (Linux only).
- Tests: the readers-diff SIG_DFL guard misses a handler that is not a plain function in the tool's
  file (a `functools.partial`); the strict plist read does not see a character reference (`&#32;`)
  or a CDATA section between elements, which Apple's reader refuses.

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
- `tests/test_frozen.py` pins SPEC, PREREG, PROMPT.md, prompts/v1 and v2, the config thresholds a row
  depends on, the alphabet and arm C, by bytes or by value: re-sealing PREREG for prereg-v2, or any
  erratum applied to those after the sample, fails it by design; update the pin in the same commit.
  `FEE_BPS_VENUE` is not pinned (a descriptive column), so setting the verified 90 does not touch it.
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

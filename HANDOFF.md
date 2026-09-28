# HANDOFF — where the last session left off

Written 2026-09-27 05:40Z by Claude (Fable 5.1) on Alex's Mac; supersedes nothing (the brain's
`state/NOW.md` on the Mac holds the same block). Update this file at the end of every session
that changes state; it is the baton a cloud session picks up.

## State
- HEAD on `main` is green: 287 tests, tree clean. Loop healthy under launchd on the Mac since
  2026-09-24; **since 2026-09-27 05:18Z it fires every calendar minute** (`StartCalendarInterval`,
  Alex installed) instead of every 60 elapsed seconds, which had skipped ~28 minutes a day.
- Sample: `prereg-v1`, T0 2026-09-25 21:40Z, ends 2026-10-23 21:40Z, day 2 of 28. Days are
  T0-anchored (`dNN`, 96 blocks each; decided by Alex 2026-09-26 before any look). d01 closed at
  95.2 % fill and is kept; BAD days 0; no `data/exclusions.tsv`.
- Arm B is **v2** since 2026-09-26 22:21Z (Alex promoted cand_2 of `proposals/2026-09-25.json`:
  every `vol violent` state is hold instead of sell; 27 of 81 states). A and C stay identical
  by construction (v1 restates the rule), so H1 lives in B−C.
- Spend ≈ $0.05 to date at $0.042/Mtok. Key: the loop's own (`typesafe-api-key-loop`).
- The nightly runs 03:30 America/Chicago (`nightly/propose.sh`): digest → one `claude -p`
  (capped 45 min awake) → `proposals/<date>.json` → 81-state policy table → `data/dash.html`.

## Decisions Alex made 2026-09-26/27 (all implemented)
T0-anchored days · build the day-28 inference now, blind (`loop/inference.py`) · nightly
rebuilds the dash · loop plist on calendar minutes · battery stays a habit (AC, lid open; no
pmset change) · three test-only knobs `JEVLOOP_CLAUDE / _TOKEN_FILE / _CLAUDE_CAP_S` ·
`nightly/settings.json` Edit-only deny rules · fan-outs on Opus.

## Tooling
`make test` · `make report` (never before day 28 without `--health`) · `make dash` →
`data/dash.html` (report §1–§3 only) · `make inference-smoke` (PREREG §4–§5 on the pre-T0
rows) · day 28: `python3 -m loop.inference --sample --out RESULTS.md`, committed beside
PREREG (§10) · `bin/promote proposals/<date>.json <k>` (Alex; the committed `.md` names the
json's sha and promote checks it).

## Watch
- Report §1 per-day table: d02 should close ≥ 95 % with `skip` 0 after 05:18Z on 09-27.
- Each morning: `ls proposals/`, `tail logs/propose.log`; the 2026-09-27 digest says
  "prompt_b v1 507, v2 …; arm B read from the v2 rows only". Do not promote again without a
  reason the table shows; v2 needs its 28 days.
- The Mac must stay on AC, lid open: on battery it sleeps within a minute (2026-09-26 lost
  840 minutes, 0.2 points from a BAD day).

## Alex's open items
- Verify the 120 bps Coinbase taker fee in-account (descriptive column, `config.FEE_BPS_VENUE`).

## Not changed on purpose (prereg-v2 notes)
- The digest's 120 bps "venue fee" line steers the slow model toward churn while H1 is at
  0 bps gross; PROMPT.md/digest are the treatment, so they stay.
- Jev reads "volatility is calm" as "not violent" (81/81, 2026-09-25 table): a calm-vs-normal
  rewrite changes no answer. Judge candidates by their table.
- Blocks that absorb a gap longer than the horizon (SPEC §10 marks the move on the first priced
  tick after it); the inference prints their count.
- PROTOCOL §3.8's wording (the spend tripwire sees the loop's sends only; the nightly's 81
  have their own HALT check). `cycle.write_row` after a torn last line (low).

## Working from a cloud checkout
There is no `data/` there. Code, tests and docs are the whole surface: `make test` is the
gate; use `fixtures/` for shapes. For anything about the live run (fill, skips, spend, the
nightly's output) ask Alex for `make report --health`, `data/dash.html`, or a `data/` snapshot;
do not add the loop's data to git without his decision (PROTOCOL §3: own store).

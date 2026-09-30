# jev-paper-loop ("JevTrader") — working rules for any Claude session

A paper-only, forward-only measurement: does a nightly rewrite of one typed question make a
fast model (Jev, TypeSafe System One) decide better than the rule its thresholds imply?
Three arms once a minute on Coinbase SOL-USD (A frozen v1, B the rewritten CURRENT, C the
no-model rule), a nightly Claude proposal, a person promotes. Read `PROTOCOL.md` (the eleven
conditions), `PREREG.md` (sealed `prereg-v1`, T0 2026-09-25 21:40Z, sample ends 2026-10-23
21:40Z), `SPEC.md` (what a row means), `CONTRACT.md` (module interfaces), `STEPS.md` (what a
person installs), and `HANDOFF.md` (the dated record: decisions, procedures, write-up notes). Where the
last session left off is the brain's baton block, `~/Projects/Claude/state/blocks/jev-paper-loop.md`;
Mac only from 2026-09-29, the GitHub remote is the code's off-machine copy and CI.

## Two blocks
v1 (`PREREG.md`, sealed) runs until 2026-10-23 21:40Z on this Mac; v2 (`PREREG-v2.md`, frozen by tag
`prereg-v2-draft` before v1 is read, sealed by `bin/seal-check`) starts at T0_v2 after the switch (STEPS §10).
Until the switch the rules below are v1's; from the switch, read them with PREREG-v2's names: the day-14 look is
`make health`, the day-28 reading `make results`, the frozen set is `tests/test_frozen.py`'s, and the baton is the
brain's block. Nobody reads report §4–§7 over either block's sample rows before its day 28.

## What must not change during the sample (until 2026-10-23 21:40Z)
- `SPEC.md` (every row carries its sha), `prompts/` (only `bin/promote`, run by Alex, writes
  there), `nightly/PROMPT.md` and the digest's content (the treatment under H1), every
  threshold in `loop/config.py`, the state alphabet, arm C's rule, the H1/H2 definitions.
- Anything that alters what an existing row means. Additive tooling, tests, guards that only
  prevent a crash or a wrong row, report lines, the dashboard: fine.
- Nobody reads report §4–§7 (H1, H2, pairs, calibration) before day 28. The day-14 look is
  `python3 -m loop.report --health --t0 20260925T214000Z` and nothing else.

## Where things run
- The loop and the nightly run on Alex's Mac under launchd (`launchd/*.plist`, hand-installed).
  `data/` (the decision log, ledger, heartbeat, dash) and `logs/` live only there and are
  gitignored; a cloud or other checkout has code, docs, fixtures and tests, not data.
- In a checkout without `data/`: `make test` (offline, ~60 s; CI runs it on every push, Linux 3.11-3.14 and macOS, and in six modes: `make test-modes`) is the whole gate;
  `make dry` needs the network (three public GETs); `make report`/`make dash`/`make status` read
  the log (without one: "no log", an empty page); `make inference-smoke`/`make results` exit 2 without it.
- Nothing here sends to api.typesafe.ai except `loop/jev.py::ask`; the ledger row comes first;
  `data/HALT` stops sends; a 401/403 writes it. Never run `make run` outside the Mac.
- Never touch `~/Projects/crypto-trading-system` or its mirror (path guard, exit 3).

## Acts that are Alex's, not Claude's
`bin/promote`; installing or booting out a plist; a line in `data/exclusions.tsv` (stop rule 3,
T0-anchored day `dNN`); clearing `data/HALT`; pmset or any system setting; spending decisions.
Put such decisions to him as options.

## Conventions
- Python 3.14 (`/opt/homebrew/bin/python3` on the Mac), standard library only, `unittest`.
- Every change with a test; `make test` green before a commit; one concern per commit; commit
  messages say what and why in plain prose. No test depends on what the live
  `prompts/CURRENT` names (`tests/fixture_prompts.pin_v1`; one test checks it builds, whatever it names).
- Report every Jev-side finding by its table, not its wording (Jev reads "volatility is calm"
  as "not violent": `proposals/2026-09-25.review.md`).
- Fan-outs (reviewers, verifiers) run on Opus; the main loop and synthesis on the session model.

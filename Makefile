# The commands STEPS.md and HANDOFF.md name. Standard library only; nothing here installs anything.
# `dry` is free (three public Coinbase GETs, no key, no ledger row, no send). `run` SENDS
# to Jev once a minute: only after STEPS.md steps 0 (PROTOCOL signed) and 1 (loop key), and
# only on the Mac (CLAUDE.md). `test` is the whole gate anywhere else.
# PY is the Mac's Homebrew python (3.14) when it exists; a checkout without it (a cloud session,
# CI) uses the python3 on PATH. `make PY=... test` overrides either.
PY ?= $(shell test -x /opt/homebrew/bin/python3 && echo /opt/homebrew/bin/python3 || command -v python3)

.PHONY: test dry run report health dash status inference-smoke results

test:
	$(PY) -m unittest discover -s tests

dry:
	$(PY) -m loop.cycle --dry --once

run:
	$(PY) -m loop.cycle --forever

# `make report` on rows of the sealed sample prints sections 1-3 only until 2026-10-23 21:40Z:
# nobody reads §4-§7 before day 28 (CLAUDE.md); `python3 -m loop.report --unblind` is a look.
report:
	$(PY) -m loop.report

# PREREG §8.4's health look, T0 from PREREG.md §11: `python3 -m loop.report --health --sample`
# (the same as `--health --t0 20260925T214000Z`; `make report --health` never worked: make
# takes the flag as its own).
health:
	$(PY) -m loop.report --health --sample

# health only (report §1-§3 + the nightly's synthetic tables) as one HTML file, data/dash.html
dash:
	$(PY) -m loop.dash

# the morning check in one screen: heartbeat age, HALT, the last row, today's spend against the
# tripwire, the sample day, the last days of the stop-rule-3 table, the newest proposal, the tail
# of logs/propose.log. Health only (report §1), like dash.
status:
	$(PY) -m loop.status

# PREREG §4-§5's inference on the rows BEFORE T0 (the shakedown): a smoke of the procedure, never a
# result. The sample form, `python3 -m loop.inference --sample --out RESULTS.md`, refuses until day 28.
inference-smoke:
	$(PY) -m loop.inference --pre-t0

# Day 28 (2026-10-23 21:40Z or later; loop/inference.py refuses before then, exit 3): the one run of
# PREREG §4-§5 on the sample, written to RESULTS.md and committed beside PREREG.md (§10). By hand,
# once; the stop rules (PREREG §8) are read from its output.
results:
	$(PY) -m loop.inference --sample --out RESULTS.md

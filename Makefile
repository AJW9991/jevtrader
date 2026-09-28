# The commands STEPS.md and HANDOFF.md name. Standard library only; nothing here installs anything.
# `dry` is free (three public Coinbase GETs, no key, no ledger row, no send). `run` SENDS
# to Jev once a minute: only after STEPS.md steps 0 (PROTOCOL signed) and 1 (loop key), and
# only on the Mac (CLAUDE.md). `test` is the whole gate anywhere else.
# PY is the Mac's Homebrew python (3.14) when it exists; a checkout without it (a cloud session,
# CI) uses the python3 on PATH. `make PY=... test` overrides either.
PY ?= $(shell test -x /opt/homebrew/bin/python3 && echo /opt/homebrew/bin/python3 || command -v python3)

.PHONY: test dry run report dash inference-smoke

test:
	$(PY) -m unittest discover -s tests

dry:
	$(PY) -m loop.cycle --dry --once

run:
	$(PY) -m loop.cycle --forever

report:
	$(PY) -m loop.report

# health only (report §1-§3 + the nightly's synthetic tables) as one HTML file, data/dash.html
dash:
	$(PY) -m loop.dash

# PREREG §4-§5's inference on the rows BEFORE T0 (the shakedown): a smoke of the procedure, never a
# result. The sample form, `python3 -m loop.inference --sample --out RESULTS.md`, refuses until day 28.
inference-smoke:
	$(PY) -m loop.inference --pre-t0

# The four commands STEPS.md names. Standard library only; nothing here installs anything.
# `dry` is free (three public Coinbase GETs, no key, no ledger row, no send). `run` SENDS
# to Jev once a minute: only after STEPS.md steps 0 (PROTOCOL signed) and 1 (loop key).
PY := /opt/homebrew/bin/python3

.PHONY: test dry run report dash

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

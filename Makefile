# The commands STEPS.md and HANDOFF.md name. Standard library only; nothing here installs anything.
# `dry` is free (three public Coinbase GETs, no key, no ledger row, no send). `run` SENDS
# to Jev once a minute: only after STEPS.md steps 0 (PROTOCOL signed) and 1 (loop key), and
# only on the Mac (CLAUDE.md). `test` is the whole gate anywhere else.
# PY is the Mac's Homebrew python (3.14) when it exists; a checkout without it (a cloud session,
# CI) uses the python3 on PATH. `make PY=... test` overrides either.
PY ?= $(shell test -x /opt/homebrew/bin/python3 && echo /opt/homebrew/bin/python3 || command -v python3)

.PHONY: test test-mode test-modes dry run report health dash status inference-smoke results

test:
	$(PY) -m unittest discover -s tests

# The suite under the conditions CI also runs it in, one MODE at a time (make test-modes runs all
# six, ~6 min): warnings as errors; a C locale with UTF-8 mode off (ASCII file names and pipes);
# a shuffled order (tests/modes/shuffled.py, seeds 1-3); and the wall clock moved to the day-28
# run, to three weeks after the sample, and to next year (tests/modes/clock), so a test that reads
# the real date fails before the calendar gets there.
MODES = werror c-locale shuffled day-28 after-sample next-year
CLOCK = PYTHONPATH="$(CURDIR)/tests/modes/clock" FAKE_NOW
test-mode:
	@case "$(MODE)" in \
	  werror) $(PY) -W error -m unittest discover -s tests ;; \
	  c-locale) LC_ALL=C LANG=C PYTHONUTF8=0 PYTHONCOERCECLOCALE=0 $(PY) -m unittest discover -s tests ;; \
	  shuffled) $(PY) tests/modes/shuffled.py 1 2 3 ;; \
	  day-28) $(CLOCK)=2026-10-23T21:56:30Z $(PY) -m unittest discover -s tests ;; \
	  after-sample) $(CLOCK)=2026-11-15T12:00:00Z $(PY) -m unittest discover -s tests ;; \
	  next-year) $(CLOCK)=2027-03-01T09:00:00Z $(PY) -m unittest discover -s tests ;; \
	  *) echo "make test-mode MODE=<one of: $(MODES)>" >&2; exit 2 ;; \
	esac

test-modes:
	@for m in $(MODES); do echo "== $$m"; $(MAKE) --no-print-directory test-mode MODE=$$m || exit 1; done

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

# Day 28 (2026-10-23 21:56Z or later, when d28 closes; loop/inference.py refuses, exit 3, until the log holds the t + h row
# of every kept block's first live row: ~30 s after the end normally, ~15.5 min at worst): the one run of
# PREREG §4-§5 on the sample, written to RESULTS.md and committed beside PREREG.md (§10). By hand,
# once; the stop rules (PREREG §8) are read from its output.
results:
	$(PY) -m loop.inference --sample --out RESULTS.md

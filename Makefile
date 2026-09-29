# The commands STEPS.md and HANDOFF.md name. Standard library only; nothing here installs anything.
# `dry` is free (three public Coinbase GETs, no key, no ledger row, no send). `run` SENDS
# to Jev once a minute: only after STEPS.md steps 0 (PROTOCOL signed) and 1 (loop key), and
# only on the Mac (CLAUDE.md). `test` is the whole gate anywhere else.
# PY is the Mac's Homebrew python (3.14) when it exists; a checkout without it (a cloud session,
# CI) uses the python3 on PATH. `make PY=... test` overrides either.
PY ?= $(shell test -x /opt/homebrew/bin/python3 && echo /opt/homebrew/bin/python3 || command -v python3)

.PHONY: test test-mode test-modes dry run report health dash status inference-smoke results backup quantiles probe probe-summarize

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

# `make report` reads every product's store (PREREG-v2's report: per product and pooled, at each
# cadence). On rows of a sealed sample it prints sections 1-3 only: v1's until 2026-10-23 21:40Z,
# PREREG-v2's until T0_v2 + 28 d (T0_v2 from PREREG-v2.md §12; while that is blank, every row
# carrying the v2 spec_sha), whatever the flags say; `python3 -m loop.report --unblind` is a look,
# appended to data/looks.tsv. v1's report on its one log: `python3 -m loop.report --log data/decisions.jsonl`.
report:
	$(PY) -m loop.report

# The day-14 health look: `python3 -m loop.report --health --sample`, sections 1-3 per product and
# pooled, T0_v2 read from PREREG-v2.md §12 (PREREG-v2 §9.5; `make report --health` never worked:
# make takes the flag as its own). v1's look, T0 from PREREG.md §11:
# `python3 -m loop.report --log data/decisions.jsonl --health --sample`.
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

# PREREG-v2's day 28 (T0_v2 + 28 d, T0_v2 from PREREG-v2.md §12), once d28 has closed: some product's log must hold a
# tick at or after T0_v2 + 28 d + h + 30 s (~16 min after the end; loop/inference_v2.py refuses, exit 3, before, and
# before the end itself, both before opening a log). It checks the seal first, also before opening a log (§10, §13): the
# annotated tag prereg-v2-seal is an ancestor of HEAD and `bin/seal-check --since prereg-v2-seal` exits 0, or it refuses
# (exit 3) unless NO_SEAL=1 (`make results NO_SEAL=1`, passed as --no-seal), which RESULTS-v2.md records. The one run
# of PREREG-v2 §4-§7 and §9 over every product's store, written to RESULTS-v2.md and committed; by hand, once; the stop
# rules (§9) are read from its output. `--accept-pending` is for logs that really stopped.
# v1's run (2026-10-23, from main before the switch; reproduced from the results-v1 tag after it):
# `python3 -m loop.inference --sample --out RESULTS.md`.
results:
	$(PY) -m loop.inference_v2 --sample --out RESULTS-v2.md$(if $(filter 1,$(NO_SEAL)), --no-seal)

backup:
	bash bin/backup-data

# PREREG-v2's two tools, never part of `test` or of anything the loop runs. `quantiles` and `probe` print their
# usage only: bin/fill1k-quantiles reads a decision log (features only) and a probe run sends public Coinbase GETs
# for a whole UTC day, so a person runs either by hand with its arguments. `probe-summarize DIR=...` is offline:
# it reads a probe directory and prints each criterion per product and the two chosen (exit 1 when the day is
# void); TICK_OVERRIDE=P=0.01,... passes --tick-override for a product whose book grid the mode misread.
quantiles:
	$(PY) bin/fill1k-quantiles --help

probe:
	$(PY) bin/probe --help

probe-summarize:
	@test -n "$(DIR)" || { echo "usage: make probe-summarize DIR=<the probe's --out directory> [TICK_OVERRIDE=P=0.01,...]" >&2; exit 2; }
	$(PY) bin/probe summarize "$(DIR)"$(if $(TICK_OVERRIDE), --tick-override "$(TICK_OVERRIDE)")

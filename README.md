# jev-paper-loop ("JevTrader")

A paper-only, forward-only measurement of the "two models at two speeds" loop: a fast typed
model (Jev, TypeSafe System One) answers one fixed question a minute about SOL-USD from a
ten-word state; a slow model proposes a rewrite of the question nightly; a person applies it.
Three arms are paired on every tick — the frozen wording, the rewritten wording, and the
no-model rule the thresholds already imply — and a sealed 28-day pre-registration says how
they are compared.

- `PROTOCOL.md` the carve-out and its eleven conditions · `PREREG.md` the sealed test ·
  `SPEC.md` what one row means · `CONTRACT.md` module interfaces · `STEPS.md` what a person
  installs · `HANDOFF.md` where the last session left off · `CLAUDE.md` working rules.
- `make test` (offline; also CI on every push), `make status` (the morning check), `make health` (report
  §1-§3 on the sample), `make dash`, `make inference-smoke`, and on day 28 `make results`.
- Nothing here places an order, holds a key in git, or reads any other trading repository.

"""The slow model, pinned (PREREG-v2 §8): every v2 night calls `claude -p --model MODEL_ID`. This is the ONE place the
id lives: nightly/propose.sh reads MODEL_ID from here (python -I -B, the repo on sys.path, nothing else imported) and
from nowhere else, and tests/test_slow_model.py holds MODEL_ID and NIGHT to PREREG-v2.md §8's line
"id `...` (night ...)", blank underscores there being "" here, the night as §8 writes it (up to its `;` once filled).

§8's rule: the id on the `claude model` line of logs/propose.log from the run of 2026-09-29 08:30Z; if that line is
`unrecorded`, lists more than one id, or is missing, the first later v1 night whose line is exactly one id; one
substitute before the draft tag if the trial night refuses it. Both are written into §8 and here in one commit, before
the draft tag. While MODEL_ID is blank every live night fails at its start, logging why, with no claude call
and no Jev send; `propose.sh --dry` makes no call and does not read it.

May: hold these strings. May not: import anything, read anything, or be set from the environment: a second source of
the id would be a second treatment.
"""
MODEL_ID = "claude-sonnet-5"        # PREREG-v2 §8 "id `...`": blank until §8 names it, before the draft tag
NIGHT = "2026-09-29 08:30Z"           # PREREG-v2 §8 "(night `...`)": the propose.log night the id was read from
ID_FORM = r"[A-Za-z0-9][A-Za-z0-9._:@/\[\]-]{0,99}"   # nightly/answered_model.py's MODEL_ID: what a `claude model` line holds

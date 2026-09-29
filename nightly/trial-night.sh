#!/bin/bash
# nightly/trial-night.sh -- PREREG-v2 §8's one trial night before the draft tag, run by a person from the worktree:
#
#   /bin/bash nightly/trial-night.sh
#
# A real `claude -p` call (not propose.sh --dry, which makes none) through this tree's nightly/propose.sh, with --root
# a fresh temp dir outside every checkout of the repo (each `git worktree list` names, the live one included) holding a
# synthetic three-product log from tests/synth.py (--products all --era v2: one log per product in config.PRODUCTS,
# where config.store puts it, rows carrying this tree's SPEC sha), and --date that log's UTC day. "Three" is §2's
# products: the trial runs only once PREREG-v2.md §2's Products line is filled and config.PRODUCTS is that set (fewer
# than two passing the probe scales the count, §2); before then it prints FAIL and makes and calls nothing, since a
# night on SOL-USD alone would read as §8's trial. The digest must then hold a summary line for every one of them
# (the synthetic log's, not the night's output: propose.sh passed every product's log). Every write of the
# night lands under the temp root, which is removed after: nothing under the live repo's (or this tree's) data/, logs/
# or proposals/. The temp root also holds data/HALT, so the night's policy table sends nothing to Jev: the trial reads
# the call, not the table (its sends would need this tree's data/ for their ledger, which the worktree must not have).
#
# Only these are read and printed (§8: "only its exit code and its claude model and 'user memory not loaded' lines are
# read"): propose.sh's exit code, and from the night's log its FAIL line (if any), the `claude exit` line, the
# `claude model` line and the "user memory not loaded" line. Then PASS or FAIL: PASS needs exit 0, `claude exit 0`
# (the OAuth token answered), a `claude model` line naming exactly one id, the memory line, and every product of §2 in
# the digest (the "digest products" line). §8 also asks the trial to show whether --settings still applies under the
# fresh config dir; it cannot from what §8 lets it read: the call has no tools (--tools ""), so nightly/settings.json,
# a deny list, changes nothing the reply, the log or the CLI's transcript records. The script says so on a NOT SHOWN
# line beside every verdict, so a PASS does not read as §8's whole trial: settling it is the author's, before the tag.
# Exit 0 on PASS, 1 on FAIL, 2 on usage, 3 when no temp root outside the checkouts can be made.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
PY="${JEVLOOP_PY:-/opt/homebrew/bin/python3}"
DAY="2026-09-30"                                  # the synthetic log's UTC day (its T0 is that day's 00:00Z)
[ $# -eq 0 ] || { echo "usage: $0 (no arguments)" >&2; exit 2; }
[ -x "$PY" ] || { echo "trial-night: no python at $PY" >&2; exit 3; }

# §2's products, filled, and config.PRODUCTS that set (in §2's order: the digest's), or not §8's trial: FAIL, nothing made
PRODUCTS="$("$PY" -I -B -c 'import sys; sys.path.insert(0, sys.argv[1])
from loop import config, dash
try:
    named = dash.read_products_v2()
except ValueError as e:
    sys.exit(f"PREREG-v2 section 2: {e}")
if named is None:
    sys.exit("PREREG-v2 section 2 does not name the products yet (a blank on its Products line)")
if set(named) != set(config.PRODUCTS) or len(named) != len(config.PRODUCTS):
    sys.exit(f"config.PRODUCTS is {chr(32).join(config.PRODUCTS)}, not {chr(32).join(named)} (PREREG-v2 section 2)")
print(" ".join(named))' "$REPO" 2>&1)" || {
  echo "FAIL: not PREREG-v2 section 8's trial: ${PRODUCTS:-the products could not be read}; nothing made, nothing called"
  exit 1
}

ROOT="$(mktemp -d "${TMPDIR:-/tmp}/jevloop-trial.XXXXXX")" || { echo "trial-night: cannot make a temp root" >&2; exit 3; }
trap 'rm -rf "$ROOT"' EXIT
ROOT="$(cd "$ROOT" && pwd -P)"
# outside both checkouts: this tree and every worktree git knows of (the live checkout among them)
TREES="$REPO
$(git -C "$REPO" worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p')"
while IFS= read -r t; do
  [ -n "$t" ] || continue
  t="$(cd "$t" 2>/dev/null && pwd -P)" || continue
  case "$ROOT/" in "$t"/*) echo "trial-night: the temp root $ROOT is inside the checkout $t; set TMPDIR elsewhere" >&2; exit 3 ;; esac
done <<EOF
$TREES
EOF

"$PY" -I -B "$REPO/tests/synth.py" --products all --era v2 --days 1 --pre-hours 0 --post-minutes 20 \
  --t0 "${DAY//-/}T000000Z" --out "$ROOT/data" >/dev/null || { echo "trial-night: tests/synth.py failed" >&2; exit 1; }
echo "trial night: no Jev send (the trial reads the call, not the table)" >"$ROOT/data/HALT"

/bin/bash "$REPO/nightly/propose.sh" --root "$ROOT" --date "$DAY" >/dev/null 2>&1
rc=$?
LOG="$ROOT/logs/propose.log"
lines="$(grep -E ' propose (FAIL |claude exit |claude model )|user memory not loaded' "$LOG" 2>/dev/null)"
echo "propose.sh exit $rc"
[ -n "$lines" ] && printf '%s\n' "$lines"
# the synthetic digest's summary lines, one per product of §2 (a product id holds no regex character but '-')
seen=""; n=0; k=0
for p in $PRODUCTS; do
  n=$((n + 1))
  grep -q "^$p | ticks [1-9]" "$ROOT/data/digest-$DAY.md" 2>/dev/null && { seen="$seen $p"; k=$((k + 1)); }
done
echo "digest products:${seen:- none} ($k of the $n PREREG-v2 section 2 names)"

ok=1
[ $rc -eq 0 ] || ok=0
printf '%s\n' "$lines" | grep -q ' propose FAIL ' && ok=0
printf '%s\n' "$lines" | grep -qE ' propose claude exit 0 after ' || ok=0
printf '%s\n' "$lines" | grep -q 'user memory not loaded' || ok=0
model="$(printf '%s\n' "$lines" | sed -n 's/.* propose claude model \([^ ]*\) .*/\1/p')"
case "$model" in ""|unrecorded|*,*) ok=0 ;; esac
[ $k -eq $n ] || ok=0
echo "NOT SHOWN: whether --settings still applies under the fresh config dir (PREREG-v2 section 8 asks it; with no tools the settings file's deny list changes nothing this run records, so the author settles it before the draft tag)"
if [ $ok -eq 1 ]; then echo "PASS: claude answered, one model ($model), user memory not loaded, a synthetic log of every product"; exit 0; fi
echo "FAIL: see the lines above (PREREG-v2 section 8: on a config-dir failure the fallback is to pin the user-memory sha)"
exit 1

#!/bin/bash
# nightly/propose.sh -- the slow model's one call a night, wrapped so nothing it does
# can reach prompts/, the key, or a tool.
#
# May: build the digest (nightly/digest.py), hand PROMPT.md + digest to `claude -p`
# with NO tools (--tools "" is the contract's belt; --restricted --strict-mcp-config
# and nightly/settings.json are the braces: no MCP server, no user settings, and a
# deny list on the secrets and the sibling repos even if a tool ever appeared), keep
# its stdout under logs/, extract exactly ONE fenced json block, validate it, write
# proposals/<date>.json, then run nightly/policy_table.py on it (81 Jev sends,
# ~$0.005; the table goes to proposals/<date>.md) unless data/HALT exists.
# May not: write under prompts/ (only bin/promote, run by a person); echo, log or
# pass on argv the OAuth token (it is read into the environment for the one call and
# unset after); exit non-zero on a failure -- launchd throttles a failing job and
# hides why, so every failure is one line in logs/propose.log and exit 0. The two
# non-zero exits are the usage error (2) and the path guard (3), both before any work.
# One run per date: a DATE whose proposals/<date>.json exists is refused (one FAIL line).
#
# Usage: nightly/propose.sh [--date YYYY-MM-DD] [--dry] [--root DIR]
#   --date  the UTC day to digest; default: yesterday
#   --dry   no claude call, no Jev send: the fixture candidate below stands in for the
#           model's reply and policy_table.py runs with --dry. Tests use this.
#   --root  where data/ logs/ proposals/ live; default: the repo. Tests pass a temp dir
#           so no run of the suite writes a proposals/*.md into the tree (they are committed).
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
# The JEVLOOP_* variables exist so tests/test_nightly.py can drive this script off the Mac and drive
# the LIVE branch with a stub claude, a temp token file and a short cap (decided by Alex 2026-09-26).
# JEVLOOP_PY and JEVLOOP_CAFFEINATE (2026-09-28) let a Linux checkout or CI run the suite: there is no
# /opt/homebrew/bin/python3 and no caffeinate there. launchd sets only PATH (the plist), so under
# launchd every one of them is its default, and the defaults are the Mac paths STEPS.md names.
PY="${JEVLOOP_PY:-/opt/homebrew/bin/python3}"
CLAUDE="${JEVLOOP_CLAUDE:-/opt/homebrew/bin/claude}"
CAFFEINATE="${JEVLOOP_CAFFEINATE:-/usr/bin/caffeinate}"
TOKEN_FILE="${JEVLOOP_TOKEN_FILE:-$HOME/.secondbrain-secrets/oauth_token}"
CLAUDE_CAP_S="${JEVLOOP_CLAUDE_CAP_S:-2700}"   # 45 min awake: the first two nights took 52 s and 51 s
# JEVLOOP_PROMPTS (2026-09-28): a prompts root for the digest and the table, so the suite runs them
# on a pinned v1 (tests/fixture_prompts.pin_v1) and never quotes the live CURRENT. Empty (always,
# under launchd): neither gets --prompts and both read the repo's own, as before.
PROMPTS_ROOT="${JEVLOOP_PROMPTS:-}"
ROOT="$REPO"; DATE=""; DRY=0

usage() { echo "usage: $0 [--date YYYY-MM-DD] [--dry] [--root DIR]" >&2; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --date) [ $# -ge 2 ] || usage; DATE="$2"; shift 2 ;;    # a trailing --date: `shift 2` would fail and loop forever
    --dry)  DRY=1; shift ;;
    --root) [ $# -ge 2 ] || usage; ROOT="$2"; shift 2 ;;
    *) usage ;;
  esac
done

# The same two prefixes as config.FORBIDDEN_PREFIXES: the nightly imports loop/ and
# must never run under the crypto repo or its mirror either (CONTRACT §0, exit 3). Checked on
# the repo, the --root and the working directory alike: every path this script writes under.
guard_path() {
  case "$1" in
    "$HOME/Projects/crypto-trading-system"*|"$HOME/Library/Mobile Documents/com~apple~CloudDocs/crypto-trading-system-backup"*)
      echo "propose: refusing to run under a forbidden prefix ($2)" >&2; exit 3 ;;
  esac
}
case "$ROOT" in /*) ;; *) ROOT="$(pwd -P)/$ROOT" ;; esac        # absolute now: the guard and every write see one path
ROOT_REAL="$(cd "$ROOT" 2>/dev/null && pwd -P || echo "$ROOT")"
guard_path "$REPO" repo
guard_path "$ROOT_REAL" root
guard_path "$(pwd -P)" cwd
# --dry writes the fixture proposal as proposals/<date>.json. In the repo that file would then be
# the day's proposal: a real night for the same date is refused (one run per date, below), no
# Claude call is made, and bin/promote would accept the fixture with a warning. So --dry runs
# only against a --root outside the repo (the suite passes a temp dir).
if [ $DRY -eq 1 ] && [ "$ROOT_REAL" = "$REPO" ]; then
  echo "usage: --dry writes fixture files; pass --root DIR outside the repo" >&2; exit 2
fi

LOGS="$ROOT/logs"
mkdir -p "$LOGS" "$ROOT/data" "$ROOT/proposals" 2>/dev/null || { echo "propose: cannot create $ROOT dirs" >&2; exit 0; }
LOG="$LOGS/propose.log"
log()  { printf '%s propose %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG" >&2; }
fail() { log "FAIL $*"; exit 0; }

# 5. the health page (report sections 1-3 only, loop/dash.py), rebuilt at the end of EVERY night --
#    an OK table, a HALT, a failed claude call, a day with no ticks -- so the file is never older
#    than a day and a bad night shows on it too. Decided by Alex 2026-09-26 ("rebuild it at the end
#    of every nightly"). Non-fatal: a dash failure is one log line, never a FAIL, and the night's
#    exit status is kept. The trap is installed here, after the usage (2) and guard (3) exits and
#    once logs/ exists; it also removes the claude call's empty cwd however the night ended.
WORK=""
rebuild_dash() {
  [ -x "$PY" ] || return 0
  ( cd "$REPO" && "$PY" -m loop.dash --log "$ROOT/data/decisions.jsonl" --out "$ROOT/data/dash.html" \
      --data "$ROOT/data" --proposals "$ROOT/proposals" ${PROMPTS_ROOT:+--prompts "$PROMPTS_ROOT"} ) >>"$LOG" 2>&1 \
    || log "dash: loop.dash exit $? (non-fatal)"
}
on_exit() {
  st=$?
  [ -n "$WORK" ] && rm -rf "$WORK"
  rebuild_dash
  exit $st
}
trap on_exit EXIT

[ -x "$PY" ] || fail "no python at $PY"
[ -n "$DATE" ] || DATE="$("$PY" -c 'import datetime as d; print((d.datetime.now(d.timezone.utc) - d.timedelta(days=1)).strftime("%Y-%m-%d"))')"
case "$DATE" in
  [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
  *) fail "bad --date $DATE" ;;
esac
cd "$REPO" || fail "cd $REPO"
log "start date=$DATE dry=$DRY root=$ROOT"
# One run per DATE. A slot the Mac slept through fires at the next wake; after the next 00:00Z that
# run digests a later "yesterday", and the regular slot that night would digest that day again. A
# second run would spend a second Claude call and overwrite proposals/<date>.json, which a
# committed table's sha or a promote may already point at -- and the json is gitignored, so an
# overwrite is gone for good. To rerun a day, a person moves the json aside first.
[ -e "$ROOT/proposals/$DATE.json" ] && fail "proposals/$DATE.json exists: one run per day, nothing overwritten, no claude call (move it aside to rerun)"
[ -e "$ROOT/proposals/$DATE.md" ] && fail "proposals/$DATE.md exists (the committed table): one run per day; rerun by hand after moving it aside"
# The day before gets no proposal when its slot was missed that way: the hole is named in the log.
PREV="$("$PY" -c 'import datetime as d, sys; print((d.date.fromisoformat(sys.argv[1]) - d.timedelta(days=1)).isoformat())' "$DATE")"
[ -e "$ROOT/proposals/$PREV.json" ] || [ -e "$ROOT/proposals/$PREV.md" ] || [ -e "$REPO/proposals/$PREV.md" ] \
  || log "note: no proposal exists for $PREV (a missed slot?); this run is for $DATE only"

# 1. digest: exit 4 = the day has no rows, so there is nothing for the model to read.
DIGEST="$ROOT/data/digest-$DATE.md"
"$PY" -m nightly.digest --date "$DATE" ${PROMPTS_ROOT:+--prompts "$PROMPTS_ROOT"} \
  --log "$ROOT/data/decisions.jsonl" --out "$DIGEST" >>"$LOG" 2>&1
rc=$?
if [ $rc -eq 4 ]; then
  [ $DRY -eq 1 ] || { log "no ticks on $DATE; nothing to propose"; exit 0; }
elif [ $rc -ne 0 ]; then
  fail "digest exit $rc"
fi

# 2. the slow model, or the fixture.
RAW="$LOGS/claude-$DATE.txt"
if [ $DRY -eq 1 ]; then
  cat >"$RAW" <<'EOF'
Fixture reply (propose.sh --dry): one candidate, no digits, full text.

```json
{"candidates": [
  {"rationale": "fixture for --dry: buy only on a deep book, so the table differs from CURRENT on the normal-liquidity pumping states and nowhere else",
   "instructions": "Decide whether to be long SOL for the next quarter of an hour. Buy on strength only when the book is deep enough to absorb the order without moving it; get flat the moment the move fades or the market turns violent.",
   "criteria": {"buy": "the trend is pumping, volatility is not violent, and liquidity is deep",
                "sell": "the trend is dumping, or volatility is violent",
                "hold": "anything else: keep whatever position is already on"}}
]}
```
EOF
else
  [ -x "$CLAUDE" ] || fail "no claude at $CLAUDE"
  [ -x "$CAFFEINATE" ] || fail "no caffeinate at $CAFFEINATE"
  [ -s "$TOKEN_FILE" ] || fail "no token file at $TOKEN_FILE"
  # The call runs in a fresh EMPTY directory, not the repo. The treatment is PROMPT.md and the
  # digest and nothing else (PROMPT.md: "everything you may know is the digest"), but claude
  # auto-loads CLAUDE.md from its working directory and every ancestor, and --restricted only
  # ignores settings files, not CLAUDE.md (only --bare or --safe-mode would, and --bare disables
  # the OAuth login). The repo gained a CLAUDE.md on 2026-09-27, which the nights run in the repo
  # from then on saw. Note what this does and does not restore: the CLI's own per-machine
  # context (cwd, git status, memory paths) differs between the repo and an empty non-git
  # directory, so the night this is deployed is a change of the model's context either way
  # (2026-09-28; HANDOFF records the date). The CLI still loads the user's own memory,
  # ~/.claude/CLAUDE.md, so its sha256 is logged each night, beside the CLI version, so which
  # input and which CLI wrote each night is on record. Any CLAUDE.md, CLAUDE.local.md or .claude
  # in an ancestor of the temp directory (a shared /tmp is world-writable) would be loaded too:
  # the ancestors are walked and the night fails rather than send with one. capped.py is run
  # by path: `-m nightly.capped` resolves against the cwd, and it imports only the standard library.
  TMPBASE="${TMPDIR:-/tmp}"
  WORK="$(mktemp -d "${TMPBASE%/}/jevloop-claude.XXXXXX")" || fail "cannot make an empty cwd for claude"
  ANC="$(cd "$WORK" && pwd -P)"
  while [ -n "$ANC" ]; do
    for f in CLAUDE.md CLAUDE.local.md .claude; do
      [ -e "$ANC/$f" ] && fail "$ANC/$f exists above claude's cwd $WORK: the CLI would auto-load it; nothing sent"
    done
    [ "$ANC" = "/" ] && break
    ANC="$(dirname "$ANC")"
  done
  MEM="$HOME/.claude/CLAUDE.md"
  if [ -f "$MEM" ]; then
    MEMSHA="$("$PY" -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest()[:12])' "$MEM" 2>/dev/null)"
    MEMSHA="sha256 ${MEMSHA:-unreadable}"
  else
    MEMSHA="absent"
  fi
  # capped too: a --version that hung would hold the night, and launchd every night after it
  CLI="$(cd "$WORK" && "$PY" "$REPO/nightly/capped.py" 10 -- "$CLAUDE" --version 2>/dev/null | head -1)"
  log "claude cwd $WORK (empty); user memory $MEM $MEMSHA; cli ${CLI:-unknown}"
  CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '\r\n' <"$TOKEN_FILE")"; export CLAUDE_CODE_OAUTH_TOKEN
  PROMPT="$(cat "$REPO/nightly/PROMPT.md")

$(cat "$DIGEST")"
  # nightly/capped.py: CLAUDE_CAP_S of AWAKE time (monotonic pauses in sleep, so a night the Mac
  # sleeps through still finishes); a hang while awake exits 124 instead of blocking every later
  # night, since launchd never starts a second instance while one runs. caffeinate stays outermost.
  T_START=$(date +%s)
  ( cd "$WORK" || exit 125; exec "$CAFFEINATE" -i "$PY" "$REPO/nightly/capped.py" "$CLAUDE_CAP_S" -- \
    "$CLAUDE" -p "$PROMPT" --tools "" --restricted --strict-mcp-config \
    --settings "$REPO/nightly/settings.json" --output-format text ) >"$RAW" 2>"$LOGS/claude-$DATE.err"
  rc=$?
  unset CLAUDE_CODE_OAUTH_TOKEN
  rm -rf "$WORK"
  log "claude exit $rc after $(( $(date +%s) - T_START )) s wall clock (cap $CLAUDE_CAP_S s awake)"
  [ $rc -eq 124 ] && fail "claude capped at $CLAUDE_CAP_S s awake (see $LOGS/claude-$DATE.err)"
  [ $rc -eq 0 ] || fail "claude exit $rc (see $LOGS/claude-$DATE.err)"
fi

# 3. exactly one fenced json block -> {"candidates": [1..3 x {instructions, criteria{buy,sell,hold}}]}.
#    A digit anywhere in a candidate's text fails the whole reply: PROMPT.md says so,
#    and policy_table.py would refuse it anyway.
"$PY" -c '
import json, os, re, sys
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
blocks = re.findall(r"^```json[ \t]*\n(.*?)\n```[ \t]*$", raw, re.S | re.M)
if len(blocks) != 1: sys.exit("expected exactly one fenced json block, found %d" % len(blocks))
d = json.loads(blocks[0])
c = d.get("candidates") if isinstance(d, dict) else None
if not isinstance(c, list) or not 1 <= len(c) <= 3: sys.exit("candidates must be a list of 1-3 objects")
out = []
for i, x in enumerate(c):
    ok = (isinstance(x, dict) and isinstance(x.get("instructions"), str) and x["instructions"].strip()
          and isinstance(x.get("criteria"), dict) and sorted(x["criteria"]) == ["buy", "hold", "sell"]
          and all(isinstance(v, str) and v.strip() for v in x["criteria"].values())
          and isinstance(x.get("rationale", ""), str))
    if not ok: sys.exit("candidate %d: not {instructions: str, criteria: {buy, sell, hold}}" % i)
    if any(ch.isdigit() for ch in x["instructions"] + "".join(x["criteria"].values())): sys.exit("candidate %d: carries a digit" % i)
    out.append({"rationale": x.get("rationale", ""), "instructions": x["instructions"],
                "criteria": {k: x["criteria"][k] for k in ("buy", "sell", "hold")}})
# serialized whole first, written beside the target, then LINKED to the target name: a failure
# never leaves a truncated json for a table or a promote to read, and a target that appeared
# meanwhile (a by-hand run beside launchd) is never overwritten: link fails, the night does
text = json.dumps({"candidates": out}, indent=2, ensure_ascii=False) + "\n"
tmp = sys.argv[2] + ".tmp"
try:
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.link(tmp, sys.argv[2])
finally:
    if os.path.exists(tmp): os.unlink(tmp)
' "$RAW" "$ROOT/proposals/$DATE.json" >>"$LOG" 2>&1 || fail "invalid proposal (see $RAW)"
log "wrote proposals/$DATE.json"

# 4. the 81-state table. --dry prints the first payload into the log and sends nothing.
#    data/HALT stops every Jev send (PROTOCOL §3.8), this one included; the spend guard
#    cannot see these sends (they never reach decisions.jsonl), so the check is here and
#    again in policy_table.py. Checked in --dry too, so the suite can exercise it.
if [ -e "$ROOT/data/HALT" ]; then
  log "HALT present ($ROOT/data/HALT): no Jev send; proposals/$DATE.json written, no table (once HALT is cleared: $PY -m nightly.policy_table --out proposals/$DATE.md proposals/$DATE.json)"
  exit 0
fi
if [ $DRY -eq 1 ]; then DRYFLAG="--dry"; else DRYFLAG=""; fi
"$PY" -m nightly.policy_table $DRYFLAG ${PROMPTS_ROOT:+--prompts "$PROMPTS_ROOT"} \
  --out "$ROOT/proposals/$DATE.md" "$ROOT/proposals/$DATE.json" >>"$LOG" 2>&1
rc=$?
[ $rc -eq 0 ] || fail "policy_table exit $rc"
log "OK proposals/$DATE.json"
exit 0                                             # on_exit (above) rebuilds the dash, after this OK line

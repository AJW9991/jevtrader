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
#
# Usage: nightly/propose.sh [--date YYYY-MM-DD] [--dry] [--root DIR]
#   --date  the UTC day to digest; default: yesterday
#   --dry   no claude call, no Jev send: the fixture candidate below stands in for the
#           model's reply and policy_table.py runs with --dry. Tests use this.
#   --root  where data/ logs/ proposals/ live; default: the repo. Tests pass a temp dir
#           so no run of the suite writes a proposals/*.md into the tree (they are committed).
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
PY=/opt/homebrew/bin/python3
CLAUDE=/opt/homebrew/bin/claude
CAFFEINATE=/usr/bin/caffeinate
TOKEN_FILE="$HOME/.secondbrain-secrets/oauth_token"
ROOT="$REPO"; DATE=""; DRY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --date) DATE="${2:-}"; shift 2 ;;
    --dry)  DRY=1; shift ;;
    --root) ROOT="${2:-}"; shift 2 ;;
    *) echo "usage: $0 [--date YYYY-MM-DD] [--dry] [--root DIR]" >&2; exit 2 ;;
  esac
done

# The same two prefixes as config.FORBIDDEN_PREFIXES: the nightly imports loop/ and
# must never run under the crypto repo or its mirror either (CONTRACT §0, exit 3).
case "$REPO" in
  "$HOME/Projects/crypto-trading-system"*|"$HOME/Library/Mobile Documents/com~apple~CloudDocs/crypto-trading-system-backup"*)
    echo "propose: refusing to run under a forbidden prefix" >&2; exit 3 ;;
esac

LOGS="$ROOT/logs"
mkdir -p "$LOGS" "$ROOT/data" "$ROOT/proposals" 2>/dev/null || { echo "propose: cannot create $ROOT dirs" >&2; exit 0; }
LOG="$LOGS/propose.log"
log()  { printf '%s propose %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG" >&2; }
fail() { log "FAIL $*"; exit 0; }

[ -x "$PY" ] || fail "no python at $PY"
[ -n "$DATE" ] || DATE="$("$PY" -c 'import datetime as d; print((d.datetime.now(d.timezone.utc) - d.timedelta(days=1)).strftime("%Y-%m-%d"))')"
case "$DATE" in
  [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
  *) fail "bad --date $DATE" ;;
esac
cd "$REPO" || fail "cd $REPO"
log "start date=$DATE dry=$DRY root=$ROOT"

# 1. digest: exit 4 = the day has no rows, so there is nothing for the model to read.
DIGEST="$ROOT/data/digest-$DATE.md"
"$PY" -m nightly.digest --date "$DATE" --log "$ROOT/data/decisions.jsonl" --out "$DIGEST" >>"$LOG" 2>&1
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
  CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '\r\n' <"$TOKEN_FILE")"; export CLAUDE_CODE_OAUTH_TOKEN
  PROMPT="$(cat "$REPO/nightly/PROMPT.md")

$(cat "$DIGEST")"
  "$CAFFEINATE" -i "$CLAUDE" -p "$PROMPT" --tools "" --restricted --strict-mcp-config \
    --settings "$REPO/nightly/settings.json" --output-format text >"$RAW" 2>"$LOGS/claude-$DATE.err"
  rc=$?
  unset CLAUDE_CODE_OAUTH_TOKEN
  [ $rc -eq 0 ] || fail "claude exit $rc (see $LOGS/claude-$DATE.err)"
fi

# 3. exactly one fenced json block -> {"candidates": [1..3 x {instructions, criteria{buy,sell,hold}}]}.
#    A digit anywhere in a candidate's text fails the whole reply: PROMPT.md says so,
#    and policy_table.py would refuse it anyway.
"$PY" -c '
import json, re, sys
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
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    json.dump({"candidates": out}, fh, indent=2, ensure_ascii=False); fh.write("\n")
' "$RAW" "$ROOT/proposals/$DATE.json" >>"$LOG" 2>&1 || fail "invalid proposal (see $RAW)"
log "wrote proposals/$DATE.json"

# 4. the 81-state table. --dry prints the first payload into the log and sends nothing.
#    data/HALT stops every Jev send (PROTOCOL §3.8), this one included; the spend guard
#    cannot see these sends (they never reach decisions.jsonl), so the check is here and
#    again in policy_table.py. Checked in --dry too, so the suite can exercise it.
if [ -e "$ROOT/data/HALT" ]; then
  log "HALT present ($ROOT/data/HALT): no Jev send; proposals/$DATE.json written, no table"
  exit 0
fi
if [ $DRY -eq 1 ]; then DRYFLAG="--dry"; else DRYFLAG=""; fi
"$PY" -m nightly.policy_table $DRYFLAG --out "$ROOT/proposals/$DATE.md" "$ROOT/proposals/$DATE.json" >>"$LOG" 2>&1
rc=$?
[ $rc -eq 0 ] || fail "policy_table exit $rc"
log "OK proposals/$DATE.json"
exit 0

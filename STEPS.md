# Your steps — 2026-09-23

Nine steps, in order, each one yours because it changes what runs without you
watching, spends money, or signs something. Steps 3 and 4 are free and can be
run today; nothing in 5–8 may happen before step 0, and 5 and 7 also need
step 1. Each step says what it changes and what it does not. Backups use the
house pattern `<file>.bak-YYYYMMDD-HHMMSS` beside the file (`*.bak-*` is
gitignored here).

Done on my side, not installed: `SPEC.md` (frozen; its sha goes into every
row), `PREREG.md` (draft until step 6), the two plists in `launchd/`
(`plutil -lint` clean). Nothing has been sent to api.typesafe.ai and no key
for the loop exists yet.

## 0. Sign PROTOCOL.md and paste the §7 line into the JEV protocol  (~3 min)

**Why.** `~/Projects/JEV/PROTOCOL.md` §5 forbids exactly what this repo does
(an always-on hook that makes a model call; `jev ask` as a decision
instrument). `PROTOCOL.md` here is the carve-out with its eleven conditions. It
is drafted, not in force: until the signature commit exists and the JEV
protocol carries the one-line pointer, nothing in this repo may send and
nothing may be loaded into launchd. `--dry` runs (step 4) are allowed now.

Read the eleven conditions, then fill the two fields in §5 (`In force from:` and
`Signed:`) in your editor and commit under their own message:

```bash
cd ~/Projects/jev-paper-loop && sed -n '/^## 3\./,/^## 4\./p' PROTOCOL.md
```

```bash
cd ~/Projects/jev-paper-loop && ${EDITOR:-vi} PROTOCOL.md && git add PROTOCOL.md && git commit -m "PROTOCOL: in force from $(date +%Y-%m-%d), signed"
```

Then the pointer. This inserts the fenced block from this repo's `PROTOCOL.md`
§4 after item 8 of the JEV protocol's §7 Open, refuses if a `9.` line is already
there, and backs the file up first:

```bash
cp ~/Projects/JEV/PROTOCOL.md ~/Projects/JEV/PROTOCOL.md.bak-$(date +%Y%m%d-%H%M%S) && /opt/homebrew/bin/python3 - <<'PY'
import re, pathlib
src = pathlib.Path.home() / "Projects/jev-paper-loop/PROTOCOL.md"
dst = pathlib.Path.home() / "Projects/JEV/PROTOCOL.md"
block = re.search(r"^## 4\..*?\n```\n(.*?)^```", src.read_text(), re.S | re.M).group(1)
text = dst.read_text()
assert "CARVE-OUT, side project only" not in text, "already pasted"
anchor = "8. The vendor's retention terms and an actual billing line from the console.\n"
assert anchor in text, "anchor line not found; paste by hand"
dst.write_text(text.replace(anchor, anchor + block, 1))
print("inserted %d lines after §7 item 8" % block.count("\n"))
PY
git -C ~/Projects/JEV diff --stat && git -C ~/Projects/JEV add PROTOCOL.md && git -C ~/Projects/JEV commit -m "PROTOCOL §7: item 9, the jev-paper-loop carve-out"
```

**What changes.** Two commits: this repo's `PROTOCOL.md` (two fields) and
`~/Projects/JEV/PROTOCOL.md` (six lines in §7 Open, additive). **What it does
not change.** Any rule in the JEV protocol, `NEXT.md`, the crypto repo's
exclusion, or `~/.claude/CLAUDE.md`. The §5 lines stay as they are; this is a
listed exception, not an edit to the list.

## 1. Mint the loop's own TypeSafe key  (~3 min, in the console)

**Why.** PROTOCOL.md §3.6: a loop-triggered rate limit or suspension (TypeSafe
MCA §6) must never reach the brain's live injection screen or the Monday
canary, which use `~/.secondbrain-secrets/typesafe-api-key`. `loop/jev.py`
looks for `TYPESAFE_API_KEY_LOOP`, then
`~/.secondbrain-secrets/typesafe-api-key-loop`, and only then falls back to the
shared key — and says which in every row's `jev.key_path`. Until this file
exists, step 5 would run on the shared key.

In the TypeSafe console create a key named `jev-paper-loop`, copy it, then in
a terminal (the key is never echoed and never lands in shell history):

```bash
umask 077 && read -rs 'K?paste the new key, then Enter: ' && printf '%s\n' "$K" > ~/.secondbrain-secrets/typesafe-api-key-loop && unset K && chmod 600 ~/.secondbrain-secrets/typesafe-api-key-loop && ls -l ~/.secondbrain-secrets/typesafe-api-key-loop && echo "bytes: $(wc -c < ~/.secondbrain-secrets/typesafe-api-key-loop)"
```

Confirm the loop resolves it — this prints the NAME of the path, never the
value:

```bash
cd ~/Projects/jev-paper-loop && /opt/homebrew/bin/python3 -c 'from loop import jev; print(jev.key()[1])'
```

Want `file:~/.secondbrain-secrets/typesafe-api-key-loop`.

**The billing line.** On the console's billing page, confirm (a) the account
has a payment method and a billing line at all (JEV PROTOCOL §7 item 8 has
wanted one for two days), and (b) the input rate is what the spend guard
assumes: `config.USD_PER_MTOK = 0.042` per million input tokens, output free
(docs, 2026-09-23). The loop is ~1,440 × ~600 tokens ≈ $0.04/day, ~$1.10 per
28-day block; `DAILY_SPEND_HALT_USD = 0.25` writes `data/HALT` at ~5× that.
If the rate on the page differs, say so before step 5 — the guard's constant
is in `loop/config.py` and a change there is a `SPEC.md` change.

**What changes.** One new 0600 file under `~/.secondbrain-secrets/`. **What it
does not change.** The shared key, `~/Projects/JEV/.env`, the canary, the
filer. The key value never appears in this repo, its log, or its rows.

## 2. OAuth token check for the nightly  (~1 min, one Claude call)

**Why.** `nightly/propose.sh` exports `CLAUDE_CODE_OAUTH_TOKEN` from
`~/.secondbrain-secrets/oauth_token` and runs one `claude -p` under
`caffeinate`. A stale token fails at 03:30 with nobody watching, and the
first proposal file would be a day late. One word now proves the token, the
binary path and `--tools ""` together:

```bash
cd "$(mktemp -d)" && CLAUDE_CODE_OAUTH_TOKEN="$(cat ~/.secondbrain-secrets/oauth_token)" caffeinate -i /opt/homebrew/bin/claude -p 'Reply with the single word OK and nothing else.' --tools "" --restricted --strict-mcp-config --settings ~/Projects/jev-paper-loop/nightly/settings.json --output-format text
```

Want `OK`. An authentication error means the token has expired: mint a
long-lived one with `claude setup-token`, write it to the same file (0600, the
`read -rs` pattern of step 1), and re-run.

**What changes.** Nothing on disk; one short call on the subscription. **What
it does not change.** The nightly is not run and no proposal is written.

## 3. `make test`  (~1 min, free, offline)

**Why.** Every condition of PROTOCOL.md §3 that is enforced in code is pinned
by a test: the path guard exits 3, HALT is honoured, the ledger row exists
before the request, an unwritable ledger sends nothing, a 401 raises, `--dry`
writes no ledger row. The tests mock `urllib.request.urlopen`; nothing under
`tests/` opens a socket.

```bash
cd ~/Projects/jev-paper-loop && make test
```

The same thing by hand (191 tests at integration, 2026-09-24; 320-odd by 2026-09-28, also run by CI on every push):

```bash
cd ~/Projects/jev-paper-loop && /opt/homebrew/bin/python3 -m unittest discover -s tests -v 2>&1 | tail -3
```

Want `OK`. **What changes.** Nothing; a temp `data/` per test. **What this
is not.** A live check of anything: the fixture snapshot is from
2026-09-24T02:28:49Z (its 100-level book from 04:51:41Z) and Jev is mocked.

## 4. `make dry` and read the row  (~2 min, free; three public GETs)

**Why.** The free thing, run first: a whole tick — feed, features, alphabet,
state string, rule_c, prompt shas, SPEC sha — with no model and no ledger
row. It is what a launchd tick will do minus the send, and reading one row
end to end is the only way to know the row is what `SPEC.md` §2 says.

```bash
cd ~/Projects/jev-paper-loop && make dry && tail -1 data/decisions.jsonl | /opt/homebrew/bin/python3 -m json.tool
```

By hand: `/opt/homebrew/bin/python3 -m loop.cycle --dry --once` (`--once` or
`--forever` is required; alone, `--dry` is a usage error, exit 2).

Read it against SPEC §2: `mode` is `dry`; `absence` is `null`; `answers`
`null`; `columns` is `{"a": null, "b": null}` (each arm `null` itself, CONTRACT
§3 step 5);
`state` is `SOL: liquidity …, flow …, trend …, vol …` with no digit; `rule_c`
is one of the three; `prompt_a_sha` starts `7a85308fd126` (v1) and `prompt_b_sha` is
CURRENT's (`b3291ca4a550` for v2, promoted 2026-09-26; they were equal while CURRENT was
v1); `spec_sha` equals `shasum -a 256 SPEC.md | cut -c1-64`;
`feed_age_s` is under 60; `jev.*` all `null`. Then:

```bash
cd ~/Projects/jev-paper-loop && ls data/ && test ! -e data/sends.tsv && echo "no ledger row: correct"
```

**What changes.** One row in `data/decisions.jsonl` and `data/heartbeat`
(both gitignored); three GETs to api.coinbase.com. **What it does not do.**
Send anything to api.typesafe.ai, read any key, write `data/sends.tsv`. Allowed
before step 0.

## 5. The first attended live run  (a few hours; ~$0.002/h)

**Why.** Before launchd runs it unwatched, watch it: `make run` is `--forever`
in a terminal, one tick a minute on the wall-clock minute, SIGINT/SIGTERM
finish the current write. Two to three hours is 120–180 ticks: enough rows
for `make report` to show the absences, the latency, the key path, the drift
count and the first outcome joins (the first join lands 15 min in). Only
after steps 0 and 1.

```bash
cd ~/Projects/jev-paper-loop && make run
```

By hand: `/opt/homebrew/bin/python3 -m loop.cycle --forever`. Leave it; come
back; `Ctrl-C`. Then:

```bash
cd ~/Projects/jev-paper-loop && make report && wc -l data/decisions.jsonl data/sends.tsv && grep -c 'typesafe-api-key-loop' data/decisions.jsonl && cat data/heartbeat
```

Read: live rows ≈ ledger rows minus the header (a retry adds a ledger row,
not a decision row); every live row's `jev.key_path` is
`file:~/.secondbrain-secrets/typesafe-api-key-loop`; `drift` count 0 and one
distinct `model_answered` = `jev-1.13.0`; absences 0 or each one explained by
`logs/`; mean latency under a few seconds; `$ to date` a fraction of a cent
per hour; `data/HALT` absent (if it exists, read it — the spend guard or a
rejected key wrote it — fix the cause, then `rm data/HALT`).

**What changes.** `data/decisions.jsonl`, `data/sends.tsv`, `data/heartbeat`;
one Jev request per minute on the loop key. **What it does not change.**
`prompts/` (arm B is still `v1`, so these rows are also a free test-retest of
the model), anything under launchd, the brain, the crypto repo.

## 6. Seal PREREG.md  (~2 min; only when a v2 is about to be promoted)

**Why.** `PREREG.md` is the test and the stop rules, written before the data.
It is a pre-registration only if it is provably older than the first row it
could have been tuned on: the first row with `prompt_b != "v1"`. The seal is a
git tag on the commit that fills T0 and the signature (PREREG §11); it must
also precede the day-14 look. Until you run `bin/promote` there is no v2 and
nothing to seal. The venue fee (SPEC §10) no longer decides H1 (2026-09-24,
decided by Alex: the primary cell is 0 bps, gross), so it does not block the
seal; but verify it in-account before the sample's first row anyway, because
`FEE_BPS_COLUMNS` is in SPEC.md (whose sha every row carries) and a value
other than 120 changes `FEE_BPS_VENUE` and its descriptive column.

Fill `T0` (the first minute boundary ≥ 24 h after the first live launchd row;
`head -1`-style: `grep -m1 '"mode":"live"' data/decisions.jsonl | cut -c1-80` —
rows are compact JSON, no space after the colon —
shows the first live tick) and the two signature fields, then:

```bash
cd ~/Projects/jev-paper-loop && git add PREREG.md && git commit -m "PREREG: T0 and signature" && git tag prereg-v1 "$(git rev-parse HEAD)" && git tag --points-at HEAD
```

Want `prereg-v1`. Only then `bin/promote proposals/<date>.json <k>` (it
refuses while `git tag -l prereg-v1` is empty). From here on the sample's
numbers are `/opt/homebrew/bin/python3 -m loop.report --t0 <T0>`: rows cut to
`[T0, T0 + 28 d)`, every arm replayed from flat at T0, the 900 s block
statistic S_k of PREREG §3–§4 beside the per-tick figures. The day-14 look
(PREREG §8.4) is `/opt/homebrew/bin/python3 -m loop.report --health --t0 <T0>`:
report §1–§3 only, no H1 or H2 number.

**What changes.** One commit, one tag. **What it does not change.** Any file
after this: a later edit to `PREREG.md` is `prereg-v2` and applies only to a
second 28-day block (PREREG §8.5).

## 7. Install the two plists  (~3 min; only after steps 0 and 1)

**Why.** PROTOCOL.md §3.10: hand-installed, never by a script, same as the
canary. The loop plist runs `python3 -m loop.cycle --once` every calendar
minute at :00 (`StartCalendarInterval`, installed 2026-09-27 05:18Z on a decision of
2026-09-26; it was
`StartInterval 60`, a ~61 s grid that skipped ~28 minutes a day) with
`RunAtLoad`, so the first tick — a live send — fires the moment it is
bootstrapped; the nightly runs `nightly/propose.sh` at 03:30 local. Stop the
attended run first: the `flock` would turn every launchd tick into an
`absence: "lock"` row until you did.

**Swapping an installed loop plist (2026-09-26, the cadence change).** One
bootout, one copy, one bootstrap; the gap is under a minute and the first
tick fires at bootstrap. Then watch two minutes of `tick_id`s land on
consecutive minutes:

```bash
cd ~/Projects/jev-paper-loop && plutil -lint launchd/com.alexward.jevloop.loop.plist && launchctl bootout gui/$(id -u)/com.alexward.jevloop.loop; cp launchd/com.alexward.jevloop.loop.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alexward.jevloop.loop.plist && sleep 130 && tail -3 logs/loop-launchd.log | cut -c1-60 && launchctl print gui/$(id -u)/com.alexward.jevloop.loop | grep -E 'state|last exit'
```

```bash
cd ~/Projects/jev-paper-loop && mkdir -p logs && plutil -lint launchd/com.alexward.jevloop.loop.plist launchd/com.alexward.jevloop.nightly.plist && cp launchd/com.alexward.jevloop.loop.plist launchd/com.alexward.jevloop.nightly.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alexward.jevloop.loop.plist && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alexward.jevloop.nightly.plist && launchctl list | grep jevloop
```

`Bootstrap failed: 5: Input/output error` on the loop was spurious for the
canary (RunAtLoad had already fired); the rows are the proof. Two minutes
later:

```bash
cd ~/Projects/jev-paper-loop && cat data/heartbeat && tail -2 data/decisions.jsonl | cut -c1-120 && tail -3 logs/loop-launchd.log && launchctl print gui/$(id -u)/com.alexward.jevloop.loop | grep -E 'state|last exit'
```

Want a heartbeat under two minutes old, `last exit code = 0`, no traceback.
Then System Settings → General → Login Items & Extensions → Allow in the
Background: both `com.alexward.jevloop.*` entries (they may show as
`python3` / `bash`) must be ON, or macOS silently stops them after a reboot.
Next morning: `ls proposals/` for the first `<date>.json` and `.md`, and
`tail logs/nightly-launchd.log`.

Undo, either or both: `launchctl bootout gui/$(id -u)/com.alexward.jevloop.loop`
and `launchctl bootout gui/$(id -u)/com.alexward.jevloop.nightly`.

**What changes.** Two files in `~/Library/LaunchAgents/`, two agents; ~$0.04/day
of Jev from the loop, one Claude call and ~$0.005 of Jev per night. **What
it does not change.** `prompts/` — the nightly writes `proposals/` only and
`bin/promote` is yours; the canary and the brain's agents; anything the other
fourteen plists in that folder do.

## 8. The sleep and reboot habit  (nothing to install)

**Why.** These are `gui/` agents: they run only while you are logged in, and
with FileVault on nothing runs between a reboot and the login screen. The
loop tolerates gaps (an absent minute is a `gap` outcome, never a wrong row),
but PREREG stop rule 3 excludes any day with outcome fill under 95 % of its live
rows (about 70 unfilled rows in a full day: an isolated missed minute costs 1, a hole of
any length costs the ~15 rows before it, a sleep broken by brief wakes about one per
wake) — and three such days pause the block. Checked today:
FileVault is on; `pmset -g` shows `sleep 1` (held off only while something
asserts), `displaysleep 0`; no auto-login user is set. Keep it so:

```bash
fdesetup status && pmset -g | grep -E '^\s*(sleep|displaysleep)' && defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser 2>&1 | tail -1
```

Want `FileVault is On.`, and the last line to say the key does not exist.
The habit: plugged in; lid open (clamshell without an external display
sleeps); **on battery the profile is `sleep 1` and `powernap 1`, so an unplugged Mac sleeps
within a minute of idling and wakes only for seconds at a time — 2026-09-26 lost 840 minutes
that way, 0.2 points from a BAD day**; after ANY reboot, log in — both agents load at login, the loop's
first tick is immediate, and `cat data/heartbeat` tells you it did. Do not
turn on auto-login to fix a gap; FileVault forbids it anyway, and the
missing minutes are the honest record.

**What changes.** Nothing. **What this is not.** A reason for `caffeinate`
on the loop (a tick is seconds; the nightly already wraps its one long call)
or for any change to a security setting.

---

Not happening, on purpose: no script installs a plist, no plist writes
`prompts/`, no tick reads a confidence, and nothing here touches
`~/Projects/crypto-trading-system` or `~/Projects/Claude`.

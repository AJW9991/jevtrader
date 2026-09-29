# Your steps — 2026-09-23

Nine steps, in order, each one yours because it changes what runs without you
watching, spends money, or signs something. Steps 3 and 4 are free and can be
run today; nothing in 5–8 may happen before step 0, and 5 and 7 also need
step 1. Each step says what it changes and what it does not. Backups use the
house pattern `<file>.bak-YYYYMMDD-HHMMSS` beside the file (`*.bak-*` is
gitignored here).

§10 is PREREG-v2's, the second block: the probe's volume, the trial night, v2's tables, the draft
tag, the switch of 2026-10-23, the seal and the morning check over three stores.

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

The same thing by hand (191 tests at integration, 2026-09-24; 836 by 2026-09-28, also run by CI on every push (Linux, macOS, and six modes: `make test-modes`)):

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
in a terminal, one tick a minute on the wall-clock minute. SIGTERM finishes the
current write, releases the lock and exits 0; Ctrl-C (SIGINT) is not handled and
stops the run where it is, with a traceback (in the sleep between ticks that
costs nothing). Two to three hours is 120–180 ticks: enough rows
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
health is `make health` (`loop.report --health --sample`): rows cut to
`[T0, T0 + 28 d)`, §1–§3 only. `loop.report --t0 <T0>` withholds §4–§7 (every arm
replayed from flat at T0, the 900 s block statistic S_k of PREREG §3–§4) until
2026-10-23 21:40Z; `--unblind` prints them and is a look. The day-28 numbers are
`make results`. The day-14 look
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
within a minute of idling and wakes only for seconds at a time — 2026-09-26 lost 840-935 minutes
that way; the UTC day's fill was 90.2 % (the 09-25 review), but the sample's days are T0-anchored, and
d01 (09-25 21:40Z to 09-26 21:40Z) closed at 95.2 %, 0.2 points above stop rule 3's line, and is kept
(`make status`, 2026-09-28)**; after ANY reboot, log in — both agents load at login, the loop's
first tick is immediate, and `cat data/heartbeat` tells you it did. Do not
turn on auto-login to fix a gap; FileVault forbids it anyway, and the
missing minutes are the honest record.

**What changes.** Nothing. **What this is not.** A reason for `caffeinate`
on the loop (a tick is seconds; the nightly already wraps its one long call)
or for any change to a security setting.

## 9. The backup copy  (~2 min; hand-installed)

The sealed sample lives in one place: `data/decisions.jsonl` on this Mac, with no Time Machine
destination and no iCloud mirror (checked 2026-09-28). `bin/backup-data` copies `data/` and
`logs/` with rsync to the iCloud Drive folder `jevtrader-backup` (beside the crypto repo's
mirror), sends nothing, and writes nothing under the repo but one line per run in
`logs/backup.log`. It refuses a destination inside the repo or under the crypto repo. A file
appended mid-copy arrives torn at its end; the readers keep every whole row before the tear
and the next run replaces the file. `tests/test_backup.py` covers the copy and the refusals.

First copy by hand, then install the hourly job (at :45, and once at load):

```bash
cd ~/Projects/jev-paper-loop && make backup && ls -la "$HOME/Library/Mobile Documents/com~apple~CloudDocs/jevtrader-backup/data/" | head -5
```

```bash
cd ~/Projects/jev-paper-loop && plutil -lint launchd/com.alexward.jevloop.backup.plist && cp launchd/com.alexward.jevloop.backup.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alexward.jevloop.backup.plist && sleep 3 && launchctl print gui/$(id -u)/com.alexward.jevloop.backup | grep -E 'state =|last exit' && tail -1 logs/backup.log
```

**Installed 2026-09-29 04:12Z and the first launchd run FAILED, exit 1** (logs/backup-launchd.log:
`rsync: .../jevtrader-backup/data/: open: Operation not permitted`), while `make backup` from the
terminal five seconds earlier was OK. iCloud Drive is a TCC-protected location: a terminal inherits
Terminal's Files-and-Folders grant, a launchd job does not, and launchd never prompts. Two ways out,
yours (system settings):
- **Narrow:** System Settings → Privacy & Security → Full Disk Access → `+` → `/usr/bin/rsync` (press
  ⌘⇧G in the file dialog and type the path). rsync is the process that opens the destination and it
  spawns nothing. Then test the job without waiting for :45:
  ```bash
  launchctl kickstart gui/$(id -u)/com.alexward.jevloop.backup && sleep 5 && tail -1 ~/Projects/jev-paper-loop/logs/backup.log
  ```
  If TCC attributes the access to the job's `/bin/bash` instead, the line still says FAIL; then:
- **By hand, daily:** `make backup` beside the morning `make status` (a day is the most that can be
  lost), and boot the hourly job out so it stops writing a FAIL line every hour:
  ```bash
  launchctl bootout gui/$(id -u)/com.alexward.jevloop.backup
  ```
Not recommended: Full Disk Access for `/bin/bash`. Every launchd bash job would carry it, and the
nightly's `claude -p`, a child of propose.sh, would inherit that reach.

Undo: `launchctl bootout gui/$(id -u)/com.alexward.jevloop.backup`. Another destination:
`bin/backup-data /Volumes/<disk>/jevtrader-backup` (edit the plist's ProgramArguments to
match, and `tests/test_nightly.py` pins the plist).

## 10. PREREG-v2: the probe's volume, the trial night, v2's tables, the draft tag, the switch, the seal

Written in the build (branch `prereg-v2`, worktree `~/Projects/jev-paper-loop-v2`) and frozen with it by the tag
`prereg-v2-draft` (PREREG-v2 §10); where this and PREREG-v2.md differ, PREREG-v2.md wins. Until switch step (6) a
command runs in the worktree unless it names `~/Projects/jev-paper-loop` (the live checkout, `main`); from (6) on the
build is `main` and everything runs in the live checkout. Nothing here is run by a script, and each step that sends,
installs or tags is yours.

### 10.1 The probe's volume (2026-10-01 UTC, once) and the products' commit

The probe's run over D = 2026-09-30 (`bin/probe run --day 2026-09-30 --out probe/2026-09-30`, under `caffeinate -i`,
started by hand before D) ends by itself after D's last slot. First, `main` into the build: PREREG-v2 §13 (0) merges
it "before any further edit of PREREG-v2.md on the build branch", and this step makes the first (a void D's §14 entry,
§2's products and their §14 entry); once is enough, and every later edit before the draft tag is a §14 entry:

```bash
cd ~/Projects/jev-paper-loop-v2 && git merge --no-edit main && make test
```

Then, on 2026-10-01 (UTC), once (PREREG-v2 §2):

```bash
cd ~/Projects/jev-paper-loop-v2 && bin/probe volume --day 2026-09-30 --out probe/2026-09-30 && make probe-summarize DIR=probe/2026-09-30
```

`volume` exits 1 when the candles endpoint does not answer (§2: criterion (2) is then restated in §14).
`probe-summarize` prints every criterion per candidate, each product's tick and atoms (a10, a90), and the two chosen;
exit 1 is a void D (§2 names what follows: the next UTC day, once, named in §14 before it starts, and §2's
`**D = …**` with it, which `bin/seal-check --draft` reads). Commit the directory verbatim, on its own (the run's stderr
file beside it, if you sent it there, goes in with it or out of the tree: the draft tag wants a clean tree):

```bash
cd ~/Projects/jev-paper-loop-v2 && git add probe/2026-09-30 && git commit -m "probe/2026-09-30: bin/probe's rows, run.json and volume.json, verbatim (PREREG-v2 §2)"
```

Then one commit adds the products (tests/test_products_added.py says what it holds): `loop/config.py` (`PRODUCTS` in
summarize's order, `TICK_P`, `LIQ_ATOMS` from its a10/a90, `LIQ_THIN_FALLBACK`), the pins in `tests/test_frozen.py`
(`THRESHOLDS`, `RULE_C` per product), and the two loop plists; PREREG-v2.md §2's Products, `TICK_p` and Atoms fields
and their §14 entry go with it or right after:

```bash
cd ~/Projects/jev-paper-loop-v2 && bin/plists --write && plutil -lint launchd/*.plist && make test
```

### 10.2 The trial night (before the draft tag, once §2's products are in)

```bash
cd ~/Projects/jev-paper-loop-v2 && /bin/bash nightly/trial-night.sh
```

One real `claude -p` call (PREREG-v2 §8) through this tree's `propose.sh`, on a synthetic three-product log in a temp
root outside both checkouts; it writes nothing under either tree's `data/`, `logs/` or `proposals/`. It reads only the
exit code, the `claude exit`, `claude model` and "user memory not loaded" lines and the digest's products. PASS needs
all of them; its NOT SHOWN line (whether `--settings` still applies under the fresh config dir) is yours to settle
before the tag, as a §14 entry or an amended §8. A refused model id allows §8's one substitute, written into §8 before
the tag.

### 10.3 v2's own tables (before the draft tag; attended, 81 sends per product, about $0.01)

`prompts/CURRENT` must name `v2` here (a merge of `main` after one of v1's promotions moves it, and `--table-only`
then refuses). From the worktree, `jev.py`'s ledger rows land in this tree's `data/sends.tsv` (created by the send,
gitignored) and `policy_table` reads this tree's `data/HALT`, not the live one, so the first command checks the live
HALT itself:

```bash
cd ~/Projects/jev-paper-loop-v2 && test "$(cat prompts/CURRENT)" = v2 && test ! -e ~/Projects/jev-paper-loop/data/HALT && printf '{"candidates": []}\n' > proposals/v2-tables.json && python3 -m nightly.policy_table proposals/v2-tables.json && git add proposals/v2-tables.md && git commit -m "proposals/v2-tables.md: v2's own tables, CURRENT only, no candidate (PREREG-v2 §8)"
```

```bash
cd ~/Projects/jev-paper-loop-v2 && bin/promote --table-only proposals/v2-tables.json
```

Then commit `prompts/v2.table.*.json` with their pins in `tests/test_frozen.py`, the message naming the answering Jev
version (each table's `model_answered`), and a §14 entry naming the run. An unanswered state is re-sent only by
`python3 -m nightly.policy_table --fill proposals/v2-tables.table.json` (§8).

### 10.4 The draft tag (before `make results` on 2026-10-23)

First, on `main` (§10: the guard and any other `main` tooling land before the draft tag). The build's commit `0898b74`
is made for `main`: it sits on `097edc0`, the v1 results guard, made on the tree `main` and `prereg-v2` last shared (it
touches the Makefile's `results` recipe, ERRATA.md, `bin/results-v1` and its test; no loop code), and adds ERRATA.md's
v2 deviations table with `tests/test_errata.py`'s reading of it, byte for byte as the build has them. Merged, as below,
both are the same commits on both branches, so the pre-tag merge meets no conflict over them; and with the table in the
base of switch step (4)'s merge, `main`'s additions at the end of ERRATA.md after the draft tag merge cleanly there
(with the table only on the build, both sides add at the same end of the file and (4) stops). `git cherry-pick 097edc0
0898b74` works too, and then the pre-tag merge stops on the Makefile's `results` recipe:

```bash
cd ~/Projects/jev-paper-loop && git merge --no-ff --no-edit 0898b74 && make test
```

The backup-job fix (§9) lands on `main` too. Then, on the build branch, all of (PREREG-v2 §10, §13):
- §1, §2, §3 and §8's pre-tag values written (the products, `TICK_p`, the atoms, arm A's per-product state counts,
  the slow model's id and its night from `grep 'claude model' ~/Projects/jev-paper-loop/logs/propose.log`), each edit a
  dated §14 entry saying what its author had read; no `________` left outside §12;
- SPEC v2 committed; the probe's directory and one v2 table per product committed (10.1, 10.3); the trial night PASS
  (10.2);
- `tests/test_frozen.py` pinning by sha what §10 lists (SPEC v2, CONTRACT, PREREG-v2.md, `nightly/PROMPT.md` v2, the
  sources of `nightly/digest.py` and `nightly/policy_table.py`, `prompts/v2.json`, one v2 table per product,
  `THRESHOLDS` with `TICK_p` and the atoms, every §14 constant, the inference constants, `RULE_C` per product). The pins
  of PREREG-v2.md and of the v2 tables stay one per line, `"<path>": "<sha256>",`: after the tag `bin/seal-check`
  lets only those lines change in that file.

Then (§13), the merge of `main`, the suite and a push:

```bash
cd ~/Projects/jev-paper-loop-v2 && git merge --no-edit main && make test && git push origin prereg-v2
```

If the merge stops on the Makefile's `results` recipe (the guard cherry-picked rather than merged; main's recipe is
v1's run behind the guard, the build's is v2's, which checks `prereg-v2-seal`): keep the build's recipe and main's
other hunks, `make test`, commit. ERRATA.md: the v2 deviations table stays last. Once CI is green on that sha (`gh run list --branch prereg-v2 --limit 1`):

```bash
cd ~/Projects/jev-paper-loop-v2 && test -z "$(git status --porcelain)" && bin/seal-check --draft && git tag -a prereg-v2-draft -m "frozen before make results (v1)" HEAD && git push origin prereg-v2-draft
```

`bin/seal-check --draft` refuses a `________` left outside §12, a missing `probe/<D>/` file or v2 table, and an edit of
PREREG-v2.md since `prereg-v2-doc` while §14 reads "(none yet)". From the tag until switch step (6), `main` takes only
RESULTS.md, HANDOFF.md, additions at the end of ERRATA.md (under a heading of their own: rows under the v2 deviations
heading are read as deviations), `proposals/`, `data/exclusions.tsv` and v1's `bin/promote` commits (§13). A fix `main`
needs in that window is a listed deviation: its own commit on `main`, and its row at the end of ERRATA.md, under the v2
deviations table while that is the file's end and, once another heading follows it, under a new
`## v2 deviations (continued)` heading with the table's header row (`bin/seal-check` reads both).

### 10.5 The switch (2026-10-23, after `make results`: PREREG-v2 §10's steps 1-11a)

One terminal, in order (steps 5 and 9 share a shell variable). A stop anywhere from (6) to (8) is
`cd ~/Projects/jev-paper-loop && git reset --hard ORIG_HEAD` and a re-bootstrap of v1's SOL loop
(`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alexward.jevloop.loop.plist`, and the nightly).

(1) v1's day 28, not before ~21:56Z (the last block's t + h row); it refuses, exit 3, until then, and without the draft
tag on `prereg-v2` (`make results NO_V2=1` only if v2 is not run: it says so in RESULTS.md):

```bash
cd ~/Projects/jev-paper-loop && tail -1 data/decisions.jsonl | cut -c1-40 && make results
```

(2) RESULTS.md with v1's `data/exclusions.tsv`, or a line that it is absent:

```bash
cd ~/Projects/jev-paper-loop && if [ -e data/exclusions.tsv ]; then git add RESULTS.md data/exclusions.tsv && git commit -m "RESULTS.md (v1) and data/exclusions.tsv"; else git add RESULTS.md && git commit -m "RESULTS.md (v1); data/exclusions.tsv is absent: no day was listed"; fi
```

(3) The tag:

```bash
cd ~/Projects/jev-paper-loop && git tag -a results-v1 -m "v1's result (PREREG.md), committed" HEAD && git push origin results-v1
```

(4) In the worktree: merge `main`, the suite there, and the ancestry, or stop with v1 running:

```bash
cd ~/Projects/jev-paper-loop-v2 && git merge --no-edit main && make test && git merge-base --is-ancestor main prereg-v2 && echo "(4) OK"
```

If it stops on ERRATA.md (`main` did not take `0898b74` before the tag, 10.4): keep this branch's ERRATA.md whole and
put `main`'s additions after it (`git diff $(git merge-base HEAD MERGE_HEAD) MERGE_HEAD -- ERRATA.md` shows them), so
the file still begins with the draft tag's text (§13 (c)); then `git add ERRATA.md && git commit --no-edit && make test`.

(4a) The nightly: booted out after 07:30Z on the switch day (§10) and bootstrapped again after (11). It fires at 03:30
local (08:30Z while Chicago is on CDT): boot it out before then and 10-23 has no night, or after its night has
finished (`tail -3 logs/propose.log`):

```bash
launchctl bootout gui/$(id -u)/com.alexward.jevloop.nightly
```

(5) Wait for this minute's SOL heartbeat, then boot the SOL loop out and keep the minute for (9):

```bash
cd ~/Projects/jev-paper-loop && M=$(date -u +%Y-%m-%dT%H:%M) && until grep -q "^$M" data/heartbeat; do sleep 1; done && launchctl bootout gui/$(id -u)/com.alexward.jevloop.loop && OUT=$(date -u +%H%M) && echo "SOL out at $OUT"
```

(6) `main` takes the build; (7) the suite:

```bash
cd ~/Projects/jev-paper-loop && git merge --ff-only prereg-v2 && make test
```

(8) CURRENT names `v2`, or is set to it and committed, naming what it replaced; else the line in HANDOFF.md:

```bash
cd ~/Projects/jev-paper-loop && WAS=$(cat prompts/CURRENT) && if [ "$WAS" = v2 ]; then echo "- $(date -u +%Y-%m-%dT%H:%MZ) switch step 8: CURRENT already v2" >> HANDOFF.md; else printf 'v2\n' > prompts/CURRENT && git add prompts/CURRENT && git commit -m "prompts/CURRENT: v2 at the switch (PREREG-v2 §10 step 8), replacing $WAS"; fi
```

(8a) `data/HALT` absent, or its v1 cause recorded (HANDOFF.md) and the file removed:

```bash
cd ~/Projects/jev-paper-loop && if [ -e data/HALT ]; then cat data/HALT; fi
```

(8b) Every plist in `launchd/` into `~/Library/LaunchAgents`, each compared. The one-process plist is in
`launchd/one-process/` and is not copied; the nightly and backup plists are unchanged, so their copies are the same
bytes:

```bash
cd ~/Projects/jev-paper-loop && plutil -lint launchd/*.plist && for f in launchd/*.plist; do cp "$f" ~/Library/LaunchAgents/ && cmp "$f" "$HOME/Library/LaunchAgents/${f#launchd/}" || echo "DIFFERS: $f"; done
```

(9) SOL in a later minute than its bootout:

```bash
until [ "$(date -u +%H%M)" != "$OUT" ]; do sleep 1; done; launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alexward.jevloop.loop.plist
```

(10) The two named products:

```bash
cd ~/Projects/jev-paper-loop && for p in $(python3 -c 'from loop import config; print(*[p for p in config.PRODUCTS if p != config.PRODUCT])'); do launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alexward.jevloop.loop.$p.plist; done
```

(11) Two minutes later, three heartbeats (and in System Settings → General → Login Items & Extensions → Allow in the
Background, the new `com.alexward.jevloop.loop.*` entries ON, as in §7); then the nightly again:

```bash
cd ~/Projects/jev-paper-loop && make status && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alexward.jevloop.nightly.plist
```

(11a) The answering Jev version of the first shakedown rows against the pinned tables' (§8, §12): each product's
first three live rows carrying this tree's SPEC sha (SOL's v1 rows carry prereg-v1's and are not read); a product with
no such row yet says so and is run again a minute later:

```bash
cd ~/Projects/jev-paper-loop && python3 - <<'EOF'
import hashlib, json
from loop import config
with open("SPEC.md", "rb") as fh:
    sha = hashlib.sha256(fh.read()).hexdigest()
for p in config.PRODUCTS:
    with open(f"prompts/v2.table.{p}.json", encoding="utf-8") as fh:
        pinned = json.load(fh)["model_answered"]
    got = []
    try:
        with open(config.store(p).decisions, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if sha not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("spec_sha") == sha and r.get("mode") == "live" and r.get("absence") is None:
                    got.append(r.get("model_answered"))
                    if len(got) == 3:
                        break
    except FileNotFoundError:
        pass
    if not got:
        print(p, f"no answered v2 row yet (tables: {pinned}): run this again in a minute")
        continue
    print(p, "first v2 rows:", sorted(set(got), key=str), "tables:", pinned,
          "same" if set(got) == {pinned} else "DIFFERENT: rebuild the tables once (PREREG-v2 §8, §12)")
EOF
```

Different: the tables are rebuilt once, as in 10.3 but from `~/Projects/jev-paper-loop` (proposal
`proposals/v2-tables-rebuild.json`); `bin/promote --table-only` allows one rebuild after the draft tag, for a Jev
version other than the pinned one, and none after the seal. One commit holds the rebuilt tables, §12's line
("Tables rebuilt at the switch: `<version>; <product> <sha, 12 hex or more>, ...`", the shas `--table-only` prints) and
the pins of both in `tests/test_frozen.py`. Same: §12's line reads `no` (it can go in with the seal's fields).

### 10.6 The seal (on `main`, once §12 is filled, before T0_v2)

T_first_v2 is the latest, over products, of each product's first live row carrying this tree's SPEC sha (§2), read as
that row's `tick_id`, as the sealed PREREG.md reads T_first ("`tick_id` of the first row", its §2) and as the sample
window is cut; T0_v2 is the first minute boundary at or after T_first_v2 + 86,400 s, which is T_first_v2 + 86,400 s
itself, a `tick_id` being a minute boundary:

```bash
cd ~/Projects/jev-paper-loop && python3 - <<'EOF'
import datetime, hashlib, json
from loop import config
with open("SPEC.md", "rb") as fh:
    sha = hashlib.sha256(fh.read()).hexdigest()
first = {}
for p in config.PRODUCTS:
    try:
        with open(config.store(p).decisions, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if sha not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("spec_sha") == sha and r.get("mode") == "live" and r.get("absence") is None:
                    first[p] = datetime.datetime.strptime(r["tick_id"], "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc)
                    print(p, "first v2 live row:", r["tick_id"], r.get("ts_rx"))
                    break
    except FileNotFoundError:
        pass
missing = [p for p in config.PRODUCTS if p not in first]
if missing:
    raise SystemExit(f"no v2 live row yet for {missing}")
t = max(first.values())
end = t + datetime.timedelta(days=1)
t0 = end.replace(second=0) + datetime.timedelta(minutes=1 if end.second else 0)
print("T_first_v2:", t.strftime("%Y%m%dT%H%M%SZ"), "  T0_v2:", t0.strftime("%Y%m%dT%H%M00Z"))
EOF
```

Fill §12 in one commit with the PREREG-v2.md pin in `tests/test_frozen.py`: the fee tiers as read in-account, with the
read time (`Fee tiers (30-day band / maker / taker, read UTC `2026-10-24T09:00Z`): `$0-$10K / 0.60 % / 1.20 %;
$10K-$50K / ...``, rows joined by `;`, the form `make dash` and the report read), the rebuild line if (11a) did not
write it, T_first_v2 and T0_v2 (each a tick_id, `YYYYMMDDTHHMM00Z`, as printed), who sealed and the date. Then:

```bash
cd ~/Projects/jev-paper-loop && bin/seal-check && git tag -a prereg-v2-seal -m "PREREG-v2 sealed" HEAD && git push origin prereg-v2-seal
```

`bin/seal-check` prints the whole `-U0` diff from the draft tag and each check, (a)-(e); (e) is `make test`, a few
minutes. A fix it refuses that §13 (c) does not cover is its own commit and one row added at the end of ERRATA.md: under
the v2 deviations table while that is the file's end, else under a new `## v2 deviations (continued)` heading with the
table's header row. Not sealed before T0_v2: the block has not started; T0_v2 is re-derived at sealing from the commit
time of the fix that lets `bin/seal-check` pass (§13). No seal by 2026-11-06: RESULTS.md records v2 as not run.

### 10.7 Every morning

```bash
cd ~/Projects/jev-paper-loop && make status
```

Three heartbeats, one per store; HALT; each `data/PAUSE.<PRODUCT>`; a pending version on its own line; today's spend
over every product's log against the tripwire (0.25 × products); the sample day from §12's T0_v2. `make backup` beside
it while the hourly job is out (§9). The day-14 look is `make health` and nothing more (§9.5).

### 10.8 Only if the shakedown shows `feed: http-429` lines: the one-process plist

```bash
cd ~/Projects/jev-paper-loop && grep -c 'feed: http-429' logs/loop-launchd*.log
```

It replaces every loop plist (a product ticked twice writes lock rows), so each one is booted out and disabled, which
keeps it from loading again at the next login, before it is bootstrapped; launchd only, not the repo (§2):

```bash
cd ~/Projects/jev-paper-loop && for l in com.alexward.jevloop.loop $(python3 -c 'from loop import config; print(*["com.alexward.jevloop.loop." + p for p in config.PRODUCTS if p != config.PRODUCT])'); do launchctl bootout gui/$(id -u)/$l; launchctl disable gui/$(id -u)/$l; done; plutil -lint launchd/one-process/com.alexward.jevloop.loop.every-product.plist && cp launchd/one-process/com.alexward.jevloop.loop.every-product.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alexward.jevloop.loop.every-product.plist
```

Back: `launchctl bootout gui/$(id -u)/com.alexward.jevloop.loop.every-product`, remove its file from
`~/Library/LaunchAgents`, then `launchctl enable` and `launchctl bootstrap` each loop plist. Its log is
`logs/loop-launchd-every-product.log`.

---

Not happening, on purpose: no script installs a plist, no plist writes
`prompts/`, no tick reads a confidence, and nothing here touches
`~/Projects/crypto-trading-system` or `~/Projects/Claude`.

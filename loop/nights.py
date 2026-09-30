"""loop/nights.py -- PREREG-v2 §8: "a refusal at the switch, in the shakedown or on any later night fails that night
like any failed night -- no proposal; the report counts failed nights with their reasons, and if no promotion results
§9.2's NO PROMOTION reading applies."

It reads logs/propose.log as nightly/propose.sh writes it, one line per event, `<UTC> propose <what>`: a run opens
with `start date=<D> dry=<0|1> root=<ROOT>` and ends with `OK <...>` or `FAIL <reason>` (propose.sh's fail() logs the
FAIL and exits). A FAIL before the run's start line (a missing python, a bad --date) belongs to no named date; it is
attributed to the day before its own UTC date, the date propose.sh defaults to (the UTC day just closed). Dry runs
(`dry=1`, `propose.sh --dry`, which calls no model) are not nights.

The nights of the sample are the UTC days D whose end (D + 1 d, 00:00Z) falls in (T0_v2, T0_v2 + 28 d]: each closes
inside the block and is digested by the night after it (CONTRACT §5; propose.sh's default date). A night is OK when a
run for D logged OK (a later refusal of a second run, "one run per day", does not undo it), FAILED when runs for D
logged only FAILs (every reason printed), and NOT RUN when no run for D was logged at all (the Mac asleep through the
slot, launchd not loaded): no proposal either way. Health only: no digest, no proposal, no answer and no outcome is
read, so it prints on any day (report §1) and in RESULTS-v2. Standard library only; this module opens the one file
read() is given.
"""
import datetime, os, re

from . import config

PROPOSE_LOG = os.path.join(config.REPO, "logs", "propose.log")
LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) propose (.*)$")
START = re.compile(r"^start date=(\d{4}-\d{2}-\d{2}) dry=(\d)\b")
UTC = datetime.timezone.utc
N_DAYS = 28


def read(path=None):
    """{"path", "lines" (None when the file is absent), "error"}: the log as text lines."""
    path = PROPOSE_LOG if path is None else path
    if not os.path.exists(path):
        return {"path": path, "lines": None, "error": None}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return {"path": path, "lines": fh.read().splitlines(), "error": None}
    except OSError as e:
        return {"path": path, "lines": None, "error": str(e)}


def _date(epoch):
    return datetime.datetime.fromtimestamp(epoch, UTC).date()


def sample_nights(t0, days=N_DAYS):
    """The UTC dates D, in order, whose end (D + 1 d at 00:00Z) falls in (t0, t0 + days x 86,400]."""
    first = _date(t0)                                   # D = t0's own date ends at the next 00:00Z, which is > t0
    last = _date(t0 + days * 86400) - datetime.timedelta(days=1)   # the last D whose end is <= t0 + 28 d
    return [first + datetime.timedelta(days=i) for i in range((last - first).days + 1)]


def runs(lines):
    """[{"date" (a date, or None for a FAIL before any start line), "ts", "dry", "end" ("OK", "FAIL" or None: no end
    line), "reasons"}] in log order. A start line while a run is open closes that run with no end line."""
    out, cur = [], None
    for raw in lines or ():
        m = LINE.match(raw.rstrip("\n"))
        if not m:
            continue
        ts, what = m.group(1), m.group(2)
        s = START.match(what)
        if s:
            cur = {"date": datetime.date.fromisoformat(s.group(1)), "ts": ts, "dry": s.group(2) != "0", "end": None,
                   "reasons": []}
            out.append(cur)
        elif what.startswith("FAIL"):
            reason = what[4:].strip() or "(no reason logged)"
            if cur is None or cur["end"] is not None:        # a FAIL before its run's start line: propose.sh's default date
                d = datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").date() - datetime.timedelta(days=1)
                out.append({"date": d, "ts": ts, "dry": False, "end": "FAIL", "reasons": [reason], "loose": True})
            else:
                cur["end"], cur["reasons"] = "FAIL", cur["reasons"] + [reason]
        elif what.startswith("OK") and cur is not None and cur["end"] is None:
            cur["end"] = "OK"
    return out


def count(log, t0, days=N_DAYS):
    """{"nights": [(date, status "OK" | "FAILED" | "NOT RUN", reasons)], "failed": n FAILED + NOT RUN, "error"} over the
    sample's nights (sample_nights), from read()'s dict."""
    rs = [r for r in runs(log["lines"]) if not r["dry"]]
    nights = []
    for d in sample_nights(t0, days):
        mine = [r for r in rs if r["date"] == d]
        if any(r["end"] == "OK" for r in mine):
            nights.append((d, "OK", []))
        elif mine:
            why = [x for r in mine for x in (r["reasons"] or ["the run logged no OK and no FAIL line (it did not finish)"])]
            nights.append((d, "FAILED", why))
        else:
            nights.append((d, "NOT RUN", []))
    return {"nights": nights, "failed": sum(1 for _, s, _ in nights if s != "OK"), "error": log["error"],
            "absent": log["lines"] is None and not log["error"]}


def lines(c, path):
    """The count's lines: the total, then every night that is not OK with its reasons, one line each."""
    n = len(c["nights"])
    if c["error"]:
        return [f"  failed nights (PREREG-v2 §8): {path} cannot be read: {c['error']}"]
    head = (f"  failed nights (PREREG-v2 §8; {path}, the nights digesting the UTC days that close in the sample): {c['failed']}"
            f" of {n}" + (" (the log is absent: no night was logged)" if c["absent"] else ""))
    out = [head]
    for d, status, why in c["nights"]:
        if status == "OK":
            continue
        out.append(f"    {d.isoformat()}: {status}" + (": " + "; ".join(why) if why else
                                                        ": no run logged for this date (no proposal)"))
    return out

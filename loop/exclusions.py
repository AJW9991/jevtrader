"""loop/exclusions.py -- data/exclusions.tsv, stop rule 3's list of excluded days (PREREG §8.3).

The file is Alex's act, written by hand; this only reads it. inference (day 28) applies it, and
`make status` shows it each morning, so a line the parser refuses is seen the day it is written,
not on day 28. Standard library only; no measurement here.
"""
import os

from . import report

N_DAYS = report.SAMPLE_DAYS                  # 28


def read_exclusions(path):
    """data/exclusions.tsv: header 'day  fill%  jev-err%  reason' (tab- or space-separated, as PREREG
    §8.3 prints it), one line per excluded day, the day as dNN or NN (T0-anchored, PREREG §2 as read
    2026-09-26). Returns (set of N, the lines verbatim). A day outside 1..28 or an unparseable day
    is an error: the file is reproduced in the write-up."""
    days, lines = set(), []
    if not path or not os.path.exists(path):
        return days, lines
    with open(path, encoding="utf-8") as fh:
        for i, raw in enumerate(fh):
            line = raw.rstrip("\n")
            if not line.strip() or (i == 0 and line.lower().startswith("day")):
                continue
            parts = line.split(None, 1)                 # any whitespace: a tab, or the two spaces PREREG prints
            tok = parts[0] if parts else ""
            num = tok[1:] if tok[:1] in "dD" else tok
            if not num.isdigit() or not 1 <= int(num) <= N_DAYS:
                raise ValueError(f"{path}:{i + 1}: day {tok!r} is not d01..d{N_DAYS:02d}")
            days.add(int(num))
            lines.append(line)
    return days, lines


def status_line(path):
    """One line for `make status`: the days the file excludes, or why it cannot be read."""
    try:
        days, _ = read_exclusions(path)
    except ValueError as e:
        return f"exclusions: REFUSED, fix before day 28: {e}"
    except OSError as e:
        return f"exclusions: {path} cannot be read: {e.strerror or e}"
    if not days:
        return f"exclusions: none ({path} {'absent' if not os.path.exists(path) else 'has no day line'})"
    return f"exclusions: {len(days)} day(s) excluded: " + " ".join(f"d{d:02d}" for d in sorted(days)) + f" ({path})"

"""loop/exclusions.py -- data/exclusions.tsv, stop rule 3's list of excluded days (PREREG §8.3).

The file is Alex's act, written by hand; this only reads it. inference (day 28) applies it, and
`make status` shows it each morning, so a line the parser refuses is seen the day it is written,
not on day 28. Standard library only; no measurement here.
"""
import os, re

from . import report

N_DAYS = report.SAMPLE_DAYS                  # 28


def read_exclusions(path):
    """data/exclusions.tsv: header 'day  fill%  jev-err%  reason' (tab-separated, or two spaces as PREREG
    §8.3 prints it; single spaces are refused), one line per excluded day, the day as dNN or NN (T0-anchored, PREREG §2 as read
    2026-09-26). Returns (set of N, the lines verbatim). A day outside 1..28 or an unparseable day
    is an error: the file is reproduced in the write-up."""
    days, lines = set(), []
    if not path or not os.path.exists(path):
        return days, lines
    try:
        with open(path, encoding="utf-8") as fh:
            raws = fh.read().split("\n")
    except UnicodeDecodeError as e:
        raise ValueError(f"{path}: not UTF-8 ({e.reason} at byte {e.start})") from None
    for i, line in enumerate(raws):
        if not line.strip() or (i == 0 and line.lower().startswith("day")):
            continue
        tok = _day_field(line)
        num = tok[1:] if tok[:1] in "dD" else tok
        if not (num.isascii() and num.isdigit()) or not 1 <= int(num) <= N_DAYS:
            raise ValueError(f"{path}:{i + 1}: day {tok!r} is not d01..d{N_DAYS:02d} (the line: {line!r})")
        days.add(int(num))
        lines.append(line)
    return days, lines


def _day_field(line):
    """The day field by the file's own separator: before the first tab when the line has one; else
    before the first run of two or more spaces (as PREREG §8.3 prints the line). A line of single
    spaces is ambiguous ('d1 6 80.0 0.0' is d1 or a typo for d16) and is returned whole, as is
    anything else, so the caller refuses it: a typo such as 'd1 6' or 'd06 d07' must never become
    a different day, or part of one, at day 28."""
    if "\t" in line:
        return line.split("\t", 1)[0].strip()
    parts = re.split(r" {2,}", line.strip(), maxsplit=1)
    return parts[0] if len(parts) == 2 else line.strip()


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

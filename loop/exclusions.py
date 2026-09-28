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
    §8.3 prints it; see _is_header for what line 1 may be), one line per excluded day (tab-separated or
    two spaces; single spaces are refused), the day as dNN or NN (T0-anchored, PREREG §2 as read
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
        if not line.strip() or (i == 0 and _is_header(line)):
            continue
        tok, why = _day_field(line)
        num = tok[1:] if tok[:1] in "dD" else tok
        if not (num.isascii() and num.isdigit() and len(num) <= 3) or not 1 <= int(num) <= N_DAYS:
            why = f"; {why}" if why else ""
            if i == 0:                                 # line 1 may be the header: say that it is not one either
                raise ValueError(f"{path}:1: line 1 is neither the header (day<TAB>fill%<TAB>jev-err%<TAB>reason) "
                                 f"nor a day line: day {tok!r} is not d01..d{N_DAYS:02d}{why} (the line: {line!r})")
            raise ValueError(f"{path}:{i + 1}: day {tok!r} is not d01..d{N_DAYS:02d}{why} (the line: {line!r})")
        days.add(int(num))
        lines.append(line)
    return days, lines


HEADER = ["day", "fill%", "jev-err%", "reason"]


def _is_header(line):
    """Line 1 is the header when its first word is 'day' (any case) and it holds no digit at all: a day
    line always has a digit in its day, so no day is skipped this way, while the header typed with
    single spaces or its columns reworded ('day fill% jev-err% reason', 'day<TAB>fill<TAB>...') is
    still a header, as it was before 52fe1a6. A first line that merely starts with 'day' and holds a
    digit ('day06 ...', 'day 16  80.0 ...', a typo) is a data line, and refused, not silently dropped."""
    words = line.split()
    return bool(words) and words[0].lower() == "day" and not any(c.isdigit() for c in line)


def _day_field(line):
    """(the day field, why the line was taken whole or ''), by the file's own separator: before the
    first tab when the line has one; else before the first run of two or more spaces (as PREREG §8.3
    prints the line). A line of single spaces is ambiguous ('d1 6 80.0 0.0' is d1 or a typo for d16)
    and is returned whole, so the caller refuses it. So is a tab line that is not the header's four
    fields (tabs after a reason are ignored; the reason may be empty), or whose fill% or jev-err% is
    not a number (n/a, as the report prints an undefined share, and 0/0 count), or whose reason begins
    with one that is not run into a letter (_leads_with_value): a tab typed inside the day
    ('d1<TAB>6<TAB>80.0<TAB>0.0 ...') shifts every column right, so it makes five fields, or, with the
    reason left out or typed after a space, or after punctuation with or without a space ('0.0',
    '0.3%. Mac', '0.0.', '0.3%, Mac', '0.0-Mac', '0.3%/Mac', '0.0,Mac', '0.0—Mac'), four whose last
    begins with the jev-err%. A reason that itself begins with a number standing apart ('3 h asleep',
    '401 from Jev', '3-hour outage', '1:30 feed down', '24/7') is refused too and can be reworded; one
    whose number runs into a letter ('3h asleep', '1.5h', '2nd night') is taken. Three typos cannot be
    caught: in the two-space form 'd1  6  80.0 ...' (meant d16) reads as d01, because a reason may
    itself hold two spaces; a tab typed inside the day of a line that also leaves out its fill% or
    jev-err% ('d1<TAB>6<TAB>80.0<TAB>asleep') is a well-formed d01 line; and so is one whose jev-err%
    has no % and runs into the reason with nothing between, so that a number meets a letter
    ('d1<TAB>6<TAB>80.0<TAB>0.0Mac asleep'), as in the reason '3h asleep'. make status prints the
    parsed days every morning, and the day-28 output recomputes stop rule 3 beside them, so such a
    line shows as a listed day the rule judged fine."""
    if "\t" in line:
        fields = line.split("\t")
        if len(fields) > len(HEADER) and fields[3].strip() and not "".join(fields[4:]).strip():
            fields = fields[:4]                        # tabs typed after the reason
        if len(fields) != len(HEADER):
            return line.strip(), TAB_FORM
        if not (_value(fields[1]) and _value(fields[2])) or _leads_with_value(fields[3]):
            return line.strip(), TAB_FORM
        return fields[0].strip(), ""
    parts = re.split(r" {2,}", line.strip(), maxsplit=1)
    return (parts[0], "") if len(parts) == 2 else (line.strip(), "")


TAB_FORM = ("a tab line is day<TAB>fill%<TAB>jev-err%<TAB>reason, fill% and jev-err% each a number or n/a,"
            " the reason not beginning with one")
_VALUE = re.compile(r"(?:\d+(?:[.,]\d*)?|[.,]\d+)[ \u00a0\u202f]?%?|\d+/\d+|n/a", re.ASCII | re.IGNORECASE)


def _value(s):
    """A fill% or jev-err% as the report prints one ('94.2%', '94.2', 'n/a'; '0/0' as its NO LIVE ROWS
    line puts a day's fill), or typed with a comma for the point, one space before the % (a plain
    space, or a no-break U+00A0 or narrow no-break U+202F, which an editor or a keyboard layout may
    put there and which look the same on screen; any other character there, a thin space or a second
    space, is refused), or a trailing ',', ';' or ':'."""
    return bool(_VALUE.fullmatch(s.strip().rstrip(",;:")))


_LEAD = re.compile(r"[0-9]+(?:[.,][0-9]+)*|[.,][0-9]+|n/a", re.ASCII | re.IGNORECASE)


def _leads_with_value(reason):
    """Whether the reason, stripped, begins with a number (ASCII digits with any '.' or ',' points
    between them, '0.3', '94,2', '1.5.2', or one point before them, '.5') or with 'n/a' in any case,
    and the character after it is not one str.isalnum takes (a letter, or a digit or numeral of any
    script): the end, a space of any kind, '%', '.', ',', ';', ':', '-', '/', '—', '(' and so on.
    So a jev-err% run into the reason by a typo is caught ('0.0', '0.3%. Mac', '0.0-Mac'), and so is
    '401 from Jev'; '3h asleep', '1.5h' and 'n/about' are words and are not. The number is read
    whole before the next character is looked at, so '1.5h' is not '1' followed by '.'."""
    r = reason.strip()
    m = _LEAD.match(r)
    return bool(m) and not r[m.end():m.end() + 1].isalnum()


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

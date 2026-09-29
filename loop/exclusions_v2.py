"""loop/exclusions_v2.py -- data/exclusions-v2.tsv, PREREG-v2 §9.3's log of excluded product-days, and the
recomputed rule beside it.

v1's reader (loop/exclusions.py, data/exclusions.tsv, days only) stays as it is: v1's result is reproduced from
`results-v1` with it. In v2 THE RULE RECOMPUTED FROM THE LOG GOVERNS (§9.3): a product's T0_v2-anchored day is
excluded when report.days_table judges it BAD (fill < 95 % or jev errors > 5 %) or when it is a closed sample day
with no live row (Alex, 2026-09-29: such a day is excluded whole). The file is Alex's log of what he saw, written
the morning after; the readers print it verbatim beside the recomputed set and name every disagreement, and a
listed day the rule judges fine is not excluded. `make status` shows the parse each morning, so a line this
refuses is seen the day it is written, not on day 28.

The file: tab-separated, header `day<TAB>product<TAB>fill%<TAB>jev-err%<TAB>reason`, one line per product-day,
the day as dNN or NN (1..28). Only tabs separate fields (v1 also took two spaces, as PREREG v1 printed its
header; v2's header is written with tabs); a line whose product is missing or not in config.PRODUCTS is refused,
and so is anything v1's parser refuses in the fill%, jev-err% and reason fields. Standard library only; no
measurement here, and nothing is written.
"""
import os

from . import config, exclusions

N_DAYS = exclusions.N_DAYS                      # 28
HEADER = ("day", "product", "fill%", "jev-err%", "reason")
FORM = ("a line is day<TAB>product<TAB>fill%<TAB>jev-err%<TAB>reason (tabs only), the day d01..d28, the product one of"
        " config.PRODUCTS, fill% and jev-err% each a number or n/a, the reason not beginning with one")


def _is_header(line):
    """Line 1 is a header when its first word is 'day' (any case) and it holds no digit (v1's test: a day line
    always has a digit). It must then be v2's: its second word is 'product'."""
    words = line.split()
    return bool(words) and words[0].lower() == "day" and not any(c.isdigit() for c in line)


def read(path=None):
    """(set of (N, product), the lines verbatim) from data/exclusions-v2.tsv (config.EXCLUSIONS_V2 when `path`
    is None, read now so a test's DATA applies). A missing file is no exclusion. Any line it cannot read as one
    product-day is a ValueError naming the file, the line number and the line: the file is reproduced in the
    write-up, so it is fixed, never skipped."""
    path = config.EXCLUSIONS_V2 if path is None else path
    out, lines = set(), []
    if not os.path.exists(path):
        return out, lines
    try:
        with open(path, encoding="utf-8") as fh:
            raws = fh.read().split("\n")
    except UnicodeDecodeError as e:
        raise ValueError(f"{path}: not UTF-8 ({e.reason} at byte {e.start})") from None
    for i, line in enumerate(raws):
        if not line.strip():
            continue
        if i == 0 and _is_header(line):
            words = line.split()
            if len(words) < 2 or words[1].lower() != "product":
                raise ValueError(f"{path}:1: the header is not v2's ({'<TAB>'.join(HEADER)}): {line!r}"
                                 " (v1's file, data/exclusions.tsv, has no product column)")
            continue
        out.add(_parse(path, i + 1, line))
        lines.append(line)
    return out, lines


def _parse(path, n, line):
    where = f"{path}:{n}"
    if "\t" not in line:
        raise ValueError(f"{where}: no tab: {FORM} (the line: {line!r})")
    fields = line.split("\t")
    if len(fields) > len(HEADER) and fields[4].strip() and not "".join(fields[5:]).strip():
        fields = fields[:5]                         # tabs typed after the reason
    if len(fields) != len(HEADER):
        raise ValueError(f"{where}: {len(fields)} fields, not {len(HEADER)}: {FORM} (the line: {line!r})")
    tok, product = fields[0].strip(), fields[1].strip()
    num = tok[1:] if tok[:1] in "dD" else tok
    if not (num.isascii() and num.isdigit() and len(num) <= 3) or not 1 <= int(num) <= N_DAYS:
        raise ValueError(f"{where}: day {tok!r} is not d01..d{N_DAYS:02d} (the line: {line!r})")
    if not product:
        raise ValueError(f"{where}: the product is missing: {FORM} (the line: {line!r})")
    if product not in config.PRODUCTS:
        raise ValueError(f"{where}: product {product!r} is not in config.PRODUCTS {tuple(config.PRODUCTS)} (the line: {line!r})")
    if not (exclusions._value(fields[2]) and exclusions._value(fields[3])) or exclusions._leads_with_value(fields[4]):
        raise ValueError(f"{where}: {FORM} (the line: {line!r})")
    return int(num), product


def recompute(days_by_product):
    """PREREG-v2 §9.3's rule from the log: {(N, product)} for every sample day d01..d28 that report.days_table
    (run per product on its own rows, T0_v2-anchored) marks BAD or NO LIVE ROWS (`empty`). An open day, and one
    --since cuts into, is not judged, and so not excluded. `days_by_product`: {product: days_table(...)["days"]}."""
    out = set()
    for p, days in days_by_product.items():
        for x in days:
            d = x["day"]
            if (x["bad"] or x["empty"]) and d[:1] == "d" and d[1:].isdigit() and 1 <= int(d[1:]) <= N_DAYS:
                out.add((int(d[1:]), p))
    return out


def _names(pairs):
    return ", ".join(f"d{n:02d} {p}" for n, p in sorted(pairs, key=lambda x: (x[1], x[0]))) or "none"


def disagreements(listed, recomputed):
    """(listed but not recomputed: NOT excluded, the rule governs; recomputed but not listed: excluded anyway)."""
    return sorted(listed - recomputed), sorted(recomputed - listed)


def lines(listed, recomputed, verbatim, path):
    """The readers' lines: the recomputed set (which governs), the file's parse, every disagreement named."""
    extra, missing = disagreements(listed, recomputed)
    out = [f"  stop rule 3 (PREREG-v2 §9.3), recomputed from the log, which governs: {len(recomputed)} product-day(s) excluded:"
           f" {_names(recomputed)}",
           f"  {path}: {len(listed)} product-day(s) listed: {_names(listed)}"]
    out.extend(f"    | {l}" for l in verbatim)
    if extra:
        out.append(f"  DISAGREE: listed, but the rule does not exclude them (fine or not yet closed), so NOT excluded: {_names(extra)}")
    if missing:
        out.append(f"  DISAGREE: the rule excludes them and the file does not list them (excluded anyway): {_names(missing)}")
    if not extra and not missing:
        out.append("  the file and the rule agree")
    return out


def status_line(path=None):
    """One line for `make status`: the product-days the file lists, or why it cannot be read."""
    path = config.EXCLUSIONS_V2 if path is None else path
    try:
        listed, _ = read(path)
    except ValueError as e:
        return f"exclusions-v2: REFUSED, fix before day 28: {e}"
    except OSError as e:
        return f"exclusions-v2: {path} cannot be read: {e.strerror or e}"
    if not listed:
        return f"exclusions-v2: none ({path} {'absent' if not os.path.exists(path) else 'has no product-day line'})"
    return f"exclusions-v2: {len(listed)} product-day(s) listed: {_names(listed)} ({path})"

"""SPEC.md v2 (PREREG-v2 §10's SPEC bullet) held to the code it describes: the header's promise that every v2 row
carries its sha and that it names PREREG-v2 §12 for T0_v2 and the fee tiers without restating them; §2's row schema
against the row cycle.new_row writes; §5's per-product liq table against config.PRODUCTS, TICK_P, LIQ_ATOMS and
LIQ_THIN_FALLBACK; §10's fee columns and the filled verified tier-0 taker row against config; §14 against the modules
it names, each value cell against the code's value (value_problem reads the forms §14 writes), and every constant of
loop/config.py (but its paths, URL and key names) named there. tests/test_frozen.py pins SPEC.md's bytes and each §14
constant's value; this file says the text and the code agree. Read, never written."""
import ast, importlib, importlib.machinery, importlib.util, os, re, sys, types, unittest
from fractions import Fraction

from loop import config, cycle

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# loop/config.py's names SPEC §14 need not list: paths, the URL and the key names (SPEC §2, §12 and §13 name them
# where they act), the per-product store's namedtuple and the v2 globals' file names (config.EXCLUSIONS_V2, LOOKS)
CONFIG_NOT_IN_14 = {"REPO", "DATA", "DECISIONS", "SENDS", "HALT", "LOCK", "HEARTBEAT", "PROMPTS", "PROPOSALS", "SPEC",
                    "PROTOCOL", "FORBIDDEN_PREFIXES", "JEV_URL", "KEY_PATHS", "Store"}
# §14 names these in parentheses, beside the constant they explain, and gives their value elsewhere (Constants holds it)
NOT_VALUED_IN_14 = {("loop.config", "FEE_BPS_VENUE_SOURCE"): "§10 quotes it whole"}
NAME = re.compile(r"`([A-Z][A-Z0-9_]*)`")
WHERE = re.compile(r"`((?:loop|nightly)/[a-z_0-9]+)\.py`|`(bin/[a-z0-9-]+)`")   # a module, or a script under bin/
# The modules whose every capitalised constant §14 names (loop/config.py has its own test, below), but these, each with
# the reason §14 leaves it out (the S6 refuter's defect 3: report.ERRATA_TIER hard-coded a fee §14 did not name, and
# ten other v2 constants were in no row, so nothing pinned them by value)
IN_14 = ("loop.book", "loop.cycle", "loop.prompts", "loop.report", "loop.inference_v2", "loop.exclusions_v2",
         "nightly.digest", "nightly.policy_table", "nightly.slow_model", "bin/promote")
_EXIT, _WORDS = "an exit code", "printed words"
_DIGEST = "the digest's layout: nightly/digest.py's source is pinned by sha (tests/test_frozen.py FILES)"
_TABLE = "nightly/policy_table.py's source is pinned by sha (tests/test_frozen.py FILES)"
NOT_IN_14 = {
    "loop.book": {"INTENTS": "the three intents, §10's buy / sell / hold", "NOTIONAL": "config.NOTIONAL_USD under a short name"},
    "loop.cycle": {"EXIT_GUARD": _EXIT, "EXIT_USAGE": _EXIT, "HALT_KEY_REJECTED": "HALT's reason, " + _WORDS,
                   "HALT_SPEND": "HALT's reason, " + _WORDS},
    "loop.prompts": {"WIRE": "a prompt file's fields (§8)", "CRITERIA": "a prompt file's answer sets (§8)",
                     "CARRIED": "the questions every version carries from v1 (§8)"},
    "loop.report": {"ARMS": "book.ARMS, the per-arm lines", "CHOICES": "rules.CHOICES", "CAL_EDGES": "CONF_THRESHOLDS and 1.0",
                    "CORRECT": "§11's labels against the choices, a withheld section's rule", "TREND_SIGN": "the trend word as a sign, a withheld section's comparator",
                    "TICKS_PER_DAY": "86400 // CADENCE_S", "DAY_TICKS": "86400 // CADENCE_S", "TITLES": "section titles",
                    "TITLES_V2": "section titles"},
    "loop.inference_v2": {"CELLS": "built from SEED_H1, ALPHA_H1, ALPHA_F and CADENCES; tests/test_frozen.py's CELLS_V2 pins each",
                          "EXIT_REFUSED": _EXIT, "UTC": "the time zone"},
    "loop.exclusions_v2": {"HEADER": "the file's columns (CONTRACT §2)", "FORM": "the line's form, printed on a refusal"},
    "nightly.digest": {"ARMS": _DIGEST, "COLUMN": _DIGEST, "CONTRADICTS": _DIGEST, "LABELS": _DIGEST, "EXIT_EMPTY": _EXIT},
    "nightly.policy_table": {"CURRENT": "the column name CURRENT's answers take; " + _TABLE, "KIND": "the .table.json's kind; " + _TABLE,
                             "TABLE_SHA_LINE": "the .md line that carries the table's sha; " + _TABLE, "EXIT_INCOMPLETE": _EXIT,
                             "FATAL_KINDS": "cycle.UNSENT_KINDS and http-429; " + _TABLE, "TRANSIENT_KINDS": "the retried kinds; " + _TABLE,
                             "HALT_STATUS": "401 and 403, cycle's HALT rule; " + _TABLE},
    "nightly.slow_model": {"ID_FORM": "answered_model.MODEL_ID's pattern; tests/test_slow_model.py holds it"},
    "bin/promote": {"HERE": "a path", "REPO": "a path"},
}
_SCRIPTS = {}


def load(module):
    """The module a §14 `where` names: loop.x / nightly.x imported, bin/<script> loaded from its file once (sys.path as it
    was: bin/promote puts the repo on it)."""
    if not module.startswith("bin/"):
        return importlib.import_module(module)
    if module not in _SCRIPTS:
        path = os.path.join(REPO, *module.split("/"))
        name = "spec14_" + re.sub(r"\W", "_", module)
        spec = importlib.util.spec_from_file_location(name, path, loader=importlib.machinery.SourceFileLoader(name, path))
        mod = importlib.util.module_from_spec(spec)
        saved = list(sys.path)
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.path[:] = saved
        _SCRIPTS[module] = mod
    return _SCRIPTS[module]


def constants(module):
    """The capitalised, non-callable, non-module names a module holds."""
    return {n for n, v in vars(load(module)).items()
            if re.fullmatch(r"[A-Z][A-Z0-9_]*", n) and not callable(v) and not isinstance(v, types.ModuleType)}


def spec_text(path=None):
    with open(path or os.path.join(REPO, "SPEC.md"), encoding="utf-8") as fh:
        return fh.read()


def section(text, n):
    """SPEC's `## n.` section, heading to the next `## ` heading (the header before §1 for n = 0)."""
    if n == 0:
        return text.split("\n## 1.", 1)[0]
    part = text.split(f"\n## {n}. ", 1)[1]
    return part.split("\n## ", 1)[0]


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def spec14(text=None):
    """{(module, name)} of §14's table: a row's `where` cell names the file (blank: the row above's), and every
    backticked CAPITALISED identifier of its name cell is a constant of that module."""
    out, where = set(), None
    for line in section(text or spec_text(), 14).splitlines():
        if not line.startswith("| ") or line.startswith("| where |"):
            continue
        c = cells(line)
        m = WHERE.search(c[0])
        if m:
            where = m.group(1).replace("/", ".") if m.group(1) else m.group(2)
        elif c[0]:
            raise ValueError(f"SPEC §14: a where cell that names no module: {c[0]!r}")
        out |= {(where, n) for n in NAME.findall(c[1])}
    return out


def top_split(cell, sep=" / "):
    """`cell` split at `sep` where it stands outside parentheses and backticks (a value like `CADENCE_S / 2` or
    (`sorted[249]` / `sorted[62]`) stays whole)."""
    parts, cur, depth, tick, i = [], "", 0, False, 0
    while i < len(cell):
        ch = cell[i]
        if not tick and depth == 0 and cell.startswith(sep, i):
            parts.append(cur)
            cur, i = "", i + len(sep)
            continue
        if ch == "`":
            tick = not tick
        elif not tick and ch in "([":
            depth += 1
        elif not tick and ch in ")]":
            depth -= 1
        cur += ch
        i += 1
    return [p.strip() for p in parts + [cur]]


def _outside_parens(text):
    out, depth = "", 0
    for ch in text:
        depth += ch == "("
        if depth == 0:
            out += ch
        depth -= ch == ")" and depth > 0
    return out


def spec14_values(text=None):
    """{(module, name): the text of its value cell} for §14's table: the name cell and the value cell split at " / "
    alike, each part of the name cell naming its constant by the first backticked name outside its parentheses. A name
    only inside parentheses (`FEE_BPS_VENUE_SOURCE`) is named, not valued: it is absent here (NOT_VALUED_IN_14 says
    where its value is). A row whose two cells split differently raises."""
    out, where = {}, None
    for line in section(text or spec_text(), 14).splitlines():
        if not line.startswith("| ") or line.startswith("| where |"):
            continue
        c = cells(line)
        m = WHERE.search(c[0])
        if m:
            where = m.group(1).replace("/", ".") if m.group(1) else m.group(2)
        names, values = top_split(c[1]), top_split(c[2])
        if len(names) != len(values):
            raise ValueError(f"SPEC §14: {len(names)} names and {len(values)} values in {line!r}")
        for n, v in zip(names, values):
            named = NAME.findall(_outside_parens(n))
            if named:
                out[(where, named[0])] = v
    return out


NOTHING = object()
NUMBER = re.compile(r"(\d+)\^(\d+)|(\d[\d,]*(?:\.\d+)?(?:e[-+]?\d+)?)(\s*MiB)?")
ARM = re.compile(r"([A-D])\s*[−-]\s*([A-D])")


def _number(text):
    """(the value, whether it was written as an integer) of the number `text` starts with, or None."""
    m = NUMBER.match(text)
    if m is None:
        return None
    if m.group(1):
        return int(m.group(1)) ** int(m.group(2)), True
    lit = m.group(3).replace(",", "")
    if "." in lit or "e" in lit:
        return float(lit), False
    return int(lit) << (20 if m.group(4) else 0), True


def _element(text, module):
    """One element of a tuple as §14 writes it: `NAME` (another constant, with an optional "= literal" that must agree),
    a backticked or quoted string, B (an arm), or a number. Returns (value, how to compare: "exact" or "number")."""
    text = text.strip()
    ref = re.fullmatch(r"`([A-Z][A-Z0-9_]*)`(?:\s*=\s*(.+))?", text)
    if ref:
        for mod in (module, "loop.config"):
            if hasattr(load(mod), ref.group(1)):
                got = getattr(load(mod), ref.group(1))
                if ref.group(2) is not None:
                    lit = _number(ref.group(2))
                    if lit is None or lit[0] != got:
                        raise ValueError(f"{text!r}: {ref.group(1)} is {got!r}")
                return got, "exact"
    if re.fullmatch(r"`[^`]*`", text) or re.fullmatch(r'"[^"]*"', text):
        return text[1:-1], "exact"
    if re.fullmatch(r"[A-D]", text):
        return text.lower(), "exact"
    n = _number(text)
    if n is not None and NUMBER.match(text).end() == len(text):
        return n[0], ("int" if n[1] else "float")
    return text, "exact"


def _same(value, want, how):
    if how == "int":
        return type(value) is int and value == want
    if how == "float":
        return type(value) is float and value == want
    return value == want


def _paren_groups(text):
    """The top-level parenthesised groups `text` starts with, e.g. "(a, b), (c, d) rest" -> ["a, b", "c, d"]."""
    groups, depth, cur = [], 0, ""
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
            if depth == 1:
                cur = ""
                continue
        elif ch == ")":
            depth -= 1
            if depth == 0:
                groups.append(cur)
                if not text[i + 1:].startswith(", ("):
                    return groups
                continue
        if depth >= 1:
            cur += ch
    return groups


def value_problem(module, name, text, value):
    """Why §14's value cell `text` does not say `value`, the code's value of module.name (None when it does). The forms
    §14 writes: a number (10,000; 2^40; 8 MiB; 1e-9; an integer written without a point, a float with one), 1/40 (an
    exact fraction), `NAME` (another constant) with an optional "= literal", a backticked or bare word, words or
    backticked words for a tuple of strings ("a b c d", "`x`, `y`: ..."), "B−C, A−C" for arm pairs, "(x, y)" for a
    tuple, "per product, §5's table (`P` v)" for a per-product dict, "0.25 × the number of products", and
    `("P",)` and PREREG-v2 §2's two probe products. Prose after the value (in parentheses or after a colon) is not read."""
    text = text.strip()
    say = lambda: f"{module}.{name}: SPEC §14 says {text!r}, the code holds {value!r}"
    try:
        lit = re.match(r"`([({\[][^`]*)`", text)
        try:
            lit = ast.literal_eval(lit.group(1)) if lit else NOTHING
        except (ValueError, SyntaxError):                                # `{BASE}` is a word, not a literal
            lit = NOTHING
        if lit is not NOTHING:                                           # a Python literal
            probe = re.match(r"`[^`]*` and PREREG-v2 §2's two probe products\b", text)
            if lit == value and repr(lit) == repr(value):
                return None
            if (probe and isinstance(value, tuple) and value[:len(lit)] == lit and len(value) == len(lit) + 2
                    and set(value[len(lit):]) <= set(config.PROBE_CANDIDATES)):
                return None
            return say()
        m = re.match(r"PREREG-v2 §8's (id|night)\b", text)
        if m:                                                            # blank underscores there are "" in the code
            from test_slow_model import id_and_night
            found = id_and_night()
            want = found[0][m.group(1) == "night"] if len(found) == 1 else None
            return None if want is not None and value == ("" if re.fullmatch(r"_*", want) else want) else say()
        if isinstance(value, dict):
            if "§5's table" not in text:
                return say() + " (a per-product value names §5's table)"
            pairs = re.findall(r"`([A-Z0-9]+-[A-Z]+)` (\([^()]*\)|[^()\s]+)", text)
            if not pairs:
                return say() + " (no product's value given)"
            for p, v in pairs:
                got = value.get(p)
                if v in ("yes", "no"):
                    ok = got is (v == "yes")
                elif v.startswith("("):
                    ok = got is not None and tuple(_element(e, module)[0] for e in v[1:-1].split(",")) == tuple(got)
                else:
                    ok = got is not None and _same(got, *_element(v, module))
                if not ok:
                    return say()
            return None
        m = re.match(r"([\d.]+) × the number of products\b", text)
        if m:
            return None if value == float(m.group(1)) * len(config.PRODUCTS) else say()
        if isinstance(value, Fraction):
            m = re.match(r"(\d+)/(\d+)\b", text)
            return None if m and Fraction(int(m.group(1)), int(m.group(2))) == value else say()
        if isinstance(value, tuple):
            ref = re.match(r"`[A-Z][A-Z0-9_]*`", text)
            if ref:                                                      # another constant's value
                return None if _same(value, *_element(ref.group(0), module)) else say()
            if value and all(isinstance(v, tuple) and len(v) == 2 and all(isinstance(x, str) for x in v) for v in value):
                return None if [(x.lower(), y.lower()) for x, y in ARM.findall(text)] == list(value) else say()
            if text.startswith("("):
                groups = _paren_groups(text)
                if value and all(isinstance(v, tuple) for v in value):
                    elems = [[_element(e, module) for e in top_split(g, ", ")] for g in groups]
                    ok = len(elems) == len(value) and all(
                        len(e) == len(v) and all(_same(x, *y) for x, y in zip(v, e)) for e, v in zip(elems, value))
                else:
                    elems = [_element(e, module) for e in top_split(groups[0], ", ")] if groups else []
                    ok = len(elems) == len(value) and all(_same(x, *y) for x, y in zip(value, elems))
                return None if ok else say()
            if value and all(isinstance(v, str) for v in value):
                lead = re.split(r"\s\(|:", text, maxsplit=1)[0]
                words = [w.strip("`") for w in re.split(r"[,\s]+", lead) if w]
                return None if words == list(value) else say()
            got = _element(text, module)
            return None if _same(value, *got) else say()
        if re.match(r"\d", text):                                        # 10,000; 2^40; 8 MiB; 1e-9
            n = _number(text)
            return None if _same(value, n[0], "int" if n[1] else "float") else say()
        m = re.match(r"(`[^`]*`(?:\s*=\s*[\d.]+)?|\"[^\"]*\"|[^\s:,(]+)", text)
        if m is None:
            return say()
        got = _element(m.group(1), module)
        if isinstance(value, str) and got[1] != "exact":
            return say()
        return None if _same(value, *got) else say()
    except (ValueError, SyntaxError) as e:
        return say() + f" ({e})"


def section14_disagreements(text=None):
    """Every §14 constant whose value cell does not say the code's value, one line each (empty when §14 and the code
    agree)."""
    out = []
    for (module, name), cell in sorted(spec14_values(text).items()):
        problem = value_problem(module, name, cell, getattr(load(module), name))
        if problem:
            out.append(problem)
    return out


def liq_table(text=None):
    """{product: (TICK_P, (a10, a90), thin fallback)} from §5's per-product table."""
    out = {}
    for line in section(text or spec_text(), 5).splitlines():
        c = cells(line) if line.startswith("| `") else None
        if not c or not re.fullmatch(r"`[A-Z0-9]+-[A-Z]+`", c[0]):
            continue
        atoms = re.fullmatch(r"\((\d+), (\d+)\)", c[2])
        out[c[0].strip("`")] = (float(c[1]), (int(atoms.group(1)), int(atoms.group(2))), {"yes": True, "no": False}[c[3]])
    return out


class Header(unittest.TestCase):
    def test_every_v2_row_carries_this_files_sha_and_section_12_is_named_not_restated(self):
        text = spec_text()
        head = " ".join(section(text, 0).split())
        self.assertIn("Every v2 row carries this file's sha256 as its `spec_sha`", head)
        self.assertIn("SPEC v2", head)
        self.assertIn("are PREREG-v2 §12's fields", head)
        self.assertTrue(text.rstrip().endswith("sha256 of this file is written into every v2 row as spec_sha; changing"
                                               " this file starts a new experiment."))
        self.assertNotIn("________", text)                                   # v1's blank verified-fee row is filled
        self.assertIsNone(re.search(r"\b20\d{6}T\d{4}00Z\b", text))          # no T0_v2 (a minute tick_id) restated
        self.assertNotIn("Fee tiers (30-day band", text)                     # nor §12's fee-tier field

    def test_what_this_tree_prints_over_the_v1_log_is_said(self):
        # the S6 refuter's defect 6: the header said nothing here changes "how v1's readers read the v1 log", but since
        # config took PREREG-v2 §6's fee columns loop.report prints (0, 2, 10, 25, 50, 90) and a venue fee of 90 over the
        # v1 log, where v1's printed (0, 2, 10, 25, 60, 120) and 120; v1's result and cells come from results-v1 (§10)
        from loop import report
        head = " ".join(section(spec_text(), 0).split())
        self.assertNotIn("how v1's readers read the v1 log", head)
        self.assertIn("reproduced from the tag `results-v1`", head)
        self.assertIn("prints §10's fee columns (" + ", ".join(f"{f:g}" for f in report._fee_list()) + ")", head)
        self.assertIn(f"the verified venue fee {report.VENUE_FEE:g} over the v1 log", head)
        self.assertIn("where v1's reader printed (0, 2, 10, 25, 60, 120) and 120", head)
        with open(os.path.join(REPO, "CONTRACT.md"), encoding="utf-8") as fh:
            contract = " ".join(fh.read().split())
        self.assertNotIn("readers still read the v1 log as before", contract)          # the same claim, CONTRACT §0
        self.assertIn("the report's fee columns over it are v2's; SPEC's header", contract)

    def test_the_verified_tier_0_taker_row_is_filled_with_the_venue_fee(self):
        text = section(spec_text(), 10)
        row = re.search(r"^Verified tier-0 taker fee: (\S+) bps\s+URL: (\S+)\s+read \(UTC\): (\S+)", text, re.M)
        self.assertIsNotNone(row)
        self.assertEqual(float(row.group(1)), config.FEE_BPS_VENUE)
        self.assertEqual(row.group(2), "https://www.coinbase.com/advanced-fees")
        self.assertEqual(row.group(3), "2026-09-27")
        self.assertIn(f"`FEE_BPS_COLUMNS = {config.FEE_BPS_COLUMNS}`", text)
        self.assertIn(f"`FEE_BPS_VENUE = {config.FEE_BPS_VENUE}`", text)


class Row(unittest.TestCase):
    def test_section_2_names_every_key_the_writer_writes(self):
        block = section(spec_text(), 2).split("```", 2)[1]
        row = cycle.new_row("2026-10-24T00:00:00.000Z", "live")
        for key in row:
            self.assertIn(f'"{key}"', block, key)
        for arm in row["columns"]:
            self.assertRegex(block, rf'"columns": \{{.*"{arm}":', arm)
        for key in row["jev"]:
            self.assertIn(f'"{key}"', block, key)
        self.assertEqual(sorted(row["columns"]), ["a", "b", "d"])
        self.assertIn(f'"prompt_a": "{config.FROZEN_A}"', block)
        self.assertIn(f'"v": {cycle.ROW_V},', block)


class Wording(unittest.TestCase):
    """Two slips the S6 refuter found: §5 counted the state string's words after the colon as ten (v1's text; there
    are eight), and §2 named the columns step by CONTRACT §3's number (7) where §13, SPEC's own list, numbers it 6."""

    def test_section_5_counts_the_state_strings_words(self):
        from loop import state
        said = re.search(r"\b(\w+) words after the colon\b", section(spec_text(), 5))
        self.assertIsNotNone(said)
        numbers = {"six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
        for a in state.all_states():
            self.assertEqual(len(state.state_string(a).split(":", 1)[1].split()), numbers[said.group(1).lower()])

    def test_section_2_names_the_columns_step_by_section_13s_number(self):
        said = re.search(r"did not reach §13's step (\d+), the columns", " ".join(section(spec_text(), 2).split()))
        self.assertIsNotNone(said)
        step = re.search(rf"^{said.group(1)}\. (\w+)", section(spec_text(), 13), re.M)
        self.assertEqual(step.group(1), "Columns")


class LiqTable(unittest.TestCase):
    def test_section_5_gives_every_product_its_tick_and_atoms_as_config_holds_them(self):
        # PREREG-v2 §3: TICK_p per product in config.py, the atoms from the product's window; the commit that adds the
        # probe products adds their rows here (STEPS §10.1), so this fails until SPEC says what config does
        want = {p: (config.TICK_P[p], config.LIQ_ATOMS[p], config.LIQ_THIN_FALLBACK[p]) for p in config.PRODUCTS}
        self.assertEqual(liq_table(), want)
        for p, (_, (a10, a90), fallback) in want.items():
            deep, thin = config.liq_cuts(p)
            line = next(l for l in section(spec_text(), 5).splitlines() if l.startswith(f"| `{p}` |"))
            self.assertIn(f"h < {deep:g}", line)
            self.assertIn(f"h > {thin:g}", line)

    def test_the_parser_reads_a_second_product(self):
        text = spec_text().replace("\n| `SOL-USD` | 0.01 |", "\n| `ETH-USD` | 0.01 | (2, 7) | yes | h < 2.5 | h > 6.5 | x |\n"
                                   "| `SOL-USD` | 0.01 |", 1)
        self.assertEqual(liq_table(text)["ETH-USD"], (0.01, (2, 7), True))


class Constants(unittest.TestCase):
    def test_every_name_in_section_14_is_a_constant_of_the_module_it_names(self):
        named = spec14()
        self.assertGreater(len(named), 60)
        for module, name in sorted(named):
            with self.subTest(module=module, name=name):
                self.assertTrue(hasattr(load(module), name))

    def test_every_constant_of_config_is_in_section_14(self):
        named = {n for m, n in spec14() if m == "loop.config"}
        mine = {n for n, v in vars(config).items() if re.fullmatch(r"[A-Z][A-Z0-9_]*", n) and not callable(v)}
        self.assertEqual(sorted(mine - named - CONFIG_NOT_IN_14), [])
        self.assertLessEqual(CONFIG_NOT_IN_14 - {"Store"}, mine)             # the exemptions are real names

    def test_every_constant_of_the_v2_modules_is_in_section_14(self):
        # SPEC §14 says "every constant, in one place", and §10 that "nothing hard-codes a fee but the constants named in
        # §14"; report.ERRATA_TIER (maker 50, taker 90) was in no row (the S6 refuter's defect 3)
        named = spec14()
        for module in IN_14:
            with self.subTest(module=module):
                mine, left = constants(module), set(NOT_IN_14.get(module, {}))
                here = {n for m, n in named if m == module}
                self.assertEqual(sorted(mine - here - left), [])
                self.assertLessEqual(left, mine)                                 # the exemptions are real names
                self.assertEqual(left & here, set())                             # and not also in §14
        self.assertLessEqual(set(NOT_IN_14), set(IN_14))
        self.assertIn(("loop.report", "ERRATA_TIER"), named)
        self.assertIn(("bin/promote", "E_MIN"), named)

    def test_every_value_in_section_14_is_the_codes(self):
        # the S6 refuter's defect 2: this class held only that each §14 name exists and test_frozen's SPEC14 pins the
        # code's values, so §14 could state an H1 seed or D readings the code does not use and the suite stayed green
        self.assertEqual(section14_disagreements(), [])
        self.assertGreater(len(spec14_values()), 60)
        self.assertEqual(set(spec14()) - set(spec14_values()), set(NOT_VALUED_IN_14))
        quoted = " ".join(section(spec_text(), 10).split())
        self.assertIn(" ".join(f'`FEE_BPS_VENUE_SOURCE = "{config.FEE_BPS_VENUE_SOURCE}"`'.split()), quoted)

    def test_a_value_section_14_misstates_is_named(self):
        # the refuter's reproduction: D's readings as 0.98 / 0.90 / 12, the MAX_*_RUN row as 5 / 5 / 5 and SEED_H1 as
        # 20261099 passed test_frozen, test_spec, test_contract, test_errata and test_config
        text = spec_text()
        for old, new in (("| 0.99 / 0.95 / 10 (PREREG-v2 §6's D readings) |", "| 0.98 / 0.90 / 12 (PREREG-v2 §6's D readings) |"),
                         ("`MAX_ERROR_RUN` | 3 / 3 / 3 |", "`MAX_ERROR_RUN` | 5 / 5 / 5 |"),
                         ("| 20261023 (family F: + i)", "| 20261099 (family F: + i)")):
            self.assertIn(old, text)
            text = text.replace(old, new, 1)
        self.assertEqual([d.split(":", 1)[0] for d in section14_disagreements(text)],
                         ["loop.inference_v2.SEED_H1", "loop.report.DRIFT_BELOW", "loop.report.LOOKUP_AT",
                          "loop.report.MODAL_MIN", "nightly.policy_table.MAX_ERROR_RUN", "nightly.policy_table.MAX_OTHER_RUN",
                          "nightly.policy_table.MAX_TRANSIENT_RUN"])
        for old, new in (("| 90.0 (v1: 120.0, unverified) |", "| 90 (v1: 120.0, unverified) |"),   # a float written as an int
                         ("| B−C, A−C, B−A, D−B, D−C |", "| B−C, A−C, B−A, D−B |"),
                         ("(`SOL-USD` (1, 4))", "(`SOL-USD` (1, 5))"),
                         ('(`TAKER_BPS`, "venue taker")', '(`TAKER_BPS`, "venue fee")'),
                         ("`FEE_BPS_COLUMNS`, transcribed", "`FEE_BPS_VENUE`, transcribed")):
            with self.subTest(new=new):
                self.assertIn(old, spec_text())
                self.assertEqual(len(section14_disagreements(spec_text().replace(old, new, 1))), 1)
        with self.assertRaises(ValueError):                                  # a row whose cells split differently
            spec14_values("# SPEC\n\n## 14. x\n\n| where | name | value |\n|---|---|---|\n| `loop/config.py` | `A` / `B` | 1 |\n")

    def test_the_v2_constants_are_there(self):
        # PREREG-v2 §10: "§14 the new constants (PRODUCTS, TICK_p, the atoms, CADENCES = (900, 3600, 14400),
        # FROZEN_A = "v2", DAILY_SPEND_HALT_USD)"
        named = spec14()
        for name in ("PRODUCTS", "TICK_P", "LIQ_ATOMS", "LIQ_THIN_FALLBACK", "CADENCES", "FROZEN_A", "DAILY_SPEND_HALT_USD",
                     "FEE_BPS_COLUMNS", "FEE_BPS_VENUE"):
            self.assertIn(("loop.config", name), named)
        self.assertIn(("loop.book", "D_COLUMN"), named)
        with self.assertRaises(ValueError):
            spec14("# SPEC\n\n## 14. x\n\n| where | name | value |\n|---|---|---|\n| `nowhere` | `X` | 1 |\n")


if __name__ == "__main__":
    unittest.main()

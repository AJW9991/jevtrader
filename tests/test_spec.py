"""SPEC.md v2 (PREREG-v2 §10's SPEC bullet) held to the code it describes: the header's promise that every v2 row
carries its sha and that it names PREREG-v2 §12 for T0_v2 and the fee tiers without restating them; §2's row schema
against the row cycle.new_row writes; §5's per-product liq table against config.PRODUCTS, TICK_P, LIQ_ATOMS and
LIQ_THIN_FALLBACK; §10's fee columns and the filled verified tier-0 taker row against config; §14 against the modules
it names, and every constant of loop/config.py (but its paths, URL and key names) named there. tests/test_frozen.py
pins SPEC.md's bytes and each §14 constant's value; this file says the text and the code agree. Read, never
written."""
import importlib, os, re, unittest

from loop import config, cycle

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# loop/config.py's names SPEC §14 need not list: paths, the URL and the key names (SPEC §2, §12 and §13 name them
# where they act), the per-product store's namedtuple and the v2 globals' file names (config.EXCLUSIONS_V2, LOOKS)
CONFIG_NOT_IN_14 = {"REPO", "DATA", "DECISIONS", "SENDS", "HALT", "LOCK", "HEARTBEAT", "PROMPTS", "PROPOSALS", "SPEC",
                    "PROTOCOL", "FORBIDDEN_PREFIXES", "JEV_URL", "KEY_PATHS", "Store"}
NAME = re.compile(r"`([A-Z][A-Z0-9_]*)`")
WHERE = re.compile(r"`((?:loop|nightly)/[a-z_0-9]+)\.py`")


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
            where = m.group(1).replace("/", ".")
        elif c[0]:
            raise ValueError(f"SPEC §14: a where cell that names no module: {c[0]!r}")
        out |= {(where, n) for n in NAME.findall(c[1])}
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
                self.assertTrue(hasattr(importlib.import_module(module), name))

    def test_every_constant_of_config_is_in_section_14(self):
        named = {n for m, n in spec14() if m == "loop.config"}
        mine = {n for n, v in vars(config).items() if re.fullmatch(r"[A-Z][A-Z0-9_]*", n) and not callable(v)}
        self.assertEqual(sorted(mine - named - CONFIG_NOT_IN_14), [])
        self.assertLessEqual(CONFIG_NOT_IN_14 - {"Store"}, mine)             # the exemptions are real names

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

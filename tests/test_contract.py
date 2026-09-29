"""CONTRACT.md's v2 interfaces (PREREG-v2 §10) held to the code: §2's data types (the row's keys, the signatures
of the per-product functions, arm D and the fee constants), §3's tick with PAUSE, §5's reader rule for
prompts.current(tick_id), and §6's list of test files. The contract is what every module is built to; a
signature it names that the code does not have, or a key the writer writes that it does not name, fails here.
Read, never written."""
import inspect, os, re, unittest

from loop import book, config, cycle, prompts, state

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def contract():
    with open(os.path.join(REPO, "CONTRACT.md"), encoding="utf-8") as fh:
        return fh.read()


def section(text, n):
    return text.split(f"\n## {n}. ", 1)[1].split("\n## ", 1)[0]


def params(text, name):
    """The parameter names of the first `name(...)` the text writes as a signature (at a line's start, after `::`, a
    backtick or two spaces; not a call such as `prompts.table(x, p)`), defaults and annotations dropped."""
    m = re.search(r"(?:^|(?<=::)|(?<=`)|(?<=  ))" + re.escape(name) + r"\(([^)]*)\)", text, re.M)
    if m is None:
        return None
    return [p.split("=")[0].split(":")[0].strip() for p in m.group(1).split(",") if p.strip()]


class DataTypes(unittest.TestCase):
    def test_the_row_names_every_key_the_writer_writes(self):
        s2 = section(contract(), 2)
        block = s2.split("**Row**", 1)[1].split("```", 2)[1]
        row = cycle.new_row("2026-10-24T00:00:00.000Z", "live")
        for key in list(row) + list(row["jev"]):
            self.assertIn(f'"{key}"', block, key)
        self.assertRegex(block, r'"columns": \{"a": .*"b": .*"d": "buy"\|"sell"\|"hold"\|null\}')
        self.assertIn(f'"prompt_a": "{config.FROZEN_A}"', block)

    def test_the_signatures_it_names_are_the_codes(self):
        s2 = section(contract(), 2)
        from loop import feed
        self.assertEqual(params(s2, "loop/feed.py::snapshot"), ["product"])          # its `now` is the tests' clock
        self.assertEqual(list(inspect.signature(feed.snapshot).parameters)[0], "product")
        for name, fn in (("adjectives", state.adjectives), ("state_string", state.state_string),
                         ("build", prompts.build), ("current", prompts.current), ("pending", prompts.pending),
                         ("table", prompts.table), ("activation_of", prompts.activation_of), ("at_cadence", book.at_cadence),
                         ("decision_rows", book.decision_rows), ("store", config.store), ("pause", config.pause),
                         ("loop_product", config.loop_product), ("liq_cuts", config.liq_cuts)):
            with self.subTest(name=name):
                self.assertEqual(params(s2, name), list(inspect.signature(fn).parameters))

    def test_arm_d_and_the_fees(self):
        s2 = " ".join(section(contract(), 2).split())
        self.assertIn('arm: ' + "|".join(f'"{a}"' for a in book.ARMS) + ",", s2)
        self.assertIn(f"`book.D_COLUMN`", s2)
        cols = ", ".join(f"{f:g}" for f in config.FEE_BPS_COLUMNS)
        self.assertIn(f"`config.FEE_BPS_COLUMNS` = ({cols})", s2)
        self.assertIn(f"`config.FEE_BPS_VENUE` = {config.FEE_BPS_VENUE}, verified", s2)


class Tick(unittest.TestCase):
    def test_step_1_holds_the_global_halt_and_the_products_pause(self):
        s3 = " ".join(section(contract(), 3).split())
        guards = s3.split("1. **Guards.**", 1)[1].split("2. **Feed.**", 1)[0]
        self.assertIn("`data/HALT` exists (the one global stop)", guards)
        self.assertIn("`data/PAUSE.<PRODUCT>` exists → this tick is HALTED too, for its product only", guards)
        self.assertIn("summed over EVERY product's decision log", guards)
        self.assertIn("`--every-product`", s3)
        self.assertIn("exits 2 before any directory is made", s3)


class Nightly(unittest.TestCase):
    def test_every_reader_asks_current_with_the_tick_it_describes(self):
        s5 = " ".join(section(contract(), 5).split())
        self.assertIn("Every reader calls `prompts.current(tick_id)` with the tick it describes", s5)
        for word in ("`activation_tick`", "`replaces`", "policy_table --fill", "--model <MODEL_ID>", "`CLAUDE_CONFIG_DIR`",
                     "bin/promote --table-only", "prompts/v<N+1>.table.<product>.json"):
            self.assertTrue(word in s5, word)                            # the section is long: name the word, not the text


class Tests(unittest.TestCase):
    def test_every_test_file_section_6_names_exists(self):
        s6 = section(contract(), 6)
        named = set(re.findall(r"`(tests/[a-z_0-9]+\.py)`", s6))
        self.assertGreater(len(named), 8)
        for rel in sorted(named):
            self.assertTrue(os.path.exists(os.path.join(REPO, rel)), rel)


if __name__ == "__main__":
    unittest.main()

"""ERRATA.md: every section it cites exists in the document it cites, so the post-sample
revision can find each entry. The frozen documents are read, never written."""
import os, re, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(REPO, name), encoding="utf-8") as fh:
        return fh.read()


def _sections(doc):
    """The top-level section numbers of a frozen document: '## 3. ...' -> '3'."""
    return set(re.findall(r"^## (\d+)\.", _read(doc), re.M))


def _cited(errata, heading):
    """The section numbers cited in the first column of the table under `## <heading>`."""
    part = errata.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    cells = [line.split("|")[1] for line in part.splitlines() if line.startswith("| §")]
    return {n for cell in cells for n in re.findall(r"§(\d+)", cell)}


def _deviations(errata):
    """(ERRATA.md without its "v2 deviations" section, that section's table rows): the section runs from its heading to
    the next heading of its level or above, as bin/seal-check reads it."""
    lines, keep, rows, depth = errata.splitlines(), [], [], None
    for line in lines:
        h = re.match(r"^(#{1,6}) ", line)
        if h:
            if re.match(r"^#{1,6} .*\bv2 deviations\b", line, re.I):
                depth = len(h.group(1))
                continue
            if depth is not None and len(h.group(1)) <= depth:
                depth = None
        if depth is None:
            keep.append(line)
        elif line.startswith("|"):
            rows.append(line)
    return "\n".join(keep), rows


DEVIATIONS_HEADER = ["| Commit | What it fixes | Why outside §13 (c) |", "|---|---|---|"]


def _deviation_tables(errata):
    """The table rows of each "v2 deviations" section, in order (bin/seal-check reads every such heading the same way,
    to the next heading of its level or above)."""
    tables, depth = [], None
    for line in errata.splitlines():
        h = re.match(r"^(#{1,6}) ", line)
        if h:
            if re.match(r"^#{1,6} .*\bv2 deviations\b", line, re.I):
                depth = len(h.group(1))
                tables.append([])
                continue
            if depth is not None and len(h.group(1)) <= depth:
                depth = None
        if depth is not None and line.startswith("|"):
            tables[-1].append(line)
    return tables


def deviation_problems(errata):
    """Why ERRATA.md's v2 deviations are not as bin/seal-check reads them (empty when they are): a `## v2 deviations`
    section first, and every such section (the first, and a `## v2 deviations (continued)` once main's additions follow
    it) a table with the header row, each row after it naming one commit."""
    bad = []
    if len(re.findall(r"^## v2 deviations \(PREREG-v2 §13\b", errata, re.M)) != 1:
        bad.append("not exactly one ## v2 deviations (PREREG-v2 §13 ...) heading")
    for rows in _deviation_tables(errata):
        if rows[:2] != DEVIATIONS_HEADER:
            bad.append(f"a v2 deviations table does not begin with {DEVIATIONS_HEADER}")
        for row in rows[2:]:
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if len(cells) != 3 or not re.fullmatch(r"[0-9a-f]{7,40}", cells[0].strip("`")):
                bad.append(f"{row!r} is not one commit, what it fixes, why")
    return bad


class Errata(unittest.TestCase):
    def test_every_cited_section_exists(self):
        errata = _read("ERRATA.md")
        for heading, doc in (("PREREG.md", "PREREG.md"), ("SPEC.md", "SPEC.md")):
            cited = _cited(errata, heading)
            self.assertTrue(cited, heading)
            self.assertLessEqual(cited, _sections(doc), (heading, sorted(cited - _sections(doc))))
        self.assertTrue(set(re.findall(r"^\| §(\d+)", errata.split("## PROTOCOL.md\n", 1)[1].split("\n## ", 1)[0], re.M))
                        <= _sections("PROTOCOL.md"))

    def test_every_entry_has_a_kind(self):
        errata = _deviations(_read("ERRATA.md"))[0]              # the v2 deviations table has rows of its own shape
        rows = [l for l in errata.splitlines() if l.startswith("| ") and not l.startswith("| §  ") and "---" not in l
                and not l.startswith("| § |") and not l.startswith("| Where |")]
        self.assertGreater(len(rows), 20)
        for l in rows:
            self.assertRegex(l.rstrip(), r"\| (stale|gloss|gap|choice) \|$", l)

    def test_every_spec_and_prereg_row_says_where_it_was_folded(self):
        # PREREG-v2 §10: "ERRATA.md's SPEC and PREREG rows that describe what the code already does are folded into the
        # text"; the rows stay (v1's sample is read by v1's documents), each marked with where it went. A SPEC row goes
        # to SPEC v2, whose section says "folded from ERRATA.md" where it landed; a PREREG row names the PREREG-v2
        # section that settled it, or says it was not folded and why
        errata, spec, prereg_v2 = _read("ERRATA.md"), _read("SPEC.md"), _read("PREREG-v2.md")
        mark = re.compile(r"\*\*(?:Folded into (SPEC v2|PREREG-v2) §(\d+)\b|Not folded:)")
        for heading in ("PREREG.md", "SPEC.md"):
            part = errata.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
            rows = [l for l in part.splitlines() if re.match(r"\| §\d", l)]          # not the header row
            self.assertGreater(len(rows), 8, heading)
            for row in rows:
                with self.subTest(row=row[:60]):
                    m = mark.search(row)
                    self.assertIsNotNone(m)
                    if heading == "SPEC.md":
                        self.assertEqual(m.group(1), "SPEC v2")
                        body = spec.split(f"\n## {m.group(2)}. ", 1)[1].split("\n## ", 1)[0]
                        self.assertIn("folded from errata.md", body.lower())
                    elif m.group(1):
                        self.assertIn(f"\n## {m.group(2)}. ", prereg_v2)

    def test_the_v2_deviations_table_exists_and_each_row_names_one_commit(self):
        # PREREG-v2 §13: a fix between prereg-v2-draft and the seal outside (c) is one commit and one row of this table;
        # bin/seal-check reads the first cell as the commit and refuses a row that names none
        self.assertEqual(deviation_problems(_read("ERRATA.md")), [])

    def test_a_row_after_mains_later_additions_goes_under_a_continued_heading(self):
        # §13: main adds at the end of ERRATA.md after the draft tag, so the deviations table stops being the end; a
        # later row is an addition at the end only under a new heading, `## v2 deviations (continued)`, which
        # bin/seal-check reads as it reads the first (the S5 refuter's defect 4: this test demanded exactly one)
        errata = (_read("ERRATA.md") + "\n## RESULTS.md (v1), 2026-10-23\n\nmain's erratum after the draft tag\n"
                  "\n## v2 deviations (continued)\n\n" + "\n".join(DEVIATIONS_HEADER) + "\n| 0123456789ab | x | y |\n")
        self.assertEqual(deviation_problems(errata), [])
        self.assertEqual(deviation_problems(errata + "| see above | x | y |\n"),
                         ["'| see above | x | y |' is not one commit, what it fixes, why"])
        self.assertNotIn("main's erratum", "\n".join(_deviations(errata)[1]))
        self.assertIn("main's erratum", _deviations(errata)[0])


if __name__ == "__main__":
    unittest.main()

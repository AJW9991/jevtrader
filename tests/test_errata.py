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

    def test_the_v2_deviations_table_exists_and_each_row_names_one_commit(self):
        # PREREG-v2 §13: a fix between prereg-v2-draft and the seal outside (c) is one commit and one row of this table;
        # bin/seal-check reads the first cell as the commit and refuses a row that names none
        errata = _read("ERRATA.md")
        self.assertEqual(len(re.findall(r"^## v2 deviations\b", errata, re.M)), 1)
        rows = _deviations(errata)[1]
        self.assertEqual(rows[:2], ["| Commit | What it fixes | Why outside §13 (c) |", "|---|---|---|"])
        for row in rows[2:]:
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            self.assertEqual(len(cells), 3, row)
            self.assertRegex(cells[0].strip("`"), r"^[0-9a-f]{7,40}$", row)


if __name__ == "__main__":
    unittest.main()

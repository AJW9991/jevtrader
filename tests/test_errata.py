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
        errata = _read("ERRATA.md")
        rows = [l for l in errata.splitlines() if l.startswith("| ") and not l.startswith("| §  ") and "---" not in l
                and not l.startswith("| § |") and not l.startswith("| Where |")]
        self.assertGreater(len(rows), 20)
        for l in rows:
            self.assertRegex(l.rstrip(), r"\| (stale|gloss|gap|choice) \|$", l)


if __name__ == "__main__":
    unittest.main()

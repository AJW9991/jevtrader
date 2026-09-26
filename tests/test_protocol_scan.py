"""PROTOCOL §3 says its conditions are enforced in code; this scans the code for the two that are
about WHERE things happen: a send leaves only through loop/jev.py::ask (§3.5, §3.11), and nothing
but bin/promote writes prompts/CURRENT (§3.7). Static, no run: a new module that opened a socket
or wrote a prompt would fail here before it ran anywhere."""
import glob, os, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE = sorted(glob.glob(os.path.join(REPO, "loop", "*.py")) + glob.glob(os.path.join(REPO, "nightly", "*.py"))
              + [os.path.join(REPO, "nightly", "propose.sh"), os.path.join(REPO, "bin", "promote")])


def _code_lines(path):
    with open(path, encoding="utf-8") as fh:
        return [l for l in fh.read().splitlines() if not l.lstrip().startswith("#")]


def _rel(p):
    return os.path.relpath(p, REPO)


class ProtocolScan(unittest.TestCase):
    def test_only_jev_py_talks_to_typesafe(self):
        hits = {_rel(p) for p in CODE if any("JEV_URL" in l or "typesafe.ai" in l for l in _code_lines(p))}
        self.assertEqual(hits, {"loop/config.py", "loop/jev.py"})
        sockets = {_rel(p) for p in CODE if any("urlopen(" in l for l in _code_lines(p))}
        self.assertEqual(sockets, {"loop/feed.py", "loop/jev.py"})       # the public venue feed, and the one send path

    def test_only_promote_writes_current(self):
        writers = {_rel(p) for p in CODE
                   if any("CURRENT" in l and ('"w"' in l or "'w'" in l) for l in _code_lines(p))}
        self.assertEqual(writers, {"bin/promote"})
        for p in CODE:
            if _rel(p) == "bin/promote":
                continue
            self.assertEqual([l for l in _code_lines(p) if "PROMPTS" in l and ('"w"' in l or "'w'" in l)], [], _rel(p))

    def test_crypto_repo_is_never_read(self):
        for p in CODE + glob.glob(os.path.join(REPO, "tests", "*.py")):
            if _rel(p) in ("loop/config.py", "tests/test_protocol_scan.py"):   # FORBIDDEN_PREFIXES, and this scan
                continue
            for l in _code_lines(p):
                if "crypto-trading-system" in l:
                    self.assertTrue("FORBIDDEN" in l or "forbidden" in l or "guard" in l or "refus" in l or "assert" in l or "case" in l or "Mobile" in l,
                                    f"{_rel(p)}: {l.strip()}")


if __name__ == "__main__":
    unittest.main()

"""The suite in a shuffled order: `python3 tests/modes/shuffled.py [--start DIR] [seed ...]` (seeds
default to 1 2 3; `make test-mode MODE=shuffled`). Each seed loads the suite as `make test` does
(discover under tests/), flattens it to single tests, shuffles them with random.Random(seed) and
runs them in that order; class and module fixtures still run around each change of class. A test
that passes only after another one (a shared cache, a module global left set, a patched config
not put back) fails here. Every error and failure is printed with its seed; exit 1 if there was one.
Standard library only; not collected by `make test` (tests/modes has no __init__.py)."""
import os, random, sys, unittest

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(TESTS)


def flat(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from flat(t)
        else:
            yield t


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    start = TESTS
    if argv[:1] == ["--start"]:
        start, argv = os.path.abspath(argv[1]), argv[2:]
    seeds = [int(x) for x in argv] or [1, 2, 3]
    os.chdir(REPO)                                   # as `make test`: `from loop import ...` resolves from the repo
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    bad = 0
    for seed in seeds:
        tests = list(flat(unittest.defaultTestLoader.discover(start, top_level_dir=start)))
        random.Random(seed).shuffle(tests)
        with open(os.devnull, "w", encoding="utf-8") as sink:
            r = unittest.TextTestRunner(stream=sink, verbosity=0).run(unittest.TestSuite(tests))
        print(f"seed {seed}: ran {r.testsRun}, errors {len(r.errors)}, failures {len(r.failures)},"
              f" skipped {len(r.skipped)}", flush=True)
        for t, tb in r.errors + r.failures:
            print(f"  seed {seed}: {t.id()}: {tb.strip().splitlines()[-1][:300]}", flush=True)
        bad += len(r.errors) + len(r.failures)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

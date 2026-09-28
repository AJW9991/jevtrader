"""The tools behind `make test-mode` (tests/modes): the clock shim moves the wall clock only when
FAKE_NOW is set, the shuffle runner really changes the order and reports a failure with its seed,
and the Makefile's modes are the ones CI runs."""
import datetime, os, re, subprocess, sys, tempfile, textwrap, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOCK = os.path.join(REPO, "tests", "modes", "clock")
SHUFFLED = os.path.join(REPO, "tests", "modes", "shuffled.py")
PROBE = ("import datetime, time; print(time.time()); print(time.time_ns()); "
         "print(datetime.datetime.now(datetime.timezone.utc).isoformat()); print(datetime.date.today().isoformat()); "
         "print(datetime.datetime.utcnow().isoformat())")


def _env(**kw):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "FAKE_NOW")}
    env.update(kw)
    return env


class ClockShim(unittest.TestCase):
    def _probe(self, env):
        r = subprocess.run([sys.executable, "-W", "ignore::DeprecationWarning", "-c", PROBE], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.split()

    def test_fake_now_moves_every_wall_clock_the_suite_reads(self):
        t, ns, now, today, utc = self._probe(_env(PYTHONPATH=CLOCK, FAKE_NOW="2031-02-03T04:05:06Z"))
        want = datetime.datetime(2031, 2, 3, 4, 5, 6, tzinfo=datetime.timezone.utc).timestamp()
        self.assertLess(abs(float(t) - want), 60)
        self.assertLess(abs(int(ns) / 1e9 - want), 60)
        self.assertTrue(now.startswith("2031-02-03T04:0"), now)
        self.assertIn(today, ("2031-02-02", "2031-02-03", "2031-02-04"))   # local date, whatever the runner's zone
        self.assertTrue(utc.startswith("2031-02-03T04:0"), utc)

    def test_without_fake_now_the_shim_does_nothing(self):
        # against a child with no shim at all, not this process: under `make test-mode MODE=day-28` this
        # process's own clock is the moved one
        real = float(self._probe(_env())[0])
        t = float(self._probe(_env(PYTHONPATH=CLOCK))[0])
        self.assertLess(abs(t - real), 60)


class ShuffledRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.order = os.path.join(self.tmp, "order.txt")

    def _suite(self, fail=False):
        names = [f"test_{c}" for c in "abcdefghij"]
        body = "".join(f"    def {n}(self):\n        _log('{n}')\n" for n in names)
        if fail:
            body += "    def test_zz_fails(self):\n        self.assertEqual(1, 2)\n"
        with open(os.path.join(self.tmp, "test_sample.py"), "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(f"""\
                import unittest
                def _log(n):
                    with open({self.order!r}, "a", encoding="utf-8") as fh:
                        fh.write(n + "\\n")
                class T(unittest.TestCase):
                """) + body)
        return names

    def _run(self, *seeds):
        return subprocess.run([sys.executable, SHUFFLED, "--start", self.tmp, *map(str, seeds)],
                              capture_output=True, text=True, timeout=120)

    def test_each_seed_runs_every_test_in_a_new_order(self):
        names = self._suite()
        r = self._run(1, 2)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("seed 1: ran 10, errors 0, failures 0, skipped 0", r.stdout)
        self.assertIn("seed 2: ran 10, errors 0, failures 0, skipped 0", r.stdout)
        with open(self.order, encoding="utf-8") as fh:
            ran = fh.read().split()
        first, second = ran[:10], ran[10:]
        self.assertEqual(sorted(first), names)
        self.assertEqual(sorted(second), names)
        self.assertNotEqual(first, names)                      # not the loader's alphabetical order
        self.assertNotEqual(first, second)                     # and the seed decides it

    def test_a_failure_exits_1_and_names_its_seed(self):
        self._suite(fail=True)
        r = self._run(7)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("seed 7: ran 11, errors 0, failures 1", r.stdout)
        self.assertRegex(r.stdout, r"seed 7: test_sample\.T\.test_zz_fails: AssertionError: 1 != 2")


class MakeAndCI(unittest.TestCase):
    def test_every_make_mode_has_a_branch_and_ci_runs_exactly_them(self):
        with open(os.path.join(REPO, "Makefile"), encoding="utf-8") as fh:
            make = fh.read()
        with open(os.path.join(REPO, ".github", "workflows", "test.yml"), encoding="utf-8") as fh:
            ci = fh.read()
        modes = re.search(r"(?m)^MODES = (.+)$", make).group(1).split()
        self.assertEqual(len(modes), 6)
        for m in modes:
            self.assertRegex(make, rf"(?m)^\s+{re.escape(m)}\) ")
        matrix = re.search(r"(?m)^\s+mode: \[(.+)\]$", ci).group(1)
        self.assertEqual([x.strip() for x in matrix.split(",")], modes)
        self.assertIn("make PY=\"$(command -v python3)\" test-mode MODE=${{ matrix.mode }}", ci)


if __name__ == "__main__":
    unittest.main()

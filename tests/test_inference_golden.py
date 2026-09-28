"""The pre-registered draw, pinned (PREREG §4-§5). loop/inference.py's bootstrap is compared, resample
for resample, against a transcription of PREREG §5 steps 1-3 written here from the text and NOT
from inference.resample_indices, on fixed non-degenerate series at the pre-registered seed; one
lower bound per statistic is pinned as a number. Mutations these tests exist to catch: sorting
descending, reading sorted[250] at 10,000 resamples, re-seeding per resample, and drawing
n // 4 + 1 starts instead of ceil(n / 4) (the same count unless 4 divides n)."""
import math, random, unittest
from unittest import mock

from loop import inference, report

SEED = 20260923                      # PREREG §4-§5, copied from the text, not read from inference.SEED
RESAMPLES = 10000                    # PREREG §4-§5
RealRandom = random.Random


def _floats(n, seed):
    """n deterministic pseudo-random floats (six decimals, as a price move would be), no ties."""
    g = RealRandom(seed)
    return [round(g.gauss(0.0, 30.0), 6) for _ in range(n)]


def _pairs(n, seed):
    """n (x, y) pairs with some correlation: x a lean-like value rounded to 12 dp, y a return."""
    g = RealRandom(seed)
    out = []
    for _ in range(n):
        x = round(g.uniform(-0.4, 0.4), 12)
        out.append((x, round(20.0 * x + g.gauss(0.0, 30.0), 6)))
    return out


def _mean(xs):
    return sum(xs) / len(xs)


def _pearson(ps):
    return report.pearson([x for x, _ in ps], [y for _, y in ps])      # "as loop/report.py::pearson" (§5 step 3)


def prereg_sorted(series, stat, resamples):
    """PREREG §5, steps 1-3, as the text reads:
    1. the n units indexed 0 .. n - 1; index i >= n wraps to i - n.
    2. one generator, random.Random(20260923), for this statistic alone; for each resample in turn,
       draw ceil(n / 4) start indices in order, each rng.randrange(n); from each start s take the
       4 units s, s + 1, s + 2, s + 3 (wrapped); concatenate in draw order; keep the first n.
    3. the statistic of each resample, undefined -> 0; sorted ascending."""
    n = len(series)
    assert n >= 4                     # "wraps to i - n" is one wrap: s + 3 <= n + 2 < 2n
    rng = RealRandom(SEED)
    out = []
    for _ in range(resamples):
        starts = [rng.randrange(n) for _ in range(math.ceil(n / 4))]
        taken = []
        for s in starts:
            for i in (s, s + 1, s + 2, s + 3):
                taken.append(series[i - n] if i >= n else series[i])
        v = stat(taken[:n])
        out.append(0.0 if v is None else v)
    return sorted(out)


class Case(unittest.TestCase):
    def same(self, got, want, what=""):
        """assertEqual for long lists without difflib's quadratic diff of 10,000 lines: the first
        index where they part, or the lengths."""
        if got == want:
            return
        i = next((i for i, (g, w) in enumerate(zip(got, want)) if g != w), min(len(got), len(want)))
        self.fail(f"{what}: lengths {len(got)} vs {len(want)}; first difference at [{i}]: "
                  f"{got[i] if i < len(got) else '-'!r} vs {want[i] if i < len(want) else '-'!r}")


class Transcription(Case):
    def test_h1_draw_n24_at_10000_is_the_transcription_and_its_lower_bound_is_pinned(self):
        s = _floats(24, 1)
        b = inference.bootstrap(s, inference.mean)                        # the defaults: seed and resamples as run at day 28
        want = prereg_sorted(s, _mean, RESAMPLES)
        self.same(b["sorted"], want, "H1 n 24")
        self.assertEqual(len(b["sorted"]), RESAMPLES)
        self.assertNotEqual(want[249], want[250])                         # so reading sorted[250] cannot pass
        self.assertEqual(b["lower"], want[249])                           # the 250th = ceil(0.025 x 10,000), nearest rank
        # The pre-registered draw's value for this series: computed once from the transcription above
        # and pasted here, so a change to the draw, the rank or the sort order shows as a number.
        self.assertAlmostEqual(b["lower"], H1_LOWER_N24, places=9)      # the draw is exact (above); the bound is a float sum

    def test_h2_draw_n24_at_10000_is_the_transcription_and_its_lower_bound_is_pinned(self):
        ps = _pairs(24, 2)
        b = inference.bootstrap(ps, inference.pearson_pairs)
        want = prereg_sorted(ps, _pearson, RESAMPLES)
        self.same(b["sorted"], want, "H2 n 24")
        self.assertNotEqual(want[249], want[250])
        # The pre-registered draw's value for this series (computed once, pasted; see above).
        self.assertAlmostEqual(b["lower"], H2_LOWER_N24, places=12)     # sum() is compensated from 3.12 on: 3.11 differs in the last bit

    def test_h1_draw_n2013_is_the_transcription(self):
        s = _floats(2013, 3)                                              # n not a multiple of 4: the last start is cut
        self.same(inference.bootstrap(s, inference.mean, resamples=120)["sorted"], prereg_sorted(s, _mean, 120), "H1 n 2013")

    def test_h2_draw_n2013_is_the_transcription(self):
        ps = _pairs(2013, 4)
        self.same(inference.bootstrap(ps, inference.pearson_pairs, resamples=30)["sorted"], prereg_sorted(ps, _pearson, 30), "H2 n 2013")

    def test_a_multiple_of_4_is_the_transcription_too(self):
        s = _floats(2012, 5)
        self.same(inference.bootstrap(s, inference.mean, resamples=80)["sorted"], prereg_sorted(s, _mean, 80), "H1 n 2012")


class Generator(Case):
    """One generator per statistic, drawn continuously: resample j's starts are draws
    j*ceil(n/4) + 1 .. (j+1)*ceil(n/4) of random.Random(20260923), and exactly ceil(n/4) per resample."""

    def _starts(self, n, resamples=3):
        seen = []
        inference.bootstrap(list(range(n)), lambda xs: seen.append(list(xs)) or 0.0, resamples=resamples)
        return [[xs[i] for i in range(0, n, 4)] for xs in seen]          # the value at a start's slot is the start itself

    def test_the_second_resample_continues_the_first_resamples_generator(self):
        for n in (8, 10, 12, 2012, 2013, 2688):
            m = math.ceil(n / 4)
            rng = RealRandom(SEED)
            draws = [rng.randrange(n) for _ in range(3 * m)]
            got = self._starts(n)
            self.same(got[0], draws[:m], f"n {n}, resample 1")
            self.same(got[1], draws[m:2 * m], f"n {n}, resample 2")      # draws ceil(n/4)+1 .. 2 ceil(n/4), not a fresh seed
            self.same(got[2], draws[2 * m:3 * m], f"n {n}, resample 3")

    def test_exactly_ceil_n_over_4_starts_are_drawn_per_resample(self):
        class Counting(RealRandom):
            calls = 0

            def randrange(self, *a, **k):
                Counting.calls += 1
                return super().randrange(*a, **k)

        for n in list(range(1, 21)) + [2012, 2013, 2688]:
            Counting.calls = 0
            idx = inference.resample_indices(Counting(SEED), n)
            self.assertEqual((Counting.calls, len(idx)), (math.ceil(n / 4), n), n)
        with mock.patch.object(inference.random, "Random", Counting):
            for n, r in ((8, 7), (2688, 3), (2013, 3)):
                Counting.calls = 0
                inference.bootstrap([0.0] * n, inference.mean, resamples=r)
                self.assertEqual(Counting.calls, r * math.ceil(n / 4), n)

    def test_each_statistic_gets_its_own_generator_from_the_seed(self):
        s = _floats(40, 6)
        a = inference.bootstrap(s, inference.mean, resamples=50)
        inference.bootstrap(_pairs(40, 7), inference.pearson_pairs, resamples=50)   # H2 in between draws nothing of H1's
        self.same(inference.bootstrap(s, inference.mean, resamples=50)["sorted"], a["sorted"], "H1 again")
        self.same(a["sorted"], prereg_sorted(s, _mean, 50), "H1 n 40")


H1_LOWER_N24 = -10.229086083333334        # sorted[249] of the H1 draw on _floats(24, 1): pasted from the transcription
H2_LOWER_N24 = -0.23551710256267708       # sorted[249] of the H2 draw on _pairs(24, 2): pasted from the transcription


if __name__ == "__main__":
    unittest.main()

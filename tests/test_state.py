"""loop/state.py against CONTRACT §2 and §6, offline, on a synthetic candle series.

No fixture is read: the boundaries are exercised on hand-built feature dicts (the only
way to sit exactly ON a cut), and `features` is pinned on a seeded random walk against
plain-index restatements of every definition in state.py's docstring. When the
fixtures builder lands a real snapshot, add a smoke test here; do not replace these.
"""
import importlib.machinery, importlib.util, math, os, random, re, statistics, unittest
from unittest import mock
from loop import config, state

W = config.WINDOW_MIN                     # 300
EPS = 1e-9


def below(x):
    return math.nextafter(x, -math.inf)   # the largest float strictly below x


def above(x):
    return math.nextafter(x, math.inf)    # the smallest float strictly above x


def candles(closes, volumes, start=1_758_600_000):
    return [{"start": start + 60 * i, "open": c, "high": c, "low": c, "close": c, "volume": v}
            for i, (c, v) in enumerate(zip(closes, volumes))]


def walk(n, seed=7, p0=200.0):
    """A seeded 1-min random walk with lognormal-ish volume: deterministic, never flat,
    never zero, so every definition below has a non-degenerate value to pin."""
    rng = random.Random(seed)
    closes, vols = [], []
    p = p0
    for _ in range(n):
        p *= math.exp(rng.gauss(0.0, 0.0008))         # ~8 bps a minute, SOL-like
        closes.append(p)
        vols.append(math.exp(rng.gauss(4.0, 0.6)))     # base units per minute
    return closes, vols


def snapshot(closes, vols, bid=199.99, ask=200.01, bid_size=20.0, ask_size=30.0, bids=None, asks=None):
    return {"ts_rx": "2026-09-23T00:00:00.000Z", "product": config.PRODUCT,
            "bid": bid, "bid_size": bid_size, "ask": ask, "ask_size": ask_size,
            "bids": [[bid, bid_size]] if bids is None else bids,
            "asks": [[ask, ask_size]] if asks is None else asks,
            "book_time": None, "candles": candles(closes, vols),
            "trades_5m": 100, "feed_age_s": 3.0, "http": {"calls": 3, "ms": 250}}


MID_FEAT = {"mid": 200.0, "spread_bps": 1.0, "l1_min_usd": 5000.0, "fill1k_bps": 0.75, "fill1k_short": False,
            "vol5_usd": 500.0, "vol5_p10": 100.0, "vol5_p90": 900.0,
            "ret15_bps": 0.0, "ret15_sd_bps": 10.0, "ret15_z": 0.0,
            "rv15": 1e-6, "rv15_med": 1e-6, "rv_ratio": 1.0, "window_min": W}


def feat(**over):
    f = dict(MID_FEAT)
    f.update(over)
    return f


class Features(unittest.TestCase):
    def setUp(self):
        self.closes, self.vols = walk(W + 20)          # 320: more than the window, like the venue's 350
        self.snap = snapshot(self.closes, self.vols)
        self.f = state.features(self.snap)

    def test_keys_and_window(self):
        self.assertEqual(tuple(self.f), state.FEATURE_KEYS)
        self.assertEqual(self.f["window_min"], W)
        for k in state.FEATURE_KEYS:
            self.assertTrue(math.isfinite(self.f[k]), k)

    def test_book_numbers(self):
        self.assertAlmostEqual(self.f["mid"], 200.0)
        self.assertAlmostEqual(self.f["spread_bps"], 1e4 * 0.02 / 200.0)
        self.assertAlmostEqual(self.f["l1_min_usd"], min(199.99 * 20.0, 200.01 * 30.0))
        # $4,000 and $6,000 at level 1: the $1,000 order fills there, so the cost is the half-spread
        self.assertAlmostEqual(self.f["fill1k_bps"], 1e4 * 0.01 / 200.0)
        self.assertIs(self.f["fill1k_short"], False)

    def test_flow_is_last_5_and_nearest_rank_over_60_blocks(self):
        c, v = self.closes[-W:], self.vols[-W:]
        usd = [a * b for a, b in zip(v, c)]                       # base volume × close
        sums = [sum(usd[i:i + 5]) for i in range(0, W, 5)]         # 60 non-overlapping 5-min sums
        self.assertEqual(len(sums), 60)
        self.assertAlmostEqual(self.f["vol5_usd"], sums[-1])
        s = sorted(sums)
        self.assertAlmostEqual(self.f["vol5_p10"], s[6 - 1])        # ceil(0.10·60) = 6th smallest
        self.assertAlmostEqual(self.f["vol5_p90"], s[54 - 1])       # ceil(0.90·60) = 54th
        self.assertLess(self.f["vol5_p10"], self.f["vol5_p90"])

    def test_nearest_rank_float_trap(self):
        # 0.1*60 == 6.000000000000001 in binary; a float ceil would give rank 7. Integer path: 6.
        vals = list(range(1, 61))
        self.assertEqual(state._nearest_rank(vals, 10), 6)
        self.assertEqual(state._nearest_rank(vals, 90), 54)
        self.assertEqual(state._nearest_rank([5.0], 10), 5.0)
        self.assertEqual(state._nearest_rank([5.0], 90), 5.0)

    def test_trend_is_ln_now_over_15_ago_z_scored_by_overlapping_sd(self):
        c = self.closes[-W:]
        ret = 1e4 * math.log(c[-1] / c[-16])                          # last CLOSED candle is now
        self.assertAlmostEqual(self.f["ret15_bps"], ret)
        r15 = [1e4 * math.log(c[i] / c[i - 15]) for i in range(15, W)]  # 285 overlapping
        self.assertEqual(len(r15), 285)
        sd = statistics.stdev(r15)
        self.assertAlmostEqual(self.f["ret15_sd_bps"], sd)
        self.assertAlmostEqual(self.f["ret15_z"], ret / sd)

    def test_rv_is_last_15_squared_returns_over_median_of_19_blocks(self):
        c = self.closes[-W:]
        sq = [math.log(c[i] / c[i - 1]) ** 2 for i in range(1, W)]    # 299 one-minute returns
        self.assertAlmostEqual(self.f["rv15"], sum(sq[-15:]))
        blocks = [sum(sq[14 + 15 * k: 14 + 15 * (k + 1)]) for k in range(19)]  # drop the 14 oldest
        self.assertEqual(len(blocks), 19)
        self.assertAlmostEqual(blocks[-1], self.f["rv15"])              # the live block IS rv15
        med = statistics.median(blocks)
        self.assertAlmostEqual(self.f["rv15_med"], med)
        self.assertAlmostEqual(self.f["rv_ratio"], self.f["rv15"] / med)

    def test_only_the_last_window_counts(self):
        # 20 leading candles of nonsense must change nothing: the window is the last 300.
        junk_c = [1.0e6] * 20 + self.closes[-W:]
        junk_v = [1.0e9] * 20 + self.vols[-W:]
        g = state.features(snapshot(junk_c, junk_v))
        for k in state.FEATURE_KEYS:
            self.assertAlmostEqual(g[k], self.f[k], msg=k)

    def test_short_window_is_refused(self):
        c, v = walk(W - 1)
        with self.assertRaises(ValueError):
            state.features(snapshot(c, v))

    def test_exactly_window_min_is_accepted(self):
        c, v = walk(W)
        self.assertEqual(state.features(snapshot(c, v))["window_min"], W)

    def test_no_scale_reads_neutral(self):
        # 300 equal closes (a stuck feed): sd = 0 and rv15_med = 0 → z 0.0, ratio 1.0 → flat/normal → hold.
        f = state.features(snapshot([150.0] * W, [1.0] * W))
        self.assertEqual(f["ret15_bps"], 0.0)
        self.assertEqual(f["ret15_z"], 0.0)
        self.assertEqual(f["rv_ratio"], 1.0)
        adj = state.adjectives(f)
        self.assertEqual((adj["trend"], adj["vol"]), ("flat", "normal"))
        self.assertEqual(state.rule_c(adj), "hold")

    def test_end_to_end_words_and_string(self):
        adj = state.adjectives(self.f)
        for d in state.DIMS:
            self.assertIn(adj[d], state.ALPHABET[d])
        s = state.state_string(adj)
        self.assertFalse(any(ch.isdigit() for ch in s))
        self.assertIn(state.rule_c(adj), ("buy", "sell", "hold"))


class Boundaries(unittest.TestCase):
    """Every cut, just below / on / just above, using nextafter so 'just' is one ulp."""

    def words(self, dim, key, x):
        return state.adjectives(feat(**{key: x}))[dim]

    def check(self, dim, key, lo, hi, wlo, wmid, whi):
        self.assertEqual(self.words(dim, key, below(lo)), wlo)
        self.assertEqual(self.words(dim, key, lo), wmid)          # ON the cut: strict <, so middle
        self.assertEqual(self.words(dim, key, above(lo)), wmid)
        self.assertEqual(self.words(dim, key, below(hi)), wmid)
        self.assertEqual(self.words(dim, key, hi), wmid)          # ON the cut: strict >, so middle
        self.assertEqual(self.words(dim, key, above(hi)), whi)
        self.assertEqual(self.words(dim, key, lo - 1.0), wlo)     # and comfortably beyond
        self.assertEqual(self.words(dim, key, hi + 1.0), whi)

    def test_liq(self):
        # PREREG-v2 §3: liq is h, the cost of walking the book for one NOTIONAL_USD order in the product's
        # half-ticks. It runs the other way round: a LOW cost is deep, so the low cut (a10 + 0.5 = 1.5 for
        # SOL) is deep's and the high cut (a90 + 0.5 = 4.5) is thin's; ON either cut is normal (strict < and
        # >). Checked on h itself: one ulp of fill1k_bps does not survive the product with mid.
        lo, hi = config.liq_cuts("SOL-USD")
        self.assertEqual((lo, hi), (1.5, 4.5))
        word = lambda h: state.liq(h, False, "SOL-USD")
        self.assertEqual([word(below(lo)), word(lo), word(above(lo)), word(below(hi)), word(hi), word(above(hi))],
                         ["deep", "normal", "normal", "normal", "normal", "thin"])
        self.assertEqual([word(0.0), word(1.0), word(2.0), word(4.0), word(5.0), word(math.inf)],
                         ["deep", "deep", "normal", "normal", "thin", "thin"])

    def test_h_is_the_fill_in_half_ticks_of_the_product(self):
        # h = fill1k_bps * mid / (1e4 * TICK_P / 2): at mid 200 and a 1c tick half a tick is 0.25 bps
        self.assertEqual(state.half_ticks(0.25, 200.0, "SOL-USD"), 1.0)
        self.assertEqual(state.half_ticks(1.125, 200.0, "SOL-USD"), 4.5)
        self.assertAlmostEqual(state.half_ticks(0.8698677800991063, 114.96, "SOL-USD"), 2.0, places=9)
        for fill, want in ((0.25, "deep"), (0.37, "deep"), (0.38, "normal"), (0.75, "normal"),
                           (1.12, "normal"), (1.13, "thin"), (3.0, "thin")):
            self.assertEqual(state.adjectives(feat(fill1k_bps=fill))["liq"], want, fill)
        # the same bps at half the price is half the ticks: the cut moves with the price in bps, not in h
        self.assertEqual(state.adjectives(feat(fill1k_bps=1.0, mid=100.0))["liq"], "normal")    # h 2.0
        self.assertEqual(state.adjectives(feat(fill1k_bps=1.0, mid=200.0))["liq"], "normal")    # h 4.0
        self.assertEqual(state.adjectives(feat(fill1k_bps=1.0, mid=300.0))["liq"], "thin")      # h 6.0

    def test_liq_reads_the_products_own_tick_atoms_and_fallback(self):
        two = ("SOL-USD", "ETH-USD")
        with mock.patch.object(config, "PRODUCTS", two), \
                mock.patch.dict(config.TICK_P, {"ETH-USD": 0.1}), \
                mock.patch.dict(config.LIQ_ATOMS, {"ETH-USD": (2, 6)}), \
                mock.patch.dict(config.LIQ_THIN_FALLBACK, {"ETH-USD": False}):
            f = feat(fill1k_bps=10.0, mid=200.0)                    # h: SOL 40.0 (1c tick), ETH 4.0 (10c tick)
            self.assertEqual(state.adjectives(f, "SOL-USD")["liq"], "thin")
            self.assertEqual(state.adjectives(f, "ETH-USD")["liq"], "normal")
            self.assertEqual(state.adjectives(feat(fill1k_bps=5.0, mid=200.0), "ETH-USD")["liq"], "deep")   # h 2.0 < 2.5
            self.assertEqual(state.adjectives(feat(fill1k_bps=17.5, mid=200.0), "ETH-USD")["liq"], "thin")  # h 7.0 > 6.5
            with mock.patch.dict(config.LIQ_THIN_FALLBACK, {"ETH-USD": True}):          # thin iff h > a90 - 0.5
                self.assertEqual(state.adjectives(feat(fill1k_bps=15.0, mid=200.0), "ETH-USD")["liq"], "thin")  # 6.0
            self.assertEqual(state.adjectives(feat(fill1k_bps=15.0, mid=200.0), "ETH-USD")["liq"], "normal")
        with self.assertRaises(KeyError):
            state.adjectives(feat(), "BTC-USD")                   # no tick for a product outside PRODUCTS (never a candidate)

    def test_liq_is_bin_fill1k_quantiles_own_rule_and_sols_atoms_are_the_quoted_output(self):
        # one rule in two places (the tool imports nothing from loop/): the same h, the same word, and
        # SOL's atoms are the tool's rounding of the h_p10 / h_p90 PREREG-v2 §3 quotes from its output
        path = os.path.join(config.REPO, "bin", "fill1k-quantiles")
        loader = importlib.machinery.SourceFileLoader("fill1k_quantiles_for_state", path)
        tool = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(tool)
        lo, hi = config.liq_cuts("SOL-USD")
        for h in [i / 8 for i in range(0, 81)] + [below(lo), above(lo), below(hi), above(hi), math.inf]:
            self.assertEqual(state.liq(h, False, "SOL-USD"), tool._word(h, lo, hi), h)
        for fill, mid in ((0.25, 200.0), (0.8698677800991063, 114.96), (3.7485, 131.0)):
            self.assertEqual(state.half_ticks(fill, mid, "SOL-USD"), tool.half_ticks(fill, mid, config.TICK_P["SOL-USD"]))
        with open(os.path.join(config.REPO, "PREREG-v2.md"), encoding="utf-8") as fh:
            text = fh.read()
        q = dict(re.findall(r"^  (h_p10|h_p90|thin_fallback|a10|a90): (\S+)$", text, re.M))
        self.assertEqual((tool.atom(float(q["h_p10"])), tool.atom(float(q["h_p90"]))), config.LIQ_ATOMS["SOL-USD"])
        self.assertEqual((int(q["a10"]), int(q["a90"])), config.LIQ_ATOMS["SOL-USD"])
        self.assertEqual(q["thin_fallback"] == "yes", config.LIQ_THIN_FALLBACK["SOL-USD"])

    def test_liq_short_side_is_thin(self):
        # a side the levels cannot fill: logged as null + fill1k_short, read as inf -> thin
        self.assertEqual(state.adjectives(feat(fill1k_bps=None, fill1k_short=True))["liq"], "thin")
        self.assertEqual(state.adjectives(feat(fill1k_bps=math.inf, fill1k_short=False))["liq"], "thin")
        self.assertEqual(state.adjectives(feat(fill1k_bps=0.5, fill1k_short=True))["liq"], "thin")   # the flag wins

    def test_l1_no_longer_sets_liq(self):
        # the old word: l1_min_usd < $1000 -> thin. It is still logged; it moves no word now.
        for l1 in (0.0, 1.0, 999.0, 1e6):
            self.assertEqual(state.adjectives(feat(l1_min_usd=l1, fill1k_bps=0.25))["liq"], "deep")
            self.assertEqual(state.adjectives(feat(l1_min_usd=l1))["liq"], "normal")
        self.assertFalse(hasattr(config, "LIQ_THIN_USD"))
        self.assertFalse(hasattr(config, "LIQ_DEEP_USD"))

    def test_flow(self):
        # flow's cuts are the window's own p10/p90, carried in feat (100.0 / 900.0 here).
        self.check("flow", "vol5_usd", MID_FEAT["vol5_p10"], MID_FEAT["vol5_p90"], "quiet", "organic", "bot_war")

    def test_trend(self):
        self.assertEqual(config.TREND_Z, 1.0)
        self.check("trend", "ret15_z", -config.TREND_Z, config.TREND_Z, "dumping", "flat", "pumping")

    def test_vol(self):
        self.assertEqual((config.VOL_RATIO_LO, config.VOL_RATIO_HI), (0.5, 2.0))
        self.check("vol", "rv_ratio", config.VOL_RATIO_LO, config.VOL_RATIO_HI, "calm", "normal", "violent")

    def test_dims_are_independent(self):
        # Moving one number moves one word.
        base = state.adjectives(MID_FEAT)
        self.assertEqual(base, {"liq": "normal", "flow": "organic", "trend": "flat", "vol": "normal"})
        for key, dim, x in (("fill1k_bps", "liq", 99.0), ("vol5_usd", "flow", 1e9),
                            ("ret15_z", "trend", -5.0), ("rv_ratio", "vol", 9.0)):
            adj = state.adjectives(feat(**{key: x}))
            self.assertNotEqual(adj[dim], base[dim])
            for other in state.DIMS:
                if other != dim:
                    self.assertEqual(adj[other], base[other])


class Walk(unittest.TestCase):
    """fill_cost_bps and fill1k_bps on hand-built books: every number below is restated
    by hand, not taken from state.py. mid is 100.0 (bid 99.99 / ask 100.01)."""
    MID = 100.0
    # asks: $200.02 + $300.09 at levels 1-2, then $1,001.00 at level 3: the order ends in level 3
    ASKS = [[100.01, 2.0], [100.03, 3.0], [100.10, 10.0]]
    # bids: $499.95 + $499.90 at levels 1-2 ($999.85), then $9,990 at level 3: ends in level 3
    BIDS = [[99.99, 5.0], [99.98, 5.0], [99.90, 100.0]]

    def test_buy_vwap_exact(self):
        rem = 1000.0 - 100.01 * 2.0 - 100.03 * 3.0                       # $499.89 left for level 3
        base = 2.0 + 3.0 + rem / 100.10                                   # SOL bought
        vwap = 1000.0 / base
        want = 1e4 * (vwap - self.MID) / self.MID
        got = state.fill_cost_bps(self.ASKS, self.MID, "buy")
        self.assertAlmostEqual(got, want, places=9)
        self.assertAlmostEqual(got, 6.0976, places=4)                     # 6.10 bps: past the 5.0 cut

    def test_sell_vwap_exact(self):
        rem = 1000.0 - 99.99 * 5.0 - 99.98 * 5.0                          # $0.15 left for level 3
        base = 5.0 + 5.0 + rem / 99.90
        vwap = 1000.0 / base
        want = 1e4 * (self.MID - vwap) / self.MID
        got = state.fill_cost_bps(self.BIDS, self.MID, "sell")
        self.assertAlmostEqual(got, want, places=9)
        self.assertAlmostEqual(got, 1.5013, places=4)

    def test_level_one_alone_is_the_half_spread(self):
        self.assertAlmostEqual(state.fill_cost_bps([[100.01, 50.0]], self.MID, "buy"), 1.0, places=9)
        self.assertAlmostEqual(state.fill_cost_bps([[99.99, 50.0]], self.MID, "sell"), 1.0, places=9)
        # exactly NOTIONAL at level 1 fills (>=), it is not short
        self.assertAlmostEqual(state.fill_cost_bps([[100.0, 10.0]], self.MID, "buy"), 0.0, places=12)

    def test_cannot_fill_is_inf(self):
        # $200.02 + $300.09 + $100.10 = $600.21 < $1,000 on the asks
        self.assertEqual(state.fill_cost_bps([[100.01, 2.0], [100.03, 3.0], [100.10, 1.0]], self.MID, "buy"),
                         math.inf)
        self.assertEqual(state.fill_cost_bps([], self.MID, "sell"), math.inf)
        with self.assertRaises(ValueError):
            state.fill_cost_bps(self.ASKS, self.MID, "hold")

    def features(self, bids, asks):
        c, v = walk(W)
        return state.features(snapshot(c, v, bid=bids[0][0], bid_size=bids[0][1], ask=asks[0][0],
                                       ask_size=asks[0][1], bids=bids, asks=asks))

    def test_features_take_the_max_of_the_two_sides(self):
        f = self.features(self.BIDS, self.ASKS)                          # buy 6.10, sell 1.50
        self.assertAlmostEqual(f["mid"], self.MID)
        self.assertAlmostEqual(f["fill1k_bps"], state.fill_cost_bps(self.ASKS, self.MID, "buy"), places=12)
        self.assertIs(f["fill1k_short"], False)
        self.assertEqual(state.adjectives(f)["liq"], "thin")
        # the sides are independent: swap which one is expensive and the max follows it
        cheap_asks = [[100.01, 50.0]]                                     # buy 1.0
        f = self.features(self.BIDS, cheap_asks)                          # sell 1.50 is now the max
        self.assertAlmostEqual(f["fill1k_bps"], state.fill_cost_bps(self.BIDS, self.MID, "sell"), places=12)
        self.assertEqual(state.adjectives(f)["liq"], "normal")
        deep_bids = [[99.99, 50.0]]
        f = self.features(deep_bids, cheap_asks)                          # 1.0 both sides: ON the cut
        self.assertAlmostEqual(f["fill1k_bps"], 1.0, places=9)
        f = self.features([[99.995, 50.0]], [[100.005, 50.0]])            # 0.5 both sides
        self.assertEqual(state.adjectives(f)["liq"], "deep")

    def test_a_short_side_logs_null_and_the_flag_and_reads_thin(self):
        for bids, asks in (([[99.99, 1.0]], [[100.01, 50.0]]),            # bids hold $99.99: short
                           ([[99.99, 50.0]], [[100.01, 1.0]])):           # asks short
            f = self.features(bids, asks)
            self.assertIsNone(f["fill1k_bps"])                            # JSON has no inf
            self.assertIs(f["fill1k_short"], True)
            self.assertEqual(state.adjectives(f)["liq"], "thin")
            import json
            self.assertEqual(json.loads(json.dumps(f, allow_nan=False))["fill1k_bps"], None)
        # an arm-C buy needs liq != thin: pumping on a short book holds (CONTRACT §2, unchanged)
        adj = dict(state.adjectives(f), trend="pumping", vol="normal")
        self.assertEqual(state.rule_c(adj), "hold")
        self.assertEqual(state.rule_c(dict(adj, liq="normal")), "buy")

    def test_a_book_side_with_no_levels_is_refused(self):
        c, v = walk(W)
        for bids, asks in (([], [[100.01, 5.0]]), ([[99.99, 5.0]], [])):
            with self.assertRaises(ValueError):
                state.features(snapshot(c, v, bids=bids, asks=asks))


FORMAT = re.compile(r"^SOL: liquidity (thin|normal|deep), flow (quiet|organic|bot_war), "
                    r"trend (dumping|flat|pumping), vol (calm|normal|violent)$")


class StateString(unittest.TestCase):
    def test_exact_format_example(self):
        adj = {"liq": "deep", "flow": "bot_war", "trend": "pumping", "vol": "calm"}
        self.assertEqual(state.state_string(adj),
                         "SOL: liquidity deep, flow bot_war, trend pumping, vol calm")

    def test_the_base_is_the_first_word_and_nothing_else_moves(self):
        # PREREG-v2 §8: the product name is the first word of the state; the default is v1's SOL
        adj = {"liq": "deep", "flow": "bot_war", "trend": "pumping", "vol": "calm"}
        self.assertEqual(state.state_string(adj, "SOL"), state.state_string(adj))
        self.assertEqual(state.state_string(adj, "ETH"), "ETH: liquidity deep, flow bot_war, trend pumping, vol calm")
        for b in ("ETH", "DOGE", "XRP"):
            for a in state.all_states():
                s = state.state_string(a, b)
                self.assertEqual(s, b + state.state_string(a)[len("SOL"):])
        for bad in ("sol", "S0L", "", None, "SOL-USD", "SOL ", "ÉTH", "{BASE}"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                state.state_string(adj, bad)

    def test_all_81_match_format_and_carry_no_digit(self):
        seen = set()
        for adj in state.all_states():
            s = state.state_string(adj)
            self.assertRegex(s, FORMAT)
            self.assertFalse(any(ch.isdigit() for ch in s), s)
            seen.add(s)
        self.assertEqual(len(seen), 81)

    def test_rejects_words_outside_the_alphabet(self):
        for bad in ({"liq": "thick", "flow": "organic", "trend": "flat", "vol": "normal"},
                    {"liq": "thin", "flow": "organic", "trend": "flat"},
                    {"liq": "thin", "flow": "organic", "trend": "flat", "vol": "Normal"}):
            with self.assertRaises(ValueError):
                state.state_string(bad)


def contract_rule(a):
    """CONTRACT §2, the three lines, restated literally and independently of state.py."""
    if a["trend"] == "pumping" and a["vol"] != "violent" and a["liq"] != "thin":
        return "buy"
    if a["trend"] == "dumping" or a["vol"] == "violent":
        return "sell"
    return "hold"


class RuleC(unittest.TestCase):
    def test_all_states_is_81_distinct_in_fixed_order(self):
        states = state.all_states()
        self.assertEqual(len(states), 81)
        self.assertEqual(len({tuple(a[d] for d in state.DIMS) for a in states}), 81)
        self.assertEqual(states[0], {"liq": "thin", "flow": "quiet", "trend": "dumping", "vol": "calm"})
        self.assertEqual(states[-1], {"liq": "deep", "flow": "bot_war", "trend": "pumping", "vol": "violent"})
        self.assertEqual(states[1]["vol"], "normal")                 # vol is the fastest-varying dim

    def test_truth_table_against_the_three_lines(self):
        for a in state.all_states():
            self.assertEqual(state.rule_c(a), contract_rule(a), a)

    def test_truth_table_counts(self):
        # buy: pumping(1) × not violent(2) × not thin(2) × any flow(3) = 12
        # sell: dumping(27) + violent(27) − both(9) = 45;  hold: 81 − 12 − 45 = 24
        from collections import Counter
        n = Counter(state.rule_c(a) for a in state.all_states())
        self.assertEqual(n, Counter({"buy": 12, "sell": 45, "hold": 24}))

    def test_hand_picked_states(self):
        A = lambda l, f, t, v: {"liq": l, "flow": f, "trend": t, "vol": v}
        self.assertEqual(state.rule_c(A("normal", "organic", "pumping", "calm")), "buy")
        self.assertEqual(state.rule_c(A("deep", "bot_war", "pumping", "normal")), "buy")
        self.assertEqual(state.rule_c(A("thin", "organic", "pumping", "calm")), "hold")     # thin blocks buy
        self.assertEqual(state.rule_c(A("deep", "organic", "pumping", "violent")), "sell")  # violent wins
        self.assertEqual(state.rule_c(A("deep", "quiet", "dumping", "calm")), "sell")
        self.assertEqual(state.rule_c(A("normal", "organic", "flat", "violent")), "sell")
        self.assertEqual(state.rule_c(A("normal", "organic", "flat", "normal")), "hold")
        self.assertEqual(state.rule_c(A("thin", "quiet", "flat", "calm")), "hold")
        self.assertEqual(state.rule_c(A("thin", "bot_war", "dumping", "violent")), "sell")

    def test_flow_never_changes_the_rule(self):
        for a in state.all_states():
            for f in state.FLOW:
                b = dict(a, flow=f)
                self.assertEqual(state.rule_c(b), state.rule_c(a))

    def test_rejects_words_outside_the_alphabet(self):
        with self.assertRaises(ValueError):
            state.rule_c({"liq": "deep", "flow": "organic", "trend": "up", "vol": "calm"})


class ThresholdsComeFromConfig(unittest.TestCase):
    def test_no_comparison_against_a_literal_in_state_py(self):
        # The property SPEC.md relies on: every cut is a config name. Checked on the AST,
        # not the text: no `Compare` node in state.py may have a numeric literal as an
        # operand (arithmetic like `/ 2.0` is fine; `x < 0.5` would not be). The two
        # legitimate literal compares are the guards `sd > 0.0` and `rv_med > 0.0`.
        import ast, os
        with open(os.path.join(config.REPO, "loop", "state.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        literal_compares = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for operand in [node.left] + node.comparators:
                    if isinstance(operand, ast.Constant) and isinstance(operand.value, (int, float)):
                        literal_compares.append((node.lineno, operand.value))
        self.assertEqual(sorted(v for _, v in literal_compares), [0.0, 0.0], literal_compares)
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                 and isinstance(n.value, ast.Name) and n.value.id == "config"}
        for name in ("TICK_P", "liq_cuts", "base", "NOTIONAL_USD", "FLOW_P_LO", "FLOW_P_HI", "TREND_Z",
                     "VOL_RATIO_LO", "VOL_RATIO_HI", "WINDOW_MIN", "PRODUCT", "HORIZON_S", "CADENCE_S"):
            self.assertIn(name, names)
        for name in ("LIQ_THIN_BPS", "LIQ_DEEP_BPS"):             # v1's bps cuts: no v2 word reads them
            self.assertNotIn(name, names)


if __name__ == "__main__":
    unittest.main()

"""Seeded property tests on synthetic logs (tests/synth.py): the join, the blocks, the book, the health
readers and the inference, each held to what SPEC.md, PREREG.md and CONTRACT.md say in words, on logs
with holes, torn and glued lines, duplicate ticks, HALT stretches, absence-only and empty days, words
outside the alphabet, the old ~61 s launchd grid, ts_rx anywhere in its minute, and a promotion.

The references below (ref_join, ref_pnl, ref_h1, ref_h2) are written from the documents' words, not
from loop/: SPEC §11 for the join (the priced row whose ts_rx is nearest t + 900 s within +-30 s,
strictly after t, ties in whole milliseconds to the earlier row; when two rows share a tick_id the
live decision speaks for it, then any other priced row, then an unpriced one), SPEC §10 for the book,
PREREG §3-§5 for S_k, the H1 mean and the H2 units and r. A disagreement between a reference and the
code is reported, never "fixed" in the test: the code's behaviour is pinned and the sentence is
an erratum in HANDOFF.md (two below: PREREG §3's "forced holds contribute 0.0" and SPEC §10's
"exactly 0.0" sentence, each against the fold SPEC §10 itself prescribes).
Offline; temp files only; nothing is sent; the live prompts/, data/ and HALT are never read.
"""
import bisect, calendar, contextlib, datetime, io, math, os, random, re, subprocess, sys, tempfile, unittest
from fractions import Fraction
from unittest import mock

import synth
from fixture_prereg import pin_prereg
from fixture_products import add_products
from fixture_prompts import pin_v1
from loop import book, config, cycle, dash, inference, inference_v2, outcomes, report, rules, state, status
from test_dash import runtime_health_only

SEEDS = tuple(range(1, 13))                       # every cheap property runs on all twelve
LOAD_SEEDS = (2, 6, 9)                            # written as bytes and read back through outcomes.load
T0S = synth.KNOBS["t0"]                           # PREREG §11's T0, as the synthetic logs' T0
T0 = report.tick_epoch(T0S)
T0_MS = calendar.timegm(datetime.datetime.strptime(T0S, "%Y%m%dT%H%M%SZ").timetuple()) * 1000
NOW = datetime.datetime(2026, 9, 27, 12, 0, tzinfo=datetime.timezone.utc)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# the documents' numbers, as the documents write them (SPEC §1, §10, §11; PREREG §3)
H_MS, TOL_MS, BAND, NOTIONAL, BLOCK_MS, BLOCKS = 900_000, 30_000, 5.0, 1000.0, 900_000, 96 * 28


def knobs(seed):
    """Every oddity on (synth.STRESS), a 2-hour shakedown and one day after T0 (the log runs 20 minutes
    into d02, so d01 closes), varied by seed: a third fire at any point of their minute (the join's
    window, its edges and ties; two of them on a 500 ms grid, so exact ties happen), a quarter start on
    the old ~61 s grid, every other one ends in a torn line, and d01 is all HALT (3), empty (6) or all
    feed absences (9)."""
    k = dict(synth.STRESS, days=1.0, phase="wild" if seed % 3 == 1 else "calendar", quantum_ms=500 if seed % 6 == 1 else 1,
             interval_hours=3.0 if seed % 4 == 1 else 0.0, torn_tail=seed % 2 == 0, promotions_h=(5.0 + seed,))
    if seed in (3, 9):
        k.update(absence_days=(1,), absence_day_kind="halt" if seed == 3 else "feed")
    if seed == 6:
        k.update(empty_days=(1,))
    return k


_TMP = None                                       # the module's temp dir, made in setUpModule
_LOGS, _FILES, _JOINS = {}, {}, {}


def setUpModule():
    # made here, not at import: a runner that interleaves modules (a shuffled order) tears this module
    # down and sets it up again, and the second round must find its directory and its files
    global _TMP
    _TMP = tempfile.TemporaryDirectory()


def tearDownModule():
    _TMP.cleanup()
    _FILES.clear()                                # their paths were in the directory just removed


def case(seed):
    """The seed's Log (no bytes but for LOAD_SEEDS); its rows are what outcomes.load returns (Load checks it)."""
    if seed not in _LOGS:
        _LOGS[seed] = on_disk(seed)[0] if seed in LOAD_SEEDS else synth.generate(seed, encode=False, **knobs(seed))
    return _LOGS[seed]


def on_disk(seed):
    """(log, path, rows read back by outcomes.load, its skipped lines) for a seed written as bytes."""
    if seed not in _FILES:
        log = synth.generate(seed, **knobs(seed))
        path = synth.write(os.path.join(_TMP.name, f"seed{seed}.jsonl"), log)
        bad = []
        _FILES[seed] = (log, path, outcomes.load(path, bad), bad)
    return _FILES[seed]


def joins(seed):
    """(outcomes.join, ref_join's outcomes, ref_join's joined rows) of a seed's rows, once."""
    if seed not in _JOINS:
        rows = case(seed).rows
        _JOINS[seed] = (outcomes.join(rows),) + ref_join(rows)
    return _JOINS[seed]


# ---- the references, from the documents' words -----------------------------------------------------
_TS = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d{3})Z$")


def ms_of(ts):
    """ts_rx (ISO 8601 UTC, milliseconds, Z: SPEC §2) -> epoch milliseconds, read off the characters."""
    y, mo, d, h, mi, s, frac = map(int, _TS.match(ts).groups())
    return calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0)) * 1000 + frac


def tick_ms(tid):
    return calendar.timegm((int(tid[:4]), int(tid[4:6]), int(tid[6:8]), int(tid[9:11]), int(tid[11:13]), 0, 0, 0, 0)) * 1000


def has_mid(r):
    return r.get("mid") is not None


def decision(r):
    """The live decision of its minute: mode live, absence null (SPEC §2; PREREG §5's 'live row')."""
    return r.get("mode") == "live" and r.get("absence") is None


def speakers(rows):
    """tick_id -> index of the row that speaks for it: the live decision, then any other priced row, then
    an unpriced one; among rows of one rank the first written."""
    best = {}
    for i, r in enumerate(rows):
        rank = 0 if decision(r) and has_mid(r) else 1 if has_mid(r) else 2
        if r["tick_id"] not in best or rank < best[r["tick_id"]][0]:
            best[r["tick_id"]] = (rank, i)
    return {t: i for t, (_, i) in best.items()}


GAP = {"mid_h": None, "ret_h_bps": None, "label": None, "absence": "gap"}


def ref_join(rows):
    """SPEC §11: ({tick_id: outcome}, {tick_id: (joined row's ts ms, its index, realised horizon ms)})."""
    cands = sorted((ms_of(r["ts_rx"]), i) for i, r in enumerate(rows) if has_mid(r))
    keys = [c[0] for c in cands]
    out, joined = {}, {}
    for tid, i in speakers(rows).items():
        r = rows[i]
        out[tid] = dict(GAP)
        if not has_mid(r):
            continue
        t = ms_of(r["ts_rx"])
        target = t + H_MS
        lo, hi = bisect.bisect_left(keys, target - TOL_MS), bisect.bisect_right(keys, target + TOL_MS)
        window = [(abs(ms - target), ms, j) for ms, j in cands[lo:hi] if ms > t]    # both edges in, strictly after t
        if not window:
            continue
        _, ms, j = min(window)                           # nearest; a tie to the earlier ts_rx, then the first written
        ret = 1e4 * math.log(rows[j]["mid"] / r["mid"])
        out[tid] = {"mid_h": rows[j]["mid"], "ret_h_bps": ret,
                    "label": "up" if ret >= BAND else "down" if ret <= -BAND else "flat", "absence": None}
        joined[tid] = (ms, j, ms - t)
    return out, joined


def priced(r):
    return all(isinstance(r.get(f), float) and r[f] > 0 for f in ("bid", "ask", "mid"))


def forced(r):
    """SPEC §10: absence set, not live, null columns, or an unpriced book: a hold for every arm, C included."""
    cols = r.get("columns") or {}
    return r.get("absence") is not None or r.get("mode") != "live" or (cols.get("a") is None and cols.get("b") is None) or not priced(r)


def ref_pnl(rows, arm, column="argmax", fee=0.0):
    """SPEC §10, from its words: rows in tick_id order (ts_rx within a minute); one paper order of NOTIONAL;
    a buy when flat opens qty = N / ask at the ask with fee N * fee / 1e4, a sell when long closes at the
    bid with fee qty * bid * fee / 1e4, anything else holds; every priced row marks to its mid; pnl per
    row DIRECTLY in bps of N; a forced row holds for every arm and marks when it has a mid; two rows of
    one minute fold. Returns ({tick_id: bps}, {tick_id: qty after}, [(tick_id, side, price)])."""
    qty, last, pnl, pos, trades = 0.0, None, {}, {}, []
    for r in sorted(rows, key=lambda r: (r["tick_id"], ms_of(r["ts_rx"]))):
        tid, usd = r["tick_id"], 0.0
        if priced(r):
            bid, ask, mid = r["bid"], r["ask"], r["mid"]
            intent = "hold" if forced(r) else r["rule_c"] if arm == "c" else r["columns"][arm][column]
            if intent == "buy" and qty == 0.0:
                qty = NOTIONAL / ask
                usd = qty * (mid - ask) - NOTIONAL * fee / 1e4
                trades.append((tid, "buy", ask))
            elif intent == "sell" and qty > 0.0:
                usd = qty * (bid - last) - qty * bid * fee / 1e4
                qty = 0.0
                trades.append((tid, "sell", bid))
            elif qty:
                usd = qty * (mid - last)
            last = mid
        pnl[tid] = pnl.get(tid, 0.0) + usd * 1e4 / NOTIONAL
        pos[tid] = qty
    return pnl, pos, trades


def sample_of(rows):
    """PREREG §2: T0 <= tick_id < T0 + 28 days."""
    return [r for r in rows if T0_MS <= tick_ms(r["tick_id"]) < T0_MS + 28 * 86_400_000]


def ref_h1(sample, x, y, t0=None):
    """PREREG §3-§4: S_k = sum of d_t = pnl_x - pnl_y over the ticks with T0 + 900k <= tick_id < T0 + 900(k+1),
    k = 0 .. 2687, an empty block 0 and kept; the statistic is the mean of the 2688."""
    px, py = ref_pnl(sample, x)[0], ref_pnl(sample, y)[0]
    t0_ms = T0_MS if t0 is None else int(t0) * 1000
    S = [0.0] * BLOCKS
    for t in px:
        S[(tick_ms(t) - t0_ms) // BLOCK_MS] += px[t] - py[t]
    return sum(S) / BLOCKS


def ref_pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    return sxy / math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))


def ref_h2(sample, outs, t0=None):
    """PREREG §5: the first live row of each block (by tick_id time from T0; the first written within a
    minute), x = round(up15 - down15, 12), y = its ret_h_bps; a gap or a missing noul drops the block."""
    first, t0_ms = {}, T0_MS if t0 is None else int(t0) * 1000
    for r in sorted((r for r in sample if decision(r)), key=lambda r: r["tick_id"]):
        first.setdefault((tick_ms(r["tick_id"]) - t0_ms) // BLOCK_MS, r)
    units = []
    for k in sorted(first):
        r = first[k]
        up, down = (r["answers"] or {}).get("up15", {}).get("noul"), (r["answers"] or {}).get("down15", {}).get("noul")
        o = outs[r["tick_id"]]
        number = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
        if number(up) and number(down) and o["absence"] is None:
            units.append((k, round(up - down, 12), o["ret_h_bps"]))
    return units, ref_pearson([u[1] for u in units], [u[2] for u in units]) if len(units) > 1 else None


# ---- the generator itself -----------------------------------------------------------------------------
class Generator(unittest.TestCase):
    def test_rows_have_the_writers_shape(self):
        # a v1-era row (the default) is what v1's loop wrote: the v2 writer's shape less table_sha and columns.d;
        # a v2-era row is the v2 writer's whole shape (PREREG-v2 §10), on every product
        full = cycle.new_row("2026-09-25T21:40:00.100Z", "live")
        jev = list(full["jev"])
        eras = {"v1": ([k for k in full if k != "table_sha"], ["a", "b"]), "v2": (list(full), list(full["columns"]))}
        self.assertEqual(eras["v2"][1], ["a", "b", "d"])
        logs = [("v1", config.PRODUCT, case(seed).rows) for seed in (1, 5)]
        products = add_products(self)
        for p, log in synth.generate_products(4, products, encode=False, **dict(knobs(4), days=0.3, era="v2")).items():
            logs.append(("v2", p, log.rows))
        for era, p, rows in logs:
            keys, cols = eras[era]
            for r in rows:
                self.assertEqual(list(r), keys, (era, p))                            # every key, in cycle.new_row's order
                self.assertEqual(list(r["jev"]), jev)
                self.assertEqual(list(r["columns"]), cols, (era, p))
                self.assertEqual(r["tick_id"], cycle.tick_id(r["ts_rx"]))
                self.assertEqual(r["product"], p)
                if r["answers"] is not None and r["absence"] is None:
                    self.assertEqual({a: r["columns"][a] for a in "ab"},
                                     {"a": rules.for_arm(r["answers"], "a"), "b": rules.for_arm(r["answers"], "b")})
                if isinstance(r["adj"], dict) and all(r["adj"][d] in state.ALPHABET[d] for d in state.DIMS):
                    self.assertEqual((r["state"], r["rule_c"]),
                                     (state.state_string(r["adj"], config.base(p)), state.rule_c(r["adj"])))
                    self.assertEqual(r["adj"], state.adjectives(r["features"], p))

    def test_v2_era_rows_carry_the_frozen_a_the_table_and_its_answer(self):
        # PREREG-v2 §1/§10: A asks the frozen v2 wording; CURRENT is v2 at T0 and moves at each promotion; table_sha
        # is set at the prompts step (so a HALT row carries it) and columns.d is the version's table answer for the
        # state: one answer per (version, state), whatever B's live answer was
        products = add_products(self)
        logs = synth.generate_products(7, products, encode=False,
                                       **dict(knobs(7), days=0.5, era="v2", promotions_h=(3.0,), no_table=("v3",), p_d_null=0.05))
        for p, log in logs.items():
            table, versions, nulls = {}, set(), 0
            for r in log.rows:
                self.assertEqual(r["spec_sha"], synth._spec_sha())                   # the v2 tree's SPEC (v1 rows: prereg-v1's)
                if r["prompt_a"] is None:
                    continue
                self.assertEqual((r["prompt_a"], r["prompt_a_sha"]), ("v2", synth.prompt_sha("v2")))
                versions.add(r["prompt_b"])
                if r["prompt_b"] == "v3":
                    self.assertIsNone(r["table_sha"])
                    self.assertIsNone(r["columns"]["d"])
                if r["absence"] is None and r["mode"] == "live" and r["answers"] is not None:
                    d = r["columns"]["d"]
                    if d is None:
                        nulls += r["prompt_b"] != "v3"
                        continue
                    self.assertEqual(r["table_sha"], synth.table_sha(r["prompt_b"], p))
                    self.assertIn(d, ("buy", "sell", "hold"))
                    self.assertEqual(table.setdefault((r["prompt_b"], r["state"]), d), d)
            self.assertEqual(versions, {"v2", "v3"}, p)
            self.assertGreater(nulls, 0, p)                                           # p_d_null: a failed table read
        self.assertTrue(all(r["prompt_a"] == "v1" and r["spec_sha"] == dash.V1_SPEC_SHA
                            for r in case(1).rows if r["prompt_a"] is not None))

    def test_products_share_one_tick_grid_and_sol_is_the_one_product_log(self):
        products = add_products(self)
        kn = dict(knobs(2), days=0.4, torn_tail=False)
        logs = synth.generate_products(2, products, **kn)
        self.assertEqual(logs[config.PRODUCT].data, synth.generate(2, **kn).data)    # SOL byte for byte
        grids = {p: {r["tick_id"] for r in log.rows} for p, log in logs.items()}
        union = set().union(*grids.values())
        for p, g in grids.items():
            self.assertGreater(len(g), 0.9 * len(union), p)                           # isolated skips differ, holes do not
            rows = [r for r in logs[p].rows if isinstance(r.get("state"), str) and r["absence"] != "guard"]
            self.assertTrue(all(r["state"].startswith(config.base(p) + ": ") for r in rows), p)
            tick = config.TICK_P[p]
            for r in rows[:200]:
                self.assertAlmostEqual(r["bid"] / tick, round(r["bid"] / tick), places=6, msg=p)   # the book on its grid
        mids = {p: next(r["mid"] for r in log.rows if r["mid"]) for p, log in logs.items()}
        self.assertEqual(len(set(mids.values())), len(products))
        # a per-product knob moves that product alone; a grid knob there is refused
        one = synth.generate_products(2, products, per_product={products[1]: {"empty_days": (1,)}}, **dict(kn, days=1.2))
        d01 = lambda rows: [r for r in rows if 0 <= report.tick_epoch(r["tick_id"]) - T0 < 86400]
        self.assertEqual(d01(one[products[1]].rows), [])
        self.assertTrue(d01(one[config.PRODUCT].rows))
        with self.assertRaises(ValueError):
            synth.generate_products(2, products, per_product={products[1]: {"holes_per_day": 9.0}}, **kn)

    def test_the_cadence_knob(self):
        log = synth.generate(3, days=1.0, cadence_s=900, pre_hours=2.0, promotions_h=())
        self.assertTrue(log.rows)
        for r in log.rows:
            self.assertEqual((report.tick_epoch(r["tick_id"]) - T0) % 900, 0)
            self.assertEqual(r["cadence_s"], 900)
        self.assertLess(len(log.rows), 1.2 * (26 * 4))
        for bad in (0, 90, 7200 * 7, 61, True):
            with self.assertRaises(ValueError, msg=bad):
                synth.generate(3, days=0.1, cadence_s=bad)
        with self.assertRaises(ValueError):
            synth.generate(3, days=0.1, cadence_s=900, interval_hours=1.0)

    def test_write_products_puts_each_log_where_config_store_does(self):
        products = add_products(self)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "DATA", d), \
                mock.patch.object(config, "DECISIONS", os.path.join(d, "decisions.jsonl")):
            paths = synth.write_products(d, synth.generate_products(3, products, days=0.05, pre_hours=0.5))
            for p in products:
                self.assertEqual(paths[p], config.store(p).decisions)
                self.assertTrue(outcomes.load(paths[p], []))

    def test_the_same_seed_gives_the_same_bytes(self):
        a = synth.generate(4, **dict(knobs(4), days=0.1))
        self.assertEqual(synth.generate(4, **dict(knobs(4), days=0.1)).data, a.data)
        self.assertEqual(synth.generate(4, encode=False, **dict(knobs(4), days=0.1)).rows, a.rows)
        self.assertNotEqual(synth.generate(5, **dict(knobs(4), days=0.1)).data, a.data)
        with self.assertRaises(TypeError):
            synth.generate(1, no_such_knob=1)

    def test_every_oddity_the_knobs_name_is_in_the_stress_logs(self):
        seen = {"lock_dup": 0, "dry_dup": 0, "live_dup": 0, "torn": 0, "glued": 0, "tail": 0, "foreign": 0}
        versions, kinds = set(), set()
        for seed in SEEDS:
            log = case(seed)
            for k in seen:
                seen[k] += log.events[k]
            versions |= {r["prompt_b"] for r in log.rows}
            kinds |= set(log.events["absence"])
        self.assertTrue(all(seen.values()), seen)
        self.assertEqual(kinds, {"feed", "jev", "halt", "lock", "guard"})
        self.assertLessEqual({None, "v1", "v2"}, versions)


# ---- (g) the reader on the bytes the loop leaves ---------------------------------------------------
class Load(unittest.TestCase):
    def test_load_keeps_glued_rows_and_skips_torn_ones(self):
        self.assertTrue(all(on_disk(s)[0].glued for s in LOAD_SEEDS if s != 6))     # seed 6's d01 is empty: few rows to tear
        for seed in LOAD_SEEDS:
            log, path, rows, bad = on_disk(seed)
            with self.subTest(seed=seed):
                self.assertEqual(rows, log.rows)                                  # every whole row, the glued ones too
                self.assertEqual(rows, case(seed).rows)                           # what every other test here reads
                self.assertEqual(len(bad), log.bad)                               # one skipped line per torn row
                self.assertEqual(log.bad, log.events["torn"] + log.events["glued"] + log.events["tail"])
                kept = [why for _, why in bad if "the whole row appended onto the torn line is kept" in why]
                self.assertEqual(len(kept), len(log.glued))
                self.assertLessEqual(set(log.glued), {r["tick_id"] for r in rows})
                if log.knobs["torn_tail"]:
                    self.assertFalse(log.data.endswith(b"\n"))
                    self.assertEqual(bad[-1][0], log.data.count(b"\n") + 1)       # the last line, and it is a skip

    def test_a_log_of_one_torn_line_is_no_rows_and_one_skip(self):
        p = os.path.join(_TMP.name, "torn-only.jsonl")
        with open(p, "wb") as fh:
            fh.write(on_disk(2)[0].data[:700])
        bad = []
        self.assertEqual((outcomes.load(p, bad), len(bad)), ([], 1))


# ---- (a), (b) the outcome join ----------------------------------------------------------------------------
class Join(unittest.TestCase):
    def test_constants_are_the_documents(self):
        self.assertEqual((config.HORIZON_S * 1000, outcomes.JOIN_TOL_S * 1000, outcomes.DEAD_BAND_BPS), (H_MS, TOL_MS, BAND))

    def test_join_is_spec_11_row_for_row(self):
        """(a) outcome, joined row and realised horizon, tick for tick, against ref_join."""
        for seed in SEEDS:
            rows = case(seed).rows
            got, want, joined = joins(seed)
            with self.subTest(seed=seed):
                self.assertEqual(set(got), set(want))
                diff = [t for t in want if got[t] != want[t]]
                self.assertEqual(diff, [], [(t, got[t], want[t]) for t in diff[:3]])
                times, mids = outcomes.priced_points(rows)                       # the row outcomes.pick takes: the one
                sp = speakers(rows)                                              # rule report.realised_horizon uses too
                for tid, (ms, j, _) in joined.items():
                    k = outcomes.pick(times, outcomes.ts_epoch(rows[sp[tid]]["ts_rx"]))
                    self.assertIsNotNone(k, tid)
                    self.assertEqual((round(times[k] * 1000), mids[k]), (ms, rows[j]["mid"]), tid)
                hz, offs = report.realised_horizon(rows), [x[2] - H_MS for x in joined.values()]
                self.assertEqual(hz["n"], len(offs))
                if offs:
                    self.assertAlmostEqual(hz["mean"], 900 + sum(offs) / len(offs) / 1000, places=6)
                    self.assertAlmostEqual(hz["max"], max(abs(o) for o in offs) / 1000, places=6)

    def test_one_outcome_per_tick_within_870_to_930_s_and_an_empty_window_is_a_gap(self):
        """(b), each read off the rows directly rather than off either join."""
        for seed in SEEDS:
            rows = case(seed).rows
            got, _, joined = joins(seed)
            with self.subTest(seed=seed):
                self.assertEqual(len(got), len({r["tick_id"] for r in rows}))      # one outcome per minute, duplicates folded
                tms = sorted(ms_of(r["ts_rx"]) for r in rows if has_mid(r))
                for tid, i in speakers(rows).items():
                    r = rows[i]
                    if not has_mid(r):
                        self.assertEqual(got[tid], GAP)
                        continue
                    t = ms_of(r["ts_rx"])
                    empty = bisect.bisect_right(tms, t + H_MS + TOL_MS) == bisect.bisect_left(tms, t + H_MS - TOL_MS)
                    self.assertEqual(got[tid] == GAP, empty, tid)
                self.assertTrue(all(H_MS - TOL_MS <= x[2] <= H_MS + TOL_MS for x in joined.values()))
                self.assertLessEqual(report.realised_horizon(rows)["max"] or 0.0, 30.0)

    def test_a_duplicate_tick_is_spoken_for_by_its_live_decision(self):
        # a lock row, a `make dry` 15-45 s into the minute, a second --once: the tick's outcome is the one
        # its (first) live decision gets, from its own ts_rx and mid, never the twin's shifted window
        dup = 0
        for seed in SEEDS:
            rows = case(seed).rows
            got = joins(seed)[0]
            times, mids = outcomes.priced_points(rows)
            by = {}
            for r in rows:
                by.setdefault(r["tick_id"], []).append(r)
            for tid, rs in by.items():
                live = [r for r in rs if decision(r) and has_mid(r)]
                if len(rs) < 2 or not live:
                    continue
                dup += 1
                j = outcomes.pick(times, outcomes.ts_epoch(live[0]["ts_rx"]))
                want = dict(GAP) if j is None else outcomes.outcome(live[0]["mid"], mids[j])
                self.assertEqual(got[tid], want, (seed, tid))
        self.assertGreater(dup, 20)


# ---- (c) PREREG §3's blocks -------------------------------------------------------------------------------
class Blocks(unittest.TestCase):
    def test_blocks_partition_the_sample_from_t0(self):
        for seed in SEEDS:
            rows = case(seed).rows
            with self.subTest(seed=seed):
                ticks = sorted({r["tick_id"] for r in rows})
                inside = [t for t in ticks if T0_MS <= tick_ms(t) < T0_MS + 28 * 86_400_000]
                d = [(t, float(i + 1)) for i, t in enumerate(ticks)]            # distinct integers: every sum is exact
                b = report._blocks(d, set(), T0, None, BLOCKS)
                self.assertEqual((b["n"], b["pre"]), (BLOCKS, len(ticks) - len(inside)))   # a pre-T0 tick is in no block
                self.assertEqual([k for k, _ in b["S"]], list(range(BLOCKS)))    # in order, none skipped, none twice
                want = [0.0] * BLOCKS
                for t, v in d:
                    k = (tick_ms(t) - T0_MS) // BLOCK_MS
                    if 0 <= k < BLOCKS:
                        want[k] += v
                self.assertEqual([v for _, v in b["S"]], want)
                ones = report._blocks([(t, 1.0) for t in inside], set(), T0, None, BLOCKS)["S"]
                self.assertTrue(all(v <= 15 for _, v in ones))                   # a block is 900 s: 15 minutes at most
                self.assertEqual(sum(v for _, v in ones), len(inside))          # each sample minute in exactly one block
                per_day = {}
                for k, _ in ones:
                    per_day[k // 96] = per_day.get(k // 96, 0) + 1
                self.assertEqual((len(per_day), set(per_day.values())), (28, {96}))
                if inside:                                                       # no count given: to the last tick's block
                    n = report._blocks([(t, 1.0) for t in inside], set(), T0)["n"]
                    self.assertEqual(n, (tick_ms(inside[-1]) - T0_MS) // BLOCK_MS + 1)
                    self.assertLessEqual(n, 96 + 2)                              # one day and 20 minutes

    # FINDING (PREREG §3's gloss against SPEC §10 and PREREG §3's own definition): §3 defines S_k as the sum
    # of book.paired's d_t over the block's rows, then says "Forced holds contribute 0.0; a block with no
    # live row has S_k = 0 and is kept (the arms agree on nothing)". SPEC §10 has a forced row carry the
    # position and mark it to the row's mid, so where the arms hold different positions a forced row's d_t
    # is the mark, and a block of HALT (or jev, guard, dry) rows has S_k = the arms' difference in marks.
    # FORCED_MARK: B buys at 21:40 (C holds); the block 21:55-22:09 holds one HALT row, mid 100 -> 101:
    # d_t there, and S_1, are +99.995 bps, not 0. book.py and loop.inference follow SPEC §10 (and §3's
    # definition), so the H1 statistic counts those marks. Seen in the seeds: seed 5, block 22 (HALT rows
    # only, S_22 = -0.3068 bps) and 68 forced-only ticks with d_t != 0; seed 12, block 59; on the 28-day
    # benchmark (synth.py --days 28 --seed 1), 58 of the 72 blocks holding rows but no live row have
    # S_k != 0, -139.84 bps in all: mean S_k(B - C) -0.7772 bps as coded, -0.7252 if the gloss held.
    def forced_mark(self):
        rows = [_live(0, 0.1, "buy", "hold"), _halt(15, 101.0), _live(30, 0.1, "hold", "hold", 101.0)]
        d = dict(book.paired(rows, None, "b", "c", "argmax", 0.0))
        return d, report._blocks(sorted(d.items()), set(), T0, None, 3)["S"]

    def test_a_forced_row_carries_and_marks_the_positions_as_spec_10_says(self):
        d, S = self.forced_mark()
        mark = 1e4 * (NOTIONAL / 100.005) * (101.0 - 100.0) / NOTIONAL
        self.assertAlmostEqual(d["20260925T215500Z"], mark, places=9)
        self.assertAlmostEqual(S[1][1], mark, places=9)



# ---- (d) the health readers never raise ------------------------------------------------------------------
def _edge_logs():
    """name -> (rows, bad, path): the logs a reader must survive besides the seeds'."""
    out = {}

    def put(name, data):
        p = os.path.join(_TMP.name, f"edge-{name}.jsonl")
        with open(p, "wb") as fh:
            fh.write(data)
        bad = []
        out[name] = (outcomes.load(p, bad), bad, p)
    put("empty", b"")
    put("before-t0", synth.generate(4, **dict(synth.STRESS, days=0.0, post_minutes=0, pre_hours=3.0)).data)
    one = on_disk(2)[0].data
    put("one-row", one[:one.index(b"\n") + 1])
    put("torn-only", one[:500])
    return out


class Readers(unittest.TestCase):
    """report §1-§3, status and the dash on the seeds' logs and on an empty log, a log wholly before T0,
    one row and one torn line: never an exception, the right days, and OUTSIDE-ALPHABET counted."""

    @classmethod
    def setUpClass(cls):
        pin_prereg(cls)                                             # report.main reads PREREG §11 for its withholding
        cls.edges = _edge_logs()
        cls.halt = os.path.join(_TMP.name, "no-HALT")               # never the repo's data/HALT
        cls.props = os.path.join(_TMP.name, "no-proposals")
        cls.plog = os.path.join(_TMP.name, "no-propose.log")

    def logs(self):
        for seed in (2, 9):
            _, path, rows, bad = on_disk(seed)
            yield f"seed {seed}", rows, bad, path
        for name, (rows, bad, path) in self.edges.items():
            yield name, rows, bad, path

    def test_report_health_and_days_on_every_seed(self):
        with mock.patch.object(config, "HALT", self.halt):
            for seed in SEEDS[::2] + (6,):                                       # 3, 6 and 9: HALT, empty, feed-only d01
                rows = case(seed).rows
                with self.subTest(seed=seed):
                    self.check_health(rows, [], joins(seed)[0])

    def check_health(self, rows, bad, outs):
        last = max((report.tick_epoch(r["tick_id"]) for r in rows), default=None)
        cut = report.in_sample(rows, T0)
        h = report.health(cut, outs, bad, T0, last)
        n = min(28, math.floor((last - T0) / 86400) + 1) if last is not None and last >= T0 else 0
        self.assertEqual([d["day"] for d in h["days"]], [f"d{j:02d}" for j in range(1, n + 1)])
        self.assertEqual(report.days_table(cut, outs, T0, last)["days"], h["days"])
        closed_empty = [d["day"] for d in h["days"] if not d["open"] and not any(decision(r) for r in cut if report.day_of(r["tick_id"], T0) == d["day"])]
        self.assertEqual(h["empty_days"], closed_empty)                            # NO LIVE ROWS: closed, no live decision
        for x in h["days"]:                                                        # PREREG §8.3 on every closed day, from its words:
            if x["open"]:                                                          # fill = live rows with a non-gap outcome over live
                continue                                                           # rows; jev share = absence jev over rows that
            a = T0_MS + (int(x["day"][1:]) - 1) * 86_400_000                       # reached the ask; BAD: fill < 95 % or share > 5 %
            day = [r for r in cut if a <= tick_ms(r["tick_id"]) < a + 86_400_000]
            live = [r for r in day if decision(r)]
            filled = sum(1 for r in live if outs[r["tick_id"]]["absence"] is None)
            asked = [r for r in day if r["mode"] == "live" and r["absence"] in (None, "jev")]
            errs = sum(1 for r in asked if r["absence"] == "jev")
            bad = (bool(live) and filled / len(live) < 0.95) or (bool(asked) and errs / len(asked) > 0.05)
            self.assertEqual((x["live"], x["filled"], x["pending"], x["attempted"], x["errors"], x["bad"]),
                             (len(live), filled, 0, len(asked), errs, bad), x["day"])
        self.assertEqual([d["day"] for d in report.days_table(rows, outs)["days"]], sorted({r["tick_id"][:8] for r in rows}))
        occ = report.occupancy(cut)
        for dim in state.DIMS:
            other = sum(1 for r in cut if isinstance(r.get("adj"), dict) and r["adj"].get(dim) not in state.ALPHABET[dim])
            line = next(l for l in occ["lines"] if l.startswith(f"  {dim:<5} "))
            self.assertEqual(f"OUTSIDE-ALPHABET {other}" in line, bool(other), line)
        return last, cut

    def test_report_render_and_main_never_raise(self):
        with mock.patch.object(config, "HALT", self.halt):
            for name, rows, bad, path in self.logs():
                with self.subTest(log=name):
                    outs = outcomes.join(rows)
                    last, cut = self.check_health(rows, bad, outs)
                    text = report.render(cut, bad, path, t0=T0, outs=outs, health_only=True, last=last)
                    self.assertFalse(any(t in text for t in report.TITLES[3:]))
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        self.assertEqual(report.main(["--log", path, "--health", "--t0", T0S]), 0)
                    self.assertEqual(buf.getvalue(), text)                             # main is render on the same cut
                    if not name.startswith("seed"):                                  # the seeds' calendar days: check_health
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(report.main(["--log", path, "--health"]), 0)

    def test_status_and_dash_render_health_only_on_every_log(self):
        pin_v1(self)
        for name, rows, bad, path in self.logs():
            with self.subTest(log=name):
                outs = outcomes.join(rows)
                for t0 in (T0, None) if name in ("seed 9", "empty") else (T0,):
                    screen = runtime_health_only(self, lambda: status.render(rows, outs, t0, NOW, "2026-09-27T11:59:00.100Z", self.halt,
                                                                               path, self.props, self.plog, "v1"))
                    self.assertIn("health only", screen)
                    page = runtime_health_only(self, lambda: dash.render(rows, outs, t0=t0, now=NOW, hb=None, props=(), current="v1", log=path))
                    self.assertTrue(page.endswith("</main></body></html>"))
                    cut = report.in_sample(rows, T0) if t0 is not None else rows
                    if t0 is not None:
                        self.assertEqual(page.count("<div class='d "), 28)
                        n = len(report.days_table(cut, outs, T0, max((report.tick_epoch(r["tick_id"]) for r in rows), default=None))["days"])
                        self.assertIn(f" of {n}; BAD days so far" if rows else "per day: no rows", screen)
                    foreign = any(isinstance(r.get("adj"), dict) and any(r["adj"].get(d) not in state.ALPHABET[d] for d in state.DIMS) for r in cut)
                    self.assertEqual("<span class='badge crit'>OUTSIDE-ALPHABET</span>" in page, foreign)
                if name in ("seed 2", "empty"):
                    out, data = os.path.join(_TMP.name, "dash", f"{name}.html"), os.path.join(_TMP.name, "dash-data")
                    os.makedirs(data, exist_ok=True)
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(dash.main(["--log", path, "--out", out, "--t0", T0S, "--data", data, "--proposals", self.props]), 0)
                    with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(config, "HALT", self.halt), \
                            mock.patch.object(config, "DATA", data), mock.patch.object(dash, "heartbeat", return_value=None):
                        self.assertEqual(status.main(["--log", path, "--t0", T0S, "--now", "2026-09-27T12:00"]), 0)


# ---- (e) SPEC §10's book ----------------------------------------------------------------------------------
class Book(unittest.TestCase):
    SEEDS = (2, 7)

    def test_replay_is_spec_10_tick_for_tick(self):
        for seed in self.SEEDS:
            rows = case(seed).rows
            for arm, col, fee in (("a", "argmax", 0.0), ("b", "argmax", 0.0), ("c", "argmax", 0.0), ("b", "c85v", 120.0)):
                with self.subTest(seed=seed, arm=arm, col=col, fee=fee):
                    got = book.replay(rows, None, arm, col, fee)
                    pnl, pos, trades = ref_pnl(rows, arm, col, fee)
                    self.assertEqual(set(got["pnl_bps_per_tick"]), set(pnl))
                    self.assertLess(max((abs(got["pnl_bps_per_tick"][t] - pnl[t]) for t in pnl), default=0.0), 1e-9)
                    self.assertEqual(got["position"], pos)
                    self.assertEqual([(t["tick_id"], t["side"], t["price"]) for t in got["trades"]], trades)

    def test_a_days_ledger_is_the_sum_of_its_rows_and_forced_rows_hold_every_arm(self):
        for seed in self.SEEDS:
            rows = case(seed).rows
            n_forced = sum(1 for r in rows if forced(r))
            decided = {r["tick_id"] for r in rows if not forced(r)}
            for arm in ("a", "b", "c"):
                with self.subTest(seed=seed, arm=arm):
                    rp = book.replay(rows, None, arm, "argmax", 0.0)
                    self.assertEqual(rp["forced_hold"], n_forced)                   # the same rows for A, B and C
                    self.assertLessEqual({t["tick_id"] for t in rp["trades"]}, decided)   # C never trades on a forced row
                    eq, days = dict(rp["equity"]), {}
                    for t, v in rp["pnl_bps_per_tick"].items():
                        days.setdefault(report.day_of(t, T0), []).append((t, v))
                    prev = 0.0
                    for d in sorted(days, key=report._day_key):
                        last_tick = max(t for t, _ in days[d])
                        self.assertAlmostEqual(eq[last_tick] - prev, math.fsum(v for _, v in days[d]), places=9)
                        prev = eq[last_tick]

    def test_a_fee_never_changes_a_decision(self):
        for seed in self.SEEDS:
            rows = case(seed).rows
            for arm in ("b", "c"):
                with self.subTest(seed=seed, arm=arm):
                    g, v = book.replay(rows, None, arm, "argmax", 0.0), book.replay(rows, None, arm, "argmax", config.FEE_BPS_VENUE)
                    self.assertEqual([(t["tick_id"], t["side"], t["price"], t["qty"]) for t in g["trades"]],
                                     [(t["tick_id"], t["side"], t["price"], t["qty"]) for t in v["trades"]])
                    fees = math.fsum(t["fee"] for t in v["trades"]) * 1e4 / NOTIONAL
                    self.assertAlmostEqual(v["equity"][-1][1], g["equity"][-1][1] - fees, places=6)

    def test_d_t_is_exactly_zero_where_both_arms_carry_one_qty_through_a_one_decision_minute(self):
        checked = 0
        for seed in self.SEEDS:
            rows = case(seed).rows
            decisions = {}
            for r in rows:
                decisions[r["tick_id"]] = decisions.get(r["tick_id"], 0) + (not forced(r))
            for x, y in (("b", "c"), ("a", "c")):
                px, py = book.replay(rows, None, x, "argmax", 0.0), book.replay(rows, None, y, "argmax", 0.0)
                d = dict(book.paired(rows, None, x, y, "argmax", 0.0))
                prev = (0.0, 0.0)
                for t, _ in px["equity"]:
                    now = (px["position"][t], py["position"][t])
                    if prev[0] == prev[1] and now[0] == now[1] and decisions[t] <= 1:
                        self.assertEqual(d[t], 0.0, (seed, x, y, t))                 # exactly, not almost
                        checked += 1
                    prev = now
        self.assertGreater(checked, 1000)

    # FINDING (SPEC §10 against itself; no seed needed): "d_t ... exactly 0.0 on any tick both arms carry
    # the same position (the same qty) into and out of" cannot hold together with "two rows with one tick_id
    # fold (+=)" when both rows are live decisions (a manual --once, or a RunAtLoad, in a minute the loop
    # already ticked: the lock does not stop it once the first tick has finished). In round_trip(), B buys
    # on the 21:41:00.100 row and sells on the 21:41:30.000 row while C holds: both arms are flat into and
    # out of 21:41, yet d_t there is minus one spread (-0.99995 bps), and report._disagreement, which reads
    # the sides into and out of a tick, does not count 21:41 as a disagreement tick. H1 is unaffected (S_k
    # sums every d_t); report §4.5's descriptive mean_d|dis and hit leave that d_t out. book.py and
    # report.py follow the fold; it is the sentence that does not hold. None of the twelve seeds here trips
    # it; the 28-day benchmark (synth.py --days 28 --seed 1, default knobs) does once, at 20261010T230700Z:
    # two live answered rows, both arms flat in and out, d_t(B - C) = d_t(B - A) = -0.568 bps.
    # The test below pins the fold; the sentence is an erratum (HANDOFF.md).
    ROUND_TRIP = "20260925T214100Z"

    def round_trip(self):
        rows = [_live(0, 0.1, "hold", "hold"), _live(1, 0.1, "buy", "hold"), _live(1, 30.0, "sell", "hold"), _live(2, 0.1, "hold", "hold")]
        return rows, book.replay(rows, None, "b", "argmax", 0.0), book.replay(rows, None, "c", "argmax", 0.0)

    def test_a_round_trip_inside_one_minute_is_flat_in_and_out_and_not_a_disagreement_tick(self):
        rows, px, py = self.round_trip()
        t = self.ROUND_TRIP
        self.assertEqual((px["position"]["20260925T214000Z"], px["position"][t], py["position"]["20260925T214000Z"], py["position"][t]),
                         (0.0, 0.0, 0.0, 0.0))
        self.assertEqual([tr["tick_id"] for tr in px["trades"]], [t, t])
        self.assertNotIn(t, report._disagreement(px, py))
        self.assertAlmostEqual(dict(book.paired(rows, None, "b", "c", "argmax", 0.0))[t], -1e4 * 0.01 / 100.005, places=9)



def _live(minute, sec, b, c, mid=100.0):
    """A live answered row at T0 + minute (ts_rx `sec` seconds in): B's choice b, rule_c c, A = C."""
    r = synth.new_row(T0_MS + 60_000 * minute + int(sec * 1000), "live", "spec")
    ans = {"a_action": {"choice": c, "probabilities": {"buy": 0.05, "sell": 0.05, "hold": 0.9}, "confidence": 0.9},
           "b_action": {"choice": b, "probabilities": {"buy": 0.05, "sell": 0.05, "hold": 0.9}, "confidence": 0.9},
           "skip": {"noul": 0.1}, "up15": {"noul": 0.4}, "down15": {"noul": 0.4}}
    adj = {"liq": "deep", "flow": "organic", "trend": "flat", "vol": "normal"}
    r.update(bid=round(mid - 0.005, 3), ask=round(mid + 0.005, 3), mid=mid, adj=adj, state=state.state_string(adj), rule_c=c,
             answers=ans, columns={"a": rules.for_arm(ans, "a"), "b": rules.for_arm(ans, "b")})
    return r


def _halt(minute, mid):
    """A HALT row at T0 + minute: priced, rule_c hold, no answers, no columns (SPEC §13.2)."""
    r = _live(minute, 0.1, "hold", "hold", mid)
    r.update(answers=None, columns={"a": None, "b": None}, absence="halt")
    return r


# ---- (f) the inference: deterministic, and PREREG §4-§5 recomputed ---------------------------------------
class Inference(unittest.TestCase):
    SEED, R = 2, 20                                   # a plain 1-day log; 20 resamples (the draw is test_inference_golden's)
    # T0 before PREREG §11's seal: a log holding rows of the sealed sample refuses --sample until day 28
    # on the real clock, whatever --now says (a copy of the live log is the live log), and the run in a
    # fresh interpreter below has no other clock than the real one.
    T0S, T0 = "20260801T000000Z", report.tick_epoch("20260801T000000Z")
    ARGV = ["--sample", "--t0", T0S, "--now", "2026-10-24T00:00", "--resamples", str(R), "--accept-pending"]

    @classmethod
    def setUpClass(cls):
        pin_prereg(cls)                                             # the in-process run's repository seal (the fresh interpreter
                                                                    # reads the repo's own: the log holds no row of either sample)
        cls.path = synth.write(os.path.join(_TMP.name, "inference.jsonl"), synth.generate(cls.SEED, **{**knobs(cls.SEED), "t0": cls.T0S}))
        cls.ex = os.path.join(_TMP.name, "exclusions.tsv")
        with open(cls.ex, "w", encoding="utf-8") as fh:
            fh.write("day\tfill%\tjev-err%\treason\n")
        cls.out = os.path.join(_TMP.name, "inference-1.txt")
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            cls.code = inference.main(cls.ARGV + ["--log", cls.path, "--exclusions", cls.ex, "--out", cls.out])
        cls.text, cls.err = buf.getvalue(), err.getvalue()

    def test_two_runs_are_byte_identical_whatever_the_hash_seed(self):
        # the second run in a fresh interpreter under another PYTHONHASHSEED: set and dict orders of strings
        # change there, and the output must not
        self.assertEqual(self.code, 0, self.err)
        out2 = os.path.join(_TMP.name, "inference-2.txt")
        p = subprocess.run([sys.executable, "-m", "loop.inference"] + self.ARGV + ["--log", self.path, "--exclusions", self.ex, "--out", out2],
                           cwd=REPO, env=dict(os.environ, PYTHONHASHSEED="4242", PYTHONIOENCODING="utf-8"),   # the text is compared as UTF-8
                           capture_output=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(p.stdout.decode(), self.text)
        with open(self.out, "rb") as a, open(out2, "rb") as b:
            self.assertEqual(a.read(), b.read())
        self.assertIn(f"{self.R} resamples, seed 20260923", self.text)
        self.assertIn(f"n blocks {BLOCKS}", self.text)

    def test_h1_and_h2_are_prereg_4_and_5_recomputed(self):
        rows = inference.read_log(self.path)[0]
        outs = outcomes.join(rows)
        sample = report.in_sample(rows, self.T0)
        h1s = inference.h1(sample, outs, self.T0, set(), self.R)
        h2s = inference.h2(sample, outs, self.T0, set(), self.R)
        for h, (x, y) in zip(h1s, (("b", "c"), ("a", "c"), ("b", "a"))):
            mean = ref_h1(sample, x, y, self.T0)
            self.assertEqual((h["pair"], h["n"]), (f"{x.upper()} - {y.upper()}", BLOCKS))
            self.assertAlmostEqual(h["mean"], mean, places=9, msg=(x, y))
            self.assertIn(f"n blocks {BLOCKS}; mean S_k {mean:.4f} bps", self.text)
        self.assertNotEqual(h1s[0]["mean"], 0.0)                              # B and C did disagree somewhere
        units, r = ref_h2(sample, ref_join(rows)[0], self.T0)
        self.assertEqual(h2s["units"], units)
        self.assertGreater(len(units), 50)
        self.assertAlmostEqual(h2s["r"], r, places=9)
        self.assertIn(f"; r {r:.4f}; lower bound", self.text)


# ---- (g) PREREG-v2 §5-§6: the draw and the bound, transcribed from PREREG-v2.md's words, not from loop/ ------------------
# §5: "circular block bootstrap of the pooled block series in block order, block length L = 4 units of the cell's own
# cadence ..., R = 10,000 resamples, seed 20261023, each resample the same length as the series: ... ⌈n/4⌉ starts per
# resample, each rng.randrange(n), four consecutive wrapped units from each, concatenated in draw order, truncated to n
# ... with this cell's seed ... and the mean ...; one random.Random(seed) per cell. The bound is sorted[⌈α·R⌉ − 1] of the
# R sorted resampled means ...: sorted[249] at α = 1/40 (H1), sorted[62] at α = 1/160 (every family-F cell ...). Reject
# H0 iff the bound is > 0." §6: family F "each at α = 1/160 ... with seed 20261023 + i, in this order": i = 1 B - C at
# 3,600 s, 2 B - C at 14,400 s, 3 A - C at 900 s, 4 B - A at 900 s.
V2_R = 10000
V2_CELLS = (("H1", "b", "c", 900, 20261023, 249), ("F1", "b", "c", 3600, 20261024, 62), ("F2", "b", "c", 14400, 20261025, 62),
            ("F3", "a", "c", 900, 20261026, 62), ("F4", "b", "a", 900, 20261027, 62))
# a fixed series (26 values: not a multiple of 4, so the last resample block is cut) on which, at every cell's seed, the
# bound's neighbours differ from it (sorted[248] < sorted[249] < sorted[250] at H1's, sorted[61] < sorted[62] < sorted[63]
# at F's), so reading sorted[250], sorted[61] or sorted[63] cannot pass; H1 rejects on it and no F cell does
V2_GOLDEN = [4.965, 5.448, 1.299, -1.194, -2.177, 1.194, -1.966, -3.21, 1.698, 1.5, 2.739, -1.642, 1.115, 0.906, -3.417,
             2.714, 2.062, 8.267, 1.709, 0.666, 4.798, 1.696, 3.827, 0.003, 1.755, 4.173]
# each cell's bound on V2_GOLDEN at R = 10,000: computed once and pasted, and held to the transcription below as well
V2_BOUNDS = {"H1": 0.2524615384615384, "F1": -0.04073076923076925, "F2": -0.07249999999999998, "F3": -0.0879230769230769,
             "F4": -0.14953846153846154}


def v2_sorted(series, seed, R=V2_R):
    """§5's R resampled means, sorted ascending, as the text reads (see above)."""
    n = len(series)
    rng = random.Random(seed)
    means = []
    for _ in range(R):
        take = []
        for _ in range(math.ceil(n / 4)):
            s = rng.randrange(n)
            take += [series[(s + j) % n] for j in range(4)]
        take = take[:n]
        means.append(sum(take) / n)
    return sorted(means)


class V2Draw(unittest.TestCase):
    def same(self, got, want, what):
        if got != want:                                   # without difflib's quadratic diff of 10,000 lines
            i = next((i for i, (g, w) in enumerate(zip(got, want)) if g != w), min(len(got), len(want)))
            self.fail(f"{what}: lengths {len(got)} vs {len(want)}, first difference at [{i}]")

    def test_the_constants_are_the_texts_and_alpha_is_an_exact_fraction(self):
        self.assertEqual((inference_v2.SEED_H1, inference_v2.RESAMPLES, inference_v2.BLOCK_LEN), (20261023, 10000, 4))
        for a, want in ((inference_v2.ALPHA_H1, Fraction(1, 40)), (inference_v2.ALPHA_F, Fraction(1, 160))):
            self.assertIs(type(a), Fraction)
            self.assertEqual(a, want)
        self.assertEqual(inference_v2.alpha_rank(inference_v2.ALPHA_H1, V2_R), 249)
        self.assertEqual(inference_v2.alpha_rank(inference_v2.ALPHA_F, V2_R), 62)
        # ceil, exactly, at other R: alpha R an integer reads the value at alpha R (0-based alpha R - 1); a hair above it, the next
        for alpha, R, want in ((Fraction(1, 160), 160, 0), (Fraction(1, 160), 161, 1), (Fraction(1, 160), 320, 1),
                               (Fraction(1, 40), 40, 0), (Fraction(1, 40), 1000, 24), (Fraction(1, 40), 1001, 25), (Fraction(1, 160), 1, 0)):
            self.assertEqual(inference_v2.alpha_rank(alpha, R), want, (alpha, R))
        # a float is refused, not rounded: round(0.00625 x 10,000) and int() both give 62, i.e. sorted[61]
        for bad in (0.025, 0.00625, 1 / 160, 1, "1/40"):
            with self.assertRaises(TypeError, msg=repr(bad)):
                inference_v2.alpha_rank(bad, V2_R)
        with self.assertRaises(TypeError):
            inference_v2.bootstrap(V2_GOLDEN, 20261024, 0.00625, resamples=10)
        for bad in (Fraction(0), Fraction(1), Fraction(-1, 40)):
            with self.assertRaises(ValueError):
                inference_v2.alpha_rank(bad, V2_R)
        for bad in (0, -1, True, 10.0):
            with self.assertRaises(ValueError):
                inference_v2.alpha_rank(Fraction(1, 40), bad)

    def test_each_cells_draw_is_the_transcription_and_its_bound_on_a_fixed_series_is_pinned(self):
        for name, x, y, c, seed, rank in V2_CELLS:
            alpha = inference_v2.ALPHA_H1 if name == "H1" else inference_v2.ALPHA_F
            b = inference_v2.bootstrap(V2_GOLDEN, seed, alpha)             # the defaults: R and L as run at day 28
            want = v2_sorted(V2_GOLDEN, seed)
            self.same(b["sorted"], want, name)
            self.assertEqual((b["n"], b["rank"]), (len(V2_GOLDEN), rank), name)
            self.assertLess(want[rank - 1], want[rank], name)                # sorted[61] != sorted[62], sorted[248] != sorted[249]
            self.assertLess(want[rank], want[rank + 1], name)
            self.assertEqual(b["lower"], want[rank], name)
            self.assertAlmostEqual(b["lower"], V2_BOUNDS[name], places=9, msg=name)   # sum() is compensated from 3.12: 3.11 may differ in the last bit
            self.assertEqual(b["reject"], V2_BOUNDS[name] > 0, name)
        self.assertEqual([n for n, *_ in V2_CELLS if V2_BOUNDS[n] > 0], ["H1"])

    def test_the_draw_cuts_the_last_block_and_each_cell_has_its_own_generator(self):
        g = random.Random(11)
        s = [round(g.gauss(0.0, 20.0), 6) for _ in range(2013)]
        self.same(inference_v2.bootstrap(s, 20261025, inference_v2.ALPHA_F, resamples=40)["sorted"], v2_sorted(s, 20261025, 40), "n 2013")
        self.same(inference_v2.bootstrap(s[:2012], 20261023, inference_v2.ALPHA_H1, resamples=40)["sorted"],
                  v2_sorted(s[:2012], 20261023, 40), "n 2012")
        a = inference_v2.bootstrap(s, 20261026, inference_v2.ALPHA_F, resamples=30)
        inference_v2.bootstrap(s, 20261027, inference_v2.ALPHA_F, resamples=30)        # another cell in between draws nothing of its
        self.same(inference_v2.bootstrap(s, 20261026, inference_v2.ALPHA_F, resamples=30)["sorted"], a["sorted"], "F3 again")
        self.assertEqual(inference_v2.bootstrap([], 20261023, inference_v2.ALPHA_H1)["lower"], None)
        self.assertFalse(inference_v2.bootstrap([], 20261023, inference_v2.ALPHA_H1)["reject"])
        # ties stay in: a series of zeros bounds at 0.0 and does not reject (> 0, not >= 0)
        z = inference_v2.bootstrap([0.0] * 12, 20261023, inference_v2.ALPHA_H1, resamples=50)
        self.assertEqual((z["lower"], z["reject"], z["n"]), (0.0, False, 12))


# ---- (h) PREREG-v2 §2, §4, §6, §9: the pooled statistic, stop rules 3-4, §9.2's row set and the fee arithmetic, -------------
# transcribed from PREREG-v2.md's words and held against loop/inference_v2.py (and report.fee_arithmetic) on a synthetic
# three-product v2 log: one product void (8 days with no row), one with a day of no row, SOL with a day of jev errors.
# §2 "Live row = a row with mode: "live" and absence: null"; "Days are T0-anchored: d N = [T0_v2 + 86,400 (N - 1),
# T0_v2 + 86,400 N)"; "Sample window = every row with T0_v2 <= tick_id < T0_v2 + 28 · 86,400 s, cut before any replay".
# §9.3 "BAD when its outcome fill (live rows whose t + h the log has reached, with a non-gap outcome, over such live rows)
# is < 95 %, or its Jev error share (rows with absence: "jev", every error kind, over rows with mode: "live" and absence
# null or "jev") is > 5 %. A product-day with no live row is excluded whole." §9.4 "A product with fewer than 21 kept days
# is void for v2 and leaves the pool." §4 "within each c-block [T0_v2 + c·j, T0_v2 + c·(j+1)), an arm's intent is its
# argmax ... on the block's decision row -- the first row of the block in book._order (least tick_id, then ts_rx) on which
# book.replay would not force a hold: a live row, priced ..., whose columns.a and columns.b are not both null or
# argmax-null -- and hold on every other row of the block ... A and B read columns.a/columns.b, C reads rule_c, D reads
# columns.d (null means hold for D only)"; "S_k,p(X - Y, col, fee) = Σ over the block's rows of d_t"; "S-bar_k = mean over
# the products p not void under §9.4 whose day containing block k is kept (§9.3) of S_k,p; a block with no such product is
# dropped". §9.2 "If no live row on a kept product-day of a non-void product has prompt_b_sha != prompt_a_sha ... NO
# PROMOTION". §6.1 "E_X,p(f) = Σ of book.replay's pnl for arm X on p's at_cadence rows over the ticks of p's kept days (an
# open position at the window's end is marked; a fill counts when its tick is on a kept day); pooled E_X(f) = Σ over
# non-void products of E_X,p(f). f*_X = 90 · E_X(0) / (E_X(0) − E_X(90)) ... "X never pays" when E_X(0) <= 0; undefined when
# X has no fill"; §6.2 "X's own 30-day volume: Σ over non-void products of (fill value on p's kept days × 30 / p's kept
# days)"; §6.3 "Δ_p(f) = E_X,p(f) − E_Y,p(f) = Σ_k S_k,p(X − Y, f) exactly; pooled Δ(f) = Σ_p Δ_p(f)".
V2_T0S = "20261024T220000Z"
V2_T0_MS = tick_ms(V2_T0S)
V2_DAY_MS = 86_400_000


def v2_null(x):
    return x is None or (isinstance(x, dict) and x.get("argmax") is None)


def v2_decides(r):
    return decision(r) and priced(r) and not (v2_null((r.get("columns") or {}).get("a")) and v2_null((r.get("columns") or {}).get("b")))


def v2_order(rows):
    return sorted(rows, key=lambda r: (r["tick_id"], ms_of(r["ts_rx"])))


def v2_intent(r, arm):
    if arm == "c":
        return r.get("rule_c")
    x = (r.get("columns") or {}).get(arm)
    return x.get("argmax") if isinstance(x, dict) else x          # D's column is the table's answer itself


def v2_book(rows, arm, c, fee=0.0):
    """§4's cadence transform and SPEC §10's book in one walk over `rows` in v2_order: the arm acts on its block's
    decision row and holds elsewhere. ({tick_id: pnl bps}, [(tick_id, side, price, qty)]), from flat."""
    acts = {}
    for r in rows:
        j = (tick_ms(r["tick_id"]) - V2_T0_MS) // (c * 1000)
        if j not in acts and v2_decides(r):
            acts[j] = id(r)
    acts_ids = set(acts.values())
    qty, last, pnl, trades = 0.0, None, {}, []
    for r in rows:
        tid, usd = r["tick_id"], 0.0
        if priced(r):
            bid, ask, mid = r["bid"], r["ask"], r["mid"]
            intent = v2_intent(r, arm) if id(r) in acts_ids else "hold"
            if intent == "buy" and qty == 0.0:
                qty = NOTIONAL / ask
                usd = qty * (mid - ask) - NOTIONAL * fee / 1e4
                trades.append((tid, "buy", ask, qty))
            elif intent == "sell" and qty > 0.0:
                usd = qty * (bid - last) - qty * bid * fee / 1e4
                trades.append((tid, "sell", bid, qty))
                qty = 0.0
            elif qty:
                usd = qty * (mid - last)
            last = mid
        pnl[tid] = pnl.get(tid, 0.0) + usd * 1e4 / NOTIONAL
    return pnl, trades


def v2_day(tid):
    return (tick_ms(tid) - V2_T0_MS) // V2_DAY_MS + 1


def v2_excluded(logs):
    """§9.3, recomputed per product from its own log: {(N, product)}."""
    out = set()
    for p, rows in logs.items():
        outs = ref_join(rows)[0]
        per = {n: [0, 0, 0, 0] for n in range(1, 29)}                  # [live, filled, jev, attempted]
        for r in rows:
            n = v2_day(r["tick_id"])
            if not 1 <= n <= 28 or r.get("mode") != "live":
                continue
            if r.get("absence") in (None, "jev"):
                per[n][3] += 1
            if r.get("absence") == "jev":
                per[n][2] += 1
            elif r.get("absence") is None:
                per[n][0] += 1
                per[n][1] += outs[r["tick_id"]]["absence"] is None
        for n, (live, filled, jev, att) in per.items():
            if live == 0 or filled / live < 0.95 or (att and jev / att > 0.05):
                out.add((n, p))
    return out


class V2Pooled(unittest.TestCase):
    R = 300                                                          # sorted[7] at 1/40, sorted[1] at 1/160

    @classmethod
    def setUpClass(cls):
        cls.products = add_products(cls, 3)
        sol, p2, p3 = cls.products
        logs = synth.generate_products(7, cls.products, encode=False, t0=V2_T0S, days=28.0, pre_hours=1.0, post_minutes=40,
                                       cadence_s=300, era="v2", promotions_h=(150.0,),
                                       per_product={p2: {"empty_days": (5,)}, p3: {"empty_days": tuple(range(2, 10))}})
        cls.logs = {p: log.rows for p, log in logs.items()}
        for i, r in enumerate(r for r in cls.logs[sol] if v2_day(r["tick_id"]) == 12 and decision(r)):
            if i % 8 == 0:                                           # d12 of SOL: an eighth of its live rows a jev error, BAD
                r.update(absence="jev", answers=None, columns={"a": None, "b": None, "d": None}, jev=dict(r["jev"], error="timeout"))
        cls.t0 = report.tick_epoch(V2_T0S)
        stores = [{"product": p, "log": p, "missing": False, "rows": cls.logs[p], "bad": [], "sha": "-", "bytes": 0} for p in cls.products]
        cls.out = inference_v2.run(stores, cls.t0, cls.t0 + 29 * 86400, resamples=cls.R, descriptive=False)
        cls.sample = {p: [r for r in rows if V2_T0_MS <= tick_ms(r["tick_id"]) < V2_T0_MS + 28 * V2_DAY_MS] for p, rows in cls.logs.items()}
        cls.ordered = {p: v2_order(rows) for p, rows in cls.sample.items()}
        cls.books = {}
        cls.excluded = v2_excluded(cls.logs)
        cls.kept_days = {p: 28 - sum(1 for _, q in cls.excluded if q == p) for p in cls.products}
        cls.pool = [p for p in cls.products if cls.kept_days[p] >= 21]

    def book(self, p, arm, c, fee=0.0):
        key = (p, arm, c, fee)
        if key not in self.books:
            self.books[key] = v2_book(self.ordered[p], arm, c, fee)
        return self.books[key]

    def ref_series(self, x, y, c, fee=0.0):
        """§4: [(k, S-bar_k)] and {p: {k: S_k,p}}."""
        S_p = {}
        for p in self.pool:
            px, py = self.book(p, x, c, fee)[0], self.book(p, y, c, fee)[0]
            s = {}
            for t in px:
                k = (tick_ms(t) - V2_T0_MS) // (c * 1000)
                s[k] = s.get(k, 0.0) + px[t] - py[t]
            S_p[p] = s
        out = []
        for k in range(28 * 86400 // c):
            ps = [p for p in self.pool if (k * c // 86400 + 1, p) not in self.excluded]
            if ps:
                out.append((k, sum(S_p[p].get(k, 0.0) for p in ps) / len(ps)))
        return out, S_p

    def test_stop_rules_3_and_4_and_the_row_set_of_9_2(self):
        sol, p2, p3 = self.products
        self.assertFalse(self.out["pending"])
        self.assertEqual(self.out["excluded"], self.excluded)
        self.assertLessEqual({(12, sol), (5, p2)} | {(n, p3) for n in range(2, 10)}, self.excluded)
        self.assertEqual(self.out["kept_days"], self.kept_days)
        self.assertEqual(self.out["pool"], self.pool)
        self.assertEqual(self.pool, [sol, p2])                       # p3: 20 kept days, void
        promoted = sum(1 for p in self.pool for r in self.sample[p]
                       if decision(r) and (v2_day(r["tick_id"]), p) not in self.excluded and r["prompt_b_sha"] != r["prompt_a_sha"])
        self.assertGreater(promoted, 0)
        self.assertEqual(self.out["promoted"], promoted)

    def test_each_cells_pooled_series_mean_and_bound_are_the_texts(self):
        for name, x, y, c, seed, _ in V2_CELLS:
            with self.subTest(cell=name):
                want, _ = self.ref_series(x, y, c)
                got = self.out["cells"][name]
                self.assertEqual([k for k, _ in got["series"]], [k for k, _ in want])
                for (k, g), (_, w) in zip(got["series"], want):
                    self.assertAlmostEqual(g, w, places=9, msg=(name, k))
                self.assertGreater(len(want), 0)
                self.assertTrue(any(v != 0.0 for _, v in want))
                vals = [v for _, v in want]
                self.assertAlmostEqual(got["mean"], sum(vals) / len(vals), places=9)
                rank = math.ceil(self.R / (40 if name == "H1" else 160)) - 1  # sorted[⌈α·R⌉ − 1]: 7 and 1 at R = 300
                self.assertEqual(got["rank"], rank)
                self.assertAlmostEqual(got["lower"], v2_sorted(vals, seed, self.R)[rank], places=9)
                self.assertEqual(got["reject"], got["lower"] > 0)

    def test_the_fee_arithmetic_is_6_1_to_6_3(self):
        # report.fee_arithmetic, fed each product's at_cadence replay (as report.cadence_table feeds it), against §6.1-§6.3
        sol, p2, p3 = self.products
        for c in config.CADENCES:
            kept = lambda p, t: p in self.pool and (v2_day(t), p) not in self.excluded
            on = {p: {r["tick_id"] for r in self.sample[p] if kept(p, r["tick_id"])} for p in self.products}
            days = {p: self.kept_days[p] if p in self.pool else 0 for p in self.products}
            rows_c = {p: book.at_cadence(self.sample[p], c, self.t0) for p in self.products}
            fa = report.fee_arithmetic(c, list(self.products), self.pool, on, days,
                                       lambda p, a, f: book.replay(rows_c[p], None, a, "argmax", f),
                                       lambda p, f: book.replay(report._bh_rows(self.sample[p]), None, "a", "argmax", f),
                                       [report.ERRATA_TIER])
            E = {}
            for a in book.ARMS:
                for p in self.pool:
                    per = {}
                    for f in (0.0, 90.0):
                        pnl, trades = self.book(p, a, c, f)
                        per[f] = sum(v for t, v in pnl.items() if kept(p, t))
                        fills = [tr for tr in trades if kept(p, tr[0])]
                    E[(a, p)] = (per[0.0], per[90.0], len(fills), sum(q * px for _, _, px, q in fills))
                    got = fa["per"][p][a]
                    self.assertAlmostEqual(got["e0"], per[0.0], places=6, msg=(c, a, p))
                    self.assertAlmostEqual(got["e90"], per[90.0], places=6, msg=(c, a, p))
                    self.assertEqual(got["fills"], E[(a, p)][2], (c, a, p))
                    self.assertAlmostEqual(got["volume_30d"], E[(a, p)][3] * 30 / self.kept_days[p], places=6, msg=(c, a, p))
                e0, e90, n = (sum(E[(a, p)][i] for p in self.pool) for i in range(3))
                x = fa["pooled"][a]
                self.assertAlmostEqual(x["e0"], e0, places=6)
                self.assertEqual(x["fills"], n)
                if not n:
                    self.assertEqual((x["fstar"], x["reading"]), (None, "undefined: no fill on a kept day"))
                elif e0 <= 0:
                    self.assertEqual((x["fstar"], x["reading"]), (None, "never pays: E(0) <= 0"))
                else:
                    self.assertAlmostEqual(x["fstar"], 90 * e0 / (e0 - e90), places=6, msg=(c, a))
            for x, y in report.PAIRS:                                   # §6.3: Delta = E_X - E_Y = the sum of S_k over kept blocks
                d0 = sum(E[(x, p)][0] - E[(y, p)][0] for p in self.pool)
                d90 = sum(E[(x, p)][1] - E[(y, p)][1] for p in self.pool)
                pr = fa["pairs"][(x, y)]
                self.assertAlmostEqual(pr["d0"], d0, places=6, msg=(c, x, y))
                self.assertAlmostEqual(pr["d90"], d90, places=6, msg=(c, x, y))
                _, S_p = self.ref_series(x, y, c)
                s = sum(v for p in self.pool for k, v in S_p[p].items() if (k * c // 86400 + 1, p) not in self.excluded)
                self.assertAlmostEqual(d0, s, places=6, msg=(c, x, y))
                X, Y = x.upper(), y.upper()
                if abs(d0 - d90) <= 1e-9:
                    self.assertTrue(pr["reading"].startswith("fees cancel"), (c, x, y))
                else:
                    fs = 90 * d0 / (d0 - d90)
                    self.assertAlmostEqual(pr["fstar"], fs, places=6)
                    if fs > 0:
                        self.assertEqual(pr["reading"], f"{X} {'stops' if d0 > 0 else 'starts'} beating {Y} above {fs:.2f} bps per fill")
                    else:
                        self.assertTrue(pr["reading"].startswith("the sign of Delta(90) holds at every fee > 0: "), (c, x, y))
            # §6.1's buy-and-hold line over the same span: bought at the ask of the first priced row, marked to every mid after
            for p in self.pool:
                priced_rows = [r for r in self.ordered[p] if priced(r)]
                qty, marks = NOTIONAL / priced_rows[0]["ask"], {}
                for prev, r in zip([None] + priced_rows, priced_rows):
                    usd = qty * (r["mid"] - (priced_rows[0]["ask"] if prev is None else prev["mid"]))
                    marks[r["tick_id"]] = marks.get(r["tick_id"], 0.0) + usd * 1e4 / NOTIONAL
                self.assertAlmostEqual(fa["per"][p]["buy-and-hold"]["e0"], sum(v for t, v in marks.items() if kept(p, t)), places=6)
                self.assertEqual(fa["per"][p]["buy-and-hold"]["fills"], 1 if kept(p, priced_rows[0]["tick_id"]) else 0)


if __name__ == "__main__":
    unittest.main()

"""Seeded property tests on synthetic logs (tests/synth.py): the join, the blocks, the book, the health
readers and the inference, each held to what SPEC.md, PREREG.md and CONTRACT.md say in words, on logs
with holes, torn and glued lines, duplicate ticks, HALT stretches, absence-only and empty days, words
outside the alphabet, the old ~61 s launchd grid, ts_rx anywhere in its minute, and a promotion.

The references below (ref_join, ref_pnl, ref_h1, ref_h2) are written from the documents' words, not
from loop/: SPEC §11 for the join (the priced row whose ts_rx is nearest t + 900 s within +-30 s,
strictly after t, ties in whole milliseconds to the earlier row; when two rows share a tick_id the
live decision speaks for it, then any other priced row, then an unpriced one), SPEC §10 for the book,
PREREG §3-§5 for S_k, the H1 mean and the H2 units and r. A disagreement between a reference and the
code is reported, never "fixed" in the test: it is kept as an expectedFailure that names the rows.
One such finding is below (Book, SPEC §10's "exactly 0.0" sentence against its own fold).
Offline; temp files only; nothing is sent; the live prompts/, data/ and HALT are never read.
"""
import bisect, calendar, contextlib, datetime, io, math, os, re, subprocess, sys, tempfile, unittest
from unittest import mock

import synth
from fixture_prompts import pin_v1
from loop import book, config, cycle, dash, inference, outcomes, report, rules, state, status
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


_TMP = tempfile.TemporaryDirectory()
_LOGS, _FILES, _JOINS = {}, {}, {}


def tearDownModule():
    _TMP.cleanup()


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


def ref_h1(sample, x, y):
    """PREREG §3-§4: S_k = sum of d_t = pnl_x - pnl_y over the ticks with T0 + 900k <= tick_id < T0 + 900(k+1),
    k = 0 .. 2687, an empty block 0 and kept; the statistic is the mean of the 2688."""
    px, py = ref_pnl(sample, x)[0], ref_pnl(sample, y)[0]
    S = [0.0] * BLOCKS
    for t in px:
        S[(tick_ms(t) - T0_MS) // BLOCK_MS] += px[t] - py[t]
    return sum(S) / BLOCKS


def ref_pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    return sxy / math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))


def ref_h2(sample, outs):
    """PREREG §5: the first live row of each block (by tick_id time from T0; the first written within a
    minute), x = round(up15 - down15, 12), y = its ret_h_bps; a gap or a missing noul drops the block."""
    first = {}
    for r in sorted((r for r in sample if decision(r)), key=lambda r: r["tick_id"]):
        first.setdefault((tick_ms(r["tick_id"]) - T0_MS) // BLOCK_MS, r)
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
        keys = list(cycle.new_row("2026-09-25T21:40:00.100Z", "live"))
        jev = list(cycle.new_row("2026-09-25T21:40:00.100Z", "live")["jev"])
        for seed in (1, 5):
            for r in case(seed).rows:
                self.assertEqual(list(r), keys)                                      # every key, in cycle.new_row's order
                self.assertEqual(list(r["jev"]), jev)
                self.assertEqual(r["tick_id"], cycle.tick_id(r["ts_rx"]))
                if r["answers"] is not None and r["absence"] is None:
                    self.assertEqual(r["columns"], {"a": rules.for_arm(r["answers"], "a"), "b": rules.for_arm(r["answers"], "b")})
                if isinstance(r["adj"], dict) and all(r["adj"][d] in state.ALPHABET[d] for d in state.DIMS):
                    self.assertEqual((r["state"], r["rule_c"]), (state.state_string(r["adj"]), state.rule_c(r["adj"])))
                    self.assertEqual(r["adj"], state.adjectives(r["features"]))

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

    @unittest.expectedFailure
    def test_prereg_3_forced_holds_contribute_zero_and_a_block_without_a_live_row_is_zero(self):
        d, S = self.forced_mark()
        self.assertEqual((d["20260925T215500Z"], S[1][1]), (0.0, 0.0))            # PREREG §3's sentence, literally


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
                            mock.patch.object(dash, "heartbeat", return_value=None):
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
    # The expectedFailure keeps it visible.
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

    @unittest.expectedFailure
    def test_d_t_is_exactly_zero_on_every_tick_both_arms_carry_one_qty_through(self):
        rows, px, py = self.round_trip()
        self.assertEqual(dict(book.paired(rows, None, "b", "c", "argmax", 0.0))[self.ROUND_TRIP], 0.0)   # SPEC §10's sentence


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
    ARGV = ["--sample", "--t0", T0S, "--now", "2026-10-24T00:00", "--resamples", str(R), "--accept-pending"]

    @classmethod
    def setUpClass(cls):
        cls.path = on_disk(cls.SEED)[1]
        cls.ex = os.path.join(_TMP.name, "exclusions.tsv")
        with open(cls.ex, "w") as fh:
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
                           cwd=REPO, env=dict(os.environ, PYTHONHASHSEED="4242"), capture_output=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(p.stdout.decode(), self.text)
        with open(self.out, "rb") as a, open(out2, "rb") as b:
            self.assertEqual(a.read(), b.read())
        self.assertIn(f"{self.R} resamples, seed 20260923", self.text)
        self.assertIn(f"n blocks {BLOCKS}", self.text)

    def test_h1_and_h2_are_prereg_4_and_5_recomputed(self):
        rows = inference.read_log(self.path)[0]
        outs = outcomes.join(rows)
        sample = report.in_sample(rows, T0)
        h1s = inference.h1(sample, outs, T0, set(), self.R)
        h2s = inference.h2(sample, outs, T0, set(), self.R)
        for h, (x, y) in zip(h1s, (("b", "c"), ("a", "c"), ("b", "a"))):
            mean = ref_h1(sample_of(rows), x, y)
            self.assertEqual((h["pair"], h["n"]), (f"{x.upper()} - {y.upper()}", BLOCKS))
            self.assertAlmostEqual(h["mean"], mean, places=9, msg=(x, y))
            self.assertIn(f"n blocks {BLOCKS}; mean S_k {mean:.4f} bps", self.text)
        self.assertNotEqual(h1s[0]["mean"], 0.0)                              # B and C did disagree somewhere
        units, r = ref_h2(sample_of(rows), ref_join(rows)[0])
        self.assertEqual(h2s["units"], units)
        self.assertGreater(len(units), 50)
        self.assertAlmostEqual(h2s["r"], r, places=9)
        self.assertIn(f"; r {r:.4f}; lower bound", self.text)


if __name__ == "__main__":
    unittest.main()

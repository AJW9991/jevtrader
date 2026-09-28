"""outcomes: the t+h join never returns the wrong row (a 20-minute gap is a
gap, a jittered t+15 row is never swapped for t+16), the window's edges, the
dead band, and a log reader that survives one truncated line. Offline; temp
files only."""
import datetime, json, math, os, tempfile, unittest

from loop import config, outcomes

T0 = datetime.datetime(2026, 9, 23, 10, 0, 0, tzinfo=datetime.timezone.utc)
H = config.HORIZON_S


def _iso(s):
    d = T0 + datetime.timedelta(seconds=s)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _row(s, mid, absence=None):
    """Row at T0+s seconds; mid None = failed before the feed."""
    d = T0 + datetime.timedelta(seconds=s)
    return {"v": 1, "tick_id": d.strftime("%Y%m%dT%H%M00Z"), "ts_rx": _iso(s), "mode": "live",
            "bid": None if mid is None else mid - 0.01, "ask": None if mid is None else mid + 0.01,
            "mid": mid, "rule_c": None if mid is None else "hold",
            "columns": {"a": None, "b": None}, "absence": absence}


class Join(unittest.TestCase):
    def test_exact_horizon_row(self):
        rows = [_row(60 * i, 100.0 + i) for i in range(20)]         # minutes 0..19, priced
        out = outcomes.join(rows, H)
        o = out[rows[0]["tick_id"]]
        self.assertEqual(o["mid_h"], 115.0)                          # minute 15, and no other
        self.assertEqual(o["ret_h_bps"], 1e4 * math.log(115.0 / 100.0))
        self.assertEqual(o["label"], "up")
        self.assertIsNone(o["absence"])
        self.assertEqual(sorted(o), ["absence", "label", "mid_h", "ret_h_bps"])
        self.assertEqual(len(out), 20)
        for r in rows[5:]:                                           # minutes 5..19: +15 is past the log
            self.assertEqual(out[r["tick_id"]], outcomes.GAP)

    def test_twenty_minute_gap_is_gap_not_the_wrong_row(self):
        rows = [_row(60 * i, 100.0) for i in range(6)] + [_row(60 * i, 100.0) for i in range(25, 60)]
        out = outcomes.join(rows, H)
        for r in rows[:6]:                                           # t+15 lands inside the outage (min 15..20)
            self.assertEqual(out[r["tick_id"]], outcomes.GAP)
        self.assertEqual(out[rows[6]["tick_id"]]["mid_h"], 100.0)    # minute 25 -> minute 40 exists
        self.assertEqual(out[rows[6]["tick_id"]]["label"], "flat")
        self.assertEqual(sum(o["absence"] == "gap" for o in out.values()), 6 + 15)   # and minutes 45..59

    def test_window_is_half_a_cadence_either_side_and_nearest_wins(self):
        # The earlier form took the FIRST row in [t+h, t+h+90] and asserted that a row at
        # H - 0.001 was a gap: that pinned the defect (a t+15 row 1 ms "early" was skipped
        # and the t+16 row taken). The window is now +-JOIN_TOL_S around t+h, nearest row.
        tol = outcomes.JOIN_TOL_S
        self.assertEqual(tol, config.CADENCE_S / 2)
        base = _row(0, 100.0)
        mid_h = lambda *rows: outcomes.join([base, *rows], H)[base["tick_id"]].get("mid_h")
        self.assertEqual(mid_h(_row(H, 101.0)), 101.0)
        self.assertEqual(mid_h(_row(H - 0.001, 101.0)), 101.0)
        self.assertEqual(mid_h(_row(H + tol, 101.0)), 101.0)                 # both edges inclusive
        self.assertEqual(mid_h(_row(H - tol, 101.0)), 101.0)
        self.assertEqual(outcomes.join([base, _row(H + tol + 0.001, 101.0)], H)[base["tick_id"]], outcomes.GAP)
        self.assertEqual(outcomes.join([base, _row(H - tol - 0.001, 101.0)], H)[base["tick_id"]], outcomes.GAP)
        self.assertEqual(outcomes.join([base, _row(H + 60, 101.0)], H)[base["tick_id"]], outcomes.GAP)   # t+16 alone
        self.assertEqual(mid_h(_row(H + 20, 103.0), _row(H - 10, 102.0)), 102.0)   # nearest, file order != time order
        self.assertEqual(mid_h(_row(H + 10, 103.0), _row(H - 10, 102.0)), 102.0)   # a tie goes to the earlier row
        self.assertEqual(mid_h(_row(H + 60, 103.0), _row(H + 1, 102.0)), 102.0)

    def test_jitter_never_picks_the_t_plus_16_row(self):
        # t at :00.050, t+15 at :00.030 (20 ms "early"), t+16 at :00.040: the t+15 mid.
        rows = [_row(0.050, 100.0), _row(H + 0.030, 101.0), _row(H + 60.040, 150.0)]
        self.assertEqual(outcomes.join(rows, H)[rows[0]["tick_id"]]["mid_h"], 101.0)

    def test_a_phase_shift_still_joins_within_half_a_cadence(self):
        # launchd's StartInterval phase can jump (a wake from sleep): t at :10, later rows
        # at :50. The row 20 s before t+h is taken over the one 40 s after it.
        rows = [_row(10, 100.0), _row(H - 20, 101.0), _row(H + 40, 150.0)]
        self.assertEqual(outcomes.join(rows, H)[rows[0]["tick_id"]]["mid_h"], 101.0)

    def test_two_rows_sharing_a_ts_rx_do_not_break_the_sort(self):
        rows = [_row(0, 100.0), _row(H, None, absence="lock"), _row(H, 101.0)]
        self.assertEqual(outcomes.join(rows, H)[rows[0]["tick_id"]]["mid_h"], 101.0)

    def test_absence_row_in_window_does_not_hide_the_priced_one(self):
        base = _row(0, 100.0)
        rows = [base, _row(H, None, absence="lock"), _row(H + 1, 104.0)]
        self.assertEqual(outcomes.join(rows, H)[base["tick_id"]]["mid_h"], 104.0)
        self.assertEqual(outcomes.join([base, _row(H, None, absence="halt")], H)[base["tick_id"]], outcomes.GAP)

    def test_row_without_mid_is_gap_and_priced_twin_wins(self):
        rows = [_row(0, None, absence="feed"), _row(0.5, 100.0), _row(H + 1, 100.0)]   # same minute, two rows
        out = outcomes.join(rows, H)
        self.assertEqual(out[rows[0]["tick_id"]]["mid_h"], 100.0)
        out2 = outcomes.join([rows[1], rows[0], rows[2]], H)                         # either file order
        self.assertEqual(out2[rows[0]["tick_id"]]["mid_h"], 100.0)
        self.assertEqual(outcomes.join([_row(0, None, absence="feed")], H)[rows[0]["tick_id"]], outcomes.GAP)

    def test_a_later_priced_twin_never_speaks_for_the_live_decision(self):
        # 2026-09-28 (review): the live tick at :00.1 has no priced row within +-30 s of its t+15
        # (that row was lost). A `make dry` 35 s into the same minute, or a double-fire, has its own
        # window [t+15:05, t+16:05], which catches the t+16 row; before this fix that outcome replaced
        # the live row's gap, so the decision was scored against a mid 16 minutes out, from another
        # row's mid_t. The live row (rank 0) keeps its gap; a lock row (unpriced, rank 2) never wins.
        rows = [_row(60 * m + 0.1, 100.0 + m) for m in range(21) if m != 15]
        dry = dict(_row(35.0, 100.5), mode="dry")
        rows.insert(1, dry)
        out = outcomes.join(rows)
        self.assertEqual(out[rows[0]["tick_id"]], outcomes.GAP)
        self.assertEqual((outcomes.rank(rows[0]), outcomes.rank(dry)), (0, 1))
        # the dry row FIRST in file order does not outrank the live row either
        out = outcomes.join([dry] + [r for r in rows if r is not dry])
        self.assertEqual(out[dry["tick_id"]], outcomes.GAP)
        # and where the live row does have an outcome, the twin's is never the one filed
        rows = [_row(60 * m + 0.1, 100.0 + m) for m in range(21)]
        rows.insert(1, dict(_row(35.0, 100.5), mode="dry"))
        self.assertEqual(outcomes.join(rows)[rows[0]["tick_id"]]["mid_h"], 115.0)
        # two live priced rows in one minute: the first in file order speaks for the tick
        rows = [_row(60 * m + 0.1, 100.0 + m) for m in range(21)]
        rows.insert(1, _row(30.0, 100.5))
        self.assertEqual(outcomes.join(rows)[rows[0]["tick_id"]]["mid_h"], 115.0)
        self.assertEqual(outcomes.rank(_row(0, None, absence="lock")), 2)

    def test_an_exact_tie_goes_to_the_earlier_row_in_whole_milliseconds(self):
        # 18.652 s before and after t+900 from a t whose fraction is .137: the two float distances
        # differ in the last bit and about a quarter of such ties went to the later row
        b = _row(0.137, 100.0)
        e = _row(900 - 18.652 + 0.137, 102.0)
        l = _row(900 + 18.652 + 0.137, 103.0)
        self.assertEqual(outcomes.join([b, e, l])[b["tick_id"]]["mid_h"], 102.0)
        for k in range(200):                                          # many fractions, always the earlier
            b = _row(0.001 * k, 100.0)
            e, l = _row(900 - 7.777 + 0.001 * k, 102.0), _row(900 + 7.777 + 0.001 * k, 103.0)
            self.assertEqual(outcomes.join([b, e, l])[b["tick_id"]]["mid_h"], 102.0, k)
        times, mids = outcomes.priced_points([b, e, l])
        self.assertEqual(outcomes.pick(times, outcomes.ts_epoch(b["ts_rx"])), 1)
        self.assertIsNone(outcomes.pick(times, outcomes.ts_epoch(l["ts_rx"])))

    def test_gap_outcome_is_a_fresh_dict(self):
        out = outcomes.join([_row(0, 100.0)], H)
        out[next(iter(out))]["label"] = "x"
        self.assertIsNone(outcomes.GAP["label"])

    def test_horizon_parameter(self):
        rows = [_row(0, 100.0), _row(300, 105.0), _row(H, 110.0)]
        self.assertEqual(outcomes.join(rows, 300)[rows[0]["tick_id"]]["mid_h"], 105.0)
        self.assertEqual(outcomes.join(rows)[rows[0]["tick_id"]]["mid_h"], 110.0)


class DeadBand(unittest.TestCase):
    def test_label_boundaries(self):
        b = config.DEAD_BAND_BPS
        self.assertEqual(outcomes.label(0.0), "flat")
        self.assertEqual(outcomes.label(b - 0.001), "flat")
        self.assertEqual(outcomes.label(-(b - 0.001)), "flat")
        self.assertEqual(outcomes.label(b), "up")
        self.assertEqual(outcomes.label(-b), "down")
        self.assertEqual(outcomes.label(b + 0.001), "up")
        self.assertEqual(outcomes.label(-(b + 0.001)), "down")

    def test_join_labels_through_the_band(self):
        for bps, want in ((3.0, "flat"), (-3.0, "flat"), (6.0, "up"), (-6.0, "down"), (0.0, "flat")):
            base = _row(0, 100.0)
            o = outcomes.join([base, _row(H, 100.0 * math.exp(bps / 1e4))], H)[base["tick_id"]]
            self.assertAlmostEqual(o["ret_h_bps"], bps, places=9)
            self.assertEqual(o["label"], want, bps)


class Load(unittest.TestCase):
    def _write(self, lines):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "decisions.jsonl")
        with open(p, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        self.addCleanup(lambda: (os.remove(p), os.rmdir(d)))
        return p

    def test_malformed_lines_skipped_and_counted(self):
        good = [json.dumps(_row(60 * i, 100.0)) for i in range(3)]
        p = self._write([good[0], good[1][:40], "", "[1, 2]", json.dumps({"ts_rx": _iso(0)}), good[2]])
        bad = []
        rows = outcomes.load(p, bad)
        self.assertEqual([r["ts_rx"] for r in rows], [_iso(0), _iso(120)])
        self.assertEqual([n for n, _ in bad], [2, 4, 5])                     # the blank line is neither
        self.assertTrue(bad[0][1].startswith("json"))
        self.assertEqual(outcomes.load(p), rows)                              # count is optional

    def test_a_whole_row_glued_onto_a_torn_line_is_kept(self):
        # a crash mid-write leaves half a row without a newline; the next tick's whole row lands on the
        # same line. The torn head is the skip; the whole row is a row (it was written in full)
        p = os.path.join(tempfile.mkdtemp(), "d.jsonl")
        a, b, c = _row(0, 100.0), _row(60, 101.0), _row(120, 102.0)
        with open(p, "w") as fh:
            fh.write(json.dumps(a, separators=(",", ":")) + "\n")
            fh.write(json.dumps(b, separators=(",", ":"))[:40])          # torn: no newline
            fh.write(json.dumps(c, separators=(",", ":")) + "\n")
        bad = []
        rows = outcomes.load(p, bad)
        self.assertEqual([r["tick_id"] for r in rows], [a["tick_id"], c["tick_id"]])
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0][0], 2)
        self.assertIn("the whole row appended onto the torn line is kept", bad[0][1])
        # a torn line with nothing whole after it is still one skipped line, and a line that is
        # not a row at all is not rescued from the middle of some other text
        with open(p, "w") as fh:
            fh.write(json.dumps(a, separators=(",", ":")) + "\n" + json.dumps(b, separators=(",", ":"))[:40] + "\n")
            fh.write('x {"v": 1} {"v":1,"tick_id":"nope"}\n')
        bad = []
        rows = outcomes.load(p, bad)
        self.assertEqual([r["tick_id"] for r in rows], [a["tick_id"]])
        self.assertEqual([n for n, _ in bad], [2, 3])                 # one entry a line: line 3's names both rescued objects not rows
        self.assertIn("2 parsed object(s) on it not a row", bad[1][1])

    def test_two_whole_rows_that_lost_their_newline_are_both_kept(self):
        # the older writer could lose exactly the newline between two whole rows (a crash after the
        # row's bytes, before its newline): neither row is torn, so both are read, in order, and the
        # line is one skipped line whose reason says so (make health's count; bin/readers-diff's "kept")
        p = os.path.join(tempfile.mkdtemp(), "d.jsonl")
        a, b, c = _row(0, 100.0), _row(60, 101.0), _row(120, 102.0)
        with open(p, "w") as fh:
            fh.write(json.dumps(a, separators=(",", ":")))                  # whole, no newline
            fh.write(json.dumps(b, separators=(",", ":")) + "\n")            # glued onto it
            fh.write(json.dumps(c, separators=(",", ":")) + "\n")
        bad = []
        rows = outcomes.load(p, bad)
        self.assertEqual([r["tick_id"] for r in rows], [a["tick_id"], b["tick_id"], c["tick_id"]])
        self.assertEqual(rows[0], a)
        self.assertEqual([(n, "two whole rows on one line (a lost newline), both kept" in why) for n, why in bad], [(1, True)])
        # a head that parses but is not a row is not a row: the tail alone is kept, and the head is named
        with open(p, "w") as fh:
            fh.write('{"v":1}' + json.dumps(b, separators=(",", ":")) + "\n")
        bad = []
        rows = outcomes.load(p, bad)
        self.assertEqual([r["tick_id"] for r in rows], [b["tick_id"]])
        self.assertEqual([n for n, _ in bad], [1])                   # one entry for the line, naming both
        self.assertIn("the whole row appended onto the torn line is kept; 1 parsed object(s) on it not a row", bad[0][1])

    def test_any_number_of_whole_rows_on_one_line_are_all_read_in_order(self):
        # three whole rows that lost two newlines; a torn head before two whole rows; objects that parse
        # but are not rows: every whole row is read once, in order, and each line is ONE skip entry
        p = os.path.join(tempfile.mkdtemp(), "d.jsonl")
        rs = [_row(60 * k, 100.0 + k) for k in range(6)]
        j = lambda r: json.dumps(r, separators=(",", ":"))
        with open(p, "w") as fh:
            fh.write(j(rs[0]) + j(rs[1]) + j(rs[2]) + "\n")                # 3 whole rows, no newlines between
            fh.write(j(rs[3])[:50] + j(rs[4]) + j(rs[5]) + "\n")           # torn, then 2 whole rows
            fh.write('{"v":1}{"v":1}\n')                                    # two objects, neither a row
        bad = []
        rows = outcomes.load(p, bad)
        self.assertEqual(rows, [rs[0], rs[1], rs[2], rs[4], rs[5]])
        self.assertEqual([n for n, _ in bad], [1, 2, 3])
        self.assertIn("3 whole rows on one line (lost newlines), all kept", bad[0][1])
        self.assertIn("two whole rows on one line (a lost newline), both kept", bad[1][1])
        self.assertNotIn("kept", bad[2][1])
        self.assertIn("2 parsed object(s) on it not a row", bad[2][1])

    def test_a_row_start_inside_a_row_never_yields_a_wrong_row(self):
        # a nested object whose first key is "v" (answers are stored verbatim) puts a row start inside
        # a row; glued after a torn line the split lands inside it, the piece does not parse, and the
        # row is lost -- never read as some other row
        p = os.path.join(tempfile.mkdtemp(), "d.jsonl")
        a, b = _row(0, 100.0), dict(_row(60, 101.0), answers={"x": {"v": 1}})
        with open(p, "w") as fh:
            fh.write(json.dumps(a, separators=(",", ":"))[:30] + json.dumps(b, separators=(",", ":")) + "\n")
        bad = []
        rows = outcomes.load(p, bad)
        self.assertEqual(rows, [])
        self.assertEqual(len(bad), 1)
        with open(p, "w") as fh:                                           # on a line of its own it is read
            fh.write(json.dumps(b, separators=(",", ":")) + "\n")
        self.assertEqual(outcomes.load(p), [b])

    def test_a_long_line_of_glued_rows_costs_no_recursion(self):
        p = os.path.join(tempfile.mkdtemp(), "d.jsonl")
        rs = [_row(60 * k, 100.0) for k in range(1500)]
        with open(p, "w") as fh:
            fh.write("".join(json.dumps(r, separators=(",", ":")) for r in rs) + "\n")
        self.assertEqual(len(outcomes.load(p)), 1500)

    def test_missing_file_raises(self):
        with self.assertRaises(OSError):
            outcomes.load(os.path.join(tempfile.mkdtemp(), "nope.jsonl"))

    def test_load_then_join(self):
        p = self._write([json.dumps(_row(60 * i, 100.0 + i)) for i in range(16)])
        rows = outcomes.load(p)
        self.assertEqual(outcomes.join(rows)[rows[0]["tick_id"]]["mid_h"], 115.0)


class Clock(unittest.TestCase):
    def test_ts_epoch(self):
        self.assertEqual(outcomes.ts_epoch("2026-09-23T10:00:00.250Z"), T0.timestamp() + 0.25)
        self.assertEqual(outcomes.ts_epoch("2026-09-23T10:00:00"), T0.timestamp())     # naive = UTC
        self.assertEqual(outcomes.ts_epoch("2026-09-23T12:00:00+02:00"), T0.timestamp())
        self.assertIsNone(outcomes.ts_epoch("yesterday"))
        self.assertIsNone(outcomes.ts_epoch(None))
        self.assertIsNone(outcomes.ts_epoch(1758621600))


class LoadGuards(unittest.TestCase):
    def test_a_tick_id_that_is_not_a_minute_is_skipped_not_crashed(self):
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "d.jsonl")
        with open(p, "w") as fh:
            fh.write('{"tick_id": "20260923T100000Z", "ts_rx": "2026-09-23T10:00:00.100Z", "mid": 1.0}\n')
            fh.write('{"tick_id": "nonsense", "ts_rx": "2026-09-23T10:01:00.100Z", "mid": 1.0}\n')
            fh.write('{"tick_id": "20260923T100230Z", "ts_rx": "2026-09-23T10:02:30.100Z", "mid": 1.0}\n')   # not floored: parseable, kept
            fh.write('{"tick_id": "20260923T100300Z", "ts_rx": "not a time", "mid": 1.0}\n')
        bad = []
        rows = outcomes.load(p, bad)
        self.assertEqual([r["tick_id"] for r in rows], ["20260923T100000Z", "20260923T100230Z"])
        self.assertEqual([n for n, _ in bad], [2, 4])
        self.assertTrue(all("not a row" in why for _, why in bad))


if __name__ == "__main__":
    unittest.main()

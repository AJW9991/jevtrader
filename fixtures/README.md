# fixtures/ — ONE recorded Coinbase snapshot set

Recorded from this Mac, candles and trades at **2026-09-24T02:28:49Z** (epoch
`1790216929`), the book re-recorded at **2026-09-24T04:51:41Z** (epoch `1790225501`) with
100 levels a side (see "What changed" below); Coinbase Advanced Trade PUBLIC market-data
endpoints, no key, no signature. `tests/test_feed.py`
loads these files and mocks `urllib.request.urlopen`; nothing under `tests/` opens a
socket. Do not re-record casually: `meta.json` → `expect` and the tests pin the numbers
in this set.

| file | what | bytes |
|---|---|---|
| `book.json` | `product_book?limit=100` — 100 bid and 100 ask levels, best first, with the venue's book time (re-recorded 2026-09-24T04:51:41Z) | 8,421 |
| `candles.json` | 350 `ONE_MINUTE` candles for the 350 minutes ending at the recording minute | 40,688 |
| `trades.json` | every trade in `[ts_rx-300, ts_rx]` via the `ticker` endpoint (532 rows) | 98,078 |
| `meta.json` | `ts_rx_epoch` the parsers use, the book's own recording time, the three exact URLs, and the pinned expectations | — |

## What changed, 2026-09-24T04:51:41Z: the book, and only the book

`liq` is now the cost of walking the book for one `NOTIONAL_USD` = $1,000 order
(`fill1k_bps`, SPEC §4–§5; decided by Alex 2026-09-24), so `feed.py` asks for
`limit=100` (`config.BOOK_LEVELS`) and the Snapshot carries `bids` / `asks`. The old
`book.json` was `limit=1` and could not be walked; it was replaced by one fresh 100-level
recording (HTTP 200, 0.223 s, 8,421 bytes). `candles.json`, `trades.json` and `ts_rx_epoch`
are unchanged, so the book is ~2 h 23 min younger than the candles: its mid (114.96) is not
the candles' last close (114.78). Nothing reads the two together except `features()`, which
takes `mid` from the book and every return from the candles, as it does live; no test
depends on them agreeing. What the new book pins (`meta.json` → `expect`): L1 114.95 ×
205.27970493 / 114.97 × 114.88 (l1_min_usd $13,208), 100 levels a side ending at 113.67 /
116.25, $118,730 bid and $163,207 ask within 5 bps of mid, `fill1k_bps` 0.8698677800991063
(the $1,000 fills at level 1 on both sides, so it is the half-spread) → `liq` deep.

## The exact commands (bash, UTC; all HTTP 200; 0.223 s, 0.223 s, 0.224 s)

```bash
# the book, 2026-09-24T04:51:41Z (epoch 1790225501): 100 levels a side
curl -sS -w '%{http_code} %{time_total}s %{size_download}B\n' -o book.json 'https://api.coinbase.com/api/v3/brokerage/market/product_book?product_id=SOL-USD&limit=100'
# candles and trades, 2026-09-24T02:28:49Z; T0 -> T1 < 1 s
T0=1790216929      # $(date -u +%s) at 2026-09-24T02:28:49Z
curl -sS -o candles.json "https://api.coinbase.com/api/v3/brokerage/market/products/SOL-USD/candles?start=$((T0-350*60))&end=$T0&granularity=ONE_MINUTE"
curl -sS -o trades.json  "https://api.coinbase.com/api/v3/brokerage/market/products/SOL-USD/ticker?limit=1000&start=$((T0-300))&end=$T0"
```

These are byte-for-byte the URLs `loop/feed.py::snapshot()` builds (`meta.json` holds
them; `test_urls_three_calls_no_retry` asserts equality). Offline replay of this set:
`python3 -m loop.feed --fixtures fixtures` → the Snapshot with `http: {calls: 0, ms: 0}`.

## Response shapes observed (verbatim)

**product_book** — every number is a string; `time` is the venue's book timestamp; with
`limit=100` each side is 100 levels, best first (bids price-descending, asks ascending, as
recorded; `feed.py` sorts anyway):
```
{"pricebook":{"product_id":"SOL-USD", "bids":[{"price":"114.95", "size":"205.27970493"}, {"price":"114.94", "size":"222.27527608"}, … 100 levels … {"price":"113.67", "size":"0.42"}], "asks":[{"price":"114.97", "size":"114.88"}, {"price":"114.98", "size":"448.8961656"}, … {"price":"116.25", "size":"4.86702943"}], "time":"2026-09-24T04:51:41.177886Z"}, "last":"114.96", "mid_market":"114.96", "spread_bps":"1.739584239367", "spread_absolute":"0.02"}
```

**candles** — `{"candles": [...]}`, NEWEST FIRST, every number a string. Row 0 is the
OPEN minute (`start == T0//60*60 == 1790216880`; its volume keeps growing until :00), so
350 rows for a 350-minute span give **349 closed** rows. Rows were contiguous (0 missing
minutes) in every probe, but the venue does not promise that; `feed.py` sorts and never fills.
```
row 0 (open):  {"start": "1790216880", "low": "114.72", "high": "114.84", "open": "114.78", "close": "114.82", "volume": "3340.24251431"}
row 1:         {"start": "1790216820", "low": "114.75", "high": "114.8", "open": "114.79", "close": "114.78", "volume": "73.46484864"}
row 349:       {"start": "1790195940", "low": "114.35", "high": "114.41", "open": "114.35", "close": "114.41", "volume": "165.98328507"}
```

**ticker** — `{"trades": [...], "best_bid": "114.8", "best_ask": "114.82"}`, trades NEWEST
FIRST. `bid`/`ask` per trade are empty strings; `time` is ISO-8601 `Z` with 6 fractional
digits; `trade_id` is NOT monotonic in time order (observed in this set).
```
row 0 (newest): {"trade_id": "354980478", "product_id": "SOL-USD", "price": "114.8", "size": "0.02613696", "time": "2026-09-24T02:28:45.725274Z", "side": "BUY", "bid": "", "ask": "", "exchange": "coinbase"}
row 531:        {"trade_id": "354979947", "product_id": "SOL-USD", "price": "114.88", "size": "0.17357242", "time": "2026-09-24T02:23:50.184479Z", "side": "SELL", "bid": "", "ask": "", "exchange": "coinbase"}
```

## What the probes established (02:25–02:58Z, 2026-09-24; ~12 requests total)

- `ticker` WITHOUT `start`/`end` returns at most **100** rows whatever `limit` says
  (`limit=100`, `500`, `1000` all → 100 rows, oldest 82–97 s old). WITH `start`/`end` it
  returns up to `limit` rows inside the window (471, then 532, then 766 in a 5-min window).
  When the window holds more than `limit`, it keeps the **NEWEST** (`limit=5` over 30 min →
  the 5 newest). So `trades_5m` is exact below 1000 and reads "≥ 1000" at 1000.
- `candles` with `end = now` includes the current open minute on top. Requesting a
  350-minute span returned exactly 350 rows (the venue's per-call maximum).
- Python's default `User-Agent` (`Python-urllib/3.14`) is accepted: HTTP 200, 180 ms.
- Per-call latency 0.16–0.22 s (curl) and 620 ms for all three inside `snapshot()` live.
- Rate limit: Coinbase documents 10 public requests/s per IP. `snapshot()` sends 3 per
  60 s tick = 0.05 req/s.
- A live `snapshot()` at 02:58:16Z returned 349 candles, `trades_5m` 766, `feed_age_s`
  16.9 (ts_rx minus the newest closed candle's `start+60`).
- Coinbase's fee-schedule pages (`coinbase.com/advanced-fees`, `help.coinbase.com/.../fees`)
  answer HTTP 403 to `curl` and to WebFetch (Cloudflare); `/advanced-fees` redirects a
  browser to login. The rate is reported in the build return, not here.

## Re-recording

Only if the venue changes shape, or what `feed.py` requests changes (as the book did on
2026-09-24). Run the commands above (all three with a fresh `T0` for a whole new set), then
update `meta.json` (`ts_rx_epoch`, the three URLs, every `expect` value) and re-run
`python3 -m unittest tests.test_feed tests.test_state tests.test_cycle -v`. Commit the
changed files together.

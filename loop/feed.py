"""Coinbase Advanced Trade PUBLIC market data -> one Snapshot dict (CONTRACT §2).

May: make exactly three unauthenticated GETs per snapshot() (book, candles,
trades) against api.coinbase.com and parse them. May not: retry, sleep, write
anything, read a key, import loop.jev, or talk to any other host. Any HTTP or
parse failure raises FeedError and the caller writes the `absence: "feed"` row.
The one tolerated failure is the trades call (trades_5m = -1): nothing in the
alphabet reads it (flow is candle volume), so a dead ticker must not cost a tick.

Rate: Coinbase allows 10 public requests/s per IP. This module sends 3 per tick
at CADENCE_S = 60, i.e. 0.05 req/s, 200x under the limit. The recorded fixtures
took 0.16-0.22 s per call (fixtures/README.md, 2026-09-24T02:28:49Z).
"""
import datetime as dt
import json
import time
import urllib.error
import urllib.request

from . import config

BASE = "https://api.coinbase.com/api/v3/brokerage/market"   # public: no key, no signature
TIMEOUT_S = 10          # 50x the observed 0.2 s; three calls fit well inside the tick's 50 s watchdog
CANDLES_REQ = 350       # venue max per call. A 350-minute span returned exactly 350 rows, the
                        # top one being the OPEN minute, so 349 close: 49 spare over WINDOW_MIN=300
TRADES_WINDOW_S = 300   # CONTRACT: trades with time >= ts_rx - 300
TRADES_LIMIT = 1000     # the ticker caps at 100 rows WITHOUT start/end and at `limit` WITH them;
                        # a quiet 5 min held 532 trades, so 1000 censors only a bot war, and a
                        # censored window keeps the NEWEST rows (verified 2026-09-24): 1000 = ">= 1000"
MAX_FEED_AGE_S = 120    # feed_age_s is 0-60 when the venue is current and 60-120 with the ONE omitted
                        # quiet newest minute SPEC §3 allows. Past that the window describes
                        # [t-k-15, t-k] while the fill and the mid are at t: a candle set lagging
                        # 8 minutes (feed_age_s 529) still assembled and flipped the fixture's
                        # adjectives (vol normal -> violent, rule_c buy -> sell). Refused, not used.


class FeedError(Exception):
    """One string: what failed and on which endpoint. No retry happens behind it."""


def _iso_ms(epoch):
    d = dt.datetime.fromtimestamp(epoch, dt.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _ep(s):
    """Venue ISO time -> epoch. Coinbase sends 'Z' and 6 fractional digits; a bare
    string (no zone) is taken as UTC rather than the Mac's local time."""
    d = dt.datetime.fromisoformat(s)
    return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).timestamp()


def _get(url):
    """One GET -> parsed JSON. Shape copied from ~/Projects/JEV/bin/jev ask(), lines
    200-215 (Request, urlopen with timeout, json.loads(r.read()), HTTPError first),
    minus the bearer header and the retry loop: the feed never retries."""
    where = url[len(BASE):].split("?")[0]
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        raise FeedError(f"http-{e.code} {where}") from None
    except Exception as e:                      # URLError, timeout, TLS, DNS: all "no feed"
        raise FeedError(f"net {type(e).__name__} {where}") from None
    try:
        return json.loads(body)
    except ValueError as e:
        raise FeedError(f"parse {where}: {e}") from None


def _num(d, k, what):
    try:
        return float(d[k])                      # the venue sends every number as a string
    except (KeyError, TypeError, ValueError):
        raise FeedError(f"parse {what}.{k}") from None


def parse_book(j, product):
    """pricebook.bids[0] / asks[0] -> (bid, bid_size, ask, ask_size, book_time)."""
    try:
        pb = j["pricebook"]
        b, a = pb["bids"][0], pb["asks"][0]
    except (KeyError, IndexError, TypeError):
        raise FeedError("parse book: no L1") from None
    if pb.get("product_id") != product:
        raise FeedError(f"book product {pb.get('product_id')!r} != {product!r}")
    bid, bs = _num(b, "price", "bid"), _num(b, "size", "bid")
    ask, az = _num(a, "price", "ask"), _num(a, "size", "ask")
    if not 0 < bid <= ask or bs <= 0 or az <= 0:   # locked (bid == ask) happens; crossed is garbage
        raise FeedError(f"book crossed or empty: {bid}x{bs} / {ask}x{az}")
    return bid, bs, ask, az, (pb.get("time") or None)


def parse_candles(j, now):
    """Rows CLOSED as of `now` (start + 60 <= now), oldest first, floats. The venue
    sends newest-first with the open minute on top (fixture: top start == now//60*60),
    and the order is not trusted: rows are sorted here."""
    raw = j.get("candles") if isinstance(j, dict) else None
    if not isinstance(raw, list):
        raise FeedError("parse candles: no list")
    rows = []
    for c in raw:
        try:
            s = int(c["start"])
        except (KeyError, TypeError, ValueError):
            raise FeedError("parse candles.start") from None
        if s + 60 <= now:
            rows.append({"start": s, "open": _num(c, "open", "candle"), "high": _num(c, "high", "candle"),
                         "low": _num(c, "low", "candle"), "close": _num(c, "close", "candle"),
                         "volume": _num(c, "volume", "candle")})
    rows.sort(key=lambda r: r["start"])
    if len(rows) < config.WINDOW_MIN:
        raise FeedError(f"candles: {len(rows)} closed rows < {config.WINDOW_MIN}")
    return rows


def check_contiguous(rows):
    """The last WINDOW_MIN closed rows must be one per minute, exactly 60 s apart, or
    FeedError. Coinbase OMITS a minute with no trades instead of sending a zero-volume
    candle, and state.py indexes by position ("15 candles ago" IS "15 minutes ago", the
    blocks are 5 and 15 rows): one missing minute inside the window would make ret15 a
    16-minute return and shift every block, silently. Refused, not filled: a forward-
    filled candle is a number the venue never sent. Only the window is checked -- a gap
    in the 49 spare rows before it is never read. An omitted NEWEST minute is not a gap
    (the window is contiguous and ends a minute earlier); feed_age_s shows it (60-120 s)."""
    w = rows[-config.WINDOW_MIN:]
    for a, b in zip(w, w[1:]):
        if b["start"] - a["start"] != 60:
            raise FeedError(f"candles: not contiguous inside the last {config.WINDOW_MIN}: "
                            f"start {a['start']} -> {b['start']} ({b['start'] - a['start']} s)")


def parse_trades(j, now):
    """Count of trades with time >= now - 300. -1 when there is no trades list."""
    raw = j.get("trades") if isinstance(j, dict) else None
    if not isinstance(raw, list):
        return -1
    cut, n = now - TRADES_WINDOW_S, 0
    for t in raw:
        try:
            ts = _ep(t["time"])                 # "2026-09-24T02:28:45.725274Z"
        except (KeyError, TypeError, ValueError):
            raise FeedError("parse trades.time") from None
        n += ts >= cut
    return n


def assemble(product, now, book_j, candles_j, trades_j, http):
    """Pure: the three payloads -> the Snapshot dict, keys exactly as CONTRACT §2.
    trades_j None (call failed) or unparseable -> trades_5m = -1, never a raise."""
    bid, bid_size, ask, ask_size, book_time = parse_book(book_j, product)
    candles = parse_candles(candles_j, now)
    check_contiguous(candles)
    age = now - (candles[-1]["start"] + 60)
    if age > MAX_FEED_AGE_S:
        raise FeedError(f"candles: newest closed minute is {age:.0f} s old > MAX_FEED_AGE_S {MAX_FEED_AGE_S}")
    try:
        trades_5m = -1 if trades_j is None else parse_trades(trades_j, now)
    except FeedError:
        trades_5m = -1
    return {
        "ts_rx": _iso_ms(now),
        "product": product,
        "bid": bid, "bid_size": bid_size, "ask": ask, "ask_size": ask_size,
        "book_time": book_time,
        "candles": candles,
        "trades_5m": trades_5m,
        "feed_age_s": round(age, 3),
        "http": {"calls": int(http["calls"]), "ms": int(round(http["ms"]))},
    }


def snapshot(product=config.PRODUCT, now=None):
    """Three GETs -> Snapshot. `now` (epoch s) exists for offline tests; live it is this
    machine's clock at ENTRY, which is ts_rx: the decision timestamp is when the tick
    began, so a fetch that straddles :00 cannot move tick_id, and "closed" means
    closed as of that instant. Raises FeedError; no retry, no sleep."""
    now = time.time() if now is None else float(now)
    end = int(now)
    http = {"calls": 0, "ms": 0.0}

    def get(url):
        http["calls"] += 1
        t0 = time.monotonic()
        try:
            return _get(url)
        finally:
            http["ms"] += (time.monotonic() - t0) * 1000.0

    book_j = get(f"{BASE}/product_book?product_id={product}&limit=1")
    candles_j = get(f"{BASE}/products/{product}/candles"
                    f"?start={end - CANDLES_REQ * 60}&end={end}&granularity=ONE_MINUTE")
    try:
        trades_j = get(f"{BASE}/products/{product}/ticker"
                       f"?limit={TRADES_LIMIT}&start={end - TRADES_WINDOW_S}&end={end}")
    except FeedError:
        trades_j = None                         # tolerated; still counted in http.calls
    return assemble(product, now, book_j, candles_j, trades_j, http)


if __name__ == "__main__":                      # probe: prints one Snapshot as JSON
    import os
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--fixtures":      # offline, from a recorded set
        d = sys.argv[2]
        def load(n):
            with open(os.path.join(d, n)) as fh:
                return json.load(fh)
        meta = load("meta.json")
        snap = assemble(meta["product"], float(meta["ts_rx_epoch"]), load("book.json"),
                        load("candles.json"), load("trades.json"), {"calls": 0, "ms": 0})
    elif len(sys.argv) == 1:                                    # live: three public GETs, no key
        snap = snapshot()
    else:
        print("usage: python3 -m loop.feed [--fixtures DIR]", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(snap))

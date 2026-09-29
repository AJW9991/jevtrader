"""Products for tests (PREREG-v2 §2). Until the probe's two products are in config.PRODUCTS, a test that needs
three products adds stand-ins for its lifetime: the first probe candidates not yet in PRODUCTS, each with a tick,
atoms and a thin fallback (illustrative values, not the probe's), the tripwire scaled as config.py computes it
(0.25 x products). Once PRODUCTS holds three, add_products changes nothing. tests/test_products_added.py runs
the whole suite this way. Not a test module: unittest discovers test*.py only."""
from unittest import mock

from loop import config

# per candidate: (TICK_P, (a10, a90), thin fallback) -- illustrative, not the probe's
STAND_IN = {"ETH-USD": (0.01, (1, 3), False), "XRP-USD": (0.0001, (1, 5), True), "DOGE-USD": (0.00001, (1, 4), False),
            "AVAX-USD": (0.01, (2, 6), False), "LINK-USD": (0.001, (1, 4), True), "ADA-USD": (0.0001, (1, 4), False)}


def add_products(tc, n=3):
    """config.PRODUCTS with at least `n` products for the test's lifetime (the class's, when `tc` is the class in
    setUpClass): stand-ins from STAND_IN appended in bin/probe's order. Returns the first `n` products."""
    enter = tc.enterClassContext if isinstance(tc, type) else tc.enterContext
    have = tuple(config.PRODUCTS)
    add = [p for p in config.PROBE_CANDIDATES if p not in have][:max(0, n - len(have))]
    if add:
        per = config.DAILY_SPEND_HALT_USD / len(have)
        enter(mock.patch.dict(config.TICK_P, {p: STAND_IN[p][0] for p in add}))
        enter(mock.patch.dict(config.LIQ_ATOMS, {p: STAND_IN[p][1] for p in add}))
        enter(mock.patch.dict(config.LIQ_THIN_FALLBACK, {p: STAND_IN[p][2] for p in add}))
        enter(mock.patch.object(config, "PRODUCTS", have + tuple(add)))
        enter(mock.patch.object(config, "DAILY_SPEND_HALT_USD", per * (len(have) + len(add))))
    return tuple(config.PRODUCTS)[:n]


def exactly(tc, products):
    """config.PRODUCTS exactly `products` for the test's lifetime (the class's, when `tc` is the class): SOL-USD as
    configured, every other product with its STAND_IN tick, atoms and thin fallback even where config holds the
    probe's real ones, and the tripwire at 0.25 x the products. For a test whose expected bytes must not move when the
    probe's products are added to config.PRODUCTS."""
    enter = tc.enterClassContext if isinstance(tc, type) else tc.enterContext
    add = [p for p in products if p != config.PRODUCT]
    per = config.DAILY_SPEND_HALT_USD / len(config.PRODUCTS)
    enter(mock.patch.dict(config.TICK_P, {p: STAND_IN[p][0] for p in add}))
    enter(mock.patch.dict(config.LIQ_ATOMS, {p: STAND_IN[p][1] for p in add}))
    enter(mock.patch.dict(config.LIQ_THIN_FALLBACK, {p: STAND_IN[p][2] for p in add}))
    enter(mock.patch.object(config, "PRODUCTS", tuple(products)))
    enter(mock.patch.object(config, "DAILY_SPEND_HALT_USD", per * len(products)))
    return tuple(products)

"""A moved wall clock for the whole suite: with this directory on PYTHONPATH and FAKE_NOW set (ISO
UTC, e.g. 2026-10-23T21:56:30Z), every Python process that starts, the suite's subprocesses
included, reads time.time(), time.time_ns(), datetime.datetime.now/utcnow/today and
datetime.date.today as FAKE_NOW plus the real time elapsed since it started. time.monotonic and
sleeps are real. `make test-mode MODE=day-28` (and after-sample, next-year) runs the suite this
way, so a test that reads the real date instead of pinning its clock fails on a date it did not
expect (CLAUDE.md: tests pin their clocks). A subprocess run with python -I ignores PYTHONPATH and
keeps the real clock. Without FAKE_NOW this does nothing."""
import os

_now = os.environ.get("FAKE_NOW")
if _now:
    import datetime as _d
    import time as _t

    _target = _d.datetime.strptime(_now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_d.timezone.utc).timestamp()
    _real = _t.time
    _off = _target - _real()
    _t.time = lambda: _real() + _off
    _t.time_ns = lambda: int((_real() + _off) * 1e9)
    _Base, _DBase = _d.datetime, _d.date

    class _FakeDateTime(_Base):
        @classmethod
        def now(cls, tz=None):
            return _Base.fromtimestamp(_real() + _off, tz)

        @classmethod
        def utcnow(cls):
            return _Base.fromtimestamp(_real() + _off, _d.timezone.utc).replace(tzinfo=None)

        @classmethod
        def today(cls):
            return _Base.fromtimestamp(_real() + _off)

    class _FakeDate(_DBase):
        @classmethod
        def today(cls):
            return _DBase.fromtimestamp(_real() + _off)

    _d.datetime, _d.date = _FakeDateTime, _FakeDate

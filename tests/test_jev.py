"""loop.jev, offline. urllib.request.urlopen is mocked in every test that could send,
and config.JEV_URL is pointed at 127.0.0.1:9 (discard) for the whole class, so a
mock that slipped would be refused by the local kernel, never seen by api.typesafe.ai.
The key is a made-up string in the environment; no real key file is ever read,
because the env entry is first in config.KEY_PATHS and first hit wins."""
import email.message, hashlib, io, json, os, tempfile, unittest, urllib.error, urllib.request, urllib.response
from unittest import mock
from loop import config, jev

KEY = "unit-test-key-not-real-0000"
URL = "http://127.0.0.1:9/v1/systemone"
STATE = "SOL: liquidity thin, flow quiet, trend flat, vol calm"
Q = {"a_action": {"type": "choice", "instructions": "Decide.",
                  "criteria": {"buy": "b", "sell": "s", "hold": "h"}},
     "skip": {"type": "noul", "instructions": "Hostile.", "criteria": {"yes": "y", "no": "n"}}}
GOOD = {"model": config.MODEL, "usage": {"input_tokens": 123, "output_tokens": 7},
        "answers": {"a_action": {"choice": "hold", "probabilities": {"buy": 0.1, "sell": 0.1, "hold": 0.8},
                                 "confidence": 0.8},
                    "skip": {"noul": 0.02}}}


class _Resp:
    """What urlopen yields: a context manager with read()."""
    def __init__(self, doc, raw=None):
        self._b = raw if raw is not None else json.dumps(doc).encode()
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def read(self):
        return self._b


_OPEN = []                                      # every HTTPError built here; closed in tearDown, or 3.14's
                                                # tempfile-backed body warns at GC and drowns the run in noise

def _http(code, retry_after=None):
    h = email.message.Message()
    if retry_after is not None:
        h["Retry-After"] = str(retry_after)
    e = urllib.error.HTTPError(URL, code, "status text", h, io.BytesIO(b""))
    _OPEN.append(e)
    return e


class JevTest(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.sends = os.path.join(self.tmp, "data", "sends.tsv")          # data/ absent, like a fresh clone
        self.enterContext(mock.patch.object(config, "SENDS", self.sends))
        self.enterContext(mock.patch.object(config, "JEV_URL", URL))
        self.enterContext(mock.patch.dict(os.environ, {"TYPESAFE_API_KEY_LOOP": KEY}))
        self.protocol = os.path.join(self.tmp, "PROTOCOL.md")    # signed: these tests are about sending
        with open(self.protocol, "w") as fh:
            fh.write("# PROTOCOL\n\nIn force from: `2026-09-24`  Signed: `test`\n")
        self.enterContext(mock.patch.object(config, "PROTOCOL", self.protocol))
        self.sleeps = []
        self.enterContext(mock.patch("time.sleep", side_effect=self.sleeps.append))
        self.urlopen = self.enterContext(mock.patch("urllib.request.urlopen"))
        self.urlopen.return_value = _Resp(GOOD)

    def tearDown(self):
        while _OPEN:
            _OPEN.pop().close()

    def rows(self):
        if not os.path.exists(self.sends):
            return None
        with open(self.sends) as fh:
            return fh.read().splitlines()

    # --- CONTRACT §6: the ledger row exists BEFORE the request --------------------
    def test_ledger_row_on_disk_before_urlopen(self):
        # "on disk" is the fsync, not the flush: reading the file back from this process sees a
        # flushed row either way, so the order of the fsync of the ledger's own fd is pinned too.
        seen, order, real_fsync = [], [], os.fsync
        def fsync(fd):
            order.append(("fsync", os.fstat(fd).st_ino == os.stat(self.sends).st_ino))
            return real_fsync(fd)
        def fake(req, timeout=None):
            order.append(("urlopen", None))
            seen.append((self.rows(), timeout))
            return _Resp(GOOD)
        self.urlopen.side_effect = fake
        with mock.patch("os.fsync", side_effect=fsync):
            jev.ask(STATE, Q)
        self.assertEqual(order, [("fsync", True), ("urlopen", None)])
        self.assertEqual(len(seen), 1)
        lines, timeout = seen[0]
        self.assertEqual(timeout, config.JEV_TIMEOUT_S)
        self.assertEqual(lines[0], "utc\tsource\tstate_chars\tq_chars\tsha12\tpaths")
        self.assertEqual(len(lines), 2)
        c = lines[1].split("\t")
        self.assertEqual(len(c), 6)
        self.assertRegex(c[0], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(c[1], "jev-paper-loop")
        self.assertEqual(c[2], str(len(STATE)))
        self.assertEqual(c[3], str(len(json.dumps(Q))))
        self.assertEqual(c[4], hashlib.sha256(STATE.encode()).hexdigest()[:12])
        self.assertEqual(c[5], "-")

    def test_ledger_header_once_and_on_empty_file(self):
        os.makedirs(os.path.dirname(self.sends))
        open(self.sends, "a").close()                                     # exists but empty (the reference's fresh-clone case)
        self.assertEqual(jev.ledger(STATE, Q), hashlib.sha256(STATE.encode()).hexdigest()[:12])
        jev.ask(STATE, Q)
        lines = self.rows()
        self.assertEqual(len(lines), 3)
        self.assertEqual(sum(l.startswith("utc\t") for l in lines), 1)

    # --- CONTRACT §6: unwritable ledger -> JevError('ledger'), nothing sent ---------
    def test_unwritable_ledger_raises_and_sends_nothing(self):
        blocker = os.path.join(self.tmp, "blocker")
        open(blocker, "w").close()                                        # a FILE where the data dir must go
        with mock.patch.object(config, "SENDS", os.path.join(blocker, "sends.tsv")):
            self.assertIsNone(jev.ledger(STATE, Q))
            with self.assertRaises(jev.JevError) as cm:
                jev.ask(STATE, Q)
        self.assertEqual(cm.exception.kind, "ledger")
        self.assertEqual(cm.exception.key_path, "env:TYPESAFE_API_KEY_LOOP")
        self.urlopen.assert_not_called()
        self.assertEqual(self.sleeps, [])

    def test_a_ledger_failure_on_the_retry_raises_the_first_attempts_billed_error(self):
        # "ledger" means nothing left and bills 0 (cycle.UNSENT_KINDS); on the retry attempt 1
        # had already left, so the row must carry attempt 1's kind, which the guard bills.
        real = jev.ledger
        for first, kind, status in ((_http(503), "http-5xx", 503), (_http(429, 2), "http-429", 429),
                                    (TimeoutError("timed out"), "timeout", None)):
            with self.subTest(kind=kind):
                calls = []
                def ledger(s, q):
                    calls.append(1)
                    return real(s, q) if len(calls) == 1 else None
                self.urlopen.reset_mock(); self.sleeps.clear()
                self.urlopen.side_effect = [first, AssertionError("the retry was sent")]
                with mock.patch.object(jev, "ledger", side_effect=ledger):
                    with self.assertRaises(jev.JevError) as cm:
                        jev.ask(STATE, Q)
                e = cm.exception
                self.assertEqual((e.kind, e.status, e.key_path), (kind, status, "env:TYPESAFE_API_KEY_LOOP"))
                self.assertIn("retry not sent", e.detail)
                self.assertEqual(len(calls), 2)
                self.assertEqual(self.urlopen.call_count, 1)               # nothing sent unledgered

    # --- CONTRACT §6: 401 -> http-4xx, no retry --------------------------------------
    def test_401_raises_http_4xx_without_retry(self):
        for code in (401, 403, 400, 404, 422):
            self.urlopen.reset_mock()
            self.urlopen.side_effect = _http(code)
            with self.assertRaises(jev.JevError) as cm:
                jev.ask(STATE, Q)
            self.assertEqual(cm.exception.kind, "http-4xx", code)
            self.assertEqual(cm.exception.status, code)
            self.assertEqual(self.urlopen.call_count, 1, code)
            self.assertEqual(self.sleeps, [])
            self.assertNotIn(KEY, str(cm.exception))
        self.assertEqual(len(self.rows()), 1 + 5)                         # one ledger row per attempt

    # --- retry: 429 honours Retry-After, capped at 5 s, exactly once -----------------
    def test_429_retries_once_honouring_retry_after_capped(self):
        self.urlopen.side_effect = [_http(429, 30), _Resp(GOOD)]
        r = jev.ask(STATE, Q)
        self.assertEqual(r["answers"], GOOD["answers"])
        self.assertEqual(self.urlopen.call_count, 2)
        self.assertEqual(self.sleeps, [5.0])                              # 30 s asked, 5 s cap
        self.assertEqual(len(self.rows()), 1 + 2)                         # header + one row per attempt

    def test_429_retry_after_small_and_absent_and_date(self):
        for hdr, want in ((2, 2.0), (None, 1.0), ("Wed, 21 Oct 2026 07:28:00 GMT", 1.0), (0, 0.0)):
            self.sleeps.clear()
            self.urlopen.side_effect = [_http(429, hdr), _Resp(GOOD)]
            jev.ask(STATE, Q)
            self.assertEqual(self.sleeps, [want], hdr)

    def test_429_twice_raises_http_429(self):
        self.urlopen.side_effect = [_http(429, 1), _http(429, 1)]
        with self.assertRaises(jev.JevError) as cm:
            jev.ask(STATE, Q)
        self.assertEqual(cm.exception.kind, "http-429")
        self.assertEqual(cm.exception.status, 429)
        self.assertEqual(self.urlopen.call_count, 2)
        self.assertEqual(self.sleeps, [1.0])

    # --- retry: 5xx once after 1.0 s, then raise ------------------------------------
    def test_500_retries_once_then_raises(self):
        self.urlopen.side_effect = [_http(500), _http(503)]
        with self.assertRaises(jev.JevError) as cm:
            jev.ask(STATE, Q)
        self.assertEqual(cm.exception.kind, "http-5xx")
        self.assertEqual(cm.exception.status, 503)                        # the last attempt's failure
        self.assertEqual(self.urlopen.call_count, 2)
        self.assertEqual(self.sleeps, [1.0])
        self.assertEqual(len(self.rows()), 1 + 2)

    def test_500_then_ok_returns(self):
        self.urlopen.side_effect = [_http(502), _Resp(GOOD)]
        self.assertEqual(jev.ask(STATE, Q)["input_tokens"], 123)
        self.assertEqual(self.sleeps, [1.0])

    def test_timeout_retries_once(self):
        self.urlopen.side_effect = [TimeoutError("timed out"), _Resp(GOOD)]
        self.assertEqual(jev.ask(STATE, Q)["model"], config.MODEL)
        self.assertEqual(self.sleeps, [1.0])
        self.urlopen.reset_mock(); self.sleeps.clear()
        self.urlopen.side_effect = [urllib.error.URLError(TimeoutError("timed out")),
                                    ConnectionRefusedError(61, "refused")]
        with self.assertRaises(jev.JevError) as cm:
            jev.ask(STATE, Q)
        self.assertEqual(cm.exception.kind, "timeout")
        self.assertIn("ConnectionRefusedError", cm.exception.detail)
        self.assertEqual(self.urlopen.call_count, 2)

    # --- parse ------------------------------------------------------------------------
    def test_parse_good_response_returns_the_four_fields(self):
        r = jev.ask(STATE, Q)
        for k in ("answers", "model", "input_tokens", "latency_ms"):
            self.assertIn(k, r)
        self.assertEqual(r["answers"], GOOD["answers"])
        self.assertEqual(r["model"], config.MODEL)
        self.assertEqual(r["input_tokens"], 123)
        self.assertIsInstance(r["input_tokens"], int)
        self.assertIsInstance(r["latency_ms"], int)
        self.assertGreaterEqual(r["latency_ms"], 0)
        self.assertEqual(r["key_path"], "env:TYPESAFE_API_KEY_LOOP")
        self.assertNotIn(KEY, repr(r))
        self.assertEqual(self.urlopen.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_drifted_model_is_still_returned(self):
        d = json.loads(json.dumps(GOOD)); d["model"] = "jev-9.9.9"
        self.urlopen.return_value = _Resp(d)
        self.assertEqual(jev.ask(STATE, Q)["model"], "jev-9.9.9")        # the caller logs drift

    def test_parse_failures_raise_parse_without_retry(self):
        cases = []
        d = json.loads(json.dumps(GOOD)); del d["answers"]; cases.append(_Resp(d))
        d = json.loads(json.dumps(GOOD)); del d["answers"]["skip"]; cases.append(_Resp(d))          # a qid unanswered
        d = json.loads(json.dumps(GOOD)); del d["answers"]["a_action"]["confidence"]; cases.append(_Resp(d))
        d = json.loads(json.dumps(GOOD)); d["answers"]["skip"] = 0.5; cases.append(_Resp(d))         # not an object
        d = json.loads(json.dumps(GOOD)); d["answers"] = []; cases.append(_Resp(d))
        d = json.loads(json.dumps(GOOD)); d["usage"] = {"input_tokens": "lots"}; cases.append(_Resp(d))
        cases.append(_Resp(None, raw=b"<html>502</html>"))
        cases.append(_Resp([1, 2, 3]))
        d = json.loads(json.dumps(GOOD)); d["usage"] = {"input_tokens": float("inf")}; cases.append(_Resp(d))   # Infinity: OverflowError
        for resp in cases:
            self.urlopen.reset_mock(); self.sleeps.clear()
            self.urlopen.return_value = resp
            with self.assertRaises(jev.JevError) as cm:
                jev.ask(STATE, Q)
            self.assertEqual(cm.exception.kind, "parse", resp.read())
            self.assertEqual(self.urlopen.call_count, 1)
            self.assertEqual(self.sleeps, [])

    def test_missing_usage_counts_zero_tokens(self):
        d = json.loads(json.dumps(GOOD)); del d["usage"]
        self.urlopen.return_value = _Resp(d)
        self.assertEqual(jev.ask(STATE, Q)["input_tokens"], 0)

    def test_null_input_tokens_keeps_the_paid_answer_at_zero_tokens(self):
        # SPEC §12: input_tokens is 0 when absent. A JSON null is absent, not a parse
        # failure: the answer is complete and was paid for (the guard bills it anyway).
        for usage in ({"input_tokens": None, "output_tokens": 7}, None):
            with self.subTest(usage=usage):
                d = json.loads(json.dumps(GOOD)); d["usage"] = usage
                self.urlopen.return_value = _Resp(d)
                r = jev.ask(STATE, Q)
                self.assertEqual(r["answers"], GOOD["answers"])
                self.assertEqual(r["input_tokens"], 0)
                self.assertIsInstance(r["input_tokens"], int)

    # --- the body: --dry prints exactly what live sends --------------------------------
    def test_dry_payload_is_the_sent_body(self):
        got = {}
        def fake(req, timeout=None):
            got["req"] = req
            return _Resp(GOOD)
        self.urlopen.side_effect = fake
        jev.ask(STATE, Q)
        req = got["req"]
        body = json.loads(req.data)
        self.assertEqual(body, jev.dry_payload(STATE, Q))
        self.assertEqual(list(body), ["model", "state", "questions"])
        self.assertEqual(body["model"], config.MODEL)
        self.assertEqual(body["state"], STATE)
        self.assertEqual(body["questions"], Q)
        self.assertEqual(req.full_url, URL)
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Authorization"), "Bearer " + KEY)
        self.assertEqual(req.get_header("Content-type"), "application/json")
        self.assertNotIn(KEY.encode(), req.data)

    def test_dry_payload_needs_no_key_no_ledger_no_socket(self):
        with mock.patch.object(config, "KEY_PATHS", (("env", "NO_SUCH_VAR_JEV_TEST"),)):
            p = jev.dry_payload(STATE, Q)
        self.assertEqual(p, {"model": config.MODEL, "state": STATE, "questions": Q})
        self.assertIsNone(self.rows())
        self.urlopen.assert_not_called()

    # --- key(): order, name-only, file forms, no-key ------------------------------------
    def test_key_prefers_loop_env_and_names_the_path_only(self):
        self.assertEqual(jev.key(), (KEY, "env:TYPESAFE_API_KEY_LOOP"))

    def test_key_file_forms_and_order(self):
        f = os.path.join(self.tmp, "k")
        name = "file:" + f.replace(os.path.expanduser("~"), "~", 1)
        paths = (("env", "NO_SUCH_VAR_JEV_TEST"), ("file", f), ("env", "TYPESAFE_API_KEY_LOOP"))
        for text, want in (("  plain-value  \n", "plain-value"),
                           ("TYPESAFE_API_KEY_LOOP=\"quoted=with=equals\"\n", "quoted=with=equals"),
                           ("\n\n  second-line\n", "second-line"),
                           ("sk_ABC==\n", "sk_ABC==")):                    # base64 padding is not a NAME= line
            with open(f, "w") as fh:
                fh.write(text)
            with mock.patch.object(config, "KEY_PATHS", paths):
                self.assertEqual(jev.key(), (want, name), text)
        with open(f, "w") as fh:
            fh.write("\n")                                                 # empty file: fall through to the next
        with mock.patch.object(config, "KEY_PATHS", paths):
            self.assertEqual(jev.key(), (KEY, "env:TYPESAFE_API_KEY_LOOP"))

    def test_no_key_raises_before_ledger_or_send(self):
        paths = (("env", "NO_SUCH_VAR_JEV_TEST"), ("file", os.path.join(self.tmp, "absent")))
        with mock.patch.object(config, "KEY_PATHS", paths):
            with self.assertRaises(jev.JevError) as cm:
                jev.ask(STATE, Q)
        self.assertEqual(cm.exception.kind, "no-key")
        self.assertIsNone(cm.exception.key_path)
        self.assertIn("NO_SUCH_VAR_JEV_TEST", cm.exception.detail)
        self.assertIsNone(self.rows())
        self.urlopen.assert_not_called()

    def test_key_with_whitespace_or_control_chars_is_refused_by_path_not_value(self):
        # http.client refuses a header with an embedded newline with a ValueError whose
        # message quotes 'Bearer <key>': the value must never get that far.
        for bad in ("FAKEKEY-abc123\nsecond-line", "FAKEKEY abc123", "FAKEKEY\x1babc", "FAKEKEY-\u00e9"):
            with self.subTest(bad=bad), mock.patch.dict(os.environ, {"TYPESAFE_API_KEY_LOOP": bad}):
                with self.assertRaises(jev.JevError) as cm:
                    jev.ask(STATE, Q)
                self.assertEqual(cm.exception.kind, "no-key")
                self.assertIn("env:TYPESAFE_API_KEY_LOOP", cm.exception.detail)
                self.assertNotIn("FAKEKEY", str(cm.exception) + repr(vars(cm.exception)))
        self.assertIsNone(self.rows())                                 # nothing ledgered, nothing sent
        self.urlopen.assert_not_called()

    def test_a_key_file_that_is_not_utf8_is_no_key_naming_its_path(self):
        # UnicodeDecodeError used to escape key() and the tick logged a billed `unexpected`
        # with key_path null. SPEC §2: an unusable key is no-key, naming its path. The error's
        # .object is the file's raw bytes, so it must not ride along as __context__ either.
        f = os.path.join(self.tmp, "k16")
        with open(f, "w", encoding="utf-16") as fh:
            fh.write("FAKEKEY-utf16-abc123\n")
        name = "file:" + f.replace(os.path.expanduser("~"), "~", 1)
        with mock.patch.object(config, "KEY_PATHS", (("file", f), ("env", "TYPESAFE_API_KEY_LOOP"))):
            with self.assertRaises(jev.JevError) as cm:
                jev.ask(STATE, Q)
        e = cm.exception
        self.assertEqual(e.kind, "no-key")                             # not a fall-through to the env key
        self.assertEqual(e.detail, name + " is not UTF-8 text")
        self.assertIsNone(e.__context__)
        self.assertNotIn("FAKEKEY", str(e) + repr(vars(e)))
        self.assertIsNone(self.rows())                                 # nothing ledgered, nothing sent
        self.urlopen.assert_not_called()

    def test_a_local_valueerror_in_the_send_never_carries_its_message(self):
        # the second belt: whatever http.client raises locally is withheld, not chained
        self.urlopen.side_effect = ValueError("Invalid header value b'Bearer %s\\nx'" % KEY)
        with self.assertRaises(jev.JevError) as cm:
            jev.ask(STATE, Q)
        e = cm.exception
        self.assertEqual(e.kind, "parse")
        self.assertIsNone(e.__cause__)
        self.assertTrue(e.__suppress_context__)
        self.assertIsNone(e.__context__)                               # not merely hidden: not kept at all
        self.assertNotIn(KEY, str(e) + repr(vars(e)))
        self.assertEqual(self.urlopen.call_count, 1)                   # no retry
        self.assertEqual(len(self.rows()), 2)                          # header + the attempt's ledger row

    # --- a redirect never carries the key anywhere -----------------------------------------
    def test_a_302_is_http_4xx_with_its_status_and_no_second_request(self):
        self.urlopen.side_effect = _http(302)
        with self.assertRaises(jev.JevError) as cm:
            jev.ask(STATE, Q)
        self.assertEqual((cm.exception.kind, cm.exception.status), ("http-4xx", 302))
        self.assertEqual(self.urlopen.call_count, 1)
        self.assertEqual(self.sleeps, [])
        self.assertEqual(len(self.rows()), 1 + 1)                          # header + the one attempt

    def test_a_redirect_through_the_real_handler_chain_is_refused_not_followed(self):
        # No socket: a stand-in HTTPHandler answers with a 302 to another host (and a 200
        # there), and urlopen is routed through an opener built as jev builds its own. The
        # authorised POST is seen once and never re-sent; an unauthenticated GET (the
        # feed's kind) is still followed.
        seen = []

        class Fake(urllib.request.HTTPHandler):
            def http_open(self, req):
                seen.append((req.full_url, req.get_header("Authorization")))
                there = "elsewhere" in req.full_url
                h = email.message.Message()
                if not there:
                    h["Location"] = RedirectHandlerTest.LOC
                r = urllib.response.addinfourl(io.BytesIO(b"{}"), h, req.full_url, code=200 if there else 302)
                r.msg = "OK" if there else "Found"
                return r
        opener = urllib.request.build_opener(jev._NoAuthRedirect, Fake)
        self.urlopen.side_effect = lambda req, timeout=None: opener.open(req, timeout=timeout)
        with self.assertRaises(jev.JevError) as cm:
            jev.ask(STATE, Q)
        self.assertEqual((cm.exception.kind, cm.exception.status), ("http-4xx", 302))
        if isinstance(cm.exception.__context__, urllib.error.HTTPError):
            _OPEN.append(cm.exception.__context__)
        self.assertEqual(seen, [(URL, "Bearer " + KEY)])                   # once, to the patched URL only
        self.assertEqual(len(self.rows()), 1 + 1)
        seen.clear()
        with opener.open(urllib.request.Request("http://127.0.0.1:9/feed"), timeout=1) as r:
            self.assertEqual(r.geturl(), RedirectHandlerTest.LOC)
        self.assertEqual(seen, [("http://127.0.0.1:9/feed", None), (RedirectHandlerTest.LOC, None)])

    def test_nothing_on_disk_or_in_errors_carries_the_key(self):
        self.urlopen.side_effect = [_http(401)]
        with self.assertRaises(jev.JevError) as cm:
            jev.ask(STATE, Q)
        self.assertNotIn(KEY, str(cm.exception) + repr(vars(cm.exception)))
        with open(self.sends) as fh:
            self.assertNotIn(KEY, fh.read())


class RedirectHandlerTest(unittest.TestCase):
    """urllib's stock redirect handler re-sends a 301/302/303 to any Location with every
    header copied, the bearer key included. jev installs its own at import."""
    LOC = "http://elsewhere.example/steal"

    def _req(self, auth, data=b"{}"):
        h = {"Content-Type": "application/json"}
        if auth:
            h["Authorization"] = "Bearer " + KEY
        return urllib.request.Request(URL, data=data, headers=h)

    def _hdrs(self):
        h = email.message.Message()
        h["Location"] = self.LOC
        return h

    def test_refuses_a_request_carrying_authorization(self):
        h = jev._NoAuthRedirect()
        for code in (301, 302, 303, 307, 308):
            for data in (b"{}", None):                                     # the POST, and a GET as well
                with self.subTest(code=code, post=data is not None):
                    self.assertIsNone(h.redirect_request(self._req(True, data), None, code, "Found",
                                                         self._hdrs(), self.LOC))

    def test_delegates_to_the_stock_handler_without_authorization(self):
        h = jev._NoAuthRedirect()
        req = self._req(False)
        with mock.patch.object(urllib.request.HTTPRedirectHandler, "redirect_request",
                               return_value="followed") as parent:
            self.assertEqual(h.redirect_request(req, None, 302, "Found", self._hdrs(), self.LOC), "followed")
        parent.assert_called_once_with(req, None, 302, "Found", mock.ANY, self.LOC)
        new = h.redirect_request(urllib.request.Request("https://api.coinbase.com/a"), None, 302, "Found",
                                 self._hdrs(), "https://api.coinbase.com/b")
        self.assertEqual(new.full_url, "https://api.coinbase.com/b")      # the real parent: a plain GET follows

    def test_the_process_wide_opener_carries_it_after_import(self):
        import loop.jev                                                    # imported above: its install stands
        op = urllib.request._opener
        self.assertIsInstance(op, urllib.request.OpenerDirector)
        redirects = [x for x in op.handlers if isinstance(x, urllib.request.HTTPRedirectHandler)]
        self.assertEqual([type(x) for x in redirects], [loop.jev._NoAuthRedirect])


class SignatureGateTest(unittest.TestCase):
    """PROTOCOL.md says nothing sends before Alex signs it. jev.ask enforces that before
    the key is read, the ledger is written or a socket is opened."""
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.sends = os.path.join(self.tmp, "sends.tsv")
        self.protocol = os.path.join(self.tmp, "PROTOCOL.md")
        self.enterContext(mock.patch.object(config, "SENDS", self.sends))
        self.enterContext(mock.patch.object(config, "PROTOCOL", self.protocol))
        self.enterContext(mock.patch.dict(os.environ, {"TYPESAFE_API_KEY_LOOP": KEY}))
        self.urlopen = self.enterContext(mock.patch("urllib.request.urlopen",
                                                    side_effect=AssertionError("urlopen was reached")))
        self.key = self.enterContext(mock.patch.object(jev, "key", wraps=jev.key))

    def _write(self, line):
        with open(self.protocol, "w") as fh:
            fh.write("# PROTOCOL\n\n## 5. Signature\n\n" + line + "\n")

    def test_the_real_protocol_has_exactly_one_parseable_signature_line(self):
        # Was "the repo as committed is unsigned" until Alex signed on 2026-09-24. What must
        # hold for good: the gate can find the line, so rewording PROTOCOL.md cannot turn
        # the gate into a permanent "unsigned" (or, worse, match a second line).
        with open(os.path.join(config.REPO, "PROTOCOL.md"), encoding="utf-8") as fh:
            self.assertEqual(len(jev._SIG.findall(fh.read())), 1)
        # and the gate says SIGNED on it: both fields carry text (a blanked line would still match)
        with mock.patch.object(config, "PROTOCOL", os.path.join(config.REPO, "PROTOCOL.md")):
            self.assertTrue(jev.signed())


    def test_unsigned_forms_refuse_before_key_ledger_or_socket(self):
        for line in ("In force from: `____________`  Signed: `____________`",
                     "In force from: ``  Signed: ``",
                     "In force from: `  `  Signed: `alex`",
                     "In force from: `2026-09-24`  Signed: `___`",
                     "no signature line at all"):
            with self.subTest(line=line):
                self._write(line)
                self.assertFalse(jev.signed())
                with self.assertRaises(jev.JevError) as cm:
                    jev.ask(STATE, Q)
                self.assertEqual(cm.exception.kind, "unsigned")
                self.key.assert_not_called()
                self.urlopen.assert_not_called()
                self.assertFalse(os.path.exists(self.sends))

    def test_missing_protocol_is_unsigned(self):
        self.assertFalse(jev.signed())

    def test_both_fields_filled_is_signed(self):
        self._write("In force from: `2026-09-24`  Signed: `Alex Ward`")
        self.assertTrue(jev.signed())

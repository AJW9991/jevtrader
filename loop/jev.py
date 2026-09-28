"""Ledger-first send to Jev. The only file in this repo that sees the key.

May: resolve the key (config.KEY_PATHS, first hit wins), append one row to
data/sends.tsv for each attempt BEFORE that attempt, POST one state and one
question set to config.JEV_URL, and parse the reply into plain values.
May not: print, log, return or raise the key's VALUE -- its path is named, in
key_path, so a row can say which key answered; retry more than once; act on an
answer (rules.py derives the columns, report.py compares them); read prompts/,
decisions.jsonl, or anything under the crypto repo. dry_payload() builds the exact
body with no key, no ledger row and no socket: the --dry tick and every test go
through it, and the live send serialises the same dict.

Copied in shape from ~/Projects/JEV/bin/jev and never imported (it exits at
import without a key): key() from lines 126-136; the ledger row, its header and
the fail-closed append from _log() lines 173-183; the two-attempt loop and the
4xx/5xx split of ask() lines 189-222.
"""
import datetime, hashlib, http.client, json, os, re, time, urllib.error, urllib.request
from loop import config

SOURCE = "jev-paper-loop"          # ledger `source`; the columns are JEV's DISCLOSURE.tsv so the two files join
HEADER = "utc\tsource\tstate_chars\tq_chars\tsha12\tpaths\n"
RETRY_S = 1.0                      # 5xx / transport failure: ONE retry after 1.0 s (reference line 221)
RETRY_AFTER_CAP_S = 5.0            # 429: honour Retry-After, capped. 20 s request + 5 s wait + 20 s request
                                   # = 45 s, the most that fits under cycle.py's 50 s watchdog
TRANSIENT = (TimeoutError, urllib.error.URLError, http.client.HTTPException, OSError)
_HOME = os.path.expanduser("~")
_ENVLINE = re.compile(r"^[A-Z][A-Z0-9_]*=")   # a key file may hold NAME=value, as the reference accepts (130-133)


class JevError(Exception):
    """kind in {unsigned, no-key, ledger, http-4xx, http-429, http-5xx, timeout, parse}. A transport
    failure that is not literally a timeout (refused, reset, DNS) is reported as `timeout`
    with the real class in detail: the contract's kind set has no other transient slot.
    status is the HTTP code when there was one -- 401/403 mean the caller writes HALT.
    key_path names the key that was used (None if none was found), never its value."""

    def __init__(self, kind, detail="", status=None, key_path=None):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind, self.detail, self.status, self.key_path = kind, detail, status, key_path


class _NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """The stock handler answers a 301/302/303 by re-sending the request as a GET to ANY
    Location -- another host, plain http -- with every header copied, Authorization
    included: one bad redirect would carry the key off to that host, in cleartext, on
    every tick. A request that carries Authorization is therefore never redirected:
    returning None makes urllib raise the 3xx itself as an HTTPError, which ask() reports
    as http-4xx with its status, without a retry. A request without it (the feed's public
    GETs) keeps the stock behaviour."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.has_header("Authorization"):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Installed at import, as the process-wide opener: urllib.request.urlopen() goes through it,
# so the send refuses redirects while the tests' mock of urlopen still stands in front of it.
urllib.request.install_opener(urllib.request.build_opener(_NoAuthRedirect))


def _name(kind, path):
    return f"{kind}:{path.replace(_HOME, '~', 1)}"


def _usable(v):
    """A key is printable ASCII with no whitespace. Anything else is refused BEFORE it
    reaches a header: http.client rejects a value with an embedded newline by raising
    ValueError('Invalid header value %r'), whose message carries 'Bearer <key>' -- a key
    in an env var with an internal newline would otherwise be printed to stderr (the
    launchd log). File keys read one line, so only the env forms can carry one."""
    return v.isascii() and v.isprintable() and not any(ch.isspace() for ch in v)


def key():
    """(value, path_name); first hit in config.KEY_PATHS wins, so a loop-triggered rate
    limit lands on the loop's own key before the brain's. The name is safe to log; the
    value goes into one Authorization header and nowhere else. A first hit that is not
    usable raises no-key naming its PATH; it does not fall through to a shared key. A file
    that is not UTF-8 text is such a hit: no-key, never an exception the tick would log as
    a billed `unexpected`."""
    for kind, path in config.KEY_PATHS:
        if kind == "env":
            v = os.environ.get(path, "").strip()
        else:
            try:
                with open(path, encoding="utf-8") as fh:     # explicit: not the locale's codec
                    text = fh.read()
            except OSError:
                continue
            except UnicodeDecodeError:       # raised below, unchained: its .object is the raw file, the key
                text = None
            if text is None:
                raise JevError("no-key", f"{_name(kind, path)} is not UTF-8 text")
            v = next((l.strip() for l in text.splitlines() if l.strip()), "")
            if _ENVLINE.match(v):
                v = v.split("=", 1)[1].strip().strip("\"'")
        if v:
            if not _usable(v):
                raise JevError("no-key", f"{_name(kind, path)} holds an unusable value "
                                         "(whitespace, a control or a non-ASCII character)")
            return v, _name(kind, path)
    raise JevError("no-key", "looked in " + ", ".join(_name(k, p) for k, p in config.KEY_PATHS))


def _utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ledger(state, questions):
    """One row per ATTEMPT, on disk (fsync) before it. Returns sha12 of the state, or None
    when the row could not be written -- ask() then refuses to send. `paths` is always
    '-': a state is four words from a closed alphabet and cannot name a file; the column
    stays so the file joins with DISCLOSURE.tsv. Header when the file is missing OR
    empty: the reference checks existence only and so never writes one after its own
    `open(LEDGER, "a").close()` on a fresh clone (jev:152)."""
    sha12 = hashlib.sha256(state.encode()).hexdigest()[:12]
    row = "\t".join((_utc(), SOURCE, str(len(state)), str(len(json.dumps(questions))), sha12, "-")) + "\n"
    try:
        d = os.path.dirname(config.SENDS)
        if d:
            os.makedirs(d, exist_ok=True)               # data/ is gitignored: a fresh clone has none
        new = not os.path.exists(config.SENDS) or os.path.getsize(config.SENDS) == 0
        with open(config.SENDS, "a") as fh:
            if new:
                fh.write(HEADER)
            fh.write(row)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        return None
    return sha12


def dry_payload(state, questions):
    """The exact body ask() sends, key order included. No key, no ledger row, no socket."""
    return {"model": config.MODEL, "state": state, "questions": questions}


def _body(payload):
    return json.dumps(payload).encode()


def _retry_after(e):
    h = e.headers.get("Retry-After") if e.headers is not None else None
    try:
        return max(0.0, min(float(h), RETRY_AFTER_CAP_S))
    except (TypeError, ValueError):                     # absent, or the HTTP-date form: wait like any transient
        return RETRY_S


def _why(e):
    return f"{type(e).__name__}: {getattr(e, 'reason', e)}"


def _parse(raw, questions, ms, kpath):
    """The fields the row needs, or JevError('parse'). Every qid asked must be answered
    in its type's shape: rules.columns() indexes those keys blind, and a half answer
    logged as a whole one would be a wrong column, not a missing one."""
    try:
        d = json.loads(raw)
        answers = d["answers"]
        if not isinstance(answers, dict):
            raise TypeError(f"answers is {type(answers).__name__}")
        for qid, q in questions.items():
            a = answers[qid]
            if not isinstance(a, dict):
                raise TypeError(f"{qid} is {type(a).__name__}")
            need = ("noul",) if q.get("type") == "noul" else ("choice", "probabilities", "confidence")
            for f in need:
                if f not in a:
                    raise KeyError(f"{qid}.{f}")
        # output is free (config): input is the spend. Absent OR null is 0 (SPEC §12): a
        # complete, paid answer must not be thrown away over a null count; the spend guard
        # charges a 0 at JEV_TOKENS_IF_UNKNOWN anyway. A string or Infinity is still `parse`.
        tokens = int((d.get("usage") or {}).get("input_tokens") or 0)
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError, RecursionError) as e:
        # ArithmeticError: "input_tokens": Infinity parses to inf and int(inf) is OverflowError;
        # RecursionError: a pathologically nested body. Either would otherwise escape as an
        # unexpected exception from a server that has stopped behaving.
        raise JevError("parse", f"{type(e).__name__}: {e}", key_path=kpath) from None
    return {"answers": answers, "model": d.get("model"), "input_tokens": tokens,
            "latency_ms": ms, "key_path": kpath}


_SIG = re.compile(r"^In force from: `([^`]*)`\s+Signed: `([^`]*)`", re.M)


def signed():
    """True only when PROTOCOL.md's last line carries both fields. PROTOCOL.md says
    nothing here sends before Alex signs it; until 2026-09-24 that rested on nobody
    running a non-dry tick while a key file existed -- and the shared key does exist.
    The check sits in ask(), which every send in cycle and policy_table goes through,
    the same choke-point pattern as JEV's read() guard. A field of underscores or
    blanks is unsigned; an unreadable file is unsigned."""
    try:
        with open(config.PROTOCOL, encoding="utf-8") as fh:
            m = _SIG.search(fh.read())
    except OSError:
        return False
    return bool(m) and all(f.strip().strip("_").strip() for f in m.groups())


def ask(state, questions):
    """One state, one question set, one answer set. Order is fixed: key, body, then per
    attempt: ledger row -> request. Two attempts at most; the second only after a 429
    (Retry-After, capped), a 5xx or a transport failure, never after another 4xx --
    401/403 mean the key is rejected and a resend would only repeat the refusal. A
    retried attempt gets its own ledger row: the ledger counts sends, not decisions.
    latency_ms is the answering request alone; the wait between attempts is ours."""
    if not signed():                                     # before the key is even read
        raise JevError("unsigned", f"{os.path.basename(config.PROTOCOL)} is not signed; nothing sent")
    k, kpath = key()                                     # no key: nothing to ledger, nothing to send
    req = urllib.request.Request(config.JEV_URL, data=_body(dry_payload(state, questions)), headers={
        "Authorization": "Bearer " + k, "Content-Type": "application/json"})
    err = None
    for attempt in (1, 2):
        if ledger(state, questions) is None:
            if err is not None:                          # the retry's row: attempt 1 already left, so its
                                                         # billed kind stands, never "ledger" (billed 0)
                raise JevError(err.kind, f"{err.detail}; retry not sent: cannot append to {config.SENDS}",
                               err.status, kpath)
            raise JevError("ledger", f"cannot append to {config.SENDS}; nothing sent", key_path=kpath)
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=config.JEV_TIMEOUT_S) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                err, wait = JevError("http-429", f"429 {e.reason}", 429, kpath), _retry_after(e)
            elif e.code >= 500:
                err, wait = JevError("http-5xx", f"{e.code} {e.reason}", e.code, kpath), RETRY_S
            else:                                        # also a 3xx: _NoAuthRedirect refused to follow it
                raise JevError("http-4xx", f"{e.code} {e.reason}", e.code, kpath) from None
        except TRANSIENT as e:
            err, wait = JevError("timeout", _why(e), None, kpath), RETRY_S
        except ValueError:
            # Raised locally before a byte leaves (http.client refusing a header or URL). Its
            # message can quote the Authorization header, so it is dropped, never chained.
            raise JevError("parse", "request refused locally (ValueError; message withheld)",
                           key_path=kpath) from None
        else:
            return _parse(raw, questions, int((time.monotonic() - t0) * 1000), kpath)
        if attempt == 1:
            time.sleep(wait)
    raise err

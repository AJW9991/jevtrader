"""loop/looks.py -- data/looks.tsv: every `python3 -m loop.report --unblind` is a look (PREREG-v2 §9.5), and
each is appended here as one line (UTC, argv, HEAD), which RESULTS-v2 §0 reproduces.

The file sits at REPO/data (config.LOOKS, read at call time, so a test that points config.DATA at a temp dir
writes there). It is versioned when it exists (.gitignore). A look that cannot be recorded is not taken:
record() raises OSError and the report refuses to unblind (it never creates data/, so a checkout without one,
the v2 build's worktree, cannot look at all). Standard library only.
"""
import datetime, os, re, shlex, subprocess

from . import config

HEADER = "utc\targv\thead\n"


def head(repo=None):
    """`git rev-parse HEAD` of the repository, or "unknown" when git or the repository cannot say."""
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo or config.REPO, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    h = r.stdout.strip()
    return h if r.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", h) else "unknown"


def record(argv, now=None, path=None, repo=None):
    """Append (UTC, argv, HEAD) to data/looks.tsv, the header first when the file is new; returns the line. argv is
    the report's own arguments, written as the shell would quote them after `python3 -m loop.report`, a tab or a
    newline inside one escaped so the line stays one TSV row. OSError when it cannot be written (no data/ there)."""
    path = config.LOOKS if path is None else path
    when = datetime.datetime.now(datetime.timezone.utc) if now is None else datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
    cmd = shlex.join(["python3", "-m", "loop.report"] + list(argv)).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")
    line = f"{when.strftime('%Y-%m-%dT%H:%M:%SZ')}\t{cmd}\t{head(repo)}\n"
    if not os.path.isdir(os.path.dirname(path) or "."):
        raise FileNotFoundError(2, "no data directory to record the look in", os.path.dirname(path))
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", encoding="utf-8") as fh:
        fh.write((HEADER if new else "") + line)
    return line

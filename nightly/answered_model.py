"""Which Claude model answered the nightly's one `claude -p` call, read AFTER the call from the
CLI's own transcript of that session. The call names no model and stays exactly as it was: a pin
would change the treatment mid-sample (HANDOFF decision 4), so the option Alex approved on
2026-09-28 is to record the model, not to pin it. This only reads what the CLI already wrote.

The CLI keeps a session as <config>/projects/<its cwd, every non-alphanumeric character a '-'>/
<session id>.jsonl, and each assistant line carries message.model. propose.sh runs the call in a
fresh `mktemp -d .../jevloop-claude.XXXXXX`, so that night's project directory ends in
`jevloop-claude-XXXXXX` and holds that one session.

Usage: answered_model.py CONFIG_DIR WORK_DIR. Prints the models found, sorted and comma-separated,
or nothing. Exit 0 always: a CLI that keeps its sessions elsewhere or in another shape makes the
night's log say "unrecorded", never stops the night.

May: list <config>/projects/*<suffix>/*.jsonl and read at most MAX_BYTES of each.
May not: write anything, read any other file, or print anything but model ids (MODEL_ID: an id,
never text from the transcript's messages).
"""
import glob, json, os, re, sys

MAX_BYTES = 16 << 20                                   # one -p call's transcript is kilobytes
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/\[\]-]{0,99}")


def slug(name):
    """The CLI's project-directory form of a path or name: every non-alphanumeric character a '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", name)


def models(config_dir, work_dir):
    """Sorted model ids of the assistant turns in the transcripts of the session run in work_dir."""
    suffix = slug(os.path.basename(os.path.normpath(work_dir)))
    if not suffix.strip("-"):
        return []
    found = set()
    pattern = os.path.join(glob.escape(config_dir), "projects", "*" + glob.escape(suffix), "*.jsonl")
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, "rb") as fh:
                data = fh.read(MAX_BYTES)
        except OSError:
            continue
        for line in data.decode("utf-8", "replace").splitlines():
            try:
                d = json.loads(line)
            except (ValueError, RecursionError):
                continue
            msg = d.get("message") if isinstance(d, dict) and d.get("type") == "assistant" else None
            m = msg.get("model") if isinstance(msg, dict) else None
            if isinstance(m, str) and m != "<synthetic>" and MODEL_ID.fullmatch(m):
                found.add(m)
    return sorted(found)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: answered_model.py CONFIG_DIR WORK_DIR", file=sys.stderr)
        return 0
    try:
        print(",".join(models(argv[0], argv[1])))
    except Exception as e:                             # never the night's failure
        print(f"answered_model: {type(e).__name__}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""nightly/capped.py -- run one command under a cap on AWAKE seconds: the nightly's one claude call.

    python3 -m nightly.capped SECONDS -- CMD [ARG ...]

Exit: the command's own code, and 128 + N when a signal N killed it (as a shell reports it:
subprocess gives -N, and sys.exit(-15) would exit 241, which reads as an ordinary code); 124
when the cap fired (the child's process group is terminated, then killed); 127 when the command
cannot be started; 2 on a usage error. stdin, stdout, stderr and the environment are inherited, so
propose.sh's redirects still apply and the token is never printed or passed on argv.

The command runs in a session and process group of its own, and the cap ends that whole group:
a hung command's own children (a `sleep` in a stub, a helper the CLI forked) used to outlive it,
since only the direct child was terminated. For the same reason a SIGTERM, SIGINT or SIGHUP sent
to capped (launchd stopping the job, ^C at a terminal) is passed on to that group, which no
longer receives them directly, and so is SIGQUIT (^\\); a signal capped itself ignores is left
ignored. When the command exits, whatever it left running in its group is ended too (launchd's
cleanup of the job's group no longer reaches it). ^Z at a terminal stops capped, not the command:
a hand run is stopped with ^C.

Why a cap, and why this clock. launchd never starts a second instance of a job while one is
running, so a `claude -p` that hangs while the machine is awake would silently block every
later night. The cap uses time.monotonic(), which on macOS is mach_absolute_time() and does
NOT advance while the machine sleeps: the night of 2026-09-26, when the Mac slept through a
52-second call for five and a half hours of wall clock and then finished it, is not a
timeout here, and must not be -- that proposal was good."""
import os, signal, subprocess, sys, time

EXIT_CAPPED = 124       # GNU timeout's code, so a log line reads the same either way
GRACE_S = 5.0           # SIGTERM to the group, then up to this long for the child, then SIGKILL to the group
FORWARDED = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT)


def _signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):     # nothing left in the group
        pass


def _end_group(pgid, grace=1.0):
    """After the command has exited: SIGTERM to its process group, then SIGKILL to whatever is left
    after `grace` seconds. A helper it forked and left running used to die with launchd's cleanup of
    the job's group; in a session of its own it would outlive the night. No-op on an empty group."""
    _signal_group(pgid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(0.05)
    _signal_group(pgid, signal.SIGKILL)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 3 or argv[1] != "--":
        sys.stderr.write("usage: python3 -m nightly.capped SECONDS -- CMD [ARG ...]\n")
        return 2
    try:
        cap = float(argv[0])
    except ValueError:
        sys.stderr.write(f"capped: SECONDS must be a number, got {argv[0]!r}\n")
        return 2
    if cap <= 0:
        sys.stderr.write("capped: SECONDS must be positive\n")
        return 2
    cmd = argv[2:]
    child, pending = [], []

    def forward(signum, frame):                             # installed before the start: none is lost in between
        pending.append(signum)
        if child:
            _signal_group(child[0].pid, signum)
    for s in FORWARDED:
        if signal.getsignal(s) != signal.SIG_IGN:
            signal.signal(s, forward)
    t0 = time.monotonic()
    try:
        p = subprocess.Popen(cmd, start_new_session=True)  # its own session, so its own process group (pgid = pid)
    except OSError as e:
        sys.stderr.write(f"capped: cannot start {cmd[0]!r}: {e.strerror}\n")
        return 127
    child.append(p)
    for s in pending:                                       # arrived while it was starting (a repeat is harmless)
        _signal_group(p.pid, s)
    try:
        rc = p.wait(timeout=cap)                            # subprocess counts time.monotonic() too
        _end_group(p.pid)                                   # what it started and left behind: launchd's job-group
        return 128 - rc if rc < 0 else rc                   # cleanup no longer reaches its own session
                                                            # killed by signal N: -N from subprocess, 128 + N out
    except subprocess.TimeoutExpired:
        _signal_group(p.pid, signal.SIGTERM)
        try:
            p.wait(timeout=GRACE_S)
        except subprocess.TimeoutExpired:
            pass
        _signal_group(p.pid, signal.SIGKILL)               # whatever is left: the child, or what it started and left behind
        p.wait()
        sys.stderr.write(f"capped: {cmd[0]!r} exceeded {cap:g} s awake (monotonic {time.monotonic() - t0:.1f} s); killed\n")
        return EXIT_CAPPED


if __name__ == "__main__":
    sys.exit(main())

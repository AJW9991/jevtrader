"""nightly/capped.py -- run one command under a cap on AWAKE seconds: the nightly's one claude call.

    python3 -m nightly.capped SECONDS -- CMD [ARG ...]

Exit: the command's own code, and 128 + N when a signal N killed it (as a shell reports it:
subprocess gives -N, and sys.exit(-15) would exit 241, which reads as an ordinary code); 124
when the cap fired (the child is terminated, then killed); 127 when the command cannot be
started; 2 on a usage error. stdin, stdout, stderr and the environment are inherited, so
propose.sh's redirects still apply and the token is never printed or passed on argv.

Why a cap, and why this clock. launchd never starts a second instance of a job while one is
running, so a `claude -p` that hangs while the machine is awake would silently block every
later night. The cap uses time.monotonic(), which on macOS is mach_absolute_time() and does
NOT advance while the machine sleeps: the night of 2026-09-26, when the Mac slept through a
52-second call for five and a half hours of wall clock and then finished it, is not a
timeout here, and must not be -- that proposal was good."""
import subprocess, sys, time

EXIT_CAPPED = 124       # GNU timeout's code, so a log line reads the same either way
GRACE_S = 5.0           # SIGTERM, then this long, then SIGKILL


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
    t0 = time.monotonic()
    try:
        p = subprocess.Popen(cmd)
    except OSError as e:
        sys.stderr.write(f"capped: cannot start {cmd[0]!r}: {e.strerror}\n")
        return 127
    try:
        rc = p.wait(timeout=cap)                            # subprocess counts time.monotonic() too
        return 128 - rc if rc < 0 else rc                   # killed by signal N: -N from subprocess, 128 + N out
    except subprocess.TimeoutExpired:
        p.terminate()
        try:
            p.wait(timeout=GRACE_S)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        sys.stderr.write(f"capped: {cmd[0]!r} exceeded {cap:g} s awake (monotonic {time.monotonic() - t0:.1f} s); killed\n")
        return EXIT_CAPPED


if __name__ == "__main__":
    sys.exit(main())

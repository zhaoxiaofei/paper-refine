"""DeepSeek Harness mechanics shared by the paper model adapters."""
from __future__ import annotations

import contextlib
import os
import select
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_common.dsh_events import line_turn_end_failed

MAX_DSH_LINE_BYTES = 1 << 20


def _writable(path: Path, adapter: str) -> bool:
    # A fixed probe name is followed when an attacker plants a symlink there,
    # and two adapters sharing a home race on the same path. mkstemp creates an
    # unpredictable name with O_CREAT|O_EXCL and never follows a link.
    try:
        fd, probe = tempfile.mkstemp(prefix=f".paper_{adapter}_write_test_",
                                     dir=str(path))
        os.close(fd)
        os.unlink(probe)
        return True
    except OSError:
        return False


def prepare_dsh_home(adapter: str) -> tuple:
    """Return the home, an error message, and any temporary home to clean up."""
    home = Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh")).expanduser()
    if home.is_dir() and _writable(home, adapter):
        return str(home), "", None
    src = home / "profiles" / "headless"
    if not src.is_dir():
        return "", (f"the dsh profile is missing: {src}; install "
                    f"@deepseek-ai/dsh and create the headless profile"), None
    try:
        tmp = Path(tempfile.mkdtemp(prefix=f"paper-{adapter}-dsh-"))
    except OSError as e:
        return "", (f"cannot create a temporary dsh home ({e}); check TMPDIR and "
                    f"the permissions of the dsh profile {src}"), None
    try:
        dst = tmp / "profiles" / "headless"
        dst.mkdir(parents=True, exist_ok=True)
        for name in ("package.json", "cordis.yml", "cordis.patch.yml",
                     "pnpm-workspace.yaml", "pnpm-lock.yaml"):
            s = src / name
            if s.is_file():
                shutil.copy2(s, dst / name)
        nm = src / "node_modules"
        if nm.is_dir():
            try:
                os.symlink(nm, dst / "node_modules")
            except OSError:
                shutil.copytree(nm, dst / "node_modules", symlinks=True)
        cred = home / ".credentials.yaml"
        if cred.is_file():
            shutil.copy2(cred, tmp / ".credentials.yaml")
    except OSError as e:
        # A read-only/partially copied profile is the documented clean-error
        # case: the callers turn `error` into the install hint and exit 2. It
        # must not escape as an uncaught traceback.
        shutil.rmtree(tmp, ignore_errors=True)
        return "", (f"cannot prepare a writable dsh home from {src}: {e}; fix "
                    f"the profile's permissions or reinstall @deepseek-ai/dsh"), None
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return str(tmp), "", tmp


def _echo_stdout(data: bytes) -> None:
    """Forward child bytes to our stdout, text-mode or buffer."""
    buf = getattr(sys.stdout, "buffer", None)
    if buf is not None:
        buf.write(data)
        buf.flush()
    else:
        sys.stdout.write(data.decode("utf-8", "replace"))
        sys.stdout.flush()


def _dsh_stream(stream):
    """The inherited stream, or DEVNULL when it has no file descriptor.

    pytest's capture object (and any StringIO/pseudo-file a caller installs)
    has no ``fileno()``; handing it to ``Popen`` raises
    ``io.UnsupportedOperation`` instead of a clear error.  Such a caller has no
    prompt to forward, so the child gets an empty stdin and can still stream.
    """
    try:
        stream.fileno()
    except (AttributeError, OSError, ValueError):
        return subprocess.DEVNULL
    return stream


def _dsh_stdin():
    return _dsh_stream(sys.stdin)


def run_dsh_streaming(cmd: list, env: dict, adapter: str) -> tuple:
    """(returncode, turn_failed) with the harness's stdout ECHOED, not buffered.

    `dsh --json` emits one JSON object per line; a verbose harness must not be
    accumulated whole. The stream is read in bounded chunks, echoed as it
    arrives, and only complete lines are parsed.
    """
    proc = subprocess.Popen(cmd, stdin=_dsh_stdin(), stdout=subprocess.PIPE,
                            stderr=_dsh_stream(sys.stderr), env=env)
    turn_failed = None
    saw_turn_end = False
    carry = b""
    terminal = False
    forced_rc = None
    # Read the raw descriptor with a bounded wait instead of blocking in
    # `read1()` until the pipe reaches EOF. `turn_end` is terminal: the old
    # loop kept the adapter blocked for a child that closed stdout but kept
    # running, or for a grandchild that inherited stdout.
    fd = proc.stdout.fileno()
    try:
        while True:
            try:
                ready = select.select([fd], [], [], 0.25)[0]
            except (OSError, ValueError):
                # select() cannot watch this descriptor (e.g. a Windows pipe):
                # keep the old streaming shape for that platform.
                ready = [fd]
            if ready:
                try:
                    chunk = os.read(fd, 1 << 20)
                except BlockingIOError:
                    continue
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                _echo_stdout(chunk)
                carry += chunk
                *lines, carry = carry.split(b"\n")
                for line in lines:
                    failed = line_turn_end_failed(line)
                    if failed is not None:
                        turn_failed = failed
                        saw_turn_end = True
                        terminal = True
                if len(carry) > MAX_DSH_LINE_BYTES:
                    carry = b""       # a single event line over budget: unusable
                if terminal:
                    break
                continue
            # No data is ready. Once the child is gone, a pipe that only a
            # grandchild still holds open will not deliver this turn's events.
            if proc.poll() is not None:
                break
        if not terminal and carry:
            failed = line_turn_end_failed(carry)
            if failed is not None:
                turn_failed = failed
                saw_turn_end = True
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            if saw_turn_end:
                # The turn completed; lingering is cleanup, not the turn.
                # Report the completed turn instead of blocking on the exit.
                forced_rc = 0
            with contextlib.suppress(OSError):
                proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError):
                    proc.kill()
                proc.wait()
    finally:
        if proc.stdout is not None:
            with contextlib.suppress(OSError):
                proc.stdout.close()
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.kill()
            proc.wait()
    if not saw_turn_end:
        # Exit status 0 with no turn_end event is NOT a completed turn: the
        # harness may have died before answering.
        print(f"{adapter}: the harness emitted no turn_end completion event", file=sys.stderr)
        turn_failed = True
    return (forced_rc if forced_rc is not None else int(proc.returncode or 0)), turn_failed

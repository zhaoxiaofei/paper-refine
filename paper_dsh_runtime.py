"""DeepSeek Harness mechanics shared by the paper model adapters."""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_common.dsh_events import line_turn_end_failed

MAX_DSH_LINE_BYTES = 1 << 20


def _writable(path: Path, adapter: str) -> bool:
    try:
        probe = path / f".paper_{adapter}_write_test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
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
    tmp = Path(tempfile.mkdtemp(prefix=f"paper-{adapter}-dsh-"))
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


def run_dsh_streaming(cmd: list, env: dict, adapter: str) -> tuple:
    """(returncode, turn_failed) with the harness's stdout ECHOED, not buffered.

    `dsh --json` emits one JSON object per line; a verbose harness must not be
    accumulated whole. The stream is read in bounded chunks, echoed as it
    arrives, and only complete lines are parsed.
    """
    proc = subprocess.Popen(cmd, stdin=sys.stdin, stdout=subprocess.PIPE,
                            stderr=sys.stderr, env=env)
    turn_failed = None
    saw_turn_end = False
    carry = b""
    try:
        # `read1`, not `read`: a buffered `read(n)` waits for n bytes (or EOF),
        # so a slow harness's first event would not be echoed until the stream
        # filled or the process exited -- the opposite of streaming.
        read_chunk = getattr(proc.stdout, "read1", proc.stdout.read)
        while True:
            chunk = read_chunk(1 << 20)
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
            if len(carry) > MAX_DSH_LINE_BYTES:
                carry = b""           # a single event line over budget: unusable
        if carry:
            failed = line_turn_end_failed(carry)
            if failed is not None:
                turn_failed = failed
                saw_turn_end = True
        proc.wait()
    finally:
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.kill()
            proc.wait()
    if not saw_turn_end:
        # Exit status 0 with no turn_end event is NOT a completed turn: the
        # harness may have died before answering.
        print(f"{adapter}: the harness emitted no turn_end completion event", file=sys.stderr)
        turn_failed = True
    return int(proc.returncode or 0), turn_failed

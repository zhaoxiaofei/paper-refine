#!/usr/bin/env python3
"""Regression checks for the 2026-11-14 fix-bugs group A harness fixes.

F01  a suite printing a bare `FAIL ...` line and exiting 0 is a failure
F03  a NOCHK suite is re-run alone once and can be reported flaky
F06  `--logs` is reusable: a non-empty directory gets a fresh run-* subdirectory
F07  the parallelism numbers match DEFAULT_JOBS = 32
F09  the module docstring documents the NOCHK exit status

Self-contained and fast: every probe builds a throwaway `.paper_test/` tree under
tempfile.mkdtemp() and runs the real runner there.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = HERE.parent
RUN_ALL = HERE / "run_all.py"
RUN_ONE = HERE / "run_one.sh"
FAILED = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[ok ] " if ok else "[FAIL] ") + name
          + (f"  [{detail}]" if not ok and detail else ""))
    if not ok:
        FAILED.append(name)


def probe_tree(tmp: Path) -> Path:
    td = tmp / ".paper_test"
    td.mkdir(parents=True)
    shutil.copy2(RUN_ALL, td / "run_all.py")
    shutil.copy2(RUN_ONE, td / "run_one.sh")
    return td


def run_runner(td: Path, *extra: str) -> tuple:
    proc = subprocess.run(
        [sys.executable, str(td / "run_all.py"), "--engine", "python", "-j", "1", *extra],
        cwd=str(td), capture_output=True, text=True, timeout=180)
    return proc.returncode, proc.stdout + proc.stderr


def test_f01_bare_fail() -> None:
    print("\n== F01: a bare FAIL line with a broken exit guard is not PASS ==")
    with tempfile.TemporaryDirectory(prefix="fixA-f01-") as tmp:
        tmp = Path(tmp)
        td = probe_tree(tmp)
        (td / "test_barefail.py").write_text(
            'print("FAIL bare form with a broken exit guard")\n', encoding="utf-8")
        rc, out = run_runner(td, "--only", "test_barefail", "--logs", str(tmp / "logs"))
        check("F01 bare FAIL + exit 0 exits 1 and does not pass",
              rc == 1 and "0 passed, 1 FAILED" in out, out[-400:])
        check("F01 the bare FAIL line is quoted as the failing check",
              "first failing checks" in out and "FAIL bare form" in out, out[-400:])


def test_f03_nochk_rerun() -> None:
    print("\n== F03: a NOCHK suite gets the documented alone re-run ==")
    with tempfile.TemporaryDirectory(prefix="fixA-f03-") as tmp:
        tmp = Path(tmp)
        td = probe_tree(tmp)
        # Silent under the parallel pass, prints a check when run in the quiet
        # `alone/` rundir -- the load-sensitive shape the docs promise to retry.
        (td / "test_silent_under_load.py").write_text(
            "import os\n"
            'tmp = os.environ.get("TMPDIR", "")\n'
            'if os.sep + "alone" + os.sep in tmp:\n'
            '    print("[ok ] quiet second run printed a check")\n',
            encoding="utf-8")
        rc, out = run_runner(td, "--only", "test_silent_under_load",
                             "--logs", str(tmp / "logs"))
        check("F03 NOCHK suite is re-run alone and reported flaky",
              rc == 0 and "FLKY" in out and "1 flaky" in out
              and "NOT re-run" not in out, out[-600:])


def test_f06_reusable_logs() -> None:
    print("\n== F06: --logs is reusable ==")
    with tempfile.TemporaryDirectory(prefix="fixA-f06-") as tmp:
        tmp = Path(tmp)
        td = probe_tree(tmp)
        (td / "test_ok.py").write_text('print("[ok ] passes")\n', encoding="utf-8")
        logs = tmp / "paper-logs"
        rc1, out1 = run_runner(td, "--only", "test_ok", "--logs", str(logs))
        rc2, out2 = run_runner(td, "--only", "test_ok", "--logs", str(logs))
        m1 = re.search(r"logs=(\S+)", out1)
        m2 = re.search(r"logs=(\S+)", out2)
        check("F06 a fresh --logs directory is used directly",
              rc1 == 0 and m1 is not None
              and Path(m1.group(1)).resolve() == logs.resolve(), out1[-300:])
        check("F06 reusing --logs starts a fresh run-* subdirectory",
              rc2 == 0 and m2 is not None
              and Path(m2.group(1)).resolve().parent == logs.resolve()
              and Path(m2.group(1)).name.startswith("run-"), out2[-400:])


def test_f07_counts() -> None:
    print("\n== F07: parallel-session counts match DEFAULT_JOBS = 32 ==")
    readme = (WS / "README.md").read_text(encoding="utf-8")
    runner = RUN_ALL.read_text(encoding="utf-8")
    check("F07 README no longer says 'seven siblings'", "seven siblings" not in readme)
    check("F07 runner docstring no longer says '15 others'", "15 others" not in runner)
    check("F07 the documented default stays 32", "DEFAULT_JOBS = 32" in runner)


def test_f09_nochk_status() -> None:
    print("\n== F09: the exit-status docstring covers NOCHK ==")
    runner = RUN_ALL.read_text(encoding="utf-8")
    check("F09 the docstring names the NOCHK exit-1 path",
          "NOCHK" in runner and "1 when one failed both ways" not in runner)
    with tempfile.TemporaryDirectory(prefix="fixA-f09-") as tmp:
        tmp = Path(tmp)
        td = probe_tree(tmp)
        (td / "test_persistent_silent.py").write_text(
            "# exits 0 without printing any check line\n", encoding="utf-8")
        rc, out = run_runner(td, "--only", "test_persistent_silent",
                             "--logs", str(tmp / "logs"))
        check("F09 a suite that stays NOCHK alone returns 1",
              rc == 1 and "NO CHECKS alone either" in out
              and "0 passed, 1 FAILED" in out, out[-500:])


def main() -> int:
    test_f01_bare_fail()
    test_f03_nochk_rerun()
    test_f06_reusable_logs()
    test_f07_counts()
    test_f09_nochk_status()
    print(f"\n{len(FAILED)} FAILED" if FAILED else "\nall checks passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())

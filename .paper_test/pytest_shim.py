#!/usr/bin/env python3
"""The tiny pytest subset the two pytest-style suites actually use.

`run_all.py` runs every `test_*.py` as a plain script -- the documented
contract is one `[ok ]`/`[FAIL]` line per check (see `.paper_test/README.md`).
Two suites were written for `python3 -m pytest` and therefore ran ZERO checks
under that runner; one of them also imported `pytest` at module load, so on a
box without the third-party package it failed before running anything.

This module provides exactly the subset those suites use: a `raises` context
manager and the `tmp_path`, `monkeypatch`, `capfd` and `capsys` fixtures. It is
imported only by those suites' `__main__` path (and only when the real `pytest`
is unavailable), so running them under pytest is unchanged.
"""
from __future__ import annotations

import contextlib
import inspect
import io
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace


class _Raises:
    """`with pytest.raises(Exc) as info:` -- the subset the suites use."""

    def __init__(self, expected):
        self.expected = expected
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            raise AssertionError(f"DID NOT RAISE {self.expected!r}")
        if not issubclass(exc_type, self.expected):
            return False
        self.value = exc
        return True


class _Pytest:
    raises = staticmethod(_Raises)


# `from pytest_shim import pytest` then `pytest.raises(...)`.
pytest = _Pytest()


class _MonkeyPatch:
    """setattr with undo, the only monkeypatch operation these suites use."""

    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value):
        self._undo.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def undo(self):
        for target, name, old in reversed(self._undo):
            setattr(target, name, old)
        self._undo.clear()


class _Capture:
    """`capfd`/`capsys`: a file-like pair with ``readouterr()``."""

    def __init__(self):
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def readouterr(self):
        out = self.stdout.getvalue()
        err = self.stderr.getvalue()
        for stream in (self.stdout, self.stderr):
            stream.seek(0)
            stream.truncate(0)
        return SimpleNamespace(out=out, err=err)


def run_tests(namespace: dict) -> int:
    """Run every module-level ``test_*`` function and print [ok ]/[FAIL] lines.

    Fixtures are constructed from the parameter names; anything else is refused
    loudly instead of being silently skipped. Returns 0 when every check passed.
    """
    module = namespace.get("__name__", "suite")
    tests = [(name, fn) for name, fn in namespace.items()
             if name.startswith("test_") and callable(fn)
             and getattr(fn, "__module__", module) == module]
    failures = []
    for name, fn in sorted(tests):
        tmp = Path(tempfile.mkdtemp(prefix=f"{module}.{name}."))
        mp = _MonkeyPatch()
        cap = _Capture()
        kwargs = {}
        capture = False
        try:
            for param in inspect.signature(fn).parameters:
                if param == "tmp_path":
                    kwargs[param] = tmp
                elif param == "monkeypatch":
                    kwargs[param] = mp
                elif param in ("capfd", "capsys"):
                    kwargs[param] = cap
                    capture = True
                else:
                    raise AssertionError(f"{name}: unsupported fixture {param!r}")
            with contextlib.ExitStack() as stack:
                if capture:
                    stack.enter_context(contextlib.redirect_stdout(cap.stdout))
                    stack.enter_context(contextlib.redirect_stderr(cap.stderr))
                fn(**kwargs)
            print(f"[ok ] {name}")
        except (Exception, SystemExit) as e:                       # noqa: BLE001
            failures.append(name)
            print(f"[FAIL] {name}: {type(e).__name__}: {e}")
            if not isinstance(e, SystemExit):
                traceback.print_exc()
        finally:
            mp.undo()
            shutil.rmtree(tmp, ignore_errors=True)
    print()
    if failures:
        print(f"[FAIL] {len(failures)} check(s) failed: {failures}")
        return 1
    if not tests:
        # Zero tests is not a pass: a filtered suite used to print
        # "[ok ] 0 check(s) passed" and the runner counted it green.
        print("[FAIL] no test ran: the module defines no runnable test_* function")
        return 1
    print(f"[ok ] {len(tests)} check(s) passed")
    return 0


def _main():
    raise SystemExit("pytest_shim is imported by a suite; it is not a runner")


if __name__ == "__main__":
    sys.exit(_main())

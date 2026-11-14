#!/usr/bin/env python3
"""Regression checks for the 2026-11-14 fix-bugs group F (agent adapters).

Covers:
  F55  qwen/dots dsh argv carries the stdin task marker `-` the one-shot form needs
  F56  qwen --reasoning-effort accepts the shared vocabulary (high/max/off)
  F57  dots --reasoning-effort accepts the shared vocabulary (off)
  F58  qwen/dots claude_env forwards the configured effort to Claude Code
  F62  run_dsh_streaming tolerates a stdin pseudo-file without a file descriptor

Run:  python3 .paper_test/test_fix_bugs_20261114_F.py
"""
from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent

FAILS = []


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}"
          + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def load(module_name: str, relative: str):
    spec = importlib.util.spec_from_file_location(module_name, WS / relative)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


qwen = load("fbF_qwen", "paper_qwen_agent.py")
dots = load("fbF_dots", "paper_dots_agent.py")
dsh_runtime = load("fbF_dsh_runtime", "paper_dsh_runtime.py")
model = load("fbF_model", "paper_model_agent.py")


def test_f55_dsh_argv_stdin_marker():
    print()
    print("== F55: the adapter dsh argv ends with the stdin task marker ==")
    home = tempfile.mkdtemp(prefix="fbF_dsh_home_")
    try:
        for name, mod in (("qwen", qwen), ("dots", dots), ("model", model)):
            original = mod.ensure_dsh_home
            mod.ensure_dsh_home = lambda: (home, "")
            try:
                argv, _env, err = mod.dsh_argv(mod.config())
            finally:
                mod.ensure_dsh_home = original
                mod._cleanup()
            check(f"F55 {name}.dsh_argv ends with `--json -`",
                  not err and len(argv) >= 2 and argv[-2:] == ["--json", "-"],
                  (err, argv))
    finally:
        import shutil
        shutil.rmtree(home, ignore_errors=True)


def test_f56_qwen_effort_choices():
    print()
    print("== F56: qwen --reasoning-effort accepts the documented levels ==")
    original = qwen._print_probe
    qwen._print_probe = lambda cfg: 0
    try:
        for level in ("high", "max", "off", "minimal"):
            rc = qwen.main(["--harness", "codex", "--reasoning-effort", level, "--probe"])
            check(f"F56 qwen --reasoning-effort {level} is accepted", rc == 0, rc)
    finally:
        qwen._print_probe = original


def test_f57_dots_effort_choices():
    print()
    print("== F57: dots --reasoning-effort accepts the documented levels ==")
    original = dots._print_probe
    dots._print_probe = lambda cfg: 0
    try:
        for level in ("off", "minimal", "high", "max"):
            rc = dots.main(["--harness", "codex", "--reasoning-effort", level, "--probe"])
            check(f"F57 dots --reasoning-effort {level} is accepted", rc == 0, rc)
    finally:
        dots._print_probe = original


def test_f58_claude_effort_env():
    print()
    print("== F58: the claude harness applies the configured reasoning effort ==")
    os.environ.pop("CLAUDE_CODE_EFFORT_LEVEL", None)
    Arg = type("Arg", (), {})
    for name, mod in (("qwen", qwen), ("dots", dots)):
        low = mod.config(type("A", (), {"harness": "claude", "reasoning_effort": "low"})())
        env = mod.claude_env(low)
        check(f"F58 {name} claude_env sets CLAUDE_CODE_EFFORT_LEVEL=low",
              env.get("CLAUDE_CODE_EFFORT_LEVEL") == "low", env.get("CLAUDE_CODE_EFFORT_LEVEL"))
        off = mod.config(type("A", (), {"harness": "claude", "reasoning_effort": "off"})())
        check(f"F58 {name} claude_env omits an unrepresentable `off` level",
              "CLAUDE_CODE_EFFORT_LEVEL" not in mod.claude_env(off))
    arg = Arg()
    arg.harness = "claude"
    arg.reasoning_effort = "high"
    qwen_high = qwen.claude_env(qwen.config(arg))
    check("F58 qwen high maps to Claude Code's max (its wire has no high)",
          qwen_high.get("CLAUDE_CODE_EFFORT_LEVEL") == "max",
          qwen_high.get("CLAUDE_CODE_EFFORT_LEVEL"))


def test_f62_pseudo_stdin():
    print()
    print("== F62: a stdin pseudo-file without a fileno does not crash the wrapper ==")
    original = sys.stdin
    sys.stdin = io.StringIO("")
    try:
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "silent.py"
            script.write_text(
                "print('{\"type\": \"status\", \"phase\": \"step_start\"}')\n",
                encoding="utf-8")
            rc, failed = dsh_runtime.run_dsh_streaming(
                [sys.executable, str(script)], {}, "test")
        check("F62 exit 0 without a turn-end event is a failed turn under pseudo-stdin",
              rc == 0 and failed is True, (rc, failed))
    finally:
        sys.stdin = original


def main() -> int:
    test_f55_dsh_argv_stdin_marker()
    test_f56_qwen_effort_choices()
    test_f57_dots_effort_choices()
    test_f58_claude_effort_env()
    test_f62_pseudo_stdin()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
        return 1
    print("PASSED: fix-bugs group F checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""`--agent deepseek`: the DeepSeek Harness CLI (`dsh`) as a session backend.

Run:  python3 .paper_test/test_deepseek_backend.py

The pipeline drives `codex` and `claude` through their presets; `deepseek` is
the third one, and it is the only preset whose one-shot contract is a property
of the INSTALLED build rather than of the flags the pipeline passes (the task
on stdin via `-`, and the `--json` event stream whose opening `session` line
carries the id a continuation adopts). These checks pin every part of that:

  * the preset argv (`dsh --profile headless --json -`), that it carries no
    codex-only MCP overrides, and that every parser accepts the name;
  * `resume_argv_for()` -- `--session-id <id>` inserted BEFORE the `-` task
    positional (an exact persisted Session; no id means no continuation, since
    a fresh session would answer the continuation prompt from memory it does
    not have) -- and `capture_agent_session_id()` reading the JSON form while
    still reading the codex/claude banner forms (the LAST id wins);
  * `deepseek_harness_problem()`: a harness whose own `--help` declares neither
    `--json` nor the stdin task form is a POSITIVE finding (the run stops with
    the fix named, before a wave of sessions fails one by one), while a probe
    that cannot read the help stays silent;
  * end to end through a fake `dsh` on PATH: a one-shot session receives the
    sandbox's own PROMPT.md byte-for-byte on stdin with cwd = the sandbox, and
    a stalled session is CONTINUED through `--session-id <id>` -- the id read
    out of the `--json` stream the fake wrote -- until the stage completes.
"""
from __future__ import annotations

import hashlib
import importlib.util
import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
TESTDIR = WS / ".paper_test"
spec = importlib.util.spec_from_file_location("paper_deepseek", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_deepseek"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []
PRESET = list(nb.AGENT_PRESETS["deepseek"])
# The harness names its sessions `session-<uuid>` (dsh 0.2.x).
DSH_SID = "session-d041d42a-c2e2-4ae3-8af5-2c78d9f8bae1"
# A codex-banner id, to prove the two id forms are read side by side.
CODEX_SID = "01a0c963-79ce-7842-bfba-88a94098c82b"


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 1. the preset: argv, choices, the derived binary set, the install hint
# ---------------------------------------------------------------------------
def test_preset():
    print()
    print("== the preset argv, the parser choices and the install hint ==")
    check("the preset is the harness's one-shot form: task on stdin, JSON events",
          PRESET == ["dsh", "--profile", "headless", "--json", "-"], str(PRESET))
    check("agent_argv() returns it unchanged (no codex-only MCP `-c` overrides)",
          nb.agent_argv("deepseek") == PRESET, str(nb.agent_argv("deepseek")))
    # The resolver reads the INSTALLED harness (see deepseek_harness_problem), so
    # this check runs against a controlled PATH: the machine's own `dsh` must
    # not decide whether the suite passes (it is what the probe is for, and
    # test_probe covers every verdict on it).
    tmp = scratch("paper_dsh_preset_")
    bindir = make_fake_dsh(tmp / "bin", mode="finish")
    real_path, real_mode = os.environ.get("PATH", ""), os.environ.get("FAKE_DSH_MODE")
    os.environ["PATH"] = f"{bindir}{os.pathsep}{real_path}"
    os.environ["FAKE_DSH_MODE"] = "finish"
    try:
        check("resolve_agent_cmd() accepts the preset name",
              nb.resolve_agent_cmd("deepseek", None, use_env=False) == PRESET)
    finally:
        os.environ["PATH"] = real_path
        if real_mode is None:
            os.environ.pop("FAKE_DSH_MODE", None)
        else:
            os.environ["FAKE_DSH_MODE"] = real_mode
        nb._HARNESS_PROBE_CACHE.clear()
    check("every --agent/--judge-agent parser offers it, and 'manual' stays offered",
          list(nb.AGENT_CHOICES) == ["codex", "claude", "deepseek", "manual"]
          and list(nb.CONFLICT_AGENT_CHOICES) == ["codex-lite", "codex", "claude", "deepseek",
                                                 "manual"],
          str(nb.AGENT_CHOICES))
    parser = nb.build_parser()
    got = parser.parse_args(["run", "--root", "/tmp/x", "--agent", "deepseek",
                             "--judge-agent", "deepseek"])
    check("`run --agent deepseek --judge-agent deepseek` parses",
          got.agent == "deepseek" and got.judge_agent == "deepseek")
    check("the conflict audit offers it too",
          parser.parse_args(["conflicts", "--root", "/tmp/x", "--agent", "deepseek"]).agent
          == "deepseek")
    check("the harness binary counts as a shipped preset CLI (not a stub)",
          nb._looks_like_preset_cmd(PRESET)
          and not nb._looks_like_preset_cmd(["python3", "stub_agent.py"]))
    hint = nb.agent_install_hint(PRESET)
    check("a missing `dsh` is answered with the install line, and only for the harness",
          "@deepseek-ai/dsh" in hint and "DSH_HOME" in hint
          and nb.agent_install_hint(["codex", "exec", "-"]) == "",
          hint.strip()[:80])


# ---------------------------------------------------------------------------
# 2. the continuation form and the session-id capture
# ---------------------------------------------------------------------------
def test_resume_forms():
    print()
    print("== the continuation: `--session-id <id>` before the `-` task positional ==")
    got = nb.resume_argv_for(PRESET, DSH_SID)
    check("the id is inserted before the stdin task, keeping the preset's own flags",
          got == ["dsh", "--profile", "headless", "--json", "--session-id", DSH_SID, "-"],
          str(got))
    check("without a captured id there is NO continuation (no directory-wide fallback)",
          nb.resume_argv_for(PRESET, "") == [])
    check("the `-` task positional stays LAST (the one-shot app takes `-` alone)",
          got[-3:] == ["--session-id", DSH_SID, "-"], str(got))
    check("a custom --agent-cmd is still left alone",
          nb.resume_argv_for(["myagent", "--flag"], DSH_SID) == [])


def test_session_id_capture():
    print()
    print("== the `--json` session line is read from _agent.log (LAST id wins) ==")
    root = scratch("paper_dsh_sid_")
    sb = root / "runs" / "r1_w1"
    sb.mkdir(parents=True)
    ctx = nb.Ctx(root)
    rec = {"id": "r1_w1", "kind": "rewrite", "round": 1, "sandbox": "runs/r1_w1"}
    (sb / "_agent.log").write_text(
        f'cmd: dsh --profile headless --json -\n'
        f'{{"type":"session","sessionId":"{DSH_SID}","cwd":"' + str(sb) + '"}\n'
        '{"type":"status","phase":"turn_end","reason":{"kind":"completed"}}\n', encoding="utf-8")
    check("the harness's camelCase `sessionId` (session-<uuid>) is captured",
          nb.capture_agent_session_id(ctx, rec) == DSH_SID,
          nb.capture_agent_session_id(ctx, rec))
    # A codex banner BEFORE the harness line and a claude result object AFTER it:
    # the position decides, not the form -- the transcript is appended per attempt.
    (sb / "_agent.log").write_text(
        f"session id: {CODEX_SID}\n"
        f'{{"type":"session","sessionId":"{DSH_SID}"}}\n'
        f'{{"type":"result","session_id":"{CODEX_SID}"}}\n', encoding="utf-8")
    check("across all three id forms the LAST occurrence wins",
          nb.capture_agent_session_id(ctx, rec) == CODEX_SID,
          nb.capture_agent_session_id(ctx, rec))
    (sb / "_agent.log").write_text('{"type":"session","sessionId":"session-nothex"}\n',
                                   encoding="utf-8")
    check("a malformed harness id is not adopted",
          nb.capture_agent_session_id(ctx, rec) == "")


# ---------------------------------------------------------------------------
# 3. the capability probe: only a POSITIVE finding stops the run
# ---------------------------------------------------------------------------
def test_probe():
    print()
    print("== the installed harness is read for the one-shot contract ==")
    tmp = scratch("paper_dsh_probe_")
    real = os.environ.get("PATH", "")
    real_mode = os.environ.get("FAKE_DSH_MODE")
    try:
        for mode, expect_problem, why in (("old", True, "a build without the contract"),
                                          ("node18", True, "a harness crashing on old node"),
                                          ("abi", True, "a harness built for another node"),
                                          ("unrelated", False, "help we cannot read"),
                                          ("finish", False, "a current build")):
            bindir = make_fake_dsh(tmp / f"bin_{mode}", mode=mode)
            os.environ["PATH"] = f"{bindir}{os.pathsep}{real}"
            os.environ["FAKE_DSH_MODE"] = mode
            nb._HARNESS_PROBE_CACHE.clear()
            problem = nb.deepseek_harness_problem(PRESET)
            check(f"{why}: problem={'named' if expect_problem else 'silent'}",
                  bool(problem) is expect_problem, problem[:120])
        # The verdict is cached per RESOLVED BINARY: pointing PATH at a good
        # `dsh` must answer for the good one, without the caller clearing
        # anything (a stale "it is broken" would block a working harness).
        bindir = make_fake_dsh(tmp / "bin_good_again", mode="finish")
        os.environ["PATH"] = f"{bindir}{os.pathsep}{real}"
        os.environ["FAKE_DSH_MODE"] = "finish"
        check("the probe's cache follows PATH, not the bare name",
              nb.deepseek_harness_problem(PRESET) == "")
        # An operator's own command is never probed and never blocked, whatever
        # the `dsh` on PATH looks like.
        bindir = make_fake_dsh(tmp / "bin_old_again", mode="old")
        os.environ["PATH"] = f"{bindir}{os.pathsep}{real}"
        os.environ["FAKE_DSH_MODE"] = "old"
        check("an explicit --agent-cmd wins over the preset and is not probed",
              nb.resolve_agent_cmd("deepseek", '["myagent", "--flag"]') == ["myagent", "--flag"])
        with contextlib.redirect_stderr(io.StringIO()):       # the die prints its reason
            try:
                nb.resolve_agent_cmd("deepseek", None, use_env=False)
                refused = False
            except SystemExit:
                refused = True
        check("the preset ROUTE still refuses that same machine (the argv is never handed back)",
              refused)
        os.environ["PATH"] = real
        nb._HARNESS_PROBE_CACHE.clear()
        check("a binary that does not run at all stays silent (the sessions will speak)",
              nb.deepseek_harness_problem(["definitely-not-a-real-dsh-binary"]) == "")
    finally:
        os.environ["PATH"] = real
        if real_mode is None:
            os.environ.pop("FAKE_DSH_MODE", None)
        else:
            os.environ["FAKE_DSH_MODE"] = real_mode
        nb._HARNESS_PROBE_CACHE.clear()


# ---------------------------------------------------------------------------
# 4. end to end through a fake `dsh` on PATH
# ---------------------------------------------------------------------------
# The fake speaks the harness's own grammar: `dsh --profile headless [--json]
# [--session-id <id>] -`, the task on stdin, the opening `session` line (with
# the id) on stdout. Modes:
#   finish      answer the task (run the real stub on this sandbox's PROMPT.md)
#   stall       write the session line and exit 0 having written nothing
#   resume_only stall on a first round, finish when asked to adopt a session
#   old         a build whose headless app has no --json / stdin task form
#   node18      the harness crashing at import under an older `node` on PATH
#   abi         the harness installed for another node than the one running it
#   unrelated   a `dsh` that is not the app this preset speaks to
# Every invocation appends one JSON line to $FAKE_DSH_LOG: argv, cwd, the
# sha256 of the stdin text, and the adopted session id (when one was given).
FAKE_DSH = '''#!/usr/bin/env python3
"""A stand-in for `dsh` (see .paper_test/test_deepseek_backend.py)."""
import hashlib, json, os, sys

TESTDIR = "__TESTDIR__"
SID = "__SID__"
MODE = os.environ.get("FAKE_DSH_MODE", "finish")

HELP_OK = """Usage: dsh --profile headless [options] [task...]

Answer one task and exit.

Arguments:
  task               the task text; multiple words are joined by spaces, and `-`
                     reads stdin

Options:
  --json             write newline-delimited run events to stdout instead of the
                     final message
  --session-id <id>  adopt the persisted Session with this id
"""
HELP_OLD = """Usage: dsh --profile headless [options] [task...]

Answer one task, print the final assistant message, and exit.

Arguments:
  task  the task text; multiple words are joined by spaces

Options:
  -h, --help  show this help
"""
HELP_UNRELATED = "usage: dsh [--profile] <name> [options]\\n"

argv = sys.argv[1:]
if MODE == "node18":
    # Under an older node the harness dies at import -- even for `--help`.
    sys.stderr.write(
        "file:///tmp/_npx/x/node_modules/@deepseek-ai/dsh-app-boot/lib/index.js:4\\n"
        'import { inspect, parseEnv } from "node:util";\\n'
        "SyntaxError: The requested module 'node:util' does not provide an export named "
        "'parseEnv'\\n\\nNode.js v18.20.8\\n")
    sys.exit(1)
if MODE == "abi":
    # Installed under one node, started by another: the native binding misses.
    sys.stderr.write(
        "dsh: fatal uncaught exception: Error: dsh: host preparation failed: No usable "
        "native binding found for node-addon-require-builtin-linux-x64-gnu (auto)\\n")
    sys.exit(1)
if "--help" in argv or "-h" in argv:
    sys.stdout.write(HELP_UNRELATED if MODE == "unrelated"
                     else HELP_OLD if MODE == "old" else HELP_OK)
    sys.exit(0)
if MODE == "old":
    sys.stderr.write("error: unknown option '--json'\\n")
    sys.exit(1)
if MODE == "unrelated":
    sys.stderr.write("dsh: this profile is not headless\\n")
    sys.exit(1)

task = sys.stdin.read()
adopted = ""
if "--session-id" in argv:
    adopted = argv[argv.index("--session-id") + 1]
log = os.environ.get("FAKE_DSH_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": argv, "cwd": os.getcwd(),
                            "stdin_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
                            "stdin_bytes": len(task.encode("utf-8")),
                            "resume_id": adopted}) + "\\n")
if "--json" in argv:
    sys.stdout.write(json.dumps({"type": "session", "sessionId": SID,
                                 "cwd": os.getcwd()}, separators=(",", ":")) + "\\n")
    sys.stdout.flush()

finish = MODE == "finish" or (MODE == "resume_only" and adopted)
if not finish:
    sys.exit(0)                      # the stall: nothing written, rc=0
sys.path.insert(0, TESTDIR)
import stub_agent  # noqa: E402
sys.exit(stub_agent.main())
'''


def make_fake_dsh(bindir: Path, mode: str) -> Path:
    bindir.mkdir(parents=True, exist_ok=True)
    p = bindir / "dsh"
    p.write_text(FAKE_DSH.replace("__TESTDIR__", str(TESTDIR)).replace("__SID__", DSH_SID),
                 encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    # The mode is not baked into the file: one fake, selected per invocation.
    (bindir / "mode").write_text(mode, encoding="utf-8")
    return bindir


def make_root(tmp: Path) -> Path:
    src = tmp / "source"
    src.mkdir()
    (src / "manuscript.md").write_text(
        "Abstract\n\n" + ("word " * 100).strip() + "\n\nIntroduction\n\n"
        + ("text " * 200).strip() + "\n\nFigure 1 | A caption here.\n\nMethods\n\nx\n",
        encoding="utf-8")
    root = tmp / "root"
    proc = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
                           "--source", str(src), "--root", str(root), "--rounds", "1",
                           "--rewrites", "1", "--revises", "0", "--judges", "1",
                           "--integrators", "0x0"],
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return root


def run_with_fake_dsh(root: Path, bindir: Path, *extra):
    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["FAKE_DSH_MODE"] = (bindir / "mode").read_text(encoding="utf-8").strip()
    env["FAKE_DSH_LOG"] = str(bindir.parent / "calls.jsonl")
    return subprocess.run([sys.executable, str(root / "paper_pipeline.py"), "run",
                           "--root", str(root), "--only", "rewrite", "--agent", "deepseek",
                           *extra],
                          capture_output=True, text=True, timeout=1800, env=env)


def calls_of(bindir: Path) -> list:
    log = bindir.parent / "calls.jsonl"
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def test_end_to_end_oneshot():
    print()
    print("== a stage runs on the harness preset: PROMPT.md on stdin, cwd = the sandbox ==")
    tmp = scratch("paper_dsh_e2e_")
    root = make_root(tmp)
    bindir = make_fake_dsh(tmp / "bin", mode="finish")
    proc = run_with_fake_dsh(root, bindir, "--retries", "0")
    out = proc.stdout + proc.stderr
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    rec = state["runs"]["r1_w1"]
    sandbox = root / "runs" / "r1_w1"
    calls = calls_of(bindir)
    # `--only rewrite` drives one session and stops: the ROUND stays incomplete
    # on purpose (exit code 3, "round 1 is incomplete"), which is what the codex
    # suite pins for the same selection.
    check("the stage completes on the harness backend (postcheck ok, round left open)",
          rec["status"] == "done" and (rec.get("postcheck") or {}).get("ok") is True
          and "round 1 is incomplete" in out,
          f"rc={proc.returncode} status={rec.get('status')} {out[-200:]}")
    check("exactly one session ran, with the preset argv",
          len(calls) == 1 and calls[0]["argv"] == PRESET[1:], str(calls[:1]))
    prompt_bytes = (sandbox / "PROMPT.md").read_bytes()
    check("the stage prompt arrived on stdin, byte for byte",
          calls and calls[0]["stdin_sha256"] == hashlib.sha256(prompt_bytes).hexdigest(),
          f"stdin={calls[0]['stdin_bytes'] if calls else 0}B "
          f"prompt={len(prompt_bytes)}B")
    check("the session ran with cwd = the stage's own sandbox",
          calls and Path(calls[0]["cwd"]) == sandbox, str(calls[:1]))
    check("no continuation was attempted on a first-round success",
          calls and calls[0]["resume_id"] == "")
    check("the transcript keeps the harness's own output (the session line)",
          (sandbox / "_agent.log").is_file()
          and f'"sessionId":"{DSH_SID}"' in (sandbox / "_agent.log").read_text(encoding="utf-8"))


def test_end_to_end_continuation():
    print()
    print("== a stalled harness session is CONTINUED through `--session-id` ==")
    tmp = scratch("paper_dsh_resume_")
    root = make_root(tmp)
    bindir = make_fake_dsh(tmp / "bin", mode="resume_only")
    proc = run_with_fake_dsh(root, bindir, "--retries", "0")
    out = proc.stdout + proc.stderr
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    rec = state["runs"]["r1_w1"]
    calls = calls_of(bindir)
    sources = [e.get("source") for e in rec.get("attempts_log") or []]
    check("the run completes on the continuation (no fresh attempt was needed)",
          rec["status"] == "done" and (rec.get("postcheck") or {}).get("ok") is True
          and "round 1 is incomplete" in out, f"rc={proc.returncode} {sources}")
    check("the attempt history shows the stopped attempt and then the continuation",
          sources == ["postcheck", "continuation"], str(sources))
    check("the continuation adopts the id read out of the `--json` stream",
          len(calls) == 2 and calls[1]["resume_id"] == DSH_SID
          and calls[1]["argv"][:5] == ["--profile", "headless", "--json", "--session-id",
                                       DSH_SID],
          str(calls[1]["argv"]) if len(calls) > 1 else str(calls))
    check("the id is recorded on the run (agent_session_id) and its budget is charged",
          rec.get("agent_session_id") == DSH_SID and rec.get("resume_attempts") == {DSH_SID: 1},
          f"{rec.get('agent_session_id')} {rec.get('resume_attempts')}")
    check("the console names the continuation",
          "[resume] r1_w1" in out and DSH_SID[:8] in out, out[-200:])


def test_end_to_end_old_harness():
    print()
    print("== an installed harness without the one-shot contract stops the run up front ==")
    tmp = scratch("paper_dsh_old_")
    root = make_root(tmp)
    bindir = make_fake_dsh(tmp / "bin", mode="old")
    proc = run_with_fake_dsh(root, bindir, "--retries", "0")
    out = proc.stdout + proc.stderr
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    rec = state["runs"].get("r1_w1") or {}
    check("the run stops before any session starts (no retries spent)",
          proc.returncode != 0 and calls_of(bindir) == [] and not rec.get("attempts_log"),
          f"rc={proc.returncode} calls={len(calls_of(bindir))}")
    check("the console names the gap, the upgrade and the escape",
          "cannot run this pipeline's sessions" in out and "@deepseek-ai/dsh" in out
          and "--agent codex|claude|manual" in out, out[-300:])


def main() -> int:
    try:
        test_preset()
        test_resume_forms()
        test_session_id_capture()
        test_probe()
        test_end_to_end_oneshot()
        test_end_to_end_continuation()
        test_end_to_end_old_harness()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} DEEPSEEK-BACKEND CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL DEEPSEEK-BACKEND CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""`codex exec resume <session-id>`: finishing a stage that stopped mid-work.

Run:  python3 .nbt_test/test_resume_continuation.py

The 2026-09-22 root lost an integration arm twice to a session that ended without
writing one file (366k / 204k tokens, task_complete with no final message). The
CLI keeps those sessions, so the pipeline can CONTINUE one instead of paying for
a fresh attempt: the corpus it read and the plan it made stay in its context.

  * `resume_argv_for()` builds the continuation argv for the two presets -- codex
    (`codex exec resume <id> <overrides> -`, id required: `resume --last` is
    global and unsafe in parallel) and claude (`... --print --resume <id>`, or
    `--continue` for this directory when no id was captured) -- and refuses to
    invent one for a custom `--agent-cmd`.
  * `capture_agent_session_id()` reads the id the CLI prints in its banner from
    the transcript the pipeline already keeps.
  * `resume_gate()` only continues an attempt that looks UNFINISHED (a process
    failure, or a postcheck error naming a deliverable that does not exist), and
    at most RESUME_ATTEMPT_LIMIT (2) times per session id.
  * end to end, through a fake `codex` on PATH: a stalled stage is continued and
    the run completes with attempts [postcheck(failed), continuation(ok)]; a
    session that keeps stalling is continued exactly twice and then fails.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
TESTDIR = WS / ".nbt_test"
spec = importlib.util.spec_from_file_location("nbt_resume", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_resume"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []
SID = "01a0c963-79ce-7842-bfba-88a94098c82b"


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
# 1. the argv builders (codex, claude, and everything else)
# ---------------------------------------------------------------------------
def test_argv_forms():
    print()
    print("== the continuation argv: codex, claude, custom ==")
    codex = ["codex", "exec", "-c", 'mcp_servers.x="approve"', "-"]
    got = nb.resume_argv_for(codex, SID)
    check("codex: `exec resume <id>` keeps the overrides and the stdin prompt last",
          got == ["codex", "exec", "resume", SID, "-c", 'mcp_servers.x="approve"', "-"], str(got))
    check("codex: no captured id means NO resume (`resume --last` is global)",
          nb.resume_argv_for(codex, "") == [])
    claude = ["claude", "--permission-mode", "bypassPermissions", "--print"]
    check("claude: `--resume <id>` is appended to the preset argv",
          nb.resume_argv_for(claude, "abc-123") == [*claude, "--resume", "abc-123"])
    check("claude: without an id it continues the newest session OF THIS DIRECTORY",
          nb.resume_argv_for(claude, "") == [*claude, "--continue"])
    check("a custom --agent-cmd has no resume form (a fresh attempt follows)",
          nb.resume_argv_for(["myagent", "--flag"], SID) == []
          and nb.resume_argv_for([], SID) == [])


# ---------------------------------------------------------------------------
# 2. the session id comes from the transcript the pipeline already keeps
# ---------------------------------------------------------------------------
def test_session_id_capture():
    print()
    print("== the session id is read from _agent.log (the LAST one wins) ==")
    root = scratch("nbt_resume_sid_")
    sb = root / "runs" / "r1_w1"
    sb.mkdir(parents=True)
    (sb / "_agent.log").write_text(
        "===== attempt 1 start =====\ncmd: codex exec -\n"
        "OpenAI Codex v0.155.1\n--------\nsession id: 01a0c963-1111-7000-8000-000000000001\n"
        "===== rc=0 =====\n\n===== attempt 2 start =====\ncmd: codex exec resume …\n"
        f"session id: {SID}\n===== rc=0 =====\n", encoding="utf-8")
    ctx = nb.Ctx(root)
    rec = {"id": "r1_w1", "kind": "rewrite", "round": 1, "sandbox": "runs/r1_w1"}
    check("the latest session id is captured",
          nb.capture_agent_session_id(ctx, rec) == SID,
          nb.capture_agent_session_id(ctx, rec))
    # A claude run configured with `--output-format json` reports the id in its
    # result object instead of the codex banner: recognized the same way, so the
    # continuation can target `--resume <id>` instead of the directory-scoped
    # `--continue`.
    (sb / "_agent.log").write_text(
        '{"type":"result","session_id":"%s","result":"done"}\n' % SID, encoding="utf-8")
    check("the JSON `session_id` form (claude --output-format json) is captured too",
          nb.capture_agent_session_id(ctx, rec) == SID,
          nb.capture_agent_session_id(ctx, rec))
    (sb / "_agent.log").write_text("no id in here\n", encoding="utf-8")
    check("a transcript without a banner yields no id (and therefore no continuation)",
          nb.capture_agent_session_id(ctx, rec) == "")


# ---------------------------------------------------------------------------
# 3. the gate: unfinished attempts only, at most twice per session id
# ---------------------------------------------------------------------------
def test_gate():
    print()
    print("== the gate: unfinished attempts only, at most 2 continuations per session ==")
    root = scratch("nbt_resume_gate_")
    sb = root / "runs" / "r1_i3"
    (sb / "integrated").mkdir(parents=True)
    sb.mkdir(exist_ok=True)
    ctx = nb.Ctx(root)
    cmd = ["codex", "exec", "-"]
    MARK = ("completion marker _pipeline_done.json missing (it is prompted as the very last "
            "step; a non-empty output directory is NOT completion)")
    LED = "integrated/DIFF_LEDGER.md is missing: it is this stage's ledger"
    rec = {"id": "r1_i3", "kind": "integrate", "round": 1, "sandbox": "runs/r1_i3",
           "status": "failed", "agent_session_id": SID,
           "postcheck": {"ok": False, "errors": [MARK, LED], "warnings": []}}
    check("a stalled attempt (deliverables absent) is a continuation candidate",
          nb.resume_unfinished_reason(ctx, rec).startswith("the stage stopped before writing"))
    argv, key, reason = nb.resume_gate(ctx, rec, cmd)
    check("the gate returns the resume argv and the session as the budget key",
          argv == ["codex", "exec", "resume", SID, "-"] and key == SID and reason, str(argv))
    rec["resume_attempts"] = {SID: nb.RESUME_ATTEMPT_LIMIT}
    argv2, _k, reason2 = nb.resume_gate(ctx, rec, cmd)
    check("after the limit the gate refuses (a fresh attempt follows)",
          argv2 == [] and reason2 == "")
    rec2 = dict(rec, postcheck={"ok": False,
                                "errors": ["rewrite: REWRITE_REPORT.md declares level 'sentence' "
                                           "but this arm is 'structural' -- the round stages one "
                                           "structural and one sentence-level arm"], "warnings": []})
    check("an attempt that FINISHED and was rejected on content is not continued",
          nb.resume_unfinished_reason(ctx, rec2) == "")
    rec3 = dict(rec, postcheck={"ok": False, "errors": [], "warnings": []},
                last_error="TIMEOUT after 14400s")
    check("a process-level failure (timeout/kill) is continued",
          nb.resume_unfinished_reason(ctx, rec3).startswith("the agent process failed"))
    p = nb.resume_prompt(rec, [MARK, LED], "the stage stopped before writing x", used=0)
    check("the continuation prompt says what stopped, what failed and what to do",
          "CONTINUATION" in p and "Do NOT start over" in p
          and "Write the completion marker" in p and MARK in p and LED in p)


# ---------------------------------------------------------------------------
# 4. end to end through a fake `codex` on PATH
# ---------------------------------------------------------------------------
FAKE_CODEX = '''#!/usr/bin/env python3
"""A stand-in for `codex`: same argv shape, scripted behaviour.

    codex exec <overrides> -            -> "stall": print the banner, write nothing
    codex exec resume <id> <ov> -       -> run the real stub with this sandbox's
                                           PROMPT.md (or stall again, mode=never)
"""
import io, os, sys
from pathlib import Path

TESTDIR = r"{testdir}"
sys.path.insert(0, TESTDIR)
import stub_agent  # noqa: E402

SID = "{sid}"
MODE = os.environ.get("FAKE_CODEX_MODE", "finish")
resumed = len(sys.argv) > 2 and sys.argv[1] == "exec" and sys.argv[2] == "resume"
sys.stderr.write(f"OpenAI Codex v0.155.1\\n--------\\nsession id: {{SID}}\\n")
prompt = sys.stdin.read()
if not resumed:
    sys.exit(0)                      # the stall: nothing written, rc=0
sandbox = Path.cwd()
(sandbox / "_fake_resume_count").write_text(
    str(int((sandbox / "_fake_resume_count").read_text() or "0") + 1
        if (sandbox / "_fake_resume_count").is_file() else "1"), encoding="utf-8")
if MODE == "never":
    sys.exit(0)                      # the continuation stalls too
stage_prompt = (sandbox / "PROMPT.md").read_text(encoding="utf-8")
sys.stdin = io.StringIO(stage_prompt)
sys.exit(stub_agent.main())
'''


def make_fake_codex(bindir: Path) -> Path:
    bindir.mkdir(parents=True, exist_ok=True)
    p = bindir / "codex"
    p.write_text(FAKE_CODEX.format(testdir=str(TESTDIR), sid=SID), encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bindir


def make_root(tmp: Path) -> Path:
    src = tmp / "source"
    src.mkdir()
    (src / "manuscript.md").write_text(
        "Abstract\n\n" + ("word " * 100).strip() + "\n\nIntroduction\n\n"
        + ("text " * 200).strip() + "\n\nFigure 1 | A caption here.\n\nMethods\n\nx\n",
        encoding="utf-8")
    root = tmp / "root"
    proc = subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), "setup",
                           "--source", str(src), "--root", str(root), "--rounds", "1",
                           "--rewrites", "1", "--revises", "0", "--judges", "1",
                           "--integrators", "0x0"],
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return root


def run_with_fake_codex(root: Path, bindir: Path, *extra, mode: str = "finish"):
    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["FAKE_CODEX_MODE"] = mode
    return subprocess.run([sys.executable, str(root / "nbt_pipeline.py"), "run",
                           "--root", str(root), "--only", "rewrite", *extra],
                          capture_output=True, text=True, timeout=1800, env=env)


def test_end_to_end_continuation():
    print()
    print("== a stalled stage is CONTINUED and the run completes ==")
    tmp = scratch("nbt_resume_e2e_")
    root = make_root(tmp)
    proc = run_with_fake_codex(root, make_fake_codex(tmp / "bin"), "--retries", "0")
    out = proc.stdout + proc.stderr
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    rec = state["runs"]["r1_w1"]
    sources = [(e.get("attempt"), e.get("source"), e.get("ok"))
               for e in rec.get("attempts_log") or []]
    check("the run completes on the continuation (no fresh attempt was needed)",
          rec["status"] == "done" and (rec.get("postcheck") or {}).get("ok") is True
          and "round 1 is incomplete" in out,   # `--only rewrite`: the ROUND stays open
          f"rc={proc.returncode} {sources}")
    check("the attempt history shows the stopped attempt and then the continuation",
          sources == [(1, "postcheck", False), (2, "continuation", True)], str(sources))
    check("the resume budget is charged per session id",
          rec.get("resume_attempts") == {SID: 1} and rec.get("agent_session_id") == SID,
          str(rec.get("resume_attempts")))
    check("the console names the continuation and its session",
          "[resume] r1_w1" in out and SID[:8] in out, out[-300:])
    check("exactly one continuation session ran, and its prompt file is cleaned up",
          (root / "runs" / "r1_w1" / "_fake_resume_count").read_text() == "1"
          and not (root / "runs" / "r1_w1" / nb.RESUME_PROMPT_FILE).exists())


def test_end_to_end_limit():
    print()
    print("== a session that keeps stalling is continued at most twice ==")
    tmp = scratch("nbt_resume_limit_")
    root = make_root(tmp)
    # Three stage attempts: the first two get a continuation, the third finds the
    # per-session budget spent (and says so) before the run gives up.
    proc = run_with_fake_codex(root, make_fake_codex(tmp / "bin"), "--retries", "2",
                               mode="never")
    out = proc.stdout + proc.stderr
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    rec = state["runs"]["r1_w1"]
    sources = [e.get("source") for e in rec.get("attempts_log") or []]
    check("the run FAILS after the continuation budget is spent",
          proc.returncode != 0 and rec["status"] == "failed", f"rc={proc.returncode} {sources}")
    check("exactly two continuations ran for that session id",
          sum(int(p.read_text()) for p in (root / "runs").glob("r1_w1*/_fake_resume_count")) == 2
          and rec.get("resume_attempts") == {SID: 2},
          f"count={rec.get('resume_attempts')} sources={sources}")
    check("the console says why no further continuation is made",
          "limit 2" in out, out[-300:])
    check("every continuation is an attempt in the history (never silent)",
          sources.count("continuation") == 2 and sources.count("postcheck") == 3, str(sources))


def main() -> int:
    try:
        test_argv_forms()
        test_session_id_capture()
        test_gate()
        test_end_to_end_continuation()
        test_end_to_end_limit()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} RESUME-CONTINUATION CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL RESUME-CONTINUATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""`codex exec resume <session-id>`: finishing a stage that stopped mid-work.

Run:  python3 .paper_test/test_resume_continuation.py

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

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
TESTDIR = WS / ".paper_test"
spec = importlib.util.spec_from_file_location("paper_resume", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_resume"] = nb
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
    root = scratch("paper_resume_sid_")
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
    root = scratch("paper_resume_gate_")
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


def test_context_overflow_gate():
    print()
    print("== a 413/context-limit failure is never continued ==")
    for label, text in (
            ("status 413", "ERROR: unexpected status 413 Payload Too Large"),
            ("request entity", "<title>413 Request Entity Too Large</title>"),
            ("length limit", "Failed to buffer the request body: length limit exceeded"),
            ("maximum context", "maximum context length exceeded")):
        check(f"{label} is classified as context overflow",
              nb.agent_failure_kind("", text) == "context_overflow", text)
    check("an ordinary process failure has no context class",
          nb.agent_failure_kind("", "agent exited rc=1") == "")

    # 2026-11-13, brief communication: the guided-review agent read the
    # pipeline's own postcheck source into its transcript. Those source
    # comments quote every overflow spelling below, so the scanner reported an
    # HTTP 413 that never happened while the real cause was the turn guard.
    source_comments = "\n".join((
        "    # `unexpected status 413`, `HTTP 413: ...`, `status code 413`",
        '    r"|^\\s*(?:error[:\\s]+)?payload too large\\b"',
        '    # both word orders: "context window ... exceeded" and "exceeds ... context window"',
    ))
    check("the classifier's own source comments are not provider evidence",
          nb.agent_failure_kind("", source_comments) == "",
          source_comments[:60])
    # The 2026-11-13 review printed a WHOLE parts file, not only its comments:
    # p06's `why = ("... request as too large ...")` and p08's string
    # continuation `"(HTTP 413 / request too large)"` still matched after the
    # first filter, so the filter must cover every Python source line.
    for _name in ("p06_postchecks.py", "p08_selection_driver.py"):
        _source = (WS / "paper_pipeline_parts" / _name).read_text(encoding="utf-8")
        check(f"the full {_name} is not provider evidence",
              nb.agent_failure_kind("", _source) == "",
              nb.agent_failure_kind("", _source))
    guard = ("[2026-11-13 20:42:43] [codex-qwen] runaway guard: the agent session "
             "issued 1001 model turns (PAPER_EVAL_PAPER_REFINE_MAX_TURNS=1000); "
             "it is looping instead of finishing the stage")
    check("a guard stop outranks the comments it printed",
          nb.agent_failure_kind("", source_comments + "\n" + guard) == "runaway",
          nb.agent_failure_kind("", source_comments + "\n" + guard))
    check("the guard's own sentence is kept",
          nb.agent_runaway_reason(guard).startswith("the agent session issued 1001"),
          nb.agent_runaway_reason(guard))
    # The guard phrase itself appears in a pipeline source comment, and a
    # transcript that quotes it must not become the reported sentence.
    guard_comment = ("    # the proxy's own `runaway guard` sentence is the real "
                     "failure cause")
    check("a source line quoting the guard phrase is not the sentence",
          nb.agent_runaway_reason(guard_comment + "\n" + guard)
          == nb.agent_runaway_reason(guard),
          nb.agent_runaway_reason(guard_comment + "\n" + guard))
    check("a real 413 still classifies",
          nb.agent_failure_kind(
              "", "ERROR: unexpected status 413 Payload Too Large")
          == "context_overflow")

    root = scratch("paper_resume_overflow_")
    sb = root / "runs" / "r1_guided_review"
    sb.mkdir(parents=True)
    ctx = nb.Ctx(root)
    rec = {"id": "r1_guided_review", "kind": "guided_review", "round": 1, "sandbox": "runs/r1_guided_review",
           "status": "failed", "agent_session_id": SID,
           "last_error": ("the agent request exceeded the provider's payload/context limit"),
           "last_failure_kind": "context_overflow",
           "postcheck": {"ok": False, "errors": [], "warnings": []}}
    argv, key, reason = nb.resume_gate(ctx, rec, ["codex", "exec", "-"])
    check("the gate refuses to resend the oversized session",
          argv == [] and key == SID and reason == "", f"{argv} / {reason}")

    rec_runaway = dict(rec, last_failure_kind="runaway",
                       last_error=("the agent session issued 1001 model turns "
                                   "(PAPER_EVAL_PAPER_REFINE_MAX_TURNS=1000); it "
                                   "is looping instead of finishing the stage"))
    argv, key, reason = nb.resume_gate(ctx, rec_runaway, ["codex", "exec", "-"])
    check("the gate does not resume a session that was stopped for looping",
          argv == [] and key == SID and reason == "", f"{argv} / {reason}")

    prompts = (nb.review_prompt(Path("/tmp/sb"), "r1_guided_review", 1),
               nb.revise_prompt(Path("/tmp/sb"), "r1_a2_revise", 1),
               nb.judge_prompt(Path("/tmp/sb"), "r1_judge", 1, "t", 1, 1, ["v1"]))
    check("every session gets an explicit bounded-context rule",
          all("CONTEXT BUDGET" in p and "CONTACT SHEET" in p for p in prompts))
    check("the visual rule requires every page on a contact sheet first",
          "EVERY page" in nb.VISUAL_INSPECTION_RULE
          and "never re-open a page" in nb.VISUAL_INSPECTION_RULE)


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
    if MODE == "overflow":
        sys.stderr.write("ERROR: unexpected status 413 Payload Too Large: length limit exceeded\\n")
        sys.exit(1)
    if MODE == "partial":
        # Do the stage's work, then stop before the completion marker: the
        # 2026-11-13 case (a two-hour revise that ended one line short).
        sys.stdin = io.StringIO(prompt)
        rc = stub_agent.main()
        marker = Path.cwd() / "_pipeline_done.json"
        if marker.is_file():
            marker.unlink()
        sys.exit(rc)
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
    proc = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
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
    # The pair is the only selection form; drive the fake codex through
    # --agent-cmd so the resume contract is still exercised end to end.
    fake = json.dumps([str(bindir / "codex"), "exec", "-"])
    return subprocess.run([sys.executable, str(root / "paper_pipeline.py"), "run",
                           "--root", str(root), "--only", "rewrite",
                           "--agent-harness", "gpt-codex",
                           "--agent-model", "default",
                           "--agent-cmd", fake, *extra],
                          capture_output=True, text=True, timeout=1800, env=env)


def test_end_to_end_continuation():
    print()
    print("== a stalled stage is CONTINUED and the run completes ==")
    tmp = scratch("paper_resume_e2e_")
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


def test_end_to_end_partial_continuation():
    print()
    print("== a package that stopped BEFORE THE MARKER is continued ==")
    tmp = scratch("paper_resume_partial_")
    root = make_root(tmp)
    proc = run_with_fake_codex(root, make_fake_codex(tmp / "bin"), "--retries", "0",
                               mode="partial")
    out = proc.stdout + proc.stderr
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    rec = state["runs"]["r1_w1"]
    sources = [(e.get("attempt"), e.get("source"), e.get("ok"))
               for e in rec.get("attempts_log") or []]
    check("a stage that did its work but stopped before the marker is continued",
          rec["status"] == "done" and sources == [(1, "postcheck", False),
                                                  (2, "continuation", True)],
          f"{sources} {str((rec.get('postcheck') or {}).get('errors'))[:200]}")
    check("the continuation wrote the missing marker (the only thing that was missing)",
          (root / "runs" / "r1_w1" / "_pipeline_done.json").is_file())
    check("the stopped attempt spent NO fresh-attempt budget (only the continuation)",
          sum(1 for e in rec.get("attempts_log") or []
              if e.get("source") in ("postcheck", "process")) == 1
          and rec.get("resume_attempts") == {SID: 1},
          f"sources={sources} resume={rec.get('resume_attempts')}")
    check("the console names it as a continuation, not a retry",
          "[resume] r1_w1: continuing session" in out and "continuation 1/2" in out,
          out[-400:])


def test_end_to_end_limit():
    print()
    print("== a session that keeps stalling is continued at most twice ==")
    tmp = scratch("paper_resume_limit_")
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


def test_end_to_end_context_overflow():
    print()
    print("== a 413 process failure goes straight to a fresh attempt ==")
    tmp = scratch("paper_resume_overflow_e2e_")
    root = make_root(tmp)
    proc = run_with_fake_codex(root, make_fake_codex(tmp / "bin"), "--retries", "1",
                               mode="overflow")
    out = proc.stdout + proc.stderr
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    rec = state["runs"]["r1_w1"]
    sources = [e.get("source") for e in rec.get("attempts_log") or []]
    resume_counts = list((root / "runs").glob("r1_w1*/_fake_resume_count"))
    check("the oversized session is never continued",
          not resume_counts and "no continuation" in out
          and "provider already rejected" in out, out[-500:])
    check("both failures are recorded as fresh process attempts",
          sources.count("process") == 2 and "continuation" not in sources, str(sources))
    check("the run record classifies the failure",
          rec.get("last_failure_kind") == "context_overflow"
          and "payload/context limit" in str(rec.get("last_error")), str(rec.get("last_error")))


def test_turn_cap() -> None:
    """The per-session model-turn cap: 3000 by default, counted from dsh events.

    A long-horizon stage (a thesis revision) needs thousands of turns, so the
    cap is generous; it exists to stop a LOOP. The counter reads the harness's
    own `turn_end` events, so it is enforced for the default dsh agent and the
    attempt records `turn_cap_enforced` when the stream carried no such signal.
    """
    print()
    print("== the per-session model-turn cap (default 3000) ==")
    old = os.environ.get("PAPER_PIPELINE_MAX_TURNS")
    try:
        os.environ.pop("PAPER_PIPELINE_MAX_TURNS", None)
        check("the default cap is 3000", nb.pipeline_max_turns() == 3000,
              str(nb.pipeline_max_turns()))
        os.environ["PAPER_PIPELINE_MAX_TURNS"] = "0"
        check("0 disables the cap", nb.pipeline_max_turns() == 0)
        for n_lines, cap, want_hit in ((5, 3, True), (2, 3, False)):
            os.environ["PAPER_PIPELINE_MAX_TURNS"] = str(cap)
            sb = scratch("turncap_")
            (sb / "PROMPT.md").write_text("noop", encoding="utf-8")
            script = ("import sys\n"
                      f"for _ in range({n_lines}):\n"
                      "    sys.stdout.write('{\"type\": \"turn_end\"}\\n'); "
                      "sys.stdout.flush()\n")
            rec = {"id": "r1_guided_review", "kind": "guided_review",
                   "round": 1, "sandbox": str(sb)}
            res = nb._execute_attempt_in(sb, rec, [sys.executable, "-c", script], 60)
            check(f"{n_lines} turn_end event(s), cap {cap}: hit={want_hit}",
                  bool(rec.get("turn_cap_hit")) is want_hit, str(res.get("error")))
            check(f"{n_lines} turn_end event(s), cap {cap}: the cap was enforceable",
                  bool(rec.get("turn_cap_enforced")) is True)
            check(f"{n_lines} turn_end event(s), cap {cap}: the run record carries the cap",
                  rec.get("max_turns") == cap)
            entry = nb.record_attempt(None, rec, False, ["noop"])
            check(f"{n_lines} turn_end event(s), cap {cap}: the per-attempt history records it",
                  entry.get("max_turns") == cap
                  and entry.get("turn_cap_hit") is want_hit
                  and entry.get("turn_cap_enforced") is True)
            if want_hit:
                check("the cap verdict is a runaway, not a provider 413",
                      res.get("failure_kind") == "runaway"
                      and f"{cap}-turn cap" in (res.get("error") or ""), str(res))
                check("the attempt header records the cap",
                      f"max_turns: {cap}" in (sb / "_agent.log").read_text(encoding="utf-8"))
    finally:
        if old is None:
            os.environ.pop("PAPER_PIPELINE_MAX_TURNS", None)
        else:
            os.environ["PAPER_PIPELINE_MAX_TURNS"] = old


def main() -> int:
    try:
        test_argv_forms()
        test_session_id_capture()
        test_gate()
        test_context_overflow_gate()
        test_turn_cap()
        test_end_to_end_continuation()
        test_end_to_end_partial_continuation()
        test_end_to_end_limit()
        test_end_to_end_context_overflow()
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

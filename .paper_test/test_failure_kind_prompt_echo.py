#!/usr/bin/env python3
"""The orchestrator's own words are not provider evidence.

Run:  python3 .paper_test/test_failure_kind_prompt_echo.py

A RETRY stage prompt quotes the previous attempt's failure verbatim
("... the agent request exceeded the provider's payload/context limit
(HTTP 413 / request too large) ..."), and `PREVIOUS_ATTEMPT_ERRORS.md` repeats
it.  Both live in the agent-writable sandbox, so an agent that echoes its prompt
or quotes the record put that sentence into the stream the failure classifier
scans, and every retry was classified as a FRESH context overflow: the failed
attempt was then not resumed (the gate refuses a continuation for an oversized
context) and the stage was retired after three phantom overflows.

These checks pin the split: text the ORCHESTRATOR wrote is excluded from the
scan, while a genuine provider overflow printed beside it is still classified.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
FAILS: list[str] = []
TMPDIRS: list[Path] = []


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_failure_kind_echo_pipeline", WS / "paper_pipeline.py")


def check(name: str, cond, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


PROMPT_ECHO = (
    "Fix these before writing the marker:\n"
    "  1. the agent request exceeded the provider's payload/context limit "
    "(HTTP 413 / request too large); a continuation would resend the same "
    "oversized context, so a fresh attempt is required\n")


# ---------------------------------------------------------------------------
# C01: `exclude` removes exactly the named text, and nothing else
# ---------------------------------------------------------------------------
def test_exclude_scope() -> None:
    print("\n== C01: the exclusion is scoped to the text it names ==")
    check("C01 a bare provider overflow is still classified",
          pp.agent_failure_kind("", "HTTP 413: Request Too Large")
          == "context_overflow")
    check("C01 the excluded text alone is NOT evidence",
          pp.agent_failure_kind("", PROMPT_ECHO, exclude=(PROMPT_ECHO,)) == "",
          str(pp.agent_failure_kind("", PROMPT_ECHO, exclude=(PROMPT_ECHO,))))
    mixed = PROMPT_ECHO + "ERROR: unexpected status 413 Payload Too Large\n"
    check("C01 a genuine overflow printed BESIDE the echo is still classified",
          pp.agent_failure_kind("", mixed, exclude=(PROMPT_ECHO,))
          == "context_overflow")
    check("C01 an empty exclusion entry excludes nothing (no wildcard)",
          pp.agent_failure_kind("", PROMPT_ECHO, exclude=("", None))
          == pp.agent_failure_kind("", PROMPT_ECHO),
          "an empty/None entry must behave exactly like the default call")
    check("C01 the default call keeps the unexcluded behaviour",
          pp.agent_failure_kind("", PROMPT_ECHO) == "context_overflow")
    check("C01 source lines quoted from this module stay filtered",
          pp.agent_failure_kind("", '# a bare status line (`413 Payload Too Large`')
          == "", "the 3.11.6 `_stderr_evidence` filter")

    # The transcript does not echo the prompt byte-for-byte: the prompt's
    # display budget truncates the line and the transcript re-indents it. The
    # observed 2026-11-18 retry echo lost "... so a fresh attempt is required"
    # and kept two leading spaces, so a whole-text replacement did not match.
    full = ("1. the agent request exceeded the provider's payload/context limit "
            "(HTTP 413 / request too large); a continuation would resend the same "
            "oversized context, so a fresh attempt is required")
    echo = ("  1. the agent request exceeded the provider's payload/context limit "
            "(HTTP 413 / request too large); a continuation would resend the same "
            "oversized context, so ")
    check("C01 a truncated, re-indented echo is still excluded",
          pp.agent_failure_kind("", echo, exclude=(full + "\n",)) == "",
          str(pp.agent_failure_kind("", echo, exclude=(full + "\n",))))
    check("C01 a wrapped continuation line is still excluded",
          pp.agent_failure_kind(
              "", "      (HTTP 413 / request too large); a continuation would "
                  "resend the same oversized context, so a fresh attempt is required",
              exclude=(full + "\n",)) == "")


# ---------------------------------------------------------------------------
# C01b: a quoted previous sentence does not name THIS session's guard
# ---------------------------------------------------------------------------
def test_runaway_reason_excludes_prompt() -> None:
    print("\n== C01b: the guard sentence comes from this session, not the prompt ==")
    stale = ("runaway agent guard: the agent session reached its 1383-turn cap "
             "(PAPER_EVAL_PAPER_REFINE_MAX_TURNS=1383) after 1384 model turns; "
             "the stage is unfinished")
    real = ('ERROR: {"error": {"message": "runaway agent guard: the agent session '
            'reached its 2827-turn cap (PAPER_EVAL_PAPER_REFINE_MAX_TURNS=2827) '
            'after 2828 model turns; the stage is unfinished"}}')
    prompt = "previous attempt failed:\n  4. " + stale + "\n"
    check("C01b without the exclusion the stale prompt sentence wins",
          "1383" in pp.agent_runaway_reason("  4. " + stale + "\n" + real))
    got = pp.agent_runaway_reason("  4. " + stale + "\n" + real, exclude=(prompt,))
    check("C01b with the exclusion the real guard line wins",
          "2827" in got and "1383" not in got, got)


# ---------------------------------------------------------------------------
# C02: an agent that echoes its own prompt is not a context overflow
# ---------------------------------------------------------------------------
def test_prompt_echo_end_to_end() -> None:
    print("\n== C02: echoing PROMPT.md does not fabricate a 413 ==")
    sb = scratch("paper_echo_prompt_")
    (sb / "PROMPT.md").write_text("# stage prompt\n" + PROMPT_ECHO, encoding="utf-8")
    rec = {"id": "r1_guided_review", "kind": "guided_review", "round": 1,
           "sandbox": str(sb)}
    cmd = [sys.executable, "-c",
           "import sys; sys.stderr.write(open('PROMPT.md', encoding='utf-8').read()); "
           "sys.exit(1)"]
    res = pp._execute_attempt_in(sb, rec, cmd, 30)
    check("C02 the caller excludes the prompt it piped to the agent",
          res.get("failure_kind") == "", str(res.get("failure_kind")))

    # The same echo plus the agent's OWN provider error must stay classified:
    # the accommodation is an exclusion, never a blanket "ignore stderr".
    sb2 = scratch("paper_echo_prompt_genuine_")
    (sb2 / "PROMPT.md").write_text("# stage prompt\n" + PROMPT_ECHO, encoding="utf-8")
    rec2 = {"id": "r1_guided_review", "kind": "guided_review", "round": 1,
            "sandbox": str(sb2)}
    cmd2 = [sys.executable, "-c",
            "import sys; sys.stderr.write(open('PROMPT.md', encoding='utf-8').read()); "
            "sys.stderr.write('ERROR: 413 Payload Too Large\\n'); sys.exit(1)"]
    res2 = pp._execute_attempt_in(sb2, rec2, cmd2, 30)
    check("C02 a real provider overflow beside the echo is still classified",
          res2.get("failure_kind") == "context_overflow", str(res2.get("failure_kind")))


# ---------------------------------------------------------------------------
# C03: the previous-attempt record the prompt points at is excluded too
# ---------------------------------------------------------------------------
def test_previous_attempt_record_echo() -> None:
    print("\n== C03: catting PREVIOUS_ATTEMPT_ERRORS.md does not fabricate a 413 ==")
    sb = scratch("paper_echo_record_")
    (sb / "PROMPT.md").write_text("# stage prompt (no failure text here)\n",
                                  encoding="utf-8")
    (sb / "PREVIOUS_ATTEMPT_ERRORS.md").write_text(
        "# COMPLETE previous-attempt failure record\n\n" + PROMPT_ECHO,
        encoding="utf-8")
    rec = {"id": "r1_a2_revise", "kind": "revise", "round": 1, "sandbox": str(sb)}
    cmd = [sys.executable, "-c",
           "import sys; "
           "sys.stderr.write(open('PREVIOUS_ATTEMPT_ERRORS.md', encoding='utf-8').read()); "
           "sys.exit(1)"]
    res = pp._execute_attempt_in(sb, rec, cmd, 30)
    check("C03 the record the prompt tells the agent to read is not evidence",
          res.get("failure_kind") == "", str(res.get("failure_kind")))


def main() -> int:
    test_exclude_scope()
    test_prompt_echo_end_to_end()
    test_runaway_reason_excludes_prompt()
    test_previous_attempt_record_echo()
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL FAILURE-KIND PROMPT-ECHO CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

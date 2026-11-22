#!/usr/bin/env python3
"""Fix-wave 1, batch I_p07p08: regressions for the p07/p08 defects.

Run:  conda run -n paper-refine-test python .paper_test/test_fix_wave1_I_p07p08.py

  F01  an audit count whose tail says the check never RAN is not a disposition.
  F40  an inability must name an object/reason, not a determiner.
  F65  DIFF_LEDGER verdict/size cells outside the prompt's vocabularies fail.
  F68  a legal count plus an item-level evidence negation is still a verdict.
  F144 a backticked `stands` probe verdict is a verdict.
  F161 `Results (page 7)` resolves like `Results, page 7`.
  F30  a timed-out session keeps its transcript, does not stall 30 s, and marks
       an incomplete pipe.
  F122 an auxiliary session cannot overwrite the accepted revise record.
  F139 the dsh capability probe runs in its own group and kills the tree.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS, TMPDIRS = [], []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fix_wave1_I", WS / "paper_pipeline.py")


def test_audit_gate():
    print("\n== F01/F40/F68: the audit coverage disposition gate ==")
    for bad in ("0 findings; the check was not performed",
                "0 findings; the sweep could not run",
                "0 findings -- not executed",
                "3 findings; the pass wasn't run"):
        check(f"F01 {bad!r} is refused", pp._audit_disposition_ok(bad) is False)
    cov = [{"check": f"M{i}", "disposition": "0 findings; the sweep could not run"}
           for i in range(1, 37)] + [{"check": f"J{i}",
                                      "disposition": f"clean -- basis: artifacts/J{i}.md"}
                                     for i in range(1, 6)]
    probs = pp.audit_coverage_problems({"dispositions": [], "coverage": cov})
    check("F01 a table of non-run counts is refused row by row",
          len(probs) == 36, f"{len(probs)} problem(s)")
    for good in ("3 findings; unable to check one quoted line",
                 "3 findings confirmed -- one location could not be verified",
                 "3 findings; X-910 could not be re-derived (quote missing)",
                 "0 findings; the sweep was re-derived from M1"):
        check(f"F68 {good!r} is a verdict", pp._audit_disposition_ok(good) is True)
    for bad in ("unable to check the", "unable to verify the", "unable -- the"):
        check(f"F40 {bad!r} names no object and is refused",
              pp._audit_disposition_ok(bad) is False)
    check("F40 a named object/reason is still accepted",
          pp._audit_disposition_ok("unable to check artwork/text parity") is True
          and pp._audit_disposition_ok("unable -- no PDF renderer") is True)


def test_ledger_vocabularies():
    print("\n== F65: DIFF_LEDGER verdict/size vocabularies ==")
    out = scratch("wave1I_led_") / "integrated"
    (out / "work" / "diffs").mkdir(parents=True)
    (out / "DIFF_LEDGER.md").write_text(
        "| donor | location | size | donor says | self says | verdict | revalidated | "
        "why | effect | artifact | finding effect |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
        "| w2 | Methods | huge | x | y | delete | confirmed | because | none | "
        "work/diffs/a.md | none |\n", encoding="utf-8")
    rep = pp.integration_ledger_report(out, ["w2"], False)
    check("an out-of-vocabulary verdict is reported",
          rep["invalid_verdict"] == ["w2: verdict=delete"], str(rep["invalid_verdict"]))
    check("an out-of-vocabulary size is reported",
          rep["invalid_size"] == ["w2: size=huge"], str(rep["invalid_size"]))
    (out / "DIFF_LEDGER.md").write_text(
        "| donor | artifact | size | verdict | finding effect | revalidated |\n"
        "|---|---|---|---|---|---|\n"
        "| w2 | work/diffs/a.md | small | port | preserves F-001 | confirmed |\n"
        "| w1 | work/diffs/b.md | large | keep-self | preserves F-002 | rejected |\n"
        "| w3 | work/diffs/c.md | small | ignore-cosmetic | none | confirmed |\n",
        encoding="utf-8")
    rep = pp.integration_ledger_report(out, ["w2"], False)
    check("the documented vocabularies stay clean",
          not rep["invalid_verdict"] and not rep["invalid_size"], str(rep))
    (out / "DIFF_LEDGER.md").write_text(
        "| donor | artifact | size | verdict | finding effect | revalidated |\n"
        "|---|---|---|---|---|---|\n"
        "| w2 | work/diffs/a.md | small | maybe | none | confirmed |\n"
        "| w1 | work/diffs/b.md | large | drop | none | rejected |\n",
        encoding="utf-8")
    rep = pp.integration_ledger_report(out, ["w2"], False)
    check("an unclassified token is reported but the legacy non-edit `drop` is not",
          rep["invalid_verdict"] == ["w2: verdict=maybe"], str(rep["invalid_verdict"]))
    # The pre-flight must fail the same ledger the postcheck does.
    sb = scratch("wave1I_self_")
    (sb / "integrated" / "work" / "diffs").mkdir(parents=True)
    shutil.copy(out / "DIFF_LEDGER.md", sb / "integrated" / "DIFF_LEDGER.md")
    (sb / "integrated" / "DIFF_LEDGER.md").write_text(
        "| donor | artifact | size | verdict | finding effect | revalidated |\n"
        "|---|---|---|---|---|---|\n"
        "| w2 | work/diffs/a.md | huge | delete | none | confirmed |\n",
        encoding="utf-8")
    _ok, errs, _warns = pp.sandbox_selfcheck(sb, "integrate", "r1_i1", 1)
    check("the pre-flight rejects the same invalid verdict and size",
          sum("outside" in e for e in errs) >= 2, str(errs)[:300])


def test_probe_and_locator():
    print("\n== F144/F161: probe verdicts and parenthesised page locators ==")
    row = {"probe id": "P2-01", "reviewer's disposition": "no anomalies",
           "your verdict": "`stands`", "evidence": "checked base/"}
    check("F144 a backticked `stands` is read as a verdict",
          bool(pp._probe_audit_verdict(row)), repr(pp._probe_audit_verdict(row)))
    row["your verdict"] = "**needs-evidence**"
    check("F144 a bolded `needs-evidence` is read as a verdict",
          bool(pp._probe_audit_verdict(row)))
    t = "# Results\n\nThe assay ran.\n"
    b = "# Results\n\nThe assay ran here.\n"
    for loc in ("Results", "Results (page 7)", "Results, page 7", "Results p. 7"):
        check(f"F161 {loc!r} resolves", pp._response_location_problem(
            "R1-1", "main.md", loc, "The assay ran here.", "The assay ran.", b, t) is None)
    check("F161 an invented locator is still refused",
          pp._response_location_problem("R1-1", "main.md", "Appendix 9", "", "", b, t))


def test_timeout_transcript():
    print("\n== F30: a timed-out session keeps its transcript and does not stall ==")
    cmd = ["/bin/sh", "-c",
           "setsid sh -c 'sleep 25' & echo OUT-LINE; echo ERR-LINE 1>&2; sleep 25"]

    def run(blind):
        sb = scratch("wave1I_f30_")
        (sb / "PROMPT.md").write_text("hi", encoding="utf-8")
        rec = {"id": "r1_a1_revise", "kind": "revise", "round": 1,
               "attempts": 0, "stage_attempts": {}}
        original = pp._descendant_pids
        if blind:
            pp._descendant_pids = lambda pid: []
        t0 = time.time()
        try:
            pp._execute_attempt_in(sb, rec, cmd, 1)
        finally:
            pp._descendant_pids = original
        elapsed = time.time() - t0
        log = (sb / "_agent.log").read_text(encoding="utf-8")
        return elapsed, log

    elapsed, log = run(False)
    check("F30 the escaped helper is killed and the attempt ends promptly",
          elapsed < 12, f"elapsed={elapsed:.1f}s")
    check("F30 the transcript of a timed-out session is not empty",
          "OUT-LINE" in log and "ERR-LINE" in log)
    elapsed, log = run(True)
    check("F30 a pipe held past the timeout is bounded, not a 30 s stall",
          elapsed < 12, f"elapsed={elapsed:.1f}s")
    check("F30 the partial transcript is kept when the reader cannot return",
          "OUT-LINE" in log, " ".join(log.split())[:90])
    check("F30 the record carries the incomplete-transcript marker",
          "TRANSCRIPT INCOMPLETE" in log)


def test_aux_identity():
    print("\n== F122: an auxiliary session cannot rewrite the stage's identity ==")
    sb = scratch("wave1I_f122_")

    def fake_execute(sandbox, rec, cmd, timeout, prompt_file, log_name, archive):
        rec.update(agent_command=["/bin/true"], prompt_file=prompt_file,
                   prompt_sha256="aux-digest", agent_model={"id": "audit"},
                   max_turns=9, turn_cap_hit=False, turn_cap_enforced=True,
                   last_attempt_started="AUX-START")
        return {"rc": 0, "dur": 1.0, "error": "", "log": ""}

    original = pp._execute_attempt_in
    pp._execute_attempt_in = fake_execute
    try:
        rec = {"id": "r1_a2_revise", "kind": "revise", "round": 1,
               "prompt_file": "PROMPT.md", "prompt_sha256": "stage-digest",
               "agent_command": ["revise-agent"], "agent_model": {"id": "revise"},
               "last_attempt_started": "STAGE-START"}
        pp._run_aux_session(sb, rec, ["/bin/true"], 5,
                            pp.REVISION_AUDIT_PROMPT_FILE, "_aux.log")
        check("F122 the revise record keeps its own prompt/digest/command/model",
              (rec.get("prompt_file"), rec.get("prompt_sha256"),
               rec.get("agent_command"), rec.get("agent_model"),
               rec.get("last_attempt_started"))
              == ("PROMPT.md", "stage-digest", ["revise-agent"],
                  {"id": "revise"}, "STAGE-START"), str(rec))
        fresh = {"id": "r2_a1_revise", "kind": "revise", "round": 1}
        pp._run_aux_session(sb, fresh, ["/bin/true"], 5,
                            pp.REVISION_AUDIT_PROMPT_FILE, "_aux.log")
        check("F122 identity fields the stage never had are not left behind",
              not [k for k in ("prompt_file", "prompt_sha256", "agent_command",
                               "agent_model", "max_turns") if k in fresh], str(fresh))
    finally:
        pp._execute_attempt_in = original


def test_dsh_probe():
    print("\n== F139: the capability probe kills its whole tree on timeout ==")
    d = scratch("wave1I_f139_")
    exe, pidfile = d / "fakedsh", d / "child.pid"
    exe.write_text("#!/bin/sh\nsetsid sh -c 'sleep 30' &\necho $! > " + str(pidfile)
                   + "\necho help\nsleep 30\n", encoding="utf-8")
    exe.chmod(0o755)
    saved = pp.DSH_PROBE_TIMEOUT_SECONDS
    pp.DSH_PROBE_TIMEOUT_SECONDS = 1
    try:
        t0 = time.time()
        out = pp._probe_dsh_headless(str(exe))
        elapsed = time.time() - t0
    finally:
        pp.DSH_PROBE_TIMEOUT_SECONDS = saved
    check("F139 a hung probe returns '' instead of hanging", out == "" and elapsed < 10,
          f"elapsed={elapsed:.1f}s")
    child = int(pidfile.read_text(encoding="utf-8").strip())
    time.sleep(0.3)
    alive = Path(f"/proc/{child}").exists()
    if alive:
        try:
            os.kill(child, 9)
        except OSError:
            pass
    check("F139 the probe's escaped helper does not survive the timeout", not alive,
          f"pid {child}")


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def main():
    for fn in (test_audit_gate, test_ledger_vocabularies, test_probe_and_locator,
               test_timeout_transcript, test_aux_identity, test_dsh_probe):
        try:
            fn()
        except Exception as exc:                                   # noqa: BLE001
            check(f"{fn.__name__} raised {type(exc).__name__}", False, str(exc)[:200])
    cleanup()
    if FAILS:
        print(f"\n{len(FAILS)} CHECK(S) FAILED: {', '.join(FAILS)}")
        return 1
    print("\nALL fix-wave1 I_p07p08 REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

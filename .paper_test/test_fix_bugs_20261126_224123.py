#!/usr/bin/env python3
"""Regression checks for the 2026-11-26 22:41 fix-bugs wave (candidates F01-F99).

One block per confirmed candidate. Fixtures are temp dirs; no network, no Word,
no repo writes (the F08/F69 blocks run a child process against a temp tree).

Run:  python3 .paper_test/test_fix_bugs_20261126_224123.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS))
import paper_pipeline as pp  # noqa: E402

FAILS = []


def check(name, condition, detail=""):
    if condition:
        print(f"[ok ] {name}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {name}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(name)


def scratch(prefix):
    return Path(tempfile.mkdtemp(prefix=f"fixbugs224123_{prefix}_"))


# ---------------------------------------------------------------------------
# F16 / F18 -- JSON extraction and the shared result-closure gate
# ---------------------------------------------------------------------------
def t_f16_f18():
    print("\n== F16 / F18 ==")
    buried = pp._json_from_text("A" * 1000 + '{ "a": 1 }' + " in this sample.", True)
    check("F16 a JSON fragment buried in long prose is not the payload", buried is None,
          repr(buried))
    check("F16 the F30 trailing-example shape still recovers the document",
          pp._json_from_text('{"a":1}\nNote: schema example is {"example": true}', True)
          == {"a": 1})
    check("F16 a fenced schema then the real document then an example still works",
          pp._json_from_text(
              '~~~json\n{"schema":"x"}\n~~~\nThe document is:\n{"a":1,"b":2}\n'
              'Note: schema example is {"z":3,"q":4,"r":5,"s":6}', True)
          == {"a": 1, "b": 2})
    check("F18 a bare `nothing found` is a result closure",
          pp._reason_is_generic_filler("nothing found"))
    check("F18 the passive `no problems were found` is refused",
          pp._reason_is_generic_filler("no problems were found"))
    check("F18 a count plus a nothing-found tail is refused",
          not pp._coverage_disposition_ok("0 findings; nothing found"))
    check("F18 `examined, nothing found` still names the work",
          not pp._reason_is_generic_filler("examined, nothing found"))
    check("F18 `no problems found in section 3` names its object",
          not pp._reason_is_generic_filler("no problems found in section 3"))
    check("F18 `nothing found in section 3` names its object too",
          not pp._reason_is_generic_filler("nothing found in section 3"))
    check("F18 `nothing was found in base/main.md` names its object",
          not pp._reason_is_generic_filler("nothing was found in base/main.md"))
    check("F18 a bare count plus a nothing-found tail is still a closure",
          pp._reason_is_generic_filler("0 findings; nothing found"))


# ---------------------------------------------------------------------------
# F39 / F93 -- audit coverage counts and confirm dispositions
# ---------------------------------------------------------------------------
def t_f39_f93():
    print("\n== F39 / F93 ==")
    cov = [{"check": c, "disposition": "clean -- basis: stub artifact"}
           for c in pp.AUDIT_COVERAGE_CHECKS]
    frozen = [{"id": "F-1", "check": "M1", "severity": "minor"}]
    fabricated = [{"check": c, "disposition": "7 findings"} for c in pp.AUDIT_COVERAGE_CHECKS]
    problems = pp.audit_coverage_problems(
        {"dispositions": [{"id": "F-1", "verdict": "confirm"}], "coverage": fabricated},
        frozen)
    check("F39 a fabricated count is refused when the frozen list backs it",
          any("claims 7 finding(s)" in p for p in problems), str(problems[:1]))
    zero = [{"check": c, "disposition": "0 findings"} for c in pp.AUDIT_COVERAGE_CHECKS]
    problems = pp.audit_coverage_problems(
        {"dispositions": [{"id": "F-1", "verdict": "confirm"}], "coverage": zero}, frozen)
    check("F39 a zero count contradicted by a confirm is refused",
          any("claims 0 findings" in p for p in problems), str(problems[:1]))
    bare = pp.audit_artifact_problems(
        {"round": 1, "dispositions": [{"id": "F-1", "verdict": "confirm"}],
         "adds": [], "coverage": cov}, ["F-1"])
    check("F93 a confirm with no reason/evidence is refused",
          any("needs a `reason`" in p for p in bare)
          and any("needs `evidence`" in p for p in bare), str(bare))
    ok = pp.audit_artifact_problems(
        {"round": 1, "dispositions": [{"id": "F-1", "verdict": "confirm",
                                       "reason": "the quoted sentence is present in base/main.md",
                                       "evidence": "base/main.md:3"}],
         "adds": [], "coverage": cov}, ["F-1"])
    check("F93 an evidenced confirm still passes", ok == [], str(ok))


# ---------------------------------------------------------------------------
# F41 / F42 -- human/LLM provenance and completed-work prose in the draft
# ---------------------------------------------------------------------------
def t_f41_f42():
    print("\n== F41 / F42 ==")
    sb = scratch("f41")
    (sb / "feedback" / "files").mkdir(parents=True)
    (sb / "feedback" / "llm" / "files").mkdir(parents=True)
    (sb / "feedback" / "files" / "human__editor.txt").write_text("human", encoding="utf-8")
    (sb / "feedback" / "llm" / "files" / "llm__editor.txt").write_text("llm", encoding="utf-8")
    check("F41 a bare basename collision is not classified as LLM",
          not pp._concern_names_llm(sb, {"source": "editor.txt"}))
    check("F41 the exact staged LLM name is still LLM",
          pp._concern_names_llm(sb, {"source": "llm__editor.txt"}))
    check("F41 the stream-qualified corpus label is still LLM",
          pp._concern_names_llm(sb, {"source": "llm_review_feedback/editor.txt"}))
    check("F41 a human corpus label is not LLM",
          not pp._concern_names_llm(sb, {"source": "human_review_feedback/editor.txt"}))
    claim = pp.response_completed_claim("We have added a new figure and changed the text.")
    check("F42 a completed-work Response claim is detected", claim is not None,
          claim.group(0) if claim else "")
    check("F42 a planned future answer is not a completed claim",
          pp.response_completed_claim("We will add a new figure.") is None)
    check("F42 a negated claim is not a completed claim",
          pp.response_completed_claim("We have not added a new figure.") is None)
    shutil.rmtree(sb, ignore_errors=True)


# ---------------------------------------------------------------------------
# F44 -- writer-input aliases are materialized, escapes are refused
# ---------------------------------------------------------------------------
def t_f44():
    print("\n== F44 ==")
    t = scratch("f44")
    root = t / "root"
    (root / "non_revised" / "raw_data").mkdir(parents=True)
    (root / "state.json").write_text("{}", encoding="utf-8")
    (root / "non_revised" / "raw_data" / "x.txt").write_text("hello\n", encoding="utf-8")
    (root / "non_revised" / "raw_data" / "n.txt").write_text("nested\n", encoding="utf-8")
    os.symlink("n.txt", root / "non_revised" / "raw_data" / "alias.txt")
    sb = root / "runs" / "r1_revise"
    (sb / "non_revised").mkdir(parents=True)
    os.symlink(os.path.relpath(root / "non_revised" / "raw_data", sb / "non_revised"),
               sb / "non_revised" / "raw_data", target_is_directory=True)
    try:
        digest = pp._write_input_digest(sb / "non_revised")
        check("F44 the canonical evidence link with a nested alias is hashed",
              bool(digest))
    except Exception as exc:  # noqa: BLE001
        check("F44 the canonical evidence link with a nested alias is hashed", False,
              f"{type(exc).__name__}: {exc}")
    os.symlink("/etc/passwd", root / "non_revised" / "raw_data" / "bad.txt")
    try:
        pp._write_input_digest(sb / "non_revised")
        check("F44 a nested link escaping the run root is refused", False)
    except ValueError as exc:
        check("F44 a nested link escaping the run root is refused",
              "escapes" in str(exc), str(exc)[:120])
    shutil.rmtree(t, ignore_errors=True)


# ---------------------------------------------------------------------------
# F52 -- the final rename re-checks a symlinked destination
# ---------------------------------------------------------------------------
def t_f52():
    print("\n== F52 ==")
    for name, var, tmp in (("docx2pdf.sh", "PDF", "PDF_TMP"),
                           ("docxcompare.sh", "OUTPUT", "OUTPUT_TMP")):
        src = (WS / name).read_text(encoding="utf-8")
        guard = re.search(
            rf'if \[\[ -L "\${var}".{{0,120}}?then.*?mv -f -- "\${tmp}" "\${var}"',
            src, re.S)
        check(f"F52 {name} re-checks the destination immediately before mv",
              guard is not None)
        proc = subprocess.run(["bash", "-n", str(WS / name)], capture_output=True, text=True)
        check(f"F52 {name} has valid bash syntax", proc.returncode == 0,
              proc.stderr[-120:])


# ---------------------------------------------------------------------------
# F69 -- scan --pdf on a missing PDF is an input error
# ---------------------------------------------------------------------------
def t_f69():
    print("\n== F69 ==")
    try:
        import docx
    except Exception as exc:  # noqa: BLE001
        check("F69 python-docx is available for the scanner fixture", False, str(exc))
        return
    t = scratch("f69")
    doc = t / "ok.docx"
    d = docx.Document()
    d.add_paragraph("Hello world.")
    d.save(doc)
    proc = subprocess.run(
        [sys.executable, "-B", str(WS / "paper_docx_format.py"), "scan", str(doc),
         "--pdf", str(t / "missing.pdf")], capture_output=True, text=True, cwd=str(WS))
    check("F69 a missing --pdf exits 2 with an input error",
          proc.returncode == 2 and "no such file" in (proc.stdout + proc.stderr),
          f"rc={proc.returncode} {(proc.stdout + proc.stderr)[-160:]}")
    # An unreadable regular file is an input error too, not a high FMT-S2 row
    # in a successful scan (R03-20261126). A root/privileged runner can read a
    # mode-000 file, so only assert the refusal where the mode bites.
    unreadable = t / "unreadable.pdf"
    unreadable.write_bytes(b"%PDF-1.4\n%%EOF\n")
    os.chmod(unreadable, 0o000)
    try:
        if os.access(unreadable, os.R_OK):
            print("[ok ] F69 an unreadable --pdf is an input error  -- "
                  "(skipped: this user can read a mode-000 file)")
        else:
            proc = subprocess.run(
                [sys.executable, "-B", str(WS / "paper_docx_format.py"), "scan",
                 str(doc), "--pdf", str(unreadable)],
                capture_output=True, text=True, cwd=str(WS))
            check("F69 an unreadable --pdf is an input error",
                  proc.returncode == 2
                  and "cannot read" in (proc.stdout + proc.stderr),
                  f"rc={proc.returncode} {(proc.stdout + proc.stderr)[-160:]}")
    finally:
        os.chmod(unreadable, 0o644)
    shutil.rmtree(t, ignore_errors=True)


# ---------------------------------------------------------------------------
# F76 -- page count need not be on the template's own name line
# ---------------------------------------------------------------------------
def t_f76():
    print("\n== F76 ==")
    docs = [{"source": "tpl.docx", "pages": 3}]
    check("F76 name and page count on separate adjacent lines pass",
          pp._template_comparison_missing(docs, "## Templates\ntpl.docx\n3 pages\n") == [])
    check("F76 the same-line form still passes",
          pp._template_comparison_missing(docs, "tpl.docx (3 pages)\n") == [])
    check("F76 a denial sentence still fails",
          pp._template_comparison_missing(
              docs, "tpl.docx (3 pages) was NOT visually compared\n") == ["tpl.docx"])
    check("F76 a denial for another template does not hide this one",
          pp._template_comparison_missing(
              docs, "- tpl.docx: 3 pages, visually compared\n"
                    "- old.docx: 2 pages NOT visually compared\n") == [])
    check("F76 the same mixed table block passes",
          pp._template_comparison_missing(
              docs, "| tpl.docx | 3 pages | visually compared |\n"
                    "| old.docx | 2 pages | NOT visually compared |\n") == [])


# ---------------------------------------------------------------------------
# F77 -- nested bash extglob
# ---------------------------------------------------------------------------
def t_f77():
    print("\n== F77 ==")
    rx = pp._extglob_to_regex("@(a@(b|c)|d)")
    check("F77 a nested extglob compiles", rx is not None)
    if rx:
        check("F77 the nested alternatives match",
              all(rx.match(s) for s in ("ab", "ac", "d"))
              and not any(rx.match(s) for s in ("ad", "a")))
    check("F77 an ordinary alternation is unchanged",
          pp._extglob_to_regex("@(a|b)").match("b") is not None)


# ---------------------------------------------------------------------------
# F88 -- a clean basis must resolve under the sandbox
# ---------------------------------------------------------------------------
def t_f88():
    print("\n== F88 ==")
    t = scratch("f88")
    (t / "base").mkdir()
    (t / "base" / "main.md").write_text("a\nb\n", encoding="utf-8")
    fabricated = [{"check": c, "disposition":
                   "clean -- basis: guided_review/artifacts/DOES_NOT_EXIST.md"}
                  for c in pp.AUDIT_COVERAGE_CHECKS]
    problems = pp.audit_coverage_problems({"coverage": fabricated}, sb=t)
    check("F88 a fabricated audit basis is refused",
          any("does not resolve" in p for p in problems), str(problems[:1]))
    absolute = [{"check": c, "disposition": "clean -- basis: /etc/passwd"}
                for c in pp.AUDIT_COVERAGE_CHECKS]
    problems = pp.audit_coverage_problems({"coverage": absolute}, sb=t)
    check("F88 an out-of-sandbox absolute basis is refused",
          any("absolute path" in p for p in problems), str(problems[:1]))
    real = [{"check": c, "disposition": "clean -- basis: base/main.md:2"}
            for c in pp.AUDIT_COVERAGE_CHECKS]
    check("F88 a resolving basis passes",
          pp.audit_coverage_problems({"coverage": real}, sb=t) == [])
    check("F88 a line outside the cited file is refused",
          bool(pp._coverage_basis_locator_problems(
              "clean -- basis: main.md:99999", "", t, base_dir=t / "base")))
    (t / "guided_review" / "artifacts").mkdir(parents=True)
    (t / "guided_review" / "artifacts" / "M8_terms.md").write_text(
        "terms\n", encoding="utf-8")
    abbrev = [{"check": c, "disposition":
               "clean -- basis: e.g. guided_review/artifacts/M8_terms.md"}
              for c in pp.AUDIT_COVERAGE_CHECKS]
    check("F88 an abbreviation is not an artifact token",
          pp.audit_coverage_problems({"coverage": abbrev}, sb=t) == [])
    version = [{"check": c, "disposition":
                "clean -- basis: rerun under Python 3.12 against "
                "guided_review/artifacts/M8_terms.md"}
               for c in pp.AUDIT_COVERAGE_CHECKS]
    check("F88 a version number is not an artifact token",
          pp.audit_coverage_problems({"coverage": version}, sb=t) == [])
    shutil.rmtree(t, ignore_errors=True)


# ---------------------------------------------------------------------------
# F89 -- unreadable documents are tracking failures
# ---------------------------------------------------------------------------
def t_f89():
    print("\n== F89 ==")
    entry = {"comparisons": [],
             "skipped": [{"baseline": "a1",
                          "reason": "unreadable trackable file (not compared): is a symlink"}]}
    counts = pp.tracking_entry_counts(entry)
    check("F89 an unreadable document counts as failed", counts[3] == 1, str(counts))
    pp._close_tracking_entry(entry)
    check("F89 the entry status says FAILED", "1 FAILED" in entry.get("status", ""),
          entry.get("status"))


# ---------------------------------------------------------------------------
# F90 -- both sides must be decidable for a judge discovery row
# ---------------------------------------------------------------------------
def _judge_sb(root, target_disp, opponent_disp):
    sb = root / "judge_x_j1"
    dd = sb / "judge_review" / "discovery"
    dd.mkdir(parents=True)
    header = "| class | probe | checked | disposition |\n|---|---|---|---|\n"
    target_rows, opp_rows = [], []
    for i in range(5):
        tdisp = target_disp if i == 0 else f"clean - checked: target/f{i}.md"
        odisp = opponent_disp if i == 0 else f"clean - checked: v1/f{i}.md"
        target_rows.append(f"| class {i} | probe | target/f{i}.md | {tdisp} |")
        opp_rows.append(f"| class {i} | probe | v1/f{i}.md | {odisp} |")
    (dd / "target.md").write_text(header + "\n".join(target_rows) + "\n", encoding="utf-8")
    (dd / "v1.md").write_text(header + "\n".join(opp_rows) + "\n", encoding="utf-8")
    (sb / "scores.json").write_text(json.dumps({
        "run_id": "judge_x_j1", "target_id": "tok", "judge_index": 1,
        "comparisons": [{
            "opponent_label": "v1", "score": 2, "basis": "consistency",
            "resolved": [{"check": "X-001", "tier": "consistency", "severity": "minor",
                          "evidence": "fixture"}],
            "introduced": [],
            "checks": {c: "clean -- fixture" for c in pp.JUDGE_COVERAGE_CHECKS},
            "reason": "fixture"}], "notes": ""}), encoding="utf-8")
    return sb


def t_f90():
    print("\n== F90 ==")
    finding = ("finding - X-001 (category 2, Major): v1/f0.md: `evidence`")
    t = scratch("f90ok")
    sb = _judge_sb(t, "clean - checked: target/f0.md", finding)
    errs, _warns = pp.judge_discovery_problems(
        sb, {"kind": "judge", "label_map": {"v1": "v1"}})
    check("F90 a decidable pair passes", errs == [], str(errs))
    t2 = scratch("f90bad")
    sb2 = _judge_sb(t2, "unknown -- counterpart undecidable: target not readable", finding)
    errs, _warns = pp.judge_discovery_problems(
        sb2, {"kind": "judge", "label_map": {"v1": "v1"}})
    check("F90 an undecidable counterpart is refused",
          any("undecidable" in e for e in errs), str(errs))
    shutil.rmtree(t, ignore_errors=True)
    shutil.rmtree(t2, ignore_errors=True)


# ---------------------------------------------------------------------------
# F95 / F96 -- probe audit evidence and already-addressed locators
# ---------------------------------------------------------------------------
def t_f95_f96():
    print("\n== F95 / F96 ==")
    t = scratch("f95")
    (t / "guided_review" / "round2").mkdir(parents=True)
    (t / "guided_review" / "round2" / "probe_results.md").write_text(
        "| probe id | status | result |\n|---|---|---|\n"
        "| P2-01 | executed | no anomalies -- checked: base/main.md:3 |\n",
        encoding="utf-8")
    (t / "audit").mkdir()
    (t / "audit" / "PROBE_AUDIT.md").write_text(
        "| probe id | reviewer disposition | verdict | evidence |\n|---|---|---|---|\n"
        "| P2-01 | clean | needs-evidence |  |\n", encoding="utf-8")
    check("F95 a bare needs-evidence is refused",
          any("without naming the missing evidence" in e
              for e in pp.probe_audit_problems(t)))
    (t / "audit" / "PROBE_AUDIT.md").write_text(
        "| probe id | reviewer disposition | verdict | evidence |\n|---|---|---|---|\n"
        "| P2-01 | clean | needs-evidence | the closure does not quote base/main.md:3 |\n",
        encoding="utf-8")
    check("F95 a named missing evidence passes", pp.probe_audit_problems(t) == [])
    base = t / "base"
    base.mkdir()
    (base / "main.md").write_text("first line\nsecond line\n", encoding="utf-8")
    check("F96 a resolving base locator passes",
          pp._base_location_problem("base/main.md:2", base) == "",
          str(pp._base_location_problem("base/main.md:2", base)))
    check("F96 an invented or out-of-range locator is refused",
          bool(pp._base_location_problem("base/nope.md:1", base))
          and bool(pp._base_location_problem("base/main.md:99999", base)))
    shutil.rmtree(t, ignore_errors=True)


# ---------------------------------------------------------------------------
# F01 / F06 -- bounded response repair and a single repair chain
# ---------------------------------------------------------------------------
def t_f01_f06():
    print("\n== F01 / F06 ==")
    t = scratch("f01")
    sb = t / "sb"
    (sb / "response").mkdir(parents=True)
    (sb / "response_prerepair").mkdir()
    (sb / "response_prerepair" / "RESPONSE_TO_REVIEWERS.md").write_text(
        "# R\n## C1\n**Response:** a\n## C2\n**Response:** b\n", encoding="utf-8")
    (sb / "response" / "RESPONSE_TO_REVIEWERS.md").write_text(
        "# R\n## C1\n**Response:** A\n## C2\n**Response:** b\n", encoding="utf-8")
    (sb / "response_prerepair" / "response_map.json").write_text(json.dumps(
        {"rows": [{"id": "C1", "response": "a"}, {"id": "C2", "response": "b"}]}),
        encoding="utf-8")
    (sb / "response" / "response_map.json").write_text(json.dumps(
        {"rows": [{"id": "C1", "response": "A"}, {"id": "C2", "response": "b"}]}),
        encoding="utf-8")
    rows = [{"id": "C1", "action": "corrected"}, {"id": "C2", "action": "kept"}]
    check("F01 a corrected row licenses its own block only",
          pp.response_repair_scope_problems(sb, rows) == [])
    (sb / "response" / "RESPONSE_TO_REVIEWERS.md").write_text(
        "# R\n## C1\n**Response:** A\n## C2\n**Response:** B\n", encoding="utf-8")
    problems = pp.response_repair_scope_problems(sb, rows)
    check("F01 rewriting another concern block is refused",
          any("changed concern block 'C2'" in p for p in problems), str(problems))
    # A change INSIDE a fenced sample of a non-corrected block is still a
    # change to that block; the old comparison deleted fenced bytes from both
    # sides and saw nothing (R04-20261126).
    (sb / "response_prerepair" / "RESPONSE_TO_REVIEWERS.md").write_text(
        "# R\n## C1\n**Response:** a\n## C2\n**Response:** b\n"
        "```sh\nold command\n```\n", encoding="utf-8")
    (sb / "response" / "RESPONSE_TO_REVIEWERS.md").write_text(
        "# R\n## C1\n**Response:** A\n## C2\n**Response:** b\n"
        "```sh\nNEW command\n```\n", encoding="utf-8")
    problems = pp.response_repair_scope_problems(sb, rows)
    check("F01/R04 a fenced-sample change in a kept block is refused",
          any("changed concern block 'C2'" in p for p in problems), str(problems))

    # F06: repair=False must fail a non-empty plan instead of opening a second
    # repair pass; the response writer's one chain is the semantic p24 pair.
    wsb = scratch("f06")
    (wsb / "response").mkdir()
    (wsb / "response" / "letter.md").write_text("n = 10", encoding="utf-8")
    rec = {"id": "r1_response", "kind": "response", "round": 1}
    plan = [{"id": "RP-1", "file": "letter.md", "location": "line 1",
             "wrong": "n = 10", "correct": "n = 20", "basis": "base",
             "evidence": "e", "edit": "replace"}]

    def fake(sb, rec, cmd, timeout, *args):
        if rec["kind"] == "write-audit":
            pp.write_json_atomic(sb / "AUDIT.json", {"rows": plan, "blocked": []})
        return {"rc": 0, "dur": 0, "error": None}

    try:
        with mock.patch.object(pp, "_execute_attempt_raw", side_effect=fake):
            pp.audit_write_output(wsb, rec, ["stub"], 10, repair=False)
        check("F06 a report-only audit fails a repairable plan", False)
    except ValueError as exc:
        check("F06 a report-only audit fails a repairable plan",
              "single bounded-repair chain" in str(exc), str(exc)[:120])
    shutil.rmtree(t, ignore_errors=True)
    shutil.rmtree(wsb, ignore_errors=True)


# ---------------------------------------------------------------------------
# F08 -- --recreate refuses a non-empty, non-conda prefix without an opt-in
# ---------------------------------------------------------------------------
def t_f08():
    print("\n== F08 ==")
    t = scratch("f08")
    (t / "bin").mkdir()
    (t / "base" / "envs").mkdir(parents=True)
    (t / "exports").mkdir()
    conda = t / "bin" / "conda"
    conda.write_text(
        "#!/usr/bin/env bash\nset -u\ncase \"$1\" in\n"
        "  run) exit 1 ;;\n"
        "  env) if [ \"$2\" = remove ]; then echo 'EnvironmentLocationNotFound' >&2; exit 1; fi; exit 0 ;;\n"
        "  info) printf '%s\\n' \"$FAKE_CONDA_BASE\"; exit 0 ;;\n"
        "  create) exit 0 ;;\nesac\nexit 0\n", encoding="utf-8")
    conda.chmod(0o755)
    (t / "exports" / "paper-refine-test.freeze.env_export.from_history.yml").write_text(
        "name: paper-refine-test\ndependencies:\n  - python=3.12\n", encoding="utf-8")
    prefix = t / "prefix"
    prefix.mkdir()
    (prefix / "precious.txt").write_text("keep me\n", encoding="utf-8")
    env = dict(os.environ,
               CONDA_EXE=str(conda), FAKE_CONDA_BASE=str(t / "base"),
               PAPER_REFINE_TEST_PREFIX=str(prefix),
               PAPER_REFINE_TEST_ENV="paper-refine-test",
               PAPER_REFINE_TEST_EXPORT_DIR=str(t / "exports"),
               CONDA_PKGS_DIRS=str(t / "pkgs"), CONDA_ENVS_PATH=str(t / "envs"),
               PIP_CACHE_DIR=str(t / "pip"))
    proc = subprocess.run(["bash", str(WS / "scripts" / "create-test-env.sh"), "--recreate"],
                          cwd=str(t), env=env, capture_output=True, text=True)
    check("F08 a non-empty non-conda prefix is refused without an opt-in",
          proc.returncode == 2 and (prefix / "precious.txt").is_file(),
          f"rc={proc.returncode} stderr={proc.stderr[-120:]}")
    shutil.rmtree(t, ignore_errors=True)


# ---------------------------------------------------------------------------
# F99 -- a validation crash is an error, not only a warning
# ---------------------------------------------------------------------------
def t_f99():
    print("\n== F99 ==")
    from types import SimpleNamespace
    t = scratch("f99")
    sb = t / "sb"
    (sb / "base").mkdir(parents=True)
    (sb / "revised").mkdir()
    (sb / "base" / "main.md").write_text("base\n", encoding="utf-8")
    (sb / "revised" / "main.md").write_text("rev\n", encoding="utf-8")
    ctx = SimpleNamespace(cfg={"format_fix": "on"}, sandbox_of=lambda rec: sb)
    rec = {"id": "r1_revise", "kind": "revise", "round": 1}
    patches = {
        "ensure_handoff_readme": lambda *a, **k: {},
        "zotero_field_continuity_check": lambda *a, **k: {},
        "submission_not_carried_areas": lambda *a, **k: set(),
        "strip_dangling_references_in_dir": lambda *a, **k: {},
        "merge_reference_strips": lambda *a, **k: {},
        "normalize_formatting_in_dir": lambda *a, **k: {"label": "x"},
        "_validate_stage_package": mock.Mock(side_effect=RuntimeError("boom")),
        "code_side_evidence": lambda *a, **k: {},
        "pre_judge_format_policy": lambda *a, **k: {},
        "venue_word_templates": lambda *a, **k: [],
        "venue_containers": lambda *a, **k: [],
    }
    errs, warns = [], []
    with mock.patch.multiple(pp, **patches):
        pp._format_fix_stage_package(ctx, rec, sb / "revised", warns, errs)
    check("F99 a deliverable-validation crash is an error",
          any("could not run" in e and "UNVALIDATED" in e for e in errs), str(errs))
    shutil.rmtree(t, ignore_errors=True)
    src = (WS / "paper_pipeline_parts" / "p04_utils.py").read_text(encoding="utf-8")
    check("F99 the crash still records its warning",
          "warns.append(_validation_error)" in src)


def main() -> int:
    for fn in (t_f16_f18, t_f39_f93, t_f41_f42, t_f44, t_f52, t_f69, t_f76,
               t_f77, t_f88, t_f89, t_f90, t_f95_f96, t_f01_f06, t_f08, t_f99):
        fn()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) FAILED:")
        for name in FAILS:
            print("  -", name)
        return 1
    print("PASS: all fix-bugs 2026-11-26 22:41 regression checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

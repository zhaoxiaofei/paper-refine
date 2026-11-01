#!/usr/bin/env python3
"""Regression checks for the 2026-11-02 00:45:46 fix-bugs wave (F01-F70).

Run:  python3 .paper_test/test_fix_bugs_20261102_004546.py

Every check names the verified candidate it pins. The candidates came from
`debug_runs/20261102-004546/02_verify_findings/verified_findings/`; each was
re-validated on this tree before the patch, and the check below is the minimal
runtime proof that the defect is gone (a static check is used only where a
runtime probe would need a whole run root and the fixed surface is a call-site
contract).
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []
TMPDIRS = []


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


pp = load("fix_bugs_pipeline_1102", WS / "paper_pipeline.py")

M30_HEADER = (
    "# M30 — source-hierarchy reconciliation\n\n"
    "| # | document | kind | number | unit | sentence | candidate producer | producer summary "
    "| seed check | disposition |\n"
    "|---|---|---|---|---|---|---|---|---|---|\n")


def m30_row(n, disposition=""):
    return (f"| {n} | paper.md | body | {n} | cm | the height is {n} | "
            f"raw_data/plot.csv:height | 3 values | read the column | {disposition} |\n")


def sb_with(files):
    d = scratch("m30_")
    for rel, text in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return d


def run_py(code, args=(), timeout=10, env=None):
    return subprocess.run([sys.executable, "-c", code, *map(str, args)],
                          capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "PYTHONPATH": str(WS), **(env or {})})


# ---------------------------------------------------------------------------
# F01/F02/F03 -- the M30 gate ranks by row IDENTITY and treats an
# unreadable/boilerplate/arbitrary ledger as missing evidence, not clean.
# ---------------------------------------------------------------------------
def test_m30_gate():
    print("\n== F01-F03: the M30 ledger gate ==")
    frozen = [{"id": "F-1", "check": "M30"}]
    sb = sb_with({
        "work/M30_hierarchy_reconciliation.md": M30_HEADER + "".join(m30_row(i) for i in (1, 2, 3)),
        "revised/work/M30_hierarchy_reconciliation.md": M30_HEADER + m30_row(1, "OK — read it"),
    })
    errs, _w = pp.m30_hierarchy_problems(sb, frozen, pkg="revised")
    check("F01 a one-row package copy cannot beat the three-row seed",
          any("DROPPED" in e for e in errs), str(errs)[:200])

    sb = sb_with({"work/M30_hierarchy_reconciliation.md": ""})
    errs, _w = pp.m30_hierarchy_problems(sb, frozen)
    check("F02 a zero-byte ledger is an ERROR", bool(errs), str(errs)[:160])
    p = sb / "work" / "M30_hierarchy_reconciliation.md"
    p.write_text(M30_HEADER + m30_row(1), encoding="utf-8")
    p.chmod(0)
    errs, _w = pp.m30_hierarchy_problems(sb, frozen)
    p.chmod(0o644)
    check("F02 an unreadable ledger is an ERROR", bool(errs), str(errs)[:160])

    sb = sb_with({"work/M30_hierarchy_reconciliation.md":
                  M30_HEADER + "".join(m30_row(i, "OK") for i in range(1, 13))})
    errs, _w = pp.m30_hierarchy_problems(sb, frozen)
    check("F03 12 identical boilerplate dispositions FAIL", bool(errs), str(errs)[:200])
    sb = sb_with({"work/M30_hierarchy_reconciliation.md": M30_HEADER + m30_row(1, "x")})
    errs, _w = pp.m30_hierarchy_problems(sb, frozen)
    check("F03 an arbitrary non-empty disposition FAILS", bool(errs), str(errs)[:200])
    sb = sb_with({"work/M30_hierarchy_reconciliation.md":
                  M30_HEADER + m30_row(1, "OK — matches raw_data/plot.csv:height")})
    errs, warns = pp.m30_hierarchy_problems(sb, frozen)
    check("F03 a documented OK -- reason still passes", not errs, f"{errs} {warns}")


# ---------------------------------------------------------------------------
# F04/F05 -- the ledger is gated in rewrite/integrate, and the revise
# postcheck reads the AUDITED list.
# ---------------------------------------------------------------------------
def test_postcheck_parity():
    print("\n== F04/F05: postcheck parity ==")
    rewrite_src = inspect.getsource(pp.postcheck_rewrite)
    integrate_src = inspect.getsource(pp.postcheck_integrate)
    revise_src = inspect.getsource(pp.postcheck_revise)
    check("F04 postcheck_rewrite runs the M30 ledger gate",
          "m30_hierarchy_problems(" in rewrite_src, rewrite_src[:80])
    check("F04 postcheck_integrate runs the M30 ledger gate",
          "m30_hierarchy_problems(" in integrate_src, integrate_src[:80])
    check("F05 postcheck_revise reads the AUDITED finding list",
          "findings_from_sandbox(sb, sandbox_audit_record(sb))" in revise_src
          and "frozen_all = _frozen_review_findings(sb)" not in revise_src)

    sb = sb_with({
        "guided_review/findings.json": json.dumps({"findings": [
            {"id": "F-1", "check": "M30"}, {"id": "F-2", "check": "M26"}]}),
        "audit/audit.json": json.dumps({"dispositions": [
            {"id": "F-1", "verdict": "drop", "reason": "not a defect"}]}),
    })
    audited = [f["id"] for f in pp.findings_from_sandbox(sb, pp.sandbox_audit_record(sb))]
    check("F05 an auditor drop is absent from the audited list", audited == ["F-2"], audited)


# ---------------------------------------------------------------------------
# F06 -- contractions/punctuation cannot hide a negated re-derivation.
# ---------------------------------------------------------------------------
def test_audit_negation():
    print("\n== F06: audit coverage negation ==")
    for text in ("the sweep wasn't re-derived", "the sweep was not, in fact, re-derived"):
        check(f"F06 refused: {text!r}", pp._audit_disposition_ok(text) is False)
    check("F06 a true re-derivation still passes",
          pp._audit_disposition_ok("the sweep was re-derived against the corpus") is True)
    check("F06 an unrelated 'not' does not veto a confirmation",
          pp._audit_disposition_ok("F-2 confirmed (the CI does not contain the point estimate)")
          is True)


# ---------------------------------------------------------------------------
# F10 -- the sandbox policy file is the COMPLETE effective policy.
# ---------------------------------------------------------------------------
def test_format_policy_seed():
    print("\n== F10: the seeded format policy ==")
    root = scratch("f10_")
    (root / "non_revised").mkdir()
    cfg = {"format_policy": {"max_em_dashes_per_1000": 0.5, "figure_ocr": False,
                             "max_empty_paragraph_run": 3}}
    (root / "pipeline_config.json").write_text(json.dumps(cfg), encoding="utf-8")
    ctx = pp.Ctx(root)
    ctx.cfg = cfg
    sb = root / "sb"
    sb.mkdir()
    seed = json.loads(pp.seed_format_policy_file(ctx, sb).read_text(encoding="utf-8"))
    eff = pp.format_policy_of(ctx)
    check("F10 the operator's dashes/OCR/blank-run values reach the sandbox",
          all(seed.get(k) == eff.get(k) for k in
              ("max_em_dashes_per_1000", "figure_ocr", "max_empty_paragraph_run")),
          {k: (seed.get(k), eff.get(k)) for k in
           ("max_em_dashes_per_1000", "figure_ocr", "max_empty_paragraph_run")})
    check("F10 every effective policy key is seeded", set(eff) <= set(seed),
          sorted(set(eff) - set(seed))[:4])


# ---------------------------------------------------------------------------
# F11 -- the response letter is REQUIRED and a misplaced one is rescued.
# ---------------------------------------------------------------------------
def test_response_deliverable():
    print("\n== F11: the response letter deliverable ==")
    table = pp.STAGE_DELIVERABLES["response"]
    check("F11 the letter is in the required list",
          pp.JOURNAL_RESPONSE_MD_REL in table["required"], table["required"])
    check("F11 the letter is not also an EXPECTED warning",
          pp.JOURNAL_RESPONSE_MD_REL not in table["expected"], table["expected"])
    # ... and a letter written at the sandbox root is now ADOPTED (the rescue
    # only handles REQUIRED entries, which is why the severity mattered).
    sb = scratch("f11_")
    (sb / "RESPONSE_TO_REVIEWERS.md").write_text("# letter\n", encoding="utf-8")
    ctx = type("C", (), {"sandbox_of": lambda self, rec: sb})()
    pp.rescue_misplaced_deliverable(ctx, {"id": "r1_response", "kind": "response", "round": 1})
    check("F11 a misplaced response letter is rescued into response/",
          (sb / pp.JOURNAL_RESPONSE_MD_REL).is_file())


# ---------------------------------------------------------------------------
# F14 -- a malformed state.json pipeline value cannot crash a prompt render.
# ---------------------------------------------------------------------------
def test_fallback_paths_shape():
    print("\n== F14: malformed state.json ==")
    saved = pp.__file__
    root = scratch("f14_")
    (root / "state.json").write_text(json.dumps({"pipeline": "x"}), encoding="utf-8")
    try:
        pp.__file__ = str(root / "paper_pipeline.py")
        try:
            got = pp.pipeline_fallback_paths()
            check("F14 a string pipeline value yields no fallback", got == [], got)
        except Exception as e:                                        # noqa: BLE001
            check("F14 a string pipeline value yields no fallback", False, repr(e))
    finally:
        pp.__file__ = saved


# ---------------------------------------------------------------------------
# F16/F17 -- the prompts use the policy's own manual-list file.
# ---------------------------------------------------------------------------
def test_prompt_handoff_targets():
    print("\n== F16/F17: prompt hand-off targets ==")
    sb = scratch("f16_")
    readme = pp.integrate_prompt(sb, "r1_i1_integrate", 1, "a1", ["w1", "a2"])
    off = pp.integrate_prompt(sb, "r1_i1_integrate", 1, "a1", ["w1", "a2"],
                              author_to_complete="off")
    check("F16 readme mode never sends integrate items to integrated/MANUAL_STEPS.md",
          "integrated/MANUAL_STEPS.md" not in readme,
          readme.count("integrated/MANUAL_STEPS.md"))
    check("F16 readme mode names integrated/README-AUTHOR-TO-COMPLETE.md",
          "integrated/README-AUTHOR-TO-COMPLETE.md" in readme)
    check("F16 off mode keeps integrated/MANUAL_STEPS.md",
          "integrated/MANUAL_STEPS.md" in off)
    rec = {"id": "r1_a2_revise", "kind": "revise", "round": 1}
    r_readme = pp.resume_prompt(rec, [], "stopped", 0)
    r_off = pp.resume_prompt(rec, [], "stopped", 0, author_to_complete="off")
    check("F17 the readme-mode continuation names the README",
          "record the item in README-AUTHOR-TO-COMPLETE.md" in r_readme)
    check("F17 the off-mode continuation names MANUAL_STEPS.md",
          "record the item in MANUAL_STEPS.md" in r_off)


# ---------------------------------------------------------------------------
# F18/F20/F29/F30/F64 -- the classified TODO inventory and the README fallback.
# ---------------------------------------------------------------------------
MANUAL_ACTIONS = None
MANUAL_HDR = ("| TODO item ID | importance | author action | description |\n"
              "|---|---|---|---|\n")


def manual_table(rows, tid="T-001"):
    return MANUAL_HDR + (f"| {tid} | critical | {pp.MANUAL_ACTIONS[0]} | {rows} |\n")


def make_root():
    root = scratch("atc_root_")
    (root / "non_revised").mkdir()
    (root / "state.json").write_text("{}", encoding="utf-8")
    (root / "pipeline_config.json").write_text(
        json.dumps({"author_to_complete": "readme"}), encoding="utf-8")
    return root


def test_manual_todo_policy():
    print("\n== F18/F20/F29/F30/F64: the manual TODO policy ==")
    root = make_root()
    pkg = root / "runs" / "r1" / "revised"
    pkg.mkdir(parents=True)
    (pkg / "MANUAL_STEPS.md").write_text(manual_table("Fix the address."), encoding="utf-8")
    errs, _w = pp.manual_todo_gate(pkg, write=False)
    check("F18 a MANUAL_STEPS-only table FAILS under readme mode",
          any("README-AUTHOR-TO-COMPLETE.md" in e for e in errs), str(errs)[:200])
    (pkg / "README-AUTHOR-TO-COMPLETE.md").write_text(
        manual_table("Fix the address.", tid="T-002"), encoding="utf-8")
    errs, _w = pp.manual_todo_gate(pkg, write=False)
    check("F18 the README table passes", not errs, str(errs)[:160])

    ctx = type("C", (), {"cfg": {"author_to_complete": "readme"}})()
    # F20: the marker fallback writes a CLASSIFIED row, not a bullet.
    root = make_root()
    pkg = root / "runs" / "r2" / "revised"
    pkg.mkdir(parents=True)
    (pkg / "MANUAL_STEPS.md").write_text(
        "# M\n\n[AUTHOR TO COMPLETE: supply the missing ethics statement]\n", encoding="utf-8")
    pp.ensure_handoff_readme(ctx, pkg)
    text = (pkg / "README-AUTHOR-TO-COMPLETE.md").read_text(encoding="utf-8")
    rows, problems, _s = pp.manual_todo_rows(pkg)
    check("F20 the fallback emits a parsed classified row",
          len(rows) == 1 and rows[0]["id"].startswith("T-") and not problems,
          f"{rows} {problems}")
    check("F20 the fallback no longer emits a bare bullet",
          "\n- supply the missing ethics statement" not in text, text[-160:])

    # F64: an existing README TABLE row for the same item is a duplicate already.
    root = make_root()
    pkg = root / "runs" / "r3" / "revised"
    pkg.mkdir(parents=True)
    (pkg / "MANUAL_STEPS.md").write_text(
        "# M\n\n[AUTHOR TO COMPLETE: supply the missing ethics statement]\n", encoding="utf-8")
    (pkg / "README-AUTHOR-TO-COMPLETE.md").write_text(
        MANUAL_HDR + f"| T-001 | minor | {pp.MANUAL_ACTIONS[2]} | supply the missing ethics statement |\n",
        encoding="utf-8")
    pp.ensure_handoff_readme(ctx, pkg)
    rows, _p, _s = pp.manual_todo_rows(pkg)
    check("F64 an existing table row is not appended twice", len(rows) == 1, rows)

    # F29/F30: a FIFO in either file must not block the gate/postcheck path.
    root = make_root()
    pkg = root / "runs" / "r4" / "revised"
    pkg.mkdir(parents=True)
    os.mkfifo(pkg / "MANUAL_STEPS.md")
    r = run_py("import paper_pipeline as pp; from pathlib import Path; "
               "print(pp.manual_todo_problems(Path(__import__('sys').argv[1])))",
               [pkg], timeout=10)
    check("F29 a FIFO MANUAL_STEPS.md does not block the TODO gate",
          r.returncode == 0, (r.stdout or r.stderr)[-160:])
    os.unlink(pkg / "MANUAL_STEPS.md")
    (pkg / "MANUAL_STEPS.md").write_text(
        "# M\n\n[AUTHOR TO COMPLETE: supply it]\n", encoding="utf-8")
    outside = scratch("f30_out_") / "outside.txt"
    outside.write_text("KEEP", encoding="utf-8")
    os.symlink(outside, pkg / "README-AUTHOR-TO-COMPLETE.md")
    r = run_py("import paper_pipeline as pp; from pathlib import Path; "
               "ctx=type('C',(),{'cfg':{'author_to_complete':'readme'}})()\n"
               "try:\n"
               "    print(pp.ensure_handoff_readme(ctx, Path(__import__('sys').argv[1])))\n"
               "except RuntimeError as e:\n"
               "    print('REFUSED', e)", [pkg], timeout=10)
    check("F30 a symlinked hand-off README is refused, not read/written through",
          "REFUSED" in r.stdout and outside.read_text() == "KEEP",
          (r.stdout + r.stderr)[-200:])


# ---------------------------------------------------------------------------
# F21 -- the package postchecks count the mode's own manual-list file.
# ---------------------------------------------------------------------------
def test_manual_count_target():
    print("\n== F21: manual-item count target ==")
    for fn in (pp.postcheck_revise, pp.postcheck_rewrite):
        src = inspect.getsource(fn)
        check(f"F21 {fn.__name__} counts handoff_target(...)",
              "handoff_target(author_to_complete_mode_of(ctx))" in src)


# ---------------------------------------------------------------------------
# F23 -- an agent-written README cannot narrow the submitted set.
# ---------------------------------------------------------------------------
def test_declared_submission_set():
    print("\n== F23: the submitted-set declaration ==")
    root = scratch("f23_")
    (root / "non_revised").mkdir()
    (root / "state.json").write_text("{}", encoding="utf-8")
    decl = "Only `main*` will be submitted.\n"
    (root / "non_revised" / "README.md").write_text(decl, encoding="utf-8")
    pkg = root / "runs" / "r1" / "revised"
    (pkg / "base").mkdir(parents=True)
    (pkg / "base" / "README.md").write_text(decl, encoding="utf-8")
    (pkg / "main.md").write_text("m", encoding="utf-8")
    (pkg / "cover.md").write_text("c", encoding="utf-8")
    (pkg / "README.md").write_text("Only `cover*` will be submitted.\n", encoding="utf-8")
    got = pp.declared_submission_set(pkg)
    check("F23 a session-written README is IGNORED",
          got["declared"] is False and got.get("untrusted_readmes") == ["README.md"], got)
    (pkg / "README.md").write_text(decl, encoding="utf-8")
    got = pp.declared_submission_set(pkg)
    check("F23 the author's byte-identical README is still honoured",
          got["declared"] is True and got["files"] == ["main.md"], got)


# ---------------------------------------------------------------------------
# F24 -- the tool materializer does not write through a planted symlink.
# ---------------------------------------------------------------------------
def test_session_tool_copy():
    print("\n== F24: _copy_session_tools ==")
    sb = scratch("f24_")
    outside = sb.parent / f"{sb.name}_outside.py"
    outside.write_text("KEEP", encoding="utf-8")
    TMPDIRS.append(outside)
    os.symlink(outside, sb / pp.DOCX_FORMAT_MODULE)
    pp._copy_session_tools(sb)
    check("F24 a symlinked destination is replaced, not written through",
          not (sb / pp.DOCX_FORMAT_MODULE).is_symlink()
          and outside.read_text() == "KEEP", outside.read_text()[:40])


# ---------------------------------------------------------------------------
# F26/F27/F28 -- writes/reads in agent-writable trees.
# ---------------------------------------------------------------------------
def test_append_and_seed_writes():
    print("\n== F26/F27/F28: agent-writable write targets ==")
    d = scratch("f26_")
    os.mkfifo(d / "_agent.log")
    started = time.time()
    pp.append_text_no_follow(d / "_agent.log", "x")
    check("F26 a FIFO log returns immediately", time.time() - started < 3)
    d = scratch("f26b_")
    target = d / "outside.txt"
    target.write_text("ORIGINAL", encoding="utf-8")
    os.link(target, d / "_agent.log")
    pp.append_text_no_follow(d / "_agent.log", "APPENDED")
    check("F26 a hard link is not written through",
          target.read_text() == "ORIGINAL", target.read_text())

    root = scratch("f27_")
    (root / "non_revised").mkdir()
    (root / "pipeline_config.json").write_text("{}", encoding="utf-8")
    corpus = root / "corpus"
    corpus.mkdir()
    (corpus / "main.md").write_text("# T\n\n12 units.\n", encoding="utf-8")
    sb = root / "sb"
    (sb / "work").mkdir(parents=True)
    outside = root / "outside.md"
    outside.write_text("KEEP", encoding="utf-8")
    os.symlink(outside, sb / "work" / "EVIDENCE_PACK.md")
    ctx = pp.Ctx(root)
    ctx.cfg = {}
    try:
        pp.seed_evidence_pack(ctx, sb, corpus, "stage")
        ok = (outside.read_text() == "KEEP"
              and not (sb / "work" / "EVIDENCE_PACK.md").is_symlink())
    except Exception as e:                                            # noqa: BLE001
        ok = False
        print("    seed_evidence_pack raised", type(e).__name__, e)
    check("F27 the evidence pack replaces a planted symlink", ok)

    src = inspect.getsource(pp._write_journal_feedback_inputs)
    check("F28 the feedback materializer has no raw write_text() left",
          ".write_text(" not in src, [ln for ln in src.splitlines() if ".write_text(" in ln][:2])


# ---------------------------------------------------------------------------
# F33/F34/F40 -- package scans name a coverage gap instead of skipping silently.
# ---------------------------------------------------------------------------
def test_scan_gaps():
    print("\n== F33/F34/F40: package scan coverage ==")
    d = scratch("f33_")
    os.mkfifo(d / "cap.tex")
    started = time.time()
    got = pp._pooled_table_caption(d / "cap.tex")
    check("F33 a FIFO caption neither blocks nor returns text",
          got == "" and time.time() - started < 3, got)

    d = scratch("f34_")
    with open(d / "huge_mcb_table.tex", "wb") as f:
        f.truncate(pp.MAX_JSON_BYTES + 1024)
    rows = pp.scan_mcb_rule_conflicts(d)
    check("F34 an unreadable/oversized MCB source is a named gap",
          bool(rows) and rows[0].get("gap") is True, rows[:1])

    d = scratch("f40_")
    with open(d / "mcb_pooled.tsv", "wb") as f:
        f.truncate(9 * 1024 * 1024)
    rows = pp.scan_pooled_table_mismatches(d)
    check("F40 an over-budget table is a named gap",
          bool(rows) and rows[0].get("gap") is True, rows[:1])


# ---------------------------------------------------------------------------
# F38/F39 -- the attempt reader/launcher is bounded.
# ---------------------------------------------------------------------------
def test_attempt_io():
    print("\n== F38/F39: the attempt prompt/transcript ==")
    d = scratch("f38_")
    os.mkfifo(d / "PROMPT.md")
    rec = {"id": "r1_w1", "kind": "rewrite", "round": 1, "attempts": []}
    started = time.time()
    res = pp._execute_attempt_in(d, rec, [sys.executable, "-c", "print('x')"], 10)
    check("F38 a FIFO PROMPT.md fails fast instead of blocking",
          time.time() - started < 5 and "could not be read" in str(res.get("error")),
          res)

    d = scratch("f39_")
    (d / "PROMPT.md").write_text("hello", encoding="utf-8")
    rec = {"id": "r1_w1", "kind": "rewrite", "round": 1, "attempts": []}
    code = ("import sys\n"
            "sys.stdout.write('x' * (17 * 1024 * 1024))\n"
            "sys.stdout.flush()\n")
    res = pp._execute_attempt_in(d, rec, [sys.executable, "-c", code], 120)
    log = (d / "_agent.log").read_text(encoding="utf-8", errors="replace")
    check("F39 an oversized transcript is truncated with a note",
          "OUTPUT TRUNCATED" in log and len(log) < 40 * 1024 * 1024,
          f"log={len(log)} rc={res.get('rc')}")


# ---------------------------------------------------------------------------
# F41 -- an unknown/removed author-to-complete value is refused.
# ---------------------------------------------------------------------------
def test_atc_mode():
    print("\n== F41: the author-to-complete mode ==")
    check("F41 the default is still readme", pp._atc_mode(None) == "readme")
    for bad in ("on", "bogus"):
        try:
            pp._atc_mode(bad)
            check(f"F41 {bad!r} is refused", False)
        except SystemExit:
            check(f"F41 {bad!r} is refused", True)


# ---------------------------------------------------------------------------
# F53 -- the D3b regression test pins the text that really existed.
# ---------------------------------------------------------------------------
def test_d3b_string():
    print("\n== F53: the D3b prompt pin ==")
    revise = pp.revise_prompt(Path("/tmp/x"), "r1_a2_revise", 1)
    check("F53 the old 'report them in ...' text is gone",
          "report them in revised/MANUAL_STEPS.md" not in revise)
    check("F53 the README classified-table sentence is present",
          "README-AUTHOR-TO-COMPLETE.md" in revise and "classified TODO table" in revise)


# ---------------------------------------------------------------------------
# F61/F62/F63 -- the published checklist is a classified table and its
# scanner/reader are bounded.
# ---------------------------------------------------------------------------
def test_published_handoff():
    print("\n== F61/F62/F63: the published hand-off README ==")
    pub = scratch("f61_")
    pp.write_published_handoff_readme(
        pub, {"items": [{"id": "F-1", "status": "open", "check": "M1", "severity": "major",
                         "location": "a.md:1", "evidence": "x"}]})
    text = (pub / "README-AUTHOR-TO-COMPLETE.md").read_text(encoding="utf-8")
    check("F61 the managed block carries a four-column table row",
          "| TODO item ID | importance | author action | description |" in text
          and "| T-001 |" in text and "\n- F-1" not in text, text[-240:])
    rows, problems = pp.manual_todo_rows_from_text(text)
    check("F61 the published row parses as a classified row", len(rows) == 1 and not problems,
          f"{rows} {problems}")

    d = scratch("f62_")
    os.mkfifo(d / "doc.md")
    (d / "keep.md").write_text("nothing", encoding="utf-8")
    r = run_py("import paper_pipeline as pp; from pathlib import Path; "
               "print(pp._handoff_marker_occurrences(Path(__import__('sys').argv[1])))",
               [d], timeout=10)
    check("F62 a FIFO package source does not block the marker scan",
          r.returncode == 0 and "[]" in r.stdout, (r.stdout + r.stderr)[-160:])

    d = scratch("f63_")
    os.mkfifo(d / "README-AUTHOR-TO-COMPLETE.md")
    r = run_py("import paper_pipeline as pp; from pathlib import Path; "
               "print(pp.write_published_handoff_readme(Path(__import__('sys').argv[1]), "
               "{'items': []}))", [d], timeout=10)
    check("F63 a FIFO existing checklist does not block publication",
          r.returncode == 0, (r.stdout + r.stderr)[-160:])


# ---------------------------------------------------------------------------
# F66 -- a judge's seeded FMT-CL1 row must be DISPOSED.
# ---------------------------------------------------------------------------
def test_judge_fmt_cl1():
    print("\n== F66: the judge's FMT-CL1 row ==")
    base = scratch("f66_")
    (base / "judge_review" / "artifacts").mkdir(parents=True)
    path = base / "judge_review" / "artifacts" / "M20_formatting.md"
    path.write_text("| rule | document | disposition |\n|---|---|---|\n"
                    "| FMT-CL1 | cover.docx |  |\n", encoding="utf-8")
    problems = pp.judge_cover_letter_artifact_problems(base, [{"rule": "FMT-CL1"}])
    check("F66 an empty-disposition FMT-CL1 row is a problem",
          any("EMPTY disposition" in p for p in problems), problems)
    path.write_text("| rule | document | disposition |\n|---|---|---|\n"
                    "| FMT-CL1 | cover.docx | formatting defect, minor |\n", encoding="utf-8")
    problems = pp.judge_cover_letter_artifact_problems(base, [{"rule": "FMT-CL1"}])
    check("F66 a disposed FMT-CL1 row passes", not problems, problems)


# ---------------------------------------------------------------------------
# F68 -- the published sibling is the ONE authoritative checklist and it
# starts from the stage's own rows.
# ---------------------------------------------------------------------------
def test_published_single_checklist():
    print("\n== F68: one authoritative author checklist ==")
    src = scratch("f68_src_")
    (src / "README-AUTHOR-TO-COMPLETE.md").write_text(
        "# Author to complete\n\n- supply the ethics statement\n", encoding="utf-8")
    out = scratch("f68_out_")
    target = out / "final_clean_version.README-AUTHOR-TO-COMPLETE.md"
    pp.write_published_handoff_readme(
        out, {"items": [{"id": "F-1", "status": "open", "severity": "major",
                         "location": "a.md:1", "evidence": "x"}]},
        existing_from=src / "README-AUTHOR-TO-COMPLETE.md", target_path=target)
    text = target.read_text(encoding="utf-8")
    check("F68 the sibling starts from the stage's own rows",
          "supply the ethics statement" in text, text[:200])
    check("F68 the sibling carries the ledger item too", "F-1" in text)
    readiness = inspect.getsource(pp.package_readiness)
    check("F68 readiness reports only the sibling when it exists",
          "_sibling_authoritative" in readiness)


# ---------------------------------------------------------------------------
# R01 -- the pre-flight expects the POLICY's manual-list file, not always
# MANUAL_STEPS.md.
# ---------------------------------------------------------------------------
def test_repair_r01_preflight_handoff_target():
    print("\n== R01: the pre-flight expects the policy's manual-list file ==")
    marker = {"status": "complete", "id": "placeholder", "kind": "placeholder",
              "round": 1, "summary": {"critical_remaining": 0, "writing_remaining": 0,
                                       "manual_items": 0}}
    for kind, pkg_dir in (("integrate", "integrated"), ("revise", "revised"),
                          ("rewrite", "rewritten")):
        sb = scratch(f"r01_{kind}_")
        (sb / pp.PROMPT_FILE).write_text(pp.placeholder_rule_text("readme"),
                                         encoding="utf-8")
        (sb / pkg_dir).mkdir(parents=True)
        (sb / pkg_dir / pp.AUTHOR_TO_COMPLETE_README).write_text(
            "# checklist\n", encoding="utf-8")
        m = dict(marker, id=f"r1_{kind}", kind=kind)
        (sb / pp.MARKER_FILE).write_text(json.dumps(m), encoding="utf-8")
        warns = pp.sandbox_selfcheck(sb, kind, f"r1_{kind}", 1)[2]
        check(f"R01 {kind}: readme mode does not warn about MANUAL_STEPS.md",
              not any("MANUAL_STEPS.md is missing" in w for w in warns),
              str([w for w in warns if "MANUAL_STEPS" in w])[:240])
    # document/off modes still name MANUAL_STEPS.md, and a package that has it
    # must not be warned that the README is absent.
    for mode in ("document", "off"):
        sb = scratch(f"r01_{mode}_")
        (sb / pp.PROMPT_FILE).write_text(pp.placeholder_rule_text(mode), encoding="utf-8")
        (sb / "integrated").mkdir()
        (sb / "integrated" / "MANUAL_STEPS.md").write_text("# steps\n", encoding="utf-8")
        m = dict(marker, id="r1_i1", kind="integrate")
        (sb / pp.MARKER_FILE).write_text(json.dumps(m), encoding="utf-8")
        warns = pp.sandbox_selfcheck(sb, "integrate", "r1_i1", 1)[2]
        check(f"R01 {mode} mode still expects MANUAL_STEPS.md",
              not any("MANUAL_STEPS.md is missing" in w for w in warns),
              str([w for w in warns if "MANUAL_STEPS" in w])[:240])


# ---------------------------------------------------------------------------
# R02 -- a run root without an author_to_complete key resolves to the
# documented default (readme), exactly like author_to_complete_mode_of.
# ---------------------------------------------------------------------------
def test_repair_r02_manual_todo_default_mode():
    print("\n== R02: the missing config key resolves to the default mode ==")
    root = scratch("r02_")
    (root / "non_revised").mkdir()
    (root / "state.json").write_text("{}", encoding="utf-8")
    (root / "pipeline_config.json").write_text("{}", encoding="utf-8")
    pkg = root / "runs/r1/revised"
    pkg.mkdir(parents=True)
    (pkg / "MANUAL_STEPS.md").write_text(
        "| TODO item ID | importance | author action | description |\n"
        "|---|---|---|---|\n"
        f"| T-001 | major | {pp.MANUAL_ACTIONS[2]} | x |\n", encoding="utf-8")
    errs, _w = pp.manual_todo_gate(pkg, write=False)
    check("R02 no mode -> the run root default is readme",
          any(pp.AUTHOR_TO_COMPLETE_README in e for e in errs), str(errs)[:240])
    errs_explicit, _w = pp.manual_todo_gate(pkg, write=False, mode="readme")
    check("R02 the inferred verdict equals the explicit readme verdict",
          errs == errs_explicit, f"{errs} != {errs_explicit}")
    # outside a run root the package stays policy-free (the documented fixture
    # escape), so a hand-made package keeps the permissive parse.
    outside = scratch("r02_out_") / "pkg"
    outside.mkdir()
    (outside / "MANUAL_STEPS.md").write_text(
        "| TODO item ID | importance | author action | description |\n"
        "|---|---|---|---|\n"
        f"| T-001 | major | {pp.MANUAL_ACTIONS[2]} | x |\n", encoding="utf-8")
    errs_out, _w = pp.manual_todo_gate(outside, write=False)
    check("R02 a package outside a run root stays permissive", not errs_out, str(errs_out)[:160])


# ---------------------------------------------------------------------------
# R03 -- a re-publication merges the stage's CURRENT rows over the sibling's
# stale rows instead of dropping them.
# ---------------------------------------------------------------------------
def test_repair_r03_republish_merges_stage_rows():
    print("\n== R03: a re-publication keeps the stage's current rows ==")
    hdr = ("# Author to complete\n\n"
           "| TODO item ID | importance | author action | description |\n"
           "|---|---|---|---|\n")
    row = "| {tid} | major | " + pp.MANUAL_ACTIONS[2] + " | {desc} |\n"
    # same T-id: the current stage row REPLACES the stale sibling row
    root = scratch("r03_same_")
    target = root / "final.author.md"
    target.write_text(hdr + row.format(tid="T-001", desc="OLD stage item"),
                      encoding="utf-8")
    stage = root / "stage" / "README-AUTHOR-TO-COMPLETE.md"
    stage.parent.mkdir()
    stage.write_text(hdr + row.format(tid="T-001", desc="NEW stage item"),
                     encoding="utf-8")
    pkg = root / "pkg"
    pkg.mkdir()
    pp.write_published_handoff_readme(pkg, {"items": []}, {"items": []},
                                      target_path=target, existing_from=stage)
    text = target.read_text(encoding="utf-8")
    check("R03 the re-published sibling carries the NEW stage row",
          "NEW stage item" in text, text[:240])
    check("R03 the stale sibling row is replaced, not duplicated",
          "OLD stage item" not in text and text.count("| T-001 |") == 1, text[:240])
    # distinct T-id: the union keeps both the prior external row and the stage row
    root2 = scratch("r03_union_")
    target2 = root2 / "final.author.md"
    target2.write_text(hdr + row.format(tid="T-001", desc="PRIOR external item"),
                       encoding="utf-8")
    stage2 = root2 / "stage" / "README-AUTHOR-TO-COMPLETE.md"
    stage2.parent.mkdir()
    stage2.write_text(hdr + row.format(tid="T-002", desc="ADDED stage item"),
                      encoding="utf-8")
    pkg2 = root2 / "pkg"
    pkg2.mkdir()
    pp.write_published_handoff_readme(pkg2, {"items": []}, {"items": []},
                                      target_path=target2, existing_from=stage2)
    text2 = target2.read_text(encoding="utf-8")
    check("R03 distinct rows are a de-duplicated union",
          "PRIOR external item" in text2 and "ADDED stage item" in text2
          and text2.count("| T-001 |") == 1 and text2.count("| T-002 |") == 1,
          text2[:300])


# ---------------------------------------------------------------------------
# R04 -- the M30 row-identity check compares against the seeded identities in
# the evidence pack, not against the answer file itself.
# ---------------------------------------------------------------------------
def _r04_hrows():
    return [{"document": "paper.md", "kind": "body", "number": n, "unit": "cm",
             "sentence": f"the height is {n}",
             "candidate producer": "raw_data/plot.csv:height",
             "producer summary": "3 values", "seed check": "read the column"}
            for n in (1, 2, 3)]


def _r04_seed_text(hrows, dispositions=None):
    rows = [dict(r, disposition=(dispositions[i] if dispositions else ""))
            for i, r in enumerate(hrows)]
    return ("# M30\n\n" + pp._evidence_artifact_table(
        rows, ["document", "kind", "number", "unit", "sentence", "candidate producer",
               "producer summary", "seed check"], "no rows") + "\n")


def test_repair_r04_m30_seed_identity():
    print("\n== R04: the M30 identity check uses the seeded evidence ==")
    frozen = [{"id": "F-1", "check": "M30"}]
    hrows = _r04_hrows()
    scans = {"hierarchy": {"rows": hrows, "count": len(hrows)}}
    # (a) the answer is written IN the seed file itself: a one-row rewrite must
    #     still be caught against the identities the evidence pack recorded.
    sb = scratch("r04_sandbox_")
    (sb / "work").mkdir(parents=True)
    (sb / "work" / "CODE_SCANS.json").write_text(json.dumps(scans), encoding="utf-8")
    (sb / "work" / "M30_hierarchy_reconciliation.md").write_text(
        _r04_seed_text(hrows[:1], ["OK — read it"]), encoding="utf-8")
    errs, _w = pp.m30_hierarchy_problems(sb, frozen)
    check("R04 a one-row rewrite of the sandbox seed is a DROPPED-row error",
          any("DROPPED" in e for e in errs), str(errs)[:240])
    # (b) the sandbox seed is gone and only a one-row package copy exists: the
    #     recorded identities still decide, so the check is not skipped.
    sb2 = scratch("r04_pkg_")
    (sb2 / "work").mkdir(parents=True)
    (sb2 / "work" / "CODE_SCANS.json").write_text(json.dumps(scans), encoding="utf-8")
    (sb2 / "revised" / "work").mkdir(parents=True)
    (sb2 / "revised" / "work" / "M30_hierarchy_reconciliation.md").write_text(
        _r04_seed_text(hrows[:1], ["OK — read it"]), encoding="utf-8")
    errs2, _w = pp.m30_hierarchy_problems(sb2, frozen, pkg="revised")
    check("R04 a missing sandbox seed does not skip the identity check",
          any("DROPPED" in e for e in errs2), str(errs2)[:240])
    # (c) the full seeded ledger, disposed in place, still passes.
    sb3 = scratch("r04_ok_")
    (sb3 / "work").mkdir(parents=True)
    (sb3 / "work" / "CODE_SCANS.json").write_text(json.dumps(scans), encoding="utf-8")
    (sb3 / "work" / "M30_hierarchy_reconciliation.md").write_text(
        _r04_seed_text(hrows, ["OK — read it"] * len(hrows)), encoding="utf-8")
    errs3, _w = pp.m30_hierarchy_problems(sb3, frozen)
    check("R04 a fully disposed seed still passes", not errs3, str(errs3)[:240])
    # (d) a real session sandbox whose evidence pack is gone cannot verify the
    #     identities; that is reported, not silently skipped.
    sb4 = scratch("r04_noref_")
    (sb4 / "work").mkdir(parents=True)
    (sb4 / "PROMPT.md").write_text("# prompt\n", encoding="utf-8")
    (sb4 / "work" / "M30_hierarchy_reconciliation.md").write_text(
        _r04_seed_text(hrows[:1], ["OK — read it"]), encoding="utf-8")
    errs4, _w = pp.m30_hierarchy_problems(sb4, frozen)
    check("R04 a missing evidence pack is reported, not skipped",
          any("identity check is not skipped" in e for e in errs4), str(errs4)[:240])


# ---------------------------------------------------------------------------
# F70 -- DOCX style headings are not content units.
# ---------------------------------------------------------------------------
def test_docx_heading():
    print("\n== F70: DOCX style headings ==")
    try:
        from docx import Document
    except ImportError:
        check("F70 python-docx available", False, "python-docx missing")
        return
    d = scratch("f70_")
    doc = Document()
    doc.add_heading("Materials and methods", level=1)
    doc.add_paragraph("We did the thing in a careful way.")
    doc.save(d / "p.docx")
    (d / "p.md").write_text(
        "# Materials and methods\n\nWe did the thing in a careful way.\n", encoding="utf-8")
    docx_rows = [r for r in pp._content_unit_paragraphs(d) if r[0].endswith(".docx")]
    md_rows = [r for r in pp._content_unit_paragraphs(d) if r[0].endswith(".md")]
    check("F70 a style heading is not a DOCX content unit",
          docx_rows == [("p.docx", 2, "We did the thing in a careful way.")], docx_rows)
    check("F70 the text path still strips its heading",
          md_rows == [("p.md", 3, "We did the thing in a careful way.")], md_rows)


def cleanup():
    import shutil
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    try:
        test_m30_gate()
        test_postcheck_parity()
        test_audit_negation()
        test_format_policy_seed()
        test_response_deliverable()
        test_fallback_paths_shape()
        test_prompt_handoff_targets()
        test_manual_todo_policy()
        test_manual_count_target()
        test_declared_submission_set()
        test_session_tool_copy()
        test_append_and_seed_writes()
        test_scan_gaps()
        test_attempt_io()
        test_atc_mode()
        test_d3b_string()
        test_published_handoff()
        test_judge_fmt_cl1()
        test_published_single_checklist()
        test_repair_r01_preflight_handoff_target()
        test_repair_r02_manual_todo_default_mode()
        test_repair_r03_republish_merges_stage_rows()
        test_repair_r04_m30_seed_identity()
        test_docx_heading()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL 2026-11-02 00:45:46 FIX-BUGS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

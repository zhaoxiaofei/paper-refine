#!/usr/bin/env python3
"""Regression checks for the 2026-11-08 fix-bugs wave 2 (verified candidates).

Each check pins one candidate this wave re-validated on the tree and repaired.
Hermetic: every fixture lives under tempfile.mkdtemp(); Node is optional.

Run:  python3 .paper_test/test_fix_bugs_20261108_wave2.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
TMPDIRS = []
FAILS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fb1108wave2_pp", "paper_pipeline.py")
cc = load("fb1108wave2_cc", "paper-skills/paper-review/scripts/convert_corpus.py")
ec = load("fb1108wave2_ec", "scripts/env_test_closure.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


WANTED = (list(pp.REQUIRED_REVIEW_CHECKS)
          + ["M19", "M18", "M20", "M21", "M22", "M23", "M24",
             "M25", "M26", "M27", "M28", "M29", "J5", "M30",
             "M31", "M32", "M33", "M34", "M35", "M36"])


def sandbox(prefix: str = "r1_guided_review") -> Path:
    sb = scratch("fb1108wave2_sb_") / prefix
    (sb / "base").mkdir(parents=True)
    (sb / "guided_review" / "artifacts").mkdir(parents=True)
    return sb


def coverage(overrides=None, default="unable -- fixture does not run this check"):
    over = dict(overrides or {})
    return [{"check": c, "disposition": over.get(c, default)} for c in WANTED]


def review_errors(sb: Path, overrides=None, findings=None, **kw):
    fj = {"submission_dir": "base", "coverage": coverage(overrides),
          "findings": list(findings or [])}
    errs = []
    pp.check_review_contract(None, sb, fj, errs, [], **kw)
    return errs


# ---------------------------------------------------------------- F001
def test_f001_split_review_ownership():
    print("\n== F001: a split half may dispose the OTHER half's checks as out of scope ==")
    sb = sandbox()
    errs = review_errors(sb, {c: "out of scope -- session B"
                              for c in ("J1", "J2", "J3", "J4", "J5")},
                         split="phases")
    check("F001 phases A: the other session's J checks are accepted",
          not any("disposes in-scope check(s)" in e for e in errs),
          [e for e in errs if "disposes in-scope" in e][:1])
    sb = sandbox("r1_guided_review_b")
    errs = review_errors(sb, {c: "out of scope -- session A"
                              for c in WANTED if c.startswith("M")},
                         split="phases")
    check("F001 phases B: the other session's M checks are accepted",
          not any("disposes in-scope check(s)" in e for e in errs),
          [e for e in errs if "disposes in-scope" in e][:1])
    sb = sandbox()
    errs = review_errors(sb, {"M1": "out of scope -- session B"}, split="phases")
    check("F001 phases A: disposing its OWN M1 as out of scope still fails",
          any("['M1']" in e for e in errs),
          [e for e in errs if "disposes in-scope" in e][:1])
    sb = sandbox()
    errs = review_errors(sb, {"M9": "out of scope -- session B"}, split="aspects")
    check("F001 aspects A: M9 belongs to B",
          not any("disposes in-scope check(s)" in e for e in errs))
    sb = sandbox()
    errs = review_errors(sb, {"M9": "out of scope -- session A"}, split="aspects")
    check("F001 aspects A: M9 is B's even when the label says A",
          not any("disposes in-scope check(s)" in e for e in errs))


# ---------------------------------------------------------------- F002/F009/F010/F011
def test_f002_f009_f010_f011_artifacts_and_basis():
    print("\n== F002/F009/F010/F011: artifact and basis gates ==")
    sb = sandbox()
    errs = review_errors(sb, {"M1": "0 findings"})
    check("F002 a `0 findings` row needs its per-sweep artifact",
          any("M1_acronyms.md" in e for e in errs), [e for e in errs if "M1_acronyms" in e])
    sb = sandbox()
    errs = review_errors(sb, {"M1": "2 findings"})
    check("F009 a finding row needs the enumeration artifact too",
          any("M1_acronyms.md" in e for e in errs), [e for e in errs if "M1_acronyms" in e])
    sb = sandbox()
    (sb / "guided_review" / "artifacts" / "M2_references.md").write_text(
        "| entry | disposition |\n|---|---|\n| x | OK — resolved |\n", encoding="utf-8")
    errs = review_errors(sb, {"M2": "clean -- basis: artifacts/M2_references.md"})
    check("F010 a clean M2 also requires M2_citations.md",
          any("M2_citations.md" in e for e in errs),
          [e for e in errs if "M2_citations" in e])
    sb = sandbox()
    (sb / "guided_review" / "artifacts" / "M18_caption_words.md").write_text(
        "| row | disposition |\n|---|---|\n| x | OK — 10 words |\n", encoding="utf-8")
    errs = review_errors(sb, {"M18": "clean -- basis: artifacts/does-not-exist.md"})
    check("F011 a non-mapped clean row's named basis must resolve",
          any("does-not-exist" in e for e in errs),
          [e for e in errs if "does-not-exist" in e])
    # R01: the documented detail-carried spelling (`disposition: "clean"` plus
    # `detail: "Basis: ..."`) certifies the sweep ran, so it needs the mapped
    # per-sweep artifact just like the inline `clean -- basis:` form.
    sb = sandbox()
    (sb / "guided_review" / "artifacts" / "check.md").write_text(
        "| row | disposition |\n|---|---|\n| x | OK — reason |\n", encoding="utf-8")
    cov = coverage({"M1": "clean"})
    for row in cov:
        if row["check"] == "M1":
            row["detail"] = "Basis: artifacts/check.md"
    errs = []
    pp.check_review_contract(
        None, sb, {"submission_dir": "base", "coverage": cov, "findings": []},
        errs, [])
    check("R01 a detail-carried clean row still needs its mapped artifact",
          any("M1_acronyms.md" in e for e in errs),
          [e for e in errs if "M1_acronyms" in e])


# ---------------------------------------------------------------- F012/F013/F026/F027
def test_f012_f013_f026_f027_shape_gates():
    print("\n== F012/F013/F026/F027: finding and table shape gates ==")
    finding = {"id": "F-001", "location": "x", "check": "M1", "category": 1,
               "severity": "Major", "evidence": "e", "explanation": "x",
               "status": "resolvable"}
    for cid, ok in (("M99", False), ("M37", False), ("M0", False),
                    ("M36", True), ("M1", True), ("J5", True)):
        sb = sandbox()
        row = dict(finding, check=cid)
        errs = review_errors(sb, findings=[row])
        bad = any("M/J check id" in e for e in errs)
        check(f"F012 check id {cid!r} is {'accepted' if ok else 'rejected'}",
              bad != ok, [e for e in errs if "M/J check id" in e][:1])
    for cat, ok in ((1.5, False), ("2", False), (True, False), (2, True)):
        sb = sandbox()
        errs = review_errors(sb, findings=[dict(finding, category=cat)])
        bad = any("category" in e for e in errs)
        check(f"F026 category {cat!r} is {'accepted' if ok else 'rejected'}",
              bad != ok, [e for e in errs if "category" in e][:1])

    tmp = scratch("fb1108wave2_tbl_")
    p = tmp / "M25_artwork_parity.md"
    p.write_text("| item | disposition |\n|---|---|\n"
                 + "".join(f"| x{i} | OK |\n" for i in range(5)), encoding="utf-8")
    check("F013 a short table of bare OK closures is rejected",
          any("bare verdict" in x for x in pp._disposition_table_problems(p)),
          pp._disposition_table_problems(p))
    p.write_text("| item | disposition |\n|---|---|\n"
                 "| x | OK — the figure is the source's own artwork |\n",
                 encoding="utf-8")
    check("F013 a row-specific OK reason is accepted",
          not pp._disposition_table_problems(p), pp._disposition_table_problems(p))
    # R03: a separator with an EMPTY reason tail is still a bare verdict.
    for disp in ("OK —", "OK -", "OK:"):
        p.write_text("| item | disposition |\n|---|---|\n"
                     f"| x | {disp} |\n", encoding="utf-8")
        check(f"R03 {disp!r} with no reason is rejected",
              any("bare verdict" in x for x in pp._disposition_table_problems(p)),
              pp._disposition_table_problems(p))
    # R12: a separator or one-token filler is not a reason either.
    for disp in ("OK — —", "OK — x", "OK — n/a"):
        p.write_text("| item | disposition |\n|---|---|\n"
                     f"| x | {disp} |\n", encoding="utf-8")
        problems = pp._disposition_table_problems(p)
        check(f"R12 {disp!r} has a filler reason and is rejected",
              any("filler reason" in x for x in problems), problems)
    p.write_text("| item | disposition |\n|---|---|\n"
                 "| x | OK — present |\n", encoding="utf-8")
    check("R12 a short but genuine reason is still accepted",
          not pp._disposition_table_problems(p),
          pp._disposition_table_problems(p))
    skill = (WS / "paper-skills" / "paper-review" / "SKILL.md").read_text(
        encoding="utf-8")
    check("R03 the skill's audit vocabulary requires a reason",
          "`OK — <reason>`" in skill)

    for value, ok in (("2 findings; none", False), ("2 findings, none", False),
                      ("2 findings -- none", False), ("2 findings but none", False),
                      ("2 findings; none critical", True), ("0 findings; none", True),
                      ("2 findings", True)):
        check(f"F027 {value!r} is {'accepted' if ok else 'rejected'}",
              pp._coverage_disposition_ok(value) is ok)


# ---------------------------------------------------------------- F005
def test_f005_repair_plan_binding():
    print("\n== F005: the repair audit binds the PLAN's wrong/correct change ==")
    tmp = scratch("fb1108wave2_repair_")
    pre, cur = tmp / "pre", tmp / "cur"
    pre.mkdir(); cur.mkdir()
    (pre / "paper.md").write_text(
        "Header.\nTitle. Alpha 10 beta. Gamma 30 delta. End.\n", encoding="utf-8")
    rows = [{"id": "RP-1", "file": "paper.md", "location": "l",
             "wrong": "10", "correct": "20", "basis": "b", "edit": "e",
             "evidence": "x"}]
    ledger = [{"id": "RP-1", "verdict": "confirmed", "reason": "applied",
               "before": "Title. Alpha 10 beta. Gamma 30 delta. End.",
               "after": "Title. Alpha 10 beta. Gamma 40 delta. Target 20. End."}]
    (cur / "REPAIR_LEDGER.json").write_text(json.dumps({"rows": ledger}),
                                           encoding="utf-8")
    (cur / "paper.md").write_text(
        "Header.\nTitle. Alpha 10 beta. Gamma 40 delta. Target 20. End.\n",
        encoding="utf-8")
    bad = pp._revised_repair_violations(pre, cur, rows, {"RP-1"}, with_reasons=True)
    check("F005 a different edit that merely contains the plan values fails",
          bad == {"paper.md": "the applied text is outside the plan's described "
                              "`wrong`/`correct` change"}, bad)
    (cur / "paper.md").write_text(
        "Header.\nTitle. Alpha 20 beta. Gamma 30 delta. End.\n", encoding="utf-8")
    ledger[0]["after"] = "Title. Alpha 20 beta. Gamma 30 delta. End."
    (cur / "REPAIR_LEDGER.json").write_text(json.dumps({"rows": ledger}),
                                           encoding="utf-8")
    bad = pp._revised_repair_violations(pre, cur, rows, {"RP-1"}, with_reasons=True)
    check("F005 the real wrong->correct change passes", bad == {}, bad)

    def case(name, pre_txt, cur_txt, wrong, correct, location, before_q, after_q):
        t = scratch("fb1108wave2_repair_case_")
        p, c = t / "pre", t / "cur"
        p.mkdir(); c.mkdir()
        (p / "paper.md").write_text(pre_txt, encoding="utf-8")
        (c / "paper.md").write_text(cur_txt, encoding="utf-8")
        plan = [{"id": "RP-1", "file": "paper.md", "location": location,
                 "wrong": wrong, "correct": correct, "basis": "b", "edit": "e",
                 "evidence": "x"}]
        led = [{"id": "RP-1", "verdict": "confirmed", "reason": "applied",
                "before": before_q, "after": after_q}]
        (c / "REPAIR_LEDGER.json").write_text(json.dumps({"rows": led}),
                                              encoding="utf-8")
        return pp._revised_repair_violations(p, c, plan, {"RP-1"}, with_reasons=True)

    bad = case("A", "We use HSP here. Later, HSPs are discussed.\n",
               "We use HSP here. Later, HSP is discussed.\n", "HSPs", "HSP",
               "later", "Later, HSPs are discussed.", "Later, HSP is discussed.")
    check("R02 a legitimate edit passes when the correct value occurs earlier",
          bad == {}, bad)
    bad = case("B", "Baseline value 20 in the pilot. The sample size was 10 in "
               "cohort B.\n",
               "Baseline value 20 in the pilot. The sample size was 20 in "
               "cohort B.\n", "10", "20", "sample size",
               "The sample size was 10 in cohort B.",
               "The sample size was 20 in cohort B.")
    check("R02 a legitimate 10->20 edit passes when 20 occurs earlier", bad == {}, bad)
    bad = case("C", "A 10. B 10.\n", "A 20. B 10.\n", "10", "20", "B",
               "A 10.", "A 20.")
    check("R02 a plan at B is not discharged by editing the value at A",
          bad == {"paper.md": "the applied text is outside the plan's described "
                              "`wrong`/`correct` change"}, bad)
    bad = case("D", "A 10. B 10.\n", "A 20. B 10.\n", "10", "20", "A",
               "A 10.", "A 20.")
    check("R02 the same-value edit at the plan's own location passes", bad == {}, bad)
    # R09: the applied repair may replace a wider span than the plan's `wrong`
    # value (the surrounding wording also changes); the plan is still realized
    # when `correct` occurs inside the replaced window.
    bad = case("E", "Header line.\nThe dose was 10 mg per day.\nFooter line.\n",
               "Header line.\nThe dose was increased to 20 mg per day.\nFooter line.\n",
               "10", "20", "Methods, paragraph 1",
               "The dose was 10 mg per day.",
               "The dose was increased to 20 mg per day.")
    check("R09 a wider replacement that realizes the plan passes", bad == {}, bad)
    # R10: the documented `paragraph N` qualifier resolves to that paragraph.
    bad = case("F", "# Results\n\nFirst measurement 10.\nSecond measurement 10.\n",
               "# Results\n\nFirst measurement 20.\nSecond measurement 10.\n",
               "10", "20", "Results, paragraph 2",
               "First measurement 10.", "First measurement 20.")
    check("R10 a plan at paragraph 2 is not discharged by editing paragraph 1",
          bad == {"paper.md": "the applied text is outside the plan's described "
                              "`wrong`/`correct` change"}, bad)
    bad = case("G", "# Results\n\nFirst measurement 10.\nSecond measurement 10.\n",
               "# Results\n\nFirst measurement 10.\nSecond measurement 20.\n",
               "10", "20", "Results, paragraph 2",
               "Second measurement 10.", "Second measurement 20.")
    check("R10 the same edit at the named paragraph passes", bad == {}, bad)


# ---------------------------------------------------------------- F015/F030/F031
def test_f015_f030_f031_cold_start():
    print("\n== F015/F030/F031: cold-start checked areas and id block ==")
    for fid, matched in (("X-900", False), ("X-9000", False), ("X-0001", False),
                         ("X-901", True), ("X-999", True), ("X-9001", True),
                         ("X-9999", True), ("X-10000", False)):
        check(f"F030 {fid} is {'inside' if matched else 'outside'} the reserved block",
              bool(pp.COLD_START_ID_RE.match(fid)) is matched)

    def errors(doc):
        tmp = scratch("fb1108wave2_cs_")
        d = tmp / "cold_start_review"
        d.mkdir()
        (d / "findings_cold_start_review.json").write_text(json.dumps(doc),
                                                           encoding="utf-8")
        (d / "coverage.md").write_text("# coverage\n", encoding="utf-8")
        return pp._cold_start_contract_problems(tmp)[0]

    e = errors({"checked": [{"area": "whole corpus", "examined": 0, "findings": 0}],
                "findings": []})
    check("F015 an examined area with 0 candidates is rejected",
          any("0 examined candidates" in x for x in e), e)
    e = errors({"checked": [{"area": "A", "examined": 1, "findings": 1},
                            {"area": "A", "examined": 1, "findings": 1}],
                "findings": [{"id": "X-901", "location": "x", "category": 1,
                              "check": "c", "severity": "Major", "evidence": "e",
                              "explanation": "x", "status": "resolvable"}]})
    check("F031 a duplicated checked area is rejected",
          any("more than once" in x for x in e), e)


# ---------------------------------------------------------------- F016/F119
def test_f016_f119_locators_and_reasons():
    print("\n== F016/F119: response locator and audit reason ==")
    ttext = "# Results\n\nThe value was 5 in the cohort.\n# Methods\n\nWe measured it.\n"
    for loc, ok in (("the", False), ("paper.md", False), ("Results", True),
                    ("whole file", True), ("paper.md:42", True),
                    ("line 42", True), ("manuscript.md:12", False),
                    # R11: a body word is not a section.
                    ("cohort", False), ("value", False)):
        p = pp._response_location_problem("JV-1", "paper.md", loc, "", "", None, ttext)
        check(f"F016 location {loc!r} is {'accepted' if ok else 'rejected'}",
              (p is None) is ok, p)
    valid = {"d1"}
    for reason, ok in (("x", False), ("ok", False), ("checked", False),
                       ("quoted text present at Results paragraph 2", True)):
        data = {"verdicts": [{"defect_id": "d1", "label": "TP", "reason": reason}]}
        cov = pp._defect_audit_coverage(data, valid,
                                        pp._normalize_defect_audit(data, valid))
        check(f"F119 reason {reason!r} is {'accepted' if ok else 'rejected'}",
              (not cov["empty_reasons"]) is ok, cov["empty_reasons"])


# ---------------------------------------------------------------- F017
def test_f017_windows_process_tree():
    print("\n== F017: Windows tools get a group and a tree kill ==")
    real_name = pp.os.name
    real_run = pp.subprocess.run
    captured = {}
    fake_proc = type("P", (), {"pid": 4242, "kill": lambda self: captured.setdefault("kill", True)})()

    def fake_run(argv, **kw):
        captured["argv"] = argv
        return None
    pp.os.name = "nt"
    pp.subprocess.run = fake_run
    try:
        kwargs = pp._tool_popen_kwargs()
        pp._kill_process_group(fake_proc)
    finally:
        pp.os.name = real_name
        pp.subprocess.run = real_run
    check("F017 the Windows branch creates a process group, not a POSIX session",
          "creationflags" in kwargs and "start_new_session" not in kwargs, kwargs)
    check("F017 the Windows timeout kills the process TREE",
          captured.get("argv", [None])[0] == "taskkill"
          and "/T" in captured.get("argv", []) and str(fake_proc.pid) in captured.get("argv", []),
          captured.get("argv"))


# ---------------------------------------------------------------- F023
def test_f023_installer_duplicate_merge():
    print("\n== F023: --merge never silently drops a duplicate serverName ==")
    if shutil.which("node") is None:
        print("[skip] node is not installed")
        return
    tmp = scratch("fb1108wave2_node_")
    dsh = tmp / "dsh"
    (dsh / "profiles" / "p1").mkdir(parents=True)
    patch = dsh / "profiles" / "p1" / "cordis.patch.yml"
    patch.write_text(
        "# profile\n"
        "# >>> codex-mcp-import (managed block; regenerate with install-codex-mcp.mjs) >>>\n"
        "- insert:\n"
        "    - id: one\n      name: '@deepseek-ai/dsh-mcp-client'\n      config:\n"
        '        serverName: "docx-compare"\n'
        "    - id: two\n      name: '@deepseek-ai/dsh-mcp-client'\n      config:\n"
        '        serverName: "docx-compare"\n'
        "    - id: other\n      name: '@deepseek-ai/dsh-mcp-client'\n      config:\n"
        '        serverName: "other"\n'
        "# <<< codex-mcp-import <<<\n", encoding="utf-8")
    servers = tmp / "servers.json"
    servers.write_text(json.dumps([{
        "name": "docx-compare", "enabled": True,
        "transport": {"type": "stdio", "command": "node", "args": ["/x.js"]}}]),
        encoding="utf-8")
    env = dict(os.environ, CODEX_HOME=str(tmp / "codex"))
    proc = subprocess.run(
        ["node", str(WS / "scripts" / "install-codex-mcp.mjs"), "--dry-run", "--merge",
         "--no-verify", "--profile", "p1", "--dsh-home", str(dsh),
         "--codex-home", str(tmp / "codex"), "--servers-json", str(servers)],
        capture_output=True, text=True, env=env, timeout=120)
    check("F023 a duplicate managed serverName fails the merge instead of being deduped",
          proc.returncode != 0 and "duplicate serverName" in proc.stderr,
          (proc.returncode, proc.stderr[-200:]))


# ---------------------------------------------------------------- F050
def test_f050_closure_markers():
    print("\n== F050: the exported closure honours markers and extras ==")

    class Dist:
        def __init__(self, name, requires):
            self.metadata = {"Name": name}
            self.version = "1.0"
            self.requires = requires

    dists = {
        "root": Dist("root", ["foo; extra == \"dev\"",
                              "bar; python_version < \"3\"",
                              "baz"]),
        "baz": Dist("baz", []),
    }

    def distribution(name):
        if name not in dists:
            raise ec.md.PackageNotFoundError(name)
        return dists[name]

    real = ec.md.distribution
    ec.md.distribution = distribution
    try:
        got = ec.closure(("root",))
    finally:
        ec.md.distribution = real
    check("F050 an optional-extra requirement is not in the closure", "foo" not in got, got)
    check("F050 an impossible-platform requirement is not in the closure",
          "bar" not in got, got)
    check("F050 an unconditional requirement is still in the closure",
          "baz" in got and "root" in got, got)


# ---------------------------------------------------------------- F053
def test_f053_xlsx_row_coordinate():
    print("\n== F053: a spreadsheet row keeps its source coordinate ==")
    tmp = scratch("fb1108wave2_xlsx_")
    p = tmp / "t.xlsx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("xl/workbook.xml",
                   '<workbook><sheets><sheet name="S1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships><Relationship Id="rId1" Type="worksheet" '
                   'Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml",
                   '<worksheet><sheetData>'
                   '<row r="1"><c r="A1"><v>7</v></c></row>'
                   '<row r="100"><c r="A100"><v>8</v></c></row>'
                   '</sheetData></worksheet>')
    text, notes = cc.xlsx_to_text(str(p))
    check("F053 row 1 keeps its coordinate", "### corpus-marker: row: S1!1" in text,
          repr(text))
    check("F053 row 100 keeps its coordinate (not renumbered to 2)",
          "### corpus-marker: row: S1!100" in text, repr(text))
    check("F053 the values are unchanged", "7" in text and "8" in text and not notes, notes)


# ---------------------------------------------------------------- F057/F059/F061
def test_f057_f059_f061_docs():
    print("\n== F057/F059/F061: the sweep reference has one ladder and both M5 directions ==")
    doc = (WS / "paper-skills" / "paper-review" / "references" / "sweeps.md").read_text(
        encoding="utf-8")
    check("F057 J5 states one severity ladder with Critical only when unrecoverable",
          "severity is set by ONE ladder" in doc
          and "Critical\nonly when the scope's topic is unrecoverable" in doc,
          "J5 ladder text missing")
    flat = " ".join(doc.split())
    check("F059 a valid plural is no longer listed as an M1 formatting defect",
          "HSP vs HSPs" not in flat
          and "an inflectional plural is NOT a formatting variant" in flat)
    check("F061 the M5 artifact models the present-but-unneeded direction",
          "present-but-unneeded items" in doc and "why\n  unneeded" in doc)
    prompt = (WS / "paper-skills" / "prompts" / "identify_issues.prompt.md").read_text(
        encoding="utf-8")
    ladder = ("a section- or argument-level one Major when the reader can recover "
              "the topic on re-reading and Critical only when the scope's topic is "
              "unrecoverable")
    for label, text in (("sweeps.md", doc),
                        ("identify_issues.prompt.md", prompt)):
        flat_text = " ".join(text.split())
        check(f"R04 {label} general calibration matches the J5 ladder",
              ladder in flat_text
              and "a section- or argument-level one Critical" not in flat_text)
    prompt_src = (WS / "paper_pipeline_parts" / "p03_prompts.py").read_text(
        encoding="utf-8")
    check("R05 the revision-audit example uses a reserved cold-start id",
          '"F-012|X-901|none"' in prompt_src
          and '"F-012|X-900|none"' not in prompt_src)


def main() -> int:
    test_f001_split_review_ownership()
    test_f002_f009_f010_f011_artifacts_and_basis()
    test_f012_f013_f026_f027_shape_gates()
    test_f005_repair_plan_binding()
    test_f015_f030_f031_cold_start()
    test_f016_f119_locators_and_reasons()
    test_f017_windows_process_tree()
    test_f023_installer_duplicate_merge()
    test_f050_closure_markers()
    test_f053_xlsx_row_coordinate()
    test_f057_f059_f061_docs()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED: {', '.join(FAILS)}")
        return 1
    print("ALL 2026-11-08 WAVE-2 FIX-BUGS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)

#!/usr/bin/env python3
"""Regression checks for the 2026-10-30 20:17 fix-bugs wave 1.

Run:  python3 .paper_test/test_fix_bugs_20261030_201726.py

Every Cxx below is a candidate from the verify-findings intersection; each
check failed on the pre-fix tree and pins the smallest observed defect.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
TMPDIRS = []
FAILS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs20261030_pp", "paper_pipeline.py")
pf = load("fixbugs20261030_pf", "paper_docx_format.py")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# C02 -- scheduler prepares only after the capacity check
# ---------------------------------------------------------------------------
def test_c02_scheduler_order():
    print("\n== C02: capacity check before prepare ==")
    src = (WS / "paper_pipeline_parts/p08_selection_driver.py").read_text("utf-8")
    body = src[src.index("def run_round_runs"):]
    loop = body[body.index("with ThreadPoolExecutor"):]
    # The examine-and-launch loop only: stop at the wait phase.
    loop = loop[:loop.index("# 2. wait for a completion")]
    cap = loop.find("if len(running) >= max(1, int(jobs))")
    prep = loop.find("state = prepare(e)")
    check("the jobs-cap check precedes prepare(e) in the launch loop",
          0 <= cap < prep, f"cap={cap} prepare={prep}")
    check("the materializer is not called for a run that cannot launch",
          "prepare(e)" in loop and cap < prep)


# ---------------------------------------------------------------------------
# C04 -- a bare table cell proves only a context-matching written number
# ---------------------------------------------------------------------------
def test_c04_number_context():
    print("\n== C04: cell provenance needs sentence/column context ==")
    tables = [("data.csv", "plot,year\n1,2020\n2,2020\n3,2020\n4,2020\n5,2020\n6,2020\n")]
    rows = [
        {"number": "1", "kind": "front", "sentence": "Ada^1^, Bob^2^, published in 2020."},
        {"number": "2", "kind": "front", "sentence": "Ada^1^, Bob^2^, published in 2020."},
        {"number": "2020", "kind": "front", "sentence": "Ada^1^, Bob^2^, published in 2020."},
    ]
    out = pf.reconcile_number_rows(rows, tables)
    check("an unrelated plot/year table proves none of the front-matter numbers",
          out["filled"] == 0 and all(not (r.get("source") or "") for r in rows), out)
    # A body-wide `story` cell 7 must not prove a bare "7" sentence with no
    # column context (the same false-proof class).
    story = [("d.csv", "story,score\n1,7\n2,8\n3,9\n4,10\n")]
    bare = [{"number": "7", "kind": "body", "sentence": "We processed seven of them."}]
    out = pf.reconcile_number_rows(bare, story)
    check("a bare cell in an unrelated column proves no context-free body number",
          out["filled"] == 0 and not (bare[0].get("source") or ""), out)
    # An unrelated column's AGGREGATE must obey the same exclusions: a sum is
    # not a licence to prove a front-matter superscript/year or a body number
    # whose sentence names nothing the table carries.
    agg_cases = [
        ("a front-matter superscript",
         [{"number": "2", "kind": "front", "sentence": "Ada^2^ and Bob wrote it."}],
         [("d.csv", "x,y\n1,9\n1,8\n0,7\n")]),
        ("a context-free body number",
         [{"number": "6", "kind": "body", "sentence": "We processed 6 of them."}],
         [("d.csv", "x,y\n1,9\n2,8\n3,7\n")]),
        ("a front-matter publication year",
         [{"number": "2020", "kind": "front",
           "sentence": "Published in 2020 by the group."}],
         [("d.csv", "x,y\n1000,9\n1000,8\n20,7\n")]),
    ]
    for label, agg_rows, agg_tables in agg_cases:
        out = pf.reconcile_number_rows(agg_rows, agg_tables)
        check(f"an unrelated column aggregate is not a proof of {label}",
              out["filled"] == 0 and not (agg_rows[0].get("source") or ""), out)
    # A bare value list with no sentence keeps its aggregate proof: the
    # documented callers that reconcile value-only rows are not broken.
    bare_agg = [{"number": "36", "source": ""}]
    out = pf.reconcile_number_rows(
        bare_agg, [("t.tsv", "name\tvalue\na\t11\nb\t12\nc\t13\n")])
    check("a sentence-less row keeps the distinctive aggregate proof",
          out["filled"] == 1 and bare_agg[0]["source"].startswith("recomputed:"), out)
    # The documented legitimate proofs stay: an aggregate, a rounded cell whose
    # sentence names the column's quantity, and the matching column's value.
    tables2 = [("dataset_summary.tsv",
                "dataset\tn_cells_total\tsample_mean_ploidy\n"
                "A\t64\t1.773\nB\t2055\t2.2\nC\t1046\t3.823\nD\t42200\t2.0\n")]
    ledger = pf.number_ledger(
        ["The 41 datasets yielded 45,365 cells; the largest had 2,055 cells and "
         "ploidies from 1.77 to 3.82."])
    pf.reconcile_number_rows(ledger, tables2)
    sources = {r["number"]: r.get("source") or "" for r in ledger}
    check("the documented sum/rounded-cell proofs still work",
          "sum of column" in sources.get("45,365", "")
          and "n_cells_total" in sources.get("2,055", "")
          and "sample_mean_ploidy" in sources.get("1.77", "")
          and "sample_mean_ploidy" in sources.get("3.82", ""), sources)


# ---------------------------------------------------------------------------
# C07 / C81 -- a row cap is named, never silent
# ---------------------------------------------------------------------------
def test_c07_c81_seed_truncation():
    print("\n== C07/C81: the M30 seed names its truncation ==")
    nums = [{"number": str(i), "sentence": f"Sample {i} was analysed.",
             "kind": "body", "document": "m.md", "document_paragraph": i}
            for i in range(1, 260)]
    table = [("data.csv", "sample,value\n" + "".join(f"{i},{i}\n" for i in range(1, 40)))]
    rows = pf.hierarchy_seed_rows(nums, table, limit=200)
    check("the hierarchy seed caps at 200 data rows plus one gap row",
          len(rows) == 201 and "further written-value row" in rows[-1]["sentence"],
          rows[-1] if rows else "")
    tmp = scratch("fixbugs30_code_")
    (tmp / "analysis.py").write_text(
        "\n".join(f"N_{i} = {i}" for i in range(250)), encoding="utf-8")
    literals = pf.code_literal_rows([(tmp, "", ())], limit=200)
    check("the code-literal table caps at 200 rows plus one truncation row",
          len(literals) == 201 and literals[-1]["file"] == "(truncated)"
          and "further module-level literal" in literals[-1]["context"],
          literals[-1] if literals else "")


# ---------------------------------------------------------------------------
# C09 -- a table/reference block is not a prose paragraph
# ---------------------------------------------------------------------------
def test_c09_table_not_prose():
    print("\n== C09: table/container text is not a mega-paragraph ==")
    long = " ".join(["word"] * 300)
    check("a markdown-table kind files no FMT-T9c/T9i prose row",
          pf.long_text_rows([long], kinds=["table"]) == [],
          pf.long_text_rows([long], kinds=["table"]))
    check("a DOCX table cell files no prose row",
          pf.long_text_rows([long], kinds=["front"], in_container=[True]) == [])
    check("references are not prose paragraphs",
          pf.long_text_rows([long], kinds=["references"]) == [])
    body = pf.long_text_rows([long], kinds=["body"])
    check("a real body paragraph still gets the advisory gap (not a finding)",
          any(r["rule"] == "FMT-T9i" and r["tier"] == "advisory" for r in body)
          and not any(r["rule"] == "FMT-T9i" and r["tier"] == "finding" for r in body),
          body)


# ---------------------------------------------------------------------------
# C10 -- venue style limits are profile data, not invented rules
# ---------------------------------------------------------------------------
def test_c10_style_limits():
    print("\n== C10: FMT-T9c/T9i follow the venue profile ==")
    long_body = " ".join(["word"] * 300)
    bare = pf.long_text_rows([long_body], kinds=["body"])
    check("no profile bar -> advisory gap, never a finding-tier long sentence",
          any(r["rule"] == "FMT-T9c" and r["tier"] == "advisory"
              and "states no sentence-length limit" in r["evidence"] for r in bare)
          and not any(r["rule"] == "FMT-T9c" and r["tier"] == "finding" for r in bare),
          bare)
    limited = pf.long_text_rows(
        [long_body], kinds=["body"],
        style_limits={"sentence_words": {"body": 46}, "paragraph_words": 250})
    check("a profile-declared bar is finding-tier and names the profile value",
          any(r["rule"] == "FMT-T9c" and r["tier"] == "finding"
              and "profile bar 46" in r["evidence"] for r in limited)
          and any(r["rule"] == "FMT-T9i" and r["tier"] == "finding" for r in limited),
          limited)
    limited_high = pf.long_text_rows(
        [" ".join(["word"] * 260)], kinds=["body"],
        style_limits={"paragraph_words": 500})
    check("a paragraph below the profile cap is not a mega-paragraph",
          not any(r["rule"] == "FMT-T9i" for r in limited_high), limited_high)
    # The profile path must actually REACH the scan: a VenueProfile that
    # declares the block has to survive normalization, format_policy_of() and
    # the sandbox format_policy.json the session's own scan reads. The bare
    # long_text_rows() call above cannot catch a dropped profile key.
    declared = {"sentence_words": {"body": 46}, "paragraph_words": 250}
    prof = pp.VenueProfile({"id": "probe-venue", "label": "Probe",
                            "style_limits": declared})
    check("normalize_venue_profile keeps a declared style_limits block",
          prof.data.get("style_limits") == declared, prof.data.get("style_limits"))
    original_profile_of = pp.venue_profile_of
    pp.venue_profile_of = lambda ctx=None, required=False: prof
    try:
        ctx = type("C", (), {"cfg": {}})()
        policy = pp.format_policy_of(ctx)
        check("format_policy_of carries the venue profile's style_limits",
              policy.get("style_limits") == declared, policy.get("style_limits"))
        sb = scratch("fixbugs30_style_")
        policy_path = pp.seed_format_policy_file(ctx, sb)
        written = json.loads(Path(policy_path).read_text(encoding="utf-8"))
        check("the sandbox format_policy.json carries style_limits",
              written.get("style_limits") == declared, written.get("style_limits"))
        scanned = pf.text_style_rows(
            ["Results", long_body], headings=[True, False], policy=written)
        check("the written policy makes the scan finding-tier at the profile bar",
              any(r["rule"] == "FMT-T9c" and r["tier"] == "finding"
                  and "profile bar 46" in r["evidence"] for r in scanned), scanned)
    finally:
        pp.venue_profile_of = original_profile_of


# ---------------------------------------------------------------------------
# C11 -- a decision table with no disposition column is not clean
# ---------------------------------------------------------------------------
def test_c11_missing_disposition():
    print("\n== C11: a renamed decision column is caught ==")
    tmp = scratch("fixbugs30_art_")
    art = tmp / "guided_review" / "artifacts"
    art.mkdir(parents=True)
    for rel in pp.DECISION_ARTIFACTS:
        p = art / Path(rel).name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("| foo | bar |\n|---|---|\n| x | y |\n", encoding="utf-8")
    report = pp.artifact_quality_report(tmp / "guided_review")
    check("every renamed decision artifact reports the missing disposition column",
          len(report) == len(pp.DECISION_ARTIFACTS)
          and all("no table with a `disposition` column" in v[0] for v in report.values()),
          report)
    # A correct seeded table still passes.
    good = scratch("fixbugs30_art_good_")
    ga = good / "guided_review" / "artifacts"
    ga.mkdir(parents=True)
    (ga / "M20_formatting.md").write_text(
        "| # | rule | tier | disposition |\n|---|---|---|---|\n"
        "| 1 | FMT-T9c | finding | OK — FMT-T9c: inside the bar |\n", encoding="utf-8")
    check("a disposed table still passes", not pp.artifact_quality_report(good / "guided_review"))


# ---------------------------------------------------------------------------
# C16 -- audit drop evidence is row-specific
# ---------------------------------------------------------------------------
def test_c16_drop_boilerplate():
    print("\n== C16: a boilerplate drop evidence is rejected ==")
    frozen = ["F-001", "F-002", "F-003"]
    same = ("the quoted text does not appear at the cited location in the manuscript at all")
    audit = {"dispositions": [{"id": i, "verdict": "drop", "reason": same, "evidence": same}
                              for i in frozen], "adds": []}
    probs = pp.audit_artifact_problems(audit, frozen)
    check("identical evidence across drops is rejected", any("SAME evidence" in p for p in probs),
          probs)
    distinct = {"dispositions": [
        {"id": "F-001", "verdict": "drop",
         "reason": "the quoted sentence is absent from base/main.md at the cited line",
         "evidence": "base/main.md:12 reads 'the assay ran twice', not the quoted sentence F-001"},
        {"id": "F-002", "verdict": "drop",
         "reason": "the cited table row does not exist in the package's raw data",
         "evidence": "raw_data/calls.csv has no row F-002 quotes ('sample 99'), checked line by line"},
        {"id": "F-003", "verdict": "drop",
         "reason": "the claimed figure label is the opposite of what the figure prints",
         "evidence": "figure 2's legend reads 'precision', while F-003 quotes 'recall' from it"},
    ], "adds": []}
    check("per-finding evidence passes",
          not [p for p in pp.audit_artifact_problems(distinct, frozen) if "SAME evidence" in p],
          pp.audit_artifact_problems(distinct, frozen))


# ---------------------------------------------------------------------------
# C20 -- a one-character OK reason is not a fact-preservation disposition
# ---------------------------------------------------------------------------
def test_c20_ok_reason():
    print("\n== C20: `OK — x` is rejected; the seed row survives ==")
    check("`OK — x` is not a reason", not pp._deletion_disposition_ok("OK — x"))
    check("the pipeline's own no-removal seed row is still valid",
          pp._deletion_disposition_ok("OK — nothing removed"))
    check("a documented surviving-location reason passes",
          pp._deletion_disposition_ok("OK — the fact survives in Sec. 2 of main.md"))
    tmp = scratch("fixbugs30_del_")
    sb = tmp / "sb"
    (sb / "revision_audit").mkdir(parents=True)
    (sb / "revision_audit" / "DELETED_PARAGRAPHS.md").write_text(
        "| # | document | line | paragraph | disposition |\n"
        "|---|---|---|---|---|\n"
        "| 1 | a.md | 3 | Fact one. | OK — x |\n", encoding="utf-8")
    probs = pp.deletion_audit_problems(sb, expected_rows=1,
                                       expected_paragraphs=["Fact one."])
    check("the deletion audit rejects `OK — x`",
          any("outside the seeded vocabulary" in p for p in probs), probs)


# ---------------------------------------------------------------------------
# C34 -- the review finding carries its status
# ---------------------------------------------------------------------------
def test_c34_review_status():
    print("\n== C34: the review contract requires `status` ==")
    sb = scratch("fixbugs30_rev_")
    (sb / "base").mkdir()
    (sb / "guided_review" / "artifacts").mkdir(parents=True)
    fj = {"submission_dir": "./base",
          "findings": [{"id": "F-001", "location": "p1", "check": "M1", "category": 2,
                        "severity": "Minor", "evidence": "e", "explanation": "x"}],
          "coverage": []}
    errs, warns = [], []
    pp.check_review_contract(None, sb, fj, errs, warns, scope="full", split="off")
    check("a finding without `status` is malformed",
          any("status None is not one of" in e for e in errs), errs)
    fj["findings"][0]["status"] = "resolvable"
    errs = []
    pp.check_review_contract(None, sb, fj, errs, warns, scope="full", split="off")
    check("a finding with a canonical status passes that check",
          not [e for e in errs if "status" in e], errs)


# ---------------------------------------------------------------------------
# C41 -- a negative first-line indent is in the indentation family
# ---------------------------------------------------------------------------
def test_c41_negative_indent():
    print("\n== C41: a negative first-line indent is not dropped ==")
    body = " ".join(["word"] * 30)
    frag_neg = (f'<w:p><w:pPr><w:ind w:firstLine="-360"/></w:pPr>'
                f'<w:r><w:t>{body}</w:t></w:r></w:p>')
    frag_plain = f'<w:p><w:r><w:t>{body}</w:t></w:r></w:p>'
    paras = [(0, len(frag_neg), frag_neg),
             (len(frag_neg), len(frag_neg) + len(frag_plain), frag_plain)]
    rows = pf.layout_consistency_rows("<w:document/>", paras, None, "x.docx")
    check("a negative indent and a flush body file FMT-T8f",
          any(r["rule"] == "FMT-T8f" for r in rows), rows)
    check("the negative paragraph is counted as the indented side",
          any("1 body paragraph(s) first-line indented" in r["evidence"] for r in rows), rows)


# ---------------------------------------------------------------------------
# C51/C52 -- bounded subprocess: process group and byte cap
# ---------------------------------------------------------------------------
def _sleeping_cmd(tmp: Path, marker: str) -> list:
    child = tmp / "child.py"
    child.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen(['sleep', sys.argv[1]])\n"
        "time.sleep(30)\n", encoding="utf-8")
    return [sys.executable, str(child), marker]


def test_c51_c52_run_bounded():
    print("\n== C51/C52: run_bounded kills the group and caps the stream ==")
    tmp = scratch("fixbugs30_bounded_")
    marker = f"{os.getpid()}98765"
    try:
        pp.run_bounded(_sleeping_cmd(tmp, marker), 1)
    except subprocess.TimeoutExpired:
        pass
    time.sleep(0.5)
    ps = subprocess.run(["ps", "-eo", "pid,ppid,cmd"], capture_output=True, text=True)
    orphans = []
    for line in ps.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[2].strip() == f"sleep {marker}":
            orphans.append(parts)
    for pid, _ppid, _cmd in orphans:
        try:
            os.kill(int(pid), 9)
        except OSError:
            pass
    check("a timed-out child's grandchild does not survive", not orphans, orphans)

    old = pp.MAX_TOOL_OUTPUT_BYTES
    pp.MAX_TOOL_OUTPUT_BYTES = 1000
    try:
        child = tmp / "writer.py"
        child.write_text("import sys\nsys.stdout.write('x' * 200000)\n"
                         "sys.stdout.flush()\n", encoding="utf-8")
        try:
            pp.run_bounded([sys.executable, str(child)], 10)
            raised = False
        except pp.ToolOutputOverBudget:
            raised = True
        check("a child that crosses the byte cap is stopped and reported", raised)
    finally:
        pp.MAX_TOOL_OUTPUT_BYTES = old


# ---------------------------------------------------------------------------
# C53 -- a newly created symlink is a bounded-repair violation
# ---------------------------------------------------------------------------
def test_c53_new_symlink():
    print("\n== C53: a new symlink under revised/ is a violation ==")
    tmp = scratch("fixbugs30_symlink_")
    pre, cur = tmp / "pre", tmp / "cur"
    pre.mkdir()
    cur.mkdir()
    (pre / "a.md").write_text("a\n", encoding="utf-8")
    (cur / "a.md").write_text("a\n", encoding="utf-8")
    os.symlink("/etc/hostname", cur / "evil.md")
    bad = pp._revised_repair_violations(pre, cur, [{"id": "x", "file": "a.md"}], {"x"})
    check("the unplanned symlink is reported", "evil.md" in bad, bad)
    # An unchanged symlink is not a NEW link and is not a violation.
    pre2, cur2 = tmp / "pre2", tmp / "cur2"
    pre2.mkdir()
    cur2.mkdir()
    (pre2 / "a.md").write_text("a\n", encoding="utf-8")
    (cur2 / "a.md").write_text("a\n", encoding="utf-8")
    os.symlink("/etc/hostname", pre2 / "same.md")
    os.symlink("/etc/hostname", cur2 / "same.md")
    check("an unchanged symlink is not reported",
          "same.md" not in pp._revised_repair_violations(
              pre2, cur2, [{"id": "x", "file": "a.md"}], {"x"}))


# ---------------------------------------------------------------------------
# C55 -- the always-built documentation names the skip states
# ---------------------------------------------------------------------------
def test_c55_docs():
    print("\n== C55: final_clean_version docs match the skip states ==")
    readme = (WS / "README.md").read_text("utf-8")
    check("the README no longer promises ALWAYS built", "ALWAYS built" not in readme)
    check("the README names the no-champion skip contract",
          "no winner/pin" in readme and "skip reason" in readme)


# ---------------------------------------------------------------------------
# C62 -- the auditor's coverage table is checked
# ---------------------------------------------------------------------------
def test_c62_audit_coverage():
    print("\n== C62: the audit coverage table is required ==")
    check("a missing coverage table is a problem",
          any("no 'coverage' table" in p
              for p in pp.audit_coverage_problems({"dispositions": [], "adds": []})))
    full = ([{"check": f"M{i}", "disposition": "clean -- re-derived"} for i in range(1, 37)]
            + [{"check": f"J{i}", "disposition": "clean -- re-derived"} for i in range(1, 6)])
    check("a complete coverage table passes", not pp.audit_coverage_problems({"coverage": full}))
    partial = [{"check": "M1", "disposition": "clean"}]
    check("a partial coverage table names the missing checks",
          any("coverage row(s) are missing" in p
              for p in pp.audit_coverage_problems({"coverage": partial})))


# ---------------------------------------------------------------------------
# C72 -- the review prompt's layout names the full D0-D5 set
# ---------------------------------------------------------------------------
def test_c72_prompt_layout():
    print("\n== C72: the review layout names every D0-D5 deliverable ==")
    text = (WS / "paper_pipeline_parts/p03_prompts.py").read_text("utf-8")
    section = text[text.index("=== CANONICAL OUTPUTS"):text.index("@@DEFECT_CLASS_RULE@@")]
    missing = [name for name in pp.DISCOVERY_ROUND_FILES if name not in section]
    check("every required discovery file is in the canonical layout",
          not missing, missing)
    check("the old three-file summary is gone",
          "findings_extra.{md,json} and new_sweeps.md." not in section)


# ---------------------------------------------------------------------------
def main() -> int:
    print("Regression checks for fix-bugs 2026-10-30 20:17 (wave 1)")
    for fn in (test_c02_scheduler_order, test_c04_number_context,
               test_c07_c81_seed_truncation, test_c09_table_not_prose,
               test_c10_style_limits, test_c11_missing_disposition,
               test_c16_drop_boilerplate, test_c20_ok_reason,
               test_c34_review_status, test_c41_negative_indent,
               test_c51_c52_run_bounded, test_c53_new_symlink,
               test_c55_docs, test_c62_audit_coverage, test_c72_prompt_layout):
        fn()
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILS:
        print(f"\n{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("\nALL FIX-BUGS (2026-10-30 20:17) CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

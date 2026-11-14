#!/usr/bin/env python3
"""Fix-bug regression assertions for group O (ranking/reports/redlines).

Run:  python3 .paper_test/test_fix_bugs_20261114_O.py

Self-contained; tempfile only. Prints "[ok ] name" / "[FAIL] name" and exits 1
if any assertion fails.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
import types
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("paper_fix_bugs_o", str(WS / "paper_pipeline.py"))
pp = importlib.util.module_from_spec(spec)
sys.modules["paper_fix_bugs_o"] = pp
spec.loader.exec_module(pp)

FAILS = []
TMPDIRS = []
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def check(name, cond, detail=""):
    if cond:
        print(f"[ok ] {name}")
    else:
        FAILS.append(f"{name}: {detail}")
        print(f"[FAIL] {name}: {detail}")


def tmpdir(prefix="fixbugs_o_"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def stat(**kw):
    d = {"n": 3, "expected_n": 3, "complete": True, "vs_original_complete": True,
         "vs_original_n": 1, "vs_original_expected": 1, "anti_regression_ok": True,
         "median": 0.0, "mean": 0.0, "iqr": 0.0, "digest": "0" * 40,
         "vs_original": 0.0, "vs_base": 0.0, "caption_note": "",
         "author_placeholders": 0}
    d.update(kw)
    return d


def make_docx(path, p1, table_cell=None, p2_xml=None, header=None):
    body = f'<w:p><w:r><w:t>{p1}</w:t></w:r></w:p>'
    if table_cell is not None:
        body += (f'<w:tbl><w:tr><w:tc><w:p><w:r><w:t>{table_cell}</w:t></w:r>'
                 f'</w:p></w:tc></w:tr></w:tbl>')
    if p2_xml is not None:
        body += f'<w:p>{p2_xml}</w:p>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   f'<w:document {W}><w:body>{body}</w:body></w:document>')
        if header is not None:
            z.writestr("word/header1.xml",
                       f'<w:hdr {W}><w:p><w:r><w:t>{header}</w:t></w:r></w:p></w:hdr>')


def over_marked_pair(root):
    long_words = " ".join(f"word{i}" for i in range(300))
    base, rev = root / "base.docx", root / "rev.docx"
    make_docx(base, "alpha beta", "1", f"<w:r><w:t>{long_words}</w:t></w:r>")
    a = " ".join(f"word{i}" for i in range(150)) + " "
    b = " ".join(f"word{i}" for i in range(150, 300))
    make_docx(rev, "alpha gamma", "2",
              f'<w:r><w:t xml:space="preserve">{a}</w:t></w:r><w:r><w:t>{b}</w:t></w:r>')
    return base, rev


def make_census_ctx(root):
    ctx = types.SimpleNamespace(
        root=root, reports_dir=root / "reports", state={},
        runs=lambda kind=None, round_no=None: [],
        round_rec=lambda r: {"field": ["a", "b"]},
        round_get=lambda r: {"field": ["a", "b"]},
        save_state=lambda: None)
    ctx.reports_dir.mkdir(parents=True, exist_ok=True)
    return ctx


def synthetic_agg():
    obs = [("j1", "a", "b", {"score": 1, "basis": "correctness", "resolved": [],
                             "introduced": [{"check": "M4", "tier": "correctness",
                                             "severity": "minor", "evidence": "row one"}]}),
           ("j2", "b", "a", {"score": 1, "basis": "correctness", "resolved": [],
                             "introduced": [{"check": "M5", "tier": "correctness",
                                             "severity": "minor", "evidence": "row two"}]})]
    return {"field": ["a", "b"],
            "issue_census": pp.build_issue_census(obs, ["a", "b"], sessions_expected=2),
            "issue_rows": pp.build_issue_ledger_rows(obs, ["a", "b"]),
            "score_rows": [], "stats": {}}


# ------------------------------------------------------------------ F48
def test_f48_docs():
    text = (WS / "paper_pipeline_parts" / "README.md").read_text(encoding="utf-8")
    check("F48 the parts README separates the executed parts from import-on-demand modules",
          "are **not** executed parts" in text and "import-on-demand module" in text
          and "`ranking.py` and `decision_report.py` are **not**" in text)
    executed = [p.name for p in (WS / "paper_pipeline_parts").glob("p[0-9][0-9]_*.py")]
    check("F48 the loader's glob does not execute ranking.py/decision_report.py",
          "ranking.py" not in executed and "decision_report.py" not in executed, executed)
    check("F48 decision_report.py is loaded on demand by p12",
          '_load_pipeline_module("paper_pipeline_parts/decision_report.py")'
          in (WS / "paper_pipeline_parts" / "p12_conflicts_decide.py").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ F49
def test_f49_round_bound():
    class Ctx:
        def rounds_count(self):
            return 1

    class Args:
        redline_cmd = None
        round = 9
        version = "all"
        tool = "auto"

    for fn, label in ((pp._cmd_redline_locked, "redline"),
                      (pp._cmd_track_locked, "track")):
        try:
            fn(Ctx(), Args())
            raised = False
        except SystemExit as e:
            raised = e.code not in (0, None)
        check(f"F49 {label} --round 9 on a 1-round root is refused", raised)


# ------------------------------------------------------------ F165/F172
def test_f165_f172_location_census():
    def obs(sess, evidence):
        return (sess, "a", "b", {"score": 0, "basis": "correctness", "resolved": [],
                "introduced": [{"check": "M4", "tier": "correctness",
                                "severity": "minor", "evidence": evidence}]})
    x = "line 42: alpha bravo charlie delta echo foxtrot golf hotel india juliet"
    y = "line 42: alpha bravo charlie delta echo foxtrot golf hotel india kilo"
    z = "line 42: alpha bravo charlie delta echo foxtrot golf hotel lima juliet"
    observations = [obs("s3", x), obs("s1", y), obs("s2", z)]
    census = pp.build_issue_census(observations, ["a", "b"], sessions_expected=3,
                                   dedup="location")
    issue_rows = pp.build_issue_ledger_rows(observations, ["a", "b"], dedup="location")
    agg = {"field": ["a", "b"], "issue_census": census, "issue_rows": issue_rows}
    ctx = make_census_ctx(tmpdir())
    sorted_rows = pp.defect_list_rows(ctx, 1, agg)
    check("F165 the fixture puts the defect list in a different order than the census",
          [r["session"] for r in sorted_rows] != [r["session"] for r in issue_rows],
          ([r["session"] for r in sorted_rows], [r["session"] for r in issue_rows]))
    filtered = pp.census_from_filtered_rows(census, sorted_rows, order_rows=issue_rows)
    a, tpl = filtered["a"], census["a"]
    check("F165 the TP-only census reproduces the recorded merge count",
          (a["total"], a["raw_own"], a["merged_own"])
          == (tpl["total"], tpl["raw_own"], tpl["merged_own"]),
          (a["total"], a["raw_own"], a["merged_own"]))
    labelled = pp.apply_defect_audit(sorted_rows,
                                     {r["defect_id"]: ("TP", "checked")
                                      for r in sorted_rows})
    audited = pp.audited_defect_agg(ctx, 1, agg, labelled)
    aa = audited["issue_census"]["a"]
    check("F172 the audited census records raw/merged instead of raw=own, merged=0",
          aa["raw_own"] == tpl["raw_own"] and aa["merged_own"] == tpl["merged_own"]
          and aa["total"] == tpl["total"],
          (aa["raw_own"], aa["merged_own"], aa["total"]))


# ------------------------------------------------------------------ F166
def test_f166_recorded_dedup():
    d = tmpdir()
    ctx = make_census_ctx(d)
    ctx.round_rec = lambda r: {"field": ["a", "b"], "dedup_mode": "location"}
    seen = {}
    real = pp.aggregate_round

    def spy(c, r, field, dedup=None, rule=None):
        seen["dedup"] = dedup
        return {"issue_census": {}, "field": field}

    try:
        pp.aggregate_round = spy
        pp.write_round_issue_census(ctx, 1)
    finally:
        pp.aggregate_round = real
    check("F166 the agg=None census back-fill uses the round's recorded dedup_mode",
          seen.get("dedup") == "location", seen)
    try:
        pp.aggregate_round = spy
        pp._defect_rows_by_reaggregation(ctx, 1)
    finally:
        pp.aggregate_round = real
    check("F166 the defect-row re-aggregation uses the recorded dedup_mode too",
          seen.get("dedup") == "location", seen)


# ------------------------------------------------------------------ F167
def test_f167_non_document_parts():
    d = tmpdir()
    base, rev = d / "base.docx", d / "rev.docx"
    make_docx(base, "same body", header="OLD HEADER")
    make_docx(rev, "same body", header="NEW HEADER")
    out = d / "out.docx"
    info = pp.builtin_tracked_changes(base, rev, out)
    with zipfile.ZipFile(out) as z:
        header = z.read("word/header1.xml").decode()
    check("F167 the built-in redline carries the revised header part",
          "NEW HEADER" in header, header[:80])
    check("F167 a changed non-document part is reported as a warning",
          info.get("non_document_parts_changed") == ["word/header1.xml"]
          and "word/header1.xml" in (info.get("warning") or ""), info)


# ------------------------------------------------------------------ F168
def test_f168_warning_join():
    d = tmpdir()
    base, rev = over_marked_pair(d)
    res = pp.redline_one_pair("builtin", [], base, rev, d / "out.docx")
    warning = res.get("warning") or ""
    check("F168 the over-marked caveat is APPENDED to the structural warning",
          "tables/content-controls" in warning and "over-marked redline" in warning,
          warning[:200])


# ------------------------------------------------------------------ F169
def test_f169_failed_audit_record():
    d = tmpdir()
    ctx = make_census_ctx(d)
    agg = synthetic_agg()
    stub = ("import json;d=json.load(open('defects.json'));"
            "json.dump({'verdicts':[{'defect_id':d['defects'][0]['defect_id'],"
            "'label':'TP','reason':'checked the quoted text'}]},open('audit.json','w'))")
    res = pp.write_round_defect_audit(ctx, 1, agg=agg,
                                      agent_cmd=[sys.executable, "-c", stub], timeout=60)
    meta_path = ctx.reports_dir / "round1_defect_audit.json"
    import json
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    check("F169 a partial audit still writes round1_defect_audit.json with ok=False",
          res.get("ok") is False and meta.get("ok") is False
          and meta.get("coverage"), (res.get("ok"), meta.get("ok")))
    # A second attempt archives the previously submitted audit before clearing it.
    pp.write_round_defect_audit(ctx, 1, agg=agg,
                                agent_cmd=[sys.executable, "-c", stub], timeout=60)
    sb = ctx.reports_dir / "defect_audit_round1"
    check("F169 the submitted audit.json is archived before the next attempt",
          (sb / "audit.previous.json").is_file(), sorted(p.name for p in sb.glob("*")))


# ------------------------------------------------------------------ F170
def test_f170_markdown_cells():
    manifest = {"generated": "now", "tool": "auto", "notes": [], "versions": [
        {"round": 1, "version": "w1", "skipped": [], "comparisons": [
            {"base_rel": "table 1|final.docx", "revised_rel": "new `doc`.docx",
             "source": "from-base", "basis": "same name", "tool": "builtin-ooxml",
             "ok": True, "warning": "bad | warning"}]}]}
    text = pp.redline_readme(manifest)
    row = next(ln for ln in text.splitlines() if "table 1" in ln)
    bullet = next(ln for ln in text.splitlines() if ln.startswith("- r1"))
    check("F170 a pipe in a document name is escaped in the README table",
          "table 1\\|final.docx" in row, row)
    check("F170 a backtick in a document name cannot close the code span",
          "``new `doc`.docx``" in row, row)
    check("F170 a pipe/newline in a warning cannot break the caveat bullet",
          "bad \\| warning" in bullet, bullet)


# ------------------------------------------------------------------ F171
def test_f171_temp_failure():
    d = tmpdir()
    base, rev = over_marked_pair(d)
    saved = (pp.docx_compare_mcp_spec, pp._redlines_inproc, pp._run_redline_cmd)
    pp.docx_compare_mcp_spec = lambda: None
    pp._redlines_inproc = lambda *a, **k: {"backend": "stub", "ok": False,
                                           "rc": None, "detail": "stub fail"}
    pp._run_redline_cmd = lambda *a, **k: {"backend": "docx-trackdiff", "ok": False,
                                           "rc": None, "detail": "stub fail"}
    import tempfile as tf
    real_mkstemp = tf.mkstemp
    tf.mkstemp = lambda *a, **k: (_ for _ in ()).throw(OSError("no space left"))
    try:
        try:
            res = pp.redline_one_pair("auto", [], base, rev, d / "out.docx")
            escaped = False
        except OSError:
            res, escaped = None, True
    finally:
        tf.mkstemp = real_mkstemp
        (pp.docx_compare_mcp_spec, pp._redlines_inproc,
         pp._run_redline_cmd) = saved
    check("F171 a temp-file OSError is recorded, not raised out of redline_one_pair",
          not escaped and res is not None and res.get("ok") is False,
          None if escaped else (res or {}).get("attempts"))


# ------------------------------------------------------------------ F173
def test_f173_unreadable_reason():
    d = tmpdir()
    base, rev = d / "base", d / "rev"
    base.mkdir()
    rev.mkdir()
    bad = base / "manuscript.docx"
    bad.write_bytes(b"not a zip")
    make_docx(rev / "manuscript.docx", "body")
    os.chmod(bad, 0o000)
    try:
        problems = []
        found = pp.list_track_files([(base, "", ())], problems=problems)
        pair_problems = []
        pp.match_docx_pairs([(base, "", ())], [(rev, "", ())],
                            base_problems=pair_problems)
    finally:
        os.chmod(bad, 0o644)
    check("F173 an unreadable trackable file is returned as a machine-readable problem",
          found == [] and len(problems) == 1 and len(pair_problems) == 1
          and problems[0]["rel"] == "manuscript.docx" and problems[0]["error"],
          problems)


# ---------------------------------------------------------- F174/F176/F178/F179
def test_ranking_fixes():
    no_census = {"median": 2.0, "mean": 2.0, "iqr": 0.0, "digest": "a" * 40}
    one = {"defect_prefix_total": 1, "median": 0.0, "mean": 0.0, "iqr": 0.0,
           "digest": "b" * 40}
    check("F174 a row with no recorded census/total is ranked WORST, never as zero defects",
          pp.champion_sort_key(no_census) > pp.champion_sort_key(one),
          pp.champion_sort_key(no_census)[:1])

    stats = {"w1": stat(vs_original_complete=None, anti_regression_ok=True, median=2.0),
             "a2": stat(median=1.0), "base": stat(median=0.0)}
    sel = pp.derive_ranking(stats, ["w1", "a2"], "base", {}, 10, 2)
    check("F176 a fresh arm with no recorded vs_original_complete is ineligible",
          "w1" not in sel["eligible"] and sel["champion"] != "w1", sel["eligible"])

    try:
        sel = pp.derive_ranking({"a2": stat(median=1.0)}, ["a2"], "missingbase", {}, 10, 2)
        raised = None
    except KeyError as e:
        sel, raised = None, e
    check("F178 a base_rep absent from stats is reported, not KeyError",
          raised is None and sel is not None and sel["champion"] == "a2",
          raised or (sel or {}).get("trace"))

    sel = pp.derive_ranking({"a2": stat(digest=None), "i1": stat(digest=None)},
                            ["a2", "i1"], None, {}, 0, 2)
    check("F179 undigested rows are ineligible instead of tie-broken by input order",
          sel["eligible"] == [] and sel["champion"] == pp.A1_ID, sel["eligible"])


# ------------------------------------------------------------ F187/F188
def test_decision_report():
    dr = pp._load_pipeline_module("paper_pipeline_parts/decision_report.py")
    common = dict(generated="now", root="/r", version="9", config_line="cfg",
                  venue_lines=[], clean_readme_name="final_clean_version.readme.md",
                  integrity={"pristine_ok": True, "pristine_detail": "ok",
                             "pinned_errors": []},
                  pin_count=0, problems=[])
    lines = dr.header_lines(certification={"certified": False, "provisional": True,
                                           "blockers": [], "notes": []},
                            verdict="PROVISIONAL", **common)
    line = next(ln for ln in lines if "Certification" in ln)
    check("F187 a PROVISIONAL verdict never says 'every gate passed'",
          "every gate passed" not in line and "provisional" in line.lower(), line)
    lines = dr.header_lines(certification={"certified": True, "blockers": [],
                                           "notes": "only round 2 of 3 is complete"},
                            verdict="CERTIFIED", **common)
    line = next(ln for ln in lines if "Certification" in ln)
    check("F188 a string notes value is joined as one note, not character by character",
          "only round 2 of 3 is complete" in line and "o; n" not in line, line)


def main() -> int:
    test_f48_docs()
    test_f49_round_bound()
    test_f165_f172_location_census()
    test_f166_recorded_dedup()
    test_f167_non_document_parts()
    test_f168_warning_join()
    test_f169_failed_audit_record()
    test_f170_markdown_cells()
    test_f171_temp_failure()
    test_f173_unreadable_reason()
    test_ranking_fixes()
    test_decision_report()
    print()
    print(f"{len(FAILS)} failure(s)" if FAILS else "all fix-bug assertions passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

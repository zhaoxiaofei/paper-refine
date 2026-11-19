#!/usr/bin/env python3
"""Regression tests for fix_bugs wave 2026-11-19, group g5_decision.

One hermetic check block per confirmed candidate:

  F025 readiness must not call a skipped publication submission-ready
  F026 a failed cross-judge audit blocks certification (decide wiring)
  F027 the judge-conflict cache key covers the detector rules
  F028 a partial judge-conflict extraction is refused, and coverage is recorded
  F029 score_model_doc publishes the recorded floor/dedup the ranking used
  F074 the PKG-16 tool-list parser keeps real tools and invents none
  F075 the PKG-23 reference parser accepts bare markers; a parse gap is recorded
  F078 package consistency scans skip code/ and non-submitted declarations
  F079 a training-data parameter selection is not a PKG-17 contradiction
  F080 PKG-18 means are computed over a common dataset set
  F081 an unreadable Zotero scan is a readiness gap under a flatten request
  F085 PKG-26 compares one role across the whole submitted set
  F086 placeholder scans follow the canonical evidence-area symlink
  F087 a sign glued to a word character is part of the value
  F090 a missing census row is missing evidence, never a zero-defect row
  F091 a partial stats row cannot abort champion selection

Run:  python3 .paper_test/test_fix_bugs_20261119_g5_decision.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []
TMPDIRS = []


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_fix_bugs_g5_decision", WS / "paper_pipeline.py")
P12_TEXT = (WS / "paper_pipeline_parts" / "p12_conflicts_decide.py").read_text("utf-8")


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def write_docx(path: Path, paragraphs):
    path.parent.mkdir(parents=True, exist_ok=True)
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(
        '<w:p><w:r><w:t xml:space="preserve">'
        + p.replace("&", "&amp;").replace("<", "&lt;")
        + "</w:t></w:r></w:p>" for p in paragraphs)
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
          'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.'
          'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            'relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document {ns}><w:body>' + body + '</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)


# ---------------------------------------------------------------------------
# F025 -- a skipped publication is never submission-ready
# ---------------------------------------------------------------------------
def test_f025_readiness_skipped_publication():
    skipped = pp.package_readiness({"skipped": "no champion pin exists"}, residuals={})
    check("F025 a skipped publication is NOT submission-ready",
          skipped["submission_ready"] is False
          and skipped["blocking_findings"] == 1
          and skipped["findings"][0]["rule"] == "PUB-1",
          str(skipped.get("findings")))
    check("F025 --require-ready refuses the skipped package",
          bool(pp.readiness_gate_problems(skipped, True)))
    clean = pp.package_readiness({"hygiene": {}}, residuals={})
    check("F025 an empty but published hygiene map is still ready",
          clean["submission_ready"] is True and clean["findings"] == [])


# ---------------------------------------------------------------------------
# F026 -- a failed judge-conflict audit is a certification blocker
# ---------------------------------------------------------------------------
class _FakeCtx:
    def __init__(self, runs, field=("i1", "i2"), reports=None):
        self._runs = list(runs)
        self._field = list(field)
        self.state = {}
        self.root = Path(reports or scratch("g5_f026_reports_"))
        self.reports_dir = self.root
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def runs(self, kind=None, round_no=None):
        return [r for r in self._runs
                if (kind is None or r.get("kind") == kind)
                and (round_no is None or r.get("round") == round_no)]

    def round_rec(self, r):
        return {"field": list(self._field)}

    def round_get(self, r):
        return {}


def _sheet(rid, target, idx, *, label="v1", score=1, opp="i2"):
    return {"id": rid, "kind": "judge", "round": 1, "status": "done",
            "target_id": target, "judge_index": idx,
            "label_map": {"v1": opp},
            "scores": {"comparisons": [{
                "opponent_label": label, "score": score, "basis": "none",
                "resolved": [], "introduced": [], "checks": {}, "reason": ""}]}}


def test_f026_failed_audit_blocks_certification():
    # The deliberate RuntimeError for an empty audit input must still fire...
    ctx = _FakeCtx([_sheet("j1", "i1", 1)], field=())
    try:
        pp.write_round_judge_conflicts(ctx, 1, agg={"field": []},
                                       agent_cmd=None, use_agent=False)
        raised = ""
    except RuntimeError as e:
        raised = str(e)
    check("F026 an empty audit input with done sheets still refuses", "empty audit input" in raised,
          raised)
    # ... and decide must record it as a blocker instead of swallowing it.
    check("F026 decide records the failed audit",
          "judge_conflict_failures.append(_jcf)" in P12_TEXT
          and "the required cross-judge manual checks were NOT produced" in P12_TEXT,
          "decide no longer records the failure")
    check("F026 the failure reaches gate_problems (certification)",
          "for _jcf in judge_conflict_failures:" in P12_TEXT
          and "gate_problems.append(" in P12_TEXT)
    check("F026 decision.json carries judge_conflicts.ok=false",
          '"judge_conflicts": {"ok": not judge_conflict_failures' in P12_TEXT)
    check("F026 the old warning-only handler is gone",
          '# noqa: BLE001\n            print(f"[decide] round {r} WARNING: '
          'judge-conflict audit failed' not in P12_TEXT)


# ---------------------------------------------------------------------------
# F027 -- the cache key covers the detector rules/version
# ---------------------------------------------------------------------------
def test_f027_conflict_fingerprint_covers_rules():
    old_version = pp.VERSION
    try:
        before = pp._judge_conflict_rules_fingerprint()
        pp.VERSION = "0.0.0-fingerprint-test"
        after = pp._judge_conflict_rules_fingerprint()
    finally:
        pp.VERSION = old_version
    check("F027 the detector-rules hash changes with the pipeline version",
          before != after, f"{before[:12]} == {after[:12]}")

    ctx = _FakeCtx([_sheet("j1", "i1", 1), _sheet("j2", "i1", 2)])
    orig_judges, orig_sel = pp.round_judges, pp.judge_selection
    try:
        pp.round_judges = lambda _ctx, _r: 2
        pp.judge_selection = lambda _ctx, _r: set()
        first = pp.write_round_judge_conflicts(ctx, 1, agg={"field": ["i1", "i2"]},
                                               agent_cmd=None, use_agent=False)
        check("F027 the report records the detector and rules hash",
              first.get("detector") == pp.VERSION
              and first.get("rules_fingerprint") == pp._judge_conflict_rules_fingerprint())
        json_path = ctx.reports_dir / "round1_judge_conflicts.json"
        stored = json.loads(json_path.read_text("utf-8"))
        opinions = stored.get("opinions") or []
        stale = json.loads(json_path.read_text("utf-8"))
        # The OLD key: opinions only. A cache entry carrying it must not be reused.
        stale["input_fingerprint"] = pp.hashlib.sha256(
            json.dumps(pp._json_safe(opinions), sort_keys=True,
                       ensure_ascii=False).encode()).hexdigest()[:16]
        stale["marker"] = "STALE-OPINIONS-ONLY-KEY"
        json_path.write_text(json.dumps(stale), "utf-8")
        second = pp.write_round_judge_conflicts(ctx, 1, agg={"field": ["i1", "i2"]},
                                                agent_cmd=None, use_agent=False)
        check("F027 an opinions-only fingerprint is not reused",
              second.get("marker") != "STALE-OPINIONS-ONLY-KEY"
              and second.get("input_fingerprint") == first.get("input_fingerprint"),
              str(second.get("input_fingerprint")))
    finally:
        pp.round_judges, pp.judge_selection = orig_judges, orig_sel


# ---------------------------------------------------------------------------
# F028 -- a partial extraction is counted and refused
# ---------------------------------------------------------------------------
def test_f028_partial_extraction():
    ctx = _FakeCtx([_sheet("j1", "i1", 1),
                    _sheet("j2", "i1", 2, label="vX")])  # vX resolves to nothing
    coverage = {}
    ops = pp.round_judge_opinions(ctx, 1, field=["i1", "i2"], coverage=coverage)
    check("F028 coverage counts the dropped comparison",
          len(ops) == 1 and coverage.get("comparisons_listed") == 2
          and coverage.get("comparisons_extracted") == 1
          and coverage.get("dropped") == {"unresolved_opponent_label": 1}
          and coverage.get("complete") is False, str(coverage))
    try:
        pp.write_round_judge_conflicts(ctx, 1, agg={"field": ["i1", "i2"]},
                                       agent_cmd=None, use_agent=False)
        raised = ""
    except RuntimeError as e:
        raised = str(e)
    check("F028 a partial extraction refuses to write a report",
          "PARTIAL" in raised and "unresolved_opponent_label" in raised, raised)

    # A complete extraction still writes, and records its coverage.
    good = _FakeCtx([_sheet("j1", "i1", 1), _sheet("j2", "i1", 2)])
    orig_judges, orig_sel = pp.round_judges, pp.judge_selection
    try:
        pp.round_judges = lambda _ctx, _r: 2
        pp.judge_selection = lambda _ctx, _r: set()
        data = pp.write_round_judge_conflicts(good, 1, agg={"field": ["i1", "i2"]},
                                              agent_cmd=None, use_agent=False)
    finally:
        pp.round_judges, pp.judge_selection = orig_judges, orig_sel
    check("F028 a complete audit records coverage.complete=true",
          (data.get("coverage") or {}).get("complete") is True
          and (data.get("coverage") or {}).get("comparisons_extracted") == 2,
          str(data.get("coverage")))
    md = pp.judge_conflicts_markdown(data)
    check("F028 the manual-check file states the coverage",
          "Coverage:" in md and "2 of 2" in md, md[:300])


# ---------------------------------------------------------------------------
# F029 -- score_model_doc documents the RECORDED floor/dedup
# ---------------------------------------------------------------------------
class _CfgCtx:
    cfg = {"tiebreak_defect_floor": 10, "dedup_mode": "off"}


def test_f029_score_model_recorded_config():
    ctx = _CfgCtx()
    live = pp.score_model_doc(ctx)
    check("F029 the documentation call still reads the live config",
          live["tiebreak_defect_floor"] == 10 and live["dedup_mode"] == "off")
    recorded = pp.score_model_doc(ctx, floor=3, dedup="location")
    check("F029 an explicit recorded floor/dedup wins",
          recorded["tiebreak_defect_floor"] == 3 and recorded["dedup_mode"] == "location",
          f"{recorded['tiebreak_defect_floor']}/{recorded['dedup_mode']}")
    check("F029 a corrupt recorded floor falls back to the live config",
          pp.score_model_doc(ctx, floor="x")["tiebreak_defect_floor"] == 10)
    check("F029 decide passes the round's recorded values",
          'floor=(final["stored"] or {}).get("tiebreak_defect_floor")' in P12_TEXT
          and 'dedup=(final["stored"] or {}).get("dedup_mode")' in P12_TEXT)


# ---------------------------------------------------------------------------
# F074 -- the PKG-16 tool-list parser
# ---------------------------------------------------------------------------
def test_f074_tool_tokens():
    got = pp._tool_tokens("The following tools were used: bedtools, samtools and STAR")
    check("F074 a normal inventory yields exactly its real tools",
          got == {"bedtools", "samtools", "STAR"}, str(sorted(got)))
    check("F074 a glued version is separated from the tool name",
          pp._tool_tokens("STAR2.7.5c, bedtools and Seurat")
          == {"STAR", "bedtools", "Seurat"},
          str(sorted(pp._tool_tokens("STAR2.7.5c, bedtools and Seurat"))))


# ---------------------------------------------------------------------------
# F075 -- the PKG-23 reference parser and its coverage gap
# ---------------------------------------------------------------------------
def test_f075_reference_markers_and_gap():
    refs = pp._numbered_reference_titles(
        ["References", "1)", "Nurk S. Telomere-to-telomere assembly.", "Science 2022."])
    check("F075 a bare '1)' marker line starts a reference entry",
          refs == {1: "Nurk S. Telomere-to-telomere assembly."}, str(refs))
    refs_bare = pp._numbered_reference_titles(
        ["References", "1", "Nurk S. Telomere-to-telomere assembly."])
    check("F075 a bare number marker line starts a reference entry",
          refs_bare == {1: "Nurk S. Telomere-to-telomere assembly."}, str(refs_bare))
    refs_bracket = pp._numbered_reference_titles(
        ["References", "[43] Nurk S. Telomere-to-telomere assembly. Science 2022."])
    check("F075 the bracketed one-line form still parses", refs_bracket.get(43) is not None)

    root = scratch("g5_f075_")
    write_docx(root / "ms-2-mainText-aaaaaaa.docx",
               ["References", "Nurk S. et al. Telomere-to-telomere assembly. Science 2022."])
    rows = pp.scan_single_cell_citation_mismatch(root)
    check("F075 an unparseable references heading records a coverage gap",
          len(rows) == 1 and rows[0].get("coverage_gap") is True
          and rows[0].get("rule") == "PKG-23", str(rows))
    ready = pp.package_readiness(
        {"hygiene": {"package_consistency": {"single_cell_citation_mismatch": rows}}})
    check("F075 the coverage gap is advisory, never a fabricated defect",
          ready["submission_ready"] is True
          and ready["findings"][0].get("detail"), str(ready["findings"]))


# ---------------------------------------------------------------------------
# F078 -- code/ and declared non-submitted files are not prose surfaces
# ---------------------------------------------------------------------------
def test_f078_package_document_surfaces():
    root = scratch("g5_f078_")
    (root / "main.md").write_text("the manuscript body\n", "utf-8")
    (root / "extra.md").write_text("an undeclared note\n", "utf-8")
    (root / "code").mkdir()
    (root / "code" / "notes.md").write_text("code notes that look like prose\n", "utf-8")
    (root / "raw_data").mkdir()
    (root / "raw_data" / "evidence.md").write_text("evidence\n", "utf-8")
    (root / "README.md").write_text("Only `main*.md` will be submitted.\n", "utf-8")
    docs = [rel for rel, _p, _t in pp._package_document_texts(root)]
    check("F078 code/ is not a manuscript surface", "code/notes.md" not in docs, str(docs))
    check("F078 raw_data/ is not a manuscript surface", "raw_data/evidence.md" not in docs)
    check("F078 the declared submitted set filters undeclared documents",
          docs == ["main.md"], str(docs))
    decl = pp.declared_submission_set(root)
    check("F078 the declaration is honoured from the author's README",
          decl.get("declared") is True and decl.get("files") == ["main.md"], str(decl))


# ---------------------------------------------------------------------------
# F079 -- training-data parameter selection is not a PKG-17 contradiction
# ---------------------------------------------------------------------------
def test_f079_training_selection():
    root = scratch("g5_f079_")
    (root / "ms-4-reporting-summary-abcdef0.md").write_text(
        "There was no overlap between parameter selection and evaluation; thresholds were "
        "fixed before the final performance metrics were inspected.\n", "utf-8")
    (root / "ms-2-mainText-abcdef0.md").write_text(
        "The parameters were selected on the training datasets before evaluation.\n", "utf-8")
    check("F079 selection on the TRAINING data is the compliant case",
          pp.scan_form_method_conflicts(root) == [], str(pp.scan_form_method_conflicts(root)))
    (root / "ms-2-mainText-abcdef0.md").write_text(
        "The 85% threshold was selected empirically to match manual karyotyping on the "
        "cell-line datasets and held fixed.\n", "utf-8")
    rows = pp.scan_form_method_conflicts(root)
    check("F079 an empirical selection on the evaluation data still flags",
          len(rows) == 1 and rows[0]["rule"] == "PKG-17", str(rows))


# ---------------------------------------------------------------------------
# F080 -- PKG-18 means over a common dataset set
# ---------------------------------------------------------------------------
def test_f080_common_dataset_means():
    root = scratch("g5_f080_")
    (root / "raw_data").mkdir()
    lines = ["dataset\tmethod\tmetric\tmean"]
    for i in range(1, 10):
        lines.append(f"d{i}\tother\tTumor_normal_ROC_AUC\t0.60")
    lines.append("d10\tother\tTumor_normal_ROC_AUC\t0.90")
    lines.append("d10\teasy\tTumor_normal_ROC_AUC\t0.85")
    (root / "raw_data" / "fig5_grid.tsv").write_text("\n".join(lines) + "\n", "utf-8")
    (root / "ms.md").write_text(
        "Other gave the highest average ROC-AUC on the tumor/normal classification.\n", "utf-8")
    check("F080 a method measured on one easy dataset does not flip a correct claim",
          pp.scan_ranking_claim_conflicts(root) == [],
          str(pp.scan_ranking_claim_conflicts(root)))
    (root / "ms.md").write_text(
        "Easy gave the highest average ROC-AUC on the tumor/normal classification.\n", "utf-8")
    rows = pp.scan_ranking_claim_conflicts(root)
    check("F080 a real contradiction on the common datasets still flags",
          len(rows) == 1 and "0.900" in rows[0]["detail"], str(rows))


# ---------------------------------------------------------------------------
# F081 -- an unreadable Zotero scan is a readiness gap under a flatten request
# ---------------------------------------------------------------------------
def test_f081_zotero_scan_gap():
    fc = {"hygiene": {"zotero_unlinked": {"requested": True},
                      "zotero_scan_gaps": [{"file": "main.docx",
                                            "error": "ValueError: unreadable"}]}}
    ready = pp.package_readiness(fc)
    check("F081 an unreadable Zotero scan is blocking under a flatten request",
          ready["submission_ready"] is False
          and any(f.get("rule") == "FMT-Z7" and "UNKNOWN" in str(f.get("detail"))
                  for f in ready["findings"]), str(ready["findings"]))
    fc2 = {"hygiene": {"zotero_unlinked": {"requested": False},
                       "zotero_scan_gaps": [{"file": "main.docx",
                                             "error": "ValueError: unreadable"}]}}
    check("F081 the gap does not gate when no flatten was requested",
          pp.package_readiness(fc2)["submission_ready"] is True)
    check("F081 publication records the scan failure",
          'zotero_scan_gaps[q.name]' in P12_TEXT
          and 'hygiene["zotero_scan_gaps"]' in P12_TEXT)


# ---------------------------------------------------------------------------
# F085 -- PKG-26 compares one role across the whole submitted set
# ---------------------------------------------------------------------------
def test_f085_duplicate_role_across_directories():
    root = scratch("g5_f085_")
    write_docx(root / "ms-2-mainText-aaaaaaa.docx", ["current main text"])
    write_docx(root / "supplementary" / "ms-2-mainText-bbbbbbb.docx", ["stale copy"])
    rows = pp.duplicate_submission_role_rows(root)
    check("F085 a stale same-role copy in another directory is reported",
          len(rows) == 1 and rows[0]["rule"] == "PKG-26"
          and "ms-2-mainText-aaaaaaa.docx" in rows[0]["detail"]
          and "supplementary/ms-2-mainText-bbbbbbb.docx" in rows[0]["detail"], str(rows))


# ---------------------------------------------------------------------------
# F086 -- placeholder scans follow the canonical evidence-area symlink
# ---------------------------------------------------------------------------
def test_f086_placeholder_symlink():
    base = scratch("g5_f086_")
    pkg = base / "pkg"
    pkg.mkdir()
    (base / "non_revised" / "raw_data").mkdir(parents=True)
    (base / "non_revised" / "raw_data" / "donorA_hap.txt").write_text("AAAA", "utf-8")
    (base / "non_revised" / "raw_data" / "donorB_phased.txt").write_text("AAAA", "utf-8")
    (pkg / "raw_data").symlink_to(base / "non_revised" / "raw_data")
    (pkg / "README.md").write_text(
        "Placeholder files: `raw_data/donorA_hap.txt`\n", "utf-8")
    decl = pp.declared_placeholder_paths(pkg)
    check("F086 a declared placeholder under the symlinked area is found",
          decl.get("files") == ["raw_data/donorA_hap.txt"], str(decl))
    copies = pp.detect_placeholder_copies(pkg, ["raw_data"])
    check("F086 identical-byte placeholder copies under the symlink are found",
          len(copies) == 1 and copies[0]["duplicates"] == "raw_data/donorA_hap.txt",
          str(copies))


# ---------------------------------------------------------------------------
# F087 -- the sign is part of the value even when glued to a word character
# ---------------------------------------------------------------------------
def test_f087_signed_numbers():
    check("F087 a Unicode minus glued to a word character keeps its sign",
          pp._conflict_numbers("x\u221212") == {-12},
          str(pp._conflict_numbers("x\u221212")))
    check("F087 an en-dash value keeps its sign",
          pp._conflict_numbers("value\u201312") == {-12},
          str(pp._conflict_numbers("value\u201312")))
    check("F087 -12 and 12 remain different number sets",
          pp._conflict_numbers("x\u221212") != pp._conflict_numbers("x12"))
    check("F087 identifiers are still not numbers",
          pp._conflict_numbers("M4 and Fig. 3d") == set())


# ---------------------------------------------------------------------------
# F090/F091 -- the pure ranking core's missing-evidence handling
# ---------------------------------------------------------------------------
def _stat(median=1.0, digest="a" * 40):
    return {"n": 3, "expected_n": 3, "complete": True, "vs_original_complete": True,
            "anti_regression_ok": True, "median": median, "mean": median, "iqr": 0.0,
            "digest": digest, "vs_original": 0.0, "vs_base": 0.0}


def _census_row(sev="fatal", tier="correctness", source="own", n=1):
    row = {"tiers": {t: {"severities": {s: {"own": 0, "peer": 0}
                                       for s in ("fatal", "critical", "major", "minor")}}
                     for t in pp.BASIS_TIERS}}
    row["tiers"][tier]["severities"][sev][source] = n
    return row


def test_f090_missing_census_row():
    stats = {"w1": _stat(), "w2": _stat()}
    census = {"w1": _census_row()}
    sel = pp.derive_ranking(stats, ["w1", "w2"], None, census, 10, 2)
    row2 = next(r for r in sel["ranking"] if r["id"] == "w2")
    check("F090 a version with no census row cannot beat a fatal-defect version",
          sel["champion"] == "w1", f"champion={sel['champion']}")
    check("F090 its ordered census is missing evidence, not a zero row",
          row2.get("defect_prefix_census") is None
          and pp.champion_sort_key(row2)[0] == 10 ** 9,
          str(row2.get("defect_prefix_census")))
    # A genuine all-zero census row still ranks ahead of a defect: the fix must
    # distinguish "no row" from "clean row".
    sel2 = pp.derive_ranking({"w1": _stat(), "w2": _stat()}, ["w1", "w2"], None,
                             {"w1": _census_row(), "w2": _census_row(n=0)}, 10, 2)
    check("F090 a genuine all-zero census row still wins", sel2["champion"] == "w2",
          str(sel2["champion"]))


def test_f091_partial_stats_row():
    stats = {"w1": _stat()}
    del stats["w1"]["vs_base"]
    try:
        sel = pp.derive_ranking(stats, ["w1"], None, {}, 10, 2)
        raised = ""
    except Exception as e:                                            # noqa: BLE001
        sel, raised = {}, f"{type(e).__name__}: {e}"
    check("F091 a missing reported statistic does not abort champion selection",
          not raised and sel.get("champion") == "w1", raised)
    stats2 = {"w1": _stat()}
    del stats2["w1"]["median"]
    try:
        sel2 = pp.derive_ranking(stats2, ["w1"], None, {}, 10, 2)
        raised = ""
    except Exception as e:                                            # noqa: BLE001
        sel2, raised = {}, f"{type(e).__name__}: {e}"
    check("F091 a missing ranking statistic makes the row ineligible, not a crash",
          not raised and sel2.get("champion") == "a1"
          and any("missing panel statistic" in ln for ln in sel2.get("trace") or []),
          raised or str(sel2.get("trace")))


def main() -> int:
    test_f025_readiness_skipped_publication()
    test_f026_failed_audit_blocks_certification()
    test_f027_conflict_fingerprint_covers_rules()
    test_f028_partial_extraction()
    test_f029_score_model_recorded_config()
    test_f074_tool_tokens()
    test_f075_reference_markers_and_gap()
    test_f078_package_document_surfaces()
    test_f079_training_selection()
    test_f080_common_dataset_means()
    test_f081_zotero_scan_gap()
    test_f085_duplicate_role_across_directories()
    test_f086_placeholder_symlink()
    test_f087_signed_numbers()
    test_f090_missing_census_row()
    test_f091_partial_stats_row()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL g5_decision FIX-BUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        cleanup()
    sys.exit(rc)

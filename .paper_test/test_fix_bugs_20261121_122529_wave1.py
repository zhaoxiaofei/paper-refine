#!/usr/bin/env python3
"""Regression tests for the 2026-11-21 12:25 fix-bugs wave 1.

One hermetic block per confirmed candidate that can be exercised without a
model backend or Word.  Each check fails on the pre-fix tree and passes here.

Run:  python3 .paper_test/test_fix_bugs_20261121_122529_wave1.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import stat
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(WS))

import docx  # noqa: E402
import paper_docx_format as df  # noqa: E402
import paper_pipeline as pp  # noqa: E402

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def cleanup():
    import shutil
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# OOXML text/token readers: legal end-tag whitespace, comments, hidden text
# ---------------------------------------------------------------------------
def test_docx_readers() -> None:
    print("\n== DOCX readers: end-tag whitespace, hidden text, comments ==")
    frag = '<w:p><w:r><w:t>Alpha Beta</w:t ></w:r></w:p>'
    check("F026 a legal `</w:t >` end tag still yields the visible text",
          df.text_of(frag) == "Alpha Beta", repr(df.text_of(frag)))
    check("F026 the split-run case does not leak markup",
          df.text_of('<w:p><w:r><w:t>Alpha</w:t ></w:r>'
                     '<w:r><w:t>Beta</w:t></w:r></w:p>') == "AlphaBeta")

    zfield = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
              '<w:r><w:instrText xml:space="preserve">ADDIN ZOTERO_ITEM '
              'CSL_CITATION {"citationID":"abc123","properties":{}}'
              '</w:instrText ></w:r>'
              '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
              '<w:r><w:t>(Smith, 2020)</w:t ></w:r>'
              '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    zrep = df.zotero_field_report(zfield)
    zf = zrep["fields"][0] if zrep.get("fields") else {}
    check("R01 a complex Zotero field survives legal end-tag whitespace",
          zf.get("kind") == "item" and "citationID" in (zf.get("instr") or ""), str(zf))
    check("R01 the whitespace-closed result keeps its visible text",
          zf.get("visible_text") == "(Smith, 2020)", repr(zf.get("visible_text")))

    xml = ('<w:body><w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl >'
           '<w:p><w:r><w:t>After</w:t></w:r></w:p></w:body>')
    spans = df.container_spans(xml)
    check("F033 `</w:tbl >` closes the container (no run to EOF)",
          bool(spans) and spans[0][1] < len(xml), str(spans))
    check("F027 `_table_spans` matches the legal close tag", bool(df._table_spans(xml)))
    check("F027 a commented-out `<w:tbl>` is not a live container",
          df._table_spans('<w:body><!-- <w:tbl> --><w:p/></w:body>') == [])

    hidden = ('<w:p><w:r><w:t>Visible</w:t></w:r>'
              '<w:r><w:rPr><w:vanish/></w:rPr><w:t>HiddenSecret</w:t></w:r></w:p>')
    check("F032 hidden (`w:vanish`) text is not manuscript text",
          df.text_of(hidden) == "Visible", repr(df.text_of(hidden)))
    check("F032 `w:vanish w:val='0'` stays visible",
          df.text_of('<w:p><w:r><w:rPr><w:vanish w:val="0"/></w:rPr>'
                     '<w:t>Shown</w:t></w:r></w:p>') == "Shown")
    check("F036 a commented-out drawing is not live content",
          df.has_drawing("<!-- <w:drawing/> -->") is False)
    check("F036 a commented-out equation is not live content",
          df.has_math("<!-- <m:oMath/> -->") is False)


def test_docx_attributes() -> None:
    print("\n== DOCX attributes: both legal quote styles ==")
    single = "<w:r><w:rPr><w:i w:val='0'/></w:rPr><w:t>x</w:t></w:r>"
    check("F096 a single-quoted `w:i w:val='0'` is OFF",
          df.run_is_italic({}, None, single) is False)
    check("F096 a single-quoted `w:b w:val='0'` is OFF",
          df.run_is_bold({}, None, single.replace("<w:i", "<w:b")) is False)

    z = scratch("attrstyles_") / "styles.docx"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as pkg:
        pkg.writestr("[Content_Types].xml",
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        pkg.writestr("word/styles.xml",
                     '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                     "<w:style w:styleId='Heading1'><w:name w:val='heading 1'/></w:style>"
                     "</w:styles>")
    check("F097 a single-quoted `w:styleId` is enumerated",
          df.docx_style_ids(z) == ["Heading1"], str(df.docx_style_ids(z)))

    t = scratch("attrtpl_") / "template.docx"
    with zipfile.ZipFile(t, "w", zipfile.ZIP_DEFLATED) as pkg:
        pkg.writestr("[Content_Types].xml",
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        pkg.writestr("word/document.xml",
                     '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                     "<w:body><w:sectPr><w:headerReference w:type='even' r:id='rId9'/>"
                     "</w:sectPr></w:body></w:document>")
    check("F101 a single-quoted `w:type='even'` reference is detected",
          df._template_uses_even_odd(t) is True)


def test_docx_package_guards() -> None:
    print("\n== DOCX package guards ==")
    d = scratch("dupmember_")
    src = d / "in.docx"
    doc = docx.Document()
    doc.add_paragraph("FIRST")
    doc.save(src)
    with zipfile.ZipFile(src) as pkg:
        names = pkg.namelist()
        parts = {n: pkg.read(n) for n in names}
    dup = d / "dup.docx"
    with zipfile.ZipFile(dup, "w", zipfile.ZIP_DEFLATED) as out:
        for n in names:
            out.writestr(n, parts[n])
            if n == "word/document.xml":
                out.writestr(n, parts[n].replace(b"FIRST", b"SECOND"))
    res = df.fix_package(dup, d / "out.docx", dict(df.POLICY_DEFAULTS))
    check("F029 a duplicate zip member is refused, not silently collapsed",
          res.get("ok") is False and "repeats member" in str(res.get("error")),
          str(res.get("error"))[:120])
    check("F029 no output package is published for an ambiguous archive",
          not (d / "out.docx").exists())

    row = ("<w:tr><w:tc><w:tcPr><w:tcW w:w='100' w:type='dxa'/>"
           "<w:gridSpan w:val='2'/></w:tcPr><w:p/></w:tc></w:tr>")
    widths = df._table_cell_widths(row)
    check("F040 a single-quoted `w:gridSpan` is read as span 2",
          widths and widths[0][1] == 2, str(widths))


def test_bib_reader() -> None:
    print("\n== .bib sibling read ==")
    d = scratch("bib_")
    real = d / "refs.bib"
    real.write_text("@article{k, title={T}, year={2020}}", encoding="utf-8")
    check("F037 a real .bib is read",
          "title={T}" in (df._read_bib_bounded(real) or ""))
    link = d / "secret.bib"
    outside = d / "outside.txt"
    outside.write_text("SECRET", encoding="utf-8")
    link.symlink_to(outside)
    check("F037 a symlinked .bib is refused", df._read_bib_bounded(link) is None)


# ---------------------------------------------------------------------------
# Pipeline: conflict audit, ranking, removal accounting, gates
# ---------------------------------------------------------------------------
def test_copy_manifest_parity() -> None:
    print("\n== corpus copy and manifest agree ==")
    src = scratch("copyparity_") / "src"
    src.mkdir()
    (src / "paper.md").write_text("x", encoding="utf-8")
    (src / "notes.tracking-a1.docx").mkdir()
    (src / "notes.tracking-a1.docx" / "x.txt").write_text("y", encoding="utf-8")
    dst = src.parent / "dst"
    pp.copy_into(src, dst, skip_aux=True, strip_bookkeeping=True)
    manifest = pp.manifest_for_sources([(src, "", ())])
    check("F062 an auxiliary-looking DIRECTORY is both copied and manifested",
          sorted((dst / "notes.tracking-a1.docx").glob("*.txt"))
          and "notes.tracking-a1.docx/x.txt" in manifest["files"],
          str(sorted(manifest["files"])))
    check("F062 the copied corpus digest equals the manifest digest",
          pp.manifest_digest(manifest)
          == pp.manifest_digest(pp.corpus_dir_manifest(dst)))


def test_bounded_tracking_read() -> None:
    print("\n== difference-tracking text read ==")
    d = scratch("trackingread_")
    base = d / "base.tex"
    base.write_text("\\documentclass{article}\n", encoding="utf-8")
    cand = d / "cand.tex"
    cand.write_text("A" * (pp.PACKAGE_TEXT_BYTES_LIMIT + 10), encoding="utf-8")
    out = d / "cand.logging-base.tex"
    pp.write_text_logging_fallback(base, cand, out, "base", "simulated failure")
    text = out.read_text(encoding="utf-8")
    check("F021 an over-budget tracking file is reported unreadable, not loaded",
          "[unreadable:" in text, text[:140])


def test_run_glob_escape() -> None:
    print("\n== run-id glob escape ==")
    runs = scratch("runglob_") / "runs"
    (runs / "victim_try1_failed").mkdir(parents=True)
    (runs / "victim_try2_failed").mkdir()

    class Ctx:
        runs_dir = runs

    dest = pp.failed_sandbox_dir(Ctx(), {"id": "*"})
    check("F060 a glob metacharacter in the run id matches no other run",
          dest.name == "*_try1_failed", dest.name)


def test_abstained_opinions() -> None:
    print("\n== abstained judge comparisons ==")

    class Ctx:
        def round_rec(self, r):
            return {"field": ["orig", "w1", "w2"]}

        def runs(self, kind=None, round_no=None):
            return [{"id": "j1", "kind": "judge", "round": 1, "status": "done",
                     "target_id": "orig", "judge_index": 1,
                     "label_map": {"w1": "w1", "w2": "w2"},
                     "scores": {"comparisons": [
                         {"opponent_label": "w1", "score": 0,
                          "checks": {"M1": "unable"}, "introduced": []},
                         {"opponent_label": "w2", "score": 2,
                          "checks": {"M1": "clean"}, "introduced": []}]}}]

    old_r, old_s = pp.round_judges, pp.judge_selection
    pp.round_judges = lambda ctx, r: 1
    pp.judge_selection = lambda ctx, r: None
    try:
        coverage = {}
        ops = pp.round_judge_opinions(Ctx(), 1, field=["orig", "w1", "w2"],
                                      coverage=coverage)
    finally:
        pp.round_judges, pp.judge_selection = old_r, old_s
    check("F002 an abstention is not copied into the opinions",
          [(o["target"], o["opponent"]) for o in ops] == [("orig", "w2")], str(ops))
    check("F002 the coverage claim is not complete when a comparison abstained",
          coverage.get("abstained") == 1 and coverage.get("complete") is False,
          str(coverage))


def test_conflict_numbers() -> None:
    print("\n== judge-conflict number parsing ==")
    check("F006 a hyphenated range is its two positive bounds",
          pp._conflict_numbers("10-12") == {10, 12}, str(pp._conflict_numbers("10-12")))
    check("F006 `10 to 12` still agrees with `10-12`",
          pp._conflict_numbers("10 to 12") == pp._conflict_numbers("10-12"))
    check("F006 an en-dash range is positive too",
          pp._conflict_numbers("1,307\u20131,309") == {1307, 1309})
    check("F006 a real negative after a word keeps its sign",
          pp._conflict_numbers("x\u221212") == {-12})


def test_final_clean_reason() -> None:
    print("\n== final_clean_version reason ==")
    reason = pp.final_clean_reason(
        {"round": 2}, [{"round": 2, "mismatch": None}], 2, None, True, True,
        {"2": ["a judge sheet is missing"]}, ["round 2: a named gate blocker"])
    check("F011 named gate blockers are not hidden behind the panel-gap sentence",
          "named gate blocker" in reason and "panel is incomplete" in reason, reason)


def test_coverage_gate() -> None:
    print("\n== review coverage dispositions ==")
    check("F014 `clean -- basis: the sweep did not run` is refused",
          pp._coverage_disposition_ok("clean -- basis: the sweep did not run") is False)
    check("F014 `Basis: the check was never performed` is refused",
          pp._coverage_row_disposition_ok(
              {"disposition": "clean",
               "detail": "Basis: the check was never performed"}) is False)
    check("F014 a named basis still passes",
          pp._coverage_disposition_ok("clean -- basis: artifacts/M1.md") is True)
    check("F014 `unable -- could not run` stays a legitimate inability",
          pp._coverage_disposition_ok("unable -- the renderer could not run") is True)


def test_removal_accounting() -> None:
    print("\n== removal accounting: polarity and post-posed denial ==")
    def unit(text):
        return {"text": text, "norm": text.lower().strip(),
                "tokens": text.lower().replace(".", "").split(), "document": "a.md"}

    base = [unit("The treatment was effective in the cohort.")]
    cand = [unit("The treatment failed to be effective in the cohort.")]
    check("F015 a reversed claim is not contained",
          pp._content_unit_contained(base[0], cand) is False)
    check("F015 the reversed claim is reported as missing",
          [u["text"] for u in pp.soft_deletion_missing_units(base, cand)]
          == [base[0]["text"]])
    check("F015 a genuine merge is still contained",
          pp._content_unit_contained(base[0],
                                     [unit("The treatment was effective in this cohort.")]) is True)

    for reason in ("OK \u2014 moving to Methods was not possible",
                   "OK \u2014 merging into Results could not be done"):
        check(f"F016 post-posed denial refused: {reason!r}",
              pp._deletion_disposition_ok(reason) is False)
    check("F016 `OK \u2014 moved to Methods` stays a real closure",
          pp._deletion_disposition_ok("OK \u2014 moved to Methods") is True)
    check("F016 `not only moved but also merged` stays additive",
          pp._reason_denies_movement("not only moved but also merged") is False)


def test_cover_letter_gate() -> None:
    print("\n== FMT-CL1 cover-letter gate ==")
    problems = pp.disposition_artifact_problems(
        [{"rule": "FMT-CL1", "location": "p1",
          "disposition": "As is -- the letter follows the manuscript template's styles"}])
    check("F018 `As is` is treated as an OK closure and needs the override",
          any("quotes no journal override" in p for p in problems), str(problems)[:120])
    check("F018 a real remediation is not an OK closure",
          pp.disposition_artifact_problems(
              [{"rule": "FMT-CL1", "location": "p1",
                "disposition": "fixed in revision"}]) == [])


def test_census_opportunities() -> None:
    print("\n== issue-census opportunities ==")
    def comp(ev):
        return {"opponent_label": "v1", "score": 1, "reason": "x", "resolved": [],
                "introduced": [{"check": "M1", "tier": "consistency", "severity": "minor",
                                "evidence": ev}], "checks": {}}
    obs = []
    for session in ("j1", "j2"):
        for opp, ev in (("w1", "line 1: alpha beta gamma delta"),
                        ("w2", "line 2: epsilon zeta eta theta")):
            obs.append((session, "a1", opp, comp(ev)))
    census = pp.build_issue_census(obs, ["a1", "w1", "w2"], sessions_expected=2)
    c = census["a1"]
    sev = c["tiers"]["consistency"]["severities"]["minor"]
    check("F004 the denominator counts (session, opponent) opportunities",
          c["own_opps"] == 4, str(c["own_opps"]))
    check("F004 own_rate no longer exceeds one for one row per comparison",
          sev["own"] == 4 and abs(sev["own_rate"] - 1.0) < 1e-9, str(sev))


def test_ranking_representative() -> None:
    print("\n== ranking a deduplicated fresh candidate ==")
    def stat(**kw):
        d = {"n": 4, "expected_n": 4, "complete": True, "median": 1.0, "mean": 1.0,
             "iqr": 0.5, "vs_original_complete": True, "vs_original_n": 2,
             "vs_original_expected": 2, "anti_regression_ok": True, "digest": "d",
             "is_base": False, "judges_seen": 2, "judges_expected": 2,
             "author_placeholders": 0, "caption_gate_ok": True, "caption_note": "",
             "captions": []}
        d.update(kw)
        return d
    stats = {"orig": stat(digest="dorig"), "r1_pin": stat(digest="d1", median=2.0),
             "r2_pin": stat(digest="d2", is_base=True, median=1.0),
             "a2": stat(digest="d2b")}
    sel = pp.derive_ranking(stats, ["w1"], "r2_pin", {}, 0, 2,
                            representatives={"w1": "r1_pin"})
    check("F005 a candidate deduplicated into a pin stays eligible",
          "w1" in sel["eligible"], str(sel["eligible"]))
    check("F005 the representative's row carries the candidate",
          any(r["id"] == "w1" and r["rep"] == "r1_pin" for r in sel["ranking"]),
          str([(r["id"], r["rep"]) for r in sel["ranking"]]))
    check("F005 that content can win", sel["champion"] == "w1", sel["champion"])


def test_defect_audit_off() -> None:
    print("\n== --no-defect-audit cleanup ==")
    root = scratch("auditoff_") / "root"
    reports = root / "reports"
    reports.mkdir(parents=True)
    stale = reports / "round1_auditedTP_defects.csv"
    stale.write_text("stale\n", encoding="utf-8")

    class Ctx:
        def __init__(self, root):
            self.root = root
            self.reports_dir = root / "reports"

        def round_rec(self, r):
            return {}

        def runs(self, **kw):
            return []

    real = pp.defect_list_rows
    pp.defect_list_rows = lambda ctx, r, agg: [{"defect_id": "D1"}]
    try:
        res = pp.write_round_defect_audit(
            Ctx(root), 1, agg={"issue_rows": [{"x": 1}], "field": []}, use_agent=False)
    finally:
        pp.defect_list_rows = real
    check("F020 the disabled audit removes the stale TP-only family",
          not stale.exists(), str(stale))
    meta = json.loads((reports / "round1_defect_audit.json").read_text(encoding="utf-8"))
    check("F020 the disabled audit records itself as off",
          meta.get("audit") == "off" and meta.get("ok") is False, str(meta))
    check("F020 the result names the removal", res.get("removed"), str(res))

    # R02: an explicit --no-defect-audit with an EMPTY defect list must still
    # remove the previous success's family and record the disabled state.
    meta_path = reports / "round1_defect_audit.json"
    meta_path.unlink()
    stale.write_text("stale\n", encoding="utf-8")
    pp.defect_list_rows = lambda ctx, r, agg: []
    try:
        res_empty = pp.write_round_defect_audit(
            Ctx(root), 1, agg={"issue_rows": [], "field": []}, use_agent=False)
    finally:
        pp.defect_list_rows = real
    check("R02 a zero-row disabled audit removes the stale TP-only family",
          not stale.exists(), str(stale))
    check("R02 a zero-row disabled audit records itself as off",
          meta_path.exists()
          and json.loads(meta_path.read_text(encoding="utf-8")).get("audit") == "off",
          meta_path.read_text(encoding="utf-8") if meta_path.exists() else "missing")
    check("R02 the zero-row result is the disabled one, not 'no defect rows'",
          res_empty.get("rows") == 0
          and res_empty.get("reason") == "the LLM defect audit is off", str(res_empty))


def test_visual_template_gate() -> None:
    print("\n== venue-template visual gate ==")
    sb = scratch("visual_") / "sandbox"
    (sb / "venue_template" / "word").mkdir(parents=True)
    (sb / "venue_template" / "word" / "template.docx").write_bytes(b"x")
    (sb / pp.VISUAL_TEMPLATE_DIR).mkdir(parents=True)
    (sb / pp.VISUAL_TEMPLATE_DIR / "manifest.json").write_text(json.dumps({
        "renderer": "word",
        "documents": [{"role": "journal", "source": "template.docx", "pdf": "journal.pdf",
                       "pages": 3, "ok": True}]}), encoding="utf-8")
    art = sb / "visual.md"
    art.write_text("template.docx was compared with the template over 3 pages.\n",
                   encoding="utf-8")
    errs, warns = [], []
    pp.check_visual_artifact(art, "visual.md", errs, warns, sandbox=sb)
    check("F022 a successful manifest whose render PDF is missing is refused",
          any("PDF is missing" in e for e in errs), str(errs)[:160])


def test_atomic_secret_mode() -> None:
    print("\n== secret-bearing atomic write ==")
    d = scratch("mode_")
    seen = []

    def write(f):
        seen.append(stat.S_IMODE(os.fstat(f.fileno()).st_mode))
        f.write("x")

    pp._atomic_write_bytes(pp.tmp_path_for(d / "state.json"), d / "state.json", write,
                           mode=0o600)
    check("F059 the temp is 0600 BEFORE the payload is written",
          seen == [0o600], str([oct(x) for x in seen]))
    check("F059 the published registry is 0600",
          stat.S_IMODE((d / "state.json").stat().st_mode) == 0o600)


def test_safe_mkdir_and_compact() -> None:
    print("\n== output-dir containment and state compaction ==")
    d = scratch("safe_")
    sb = d / "sb"
    sb.mkdir()
    outside = d / "outside"
    outside.mkdir()
    (sb / "revised").symlink_to(outside, target_is_directory=True)
    refused = False
    try:
        pp.safe_mkdir(sb / "revised")
    except SystemExit:
        refused = True
    check("F061 mkdir through a planted symlink is refused", refused)
    check("F061 the outside directory was not written",
          list(outside.iterdir()) == [])

    root = d / "root"
    st = {"runs": {"r1": {"id": "r1", "sandbox": "runs/r1",
                          "judge_evidence": {"label": "x", "format": {"rows": [1]}}}}}
    check("F063 a payload with no artifact on disk is NOT compacted",
          pp.compact_state(st, root) == 0
          and st["runs"]["r1"]["judge_evidence"].get("compacted") is None)
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "judge_evidence_r1.json").write_text("{}", encoding="utf-8")
    check("F063 a payload with its artifact IS compacted",
          pp.compact_state(st, root) > 0
          and st["runs"]["r1"]["judge_evidence"].get("compacted") is True)


def test_state_reader() -> None:
    print("\n== deeply nested state.json ==")
    p = scratch("state_") / "state.json"
    p.write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")
    data, problem = pp.load_state_file(p)
    check("F066 a deeply nested registry returns the documented problem string",
          data is None and "not valid JSON" in problem, str(problem)[:80])


def test_required_assets() -> None:
    print("\n== setup bundle preflight ==")
    required = set(pp.PIPELINE_REQUIRED_ASSET_FILES)
    wanted = {
        "paper-skills/paper-review/SKILL.md",
        "paper-skills/paper-review/references/sweeps.md",
        "paper-skills/paper-review/references/discovery.md",
        "paper-skills/paper-revise/SKILL.md",
        "paper-skills/paper-revise/references/edit_rules.md",
        "paper-skills/paper-revise/scripts/revision_token.py",
    }
    check("F073 the preflight names the skill assets the prompts read/run",
          wanted <= required, str(sorted(wanted - required)))
    check("F073 every named asset exists in this checkout",
          all((WS / name).is_file() for name in wanted))


def test_csv_formula() -> None:
    print("\n== CSV formula neutralisation ==")
    d = scratch("csv_")
    p = pp.write_csv_atomic(d / "r.csv", ["version", "evidence"],
                            [{"version": "w1",
                              "evidence": '=HYPERLINK("http://evil","click")'},
                             {"version": 2, "evidence": -12}])
    text = p.read_text(encoding="utf-8")
    check("F087 a string formula cell is neutralised", "'=HYPERLINK" in text, text)
    check("F087 a numeric negative value stays a number", ",-12" in text, text)


def test_pkg9_table_only_tool() -> None:
    print("\n== PKG-9: a tool named only in a table ==")
    root = scratch("pkg9_")
    doc = docx.Document()
    doc.add_paragraph("The scores are reported as percentiles in the table.")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Affinity (IC50)"
    table.cell(0, 1).text = "(MixMHCpred)"
    doc.save(root / "manuscript.docx")
    rows = pp.affinity_definition_rows(root)
    check("F091 a tool absent from the prose is reported as unsupported",
          any(r.get("rule") == "PKG-9" for r in rows), str(rows)[:180])


def test_pdf_summary() -> None:
    print("\n== pdf summary rounds=[] ==")
    manifest = {"sets": [
        {"label": "a", "round": 1, "documents": [{"ok": True, "rel": "a", "out": "a"}]},
        {"label": "b", "round": 2, "documents": [{"ok": True, "rel": "b", "out": "b"}]},
    ]}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pp.pdf_summary(manifest, rounds=[])
    check("F024 an explicit empty round list summarises no PDF",
          "0 PDF(s)" in buf.getvalue(), buf.getvalue()[:80])


def test_bounded_docx_part() -> None:
    print("\n== forged DOCX part size ==")
    d = scratch("forged_")
    p = d / "forged.zip"
    data = b"A" * (32 * 1024 * 1024)
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", data)
    raw = bytearray(p.read_bytes())
    central = raw.find(b"PK\x01\x02")
    local = raw.find(b"PK\x03\x04")
    struct.pack_into("<I", raw, local + 22, 10)       # declared local size
    struct.pack_into("<I", raw, central + 24, 10)     # declared central size
    crc = zlib.crc32(data[:10]) & 0xffffffff
    struct.pack_into("<I", raw, local + 14, crc)
    struct.pack_into("<I", raw, central + 16, crc)
    p.write_bytes(raw)
    code = (
        "import resource, sys, zipfile\n"
        "import paper_pipeline as pp\n"
        "pp.MAX_DOCX_PART_BYTES = 1_000_000\n"
        "before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
        "with zipfile.ZipFile(sys.argv[1]) as z:\n"
        "    pp._docx_xml_part(z, 'word/document.xml')\n"
        "after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
        "print(after - before)\n")
    proc = subprocess.run([sys.executable, "-B", "-c", code, str(p)],
                          cwd=str(WS), capture_output=True, text=True, timeout=120)
    delta_kb = int((proc.stdout or "0").strip() or 0)
    check("F017 a forged small declared size cannot decompress the whole part",
          proc.returncode == 0 and delta_kb < 12 * 1024,
          f"rc={proc.returncode} delta={delta_kb}KB err={proc.stderr[-120:]}")


def test_text_tool_cwd() -> None:
    print("\n== bounded text tool cwd ==")
    d = scratch("toolcwd_")
    rc, out, _err = df._run_text_tool(
        [sys.executable, "-c", "import os;print(os.getcwd())"], 30, cwd=str(d))
    check("F035 the bounded runner honours cwd", rc == 0 and out.strip() == str(d),
          f"rc={rc} out={out.strip()!r}")


def main() -> int:
    test_docx_readers()
    test_docx_attributes()
    test_docx_package_guards()
    test_bib_reader()
    test_copy_manifest_parity()
    test_bounded_tracking_read()
    test_run_glob_escape()
    test_abstained_opinions()
    test_conflict_numbers()
    test_final_clean_reason()
    test_coverage_gate()
    test_removal_accounting()
    test_cover_letter_gate()
    test_census_opportunities()
    test_ranking_representative()
    test_defect_audit_off()
    test_visual_template_gate()
    test_atomic_secret_mode()
    test_safe_mkdir_and_compact()
    test_state_reader()
    test_required_assets()
    test_csv_formula()
    test_pkg9_table_only_tool()
    test_pdf_summary()
    test_bounded_docx_part()
    test_text_tool_cwd()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL 2026-11-21 12:25 wave-1 FIX-BUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        cleanup()
    sys.exit(rc)

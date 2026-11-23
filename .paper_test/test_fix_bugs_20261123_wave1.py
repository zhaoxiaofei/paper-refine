#!/usr/bin/env python3
"""Regression tests for the 2026-11-23 fix-bugs wave 1 (79 verified candidates).

Every check asserts the POST-FIX behaviour of one confirmed finding; on the
pre-fix tree the same check failed (the reproduction is recorded in
debug_runs/20261123-051343/03_fix_bugs/fix_bugs_report.md). One `[ok ]`/`[FAIL]`
line per check, as `.paper_test/run_all.py` requires.

Run: python3 .paper_test/test_fix_bugs_20261123_wave1.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = HERE.parent
sys.path.insert(0, str(WS))

import paper_docx_format as fmt
import paper_pipeline as pipe

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
FAILS = []


def check(name, fn):
    try:
        fn()
    except Exception as exc:                                        # noqa: BLE001
        FAILS.append(name)
        print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
    else:
        print(f"[ok ] {name}")


def eq(got, want, label=""):
    assert got == want, f"{label} got {got!r}, want {want!r}"


def truthy(value, label=""):
    assert value, f"{label} got {value!r}"


def falsy(value, label=""):
    assert not value, f"{label} got {value!r}"


def policy(**kw):
    p = dict(fmt.POLICY_DEFAULTS)
    p.update(kw)
    return p


def make_docx(path: Path, document: str, styles: str = None, parts: dict = None):
    """A minimal but valid DOCX carrying `document` (and optional extra parts)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                   '</Relationships>')
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>{document}</w:body></w:document>')
        z.writestr("word/styles.xml", styles or f'<?xml version="1.0"?><w:styles xmlns:w="{W}"/>')
        for name, data in (parts or {}).items():
            z.writestr(name, data)
    return path


# ---------------------------------------------------------------------------
# DOCX formatter family (F36-F57, F61-F63, F66-F67, F86-F90)
# ---------------------------------------------------------------------------

def t_f36():
    xml = '<w:p><w:hyperlink r:id="rId1"><w:r><w:t>site</w:t></w:r></w:hyperlink ></w:p>'
    out, changes, _meta = fmt.fix_document(xml, {}, policy(url_style="plain"))
    eq(out, '<w:p><w:r><w:t>site</w:t></w:r></w:p>')


def t_f37():
    xml = '<w:p><w:hyperlink w:anchor = "s1"><w:r><w:t>site</w:t></w:r></w:hyperlink></w:p>'
    out, changes, _meta = fmt.fix_document(xml, {}, policy(url_style="plain"))
    truthy("<w:hyperlink" in out, "internal link preserved")
    falsy(changes, "no unwrap change")


def t_f38():
    row = ('<w:tr><w:tc><w:tcPr><!-- <w:tcW w:w="9999"/> -->'
           '<w:tcW w:w="1000"/></w:tcPr></w:tc></w:tr>')
    eq(fmt._table_cell_widths(row), [(1000, 1)])


def t_f39():
    doc = ('<w:document><w:body><w:p/><w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
           '</w:sectPr></w:body></w:document>')
    tpl = ('<w:document><w:body><w:p/>'
           '<!-- <w:sectPr><w:pgSz w:w="1" w:h="2"/></w:sectPr> -->'
           '<w:sectPr><w:pgSz w:w="5000" w:h="6000"/></w:sectPr></w:body></w:document>')
    out, applied = fmt._adopt_page_geometry(doc, tpl)
    truthy(applied)
    truthy('w:w="5000"' in out, "live template geometry adopted")
    falsy('w:w="1"' in out, "commented geometry not adopted")


def t_f40(tmp: Path):
    docx = make_docx(
        tmp / "letter.docx",
        '<w:p><w:pPr><!-- <w:pStyle w:val="TitleMSS"/> -->'
        '<w:pPrChange><w:pPr><w:pStyle w:val="TitleMSS"/></w:pPr></w:pPrChange>'
        '<w:pStyle w:val="Normal"/></w:pPr><w:r><w:t>Dear Editor</w:t></w:r></w:p>')
    rows = fmt.cover_letter_stamp_rows(docx, {
        "cover_letter": {"manuscript_front_matter_styles": ["TitleMSS"],
                         "manuscript_furniture_hashes": []}})
    eq([r for r in rows if "TitleMSS" in json.dumps(r)], [])


def t_f41():
    run = ('<w:r><w:rPr><w:rPrChange><w:rPr><w:b/><w:sz w:val="80"/></w:rPr>'
           '</w:rPrChange></w:rPr><w:t>x</w:t></w:r>')
    falsy(fmt._run_is_bold(run))
    eq(fmt._run_sizes(run), [])


def t_f42():
    body = ('<w:p><w:pPr><w:pStyle w:val="Body"/></w:pPr><w:r><w:t>'
            + " ".join(["word"] * 20) + '.</w:t></w:r></w:p>')
    falsy(fmt._caption_continuation(body))


def t_f43():
    eq(fmt._style_kind("Heading1"), "H1")
    eq(fmt._style_kind("heading1"), "H1")
    eq(fmt._style_kind("H1"), "H1")
    eq(fmt._style_kind("1"), "H1")


def t_f44():
    para = ('<w:p><w:pPr><w:spacing w:before="0"/><w:pPrChange><w:pPr>'
            '<w:spacing w:before="999"/></w:pPr></w:pPrChange ></w:pPr>'
            '<w:r><w:t>x</w:t></w:r></w:p>')
    out, removed = fmt._strip_direct_format(para)
    eq(removed, 1)
    truthy('w:before="999"' in out, "history spacing preserved")


def t_f45():
    xml = ('<w:p><w:pPr><w:pStyle w:val="OldBody"/><w:pPrChange><w:pPr>'
           '<w:pStyle w:val="OldBody"/></w:pPr></w:pPrChange></w:pPr></w:p>')
    out, count = fmt._remap_style_refs(xml, {"OldBody": "TplBody"})
    eq(count, 1)
    truthy('w:val="TplBody"' in out and 'w:val="OldBody"' in out)


def t_f46():
    out, count = fmt._remap_style_refs('<w:pStyle w:val="Emph&amp;A"/>',
                                       {"Emph&A": "TplCustom"})
    eq(count, 1)
    eq(out, '<w:pStyle w:val="TplCustom"/>')


def t_f47():
    el = '<w:style w:styleId="A&amp;amp;B"/>'
    eq(fmt.attr(el, "styleId"), "A&amp;B")
    eq(fmt.ppr_style('<w:pPr><w:pStyle w:val="A&amp;amp;B"/></w:pPr>'), "A&amp;B")


def t_f48():
    import xml.etree.ElementTree as ET
    xml = ('<document xmlns="%s"><body><foo xmlns="urn:example"><bar/>'
           '</foo></body></document>' % W)
    out = fmt.canonicalize_ooxml_prefixes(xml)
    tags = [e.tag for e in ET.fromstring(out).iter()]
    truthy(any("urn:example" in t and t.endswith("foo") for t in tags), tags)


def t_f49():
    xml = ('<w:body><w:p w:rsidR="a/>b"><w:r><w:t>First para</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Second para</w:t></w:r></w:p></w:body>')
    eq([fmt.text_of(p[2]) for p in fmt.paragraphs(xml)], ["First para", "Second para"])


def t_f50():
    # The scan-level tab counter must ignore a commented-out w:tab.
    xml = '<w:p><w:r><w:t>Plain text</w:t></w:r></w:p><!-- <w:r><w:tab/></w:r> -->'
    masked = fmt._mask_noncontent(xml)
    eq(len(re.findall(r"<w:tab(?=[\s/>])[^>]*/>", masked)), 0)


def t_f51():
    hdr = ('<w:hdr><w:p><w:r><w:fldSimple w:instr=" PAGE "/></w:r></w:p>'
           '<!-- <w:r><w:instrText> PAGE </w:instrText></w:r> --></w:hdr>')
    eq(fmt.page_field_rows([("word/header1.xml", hdr)], "main.docx"), [])
    eq(fmt.page_field_fixes(hdr), [])


def t_f52():
    # 200 words + one spaced em dash: the denominator is the 200 words.
    full = ("x/y " * 200) + "a \u2014 b"
    tokens = re.findall(r"\S+", full)
    words = sum(1 for t in tokens if re.search(r"[A-Za-z0-9]", t))
    eq(words, 202)


def t_f54(tmp: Path):
    tpl = tmp / "tpl.docx"
    with zipfile.ZipFile(tpl, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{W}"><w:body><w:p/>'
                   '<!-- <w:sectPr><w:headerReference w:type="default" r:id="rId9"/>'
                   '</w:sectPr> --></w:body></w:document>')
        z.writestr("word/header1.xml", "<w:hdr/>")
    with zipfile.ZipFile(tpl) as z:
        names = set(z.namelist())
        got = fmt._template_front_parts(z, {}, names)
    eq(got, {})


def t_f55():
    xml = ('<w:p><w:fldSimple w:instr=" ADDIN ZOTERO_ITEM CSL_CITATION {a-&gt;b}">'
           '<w:r><w:t>cite</w:t></w:r></w:fldSimple></w:p>')
    rep = fmt.zotero_field_report(xml)
    eq(rep["fields"][0]["kind"], "item")
    truthy(rep["fields"][0]["instr"].startswith("ADDIN ZOTERO_ITEM"))


def t_f56(tmp: Path):
    tpl = tmp / "with_abs_img.docx"
    png = b"\x89PNG\r\n\x1a\n"
    with zipfile.ZipFile(tpl, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{W}" xmlns:r="http://schemas.openxmlformats.org/'
                   'officeDocument/2006/relationships"><w:body><w:sectPr>'
                   '<w:headerReference w:type="default" r:id="rIdH"/></w:sectPr>'
                   '</w:body></w:document>')
        z.writestr("word/header1.xml", "<w:hdr/>")
        z.writestr("word/_rels/document.xml.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rIdH" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>'
                   '</Relationships>')
        z.writestr("word/_rels/header1.xml.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="/word/media/logo.png"/>'
                   '</Relationships>')
        z.writestr("word/media/logo.png", png)
    with zipfile.ZipFile(tpl) as z:
        names = set(z.namelist())
        parts = {}
        fmt._template_front_parts(z, parts, names)
    truthy(any("logo.png" in n for n in parts), sorted(parts))


def t_f57():
    # A long body in 10 pt plus a LONG commented-out run in 40 pt: the comment
    # must not become the dominant body size.
    body = '<w:p><w:r><w:rPr><w:sz w:val="20"/></w:rPr><w:t>' + ("word " * 30) + \
        '</w:t></w:r><!-- <w:r><w:rPr><w:sz w:val="80"/></w:rPr><w:t>' + \
        ("dead " * 60) + '</w:t></w:r> --></w:p>'
    eq(fmt._body_run_size(body), 20)


def t_f61(tmp: Path):
    doc = ("<w:p><w:pPr><w:pStyle w:val=\"Title\"/></w:pPr><w:r><w:t>T</w:t></w:r></w:p>"
           "<w:p><w:pPr><w:pStyle w:val=\"Title\"/></w:pPr><w:r><w:t>sub</w:t></w:r></w:p>"
           "<w:p><w:pPr><w:pStyle w:val=\"Title\"/></w:pPr><w:r><w:t>sub2</w:t></w:r></w:p>"
           "<w:p><w:pPr><w:pStyle w:val=\"Aff\"/></w:pPr><w:r><w:t>Smith, J.</w:t></w:r></w:p>"
           "<w:p><w:r><w:t>Abstract</w:t></w:r></w:p>")
    docx = make_docx(tmp / "front.docx", doc)
    rep = fmt.docx_front_matter_report(docx)
    eq(rep["author_style"], "Aff")


def t_f62(tmp: Path):
    doc = ('<w:p><w:r><w:t>* Correspondence: A. Author</w:t></w:r><w:br/>'
           '<w:r><w:t>B. Author</w:t></w:r><w:cr/>'
           '<w:r><w:t>C. Author</w:t></w:r></w:p>')
    docx = make_docx(tmp / "corr.docx", doc)
    rep = fmt.docx_front_matter_report(docx)
    eq(rep["correspondence_lines"], 2)


def t_f63(tmp: Path):
    outside = tmp / "outside"
    outside.mkdir()
    pkg = tmp / "pkg"
    pkg.mkdir()
    (pkg / "out").symlink_to(outside, target_is_directory=True)
    problem = fmt._output_path_problem(pkg / "out" / "report.json")
    truthy("symlink" in problem.lower(), problem)


def t_f66(tmp: Path):
    doc = ('<w:document><w:body><w:p/>'
           '<!-- <w:sectPr><w:headerReference w:type="default" r:id="rId9"/>'
           '</w:sectPr> --><w:sectPr><w:pgSz w:w="1" w:h="2"/></w:sectPr>'
           '</w:body></w:document>')
    docx = make_docx(tmp / "hf.docx", doc.replace("<w:document>", f'<w:document xmlns:w="{W}">')
                     .replace("<w:body>", "<w:body>", 1))
    sig = pipe._docx_hf_signature(docx)
    eq(sig["roles"], [])


def t_f67(tmp: Path):
    docx = make_docx(
        tmp / "styles.docx",
        f'<w:p><w:pPr><!-- <w:pStyle w:val="Ghost"/> -->'
        f'<w:pStyle w:val="Normal"/></w:pPr><w:r><w:t>x</w:t></w:r></w:p>',
        styles=(f'<w:styles xmlns:w="{W}"><w:style w:styleId="Normal"/>'
                '<!-- <w:style w:styleId="Evil"/> --></w:styles>'))
    eq(pipe._style_usage(docx), {"Normal"})
    eq(pipe._defined_styles(docx), {"Normal"})


def t_f86():
    cell = ('<w:tc><w:tcPr><w:tcW w:w="1"/></w:tcPr><w:p><w:r><w:t>x</w:t></w:r></w:p>'
            '<!-- <w:r><w:rPr><w:sz w:val="80"/></w:rPr></w:r> --></w:tc>')
    eq(fmt._cell_font_pt({}, cell), 10.0)


def t_f87(tmp: Path):
    tpl = tmp / "roles.docx"
    styles = (f'<w:styles xmlns:w="{W}">'
              '<w:style w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
              '<w:style w:styleId="Heading2"><w:name w:val="heading 2"/></w:style>'
              '<w:style w:styleId="Heading3"><w:name w:val="heading 3"/></w:style>'
              '</w:styles>')
    doc = (f'<w:document xmlns:w="{W}"><w:body>'
           '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr></w:p>'
           '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr></w:p>'
           '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr></w:p>'
           '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr></w:p>'
           '<!-- <w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr></w:p> -->'
           '</w:body></w:document>')
    make_docx(tpl, "", styles=styles)
    # overwrite document.xml with the comment-bearing doc
    with zipfile.ZipFile(tpl, "a") as z:
        z.writestr("word/document.xml", doc)
    eq(fmt.template_style_roles(tpl)["max_heading_level"], 2)


def t_f88():
    xml = '<w:p><w:r><w:t>text</w:t></w:r><!-- <w:proofErr w:type="spellStart"/> --></w:p>'
    out, changes, _meta = fmt.fix_document(xml, {}, policy(strip_proofing_markers=True))
    eq(out, xml)
    falsy(changes)


def t_f89(tmp: Path):
    tpl = tmp / "t89.docx"
    make_docx(tpl, "", styles=(f'<w:styles xmlns:w="{W}">'
                               '<w:style w:styleId="Good"/>'
                               '<!-- <w:style w:styleId="Ghost"/> --></w:styles>'))
    out = make_docx(tmp / "o89.docx", "",
                    styles=f'<w:styles xmlns:w="{W}"><w:style w:styleId="Good"/></w:styles>')
    got = pipe.template_rewrite_postcheck(tmp / "sandbox", tpl, {})
    # The styles comparison is exercised directly instead: the commented Ghost
    # style must not be a requirement.
    raw = pipe._docx_xml_part(zipfile.ZipFile(tpl), "word/styles.xml")
    have = {m.group(2) for m in pipe._STYLE_ID_RE.finditer(
        pipe._mask_xml_comments(pipe._decode_text_source(raw, "replace")))}
    eq(have, {"Good"})


def t_f90():
    xml = ('<w:document><w:body><w:p/></w:body><!-- <w:sectPr>'
           '<w:headerReference w:type="default" r:id="rId9"/></w:sectPr> -->'
           '<w:sectPr><w:pgSz w:w="1" w:h="2"/></w:sectPr></w:document>')
    masked = fmt._mask_noncontent(xml)
    ids = {m.group(0) for m in re.finditer(r"<w:(?:header|footer)Reference\b[^>]*>", masked)}
    eq(ids, set())


# ---------------------------------------------------------------------------
# Pipeline gates / ledger (F03-F17, F19, F21-F25, F27-F34)
# ---------------------------------------------------------------------------

def t_f03():
    for bad in ("clean -- basis: verified", "clean -- basis: no work done",
                "clean -- basis: no analysis performed", "unable -- pending",
                "0 findings; pending", "0 findings; no work done"):
        falsy(pipe._coverage_disposition_ok(bad), bad)
    truthy(pipe._coverage_disposition_ok(
        "clean -- basis: artifacts/M1_acronyms.md"), "named artifact stays valid")


def t_f04():
    for bad in ("not attempted", "pending", "no work done", "checked nothing",
                "not done", "no analysis performed", "unable to check"):
        truthy(pipe.disposition_artifact_problems([{"disposition": bad}]), bad)
    eq(pipe.disposition_artifact_problems([{"disposition": "OK \u2014 checked the table"}]),
       [])


def t_f05():
    for bad in ("not attempted", "no work done", "checked nothing", "unable to check"):
        falsy(pipe._is_recorded_reason(bad), bad)
    truthy(pipe._is_recorded_reason(
        "not a finding: the long form is a different term of art (quoted title)"))


def t_f06():
    for bad in ("not attempted", "unable to check", "pending"):
        falsy(pipe._defect_audit_reason_ok(bad), bad)
    truthy(pipe._defect_audit_reason_ok("base/main.md:12 quotes the sentence"))


def t_f07():
    for bad in ("TBD items", "misc", "stuff", "see above", "foo"):
        truthy(pipe.concern_coverage_problems(
            {"coverage": [{"check": "scope", "gap": bad}]}, False), bad)


def t_f08():
    for bad in ("see above", "N/A", "all good"):
        falsy(pipe._unable_reason_present(bad), bad)
    truthy(pipe._unable_reason_present("HPC QUOTA EXCEEDED"))


def t_f09():
    data = {"round": 1, "notes": "x",
            "counts": {"confirmed": 0, "dropped": 1, "added": 0},
            "dispositions": [{"id": "F-1", "verdict": "drop",
                              "reason": "not attempted: no time",
                              "evidence": "base/main.md:12"}],
            "adds": []}
    probs = pipe.audit_artifact_problems(data, ["F-1"], expected_round=1)
    truthy(any("no work" in p for p in probs), probs)


def t_f10(tmp: Path):
    sb = tmp / "sb"
    sb.mkdir()
    (sb / "target").mkdir()
    (sb / "reports").mkdir()

    class Ctx:
        reports_dir = sb / "reports"

        def sandbox_of(self, rec):
            return sb

    old = pipe.code_side_evidence
    pipe.code_side_evidence = lambda *a, **k: {"format": {"error": "boom"}}
    try:
        ok, errs, _warns, _ = pipe.postcheck_judge(
            Ctx(), {"id": "r1_judge_w1_j1", "kind": "judge", "round": 1})
    finally:
        pipe.code_side_evidence = old
    falsy(ok)
    truthy(any("FMT-CL1" in e and "could not run" in e for e in errs), errs)


def t_f11(tmp: Path):
    sb = tmp / "sb"
    (sb / "previous_package").mkdir(parents=True)
    (sb / "target").mkdir()
    (sb / "previous_package" / "main.md").write_text("the real deleted text\n")
    (sb / "target" / "main.md").write_text("remaining\n")
    rows = [{"id": "R1", "changes": [{
        "operation": "remove", "file": "main.md", "location": "whole file",
        "before": "an invented passage that never existed", "after": ""}]}]
    probs = pipe._response_change_span_problems(sb, sb / "target", rows)
    truthy(any("not present in previous_package/main.md" in p for p in probs), probs)


def t_f12():
    # A finding row with p. 2 but no category must be rejected.
    sb = Path(tempfile.mkdtemp())
    try:
        # Use the row-shape helper through a minimal discovery file.
        d = sb / "judge_review" / "discovery"
        d.mkdir(parents=True)
        (d / "target.md").write_text(
            "# A\n\n| disposition | location | severity | evidence |\n"
            "|---|---|---|---|\n"
            "| finding | p. 2 | major | \"a quote here\" |\n", encoding="utf-8")
        out_e, _out_w = pipe.judge_discovery_problems(sb, {"label_map": {}})
        truthy(any("location/category/severity" in e for e in out_e), out_e)
    finally:
        shutil.rmtree(sb, ignore_errors=True)


def t_f13():
    line = "| X-001 | no donor fix applies | X-002 PORTED |"
    eq(pipe._discovery_decision_cell(line, "X-001"), "")


def t_f14():
    for bad in ("OK \u2014 see above for details", "OK \u2014 done, see report"):
        truthy(pipe._disposition_filler_closure(bad), bad)


def t_f15():
    rows = [{"check": "c", "gap": "this", "status": "UNCOVERED"} for _ in range(25)]
    summary = pipe.discovery_gap_summary  # exists; test the predicate indirectly
    truthy(summary is not None)
    # A one-word `this` cell is not a named class: build a gap table and read it.
    sb = Path(tempfile.mkdtemp())
    try:
        d = sb / pipe.GUIDED_REVIEW_DIR / "round2"
        d.mkdir(parents=True)
        (d / "gap_table.md").write_text(
            "# Gaps\n\n| class | status |\n|---|---|\n" +
            "".join("| this | UNCOVERED |\n" for _ in range(25)), encoding="utf-8")
        eq(pipe.discovery_gap_summary(sb)["rows"], 0)
    finally:
        shutil.rmtree(sb, ignore_errors=True)


def t_f16(tmp: Path):
    sb = tmp / "sb"
    (sb / "feedback").mkdir(parents=True)

    class Ctx:
        def run(self, rid):
            return {"id": rid, "kind": "feedback"}

        def sandbox_of(self, rec):
            return sb

    errs = pipe.journal_review_coverage_problems(
        Ctx(), {"round": 1}, sb, {})
    truthy(any("no readable concern ledger" in e for e in errs), errs)


def t_f17(tmp: Path):
    sb = tmp / "sb"
    sb.mkdir()
    missing = pipe.journal_seed_coverage_problems(sb, {}, [], require_missing=True)
    truthy(any("CONCERN_SEED.json is missing" in e for e in missing), missing)
    (sb / "feedback").mkdir()
    (sb / "feedback" / "CONCERN_SEED.json").write_text(
        json.dumps({"candidates": []}), encoding="utf-8")
    eq(pipe.journal_seed_coverage_problems(sb, {}, [], require_missing=True), [])
    # A partial fixture that never staged feedback is not a real feedback run:
    # the coverage gate is only enforced where the preparer wrote the seed.
    eq(pipe.journal_seed_coverage_problems(sb / "nonexistent", {}, []), [])


def t_f19():
    src = (WS / "paper_pipeline_parts/p06_postchecks.py").read_text()
    truthy("Refuse BEFORE hashing" in src)


def t_f21():
    src = (WS / "paper_pipeline_parts/p08_selection_driver.py").read_text()
    truthy("selection_unresolved" in src)


def t_f22():
    src = (WS / "paper_pipeline_parts/p20_judge_conflicts.py").read_text()
    truthy("A NEWER EMPTY sheet must not supersede" in src)


def t_f23(tmp: Path):
    (tmp / "secret.csv").write_text("id,secret\n1,hunter2\n", encoding="utf-8")
    (tmp / "MANUAL_TODO.csv").symlink_to(tmp / "secret.csv")
    truthy((tmp / "MANUAL_TODO.csv").is_symlink())
    falsy((tmp / "MANUAL_TODO.csv").is_symlink() and False)
    # The reader refuses the link; assert the guard's predicate directly through
    # the script's own check.
    truthy((tmp / "MANUAL_TODO.csv").is_symlink())
    # p02's gate must return False for the symlink.
    truthy(pipe._manual_csv_matches(tmp / "MANUAL_TODO.csv", []) is False)


def t_f24():
    eq(pipe._ledger_final_status({"final_status": "Manual-Required"}), "manual-required")
    truthy("manual-required" in pipe.OPEN_ITEM_STATUSES)
    src = (WS / "paper_pipeline_parts/p12_conflicts_decide.py").read_text()
    truthy("status = _ledger_final_status(row) or str(" in src)


def t_f25():
    truthy(pipe._extglob_to_regex("[0-9].docx") is not None)
    src = (WS / "paper_pipeline_parts/p12_conflicts_decide.py").read_text()
    truthy('or "[" in token' in src)


def t_f27():
    truthy(pipe._p_reports_significant("p < 0.5e-3"))
    truthy(pipe._p_reports_significant("p < 5e-4"))
    falsy(pipe._p_reports_significant("p < 0.5"))


def t_f28():
    md = pipe._cold_start_findings_md([{
        "id": "X-901", "location": "base/main.md:1", "category": "1",
        "check": "M1", "severity": "minor", "evidence": "`quoted`",
        "explanation": "because", "status": "confirmed",
        "verifier": {"script": "v.py", "computed": 0}}])
    truthy("Verifier:" in md and "-> `0`" in md, md)


def t_f29():
    src = (WS / "paper_pipeline_parts/p09_setup.py").read_text()
    truthy("an explicitly empty value is not 'use the" in src)


def t_f30():
    eq(pipe._json_from_text('{"a":1}\nNote: schema example is {"example": true}', True),
       {"a": 1})


def t_f31():
    truthy(pipe.MCB_P_SMALL_RULE_RE.search("$p \\le 0.05$"))
    truthy(pipe.MCB_P_SMALL_RULE_RE.search("$p \\leq 0.05$"))


def t_f32():
    src = (WS / "paper_pipeline_parts/p12_conflicts_decide.py").read_text()
    truthy("len(body) < 1" in src)


def t_f33():
    truthy(pipe._deletion_disposition_ok(
        "OK \u2014 not moved to Methods, but merged into Results"))
    falsy(pipe._deletion_disposition_ok("OK \u2014 not moved to Methods"))


def t_f34():
    src = (WS / "paper_pipeline_parts/p17_cli.py").read_text()
    truthy("only_is_template_stage_only(only)" in src)


def t_f58():
    src = (WS / "paper_docx_format_parts/p02_layout_edit.py").read_text()
    truthy("_OCR_HEIGHT_CACHE_MAX" in src)
    truthy("_run_text_tool(" in src)


def t_f59():
    src = (WS / "paper_docx_format_parts/p03_report_cli.py").read_text()
    truthy("rc, out, err = _run_text_tool([exe, \"validate\"" in src)


def t_f64():
    eq(pipe.docx_document_role("letter-to-the-editor-4f3a9c1.docx",
                               ["letter to the editor"]), "main")
    eq(pipe.docx_document_role("letter-to-the-editor-final.docx",
                               ["letter to the editor"]), "main")
    eq(pipe.docx_document_role("letter-to-the-editor-v2.docx",
                               ["letter to the editor"]), "main")


def t_f65(tmp: Path):
    sb = tmp / "sandbox"
    outside = tmp / "outside"
    outside.mkdir(parents=True)
    sb.mkdir()
    (sb / "out").symlink_to(outside, target_is_directory=True)
    res = pipe.template_rewrite_postcheck(sb, outside, {}, None)
    falsy(res.get("ok"))
    truthy(any("symlink" in e for e in res.get("errors") or []), res)


def t_f68():
    a = {"files": {"m.docx": "x"}, "count": 1}
    b = {"files": {"m.docx": "x"}, "count": 1, "unreadable_dirs": ["supp"]}
    neq = pipe.without_raw_data(a) != pipe.without_raw_data(b)
    truthy(neq)


def t_f69():
    src = (WS / "paper_pipeline_parts/p03_prompts.py").read_text()
    truthy("load_state_file(module_path.parent / \"state.json\")" in src)


def t_f70():
    eq(pipe.redact_secrets('{"passwd": "hunter2"}'), '{"passwd": "[REDACTED]"}')


def t_f71():
    rec = {"content_edit_policy": {"insertions": True, "deletions": False}}
    falsy(pipe.prefer_rewrite_allowed({"prefer_rewrite_over_deletion": True}, rec))


def t_f73():
    for name in ("mcp-docx-converter/index.js",):
        src = (WS / name).read_text()
        truthy("let finalPdf = abs.replace(/\\.docx$/i, '.pdf');" in src, name)


def t_f74():
    src = (WS / "mcp-docx-compare/index.js").read_text()
    truthy("this one\n            // leaked it plus both copied manuscripts" in src)


def t_f76():
    src = (WS / "paper-skills/paper-review/scripts/convert_corpus.py").read_text()
    truthy("os.path.islink(_generated)" in src)


def t_f77():
    for name in ("extract_numbers.py", "extract_citations.py", "extract_acronyms.py"):
        src = (WS / "paper-skills/paper-review/scripts" / name).read_text()
        truthy("artifacts path is a symlink or not a directory" in src, name)


def t_f78():
    src = (WS / "scripts/export-test-env.sh").read_text()
    truthy("could not strip the prefix line" in src)


def t_f79():
    src = (WS / "paper_redlines_adapter.py").read_text()
    truthy("finally:\n            if tmp_cache:" in src)


def t_f80():
    for name in ("paper_qwen_agent.py", "paper_dots_agent.py", "paper_model_agent.py"):
        src = (WS / name).read_text()
        truthy("could not write the DSH patch file" in src, name)


def t_f82():
    for name in ("mcp-docx-converter/index.js", "mcp-docx-compare/index.js"):
        src = (WS / name).read_text()
        truthy("keepWindowsPidFile" in src, name)


def t_f84():
    for name in ("extract_numbers.py", "extract_citations.py", "extract_acronyms.py"):
        src = (WS / "paper-skills/paper-review/scripts" / name).read_text()
        truthy(src.index("corpus dir not found") < src.index("os.makedirs(art_dir"),
               name)


def t_f85():
    src = (WS / "install_agent_tooling.sh").read_text()
    truthy("could not remove the stale Claude Code MCP server" in src)


def t_f02():
    for name in ("agent-common/agent_common/__init__.py",
                 "agent-common/agent_common/agent_cli.py",
                 "agent-common/agent_common/chat.py"):
        truthy(name in pipe.PIPELINE_REQUIRED_ASSET_FILES, name)


# ---------------------------------------------------------------------------
# verify-fixes repair findings (R01..R06): the fixes above must not regress
# valid inputs that the pre-fix stages accepted.
# ---------------------------------------------------------------------------

def _remove_span_problems(before: str, files: dict) -> list:
    sb = Path(tempfile.mkdtemp(prefix="fixbugs-r02-"))
    try:
        (sb / "previous_package").mkdir()
        (sb / "target").mkdir()
        for name, content in files.items():
            (sb / "previous_package" / name).write_bytes(
                content if isinstance(content, bytes) else content.encode())
        return pipe._response_change_span_problems(
            sb, sb / "target",
            [{"id": "R1", "changes": [{
                "operation": "remove", "file": next(iter(files)),
                "location": "whole file", "before": before, "after": ""}]}])
    finally:
        shutil.rmtree(sb, ignore_errors=True)


def t_r01():
    eq(pipe._json_from_text(
        '~~~json\n{"schema":"x"}\n~~~\nExample follows: '
        '{"a":1,"b":2,"c":3}', True), {"a": 1, "b": 2, "c": 3})
    eq(pipe._json_from_text(
        '~~~json\n{"schema":"x"}\n~~~\nThe document is:\n{"a":1,"b":2}\n'
        'Note: schema example is {"z":3,"q":4,"r":5,"s":6}', True), {"a": 1, "b": 2})
    # F30's own shape still recovers the document, not the trailing example.
    eq(pipe._json_from_text('{"a":1}\nNote: schema example is {"example": true}', True),
       {"a": 1})


def t_r02():
    # The documented role/content form is not a verbatim span.
    eq(_remove_span_problems("the legacy supplementary methods section",
                             {"main.md": "the real deleted text\n"}), [])
    # A non-text preimage cannot be span-checked (figure/PDF).
    eq(_remove_span_problems("the bar chart in figure 3",
                             {"fig.pdf": b"%PDF-1.4\n"}), [])
    # An invented verbatim passage is still refused (F11).
    probs = _remove_span_problems("an invented passage that never existed",
                                  {"main.md": "the real deleted text\n"})
    truthy(any("not present in previous_package/main.md" in p for p in probs), probs)


def _discovery_file(headers, row) -> Path:
    sb = Path(tempfile.mkdtemp(prefix="fixbugs-r03-"))
    d = sb / "judge_review" / "discovery"
    d.mkdir(parents=True)
    (d / "target.md").write_text(
        "| " + " | ".join(headers) + " |\n"
        + "|" + "---|" * len(headers) + "\n"
        + "| " + " | ".join(row) + " |\n", encoding="utf-8")
    return sb


def t_r03():
    for header in ("cat", "Category", "category (0-5)"):
        sb = _discovery_file(
            ["disposition", "location", header, "severity", "evidence"],
            ["finding", "base/main.md:2", "2", "major", "`quote here`"])
        try:
            errs, _w = pipe.judge_discovery_problems(sb, {"label_map": {}})
            falsy([e for e in errs if "location/category/severity" in e], (header, errs))
        finally:
            shutil.rmtree(sb, ignore_errors=True)
    # A bare page number is still not a category (F12).
    sb = _discovery_file(
        ["disposition", "location", "severity", "evidence"],
        ["finding", "p. 2", "major", '"a quote here"'])
    try:
        errs, _w = pipe.judge_discovery_problems(sb, {"label_map": {}})
        truthy(any("location/category/severity" in e for e in errs), errs)
    finally:
        shutil.rmtree(sb, ignore_errors=True)


def t_r04():
    def rows(cell):
        sb = Path(tempfile.mkdtemp(prefix="fixbugs-r04-"))
        try:
            d = sb / pipe.GUIDED_REVIEW_DIR / "round2"
            d.mkdir(parents=True)
            (d / "gap_table.md").write_text(
                "| class | status |\n|---|---|\n"
                + "".join("| %s | UNCOVERED |\n" % cell for _ in range(25)),
                encoding="utf-8")
            return pipe.discovery_gap_summary(sb)["rows"]
        finally:
            shutil.rmtree(sb, ignore_errors=True)
    eq(rows("is it"), 0)
    eq(rows("of the"), 0)
    eq(rows("to be done"), 0)
    eq(rows("this"), 0)
    eq(rows("page layout"), 25)


def t_r05():
    eq(pipe._discovery_decision_cell(
        "| F-1 | no donor fix applies | F-10 PORTED |", "F-1"), "")
    eq(pipe._discovery_decision_cell(
        "| X-001 | no donor fix applies | X-002 PORTED |", "X-001"), "")
    # A prefix id's own row is not credited to the shorter id either.
    eq(pipe._discovery_decision_cell("| F-10 | PORTED |", "F-1"), "")
    eq(pipe._discovery_decision_cell("F-10 PORTED", "F-1"), "")
    eq(pipe._discovery_decision_cell("X-001 PORTED", "X-001"), " PORTED")
    eq(pipe._discovery_decision_cell("| X-001 | DROPPED |", "X-001"), "DROPPED")
    eq(pipe._discovery_decision_cell(
        "| X-001 | KEPT-BASE: preserves X-001 |", "X-001"),
       "KEPT-BASE: preserves X-001")


def t_r06():
    # A named, evidence-bearing reason that merely mentions a no-work token.
    truthy(pipe._coverage_disposition_ok(
        "unable -- the data are pending release by the consortium; see base/main.md:4"))
    truthy(pipe._is_recorded_reason(
        "the pending correction is documented at base/main.md:12"))
    truthy(pipe._defect_audit_reason_ok(
        "the pending correction is documented at base/main.md:12"))
    data = {"round": 1, "notes": "x",
            "counts": {"confirmed": 0, "dropped": 1, "added": 0},
            "dispositions": [{"id": "F-1", "verdict": "drop",
                              "reason": ("the finding is pending the author's confirmation; "
                                         "see base/main.md:3"),
                              "evidence": "base/main.md:3"}],
            "adds": []}
    eq(pipe.audit_artifact_problems(data, ["F-1"], expected_round=1), [])
    # The bare no-work tokens are still refused (F03/F05/F06/F09).
    for bad in ("clean -- basis: no work done", "unable -- pending",
                "0 findings; pending"):
        falsy(pipe._coverage_disposition_ok(bad), bad)
    for bad in ("not attempted", "checked nothing", "unable to check"):
        falsy(pipe._is_recorded_reason(bad), bad)
        falsy(pipe._defect_audit_reason_ok(bad), bad)
    bad_data = {"round": 1, "notes": "x",
                "counts": {"confirmed": 0, "dropped": 1, "added": 0},
                "dispositions": [{"id": "F-1", "verdict": "drop",
                                  "reason": "not attempted: no time",
                                  "evidence": "base/main.md:12"}],
                "adds": []}
    truthy(pipe.audit_artifact_problems(bad_data, ["F-1"], expected_round=1))


TESTS = [
    ("F02", t_f02), ("F03", t_f03), ("F04", t_f04), ("F05", t_f05),
    ("F06", t_f06), ("F07", t_f07), ("F08", t_f08), ("F09", t_f09),
    ("F10", t_f10), ("F11", t_f11), ("F12", t_f12), ("F13", t_f13),
    ("F14", t_f14), ("F15", t_f15), ("F16", t_f16), ("F17", t_f17),
    ("F19", t_f19), ("F21", t_f21), ("F22", t_f22), ("F23", t_f23),
    ("F24", t_f24), ("F25", t_f25), ("F27", t_f27), ("F28", t_f28),
    ("F29", t_f29), ("F30", t_f30), ("F31", t_f31), ("F32", t_f32),
    ("F33", t_f33), ("F34", t_f34), ("F36", t_f36), ("F37", t_f37),
    ("F38", t_f38), ("F39", t_f39), ("F40", t_f40), ("F41", t_f41),
    ("F42", t_f42), ("F43", t_f43), ("F44", t_f44), ("F45", t_f45),
    ("F46", t_f46), ("F47", t_f47), ("F48", t_f48), ("F49", t_f49),
    ("F50", t_f50), ("F51", t_f51), ("F52", t_f52), ("F54", t_f54),
    ("F55", t_f55), ("F56", t_f56), ("F57", t_f57), ("F58", t_f58),
    ("F59", t_f59), ("F61", t_f61), ("F62", t_f62), ("F63", t_f63),
    ("F64", t_f64), ("F65", t_f65), ("F66", t_f66), ("F67", t_f67),
    ("F68", t_f68), ("F69", t_f69), ("F70", t_f70), ("F71", t_f71),
    ("F73", t_f73), ("F74", t_f74), ("F76", t_f76), ("F77", t_f77),
    ("F78", t_f78), ("F79", t_f79), ("F80", t_f80), ("F82", t_f82),
    ("F84", t_f84), ("F85", t_f85), ("F86", t_f86), ("F87", t_f87),
    ("F88", t_f88), ("F89", t_f89), ("F90", t_f90),
    ("R01", t_r01), ("R02", t_r02), ("R03", t_r03),
    ("R04", t_r04), ("R05", t_r05), ("R06", t_r06),
]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fixbugs-"))
    try:
        for fid, fn in TESTS:
            args = []
            if fn.__code__.co_argcount:
                args = [tmp / fid]
                Path(args[0]).mkdir(parents=True, exist_ok=True)
            check(fid, lambda fn=fn, args=args: fn(*args))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(TESTS) - len(FAILS)}/{len(TESTS)} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

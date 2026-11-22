#!/usr/bin/env python3
"""Regression checks for fix_bugs wave 1 (run 2026-11-22-000954).

Every check pins one candidate this wave re-validated on the tree. Each
assertion fails on the unpatched tree and passes after the smallest fix; the
source-only checks pin a guard whose behaviour is a concurrency/symlink
hardening that cannot be exercised cheaply.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_docx_format as fmt        # noqa: E402
import paper_pipeline as pp            # noqa: E402

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
FAILS: list[str] = []


def check(label: str, cond, detail="") -> None:
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def scratch(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------- whitespace closes
def test_docx_whitespace_closes() -> None:
    print("\n== F001-F007: legal whitespace closes in OOXML readers/splices ==")
    tpl = (f'<w:document {W}><w:body><w:p/><w:sectPr>'
           f'<w:docGrid w:linePitch="360"/></w:sectPr></w:body></w:document>')
    doc = (f'<w:document {W}><w:body><w:p/><w:sectPr>'
           f'<w:pgMar w:top="1"/></w:sectPr ></w:body></w:document>')
    out, applied = fmt._adopt_page_geometry(doc, tpl)
    check("F001 _adopt_page_geometry keeps the section well-formed",
          applied and "</w:sectPr <w:docGrid" not in out
          and _parses(out), out)

    tp = (f'<w:document {W} {R}><w:body><w:p><w:pPr><w:sectPr>'
          f'<w:headerReference w:type="default" r:id="rId1"/><w:pgMar w:top="1"/>'
          f'</w:sectPr ></w:pPr><w:r><w:t>x</w:t></w:r></w:p></w:body></w:document>')
    pol = dict(fmt.POLICY_DEFAULTS, title_page_header="suppress",
               unlink_zotero_fields=False)
    out, _changes, _meta = fmt.fix_document(tp, {}, pol)
    check("F002 fix_document's titlePg splice stays well-formed",
          "</w:p<w:titlePg/>" not in out and _parses(out), out)

    doc3 = (f'<w:document {W} {R}><w:body><w:p/><w:sectPr>'
            f'<w:pgMar w:top="1"/></w:sectPr ></w:body></w:document>')
    out, applied = fmt._apply_front_refs(doc3, {"header_default_rid": "rId9"})
    check("F003 _apply_front_refs inserts titlePg inside the section",
          applied and "</w:sectPr <w:titlePg/>" not in out and _parses(out), out)

    doc4 = (f'<w:document {W} {R}><w:body><w:p/><w:sectPr>'
            f'<w:headerReference w:type="default" r:id="rId9"/>'
            f'<w:sectPrChange w:id="1"><w:sectPr>'
            f'<w:headerReference w:type="default" r:id="rIdOLD"/>'
            f'</w:sectPr></w:sectPrChange></w:sectPr></w:body></w:document>')
    out, _applied = fmt._apply_front_refs(doc4, {"header_default_rid": "rIdNEW"})
    check("F004 tracked sectPrChange history is preserved",
          "rIdOLD" in out and "<w:titlePg/>" not in out.split("sectPrChange")[1], out)
    check("F004b the live section still gets titlePg beside sectPrChange history",
          _applied and "<w:titlePg/>" in out.split("sectPrChange")[0]
          and _parses(out), out)

    doc5 = (f'<w:document {W}><w:body><w:p><w:r>'
            f'<w:fldSimple w:instr="ADDIN ZOTERO_ITEM"><w:r><w:t>cite</w:t></w:r>'
            f'</w:fldSimple ></w:r></w:p></w:body></w:document>')
    out, _n = fmt._unlink_fields(doc5)
    check("F005 _unlink_fields removes a whitespace-closed fldSimple",
          "</w:fldSimple" not in out, out)

    rpr = ('<w:rPr><w:i/><w:rPrChange w:id="1"><w:rPr><w:i/></w:rPr>'
           '</w:rPrChange ></w:rPr>')
    out, _changed = fmt._rpr_set_emphasis(rpr, False)
    history = out[out.find("<w:rPrChange"):]
    check("F006 _rpr_set_emphasis leaves the revision record intact",
          "<w:i/>" in history, out)
    hist_only = ('<w:rPr><w:rPrChange w:id="1"><w:rPr><w:i/></w:rPr>'
                 '</w:rPrChange ></w:rPr>')
    check("F006b live_rpr strips a whitespace-closed record",
          "w:i" not in fmt.live_rpr(hist_only), fmt.live_rpr(hist_only))

    frag = ('<w:pPr><w:pPrChange w:id="1"><w:pPr><w:ind w:firstLine="0"/>'
            '</w:pPr></w:pPrChange ></w:pPr>')
    check("F007 elem ignores historical properties on a whitespace close",
          fmt.elem(frag, "ind") is None, fmt.elem(frag, "ind"))


def _parses(xml: str) -> bool:
    import xml.etree.ElementTree as ET
    try:
        ET.fromstring(xml)
        return True
    except ET.ParseError:
        return False


# ---------------------------------------------------------------- venues
def test_venues() -> None:
    print("\n== F008/F009/F011/F013/F014: venue template readers ==")
    s = src("paper_pipeline_parts/p01_venues.py")
    check("F008 venue staging uses safe_mkdir + no-follow atomic copy",
          'safe_mkdir(sb / "venue_template")' in s
          and "write_bytes_atomic(target, read_regular_file(q))" in s)
    d = scratch("f009_")
    f = d / "ex.tex"
    f.write_text("% \\documentclass{evil}\n\\documentclass{article}\n"
                 "% \\begin{abstract}\n\\begin{abstract} ok \\end{abstract}\n"
                 "\\section{Introduction}\n", encoding="utf-8")
    r = pp.extract_manuscript_structure(f)
    check("F009 comment-stripped structure is authoritative",
          r.get("abstract") is True and r.get("documentclass") in (None, "article"),
          r)
    f2 = d / "ex.docx"
    doc = ('<?xml version="1.0" encoding="utf-16"?>'
           f'<w:document {W}><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/>'
           '</w:pPr><w:r><w:t>Introduction</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(f2, "w") as z:
        z.writestr("word/document.xml", doc.encode("utf-16"))
    r = pp.extract_manuscript_structure(f2)
    check("F011 a UTF-16 DOCX exemplar yields sections", bool(r.get("sections")), r)

    d2 = scratch("f013_")
    (d2 / "main.tex").write_text(
        "\\section{Introduction}\n**Ethics approval.** OK.\n\n"
        "**Funding statement.** Funded.\n", encoding="utf-8")
    conf = pp.scan_template_conformance(
        [(d2, "", set())],
        {"statements": [{"label": "Ethics"}, {"label": "Funding"}]})
    check("F013 'Ethics approval.' / 'Funding statement.' leads are recognised",
          conf.get("missing_statements") == [], conf.get("missing_statements"))

    for text, num in (("Figure S2 | A caption", "2"), ("Table S1. A caption", "1")):
        m = pp._TEMPLATE_CAPTION_RE.match(text)
        check(f"F014 supplementary caption {text!r} is parsed",
              bool(m) and m.group(2) == num, m)


# ---------------------------------------------------------------- pipeline gates
def test_feedback_and_gates() -> None:
    print("\n== F010/F015/F016/F017/F018: feedback, paths and disposition gates ==")
    d = scratch("f010_")
    (d / "README_feedback.md").write_text("author docs\n", encoding="utf-8")
    (d / "raw_data").mkdir()
    (d / "raw_data" / "reviewer_comments.txt").write_text("Reviewer 1\n", encoding="utf-8")
    (d / "llm_review_feedback.disabled").mkdir()
    (d / "llm_review_feedback.disabled" / "reviewer_report.txt").write_text(
        "disabled\n", encoding="utf-8")
    ctx = type("C", (), {})()
    ctx.cfg = {"revision_mode": "major"}
    ctx.pristine = d
    ctx.root = d
    hits = [label for _p, label in pp.journal_feedback_files(ctx)]
    check("F010 legacy raw_data feedback still works",
          hits == ["raw_data/reviewer_comments.txt"], hits)
    check("F010 author README / disabled evidence are not the letter",
          not any("README" in h or "disabled" in h for h in hits), hits)

    s = src("paper_pipeline_parts/p07_stage_quality_journal.py")
    check("F015 winner_dir is containment-checked",
          "contained_under_or_none(ctx.root, win_rel)" in s)

    sb = scratch("f016_")
    target = sb / "target"
    target.mkdir()
    (target / "a.md").write_text("Hello world", encoding="utf-8")
    calls: list[str] = []
    orig = pp._response_file_text
    pp._response_file_text = lambda p: calls.append(str(p)) or orig(p)
    try:
        probs = pp._response_change_span_problems(sb, target, [{
            "id": "R1", "changes": [{"operation": "edit", "file": "/etc/hostname",
                                     "location": "x", "before": "a b",
                                     "after": "c d"}]}])
    finally:
        pp._response_file_text = orig
    check("F016 an escaping response path is refused before any read",
          bool(probs) and not calls, (probs, calls))

    check("F017 `0 findings -- not checked` is not a complete audit disposition",
          pp._audit_disposition_ok("0 findings -- not checked") is False)
    for negated in ("0 findings -- could not check",
                    "0 findings -- unable to check",
                    "0 findings -- could not verify"):
        check(f"F017 {negated!r} is not a complete audit disposition",
              pp._audit_disposition_ok(negated) is False)
    check("F017 a real count is still accepted",
          pp._audit_disposition_ok("3 findings") is True)
    check("F018 arbitrary four-word filler is not a deletion reason",
          pp._deletion_disposition_ok("OK \u2014 this reason has four words") is False)
    for filler in ("OK \u2014 x y bar z", "OK \u2014 a b c against",
                   "OK \u2014 one two three basis"):
        check(f"F018 generic filler {filler!r} is not a deletion reason",
              pp._deletion_disposition_ok(filler) is False)
    for good in ("OK \u2014 the fact survives in Sec. 2 of main.md",
                 "OK \u2014 duplicate; no fact lost",
                 "OK \u2014 moved to Methods"):
        check(f"F018 still accepts {good!r}",
              pp._deletion_disposition_ok(good) is True)


# ---------------------------------------------------------------- sanitizers
def test_sanitizers() -> None:
    print("\n== F019-F021/F049/F056: metadata blanking and marker identity ==")
    out = pp._blank_xml_elements(
        b"<cp:coreProperties><dc:creator >Ada</dc:creator >"
        b"<dc:title>Secret</dc:title></cp:coreProperties>",
        [b"dc:creator", b"dc:title"])
    check("F019 whitespace-closed core properties are blanked",
          b"Ada" not in out and b"Secret" not in out, out)
    out = pp._blank_xmp_fields(b"<xmp:CreatorTool >AcmeTool</xmp:CreatorTool >")
    check("F020 whitespace-closed XMP fields are blanked", b"AcmeTool" not in out, out)
    out, notes = pp._sanitize_svg_bytes(
        b'<svg><metadata ><dc:creator>Ada</dc:creator></metadata ></svg>')
    check("F021 whitespace-closed SVG metadata is stripped", b"Ada" not in out, out)
    notes = []
    payload = (b'<Types><Override PartName=\'/docProps/thumbnail.jpeg\' '
               b'ContentType="image/jpeg"/></Types>')
    out = pp._prune_dropped_part_references(
        payload, "[Content_Types].xml", {"docprops/thumbnail.jpeg"}, notes)
    check("F049 a single-quoted PartName Override is dropped",
          b"thumbnail" not in out, out)
    rec = {"id": "run-1", "kind": "review"}
    check("F056 a legacy marker naming a foreign run_id is not this run's",
          pp._trial_marker_names_this_run({"run_id": "someone-else"}, rec) is False
          and pp._trial_marker_names_this_run({"run_id": "run-1"}, rec) is True)


# ---------------------------------------------------------------- adapters/secrets
def test_secrets() -> None:
    print("\n== F022/F024/F025/F026: credentials in argv/records and transport ==")
    import paper_qwen_agent as q
    import paper_dots_agent as dots
    import agent_common.model_runtime as rt
    # The F022 assertions are about an explicit base URL. An ambient provider
    # key (`DOTS_API_KEY` in the mechanical test gate's environment) outranks
    # the URL secret by design, so leaving it set makes the result depend on
    # the caller's shell rather than on the splitting code under test. Clear
    # the provider variables for these two calls and restore them afterwards:
    # the assertion is unchanged, the URL secret must still be split off AND
    # reach the API-key channel.
    _ambient = {name: os.environ.pop(name, None)
                for name in ("PAPER_QWEN_API_KEY", "PAPER_DOTS_API_KEY",
                             "DOTS_API_KEY")}
    try:
        cfg = q.config(argparse.Namespace(
            base_url="https://user:sekret@host/v1?api_key=qsecret&model=m"))
        check("F022 qwen base URL carries no credential",
              "sekret" not in cfg["base_url"] and "qsecret" not in cfg["base_url"]
              and cfg["api_key"] == "sekret", cfg)
        cfg = dots.config(argparse.Namespace(
            base_url="https://user:dsecret@host/v1"))
        check("F022 dots base URL carries no credential",
              "dsecret" not in cfg["base_url"] and cfg["api_key"] == "dsecret",
              cfg)
    finally:
        for _name, _value in _ambient.items():
            if _value is not None:
                os.environ[_name] = _value
    sel = rt.AgentSelection(harness="dsh", model="m", legacy="", model_name="m",
                            prep_json={"api_key": "supersecret"})
    check("F024 AgentSelection repr redacts prep_json", "supersecret" not in repr(sel))
    check("F025 short HTTP-error reads are guarded",
          "could not read the HTTP" in src("paper_qwen_agent.py")
          and "could not read the HTTP" in src("paper_dots_agent.py"))
    check("F026 a refused redirect is classified permanent",
          q._permanent_transport_error("HTTP 302 redirect refused") is True
          and q._permanent_transport_error("timed out") is False)


# ---------------------------------------------------------------- tracking/helpers
def test_tracking_and_sandbox() -> None:
    print("\n== F036/F037/F039/F040/F051/F065/F069: tracking and output dirs ==")
    d = scratch("f036_")
    def mk(name, texts):
        p = d / name
        body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in texts)
        doc = (f'<w:document {W} xmlns:mc="http://schemas.openxmlformats.org/'
               f'markup-compatibility/2006" xmlns:w14="http://schemas.microsoft.com/'
               f'office/word/2010/wordml" mc:Ignorable="w14"><w:body>{body}'
               f'</w:body></w:document>')
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", doc)
            z.writestr("[Content_Types].xml", "<Types/>")
        return p
    base, cand = mk("base.docx", ["same", "old"]), mk("cand.docx", ["same", "new"])
    out = d / "out.docx"
    r = pp.write_docx_logging_fallback(base, cand, out, "base", "tracking unavailable")
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    check("F036 the logging fallback passes document.xml (namespaces survive)",
          r.get("ok") is True and "xmlns:w14" in xml and _parses(xml), r.get("error"))

    h = src("paper_pipeline_parts/p18_helpers.py")
    check("F037 the reader uses os.read and never closes a live pipe",
          "os.read(pipe.fileno(), 65536)" in h
          and "Never close a pipe a live reader" in h)
    drv = src("paper_pipeline_parts/p08_selection_driver.py")
    check("F039 the aux marker is read through the no-follow bounded reader",
          "read_regular_file(marker, MAX_PAYLOAD_BYTES)" in drv)
    check("F040 the selfcheck mailbox is opened once with O_NOFOLLOW",
          "_open_regular_no_follow(request)" in drv)
    post = src("paper_pipeline_parts/p06_postchecks.py")
    check("F051 template visuals use safe_mkdir + atomic copies",
          "safe_mkdir(sb / VISUAL_TEMPLATE_DIR)" in post
          and "write_bytes_atomic(dest / rec[\"pdf\"]" in post)
    prof = src("paper_pipeline_parts/p19_profiles.py")
    check("F065 the frozen-review tree uses safe_mkdir",
          "safe_mkdir(sb / GUIDED_REVIEW_DIR)" in prof)
    confl = src("paper_pipeline_parts/p20_judge_conflicts.py")
    check("F069 the conflict sandbox uses safe_mkdir",
          'safe_mkdir(ctx.reports_dir / F"conflict_check_round{int(r)}")' in confl)


# ---------------------------------------------------------------- report/format
def test_report_and_format() -> None:
    print("\n== F052/F073/F074/F076/F079/F080/F081/F082/F083/F084/F086/F087 ==")
    d = scratch("f052_")
    f = d / "ART.md"
    f.write_text("| item | disposition notes |\n|---|---|\n| x | OK |\n",
                 encoding="utf-8")
    check("F052 a renamed disposition column still runs the shared checks",
          bool(pp._disposition_table_problems(f)), pp._disposition_table_problems(f))

    dup = d / "dup.docx"
    doc = f'<w:document {W}><w:body><w:p/></w:body></w:document>'
    with zipfile.ZipFile(dup, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'content-types"><Default Extension="xml" ContentType="application/xml"/></Types>')
        z.writestr("word/document.xml", doc)
        z.writestr("word/document.xml", doc)
    res = fmt.analyse_package(dup, dict(fmt.POLICY_DEFAULTS))
    check("F073 a duplicate-member DOCX is not reported clean",
          any(r.get("rule") == "FMT-X1" for r in res["rows"]), res["rows"])

    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            'relationships" xmlns:pkg="http://schemas.openxmlformats.org/package/2006/'
            'relationships"><pkg:Relationship Id="rId1" Type="http://x/header" '
            'Target="header1.xml"/><!-- <Relationship Id="rId2" Type="http://x/header" '
            'Target="header2.xml"/> --></Relationships>')
    ids = [r["id"] for r in fmt._rels_entries(rels)]
    check("F074 prefixed rels parse and comments are not live",
          ids == ["rId1"], ids)

    check("F076 heading/URL/proofing rules are finding-tier",
          all(fmt.tier_of(x) == "finding" for x in
              ("FMT-T3a", "FMT-T3b", "FMT-T6a", "FMT-T6f", "FMT-T7a",
               "FMT-T7b", "FMT-S5")))
    check("F079 an explicit min_figure_text_pt=0 disables FMT-IM6",
          fmt.figure_text_size_rows(d / "none.docx",
                                    {"min_figure_text_pt": 0,
                                     "figure_text": {"min_pt": 80}}) == [])
    sl = {"sentence_words": {"methods": 61}, "paragraph_words": 250}
    mrows = [r for r in fmt.long_text_rows(
        [" ".join(["word"] * 61) + "."], [False], ["methods"], style_limits=sl)
        if r["rule"] == "FMT-T9c" and "long sentence" in r["evidence"]]
    check("F080 a venue-declared methods sentence bar is finding-tier",
          bool(mrows) and mrows[0]["tier"] == "finding", mrows[:1])

    # R01: after a write, repair-layout must re-scan the referenced header/
    # footer parts. Header1 has a fixable duplicate PAGE paragraph (so a change
    # is written); header2 has two PAGE fields in ONE paragraph, which the
    # fixer leaves to the author, so FMT-S10 must remain and ok must be false.
    def _field_runs(n):
        return (f'<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                f'<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
                f'<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                f'<w:r><w:t>{n}</w:t></w:r>'
                f'<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    hdr1 = f'<w:hdr {W}><w:p>{_field_runs(1)}</w:p><w:p>{_field_runs(2)}</w:p></w:hdr>'
    hdr2 = f'<w:hdr {W}><w:p>{_field_runs(1)}{_field_runs(2)}</w:p></w:hdr>'
    doc_r01 = (f'<w:document {W} {R}><w:body><w:p><w:r><w:t>Body.</w:t></w:r></w:p>'
               f'<w:sectPr><w:headerReference w:type="default" r:id="rIdH1"/>'
               f'<w:headerReference w:type="first" r:id="rIdH2"/>'
               f'</w:sectPr></w:body></w:document>')
    rels_r01 = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                'relationships"><Relationship Id="rIdH1" Type="http://x/header" '
                'Target="header1.xml"/><Relationship Id="rIdH2" Type="http://x/header" '
                'Target="header2.xml"/></Relationships>')
    r01 = d / "r01.docx"
    with zipfile.ZipFile(r01, "w") as z:
        z.writestr("word/document.xml", doc_r01)
        z.writestr("word/header1.xml", hdr1)
        z.writestr("word/header2.xml", hdr2)
        z.writestr("word/_rels/document.xml.rels", rels_r01)
    rep01 = fmt.repair_layout_package(r01, d / "r01.out.docx", dict(fmt.POLICY_DEFAULTS))
    check("R01 repair-layout still reports FMT-S10 after a written repair",
          rep01["ok"] is False
          and any(r.get("rule") == "FMT-S10"
                  and str(r.get("location", "")).endswith("header2.xml")
                  for r in rep01["remaining"]), rep01)

    rel = d / "rel.docx"
    with zipfile.ZipFile(rel, "w") as z:
        z.writestr("word/_rels/document.xml.rels",
                   "<Relationships><Relationship Id='rId1' Type='http://x/image' "
                   "Target='media/i.png'/></Relationships>")
    with zipfile.ZipFile(rel) as z:
        got = fmt.part_rels(z, "word/document.xml")
    check("F081 part_rels reads single-quoted attributes",
          got == {"rId1": "media/i.png"}, got)

    s = src("paper_docx_format_parts/p03_report_cli.py")
    check("F082 absolute template relationship targets are normalised",
          'rel = norm[len("word/"):] if norm.startswith("word/") else norm' in s)
    doc = (f'<w:document {W} xmlns:rel="http://schemas.openxmlformats.org/'
           f'officeDocument/2006/relationships"><w:body><w:sectPr>'
           f'<w:headerReference w:type="default" rel:id="rId7"/></w:sectPr>'
           f'</w:body></w:document>')
    parts = {"word/_rels/document.xml.rels":
             b'<Relationships><Relationship Id="rId7" Type="http://x/header" '
             b'Target="header1.xml"/></Relationships>'}
    check("F083 header/footer references use the bound relationship prefix",
          fmt.referenced_header_footer_parts(parts, doc) == {"word/header1.xml"})
    check("F084 descriptive header/footer part names are remapped",
          "header[^/]*|footer[^/]*" in s)
    check("F086 an over-long PDF object number is skipped, not raised",
          fmt._pdf_object_bodies(b"9" * 5000 + b" 0 obj\n<< >>\nendobj\n") == {})
    check("F087 the page-budget gap is emitted without a PDF",
          "elif pages is None and _max is not None:" in s)


# ---------------------------------------------------------------- styles/counting
def test_styles_and_counting() -> None:
    print("\n== F058/F059/F090/F091: cover letter, TeX prose and styles ==")
    check("F058 'Sincerely, The Authors' closes the letter",
          bool(pp.LENGTH_COVER_CLOSING_RE.match("Sincerely, The Authors")))
    out, _caps, _end = pp._tex_length_scan(
        "\\section{Results} We found a significant effect.\n")
    check("F059 prose sharing a \\section line is still counted",
          "We found a significant effect." in " ".join(out), out)
    d = scratch("f090_")
    p = d / "s.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document {W}><w:body><w:p><w:pPr>'
                   '<w:pStyle w:val=\'Heading1\'/></w:pPr></w:p></w:body></w:document>')
        z.writestr("word/styles.xml",
                   f'<w:styles {W}><w:style w:styleId=\'Heading1\'/></w:styles>')
    check("F090 single-quoted style ids are visible",
          "Heading1" in pp._style_usage(p) and "Heading1" in pp._defined_styles(p))
    t = d / "t.docx"
    with zipfile.ZipFile(t, "w") as z:
        z.writestr("word/document.xml", f'<w:document {W}><w:body/></w:document>')
        z.writestr("word/header1.xml",
                   f'<w:hdr {W}><w:p><w:r><w:t>six word template guide sentence '
                   f'here</w:t ></w:r></w:p></w:hdr>')
    check("F091 template prose on a whitespace close is not protected",
          "word/header1.xml" not in pp._protected_template_parts(t))


# ---------------------------------------------------------------- facts/chunking
def _u(text: str) -> dict:
    return {"text": text, "norm": text.lower(),
            "tokens": text.lower().replace(".", "").split(), "document": "a.md"}


def test_facts_and_dedup() -> None:
    print("\n== F053/F054/F055/F057/F064: facts, units and containment ==")
    b, c = _u("The dose was 5 mg."), _u("The dose was 5 ml.")
    check("F053 a single-digit value+unit change is reported",
          bool(pp._fact_unit_change_examples([b], [c], pairs=[(b, c)])))
    b2, c2 = _u("The dose was 55 mg."), _u("The dose was 55 mg or 55 ml.")
    check("F054 an added second unit is a new fact",
          bool(pp._fact_unit_change_examples([b2], [c2], pairs=[(b2, c2)])))
    _line, words, _doc = pp.dedup_location_of(
        "a/very/long/path/to/the/manuscript/paper.md lines 42: only four short words")
    check("F055 the minimum-word test tokenizes the excerpt, not the location",
          len(words) < pp.DEDUP_MIN_WORDS, words)
    e1 = ('main.md line 12: "the patient\'s dose was reduced from 55 mg to 20 mg '
          'after two weeks of treatment."')
    e2 = ('main.md line 12: "the patient\'s dose was reduced from 55 mg to 25 mg '
          'after two weeks of treatment."')
    l1, l2 = pp.dedup_location_of(e1), pp.dedup_location_of(e2)
    check("F055 an apostrophe inside a quoted excerpt does not truncate it",
          len(l1[1]) >= pp.DEDUP_MIN_WORDS and len(l2[1]) >= pp.DEDUP_MIN_WORDS,
          (l1, l2))
    check("F055 the two quoted findings merge under dedup_mode=location",
          pp.dedup_rows_match("M20", l1, "M20", l2) is True, (l1, l2))
    check("F057 a bare single digit is not a fact but `5 mg` is",
          pp._short_text_carries_fact("3") is False
          and pp._short_text_carries_fact("5 mg") is True)
    base = _u("The treatment was effective in the cohort.")
    check("F064 another sentence's negation does not defeat containment",
          pp._content_unit_contained(
              base, [_u("The treatment was effective in the cohort. "
                        "The drug was not toxic.")]) is True
          and pp._content_unit_contained(
              base, [_u("The treatment was not effective in the cohort. "
                        "The drug was safe.")]) is False)


# ---------------------------------------------------------------- conflicts/resume
def test_conflicts_and_resume() -> None:
    print("\n== F066/F071/F106: conflicts and continuation ==")
    check("F066 a summary-only conflict is dropped",
          pp._normalize_llm_conflicts([{
              "kind": "contradiction", "member": "A", "opponent": "B",
              "summary": "they disagree"}]) == [])
    kept, rejected = pp._validate_llm_conflicts(
        [{"member": "A", "opponent": "B", "judges": ["j1"], "summary": "x",
          "evidence": []}],
        [{"target": "A", "opponent": "B", "judge_run": "j1", "reason": "r"}])
    check("F066 a conflict with no quote is rejected",
          not kept and rejected, (kept, rejected))

    s = src("paper_pipeline_parts/p08_selection_driver.py")
    check("F071 a process-level failure clears the stale postcheck",
          'rec.pop("postcheck", None)' in s)
    rec = {"id": "revise_1", "status": "failed", "last_error": "timeout after 900s"}
    check("F071 a process-level failure is still a continuation candidate",
          bool(pp.resume_unfinished_reason(type("C", (), {})(), rec)))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        argv, _key, reason, _mode = pp.resume_gate(
            type("C", (), {})(), {"id": "revise_1", "status": "failed",
                                  "last_error": "timeout"}, [])
    check("F106 an empty continuation command is reported, not silent",
          argv == [] and "[resume]" in buf.getvalue(), buf.getvalue())


# ---------------------------------------------------------------- harness/ranking
def test_harness_and_docs() -> None:
    print("\n== F092/F093/F102/F103: test harness and ranking docs ==")
    sys.path.insert(0, str(ROOT / "paper-skills" / "tests"))
    import validate_skill as v
    # A unique HERMETIC directory outside the SYSTEM temp tree and outside the
    # skill tree: the old hard-coded debug_runs path mutated an unrelated run
    # and its cleanup could delete operator data (F080). A fresh checkout does
    # not carry the ignored `tmp/` directory, so create its parent first, and
    # fall back to a non-temp cache dir outside the checkout when the checkout
    # itself is read-only: the refusal needs a non-empty path that is NOT under
    # `tempfile.gettempdir()`, or the gate deletes it instead of refusing.
    base = ROOT / "tmp"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = Path.home() / ".cache" / "paper-refine-tests"
        base.mkdir(parents=True, exist_ok=True)
    keep = Path(tempfile.mkdtemp(prefix="s092-", dir=base))
    (keep / "precious.txt").write_text("keep", encoding="utf-8")
    try:
        refused = False
        try:
            v._fresh_run_dir(str(keep), str(ROOT / "paper-skills"))
        except SystemExit:
            refused = True
        check("F092 a non-empty run dir outside the temp tree is refused",
              refused and (keep / "precious.txt").exists())
    finally:
        shutil.rmtree(keep, ignore_errors=True)

    ids = re.findall(r'check\("([A-Za-z]+\d+)\b',
                     src("paper-skills/tests/validate_skill.py"))
    check("F093 every validate_skill check id is unique",
          len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1])
    check("F093 the README check count matches the unique receipts",
          "# 52 checks" in src("paper-skills/README.md"))
    ranking = src("paper_pipeline_parts/ranking.py")
    check("F102 the docs name the ordered census as the leading key",
          "defect_prefix_census  the ORDERED" in ranking)
    check("F103 the docs no longer promise an `id` final rung",
          "then the mean, IQR and\n#     digest." in ranking)


def main() -> int:
    test_docx_whitespace_closes()
    test_venues()
    test_feedback_and_gates()
    test_sanitizers()
    test_secrets()
    test_tracking_and_sandbox()
    test_report_and_format()
    test_styles_and_counting()
    test_facts_and_dedup()
    test_conflicts_and_resume()
    test_harness_and_docs()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
        return 1
    print("ALL fix_bugs_20261122_wave1 REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

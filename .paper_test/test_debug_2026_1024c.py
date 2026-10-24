#!/usr/bin/env python3
"""Regressions for the 2026-10-24c debug round.

Each check pins a defect reproduced against 5490b6c and the behaviour around it
that must keep working. Run: python3 .paper_test/test_debug_2026_1024c.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import struct
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_c24c_pipeline", WS / "paper_pipeline.py")
fmt = _load("paper_c24c_format", WS / "paper_docx_format.py")

FAILS = []
SCRATCH = Path(tempfile.mkdtemp(prefix="paper_c24c_"))


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def tmpdir(name: str) -> Path:
    path = SCRATCH / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_docx(path: Path, paragraphs: list, extra: dict = None) -> Path:
    W = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'
                   for t in paragraphs)
    xml = f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def png_bytes(w: int, h: int) -> bytes:
    """A minimal valid RGB PNG, for the image-geometry checks."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def zotero_field(props: str) -> str:
    return ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> ADDIN ZOTERO_ITEM CSL_CITATION '
            '{"citationID":"abc","properties":' + props +
            ',"citationItems":[]} </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>[1]</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')


# ---------------------------------------------------------------------------
# C1 -- a non-object Zotero `properties` value must not crash a scan/fix
# ---------------------------------------------------------------------------
def test_zotero_malformed_properties():
    print()
    print("== C1: malformed Zotero properties is in-scope input, not a crash ==")
    xml = zotero_field('["x"]')
    for fn in (fmt.zotero_citation_state, fmt.zotero_parity_rows,
               fmt.zotero_refresh_document):
        try:
            fn(xml)
            err = ""
        except Exception as e:                                        # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
        check(f"{fn.__name__} handles a list properties value without raising", not err, err)
    # The healthy object shape still reads its marker.
    clean = zotero_field('{"formattedCitation":"[1]"}')
    state = fmt.zotero_citation_state(clean)
    check("the object-shaped properties still yields its marker",
          state["fields"] and state["fields"][0]["marker"] == "[1]", str(state["fields"][:1]))


# ---------------------------------------------------------------------------
# C2/M7 -- sentence deletion must not widen over a URL tail or overlap
# ---------------------------------------------------------------------------
def test_sentence_split_and_windows():
    print()
    print("== C2/M7: the deleter's sentence windows are exact and non-overlapping ==")
    text = ("The old code lives at github.com/a/y. "
            "This sentence is legitimate content that must survive.")
    spans = fmt.sentence_spans(text)
    check("a URL path tail 'y.' does not merge the next sentence", len(spans) == 2,
          str([(a, b, text[a:b]) for a, b in spans]))
    cluster = "The effect was strongest in cluster A. By contrast, it faded."
    check("a cluster label 'A.' does not merge the next sentence",
          len(fmt.sentence_spans(cluster)) == 2, str(fmt.sentence_spans(cluster)))
    by_name = "This was written by J. Smith. It still matters."
    check("a name context still keeps 'J. Smith' together",
          len(fmt.sentence_spans(by_name)) == 2
          and by_name[slice(*fmt.sentence_spans(by_name)[0])]
          == "This was written by J. Smith.",
          str(fmt.sentence_spans(by_name)))
    # The last window's leading-whitespace eat used to overlap the previous
    # window; rewrite_text_spans kept only the first edit and the whole removal
    # was refused with "the edit did not reproduce ...".
    para = "First pointer a. Second pointer b."
    windows = fmt.sentence_windows(para, [(14, 15), (32, 33)])
    check("sentence windows never overlap", all(windows[i][0] >= windows[i - 1][1]
                                                for i in range(1, len(windows))),
          str(windows))
    doc = tmpdir("c2") / "c2.docx"
    make_docx(doc, [text])
    out = tmpdir("c2") / "out.docx"
    finder = lambda t: [(t.find("github.com/a/y"), t.find("github.com/a/y") + 12)]
    res = fmt.strip_reference_sentences(doc, out, finder)
    got = "\n".join(pp._docx_paragraphs(out)) if out.is_file() else ""
    check("deleting the pointer keeps the following legitimate sentence",
          res.get("ok") and "legitimate content that must survive" in got, f"{res} -> {got!r}")
    doc2 = tmpdir("c2") / "c2b.docx"
    make_docx(doc2, [para])
    out2 = tmpdir("c2") / "out2.docx"
    res2 = fmt.strip_reference_sentences(doc2, out2, lambda t: [(14, 15), (32, 33)])
    check("two pointer sentences in one paragraph are both removed",
          res2.get("ok") and not res2.get("skipped") and res2.get("removed")
          and len(res2["removed"]) == 2, json.dumps(res2)[:400])


# ---------------------------------------------------------------------------
# H1 -- step 9 must not rewrite an unstyled reference list's titles
# ---------------------------------------------------------------------------
def test_reference_titles_preserved():
    print()
    print("== H1: an unstyled reference list is never rewritten ==")
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = ("<w:p><w:r><w:t>Body</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>The color was clear. Another color result. A colour note.</w:t>"
            "</w:r></w:p>"
            "<w:p><w:r><w:t>References</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>1. Colour analysis of tumours. Nature Methods 11, 430 (2014)."
            "</w:t></w:r></w:p>")
    xml = f'<w:document {W}><w:body>{body}</w:body></w:document>'
    policy = dict(fmt.POLICY_DEFAULTS, term_spelling="dominant")
    new, changes, _meta = fmt.fix_document(xml, {}, policy)
    text = fmt.text_of(new)
    check("a reference title keeps its quoted spelling", "Colour analysis" in text, changes)
    check("the body's minority spelling is still normalized", "A color note." in text, text)


# ---------------------------------------------------------------------------
# H2 -- e-mail glue inside the address token is detected and repaired
# ---------------------------------------------------------------------------
def test_email_glue():
    print()
    print("== H2: e-mail glue is detected from the address token itself ==")
    glued = "Correspondence: lead contactzhenxie@tsinghua.edu.cn"
    rows = fmt.correspondence_glue_rows([glued], [False])
    check("the documented contactzhenxie@ glue produces an FMT-X2 row",
          len(rows) == 1 and rows[0]["rule"] == "FMT-X2", str(rows))
    spans = [sp for sp in fmt.hygiene_spans(
        '<w:p><w:r><w:t xml:space="preserve">' + glued + '</w:t></w:r></w:p>')
        if sp["rule"] == "FMT-X2" and sp["fix"] == "mechanical"]
    check("the glue repair is a mechanical one-space insertion", len(spans) == 1, str(spans))
    if spans:
        para = ('<w:p><w:r><w:t xml:space="preserve">' + glued + '</w:t></w:r></w:p>')
        new, applied = fmt.rewrite_text_spans(
            para, [(spans[0]["start"], spans[0]["end"], spans[0]["repl"])])
        check("the repair actually inserts the space",
              fmt.text_of(new) == "Correspondence: lead contact zhenxie@tsinghua.edu.cn",
              fmt.text_of(new))
    after = "Contact zhenxie@tsinghua.edu.cnHowever we proceed."
    arows = fmt.correspondence_glue_rows([after], [False])
    check("a word absorbed by the TLD is reported as glue after",
          len(arows) == 1 and "glued to the text after it" in arows[0]["evidence"],
          str(arows))
    for clean in ("A healthy zhenxie@tsinghua.edu.cn address.",
                  "contact@tsinghua.edu.cn",
                  "user@myExample.com is valid"):
        check(f"a healthy address is not re-spaced: {clean}",
              fmt.correspondence_glue_rows([clean], [False]) == [])


# ---------------------------------------------------------------------------
# M8/M9 -- scan/fix agreement on tables and orphan header/footer parts
# ---------------------------------------------------------------------------
def test_scan_fix_alignment():
    print()
    print("== M8/M9: the fixer's fence agrees with the scanner's reach ==")
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    xml = (f'<w:document {W}><w:body><w:tbl><w:tr><w:tc><w:p><w:r>'
           f'<w:br w:type="page"/></w:r></w:p></w:tc></w:tr></w:tbl>'
           f'<w:p><w:r><w:t>Body text.</w:t></w:r></w:p></w:body></w:document>')
    rows = fmt.analyse_document(xml, {}, dict(fmt.POLICY_DEFAULTS), "x.docx")["rows"]
    s1 = [r for r in rows if r["rule"] == "FMT-S1"]
    check("an in-table page break is reported as manual, not mechanical",
          len(s1) == 1 and s1[0]["fix"] == "manual", str(s1))
    src8, out8 = tmpdir("m8") / "x.docx", tmpdir("m8") / "y.docx"
    with zipfile.ZipFile(src8, "w") as z:
        z.writestr("word/document.xml", xml)
    fixed8 = fmt.fix_package(src8, out8, dict(fmt.POLICY_DEFAULTS))
    check("fix succeeds on the in-table FMT-S1 fixture",
          fixed8["ok"] and not fixed8.get("verified", {}).get("remaining_mechanical_rules"),
          f"{fixed8.get('error')} / {fixed8.get('verified', {}).get('remaining_mechanical_rules')}")

    d = tmpdir("m89")
    src, out = d / "x.docx", d / "y.docx"
    doc = (f'<?xml version="1.0"?><w:document {W} '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
           '<w:body><w:p><w:r><w:t>Body.</w:t></w:r></w:p>'
           '<w:sectPr><w:footerReference w:type="default" r:id="rId1"/></w:sectPr>'
           '</w:body></w:document>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.'
            'openxmlformats.org/officeDocument/2006/relationships/footer" '
            'Target="footer1.xml"/></Relationships>')
    page = '<w:p><w:r><w:instrText> PAGE </w:instrText></w:r></w:p>'
    WP = ('xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
          'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
          'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')

    def draw():
        return ('<w:r><w:drawing><wp:inline><wp:extent cx="914400" cy="914400"/>'
                '<a:graphic><a:graphicData><pic:pic><pic:blipFill>'
                '<a:blip r:embed="rId2"/></pic:blipFill></pic:pic>'
                '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>')

    # A distorted 10x20 image in EACH footer: the referenced footer1's FMT-IM1
    # must be scanned AND repaired; the orphan footer2's must be neither, or
    # `fix` reports ok while the scan still shows a mechanical row.
    f1 = (f'<?xml version="1.0"?><w:ftr {W} {WP}><w:p><w:r><w:t>Page</w:t></w:r>'
          f'{draw()}</w:p>{page}</w:ftr>')
    # One paragraph carrying a visible label AND two PAGE fields: the fixer's
    # page_field_fixes refuses that shape (len(spans) <= 1), which is the shape
    # that made an orphan part fail the whole fix.
    f2 = (f'<?xml version="1.0"?><w:ftr {W} {WP}><w:p><w:r><w:t>Page 2</w:t></w:r>'
          f'{draw()}'
          '<w:r><w:instrText> PAGE </w:instrText></w:r>'
          '<w:r><w:instrText> PAGE </w:instrText></w:r></w:p></w:ftr>')
    frels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
             'package/2006/relationships"><Relationship Id="rId2" Type="http://schemas.'
             'openxmlformats.org/officeDocument/2006/relationships/image" '
             'Target="media/image1.png"/></Relationships>')
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("word/document.xml", doc)
        z.writestr("word/_rels/document.xml.rels", rels)
        z.writestr("word/footer1.xml", f1)
        z.writestr("word/_rels/footer1.xml.rels", frels)
        z.writestr("word/footer2.xml", f2)
        z.writestr("word/_rels/footer2.xml.rels", frels)
        z.writestr("word/media/image1.png", png_bytes(10, 20))
    scan = fmt.analyse_package(src, dict(fmt.POLICY_DEFAULTS))
    check("the scanner ignores the orphan footer2", not [r for r in scan["rows"]
                                                        if r["rule"] == "FMT-S10"])
    im1 = [r for r in scan["rows"] if r["rule"] == "FMT-IM1"]
    check("only the referenced footer's image geometry is scanned",
          len(im1) == 1 and im1[0]["location"].startswith("footer1.xml"),
          str([r["location"] for r in im1]))
    fixed = fmt.fix_package(src, out, dict(fmt.POLICY_DEFAULTS))
    check("fix does not fail on a document the scan calls clean", fixed["ok"],
          f"{fixed.get('error')} / {fixed.get('verified', {}).get('remaining_mechanical_rules')}")
    check("the orphan part is not rewritten",
          zipfile.ZipFile(src).read("word/footer2.xml")
          == zipfile.ZipFile(out).read("word/footer2.xml"))
    after = fmt.analyse_package(out, dict(fmt.POLICY_DEFAULTS))
    check("no mechanical image row survives the fix",
          not [r for r in after["rows"] if r["rule"] == "FMT-IM1"],
          str([r["location"] for r in after["rows"] if r["rule"] == "FMT-IM1"]))


# ---------------------------------------------------------------------------
# M3 -- the audit's confirmed count is the kept set, not kept - adds
# ---------------------------------------------------------------------------
def test_audit_effect():
    print()
    print("== M3: confirmed = the frozen findings the auditor kept ==")
    frozen = [{"id": f"F{i}"} for i in range(10)]
    split = pp.apply_audit_to_findings(
        frozen, {"dispositions": [{"id": "F0", "verdict": "drop"}],
                 "adds": [{"id": "AU-1"}, {"id": "AU-2"}]})
    effect = pp.audit_effect_summary(split)
    check("10 frozen, 1 dropped, 2 adds -> confirmed 9", effect["confirmed"] == 9, str(effect))
    check("confirmed + dropped equals the frozen count",
          effect["confirmed"] + effect["dropped"] == len(frozen), str(effect))
    check("confirmed + added equals the effective count",
          effect["confirmed"] + effect["added"] == effect["effective"], str(effect))


# ---------------------------------------------------------------------------
# G2 -- an all-caps `unable` reason is a reason
# ---------------------------------------------------------------------------
def test_unable_reason_case():
    print()
    print("== G2: `unable -- HPC QUOTA EXCEEDED` states a reason ==")
    check("an all-caps reason passes", pp._unable_reason_present("HPC QUOTA EXCEEDED"))
    check("an empty reason fails", not pp._unable_reason_present(""))


# ---------------------------------------------------------------------------
# M1 -- journal modes declare the feedback dependency the materializer enforces
# ---------------------------------------------------------------------------
def test_upstream_deps_journal():
    print()
    print("== M1: the journal materializer's dependency is in upstream_deps ==")

    class Ctx:
        pass

    ctx = Ctx()
    ctx.cfg = {"revision_mode": "transfer"}
    rec = {"kind": "rewrite", "round": 1}
    check("transfer-mode rewrite lists the feedback run",
          pp.upstream_deps(rec, ctx) == ["r1_a1", "r1_feedback"],
          str(pp.upstream_deps(rec, ctx)))
    check("transfer-mode review lists the feedback run",
          pp.upstream_deps({"kind": "review", "round": 1}, ctx) ==
          ["r1_a1", "r1_feedback"])
    ctx.cfg = {"revision_mode": "llm"}
    check("the no-journal path keeps its old dependency list",
          pp.upstream_deps(rec, ctx) == ["r1_a1"], str(pp.upstream_deps(rec, ctx)))


# ---------------------------------------------------------------------------
# M2 -- the read-only raw-data area is not repointed by the pipeline itself
# ---------------------------------------------------------------------------
def test_raw_data_repoint_scope():
    print()
    print("== M2: canonicalize repoints references OUTSIDE the read-only area only ==")
    d = tmpdir("m2")
    (d / "raw_figs").mkdir()
    (d / "raw_figs" / "counts.tsv").write_text("a\n", encoding="utf-8")
    (d / "raw_figs" / "run.py").write_text("open('raw_figs/counts.tsv')\n", encoding="utf-8")
    (d / "ms.tex").write_text("\\input{raw_figs/counts.tsv}\n", encoding="utf-8")
    warns = []
    res = pp.canonicalize_raw_data_dir(d, warns)
    check("the directory is renamed and the outside reference repointed",
          res["renamed"] and (d / "ms.tex").read_text(encoding="utf-8")
          == "\\input{raw_data/counts.tsv}\n", str(res))
    check("a file INSIDE the raw-data area is byte-identical",
          (d / "raw_data" / "run.py").read_text(encoding="utf-8")
          == "open('raw_figs/counts.tsv')\n", (d / "raw_data" / "run.py").read_text())


# ---------------------------------------------------------------------------
# M4 -- a required documentclass is not satisfied by a Word-only corpus
# ---------------------------------------------------------------------------
def test_required_documentclass():
    print()
    print("== M4: a required documentclass cannot silently pass with no LaTeX ==")
    d = tmpdir("m4")
    (d / "ms.md").write_text("# Introduction\n\nText.\n", encoding="utf-8")
    req = {"documentclass": "article", "mandatory_sections": [], "statements": [],
           "sections": []}
    conf = pp.scan_template_conformance([(d, "", ())], req)
    check("class_ok is false and names the required class",
          conf["class_ok"] is False and conf["required"]["documentclass"] == "article",
          json.dumps({k: conf[k] for k in ("class_ok", "required")}))


# ---------------------------------------------------------------------------
# M6 -- a legacy .doc form is not read as UTF-8 text
# ---------------------------------------------------------------------------
def test_legacy_doc_form():
    print()
    print("== M6: an unreadable .doc form is a recorded gap, not a clean read ==")
    d = tmpdir("m6")
    make_docx(d / "manuscript.docx",
              ["Software. FastQC 0.11 and STAR 2.7 were used."])
    (d / "reporting_summary.doc").write_bytes(b"\xd0\xcf\x11\xe0garbage software")
    rows = pp.scan_form_software_coverage(d)
    check("the .doc form gets the could-not-read row",
          len(rows) == 1 and "could not be read as text" in rows[0]["detail"], str(rows))
    check("the false 'no software inventory' row is gone",
          not any("carries no software inventory" in r["detail"] for r in rows), str(rows))


# ---------------------------------------------------------------------------
# G5/G6/G16/G17 -- DOCX writer/details
# ---------------------------------------------------------------------------
def test_docx_writer_details():
    print()
    print("== G5/G6/G16/G17: writer insertions, markers, tabs, remote templates ==")
    para = '<w:p><w:r><w:t>Correspondence:Zhen</w:t></w:r></w:p>'
    for pos in (0, 16):
        new, applied = fmt.rewrite_text_spans(para, [(pos, pos, " ")])
        check(f"a zero-length insertion at {pos} is applied",
              applied and fmt.text_of(new) != fmt.text_of(para),
              f"{applied} -> {fmt.text_of(new)!r}")
    split_para = '<w:p><w:r><w:t>abc</w:t><w:t>def</w:t></w:r></w:p>'
    new, _applied = fmt.rewrite_text_spans(split_para, [(3, 3, "X")])
    check("a zero-length insertion on a w:t boundary is emitted once",
          fmt.text_of(new) == "abcXdef", fmt.text_of(new))
    marked = ('<w:p><w:r><w:lastRenderedPageBreak/></w:r>'
              '<w:r><w:t>Hello</w:t></w:r></w:p>')
    new, _applied = fmt.rewrite_text_spans(marked, [(2, 3, "")])
    check("an edit keeps a standalone lastRenderedPageBreak marker",
          "lastRenderedPageBreak" in new, new)
    tabbed = ('<w:p><w:r><w:t>abc </w:t><w:tab/><w:t> def </w:t></w:r></w:p>')
    check("a w:tab splits visual_text_lines instead of counting as empty text",
          fmt.visual_text_lines(tabbed) == [(0, 4), (5, 10)],
          str(fmt.visual_text_lines(tabbed)))

    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    d = tmpdir("g17")
    src, out = d / "t.docx", d / "t-out.docx"
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/attachedTemplate" Target="file:///C:\\Users\\a\\t.dotx"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/attachedTemplate" Target="https://example.org/t.dotx"/>'
            '</Relationships>')
    settings = (f'<?xml version="1.0"?><w:settings {W} '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<w:attachedTemplate r:id="rId1"/>'
                '<w:attachedTemplate r:id="rId2"/></w:settings>')
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("word/document.xml", f'<w:document {W}><w:body/></w:document>')
        z.writestr("word/settings.xml", settings)
        z.writestr("word/_rels/settings.xml.rels", rels)
    res = fmt.strip_local_path_links(src, out)
    after = zipfile.ZipFile(out).read("word/settings.xml").decode("utf-8")
    check("the local attachedTemplate is removed", res["ok"] and "rId1" not in after, str(res))
    check("the remote attachedTemplate survives", 'r:id="rId2"' in after, after)


# ---------------------------------------------------------------------------
# H3 -- the winner reuse key comes from the field the round record carries
# ---------------------------------------------------------------------------
def test_winner_tracking_key():
    print()
    print("== H3: the round record carries `champion`, not `winner_id` ==")
    d = tmpdir("h3")
    root = d / "root"
    (root / "tracking").mkdir(parents=True)
    win = root / "round1_winner"
    win.mkdir()
    captured = {}

    class Ctx:
        pass

    ctx = Ctx()
    ctx.root = root
    ctx.pristine = d / "src"
    ctx.pristine.mkdir()
    ctx.reports_dir = d / "reports"
    ctx.reports_dir.mkdir()
    ctx.round_get = lambda r: {"champion": "w1", "winner_dir": "round1_winner"}
    ctx.rounds_count = lambda: 1
    ctx.cfg = {}
    ctx.run = lambda rid: None
    ctx.sandbox_of = lambda rec: root
    ctx.log = lambda *a, **k: None

    old_track = pp._track_one_entry
    old_compile = pp.compile_tracking_pdfs
    old_close = pp._close_tracking_entry
    old_fresh = pp.tracking_entry_is_fresh
    old_readme = pp.tracking_readme

    def fake_track(ctx_, entry, **kw):
        captured.setdefault("vids", []).append(kw.get("vid"))
        entry["comparisons"].append({"ok": True, "tool": "x", "cand_rel": "a",
                                     "baseline": "orig", "note": ""})

    try:
        pp._track_one_entry = fake_track
        pp.compile_tracking_pdfs = lambda *a, **k: None
        pp._close_tracking_entry = lambda *a, **k: None
        pp.tracking_entry_is_fresh = lambda *a, **k: False
        pp.tracking_readme = lambda *a, **k: "test readme"
        pp.run_difference_tracking(ctx, rounds=[1], versions=["w1"])
    finally:
        pp._track_one_entry = old_track
        pp.compile_tracking_pdfs = old_compile
        pp._close_tracking_entry = old_close
        pp.tracking_entry_is_fresh = old_fresh
        pp.tracking_readme = old_readme
    vids = captured.get("vids") or []
    check("the winner is tracked under the champion's version id",
          vids and vids[-1] == "w1", str(vids))


# ---------------------------------------------------------------------------
# L1 / G9 / G10 / L3 / cover / captions
# ---------------------------------------------------------------------------
def test_pipeline_text_rules():
    print()
    print("== L1/G9/G10/L3: abstract token, bare limits, attribute order, COVID-19 ==")
    got = pp._tex_length_scan(
        "\\newpage\\begin{abstract}\nAbstract words here.\\end{abstract}\n"
        "\\section{Intro}\nBody words.")
    check("a \\begin{abstract} not at column 0 is still an abstract",
          got[0][:2] == ["Abstract", "Abstract words here."], str(got))
    probs = []
    limits = pp._clean_length_limits({"abstract": 300, "main_text": 5000}, "x", probs)
    check("a bare-number length limit normalizes instead of being rejected",
          not probs and limits and limits["abstract"] == {"base": 300, "relaxation": 1.0},
          f"{limits} {probs}")
    check("COVID-19 does not bind to reference 19",
          not list(pp.INLINE_CITATION_RE.finditer("COVID-19 was studied.")),
          str([m.group(0) for m in pp.INLINE_CITATION_RE.finditer("COVID-19 was studied.")]))
    check("a real word+number citation still binds",
          [(m.group(1), m.group(2)) for m in
           pp.INLINE_CITATION_RE.finditer("single-cell43 analysis")] ==
          [("single-cell", "43")])
    # G10: OOXML attribute order is not significant. Word writes r:id before
    # w:type in some files; the positional reader returned no roles at all.
    d = tmpdir("c24")
    hf = d / "hf.docx"
    hf_xml = ('<?xml version="1.0"?><w:document '
              'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
              '<w:body><w:sectPr><w:headerReference r:id="rId1" w:type="default"/>'
              '</w:sectPr></w:body></w:document>')
    with zipfile.ZipFile(hf, "w") as z:
        z.writestr("word/document.xml", hf_xml)
    sig = pp._docx_hf_signature(hf)
    check("a headerReference with r:id before w:type still yields its role",
          sig.get("roles") == [("header", "default")], str(sig))
    # G13: a mark at the paragraph's FINAL offset (a trailing soft break) is
    # part of the emitted range; `< end` dropped it from the redline.
    out = []
    pp._emit_text(out, "abc ", [(0, 4, {"split": True, "element": None, "rpr": None})],
                  [(4, {"text": "<w:br/>"})], 0, 4, "eq", [0],
                  "2026-01-01T00:00:00Z")
    check("a trailing soft break mark is emitted by the redline",
          any(getattr(e, "tag", "").endswith("}br") for e in out),
          str([getattr(e, "tag", e) for e in out]))


def test_cover_and_caption():
    print()
    print("== cover close / caption label align with count_words.py ==")
    d = tmpdir("cover")
    letter = d / "cover_letter.md"
    letter.write_text(
        "Dear Editor,\n\n"
        "Regards the statistical concern, we reran the model and the result held.\n"
        "Best regards are due to the reviewers for a careful reading.\n\n"
        "Sincerely,\nThe Authors\n", encoding="utf-8")
    lines = letter.read_text(encoding="utf-8").splitlines()
    close_at = next(i for i, ln in enumerate(lines)
                    if pp.LENGTH_COVER_CLOSING_RE.match(ln.strip()))
    check("a body line starting 'Regards' is not the close",
          close_at == len(lines) - 2, f"close_at={close_at} candidates={lines[close_at]!r}")
    import subprocess
    r = subprocess.run([sys.executable,
                        str(WS / "paper-skills/paper-review/scripts/count_words.py"),
                        str(letter), "--section", "cover-letter", "--json"],
                       capture_output=True, text=True, cwd=str(WS))
    script = json.loads(r.stdout) if r.returncode == 0 else {}
    check("count_words.py uses the same close rule",
          script and script["rows"][0]["words"] > 0, r.stdout[-200:] + r.stderr[-200:])

    cap = "Fig | 1 | Legend words here now."
    check("the pipeline and count_words.py both read the piped label",
          bool(pp.CAPTION_START_RE.match(cap)) and
          bool(_count_words().CAPTION.match(cap)))
    check("a sentence starting 'Figure x.' is not a legend in either",
          not pp.CAPTION_START_RE.match("Figure x. This is a sentence.") and
          not _count_words().CAPTION.match("Figure x. This is a sentence."))


def _count_words():
    sys.path.insert(0, str(WS / "paper-skills/paper-review/scripts"))
    return _load("paper_c24c_countwords",
                 WS / "paper-skills/paper-review/scripts/count_words.py")


def test_bib_nested_braces():
    print()
    print("== L14: a nested-brace .bib value is skipped, not truncated ==")
    nested = "@article{x, title = {Growth was {100} percent higher}, journal = {Nature}}"
    check("a nested title contributes no truncated prose",
          fmt.bib_prose_paragraphs(nested) == [], str(fmt.bib_prose_paragraphs(nested)))
    check("a plain title is still returned",
          fmt.bib_prose_paragraphs("@article{x, title = {Growth was higher}}")
          == ["Growth was higher"])
    check("a field-less file still uses the text fallback",
          fmt.bib_prose_paragraphs("plain prose without fields")
          == ["plain prose without fields"])


def test_manual_count_and_symlink_guard():
    print()
    print("== manual-step count / readonly symlink / round-count separator ==")
    d = tmpdir("misc")
    manual = d / "MANUAL_STEPS.md"
    manual.write_text(
        "2024. We repeated the assay.\n"
        "3. Real item\n"
        "| h | h |\n| --- | --- |\n"
        "- also a bullet | with | pipes\n"
        "- real step\n", encoding="utf-8")
    check("a year is not a numbered manual step and a piped bullet counts once",
          pp.count_manual_steps(manual) == 3, str(pp.count_manual_steps(manual)))

    real = d / "real"
    real.mkdir()
    f = real / "a.csv"
    f.write_text("x", encoding="utf-8")
    os.chmod(f, 0o644)
    link = d / "link"
    os.symlink(real, link)
    pp.make_tree_readonly(link)
    import stat
    check("a symlinked evidence root is not chmod'ed through",
          stat.S_IMODE(f.stat().st_mode) == 0o644,
          oct(stat.S_IMODE(f.stat().st_mode)))

    check("an underscore is a round-count separator, not int(1_2)=12",
          pp.parse_round_counts("1_2", 2, "--rewrites") == [1, 2],
          str(pp.parse_round_counts("1_2", 2, "--rewrites")))


if __name__ == "__main__":
    try:
        test_zotero_malformed_properties()
        test_sentence_split_and_windows()
        test_reference_titles_preserved()
        test_email_glue()
        test_scan_fix_alignment()
        test_audit_effect()
        test_unable_reason_case()
        test_upstream_deps_journal()
        test_raw_data_repoint_scope()
        test_required_documentclass()
        test_legacy_doc_form()
        test_docx_writer_details()
        test_winner_tracking_key()
        test_pipeline_text_rules()
        test_cover_and_caption()
        test_bib_nested_braces()
        test_manual_count_and_symlink_guard()
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for name in FAILS:
            print("  -", name)
        raise SystemExit(1)
    print("ALL 2026-10-24c DEBUG REGRESSIONS PASSED")

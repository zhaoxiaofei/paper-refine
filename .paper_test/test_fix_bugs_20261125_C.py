#!/usr/bin/env python3
"""Regression checks for the 2026-11-25 02:31 fix-bugs wave, group C.

Every check pins a finding confirmed against this tree by re-reading the cited
code and reproducing it. The suite is hermetic: temp dirs only, no network, no
Word/Office, no TeX engine (the two shell/compile checks use stubs on PATH and
exercise the real wrappers).

Run:  python3 .paper_test/test_fix_bugs_20261125_C.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fmt = load("fixbugs1125c_fmt", "paper_docx_format.py")

FAILS = []
TMPDIRS = []


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def cleanup() -> None:
    for tmp in TMPDIRS:
        for p in [tmp, *tmp.rglob("*")]:
            if p.is_symlink():
                # chmod follows the link; never touch a target outside the fixture.
                continue
            with contextlib.suppress(OSError):
                if p.is_dir():
                    p.chmod(0o755)
                else:
                    p.chmod(0o644)
        shutil.rmtree(tmp, ignore_errors=True)


NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
</Types>"""
RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
</Relationships>"""
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="24"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:rPr><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="Caption"/></w:style>
<w:style w:type="paragraph" w:styleId="Bibliography"><w:name w:val="Bibliography"/></w:style>
<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr></w:style>
</w:styles>"""

PAGE_FIELD = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
              '<w:r><w:instrText> PAGE </w:instrText></w:r>'
              '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
              '<w:r><w:t>{n}</w:t></w:r>'
              '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def make_docx(path: Path, body: str, styles: str = STYLES,
              extra: dict | None = None, doc_rels: str | None = None) -> Path:
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document {NS}><w:body>{body}'
           '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>'
           '</w:body></w:document>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
        if doc_rels is not None:
            z.writestr("word/_rels/document.xml.rels", doc_rels)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def png_bytes(w: int, h: int) -> bytes:
    raw = b"".join(b"\x00" + b"\x40\x80\xc0" * w for _ in range(h))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


# ---------------------------------------------------------------- F025
def test_f025_partial_page_field_repair_is_not_published():
    print("\n== F025: a surviving FMT-S10 must not be verified as cleared ==")
    tmp = scratch("c_f025_")
    header = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              f'<w:p>{PAGE_FIELD.format(n=1)}</w:p>'
              f'<w:p><w:r><w:t xml:space="preserve">Page </w:t></w:r>'
              f'{PAGE_FIELD.format(n=2)}</w:p>'
              f'<w:p>{PAGE_FIELD.format(n=3)}</w:p>'
              '</w:hdr>')
    body = ('<w:p><w:r><w:t>Title</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Body text.</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Last.</w:t></w:r></w:p>')
    src = make_docx(tmp / "hdr.docx", body,
                    extra={"word/header1.xml": header}, doc_rels=DOC_RELS)
    # The document must actually reference the header (an orphan part is not
    # scanned); add the reference to the section it already carries.
    with zipfile.ZipFile(src) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["word/document.xml"] = parts["word/document.xml"].decode().replace(
        "<w:sectPr>",
        '<w:sectPr><w:headerReference w:type="default" r:id="rId7"/>').encode()
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in parts.items():
            z.writestr(n, d)
    policy = dict(fmt.load_policy(None))
    before = [r for r in fmt.analyse_package(src, policy)["rows"]
              if r["rule"] == "FMT-S10"]
    check("F025 the input has a mechanical FMT-S10 before the fix",
          bool(before) and before[0]["fix"] == "mechanical",
          str(before[:1]))
    out = tmp / "fixed.docx"
    rep = fmt.fix_package(src, out, policy)
    v = rep.get("verified") or {}
    check("F025 a partially repaired PAGE-field header is not published as clean",
          rep.get("ok") is False and "FMT-S10" in (v.get("remaining_mechanical_rules") or [])
          and not out.exists(),
          f"ok={rep.get('ok')} remaining={v.get('remaining_mechanical_rules')} "
          f"exists={out.exists()}")


# ---------------------------------------------------------------- F026
def test_f026_field_result_quotes_are_not_mechanical():
    print("\n== F026: a straight quote inside a Zotero result is not a "
          "mechanical FMT-T1 the fixer must rewrite ==")
    tmp = scratch("c_f026_")
    body = ('<w:p><w:r><w:t>Title</w:t></w:r></w:p>'
            '<w:p><w:r><w:t xml:space="preserve">A curly \u201cquote\u201d in prose.</w:t></w:r></w:p>'
            '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText> ADDIN ZOTERO_ITEM CSL_CITATION {"citationID":"c1"} </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t xml:space="preserve">Smith\'s "quoted" 2020</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
            '<w:p><w:r><w:t>Body text.</w:t></w:r></w:p>')
    src = make_docx(tmp / "qfield.docx", body)
    policy = dict(fmt.load_policy(None))
    policy["quote_style"] = "curly"
    out = tmp / "fixed.docx"
    rep = fmt.fix_package(src, out, policy)
    v = rep.get("verified") or {}
    check("F026 the fixer accepts the document and keeps the live field intact",
          rep.get("ok") is True and v.get("zotero_field_signature_kept") is True
          and out.exists(),
          f"ok={rep.get('ok')} sig={v.get('zotero_field_signature_kept')} "
          f"remaining={v.get('remaining_mechanical_rules')}")
    if out.exists():
        with zipfile.ZipFile(out) as z:
            fixed = z.read("word/document.xml").decode()
        check("F026 the field result text is carried through verbatim",
              'Smith\'s "quoted" 2020' in fixed, fixed[fixed.find("Smith") - 40:][:120])
        rows = [r for r in fmt.analyse_package(out, policy)["rows"]
                if r["rule"] == "FMT-T1"]
        check("F026 a quote held in a live field result is style-field/protected, "
              "never a mechanical row the fixer can never clear",
              bool(rows) and all(r["fix"] == "style-field" and r["protected"]
                                 for r in rows),
              str([(r["rule"], r["fix"], r["protected"]) for r in rows]))
    else:
        check("F026 the field result text is carried through verbatim", False,
              "no output was published")
        check("F026 a quote held in a live field result is style-field/protected, "
              "never a mechanical row the fixer can never clear", False,
              "no output was published")


# ---------------------------------------------------------------- F027
def test_f027_huge_decimal_attributes_do_not_crash():
    print("\n== F027: an unbounded decimal attribute is not an int() crash ==")
    tmp = scratch("c_f027_")
    big = "1" * 5000
    words = " ".join(["word"] * 30)
    body_a = ('<w:p><w:r><w:t>Title</w:t></w:r></w:p>'
              f'<w:p><w:pPr><w:ind w:firstLine="{big}"/></w:pPr>'
              f'<w:r><w:t>{words}.</w:t></w:r></w:p>')
    src_a = make_docx(tmp / "bigint.docx", body_a)
    policy = dict(fmt.load_policy(None))
    try:
        res_a = fmt.analyse_package(src_a, policy)
        ok_a = isinstance(res_a, dict) and isinstance(res_a.get("rows"), list)
        detail_a = f"rows={len(res_a.get('rows') or [])}"
    except Exception as e:  # noqa: BLE001 - the crash IS the finding
        ok_a, detail_a = False, f"{type(e).__name__}: {e}"
    check("F027a a 5000-digit w:firstLine does not abort the scan", ok_a, detail_a)

    body_b = ('<w:p><w:r><w:t>Title</w:t></w:r></w:p>'
              '<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="2000"/>'
              '<w:gridCol w:w="3000"/></w:tblGrid>'
              '<w:tr><w:tc><w:tcPr><w:tcW w:w="2000" w:type="dxa"/></w:tcPr>'
              '<w:p><w:r><w:t>ID</w:t></w:r></w:p></w:tc>'
              '<w:tc><w:tcPr><w:tcW w:w="3000" w:type="dxa"/></w:tcPr>'
              '<w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc></w:tr>'
              '<w:tr><w:tc><w:tcPr><w:tcW w:w="2000" w:type="dxa"/></w:tcPr>'
              f'<w:p><w:r><w:rPr><w:sz w:val="{big}"/></w:rPr>'
              '<w:t>D01M07AA0</w:t></w:r></w:p></w:tc>'
              '<w:tc><w:tcPr><w:tcW w:w="3000" w:type="dxa"/></w:tcPr>'
              '<w:p><w:r><w:t>x</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
              '<w:p><w:r><w:t>End.</w:t></w:r></w:p>')
    src_b = make_docx(tmp / "bigsz.docx", body_b)
    try:
        res_b = fmt.analyse_package(src_b, policy)
        ok_b = isinstance(res_b, dict) and isinstance(res_b.get("rows"), list)
        detail_b = f"rows={len(res_b.get('rows') or [])}"
    except Exception as e:  # noqa: BLE001
        ok_b, detail_b = False, f"{type(e).__name__}: {e}"
    check("F027b a 5000-digit w:sz in an identifier table cell does not abort "
          "the scan", ok_b, detail_b)


# ---------------------------------------------------------------- F028
def test_f028_scan_figures_unreadable_compression():
    print("\n== F028: scan-figures reports an unsupported-compression DOCX as "
          "unreadable (exit 2), not a traceback ==")
    tmp = scratch("c_f028_")
    src = make_docx(tmp / "badmethod.docx",
                    '<w:p><w:r><w:t>Title</w:t></w:r></w:p>')
    data = bytearray(src.read_bytes())
    eocd = data.rfind(b"PK\x05\x06")
    n = int.from_bytes(data[eocd + 10:eocd + 12], "little")
    pos = int.from_bytes(data[eocd + 16:eocd + 20], "little")
    for _ in range(n):
        assert data[pos:pos + 4] == b"PK\x01\x02", "central directory layout"
        data[pos + 10:pos + 12] = (99).to_bytes(2, "little")
        namelen = int.from_bytes(data[pos + 28:pos + 30], "little")
        extralen = int.from_bytes(data[pos + 30:pos + 32], "little")
        comlen = int.from_bytes(data[pos + 32:pos + 34], "little")
        pos += 46 + namelen + extralen + comlen
    bad = tmp / "badmethod.docx"
    bad.write_bytes(bytes(data))
    fig = tmp / "fig.png"
    fig.write_bytes(png_bytes(20, 10))
    proc = subprocess.run(
        [sys.executable, str(WS / "paper_docx_format.py"), "scan-figures",
         str(fig), "--from-docx", str(bad)],
        capture_output=True, text=True, timeout=180)
    blob = (proc.stdout or "") + (proc.stderr or "")
    check("F028 an unsupported compression method exits 2 with 'cannot read'",
          proc.returncode == 2 and "cannot read" in blob and "Traceback" not in blob,
          f"rc={proc.returncode} tail={blob.strip()[-300:]}")


# ---------------------------------------------------------------- F029
def test_f029_whitespace_closed_drawing_close():
    print("\n== F029: a legal whitespace-closed </w:drawing > is still scanned ==")
    tmp = scratch("c_f029_")
    png = tmp / "img1.png"
    png.write_bytes(png_bytes(200, 100))
    from docx import Document
    from docx.shared import Inches
    base = tmp / "base.docx"
    doc = Document()
    doc.add_paragraph("Title")
    # 2:1 source placed at 4:1 -> FMT-IM1 (distorted extent).
    doc.add_picture(str(png), width=Inches(2), height=Inches(0.5))
    doc.add_paragraph("End.")
    doc.save(base)
    with zipfile.ZipFile(base) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    doc_xml = parts["word/document.xml"].decode()
    check("F029 the fixture carries a </w:drawing> close to respell",
          "</w:drawing>" in doc_xml, doc_xml[doc_xml.find("<w:drawing"):][:120])
    results = {}
    for tag, close in (("exact", "</w:drawing>"), ("ws", "</w:drawing >")):
        out = tmp / f"{tag}.docx"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for n, d in parts.items():
                if n == "word/document.xml":
                    d = d.decode().replace("</w:drawing>", close).encode()
                z.writestr(n, d)
        rows = [r for r in fmt.analyse_package(out, fmt.load_policy(None))["rows"]
                if r["rule"] == "FMT-IM1"]
        results[tag] = rows
    check("F029 the same distorted image is FMT-IM1 with either close spelling",
          bool(results["exact"]) and len(results["exact"]) == len(results["ws"]),
          f"exact={[(r['rule'], r['location']) for r in results['exact']]} "
          f"ws={[(r['rule'], r['location']) for r in results['ws']]}")


# ---------------------------------------------------------------- F030
def test_f030_keepnext_repairs_the_live_element():
    print("\n== F030: the keepNext repair edits the live element, not a "
          "commented-out copy ==")
    tmp = scratch("c_f030_")
    body = ('<w:p><w:r><w:t>Title</w:t></w:r></w:p>'
            '<w:p><w:pPr><!-- <w:keepNext w:val="0"/> -->'
            '<w:pStyle w:val="Heading1"/><w:keepNext w:val="0"/></w:pPr>'
            '<w:r><w:t>Results</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Body text.</w:t></w:r></w:p>')
    src = make_docx(tmp / "keepnext.docx", body)
    policy = dict(fmt.load_policy(None))
    out = tmp / "fixed.docx"
    rep = fmt.fix_package(src, out, policy)
    check("F030 the fixer accepts the document", rep.get("ok") is True,
          f"ok={rep.get('ok')} remaining={(rep.get('verified') or {}).get('remaining_mechanical_rules')}")
    if rep.get("ok") and out.exists():
        with zipfile.ZipFile(out) as z:
            fixed = z.read("word/document.xml").decode()
        after = [r for r in fmt.analyse_package(out, policy)["rows"]
                 if r["rule"] == "FMT-T3a"]
        live = ""
        for _p0, _p1, para in fmt.paragraphs(fixed):
            if "Results" in fmt.text_of(para):
                live = fmt.child_elem(fmt.ppr_of(para), "keepNext") or ""
                break
        check("F030 the live keepNext is on and no FMT-T3a remains",
              not after and live == "<w:keepNext/>",
              f"after={after[:1]} live={live!r} "
              f"xml={fixed[fixed.find('Results') - 220:][:220]}")


# ---------------------------------------------------------------- F032
def test_f032_first_bibliography_entry_is_field_protected():
    print("\n== F032: the first entry of a live bibliography field is protected ==")
    tmp = scratch("c_f032_")
    body = ('<w:p><w:r><w:t>Title</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText> ADDIN ZOTERO_BIBL {"uncited":[]} CSL_BIBLIOGRAPHY </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t xml:space="preserve">1. Doe  J. </w:t></w:r></w:p>'
            '<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>'
            '<w:r><w:t xml:space="preserve">2. Roe, R. A title. Nature 1, 1 (2024). </w:t></w:r></w:p>'
            '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
            '<w:p><w:r><w:t>Body text.</w:t></w:r></w:p>')
    src = make_docx(tmp / "bibfield.docx", body)
    rows = [r for r in fmt.analyse_package(src, fmt.load_policy(None))["rows"]
            if r["rule"] == "FMT-T6d"]
    check("F032 both entries of the live bibliography field are protected",
          len(rows) == 2 and all(r["protected"] for r in rows),
          str([(r["location"], r["protected"], r["evidence"][-32:]) for r in rows]))


# ---------------------------------------------------------------- F033
def test_f033_rewrite_keeps_quoted_gt_attributes():
    print("\n== F033: a legal '>' inside a w:t attribute is not a tag boundary ==")
    tmp = scratch("c_f033_")
    open_tag = '<w:t w:rsidR="a>b" xml:space="preserve">'
    body = ('<w:p><w:r><w:t>Title</w:t></w:r></w:p>'
            '<w:p><w:r><w:t w:rsidR="a>b" xml:space="preserve">'
            'This is the the body text.</w:t></w:r></w:p>')
    src = make_docx(tmp / "wtattr.docx", body)
    policy = dict(fmt.load_policy(None))
    out = tmp / "fixed.docx"
    rep = fmt.fix_package(src, out, policy)
    check("F033 the fixer accepts the document", rep.get("ok") is True,
          f"ok={rep.get('ok')} remaining={(rep.get('verified') or {}).get('remaining_mechanical_rules')}")
    if out.exists():
        with zipfile.ZipFile(out) as z:
            fixed = z.read("word/document.xml").decode()
        check("F033 the rewritten w:t keeps rsidR/xml:space and fixes the text",
              open_tag in fixed and "the the" not in fixed,
              fixed[fixed.find("This is"):][:180])


# ---------------------------------------------------------------- F034
def test_f034_latex_compile_copy_does_not_follow_dir_symlinks():
    print("\n== F034: the .tex compile copy does not copy an outside symlink "
          "target ==")
    tmp = scratch("c_f034_")
    src = tmp / "texsrc"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}Hi\\end{document}\n")
    outside = tmp / "texoutside"
    outside.mkdir()
    (outside / "secret.txt").write_text("SECRET-OUTSIDE")
    (src / "linked").symlink_to(outside, target_is_directory=True)
    fakebin = tmp / "fakebin"
    fakebin.mkdir()
    log = tmp / "engine.log"
    engine = fakebin / "latexmk"
    engine.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "with open(os.environ['FAKE_TEX_LOG'], 'w') as fh:\n"
        "    fh.write('CWD=' + os.getcwd() + '\\n')\n"
        "    for root, dirs, files in os.walk('.'):\n"
        "        for name in files:\n"
        "            fh.write(os.path.join(root, name) + '\\n')\n"
        "sys.exit(0)\n")
    engine.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = str(fakebin) + os.pathsep + env.get("PATH", "")
    env["FAKE_TEX_LOG"] = str(log)
    old_path = os.environ.get("PATH")
    old_log = os.environ.get("FAKE_TEX_LOG")
    os.environ["PATH"] = env["PATH"]
    os.environ["FAKE_TEX_LOG"] = str(log)
    try:
        res = fmt.validate_latex(src / "main.tex", workdir=tmp / "texwork")
    finally:
        if old_path is not None:
            os.environ["PATH"] = old_path
        if old_log is None:
            os.environ.pop("FAKE_TEX_LOG", None)
        else:
            os.environ["FAKE_TEX_LOG"] = old_log
    copied = log.read_text() if log.exists() else ""
    check("F034 the engine compiles main.tex but no outside symlinked content",
          res.get("ok") is True and "main.tex" in copied
          and "linked/secret.txt" not in copied,
          f"result={res.get('ok')} copied={copied!r}")


# ---------------------------------------------------------------- F035
def test_f035_docxcompare_absolutizes_relative_output():
    print("\n== F035: docxcompare.sh hands Word an absolute output path for a "
          "relative argument ==")
    tmp = scratch("c_f035_")
    bindir = tmp / "bin"
    bindir.mkdir()
    outdir = tmp / "out"
    outdir.mkdir()
    pslog = tmp / "ps.txt"
    (tmp / "orig.docx").write_bytes(b"PK\x03\x04orig")
    (tmp / "revised.docx").write_bytes(b"PK\x03\x04rev")
    # powershell.exe stub: record the decoded script, emulate Word resolving a
    # relative output against ITS OWN working directory (so only an absolute
    # output is written where the wrapper checks/renames it).
    ps = bindir / "powershell.exe"
    ps.write_text(
        "#!/usr/bin/env python3\n"
        "import base64, os, re, sys, zipfile\n"
        "args = sys.argv[1:]\n"
        "enc = args[args.index('-EncodedCommand') + 1]\n"
        "script = base64.b64decode(enc).decode('utf-16-le')\n"
        "open(os.environ['STUB_PS_LOG'], 'w').write(script)\n"
        "m = re.search(r\"^\\$outputPath\\s*=\\s*'(.*)'$\", script, re.M)\n"
        "out = m.group(1) if m else ''\n"
        "if out.startswith('/'):\n"
        "    with zipfile.ZipFile(out, 'w') as z:\n"
        "        z.writestr('[Content_Types].xml', '<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>')\n"
        "        z.writestr('word/document.xml', '<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body/></w:document>')\n"
        "        z.writestr('word/_rels/document.xml.rels', '<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"/>')\n"
        "sys.exit(0)\n")
    ps.chmod(0o755)
    # wslpath stub: a relative path is returned unchanged (as observed on WSL).
    wp = bindir / "wslpath"
    wp.write_text("#!/usr/bin/env python3\nimport sys\nprint(sys.argv[-1])\n")
    wp.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    env["STUB_PS_LOG"] = str(pslog)
    env["DOCXCOMPARE_TIMEOUT"] = "30"
    proc = subprocess.run(
        ["bash", str(WS / "docxcompare.sh"), str(tmp / "orig.docx"),
         str(tmp / "revised.docx"), "rel-out.docx"],
        cwd=str(outdir), capture_output=True, text=True, timeout=120, env=env)
    blob = (proc.stdout or "") + (proc.stderr or "")
    script = pslog.read_text() if pslog.exists() else ""
    m = re.search(r"^\$outputPath\s*=\s*'(.*)'$", script, re.M)
    handed = m.group(1) if m else ""
    check("F035 a relative output is resolved before Word sees it",
          proc.returncode == 0 and handed.startswith("/")
          and (outdir / "rel-out.docx").exists(),
          f"rc={proc.returncode} outputPath={handed!r} "
          f"out_exists={(outdir / 'rel-out.docx').exists()} tail={blob.strip()[-200:]}")


# ---------------------------------------------------------------- main
def main() -> int:
    try:
        test_f025_partial_page_field_repair_is_not_published()
        test_f026_field_result_quotes_are_not_mechanical()
        test_f027_huge_decimal_attributes_do_not_crash()
        test_f028_scan_figures_unreadable_compression()
        test_f029_whitespace_closed_drawing_close()
        test_f030_keepnext_repairs_the_live_element()
        test_f032_first_bibliography_entry_is_field_protected()
        test_f033_rewrite_keeps_quoted_gt_attributes()
        test_f034_latex_compile_copy_does_not_follow_dir_symlinks()
        test_f035_docxcompare_absolutizes_relative_output()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}): {FAILS}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

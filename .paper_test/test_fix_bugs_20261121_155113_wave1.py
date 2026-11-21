#!/usr/bin/env python3
"""Regression tests for the 2026-11-21 15:51 fix-bugs wave 1.

One hermetic block per candidate that can be exercised without a model backend
or Word.  Each check fails on the pre-fix tree and passes here, except the
documented FALSE_POSITIVE checks (F039/F095), which pin why the claim does not
hold.

Run:  python3 .paper_test/test_fix_bugs_20261121_155113_wave1.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib
from pathlib import Path
from types import SimpleNamespace

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(WS))

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
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def zip_docx(path: Path, docs: list, extra: dict = None) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/_rels/document.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'relationships"/>')
        for name, data in (extra or {}).items():
            z.writestr(name, data)
        for i, doc in enumerate(docs):
            z.writestr("word/document.xml" if i == 0 else f"word/document{len(docs)}.xml",
                       doc)
    return path


def png_bytes(w=100, h=100) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" * 10))
            + chunk(b"IEND", b""))


# ---------------------------------------------------------------------------
# OOXML token readers: legal `</w:t >` and quote-agnostic attributes
# ---------------------------------------------------------------------------
def test_docx_token_readers() -> None:
    print("\n== OOXML token readers ==")
    run = '<w:r><w:rPr><w:i/></w:rPr><w:t>alpha beta</w:t ></w:r>'
    pieces = df.split_run_text_span(run, 0, 5)
    check("F002 a legal `</w:t >` run can be split",
          pieces is not None and df.text_of(pieces[0]) + df.text_of(pieces[1])
          + df.text_of(pieces[2]) == "alpha beta", repr(pieces))

    long_p = ('<w:p><w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>'
              + "word " * 30 + "</w:t></w:r></w:p>")
    heading = ('<w:p><w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr>'
               '<w:t>Introduction</w:t%s></w:r></w:p>')
    check("F004 a heading closed with `</w:t >` is detected",
          [h[1] for h in df.heading_like_paragraphs(long_p + heading % " ")]
          == ["Introduction"],
          repr(df.heading_like_paragraphs(long_p + heading % " ")))
    check("F004 the exact-close heading still detects",
          [h[1] for h in df.heading_like_paragraphs(long_p + heading % "")]
          == ["Introduction"])

    body_sq = (long_p.replace('w:sz w:val="24"', "w:sz w:val='24'")
               + (heading % "").replace('w:sz w:val="32"', "w:sz w:val='32'"))
    check("F005 a single-quoted body `w:sz` is the dominant size",
          df._body_run_size(body_sq) == 24, repr(df._body_run_size(body_sq)))
    check("F005 a single-quoted heading size is detected",
          [h[1] for h in df.heading_like_paragraphs(body_sq)] == ["Introduction"],
          repr(df.heading_like_paragraphs(body_sq)))

    bold_sq = long_p + (heading % "").replace(
        "<w:b/>", "<w:b w:val='1'/>").replace(
        'w:sz w:val="32"', "w:sz w:val='32'")
    check("F006 a single-quoted `<w:b w:val='1'/>` is bold",
          [h[1] for h in df.heading_like_paragraphs(bold_sq)] == ["Introduction"],
          repr(df.heading_like_paragraphs(bold_sq)))

    corr = ('<w:p><w:r><w:rPr><w:b/></w:rPr>'
            '<w:t>  * Correspondence: Zhen Xie</w:t%s></w:r></w:p>')
    para = corr % " "
    check("F009 the leading whitespace is measured on `</w:t >`",
          df._correspondence_lead(para) == 2, repr(df._correspondence_lead(para)))
    bolded = df._bold_label_runs(para)
    check("F007 the correspondence label is bolded on `</w:t >`",
          bolded != para, "paragraph unchanged")
    check("F008 the bold label is recognised on `</w:t >`",
          df._label_is_bold(bolded.replace("<w:rPr><w:b/></w:rPr>",
                                           "<w:rPr><w:b/></w:rPr>")) is True)
    check("F008 a roman label is still reported as not bold",
          df._label_is_bold(para.replace("<w:rPr><w:b/></w:rPr>",
                                         "<w:rPr><w:i/></w:rPr>")) is False)


def test_table_readers() -> None:
    print("\n== table geometry readers ==")
    for close in ("", " "):
        tbl = ('<w:tbl><w:tblCellMar><w:left w:w="200" w:type="dxa"/>'
               '<w:right w:w="300" w:type="dxa"/></w:tblCellMar%s></w:tbl>'
               % close)
        check(f"F010 table cell margins with close={close!r}",
              df._table_cell_margins(tbl) == (200, 300),
              repr(df._table_cell_margins(tbl)))
    tbl_sq = ('<w:tbl><w:tblCellMar><w:left w:w=\'200\' w:type=\'dxa\'/>'
              "<w:right w:w='300' w:type='dxa'/></w:tblCellMar></w:tbl>")
    check("F010 single-quoted cell margins are read",
          df._table_cell_margins(tbl_sq) == (200, 300),
          repr(df._table_cell_margins(tbl_sq)))

    for close in ("", " "):
        row = ('<w:tr><w:tc><w:tcPr><w:tcW w:w="500" w:type="dxa"/>'
               '</w:tcPr%s><w:p/></w:tc></w:tr>' % close)
        check(f"F077 a tcPr closed with {close!r} keeps its width",
              df._table_cell_widths(row) == [(500, 1)],
              repr(df._table_cell_widths(row)))

    grid = ('<w:tbl><w:tblGrid><w:gridCol w:w="4000"/><w:gridCol w:w="4000"/>'
            '</w:tblGrid><w:tr><w:tc><w:tcPr><w:tcW w:w=\'4000\' w:type=\'dxa\'/>'
            '</w:tcPr><w:p><w:r><w:t>SRR28357490123456789012345678901234567890</w:t>'
            '</w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:w=\'4000\' w:type=\'dxa\'/>'
            '</w:tcPr><w:p><w:r><w:t>slack column</w:t></w:r></w:p></w:tc></w:tr>'
            '</w:tbl>')
    check("F079 a tblGrid closed with whitespace is read",
          df._table_grid_widths(grid.replace("</w:tblGrid>", "</w:tblGrid >"))
          == [4000, 4000], repr(df._table_grid_widths(grid)))
    styles = {}
    rows = df.table_layout_rows(grid, styles, "doc.docx")
    fixes = df.table_layout_fixes(grid, rows)
    repaired = fixes[0][2] if fixes else grid
    check("F011 the table repair rewrites a single-quoted w:tcW",
          "w:tcW w:w='4000'" not in repaired and "w:tcW" in repaired,
          repaired[:300])
    check("R02 a single-quoted gridCol width is read",
          df._table_grid_widths("<w:tblGrid><w:gridCol w:w='4000'/></w:tblGrid>")
          == [4000],
          repr(df._table_grid_widths(
              "<w:tblGrid><w:gridCol w:w='4000'/></w:tblGrid>")))
    cell_sq = ('<w:tc><w:p><w:r><w:rPr><w:sz w:val=\'24\'/></w:rPr>'
               '<w:t>x</w:t></w:r></w:p></w:tc>')
    check("R02 a single-quoted run size is the cell's font size",
          df._cell_font_pt({}, cell_sq) == 12.0, repr(df._cell_font_pt({}, cell_sq)))


# ---------------------------------------------------------------------------
# Section / field / tab / superscript token readers
# ---------------------------------------------------------------------------
def test_section_field_readers() -> None:
    print("\n== section, field, tab and superscript readers ==")
    sect = ('<w:document><w:body><w:sectPr >'
            '<w:headerReference w:type="default" r:id="rId6"/>'
            '</w:sectPr ></w:body></w:document>')
    check("F074 a `</w:sectPr >` section is read",
          df.first_section_props(sect) is not None,
          repr(df.first_section_props(sect)))

    tabs = ('<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/>'
            '</w:tabs ></w:pPr><w:r><w:t>hello</w:t></w:r></w:p>')
    check("F075 a tab-stop definition is not a text newline",
          df.text_of(tabs) == "hello", repr(df.text_of(tabs)))

    zfield = ('<w:p><w:fldSimple w:instr=" ADDIN ZOTERO_ITEM CSL_CITATION '
              '{\\"citationID\\":\\"abc\\"} "><w:r><w:t>(Smith, 2020)</w:t>'
              '</w:r></w:fldSimple ></w:p>')
    rep = df.zotero_field_report(zfield)
    check("F076 a `</w:fldSimple >` live Zotero field is inventoried",
          rep["fields"] and rep["counts"]["zotero"] == 1, json.dumps(rep["counts"]))

    rpr_change = ('<w:r><w:rPr><w:rPrChange w:id="1" w:author="A"><w:rPr>'
                  '<w:vanish/></w:rPr></w:rPrChange></w:rPr>'
                  '<w:t>Visible text</w:t></w:r>')
    check("F003 the OLD rPr's `w:vanish` does not hide live text",
          df.text_of("<w:p>" + rpr_change + "</w:p>") == "Visible text",
          repr(df.text_of("<w:p>" + rpr_change + "</w:p>")))
    check("F003 a live `w:vanish` still hides text",
          df.text_of('<w:p><w:r><w:rPr><w:vanish/></w:rPr>'
                     "<w:t>Hidden</w:t></w:r></w:p>") == "")

    change = ('<w:sectPr><w:sectPrChange w:id="1"><w:sectPr>'
              '<w:headerReference w:type="first" r:id="old"/></w:sectPr>'
              '</w:sectPrChange ></w:sectPr>')
    stripped = df._strip_sect_changes(change)
    check("F093 a `</w:sectPrChange >` record is blanked",
          "old" not in stripped, stripped)

    sup = ('<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
           '<w:t>1</w:t ></w:r>')
    check("F014 a superscript run closed with `</w:t >` is counted",
          pp._superscript_run_count(sup) == 1,
          repr(pp._superscript_run_count(sup)))


def test_header_footer_signature() -> None:
    print("\n== header/footer role detection ==")
    tmp = scratch("hf_sig_")
    p = tmp / "hf.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'content-types"/>')
        z.writestr("word/document.xml",
                   '<w:document xmlns:w="http://x"><w:body><w:sectPr >'
                   '<w:headerReference w:type=\'default\' r:id="rId6"/>'
                   '</w:sectPr ></w:body></w:document>')
        z.writestr("word/header1.xml",
                   '<w:hdr xmlns:w="http://x"><w:p><w:r><w:t>H</w:t></w:r></w:p></w:hdr>')
        z.writestr("word/_rels/document.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                   '2006/relationships"><Relationship Id="rId6" Type="http://schemas.'
                   'openxmlformats.org/officeDocument/2006/relationships/header" '
                   'Target="header1.xml"/></Relationships>')
    sig = pp._docx_hf_signature(p)
    check("F012/F013 a single-quoted w:type in a whitespace-closed section is read",
          sig.get("roles") == [("header", "default")], json.dumps(sig))


# ---------------------------------------------------------------------------
# Duplicate ZIP member refused by template application
# ---------------------------------------------------------------------------
def test_duplicate_zip_member() -> None:
    print("\n== duplicate ZIP member ==")
    tmp = scratch("dup_zip_")
    src = tmp / "src.docx"

    def make(path: Path, duplicate: bool) -> None:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml",
                       '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
                       'content-types"/>')
            z.writestr("word/styles.xml", '<w:styles xmlns:w="http://x"/>')
            doc = ('<w:document xmlns:w="http://x"><w:body><w:p><w:r><w:t>%s'
                   '</w:t></w:r></w:p></w:body></w:document>')
            z.writestr("word/document.xml", doc % "ONE")
            if duplicate:
                z.writestr("word/document.xml", doc % "TWO")

    make(src, True)
    tpl = tmp / "tpl.docx"
    make(tpl, False)
    out = tmp / "out.docx"
    with contextlib.redirect_stderr(io.StringIO()):
        res = df.apply_word_template(src, out, tpl)
    check("F015 a duplicate `word/document.xml` is refused",
          res.get("ok") is False and "repeats member" in str(res.get("error")),
          json.dumps(res)[:300])


# ---------------------------------------------------------------------------
# Silent exception paths become recorded gaps
# ---------------------------------------------------------------------------
def test_pdf_and_image_gaps() -> None:
    print("\n== PDF/image scan gaps ==")
    tmp = scratch("scan_gaps_")
    pkg = tmp / "pkg"
    pkg.mkdir()
    (pkg / "a.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    mod = pp._format_module()
    orig_pdf, orig_logic = pp._pdf_text_info, mod.logic_rows

    def boom(*_a, **_k):
        raise RuntimeError("logic exploded")

    pp._pdf_text_info = lambda _p: ("Some text.\n\nMore text.", None)
    mod.logic_rows = boom
    try:
        res = pp.scan_format_in_sources([(pkg, "", ())])
    finally:
        pp._pdf_text_info, mod.logic_rows = orig_pdf, orig_logic
    gap = [r for r in res["rows"] if r.get("rule") == "FMT-PDF0"
           and "logic_rows" in str(r.get("evidence"))]
    check("F016 a crashed PDF rule is a recorded FMT-PDF0 gap", bool(gap),
          json.dumps(res["rows"])[:300])

    pkg2 = tmp / "pkg2"
    pkg2.mkdir()
    (pkg2 / "fig1.png").write_bytes(png_bytes())
    orig_img = mod.image_resolution_rows

    def boom2(*_a, **_k):
        raise RuntimeError("image exploded")

    mod.image_resolution_rows = boom2
    try:
        res2 = pp.scan_format_in_sources([(pkg2, "", ())])
    finally:
        mod.image_resolution_rows = orig_img
    gap2 = [r for r in res2["rows"] if r.get("rule") == "FMT-IM4"
            and "NOT measured" in str(r.get("evidence"))]
    check("F017 a failed image read is a recorded FMT-IM4 gap", bool(gap2),
          json.dumps(res2["rows"])[:300])


# ---------------------------------------------------------------------------
# Bounded standalone image + regular-file reads
# ---------------------------------------------------------------------------
def test_bounded_reads() -> None:
    print("\n== bounded reads ==")
    tmp = scratch("bounded_")
    big = tmp / "big.png"
    big.write_bytes(b"not-a-real-png" + b"x" * 500)
    old = getattr(df, "MAX_STANDALONE_IMAGE_BYTES", None)
    df.MAX_STANDALONE_IMAGE_BYTES = 64
    try:
        rows = df.image_resolution_rows(big, 6.5, {"min_image_dpi": 300})
    finally:
        if old is None:
            del df.MAX_STANDALONE_IMAGE_BYTES
        else:
            df.MAX_STANDALONE_IMAGE_BYTES = old
    check("F023 an over-budget standalone image is an FMT-IM4 gap, not a clean read",
          rows and rows[0]["rule"] == "FMT-IM4" and "NOT measured" in rows[0]["evidence"],
          json.dumps(rows)[:300])

    p = tmp / "grows.txt"
    p.write_bytes(b"0123456789")
    real_fstat = pp.os.fstat

    class FakeStat:
        st_mode = stat.S_IFREG | 0o644
        st_nlink = 1
        st_size = 1

    try:
        pp.os.fstat = lambda _fd: FakeStat()
        try:
            data = pp.read_regular_file(p, 4)
        except OSError as exc:
            data = f"OSError: {exc}"
    finally:
        pp.os.fstat = real_fstat
    check("F027 a file that grew after fstat is rejected by the read cap",
          isinstance(data, str) and "read budget" in data, repr(data))


# ---------------------------------------------------------------------------
# Metadata sanitizer: legal whitespace before a closing tag
# ---------------------------------------------------------------------------
def test_metadata_sanitizer() -> None:
    print("\n== accepted judge view ==")
    xml = ('<w:document xmlns:w="http://x"><w:body>'
           '<w:ins w:id="1"><w:r><w:t>INSERTED</w:t></w:r></w:ins >'
           '<w:rsids><w:rsid w:val="ABC"/></w:rsids >'
           '<w:p><w:r><w:t>KEPT</w:t></w:r></w:p></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml", xml)
    out, _notes = pp._sanitize_ooxml_bytes(buf.getvalue())
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        got = z.read("word/document.xml")
    check("F034 `</w:ins >` is unwrapped in the accepted view",
          b"<w:ins" not in got and b"INSERTED" in got, got[:300])
    check("F034 `</w:rsids >` is stripped from the accepted view",
          b"rsids" not in got, got[:300])
    check("F034 the accepted view stays well-formed",
          __import__("xml.etree.ElementTree", fromlist=["fromstring"]).fromstring(got)
          is not None)


# ---------------------------------------------------------------------------
# Serialization restores every xmlns declaration, quote-style independent
# ---------------------------------------------------------------------------
def test_serialize_namespaces() -> None:
    print("\n== redline serialization namespaces ==")
    import xml.etree.ElementTree as ET
    raw = (b'<?xml version="1.0" encoding="UTF-8"?>'
           b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
           b'2006/main" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/'
           b'2006" xmlns:w14=\'http://schemas.microsoft.com/office/word/2010/wordml\' '
           b'mc:Ignorable="w14"><w:body><w:p/></w:body></w:document>')
    out = pp._serialize_document(ET.fromstring(raw), raw)
    check("F035 a single-quoted xmlns:w14 is restored",
          b"xmlns:w14=" in out, out[:300])

    pad = b"<!-- " + b"x" * 7000 + b" -->"
    raw2 = (b'<?xml version="1.0" encoding="UTF-8"?>' + pad
            + b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
              b'2006/main" xmlns:mc="http://schemas.openxmlformats.org/markup-'
              b'compatibility/2006" xmlns:w14="http://schemas.microsoft.com/office/word/'
              b'2010/wordml" mc:Ignorable="w14"><w:body><w:p/></w:body></w:document>')
    out2 = pp._serialize_document(ET.fromstring(raw2), raw2)
    check("F084 a declaration past the 6 KB prolog is restored",
          b"xmlns:w14=" in out2, out2[:300])

    ns = (b'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
          b'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" ')
    raw3 = (b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<!-- Generated by <tool> -->'
            b'<w:document ' + ns
            + b'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
              b'mc:Ignorable="w14"><w:body><w:p/></w:body></w:document>')
    out3 = pp._serialize_document(ET.fromstring(raw3), raw3)
    check("R01 a `<tool>` inside a prolog comment is not the document element",
          b"xmlns:w14=" in out3, out3[:300])

    raw4 = (b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<!DOCTYPE w:document [<!ENTITY x "y">]>'
            b'<w:document ' + ns
            + b'w:note="a>b" '
              b'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
              b'mc:Ignorable="w14"><w:body><w:p/></w:body></w:document>')
    out4 = pp._serialize_document(ET.fromstring(raw4), raw4)
    check("R01 a `>` inside a quoted attribute does not truncate the root tag",
          b"xmlns:w14=" in out4, out4[:300])


# ---------------------------------------------------------------------------
# Predictable temp siblings are no longer followed
# ---------------------------------------------------------------------------
def test_temp_sibling_symlinks() -> None:
    print("\n== predictable temp siblings ==")
    tmp = scratch("tmp_link_")
    victim = tmp / "victim.txt"
    victim.write_text("ORIG")
    src = tmp / "src.txt"
    src.write_text("NEW")

    dest = tmp / "tracked.docx"
    # The pre-fix name is `.{name}.track-{pid}-{time_ns}`: make it predictable,
    # plant a symlink at exactly that path, and let `tmp_path_for` (the fixed
    # code's reservation) return the same planted path.
    planted = dest.with_name(".tracked.docx.track-4242-777")
    if planted.exists() or planted.is_symlink():
        planted.unlink()
    os.symlink(victim, planted)
    real_tmp = pp.tmp_path_for
    real_pid, real_ns = pp.os.getpid, pp.time.time_ns
    pp.tmp_path_for = lambda _p: planted
    pp.os.getpid = lambda: 4242
    pp.time.time_ns = lambda: 777
    try:
        try:
            pp._tracking_write_copy(src, dest)
        except OSError:
            pass
    finally:
        pp.tmp_path_for = real_tmp
        pp.os.getpid, pp.time.time_ns = real_pid, real_ns
    check("F020 a planted symlink at the tracking temp is not followed",
          victim.read_text() == "ORIG", victim.read_text())

    root = tmp / "root"
    (root / "pkg").mkdir(parents=True)
    dest2 = root / "pkg" / "restored.txt"
    planted2 = dest2.with_name(".restored.txt.restore-4242-777")
    os.symlink(victim, planted2)
    pp.tmp_path_for = lambda _p: planted2
    pp.os.getpid = lambda: 4242
    pp.time.time_ns = lambda: 777
    try:
        try:
            pp._safe_restore_copy(src, dest2, root)
        except OSError:
            pass
    finally:
        pp.tmp_path_for = real_tmp
        pp.os.getpid, pp.time.time_ns = real_pid, real_ns
    check("F111 a planted symlink at the restore temp is not followed",
          victim.read_text() == "ORIG", victim.read_text())


# ---------------------------------------------------------------------------
# MCP child runner: an overflow with a failed tree kill still settles
# ---------------------------------------------------------------------------
def test_mcp_overflow_settles() -> None:
    print("\n== MCP child-runner overflow ==")
    tmp = scratch("mcp_")
    for server in ("mcp-docx-compare", "mcp-docx-converter"):
        module = (WS / server / "run-child.mjs").as_uri()
        script = tmp / f"{server}.mjs"
        script.write_text(
            f"import {{ runFile }} from '{module}';\n"
            "const t0 = Date.now();\n"
            "const child = runFile('/bin/sh', ['-c', "
            "'yes x | head -c 100000; exec sleep 3'], {\n"
            "  timeout: 0, maxBuffer: 64, killGraceMs: 200,\n"
            "  killTree: () => ({ error: 'injected kill failure' }),\n"
            "});\n"
            "const timer = setTimeout(() => { console.log('PENDING'); "
            "process.exit(0); }, 1500);\n"
            "child.then(() => { console.log('RESOLVED'); clearTimeout(timer); "
            "process.exit(0); },\n"
            "  (e) => { console.log('REJECTED overBudget=' + e.overBudget); "
            "clearTimeout(timer); process.exit(0); });\n")
        proc = subprocess.run(["node", str(script)], capture_output=True,
                              text=True, timeout=10)
        check(f"F019 {server} overflow settles after a failed tree kill",
              "REJECTED overBudget=true" in proc.stdout, proc.stdout.strip()
              + " " + proc.stderr.strip()[:200])


# ---------------------------------------------------------------------------
# Documentation / CLI consistency
# ---------------------------------------------------------------------------
def test_docs_and_cli() -> None:
    print("\n== docs and CLI consistency ==")
    example = pp.load_venue_profile("example-journal")
    caps = example.length_limits()
    readme = (WS / "venue_profiles" / "README.md").read_text("utf-8")
    check("F039 the README's example caps are the profile's relaxed caps",
          caps["abstract"]["cap"] == 275 and caps["main text"]["cap"] == 6000
          and "Research Article 275/6000" in readme,
          json.dumps(caps))

    layout = (WS / "paper_docx_format_parts" / "p02_layout_edit.py").read_text("utf-8")
    check("F040 the caption comment states that a drawing does not close the block",
          "no embedded drawing" not in layout and "drawing does NOT close" in layout)

    prelude = (WS / "paper_pipeline_parts" / "p00_prelude.py").read_text("utf-8")
    docs = (WS / "docs" / "agent-harnesses.md").read_text("utf-8")
    check("F042 the version history no longer promises removed aliases",
          "REPLACED by these axes" in prelude
          and "legacy `--agent` / `--judge-agent` shortcuts are gone" in docs)

    err = io.StringIO()
    code = None
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            pp._cmd_run_locked(None, SimpleNamespace(timeout=-1))
    except SystemExit as exc:
        code = exc.code
    check("F095 `run --timeout -1` is rejected, not turned into an instant timeout",
          code == 2 and "non-negative" in err.getvalue(), f"code={code} {err.getvalue()}")


def main() -> int:
    test_docx_token_readers()
    test_table_readers()
    test_section_field_readers()
    test_header_footer_signature()
    test_duplicate_zip_member()
    test_pdf_and_image_gaps()
    test_bounded_reads()
    test_metadata_sanitizer()
    test_serialize_namespaces()
    test_temp_sibling_symlinks()
    test_mcp_overflow_settles()
    test_docs_and_cli()
    cleanup()
    print(f"\n{len(FAILS)} failure(s)")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("OK all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

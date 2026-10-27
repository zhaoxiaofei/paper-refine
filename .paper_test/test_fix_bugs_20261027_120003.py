#!/usr/bin/env python3
"""Regression checks for the 2026-10-27 12:00 fix-bugs wave.

Every check pins a finding confirmed against this tree by re-reading the cited
code and reproducing it. The suite is hermetic: temp dirs only, no network, no
Word/Office (the one PDF check needs ImageMagick and is skipped without it).

Run:  python3 .paper_test/test_fix_bugs_20261027_120003.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs1027c_pp", "paper_pipeline.py")
pf = load("fixbugs1027c_pf", "paper_docx_format.py")

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
            with contextlib.suppress(OSError):
                if p.is_dir():
                    p.chmod(0o755)
                else:
                    p.chmod(0o644)
        shutil.rmtree(tmp, ignore_errors=True)


NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr/></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
</w:styles>"""


def make_docx(path: Path, body: str, document: str = None, styles: str = STYLES) -> Path:
    doc = document or ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       f'<w:document {NS}><w:body>{body}'
                       '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>'
                       '</w:body></w:document>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
    return path


# ---------------------------------------------------------------- F11
def test_f11_self_closing_wt():
    print("\n== F11: a self-closing w:t does not swallow the next run ==")
    para = '<w:p><w:r><w:t xml:space="preserve"/></w:r><w:r><w:t>colour</w:t></w:r></w:p>'
    check("text_of reads only the real text", pf.text_of(para) == "colour",
          repr(pf.text_of(para)))
    new, applied = pf.rewrite_text_spans(para, [(0, 0, "X")])
    check("the rewrite does not escape run markup", "&lt;/w:r&gt;" not in new, new[:160])
    tmp = scratch("f11_")
    src = make_docx(tmp / "i.docx", '<w:p><w:r><w:t>We use color here.</w:t></w:r></w:p>'
                    '<w:p><w:r><w:t xml:space="preserve"/></w:r>'
                    '<w:r><w:t>We use colour here.</w:t></w:r></w:p>')
    rep = pf.fix_package(src, tmp / "o.docx", dict(pf.POLICY_DEFAULTS))
    with zipfile.ZipFile(tmp / "o.docx") as z:
        dx = z.read("word/document.xml").decode()
    check("fix_package does not corrupt the package", "&lt;/w:r&gt;" not in dx
          and dx.count("here.") == 2, f"ok={rep.get('ok')}")


# ---------------------------------------------------------------- F12
def test_f12_unlink_fields():
    print("\n== F12: --unlink removes the fldChar begin/end runs ==")
    xml = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           '<w:r><w:instrText> ADDIN ZOTERO_ITEM CSL_CITATION {}</w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
           '<w:r><w:t>result</w:t></w:r>'
           '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    new, removed = pf._unlink_fields(xml)
    check("no live fldChar survives", "fldChar" not in new, new[:200])
    check("the field result text survives", "result" in new, new[:200])
    check("the field is reported as unlinked", removed == 1)


# ---------------------------------------------------------------- F13
def test_f13_anchor_paragraph():
    print("\n== F13: a break-only paragraph carrying a bookmark is not deleted ==")
    tmp = scratch("f13_")
    body = ('<w:p><w:r><w:t>First.</w:t></w:r></w:p>'
            '<w:p><w:r><w:br w:type="page"/></w:r>'
            '<w:bookmarkStart w:id="7" w:name="MethodSection"/><w:bookmarkEnd w:id="7"/></w:p>'
            '<w:p><w:r><w:t>Methods.</w:t></w:r></w:p>')
    src = make_docx(tmp / "i.docx", body)
    rep = pf.fix_package(src, tmp / "o.docx", dict(pf.POLICY_DEFAULTS))
    with zipfile.ZipFile(tmp / "o.docx") as z:
        dx = z.read("word/document.xml").decode()
    check("the bookmark survives", "MethodSection" in dx, f"ok={rep.get('ok')}")
    check("the scanner has the same anchor guard",
          "has_anchor" in inspect.getsource(pf.analyse_document)
          and "has_anchor" in inspect.getsource(pf.fix_document))


# ---------------------------------------------------------------- F14
def test_f14_sectpr_break():
    print("\n== F14: scanner and fixer agree on a sectPr-bearing break paragraph ==")
    tmp = scratch("f14_")
    body = ('<w:p><w:pPr><w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr></w:pPr>'
            '<w:r><w:br w:type="page"/></w:r></w:p>'
            '<w:p><w:r><w:t>Main text.</w:t></w:r></w:p>')
    src = make_docx(tmp / "i.docx", body)
    rows = [r for r in pf.analyse_package(src, dict(pf.POLICY_DEFAULTS))["rows"]
            if r["rule"] == "FMT-S1"]
    check("the sectPr row is manual", bool(rows) and rows[0]["fix"] == "manual", rows)
    rep = pf.fix_package(src, tmp / "o.docx", dict(pf.POLICY_DEFAULTS))
    check("fix is not blocked by its own scanner row", rep.get("ok") is True,
          f"ok={rep.get('ok')} remaining={(rep.get('verified') or {}).get('remaining_mechanical_rules')}")


# ---------------------------------------------------------------- F15
def test_f15_unreadable_parts():
    print("\n== F15: unreadable DOCX parts are reported, never a traceback ==")
    tmp = scratch("f15_")
    bad = make_docx(tmp / "bad.docx", "<w:p/>", styles="<w:styles><w:style>")
    rep = pf.repair_layout_package(bad, tmp / "bad.out.docx", dict(pf.POLICY_DEFAULTS))
    check("repair-layout reports malformed styles", rep.get("ok") is False and rep.get("error"),
          {k: rep.get(k) for k in ("ok", "error")})
    src = make_docx(tmp / "z.docx", '<w:p><w:r><w:t>x</w:t></w:r></w:p>')
    data = bytearray(src.read_bytes())
    for sig, off in ((b"PK\x03\x04", 8), (b"PK\x01\x02", 10)):
        i = 0
        while True:
            i = data.find(sig, i)
            if i < 0:
                break
            nlen = int.from_bytes(data[i + (26 if sig == b"PK\x03\x04" else 28):][:2], "little")
            name = data[i + (30 if sig == b"PK\x03\x04" else 46):][:nlen]
            if name == b"word/document.xml":
                data[i + off:i + off + 2] = (99).to_bytes(2, "little")
            i += 4
    src.write_bytes(bytes(data))
    rep = pf.refresh_zotero_package(src, tmp / "z.out.docx", dict(pf.POLICY_DEFAULTS))
    check("refresh reports an unsupported compression method", rep.get("ok") is False,
          {k: rep.get(k) for k in ("ok", "skip")})


# ---------------------------------------------------------------- F16
def test_f16_malformed_document():
    print("\n== F16: scan reports FMT-X1 on a malformed document.xml ==")
    tmp = scratch("f16_")
    bad = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document {NS}><w:body><w:p><w:r><w:t>x</w:t></w:r></w:body></w:document>')
    src = make_docx(tmp / "b.docx", "", document=bad)
    rows = pf.analyse_package(src, dict(pf.POLICY_DEFAULTS))["rows"]
    check("scan files FMT-X1", any(r["rule"] == "FMT-X1" for r in rows),
          [r["rule"] for r in rows])


# ---------------------------------------------------------------- F17
def test_f17_image_only_page():
    print("\n== F17: an image-only PDF page is not a blank page ==")
    if shutil.which("convert") is None or shutil.which("pdftotext") is None:
        print("[skip] ImageMagick/pdftotext not installed")
        return
    tmp = scratch("f17_")
    pdf = tmp / "f.pdf"
    proc = subprocess.run(["convert", "-size", "600x800", "xc:red", str(pdf)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"[skip] ImageMagick could not make the PDF: {proc.stderr[:120]}")
        return
    res = pf.check_pdf(pdf, dict(pf.POLICY_DEFAULTS))
    check("the image page is not reported blank", not res["blank_pages"],
          f"pages={res['pages']} blank={res['blank_pages']}")


# ---------------------------------------------------------------- F17b
def _header_logo_pdf(path: Path) -> None:
    """4 pages: text, running-head logo only, text, header logo + body figure.

    A real (if hand-built) PDF, not one image per page, so pdftotext finds body
    text on pages 1/3 and pages 2/4 carry no text. The header logo is the SAME
    small image on every page; page 4 adds a distinct body-sized figure. Hermetic
    on purpose: no TeX/ImageMagick needed to pin the furniture-image regression.
    """
    head = bytes([255, 0, 0]) * 8                  # 4x2 RGB, repeated header logo
    body_img = bytes(range(192))                   # 8x8 RGB, page-4 figure
    bodies = [
        b"q 28 0 0 14 283 800 cm /Im1 Do Q\n"
        b"BT /F1 12 Tf 72 700 Td (Page one body text.) Tj ET\n",
        b"q 28 0 0 14 283 800 cm /Im1 Do Q\n",
        b"q 28 0 0 14 283 800 cm /Im1 Do Q\n"
        b"BT /F1 12 Tf 72 700 Td (Page three body text.) Tj ET\n",
        b"q 28 0 0 14 283 800 cm /Im1 Do Q\n"
        b"q 400 0 0 400 97 250 cm /Im2 Do Q\n",
    ]
    kids = " ".join(f"{6 + 2 * i} 0 R" for i in range(len(bodies)))
    objs = {
        1: b"<</Type /Catalog /Pages 2 0 R>>",
        2: f"<</Type /Pages /Kids [{kids}] /Count {len(bodies)}>>".encode(),
        3: b"<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>",
        4: (b"<</Type /XObject /Subtype /Image /Width 4 /Height 2 /ColorSpace "
            b"/DeviceRGB /BitsPerComponent 8 /Length %d>>\nstream\n" % len(head))
           + head + b"\nendstream",
        5: (b"<</Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace "
            b"/DeviceRGB /BitsPerComponent 8 /Length %d>>\nstream\n" % len(body_img))
           + body_img + b"\nendstream",
    }
    for i, body in enumerate(bodies):
        page_num, cont_num = 6 + 2 * i, 7 + 2 * i
        objs[page_num] = (
            f"<</Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources "
            f"<</Font <</F1 3 0 R>> /XObject <</Im1 4 0 R /Im2 5 0 R>>>> "
            f"/Contents {cont_num} 0 R>>").encode()
        objs[cont_num] = (b"<</Length %d>>\nstream\n" % len(body)) + body + b"\nendstream"
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {max(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for num in sorted(objs):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += (f"trailer\n<</Size {max(objs) + 1} /Root 1 0 R>>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    path.write_bytes(out)


def test_f17b_header_logo_blank_page():
    print("\n== F17b: a running-head image does not hide a blank body page ==")
    if shutil.which("pdftotext") is None or shutil.which("pdfimages") is None:
        print("[skip] pdftotext/pdfimages not installed")
        return
    tmp = scratch("f17b_")
    pdf = tmp / "hdr.pdf"
    _header_logo_pdf(pdf)
    res = pf.check_pdf(pdf, dict(pf.POLICY_DEFAULTS))
    check("a header-logo-only page is still blank",
          2 in res["blank_pages"], f"pages={res['pages']} blank={res['blank_pages']}")
    check("a page whose body carries a figure is not blank", 4 not in res["blank_pages"],
          res["blank_pages"])
    rows = [(r["rule"], r["location"]) for r in res["rows"]]
    check("only page 2 is reported", rows == [("FMT-S2", "page 2")], rows)


# ---------------------------------------------------------------- F18
def test_f18_zero_length_tail():
    print("\n== F18: a zero-length insertion after a trailing break is written ==")
    for tail in ("<w:br/>", "<w:tab/>", "<w:noBreakHyphen/>",
                 '<w:sym w:font="Wingdings" w:char="F0A7"/>'):
        para = f'<w:p><w:r><w:t>abc</w:t>{tail}</w:r></w:p>'
        new, applied = pf.rewrite_text_spans(para, [(4, 4, "X")])
        check(f"insert after {tail[:14]} lands in the paragraph", "X" in new,
              f"applied={applied} new={new!r}")


# ---------------------------------------------------------------- F19
def test_f19_rpr_whitespace():
    print("\n== F19: an rPr end tag with whitespace is handled ==")
    got, _changed = pf._rpr_set_emphasis('<w:rPr ><w:b/></w:rPr >', True)
    try:
        ET.fromstring(f'<w:r {NS}>{got}</w:r>')
        ok = True
    except ET.ParseError:
        ok = False
    check("the edited rPr stays well-formed", ok, got)
    check("rpr_of accepts the whitespace end tag",
          pf.rpr_of('<w:r><w:rPr ><w:b/></w:rPr ></w:r>') is not None)


# ---------------------------------------------------------------- F20
def test_f20_titlepg_order():
    print("\n== F20: titlePg lands before the CT_SectPr ordered tail ==")
    body = ('<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
            '<w:textDirection w:val="tbRl"/><w:bidi/><w:docGrid w:linePitch="360"/></w:sectPr>')
    new, _ok = pf._apply_front_refs(body, {"header_text": "H", "footer_text": "F"})
    check("titlePg precedes textDirection", -1 < new.find("<w:titlePg") < new.find("<w:textDirection"),
          new[:260])


# ---------------------------------------------------------------- F21
def test_f21_same_run_emphasis():
    print("\n== F21: two labels in ONE run are both repaired ==")
    tmp = scratch("f21_")
    ital = lambda t: f'<w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve">{t}</w:t></w:r>'
    roman = lambda t: f'<w:r><w:t xml:space="preserve">{t}</w:t></w:r>'
    body = ('<w:p>' + ital("(Co-corresponding author; A)") + roman(", ")
            + ital("(Co-corresponding author; B)") + roman(", ")
            + ital("(Co-corresponding author; C)") + roman(".") + '</w:p>'
            '<w:p>' + roman("Note (Co-corresponding author; X) and "
                            "(Co-corresponding author; Y) done.") + '</w:p>')
    src = make_docx(tmp / "i.docx", body)
    rep = pf.fix_package(src, tmp / "o.docx", dict(pf.POLICY_DEFAULTS))
    with zipfile.ZipFile(tmp / "o.docx") as z:
        dx = z.read("word/document.xml").decode()
        rows = pf.analyse_document(dx, pf.parse_styles(z), dict(pf.POLICY_DEFAULTS), "x")["rows"]
    check("the re-scan has no FMT-T9a", not [r for r in rows if r["rule"] == "FMT-T9a"],
          f"ok={rep.get('ok')} changes={rep.get('changes')}")
    note = dx.split("<w:p>")[2] if len(dx.split("<w:p>")) > 2 else dx
    check("both labels in the second paragraph are italic",
          note.count("<w:i/>") == 2, note[:400])


# ---------------------------------------------------------------- F22
def test_f22_verifier_not_intersection():
    print("\n== F22: the fixer's self-check rejects an INTRODUCED mechanical rule ==")
    src = inspect.getsource(pf.fix_package)
    check("remaining is every mechanical rule in the output",
          "remaining = sorted(mech_after)" in src
          and "mech_before & mech_after" not in src,
          [ln.strip() for ln in src.splitlines() if "remaining =" in ln][:2])


# ---------------------------------------------------------------- F24/F25
def test_f24_f25_mcp_probe():
    print("\n== F24/F25: the MCP probe accepts a trailing comment and a spaced path ==")
    tmp = scratch("mcp_")
    (tmp / "a b").mkdir()
    exe = tmp / "a b" / "node.exe"
    exe.write_text("")
    exe.chmod(0o755)
    cfg = tmp / "config.toml"
    cfg.write_text(f'[mcp_servers.docx-converter] # note\ncommand = "{exe}"\nargs = []\n')
    old = os.environ.get("CODEX_HOME")
    os.environ["CODEX_HOME"] = str(tmp)
    try:
        check("the spec reader and the probe agree it is configured",
              bool(pp.mcp_server_unusable_reason("docx-converter")) is False,
              pp.mcp_server_unusable_reason("docx-converter"))
        spec = pp.mcp_server_spec("docx-converter")
        check("the full spaced command survives", spec.get("command") == str(exe), spec)
    finally:
        if old is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = old


# ---------------------------------------------------------------- F27
def test_f27_failed_fixer():
    print("\n== F27: ok=False with no changes is a failure, not 'already clean' ==")
    tmp = scratch("f27_")
    doc = tmp / "sect.docx"
    doc.write_bytes(b"PK\x03\x04dummy")
    old = pp._format_module

    class Fake:
        @staticmethod
        def fix_package(path, tmpout, policy):
            Path(tmpout).write_bytes(b"PK\x03\x04out")
            return {"ok": False, "changes": [], "error": None,
                    "verified": {"remaining_mechanical_rules": ["FMT-S1"]}}

    pp._format_module = lambda: Fake
    try:
        rep = pp.fix_docx_in_place(doc, {})
    finally:
        pp._format_module = old
    check("the failed fixer is reported", bool(rep.get("error"))
          and rep.get("applied") is False, rep)


# ---------------------------------------------------------------- F28
def test_f28_sandbox_order():
    print("\n== F28: the newest add-venue sandbox wins across name formats ==")
    tmp = scratch("f28_")
    base = tmp / ".add-venue"
    base.mkdir()
    (base / "v-20261027T120000Z").mkdir()
    (base / "v-20261027T120000123456Z-a1b2c3").mkdir()
    got = pp.latest_add_venue_sandbox(tmp, "v")
    check("the microsecond sandbox is newest",
          got is not None and got.name.endswith("123456Z-a1b2c3"),
          got.name if got else None)


# ---------------------------------------------------------------- F29
def test_f29_invalid_char_refs():
    print("\n== F29: XML-invalid character references stay literal ==")
    for ref in ("&#0;", "&#x1F;", "&#xFFFE;"):
        check(f"{ref} stays literal", pf.unesc(ref) == ref, repr(pf.unesc(ref)))


# ---------------------------------------------------------------- F31
def test_f31_render_fallback_args():
    print("\n== F31: the render fallback forwards timeout/page_images ==")
    tmp = scratch("f31_")
    (tmp / "x.docx").write_bytes(b"x")
    orig = pp.render_docx_visual
    calls = []

    def wrapper(docx, out_dir, renderer=None, timeout=900, page_images=True):
        if renderer is None:
            return orig(docx, out_dir, None, timeout=timeout, page_images=page_images)
        calls.append((timeout, page_images))
        return {"ok": True, "renderer": renderer[0]}

    old_choices = pp.visual_renderer_choices
    pp.render_docx_visual = wrapper
    pp.visual_renderer_choices = lambda: [("fake", "/bin/true")]
    try:
        res = orig(tmp / "x.docx", tmp, None, timeout=7, page_images=False)
    finally:
        pp.render_docx_visual = orig
        pp.visual_renderer_choices = old_choices
    check("the fallback call keeps timeout=7 and page_images=False",
          res.get("ok") and calls == [(7, False)], calls)


# ---------------------------------------------------------------- F33
def test_f33_redline_restore():
    print("\n== F33: a failed best-redline restore does not name a winner ==")
    src = inspect.getsource(pp.redline_one_pair)
    check("the restore failure is caught, not suppressed",
          "could not be restored" in src and "with contextlib.suppress(OSError):\n            shutil.copyfile(best[1], out)" not in src,
          [ln.strip() for ln in src.splitlines() if "restore" in ln][:4])


# ---------------------------------------------------------------- F37
def test_f37_bounded_repair_audit():
    print("\n== F37: only confirmed plan rows may change files ==")
    tmp = scratch("f37_")
    pre, cur = tmp / "pre", tmp / "cur"
    for d in (pre, cur):
        d.mkdir()
        (d / "a.docx").write_text("A")
        (d / "b.docx").write_text("B")
    (cur / "a.docx").write_text("A2")
    (cur / "REPAIR_LEDGER.json").write_text("{}")
    rows = [{"id": "R1", "file": "a.docx"}, {"id": "R2", "file": "b.docx"}]
    bad = pp._revised_repair_violations(pre, cur, rows, {"R1"})
    check("a confirmed row's file and the ledger pass", bad == [], bad)
    # The bounded-repair prompt requires the hand-off report too; under the
    # readme policy that file is README-AUTHOR-TO-COMPLETE.md, not MANUAL_STEPS.md.
    (cur / "README-AUTHOR-TO-COMPLETE.md").write_text("# Author to complete\n")
    bad = pp._revised_repair_violations(pre, cur, rows, {"R1"})
    check("the readme hand-off report is bookkeeping", bad == [], bad)
    (cur / "b.docx").write_text("B2")
    bad = pp._revised_repair_violations(pre, cur, rows, {"R1"})
    check("an unplanned edit is caught", bad == ["b.docx"], bad)


# ---------------------------------------------------------------- F38/F39/F40
def _review_sandbox(tmp: Path, m1_md: str, coverage: list, parity_body: str):
    sb = Path(tmp)
    art = sb / "review" / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    (art / "M1_acronyms.md").write_text(m1_md, encoding="utf-8")
    for fname in ("M25_artwork_parity.md", "M26_conventions.md", "M27_evidence_coverage.md",
                  "M28_symmetry.md", "M29_caption_schema.md",
                  "M30_hierarchy_reconciliation.md", "M31_artwork_legend.md",
                  "M32_statistics.md", "M33_availability.md", "M34_source_data_coverage.md",
                  "M35_disclosures.md", "M36_zotero_parity.md", "M2_references.md"):
        (art / fname).write_text(parity_body, encoding="utf-8")
    (sb / "review" / "ARCHITECTURE.md").write_text(
        "| scope | disposition |\n|---|---|\n| ms | OK |\n", encoding="utf-8")
    fj = {"submission_dir": "./base", "guidelines_source": "x", "findings": [],
          "artifacts": {}, "coverage": coverage}
    return sb, fj


def _coverage(m1="clean -- basis: x"):
    return ([{"check": f"M{i}", "disposition": (m1 if i == 1 else "clean -- basis: x")}
             for i in range(1, 18)]
            + [{"check": f"J{i}", "disposition": "clean -- basis: x"} for i in range(1, 5)]
            + [{"check": c, "disposition": "clean -- basis: x"}
               for c in ("M18", "M19", "M20", "M21", "M22", "M23", "M24", "M25", "M26",
                         "M27", "M28", "M29", "M30", "M31", "M32", "M33", "M34", "M35",
                         "M36", "J5")])


def test_f38_stub_artifacts():
    print("\n== F38: header-only parity/architecture stubs fail the review contract ==")
    ctx = pp.Ctx(Path("/tmp/x"))
    ctx.cfg = {}
    sb, fj = _review_sandbox(scratch("f38_"), "# M1\n\n| acronym |\n|---|\n| CN |\n",
                             _coverage(), "| disposition |\n|---|\n")
    errs = []
    pp.check_review_contract(ctx, sb, fj, errs, [])
    check("the header-only parity artifacts are rejected",
          any("NO data row" in e for e in errs), str(errs)[:240])
    # a real one-row table still passes
    sb, fj = _review_sandbox(scratch("f38b_"), "# M1\n\n| acronym |\n|---|\n| CN |\n",
                             _coverage(), "| row | disposition |\n|---|---|\n| x | OK |\n")
    errs = []
    pp.check_review_contract(ctx, sb, fj, errs, [])
    check("a disposed one-row table passes", not any("NO data row" in e for e in errs),
          str(errs)[:240])


def test_f39_m1b_bare_token():
    print("\n== F39: a bare M1b mention is not a disposition ==")
    ctx = pp.Ctx(Path("/tmp/x"))
    ctx.cfg = {}
    m1 = ("# M1\n\n## M1b\n\n| acronym | context | file:line | long form | excerpt |\n"
          "|---|---|---|---|---|\n| CN | body | x:1 | copy-number | y |\n")
    sb, fj = _review_sandbox(scratch("f39_"), m1, _coverage("M1b long forms were reviewed"), "")
    errs = []
    pp.check_review_contract(ctx, sb, fj, errs, [])
    check("a bare token does not clear the gate",
          any("does not give a recorded REASON" in e for e in errs), str(errs)[:200])
    sb, fj = _review_sandbox(scratch("f39b_"), m1,
                             _coverage("M1b rows are long forms inside quoted titles"),
                             "| row | disposition |\n|---|---|\n| x | OK |\n")
    errs = []
    pp.check_review_contract(ctx, sb, fj, errs, [])
    check("a recorded reason clears the gate", not any("M1b long-form row" in e for e in errs),
          str(errs)[:200])


def test_f40_revision_ledger():
    print("\n== F40: ID-only revision-ledger rows are not a disposal ==")
    tmp = scratch("f40_")
    pkg = tmp / "revised"
    pkg.mkdir()
    (pkg / "revision_report.json").write_text(
        json.dumps({"F-001": "", "F-002": None, "F-003": "fixed"}))
    errs, _warns = pp.revision_ledger_problems(pkg, ["F-001", "F-002", "F-003"], 3)
    check("id-only mappings are rejected", any("without a VERDICT" in e for e in errs),
          str(errs)[:200])
    (pkg / "revision_report.json").write_text(json.dumps({"rows": [
        {"id": "F-001", "verdict": "fixed"},
        {"id": "F-002", "verdict": "false-positive"},
        {"id": "F-003", "verdict": "confirmed"}]}))
    errs, _warns = pp.revision_ledger_problems(pkg, ["F-001", "F-002", "F-003"], 3)
    check("rows with verdicts pass", errs == [], errs)
    # The container name is not pinned: a plain ID LIST is the documented
    # naming shape (test_llm_stochastic_failures A8b) and stays accepted.
    (pkg / "revision_report.json").write_text(json.dumps(
        {"finding_ids": ["F-001", "F-002", "F-003"]}))
    errs, _warns = pp.revision_ledger_problems(pkg, ["F-001", "F-002", "F-003"], 3)
    check("a plain id list is still accepted", errs == [], errs)


# ---------------------------------------------------------------- F41
def test_f41_scoped_close():
    print("\n== F41: a scoped close requires every planned run ==")
    src = inspect.getsource(pp.drive_round)
    check("the close checks the whole run plan, not only a2",
          "plan_missing = [e[\"id\"] for e in round_run_plan(ctx, r)" in src,
          [ln.strip() for ln in src.splitlines() if "plan_missing" in ln][:2])


# ---------------------------------------------------------------- F42
def test_f42_damaged_registry():
    print("\n== F42: a malformed rounds/pinned container is refused, never a traceback ==")
    for bad in ({"rounds": [{"x": 1}], "pinned": []},
                {"rounds": "broken", "pinned": []},
                {"rounds": {}, "pinned": {"bad": True}}):
        tmp = scratch("f42_")
        st = {"version": 3, "runs": {}, **bad}
        (tmp / "state.json").write_text(json.dumps(st))
        ctx = pp.Ctx(tmp)
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                ctx.load(need_cfg=False)
            raised = False
        except SystemExit:
            raised = True
        check(f"{list(bad)} is refused with a damage message",
              raised and "state.json is damaged" in err.getvalue(),
              err.getvalue()[:160])


# ---------------------------------------------------------------- F43/F44
def test_f43_f44_frozen_driver():
    print("\n== F43/F44: an edited/deleted frozen driver is refused ==")
    old_st, old_ident = pp.root_pipeline_staleness, pp.pipeline_identity
    try:
        pp.root_pipeline_staleness = lambda ctx: {
            "frozen": "/r/paper_pipeline.py", "frozen_sha256": "aaa",
            "recorded_sha256": "bbb"}
        pp.pipeline_identity = lambda: {"sha256": "aaa", "path": "/r/paper_pipeline.py"}
        mm = pp.running_pipeline_mismatch(SimpleNamespace(root=Path("/r")))
        check("an edited frozen copy sets frozen_differs", mm["frozen_differs"] is True, mm)
        pp.root_pipeline_staleness = lambda ctx: {
            "frozen": None, "frozen_sha256": "", "recorded_sha256": "bbb"}
        mm = pp.running_pipeline_mismatch(SimpleNamespace(root=Path("/r")))
        check("a deleted frozen copy is unverifiable", mm["unverifiable"] is True, mm)
    finally:
        pp.root_pipeline_staleness, pp.pipeline_identity = old_st, old_ident


# ---------------------------------------------------------------- F45
def test_f45_judge_validation():
    print("\n== F45: judges are validated against the real round count ==")
    tmp = scratch("f45_")
    (tmp / "state.json").write_text(json.dumps({"version": 3, "runs": {},
                                               "rounds": {}, "pinned": []}))
    (tmp / "pipeline_config.json").write_text(json.dumps(
        {"rounds": 0, "judges": [2, 0], "rewrites": [0], "revises": [1]}))
    ctx = pp.Ctx(tmp)
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            ctx.load(need_cfg=False)
        raised = False
    except SystemExit:
        raised = True
    check("rounds=0 + judges=[2,0] is refused", raised
          and "--judges must be >= 1 per round" in err.getvalue(), err.getvalue()[:160])


# ---------------------------------------------------------------- F46
def test_f46_unreadable_pristine():
    print("\n== F46: an unreadable pristine file is a changed pristine, not a traceback ==")
    tmp = scratch("f46_")
    pr = tmp / "non_revised"
    pr.mkdir()
    f = pr / "ms.md"
    f.write_text("x")
    ctx = SimpleNamespace(pristine=pr, source_manifest=pp.hash_manifest(pr))
    f.chmod(0)
    try:
        ok, detail = pp.pristine_integrity(ctx)
    finally:
        f.chmod(0o644)
    check("the check returns a changed verdict", ok is False and "changed" in detail, detail)


# ---------------------------------------------------------------- F48
def test_f48_state_roundtrip():
    print("\n== F48: state.json revives its own JSON sentinels ==")
    tmp = scratch("f48_")
    p = tmp / "state.json"
    pp.write_json_atomic(p, {"x": float("inf"), "y": "Infinity", "z": float("nan")})
    state, problem = pp.load_state_file(p)
    check("load_state_file revives inf/NaN and preserves the literal string",
          problem == "" and state["x"] == float("inf") and state["y"] == "Infinity"
          and state["z"] != state["z"], state)


# ---------------------------------------------------------------- F49
def test_f49_venue_profiles_manifest():
    print("\n== F49: venue_profiles is a frozen, manifested runtime asset ==")
    manifest = pp.module_manifest(WS)
    check("module_manifest records venue_profiles",
          bool(manifest.get("venue_profiles")),
          {k: (str(v)[:8] if v else None) for k, v in manifest.items()})


# ---------------------------------------------------------------- F51
def test_f51_symlink_only_source():
    print("\n== F51: setup refuses a symlink-only --source ==")
    tmp = scratch("f51_")
    src = tmp / "src"
    src.mkdir()
    real = tmp / "real.md"
    real.write_text("# Title\n")
    os.symlink(real, src / "ms.md")
    root = tmp / "root"
    proc = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
                           "--root", str(root), "--source", str(src)],
                          capture_output=True, text=True, timeout=300)
    check("setup exits non-zero with the symlink reason",
          proc.returncode != 0 and "only symlink" in (proc.stdout + proc.stderr),
          (proc.stdout + proc.stderr)[-300:])
    check("no root was created", not root.exists())


# ---------------------------------------------------------------- F56/F57
def test_f56_f57_runner():
    print("\n== F56/F57: the test runner quotes its path and validates --logs ==")
    spec = importlib.util.spec_from_file_location("fixbugs1027c_runner",
                                                  str(WS / ".paper_test/run_all.py"))
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    seen = {}

    class FakeProc:
        returncode = 0

    old_run = runner.subprocess.run
    old_one = runner.RUN_ONE
    runner.RUN_ONE = Path("/tmp/pr space/.paper_test/run_one.sh")
    runner.subprocess.run = lambda argv, **kw: (seen.setdefault("argv", argv), FakeProc())[1]
    try:
        runner.engine_parallel(["test_x"], 1, scratch("f56_"), sys.executable)
    finally:
        runner.subprocess.run = old_run
        runner.RUN_ONE = old_one
    cmd = seen.get("argv", [""])[-1]
    check("the runner path is shell-quoted", cmd.startswith("'/tmp/pr space/"), cmd)
    logs_file = scratch("f57_") / "logs"
    logs_file.write_text("")
    try:
        runner.run_dir_under(str(logs_file))
        raised = False
    except SystemExit as e:
        raised = e.code == 2
    check("--logs on a regular file is a usage error", raised)


# ---------------------------------------------------------------- F01-F08
def test_f01_f08_symlinks_and_special_files():
    print("\n== F01-F08: symlink-safe restores/walks and non-blocking JSON ==")
    # F01 raw data link, and a symlinked parent directory
    tmp = scratch("f01_")
    pristine = tmp / "pristine"
    (pristine / "raw_data").mkdir(parents=True)
    (pristine / "raw_data/data.txt").write_text("PRISTINE-RAW")
    cand = tmp / "cand"
    (cand / "raw_data").mkdir(parents=True)
    victim = tmp / "victim1.txt"
    victim.write_text("VICTIM1")
    os.symlink(victim, cand / "raw_data/data.txt")
    pp.enforce_readonly_raw_data(SimpleNamespace(pristine=pristine), cand, [])
    check("F01 a file link is replaced, its target untouched",
          victim.read_text() == "VICTIM1" and not (cand / "raw_data/data.txt").is_symlink(),
          victim.read_text())
    pristine2 = tmp / "pristine2"
    (pristine2 / "raw_data/sub").mkdir(parents=True)
    (pristine2 / "raw_data/sub/data.txt").write_text("P2")
    cand2 = tmp / "cand2"
    (cand2 / "raw_data").mkdir(parents=True)
    outside = tmp / "outside1"
    outside.mkdir()
    os.symlink(outside, cand2 / "raw_data/sub")
    victim2 = outside / "data.txt"
    victim2.write_text("SAFE")
    pp.enforce_readonly_raw_data(SimpleNamespace(pristine=pristine2), cand2, [])
    check("F01 a symlinked parent is refused", victim2.read_text() == "SAFE")
    # F02 backfill through a symlinked parent
    base = tmp / "base2"
    (base / "sub").mkdir(parents=True)
    (base / "sub/x.docx").write_text("BASE-DOC")
    sb = tmp / "sb2"
    (sb / "revised").mkdir(parents=True)
    out2 = tmp / "outside2"
    out2.mkdir()
    os.symlink(out2, sb / "revised/sub")
    info = pp.backfill_missing_files(SimpleNamespace(sandbox_of=lambda rec: sb),
                                     {"id": "r1"}, [(base, "", ())], [])
    check("F02 backfill refuses the symlinked parent",
          not (out2 / "x.docx").exists() and info["errors"], info["errors"])
    # F03 tracking auxiliary
    victim3 = tmp / "victim3.bin"
    victim3.write_text("ORIG")
    aux = tmp / "main.tracking-original.docx"
    os.symlink(victim3, aux)
    pp.tracking_force_writable(aux)
    check("F03 force-writable unlinks the link", not aux.is_symlink()
          and victim3.read_text() == "ORIG")
    aux2 = tmp / "main.tracking-original.docx"
    os.symlink(victim3, aux2)
    src3 = tmp / "src3.bin"
    src3.write_text("TRACKED")
    pp._tracking_write_copy(src3, aux2)
    check("F03 the tracking copy replaces the link", victim3.read_text() == "ORIG"
          and aux2.read_text() == "TRACKED")
    # F04 prompt / log
    victim4 = tmp / "victim4.md"
    victim4.write_text("V4")
    prompt = tmp / "REPAIR_PROMPT.md"
    os.symlink(victim4, prompt)
    pp.write_text_atomic(prompt, "PROMPT")
    check("F04 the prompt write replaces the link", victim4.read_text() == "V4"
          and prompt.read_text() == "PROMPT")
    victim5 = tmp / "victim5.log"
    victim5.write_text("V5")
    log = tmp / "_agent.log"
    os.symlink(victim5, log)
    pp.append_text_no_follow(log, "LOG")
    check("F04 the log append does not follow the link",
          victim5.read_text() == "V5" and log.read_text() == "LOG")
    # F05 merge tree
    stage = tmp / "stage"
    (stage / "official").mkdir(parents=True)
    secret = tmp / "secret.txt"
    secret.write_text("SECRET")
    os.symlink(secret, stage / "official/leak.txt")
    store = tmp / "store"
    (store / "official").mkdir(parents=True)
    pp._merge_tree(stage / "official", store / "official")
    check("F05 a source symlink is not published", not (store / "official/leak.txt").exists())
    victim6 = tmp / "victim6.txt"
    victim6.write_text("V6")
    os.symlink(victim6, store / "official/file.txt")
    (stage / "official/file.txt").write_text("NEW")
    pp._merge_tree(stage / "official", store / "official")
    check("F05 a destination symlink is replaced",
          victim6.read_text() == "V6" and (store / "official/file.txt").read_text() == "NEW")
    # F06 copy_into with a symlinked source root
    real = tmp / "real"
    real.mkdir()
    (real / "secret.txt").write_text("SECRET")
    link = tmp / "src_link"
    os.symlink(real, link)
    dst = tmp / "dst6"
    dst.mkdir()
    pp.copy_into(link, dst)
    check("F06 a symlinked source root is not traversed",
          not (dst / "secret.txt").exists())
    # F07 nested directory link in a followed walk
    root7 = tmp / "root7"
    (root7 / "non_revised/raw_data").mkdir(parents=True)
    (root7 / "non_revised/raw_data/a.txt").write_text("A")
    sb7 = tmp / "sb7"
    sb7.mkdir()
    os.symlink(root7 / "non_revised/raw_data", sb7 / "raw_data")
    outside7 = tmp / "outside7"
    outside7.mkdir()
    (outside7 / "secret.txt").write_text("S")
    os.symlink(outside7, root7 / "non_revised/raw_data/nested")
    names = [p.relative_to(sb7).as_posix()
             for p in pp._iter_tree_files(sb7, follow_dir_links=True)]
    check("F07 the top-level evidence link is followed", "raw_data/a.txt" in names, names)
    check("F07 a nested link is not followed",
          not any("nested" in n for n in names), names)
    # F08 FIFO
    if hasattr(os, "mkfifo"):
        fifo = tmp / "findings.json"
        os.mkfifo(fifo)
        t0 = time.time()
        val = pp.read_json(fifo, lenient=True)
        check("F08 read_json does not block on a FIFO",
              val is None and time.time() - t0 < 2, f"{val!r} {time.time() - t0:.2f}s")


# ---------------------------------------------------------------- F59/F60
def test_f59_f60_docs():
    print("\n== F59/F60: Node-only checks skip and the README no longer overclaims ==")
    text = (WS / ".paper_test/test_fix_bugs_20261027_074031.py").read_text(encoding="utf-8")
    check("both Node-only checks are guarded", text.count('shutil.which("node")') >= 2,
          text.count('shutil.which("node")'))
    readme = (WS / "README.md").read_text(encoding="utf-8")
    check("README no longer calls .paper_test/README.md the full table",
          "for the full table" not in readme
          and "table of the main suites" in readme)


def main() -> int:
    tests = [
        test_f11_self_closing_wt, test_f12_unlink_fields, test_f13_anchor_paragraph,
        test_f14_sectpr_break, test_f15_unreadable_parts, test_f16_malformed_document,
        test_f17_image_only_page, test_f17b_header_logo_blank_page, test_f18_zero_length_tail, test_f19_rpr_whitespace,
        test_f20_titlepg_order, test_f21_same_run_emphasis, test_f22_verifier_not_intersection,
        test_f24_f25_mcp_probe, test_f27_failed_fixer, test_f28_sandbox_order,
        test_f29_invalid_char_refs, test_f31_render_fallback_args, test_f33_redline_restore,
        test_f37_bounded_repair_audit, test_f38_stub_artifacts, test_f39_m1b_bare_token,
        test_f40_revision_ledger, test_f41_scoped_close, test_f42_damaged_registry,
        test_f43_f44_frozen_driver, test_f45_judge_validation, test_f46_unreadable_pristine,
        test_f48_state_roundtrip, test_f49_venue_profiles_manifest, test_f51_symlink_only_source,
        test_f56_f57_runner, test_f01_f08_symlinks_and_special_files, test_f59_f60_docs,
    ]
    for fn in tests:
        try:
            fn()
        except Exception as e:                                    # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(f"{fn.__name__} completed", False, f"{type(e).__name__}: {e}")
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL 2026-10-27 12:00 FIX-BUGS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

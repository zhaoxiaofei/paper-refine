#!/usr/bin/env python3
"""Regressions pinned from the 2026-10-07 focused audit.

Each check fails on the tree the audit reviewed:

  G1  `setup --revision-mode major|minor` wrote `rounds: 1` while the per-round
      lists still carried the three entries the default `--rounds 3` expanded
      to (`set-revision-mode` writes length-1 lists for the same mode);
  G2  an encrypted (or otherwise unreadable) .docx leaked a raw zip traceback
      out of `scan`/`fix` instead of the module's FMT-X1 / `ok: false` report;
  G3  the fixer rewrote text inside a live Zotero field RESULT (the scanner had
      no protected row for it, so "every mechanical finding resolved" held while
      the citation's rendered text changed);
  G4  a duplicate `w:fldChar separate` inside one field was silently accepted;
  G5  a Zotero field written as `w:fldSimple` was invisible to the inventory;
  G6  a note-style manuscript (citations in `word/footnotes.xml`) reported zero
      fields -- the stage gate protected nothing;
  G7  a bibliography field whose visible reference list shrank changed nothing;
  G8  a deliberately CROPPED image (`a:srcRect`) was reported as FMT-IM1 and the
      "fix" then distorted it by rewriting cy;
  G9  a self-closing `<w:sectPr .../>` as the first section made the page-1
      header/footer signature read the FOLLOWING section.
  G13 the bundled formatter's own EVIDENCE-area set omitted
      `llm_review_feedback/`, so its `scan`/`validate` CLIs treated an LLM
      review's .docx as submission content;
  G14 a zip without `word/document.xml` must stay `unreadable-docx` -- reading
      several parts must not turn a broken package into an empty inventory.

Run:  python3 .paper_test/test_audit_gaps_2026_1007.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_gaps", str(WS / "paper_pipeline.py"))
PP = importlib.util.module_from_spec(spec)
sys.modules["paper_gaps"] = PP
spec.loader.exec_module(PP)
fspec = importlib.util.spec_from_file_location("gaps_fmt", str(WS / "paper_docx_format.py"))
FMT = importlib.util.module_from_spec(fspec)
sys.modules["gaps_fmt"] = FMT
fspec.loader.exec_module(FMT)

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
WP = 'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
PIC = 'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def doc(body: str) -> str:
    return f'<?xml version="1.0"?><w:document {W} {R}><w:body>{body}</w:body></w:document>'


def para(inner: str, style: str = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{inner}</w:p>"


def item_field(cid="CIT0001", visible="19", instr_tail="", fld_simple=False) -> str:
    payload = json.dumps({"citationID": cid, "properties": {"formattedCitation": visible},
                          "citationItems": [], "schema": "x"})
    if fld_simple:
        return (f'<w:fldSimple w:instr=" ADDIN ZOTERO_ITEM CSL_CITATION '
                f'{payload.replace(chr(34), "&quot;")} "><w:r><w:t>{visible}</w:t></w:r>'
                f'</w:fldSimple>')
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve"> ADDIN ZOTERO_ITEM CSL_CITATION '
            f'{payload}{instr_tail} </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r><w:t xml:space="preserve">{visible}</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def bibl_field(visible: str) -> str:
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> ADDIN ZOTERO_BIBL {"uncited":[]} '
            'CSL_BIBLIOGRAPHY </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r><w:t xml:space="preserve">{visible}</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


BASE_PACKAGE = {
    "[Content_Types].xml":
        '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/'
        '2006/content-types"/>',
    "_rels/.rels":
        '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
        'package/2006/relationships"/>',
    "word/styles.xml":
        f'<?xml version="1.0"?><w:styles {W}>'
        '<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
        '</w:styles>',
}


def make_package(path: Path, parts: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return path


def make_docx(path: Path, document_xml: str, extra: dict = None) -> Path:
    parts = dict(BASE_PACKAGE)
    parts["word/document.xml"] = document_xml
    parts.update(extra or {})
    return make_package(path, parts)


def encrypt(path: Path) -> None:
    """Mark every zip entry as encrypted (the flag zipfile raises RuntimeError on)."""
    data = bytearray(path.read_bytes())
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = 0
        while True:
            i = data.find(sig, i)
            if i < 0:
                break
            flags = int.from_bytes(data[i + off:i + off + 2], "little") | 1
            data[i + off:i + off + 2] = flags.to_bytes(2, "little")
            i += 4
    path.write_bytes(bytes(data))


# ---------------------------------------------------------------- G1
def test_scoped_setup_plan_is_consistent():
    print()
    print("== G1: setup --revision-mode writes a plan that agrees with its rounds ==")
    tmp = scratch("paper_gaps_scoped_")
    src = tmp / "src"
    src.mkdir()
    (src / "manuscript.txt").write_text("Abstract\nWe used scRNA-seq.\n", encoding="utf-8")
    root = tmp / "root"
    r = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
                        "--source", str(src), "--root", str(root),
                        "--revision-mode", "major", "--journal", "Journal of Tests"],
                       capture_output=True, text=True, timeout=600)
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("G1 setup succeeds", r.returncode == 0, r.stderr[-200:])
    check("G1 the mode forces one round", cfg["rounds"] == 1, json.dumps(cfg.get("rounds")))
    for key, want in (("rewrites", [0]), ("revises", [1]), ("integrators", [0]),
                      ("review_scope", ["full"])):
        check(f"G1 {key} carries exactly the one round's value",
              list(cfg.get(key) or []) == want,
              f"{cfg.get(key)!r} vs {want!r}")
    check("G1 the printed plan shows the same one-round list",
          "rewrites per round (M): [0]" in r.stdout
          and "rewrites per round (M): [0, 0, 0]" not in r.stdout,
          [ln for ln in r.stdout.splitlines() if "rewrites per round" in ln])


# ---------------------------------------------------------------- G2
def test_unreadable_docx_never_leaks_a_traceback():
    print()
    print("== G2: an encrypted .docx degrades to FMT-X1 / ok:false, never a traceback ==")
    tmp = scratch("paper_gaps_enc_")
    pkgdir = tmp / "pkg"
    pkgdir.mkdir()
    enc = make_docx(pkgdir / "locked.docx", doc(para('<w:r><w:t>Hello</w:t></w:r>')))
    encrypt(enc)
    scan = subprocess.run([sys.executable, str(WS / "paper_docx_format.py"), "scan",
                           str(pkgdir), "--json", str(tmp / "scan.json")],
                          capture_output=True, text=True)
    rows = json.loads((tmp / "scan.json").read_text(encoding="utf-8"))["rows"] \
        if (tmp / "scan.json").is_file() else []
    check("G2 the scan survives an encrypted package",
          scan.returncode == 0 and "Traceback" not in scan.stderr,
          (scan.stderr or scan.stdout)[-200:])
    check("G2 the scan reports the encrypted file as FMT-X1",
          any(r.get("rule") == "FMT-X1" and r.get("document") == "locked.docx" for r in rows),
          str([r.get("rule") for r in rows]))
    fix = subprocess.run([sys.executable, str(WS / "paper_docx_format.py"), "fix", str(enc),
                          "--out", str(tmp / "out.docx")],
                         capture_output=True, text=True)
    check("G2 the fixer reports the encrypted package instead of crashing",
          fix.returncode == 1 and "Traceback" not in fix.stderr
          and "unreadable DOCX package" in (fix.stdout + fix.stderr),
          (fix.stdout + fix.stderr)[-200:])
    bad = make_docx(tmp / "badstyles.docx", doc(para('<w:r><w:t>x</w:t></w:r>')),
                    extra={"word/styles.xml": "<w:styles> not xml"})
    fix2 = subprocess.run([sys.executable, str(WS / "paper_docx_format.py"), "fix", str(bad),
                           "--out", str(tmp / "out2.docx")],
                          capture_output=True, text=True)
    check("G2 a malformed styles.xml is reported, not a ParseError traceback",
          fix2.returncode == 1 and "Traceback" not in fix2.stderr,
          (fix2.stdout + fix2.stderr)[-200:])


# ---------------------------------------------------------------- G3
def test_formatter_never_edits_inside_a_live_field():
    print()
    print("== G3: text inside a live field result is field-protected ==")
    tmp = scratch("paper_gaps_fieldedit_")
    src = make_docx(tmp / "src.docx", doc(para(item_field(visible="The the 19"))))
    info = FMT.analyse_package(src, dict(FMT.POLICY_DEFAULTS))
    g1 = [r for r in info["rows"] if r["rule"] == "FMT-G1"]
    check("G3 the doubled word inside the field is still reported",
          len(g1) == 1, str(info["rows"]))
    check("G3 the row is field-protected (style-field, never mechanical)",
          bool(g1) and g1[0]["fix"] == "style-field" and g1[0]["protected"] is True,
          json.dumps(g1[:1]))
    out = tmp / "out.docx"
    rep = FMT.fix_package(src, out, dict(FMT.POLICY_DEFAULTS))
    with zipfile.ZipFile(out) as z:
        after = z.read("word/document.xml").decode("utf-8")
    check("G3 the fixer leaves the citation's visible text alone",
          "The the 19" in after and "The 19" not in after, after[after.find("<w:t"):][:120])
    check("G3 the fixer's own verification stays green",
          rep["verified"]["mechanical_findings_before"] == 0
          and rep["verified"]["remaining_mechanical_rules"] == [],
          json.dumps({k: rep["verified"][k] for k in ("mechanical_findings_before",
                                                      "mechanical_findings_after")}))


# ---------------------------------------------------------------- G4/G5/G6/G7
def test_field_inventory_gaps():
    print()
    print("== G4-G7: the field inventory sees fldSimple, footnotes and shrink ==")
    dup = FMT.zotero_field_report(doc(para(
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> ADDIN ZOTERO_ITEM CSL_CITATION '
        '{"citationID":"a","citationItems":[],"properties":{},"schema":"x"} </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        '<w:r><w:t>1</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>')))
    check("G4 a duplicate fldChar separate is a structural error",
          any("duplicate-separate" in e for e in dup["errors"]), str(dup["errors"]))

    simple = FMT.zotero_field_report(doc(para(item_field(cid="b1", visible="2",
                                                         fld_simple=True))))
    check("G5 a fldSimple Zotero citation is inventoried",
          simple["counts"]["item"] == 1 and simple["fields"][0]["citationID"] == "b1",
          json.dumps(simple["counts"]) + str(simple["errors"]))
    plain = FMT.zotero_field_report(doc(para('<w:r><w:t>2</w:t></w:r>')))
    cont = FMT.zotero_field_continuity_problems(simple, plain)
    check("G5 converting the fldSimple field to plain text is an error",
          any("plain-text replacement" in e for e in cont["errors"]), str(cont["errors"]))

    switched = FMT.zotero_field_report(doc(para(item_field(
        cid="sw1", visible="4", instr_tail=" \\* MERGEFORMAT"))))
    check("G12 a citation with a trailing Word field switch is still parsed",
          switched["fields"][0]["citationID"] == "sw1" and not switched["errors"],
          f"{switched['fields'][0]['citationID']!r} {switched['errors']}")
    junk = FMT.zotero_field_report(doc(para(item_field(
        cid="j1", visible="4", instr_tail=" oops"))))
    check("G12 junk after the citation JSON is still a fault",
          "bad-citation-json" in (junk["error_codes"] or {}), str(junk["errors"]))

    tmp = scratch("paper_gaps_parts_")
    fn_field = ('<w:footnote w:id="1">'
                + para(item_field(cid="fn1", visible="Chen 2017"))
                + "</w:footnote>")
    note = make_docx(tmp / "note.docx", doc(para('<w:r><w:t>Body text.</w:t></w:r>')),
                     extra={"word/footnotes.xml": f'<?xml version="1.0"?><w:footnotes {W}>{fn_field}'
                                                  f'</w:footnotes>'})
    rep = FMT.zotero_report_for_docx(note)
    check("G6 a field in word/footnotes.xml is inventoried",
          rep["counts"]["item"] == 1, json.dumps(rep["counts"]))
    stripped = make_docx(tmp / "note_plain.docx", doc(para('<w:r><w:t>Body text.</w:t></w:r>')),
                         extra={"word/footnotes.xml":
                                f'<?xml version="1.0"?><w:footnotes {W}>'
                                '<w:footnote w:id="1"><w:p><w:r><w:t>Chen 2017</w:t></w:r>'
                                '</w:p></w:footnote></w:footnotes>'})
    cont2 = FMT.zotero_field_continuity_problems(rep, FMT.zotero_report_for_docx(stripped))
    check("G6 deleting the footnote field is refused",
          any("ALL 1 Zotero field" in e for e in cont2["errors"]), str(cont2["errors"]))

    base = FMT.zotero_field_report(doc(para(bibl_field("1. Alpha 2019. 2. Beta 2020."))))
    shrank = FMT.zotero_field_report(doc(para(bibl_field("1. Alpha 2019."))))
    cont3 = FMT.zotero_field_continuity_problems(base, shrank)
    check("G7 a shrunken bibliography's visible text is reported",
          any("shrank" in w for w in cont3["warnings"]), str(cont3["warnings"]))
    grown = FMT.zotero_field_report(doc(para(bibl_field(
        "1. Alpha 2019. 2. Beta 2020. 3. Gamma 2021."))))
    cont4 = FMT.zotero_field_continuity_problems(base, grown)
    check("G7 a grown bibliography is an ordinary revision (no warning)",
          not any("shrank" in w for w in cont4["warnings"]), str(cont4["warnings"]))

    degraded = FMT.zotero_field_report(doc(para(
        '<w:r><w:instrText xml:space="preserve"> ADDIN ZOTERO_ITEM CSL_CITATION '
        '{"citationID":"x"} </w:instrText></w:r>')))
    gone = FMT.zotero_field_report(doc(para('<w:r><w:t>plain text now</w:t></w:r>')))
    cont5 = FMT.zotero_field_continuity_problems(degraded, gone)
    check("G10 a baseline whose structure cannot be inventoried is reported, "
          "not compared empty-to-empty",
          any("no field baseline" in w for w in cont5["warnings"]), str(cont5["warnings"]))


# ---------------------------------------------------------------- G8
def png(w: int, h: int) -> bytes:
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
            + struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00")


def drawing_docx(path: Path, src_rect: str) -> Path:
    document = (f'<?xml version="1.0"?><w:document {W} {R}><w:body>'
                f'<w:p><w:r><w:drawing><wp:inline {WP} {A} {PIC}>'
                f'<wp:extent cx="1000000" cy="1000000"/>'
                f'<a:graphic><a:graphicData uri="pic"><pic:pic><pic:blipFill>'
                f'<a:blip r:embed="rId9"/>{src_rect}</pic:blipFill></pic:pic>'
                f'</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
                f'</w:body></w:document>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships"><Relationship Id="rId9" Type="http://schemas.'
            'openxmlformats.org/officeDocument/2006/relationships/image" '
            'Target="media/image1.png"/></Relationships>')
    return make_docx(path, document, extra={"word/_rels/document.xml.rels": rels,
                                            "word/media/image1.png": png(200, 100)})


def test_cropped_image_is_not_repaired():
    print()
    print("== G8: a cropped image's drawn ratio is compared with the CROP ==")
    tmp = scratch("paper_gaps_crop_")
    crop = drawing_docx(tmp / "cropped.docx", '<a:srcRect l="0" t="0" r="50000" b="0"/>')
    check("G8 a 50%-cropped 2:1 PNG drawn square is not FMT-IM1",
          not [r for r in FMT.analyse_package(crop, dict(FMT.POLICY_DEFAULTS))["rows"]
               if r["rule"] == "FMT-IM1"],
          str(FMT.analyse_package(crop, dict(FMT.POLICY_DEFAULTS))["rows"]))
    out = tmp / "cropped.fixed.docx"
    FMT.fix_package(crop, out, dict(FMT.POLICY_DEFAULTS))
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    check("G8 the fixer leaves the cropped extent alone",
          'cx="1000000" cy="1000000"' in xml, xml[xml.find("<wp:extent"):][:60])
    plain = drawing_docx(tmp / "plain.docx", "")
    rows = [r for r in FMT.analyse_package(plain, dict(FMT.POLICY_DEFAULTS))["rows"]
            if r["rule"] == "FMT-IM1"]
    check("G8 an UNCROPPED 2:1 PNG drawn square is still FMT-IM1", len(rows) == 1, str(rows))
    out2 = tmp / "plain.fixed.docx"
    FMT.fix_package(plain, out2, dict(FMT.POLICY_DEFAULTS))
    with zipfile.ZipFile(out2) as z:
        xml2 = z.read("word/document.xml").decode("utf-8")
    check("G8 and its aspect ratio is still restored",
          'cx="1000000" cy="500000"' in xml2, xml2[xml2.find("<wp:extent"):][:60])


# ---------------------------------------------------------------- G9
def test_self_closing_first_section():
    print()
    print("== G9: a self-closing first sectPr is read as its own section ==")
    tmp = scratch("paper_gaps_sect_")
    body = (para('<w:r><w:t>page one</w:t></w:r><w:sectPr/>')
            + para('<w:r><w:t>page two</w:t></w:r>'
                   '<w:sectPr><w:headerReference w:type="default" r:id="rId6"/></w:sectPr>'))
    xml = (f'<?xml version="1.0"?><w:document {W} {R}><w:body>{body}</w:body></w:document>')
    check("G9 the formatter reads the FIRST (empty) section",
          FMT.first_section_props(xml) == "<w:sectPr/>", repr(FMT.first_section_props(xml)))
    docx = make_docx(tmp / "two_sections.docx", xml)
    sig = PP._docx_hf_signature(docx)
    check("G9 the page-1 furniture signature does not borrow the next section's header",
          sig.get("roles") == [], json.dumps(sig))
    container = (f'<?xml version="1.0"?><w:document {W} {R}><w:body>'
                 + para('<w:r><w:t>one</w:t></w:r>'
                        '<w:sectPr><w:headerReference w:type="first" r:id="rId5"/></w:sectPr>')
                 + para('<w:r><w:t>two</w:t></w:r>'
                        '<w:sectPr><w:headerReference w:type="default" r:id="rId6"/></w:sectPr>')
                 + '</w:body></w:document>')
    check("G9 a normal first section is still read as itself",
          'w:type="first"' in (FMT.first_section_props(container) or ""),
          repr(FMT.first_section_props(container)))


# ---------------------------------------------------------------- G11
def test_document_key_collision_is_reported():
    print()
    print("== G11: two documents that pair to one token-free key are named ==")
    tmp = scratch("paper_gaps_clash_")
    (tmp / "base").mkdir()
    (tmp / "out").mkdir()
    for name, field_xml in (("appendix-a.docx", item_field(cid="a1", visible="9")),
                            ("appendix-b.docx", item_field(cid="b1", visible="7"))):
        make_docx(tmp / "base" / name, doc(para(field_xml)))
        make_docx(tmp / "out" / name, doc(para(field_xml)))
    check("G11 the two names really do strip to one key",
          PP._docx_field_key("appendix-a.docx") == PP._docx_field_key("appendix-b.docx")
          == "appendix.docx", PP._docx_field_key("appendix-a.docx"))
    errs, warns = [], []
    PP.zotero_field_continuity_check(tmp / "base", tmp / "out", "clash", errs, warns)
    check("G11 the collision is reported instead of silently dropping a document",
          sum("pair to one key" in w for w in warns) >= 1, str(warns))


# ---------------------------------------------------------------- G13
def test_the_llm_review_area_is_evidence_for_the_formatter():
    print()
    print("== G13: the formatter's own EVIDENCE set names llm_review_feedback/ ==")
    check("G13 paper_docx_format names the pipeline's evidence areas",
          set(FMT.EVIDENCE_DIRNAMES) == set(PP.EVIDENCE_DIRNAMES),
          f"{sorted(FMT.EVIDENCE_DIRNAMES)} vs {sorted(PP.EVIDENCE_DIRNAMES)}")
    tmp = scratch("paper_gaps_evdir_")
    pkg = tmp / "pkg"
    (pkg / "llm_review_feedback").mkdir(parents=True)
    make_docx(pkg / "main.docx",
              doc(para('<w:r><w:t>A clean manuscript paragraph, nothing to report.</w:t></w:r>')))
    make_docx(pkg / "llm_review_feedback" / "review.docx",
              doc(para('<w:r><w:t>The the review carries a doubled word.</w:t></w:r>')))
    scan = FMT.scan_paths([pkg], dict(FMT.POLICY_DEFAULTS))
    check("G13 a .docx inside llm_review_feedback/ is not scanned as submission content",
          [Path(f).name for f in scan["files"]] == ["main.docx"], str(scan["files"]))
    check("G13 its doubled word is not reported as a submission finding",
          scan["rows"] == [], str(scan["rows"])[:200])
    val = FMT.validate_paths([pkg], timeout=60)
    check("G13 validate does not treat it as a deliverable",
          val["files"] == 1
          and [Path(r["file"]).name for r in val["results"]] == ["main.docx"],
          f"files={val['files']} {[r['file'] for r in val['results']]}")


# ---------------------------------------------------------------- G14
def test_a_package_without_the_main_part_is_still_unreadable():
    print()
    print("== G14: a zip without word/document.xml is still an unreadable DOCX ==")
    tmp = scratch("paper_gaps_nomain_")
    pkg = make_package(tmp / "no_main.docx",
                       {"word/footnotes.xml": f'<?xml version="1.0"?><w:footnotes {W}/>'
                                              f'</w:footnotes>'})
    rep = FMT.zotero_report_for_docx(pkg)
    check("G14 the missing main part is reported, not read as 'no fields'",
          rep["error_codes"] == {"unreadable-docx": 1} and not rep["fields"],
          json.dumps(rep)[:200])


def main() -> int:
    try:
        test_scoped_setup_plan_is_consistent()
        test_unreadable_docx_never_leaks_a_traceback()
        test_formatter_never_edits_inside_a_live_field()
        test_field_inventory_gaps()
        test_cropped_image_is_not_repaired()
        test_self_closing_first_section()
        test_document_key_collision_is_reported()
        test_the_llm_review_area_is_evidence_for_the_formatter()
        test_a_package_without_the_main_part_is_still_unreadable()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL 2026-10-07 AUDIT-GAP CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

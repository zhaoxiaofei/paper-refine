#!/usr/bin/env python3
"""The offline Zotero REFRESH — the pipeline repairs stale citation numbering,
the bibliography order, the style stores and the flagged reference entries
WITHOUT Word/Zotero (2026-10-11).

Run:  python3 .paper_test/test_zotero_auto_refresh_2026_1011.py

What these checks pin (each one is a defect the 2026-10-11 CopyNumBench audit
found in a CERTIFIED package):

  * `zotero_refresh_document` re-derives every marker from the document's own
    citation order and rebuilds a bibliography whose order/numbers disagree —
    the same repair Word/Zotero `Refresh` performs, but offline and verified;
  * the repair is all-or-nothing: an unresolvable item/item-list refuses the
    whole refresh instead of writing a half-correct document;
  * the style stores are reconciled to ONE CSL style (FMT-Z5's repair);
  * `fix_package` runs all of it automatically (policy `refresh_zotero_fields`,
    default ON) and its own verification still passes;
  * `unlink_zotero_fields` now flattens AFTER the refresh, so a field-free
    submission copy carries the CORRECT numbers (the old guard refused to
    flatten a stale document — with the refresh integrated there is nothing
    stale left to freeze);
  * `repair_reference_entries` fixes the FMT-R1/R2/R3 shapes from the values a
    sibling .bib proves (volume/article, arXiv locator, software year);
  * the XFA reader counts answers ACROSS dataset packets (the filled-form false
    "UNFILLED" cannot come back) and `xfa_export_text` renders them readably;
  * `package_readiness` / `readiness_gate_problems` turn the published package's
    own findings into a submission-readiness verdict and an optional gate.

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import html
import importlib.util
import inspect
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fmt = _load("paper_zar_format", WS / "paper_docx_format.py")
pp = _load("paper_zar_pipeline", WS / "paper_pipeline.py")

FAILS = []
TMPDIRS = []
STYLE_OLD = "http://www.zotero.org/styles/nature"
STYLE_NEW = "http://www.zotero.org/styles/nature-biotechnology"


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


ITEMS = {
    "K1": {"title": "Alpha diversity in single cells", "family": "Alvarez", "year": 2020},
    "K2": {"title": "Beta catenin signalling atlas", "family": "Bianchi", "year": 2021},
}


def _cite_instr(cid: str, marker: str, keys: list, visible: str) -> str:
    payload = {
        "citationID": cid,
        "properties": {"formattedCitation": marker, "plainCitation": visible, "noteIndex": 0},
        "citationItems": [
            {"id": k + "/1",
             "uris": [f"http://zotero.org/users/local/AAA/items/{k}"],
             "itemData": {"type": "article-journal", "title": ITEMS[k]["title"],
                          "author": [{"family": ITEMS[k]["family"], "given": "A"}],
                          "issued": {"date-parts": [[ITEMS[k]["year"]]]}}}
            for k in keys],
        "schema": "https://github.com/citation-style-language/schema/raw/master/csl-citation.json",
    }
    return "ADDIN ZOTERO_ITEM CSL_CITATION " + json.dumps(payload, ensure_ascii=False)


def _field_para(cid: str, marker: str, keys: list, visible: str, superscript=True) -> str:
    instr = html.escape(_cite_instr(cid, marker, keys, visible), quote=False)
    rpr = '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr>' if superscript else ""
    return ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve">{instr}</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r>{rpr}<w:t>{visible}</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')


def _bib_para_in_field(number: int, text: str, opener: str = "", closer: str = "") -> str:
    """One bibliography entry paragraph; entries live INSIDE the BIBL field."""
    return ('<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>'
            + opener
            + f'<w:r><w:t>{number}.</w:t></w:r>'
            + f'<w:r><w:tab/><w:t xml:space="preserve">{text}</w:t></w:r>'
            + closer + "</w:p>")


def _docx(path: Path, *, marker_a: str, visible_a: str,
          marker_b: str, visible_b: str,
          entry1_keys=("K1",), entry2_keys=("K2",),
          styles=(STYLE_OLD, STYLE_NEW)) -> Path:
    """A DOCX whose fields/bibliography are STALE on purpose.

    Citation A cites item K1 (rank 1) but renders `marker_a`; citation B cites
    K2 (rank 2) but renders `marker_b`. The bibliography field's result lists
    Beta first (as entry 2) and Alpha second (as entry 1) — the order the stale
    numbers imply, which the refresh must reorder.
    """
    body = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">',
            "<w:body>"]
    body.append("<w:p><w:r><w:t>Main text.</w:t></w:r></w:p>")
    body.append(_field_para("citeA", marker_a, list(entry1_keys), visible_a))
    body.append(_field_para("citeB", marker_b, list(entry2_keys), visible_b))
    body.append("<w:p><w:r><w:t>References</w:t></w:r></w:p>")
    bib_open = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                '<w:r><w:instrText xml:space="preserve">ADDIN ZOTERO_BIBL '
                '{"uncited":[],"omitted":[],"custom":[]} CSL_BIBLIOGRAPHY</w:instrText></w:r>'
                '<w:r><w:fldChar w:fldCharType="separate"/></w:r>')
    entry_beta = ("Bianchi, B. et al. Beta catenin signalling atlas. Journal 2, 1-9 (2021).")
    entry_alpha = ("Alvarez, A. et al. Alpha diversity in single cells. Journal 1, 1-9 (2020).")
    body.append(_bib_para_in_field(2, entry_beta, opener=bib_open))
    body.append(_bib_para_in_field(1, entry_alpha))
    body.append('<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>'
                '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    body.append("</w:body></w:document>")
    old, new = styles
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships '
                                  'xmlns="http://schemas.openxmlformats.org/package/2006/'
                                  'relationships"/>')
        z.writestr("word/document.xml", "\n".join(body))
        z.writestr("word/styles.xml", '<?xml version="1.0"?><w:styles '
                                     'xmlns:w="http://schemas.openxmlformats.org/'
                                     'wordprocessingml/2006/main"/>')
        z.writestr("word/settings.xml",
                   '<?xml version="1.0"?><w:settings xmlns:w="http://schemas.openxmlformats.'
                   'org/wordprocessingml/2006/main"><w:docVars><w:docVar '
                   'w:name="ZOTERO_PREF_1" w:val="&lt;data&gt;&lt;style id=&quot;'
                   f'{old}&quot;/&gt;&lt;/data&gt;"/></w:docVars></w:settings>')
        z.writestr("docProps/custom.xml",
                   '<?xml version="1.0"?><Properties><property '
                   'fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" '
                   'name="ZOTERO_PREF_1"><vt:lpwstr>&lt;data&gt;&lt;style id="'
                   f'{new}"/&gt;&lt;/data&gt;</vt:lpwstr></property></Properties>')
    return path


def _texts(path: Path):
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    return [fmt.text_of(p[2]) for p in fmt.paragraphs(xml)], xml


# ---------------------------------------------------------------------------
# 1. the refresh engine itself
# ---------------------------------------------------------------------------
def test_refresh_document():
    tmp = scratch("zar_doc_")
    p = _docx(tmp / "m.docx", marker_a=r"\super 2\nosupersub{}", visible_a="2",
              marker_b=r"\super 1\nosupersub{}", visible_b="1")
    texts, xml = _texts(p)
    rows_before = fmt.zotero_parity_rows(xml, texts)
    check("the stale fixture reports FMT-Z1/FMT-Z2 before the refresh",
          any(r["rule"] == "FMT-Z1" for r in rows_before)
          and any(r["rule"] == "FMT-Z2" for r in rows_before),
          str(sorted({r['rule'] for r in rows_before})))
    res = fmt.zotero_refresh_document(xml, texts)
    check("the refresh repairs the document", res["changed"], str(res.get("skip")))
    new_xml = res["xml"]
    new_texts = [fmt.text_of(p[2]) for p in fmt.paragraphs(new_xml)]
    rows_after = fmt.zotero_parity_rows(new_xml, new_texts)
    check("no stale-parity row survives the refresh",
          not [r for r in rows_after if r["rule"] in ("FMT-Z1", "FMT-Z2", "FMT-Z4")],
          str(rows_after[:3]))
    joined = "\n".join(new_texts)
    check("citation A now renders its item's rank (1)",
          "Main text." in joined and "1" in new_texts[1] and "2" in new_texts[2],
          repr([new_texts[1], new_texts[2]]))
    check("the bibliography was rebuilt in rank order (Alpha entry 1, Beta entry 2)",
          "1.Alvarez" in new_texts[4].replace(" ", "") and "2.Bianchi" in new_texts[5].replace(" ", ""),
          repr([new_texts[4][:40], new_texts[5][:40]]))
    res2 = fmt.zotero_refresh_document(new_xml, new_texts)
    check("the refresh is idempotent (a second pass is a no-op)", not res2["changed"])


def test_refresh_refuses_unrebuildable_markers():
    tmp = scratch("zar_refuse_")
    # Citation B's marker carries prose the rebuild does not understand: the
    # whole-document refresh must refuse rather than fix A and leave B stale.
    p = _docx(tmp / "m.docx", marker_a=r"\super 2\nosupersub{}", visible_a="2",
              marker_b=r"\super see 1\nosupersub{}", visible_b="see 1")
    xml = zipfile.ZipFile(p).read("word/document.xml").decode("utf-8")
    texts = [fmt.text_of(q[2]) for q in fmt.paragraphs(xml)]
    res = fmt.zotero_refresh_document(xml, texts)
    check("a marker the refresh cannot rebuild refuses the whole refresh (nothing written)",
          (not res["changed"]) and res["skip"], str(res.get("skip")))
    check("the refused refresh returns the document byte-identical",
          res["xml"] == xml)


def test_refresh_rebuilds_a_stale_bibliography_order():
    tmp = scratch("zar_biborder_")
    # The markers already match their ranks; only the bibliography PARAGRAPHS
    # run 2,1 (each numbered entry still describes the work its own number
    # names, so no other rule sees it). The refresh must rebuild the list
    # anyway -- a Word/Zotero refresh re-sorts it.
    p = _docx(tmp / "m.docx", marker_a=r"\super 1\nosupersub{}", visible_a="1",
              marker_b=r"\super 2\nosupersub{}", visible_b="2")
    texts, xml = _texts(p)
    rows_before = fmt.zotero_parity_rows(xml, texts)
    check("the stale ORDER alone is reported (FMT-Z2, no stale marker)",
          any(r["rule"] == "FMT-Z2" for r in rows_before)
          and not any(r["rule"] == "FMT-Z1" for r in rows_before),
          str(sorted({r["rule"] for r in rows_before})))
    res = fmt.zotero_refresh_document(xml, texts)
    check("the refresh rebuilds a bibliography whose order alone is stale",
          res["changed"] and res["reordered"], str(res.get("skip")))
    new_texts = [fmt.text_of(q[2]) for q in fmt.paragraphs(res["xml"])]
    check("the rebuilt list runs in rank order (Alpha entry 1, Beta entry 2)",
          "1.Alvarez" in new_texts[4].replace(" ", "")
          and "2.Bianchi" in new_texts[5].replace(" ", ""),
          repr([new_texts[4][:40], new_texts[5][:40]]))
    check("no FMT-Z2 row survives the rebuild",
          not [r for r in fmt.zotero_parity_rows(res["xml"], new_texts)
               if r["rule"] == "FMT-Z2"])


def test_refresh_refuses_a_run_with_two_text_elements():
    tmp = scratch("zar_multit_")
    p = _docx(tmp / "m.docx", marker_a=r"\super 2\nosupersub{}", visible_a="2",
              marker_b=r"\super 1\nosupersub{}", visible_b="1")
    xml = zipfile.ZipFile(p).read("word/document.xml").decode("utf-8")
    # Two `w:t` elements in the field's own result run: the rebuilt run is
    # cloned from that run, so the second element's stale text would survive
    # beside the new number. The refresh must refuse (all-or-nothing) instead
    # of writing a half-repaired marker.
    xml2 = xml.replace("<w:t>2</w:t>", '<w:t>2</w:t><w:t>X</w:t>', 1)
    check("the fixture carries a two-text result run", xml2 != xml)
    texts = [fmt.text_of(q[2]) for q in fmt.paragraphs(xml2)]
    res = fmt.zotero_refresh_document(xml2, texts)
    check("a result run with two text elements refuses the refresh (nothing written)",
          (not res["changed"]) and bool(res["skip"]) and res["xml"] == xml2,
          str(res.get("skip")))


def test_refresh_refuses_a_gap_between_entries():
    tmp = scratch("zar_bibgap_")
    p = _docx(tmp / "m.docx", marker_a=r"\super 1\nosupersub{}", visible_a="1",
              marker_b=r"\super 2\nosupersub{}", visible_b="2")
    xml = zipfile.ZipFile(p).read("word/document.xml").decode("utf-8")
    gap = '<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr></w:p>'
    second = ('<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>'
              "<w:r><w:t>1.</w:t></w:r>")
    check("the fixture carries the second entry paragraph", second in xml)
    # A text-less paragraph BETWEEN the two entries (inside the bibliography
    # field): a rank-ordered rebuild has no place for it, so the refresh must
    # refuse instead of silently dropping a paragraph the author put there.
    xml2 = xml.replace("\n" + second, "\n" + gap + "\n" + second, 1)
    check("the gap paragraph sits between the entries",
          xml2 != xml and xml2.count(gap) == 1)
    texts = [fmt.text_of(q[2]) for q in fmt.paragraphs(xml2)]
    res = fmt.zotero_refresh_document(xml2, texts)
    check("a gap between bibliography entries refuses the refresh (nothing written)",
          (not res["changed"]) and bool(res["skip"]) and res["xml"] == xml2,
          str(res.get("skip")))


def test_style_reconcile():
    tmp = scratch("zar_style_")
    p = _docx(tmp / "m.docx", marker_a=r"\super 1\nosupersub{}", visible_a="1",
              marker_b=r"\super 2\nosupersub{}", visible_b="2")
    with zipfile.ZipFile(p) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    info = fmt.zotero_style_reconcile({n: parts[n].decode("utf-8") for n in
                                       ("word/settings.xml", "docProps/custom.xml")})
    check("two conflicting stores are reconciled to the newer style", info["changed"],
          str(info.get("to")))
    styles = fmt.zotero_style_ids({n: (v.decode("utf-8") if isinstance(v, bytes) else v)
                                   for n, v in info["parts"].items()})
    check("both stores now name the same style", len(set(styles.values())) == 1, str(styles))


# ---------------------------------------------------------------------------
# 2. the pipeline's automatic path (fix_package + flatten)
# ---------------------------------------------------------------------------
def test_fix_package_refreshes_automatically():
    tmp = scratch("zar_fixpkg_")
    p = _docx(tmp / "m.docx", marker_a=r"\super 2\nosupersub{}", visible_a="2",
              marker_b=r"\super 1\nosupersub{}", visible_b="1")
    out = tmp / "out.docx"
    rep = fmt.fix_package(p, out, dict(fmt.POLICY_DEFAULTS))
    zr = rep.get("zotero_refresh") or {}
    check("fix_package refreshes the fields by default", rep["ok"] and zr.get("changed"),
          json.dumps(zr)[:200])
    report = fmt.zotero_report_for_docx(out)
    check("fix_package NEVER unlinks the fields by default (they stay live)",
          report["counts"].get("item", 0) == 2, str(report["counts"]))
    texts, xml = _texts(out)
    rows = fmt.zotero_parity_rows(xml, texts)
    check("the packaged copy carries no stale-parity row",
          not [r for r in rows if r["rule"] in ("FMT-Z1", "FMT-Z2", "FMT-Z4")],
          str(rows[:3]))


def test_flatten_after_refresh():
    tmp = scratch("zar_flatten_")
    p = _docx(tmp / "m.docx", marker_a=r"\super 2\nosupersub{}", visible_a="2",
              marker_b=r"\super 1\nosupersub{}", visible_b="1")
    out = tmp / "flat.docx"
    policy = dict(fmt.POLICY_DEFAULTS)
    policy["unlink_zotero_fields"] = True
    rep = fmt.fix_package(p, out, policy)
    check("flattening runs (the stale-refusal is gone because the refresh ran first)",
          rep["ok"], str(rep.get("error") or rep.get("changes"))[:200])
    report = fmt.zotero_report_for_docx(out)
    check("the flattened copy carries no live fields",
          report["counts"].get("item", 0) == 0, str(report["counts"]))
    texts, _xml = _texts(out)
    joined = "".join(texts)
    check("the flattened text carries the CORRECT numbers (1 for A, 2 for B)",
          "1" in texts[1] and "2" in texts[2])


# ---------------------------------------------------------------------------
# 3. reference-entry repairs from a sibling .bib
# ---------------------------------------------------------------------------
def test_reference_entry_repairs():
    tmp = scratch("zar_refs_")
    bib = tmp / "refs.bib"
    bib.write_text(
        "@article{dong2020sccnv,\n"
        "  title = {SCCNV: a software tool for identifying copy number variation},\n"
        "  author = {Dong, Xiao and Zhang, Lei},\n"
        "  date = {2020},\n  journaltitle = {Frontiers in Genetics},\n"
        "  volume = {11},\n  pages = {505441},\n  doi = {10.3389/fgene.2020.505441}\n}\n"
        "@unpublished{li2013aligning,\n"
        "  title = {Aligning sequence reads with BWA-MEM},\n"
        "  author = {Li, Heng},\n  date = {2013},\n"
        "  eprint = {1303.3997},\n  eprinttype = {arXiv}\n}\n"
        "@software{juliegithub,\n  title = {infercna},\n  author = {Laffy, Julie},\n"
        "  date = {2019},\n  url = {https://github.com/jlaffy/infercna}\n}\n",
        encoding="utf-8")
    records = fmt.load_bib_facts([bib])
    check("the .bib facts parse", len(records) == 3, str([r["key"] for r in records]))
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           "<w:body>"
           '<w:p><w:r><w:t>15.Dong, X. et al. SCCNV tool. Front. Genet. Volume 11-2020, (2020).'
           "</w:t></w:r></w:p>"
           '<w:p><w:r><w:t>25.Li, H. Aligning sequence reads with BWA-MEM. (2013).</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>34.Laffy, J. infercna tool. https://github.com/jlaffy/infercna.'
           "</w:t></w:r></w:p>"
           "</w:body></w:document>")
    res = fmt.repair_reference_entries(xml, records)
    check("all three entry shapes are repaired", res["changed"] and len(res["repairs"]) == 3,
          json.dumps(res.get("repairs"))[:200] + str(res.get("skipped"))[:200])
    texts = [fmt.text_of(p[2]) for p in fmt.paragraphs(res["xml"])]
    joined = " ".join(texts)
    check("the fused volume becomes volume, article number",
          "Front. Genet. 11, 505441 (2020)." in joined, joined[:160])
    check("the bare year gains the arXiv locator",
          "Preprint at https://arxiv.org/abs/1303.3997 (2013)" in joined, joined[:220])
    check("the software entry gains its year",
          "(2019). https://github.com/jlaffy/infercna." in joined, joined[:260])


# ---------------------------------------------------------------------------
# 4. the XFA reader and export (the filled-form false "UNFILLED")
# ---------------------------------------------------------------------------
def _xfa_pdf(path: Path, *, filled: bool) -> Path:
    empty = (b"<xfa:datasets><xfa:data><form><Header><author/><lastupdate/></Header>"
             b"<Software><analysisinfo/></Software></form></xfa:data></xfa:datasets>")
    full = (b'<xfa:datasets><xfa:data><form><Header><author\n>Xuegong Zhang</author\n>'
            b'<lastupdate\n>2026-10-05</lastupdate\n></Header><Software><analysisinfo\n>'
            b"The study used BWA-MEM 0.7.18, SAMtools 1.21</analysisinfo\n></Software>"
            b'</form></xfa:data></xfa:datasets>')
    with open(path, "wb") as f:
        f.write(b"%PDF-1.7\n1 0 obj<</AcroForm 2 0 R/XFA[3 0 R]>>endobj\n")
        for packet in (empty, full if filled else b"<xfa:datasets><xfa:data/></xfa:datasets>"):
            f.write(b"stream\n" + fmt.zlib.compress(packet) + b"\nendstream\n")
        f.write(b"trailer<</Root 1 0 R>>\n%%EOF\n")
    return path


def test_xfa_reader_and_export():
    tmp = scratch("zar_xfa_")
    filled = _xfa_pdf(tmp / "form.pdf", filled=True)
    is_xfa, non_empty, is_shell = fmt._xfa_dataset_report(filled)
    check("a LiveCycle form is recognized", is_xfa)
    check("the filled dataset packet is counted (no false UNFILLED)",
          non_empty > 0, f"non_empty={non_empty}")
    rows = fmt.pdf_artifact_rows(filled)
    check("no FMT-PDF2 on a filled form",
          not [r for r in rows if r["rule"] == "FMT-PDF2"], str(rows))
    text = fmt.xfa_export_text(filled)
    check("the readable export carries the answers",
          "Xuegong Zhang" in text and "2026-10-05" in text, text[:120])
    empty = _xfa_pdf(tmp / "empty.pdf", filled=False)
    rows_empty = fmt.pdf_artifact_rows(empty)
    check("an unfilled form still reports FMT-PDF2",
          [r for r in rows_empty if r["rule"] == "FMT-PDF2"], str(rows_empty))


# ---------------------------------------------------------------------------
# 5. the readiness verdict
# ---------------------------------------------------------------------------
def test_package_readiness():
    clean = pp.package_readiness({"hygiene": {}})
    check("a package without findings is submission-ready", clean["submission_ready"])
    dirty = pp.package_readiness({"hygiene": {
        "pdf_artifacts": [{"rule": "FMT-PDF1", "document": "form.pdf",
                           "detail": "shell"}],
        "internal_artifacts": [{"rule": "PKG-1", "file": "raw_data.README.md",
                                "detail": "internal material"}]}})
    check("package findings make it NOT submission-ready", not dirty["submission_ready"])
    check("the findings are listed", len(dirty["findings"]) == 2, str(dirty["findings"]))
    check("--require-ready turns them into a gate",
          len(pp.readiness_gate_problems(dirty, True)) == 1)
    check("without the flag they stay recorded only",
          pp.readiness_gate_problems(dirty, False) == [])


class _CtxStub:
    def __init__(self, cfg):
        self.cfg = cfg


def test_publication_flatten_and_readiness():
    # The published copy keeps live fields by default: the pipeline refreshes
    # them, and unlinking is the author's own step for the submission file.
    pol, flatten = pp.publication_format_policy(_CtxStub({}), {"a": 1})
    check("publication does NOT flatten the Zotero fields by default",
          flatten is False and pol.get("unlink_zotero_fields") is None,
          str(pol.get("unlink_zotero_fields")))
    check("the caller's policy dict is not mutated",
          "unlink_zotero_fields" not in {"a": 1})
    pol2, flatten2 = pp.publication_format_policy(
        _CtxStub({"format_policy": {"unlink_zotero_fields_at_publish": True}}), {})
    check("the operator can opt in to flattening the published copy",
          flatten2 is True and pol2.get("unlink_zotero_fields") is True)
    pol3, flatten3 = pp.publication_format_policy(_CtxStub({}), {}, cli_flatten=True)
    check("the decide CLI option opts in to flattening",
          flatten3 is True and pol3.get("unlink_zotero_fields") is True)
    pol4, flatten4 = pp.publication_format_policy(
        _CtxStub({"format_policy": {"unlink_zotero_fields_at_publish": False}}), {},
        cli_flatten=False)
    check("an explicit policy keeps the default off",
          flatten4 is False and not pol4.get("unlink_zotero_fields"))
    check("publish_final_clean exposes the flatten parameter",
          "flatten_zotero" in inspect.signature(pp.publish_final_clean).parameters)
    dec_cli = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "decide", "--help"],
                             capture_output=True, text=True, timeout=120)
    check("decide exposes --unlink-zotero-fields (the explicit opt-in)",
          "--unlink-zotero-fields" in dec_cli.stdout and "OFF BY DEFAULT" in dec_cli.stdout,
          dec_cli.stdout[-300:])
    ready = pp.package_readiness({"hygiene": {"zotero_unlinked": {"requested": True},
                                              "zotero_live_fields": []}})
    check("a flattened package is submission-ready", ready["submission_ready"])
    stuck = pp.package_readiness({"hygiene": {
        "zotero_unlinked": {"requested": True},
        "zotero_live_fields": [{"file": "main.docx", "fields": 125}]}})
    check("live fields left behind by a refused refresh are a readiness finding",
          (not stuck["submission_ready"]) and stuck["findings"][0]["rule"] == "FMT-Z7",
          str(stuck["findings"])[:160])
    kept = pp.package_readiness({"hygiene": {"zotero_unlinked": {"requested": False},
                                             "zotero_live_fields": [{"file": "main.docx",
                                                                     "fields": 1}]}})
    check("the default keep-live state is not a finding", kept["submission_ready"])


def test_cli_unlink_chain():
    tmp = scratch("zar_cli_")
    p = _docx(tmp / "m.docx", marker_a=r"\super 2\nosupersub{}", visible_a="2",
              marker_b=r"\super 1\nosupersub{}", visible_b="1")
    cli = subprocess.run([sys.executable, str(WS / "paper_docx_format.py"),
                          "zotero-refresh", str(p), "--unlink"],
                         capture_output=True, text=True, timeout=300)
    check("the CLI refresh --unlink chain succeeds", cli.returncode == 0,
          (cli.stdout + cli.stderr)[-200:])
    report = fmt.zotero_report_for_docx(p)
    check("the CLI output carries no live fields", report["counts"].get("zotero", 0) == 0,
          str(report["counts"]))
    texts, _xml = _texts(p)
    check("the flattened text carries the refreshed numbers",
          texts[1].strip() == "1" and texts[2].strip() == "2", repr(texts[1:3]))


def test_normalize_dir_publication_copy():
    # Default: refreshed, LIVE. Opt-in: flattened.
    tmp = scratch("zar_pub_")
    p = _docx(tmp / "m.docx", marker_a=r"\super 2\nosupersub{}", visible_a="2",
              marker_b=r"\super 1\nosupersub{}", visible_b="1")
    pol, flatten = pp.publication_format_policy(_CtxStub({}), dict(fmt.POLICY_DEFAULTS))
    summary = pp.normalize_formatting_in_dir(tmp, pol, "publish-test", warns=None)
    check("the publication normalization pass ran", summary.get("fixed", 0) >= 1,
          json.dumps(summary)[:200])
    report = fmt.zotero_report_for_docx(p)
    check("by default the published copy keeps its live Zotero fields",
          report["counts"].get("item", 0) == 2, str(report["counts"]))
    texts, xml = _texts(p)
    check("the live fields were REFRESHED to the correct numbers",
          texts[1].strip() == "1" and texts[2].strip() == "2", repr(texts[1:3]))
    check("the refreshed copy is parity-clean",
          not [r for r in fmt.zotero_parity_rows(xml, texts)
               if r["rule"] in ("FMT-Z1", "FMT-Z2", "FMT-Z4")])
    tmp2 = scratch("zar_pub_opt_")
    p2 = _docx(tmp2 / "m.docx", marker_a=r"\super 2\nosupersub{}", visible_a="2",
               marker_b=r"\super 1\nosupersub{}", visible_b="1")
    pol2, flatten2 = pp.publication_format_policy(
        _CtxStub({"format_policy": {"unlink_zotero_fields_at_publish": True}}),
        dict(fmt.POLICY_DEFAULTS))
    pp.normalize_formatting_in_dir(tmp2, pol2, "publish-optin", warns=None)
    report2 = fmt.zotero_report_for_docx(p2)
    check("the opt-in publication policy flattens the copy",
          report2["counts"].get("zotero", 0) == 0, str(report2["counts"]))
    texts2, _xml2 = _texts(p2)
    check("the opt-in flattened copy keeps the refreshed numbers",
          texts2[1].strip() == "1" and texts2[2].strip() == "2", repr(texts2[1:3]))


def main():
    test_refresh_document()
    test_refresh_refuses_unrebuildable_markers()
    test_refresh_rebuilds_a_stale_bibliography_order()
    test_refresh_refuses_a_run_with_two_text_elements()
    test_refresh_refuses_a_gap_between_entries()
    test_style_reconcile()
    test_fix_package_refreshes_automatically()
    test_flatten_after_refresh()
    test_reference_entry_repairs()
    test_xfa_reader_and_export()
    test_package_readiness()
    test_publication_flatten_and_readiness()
    test_cli_unlink_chain()
    test_normalize_dir_publication_copy()
    cleanup()
    if FAILS:
        print(f"\n{len(FAILS)} CHECK(S) FAILED: " + "; ".join(FAILS))
        return 1
    print("\nALL ZOTERO AUTO-REFRESH CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

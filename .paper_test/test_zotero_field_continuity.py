#!/usr/bin/env python3
"""Live Zotero fields are carried from one DOCX version into the next.

The real failure this suite pins: the setup FORMAT-FIX's "stray empty
paragraph" rule treated the no-text paragraph that holds a Zotero
bibliography's closing `w:fldChar w:fldCharType="end"` (it sits directly
before the next heading) as an empty paragraph and deleted it, leaving the
`ADDIN ZOTERO_BIBL` field unterminated; separately, a rewrite arm rebuilt its
paragraphs from their `w:t` text and dropped every one of the 124 live
citation fields, keeping only their visible numbers as plain text.

Asserts:
  * `paper_docx_format.fix_package` keeps the bibliography terminator (and
    every field signature) and refuses to come back `ok` when a mechanical fix
    would add, remove or unbalance a field;
  * `zotero_field_report` finds unclosed fields, stray field chars, bad
    citation JSON and duplicate citationIDs;
  * `zotero_field_continuity_problems` allows add/edit/delete-with-text but
    fails total loss, new malformation and field->plain-text replacement;
  * the pipeline stage gate (`_format_fix_stage_package`), the template
    postcheck and the code-side template rebuild all run it against their
    base/self input;
  * every prompt (review, rewrite, revise, integrate, judge, conform) states
    the continuity contract and the repair route for plain-text citations.

Run:  python3 .paper_test/test_zotero_field_continuity.py
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


NB = _load("paper_pipeline", WS / "paper_pipeline.py")
FMT = _load("paper_docx_format", WS / "paper_docx_format.py")

FAILS = []
TMPDIRS = []
NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"[1:-1]


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


# ---- fixtures ---------------------------------------------------------------

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{NS}">
  <w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="480" w:after="360"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Bibliography"><w:name w:val="Bibliography"/></w:style>
</w:styles>"""


def make_docx(path: Path, document_xml: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", document_xml)
        z.writestr("word/styles.xml", STYLES)
    return path


def para(inner: str, style: str = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{inner}</w:p>"


def run(text: str) -> str:
    return f"<w:r><w:t>{xml_escape(text)}</w:t></w:r>"


def fld(kind: str) -> str:
    return f'<w:r><w:fldChar w:fldCharType="{kind}"/></w:r>'


def item_field(cid: str = "CIT0001", visible: str = "19", key: str = "ITEM0001",
               bad_json: bool = False) -> str:
    data = {"citationID": cid, "properties": {"noteIndex": 0},
            "citationItems": [{"id": key,
                               "uris": [f"http://zotero.org/users/local/TESTLOCAL/items/{key}"]}],
            "schema": ("https://github.com/citation-style-language/schema/raw/master/"
                       "csl-citation.json")}
    instr = " ADDIN ZOTERO_ITEM CSL_CITATION " + ("{not valid json" if bad_json
                                                  else json.dumps(data))
    return (fld("begin")
            + f'<w:r><w:instrText xml:space="preserve">{xml_escape(instr)}</w:instrText></w:r>'
            + fld("separate") + f"<w:r><w:t>{xml_escape(visible)}</w:t></w:r>" + fld("end"))


def bibl_open() -> str:
    instr = ' ADDIN ZOTERO_BIBL {"uncited":[],"omitted":[],"custom":[]} CSL_BIBLIOGRAPHY '
    return (fld("begin")
            + f'<w:r><w:instrText xml:space="preserve">{xml_escape(instr)}</w:instrText></w:r>'
            + fld("separate"))


def broken_item(cid: str = "CIT0001", visible: str = "19", key: str = "ITEM0001") -> str:
    """An item field whose closing fldChar end is missing (a malformed field)."""
    return item_field(cid, visible, key).rsplit(fld("end"), 1)[0]


def document(parts: list) -> str:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{NS}"><w:body>' + "".join(parts)
            + "</w:body></w:document>")


REF1 = "1. Chen, C. Single-cell analyses. Science 356 (2017)."
REF2 = "2. Doe, J. Another reference. Nature 1 (2020)."


def live_doc(bibl_end: bool = True) -> str:
    """The real shape: the BIBL terminator is the no-text paragraph before a heading."""
    parts = [
        para(run("CopyNumBench")),
        para(run("The first result cites ") + item_field() + run(" and continues.")),
        para(run("References"), style="Heading1"),
        para(bibl_open() + run(REF1), style="Bibliography"),
        para(run(REF2), style="Bibliography"),
    ]
    if bibl_end:
        parts.append(para(fld("end")))
    parts += [para(run("Figure legends"), style="Heading1"), para(run("Fig. 1 | A legend."))]
    return document(parts)


def plain_doc() -> str:
    """A text round-trip: the visible citation/bibliography text survives, the fields do not."""
    return document([para(run("CopyNumBench")),
                     para(run("The first result cites 19 and continues.")),
                     para(run("References"), style="Heading1"),
                     para(run(REF1), style="Bibliography"),
                     para(run(REF2), style="Bibliography"),
                     para(run("Figure legends"), style="Heading1"),
                     para(run("Fig. 1 | A legend."))])


# =====================================================================
# ZC1 - the formatter may not delete a field's terminator paragraph
# =====================================================================

def test_fixer_preserves_field_terminator():
    print()
    print("== ZC1: FORMAT-FIX carries every live field over unchanged ==")
    tmp = scratch("paper_zc_fix_")
    src = make_docx(tmp / "live.docx", live_doc())
    out = tmp / "fixed.docx"
    rep = FMT.fix_package(src, out, dict(FMT.POLICY_DEFAULTS))
    verified = rep.get("verified") or {}
    check("ZC1 the fixer accepts the field-preserving repair",
          rep.get("ok") is True,
          str(rep.get("error") or verified.get("zotero_field_problems")))
    check("ZC1 the fixer kept the field signature",
          verified.get("zotero_field_signature_kept") is True)
    after = FMT.zotero_report_for_docx(out)
    check("ZC1 the bibliography field is still complete",
          after["counts"]["bibliography"] == 1 and after["counts"]["incomplete"] == 0,
          str(after["counts"]) + " " + str(after["errors"]))
    check("ZC1 the citation field is still live",
          after["counts"]["item"] == 1)
    check("ZC1 no field-integrity error survives",
          not after["errors"], str(after["errors"]))
    groups, _ignored = FMT.stray_empty_paragraph_groups(
        FMT.paragraphs(live_doc()), {"max_empty_paragraph_run": 1, "empty_paragraph_slots": []})
    drop = sorted({i for indices, _kind in groups for i in indices})
    check("ZC1 the fldChar-only paragraph is not 'empty' for the stray rule",
          drop == [], f"drop set {drop}")


# =====================================================================
# ZC2 - the field inventory reports malformed structure
# =====================================================================

def test_report_detects_malformed():
    print()
    print("== ZC2: the inventory finds malformed fields ==")
    clean = FMT.zotero_field_report(live_doc())
    check("ZC2 a clean document has no field error",
          not clean["errors"] and clean["counts"]["incomplete"] == 0,
          str(clean["errors"]))
    unclosed = FMT.zotero_field_report(live_doc(bibl_end=False))
    check("ZC2 an unclosed bibliography begin is reported",
          "unclosed-field" in (unclosed["error_codes"] or {}),
          str(unclosed["error_codes"]))
    stray = FMT.zotero_field_report(document([para(run("Text")), para(fld("end"))]))
    check("ZC2 a stray field end is reported",
          "end-outside-field" in (stray["error_codes"] or {}),
          str(stray["error_codes"]))
    bad = FMT.zotero_field_report(document([para(run("Cites ") + item_field(bad_json=True))]))
    check("ZC2 unparseable citation JSON is reported",
          "bad-citation-json" in (bad["error_codes"] or {}),
          str(bad["error_codes"]))
    dup = FMT.zotero_field_report(
        document([para(run("A ") + item_field(cid="SAMEID")),
                  para(run("B ") + item_field(cid="SAMEID"))]))
    check("ZC2 a duplicate citationID is reported",
          "duplicate-citation-id" in (dup["error_codes"] or {}),
          str(dup["error_codes"]))


# =====================================================================
# ZC3 - continuity: add/edit/delete-with-text allowed, the rest fails
# =====================================================================

def _cont(base_xml: str, out_xml: str) -> dict:
    return FMT.zotero_field_continuity_problems(FMT.zotero_field_report(base_xml),
                                                FMT.zotero_field_report(out_xml))


def test_continuity_rules():
    print()
    print("== ZC3: the continuity gate ==")
    same = _cont(live_doc(), live_doc())
    check("ZC3 an unchanged field set passes",
          not same["errors"] and not same["deleted"], str(same["errors"]))
    edited_doc = live_doc().replace(item_field(), item_field(visible="19,20"))
    edited = _cont(live_doc(), edited_doc)
    check("ZC3 editing a field's result is allowed and recorded",
          not edited["errors"] and edited["edited"], f"{edited['errors']} {edited['edited']}")
    added_doc = document([para(run("CopyNumBench")),
                          para(run("The first result cites ") + item_field() + run(" and ") +
                               item_field(cid="CIT0002", visible="20", key="ITEM0002")),
                          para(run("References"), style="Heading1"),
                          para(bibl_open() + run(REF1), style="Bibliography"),
                          para(fld("end")), para(run("Figure legends"), style="Heading1")])
    added = _cont(live_doc(), added_doc)
    check("ZC3 adding a field is allowed",
          not added["errors"] and added["added"] == ["CIT0002"], f"{added['errors']}")
    # Delete one citation AND its visible text: allowed (recorded as deleted).
    removed_text = document([para(run("CopyNumBench")),
                             para(run("The first result continues without a citation.")),
                             para(run("References"), style="Heading1"),
                             para(bibl_open() + run(REF1), style="Bibliography"),
                             para(run(REF2), style="Bibliography"), para(fld("end")),
                             para(run("Figure legends"), style="Heading1")])
    deleted = _cont(live_doc(), removed_text)
    check("ZC3 deleting a citation with its visible text is allowed",
          not deleted["errors"] and deleted["deleted"] == ["CIT0001"], str(deleted["errors"]))
    # The same deletion that leaves the number behind is a plain-text replacement.
    plain = _cont(live_doc(), plain_doc())
    check("ZC3 field -> plain text is an error",
          plain["errors"] and plain["plain_text"], str(plain["plain_text"][:1]))
    check("ZC3 the plain-text error names the repair route",
          any("re-create the live field" in e for e in plain["errors"]),
          "; ".join(plain["errors"])[:200])
    total_loss = _cont(live_doc(), document([para(run("CopyNumBench")),
                                             para(run("Nothing cited here."))]))
    check("ZC3 deleting ALL fields is an error",
          any("ALL" in e and "Zotero field" in e for e in total_loss["errors"]),
          str(total_loss["errors"][:1]))
    malformed = _cont(live_doc(), live_doc(bibl_end=False))
    check("ZC3 a NEW malformation is an error",
          any("unclosed-field" in e for e in malformed["errors"]), str(malformed["errors"][:1]))
    # Fixing one malformed field while breaking ANOTHER of the same kind is still
    # a new error (a per-code count comparison would have missed it).
    fixed_one = _cont(
        document([para(run("A cites ") + broken_item("CIT0001", "19", "ITEM0001"))]),
        document([para(run("A cites ") + item_field("CIT0001", "19", "ITEM0001")),
                  para(run("B cites ") + broken_item("CIT0002", "20", "ITEM0002"))]))
    check("ZC3 fixing one field while breaking another is a new error",
          any("unclosed-field" in e for e in fixed_one["errors"]),
          str(fixed_one["errors"][:1]))
    inherited = _cont(live_doc(bibl_end=False), live_doc(bibl_end=False))
    check("ZC3 an inherited malformation is a warning, not a new error",
          not inherited["errors"] and inherited["warnings"], f"{inherited['errors']} "
          f"{inherited['warnings']}")


# =====================================================================
# ZC4 - the pipeline gate, the stage hook and the conform hooks
# =====================================================================

def test_pipeline_gate():
    print()
    print("== ZC4: the pipeline stage gate ==")
    tmp = scratch("paper_zc_gate_")
    base = tmp / "base"
    out = tmp / "out"
    make_docx(base / "cnb-mainText-181c700.docx", live_doc())
    make_docx(out / "cnb-mainText-4f3a9c1.docx", plain_doc())
    errs, warns = [], []
    rep = NB.zotero_field_continuity_check(base, out, "r1_w2", errs, warns)
    check("ZC4 the gate pairs documents by version-token-free name",
          rep["checked"] == 1, str(rep))
    check("ZC4 the gate fails the text round-trip",
          rep["errors"] > 0 and errs and errs[0].startswith("ZOTERO FIELD CONTINUITY:"),
          str(errs[:1]))
    good = tmp / "good"
    make_docx(good / "cnb-mainText-4f3a9c1.docx", live_doc())
    errs2, warns2 = [], []
    rep2 = NB.zotero_field_continuity_check(base, good, "r1_w1", errs2, warns2)
    check("ZC4 the gate passes a field-preserving version",
          rep2["checked"] == 1 and not errs2 and not rep2["errors"], str(errs2))
    check("ZC4 the rewrite/revise/integrate postcheck runs the gate",
          "zotero_field_continuity_check(" in inspect.getsource(NB._format_fix_stage_package),
          "the stage postcheck must enforce it")
    check("ZC4 the template-first postcheck runs the gate",
          "zotero_field_continuity_problems(" in inspect.getsource(NB.template_rewrite_postcheck))
    check("ZC4 the code-side template rebuild runs the gate",
          "zotero_field_continuity_problems(" in inspect.getsource(
              NB.rebuild_package_from_templates))
    check("ZC4 the formatter keeps its own field fence",
          "zotero_field_signature(" in inspect.getsource(FMT.fix_package))


# =====================================================================
# ZC5 - every prompt states the contract
# =====================================================================

def test_prompt_contract():
    print()
    print("== ZC5: prompts carry the continuity contract ==")
    sb = Path("/tmp/paper_zc_prompt")
    prompts = {
        "review": NB.review_prompt(sb, "r1_review", 1),
        "rewrite": NB.rewrite_prompt(sb, "r1_w1", 1),
        "revise": NB.revise_prompt(sb, "r1_a2_revise", 1),
        "integrate": NB.integrate_prompt(sb, "r1_i1", 1, "a1", ["w1"]),
        "judge": NB.judge_prompt(sb, "r1_judge_t1_j1", 1, "t1", 1, 3, ["v1"]),
        "zotero-off": NB.rewrite_prompt(sb, "r1_w1", 1, zotero="off"),
    }
    for name, text in prompts.items():
        unresolved = sorted(set(re.findall(r"@@[A-Z0-9_]+@@", text)))
        check(f"ZC5 {name} has no unresolved @@TOKEN@@", not unresolved, str(unresolved))
        check(f"ZC5 {name} states the field-continuity contract",
              "FIELD CONTINUITY (code-enforced)" in text
              and "--preserve-baseline-citations" in text
              and "RE-CREATE the field" in text)
    check("ZC5 rewrite tells the agent a text rebuild destroys fields",
          "destroys every fldChar/instrText run" in prompts["rewrite"])
    check("ZC5 review files a field-less citation as a defect",
          "field-continuity/preservation defect" in prompts["review"])
    check("ZC5 judge scores lost fields as a preservation defect",
          "IS a preservation defect" in prompts["judge"])
    check("ZC5 the template-first conform prompt carries the rule",
          "CARRY EVERY LIVE ZOTERO FIELD OVER" in inspect.getsource(NB.apply_template_prompt))
    check("ZC5 the guideline conform prompt carries the rule",
          "CARRY EVERY LIVE ZOTERO FIELD OVER" in inspect.getsource(
              NB.apply_guideline_conform_prompt))


def main() -> int:
    sections = (("fixer", test_fixer_preserves_field_terminator),
                ("inventory", test_report_detects_malformed),
                ("continuity", test_continuity_rules),
                ("gate", test_pipeline_gate),
                ("prompts", test_prompt_contract))
    try:
        for name, fn in sections:
            try:
                fn()
            except Exception as e:                                  # noqa: BLE001
                check(f"{name} section completed", False, f"{type(e).__name__}: {e}")
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL ZOTERO FIELD-CONTINUITY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

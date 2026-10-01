#!/usr/bin/env python3
"""Regression checks for the confirmed findings of the 2026-10-02 general audit.

Run:  python3 .paper_test/test_general_audit_2026_1002.py

Every check below reproduces a defect that was confirmed against the tree (not
merely reported by the audit), and fails on the pre-fix tree. The audit's source
documents are read-only inputs under `audit_data/2026-1002-0138-general-audit/`.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
TMPDIRS = []
FAILS = []

P = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fmt = load("paper_docx_format_audit", WS / "paper_docx_format.py")
nb = load("paper_pipeline_audit", WS / "paper_pipeline.py")


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


CONTENT_TYPES = """<?xml version="1.0"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
RELS = """<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
STYLES = (f'<?xml version="1.0"?><w:styles xmlns:w="{P[1:-1]}">'
          '<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
          '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>'
          '<w:rPr><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr></w:style>'
          '</w:styles>')


def make_package(path: Path, document_xml: str) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", document_xml)
        z.writestr("word/styles.xml", STYLES)
    return path


def document(body: str) -> str:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<w:document xmlns:w="{P[1:-1]}" xmlns:r="{RNS}"><w:body>{body}</w:body>'
            f'</w:document>')


# ---------------------------------------------------------------------------
# paper_docx_format.py
# ---------------------------------------------------------------------------

def test_self_closing_paragraph():
    print("\n== FMT-S1 repair keeps a self-closing empty paragraph well formed ==")
    tmp = scratch("audit_fmt_selfclose_")
    doc = document(
        '<w:p><w:r><w:t>Title page.</w:t></w:r></w:p>'
        '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
        '<w:p w:rsidR="00AB12CD"/>'
        '<w:p><w:r><w:t>Body text.</w:t></w:r></w:p>'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>')
    src, out = make_package(tmp / "in.docx", doc), tmp / "out.docx"
    rep = fmt.fix_package(src, out, fmt.load_policy(None))
    fixed = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")
    check("the moved break stays INSIDE the following self-closing paragraph",
          '<w:p w:rsidR="00AB12CD"><w:pPr><w:pageBreakBefore/></w:pPr></w:p>' in fixed,
          fixed[fixed.find("rsidR"):][:80])
    check("the fixed package is schema-valid (or the CLI is unavailable)",
          rep["verified"]["schema_ok"] in (True, None),
          f"{rep['verified']['schema_ok']} {rep['verified']['schema_detail']}")
    check("the fixer's self-verification accepts the valid repair", rep["ok"] is True,
          str(rep["verified"]))
    bare = fmt.insert_into_ppr("<w:p/>", "<w:keepNext/>")
    check("a bare self-closing <w:p/> is expanded too",
          bare == "<w:p><w:pPr><w:keepNext/></w:pPr></w:p>", bare)


def test_text_edit_identity():
    print("\n== text-identity proof survives a deleted paragraph and quote normalisation ==")
    tmp = scratch("audit_fmt_textedit_")
    doc = document(
        '<w:p><w:r><w:t>Front matter.</w:t></w:r></w:p>'
        '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
        '<w:p><w:r><w:t>The tumour response was measured.</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>We used tumor measurements.</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Another tumor measurement.</w:t></w:r></w:p>')
    src, out = make_package(tmp / "in.docx", doc), tmp / "out.docx"
    rep = fmt.fix_package(src, out, fmt.load_policy(None))
    check("a spelling edit AFTER a deleted break-only paragraph is verified",
          rep["ok"] is True and rep["verified"]["text_diff_only_recorded_edits"]
          and rep["verified"]["text_edits"] >= 1, str(rep["verified"]))
    tmp2 = scratch("audit_fmt_quote_")
    doc2 = document(
        '<w:p><w:r><w:t>We used tumor measurements.</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Another tumor measurement.</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>A third tumor measurement.</w:t></w:r></w:p>'
        '<w:p><w:r><w:t xml:space="preserve">The "tumour" wording appears once.</w:t></w:r></w:p>')
    src2, out2 = make_package(tmp2 / "in.docx", doc2), tmp2 / "out.docx"
    policy = fmt.load_policy(None)
    policy["quote_style"] = "curly"
    rep2 = fmt.fix_package(src2, out2, policy)
    check("a quote_style change plus a text edit is verified",
          rep2["ok"] is True and rep2["verified"]["text_diff_only_recorded_edits"],
          str(rep2["verified"]))


def test_title_page_section():
    print("\n== FMT-S3 targets the section that governs page 1 ==")
    section = ('<w:sectPr><w:headerReference w:type="default" r:id="rId6"/>'
               '<w:pgSz w:w="11906" w:h="16838"/></w:sectPr>')
    doc = document('<w:p><w:r><w:t>Title page.</w:t></w:r></w:p>' + section
                   + '<w:p><w:r><w:t>Body.</w:t></w:r></w:p>' + section)
    rows = fmt.analyse_document(doc, {}, fmt.load_policy(None), "x.docx")["rows"]
    check("the scan reports FMT-S3 for a two-section manuscript",
          any(r["rule"] == "FMT-S3" for r in rows), str([r["rule"] for r in rows]))
    fixed, changes, _meta = fmt.fix_document(doc, {}, fmt.load_policy(None))
    first = fixed[:fixed.find("</w:sectPr>")]
    check("the fix adds w:titlePg to the FIRST section, not the last",
          "<w:titlePg" in first and fixed.count("<w:titlePg") == 1, str(changes))
    after = fmt.analyse_document(fixed, {}, fmt.load_policy(None), "x.docx")["rows"]
    check("the fixed manuscript re-scans clean for FMT-S3",
          not any(r["rule"] == "FMT-S3" for r in after))
    late = document('<w:p><w:r><w:t>Title page.</w:t></w:r></w:p>' + section
                    + '<w:p><w:r><w:t>Body.</w:t></w:r></w:p>'
                    + section.replace("</w:sectPr>", "<w:titlePg/></w:sectPr>"))
    late_rows = fmt.analyse_document(late, {}, fmt.load_policy(None), "x.docx")["rows"]
    check("a titlePg in a LATER section does not silence the first section's finding",
          any(r["rule"] == "FMT-S3" for r in late_rows),
          str([r["rule"] for r in late_rows]))


def test_keep_list_and_ledgers():
    print("\n== empty-run keep list, term boundary and number attribution ==")
    para = ('<w:p><w:r><w:t>tumour</w:t></w:r><w:r><w:cr/></w:r>'
            '<w:r><w:commentReference w:id="3"/></w:r><w:r><w:t>text</w:t></w:r></w:p>')
    new_para, _applied = fmt.rewrite_text_spans(para, [(0, 6, "tumor")])
    check("an edited paragraph keeps its w:cr and comment-anchor runs",
          "<w:cr/>" in new_para and "<w:commentReference" in new_para, new_para[:160])
    cnv_rows = fmt.key_term_rows(["The CNV calls were compared."])
    check("a CNV mention does not open a bogus 'CN' ledger row",
          "CN" not in [r["term"] for r in cnv_rows] and "CNV" in [r["term"] for r in cnv_rows],
          str([r["term"] for r in cnv_rows]))
    cn_rows = fmt.key_term_rows(["The CN state was called."])
    check("a standalone CN is still counted", "CN" in [r["term"] for r in cn_rows])
    led = fmt.number_ledger(["Run one used 3 samples. Run two used 3 samples."])
    check("each numeric literal is attributed to its own sentence",
          len(led) == 2 and led[1]["sentence"].startswith("Run two"),
          str([r["sentence"] for r in led]))
    stats = fmt.table_column_stats([("t.md", "| sample | count |\n|---|---|\n| a | 3 |\n| b | 4 |\n")])
    check("a markdown separator row is not a data row; pipes make no phantom columns",
          [s["column"] for s in stats] == ["sample", "count"]
          and {s["n rows"] for s in stats} == {2},
          f"{[s['column'] for s in stats]} {[s['n rows'] for s in stats]}")
    js_dir = scratch("audit_fmt_json_")
    (js_dir / "cfg.json").write_text('{\n  "n_samples": 15,\n  "threshold": 0.05\n}\n')
    json_rows = fmt.code_literal_rows([(js_dir, "", ())])
    check("JSON config literals are extracted (as the extension list promises)",
          {r["symbol"] for r in json_rows} == {"n_samples", "threshold"},
          str([(r["symbol"], r["value"]) for r in json_rows]))


def test_pdf_and_encoding_defects():
    print("\n== check-pdf fails loudly; a UTF-16 document.xml is reported, not a crash ==")
    tmp = scratch("audit_fmt_pdf_")
    bad = tmp / "not-a.pdf"
    bad.write_text("this is not a pdf")
    res = fmt.check_pdf(bad, fmt.load_policy(None))
    check("check_pdf reports an unreadable PDF instead of 0 clean pages",
          res["ok"] is False and [r["rule"] for r in res["rows"]] == ["FMT-S2"],
          f"pages={res['pages']} ok={res['ok']} rows={[r['rule'] for r in res['rows']]}")
    docx = tmp / "utf16.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", document('<w:p><w:r><w:t>x</w:t></w:r></w:p>').encode("utf-16"))
        z.writestr("word/styles.xml", STYLES)
    try:
        info = fmt.analyse_package(docx, fmt.load_policy(None))
        rules = [r["rule"] for r in info["rows"]]
    except Exception as exc:                                       # noqa: BLE001
        rules = [f"raised {type(exc).__name__}"]
    check("a UTF-16 word/document.xml becomes an FMT-X1 row, not a crash",
          rules == ["FMT-X1"], str(rules))


def test_italic_and_size_boundaries():
    print("\n== style regexes do not swallow longer element names ==")
    tmp = scratch("audit_fmt_regex_")
    doc = document(
        '<w:p><w:r><w:t>Abstract</w:t></w:r></w:p>'
        '<w:p><w:r><w:rPr><w:i/><w:imprint/></w:rPr>'
        '<w:t xml:space="preserve">* Correspondence: a@example.org</w:t></w:r></w:p>')
    src, out = make_package(tmp / "in.docx", doc), tmp / "out.docx"
    fmt.fix_package(src, out, fmt.load_policy(None))
    fixed = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")
    check("removing an italic run keeps a sibling w:imprint element",
          "<w:imprint" in fixed and "<w:i/>" not in fixed, fixed[fixed.find("rPr"):][:120])
    tmp2 = scratch("audit_fmt_sz_")
    doc2 = document('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
                    '<w:r><w:rPr><w:sz w:val="40"/><w:szCs w:val="40"/></w:rPr>'
                    '<w:t>Results</w:t></w:r></w:p>')
    src2, out2 = make_package(tmp2 / "in.docx", doc2), tmp2 / "out.docx"
    policy = fmt.load_policy(None)
    policy["align_heading_sizes"] = True
    fmt.fix_package(src2, out2, policy)
    fixed2 = zipfile.ZipFile(out2).read("word/document.xml").decode("utf-8")
    check("dropping a direct w:sz override keeps w:szCs",
          re.search(r"<w:sz\s", fixed2) is None and "<w:szCs" in fixed2,
          fixed2[fixed2.find("rPr"):][:160])


# ---------------------------------------------------------------------------
# paper_pipeline.py
# ---------------------------------------------------------------------------

def test_pipeline_prompt_and_limits():
    print("\n== the rendered length rule never prints a 'None' cap ==")
    for vid in ("generic", "example-journal"):
        text = nb.length_rule_text(nb.load_venue_profile(vid))
        check(f"{vid}: the M19 rule carries no literal 'None words'",
              "None words" not in text and "None" not in text.split("COUNTING RULE")[0],
              [l.strip() for l in text.splitlines() if "None" in l][:2])
    nbt = nb.length_rule_text(nb.load_venue_profile("nature-biotechnology"))
    check("nature-biotechnology still states its 650-word operator cap",
          "SEPARATE cap of 650 words" in nbt)
    check("lenient_word_limit is an exact floor", nb.lenient_word_limit(100, 1.15) == 115
          and nb.lenient_word_limit(150, 1.10) == 165 and nb.lenient_word_limit(3000, 1.25) == 3750,
          f"{nb.lenient_word_limit(100, 1.15)} {nb.lenient_word_limit(150, 1.10)}")
    check("ADD_VENUE_PROMPT describes relaxation as a factor, not extra words",
          "extra words" not in nb.ADD_VENUE_PROMPT and 'factor >= 1.0' in nb.ADD_VENUE_PROMPT)


# ---------------------------------------------------------------------------
# paper-skills scripts + repository surfaces
# ---------------------------------------------------------------------------

def test_skill_scripts():
    print("\n== BOM handling and citation order ==")
    sys.path.insert(0, str(WS / "paper-skills/paper-review/scripts"))
    import convert_corpus as cc
    tmp = scratch("audit_skill_bom_")
    bom = tmp / "bom.txt"
    bom.write_bytes("\ufeffAbstract\nWe did a thing.\n".encode("utf-8"))
    text, notes = cc.plain_copy(str(bom))
    check("plain_copy strips a UTF-8 BOM", text.startswith("Abstract") and not notes,
          repr(text[:12]))
    work = scratch("audit_skill_cite_")
    (work / "corpus").mkdir()
    (work / "corpus" / "ms.txt").write_text(
        "Title\n\nWe used A [1], then B [2], then A again [1].\n\nReferences\n\n"
        "1. Alpha A. Nature. 2020.\n2. Beta B. Science. 2021.\n", encoding="utf-8")
    proc = subprocess.run([sys.executable,
                           str(WS / "paper-skills/paper-review/scripts/extract_citations.py"),
                           "--work", str(work), "--out", str(work / "out")],
                          capture_output=True, text=True)
    art = (work / "out/artifacts/M2_citations.md").read_text(encoding="utf-8")
    check("re-citing an earlier reference is not an order violation",
          proc.returncode == 0
          and re.search(r"Order violations.*: 0\b", art) is not None,
          [l for l in art.splitlines() if "Order violations" in l])
    work2 = scratch("audit_skill_cite2_")
    (work2 / "corpus").mkdir()
    (work2 / "corpus" / "ms.txt").write_text(
        "Title\n\nWe used B [2], then A [1].\n\nReferences\n\n"
        "1. Alpha A. Nature. 2020.\n2. Beta B. Science. 2021.\n", encoding="utf-8")
    subprocess.run([sys.executable,
                    str(WS / "paper-skills/paper-review/scripts/extract_citations.py"),
                    "--work", str(work2), "--out", str(work2 / "out")],
                   capture_output=True, text=True)
    art2 = (work2 / "out/artifacts/M2_citations.md").read_text(encoding="utf-8")
    check("a genuinely out-of-order first appearance is still flagged",
          re.search(r"Order violations.*: 1\b", art2) is not None,
          [l for l in art2.splitlines() if "Order violations" in l])


def test_repo_surfaces():
    print("\n== the MCP converter chain and the shipped converter mode ==")
    check("docx2pdf.sh is executable in the working tree",
          os.access(WS / "docx2pdf.sh", os.X_OK))
    js = (WS / "mcp-docx-converter/index.js").read_text(encoding="utf-8")
    check("the hardcoded developer path is gone",
          "/home/zhaoxiaofei" not in js)
    check("an existing-but-non-executable candidate cannot shadow PATH",
          "X_OK" in js and "isExecutable" in js)
    if shutil.which("wslpath") or shutil.which("cygpath"):
        tmp = scratch("audit_pdf_link_")
        (tmp / "real").mkdir()
        (tmp / "link").mkdir()
        (tmp / "bin").mkdir()
        target = tmp / "real/target.pdf"
        target.write_bytes(b"%PDF-1.4 fake")
        os.symlink("../real/target.pdf", tmp / "link/alias.docx")
        fake = tmp / "bin/powershell.exe"
        fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        os.chmod(fake, 0o755)
        env = dict(os.environ, PATH=f"{tmp / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}")
        proc = subprocess.run(["/bin/bash", str(WS / "docx2pdf.sh"), str(tmp / "link/alias.docx")],
                              capture_output=True, text=True, env=env, timeout=120)
        check("a .docx symlink to a real .pdf is refused without deleting the PDF",
              proc.returncode == 2 and target.is_file(),
              f"rc={proc.returncode} exists={target.is_file()} err={proc.stderr[-120:]!r}")
    else:
        print("[skip] docx2pdf.sh symlink guard needs wslpath/cygpath")


def main() -> int:
    try:
        test_self_closing_paragraph()
        test_text_edit_identity()
        test_title_page_section()
        test_keep_list_and_ledgers()
        test_pdf_and_encoding_defects()
        test_italic_and_size_boundaries()
        test_pipeline_prompt_and_limits()
        test_skill_scripts()
        test_repo_surfaces()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} GENERAL-AUDIT CHECK(S) FAILED")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("ALL GENERAL-AUDIT (2026-10-02) CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

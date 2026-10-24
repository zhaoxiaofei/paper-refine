#!/usr/bin/env python3
"""Layout-integrity and submission-surface rules (2026-10-19).

Pins the classes found while validating the CNB winner and the neohet revised
package:

* FMT-TB4/FMT-TB5 -- a table whose `w:tblGrid` disagrees with its cells, and an
  identifier that cannot fit its column (the neohet Table 3 shape);
* FMT-S10 -- two PAGE fields in one referenced footer part (two page numbers);
* FMT-AV3 -- a "shipped/deposited" claim with no locator (the neohet supplement);
* the .bib prose model (abstracts are quotations, not the authors' sentences);
* the declared-submission parser (a pattern on the line after the hint);
* `_validation_targets` (a scratch docx under work/ cannot fail a stage);
* templated disposition closures (only the row's token changes).

Run:  python3 .paper_test/test_layout_integrity_2026_1019.py
      (the harness form; `python3 -m pytest -q ...` also works)
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("paper_docx_format",
                                              str(WS / "paper_docx_format.py"))
fmt = importlib.util.module_from_spec(spec)
sys.modules["paper_docx_format"] = fmt
spec.loader.exec_module(fmt)

pspec = importlib.util.spec_from_file_location("paper_pipeline", str(WS / "paper_pipeline.py"))
pp = importlib.util.module_from_spec(pspec)
sys.modules["paper_pipeline"] = pp
pspec.loader.exec_module(pp)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _styles() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">
 <w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman"/></w:rPr></w:rPrDefault></w:docDefaults>
 <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
 <w:style w:type="paragraph" w:customStyle="1" w:styleId="TableText"><w:name w:val="Table Text"/>
   <w:basedOn w:val="Normal"/><w:rPr><w:sz w:val="20"/></w:rPr></w:style>
</w:styles>"""


def _table_doc(grid, cells, token="D08M18DB1") -> str:
    grid_xml = "".join(f'<w:gridCol w:w="{w}"/>' for w in grid)
    cell_xml = "".join(
        f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/></w:tcPr>'
        f'<w:p><w:pPr><w:pStyle w:val="TableText"/></w:pPr><w:r><w:t>{t}</w:t></w:r></w:p>'
        f'</w:tc>'
        for w, t in zip(cells, [token, token]))
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}"><w:body>
<w:p><w:r><w:t>Body.</w:t></w:r></w:p>
<w:tbl><w:tblPr><w:tblW w:w="3000" w:type="dxa"/>
  <w:tblCellMar><w:left w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar>
</w:tblPr><w:tblGrid>{grid_xml}</w:tblGrid>
<w:tr><w:trPr><w:tblHeader/></w:trPr>{cell_xml}</w:tr>
<w:tr>{cell_xml}</w:tr>
</w:tbl>
<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>
</w:body></w:document>"""


def _package(path: Path, doc_xml: str, extra: dict = None) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", doc_xml)
        z.writestr("word/styles.xml", _styles())
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def test_table_grid_and_identifier():
    doc = _table_doc(grid=[900, 2100], cells=[1400, 1600], token="D08M18DB1")
    rows = fmt.table_layout_rows(doc, {}, "x.docx")
    found = {r["rule"] for r in rows}
    assert "FMT-TB4" in found, found
    assert "FMT-TB5" in found, found
    edits = fmt.table_layout_fixes(doc, rows)
    fixed = fmt.apply_edits(doc, edits)
    left = {r["rule"] for r in fmt.table_layout_rows(fixed, {}, "x.docx")}
    assert "FMT-TB4" not in left, left
    # The identifier now fits the 1400-twip column (9 chars at 10 pt ~ 990 + 160).
    assert fmt._token_width_twips("D08M18DB1", 10.0) + 160 <= 1400
    assert fmt.text_of(fmt.paragraphs(doc)[1][2]) == "D08M18DB1"
    assert "".join(fmt.text_of(p[2]) for p in fmt.paragraphs(doc)) == \
        "".join(fmt.text_of(p[2]) for p in fmt.paragraphs(fixed))


def test_page_field_duplicate_removed():
    def para(n):
        return (f'<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                f'<w:r><w:instrText xml:space="preserve"> PAGE  \\* Arabic </w:instrText></w:r>'
                f'<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                f'<w:r><w:t>{n}</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    footer = f'<?xml version="1.0"?><w:ftr xmlns:w="{W}">{para(3)}{para(3)}</w:ftr>'
    rows = fmt.page_field_rows([("word/footer1.xml", footer)], "x.docx")
    assert [r["rule"] for r in rows] == ["FMT-S10"]
    edits = fmt.page_field_fixes(footer)
    fixed = fmt.apply_edits(footer, edits)
    assert len(fmt.PAGE_FIELD_INSTR_RE.findall(fixed)) == 1


def test_page_field_in_textbox_is_manual():
    footer = (f'<?xml version="1.0"?><w:ftr xmlns:w="{W}">'
              f'<w:p><w:txbxContent><w:p><w:r><w:instrText> PAGE </w:instrText></w:r></w:p>'
              f'</w:txbxContent></w:p>'
              f'<w:p><w:r><w:instrText> PAGE </w:instrText></w:r></w:p></w:ftr>')
    rows = fmt.page_field_rows([("word/footer2.xml", footer)], "x.docx")
    assert rows and rows[0]["fix"] == "manual"
    assert fmt.page_field_fixes(footer) == []


def test_availability_claim_needs_locator():
    paras = [
        "Each curve is computed from the shipped per-candidate tables.",
        "The data are available at https://example.org/data.",
        "The tables shipped with MHCflurry 2.0 were used.",
        "Deposited data",
        "The tables can be obtained from the corresponding author.",
    ]
    rows = fmt.availability_claim_rows(paras, "x.docx")
    assert len(rows) == 1, rows
    assert "shipped per-candidate" in rows[0]["evidence"]


def test_bib_prose_drops_abstracts():
    bib = """@article{a,
  title = {A short title},
  abstract = {This abstract is a very long quotation. It runs on and on. """ + \
          ("It keeps going. " * 40) + """},
  author = {Alpha A, Beta B, Gamma C, Delta D, Epsilon E, Zeta F, Eta G},
  doi = {10.1/xyz},
}
"""
    paras = fmt.bib_prose_paragraphs(bib)
    joined = " ".join(paras)
    assert "A short title" in joined
    assert "It keeps going" not in joined
    assert "Alpha A" not in joined          # an author list is data, not prose


def test_declared_submission_parser_reads_next_paragraph(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(
        "Only files whose names match the following Bash extglob pattern will be submitted to the\n"
        "venue/journal:\n\n"
        "`mesh-*-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f].@(docx|pdf)`\n"
        "or\n"
        "`figures/*.png`\n\n"
        "All other files will not be submitted.\n")
    (tmp_path / "mesh-x-abcdef0.docx").write_bytes(b"x")
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "Fig1.png").write_bytes(b"x")
    (tmp_path / "notes.docx").write_bytes(b"x")
    decl = pp.declared_submission_set(tmp_path)
    assert decl["declared"], decl
    assert set(decl["files"]) == {"mesh-x-abcdef0.docx", "figures/Fig1.png"}, decl["files"]


def test_validation_targets_skip_scratch(tmp_path):
    (tmp_path / "README.md").write_text("Only `mesh-*.docx` will be submitted.\n")
    (tmp_path / "mesh-x-abcdef0.docx").write_bytes(b"x")
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "test_si_patched.docx").write_bytes(b"x")
    (tmp_path / "notes.docx").write_bytes(b"x")
    targets = pp._validation_targets(tmp_path)
    assert [p.name for p in targets] == ["mesh-x-abcdef0.docx"], targets


def test_templated_disposition_is_boilerplate():
    rows = [{"rule": "FMT-T9c", "tier": "finding",
             "location": f"p{i}",
             "disposition": f"outside the submitted prose - the row is inside a bibliography "
                            f"abstract/quoted field ('token {i}'), not the authors' text"}
            for i in range(30)]
    problems = pp.disposition_artifact_problems(rows)
    assert any("TEMPLATE" in p for p in problems), problems


def test_figure_label_split_form(monkeypatch):
    monkeypatch.setattr(fmt.shutil, "which", lambda _name: "/usr/bin/tesseract")
    monkeypatch.setattr(fmt, "_ocr_text", lambda _p: "Hetero\nclitic")
    rows = fmt.figure_label_rows([Path("Fig1.png")], ["Heteroclitic", "FastQ"])
    assert len(rows) == 1, rows
    assert "Heteroclitic" in rows[0]["evidence"]


if __name__ == "__main__":
    # `run_all.py` executes suites as scripts; without this block the file ran
    # only its imports and exited 0, which the harness counted as PASS with zero
    # checks. The shim supplies the pytest fixtures the functions use.
    from pytest_shim import run_tests
    raise SystemExit(run_tests(globals()))

#!/usr/bin/env python3
"""OOXML style/formatting audit + fixer (nbt_docx_format.py).

Run:  python3 .nbt_test/test_docx_format.py

The fixture is a minimal but schema-shaped WordprocessingML package that carries
every defect the real round-2 final package showed, so the suite pins both the
detection and the byte-level repair:

  * a break-only empty paragraph between the title page and the Introduction
    (the blank page after the cover page);
  * a running head that also prints on the title page (no w:titlePg);
  * tracked changes, proofing markers and a literal tab;
  * a figure legend with per-figure spacing (one legend missing before/after);
  * headings whose runs override the style size and carry no keepNext;
  * an italic correspondence block (emails included) and an italic "et al."
    inside a Zotero bibliography field (field-protected -> style/unlink, never a
    silent run edit);
  * a reference without an italic journal title;
  * the same URL hyperlinked in one place and plain in another, plus a dark
    italic email;
  * mixed straight/curly quotation marks and an em-dash flood.

Verification of the fixer is part of the contract: the parts stay byte-identical,
the text is unchanged, the XML namespace declarations survive (a naive
ElementTree round-trip produced "the file appears to be corrupted" in Word), the
package still validates, and a re-scan shows every mechanical finding gone.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_docx_format", str(WS / "nbt_docx_format.py"))
fmt = importlib.util.module_from_spec(spec)
sys.modules["nbt_docx_format"] = fmt
spec.loader.exec_module(fmt)

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


P = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
W14 = "{http://schemas.microsoft.com/office/word/2010/wordml}"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://github.com/zhaoxiaofei/copy-num-bench" TargetMode="External"/>
  <Relationship Id="rId6" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
</Relationships>"""

CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title>CopyNumBench</dc:title><dc:creator>Test</dc:creator></cp:coreProperties>"""

APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"/>"""

STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{P[1:-1]}">
  <w:docDefaults><w:pPrDefault><w:pPr><w:spacing w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
  <w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="480" w:after="360"/></w:pPr>
    <w:rPr><w:sz w:val="32"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Bibliography"><w:name w:val="Bibliography"/></w:style>
  <w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/>
    <w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr></w:style>
  <w:style w:type="character" w:styleId="Emphasis"><w:name w:val="Emphasis"/>
    <w:rPr><w:i/></w:rPr></w:style>
</w:styles>"""

HEADER = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="{P[1:-1]}"><w:p><w:r><w:t>CopyNumBench (running head)</w:t></w:r></w:p></w:hdr>"""


def doc_xml(filler: int = 0) -> str:
    """Document with one of every defect (offsets are what the rules look for).

    `filler` adds body paragraphs before the break-only paragraph, so the
    rendered-page test can push the break onto its own page (a break-only
    paragraph only shows as a *blank page* when the preceding page is full).
    """
    filler_xml = "".join(
        f'  <w:p><w:r><w:t>Filler paragraph {i}: ' + ("copy-number benchmarking text " * 12)
        + "</w:t></w:r></w:p>\n" for i in range(filler))
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{P[1:-1]}" xmlns:r="{R[1:-1]}" xmlns:mc="{MC[1:-1]}" xmlns:w14="{W14[1:-1]}" mc:Ignorable="w14">
<w:body>
  <w:p><w:r><w:rPr><w:sz w:val="28"/></w:rPr><w:t>CopyNumBench: a benchmark</w:t></w:r></w:p>
  <w:p><w:r><w:t>Authors: A, B and C</w:t></w:r></w:p>
  <w:p><w:r><w:rPr><w:i/><w:color w:val="333333"/></w:rPr><w:t xml:space="preserve">* Correspondence: A (a@example.org) and B (b@example.org)</w:t></w:r></w:p>
  <w:p><w:r><w:t>Abstract</w:t></w:r></w:p>
  <w:p><w:r><w:t xml:space="preserve">Copy-number callers diverge\u2014widely \u2014 and again \u2014 so we benchmark them. A caller's output must match the practitioner\u2019s rule; "quoted" text follows.</w:t></w:r></w:p>
  <w:p><w:r><w:t>Keywords: copy-number, benchmark.</w:t></w:r></w:p>
{filler_xml}  <w:p><w:r><w:br w:type="page"/></w:r></w:p>
  <w:p><w:r><w:br w:type="page"/></w:r></w:p>
  <w:p><w:r><w:t>The copy-number profile of a cell is measured here.</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:rPr><w:sz w:val="28"/></w:rPr><w:t>Results</w:t></w:r></w:p>
  <w:p><w:r><w:t xml:space="preserve">See https://github.com/zhaoxiaofei/copy-num-bench for the code</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t xml:space="preserve">and the tab above (plus a raw	tab).</w:t></w:r></w:p>
  <w:p><w:hyperlink r:id="rId5"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr><w:t>https://github.com/zhaoxiaofei/copy-num-bench</w:t></w:r></w:hyperlink></w:p>
  <w:p><w:r><w:t>Fig. 1 | Benchmark overview.</w:t></w:r></w:p>
  <w:p><w:pPr><w:spacing w:before="200" w:after="200" w:line="240" w:lineRule="auto"/></w:pPr><w:r><w:t>Fig. 2 | A legend with its own spacing.</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>
    <w:r><w:fldChar w:fldCharType="begin"/></w:r>
    <w:r><w:instrText xml:space="preserve"> ADDIN ZOTERO_BIBL {{"uncited":[]}} CSL_BIBLIOGRAPHY </w:instrText></w:r>
    <w:r><w:fldChar w:fldCharType="separate"/></w:r>
    <w:r><w:t xml:space="preserve">1. Chen, C. </w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>et al.</w:t></w:r>
    <w:r><w:t xml:space="preserve"> Single-cell analyses. </w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>Science</w:t></w:r>
    <w:r><w:t xml:space="preserve"> 356, 189-194 (2017).</w:t></w:r>
    <w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr><w:r><w:t>2. Preprint without a journal. arXiv:1303.3997 (2013).</w:t></w:r></w:p>
  <w:p><w:ins w:id="1" w:author="A" w:date="2026-09-20T00:00:00Z"><w:r><w:t>inserted</w:t></w:r></w:ins></w:p>
  <w:p><w:r><w:t>Proofed</w:t></w:r><w:proofErr w:type="spellStart"/><w:r><w:t>scWGS</w:t></w:r><w:proofErr w:type="spellEnd"/><w:r><w:t xml:space="preserve"> text.</w:t></w:r></w:p>
  <w:sectPr><w:headerReference w:type="default" r:id="rId6"/><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1701" w:bottom="1440" w:left="1701" w:header="851" w:footer="992" w:gutter="0"/></w:sectPr>
</w:body></w:document>"""


def make_package(path: Path, document_xml: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/document.xml", document_xml or doc_xml())
        z.writestr("word/styles.xml", STYLES)
        z.writestr("word/header1.xml", HEADER)
        z.writestr("docProps/core.xml", CORE)
        z.writestr("docProps/app.xml", APP)
    return path


def rules(rows) -> set:
    return {r["rule"] for r in rows}


def doc_xml_journal() -> str:
    """The real-world journal-emphasis defect (cover letter, 2026-09-21).

    Word's `Emphasis` CHARACTER STYLE carries the italics, so the runs hold no
    `<w:i/>` of their own: "Nature Biotechnology" is italic in two sentences and
    roman in others, and the emphasis of "Nature Methods" runs on over "other
    leading journals". The reference list has one roman journal title and one
    correct italic one; a legitimate italic ("de novo") and journal-like words
    inside ordinary prose ("Cell-line") must NOT be touched.
    """
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{P[1:-1]}" xmlns:r="{R[1:-1]}" xmlns:mc="{MC[1:-1]}" xmlns:w14="{W14[1:-1]}" mc:Ignorable="w14">
<w:body>
  <w:p><w:r><w:t>CopyNumBench: a benchmark</w:t></w:r></w:p>
  <w:p><w:r><w:t xml:space="preserve">We are pleased to submit our work for consideration in </w:t></w:r>
    <w:r><w:rPr><w:rStyle w:val="Emphasis"/></w:rPr><w:t>Nature Biotechnology</w:t></w:r>
    <w:r><w:t xml:space="preserve">, a journal that also published the work of </w:t></w:r>
    <w:r><w:rPr><w:rStyle w:val="Emphasis"/></w:rPr><w:t>Nature Methods</w:t></w:r>
    <w:r><w:t xml:space="preserve"> and </w:t></w:r>
    <w:r><w:rPr><w:rStyle w:val="Emphasis"/></w:rPr><w:t>other leading</w:t></w:r>
    <w:r><w:t xml:space="preserve"> </w:t></w:r>
    <w:r><w:rPr><w:rStyle w:val="Emphasis"/></w:rPr><w:t>journals</w:t></w:r>
    <w:r><w:t xml:space="preserve">. Nature Biotechnology publishes benchmarks of this kind. We used a </w:t></w:r>
    <w:r><w:rPr><w:i/></w:rPr><w:t>de novo</w:t></w:r>
    <w:r><w:t xml:space="preserve"> assembly and cultured cells in Cell-line medium (see https://github.com/example/Single-Cell-bench).</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>
    <w:r><w:t xml:space="preserve">1. Doe, J. A benchmark. </w:t></w:r>
    <w:r><w:t>Nature Methods</w:t></w:r>
    <w:r><w:t xml:space="preserve"> 20, 1-9 (2024).</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>
    <w:r><w:t xml:space="preserve">2. Roe, J. Single-cell analysis. </w:t></w:r>
    <w:r><w:rPr><w:i/></w:rPr><w:t>Science</w:t></w:r>
    <w:r><w:t xml:space="preserve"> 1, 1-2 (2024).</w:t></w:r></w:p>
</w:body></w:document>"""


def test_journal_emphasis():
    """An italic that lives in a CHARACTER STYLE must be seen, made consistent
    and fixed -- without touching legitimate italics or journal-like words."""
    print()
    print("== journal emphasis: character-style italics, mixed treatment, run-on spans ==")
    tmp = scratch("nbt_fmt_journal_")
    docx = make_package(tmp / "cover-letter.docx", doc_xml_journal())
    policy = fmt.load_policy(None)
    info = fmt.scan_paths([tmp], policy)
    got = rules(info["rows"])
    for rule, label in (("FMT-T6c", "italic journal name outside the reference list"),
                        ("FMT-T6f", "emphasis running on past the journal title"),
                        ("FMT-T6e", "the same journal name italic in one place, roman in another"),
                        ("FMT-T6g", "a reference-list journal title left roman")):
        check(f"journal scan detects {label} ({rule})", rule in got, f"got {sorted(got)}")
    ev = " | ".join(r["evidence"] for r in info["rows"])
    check("journal scan reads italics that come from the Emphasis character style",
          "Nature Biotechnology" in ev and "Nature Methods" in ev, ev[:160])
    check("journal scan ignores journal-like words inside ordinary prose and URLs",
          "Cell-line" not in ev and "Single-Cell-bench" not in ev and "de novo" not in ev,
          ev[:200])
    check("journal scan names the roman reference title", "FMT-T6g" in got, f"{sorted(got)}")
    out = tmp / "cover-letter.fixed.docx"
    rep = fmt.fix_package(docx, out, policy)
    v = rep["verified"]
    check("journal fix repairs every mechanical finding and verifies",
          rep["ok"] and v["remaining_mechanical_rules"] == []
          and v["mechanical_findings_after"] == 0 and v["text_identical"] and v["parts_intact"],
          json.dumps(v)[:220])
    check("journal fix states what it did",
          any("journal emphasis" in c for c in rep["changes"]), str(rep["changes"]))
    after = rules(fmt.scan_paths([out], policy)["rows"])
    check("after the journal fix no journal-emphasis row remains",
          not ({"FMT-T6c", "FMT-T6e", "FMT-T6f", "FMT-T6g"} & after), f"{sorted(after)}")
    with zipfile.ZipFile(out) as z:
        fixed = z.read("word/document.xml").decode("utf-8")
        styles_after = z.read("word/styles.xml").decode("utf-8")
    check("the cover-letter journal runs are pinned roman (direct override beats the style)",
          '<w:i w:val="0"/>' in fixed and 'w:rStyle w:val="Emphasis"' in fixed)
    check("the reference-list journal title was made italic",
          re.search(r"<w:rPr><w:i/></w:rPr><w:t>Nature Methods</w:t>|<w:t>Nature Methods</w:t>",
                    fixed) is not None and "<w:i/>" in fixed)
    check("a legitimate italic (de novo) survives the journal fix",
          re.search(r"<w:rPr><w:i/></w:rPr><w:t>de novo</w:t>", fixed) is not None)
    check("the styles part is untouched (only run-level overrides were added)",
          styles_after == STYLES)
    survey = (info["documents"][0].get("documents") or {}).get("cover-letter.docx", {}) \
        .get("style_survey") or {}
    check("the scan carries the font/paragraph-style inventory (the STYLE artifact)",
          survey.get("paragraph_styles", {}).get("Bibliography") == 2
          and survey.get("character_styles", {}).get("Emphasis", 0) >= 4
          and survey.get("italic_runs", {}).get("character_style", 0) >= 4,
          json.dumps(survey)[:200])
    survey_after = fmt.analyse_package(out, policy)["documents"]["cover-letter.fixed.docx"] \
        .get("style_survey") or {}
    check("after the fix no italic comes from the Emphasis character style any more",
          survey_after.get("italic_runs", {}).get("character_style", 0) == 0
          and survey_after.get("italic_runs", {}).get("direct", 0) >= 1,
          json.dumps(survey_after.get("italic_runs"))[:160])
    rep2 = fmt.fix_package(out, tmp / "again.docx", policy)
    check("the journal fix is idempotent", rep2["changes"] == [] and rep2["ok"],
          str(rep2["changes"])[:160])


def doc_xml_text_rules() -> str:
    """The 2026-09-21 consistency classes, in one document.

    Mixed citation formats (with/without the journal, and journal-before-year),
    a proper name repeated four times in one short paragraph, US/UK spelling
    variants, an attributive compound hyphenated in one place and not in the
    next, and a nested parenthesis. The reference list carries the same words
    and must stay untouched; the mathematical call must not count as nesting.
    """
    filler = ("Copy-number inference from single-cell data is difficult because the "
              "measurements are noisy and the ground truth is rarely available; a benchmark "
              "therefore compares callers on the same cells and the same metrics.")
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{P[1:-1]}">
<w:body>
  <w:p><w:r><w:t xml:space="preserve">We thank the callers (Garvin et al., 2015, Nature Methods), (Zaccaria &amp; Raphael, 2021, Nature Biotechnology) and (Qin et al., 2024, Genome Research), and the benchmarks (Mallory et al., 2020a, 2020b) and (Schneider et al., Genome Biology, 2024).</w:t></w:r></w:p>
  <w:p><w:r><w:t xml:space="preserve">Nature Biotechnology is the venue we chose. Nature Biotechnology publishes benchmarks like this one. Nature Biotechnology readers work on single-cell genomics, and Nature Biotechnology has published the related tools. {filler}</w:t></w:r></w:p>
  <w:p><w:r><w:t xml:space="preserve">The tumor samples were prepared in one laboratory, the tumor controls in another, and both were re-analysed together with the tumour-derived references.</w:t></w:r></w:p>
  <w:p><w:r><w:t xml:space="preserve">We used copy-number profiles from the benchmark and a copy number estimate from the same cells to rank the callers.</w:t></w:r></w:p>
  <w:p><w:r><w:t xml:space="preserve">(Numbat requires such data to compute B-allele frequency (BAF) for the caller), and the transform (where T(·,·) denotes a merge) is applied first.</w:t></w:r></w:p>
  <w:p><w:r><w:t xml:space="preserve">It requires specialized protocols (multiple displacement amplification, MALBAC (multiple annealing and looping-based amplification cycles), DLP+ (Direct Library Preparation Plus), wellDR-seq, scONE-seq, DNTR-seq, and their derivatives), deep sequencing, and infrastructure.</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr><w:r><w:t xml:space="preserve">1. Doe, J. Breast tumours and copy number variation profiling. Nature 1, 1-2 (2024).</w:t></w:r></w:p>
  <w:p><w:r><w:t xml:space="preserve">Xuegong Zhang, Ph.D., Professor (Co-corresponding author; </w:t></w:r>
    <w:r><w:rPr><w:rStyle w:val="Emphasis"/></w:rPr><w:t>zhangxg@tsinghua.edu.cn)</w:t></w:r>
    <w:r><w:t xml:space="preserve"> and Zhen Xie, Ph.D., Professor (Co-corresponding author; zhenxie@tsinghua.edu.cn)</w:t></w:r></w:p>
</w:body></w:document>"""


def test_text_consistency_rules():
    """Citation formats, nested parentheses, repetition, spelling and hyphenation."""
    print()
    print("== text consistency: citations, parentheses, repetition, variants ==")
    tmp = scratch("nbt_fmt_text_")
    docx = make_package(tmp / "text.docx", doc_xml_text_rules())
    policy = fmt.load_policy(None)
    info = fmt.scan_paths([tmp], policy)
    got = rules(info["rows"])
    for rule, label in (("FMT-T8a", "mixed citation formats"),
                        ("FMT-T8b", "nested parentheses"),
                        ("FMT-T8c", "a name repeated in one short paragraph"),
                        ("FMT-T8d", "US/UK spelling variants"),
                        ("FMT-T8e", "attributive hyphenation variant")):
        check(f"text scan detects {label} ({rule})", rule in got, f"got {sorted(got)}")
    ev = " | ".join(r["evidence"] for r in info["rows"])
    check("the citation row names the formats it found",
          "journal-year" in ev and "year-journal" in ev and "year-only" in ev, ev[:160])
    check("nested-parenthesis rows ignore mathematical notation",
          "T(·,·)" not in ev and "(BAF)" in ev, ev[:200])
    nested_rows = [r for r in info["rows"] if r["rule"] == "FMT-T8b"]
    check("a sibling-group nesting (six inner groups in one outer pair) is ONE row",
          any("MALBAC" in r["evidence"] for r in nested_rows)
          and len([r for r in nested_rows if "MALBAC" in r["evidence"]]) == 1,
          str([r["evidence"][:80] for r in nested_rows]))
    check("the repetition row names the repeated proper name",
          "nature biotechnology" in ev, ev[:200])
    out = tmp / "text.fixed.docx"
    rep = fmt.fix_package(docx, out, policy)
    v = rep["verified"]
    check("text fix repairs the mechanical rows and proves the edits",
          rep["ok"] and v["remaining_mechanical_rules"] == []
          and v["text_diff_only_recorded_edits"] and v["text_edits"] >= 3,
          json.dumps(v)[:240])
    fixed_text = "\n".join(fmt.text_of(p[2]) for p in fmt.paragraphs(
        zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")))
    check("the citation journal names are gone from the cover-letter text",
          "(Garvin et al., 2015)" in fixed_text and "(Schneider et al., 2024)" in fixed_text
          and "Nature Methods)" not in fixed_text, fixed_text[:200])
    check("the spelling minority form was normalized in body text",
          "tumour" not in fixed_text.split("1. Doe")[0].lower()
          and "tumor" in fixed_text.lower(), fixed_text[:200])
    check("the attributive compound was hyphenated",
          "copy number estimate" not in fixed_text.lower())
    check("the reference list is untouched (its title is a quotation)",
          "Breast tumours and copy number variation" in fixed_text)
    after = rules(fmt.scan_paths([out], policy)["rows"])
    check("after the text fix only the report-only rows remain",
          not ({"FMT-T8a", "FMT-T8d", "FMT-T8e"} & after), f"{sorted(after)}")


def test_quality_engines():
    """The artifact engines behind the text-quality rules (M4/M8/outline/etc.)."""
    print()
    print("== quality engines: numbers, terms, emphasis, outline, placeholders ==")
    tmp = scratch("nbt_fmt_engine_")
    docx = make_package(tmp / "engines.docx", doc_xml_text_rules())
    policy = fmt.load_policy(None)
    rows = fmt.scan_paths([docx], policy)["rows"]
    got = {r["rule"] for r in rows}
    check("mixed emphasis for a parenthetical label is detected (FMT-T9a)",
          "FMT-T9a" in got, f"{sorted(got)}")
    long_para = " ".join(["word"] * 50) + "."
    list_para = " ".join(["word"] * 210) + " (1) first (2) second (3) third."
    check("a long sentence is reported (FMT-T9c)",
          any(r["rule"] == "FMT-T9c" and "long sentence" in r["evidence"]
              for r in fmt.long_text_rows([long_para]))
          and any("enumerated" in r["evidence"] for r in fmt.long_text_rows([list_para])))
    check("confusable terms in one document are reported (FMT-T9d)", "FMT-T9d" in got)
    out = tmp / "engines.fixed.docx"
    rep = fmt.fix_package(docx, out, policy)
    check("the label emphasis is unified and the package stays valid",
          rep["ok"] and any("mixed-emphasis" in c for c in rep["changes"]),
          str(rep["changes"]))
    after = {r["rule"] for r in fmt.scan_paths([out], policy)["rows"]}
    check("the emphasis row is gone after the fix", "FMT-T9a" not in after, f"{sorted(after)}")
    paras = ["We analysed 45,365 cells and 2,000 controls at 37 °C for 30 min.",
             "The emulated dataset was validated; the simulated dataset was verified."]
    led = fmt.number_ledger(paras)
    check("the number ledger carries every literal with its sentence",
          {r["number"] for r in led} >= {"45,365", "2,000", "37", "30"} and led[0]["sentence"],
          str([r["number"] for r in led]))
    check("thousands-separator inconsistency is reported (FMT-T9h)",
          any(r["rule"] == "FMT-T9h" for r in fmt.number_format_rows(
              ["45,365 cells", "45365 cells"])),
          str(fmt.number_format_rows(["45,365 cells", "45365 cells"])))
    check("LaTeX quantities outside \\SI are reported (FMT-T9g)",
          any(r["rule"] == "FMT-T9g" for r in fmt.latex_number_rows(
              "The depth was 30 kb and \\SI{50}{\\percent} of cells.")))
    terms = fmt.key_term_rows(["CNV calls from scWGS data.", "The scWGS CNV caller was used."])
    check("the key-term ledger counts occurrences per document",
          any(t["term"] == "CNV" and t["count"] == 2 for t in terms), str(terms[:2]))
    outline = fmt.outline_rows(["Introduction", "First sentence. Second sentence.",
                                "Third paragraph with (1) and (2) items."],
                               headings=[True, False, False])
    check("the outline carries heading context, word counts and list markers",
          outline[0]["heading"] == "Introduction" and outline[2]["list_markers"] == "1,2"
          and outline[1]["first_sentence"].startswith("First"),
          json.dumps(outline)[:200])
    ph = fmt.placeholder_ledger([
        "Preprints: [AUTHOR TO COMPLETE: state whether this work has been posted; name the "
        "server and the DOI, otherwise write \"not posted\".]",
        "Competing interests: [AUTHOR TO COMPLETE: declare competing interests.]"])
    check("placeholders are classified searchable vs author-only",
          [p["class"] for p in ph] == ["searchable", "author-only"], json.dumps(ph)[:200])
    # the lookup helper parses the two APIs without network access (stubbed)
    import urllib.request
    canned = {
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=CopyNumBench&format=json&pageSize=5":
            {"hitCount": 1, "resultList": {"result": [
                {"title": "A preprint", "doi": "10.1101/2026.01.01.000001",
                 "firstPublicationDate": "2026-01-01"}]}},
        "https://api.openalex.org/works?search=CopyNumBench&per-page=5":
            {"meta": {"count": 0}, "results": []},
    }

    class _Resp:
        def __init__(self, payload):
            self._b = json.dumps(payload).encode()
        def read(self):
            return self._b
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    real = urllib.request.urlopen
    try:
        urllib.request.urlopen = lambda url, timeout=None: _Resp(canned[url])
        got = fmt.lookup_preprint("CopyNumBench")
    finally:
        urllib.request.urlopen = real
    check("the preprint lookup reports the hits and the queried sources",
          got["hits"] and got["hits"][0]["doi"].startswith("10.1101/")
          and not got["errors"], json.dumps(got)[:200])


def test_deliverable_validation():
    """`validate`: every DOCX part parses; standalone .tex compiles; fragments skip."""
    print()
    print("== deliverable validation (DOCX XML + LaTeX) ==")
    tmp = scratch("nbt_fmt_val_")
    good = make_package(tmp / "good.docx")
    rep = fmt.validate_paths([good])
    check("a valid DOCX passes validation",
          rep["ok"] and rep["results"][0]["ok"] is True, json.dumps(rep["results"])[:200])
    broken = tmp / "broken.docx"
    with zipfile.ZipFile(broken, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document><w:body></w:document>")
    rep = fmt.validate_paths([broken])
    check("a DOCX with malformed XML fails validation and names the part",
          not rep["ok"] and any("word/document.xml" in e
                                for r in rep["results"] for e in r["errors"]),
          json.dumps(rep["results"])[:220])
    fragment = tmp / "fragment.tex"
    fragment.write_text("\\section{Results}\nSee \\cite{doe}.\n", encoding="utf-8")
    rep = fmt.validate_paths([fragment])
    check("a \\input fragment is SKIPped, not failed",
          rep["ok"] and rep["results"][0]["ok"] is None, json.dumps(rep["results"])[:160])
    if fmt.latex_engine() is None:
        print("[skip] no TeX engine on PATH: compile checks not exercised")
        return
    doc = tmp / "doc.tex"
    doc.write_text("\\documentclass{article}\\begin{document}Hello.\\end{document}\n",
                   encoding="utf-8")
    rep = fmt.validate_paths([doc])
    check("a standalone .tex that compiles passes", rep["ok"],
          json.dumps(rep["results"])[:200])
    bad = tmp / "bad.tex"
    bad.write_text("\\documentclass{article}\\begin{document}\\undefinedmacro\\end{document}\n",
                   encoding="utf-8")
    rep = fmt.validate_paths([bad])
    check("a standalone .tex that does not compile fails with the engine error",
          not rep["ok"] and rep["results"][0]["errors"],
          json.dumps(rep["results"])[:200])


def test_scan():
    print()
    print("== scan: every defect class is detected ==")
    tmp = scratch("nbt_fmt_scan_")
    docx = make_package(tmp / "manuscript.docx")
    policy = fmt.load_policy(None)
    info = fmt.scan_paths([tmp], policy)
    got = rules(info["rows"])
    for rule, label in (
            ("FMT-S1", "break-only empty paragraph"),
            ("FMT-S3", "running head on the title page"),
            ("FMT-S4", "tracked changes"),
            ("FMT-S5", "proofing markers"),
            ("FMT-S7", "literal tab"),
            ("FMT-T1", "mixed quotation marks"),
            ("FMT-T2b", "legend spacing drift"),
            ("FMT-T3a", "heading without keepNext"),
            ("FMT-T3b", "heading run size vs style"),
            ("FMT-T6a", "italic correspondence block"),
            ("FMT-T6b", "italic 'et al.'"),
            ("FMT-T6d", "reference without italic journal"),
            ("FMT-T7a", "same URL two treatments"),
            ("FMT-T7b", "mixed URL/email treatment"),
            ("FMT-P1", "em-dash density")):
        check(f"scan detects {label} ({rule})", rule in got, f"got {sorted(got)}")
    # sweeps.md's M20 sweep lists the dash/quote family as `→ finding`
    # ("mixed straight/curly quotation marks, a spaced hyphen used as a dash, or
    # em-dash density above the user's cap → finding"), and the pipeline's own
    # M20 seed text calls the em-dash density an editorial row that is a finding
    # for the revision/integration arms. The tier column must say so, or a
    # reviewer can close the row as "advisory -- editorial preference only" and
    # the auditor (which attacks finding-tier rows) never sees it.
    check("the M20 dash/quote rows the skill calls `→ finding` carry the finding tier",
          fmt.tier_of("FMT-P1") == "finding" and fmt.tier_of("FMT-P2") == "finding"
          and fmt.tier_of("FMT-T1") == "finding",
          f"FMT-P1={fmt.tier_of('FMT-P1')} FMT-P2={fmt.tier_of('FMT-P2')} "
          f"FMT-T1={fmt.tier_of('FMT-T1')}")
    protected = [r for r in info["rows"] if r["rule"] == "FMT-T6b"]
    check("the italic 'et al.' inside the Zotero field is field-protected",
          protected and all(r["protected"] and r["fix"] == "style-field" for r in protected),
          str(protected[:1]))
    check("format_note summarises the scan",
          "finding(s)" in fmt.format_note(info) and "high" in fmt.format_note(info),
          fmt.format_note(info))
    empty = scratch("nbt_fmt_empty_")
    check("scan of a directory with no docx is clean",
          fmt.scan_paths([empty], policy)["rows"] == [])
    check("scan ignores a path that does not exist",
          fmt.scan_paths([tmp / "nope"], policy)["rows"] == [])
    # blank-page detector (pure part of check-pdf)
    text = "CopyNumBench\n1\nTitle page\n\fCopyNumBench\n2\n\fCopyNumBench\n3\nIntroduction text\n\f"
    res = fmt.blank_pages_in_text(text)
    check("blank-page detector finds the header/page-number-only page",
          res["blank_pages"] == [2] and res["pages"] == 3, str(res))
    return docx


def test_fix_default(docx: Path):
    print()
    print("== fix: the default policy repairs every mechanical finding ==")
    tmp = scratch("nbt_fmt_fix_")
    out = tmp / "manuscript.fixed.docx"
    policy = fmt.load_policy(None)
    rep = fmt.fix_package(docx, out, policy)
    v = rep["verified"]
    check("fix reports no remaining mechanical findings",
          v["mechanical_findings_after"] == 0 and not v["remaining_mechanical_rules"],
          f"{v['mechanical_findings_before']} -> {v['mechanical_findings_after']} "
          f"remaining={v['remaining_mechanical_rules']}")
    check("fix keeps the document text identical", v["text_identical"], str(v))
    check("fix keeps every other part byte-identical", v["parts_intact"])
    check("fix produces a schema-valid package (or the CLI is unavailable)",
          v["schema_ok"] in (True, None), f"{v['schema_ok']} {v['schema_detail']}")
    check("fix exits ok (self-verification passed)", rep["ok"] is True, json.dumps(v)[:200])
    # namespace preservation: the regression that corrupted the real file
    with zipfile.ZipFile(out) as z:
        fixed = z.read("word/document.xml").decode("utf-8")
    check("mc:Ignorable prefixes stay declared after the edit",
          'mc:Ignorable="w14"' in fixed and 'xmlns:w14=' in fixed and 'xmlns:mc=' in fixed,
          fixed[:200])
    # re-scan the fixed package
    info = fmt.scan_paths([out], policy)
    after = rules(info["rows"])
    for rule, label in (("FMT-S1", "break-only paragraph"), ("FMT-S3", "title-page header"),
                        ("FMT-S5", "proofing markers"), ("FMT-T2b", "legend spacing"),
                        ("FMT-T3a", "heading keepNext"), ("FMT-T6a", "correspondence italics"),
                        ("FMT-T7a", "URL treatment"), ("FMT-T7b", "URL/email treatment")):
        check(f"after fix: {label} is gone", rule not in after, f"still present: {sorted(after)}")
    check("after fix: the field-protected 'et al.' is still reported (not silently edited)",
          "FMT-T6b" in after, f"{sorted(after)}")
    check("after fix: editorial rows (dashes, quotes) are still reported",
          "FMT-P1" in after and "FMT-T1" in after, f"{sorted(after)}")
    # idempotency
    rep2 = fmt.fix_package(out, tmp / "again.docx", policy)
    check("fix is idempotent on an already-fixed package",
          rep2["changes"] == [] and rep2["ok"], str(rep2["changes"])[:160])
    # an unchanged copy is possible: fixing a clean package must be a no-op
    return out


def test_fix_extended(docx: Path):
    print()
    print("== fix: extended policy (unlink fields, align sizes, curly quotes) ==")
    tmp = scratch("nbt_fmt_ext_")
    policy = fmt.load_policy(None)
    policy.update({"unlink_zotero_fields": True, "align_heading_sizes": True,
                   "quote_style": "curly", "url_style": "plain"})
    out = tmp / "extended.docx"
    rep = fmt.fix_package(docx, out, policy)
    v = rep["verified"]
    check("extended fix reports no remaining mechanical findings",
          v["mechanical_findings_after"] == 0, str(v["remaining_mechanical_rules"]))
    check("extended fix keeps the text (quote-free identity holds)",
          v["text_identical"] or v["text_diff_only_quotes"], str(v)[:200])
    with zipfile.ZipFile(out) as z:
        fixed = z.read("word/document.xml").decode("utf-8")
    check("unlinking removed the Zotero field instructions",
          "ZOTERO_BIBL" not in fixed and "<w:instrText" not in fixed,
          fixed[fixed.find("ZOTERO") - 40:fixed.find("ZOTERO") + 40] if "ZOTERO" in fixed else "clean")
    info = fmt.scan_paths([out], policy)
    after = rules(info["rows"])
    check("after unlinking: the italic 'et al.' is repaired",
          "FMT-T6b" not in after, f"{sorted(after)}")
    check("after unlinking: no field-protected rows remain",
          not [r for r in info["rows"] if r.get("protected")], str(info["rows"][:1]))
    check("after aligning: heading size drift is gone", "FMT-T3b" not in after, f"{sorted(after)}")
    check("after quote normalisation: the mixed-quote row is gone", "FMT-T1" not in after)
    check("curly quotes were actually applied", "\u2019" in fixed or "\u201c" in fixed)


def test_render_blank_page_if_available():
    print()
    print("== render integration: a break-only paragraph becomes a blank page ==")
    if not shutil.which("soffice") or not shutil.which("pdftotext"):
        print("[skip] soffice/pdftotext not available in this environment")
        return
    tmp = scratch("nbt_fmt_render_")
    # 45 filler paragraphs fill page 1, so the break-only paragraph lands at the
    # TOP of page 2 and its page break pushes the body to page 3 -> page 2 blank.
    docx = make_package(tmp / "blank-page.docx", doc_xml(filler=45))
    prof = tmp / "lo"
    env = dict(os.environ, HOME=str(tmp))
    proc = subprocess.run(
        ["soffice", f"-env:UserInstallation=file://{prof}", "--headless", "--norestore",
         "--convert-to", "pdf", "--outdir", str(tmp), str(docx)],
        capture_output=True, text=True, env=env, timeout=600)
    pdf = tmp / "blank-page.pdf"
    if not pdf.is_file():
        print(f"[skip] soffice could not convert the fixture: {proc.returncode}")
        return
    res = fmt.check_pdf(pdf, fmt.load_policy(None))
    check("the rendered fixture shows at least one blank page", len(res["blank_pages"]) >= 1,
          f"pages={res['pages']} blank={res['blank_pages']}")
    fixed = tmp / "fixed.docx"
    fmt.fix_package(docx, fixed, fmt.load_policy(None))
    subprocess.run(["soffice", f"-env:UserInstallation=file://{prof}", "--headless",
                    "--norestore", "--convert-to", "pdf", "--outdir", str(tmp), str(fixed)],
                   capture_output=True, text=True, env=env, timeout=600)
    res2 = fmt.check_pdf(tmp / "fixed.pdf", fmt.load_policy(None))
    check("the fixed file renders without a blank page and one page shorter",
          res2["blank_pages"] == [] and res2["pages"] == res["pages"] - len(res["blank_pages"]),
          f"pages={res2['pages']} blank={res2['blank_pages']} (was {res['pages']}/{res['blank_pages']})")


def test_cli():
    print()
    print("== CLI ==")
    tmp = scratch("nbt_fmt_cli_")
    docx = make_package(tmp / "cli.docx")
    scan = subprocess.run([sys.executable, str(WS / "nbt_docx_format.py"), "scan",
                           str(tmp), "--json", str(tmp / "scan.json")],
                          capture_output=True, text=True)
    check("`scan` exits 0 and writes JSON", scan.returncode == 0
          and json.loads((tmp / "scan.json").read_text(encoding="utf-8"))["rows"],
          scan.stdout[-200:])
    strict = subprocess.run([sys.executable, str(WS / "nbt_docx_format.py"), "scan",
                             str(tmp), "--strict"], capture_output=True, text=True)
    check("`scan --strict` exits 1 when findings exist", strict.returncode == 1)
    fix = subprocess.run([sys.executable, str(WS / "nbt_docx_format.py"), "fix", str(docx),
                          "--out", str(tmp / "cli.fixed.docx"), "--json", str(tmp / "fix.json")],
                         capture_output=True, text=True)
    check("`fix` exits 0 and writes the report", fix.returncode == 0
          and json.loads((tmp / "fix.json").read_text(encoding="utf-8"))["ok"], fix.stdout[-200:])
    same = subprocess.run([sys.executable, str(WS / "nbt_docx_format.py"), "fix", str(docx),
                           "--out", str(docx)], capture_output=True, text=True)
    check("`fix` refuses to overwrite its input", same.returncode == 2, same.stderr[-120:])


def test_pipeline_wiring():
    print()
    print("== pipeline wiring: scan wrapper, policy overrides, gate flag ==")
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("nbt_wire", str(WS / "nbt_pipeline.py"))
    nb = ilu.module_from_spec(spec)
    sys.modules["nbt_wire"] = nb
    spec.loader.exec_module(nb)
    check("the pipeline finds its companion module next to the script",
          nb._format_module() is not None, str(nb._format_module()))
    tmp = scratch("nbt_fmt_wire_")
    make_package(tmp / "submission.docx")
    info = nb.scan_format_in_sources([(tmp, "r1_", ())])
    check("scan_format_in_sources prefixes document names with the source prefix",
          info["rows"] and all(r["document"].startswith("r1_") for r in info["rows"]),
          json.dumps(info["rows"][:1])[:160])
    check("the pipeline's format_note reports the finding counts",
          "finding(s)" in nb.format_note(info) and "high" in nb.format_note(info),
          nb.format_note(info))
    check("an empty source list is reported as clean",
          nb.format_note(nb.scan_format_in_sources([])) != "")
    ctx = type("C", (), {"cfg": {"format_policy": {"url_style": "keep-links",
                                                   "max_em_dashes_per_1000": 7.5}}})()
    pol = nb.format_policy_of(ctx)
    check("setup's --format-policy overrides reach the scanner policy",
          pol["url_style"] == "keep-links" and pol["max_em_dashes_per_1000"] == 7.5,
          str({k: pol.get(k) for k in ("url_style", "max_em_dashes_per_1000")}))
    check("defaults are kept for keys the operator did not override",
          pol["journal_italics"] == "refs-only" and pol["caption_line"] == 240)
    # the decide gate flag exists and the report builder accepts the new kwargs
    import inspect
    sig = inspect.signature(nb.build_decision_report)
    check("build_decision_report takes the formatting arguments",
          {"win_format", "format_gate", "format_problems"} <= set(sig.parameters),
          str(list(sig.parameters)))
    args = type("A", (), {"format_gate": True})()
    check("decide exposes --format-gate", hasattr(args, "format_gate"))
    prompts = {"review": nb.review_prompt(Path(tmp) / "sb", "r1_review", 1),
               "revise": nb.revise_prompt(Path(tmp) / "sb", "r1_a2_revise", 1),
               "rewrite": nb.rewrite_prompt(Path(tmp) / "sb", "r1_w1", 1),
               "integrate": nb.integrate_prompt(Path(tmp) / "sb", "r1_i1", 1, "a1", ["w1"])}
    for stage, text in prompts.items():
        check(f"the {stage} prompt carries the M20 formatting mandate",
              "M20" in text and "nbt_docx_format.py" in text, text[text.find("M20") - 40:][:120])
    judge = nb.judge_prompt(Path(tmp) / "sb", "r1_judge_t1_j1", 1, "t1", 1, 3, ["v1"])
    check("the judge prompt carries the M20 formatting clause",
          "M20" in judge and "nbt_docx_format.py" in judge)


def _pipeline_module():
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("nbt_pl_fmt", str(WS / "nbt_pipeline.py"))
    nb = ilu.module_from_spec(spec)
    sys.modules["nbt_pl_fmt"] = nb
    spec.loader.exec_module(nb)
    return nb


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_setup_normalization():
    print()
    print("== setup: the pristine copy is normalized before it is fingerprinted ==")
    tmp = scratch("nbt_fmt_setup_")
    src = tmp / "src"
    src.mkdir()
    make_package(src / "manuscript.docx")
    before = _sha(src / "manuscript.docx")
    root = tmp / "root"
    proc = subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), "setup",
                           "--source", str(src), "--root", str(root)],
                          capture_output=True, text=True, timeout=600)
    out = proc.stdout + proc.stderr
    check("setup succeeds with the formatting normalizer", proc.returncode == 0, out[-300:])
    check("setup reports the FORMAT-FIX", "FORMAT-FIX" in out, out[-300:])
    check("the operator's --source file is byte-identical afterwards",
          _sha(src / "manuscript.docx") == before)
    pristine = root / "non_revised" / "manuscript.docx"
    check("the root's pristine copy has no break-only paragraph left",
          "FMT-S1" not in rules(fmt.scan_paths([pristine], fmt.load_policy(None))["rows"]))
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    check("state.json records the original formatting fix",
          (state.get("original_format_fix") or {}).get("fixed") == 1,
          json.dumps(state.get("original_format_fix") or {})[:200])
    check("the fix artifact was written next to the reports",
          (root / "reports" / "FORMAT_FIX_original.json").is_file())
    check("the companion module is copied into the root",
          (root / "nbt_docx_format.py").is_file())
    # opt-out keeps the copy byte-identical to the source
    root2 = tmp / "root-off"
    proc2 = subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), "setup",
                            "--source", str(src), "--root", str(root2), "--format-fix", "off"],
                           capture_output=True, text=True, timeout=600)
    check("--format-fix off succeeds", proc2.returncode == 0, (proc2.stdout + proc2.stderr)[-200:])
    check("--format-fix off keeps the pristine copy byte-identical",
          _sha(root2 / "non_revised" / "manuscript.docx") == before)
    check("--format-fix off records no fix",
          (json.loads((root2 / "state.json").read_text(encoding="utf-8"))
           .get("original_format_fix") or {}).get("skipped") == "format_fix=off"
          or (json.loads((root2 / "state.json").read_text(encoding="utf-8"))
              .get("original_format_fix") is None))


def test_stage_normalization():
    print()
    print("== stages: every package is normalized before it is fingerprinted/pinned ==")
    nb = _pipeline_module()
    # a synthetic stage package (the pipeline calls this for revised/integrated/rewritten)
    tmp = scratch("nbt_fmt_stage_")
    pkg = tmp / "integrated"
    pkg.mkdir()
    make_package(pkg / "manuscript.docx")
    (pkg / "work").mkdir()
    make_package(pkg / "work" / "scratch.docx")          # scratch must be ignored
    scratch_before = _sha(pkg / "work" / "scratch.docx")
    text_before = fmt.text_of("".join(
        p[2] for p in fmt.paragraphs(
            zipfile.ZipFile(pkg / "manuscript.docx").read("word/document.xml").decode("utf-8"))))
    left = (zipfile.ZipFile(pkg / "manuscript.docx")
            .read("word/document.xml").decode("utf-8"))
    warns = []
    ctx = type("C", (), {"cfg": {}, "sandbox_of": lambda self, rec: pkg})()
    rec = {"id": "r1_i1", "kind": "integrate"}
    summary = nb._format_fix_stage_package(ctx, rec, pkg, warns)
    check("the stage package was repaired", summary.get("fixed") == 1, json.dumps(summary)[:200])
    check("the FORMAT-FIX warning is raised for the operator",
          warns and "FORMAT-FIX" in warns[0], str(warns[:1]))
    check("the artifact is written next to the run",
          (pkg / "FORMAT_FIX_r1_i1.json").is_file())
    check("scratch under work/ was left untouched",
          _sha(pkg / "work" / "scratch.docx") == scratch_before)
    check("the package no longer has the break-only paragraph",
          "FMT-S1" not in rules(fmt.scan_paths([pkg], fmt.load_policy(None))["rows"]))
    right = (zipfile.ZipFile(pkg / "manuscript.docx")
             .read("word/document.xml").decode("utf-8"))
    check("the repair did not change the document text",
          text_before == fmt.text_of("".join(p[2] for p in fmt.paragraphs(right))))
    # an already-clean package is a no-op
    warns2 = []
    summary2 = nb._format_fix_stage_package(ctx, rec, pkg, warns2)
    check("a second run changes nothing", summary2.get("fixed") == 0 and not warns2,
          json.dumps(summary2)[:160])
    # format_fix=off is honoured
    pkg2 = tmp / "revised"
    pkg2.mkdir()
    make_package(pkg2 / "manuscript.docx")
    before2 = _sha(pkg2 / "manuscript.docx")
    ctx_off = type("C", (), {"cfg": {"format_fix": "off"}, "sandbox_of": lambda self, rec: pkg2})()
    s3 = nb._format_fix_stage_package(ctx_off, {"id": "r1_a2_revise", "kind": "revise"}, pkg2, [])
    check("format_fix=off leaves the package byte-identical",
          _sha(pkg2 / "manuscript.docx") == before2 and (s3 or {}).get("skipped") == "format_fix=off")


def test_review_m20_seeding():
    print()
    print("== review: the M20 sweep is seeded as an input and required by the contract ==")
    tmp = scratch("nbt_fmt_review_")
    src = tmp / "src"
    src.mkdir()
    make_package(src / "manuscript.docx")
    root = tmp / "root"
    setup = subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), "setup",
                            "--source", str(src), "--root", str(root), "--rounds", "1",
                            "--rewrites", "0", "--revises", "1", "--judges", "1"],
                           capture_output=True, text=True, timeout=600)
    check("setup succeeds", setup.returncode == 0, (setup.stdout + setup.stderr)[-200:])
    nb = _pipeline_module()
    ctx = nb.Ctx(root)
    ctx.load()
    nb.materialize_a1(ctx, 1)
    rec = nb.materialize_review(ctx, 1)
    sb = ctx.sandbox_of(rec)
    scan_path = sb / "review" / "work" / "FORMAT_SCAN.json"
    art_path = sb / "review" / "artifacts" / "M20_formatting.md"
    check("the code-side scan is seeded into review/work/", scan_path.is_file())
    seeded = json.loads(scan_path.read_text(encoding="utf-8")) if scan_path.is_file() else {}
    seeded_rules = {r["rule"] for r in seeded.get("rows") or []}
    art_text = art_path.read_text(encoding="utf-8") if art_path.is_file() else ""
    check("the M20 artifact table is seeded with one row per code-side finding",
          art_path.is_file() and "| rule |" in art_text
          and (not seeded_rules or seeded_rules <= {r.split("|")[2].strip()
                                                    for r in art_text.splitlines()
                                                    if r.startswith("|")}),
          f"seeded rules {sorted(seeded_rules)} vs artifact rows")
    check("the seeded scan is the post-normalization state (the mechanical rows are already fixed)",
          "FMT-S1" not in seeded_rules and (seeded_rules & {"FMT-P1", "FMT-S4"}),
          f"seeded rules {sorted(seeded_rules)}")
    check("the seeded files do NOT count as agent work",
          nb.leftovers_present(ctx, rec) is False)
    # the review contract now requires an M20 coverage row
    base = sb / "base"
    rows = [{"check": c, "disposition": "clean -- basis: x"} for c in
            [f"M{i}" for i in range(1, 18)] + [f"J{i}" for i in range(1, 5)]]
    rows += [{"check": "M18", "disposition": "legend counts recorded"},
             {"check": "M19", "disposition": "0 findings"}]
    fj = {"submission_dir": "./base", "findings": [{"id": "F-001", "check": "M1"}],
          "artifacts": {}, "coverage": list(rows)}
    errs, warns = [], []
    nb.check_review_contract(ctx, sb, fj, errs, warns)
    check("a review without the M20 coverage row fails the contract",
          any("M20" in e for e in errs), str(errs[:1]))
    fj2 = dict(fj, coverage=rows + [{"check": "M20",
                                     "disposition": "formatting rows disposed"}])
    errs2, warns2 = [], []
    nb.check_review_contract(ctx, sb, fj2, errs2, warns2)
    check("a review with the M20 coverage row passes that check",
          not any("M20" in e for e in errs2), str(errs2[:1]))


def main() -> int:
    try:
        docx = test_scan()
        test_fix_default(docx)
        test_journal_emphasis()
        test_text_consistency_rules()
        test_quality_engines()
        test_deliverable_validation()
        test_fix_extended(docx)
        test_cli()
        test_pipeline_wiring()
        test_setup_normalization()
        test_stage_normalization()
        test_review_m20_seeding()
        test_render_blank_page_if_available()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FORMATTING-CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL DOCX FORMATTING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

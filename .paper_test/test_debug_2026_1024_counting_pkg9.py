#!/usr/bin/env python3
"""Regressions for the 2026-10-24 debug run (findings C01-C09).

Each check reproduces one candidate from
``debug_runs/20261024-141221/01_find/findings`` on the current tree:

  * C01 -- the M19 no-heading branch honours ``counting.main_text.excludes``:
    it skips the excluded back matter and still counts a later included section;
  * C02 -- ``count_words.py`` normalizes ``_`` in a section kind like the
    pipeline does (script/pipeline parity);
  * C03 -- the M19 renderer names the back-matter exclusions instead of saying
    "nothing EXCLUDED" for a venue that leaves only back matter out;
  * C04 -- PKG-9 reads DOCX tables and body prose from the standard library, so
    the contradiction check runs when ``python-docx`` is absent;
  * C07 -- the M19 note names the span it actually counted, and the boundary
    heading after an excluded abstract is only skipped when the venue counts
    that section;
  * C08 -- the profile schema no longer claims ``counting.source``/``.note`` are
    rendered when no renderer reads them;
  * C09 -- a venue that excludes table captions has them subtracted by both
    counters.

``PAPER_WS`` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_debug_1024", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_debug_1024"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []
COUNTER = WS / "paper-skills" / "paper-review" / "scripts" / "count_words.py"


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    path = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(path)
    return path


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def main_row(payload):
    rows = [r for r in (payload or {}).get("rows") or [] if r["section"] == "main text"]
    return rows[0] if rows else None


def counter(manuscript: Path, *args: str):
    cmd = [sys.executable, str(COUNTER), str(manuscript),
           "--section", "main-text", "--json", *args]
    run = subprocess.run(cmd, capture_output=True, text=True)
    if run.returncode != 0:
        return None, run.stderr.strip() or run.stdout.strip()
    return json.loads(run.stdout), ""


def scan_row(folder: Path, profile=None):
    info = nb.scan_lengths_in_sources([(folder, "", ())], profile=profile)
    rows = [r for r in info["rows"] if r["section"] == "main text"]
    return rows[0] if rows else None


def make_docx(path: Path, prose, rows) -> Path:
    """A minimal but valid DOCX (stdlib only) with body paragraphs and a table."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    paras = "".join(
        f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(t)}</w:t></w:r></w:p>"
        for t in prose)
    table = ""
    if rows:
        table = "<w:tbl>" + "".join(
            "<w:tr>" + "".join(
                f"<w:tc><w:p><w:r><w:t xml:space=\"preserve\">{escape(c)}</w:t>"
                f"</w:r></w:p></w:tc>" for c in row) + "</w:tr>" for row in rows) + "</w:tbl>"
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{ns}"><w:body>{paras}{table}</w:body></w:document>')
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>')
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("word/document.xml", document)
    return path


# =====================================================================
# C01 -- the no-heading branch honours the venue's exclusions
# =====================================================================

def test_c01_no_heading_excludes():
    print()
    print("== C01: a no-heading Brief skips excluded back matter and counts References ==")
    brief = nb.load_venue_profile("nature-biotechnology", root=str(WS)) \
        .with_article_type("brief-communication")
    doc = ("A short title\n\nA. Author, B. Author\n\n"
           "The abstract states the finding in three sentences.\n\n"
           "The body states the result and its support.\n\n"
           "Acknowledgements\n\nWe thank our funders.\n\n"
           "References\n\n1. Ref one. 2. Ref two.\n")
    folder = scratch("c01_brief_")
    write(folder / "ms.md", doc)
    row = scan_row(folder, brief)
    payload, err = counter(folder / "ms.md",
                           "--venue-profile",
                           str(WS / "venue_profiles" / "nature-biotechnology.json"),
                           "--article-type", "brief-communication")
    srow = main_row(payload)
    check("C01 the pipeline skips Acknowledgements but counts the included References",
          row is not None and row["words"] == 29, f"{row} {err}")
    check("C01 the note no longer claims the whole document is counted",
          row is not None and "whole document" not in row["note"], str(row))
    check("C01 count_words.py returns the same span (parity)",
          srow is not None and row is not None and srow["words"] == row["words"],
          f"pipeline={row} script={srow} {err}")


# =====================================================================
# C02 -- underscore section kinds normalize like the pipeline
# =====================================================================

def test_c02_underscore_kind():
    print()
    print("== C02: a profile using figure_legends counts the same in both tools ==")
    doc = ("Title here\n\nAbstract\n\nabs words\n\nIntroduction\n\nbody words only\n\n"
           "Figure 1 | caption words one two\n\nMethods\n\nmethod words\n\n"
           "References\n\nref one two\n")
    data = {"id": "x", "article_types": [{
        "id": "default", "label": "Default",
        "length_limits": {"abstract": {"base": None, "relaxation": None},
                          "main_text": {"base": 10000, "relaxation": 1.0}},
        "captions": None,
        "counting": {"main_text": {"excludes": [
            "abstract", "methods", "references", "figure_legends"]}}}],
        "default_article_type": "default"}
    folder = scratch("c02_underscore_")
    write(folder / "ms.md", doc)
    write(folder / "p.json", json.dumps(data))
    prof = nb.VenueProfile(data, origin="test")
    row = scan_row(folder, prof)
    payload, err = counter(folder / "ms.md", "--venue-profile", str(folder / "p.json"))
    srow = main_row(payload)
    check("C02 the pipeline normalizes figure_legends and subtracts the caption",
          row is not None and row["words"] == 3, f"{row} {err}")
    check("C02 count_words.py applies the same convention", srow is not None
          and row is not None and srow["words"] == row["words"],
          f"pipeline={row} script={srow} {err}")


# =====================================================================
# C03 -- the renderer names back-matter exclusions
# =====================================================================

def test_c03_renderer_back_matter():
    print()
    print("== C03: the Brief renderer names the back matter it leaves out ==")
    brief = nb.load_venue_profile("nature-biotechnology", root=str(WS)) \
        .with_article_type("brief-communication")
    text = nb.main_text_counting_text(brief)
    check("C03 the renderer does not say 'nothing EXCLUDED'",
          "nothing EXCLUDED" not in text, text)
    check("C03 it names the excluded back matter",
          "acknowledgements" in text and "outside the count" in text, text)
    check("C03 it still says the abstract/references/legends are INSIDE the count",
          "INSIDE the count" in text and "references" in text, text)
    check("C03 the default Article text still names the four excluded sections",
          "the abstract, Methods, references and figure legends EXCLUDED"
          in nb.main_text_counting_text(nb.default_venue_profile()),
          nb.main_text_counting_text(nb.default_venue_profile()))


# =====================================================================
# C04 -- PKG-9 runs without python-docx
# =====================================================================

def test_c04_pkg9_stdlib_docx():
    print()
    print("== C04: PKG-9 reads a DOCX table/prose without python-docx ==")
    folder = scratch("c04_pkg9_")
    prose = [
        "To limit peak random-access memory, candidates whose NetMHCpan-predicted "
        "half-maximal inhibitory concentration (IC50) exceeds 10,000 nM are discarded.",
        "MMP_aff ranks candidates by the percentile rank of the MixMHCpred score "
        "against a length- and allotype-matched background of random peptides.",
    ]
    rows = [
        ["MMP_aff", "PWM-derived", "MixMHCpred_aff", "Affinity (IC50) percentile",
         "Percentile rank of the predicted IC50 of the pMHC pair (MixMHCpred)"],
        ["NMP_aff", "NN ensemble", "NetMHCpan_aff", "Affinity (IC50)",
         "Predicted IC50 of the pMHC pair (NetMHCpan)"],
    ]
    make_docx(folder / "mixed.docx", prose, rows)
    got = nb.affinity_definition_rows(folder)
    tools = {r["evidence"].split("for ", 1)[1].split(",", 1)[0].strip("'")
             for r in got if " for " in r["evidence"]}
    check("C04 PKG-9 flags the MixMHCpred IC50 claim without python-docx",
          any("MixMHCpred" in t for t in tools), str(got)[:240])
    check("C04 PKG-9 leaves the supported NetMHCpan row alone",
          not any("NetMHCpan" in t for t in tools), str(tools))
    check("C04 the contradiction scan carries the row",
          any(r.get("rule") == "PKG-9" for r in nb.package_contradiction_rows(folder)),
          str(nb.package_contradiction_rows(folder))[:240])


# =====================================================================
# C07 -- the note names the counted span; excluded boundary is not skipped
# =====================================================================

def test_c07_note_and_boundary():
    print()
    print("== C07: the note names the span, and an excluded boundary ends the count ==")
    lines = "Introduction\nMethods\nmethod words\nReferences\nref\n".splitlines()
    row = nb._length_rows_for_lines(lines, "ms.md")[-1]
    check("C07 an excluded Methods body is not counted",
          row["words"] == 0, str(row))
    check("C07 the note says the count starts after the main-text heading",
          "after the main-text heading" in row["note"]
          and "beginning of the document" not in row["note"], row["note"])

    lines2 = ("Abstract\nabs words here\nMethods\nmethod words\n"
              "References\nref\n").splitlines()
    row2 = nb._length_rows_for_lines(lines2, "ms.md")[-1]
    check("C07 an excluded heading directly after the abstract is not skipped",
          row2["words"] == 0, str(row2))

    folder = scratch("c07_note_")
    write(folder / "ms.md", "Introduction\nMethods\nmethod words\nReferences\nref\n")
    payload, err = counter(folder / "ms.md")
    srow = main_row(payload)
    check("C07 count_words.py agrees on the span and the note",
          srow is not None and srow["words"] == 0
          and "after the main-text heading" in srow["note"], f"{srow} {err}")


# =====================================================================
# C08 -- the profile schema tells the truth about source/note
# =====================================================================

def test_c08_schema_doc():
    print()
    print("== C08: the schema does not claim counting.source/.note are rendered ==")
    readme = (WS / "venue_profiles" / "README.md").read_text(encoding="utf-8")
    check("C08 the schema no longer says both are read by the M19 renderers",
          "both are read by the M19 renderers" not in readme)


# =====================================================================
# C09 -- table captions are a counting kind
# =====================================================================

def test_c09_table_captions():
    print()
    print("== C09: a venue that excludes table captions has them subtracted ==")
    fr = nb.load_venue_profile("frontiers-in-immunology", root=str(WS))
    doc = ("Abstract\n\nAbstract words.\n\nIntroduction\n\nBody words.\n\n"
           "Table 1 | table caption words that the venue excludes\n\n"
           "References\n\nref one\n")
    folder = scratch("c09_table_")
    write(folder / "ms.md", doc)
    row = scan_row(folder, fr)
    payload, err = counter(folder / "ms.md", "--venue-profile",
                           str(WS / "venue_profiles" / "frontiers-in-immunology.json"),
                           "--article-type", "original-research")
    srow = main_row(payload)
    check("C09 the profile declares table captions outside the count",
          "table-captions" in fr.main_text_excludes(), str(fr.main_text_excludes()))
    check("C09 the pipeline subtracts the table caption", row is not None
          and row["words"] == 2, f"{row} {err}")
    check("C09 count_words.py subtracts it too (parity)", srow is not None
          and row is not None and srow["words"] == row["words"],
          f"pipeline={row} script={srow} {err}")

    # The default/NBT Article convention does not exclude table captions: the
    # new kind is opt-in profile data, never a global behaviour change.
    nbt = nb.load_venue_profile("nature-biotechnology", root=str(WS))
    folder2 = scratch("c09_nbt_")
    write(folder2 / "ms.md", doc)
    row2 = scan_row(folder2, nbt)
    check("C09 a profile that does not exclude table captions still counts them",
          row2 is not None and row2["words"] == 12, str(row2))


def main() -> int:
    test_c01_no_heading_excludes()
    test_c02_underscore_kind()
    test_c03_renderer_back_matter()
    test_c04_pkg9_stdlib_docx()
    test_c07_note_and_boundary()
    test_c08_schema_doc()
    test_c09_table_captions()
    for path in TMPDIRS:
        shutil.rmtree(path, ignore_errors=True)
    print(f"\n{len(FAILS)} failed")
    for name in FAILS:
        print("  FAILED:", name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Regressions for the 2026-10-15 package-hygiene round.

The operator's two delivered packages (`cnb-30to31-1015-1812-669237d`,
`neohet-13to14-1015-1812-669237d`) carried, inside the directory the author
hands to the journal:

  * `figures/figS3.png:Zone.Identifier` -- a WSL/Windows "downloaded from the
    internet" alternate-data-stream stub, a 191-byte file whose NAME reads like
    a figure the submission does not contain;
  * a top-level `__pycache__/paper_docx_format.cpython-312.pyc` -- the side
    effect of RUNNING a helper script;
  * `code/README.md`, written by the revision session, narrating that session's
    finding ids and hand-off paths (`revised/MANUAL_STEPS.md`, `X-907`);
  * `word/_rels/settings.xml.rels` entries attaching the venue's own
    `*.dotx` by a `file:///C:\\Users\\<someone>\\OneDrive...` path.

The neohet root did not execute the fixed orchestrator at all: `state.json`
recorded the repository's CURRENT sha256 while the copy frozen beside it was
four commits older, so the fixes that would have removed three of the four were
not in the code that ran. This suite pins the four fixes:

  1. `is_non_shippable_name` = OS junk + bytecode cache + Word owner file, and
     `copy_into` never lets one into a corpus (a pin, a winner, a published
     package);
  2. `strip_non_shippable_files_in_dir` sweeps a package built before the filter
     existed, and never touches an evidence area (`raw_data/` is byte-frozen);
  3. `readme_internal_note_rows` / `hold_internal_readme_notes` recognise the
     session-written README and MOVE it out of the package (the operator keeps
     the text, the package stays clean), while both the author's own README --
     which carries the submitted-set declaration -- and a `README_RERUN.md`
     written for a reader who will run the code are left in place;
  4. `root_pipeline_staleness` reports a frozen bundle that no longer matches
     the sha256 its own state.json records.

Run:  python3 .paper_test/test_package_hygiene_2026_1015.py
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

from bundle_source_lib import copy_bundle
WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_hyg", str(WS / "paper_pipeline.py"))
pp = importlib.util.module_from_spec(spec)
sys.modules["paper_hyg"] = pp
spec.loader.exec_module(pp)
FMT = pp._format_module()

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def tmpdir(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=f"hyg_{prefix}_"))
    TMPDIRS.append(d)
    return d


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# The two texts are quoted from the delivered neohet package verbatim (the
# session note) and from its own README (the declaration the dropped file must
# NOT be confused with).
SESSION_NOTE = (
    "# code/ - no analysis-code revision was in scope for this run\n"
    "\n"
    "This directory is deliberately empty of revised code. The decision, with its evidence:\n"
    "\n"
    "* **No frozen finding asks for a code change.** The 31 effective findings of this round "
    "(17 `F-*`,\n"
    "  13 `X-*`, 1 `AU-*`) were all re-verified against the corpus;\n"
    "* **X-907** - the exact file, byte evidence and steps are in `revised/MANUAL_STEPS.md` "
    "(item 13).\n"
)
AUTHOR_README = (
    "# What will be submitted\n"
    "\n"
    "Only files whose names match the following Bash extglob pattern will be submitted:\n"
    "\n"
    "`neohetero-*-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f].@(docx|pdf)`\n"
    "or\n"
    "`figures/*.png`\n"
    "\n"
    "All other files will not be submitted.\n"
)
RERUN_README = (
    "# code/ - precision-recall companion\n"
    "\n"
    "## Why this code ships\n"
    "\n"
    "Every number is computed from the per-candidate tables shipped in "
    "`raw_data/hpep-v07.zip`.\n"
    "\n"
    "## Commands (in order)\n"
    "\n"
    "```bash\n"
    "python3 code/auprc_from_shipped_tables.py --zip raw_data/hpep-v07.zip\n"
    "```\n"
)


def make_package(root: Path) -> Path:
    pkg = root / "final_clean_version_demo"
    write(pkg / "paper-1-mainText-abc1234.docx", "not really a docx")
    write(pkg / "README.md", AUTHOR_README)
    write(pkg / "code" / "README.md", SESSION_NOTE)
    write(pkg / "code" / "README_RERUN.md", RERUN_README)
    write(pkg / "figures" / "FigureS3.png", "png")
    write(pkg / "figures" / "figS3.png:Zone.Identifier", "[ZoneTransfer]\nZoneId=3\n")
    write(pkg / "__pycache__" / "paper_docx_format.cpython-312.pyc", "bytecode")
    write(pkg / "~$paper-1-mainText-abc1234.docx", "lock")
    write(pkg / ".DS_Store", "index")
    write(pkg / "raw_data" / "hpep-v07.zip", "zip")
    write(pkg / "raw_data" / "note.bin:Zone.Identifier", "[ZoneTransfer]\n")
    return pkg


def test_name_classes():
    check("`figS3.png:Zone.Identifier` is non-shippable",
          pp.is_non_shippable_name("figS3.png:Zone.Identifier"))
    check("a `.pyc` bytecode cache is non-shippable",
          pp.is_non_shippable_name("paper_docx_format.cpython-312.pyc"))
    check("a Word owner file is non-shippable",
          pp.is_non_shippable_name("~$paper-1-mainText-abc1234.docx"))
    check("`.DS_Store` is non-shippable", pp.is_non_shippable_name(".DS_Store"))
    for keep in ("paper-1-mainText-abc1234.docx", "README.md", "README_RERUN.md",
                 "paper_pipeline.py", "FigureS3.png", "hpep-v07.zip", "notes.pyc.md"):
        check(f"`{keep}` is shippable", not pp.is_non_shippable_name(keep))


def test_identity_vs_delivery_split():
    """A CORPUS keeps junk bytes (identity first); only the DELIVERED copy strips.

    The order was measured on the real root: with the strip BEFORE the pin check,
    the neohet root compared 414 files against its pin's 415 and `decide`
    published nothing at all. The identity is therefore the tree AS IT WAS, and
    the never-ship rule is enforced on the delivered copy -- which is exactly
    what the second half of this test checks.
    """
    src = tmpdir("identity")
    (src / "figures").mkdir(parents=True)
    write(src / "doc.docx", "content")
    write(src / "figures" / "FigureS3.png", "png")
    clean = src.parent / "clean"
    pp.copy_into(src, clean)                      # the corpus copy, byte-for-byte
    check("a corpus copy carries the real files",
          (clean / "doc.docx").is_file() and (clean / "figures" / "FigureS3.png").is_file())
    write(src / "figures" / "figS3.png:Zone.Identifier", "stub")
    write(src / "__pycache__" / "mod.cpython-312.pyc", "bytecode")
    write(src / "~$doc.docx", "lock")
    junked = src.parent / "junked"
    pp.copy_into(src, junked)
    check("a corpus copy keeps the junk bytes (identity first)",
          (junked / "figures" / "figS3.png:Zone.Identifier").is_file()
          and (junked / "~$doc.docx").is_file()
          and (junked / "__pycache__" / "mod.cpython-312.pyc").is_file())
    check("so a corpus that gained junk is a DIFFERENT corpus identity",
          pp.manifest_digest(pp.corpus_dir_manifest(junked))
          != pp.manifest_digest(pp.corpus_dir_manifest(clean)))
    check("and the delivery sweep still removes it",
          "figures/figS3.png:Zone.Identifier" in
          pp.strip_non_shippable_files_in_dir(junked)["removed"]
          and not (junked / "~$doc.docx").exists())


def test_sweep():
    pkg = make_package(tmpdir("sweep"))
    res = pp.strip_non_shippable_files_in_dir(pkg)
    check("the sweep removes the figures/ stub",
          "figures/figS3.png:Zone.Identifier" in res["removed"], str(res))
    check("the sweep removes the top-level .pyc",
          "__pycache__/paper_docx_format.cpython-312.pyc" in res["removed"], str(res))
    check("the sweep removes the lock file and the desktop index",
          "~$paper-1-mainText-abc1234.docx" in res["removed"] and ".DS_Store" in res["removed"],
          str(res))
    check("the sweep NEVER touches an evidence area",
          "raw_data/note.bin:Zone.Identifier" in res["kept_in_evidence"]
          and (pkg / "raw_data" / "note.bin:Zone.Identifier").is_file(), str(res))
    check("the sweep keeps the manuscript documents",
          (pkg / "paper-1-mainText-abc1234.docx").is_file()
          and (pkg / "figures" / "FigureS3.png").is_file())


def test_readme_notes():
    pkg = make_package(tmpdir("readme"))
    rows = pp.readme_internal_note_rows(pkg / "code" / "README.md")
    check("the session note is recognised as an internal-note README", bool(rows), str(rows[:2]))
    check("the finding-ledger line is named with its line number",
          any(r["line"] == 5 for r in rows), str(rows))
    check("the author's own README is NOT an internal note",
          pp.readme_internal_note_rows(pkg / "README.md") == [])
    check("a README_RERUN.md for a reader is NOT an internal note",
          pp.readme_internal_note_rows(pkg / "code" / "README_RERUN.md") == [])
    dest = pkg.parent / "reports" / "readme_notes"
    held = pp.hold_internal_readme_notes(pkg, dest)
    check("the session note is HELD OUT of the package",
          [h["file"] for h in held] == ["code/README.md"], str(held))
    check("the held note is readable at its new home",
          (dest / "code" / "README.md").is_file())
    check("the package no longer carries it", not (pkg / "code" / "README.md").exists())
    check("the author's README stays (the submitted-set declaration travels)",
          (pkg / "README.md").is_file())
    check("README_RERUN.md stays (it documents how to run the code)",
          (pkg / "code" / "README_RERUN.md").is_file())


def test_patterns_do_not_overfire():
    """The new PKG-1 patterns must not turn ordinary manuscript prose into a row."""
    prose = (
        "Methods\n"
        "\n"
        "In this run we used the default seed. The pipeline (Fig. 1) carries the reads.\n"
        "All data were processed with the released code, and the findings of the study are "
        "reported in Table 2.\n"
        "Fig. 3 shows the F-1 hybrid; the F-2 generation was discarded.\n"
        "The effective findings were summarized as previously described [12].\n"
        "Antigen X-2 and AU-3 were measured separately.\n"
    )
    hits = [line for line in prose.splitlines()
            if any(pat.search(line) for _lab, pat in pp.INTERNAL_ARTIFACT_RES)]
    check("ordinary Methods prose is not flagged as internal material", not hits, str(hits))
    note_lines = [line for line in SESSION_NOTE.splitlines()
                  if any(pat.search(line) for _lab, pat in pp.INTERNAL_ARTIFACT_RES)]
    check("the session note IS flagged (every line that carries it)", len(note_lines) >= 3,
          str(note_lines))


def test_staleness_report():
    root = tmpdir("stale")
    copy_bundle(WS, root)
    (root / "state.json").write_text("{}", encoding="utf-8")

    class Ctx:
        pass

    ctx = Ctx()
    ctx.root = root
    frozen = pp.sha256_file(root / "paper_pipeline.py")
    ctx.state = {"pipeline": {"path": str(WS / "paper_pipeline.py"), "sha256": frozen}}
    st = pp.root_pipeline_staleness(ctx)
    check("a matching frozen bundle is not reported as differing",
          st["frozen_sha256"] == frozen and not st["frozen_differs"], str(st))
    check("its note does not claim a mismatch",
          "WARNING" not in pp.pipeline_snapshot_note(ctx),
          pp.pipeline_snapshot_note(ctx)[:120])

    other = "0" * 64
    ctx.state = {"pipeline": {"path": str(WS / "paper_pipeline.py"), "sha256": other}}
    st = pp.root_pipeline_staleness(ctx)
    check("a frozen bundle that contradicts the record IS reported",
          st["frozen_differs"] and bool(st["frozen_sha256"]), str(st))
    check("the note says the recorded fixes are not in effect",
          "WARNING" in pp.pipeline_snapshot_note(ctx),
          pp.pipeline_snapshot_note(ctx)[:160])


def test_comma_glue_rule():
    """FMT-G4: the missing space after a comma inside a list, and its neighbours.

    The strings are the two shapes that SHIPPED in the 2026-10-15 CNB package
    (the Reporting Summary's rendered version list and the supplementary .bib's
    keyword lists). The near misses are the ones the first cut of the rule
    actually produced on those corpora -- a citation key continuation
    (`2020a,b`), a citation range (`11,12`), a three-digit group (`684,498`)
    and an author's initials (`AL,Mehling`).
    """
    if FMT is None:
        check("paper_docx_format.py is importable", False, "module not found")
        return
    found = [
        "SAMtools 1.21, SafeMut 0.1.7, Ginkgo d7c7790, AneuFinder 1.34.0,copynumber 1.38.0,",
        "CHISEL 1.1.4, SCCNV v1.0.2, SeCNV 3c9047f, FLCNA 89902690,SCYN eeef200, scAbsolute v1.0.0,",
        "Python 3.12.8, STAR 2.7.5c, CaSpER 0.2.0,CONICSmat 0.0.0.1, CopyKAT 1.1.0,",
        "keywords = {Breast carcinoma,DNA aneuploidy,Molecular subtyping,Prognosis}",
    ]
    for s in found:
        check(f"FMT-G4 fires on {s[:46]!r}...", bool(FMT.comma_glue_rows(s)), s[:70])
    quiet = [
        "values 11,12 and 13,14; n = 684,498 cells; 1,234.5 (mean); Fig. 45,46",
        "see DNTR-seq21,39 and Ref. 24,29",
        "(Mallory et al., 2020a,b).",
        "Author AL,Mehling et al.",
        "SAMtools 1.21, SafeMut 0.1.7, HMMcopy 1.48.0",
        "We used the default,however some runs differed.",   # FMT-G3's shape, not this rule's
    ]
    for s in quiet:
        rows = FMT.comma_glue_rows(s)
        check(f"FMT-G4 stays quiet on {s[:46]!r}...", not rows, str(rows))
    check("FMT-G4 is a finding-tier rule",
          FMT.tier_of("FMT-G4") == "finding" and "FMT-G4" in FMT.FINDING_TIER_RULES)


def test_pdf_production_note_rule():
    """FMT-PDF7: a submitted PDF that opens by narrating its own production."""
    if FMT is None:
        check("paper_docx_format.py is importable", False, "module not found")
        return
    shipped = (
        "Nature Portfolio life-sciences reporting summary: a static rendering of the form's own "
        "questions and the author's own answers, because the submitted PDF is an Adobe LiveCycle "
        "form whose static page shows only a viewer placeholder. Sections the form leaves empty "
        "are omitted. Checklist rows show the form's own box labels."
    )
    check("the shipped CNB production note is recognised",
          bool(FMT.pdf_production_note(shipped)), FMT.pdf_production_note(shipped)[:90])
    for ok in ("Title\n\nAbstract\n\nThe tumor microenvironment ...",
               "Reporting Summary\n\nCorresponding author(s): A. Author\n\nStudy type: Life sciences"):
        check(f"an ordinary document opening is not flagged ({ok[:24]!r}...)",
              not FMT.pdf_production_note(ok))


def test_real_packages_are_clean_now():
    """The two delivered packages carry no finding from this round's rules.

    This is the end-to-end half of the suite: the checks above pin the RULES,
    this one pins the two packages the operator hands over. It reads as a
    failure until the fixes are applied (that is how the defects were confirmed
    in the first place), so it stays.
    """
    pkg = Path("/home/zhaoxiaofei/manuscript-postgrad-data/cnb-30to31-1015-1812-669237d/"
               "final_clean_version_cnb-30to31-1015-1812-669237d")
    if not pkg.is_dir():
        print("skip: the CNB delivered package is not readable here")
        return
    rows = pp.package_pdf_rows(pkg)
    check("CNB: the delivered Reporting Summary carries no production note",
          not any(r.get("rule") == "FMT-PDF7" for r in rows),
          str([(r.get("rule"), r.get("document")) for r in rows])[:200])
    summary = pkg / "cnb-31-nr-reporting-summary-filled-6d29898.pdf"
    if summary.is_file() and FMT is not None:
        try:
            import subprocess as _sp
            txt = _sp.run(["pdftotext", str(summary), "-"], capture_output=True,
                          text=True).stdout
        except OSError:
            txt = ""
        if txt:
            check("CNB: the Reporting Summary's version list is spaced",
                  not FMT.comma_glue_rows(txt), str(FMT.comma_glue_rows(txt))[:120])
    bib = pkg / "cnb-31-3-suppAll-0a68ba8.bib"
    if bib.is_file() and FMT is not None:
        check("CNB: the supplementary .bib carries no comma-glued list",
              not FMT.comma_glue_rows(bib.read_text(encoding="utf-8", errors="replace")),
              str(FMT.comma_glue_rows(bib.read_text(encoding="utf-8",
                                                      errors="replace")))[:120])


def test_delivered_packages_if_present():
    """When the operator's own two packages are on disk, check their invariants.

    Skipped (never silently passed) when the root is not readable from here --
    the suite must be runnable on any machine.
    """
    base = Path("/home/zhaoxiaofei/manuscript-postgrad-data")
    pkgs = {
        "cnb-30to31-1015-1812-669237d": "cnb-31-2-mainText-0a68ba8.docx",
        "neohet-13to14-1015-1812-669237d": "neohetero-15-2-mainText-FrontiersTemplate-zotero-eea7809.docx",
    }
    if not base.is_dir():
        print("skip: the operator's manuscript-postgrad-data tree is not readable here")
        return
    for root_name in pkgs:
        pkg = base / root_name / f"final_clean_version_{root_name}"
        if not pkg.is_dir():
            print(f"skip: {pkg} is not present")
            continue
        junk = [p.relative_to(pkg).as_posix() for p in pkg.rglob("*")
                if p.is_file() and pp.is_non_shippable_name(p.name)]
        check(f"{root_name}: the delivered package carries no OS junk / bytecode / lock file",
              not junk, str(junk))
        _decl = pp.declared_submission_set(pkg)
        submitted = sorted(_decl.get("files") or [])
        submitted_docs = [pkg / f for f in submitted
                          if Path(f).suffix.lower() in (".docx", ".tex")]
        attached = []
        for doc in submitted_docs:
            if doc.suffix.lower() != ".docx" or not doc.is_file():
                continue
            _mod = pp._format_module()
            rows = _mod.local_path_link_rows(doc) if hasattr(_mod, "local_path_link_rows") else []
            attached += [f"{doc.name}: {r[3]}" for r in rows]
        check(f"{root_name}: no submitted document attaches a template by a local path",
              not attached, str(attached[:2]))


def test_soft_breaks_are_separators():
    """A `w:br` is a SEPARATOR: reading across one invented a glued address.

    The 2026-10-15b neohet package renders

        * Correspondence:
        Zhen Xie
        zhenxie@tsinghua.edu.cn

    and the delivered status reported "the address is glued to the word before
    it" (the operator's audit re-found it). The break is a DELIMITER: both
    readers keep it as a newline, FMT-X2 folds it to a space for its checks, and
    a genuinely glued `Zhen Xiezhenxie@…` -- which is what the OLD package
    really has -- still reports.
    """
    import shutil
    import tempfile
    import zipfile
    d = Path(tempfile.mkdtemp(prefix="hyg_br_"))
    try:
        doc = d / "corr.docx"
        body = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p>"
            "<w:r><w:t>* Correspondence:</w:t></w:r>"
            "<w:r><w:br/><w:t>Zhen Xie</w:t></w:r>"
            "<w:r><w:br/><w:t>zhenxie@tsinghua.edu.cn</w:t></w:r>"
            "</w:p></w:body></w:document>")
        with zipfile.ZipFile(doc, "w") as z:
            z.writestr("word/document.xml", body)
        paras = pp._docx_paragraphs(doc)
        check("the pipeline reader keeps the soft break (a separator, not glue)",
              paras == ["* Correspondence:\nZhen Xie\nzhenxie@tsinghua.edu.cn"], str(paras))
        fmt = pp._format_module()
        if fmt is not None:
            check("the format module's text_of keeps it too",
                  fmt.text_of(body) == "* Correspondence:\nZhen Xie\nzhenxie@tsinghua.edu.cn",
                  repr(fmt.text_of(body)))
            check("FMT-X2 stays quiet on the separated block",
                  not fmt.correspondence_glue_rows(paras, [False]),
                  "reported a glued address")
            check("FMT-X2 still fires on a REAL glue",
                  bool(fmt.correspondence_glue_rows(
                      ["* Correspondence:Zhen Xiezhenxie@tsinghua.edu.cn"], [False])))
            check("the line-edge spaces are found around the break",
                  [(sp["start"], sp["end"]) for sp in fmt.hygiene_spans(
                      "<w:p><w:r><w:t xml:space=\"preserve\">* Correspondence: </w:t></w:r>"
                      "<w:r><w:br/></w:r><w:r><w:t xml:space=\"preserve\">Zhen Xie</w:t>"
                      "</w:r></w:p>") if sp["rule"] == "FMT-P4"] == [(17, 18)],
                  str(fmt.hygiene_spans(
                      "<w:p><w:r><w:t xml:space=\"preserve\">* Correspondence: </w:t></w:r>"
                      "<w:r><w:br/></w:r><w:r><w:t xml:space=\"preserve\">Zhen Xie</w:t>"
                      "</w:r></w:p>")))
            # ... and the writer must not delete the break with the space.
            para = ("<w:p><w:r><w:t xml:space=\"preserve\">* Correspondence: </w:t></w:r>"
                    "<w:r><w:br/></w:r><w:r><w:t xml:space=\"preserve\">Zhen Xie</w:t></w:r>"
                    "</w:p>")
            spans = [(sp["start"], sp["end"], sp["repl"])
                     for sp in fmt.hygiene_spans(para) if sp["fix"] == "mechanical"]
            fixed, _applied = fmt.rewrite_text_spans(para, spans)
            check("the writer keeps the break it deletes the space beside",
                  fixed.count("<w:br/>") == 1
                  and fmt.text_of(fixed) == "* Correspondence:\nZhen Xie",
                  repr(fmt.text_of(fixed)))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_producer_extraction_boundaries():
    """PKG-5's producer name: a section is not a tool, a sentence end is a stop."""
    import tempfile
    import shutil
    try:
        import docx                                              # noqa: PLC0415
    except Exception:                                            # noqa: BLE001
        print("skip: python-docx is not installed here")
        return
    d = Path(tempfile.mkdtemp(prefix="hyg_p5_"))
    try:
        # The 2026-10-15b shape: a legend that ends "... to the Results." must
        # not become a producer named "Results", and the tables' own (correct)
        # rows must not be reported either.
        doc = docx.Document()
        doc.add_paragraph("Figure S1. Heteroclitic peptides expand the pool. "
                          "The analysis is a proof of concept for the design-space "
                          "argument made in Results.")
        doc.add_paragraph("Figure S2. A candidate mechanism. Created with BioRender.com.")
        t = doc.add_table(rows=1, cols=2)
        t.cell(0, 0).text = "Matplotlib, seaborn (Figures 2, 4, S1 and S3)"
        t.cell(0, 1).text = "https://matplotlib.org"
        doc.save(str(d / "supp.docx"))
        rows = pp.display_provenance_rows(d)
        check("a section name is not a producer (no PKG-5 row)", not rows,
              str([(r.get("item"), r.get("reference")) for r in rows]))
        # The CONTROL: the same table against a legend that really does name a
        # different tool must still report.
        doc2 = docx.Document()
        doc2.add_paragraph("Figure S1. Schematic of the pipeline. Created with BioRender.com.")
        t2 = doc2.add_table(rows=1, cols=2)
        t2.cell(0, 0).text = "Matplotlib, seaborn (Figure S1)"
        t2.cell(0, 1).text = "https://matplotlib.org"
        doc2.save(str(d / "supp2.docx"))
        (d / "supp.docx").unlink()
        rows2 = pp.display_provenance_rows(d)
        check("the real contradiction is still reported",
              len(rows2) == 1 and "Matplotlib" in str(rows2[0].get("reference")),
              str([(r.get("item"), r.get("reference")) for r in rows2]))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_stale_pipeline_chain_warning():
    """A root that froze ANOTHER root's copy is warned about, the direct ones are not."""
    import shutil
    import tempfile
    import json
    d = Path(tempfile.mkdtemp(prefix="hyg_chain_"))
    try:
        repo_pipeline = WS / "paper_pipeline.py"
        # an "old root" holding a stale frozen copy, and a "new root" that froze
        # the old root's copy (the 2026-10-15b neohet shape)
        old_root = d / "old-root"
        old_root.mkdir()
        (old_root / "paper_pipeline.py").write_bytes(b"# stale pipeline\n")
        # The old root records the tree the operator MAINTAINS as its origin (that
        # is what a real root's state.json holds); its own frozen copy is stale.
        (old_root / "state.json").write_text(json.dumps(
            {"pipeline": {"path": str(repo_pipeline), "sha256": "0" * 64}}),
            encoding="utf-8")
        new_root = d / "new-root"
        new_root.mkdir()
        shutil.copy2(old_root / "paper_pipeline.py", new_root / "paper_pipeline.py")
        (new_root / "state.json").write_text(json.dumps(
            {"pipeline": {"path": str(old_root / "paper_pipeline.py"),
                          "sha256": pp.sha256_file(old_root / "paper_pipeline.py")}}),
            encoding="utf-8")

        class Ctx:                                                # noqa: D401
            pass

        ctx = Ctx()
        ctx.root = new_root
        ctx.state = json.loads((new_root / "state.json").read_text(encoding="utf-8"))
        st = pp.root_pipeline_staleness(ctx)
        check("the chain walk finds the maintained tree", bool(st.get("maintained_path")),
              str(st)[:160])
        check("a root that froze another root's copy is marked foreign",
              bool(st.get("frozen_foreign")), str(st)[:160])
        note = pp.pipeline_snapshot_note(ctx)
        check("and it is warned about", "WARNING" in note, note[:120])
        check("the maintained tree is the repo file", st.get("maintained_path") == str(repo_pipeline),
              str(st.get("maintained_path")))

        # A root whose origin IS the maintained tree is not "foreign": the
        # ordinary origin-moved-on sentence covers it instead.
        direct = d / "direct-root"
        direct.mkdir()
        shutil.copy2(repo_pipeline, direct / "paper_pipeline.py")
        (direct / "state.json").write_text(json.dumps(
            {"pipeline": {"path": str(repo_pipeline), "sha256": pp.sha256_file(repo_pipeline)}}),
            encoding="utf-8")
        ctx2 = Ctx()
        ctx2.root = direct
        ctx2.state = json.loads((direct / "state.json").read_text(encoding="utf-8"))
        st2 = pp.root_pipeline_staleness(ctx2)
        check("a root set up from the maintained tree is not foreign",
              not st2.get("frozen_foreign"), str(st2)[:140])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    test_name_classes()
    test_identity_vs_delivery_split()
    test_sweep()
    test_readme_notes()
    test_patterns_do_not_overfire()
    test_staleness_report()
    test_comma_glue_rule()
    test_pdf_production_note_rule()
    test_real_packages_are_clean_now()
    test_soft_breaks_are_separators()
    test_producer_extraction_boundaries()
    test_stale_pipeline_chain_warning()
    test_delivered_packages_if_present()
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)
    if FAILS:
        print(f"\n{len(FAILS)} FAILED: " + "; ".join(FAILS))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

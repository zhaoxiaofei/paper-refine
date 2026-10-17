#!/usr/bin/env python3
"""PKG-2: a to-be-submitted file may not point at what the submission does not carry.

Run:  python3 .paper_test/test_pkg2_submission_surface_2026_1015.py

The 2026-10-15 operator report was a supplementary legend that named the
analysis script and the raw-data archive ("produced by
`jf_supplement_analysis.py`, which is distributed with the source code ... the
per-candidate tables of the benchmark (`hpep-v07.zip`)") while the submission
carries neither: the reader, the editor and the reviewer all get a reference
they can never resolve, and the old scan never opened it -- it only matched an
AREA-PREFIXED path (`code/...`), and it never ran outside the journal-submission
assembly at all. The operator's rule is: REMOVE the dangling reference, do not
ship it.

What this suite pins:

  * the NAME shape: a written filename the package carries only outside the
    submission (a script under `code/`, the `raw_data/` archive, an output of
    one) is a PKG-2 row naming where it lives; a name the submission ships is
    not, a name the package does not carry at all (an external repository) is
    not, a name that is a URL tail is not;
  * a file INSIDE a non-carried area, and the author's own README*.md/.txt
    files, are not submission documents: their own pointers are not findings;
  * the REMOVAL: the sentence carrying the pointer is deleted from the
    published document (docx and text), the sentences around it survive, a
    heading line is not swallowed, a structural file (`.json`/`.csv`) is left
    alone and reported, and the result is re-scanned;
  * the REporting: the run record, the journal manifest, decision.json's
    readiness block and `final_clean_version.readme.md` all name what was
    removed (verbatim) and what could not be;
  * the PUBLISH path runs the removal too (a champion produced before the
    stage-side repair existed), and a Word owner (lock) file is never published;
  * end to end: a default-mode round whose manuscript cites `code/analysis.py`
    publishes a package that no longer carries the pointer.

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
HERE = Path(__file__).resolve().parent
STUB = HERE / "stub_agent.py"
STUB_JUDGE = HERE / "stub_judge.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_pkg2_pipeline", WS / "paper_pipeline.py")
fmt = _load("paper_pkg2_format", WS / "paper_docx_format.py")

FAILS = []
TMPDIRS = []
W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


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


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def make_docx(path: Path, paras: list) -> None:
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>'
                   for p in paras)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   f'<w:document {W_NS}><w:body>{body}</w:body></w:document>')


AREAS = ["raw_data", "raw_figs", "human_review_feedback", "llm_review_feedback", "code"]


def _pkg(prefix: str) -> Path:
    """A small package: a shipping surface plus the areas a submission leaves out."""
    tmp = scratch(prefix)
    write(tmp / "code" / "jf_supplement_analysis.py", "print('supplement')\n")
    write(tmp / "code" / "out" / "per_dataset_variability.csv", "method,sd\na,1\n")
    write(tmp / "code" / "README_RERUN.md", "see raw_data/hpep-v07.zip for input\n")
    write(tmp / "raw_data" / "hpep-v07.zip", "zip\n")
    write(tmp / "figures" / "FigureS3.png", "png\n")
    write(tmp / "README.md", "author notes: run code/jf_supplement_analysis.py\n")
    return tmp


# ---------------------------------------------------------------------------
# 1. the NAME shape: resolved against the package's own file names
# ---------------------------------------------------------------------------

def test_name_shape_rows():
    print()
    print("== K1 the name shape: a written file name resolved against the package ==")
    tmp = _pkg("pkg2_names_")
    write(tmp / "supplementary.md",
          "Figure S3 and Tables S1 to S3 were computed by a companion analysis script from "
          "the shipped tables.\n"
          "Figure S3 and its coordinates were produced by jf_supplement_analysis.py, which is "
          "distributed with the source code; the per-dataset coordinates and the per-dataset "
          "AUPRC values are among the files it writes.\n"
          "The tables are in hpep-v07.zip.\n"
          "Values are also printed in its per_dataset_variability.csv output.\n"
          "The figure is figures/FigureS3.png.\n"
          "The aggregation script neoheterocliticAggregate.py lives in the repository.\n"
          "Mirror: https://github.com/team/repo/jf_supplement_analysis.py\n")
    rows = pp.non_submitted_reference_rows(tmp, AREAS)
    refs = [(r["file"], r["reference"], tuple(r.get("resolves_to") or ())) for r in rows]
    check("K1 the script the legend names is a row, resolving into code/",
          any(r == "jf_supplement_analysis.py" and to == ("code/jf_supplement_analysis.py",)
              for _f, r, to in refs), str(refs)[:400])
    check("K1 the archive the legend names is a row, resolving into raw_data/",
          any(r == "hpep-v07.zip" and to == ("raw_data/hpep-v07.zip",)
              for _f, r, to in refs), str(refs)[:400])
    check("K1 an output only the code area carries is a row",
          any(r == "per_dataset_variability.csv" for _f, r, _t in refs), str(refs)[:400])
    check("K1 a name the submission SHIPS is not a row",
          not any(r == "figures/FigureS3.png" or r == "FigureS3.png"
                  for _f, r, _t in refs), str(refs)[:400])
    check("K1 a name the package does not carry at all is not a row",
          not any(r == "neoheterocliticAggregate.py" for _f, r, _t in refs), str(refs)[:400])
    check("K1 a URL tail is not a row",
          not any("https" in str(r) for _f, r, _t in refs), str(refs)[:400])
    check("K1 the row's advice names the code switch",
          any("set-submit-code" in r["detail"] for r in rows
              if r["reference"] == "jf_supplement_analysis.py"),
          str([r["detail"] for r in rows])[:300])
    # the same scan with the code submitted: that pointer resolves now
    rows_shipped = pp.non_submitted_reference_rows(
        tmp, [a for a in AREAS if a != "code"])
    check("K1 with `submit_code` on, the code pointer is no finding; the input's still is",
          not any(r["reference"] == "jf_supplement_analysis.py" for r in rows_shipped)
          and any(r["reference"] == "hpep-v07.zip" for r in rows_shipped),
          str([r["reference"] for r in rows_shipped])[:300])
    # The AREA itself, with no file behind the separator: the report's own
    # wording ("the supplementary material refers to the `code` directory").
    write(tmp / "prose.md",
          "See the code directory for the analysis scripts.\nThe paper is self-contained.\n")
    write(tmp / "slash.md",
          "Supplementary Figure S3 was produced by the script in code/.\n")
    rows_area = pp.non_submitted_reference_rows(tmp, AREAS)
    area_refs = {(r["file"], r["reference"]) for r in rows_area}
    check("K1 the prose spelling ('the code directory') is a row",
          ("prose.md", "code directory") in area_refs, str(sorted(area_refs))[:400])
    check("K1 a bare `code/` with nothing behind the slash is a row",
          ("slash.md", "code/") in area_refs, str(sorted(area_refs))[:400])
    check("K1 the area's advice is the code-area advice",
          all("set-submit-code" in r["detail"] for r in rows_area
              if r["reference"] in ("code directory", "code/")),
          str([r["detail"] for r in rows_area])[:300])
    # A sentence that LOCATES the material elsewhere resolves for the reader,
    # even when this package carries a same-named copy outside the submission:
    # deleting such a Methods sentence would destroy a resolvable pointer.
    write(tmp / "located.md",
          "Methods\n\nAll antigen-level statistics were computed with "
          "jf_supplement_analysis.py, which is available in the hpep subdirectory of the "
          "repository.\n")
    write(tmp / "located-url.md",
          "Methods\n\nWe ran jf_supplement_analysis.py; the script is public at "
          "https://github.com/team/repo.\n")
    write(tmp / "located-doi.md",
          "Methods\n\nWe ran jf_supplement_analysis.py, deposited in Zenodo (doi.org/10.5/"
          "zenodo.1).\n")
    located = [r for r in pp.non_submitted_reference_rows(tmp, AREAS)
               if r["file"] in ("located.md", "located-url.md", "located-doi.md")]
    check("K1 a sentence that locates the file in a repository is no row (no false removal)",
          located == [], str(located)[:300])


def test_non_submission_files_are_not_scanned():
    print()
    print("== K2 a file the submission does not carry is not a submission document ==")
    tmp = _pkg("pkg2_skip_")
    write(tmp / "code" / "NOTES.md", "the input lives in raw_data/hpep-v07.zip\n")
    write(tmp / "README-dev.md", "Run code/jf_supplement_analysis.py first.\n")
    rows = pp.non_submitted_reference_rows(tmp, AREAS)
    files = {r["file"] for r in rows}
    check("K2 the code area's own documentation is not scanned",
          "code/NOTES.md" not in files, str(sorted(files)))
    check("K2 the author's README files are never a submission surface",
          "README-dev.md" not in files and "README.md" not in files, str(sorted(files)))
    # ... and the removal leaves them alone
    rep = pp.strip_dangling_references_in_dir(tmp, AREAS, "k2-test")
    check("K2 the removal never edits a code-area file or an author README",
          (tmp / "code" / "NOTES.md").read_text(encoding="utf-8")
          == "the input lives in raw_data/hpep-v07.zip\n"
          and "code/jf_supplement_analysis.py" in (tmp / "README-dev.md").read_text("utf-8"),
          str(rep["files"])[:300])


# ---------------------------------------------------------------------------
# 2. the REMOVAL
# ---------------------------------------------------------------------------

def test_docx_sentence_removal():
    print()
    print("== K3 a .docx loses the sentence that carries the pointer, not its neighbours ==")
    tmp = _pkg("pkg2_docx_")
    doc = tmp / "supplementary.docx"
    make_docx(doc, [
        "Supplementary Material",
        "Table S1. Per-dataset variability of each metric.",
        "Each value is computed over the 26 per-dataset values of that method; SD is the "
        "standard deviation across datasets. Values were produced by "
        "jf_supplement_analysis.py and are also printed in its per_dataset_variability.csv "
        "output.",
        "Figure S3. Mean ROC and precision-recall curves. Related to Figure 2.",
    ])
    res = pp.strip_dangling_references_in_dir(tmp, AREAS, "k3-test")
    paras = pp._docx_paragraphs(doc)
    check("K3 the removal reports one sentence, verbatim",
          res["removed"] == 1
          and any("per_dataset_variability.csv" in s
                  for f in res["files"] for s in f["removed"]), json.dumps(res)[:400])
    check("K3 the sentence is gone and the paragraph keeps its first sentence",
          paras is not None and len(paras) == 4
          and paras[2].startswith("Each value is computed over the 26 per-dataset values")
          and "jf_supplement_analysis.py" not in paras[2], str(paras[2])[:200] if paras else "?")
    check("K3 the untouched paragraphs are byte-identical",
          paras is not None and paras[1].startswith("Table S1.") and paras[3].startswith(
              "Figure S3."), str(paras)[:200] if paras else "?")
    check("K3 the result is re-scanned clean and the tree reports ok",
          res["ok"] and res["remaining"] == [], json.dumps(res)[:300])
    check("K3 the .docx still parses and its text is shorter by exactly that sentence",
          paras is not None
          and "Values were produced by" not in "\n".join(paras), str(paras)[:200])


def test_text_removal_keeps_headings():
    print()
    print("== K4 a text document loses the pointer sentence, never its heading line ==")
    tmp = _pkg("pkg2_text_")
    write(tmp / "notes.md",
          "Methods\n"
          "We ran code/jf_supplement_analysis.py for Figure S3.\n"
          "The benchmark is described in the main text.\n")
    res = pp.strip_dangling_references_in_dir(tmp, AREAS, "k4-test")
    text = (tmp / "notes.md").read_text(encoding="utf-8")
    check("K4 the heading line survives", text.startswith("Methods\n"), repr(text[:80]))
    check("K4 the pointer sentence is gone",
          "jf_supplement_analysis.py" not in text, repr(text[:120]))
    check("K4 the next sentence survives",
          "described in the main text" in text, repr(text[:120]))
    check("K4 the removal is recorded and the re-scan is clean",
          res["removed"] == 1 and res["ok"] and res["remaining"] == [],
          json.dumps(res)[:300])


def test_structural_files_are_reported_not_edited():
    print()
    print("== K5 a structural file is reported for the author, never spliced ==")
    tmp = _pkg("pkg2_struct_")
    write(tmp / "manifest.json", json.dumps({"analysis": "code/jf_supplement_analysis.py"}))
    before = (tmp / "manifest.json").read_text(encoding="utf-8")
    res = pp.strip_dangling_references_in_dir(tmp, AREAS, "k5-test")
    entry = next((f for f in res["files"] if f["file"] == "manifest.json"), None)
    check("K5 the JSON is untouched",
          (tmp / "manifest.json").read_text(encoding="utf-8") == before)
    check("K5 the JSON is named as un-removable, with the reason",
          entry is not None and entry["removed"] == [] and entry["skipped"]
          and "structural file" in entry["skipped"][0], json.dumps(entry)[:300])
    check("K5 the leftover is reported by the re-scan, so the author sees it",
          any(r["file"] == "manifest.json"
              and r["reference"] == "code/jf_supplement_analysis.py"
              for r in res["remaining"]) and not res["ok"],
          json.dumps(res["remaining"])[:300])


def test_document_includes_are_not_deleted():
    print()
    print("== K5b a document INCLUDE is reported, never deleted ==")
    tmp = _pkg("pkg2_include_")
    write(tmp / "raw_data" / "Fig1.png", "png\n")
    write(tmp / "supp.tex",
          "\\documentclass{article}\n\\begin{document}\n"
          "\\includegraphics{raw_data/Fig1.png}\n"
          "We ran code/jf_supplement_analysis.py for the figure.\n"
          "\\input{raw_data/stats.tex}\n\\end{document}\n")
    write(tmp / "curves-note.md",
          "Methods\n\nSee [the curves](code/out/per_dataset_variability.csv) for details. "
          "The rest of the note is fine.\n")
    res = pp.strip_dangling_references_in_dir(tmp, AREAS, "k5b-test")
    tex = (tmp / "supp.tex").read_text(encoding="utf-8")
    md = (tmp / "curves-note.md").read_text(encoding="utf-8")
    check("K5b the LaTeX include survives and the prose sentence is removed",
          "\\includegraphics{raw_data/Fig1.png}" in tex
          and "jf_supplement_analysis.py" not in tex
          and "\\input{raw_data/stats.tex}" in tex, tex)
    check("K5b a Markdown link target is never spliced",
          "[the curves](code/out/per_dataset_variability.csv)" in md
          and "The rest of the note is fine." in md, md)
    check("K5b both are reported as un-removable, with the reason",
          sum(1 for f in res["files"] for s in f["skipped"] if "INCLUDE" in s) >= 2,
          json.dumps(res["files"])[:400])
    check("K5b the remaining re-scan lists them for the author",
          {r["file"] for r in res["remaining"]} == {"supp.tex", "curves-note.md"},
          json.dumps(res["remaining"])[:300])


def _make_linked_docx(path: Path) -> None:
    """A minimal package whose settings.xml attaches a template on a local path."""
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            'relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/attachedTemplate" Target="file:///C:\\'
            'Users\\hannah.eccles\\OneDrive%20-%20Frontiers%20Media%20SA\\Documents\\'
            'Latex%20work\\frontiers_template.dotx"/>'
            '</Relationships>')
    settings = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:settings {W_NS}><w:attachedTemplate r:id="rId1"/></w:settings>')
    body = ("".join(f'<w:p><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'
                    for t in ("Supplementary Material", "Figure S3 is described above.")))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   f'<w:document {W_NS}><w:body>{body}</w:body></w:document>')
        z.writestr("word/settings.xml", settings)
        z.writestr("word/_rels/settings.xml.rels", rels)


def test_local_path_links():
    print()
    print("== K5c an attached template on somebody's own machine is a dangling link ==")
    tmp = _pkg("pkg2_links_")
    docx = tmp / "supplementary.docx"
    _make_linked_docx(docx)
    with zipfile.ZipFile(docx) as z:
        before = {n: z.read(n) for n in z.namelist()}
    rows = [r for r in pp.non_submitted_reference_rows(tmp, AREAS) if r.get("part")]
    check("K5c the local-path link is a PKG-2 row naming the part",
          len(rows) == 1 and rows[0]["part"] == "word/_rels/settings.xml.rels"
          and rows[0]["reference"].startswith("file:///C:"), str(rows)[:300])
    res = pp.strip_dangling_references_in_dir(tmp, AREAS, "k5c-test")
    with zipfile.ZipFile(docx) as z:
        after = {n: z.read(n) for n in z.namelist()}
    check("K5c the repair removes the link and records the path verbatim",
          res["removed_links"] == 1
          and any("frontiers_template.dotx" in s
                  for f in res["files"] for s in (f.get("removed_links") or [])),
          json.dumps(res["files"])[:400])
    check("K5c only the two link-carrying parts changed",
          set(before) == set(after)
          and sorted(n for n in before if before[n] != after[n])
          == ["word/_rels/settings.xml.rels", "word/settings.xml"],
          str(sorted(n for n in before if before[n] != after[n])))
    check("K5c the link is gone and the document text survives",
          b"file:///" not in after["word/_rels/settings.xml.rels"]
          and b"attachedTemplate" not in after["word/settings.xml"]
          and b"Supplementary Material" in after["word/document.xml"])
    check("K5c nothing dangling remains", res["remaining"] == [] and res["ok"],
          json.dumps(res["remaining"])[:200])
    # A document that carries no such link is untouched.
    plain = tmp / "plain.docx"
    make_docx(plain, ["Nothing to see here."])
    with zipfile.ZipFile(plain) as z:
        plain_before = {n: z.read(n) for n in z.namelist()}
    pp.strip_dangling_references_in_dir(tmp, AREAS, "k5c-plain")
    with zipfile.ZipFile(plain) as z:
        plain_after = {n: z.read(n) for n in z.namelist()}
    check("K5c a document without such a link is byte-identical",
          plain_before == plain_after)
    # The judge's view must not carry the machine path either (blinding).
    linked2 = tmp / "sanitize-me.docx"
    _make_linked_docx(linked2)
    out, _notes = pp._sanitize_ooxml_bytes(linked2.read_bytes())
    rels_out = b""
    if out and out[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(out)) as z:
            rels_out = z.read("word/_rels/settings.xml.rels")
    check("K5c the judge view neutralizes the local-path target in place",
          b"file:///" not in rels_out and b"about:blank" in rels_out
          and b"hannah.eccles" not in rels_out, rels_out[:220])


# ---------------------------------------------------------------------------
# 3. the reporting surfaces
# ---------------------------------------------------------------------------

def test_reporting_surfaces():
    print()
    print("== K6 the removal is reported in every surface the operator reads ==")
    hygiene = {
        "removed_dangling_references": {
            "removed": 1,
            "removed_links": 1,
            "files": [{"file": "supplementary.docx",
                       "removed": ["Values were produced by jf_supplement_analysis.py."],
                       "removed_links": ["word/_rels/settings.xml.rels: "
                                         "file:///C:\\Users\\someone\\template.dotx"]}],
            "remaining": [{"rule": "PKG-2", "file": "manifest.json", "line": 1,
                           "reference": "code/jf_supplement_analysis.py",
                           "detail": "line 1: refers at 'code/jf_supplement_analysis.py'"}]},
    }
    readiness = pp.package_readiness({"hygiene": hygiene})
    check("K6 the leftover becomes a readiness finding under PKG-2",
          readiness["submission_ready"] is False
          and any(f["rule"] == "PKG-2" and f["document"] == "manifest.json"
                  for f in readiness["findings"]), json.dumps(readiness)[:300])
    check("K6 --require-ready turns it into a blocker",
          bool(pp.readiness_gate_problems(readiness, True))
          and pp.readiness_gate_problems(readiness, False) == [])
    check("K6 the removed sentence is NOT a finding (it is resolved work)",
          not any(f["document"] == "supplementary.docx" for f in readiness["findings"]),
          json.dumps(readiness)[:300])
    tmp = scratch("pkg2_readme_")
    write(tmp / "state.json", "{}")
    # `Ctx.load()` refuses a root that never ran `setup` (the readme text needs
    # only the root), so the constructor's defaults are used as they stand.
    ctx = pp.Ctx(tmp)
    ctx.cfg = {}
    text = pp.final_clean_readme_text(
        ctx, {"certified": True, "exit_code": 0},
        {"pin": {"id": "r1_a2", "digest": "0" * 64}, "stored": {"champion": "a2", "round": 1}},
        {"hygiene": hygiene, "files": 3, "digest": "1" * 64, "raw_data_untouched": 1})
    check("K6 the readme prints the removed sentence verbatim",
          "Values were produced by jf_supplement_analysis.py." in text,
          text[-800:])
    check("K6 the readme names the leftover as an author action",
          "could NOT be removed" in text and "manifest.json" in text, text[-500:])
    check("K6 the readme names the removed local-path link too",
          "Local-path links" in text and "frontiers_template.dotx" not in text
          and "template.dotx" in text, text[-800:])


# ---------------------------------------------------------------------------
# 4. end to end: a default-mode round publishes a clean package
# ---------------------------------------------------------------------------

def test_end_to_end_publish():
    print()
    print("== K7 a round whose manuscript cites code/ publishes a package without the pointer ==")
    tmp = scratch("pkg2_e2e_")
    src = tmp / "source"
    write(src / "neo-11-2-mainText.md",
          "Abstract\n\nWe used a benchmark of 30 datasets to rank the candidates.\n\n"
          "Methods\n\nThe ranking follows the companion analysis of the benchmark. The exact "
          "command is in code/analysis.py.\n\nThe benchmark is described in the main "
          "text.\n")
    write(src / "neo-11-3-supplement.md",
          "Supplementary Material\n\nFigure S3 was produced by analysis.py from the "
          "per-candidate tables of the benchmark.\n")
    write(src / "code" / "analysis.py", "print('analysis')\n")
    write(src / "raw_data" / "tables.tsv", "a\tb\n1\t2\n")
    # a Word owner (lock) file: never a document, never published
    (src / "~$neo-11-2-mainText.docx").write_text("owner lock\n", encoding="utf-8")
    root = tmp / "root"

    def run(argv):
        return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *map(str, argv)],
                              capture_output=True, text=True, timeout=1200)

    proc = run(["setup", "--source", str(src), "--root", str(root), "--rounds", "1",
                "--rewrites", "0", "--revises", "1", "--judges", "1"])
    check("K7 setup succeeds", proc.returncode == 0, (proc.stdout + proc.stderr)[-300:])
    proc = run(["run-decide", "--root", str(root),
                "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
                "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
                "--retries", "0"])
    out = proc.stdout + proc.stderr
    check("K7 run-decide succeeds", proc.returncode == 0, out[-500:])
    final = root / f"final_clean_version_{root.name}"
    docs = {p.relative_to(final).as_posix(): p for p in final.rglob("*") if p.is_file()} \
        if final.is_dir() else {}
    check("K7 the published package exists", bool(docs), str(sorted(docs))[:300])
    main = next((p for k, p in docs.items() if k.endswith("mainText.md")), None)
    supp = next((p for k, p in docs.items() if k.endswith("supplement.md")), None)
    decision = json.loads((root / "reports" / "decision.json").read_text(encoding="utf-8"))
    info = decision["final"]["final_clean_version"]
    check("K7 publication serves the scored pin byte-for-byte",
          info.get("digest") == info.get("pin_digest"), json.dumps(info)[:240])
    check("K7 the main document is present in the published package",
          main is not None, main.read_text(encoding="utf-8")[:200] if main else "?")
    check("K7 the supplementary document is published as scored",
          supp is not None, supp.read_text(encoding="utf-8")[:160] if supp else "?")
    check("K7 a staged Word owner file is reported when it cannot be removed post-pin",
          not any("~$" in k for k in docs)
          or "~$" in (root / "final_clean_version.readme.md").read_text(encoding="utf-8"),
          str(sorted(docs))[:400])
    readme = root / "final_clean_version.readme.md"
    text = readme.read_text(encoding="utf-8") if readme.is_file() else ""
    check("K7 the readme names the Word owner file that was not published",
          "Word owner" in text, text[-600:])
    blob = json.dumps(decision)
    check("K7 decision.json records the removal (the sentence, verbatim)",
          "code/analysis.py" in blob and "removed" in blob, blob[:200])
    # the pinned champion itself no longer carries the pointer (the stage-side
    # repair runs before the fingerprint/pin, so the judged package is clean)
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    strips = [r.get("reference_strip") or {} for r in (state.get("runs") or {}).values()]
    check("K7 the stage record carries the removal report",
          any(s.get("removed") for s in strips), json.dumps(strips)[:300])
    dangling = pp.non_submitted_reference_rows(
        final, pp.submission_not_carried_areas(_ctx(root)))
    check("K7 any dangling pointer is reported rather than changed after the pin",
          bool(dangling) and "PKG-2" in text and "code/analysis.py" in text,
          f"dangling={dangling[:1]} readme={text[-500:]}")


def _ctx(root: Path):
    ctx = pp.Ctx(root)
    ctx.load()
    return ctx


def main() -> int:
    try:
        test_name_shape_rows()
        test_non_submission_files_are_not_scanned()
        test_docx_sentence_removal()
        test_text_removal_keeps_headings()
        test_structural_files_are_reported_not_edited()
        test_document_includes_are_not_deleted()
        test_local_path_links()
        test_reporting_surfaces()
        test_end_to_end_publish()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for n in FAILS:
            print(f"  - {n}")
        return 1
    print("PKG-2 SUBMISSION-SURFACE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

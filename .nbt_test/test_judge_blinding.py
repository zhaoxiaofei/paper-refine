#!/usr/bin/env python3
"""Blind judging: a judge sees submission CONTENT only.

Run:  python3 .nbt_test/test_judge_blinding.py

The judge must not be able to score - or even perceive - file names, timestamps,
auxiliary/derived files, document metadata, or provenance (was this package
rewritten, integrated, revised, or is it the pristine original? which round?).
This suite attacks the judge-view transform with:

  * a Word-ish DOCX carrying every metadata class Word writes (core/app/custom
    properties, rsids, paraId/textId, proofing markers, last-rendered-page
    breaks, a thumbnail, customXml payloads, attachedTemplate, docVars,
    trackChanges, tracked insertions/deletions, formatting-change records and a
    comment with an author/date) plus the pipeline's own hand-off marker;
  * a second corpus that represents the SAME submission after the pipeline has
    processed it (revision token in the file name, the pipeline's formatter has
    re-zipped the docx, CHANGELOG/MANUAL_STEPS/REVISION_REPORT/revision_report/
    DIFF_LEDGER/VISUAL_CHECK present, work/ scratch, a *.tracked.docx auxiliary
    and a derived .aux/.log).

It then asserts that the two judge views expose the same *metadata* surface
(canonical zip, one timestamp/mode, no properties, no revision marks) and only
the placeholder names, and that the judge PROMPT/session carries no round, arm
or ordering hints.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_blind", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_blind"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"


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


CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Secret title</dc:title><dc:creator>Jane Author</dc:creator>
  <cp:lastModifiedBy>jane.laptop</cp:lastModifiedBy><cp:revision>37</cp:revision>
  <dcterms:created xsi:type="dcterms:W3CDTF">2026-01-02T03:04:05Z</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">2026-09-19T10:11:12Z</dcterms:modified>
</cp:coreProperties>"""

APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Application>Microsoft Office Word</Application><AppVersion>16.0000</AppVersion>
  <Company>University of Somewhere</Company><Manager>Prof. X</Manager>
  <TotalTime>42</TotalTime><Pages>7</Pages><Words>4321</Words><Characters>26000</Characters>
</Properties>"""

SETTINGS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="{W}">
  <w:proofState w:spelling="dirty" w:grammar="dirty"/>
  <w:attachedTemplate r:id="rId9"/>
  <w:trackChanges/>
  <w:docVars><w:docVar w:name="AuthorNote" w:val="reviewed by J.A."/></w:docVars>
  <w:rsids><w:rsidRoot w:val="00AB12CD"/><w:rsid w:val="00AB12CD"/></w:rsids>
</w:settings>"""

COMMENTS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="{W}">
  <w:comment w:id="1" w:author="Jane Author" w:initials="JA" w:date="2026-09-01T00:00:00Z">
    <w:p><w:r><w:t>Please check this number.</w:t></w:r></w:p>
  </w:comment>
</w:comments>"""


def document_xml(marker: str = "") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}" xmlns:w14="{W14}" w14:paraId="12345678" w14:textId="9ABCDEF0">
<w:body>
  <w:p w14:paraId="11111111" w:rsidR="00AB12CD" w:rsidRDefault="00AB12CD">
    <w:r><w:t>Results</w:t></w:r><w:proofErr w:type="spellStart"/><w:r><w:t>scWGS</w:t></w:r>
    <w:proofErr w:type="spellEnd"/><w:lastRenderedPageBreak/>
  </w:p>
  <w:p><w:ins w:id="1" w:author="Jane Author" w:date="2026-09-01T00:00:00Z">
      <w:r><w:t>An inserted sentence.</w:t></w:r></w:ins></w:p>
  <w:p><w:del w:id="2" w:author="Jane Author" w:date="2026-09-01T00:00:00Z">
      <w:r><w:delText>A deleted sentence.</w:delText></w:r></w:del></w:p>
  <w:p><w:r><w:rPr><w:rPrChange w:id="3" w:author="Jane Author"
         w:date="2026-09-01T00:00:00Z"><w:rPr><w:b/></w:rPr></w:rPrChange></w:rPr>
      <w:t>A sentence whose formatting changed.</w:t></w:r></w:p>
  <w:p><w:r><w:t xml:space="preserve">Accession: [AUTHOR TO COMPLETE: accession number]. {marker}</w:t></w:r></w:p>
</w:body></w:document>"""


def make_wordish_docx(path: Path, marker: str = "") -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("word/document.xml", document_xml(marker))
        z.writestr("word/settings.xml", SETTINGS)
        z.writestr("word/comments.xml", COMMENTS)
        z.writestr("docProps/core.xml", CORE)
        z.writestr("docProps/app.xml", APP)
        z.writestr("docProps/custom.xml",
                   '<?xml version="1.0"?><Properties><property name="AuthorEmail">'
                   'jane@example.org</property></Properties>')
        z.writestr("docProps/thumbnail.jpeg", b"\xff\xd8\xff\xe0stale-thumbnail-bytes")
        z.writestr("customXml/item1.xml",
                   '<?xml version="1.0"?><AuthorData who="Jane Author" machine="LAPTOP-7"/>')
        z.writestr("customXml/_rels/item1.xml.rels",
                   '<?xml version="1.0"?><Relationships/>')
    return path


def view_files(corpus: Path) -> list:
    return sorted([(p.relative_to(corpus).as_posix(), p) for p in corpus.rglob("*") if p.is_file()])


def build_view(corpus: Path, dst: Path, seed: str = "seed-A") -> None:
    """Exactly what build_judge_view does, without needing a pipeline root."""
    # The judge-view rules: auxiliaries, bookkeeping/report files and work/
    # scratch are never part of a view (same helper the pipeline uses).
    files = nb.corpus_dir_view_files(corpus)
    _dirs, file_map = nb._view_layout(files, 1, "tok", seed)
    dst.mkdir(parents=True, exist_ok=True)
    for rel, src in files:
        out = dst / file_map[rel]
        out.parent.mkdir(parents=True, exist_ok=True)
        data, _notes = nb._transform_view_file(rel, src, file_map)
        if data is None:
            shutil.copyfile(src, out)
        else:
            out.write_bytes(data)
    nb.stamp_tree(dst, 1700000000.0)


def docx_parts(payload: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_sanitizer_invariants():
    print()
    print("== the OOXML sanitizer removes every metadata class and canonicalizes the zip ==")
    tmp = scratch("nbt_blind_unit_")
    docx = make_wordish_docx(tmp / "wordish.docx")
    out, notes = nb._sanitize_ooxml_bytes(docx.read_bytes())
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        names = z.namelist()
        infos = z.infolist()
        parts = {n: z.read(n) for n in names}
    check("the archive is canonical (sorted names, one method/date/attr, no extra)",
          names == sorted(names)
          and len({i.compress_type for i in infos}) == 1
          and len({i.date_time for i in infos}) == 1
          and all(i.extra == b"" and i.comment == b"" for i in infos)
          and len({i.external_attr for i in infos}) == 1)
    check("the thumbnail part is dropped",
          not any(n.lower().startswith("docprops/thumbnail") for n in names))
    joined = b"".join(parts.values())
    for needle, label in ((b"rsid", "rsids"), (b"paraId", "paragraph ids"),
                          (b"textId", "text ids"), (b"proofErr", "proofing markers"),
                          (b"lastRenderedPageBreak", "rendered-page caches"),
                          (b"proofState", "proofing state"),
                          (b"attachedTemplate", "attached template"),
                          (b"docVars", "document variables"),
                          (b"trackChanges", "track-changes mode")):
        check(f"no {label} survive", needle not in joined)
    check("tracked changes are accepted (no w:ins / w:del / *PrChange)",
          b"<w:ins" not in joined and b"<w:del" not in joined and b"PrChange" not in joined
          and b"A deleted sentence" not in joined and b"An inserted sentence." in joined)
    core = parts["docProps/core.xml"].decode("utf-8", "replace")
    app = parts["docProps/app.xml"].decode("utf-8", "replace")
    check("core properties are neutralized (creator, machine, revision, dates)",
          "Jane Author" not in core and "jane.laptop" not in core
          and "<cp:revision>1</cp:revision>" in core and "2026-09-19T10:11:12Z" not in core)
    check("app properties and Word's cached statistics are neutralized",
          "Microsoft Office Word" not in app and "University of Somewhere" not in app
          and "<Words>0</Words>" in app and "<Pages>0</Pages>" in app)
    check("custom properties and customXml payloads are blanked",
          b"jane@example.org" not in joined and b"LAPTOP-7" not in joined
          and parts["customXml/item1.xml"] ==
          b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><root/>')
    comments = parts.get("word/comments.xml", b"").decode("utf-8", "replace")
    check("comment authors/dates are neutralized",
          "Jane Author" not in comments and 'w:author="author"' in comments)
    check("the pipeline hand-off marker prefix is neutralized, the payload kept",
          b"AUTHOR TO COMPLETE" not in joined and b"[TO BE COMPLETED: accession number]" in joined)
    again, _ = nb._sanitize_ooxml_bytes(out)
    check("the sanitizer is idempotent (the view is stable)",
          again == out, f"{len(again)} vs {len(out)} bytes")
    check("the sanitizer reports what it did", bool(notes), str(notes))


def test_two_provenance_views():
    print()
    print("== a Word-saved package and its pipeline-processed twin are indistinguishable "
          "apart from content ==")
    tmp = scratch("nbt_blind_pair_")
    orig = tmp / "orig"
    rev = tmp / "revised"
    orig.mkdir()
    rev.mkdir()

    def fill(corpus: Path, stem: str) -> None:
        """A real package: sources, their compiled twins and build debris."""
        make_wordish_docx(corpus / f"{stem}.docx")
        (corpus / f"{stem}.md").write_text("Abstract\n\nWe report.\n", encoding="utf-8")
        # derived twins -- a judge gets the source, not what it compiles to
        (corpus / f"{stem}.pdf").write_bytes(b"%PDF-1.4 compiled from the .docx\n")
        (corpus / f"{stem}.bib").write_text("@article{x, title={X}}\n", encoding="utf-8")
        (corpus / f"{stem}.bbl").write_text(
            "\\begin{thebibliography}{1}\n% compiled from the .bib\n", encoding="utf-8")
        # a reference list with NO editable source: the only copy of the content
        (corpus / "orphan.bbl").write_text(
            "\\begin{thebibliography}{1}\n% orphan: no .bib shipped\n", encoding="utf-8")
        # Word's "~$" owner file names its author; the .aux/.log name the build
        (corpus / f"~${stem}.docx").write_bytes(b"Jane Author\x00owner file")
        (corpus / f"{stem}.aux").write_text("\\relax\n", encoding="utf-8")
        (corpus / f"{stem}.log").write_text("build log\n", encoding="utf-8")

    fill(orig, "manuscript")
    # the "revised" twin: token-renamed file, the pipeline's own formatter re-zips
    # the docx, and every pipeline by-product is present
    fill(rev, "manuscript-abc1234")
    fmt = importlib.util.spec_from_file_location("fmt_blind", str(WS / "nbt_docx_format.py"))
    fmt_mod = importlib.util.module_from_spec(fmt)
    sys.modules["fmt_blind"] = fmt_mod
    fmt.loader.exec_module(fmt_mod)
    fixed = rev / "manuscript-abc1234.fixed.docx"
    fmt_mod.fix_package(rev / "manuscript-abc1234.docx", fixed, fmt_mod.load_policy(None))
    fixed.replace(rev / "manuscript-abc1234.docx")
    for name, text in (("CHANGELOG.md", "# changelog\n"), ("MANUAL_STEPS.md", "1. x\n"),
                       ("REVISION_REPORT.md", "# report\n"),
                       ("revision_report.json", "[{\"id\": \"F-001\"}]"),
                       ("DIFF_LEDGER.md", "# ledger\n"), ("VISUAL_CHECK.md", "not visually verified\n")):
        (rev / name).write_text(text, encoding="utf-8")
    (rev / "work").mkdir()
    (rev / "work" / "scratch.txt").write_text("scratch\n", encoding="utf-8")
    (rev / "manuscript-abc1234.tracked.docx").write_bytes((rev / "manuscript-abc1234.docx").read_bytes())
    v_orig, v_rev = tmp / "view_orig", tmp / "view_rev"
    build_view(orig, v_orig)
    build_view(rev, v_rev)
    names_o = sorted(p.relative_to(v_orig).as_posix() for p in v_orig.rglob("*") if p.is_file())
    names_r = sorted(p.relative_to(v_rev).as_posix() for p in v_rev.rglob("*") if p.is_file())
    check("both views contain ONLY submission content (bookkeeping/aux/derived/work stripped)",
          len(names_o) == 4 and len(names_r) == 4, f"{names_o} vs {names_r}")
    check("every view file name is an anonymous placeholder",
          all(re.fullmatch(r"(?:d\d+/)*f\d+\.[A-Za-z0-9]+", n) for n in names_o + names_r),
          f"{names_o} {names_r}")
    check("the two views have the same tree shape and file types",
          sorted(Path(n).suffix.lower() for n in names_o)
          == sorted(Path(n).suffix.lower() for n in names_r))
    keep_exts = sorted(Path(n).suffix.lower() for n in names_o)
    check("a view is handed the SOURCES (.md, .docx, .bib) and nothing compiled from them",
          keep_exts == [".bbl", ".bib", ".docx", ".md"]
          and sorted(Path(n).suffix.lower() for n in names_r) == keep_exts, str(keep_exts))
    # of the two .bbl files, the one whose .bib ships is dropped and the orphan
    # (the ONLY copy of that reference list) stays
    bbl = [p for p in v_orig.rglob("*") if p.suffix == ".bbl"]
    check("a compiled .bbl beside its .bib is dropped; the orphan .bbl stays",
          len(bbl) == 1 and b"orphan" in bbl[0].read_bytes(), str([p.name for p in bbl]))
    check("no compiled PDF, no build by-product (.aux/.log) and no Word owner file reaches a view",
          ".pdf" not in keep_exts and ".aux" not in keep_exts and ".log" not in keep_exts
          and not any(n.lower().endswith(nb.VIEW_STRIP_DERIVED_SUFFIXES)
                      for n in names_o + names_r)
          and not any(Path(n).stem.startswith("~$") for n in names_o + names_r),
          f"{names_o} {names_r}")
    mtimes_o = {p.stat().st_mtime for p in v_orig.rglob("*")}
    mtimes_r = {p.stat().st_mtime for p in v_rev.rglob("*")}
    modes = {p.stat().st_mode & 0o777 for p in [*v_orig.rglob("*"), *v_rev.rglob("*")] if p.is_file()}
    check("one timestamp per view, identical across views",
          len(mtimes_o) == 1 and mtimes_o == mtimes_r, f"{mtimes_o} vs {mtimes_r}")
    check("uniform file modes", modes == {0o644}, str(modes))
    docx_o = next(p for p in v_orig.rglob("*") if p.suffix == ".docx")
    docx_r = next(p for p in v_rev.rglob("*") if p.suffix == ".docx")
    parts_o, parts_r = docx_parts(docx_o.read_bytes()), docx_parts(docx_r.read_bytes())
    check("both sanitized docx expose the same canonical zip surface",
          sorted(parts_o) == sorted(parts_r), f"{sorted(parts_o)} vs {sorted(parts_r)}")
    joined = b"".join(parts_o.values()) + b"".join(parts_r.values())
    for needle, label in ((b"rsid", "rsids"), (b"paraId", "paraIds"), (b"textId", "textIds"),
                          (b"proofErr", "proofing markers"), (b"Jane Author", "author names"),
                          (b"LAPTOP", "machine names"), (b"University of Somewhere", "company"),
                          (b"AUTHOR TO COMPLETE", "pipeline markers"),
                          (b"<w:ins", "tracked insertions"), (b"<w:del", "tracked deletions")):
        check(f"no {label} in either view", needle not in joined)
    check("the revision token from the revised file name appears nowhere",
          b"abc1234" not in joined
          and not any("abc1234" in n for n in names_o + names_r))


def test_judge_prompt_and_ids():
    print()
    print("== the judge prompt and session ids carry no round/arm/ordering hints ==")
    rid = nb.rid_judge(2, "tok9", 3)
    check("a judge run id has no round prefix", rid == "judge_tok9_j3" and "r2" not in rid, rid)
    prompt = nb.judge_prompt(Path("/tmp/x"), rid, 2, "tok9", 3, 3, ["v1", "v2"])
    # Provenance vocabulary the judge must never learn from its own prompt. (The
    # words "base"/"original"/"pristine" stay: `original/` is the documented
    # regression anchor every judge is given, and "base numbers" refers to the
    # journal's length limits -- neither identifies the target's history.)
    forbidden = {
        r"\bround\b": "the word 'round'",
        r"\barm\b": "the word 'arm'",
        r"\brewrite\b": "the word 'rewrite'",
        r"\brevised\b": "the word 'revised'",
        r"\brevision\b": "the word 'revision' (as a stage)",
        r"\bintegration\b": "the word 'integration'",
        r"\bmerge\b": "the word 'merge'",
        r"\bchampion\b": "the word 'champion'",
        r"\b(?:a1|a2|w1|i1)\b": "an arm id",
        r"\br\d+_judge": "a round-prefixed run id",
        r"CHANGELOG": "a bookkeeping file name",
        r"MANUAL_STEPS": "a bookkeeping file name",
        r"REVISION_REPORT": "a bookkeeping file name",
        r"DIFF_LEDGER": "a bookkeeping file name",
        r"AUTHOR TO COMPLETE": "the pipeline's own marker token",
    }
    for pat, label in forbidden.items():
        hits = re.findall(pat, prompt, re.I)
        check(f"the judge prompt contains no {label}",
              not hits, f"{len(hits)} hit(s): {hits[:3]}")
    check("the judge prompt states the blinding rule",
          "BLINDING RULE" in prompt and "no ordering, age or origin information" in prompt)
    check("the judge prompt uses the provenance-neutral placeholder rule",
          "PLACEHOLDER TEXT IN A PACKAGE" in prompt)
    check("the scores.json template no longer asks for a round",
          '"round"' not in prompt and '"run_id": "judge_tok9_j3"' in prompt)
    # the sheet contract: a missing round is accepted, a wrong one is not
    ok_sheet = {"run_id": rid, "target_id": "tok9", "judge_index": 3,
                "comparisons": [{"opponent_label": "v1", "score": 1, "basis": "correctness",
                                 "resolved": [], "introduced": [],
                                 "reason": "target states the number more precisely than v1"},
                                {"opponent_label": "v2", "score": 0, "basis": "none",
                                 "resolved": [], "introduced": [],
                                 "reason": "no material difference against v2 here"}]}
    rec = {"id": rid, "kind": "judge", "round": 2, "target_id": "tok9", "judge_index": 3,
           "label_map": {"v1": "a2", "v2": "w1"}}
    errs, warns = nb.validate_judge_sheet(dict(ok_sheet), rec)
    check("a judge sheet WITHOUT a round field is accepted",
          not [e for e in errs if "round" in e], str(errs[:2]))
    # A judge cannot know the round (it is never told one), so a sheet that
    # invents one must not cost a 30-minute session: it is a note, not a failure.
    errs2, warns2 = nb.validate_judge_sheet(dict(ok_sheet, round=1), rec)
    check("a judge sheet with an invented round is a warning, not a failure",
          not any("round" in e for e in errs2) and any("round" in w for w in warns2),
          f"{errs2[:2]} / {warns2[:2]}")
    errs3 = []
    nb._marker_checks(rec, {"stage": "judge", "status": "complete", "run_id": rid}, "judge",
                      errs3, [])
    check("a completion marker without a round is accepted", errs3 == [], str(errs3))
    errs4, warns4 = [], []
    nb._marker_checks(rec, {"stage": "judge", "status": "complete", "run_id": rid, "round": 1},
                      "judge", errs4, warns4)
    check("a completion marker with an invented round is a warning, not a failure",
          errs4 == [] and any("round" in w for w in warns4), f"{errs4} / {warns4[:1]}")


def test_derived_output_rule():
    print()
    print("== a view is handed the SOURCES, not what can be compiled from them ==")
    check("a .bbl beside its .bib is excluded (the .bib is the source)",
          nb._is_view_excluded_file("refs.bbl", ["refs.bib", "refs.bbl"]))
    check("a .bbl with NO .bib shipped stays (only copy of the reference list)",
          not nb._is_view_excluded_file("refs.bbl", ["refs.bbl", "manuscript.md"]))
    check("a PDF beside its .docx is excluded",
          nb._is_view_excluded_file("manuscript.pdf", ["manuscript.docx", "manuscript.pdf"]))
    check("a PDF beside its .tex is excluded (version tokens ignored)",
          nb._is_view_excluded_file("supp-4f3a9c1.pdf", ["supp-b.tex", "supp-4f3a9c1.pdf"]))
    check("a figure PDF with no editable source stays",
          not nb._is_view_excluded_file("Fig1.pdf", ["Fig1.png", "data.tsv"]))
    check("a .txt beside a figure PDF is not a source/derived pair",
          not nb._is_view_excluded_file("Fig1.pdf", ["Fig1.txt"]))
    check("the build by-products stay excluded next to their sources",
          all(nb._is_view_excluded_file(n, [n, "manuscript.tex"])
              for n in ("manuscript.aux", "manuscript.log", "manuscript.synctex.gz",
                        "manuscript.toc", "~$manuscript.docx")))


def main() -> int:
    try:
        test_sanitizer_invariants()
        test_derived_output_rule()
        test_two_provenance_views()
        test_judge_prompt_and_ids()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} JUDGE-BLINDING CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL JUDGE-BLINDING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

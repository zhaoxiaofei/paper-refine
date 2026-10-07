#!/usr/bin/env python3
"""Regressions pinned from the 2026-10-08 adversarial gap audits.

The audits (`audit_data/2026-1008-0144-adversary-audit-4c5f756/`) were triaged
candidate by candidate; each check below FAILS on the tree they reviewed:

  A1  the judge-view sanitizer unwrapped only the OUTER `w:ins` of a nested
      insertion (Word writes those), so the inner revision mark survived in a
      "view is the accepted document" artifact;
  A2  the sanitizer dropped `docProps/thumbnail.*` but left the package
      relationship (and any `[Content_Types].xml` Override) pointing at the
      removed part -- a dangling OPC reference, which is what makes Word offer
      "unreadable content"/repair;
  A3  the stage LaTeX validation compared the WHOLE package against the input,
      so one already-broken sibling file pardoned a break the stage introduced
      in a document that compiled before (the function's own docstring promises
      the per-document rule);
  A4  `extract_citations.py` enumerated no `\\cite` key at all: a LaTeX
      submission reported "0 call-outs ... Orphans: none | Uncited: none" for a
      manuscript that cites throughout;
  A5  `paper_docx_format.NUMBER_RE` read `1.2e-4` as the two numbers `1` and
      `4`, so the author's p-value never reached the M30 numbers ledger and two
      values nobody wrote did;
  A6  the M30 seed tokenised a shipped header as ONE token, so `Age_years`
      never overlapped the sentence's "age"/"years" and the column that
      produced the written value was reported as absent from the corpus.

Run:  python3 .paper_test/test_adversary_gaps_2026_1008.py
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import posixpath
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("adv_pipeline", str(WS / "paper_pipeline.py"))
PP = importlib.util.module_from_spec(spec)
sys.modules["adv_pipeline"] = PP
spec.loader.exec_module(PP)
fspec = importlib.util.spec_from_file_location("adv_fmt", str(WS / "paper_docx_format.py"))
FMT = importlib.util.module_from_spec(fspec)
sys.modules["adv_fmt"] = FMT
fspec.loader.exec_module(FMT)

SCRIPTS = WS / "paper-skills/paper-review/scripts"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
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


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


# A valid-enough minimal package: content types, the package relationships (with
# Word's own thumbnail relationship), the thumbnail part and the body.
CONTENT_TYPES = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="jpeg" ContentType="image/jpeg"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/thumbnail.jpeg" ContentType="image/jpeg"/>
</Types>"""
PKG_RELS = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail" Target="docProps/thumbnail.jpeg"/>
</Relationships>"""
CORE = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>Jane Author</dc:creator><cp:lastModifiedBy>Jane Author</cp:lastModifiedBy></cp:coreProperties>"""
# A part's own relationships live in `<dir>/_rels/<name>.rels` and resolve
# their targets INSIDE `<dir>`: this one's `../docProps/thumbnail.jpeg` names
# the part the sanitizer removes.
DOC_RELS = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../docProps/thumbnail.jpeg"/>
</Relationships>"""


def make_package(path: Path, document: bytes) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", PKG_RELS)
        z.writestr("docProps/core.xml", CORE)
        z.writestr("docProps/thumbnail.jpeg", b"\xff\xd8\xff\xe0stale-render")
        z.writestr("word/document.xml", document)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
    return path


def body(paragraph: str) -> bytes:
    return f'<w:document xmlns:w="{W}"><w:body><w:p>{paragraph}</w:p></w:body></w:document>'.encode()


def sanitized(path: Path):
    data, notes = PP._sanitize_ooxml_bytes(path.read_bytes())
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return data, notes, {n: z.read(n) for n in z.namelist()}


def dangling_pointers(parts: dict) -> list:
    """Every internal `.rels` Target and `[Content_Types].xml` Override without a part."""
    names = set(parts)
    bad = []
    for name, payload in parts.items():
        if not name.endswith(".rels"):
            continue
        # A `.rels` target resolves against the rels part's own directory:
        # `_rels/.rels` is package-absolute, `word/_rels/document.xml.rels`
        # resolves inside `word/` (the same rule the sanitizer prunes by).
        base = name.rpartition("_rels/")[0]
        for rel in ET.fromstring(payload):
            if rel.get("TargetMode") == "External":
                continue
            target = posixpath.normpath(posixpath.join(base, rel.get("Target") or "")).lstrip("/")
            if target and target not in names:
                bad.append(f"{name} -> {target}")
    ct = parts.get("[Content_Types].xml")
    if ct is not None:
        for el in ET.fromstring(ct):
            if el.tag.endswith("Override"):
                part = (el.get("PartName") or "").lstrip("/")
                if part and part not in names:
                    bad.append(f"[Content_Types].xml Override -> {part}")
    return bad


def test_nested_revision_marks_are_accepted():
    print("\n== A1 the judge view is the accepted document, nested revisions included ==")
    tmp = scratch("adv_nested_ins_")
    nested = body('<w:ins w:id="1" w:author="A"><w:r><w:t>outer</w:t></w:r>'
                  '<w:ins w:id="2" w:author="B"><w:r><w:t>inner</w:t></w:r></w:ins></w:ins>'
                  '<w:r><w:t> tail</w:t></w:r>')
    doc = make_package(tmp / "nested.docx", nested)
    data, notes, parts = sanitized(doc)
    xml = parts["word/document.xml"]
    check("A1 no revision mark survives the nested unwrap",
          b"<w:ins" not in xml and b"</w:ins>" not in xml, xml.decode()[:220])
    check("A1 the accepted text of every revision is kept",
          b"outer" in xml and b"inner" in xml and b" tail" in xml, xml.decode()[:220])
    check("A1 the sanitized document is well-formed XML",
          ET.fromstring(xml) is not None)
    check("A1 the sanitizer still reports what it did", bool(notes), str(notes))
    again, _notes2 = PP._sanitize_ooxml_bytes(data)
    check("A1 the sanitizer stays idempotent", again == data,
          f"{len(again)} vs {len(data)} bytes")


def test_dropped_thumbnail_leaves_no_pointer():
    print("\n== A2 a removed part takes its relationships and Overrides with it ==")
    tmp = scratch("adv_thumbnail_")
    doc = make_package(tmp / "thumb.docx",
                       body('<w:ins w:id="1" w:author="A"><w:r><w:t>hello</w:t></w:r></w:ins>'))
    data, notes, parts = sanitized(doc)
    check("A2 the thumbnail part is dropped",
          not any(n.lower().startswith("docprops/thumbnail") for n in parts))
    check("A2 no dangling relationship / content-type Override is left",
          dangling_pointers(parts) == [], dangling_pointers(parts))
    check("A2 the content-type Default for the dropped part's extension stays",
          b'Extension="jpeg"' in parts["[Content_Types].xml"],
          parts["[Content_Types].xml"].decode()[:200])
    check("A2 the sanitizer names the pointer it pruned", bool(notes), str(notes))
    base_dir_fn = getattr(PP, "_rels_part_base_dir", None)
    check("A2 a nested rels part resolves its target inside its own directory",
          base_dir_fn is not None
          and base_dir_fn("word/_rels/document.xml.rels") == "word/",
          base_dir_fn("word/_rels/document.xml.rels") if base_dir_fn else "no such helper")
    nested = parts.get("word/_rels/document.xml.rels", b"")
    check("A2 the nested rels part is sanitized too (nothing points at the removed part)",
          bool(nested) and b"thumbnail" not in nested, nested.decode()[:200])
    out = tmp / "thumb.sanitized.docx"
    out.write_bytes(data)
    rep = FMT.validate_docx_parts(out)
    check("A2 the sanitized package still validates as a DOCX",
          rep["ok"] is True, json.dumps(rep)[:220])
    if shutil.which("docx"):
        check("A2 the OOXML schema checker accepts the sanitized package",
              rep.get("schema_ok") is not False, json.dumps(rep)[:220])


def test_new_latex_break_is_not_pardoned_by_a_broken_sibling():
    print("\n== A3 the LaTeX validation pairs per file, not per package ==")
    if FMT.latex_engine() is None:
        print("[skip] no TeX engine on PATH: the compile pairing is not exercised")
        return
    tmp = scratch("adv_tex_")
    inp, out = tmp / "in", tmp / "out"
    inp.mkdir()
    out.mkdir()
    broken = "\\documentclass{article}\n\\begin{document}\nAuthor break: \\undefinedmacro\n\\end{document}\n"
    good = "\\documentclass{article}\n\\begin{document}\nCompiles fine.\n\\end{document}\n"
    newly_broken = ("\\documentclass{article}\n\\begin{document}\n"
                    "A break this stage introduced: \\begin{itemize}\n\\end{document}\n")
    (inp / "broken.tex").write_text(broken, encoding="utf-8")
    (inp / "ok.tex").write_text(good, encoding="utf-8")
    (out / "broken.tex").write_text(broken, encoding="utf-8")
    (out / "ok.tex").write_text(newly_broken, encoding="utf-8")
    errs, warns = [], []
    PP._validate_stage_package(None, {}, out, inp, errs, warns)
    check("A3 a NEW break in a document that compiled FAILS the attempt",
          any("ok.tex" in e for e in errs), f"errs={errs}")
    check("A3 the already-broken sibling is reported, not failed",
          any("broken.tex" in w for w in warns) and not any("broken.tex" in e for e in errs),
          f"warns={warns}")
    errs2, warns2 = [], []
    PP._validate_stage_package(None, {}, inp, inp, errs2, warns2)
    check("A3 an inherited break (same file, unchanged) stays a warning",
          not errs2 and bool(warns2), f"errs={errs2} warns={warns2}")

    # The stage's own version token is part of the name (`...-supp-b.tex` ->
    # `...-supp-c.tex`): a renamed document is the SAME document, so an
    # inherited break there is a warning too -- and a NEW break under a rename
    # still fails.
    inp2, out2 = tmp / "in2", tmp / "out2"
    inp2.mkdir()
    out2.mkdir()
    (inp2 / "cnb-11-3-supp-b.tex").write_text(broken, encoding="utf-8")
    (out2 / "cnb-11-3-supp-c.tex").write_text(broken, encoding="utf-8")
    errs3, warns3 = [], []
    PP._validate_stage_package(None, {}, out2, inp2, errs3, warns3)
    check("A3 a version-token rename still pairs with the same document",
          not errs3 and any("supp-c.tex" in w for w in warns3),
          f"errs={errs3} warns={warns3}")
    (inp2 / "cnb-11-3-supp-b.tex").write_text(good, encoding="utf-8")
    errs4, warns4 = [], []
    PP._validate_stage_package(None, {}, out2, inp2, errs4, warns4)
    check("A3 a NEW break under a version-token rename still fails the attempt",
          any("supp-c.tex" in e for e in errs4), f"errs={errs4}")


CIT_TEX = r"""\documentclass{article}
\begin{document}
Known \cite{known}, missing \citep[see][p. 4]{ghost2020}, pair \textcite{known,ghost2020}.
% a commented-out \cite{commented}
\begin{verbatim}
\cite{verbatimkey}
\end{verbatim}
\nocite{silent}
\begin{thebibliography}{9}
\bibitem{known} K. Known. 2019.
\bibitem{never} N. Never. 2018.
\end{thebibliography}
\end{document}
"""


def run_citation_sweep(submission: Path, work: Path, out: Path) -> dict:
    subprocess.run([sys.executable, str(SCRIPTS / "convert_corpus.py"),
                    "--submission", str(submission), "--work", str(work)],
                   capture_output=True, text=True, check=True)
    proc = subprocess.run([sys.executable, str(SCRIPTS / "extract_citations.py"),
                           "--work", str(work), "--out", str(out)],
                          capture_output=True, text=True)
    art = (out / "artifacts/M2_citations.json")
    data = json.loads(art.read_text(encoding="utf-8")) if art.is_file() else {}
    return {"rc": proc.returncode, "stdout": proc.stdout,
            "md": (out / "artifacts/M2_citations.md").read_text(encoding="utf-8")
            if (out / "artifacts/M2_citations.md").is_file() else "",
            "json": data}


def test_latex_citations_are_enumerated():
    print("\n== A4 LaTeX \\cite keys enter M2 (they used to be invisible) ==")
    tmp = scratch("adv_cite_")
    sub = tmp / "sub"
    sub.mkdir()
    (sub / "paper.tex").write_text(CIT_TEX, encoding="utf-8")
    res = run_citation_sweep(sub, tmp / "work", tmp / "out")
    m2 = res["json"]
    check("A4 the sweep exits 0", res["rc"] == 0, res["stdout"][:200])
    keys = [(c["file"], c["key"]) for c in m2.get("tex_callouts", [])]
    check("A4 one row per \\cite KEY (including a multi-key \\cite)",
          sorted(k for _f, k in keys) == ["ghost2020", "ghost2020", "known", "known"],
          str(keys))
    check("A4 a commented-out \\cite is not a call-out",
          "commented" not in [k for _f, k in keys], str(keys))
    check("A4 a \\cite inside verbatim is not a call-out",
          "verbatimkey" not in [k for _f, k in keys], str(keys))
    check("A4 \\nocite is cited, but not an in-text call-out",
          "silent" not in [k for _f, k in keys]
          and m2.get("tex_nocite_keys", {}).get("paper.tex.txt") == ["silent"],
          json.dumps(m2.get("tex_nocite_keys")))
    check("A4 an orphan \\cite key is reported",
          m2.get("tex_orphan_keys") == ["ghost2020", "silent"]
          and m2.get("tex_orphan_keys_by_file", {}).get("paper.tex.txt") ==
          ["ghost2020", "silent"], json.dumps(m2.get("tex_orphan_keys")))
    check("A4 an uncited \\bibitem is reported",
          m2.get("tex_uncited_keys") == ["never"], json.dumps(m2.get("tex_uncited_keys")))
    check("A4 \\bibitem entries are enumerated as reference entries",
          sorted(b["key"] for b in m2.get("tex_bibitem_entries", [])) == ["known", "never"],
          json.dumps(m2.get("tex_bibitem_entries")))
    check("A4 the artifact prints the LaTeX key space",
          "LaTeX key space" in res["md"] and "LaTeX orphan keys" in res["md"])
    check("A4 a cited \\bibitem is not reported uncited",
          "known" not in (m2.get("tex_uncited_keys") or []))

    # A .tex that cites but ships no list at all: `unable`, never a clean "none".
    sub2 = tmp / "sub2"
    sub2.mkdir()
    (sub2 / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nSee \\cite{nolist2020}.\n"
        "\\end{document}\n", encoding="utf-8")
    res2 = run_citation_sweep(sub2, tmp / "work2", tmp / "out2")
    check("A4 \\cite with no list in the corpus is UNRESOLVED, not clean",
          res2["json"].get("tex_unresolved") is True
          and "UNRESOLVED" in res2["md"]
          and "unable" in res2["md"], res2["stdout"][:220])


def test_scientific_notation_is_one_number():
    print("\n== A5 an exponent belongs to the number ==")
    rows = FMT.number_ledger(["The effect was significant (p = 1.2e-4, n = 12)."])
    numbers = [r["number"] for r in rows]
    check("A5 1.2e-4 is one token, not 1 and 4",
          "1.2e-4" in numbers and "1" not in numbers and "4" not in numbers, str(numbers))
    check("A5 the other numbers of the sentence still land",
          numbers.count("12") == 1, str(numbers))
    check("A5 FMT-T9h ignores an exponent (it is not a separator case)",
          [r["rule"] for r in FMT.number_format_rows(
              ["1,234 samples and 12,345 cells at a threshold of 1.2e-4"])] == [],
          str(FMT.number_format_rows(["1,234 samples and 12,345 cells at 1.2e-4"])))
    check("A5 a genuine separator mix is still reported",
          any(r["rule"] == "FMT-T9h" for r in FMT.number_format_rows(
              ["1,234 samples and 12345 cells"])),
          str(FMT.number_format_rows(["1,234 samples and 12345 cells"])))
    check("A5 a decimal with a separator is still a separator case",
          [r["rule"] for r in FMT.number_format_rows(
              ["The cohort had 1,234.5 cells and 56789 counts"])] == ["FMT-T9h"],
          str(FMT.number_format_rows(["The cohort had 1,234.5 cells and 56789 counts"])))


def test_snake_case_headers_reach_the_m30_seed():
    print("\n== A6 a shipped header's own nouns are tokens (Age_years ~ age) ==")
    header_tokens = getattr(FMT, "_m30_header_tokens", None)
    if header_tokens is None:
        check("A6 a header tokeniser exists", False,
              "paper_docx_format has no _m30_header_tokens")
        return
    check("A6 a header splits on underscores and camelCase",
          header_tokens("Age_years") >= {"age", "years"}
          and header_tokens("nSamples") >= {"samples"},
          str(sorted(header_tokens("Age_years"))))
    rows = [{"document": "main.txt", "number": "64", "unit": "years",
             "sentence": "The mean age was 64 years.", "source": "",
             "document_paragraph": 3, "kind": "abstract"}]
    seeded = FMT.hierarchy_seed_rows(
        rows, [("supp.csv", "Age_years,Sex\n64,M\n54,F\n70,F\n")], limit=10)
    producers = [r["candidate producer"] for r in seeded]
    check("A6 the Age_years column is the candidate producer, not 'no column matches'",
          producers == ["supp.csv:Age_years"], str(producers))
    check("A6 the seed check cites the column's own values",
          "matches a cell in column 'Age_years'" in seeded[0]["seed check"],
          seeded[0]["seed check"])


def main() -> int:
    try:
        test_nested_revision_marks_are_accepted()
        test_dropped_thumbnail_leaves_no_pointer()
        test_new_latex_break_is_not_pardoned_by_a_broken_sibling()
        test_latex_citations_are_enumerated()
        test_scientific_notation_is_one_number()
        test_snake_case_headers_reach_the_m30_seed()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL 2026-10-08 ADVERSARY-GAP CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

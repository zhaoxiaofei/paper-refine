#!/usr/bin/env python3
"""Regression checks for the 2026-11-04 verify-fixes repair round.

Each check below pins one issue from
`debug_runs/20261104-230041/04_verify_fixes/review_findings.json`
(R01-R10) and failed on the tree the read-only reviewer inspected.

Run:

    python3 .paper_test/test_repair_fixes_20261104.py
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []
TMPDIRS = []

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("repair20261104_pp", "paper_pipeline.py")
cc = load("repair20261104_cc", "paper-skills/paper-review/scripts/convert_corpus.py")
ec = load("repair20261104_ec", "paper-skills/paper-review/scripts/extract_citations.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(p)
    return p


def zip_bytes(parts: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, payload in parts.items():
            z.writestr(name, payload)
    return buf.getvalue()


def _extract(files: dict) -> dict:
    d = scratch("repair_cit_")
    work = d / "work"
    (work / "corpus").mkdir(parents=True)
    for name, text in files.items():
        (work / "corpus" / name).write_text(text, encoding="utf-8")
    old = sys.argv
    sys.argv = ["extract_citations.py", "--work", str(work), "--out", str(d / "out")]
    try:
        ec.main()
    finally:
        sys.argv = old
    return json.loads((d / "out" / "artifacts" / "M2_citations.json").read_text())


def _docx_to_text(xml_body: str) -> tuple:
    d = scratch("repair_docx_")
    p = d / "x.docx"
    p.write_bytes(zip_bytes({"word/document.xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="' + WORD_NS + '"><w:body>' + xml_body
        + "</w:body></w:document>").encode()}))
    return cc.docx_to_text(str(p))


# ---------------------------------------------------------------------------
def test_r01() -> None:
    print("\n== R01: repair authorization bound to the quoted occurrence ==")
    d = scratch("repair_r01_")
    (d / "pre").mkdir()
    (d / "cur").mkdir()
    (d / "pre" / "m.md").write_text("A = 10 and B = 10\n")
    (d / "cur" / "m.md").write_text("A = 20 and B = 20\n")
    check("R01 a bare repeated value cannot authorize a second edit",
          pp._repair_spans_cover(d / "pre", d / "cur", "m.md",
                                 [("10", "20")]) is not None)
    (d / "cur" / "m.md").write_text("A = 20 and B = 10\n")
    check("R01 one quoted edit among repeated values still passes",
          pp._repair_spans_cover(d / "pre", d / "cur", "m.md",
                                 [("10", "20")]) is None)
    (d / "cur" / "m.md").write_text("A = 20 and B = 20\n")
    check("R01 two confirmed rows authorize the two occurrences",
          pp._repair_spans_cover(d / "pre", d / "cur", "m.md",
                                 [("10", "20"), ("10", "20")]) is None)
    (d / "pre" / "m2.md").write_text("The cat sat on the mat.\n")
    (d / "cur" / "m2.md").write_text("A dog lay on the rug.\n")
    check("R01 one row may cover several diff runs inside its quoted span",
          pp._repair_spans_cover(d / "pre", d / "cur", "m2.md",
                                 [("The cat sat on the mat",
                                   "A dog lay on the rug")]) is None)


def test_r02() -> None:
    print("\n== R02: Word namespace declaration spellings ==")
    visible = ["Visible text"]
    for label, decl in (
            ("double quotes", f'xmlns:a="{WORD_NS}"'),
            ("single quotes", f"xmlns:a='{WORD_NS}'"),
            ("spaces around =", f'xmlns:a = "{WORD_NS}"')):
        lines, _ = cc.docx_part_to_lines(
            f'<a:document {decl}><a:body><a:p><a:r><a:t>Visible text</a:t>'
            "</a:r></a:p></a:body></a:document>")
        check(f"R02 a prefixed Word namespace with {label} converts", lines == visible, lines)
    lines, _ = cc.docx_part_to_lines(
        f'<document xmlns="{WORD_NS}"><body><p><r><t>Visible text</t></r>'
        "</p></body></document>")
    check("R02 a default Word namespace converts", lines == visible, lines)

    for label, root, nsattr, delxml in (
            ("single quotes", "a:document", f"xmlns:a='{WORD_NS}'",
             '<a:del a:author="r1_w1"><a:r><a:delText>DELETED</a:delText></a:r></a:del>'),
            ("spaces around =", "a:document", f'xmlns:a = "{WORD_NS}"',
             '<a:del a:author="r1_w1"><a:r><a:delText>DELETED</a:delText></a:r></a:del>'),
            ("default namespace", "document", f'xmlns="{WORD_NS}"',
             '<del author="r1_w1"><r><delText>DELETED</delText></r></del>')):
        close = "a:document" if root.startswith("a:") else "document"
        body = (f'<?xml version="1.0" encoding="UTF-8"?><{root} {nsattr}>'
                f'<a:body><a:p>{delxml}<a:r><a:t>Visible</a:t></a:r></a:p></a:body>'
                f"</{close}>").encode()
        if not root.startswith("a:"):
            body = (body.replace(b"<a:body>", b"<body>")
                    .replace(b"<a:p>", b"<p>").replace(b"<a:r>", b"<r>")
                    .replace(b"<a:t>", b"<t>").replace(b"</a:t>", b"</t>")
                    .replace(b"</a:r>", b"</r>").replace(b"</a:p>", b"</p>")
                    .replace(b"</a:body>", b"</body>"))
        data, notes = pp._sanitize_ooxml_bytes(zip_bytes({"word/document.xml": body}))
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            out = z.read("word/document.xml")
        check(f"R02 the sanitizer strips a revision written with {label}",
              b"r1_w1" not in out and b"DELETED" not in out, notes)


def test_r03() -> None:
    print("\n== R03: ambiguity is per reference table ==")
    fm = {"a/plot.tex": "d01/f2.tex", "b/plot.tex": "d02/f3.tex",
          "plot.pdf": "d03/f4.pdf"}
    out = pp._rewrite_view_references(r"\includegraphics{plot}", "main.tex",
                                      "main.tex", fm)
    check("R03 a unique image target is rewritten despite a sibling stem clash",
          out == r"\includegraphics{d03/f4}", out)
    out = pp._rewrite_view_references(r"\input{part.tex}", "b/main.tex", "b/main.tex",
                                      {"a/part.tex": "d01/f2.tex",
                                       "b/part.tex": "d02/f3.tex"})
    check("R03 the ambiguous source basename still resolves locally",
          "f2" not in out and "f3" in out, out)


def test_r04() -> None:
    print("\n== R04: brace groups after a singular cite macro are prose ==")
    o = _extract({"main.tex.txt":
                  r"\documentclass{article}\begin{document}\cite{a} {Figure 1}"
                  r"\bibitem{a} A\end{document}"})
    check("R04 a following prose group is not a citation key",
          [c["key"] for c in o["tex_callouts"]] == ["a"],
          [c["key"] for c in o["tex_callouts"]])
    check("R04 no orphan is fabricated from the prose group",
          not o.get("tex_orphan_keys_by_file"),
          o.get("tex_orphan_keys_by_file"))
    o = _extract({"main.tex.txt":
                  r"\documentclass{article}\begin{document}\parencites{a}{b}"
                  r"\bibitem{a} A\bibitem{b} B\end{document}"})
    check("R04 a multicite macro still yields every key",
          sorted(c["key"] for c in o["tex_callouts"]) == ["a", "b"],
          [c["key"] for c in o["tex_callouts"]])


def test_r05() -> None:
    print("\n== R05: hidden-run filtering honours w:vanish w:val ==")
    text, notes = _docx_to_text(
        '<w:p><w:r><w:rPr><w:vanish w:val="false"/></w:rPr>'
        "<w:t>VISIBLE despite vanish false</w:t></w:r></w:p>"
        '<w:p><w:r><w:rPr><w:vanish w:val="0"/></w:rPr>'
        "<w:t>VISIBLE despite vanish zero</w:t></w:r></w:p>"
        '<w:p><w:r><w:rPr><w:vanish w:val="true"/></w:rPr>'
        "<w:t>HIDDEN true</w:t></w:r></w:p>"
        '<w:p><w:r><w:rPr><w:vanish/></w:rPr>'
        "<w:t>HIDDEN bare</w:t></w:r></w:p>")
    check("R05 val=false and val=0 keep the run visible",
          "VISIBLE despite vanish false" in text
          and "VISIBLE despite vanish zero" in text, text)
    check("R05 val=true and a bare vanish still hide the run",
          "HIDDEN true" not in text and "HIDDEN bare" not in text, text)
    check("R05 the hidden-text note is kept",
          any("hidden" in n for n in notes), notes)


def test_r06() -> None:
    print("\n== R06: .bib keys resolve through the root's bibliography closure ==")
    o = _extract({
        "a.tex.txt": (r"\documentclass{article}\begin{document}"
                      r"\bibliography{refs}\cite{onlyiny}\cite{onlyb}"
                      r"\end{document}"),
        "b.tex.txt": (r"\documentclass{article}\begin{document}"
                      r"\bibliography{other}\cite{onlyb}\end{document}"),
        "refs.bib.txt": "@article{onlyiny, title={Y}}\n",
        "other.bib.txt": "@article{onlyb, title={B}}\n"})
    check("R06 a key from an unrelated .bib is still an orphan",
          o.get("tex_orphan_keys_by_file", {}).get("a.tex.txt") == ["onlyb"],
          o.get("tex_orphan_keys_by_file"))
    check("R06 a key from the root's own .bib resolves",
          "b.tex.txt" not in o.get("tex_orphan_keys_by_file", {}),
          o.get("tex_orphan_keys_by_file"))


def test_r07() -> None:
    print("\n== R07: RTF escaped \\ucN fallbacks are consumed, not emitted ==")

    def rtf(content: str) -> str:
        d = scratch("repair_rtf_")
        p = d / "x.rtf"
        p.write_text(content, encoding="latin-1")
        return cc.rtf_to_text(str(p))[0]

    check("R07 one escaped fallback is not text",
          rtf(r"{\rtf1\ansi \uc1\u945\'e9X}") == "\u03b1X",
          repr(rtf(r"{\rtf1\ansi \uc1\u945\'e9X}")))
    check("R07 two escaped fallbacks are both consumed",
          rtf(r"{\rtf1\ansi \uc2\u945\'e9\'e8X}") == "\u03b1X",
          repr(rtf(r"{\rtf1\ansi \uc2\u945\'e9\'e8X}")))
    check("R07 a literal fallback is still consumed",
          rtf(r"{\rtf1\ansi \uc1\u945?X}") == "\u03b1X",
          repr(rtf(r"{\rtf1\ansi \uc1\u945?X}")))
    check("R07 a uc0 surrogate pair still decodes",
          rtf(r"{\rtf1\ansi \uc0\u-10179\u-8704}") == "\U0001f600",
          repr(rtf(r"{\rtf1\ansi \uc0\u-10179\u-8704}")))
    check("R07 a control word after a unicode escape is still executed",
          rtf(r"{\rtf1\ansi \uc1\u945\par after}") == "\u03b1\nafter",
          repr(rtf(r"{\rtf1\ansi \uc1\u945\par after}")))


def test_r08() -> None:
    print("\n== R08: non-compiled regions are not compile roots ==")
    d = scratch("repair_tex_")
    fixtures = {
        "verbatim.tex": "\\begin{verbatim}\n\\documentclass{article}\n\\end{verbatim}\n",
        "lstlisting.tex": "\\begin{lstlisting}\n\\documentclass{article}\n\\end{lstlisting}\n",
        "minted.tex": "\\begin{minted}{tex}\n\\documentclass{article}\n\\end{minted}\n",
        "comment.tex": "\\begin{comment}\n\\documentclass{article}\n\\end{comment}\n",
        "inline.tex": "\\verb|\\documentclass{article}|\n",
        "real.tex": "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
    }
    for name, body in fixtures.items():
        (d / name).write_text(body)
    roots = pp.latex_root_documents(d)
    check("R08 only the real document is a compile root",
          roots == ["real.tex"], roots)


def test_r09() -> None:
    print("\n== R09: a surname starts with an uppercase letter ==")
    o = _extract({"main.md.txt": "# Main\n\nAs (élève, 2020) and árbol et al., "
                                 "2020 note.\n"})
    check("R09 lowercase non-ASCII prose words are not author-year call-outs",
          not o.get("callouts"), o.get("callouts"))
    o = _extract({"main.md.txt": "# Main\n\nAs (García, 2020) and Åberg et al., "
                                 "2021 note.\n"})
    check("R09 non-ASCII uppercase surnames still inventory",
          sorted(c["refs"][0] for c in o["callouts"]) == ["García 2020", "Åberg 2021"],
          [c["refs"] for c in o["callouts"]])
    o = _extract({"main.md.txt": "# Main\n\n(van der Waals et al., 2019).\n"})
    check("R09 a nobiliary particle does not defeat the uppercase check",
          [c["refs"][0] for c in o["callouts"]] == ["van der Waals 2019"],
          [c["refs"] for c in o["callouts"]])


def test_r10() -> None:
    print("\n== R10: mixed author-year clusters keep every item ==")
    o = _extract({"main.md.txt":
                  "# Main\n\n(Smith, 2019; Jones et al., 2020).\n"})
    check("R10 an et-al item does not swallow the cluster",
          sorted(c["refs"][0] for c in o["callouts"]) == ["Jones 2020", "Smith 2019"],
          [c["refs"] for c in o["callouts"]])
    o = _extract({"main.md.txt":
                  "# Main\n\n(Smith & Jones, 2019; Lee, 2020).\n"})
    check("R10 an ampersand item keeps both surnames",
          sorted(c["refs"][0] for c in o["callouts"])
          == ["Lee 2020", "Smith and Jones 2019"],
          [c["refs"] for c in o["callouts"]])
    o = _extract({"main.md.txt": "# Main\n\n(Smith, 2019; Jones, 2020).\n"})
    check("R10 a plain cluster still yields every call-out",
          sorted(c["refs"][0] for c in o["callouts"]) == ["Jones 2020", "Smith 2019"],
          [c["refs"] for c in o["callouts"]])


# ---------------------------------------------------------------------------
def main() -> int:
    print("Regression checks for the 2026-11-04 verify-fixes repair round")
    for fn in (test_r01, test_r02, test_r03, test_r04, test_r05, test_r06,
               test_r07, test_r08, test_r09, test_r10):
        fn()
    for tmp in TMPDIRS:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILS:
        print(f"\n{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("\nALL 2026-11-04 REPAIR-FIXES CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

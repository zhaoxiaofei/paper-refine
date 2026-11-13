#!/usr/bin/env python3
"""M19 parity between the frozen pipeline and the standalone review skill."""
from pathlib import Path
from tempfile import TemporaryDirectory

from bundle_source_lib import load_bundle


WS = Path(__file__).resolve().parent.parent


def test_f02_f05_f31(pipe, words, check) -> None:
    print()
    print("== F02/F05/F31: M19 keyword/References parity and comment parity ==")
    lines = ["Abstract", "We studied X.", "2 Keywords: alpha beta gamma",
             "Introduction", "Body text here and more."]
    pip = [(r["section"], r["words"]) for r in pipe._length_rows_for_lines(lines, "ms.md")]
    cwr = [(s, w) for s, w, _ in words.sections("\n".join(lines))]
    check("F02 a numbered Keywords heading is a boundary in both counters",
          pip == cwr == [("abstract", 3), ("main text", 5)], f"PIP={pip} CW={cwr}")

    tex = r"""\documentclass{article}
\begin{document}
\begin{abstract}
We studied X.
\end{abstract}
\section{Introduction}
Body text here and more.
\begin{thebibliography}{9}
\bibitem{a} Alpha et al. A title. 2020.
\bibitem{b} Beta et al. Another title. 2021.
\end{thebibliography}
\end{document}
"""
    ls, caps, ae = pipe._tex_length_scan(tex)
    pip = [(r["section"], r["words"]) for r in
           pipe._length_rows_for_lines(ls, "ms.tex", caption_spans=caps, abstract_end=ae)]
    cwr = [(s, w) for s, w, _ in words.sections("\n".join(words.tex_lines(tex)[0]))]
    check("F05 an inline bibliography is excluded by both counters",
          pip == cwr and ("main text", 5) in pip, f"PIP={pip} CW={cwr}")

    src = r"x\\% \input{hidden.tex}"
    check("F31 a \\\\% comment ends the line (parity with strip_tex_comment)",
          pipe._tex_strip_comments(src) == pipe.strip_tex_comment(src) == "x\\\\")
    check("F31 a commented-out \\input is not a dependency",
          pipe.tex_input_targets(src) == [], pipe.tex_input_targets(src))


def test_f020(pipe, words, check, f020):
    # F020: the skill and the pipeline subtract the same caption span, even
    # when a heading line sits inside the span.
    f020_text = ("Funding\n1. Introduction\nCopy-number (CN) burden.\n"
                 "Figure 1. legend text here\n**Methods**\nKeywords\n## Abstract\n")
    (f020 / "ms.md").write_text(f020_text, encoding="utf-8")
    skill_main = [r for r in words.sections(f020_text) if r[0] == "main text"]
    pipe_main = [r for r in pipe.scan_lengths_in_sources([(f020, "", ())])["rows"]
                 if r["section"] == "main text"]
    check("F020 (caption span subtraction inspected against scan_lengths_in_sources)",
          len(skill_main) == 1 and len(pipe_main) == 1
          and skill_main[0][1] == pipe_main[0]["words"] == 3
          and "5 caption word(s) subtracted" in skill_main[0][2]
          and "5 caption word(s) subtracted" in pipe_main[0]["note"],
          f"skill={skill_main} pipeline={pipe_main}")


def main():
    pipe = load_bundle("word_count_pipeline", WS / "paper_pipeline.py")
    words = load_bundle("word_count_skill", WS / "paper-skills/paper-review/scripts/count_words.py")
    failures = []

    def check(name, ok, detail=""):
        print(f"[{'ok ' if ok else 'FAIL'}] {name}  {detail}")
        if not ok:
            failures.append(name)

    test_f02_f05_f31(pipe, words, check)
    with TemporaryDirectory(prefix="paper_word_parity_") as directory:
        test_f020(pipe, words, check, Path(directory))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())

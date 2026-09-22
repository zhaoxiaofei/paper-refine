#!/usr/bin/env python3
"""Design-audit regression suite (2026-09-19, potential-design-issue-report).

Run:  python3 .nbt_test/test_design_audit_2026_0919.py

Every check below failed on the tree that the audit reviewed (or, for the items
already closed by the previous bug-audit round, is asserted here so the fix
cannot regress). Covered surface, one section per confirmed defect:

  * D1 LaTeX counting: count_words.py must read `.tex`/`.ltx` sources (abstract
    environment, section headings, \\caption lines) instead of answering with a
    markup-inclusive "whole file" row;
  * D2 a one-line `\\begin{abstract} ... \\end{abstract}` must not be counted as
    zero words (the text used to vanish from both implementations);
  * D3 a multi-paragraph LaTeX abstract ends at `\\end{abstract}`, not at the
    first blank line (paragraph 2 used to leak into the main-text count);
  * D4 M19 caption subtraction must stay inside the main-text span: a legend
    after Methods is not part of the text the count already excluded it from;
  * D5 the cover-letter row is a user PREFERENCE, so it must not be reported as
    an over-cap section (the decide warning named it as a cap breach, cap None);
  * D6 M18 is mandatory in every caption state: the review prompt used to say
    "M18 need not appear" while its own postcheck hard-fails without the row;
  * D7 the standalone fallback prompt must carry the same check-ID contract as
    SKILL.md / sweeps.md (M18+M19+M20 always, proposals from M21, cover-letter mode);
  * D8 caption dialects/extensions: `.markdown`/`.rst` manuscripts are length
    scanned, so their legends must be enumerated too.

`NBT_WS` retargets the suite at another copy of the tree.
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
spec = importlib.util.spec_from_file_location("nbt_design_audit", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_design_audit"] = nb
spec.loader.exec_module(nb)

COUNT_WORDS = WS / "nbt-skills/nbt-review/scripts/count_words.py"
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


def write(p: Path, data: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data, encoding="utf-8")


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def make_docx(path: Path, paragraphs) -> None:
    body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in paragraphs)
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body>{body}</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("word/document.xml", xml)


def scan_rows(tmp: Path, name: str) -> dict:
    info = nb.scan_lengths_in_sources([(tmp, "", ())])
    return {(r["document"], r["section"]): r for r in info["rows"] if r["document"] == name}


def script_rows(path: Path, *args) -> list:
    proc = subprocess.run([sys.executable, str(COUNT_WORDS), str(path), "--json"] + list(args),
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        return []
    return json.loads(proc.stdout)["rows"]


# =====================================================================
# D1-D3 -- the bundled M19 counter must read LaTeX
# =====================================================================

TEX_ONE_LINE = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "\\begin{abstract} We show that the compact abstract survives the count. \\end{abstract}\n"
    "\\section{Introduction}\n"
    "This body has eight words in total.\n"
    "\\end{document}\n"
)
TEX_ONE_LINE_ABSTRACT_WORDS = 9      # "We show that the compact abstract survives the count."
TEX_ONE_LINE_MAIN_WORDS = 7          # "This body has eight words in total."


def tex_multi_paragraph(abstract_words=50, para2_words=50, body_words=30) -> str:
    para1 = " ".join(["alpha"] * abstract_words)
    para2 = " ".join(["beta"] * para2_words)
    body = " ".join(["gamma"] * body_words)
    return ("\\documentclass{article}\n\\begin{document}\n"
            f"\\begin{{abstract}}\n{para1}\n\n{para2}\n\\end{{abstract}}\n"
            f"\\section{{Introduction}}\n{body}\n"
            "\\end{document}\n")


def test_latex_counting():
    print()
    print("== D1-D3: LaTeX sources are counted by the shared M19 rule ==")
    tmp = scratch("nbt_de_tex_")
    # D2: one-line abstract
    write(tmp / "one-line.tex", TEX_ONE_LINE)
    rows = scan_rows(tmp, "one-line.tex")
    abs_row, main_row = rows.get(("one-line.tex", "abstract")), rows.get(("one-line.tex", "main text"))
    check("D2 the pipeline counts a one-line LaTeX abstract",
          abs_row is not None and abs_row["words"] == TEX_ONE_LINE_ABSTRACT_WORDS,
          f"{abs_row and abs_row['words']} != {TEX_ONE_LINE_ABSTRACT_WORDS}")
    check("D2 ... and keeps it out of the main text",
          main_row is not None and main_row["words"] == TEX_ONE_LINE_MAIN_WORDS,
          f"{main_row and main_row['words']} != {TEX_ONE_LINE_MAIN_WORDS}")
    srows = {(r["section"]): r for r in script_rows(tmp / "one-line.tex")}
    check("D1 count_words.py counts the one-line LaTeX abstract too",
          srows.get("abstract", {}).get("words") == TEX_ONE_LINE_ABSTRACT_WORDS
          and srows.get("main text", {}).get("words") == TEX_ONE_LINE_MAIN_WORDS,
          str(srows))
    check("D1 count_words.py reports a LaTeX manuscript shape, not 'whole file'",
          "abstract" in srows and "whole file" not in srows, str(list(srows)))
    # --section whole must answer with a whole-file row for every format: a
    # shaped document used to filter its own rows away and print nothing.
    wrows = [r for r in script_rows(tmp / "one-line.tex", "--section", "whole")
             if r["section"] == "whole file"]
    check("D1 --section whole on a .tex reports the whole file (18 counted words)",
          len(wrows) == 1 and wrows[0]["words"] == 18, str(wrows))
    write(tmp / "plain.md", "Abstract\n\n" + " ".join(["word"] * 12) + "\n")
    wrows = [r for r in script_rows(tmp / "plain.md", "--section", "whole")
             if r["section"] == "whole file"]
    check("D1 --section whole on a shaped .md also reports the whole file",
          len(wrows) == 1 and wrows[0]["words"] == 13, str(wrows))

    # D3: multi-paragraph abstract
    write(tmp / "two-para.tex", tex_multi_paragraph())
    rows = scan_rows(tmp, "two-para.tex")
    abs_row = rows.get(("two-para.tex", "abstract"))
    main_row = rows.get(("two-para.tex", "main text"))
    check("D3 the pipeline keeps a two-paragraph LaTeX abstract whole",
          abs_row is not None and abs_row["words"] == 100,
          f"{abs_row and abs_row['words']} != 100")
    check("D3 ... and the main text starts after \\end{abstract}",
          main_row is not None and main_row["words"] == 30,
          f"{main_row and main_row['words']} != 30")
    srows = {r["section"]: r for r in script_rows(tmp / "two-para.tex")}
    check("D1/D3 count_words.py agrees with the pipeline on the same .tex",
          srows.get("abstract", {}).get("words") == 100
          and srows.get("main text", {}).get("words") == 30, str(srows))


# =====================================================================
# D4 -- caption subtraction stays inside the main-text span
# =====================================================================

def test_caption_span():
    print()
    print("== D4: M19 subtracts only the legends inside the main-text span ==")
    tmp = scratch("nbt_de_cap_")
    body = " ".join(["maintext"] * 20)
    in_span = "Figure 1 | A legend with words in it here."
    out_span = "Figure 2 | Another legend with different words here."
    md = (f"Abstract\n\n{'abs ' * 10}\n\nIntroduction\n\n{body}\n\n{in_span}\n\n"
          f"Methods\n\nx y z\n\n{out_span}\n")
    write(tmp / "ms.md", md)
    rows = scan_rows(tmp, "ms.md")
    main_row = rows.get(("ms.md", "main text"))
    # the 20-word body plus the in-span legend, minus that legend = 20; the
    # legend after Methods is outside the span and must not be subtracted.
    want = 20
    check("D4 a .md legend after Methods is not subtracted from the main text",
          main_row is not None and main_row["words"] == want,
          f"{main_row and main_row['words']} != {want}")
    srows = {r["section"]: r for r in script_rows(tmp / "ms.md", "--section", "main-text")}
    check("D4 count_words.py agrees (both subtract only the in-span legend)",
          srows.get("main text", {}).get("words") == want, str(srows))

    make_docx(tmp / "ms.docx",
              ["Abstract", "abs " * 10, "Introduction", body, in_span, "Methods", "x y z",
               out_span])
    rows = scan_rows(tmp, "ms.docx")
    main_row = rows.get(("ms.docx", "main text"))
    check("D4 a .docx legend after Methods is not subtracted from the main text",
          main_row is not None and main_row["words"] == want,
          f"{main_row and main_row['words']} != {want}")

    # LaTeX: the legend is a \caption, and only the in-span one is subtracted
    tex_head = ("\\begin{abstract}\n" + " ".join(["abs"] * 10) + "\n\\end{abstract}\n"
                "\\section{Introduction}\n" + body + "\n")
    write(tmp / "in.tex", tex_head
          + "\\begin{figure}\n\\caption{A legend inside the main text span.}\n\\end{figure}\n"
          + "\\section{Methods}\nWe worked.\n")
    write(tmp / "out.tex", tex_head + "\\section{Methods}\nWe worked.\n"
          + "\\begin{figure}\n\\caption{A legend after the methods heading.}\n\\end{figure}\n")
    rows = scan_rows(tmp, "in.tex")
    main_row = rows.get(("in.tex", "main text"))
    check("D4 the .tex legend inside the span is subtracted",
          main_row is not None and main_row["words"] == 20,
          f"{main_row and main_row['words']} != 20")
    rows = scan_rows(tmp, "out.tex")
    main_row = rows.get(("out.tex", "main text"))
    check("D4 the .tex legend after Methods is not subtracted",
          main_row is not None and main_row["words"] == 20,
          f"{main_row and main_row['words']} != 20")


# =====================================================================
# D5 -- the cover-letter preference is not a cap
# =====================================================================

def test_cover_letter_preference():
    print()
    print("== D5: the 300-500-word cover-letter range is a preference, not a cap ==")
    tmp = scratch("nbt_de_cover_")
    write(tmp / "cover-letter.md",
          "Dear Editor,\n\n" + " ".join(["persuade"] * 600)
          + "\n\nSincerely,\nA. Author\n")
    info = nb.scan_lengths_in_sources([(tmp, "", ())])
    row = [r for r in info["rows"] if r["section"] == "cover letter"][0]
    check("D5 a long cover letter is surfaced as outside the preference",
          row["within_preference"] is False and row.get("over_preference") is True, str(row))
    check("D5 ... and not as an over-cap section",
          row["over_limit"] is False, str(row))
    check("D5 the scan's over_limit list carries no cover letter",
          not any(r["section"] == "cover letter" for r in info["over_limit"]), str(info["over_limit"]))
    srow = [r for r in script_rows(tmp / "cover-letter.md") if r["section"] == "cover letter"][0]
    check("D5 the bundled script keeps the same semantics",
          srow["over_limit"] is False and srow["within_preference"] is False, str(srow))
    note = nb.length_note(info)
    check("D5 the note still names the preference, not a cap breach",
          "OUTSIDE-PREFERENCE" in note and "not an NBT limit" in note, note)


# =====================================================================
# D6 -- M18 is mandatory in the review contract (prompt == postcheck)
# =====================================================================

def test_m18_coverage_contract():
    print()
    print("== D6: the M18 coverage row is always required ==")
    tmp = scratch("nbt_de_m18_")
    sb = tmp / "runs" / "r1_a2_review"
    write(sb / "base" / "ms.md", "text\n")
    write(sb / "review" / "artifacts" / "M1_acronyms.md", "| row |\n|---|\n")
    ctx = type("C", (), {"cfg": {}})()
    cov = ([{"check": f"M{i}", "disposition": "clean -- basis: x"} for i in range(1, 18)]
           + [{"check": f"J{i}", "disposition": "clean -- basis: x"} for i in range(1, 5)]
           + [{"check": "M19", "disposition": "0 findings"}])
    fj = {"submission_dir": "./base", "findings": [{"id": "F-001", "check": "M1"}],
          "artifacts": {}, "coverage": cov}
    errs, warns = [], []
    nb.check_review_contract(ctx, sb, fj, errs, warns)
    check("D6 a review without an M18 coverage row fails the contract",
          any("M18" in e for e in errs), str(errs))

    prompt = nb.review_prompt(tmp, "r1_review", 1)
    flat = re.sub(r"\s+", " ", prompt)
    check("D6 the no-cap review prompt no longer says M18 may be omitted",
          "M18 need not appear" not in flat, flat[flat.find("M18 need not appear") - 120:][:200]
          if "M18 need not appear" in flat else "")
    check("D6 ... and it still demands M18's own coverage row",
          "Give M18 its own coverage row" in flat)
    check("D6 the prompt does not claim M18 is absent from references/sweeps.md",
          "not in references/sweeps.md" not in flat)
    check("D6 the header docstring matches the postcheck",
          "M1-M17/J1-J4 (+M18 only when the caption" not in
          (WS / "nbt_pipeline.py").read_text(encoding="utf-8"))


# =====================================================================
# D7 -- the standalone fallback prompt carries the same contract
# =====================================================================

def test_fallback_prompt_contract():
    print()
    print("== D7: identify_issues.prompt.md matches SKILL.md / sweeps.md ==")
    prompt = (WS / "nbt-skills/prompts/identify_issues.prompt.md").read_text(encoding="utf-8")
    skill = (WS / "nbt-skills/nbt-review/SKILL.md").read_text(encoding="utf-8")
    sweeps = (WS / "nbt-skills/nbt-review/references/sweeps.md").read_text(encoding="utf-8")
    check("D7 the fallback hard rule makes M18 and M19 mandatory",
          "M1–M17 are EXHAUSTIVE and MANDATORY, and M18" in prompt, "")
    check("D7 the fallback no longer defers M18 to 'when the caption suggestion is active'",
          "M18 only when the pipeline's caption suggestion is active" not in prompt)
    check("D7 the fallback acceptance check lists the 24 defined check IDs",
          "all 21 check IDs" not in prompt
          and "M1–M17, J1–J4, M18 (legend counts), M19" in prompt and "M20" in prompt)
    check("D7 the fallback numbers discovery proposals from M21",
          "as M18, M19" not in prompt and "M21" in prompt)
    check("D7 the fallback documents the cover-letter counting mode",
          "--section cover-letter" in prompt)
    check("D7 SKILL.md's coverage table requires M18/M19/M20 in every state",
          "plus M19 — and M18 when the caption suggestion is active" not in skill
          and "M18 (legend counts), M19 (abstract/main-text/cover-letter lengths) and M20" in skill)
    check("D8 the sweeps FINDING FORMAT admits M18-M24 findings",
          "check: <M1–M24|J1–J4>" in sweeps and "check: <M1–M20|J1–J4>" not in sweeps)


# =====================================================================
# D8 -- every length-scanned text format is enumerated for M18 too
# =====================================================================

def test_caption_extension_parity():
    print()
    print("== D8: caption enumeration covers every length-scanned text format ==")
    tmp = scratch("nbt_de_ext_")
    md = ("Introduction\n\n" + " ".join(["body"] * 30)
          + "\n\nFigure 1 | A legend for the rst manuscript.\n\nMethods\n\nx\n")
    write(tmp / "ms.markdown", md)
    write(tmp / "ms.rst", md)
    caps = nb.scan_captions_in_sources([(tmp, "", ())])
    files = {c["document"] for c in caps["captions"]}
    check("D8 a .markdown legend is enumerated",
          any(f.endswith("ms.markdown") for f in files), str(sorted(files)))
    check("D8 a .rst legend is enumerated",
          any(f.endswith("ms.rst") for f in files), str(sorted(files)))
    rows = scan_rows(tmp, "ms.rst")
    main_row = rows.get(("ms.rst", "main text"))
    check("D8 ... and its legend is not counted as main text",
          main_row is not None and main_row["words"] == 30,
          f"{main_row and main_row['words']} != 30")


# =====================================================================
# D9 -- a \caption group is subtracted exactly; neighbouring prose is not
# =====================================================================

def test_tex_caption_boundaries():
    print()
    print("== D9: LaTeX captions subtract their own words only ==")
    tmp = scratch("nbt_de_texcap_")
    body = " ".join(["maintext"] * 20)
    head = ("\\begin{abstract}\n" + " ".join(["abs"] * 10) + "\n\\end{abstract}\n"
            "\\section{Introduction}\n" + body + "\n")
    tail = "\\section{Methods}\nWe worked.\n"
    # A caption group sharing its line with trailing prose: the 4 prose words
    # belong to the main text; the 2 caption words do not.
    write(tmp / "mixed.tex",
          head + "\\caption{A legend.} This sentence is prose.\n" + tail)
    # The same, with the caption group wrapping over two source lines.
    write(tmp / "wrapped.tex",
          head + "\\caption{A legend that wraps over\ntwo source lines.} "
                 "This sentence is prose.\n" + tail)
    # An environment token sharing its line with prose contributes no word.
    write(tmp / "env.tex", head + "\\begin{figure} See the four panels below.\n" + tail)
    for name, want in (("mixed.tex", 24), ("wrapped.tex", 24), ("env.tex", 25)):
        rows = scan_rows(tmp, name)
        main_row = rows.get((name, "main text"))
        check(f"D9 {name}: main text counts the prose, not the caption",
              main_row is not None and main_row["words"] == want,
              f"{main_row and main_row['words']} != {want}")
        srows = {r["section"]: r for r in script_rows(tmp / name, "--section", "main-text")}
        check(f"D9 {name}: count_words.py agrees",
              srows.get("main text", {}).get("words") == want, str(srows))


def main() -> int:
    sections = (("latex", test_latex_counting),
                ("caption-span", test_caption_span),
                ("cover-letter", test_cover_letter_preference),
                ("m18-contract", test_m18_coverage_contract),
                ("fallback-prompt", test_fallback_prompt_contract),
                ("caption-exts", test_caption_extension_parity),
                ("tex-caption-boundaries", test_tex_caption_boundaries))
    try:
        for name, fn in sections:
            try:
                fn()
            except Exception as e:                                  # noqa: BLE001
                check(f"{name} section completed", False, f"{type(e).__name__}: {e}")
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("all design-audit checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

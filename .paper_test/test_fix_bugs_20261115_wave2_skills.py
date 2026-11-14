#!/usr/bin/env python3
"""Regression checks for 2026-11-15 fix-bugs wave 2, group `skills`.

Every check pins one candidate this wave re-validated on the tree and repaired:
F265/F266 (M19 section boundaries), F268 (LaTeX `__` root name), F269
(reference-heading recognition), F272 (per-table M1b context), F275
(occurrence sweep vs the reference list), F277 (converted-corpus word count)
and F278 (value-notation equivalence).

Hermetic: every fixture lives under tempfile.mkdtemp(); each CLI check drives
its own corpus under that directory.

Run:  python3 .paper_test/test_fix_bugs_20261115_wave2_skills.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
SCRIPTS = WS / "paper-skills" / "paper-review" / "scripts"
TMPDIRS: list[Path] = []
FAILS: list[str] = []
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run(script: str, *args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          cwd=str(cwd or WS), capture_output=True, text=True, timeout=180)


def rows_by_section(proc) -> dict:
    data = json.loads(proc.stdout)
    return {row["section"]: row for row in data["rows"]}


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# F265 — structured abstract: subheadings are not body section boundaries
# --------------------------------------------------------------------------
def check_f265() -> None:
    d = scratch("f265_")
    write(d / "ms.md", """Abstract
Background:
Cells grow quickly in this culture system.
Methods:
We used a standard protocol in the study.
Results:
The treatment reduced growth by half in every sample.
Conclusions:
The approach is useful for future work in the field.

Introduction
Body introduction text here with several words.

Methods
Methods body text.

References
1. A. One. 2019.
""")
    proc = run("count_words.py", d / "ms.md", "--json")
    rows = rows_by_section(proc)
    check("F265 structured abstract is counted as the abstract, not the body",
          rows["abstract"]["words"] == 34 and rows["main text"]["words"] == 7,
          {k: v["words"] for k, v in rows.items()})

    profile = {"id": "x", "default_article_type": "article",
               "article_types": [{"id": "article", "label": "Article",
                                  "length_limits": {
                                      "abstract": {"base": 30, "relaxation": 1.0},
                                      "main_text": {"base": 30, "relaxation": 1.0}}}]}
    write(d / "p.json", json.dumps(profile))
    proc = run("count_words.py", d / "ms.md", "--venue-profile", d / "p.json", "--json")
    rows = rows_by_section(proc)
    check("F265 the abstract over-cap is flagged and the main text is not",
          rows["abstract"]["over_limit"] is True
          and rows["main text"]["over_limit"] is False,
          {k: (v["words"], v["over_limit"]) for k, v in rows.items()})

    # A real body heading after a blank line is still a boundary.
    write(d / "normal.md", """Abstract
First abstract line with several words.
Second abstract line with several words.

Methods
Methods body text.

Results
Results body text here.
""")
    proc = run("count_words.py", d / "normal.md", "--json")
    rows = rows_by_section(proc)
    check("F265 a blank-line-separated Methods heading still ends the abstract",
          rows["abstract"]["words"] == 12 and rows["main text"]["words"] == 4,
          {k: v["words"] for k, v in rows.items()})


# --------------------------------------------------------------------------
# F266 — combined headings
# --------------------------------------------------------------------------
def check_f266() -> None:
    d = scratch("f266_")
    write(d / "rd.md", """Abstract
First abstract paragraph with five words.
Second abstract paragraph with six words.

Results and Discussion
We found that cells grew fast and the cohort was large in this study.

Methods
Cells were grown and measured carefully with standard tools.

References
1. A. One. 2019.
""")
    rows = rows_by_section(run("count_words.py", d / "rd.md", "--json"))
    check("F266 'Results and Discussion' ends the abstract and stays in the main text",
          rows["abstract"]["words"] == 12 and rows["main text"]["words"] == 14,
          {k: v["words"] for k, v in rows.items()})

    write(d / "mm.md", """Abstract
A short abstract with a few words.

Introduction
Intro text here.

Methods and Materials
We used many lengthy procedures and reagents in this section of the study.

References
1. A. One. 2019.
""")
    rows = rows_by_section(run("count_words.py", d / "mm.md", "--json"))
    check("F266 'Methods and Materials' is the methods kind (excluded from main text)",
          rows["abstract"]["words"] == 7 and rows["main text"]["words"] == 3,
          {k: v["words"] for k, v in rows.items()})


# --------------------------------------------------------------------------
# F268 — '__' in a LaTeX root filename is not a directory separator
# --------------------------------------------------------------------------
def _cite_package(base: Path, root_name: str, input_arg: str = "chapter") -> dict:
    sub = base / "sub"
    write(sub / f"{root_name}.tex", "\\documentclass{article}\n"
          "\\begin{document}\n"
          f"\\input{{{input_arg}}}\n"
          "Body text with \\cite{smith2019}.\n"
          "\\bibliography{refs}\n"
          "\\end{document}\n")
    write(sub / "chapter.tex", "\\section{Results}\n"
          "More text and another call \\cite{smith2019}.\n")
    write(sub / "refs.bib", "@article{smith2019, title={T}, year={2019}}\n")
    work, out = base / "work", base / "out"
    run("convert_corpus.py", "--submission", sub, "--work", work)
    run("extract_citations.py", "--work", work, "--out", out)
    return json.loads((out / "artifacts" / "M2_citations.json").read_text(encoding="utf-8"))


def check_f268() -> None:
    d = scratch("f268_")
    m = _cite_package(d / "double", "supp__main")
    check("F268 a root basename containing '__' resolves its inputs and bibliography",
          m["tex_orphan_keys"] == [] and m["tex_orphan_keys_by_file"] == {},
          {"orphans": m["tex_orphan_keys"], "by_file": m["tex_orphan_keys_by_file"],
           "uncited": m["tex_uncited_keys"]})

    m = _cite_package(d / "single", "supp_main")
    check("F268 control: a single-underscore root stays clean",
          m["tex_orphan_keys"] == [], m["tex_orphan_keys"])

    # Relative resolution still works for a nested child.
    sub = d / "nested" / "sub"
    write(sub / "main.tex", "\\documentclass{article}\n\\begin{document}\n"
          "\\input{tools/chapter}\nBody \\cite{a}.\n\\end{document}\n")
    write(sub / "tools" / "chapter.tex", "\\section{R}\nText \\cite{a}.\n")
    write(sub / "tools" / "refs.bib", "@article{a, title={A}, year={2019}}\n")
    write(sub / "main.tex", "\\documentclass{article}\n\\begin{document}\n"
          "\\input{tools/chapter}\nBody \\cite{a}.\n"
          "\\bibliography{tools/refs}\n\\end{document}\n")
    work, out = d / "nested" / "work", d / "nested" / "out"
    run("convert_corpus.py", "--submission", sub, "--work", work)
    run("extract_citations.py", "--work", work, "--out", out)
    m = json.loads((out / "artifacts" / "M2_citations.json").read_text(encoding="utf-8"))
    check("F268 a nested child keeps its directory-qualified resolution",
          m["tex_orphan_keys"] == [], m["tex_orphan_keys"])


# --------------------------------------------------------------------------
# F269 — reference headings: Markdown emphasis and LaTeX forms
# --------------------------------------------------------------------------
def check_f269() -> None:
    d = scratch("f269_md_")
    sub = d / "sub"
    write(sub / "ms.md", """# Results
We used PCR and found p = 0.03 in the cohort.

**References**

1. Smith J. A scRNA-seq atlas with p = 0.001. Nature. 2019.
""")
    work, out = d / "work", d / "out"
    run("convert_corpus.py", "--submission", sub, "--work", work)
    run("extract_numbers.py", "--work", work, "--out", out)
    run("extract_acronyms.py", "--work", work, "--out", out)
    m4 = json.loads((out / "artifacts" / "M4_numbers.json").read_text(encoding="utf-8"))
    values = [row["value"] for row in m4["metrics"] if row["label"] == "p-value"]
    check("F269 a bold '**References**' heading stops the M4 sweep",
          0.001 not in [float(v) for v in values] and 0.03 in [float(v) for v in values],
          values)
    m1 = json.loads((out / "artifacts" / "M1_acronyms.json").read_text(encoding="utf-8"))
    acronyms = {row["acronym"] for row in m1}
    check("F269 a bold reference heading keeps cited-title acronyms out of M1",
          "scRNA-seq" not in acronyms and "PCR" in acronyms, sorted(acronyms))

    d = scratch("f269_tex_")
    sub = d / "sub"
    write(sub / "paper.tex", """\\documentclass{article}
\\begin{document}
\\section{Results}
We found p = 0.03 in the cohort.

\\section{References}
\\begin{thebibliography}{9}
\\bibitem{smith2019} Smith J, Jones A. A trial with p = 0.001 in Smith et al. 2019. Nature. 2019.
\\end{thebibliography}

\\section{Discussion}
We found p = 0.04 in the follow-up.
\\end{document}
""")
    work, out = d / "work", d / "out"
    run("convert_corpus.py", "--submission", sub, "--work", work)
    run("extract_numbers.py", "--work", work, "--out", out)
    run("extract_citations.py", "--work", work, "--out", out)
    m4 = json.loads((out / "artifacts" / "M4_numbers.json").read_text(encoding="utf-8"))
    values = sorted(float(row["value"]) for row in m4["metrics"] if row["label"] == "p-value")
    check("F269 a LaTeX \\section{References} list is skipped and the next section resumes",
          values == [0.03, 0.04], values)
    m2 = json.loads((out / "artifacts" / "M2_citations.json").read_text(encoding="utf-8"))
    check("F269 a \\bibitem emits no phantom author-year call-out",
          m2["callouts"] == [], m2["callouts"])

    # A `\bibliography{...}` command has no closing environment: the region
    # must end at the next sectioning command, not swallow the rest.
    d = scratch("f269_bibcmd_")
    sub = d / "sub"
    write(sub / "paper.tex", "\\documentclass{article}\n\\begin{document}\n"
          "\\section{Results}\nWe found p = 0.05 in the cohort.\n"
          "\\bibliography{refs}\n"
          "\\section{Discussion}\nWe found p = 0.06 in the follow-up.\n"
          "\\end{document}\n")
    write(sub / "refs.bib", "@article{x, title={T with p = 0.001}, year={2019}}\n")
    work, out = d / "work", d / "out"
    run("convert_corpus.py", "--submission", sub, "--work", work)
    run("extract_numbers.py", "--work", work, "--out", out)
    m4 = json.loads((out / "artifacts" / "M4_numbers.json").read_text(encoding="utf-8"))
    values = sorted(float(row["value"]) for row in m4["metrics"] if row["label"] == "p-value")
    check("F269 a \\bibliography region ends at the next section heading",
          values == [0.05, 0.06], values)

    # The shared stop patterns must see a SINGLE backslash: a doubled escape
    # compiles but silently stops matching sectioning commands.
    for modname, script, attr in (
            ("fb1115wave2_num", "extract_numbers.py", "REF_TEX_END_RE"),
            ("fb1115wave2_cit", "extract_citations.py", "REF_TEX_END_RE"),
            ("fb1115wave2_acr", "extract_acronyms.py", "REF_TEX_END_RE"),
            ("fb1115wave2_occ", "extract_occurrences.py", "REF_END_RE")):
        mod = load(modname, SCRIPTS / script)
        check(f"F269 {script} ends the region at a LaTeX section heading",
              bool(getattr(mod, attr).match(r"\section{Discussion}")))

    mod = load("fb1115wave2_enum", SCRIPTS / "enumerate_conventions.py")
    check("F269 enumerate_conventions recognises the emphasised heading",
          bool(mod._REF_HEADING_RE.match("**References**"))
          and bool(mod._REF_HEADING_RE.match("References")))


# --------------------------------------------------------------------------
# F272 — each table caption is its own M1b context
# --------------------------------------------------------------------------
def check_f272() -> None:
    d = scratch("f272_")
    sub = d / "sub"
    write(sub / "ms.md", """Abstract
Copy-number (CN) alterations were common in the cohort.

Table 1 | Baseline characteristics.
Copy-number burden per cell was measured.

Table 2 | Follow-up characteristics.
Copy-number burden per cell was measured again.
""")
    work, out = d / "work", d / "out"
    run("convert_corpus.py", "--submission", sub, "--work", work)
    run("extract_acronyms.py", "--work", work, "--out", out)
    rows = json.loads((out / "artifacts" / "M1_acronyms.json").read_text(encoding="utf-8"))
    cn = next(row for row in rows if row["acronym"] == "CN")
    check("F272 the second table's first long-form use is not an M1(k) residue",
          cn["long_form_after_first_use"] == {},
          cn["long_form_after_first_use"])
    check("F272 each table caption carries its own first-use context",
          "table 1" in cn["long_form_first_use"]
          and "table 2" in cn["long_form_first_use"],
          cn["long_form_first_use"])


# --------------------------------------------------------------------------
# F275 — occurrence enumeration skips the reference list
# --------------------------------------------------------------------------
def check_f275() -> None:
    d = scratch("f275_")
    write(d / "corpus" / "ms.txt", """Results
We measured copy-number burden in every cell.

References
1. Smith J. Copy number variation in cancer. Nature. 2019.
""")
    proc = run("extract_occurrences.py", "--work", d, "--term", "copy number", "--out", d / "o")
    data = json.loads((d / "o" / "occurrences_copy_number.json").read_text(encoding="utf-8"))
    occ = [(o["file"], o["line"]) for o in data[0]["occurrences"]]
    check("F275 a reference title is not an occurrence of the manuscript term",
          occ == [("ms.txt", 2)], occ)
    check("F275 the sweep still reports the body occurrence",
          proc.returncode == 0 and data[0]["n"] == 1, data[0]["n"])

    d = scratch("f275_bib_")
    write(d / "corpus" / "ms.txt", "Results\nWe measured copy-number burden in every cell.\n")
    write(d / "corpus" / "refs.bib.txt",
          "Smith J. Copy number variation in cancer. Nature. 2019.\n")
    write(d / "corpus" / "library.bib.txt",
          "Jones A. Copy number losses in tumours. Cell. 2020.\n")
    run("extract_occurrences.py", "--work", d, "--term", "copy number", "--out", d / "o")
    data = json.loads((d / "o" / "occurrences_copy_number.json").read_text(encoding="utf-8"))
    check("F275 a reference-role file is skipped by name (including a .bib file)",
          [o["file"] for o in data[0]["occurrences"]] == ["ms.txt"],
          data[0]["occurrences"])


# --------------------------------------------------------------------------
# F277 — the converter's corpus text is a supported M19 input
# --------------------------------------------------------------------------
def _docx(path: Path, body_paras, header: str, footer: str) -> None:
    def para(t):
        return f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>"

    def part(tag, text):
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:{tag} xmlns:w="{W}">{para(text)}</w:{tag}>')

    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:document xmlns:w="{W}"><w:body>'
                + "".join(para(t) for t in body_paras)
                + "</w:body></w:document>")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", document)
        z.writestr("word/header1.xml", part("hdr", header))
        z.writestr("word/footer1.xml", part("ftr", footer))


def check_f277() -> None:
    d = scratch("f277_tex_")
    write(d / "corpus" / "paper.tex.txt",
          "\\documentclass{article}\n\\begin{abstract}\nShort abstract here.\n"
          "\\end{abstract}\n\\section{Introduction}\n"
          "Body words one two three four five six seven.\n")
    proc = run("count_words.py", d / "corpus" / "paper.tex.txt",
               "--base-main-text", "5", "--json")
    data = json.loads(proc.stdout)
    rows = {row["section"]: row for row in data["rows"]}
    check("F277 a .tex.txt corpus file is counted with the LaTeX shape",
          "abstract" in rows and "main text" in rows
          and rows["abstract"]["words"] == 3 and rows["main text"]["words"] == 9,
          {k: v["words"] for k, v in rows.items()})
    check("F277 the main-text cap applies to a .tex.txt corpus file",
          data["caps"]["main text"] == 6 and rows["main text"]["over_limit"] is True,
          {"caps": data["caps"], "over": rows["main text"]["over_limit"]})

    write(d / "corpus" / "main.tex.txt",
          "\\documentclass{article}\n\\begin{document}\n\\input{chapter}\n\\end{document}\n")
    write(d / "corpus" / "chapter.tex.txt",
          "\\section{Introduction}\nBody words one two three four five six seven "
          "eight nine ten.\n")
    proc = run("count_words.py", d / "corpus" / "main.tex.txt",
               "--base-main-text", "5", "--json")
    rows = {row["section"]: row for row in json.loads(proc.stdout)["rows"]}
    check("F277 an include is resolved to the converted child",
          rows["main text"]["words"] == 12, rows)

    d = scratch("f277_docx_")
    _docx(d / "sub" / "ms.docx",
          ["Abstract", "Short abstract here.", "Introduction", "Body text words here now."],
          "Running head title", "Page 1 of 9")
    run("convert_corpus.py", "--submission", d / "sub", "--work", d / "work")
    corpus_file = d / "work" / "corpus" / "ms.docx.txt"
    check("F277 the converter's DOCX text carries page furniture",
          "corpus-marker" in corpus_file.read_text(encoding="utf-8"))
    proc = run("count_words.py", corpus_file, "--json")
    rows = {row["section"]: row for row in json.loads(proc.stdout)["rows"]}
    check("F277 header/footer/markers are not charged to the main text",
          rows["abstract"]["words"] == 3 and rows["main text"]["words"] == 5,
          {k: v["words"] for k, v in rows.items()})


# --------------------------------------------------------------------------
# F278 — value-mode notation equivalence is two-way
# --------------------------------------------------------------------------
def check_f278() -> None:
    d = scratch("f278_")
    write(d / "corpus" / "a.txt",
          "The cohort had 1234 cells and another 1,234 cells.\n"
          "We saw \u22125 events and -5 controls.\n")
    run("extract_occurrences.py", "--work", d,
        "--value", "1234", "--value=-5", "--out", d / "o")
    files = sorted((d / "o").glob("occurrences_1234_*.json"))
    data = json.loads(files[0].read_text(encoding="utf-8"))
    by_target = {block["target"]: block for block in data}
    plain = [(o["line"], o["match"]) for o in by_target["1234"]["occurrences"]]
    signed = [(o["line"], o["match"]) for o in by_target["-5"]["occurrences"]]
    check("F278 a plain integer target also matches its comma-grouped spelling",
          ("1,234" in [m for _l, m in plain]) and ("1234" in [m for _l, m in plain]),
          plain)
    check("F278 a target written with ASCII '-' matches the U+2212 spelling",
          "\u22125" in [m for _l, m in signed], signed)

    d = scratch("f278_rev_")
    write(d / "corpus" / "a.txt", "Value 1,234 and 1234; minus \u22125 and -5.\n")
    run("extract_occurrences.py", "--work", d,
        "--value", "1,234", "--value=\u22125", "--out", d / "o")
    files = sorted((d / "o").glob("occurrences_*.json"))
    data = json.loads(files[0].read_text(encoding="utf-8"))
    by_target = {block["target"]: block for block in data}
    grouped = [o["match"] for o in by_target["1,234"]["occurrences"]]
    unicode_minus = [o["match"] for o in by_target["\u22125"]["occurrences"]]
    check("F278 reverse direction: grouped target also matches the plain form",
          "1234" in grouped and "1,234" in grouped, grouped)
    check("F278 reverse direction: U+2212 target also matches ASCII '-'",
          "-5" in unicode_minus and "\u22125" in unicode_minus, unicode_minus)


def main() -> int:
    check_f265()
    check_f266()
    check_f268()
    check_f269()
    check_f272()
    check_f275()
    check_f277()
    check_f278()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL WAVE-2 SKILLS REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

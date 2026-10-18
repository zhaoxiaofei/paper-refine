#!/usr/bin/env python3
"""The 2026-10-17 debug round: the defects an independent audit of `df319ed`
reported and this round reproduced on the tree.

Run:  python3 .paper_test/test_debug_2026_1017.py

The audit reports only seed the list; every check below was re-derived, and
what it pins is the behaviour that was WRONG on the unmodified tree:

  * the M2 reference seed read the STRIPPED paragraph view of the corpus, in
    which `text_source_paragraphs()` has already folded every paragraph onto
    one line and removed the LaTeX scaffolding: a `\\begin{thebibliography}`
    list yielded ZERO rows (the marker `REFERENCE_BIBITEM_RE` is line-anchored
    and the marker text was gone) and a `.bib` file was never read at all (the
    corpus glob had no `*.bib`). The seed now reads the sources' own text while
    every other scan keeps the stripped one;
  * `reset_run_record()` left `agent_session_id` behind, and every caller of it
    replaces the sandbox (`rebuild_sandbox` moves the old one to
    `runs/<id>_try<N>_failed/`, the revalidation reset deletes it): the next
    attempt's continuation adopted a session whose transcript is not in this
    sandbox, i.e. it resumed the superseded round's conversation;
  * the `dsh` help probe reports "declares neither `--json` nor the stdin task
    form" whenever EITHER half is missing, so a build that does carry `--json`
    was told to go looking for a flag it already answers;
  * the compare MCP server's existence check ran on the RAW path string while
    `execFile` was handed `path.resolve()` of it: `existsSync` follows symlinks
    and `..` through the kernel, so `<dir>/link/../../x.docx` validated one
    document and redlined a DIFFERENT one (the converter had the same shape);
  * the skill's `count_words.py` caption rule diverged from the pipeline's own
    (`paper_pipeline._caption_units_from_lines`), which its docstring says it
    mirrors: a bare `Fig. S3` label and a markdown heading did not end a legend
    (so the NEXT legend was subtracted from the main text -- an undercount,
    the direction that reads as a false "within limit"), and `Figures 2 |`,
    `Fig. 3(a).` were not captions at all (an overcount).

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []
TMPDIRS = []
SID = "01a0c963-2222-7000-8000-000000000002"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_debug1017_pipeline", WS / "paper_pipeline.py")
fmt = _load("paper_debug1017_format", WS / "paper_docx_format.py")
cw = _load("paper_debug1017_count_words", WS / "paper-skills/paper-review/scripts/count_words.py")


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def skip(name, why):
    print(f"[skip] {name}  -- {why}")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def write_mini_corpus(src: Path) -> None:
    """One LaTeX manuscript (a `thebibliography`) plus the `.bib` it cites."""
    (src / "manuscript.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\section{Introduction}\n"
        "The aligner is standard; see doi:10.1093/bioinformatics/btp324 for it.\n"
        "\\section*{References}\n"
        "\\begin{thebibliography}{9}\n"
        "\\bibitem{berg2016} Berg JK. Forest dynamics. Ecology 2016. doi:10.1890/15-0001.1\n"
        "\\bibitem{smith2019} Smith A. Soil carbon. Genome Biol 2019. doi:10.1186/gb-2119-0002\n"
        "\\end{thebibliography}\n"
        "\\end{document}\n", encoding="utf-8")
    (src / "refs.bib").write_text(
        "@article{lee2014,\n  title={Tree growth},\n  doi={10.1007/s11295-014-0004}\n}\n"
        "@article{oz2020,\n  title={Root depth},\n  doi={10.1000/zz-2020}\n}\n", encoding="utf-8")


def test_reference_seed_reads_the_production_corpus():
    print()
    print("== the M2 seed reads a LaTeX bibliography and a .bib file ==")
    tmp = scratch("paper_debug1017_corpus_")
    src = tmp / "src"
    src.mkdir()
    write_mini_corpus(src)
    sources = [(src, "", pp.CORPUS_EXCLUDE_TOP)]
    stripped = pp.corpus_text_documents(sources)
    seed_docs = pp.corpus_text_documents(sources, raw_text=True, include_bib=True)
    check("the stripped view is still what every other corpus scan reads",
          [n for n, _rows in stripped] == ["manuscript.tex"]
          and fmt.reference_entries(stripped) == [],
          f"docs={[n for n, _r in stripped]} entries={fmt.reference_entries(stripped)}")
    check("the seed's view carries the .bib file too",
          [n for n, _rows in seed_docs] == ["manuscript.tex", "refs.bib"],
          str([n for n, _r in seed_docs]))
    got = {(d, l): b for d, l, b in fmt.reference_entries(seed_docs)}
    check("`\\bibitem{key}` labels the entry and its own text survives",
          ("manuscript.tex", "berg2016") in got
          and "Forest dynamics" in got[("manuscript.tex", "berg2016")],
          str(sorted(got)))
    check("the `.bib` entries reach the seed without any heading",
          ("refs.bib", "lee2014") in got and ("refs.bib", "oz2020") in got,
          str(sorted(got)))
    rows = fmt.reference_integrity_rows(seed_docs)
    by_doi = {r["identifier"]: r for r in rows}
    check("every DOI of both files is a row now",
          set(by_doi) == {"10.1890/15-0001.1", "10.1186/gb-2119-0002",
                          "10.1007/s11295-014-0004", "10.1000/zz-2020"},
          str(sorted(by_doi)))
    check("the year-token corruption signal still fires on the LaTeX entry",
          "2119" in by_doi["10.1186/gb-2119-0002"]["signal"], by_doi["10.1186/gb-2119-0002"]["signal"])
    check("a DOI that appears ONCE is not reported as a duplicate",
          by_doi["10.1890/15-0001.1"]["signal"] == "" and by_doi["10.1007/s11295-014-0004"]["signal"] == "",
          str([(d, r["signal"]) for d, r in by_doi.items()]))


def test_reset_drops_the_stale_session():
    print()
    print("== a reset run cannot continue a session whose sandbox was replaced ==")
    tmp = scratch("paper_debug1017_reset_")
    sb = tmp / "runs" / "r1_i3"
    (sb / "integrated").mkdir(parents=True)
    ctx = pp.Ctx(tmp)
    cmd = ["codex", "exec", "-"]
    rec = {"id": "r1_i3", "kind": "integrate", "round": 1, "sandbox": "runs/r1_i3",
           "status": "failed", "agent_session_id": SID, "resume_attempts": {SID: 1},
           "postcheck": {"ok": False, "warnings": [],
                         "errors": ["integrated/DIFF_LEDGER.md is missing: it is this "
                                    "stage's ledger"]}}
    argv, key, _why = pp.resume_gate(ctx, rec, cmd)
    check("an unfinished attempt in a live sandbox IS continued (baseline)",
          argv == ["codex", "exec", "resume", SID, "-"] and key == SID, str(argv))
    shutil.rmtree(sb)                     # rebuild_sandbox() replaces the sandbox
    pp.reset_run_record(rec)              # what `retry` and the revalidation pass do
    check("the session id of the replaced sandbox is gone",
          not rec.get("agent_session_id"), str(rec.get("agent_session_id")))
    rec["status"] = "failed"
    rec["postcheck"] = dict(rec.get("postcheck") or {})
    argv2, key2, _why2 = pp.resume_gate(ctx, rec, cmd)
    check("the continuation is refused, and the next attempt is a fresh one",
          argv2 == [] and key2 == "__continue__", f"{argv2} {key2}")


def test_harness_probe_names_the_missing_half():
    print()
    print("== the `dsh` probe names the half its report is about ==")
    tmp = scratch("paper_debug1017_dsh_")
    real_path = os.environ.get("PATH", "")
    try:
        bindir = tmp / "bin"
        bindir.mkdir()
        fake = bindir / "dsh"
        fake.write_text(
            "#!/bin/sh\n"
            'case "$*" in *--help*)\n'
            '  echo "Usage: dsh --profile headless [options]"\n'
            '  echo "  --json   write newline-delimited run events to stdout"\n'
            '  echo "Arguments: task   the task text; words are joined by spaces"\n'
            "  exit 0;;\nesac\nexit 1\n", encoding="utf-8")
        fake.chmod(0o755)
        os.environ["PATH"] = f"{bindir}{os.pathsep}{real_path}"
        pp._HARNESS_PROBE_CACHE.clear()
        problem = pp.dsh_harness_problem(["dsh", "--profile", "headless", "--json", "-"])
        check("a build WITHOUT the stdin task form is still refused",
              "cannot run this pipeline's sessions" in problem, problem[:90])
        check("and the report names the half that is actually missing",
              "no stdin task form" in problem and "declares neither" not in problem,
              problem[:200])
        (bindir / "dsh").write_text(
            "#!/bin/sh\n"
            'case "$*" in *--help*)\n'
            '  echo "Usage: dsh --profile headless [options] [task...]"\n'
            '  echo "Arguments: task  the task text; `-` reads stdin"\n'
            "  exit 0;;\nesac\nexit 1\n", encoding="utf-8")
        (bindir / "dsh").chmod(0o755)
        pp._HARNESS_PROBE_CACHE.clear()
        problem2 = pp.dsh_harness_problem(["dsh", "--profile", "headless", "--json", "-"])
        check("a build WITHOUT `--json` is named the same way",
              "no `--json` flag" in problem2 and "declares neither" not in problem2,
              problem2[:200])
    finally:
        os.environ["PATH"] = real_path
        pp._HARNESS_PROBE_CACHE.clear()


def test_mcp_validates_the_path_it_processes():
    print()
    print("== the DOCX MCP servers validate the path they actually open ==")
    tmp = scratch("paper_debug1017_mcp_")
    real_path = os.environ.get("PATH", "")
    real_compare, real_roots = os.environ.get("DOCXCOMPARE_SH"), os.environ.get("DOCX_MCP_ALLOWED_ROOTS")
    try:
        root = tmp / "root"
        root.mkdir()
        (root / "inner" / "real").mkdir(parents=True)
        (root / "x.docx").write_bytes(b"PK\x03\x04 INSIDE the root")
        (root / "dirlink").symlink_to(root / "inner" / "real")
        # The kernel resolves this through the symlink to <root>/x.docx (which
        # EXISTS, so `existsSync` on the raw string says yes); `path.resolve()`
        # -- the path the server hands to the comparer -- is <work>/x.docx.
        exotic = root / "dirlink" / ".." / ".." / "x.docx"
        log = tmp / "argv.txt"
        stub = tmp / "cmp.sh"
        stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {log}\nexit 0\n', encoding="utf-8")
        stub.chmod(0o755)
        os.environ["DOCXCOMPARE_SH"] = str(stub)
        os.environ.pop("DOCX_MCP_ALLOWED_ROOTS", None)
        if not shutil.which("node"):
            skip("the compare server validates path.resolve()", "node is not on PATH")
            return
        rep = pp.mcp_stdio_tool_call(
            {"command": "node", "args": [str(WS / "mcp-docx-compare" / "index.js")]},
            pp.DOCX_COMPARE_MCP_TOOL,
            {"originalPath": str(exotic), "revisedPath": str(root / "x.docx")}, timeout=180)
        res = rep.get("result") or {}
        text = " ".join(c.get("text", "") for c in (res.get("content") or []))
        check("a path whose RESOLVED form does not exist is refused up front",
              res.get("isError") and "existing absolute .docx file" in text, text.strip()[:140])
        check("and the comparer is never handed a path the server did not check",
              not log.is_file(), log.read_text() if log.is_file() else "")
    finally:
        os.environ["PATH"] = real_path
        if real_compare is None:
            os.environ.pop("DOCXCOMPARE_SH", None)
        else:
            os.environ["DOCXCOMPARE_SH"] = real_compare
        if real_roots is None:
            os.environ.pop("DOCX_MCP_ALLOWED_ROOTS", None)
        else:
            os.environ["DOCX_MCP_ALLOWED_ROOTS"] = real_roots


def _pipeline_caption_words(lines: list) -> int:
    return sum(pp.count_words(" ".join(lines[a:b]))
               for _label, _text, a, b in pp._caption_units_from_lines(lines, with_spans=True))


def _skill_caption_words(lines: list) -> int:
    return sum(cw.count_words(" ".join(lines[a:b])) for a, b in cw.caption_ranges(lines))


def test_caption_rule_parity():
    print()
    print("== the skill's caption rule reads a document as the pipeline does ==")
    fixtures = {
        "a bare `Fig. S3` label ends the legend":
            ["## Results", "", "Figure 1 | Growth curves across the full time series",
             "Fig. S3", "Dose-response of the treated cells, described in the supplement",
             "", "## Discussion", "", "We measured growth in the field.", ""],
        "a markdown heading ends the legend":
            ["## Results", "", "Figure 2 | Soil carbon by depth", "## Discussion",
             "We measured soil carbon in the field over the season.", ""],
        "a wrapped legend keeps its continuation":
            ["## Results", "", "Figure 3 | A very long legend that wraps",
             "over two lines without punctuation at the end",
             "and then the next paragraph starts here.", ""],
        "`Figures 2 |` and `Fig. 3(a).` are captions here too":
            ["## Results", "", "Figures 2 | Soil carbon by depth.", "", "Fig. 3(a). Growth curves.",
             "", "Body text follows.", ""],
        "a body sentence that only NAMES a figure is not a legend":
            ["## Results", "", "Fig. 2 shows the growth curves of all cohorts.", "",
             "Body text follows.", ""],
    }
    for name, lines in fixtures.items():
        want, got = _pipeline_caption_words(lines), _skill_caption_words(lines)
        check(name, want == got, f"pipeline={want} skill={got}")


def main() -> int:
    test_reference_seed_reads_the_production_corpus()
    test_reset_drops_the_stale_session()
    test_harness_probe_names_the_missing_half()
    test_mcp_validates_the_path_it_processes()
    test_caption_rule_parity()
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL 2026-10-17 DEBUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

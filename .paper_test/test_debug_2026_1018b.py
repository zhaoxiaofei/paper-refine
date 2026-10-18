#!/usr/bin/env python3
"""The 2026-10-18 second debug round: defects re-derived from the find stage.

Run:  python3 .paper_test/test_debug_2026_1018b.py

Every check below was reproduced on the unmodified tree first.  The candidate
reports only seeded the list; the assertions pin what was actually wrong:

  * F01 a symlinked stage package root made the destructive sweeps delete and
    rewrite files outside the run sandbox;
  * F02 `coverletter`/`plainLetter` role names were understood by the
    orchestrator but not by the formatter or the bundled review scripts, and
    `supp`/`main` were still matched as substrings there;
  * F03 an unparseable document was reported as "0 hand-off markers" instead of
    UNKNOWN (the scanner returned it in `unparsed`);
  * F04 a one-sided cover-letter preference printed "no preference" and
    "None-200";
  * F05 the docs and `count_words.py` still claimed a 650-word default total cap
    that the shipped profiles and the pipeline had deliberately removed;
  * F07 ordinary stdout prose containing an overflow phrase was classified as a
    provider context overflow;
  * F08 any nested `work/` directory counted as visual-render evidence, not just
    the documented top-level `OUT/work/`;
  * F09 the unused `@modelcontextprotocol/sdk` dependency stayed pinned at the
    vulnerable 1.30.0 in both MCP lockfiles;
  * F10 `.paper_test/README.md` advertised a stdlib-only harness that imports
    `python-docx` and `openpyxl`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []
TMPDIRS = []


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_debug1018b_pipeline", WS / "paper_pipeline.py")


def check(name: str, cond, detail: str = "") -> None:
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


# ---------------------------------------------------------------------------
# F01: a symlinked package root is never a destructive-walk target
# ---------------------------------------------------------------------------
def test_symlinked_package_root() -> None:
    print("\n== F01: a symlinked package root cannot touch files outside the run ==")
    root = scratch("paper_debug1018b_symlink_")
    outside = root / "outside"
    outside.mkdir()
    (outside / "victim.pyc").write_text("x", encoding="utf-8")
    doc = outside / "doc.md"
    doc.write_text("See code/analysis.py for the run.\n", encoding="utf-8")
    link = root / "pkg"
    os.symlink(outside, link)

    res = pp.strip_non_shippable_files_in_dir(link)
    check("F01 the non-shippable sweep refuses a symlinked root",
          not (res.get("removed") or []) and (outside / "victim.pyc").is_file(),
          f"{res!r} victim={ (outside / 'victim.pyc').is_file() }")
    rep = pp.strip_dangling_references_in_dir(link, ["code"], "probe")
    check("F01 the PKG-2 rewrite refuses a symlinked root",
          not (rep.get("files") or [])
          and doc.read_text(encoding="utf-8") == "See code/analysis.py for the run.\n",
          json.dumps(rep)[:300])

    # The stage postcheck entry point must fail the stage before any of its
    # earlier helpers (hand-off README, format normalization) write through it.
    sb = root / "runs" / "r1_w1"
    sb.mkdir(parents=True)
    stage_out = sb / "rewritten"
    os.symlink(outside, stage_out)
    ctx = pp.Ctx(root)
    ctx.cfg = {"format_fix": "on", "author_to_complete": "readme"}
    rec = {"id": "r1_w1", "kind": "rewrite", "round": 1,
           "sandbox": "runs/r1_w1"}
    errs, warns = [], []
    pp._format_fix_stage_package(ctx, rec, stage_out, warns, errs)
    check("F01 the stage postcheck REJECTS a symlinked package root",
          bool(errs) and "symlink" in " ".join(errs).lower(), f"errs={errs!r}")
    check("F01 the rejected package still holds its outside files",
          (outside / "victim.pyc").is_file()
          and doc.read_text(encoding="utf-8") == "See code/analysis.py for the run.\n",
          f"victim={(outside / 'victim.pyc').is_file()} doc={doc.read_text(encoding='utf-8')!r}")


# ---------------------------------------------------------------------------
# F02: one role vocabulary across the orchestrator, formatter and review scripts
# ---------------------------------------------------------------------------
def test_document_roles_agree() -> None:
    print("\n== F02: coverletter/plainLetter are one role in every module ==")
    base = WS / "paper-skills" / "paper-review" / "scripts"
    cw = _load("paper_debug1018b_cw", base / "count_words.py")
    cc = _load("paper_debug1018b_cc", base / "convert_corpus.py")
    fm = _load("paper_debug1018b_fmt", WS / "paper_docx_format.py")
    extract = {
        n: _load(f"paper_debug1018b_{n}", base / f"{n}.py")
        for n in ("extract_acronyms", "extract_citations", "extract_numbers")
    }
    all_scripts = {
        "count_words": cw, "convert_corpus": cc,
        "extract_acronyms": extract["extract_acronyms"],
        "extract_citations": extract["extract_citations"],
        "extract_numbers": extract["extract_numbers"],
        "extract_occurrences": _load("paper_debug1018b_eo", base / "extract_occurrences.py"),
        "enumerate_conventions": _load("paper_debug1018b_ec",
                                        base / "enumerate_conventions.py"),
    }

    check("F02 the orchestrator keeps coverletter as the cover letter",
          pp.docx_document_role("coverletter.docx") == "cover"
          and pp._is_cover_letter_lines([], "coverletter.md"))
    check("F02 the orchestrator understands camelCase plainLetter",
          pp.docx_document_role("plainLetter.md") == "cover"
          and pp._is_cover_letter_lines([], "plainLetter.md"))
    check("F02 the formatter understands concatenated coverletter",
          fm.is_cover_letter_doc("coverletter.docx")
          and fm.is_cover_letter_doc("plainLetter.docx")
          and not fm.is_cover_letter_doc("support.docx"))
    check("F02 count_words names both cover-letter spellings",
          cw.is_cover_letter("", "coverletter.md")
          and cw.is_cover_letter("", "plainLetter.md"))
    check("F02 convert_corpus names both cover-letter spellings",
          cc.guess_role("coverletter.docx") == "cover letter"
          and cc.guess_role("plainLetter.md") == "cover letter")
    check("F02 convert_corpus no longer reads support/suppress as supplementary",
          cc.guess_role("support.docx") != "supplementary"
          and cc.guess_role("suppress.md") != "supplementary",
          f"support={cc.guess_role('support.docx')!r} "
          f"suppress={cc.guess_role('suppress.md')!r}")
    check("F02 convert_corpus no longer reads 'main' inside domain_notes",
          cc.guess_role("domain_notes.md") != "main text",
          cc.guess_role("domain_notes.md"))
    check("F02 convert_corpus still reads a real supplement name",
          cc.guess_role("supp-info.txt") == "supplementary",
          cc.guess_role("supp-info.txt"))

    bad_cover = {name: mod._COVER_WORD_RE.search("coverletter.md") is None
                 for name, mod in all_scripts.items()
                 if hasattr(mod, "_COVER_WORD_RE")}
    bad_plain = {name: mod._COVER_WORD_RE.search("plainLetter.md") is None
                 for name, mod in all_scripts.items()
                 if hasattr(mod, "_COVER_WORD_RE")}
    check("F02 every bundled script recognises concatenated coverletter",
          not any(bad_cover.values()), str(bad_cover))
    check("F02 every bundled script recognises camelCase plainLetter",
          not any(bad_plain.values()), str(bad_plain))
    false_pos = {name: [n for n in ("discovery.md", "coverage_table.txt",
                                    "recovered_notes.tex")
                        if mod._COVER_WORD_RE.search(n)]
                 for name, mod in all_scripts.items()
                 if hasattr(mod, "_COVER_WORD_RE")}
    check("F02 the word rule still refuses the old cover substrings",
          not any(false_pos.values()), str(false_pos))

    for name, mod in extract.items():
        roles = {n: mod.classify_context(n) for n in
                 ("support.docx", "suppress.md", "supp_info.txt")}
        check(f"F02 {name}: supp-word roles are word-anchored",
              roles["support.docx"] == "main text"
              and roles["suppress.md"] == "main text"
              and roles["supp_info.txt"] == "supplementary", str(roles))


# ---------------------------------------------------------------------------
# F03: an unparseable document is UNKNOWN, not zero markers
# ---------------------------------------------------------------------------
def test_unparsed_marker_state() -> None:
    print("\n== F03: a document the marker scan cannot read is UNKNOWN ==")
    root = scratch("paper_debug1018b_unparsed_")
    pkg = root / "revised"
    pkg.mkdir()
    (pkg / "broken.docx").write_bytes(b"not a zip")
    scan = pp.scan_placeholders_in_sources([(pkg, "", ())])
    check("F03 the scanner still reports the file as unparsed",
          scan.get("unparsed") == ["broken.docx"] and scan.get("count") == 0,
          str(scan))

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.cfg = {"author_to_complete": "readme"}
    ctx.state = {}
    errs, warns = [], []
    rep = pp.placeholder_residual_report(ctx, pkg, [(pkg, "", ())],
                                         "revise", True, errs, warns)
    check("F03 readme/off mode GATES an unreadable marker document",
          bool(errs) and "broken.docx" in str(rep.get("handoff_marker_scan_error")),
          f"errs={errs!r} rep={rep!r}")
    check("F03 the report records which files were unreadable",
          rep.get("handoff_marker_unparsed") == ["broken.docx"], str(rep))

    ctx.cfg = {"author_to_complete": "document"}
    errs2, warns2 = [], []
    rep2 = pp.placeholder_residual_report(ctx, pkg, [(pkg, "", ())],
                                          "revise", True, errs2, warns2)
    check("F03 document mode does not fail on the same unreadable file",
          not errs2, f"errs={errs2!r}")
    check("F03 document mode still records the unknown marker state",
          rep2.get("handoff_marker_unparsed") == ["broken.docx"] and bool(warns2),
          f"warns={warns2!r}")

    # A PDF/PPT rendering is accepted submission content the pipeline does not
    # edit: it is reported as UNKNOWN, but it must not fail a normal package
    # (the repository's recovery tests ship a reporting-summary PDF).
    pdf_pkg = root / "pdf_only"
    pdf_pkg.mkdir()
    (pdf_pkg / "reporting-summary.pdf").write_bytes(b"%PDF-not-a-real-pdf")
    ctx.cfg = {"author_to_complete": "readme"}
    errs3, warns3 = [], []
    rep3 = pp.placeholder_residual_report(ctx, pdf_pkg, [(pdf_pkg, "", ())],
                                          "revise", True, errs3, warns3)
    check("F03 an accepted PDF rendering is REPORTED, not gated",
          not errs3
          and rep3.get("handoff_marker_unparsed") == ["reporting-summary.pdf"]
          and bool(warns3),
          f"errs={errs3!r} rep={rep3!r} warns={warns3!r}")


# ---------------------------------------------------------------------------
# F04: a one-sided preference is printed as that side, never "None"
# ---------------------------------------------------------------------------
def test_one_sided_cover_preference() -> None:
    print("\n== F04: one-sided cover-letter preferences are rendered correctly ==")
    lim = {"cover letter": {"min": None, "max": 200, "total_max": None,
                            "source": "Frontiers"}}
    row = pp._cover_letter_row(["Dear Editor,", "word " * 210], "cover.md",
                               limits=lim)
    note = pp.length_note({"rows": [row],
                           "limits": {"cover letter": lim["cover letter"],
                                      "abstract": {"cap": None},
                                      "main text": {"cap": None}},
                           "venue": "frontiers-in-immunology"})
    check("F04 a max-only row says 'at most 200', not 'no preference'",
          "at most 200" in row["note"]
          and "configures no cover-letter preference" not in row["note"],
          row["note"])
    check("F04 the decision note says 'at most 200', not 'None-200'",
          "at most 200" in note and "None-200" not in note, note)

    lim2 = {"cover letter": {"min": 300, "max": None, "total_max": None,
                             "source": "x"}}
    row2 = pp._cover_letter_row(["Dear Editor,", "word " * 10], "cover.md",
                                limits=lim2)
    check("F04 a min-only row says 'at least 300', not '300-None'",
          "at least 300" in row2["note"] and "300-None" not in row2["note"],
          row2["note"])


# ---------------------------------------------------------------------------
# F05: the shipped profiles and the pipeline have no 650-word total cap
# ---------------------------------------------------------------------------
def test_default_total_cap_is_absent() -> None:
    print("\n== F05: no invented 650-word total cap ==")
    base = WS / "paper-skills" / "paper-review" / "scripts"
    cw = _load("paper_debug1018b_cw_f05", base / "count_words.py")
    check("F05 the pipeline records no default total cap",
          pp.length_limits()["cover letter"]["total_max"] is None
          and pp.COVER_LETTER_TOTAL_MAX_WORDS is None)
    check("F05 count_words records no built-in total cap",
          cw.COVER_LETTER_TOTAL_MAX is None, str(cw.COVER_LETTER_TOTAL_MAX))

    root = scratch("paper_debug1018b_cap_")
    letter = root / "cover.md"
    letter.write_text("Dear Editor,\n\n" + ("word " * 660) + "\n\nSincerely,\nA. Author\n",
                      encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(base / "count_words.py"), str(letter),
         "--section", "cover-letter", "--json"],
        capture_output=True, text=True, timeout=120)
    rows = json.loads(proc.stdout or "{}").get("rows") or []
    total = [r for r in rows if r.get("section") == "cover letter total"]
    check("F05 a no-profile 660-word letter is not over an invented cap",
          proc.returncode == 0 and total
          and total[0].get("total_max") is None
          and total[0].get("over_limit") is False,
          f"rc={proc.returncode} total={total!r} err={proc.stderr[-200:]!r}")

    readme = (WS / "README.md").read_text(encoding="utf-8")
    skill = (WS / "paper-skills/paper-review/SKILL.md").read_text(encoding="utf-8")
    identify = (WS / "paper-skills/prompts/identify_issues.prompt.md").read_text(
        encoding="utf-8")
    address = (WS / "paper-skills/prompts/adress_issues.prompt.md").read_text(
        encoding="utf-8")
    check("F05 README no longer claims a default 650-word cap",
          "650-word operator cap" not in readme
          and "ships with the default profile" not in readme,
          "README still names the removed cap")
    check("F05 SKILL/prompts no longer claim 'capped at 650 words by default'",
          "capped at 650 words by default" not in skill
          and "capped at 650 words by default" not in identify
          and "capped at 650 words by default" not in address)
    revise_skill = (WS / "paper-skills/paper-revise/SKILL.md").read_text(
        encoding="utf-8")
    skills_readme = (WS / "paper-skills/README.md").read_text(encoding="utf-8")
    check("F05 the revise SKILL/paper-skills README carry no 650-word default",
          "capped at 650 words by default" not in revise_skill
          and "capped at 650 words by default" not in skills_readme)


# ---------------------------------------------------------------------------
# F07: ordinary stdout prose is not a provider context overflow
# ---------------------------------------------------------------------------
def test_context_overflow_prose_is_not_an_error() -> None:
    print("\n== F07: stdout manuscript prose is not an overflow record ==")
    negatives = [
        "The manuscript's limitations say the maximum context length of the "
        "earlier model was 8k tokens.",
        "The results were: 413 cells in the request group were too large to analyse.",
        # A line that STARTS with the count is prose too; only an HTTP-status
        # shape (`413 Payload Too Large`) is an error record.
        "413 cells in the request group were too large to analyse.",
        "Input: the maximum context length of the earlier model was 8k tokens.",
    ]
    for text in negatives:
        check(f"F07 prose stays unclassified: {text[:38]!r}",
              pp.agent_failure_kind(text, "error: compile failed") == "",
              pp.agent_failure_kind(text, "error: compile failed"))
    positives = (
        "ERROR: unexpected status 413 Payload Too Large",
        "context_length_exceeded",
        "HTTP 413: Request Too Large",
        "Payload Too Large",
        "413 Payload Too Large",
        "Error: 413 Payload Too Large",
        "Error: 400 Your input exceeds the context window of this model",
        "maximum context length is 4096 tokens",
        "prompt is too long: 250000 tokens > 200000 maximum",
        "too many tokens in the request",
        # A provider's structured error on stdout was classified before the
        # filter; both single-line and pretty-printed JSON must stay visible.
        '{"error":{"message":"maximum context length is 4096 tokens"}}',
        '{\n "error": {\n  "message": "maximum context length is 4096 tokens"\n }\n}',
        # An HTML error page on stdout is an error channel too.
        "<title>413 Request Entity Too Large</title>",
    )
    for text in positives:
        check(f"F07 the real form still classifies: {text[:38]!r}",
              pp.agent_failure_kind("", text) == "context_overflow", text)

    sb = scratch("paper_debug1018b_exec_")
    (sb / "PROMPT.md").write_text("noop", encoding="utf-8")
    rec = {"id": "r1_review", "kind": "review", "round": 1, "sandbox": str(sb)}
    cmd = [sys.executable, "-c",
           "print(\"The results were: 413 cells in the request group were too "
           "large to analyse.\"); raise SystemExit(1)"]
    res = pp._execute_attempt_in(sb, rec, cmd, 30)
    check("F07 the CALLER does not read prose stdout as an overflow",
          res.get("failure_kind") == "", str(res.get("failure_kind")))


# ---------------------------------------------------------------------------
# F08: only the documented top-level work/ holds render evidence
# ---------------------------------------------------------------------------
def test_visual_evidence_is_top_level_work_only() -> None:
    print("\n== F08: only the top-level work/ holds rendered-page evidence ==")
    root = scratch("paper_debug1018b_vis_")
    (root / "work").mkdir()
    (root / "work" / "page-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "figures" / "work").mkdir(parents=True)
    (root / "figures" / "work" / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "figures" / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    got = [p.relative_to(root).as_posix() for p in pp.render_evidence_files([root])]
    check("F08 a nested figures/work image is NOT render evidence",
          got == ["work/page-1.png"], str(got))

    art = root / "VISUAL_CHECK.md"
    art.write_text("Every page was rendered and looked at.\n", encoding="utf-8")
    with mock.patch.object(pp, "visual_tools_available", return_value=True):
        errs, warns = [], []
        pp.check_visual_artifact(art, "the visual record", errs, warns,
                                 render_roots=[root])
        check("F08 the gate passes with a real top-level render", not errs,
              f"errs={errs!r}")
        (root / "work" / "page-1.png").unlink()
        errs, warns = [], []
        pp.check_visual_artifact(art, "the visual record", errs, warns,
                                 render_roots=[root])
        check("F08 the gate fails with only a nested figures/work image",
              bool(errs), f"errs={errs[:1]!r}")


# ---------------------------------------------------------------------------
# F09: the unused, vulnerable SDK is not a dependency of either MCP server
# ---------------------------------------------------------------------------
def test_mcp_sdk_dependency_removed() -> None:
    print("\n== F09: the vulnerable unused SDK is gone from both servers ==")
    for name in ("mcp-docx-converter", "mcp-docx-compare"):
        pkg = WS / name
        manifest = json.loads((pkg / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((pkg / "package-lock.json").read_text(encoding="utf-8"))
        deps = manifest.get("dependencies") or {}
        locked = lock.get("packages") or {}
        check(f"F09 {name} no longer declares the SDK",
              "@modelcontextprotocol/sdk" not in deps, str(sorted(deps)))
        check(f"F09 {name} lockfile no longer carries the SDK",
              "node_modules/@modelcontextprotocol/sdk" not in locked,
              str([k for k in locked if "modelcontextprotocol" in k]))
        check(f"F09 {name} imports the server package, not the SDK",
              "@modelcontextprotocol/server" in deps
              and (pkg / "index.js").read_text(encoding="utf-8").count(
                  "@modelcontextprotocol/sdk") == 0)


# ---------------------------------------------------------------------------
# F10: the harness README names its real test dependencies
# ---------------------------------------------------------------------------
def test_harness_readme_lists_dependencies() -> None:
    print("\n== F10: the harness README names python-docx and openpyxl ==")
    readme = (WS / ".paper_test/README.md").read_text(encoding="utf-8")
    check("F10 the suite dependencies are documented",
          "python-docx" in readme and "openpyxl" in readme,
          readme[:220])
    check("F10 the stdlib-only claim is gone",
          "They need nothing but" not in readme, readme[:220])


def main() -> int:
    test_symlinked_package_root()
    test_document_roles_agree()
    test_unparsed_marker_state()
    test_one_sided_cover_preference()
    test_default_total_cap_is_absent()
    test_context_overflow_prose_is_not_an_error()
    test_visual_evidence_is_top_level_work_only()
    test_mcp_sdk_dependency_removed()
    test_harness_readme_lists_dependencies()
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL 2026-10-18b DEBUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

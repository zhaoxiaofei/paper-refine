#!/usr/bin/env python3
"""Structural invariants of the simplified tree (2026-10-25).

Run:  python3 .paper_test/test_source_layout_2026_1025.py

* every maintained source file is <= 10,000 lines;
* the two loaders are thin and their ordered parts directories exist;
* the input-area names and the removed compatibility aliases stay removed;
* the shared CSV writer is the ONLY `csv.DictWriter` site;
* `--champion-select` and its persisted `set-champion-select` command exist.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sys
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def maintained_sources() -> list:
    """Every maintained .py file (the tree's own code, not fixtures/scratch).

    os.walk with pruning, not rglob: the repo carries multi-GB scratch trees
    (paper_rounds, debug_runs, test logs) and walking them just to discard them
    made this structural check take minutes.
    """
    skip = {".git", "__pycache__", "tmp", "debug_runs", "paper_rounds", "audit_data",
            ".pytest_cache", ".ruff_cache", "node_modules", ".paper_test", "media",
            "uploads", "revision_history"}
    out = []
    for root, dirs, files in os.walk(WS):
        dirs[:] = sorted(d for d in dirs if d not in skip)
        for name in files:
            if name.endswith(".py"):
                out.append(Path(root) / name)
    return sorted(out)


def test_line_limit():
    print("\n== every source file is <= 10,000 lines ==")
    offenders = []
    for p in maintained_sources():
        n = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        if n > 10000:
            offenders.append(f"{p.relative_to(WS)}: {n}")
    check("no maintained source file exceeds 10,000 lines", not offenders, str(offenders))
    for name in ("paper_pipeline.py", "paper_docx_format.py"):
        n = len((WS / name).read_text(encoding="utf-8").splitlines())
        check(f"{name} is a thin loader (<= 1,000 lines)", n <= 1000, f"{n} lines")


def test_loaders_and_parts():
    print("\n== loaders execute ordered parts; the parts directories exist ==")
    for stem in ("paper_pipeline", "paper_docx_format"):
        parts = WS / f"{stem}_parts"
        files = sorted(parts.glob("p[0-9][0-9]_*.py"))
        check(f"{stem}_parts/ exists with ordered parts", parts.is_dir() and bool(files),
              str(files[:2]))
        check(f"{stem}_parts/ has no part over 10,000 lines",
              all(len(p.read_text(encoding="utf-8").splitlines()) <= 10000 for p in files))
        # Every part compiles as a real file on its own (no syntax fragments).
        bad = []
        for p in files:
            try:
                ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError as e:
                bad.append(f"{p.name}: {e}")
        check(f"{stem}_parts/ files are real Python sources", not bad, str(bad))
    pp = load("layout_pipeline", WS / "paper_pipeline.py")
    fmt = load("layout_format", WS / "paper_docx_format.py")
    check("the loaded pipeline exposes its public helpers",
          all(hasattr(pp, n) for n in ("champion_select_of", "auto_champion_vid",
                                       "write_csv_atomic", "module_manifest", "main")))
    check("the loaded formatter exposes its public helpers",
          all(hasattr(fmt, n) for n in ("analyse_package", "tier_of", "write_json", "main")))
    manifest = pp.module_manifest(WS)
    check("the module manifest records both parts directories",
          manifest.get("paper_pipeline_parts") and manifest.get("paper_docx_format_parts"),
          str({k: (str(v)[:8] if v else None) for k, v in manifest.items()}))


def test_removed_compatibility():
    print("\n== the removed compatibility spellings stay removed ==")
    pp = load("layout_pipeline_compat", WS / "paper_pipeline.py")
    fmt = load("layout_format_compat", WS / "paper_docx_format.py")
    check("no legacy input-area constants", not any(
        hasattr(pp, n) for n in ("PRISTINE_DIR_LEGACY", "RAW_DATA_DIR_LEGACY",
                                 "JOURNAL_MODE_NONE", "JOURNAL_MODE_ALIASES")))
    check("no legacy-name resolver", not any(
        hasattr(pp, n) for n in ("existing_dirname", "canonicalize_raw_data_dir")))
    check("input-area names are canonical", pp.PRISTINE_DIRNAMES == ("non_revised",)
          and pp.RAW_DATA_DIRNAMES == ("raw_data",))
    check("the formatter's evidence areas agree",
          fmt.RAW_DATA_DIRNAMES == ("raw_data",) and "raw_figs" not in fmt.EVIDENCE_DIRNAMES)
    check("the legacy author-to-complete values are gone",
          "on" not in pp.AUTHOR_TO_COMPLETE_MODES
          and "document" in pp.AUTHOR_TO_COMPLETE_MODES)
    check("the legacy revision-mode alias is gone", "none" not in pp.JOURNAL_MODES)
    check("the shared CSV writer is defined", hasattr(pp, "write_csv_atomic"))
    # No second writer implementation outside the helper.
    sites = []
    for p in maintained_sources():
        if p.name == "p04_utils.py" and p.parent.name == "paper_pipeline_parts":
            continue
        if "csv.DictWriter" in p.read_text(encoding="utf-8", errors="replace"):
            sites.append(str(p.relative_to(WS)))
    check("csv.DictWriter exists only in the shared helper", not sites, str(sites))


def test_champion_select_cli():
    print("\n== the champion-selection surface exists ==")
    pp = load("layout_pipeline_cs", WS / "paper_pipeline.py")
    parser = pp.build_parser()
    # Parse a representative invocation without touching a root.
    ns = parser.parse_args(["run", "--root", "/tmp/x", "--champion-select", "integrate"])
    check("run accepts --champion-select integrate", ns.champion_select == "integrate")
    ns = parser.parse_args(["setup", "--source", "/tmp/x", "--root", "/tmp/y"])
    check("the flag defaults to None (the config/default decides)",
          ns.champion_select is None)
    ns = parser.parse_args(["set-champion-select", "revise", "--root", "/tmp/x"])
    check("set-champion-select persists revise", ns.mode == "revise")
    ns = parser.parse_args(["decide", "--root", "/tmp/x", "--champion-select", "judge"])
    check("decide accepts the judge override", ns.champion_select == "judge")


def test_fact_preservation_prompts():
    print("\n== every role is told that a fact is not a removal surface ==")
    pp = load("layout_pipeline_facts", WS / "paper_pipeline.py")
    check("the shared decision block carries rule D8",
          "A FACT IS NOT A REMOVAL SURFACE" in pp.SHARED_DECISION_BLOCK)
    revise_flat = " ".join(pp.REVISE_DIRECTIVES.split())
    check("the revise directives name the fact-preserving repair",
          "FACT-PRESERVING REPAIR" in revise_flat
          and "never by removing the sentence" in revise_flat)
    check("the audit may drop an invented requirement and a delete-the-fact remedy",
          "invents a requirement the corpus's recorded rules do not" in pp.AUDIT_DIRECTIVES
          and "no confirmed finding may be resolved by deleting the fact" in pp.AUDIT_DIRECTIVES)
    check("the review discovery prompt forbids invented structural findings",
          "Discovery findings obey shared rule D8" in pp.REVIEW_DIRECTIVES)
    check("the probe prompt forbids inventing a structural requirement",
          "Do NOT invent a structural requirement" in pp.PROBE_DIRECTIVES)


def test_operational_contract():
    print("\n== runner default, AGENTS binding and the frozen-root rule ==")
    run_all = load("layout_run_all", WS / ".paper_test" / "run_all.py")
    check("run_all.py defaults to 32 jobs", getattr(run_all, "DEFAULT_JOBS", None) == 32,
          str(getattr(run_all, "DEFAULT_JOBS", None)))
    readme = (WS / "README.md").read_text(encoding="utf-8")
    flat_readme = " ".join(readme.split())
    check("README documents the 32-job default",
          "32 jobs by default" in flat_readme, flat_readme[:200])
    check("README says AGENTS.md is binding and a violation is a bug",
          "is binding" in flat_readme and "must be respected" in flat_readme
          and "violation of any such rule is a" in flat_readme
          and "bug" in flat_readme)
    agents = (WS / "AGENTS.md").read_text(encoding="utf-8")
    flat_agents = " ".join(agents.split())
    check("AGENTS.md says a rule violation is a bug",
          "violation of any rule is a bug" in flat_agents)
    check("AGENTS.md requires setup to freeze every runtime file into --root",
          "A root runs a frozen copy" in flat_agents
          and "must copy every file the running project executes or reads by path" in flat_agents)
    check("AGENTS.md separates finding generation from finding-consuming repair",
          "Rule 1A. **Detection and repair are separate.**" in agents
          and "Rule 1B. **Every finding-consuming session independently re-verifies" in agents
          and "finding-generating" in agents and "finding-consuming" in agents)
    check("AGENTS.md names the integrator's donor set as a caller-supplied candidate source",
          "caller-supplied candidate source" in agents
          and "generates no new finding" in agents
          and "invents no third reading" in agents)
    check("AGENTS.md limits the language/format exception to the role's own candidate",
          "in-role mechanical language/format pass" in agents
          and "may not change a claim, fact" in agents)


def main() -> int:
    test_line_limit()
    test_loaders_and_parts()
    test_removed_compatibility()
    test_champion_select_cli()
    test_fact_preservation_prompts()
    test_operational_contract()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL SOURCE-LAYOUT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

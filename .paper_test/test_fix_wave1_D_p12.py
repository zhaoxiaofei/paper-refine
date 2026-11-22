#!/usr/bin/env python3
"""Regression tests for fix-bugs wave 1, batch D_p12 (p12_conflicts_decide.py).

  F11  a too-large text file is a PKG-1 coverage gap, never a clean scan
  F12  PKG-12 parses the `p-value` / `P value` cell spellings
  F13  PKG-15 compares rows whose mean uses U+2212
  F79  PKG-12 scans a row with an empty edge cell
  F80  PKG-22 matches contracted negations (incl. U+2019)
  F81  PKG-4 expands em-dash and `to` ranges
  F90  wildcards inside an extglob alternative are globs, not literals
  F120 p exactly at a strict caption's alpha is not significant
  F121 a coverage-gap row keeps its document
  F198 a coverage-gap row prints no `line 0`
  F127 sync-code leaves a root-only asset dir unmanaged, not "up to date"

Run: python3 .paper_test/test_fix_wave1_D_p12.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
FAILS = []


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_fix_wave1_D_p12", WS / "paper_pipeline.py")


def check(name: str, cond: bool, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def pkg12(caption: str, rows: list) -> Path:
    d = scratch("p12_mcb_")
    (d / "mcb_table.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\begin{table}\n" + caption +
        "\n\\begin{tabular}{lllll}\n" + "\n".join(rows) + " \\\\\n\\end{tabular}\n"
        "\\end{table}\n\\end{document}\n", "utf-8")
    return d


def pkg12_rows(d: Path) -> list:
    return [r for r in pp.scan_mcb_rule_conflicts(d) if r.get("rule") == "PKG-12"]


# ---------------------------------------------------------------------------
def test_f11_large_file_gap() -> None:
    print("\n== F11: a too-large file is a PKG-1 coverage gap ==")
    d = scratch("p12_f11_")
    (d / "notes.md").write_text("# Notes\n\nREPLACEMENT LEDGER\n", "utf-8")
    check("F11 the small control file yields a real finding",
          bool([r for r in pp.internal_artifact_rows(d) if not r.get("gap")]))
    gen = (d / "big_notes.md").open("w", encoding="utf-8")
    gen.write("# Big\n\nREPLACEMENT LEDGER\n" + ("x" * 99 + "\n") * 26000)
    gen.close()
    rows = pp.internal_artifact_rows(d)
    gaps = [r for r in rows if r.get("gap")]
    check("F11 a file over the text limit is reported as a coverage gap",
          len(gaps) == 1 and gaps[0].get("file") == "big_notes.md"
          and gaps[0].get("advisory") is True, json.dumps(gaps)[:300])


def test_f12_p_value_spelling() -> None:
    print("\n== F12: PKG-12 parses `p-value` / `P value` ==")
    check("F12 _parse_p reads `p-value = 0.30`",
          pp._parse_p("p-value = 0.30") == 0.3, repr(pp._parse_p("p-value = 0.30")))
    check("F12 _parse_p reads `P value < 0.001`",
          pp._parse_p("P value < 0.001") == 0.001, repr(pp._parse_p("P value < 0.001")))
    cap = "\\caption{Small p and an interval entirely below 0 mark a significant difference.}"
    rows = pkg12_rows(pkg12(cap, ["G1 & 10 & p-value = 0.30 & 1 & [0.1, 0.4]"]))
    check("F12 a `p-value` row with a contradiction is reported", len(rows) == 1,
          json.dumps(rows)[:300])


def _pooled_pkg(units_b: str, mcb_b: str) -> Path:
    d = scratch("p12_f13_")
    (d / "Fig_mcb_pooled.tsv").write_text(
        "method\tn_units\tmean\nA\t9\t69.37\nB\t9\t" + mcb_b + "\n", "utf-8")
    (d / "Fig_pooled_units.tsv").write_text(
        "method\tn_units\tmean\nA\t21\t80.94\nA\t21\t80.90\n"
        "B\t21\t-27.70\nB\t21\t" + units_b + "\n", "utf-8")
    return d


def test_f13_unicode_minus() -> None:
    print("\n== F13: PKG-15 parses a U+2212 mean ==")
    # The typographic minus appears in the sibling units table ...
    rows = [r for r in pp.scan_pooled_table_mismatches(_pooled_pkg("\u221227.80", "-12.5"))
            if r.get("rule") == "PKG-15"]
    check("F13 a U+2212 mean in the units table is compared, not dropped",
          {r.get("reference") for r in rows} == {"A", "B"}, json.dumps(rows)[:400])
    # ... and in the pooled table itself.
    rows = [r for r in pp.scan_pooled_table_mismatches(_pooled_pkg("-27.80", "\u221212.5"))
            if r.get("rule") == "PKG-15"]
    check("F13 a U+2212 mean in the pooled table is compared, not dropped",
          {r.get("reference") for r in rows} == {"A", "B"}, json.dumps(rows)[:400])


def test_f79_empty_edge_cell() -> None:
    print("\n== F79: PKG-12 scans a row with an empty edge cell ==")
    cap = "\\caption{Small p and an interval entirely below 0 mark a significant difference.}"
    check("F79 a trailing empty cell does not drop the row",
          len(pkg12_rows(pkg12(cap, ["G1 & 10 & 0.03 & 1 & [-0.2, 0.5] &"]))) == 1)
    check("F79 a leading empty cell does not drop the row",
          len(pkg12_rows(pkg12(cap, ["& G1 & 10 & 0.03 & 1 & [-0.2, 0.5]"]))) == 1)


def test_f80_contractions() -> None:
    print("\n== F80: PKG-22 matches contracted negations ==")
    for text in ("This doesn't demonstrate the effect.",
                 "This doesn\u2019t demonstrate the effect.",
                 "This isn't an intrinsic property.",
                 "This shouldn't be read as evidence."):
        check(f"F80 negation matched: {text!r}",
              bool(pp.NEGATED_NOTE_RE.search(text)))


def test_f81_ranges() -> None:
    print("\n== F81: PKG-4 expands em-dash / `to` ranges ==")
    check("F81 an em-dash range cites its interior label",
          pp._pkg4_cited_labels("2\u20144") == ["2", "3", "4"],
          repr(pp._pkg4_cited_labels("2\u20144")))
    check("F81 a `to` range cites its interior label",
          pp._pkg4_cited_labels("2 to 4") == ["2", "3", "4"],
          repr(pp._pkg4_cited_labels("2 to 4")))
    m = pp.PKG4_FIGURE_CITE_RE.search("Figures 2\u20144")
    check("F81 the citation regex captures the em-dash range",
          bool(m) and m.group("labels") == "2\u20144",
          m.group("labels") if m else None)


def test_f90_extglob() -> None:
    print("\n== F90: wildcards inside @() alternatives are globs ==")
    rx = pp._extglob_to_regex("@(ms-*.docx|ms-*.pdf)")
    check("F90 @(ms-*.docx|ms-*.pdf) matches ms-1.docx",
          bool(rx and rx.match("ms-1.docx")))
    check("F90 the same pattern matches ms-1.pdf", bool(rx and rx.match("ms-1.pdf")))
    check("F90 the wildcard does not cross into another extension",
          bool(rx) and not rx.match("ms-1.txt"))


def test_f120_strict_alpha() -> None:
    print("\n== F120: p exactly at a strict caption alpha ==")
    strict = "\\caption{Small p < 0.05 and an interval entirely below 0 mark a significant difference.}"
    rows = pkg12_rows(pkg12(strict, ["G1 & 10 & 0.05 & 1 & [0.1, 0.4]"]))
    check("F120 p=0.05 under a `p < 0.05` caption contradicts an excluding CI",
          len(rows) == 1, json.dumps(rows)[:300])
    loose = ("\\caption{Small p <= 0.05 and an interval entirely below 0 mark a "
             "significant difference.}")
    rows = pkg12_rows(pkg12(loose, ["G1 & 10 & 0.05 & 1 & [0.1, 0.4]"]))
    check("F120 the same cell is significant under a `p <= 0.05` caption", rows == [],
          json.dumps(rows)[:300])


def test_f121_f198_readiness_gap_row() -> None:
    print("\n== F121/F198: readiness names the gap's document and prints no line 0 ==")
    gap = {"rule": "PKG-22", "severity": "low", "fix": "none", "file": "", "line": 0,
           "reference": "", "gap": True, "advisory": True, "document": "supp.docx",
           "detail": "PKG-22 was NOT evaluated on 1 input(s): supp.docx"}
    ready = pp.package_readiness(
        {"hygiene": {"package_consistency": {"cited_note_negations": [gap]}}})
    rows = [f for f in ready.get("findings") or [] if f.get("rule") == "PKG-22"]
    check("F121 the gap row keeps the document it names",
          len(rows) == 1 and rows[0].get("document") == "supp.docx", json.dumps(rows)[:300])
    check("F198 the gap row's detail carries no `line 0`",
          bool(rows) and "line 0" not in str(rows[0].get("detail")))


def test_f127_sync_unmanaged_asset() -> None:
    print("\n== F127: sync-code leaves a root-only asset dir unmanaged ==")
    sys.path.insert(0, str(HERE))
    from bundle_source_lib import copy_bundle
    base = scratch("p12_f127_")
    trim, root = base / "trim", base / "root"
    copy_bundle(WS, trim)                      # a trimmed checkout: no venue_profiles/
    copy_bundle(WS, root)
    (root / "venue_profiles").mkdir()
    (root / "venue_profiles" / "stale.json").write_text("{}", encoding="utf-8")
    (root / "pipeline_config.json").write_text("{}", encoding="utf-8")
    (root / "state.json").write_text(json.dumps({
        "version": 3, "runs": {}, "rounds": {}, "pinned": [], "log": [],
        "pipeline": {"path": str(trim / "paper_pipeline.py"),
                     "sha256": pp.sha256_file(trim / "paper_pipeline.py"),
                     "version": pp.VERSION,
                     "modules": pp.module_manifest(root)}}), encoding="utf-8")
    p = subprocess.run([sys.executable, str(trim / "paper_pipeline.py"), "sync-code",
                        "--root", str(root)], capture_output=True, text=True, timeout=180)
    state = json.loads((root / "state.json").read_text())
    mods = state.get("pipeline", {}).get("modules", {})
    check("F127 sync-code succeeds on the trimmed tree", p.returncode == 0,
          (p.stdout + p.stderr)[-400:])
    check("F127 the note does not claim venue_profiles was brought up to date",
          "brought up to date" not in p.stdout, p.stdout[-500:])
    check("F127 the stale dir is reported as unmanaged",
          "UNMANAGED" in p.stdout and
          state.get("pipeline", {}).get("unmanaged_assets") == ["venue_profiles"],
          p.stdout[-300:])
    check("F127 the manifest records the ROOT's digest, never None",
          mods.get("venue_profiles") == pp.asset_dir_digest(root, "venue_profiles")
          and mods.get("venue_profiles") is not None)


def main() -> int:
    for fn in (test_f11_large_file_gap, test_f12_p_value_spelling, test_f13_unicode_minus,
               test_f79_empty_edge_cell, test_f80_contractions, test_f81_ranges,
               test_f90_extglob, test_f120_strict_alpha, test_f121_f198_readiness_gap_row,
               test_f127_sync_unmanaged_asset):
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all checks passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

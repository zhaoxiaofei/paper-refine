#!/usr/bin/env python3
"""The two renamed INPUT areas, and the READ-ONLY raw-data rule.

  * `non_revised/` (the root's pristine copy of --source) and `raw_data/` (the
    corpus's raw-data directory) are the ONLY accepted spellings. The removed
    legacy names are refused by setup and by every command that loads a root;
    there is no migration and no alias resolution.
  * The raw-data directory is an INPUT: a package carries it byte-for-byte. A
    stage that edited, added or dropped a file inside it gets the original's copy
    back (recorded as a warning).

Run:  python3 .paper_test/test_input_area_names.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xfix as xf  # noqa: E402

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_areas", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_areas"] = nb
spec.loader.exec_module(nb)

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


def make_docx(path: Path, text: str) -> None:
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", doc)


SUPP_TEX = ("\\documentclass{article}\n"
            "\\includegraphics{raw_data/Fig1.png}\n"
            "\\input{raw_data/stats.tex}\n")


def build_root(tmp: Path):
    """A root set up by the PREVIOUS pipeline: `non_revised/` + `raw_data/`."""
    root = tmp / "root"
    src = tmp / "source"
    (src / "raw_data").mkdir(parents=True)
    make_docx(src / "cnb01A-1-coverLetter-b.docx", "cover letter v b")
    (src / "cnb01A-3-suppAll-b.tex").write_text(SUPP_TEX, encoding="utf-8")
    (src / "raw_data" / "Fig1.png").write_bytes(b"\x89PNG-fig1")
    (src / "raw_data" / "dataset_summary.tsv").write_text("sample\tcells\n", encoding="utf-8")
    (src / "raw_data" / "stats.tex").write_text("% stats\n", encoding="utf-8")
    (src / "cnb01A-3-suppAll-b.aux").write_text("\\relax\n", encoding="utf-8")

    root.mkdir(parents=True)
    shutil.copytree(src, root / "non_revised")
    (root / "pipeline_config.json").write_text(json.dumps(
        {"rounds": 1, "judges": 1, "source": str(src)}), encoding="utf-8")
    ctx = nb.Ctx(root)
    ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "source_manifest": nb.hash_manifest(root / "non_revised"),
                 "original_digest": "x", "judge_salt": "testsalt"}
    ctx.cfg = {"rounds": 1, "judges": 1, "source": str(src), "caption_limit": 0}
    return ctx


def build_revise_sandbox(ctx, tamper=True, drop=()):
    """Materialize an r1_a2_revise sandbox; `tamper` writes into raw data."""
    rid = "r1_a2_revise"
    sb = ctx.runs_dir / rid
    sb.mkdir(parents=True)
    pris_name = nb.PRISTINE_DIR
    shutil.copytree(ctx.pristine, sb / "base")
    shutil.copytree(ctx.pristine, sb / pris_name)
    (sb / "targeted_review").mkdir()
    (sb / "targeted_review" / "findings.json").write_text(json.dumps(
        {"submission_dir": "./base", "guidelines_source": "test",
         "findings": [{"id": "F-001", "location": "x", "category": 0, "check": "M1",
                       "severity": "Minor", "evidence": "e", "explanation": "x",
                       "status": "resolvable"}],
         "artifacts": {}, "coverage": xf.coverage_rows()}), encoding="utf-8")
    rev = sb / "revised"
    rev.mkdir()
    for p in sorted(ctx.pristine.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ctx.pristine).as_posix()
        if rel in drop or rel.endswith((".aux", ".log", ".synctex.gz")):
            continue
        dst = rev / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
    if tamper:
        # exactly what the 2026-09-22 round-1 revise arm did to the real corpus:
        # a column added to a data table, a figure source edited, one asset gone
        # and one brand-new file inside the read-only directory.
        (rev / "raw_data" / "dataset_summary.tsv").write_text(
            "sample\tcells\tsource_accession\n", encoding="utf-8")
        (rev / "raw_data" / "stats.tex").write_text("% stats, reworded\n", encoding="utf-8")
        (rev / "raw_data" / "Fig1.png").unlink()
        (rev / "raw_data" / "scratch_notes.csv").write_text("a,b\n", encoding="utf-8")
    xf.write_language_pass(rev)
    (rev / "revision_report.json").write_text(json.dumps(
        [{"id": "F-001", "verdict": "fixed", "rationale": "done"}]), encoding="utf-8")
    (rev / "CHANGELOG.md").write_text("# changelog\n", encoding="utf-8")
    (rev / "MANUAL_STEPS.md").write_text("1. (none)\n", encoding="utf-8")
    (rev / "VISUAL_CHECK.md").write_text(
        "Renderer: none available; pages not visually verified; manual step recorded.",
        encoding="utf-8")
    (sb / "_pipeline_done.json").write_text(json.dumps(
        {"stage": "revise", "run_id": rid, "round": 1, "status": "complete",
         "summary": {"findings_total": 1, "fixed": 1, "critical_remaining": 0,
                     "manual_items": 0}}), encoding="utf-8")
    rec = ctx.register(rid, "revise", 1, f"runs/{rid}", upstream_run_id="r1_a2_review",
                       source_id="a1")
    rec["inputs_manifest"] = {"base": nb.hash_manifest(sb / "base"),
                              pris_name: nb.hash_manifest(sb / pris_name),
                              "targeted_review": nb.hash_manifest(sb / "targeted_review")}
    return rec, sb


def test_names_and_resolution():
    print()
    print("== the input areas use ONE canonical name each; the legacy spellings are gone ==")
    tmp = scratch("paper_areas_names_")
    ctx = build_root(tmp)
    check("a root uses the canonical `non_revised/` name",
          (ctx.root / "non_revised").is_dir() and not (ctx.root / "non-revised").exists())
    check("the directory-name helpers return the canonical names",
          nb.raw_data_dirname(ctx.pristine) == "raw_data"
          and nb.pristine_dirname(ctx.root) == "non_revised")
    ok_before, detail_before = nb.pristine_integrity(ctx)
    check("the pristine copy verifies", ok_before, detail_before)
    check("there is no legacy-name resolution or migration helper",
          not hasattr(nb, "migrate_legacy_dir_names")
          and not hasattr(nb, "existing_dirname")
          and not hasattr(nb, "canonicalize_raw_data_dir")
          and not hasattr(nb, "PRISTINE_DIR_LEGACY")
          and not hasattr(nb, "RAW_DATA_DIR_LEGACY"))
    check("a NEW root is created under the canonical names (setup's own rule)",
          nb.pristine_dirname(tmp / "no-root-here") == nb.PRISTINE_DIR
          and nb.raw_data_dirname(tmp / "no-root-here") == nb.RAW_DATA_DIR)
    check("a manifest keyed with a legacy spelling does NOT compare equal",
          not nb.manifests_equal({"files": {"raw_figs/x.tsv": "d"}, "count": 1},
                                  {"files": {"raw_data/x.tsv": "d"}, "count": 1}))
    check("the raw-data predicate accepts only raw_data/",
          nb.is_raw_data_rel("raw_data/a/b.tsv") and nb.is_raw_data_rel("raw_data/a.tsv")
          and not nb.is_raw_data_rel("raw_figs/a/b.tsv")
          and not nb.is_raw_data_rel("raw_data.tsv") and not nb.is_raw_data_rel("code/a.py"))
    # setup refuses a source that still uses a removed spelling.
    legacy_src = tmp / "legacy-source"
    (legacy_src / "raw_figs").mkdir(parents=True)
    (legacy_src / "raw_figs" / "x.tsv").write_text("a,b\n", encoding="utf-8")
    (legacy_src / "m.md").write_text("# T\n\nbody\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
                        "--source", str(legacy_src), "--root", str(tmp / "legacy-root")],
                       capture_output=True, text=True, timeout=120)
    check("setup refuses a --source with the removed legacy input-area name",
          r.returncode != 0 and "removed legacy spelling" in (r.stdout + r.stderr),
          (r.stdout + r.stderr)[-300:])
    # A stage-created legacy directory is never treated as ordinary submission
    # content: the package check names it and the postcheck fails the attempt.
    pkg = tmp / "pkg"
    shutil.copytree(ctx.pristine / "raw_data", pkg / "raw_data")
    (pkg / "raw_figs").mkdir()
    (pkg / "raw_figs" / "old.tsv").write_text("a,b\n", encoding="utf-8")
    warns = []
    info = nb.verify_readonly_raw_data(ctx, pkg, warns)
    check("a package carrying a legacy input-area name is flagged",
          bool(info.get("legacy_input_areas"))
          and any("REMOVED input-area spelling" in w for w in warns),
          f"{info.get('legacy_input_areas')} {warns[-2:]}")


def test_readonly_enforcement():
    print()
    print("== a stage that writes inside the read-only raw-data directory ==")
    tmp = scratch("paper_areas_ro_")
    ctx = build_root(tmp)
    pris_tsv = (ctx.pristine / "raw_data" / "dataset_summary.tsv").read_bytes()
    pris_png = (ctx.pristine / "raw_data" / "Fig1.png").read_bytes()
    rec, sb = build_revise_sandbox(ctx, tamper=True)
    ok = nb.postcheck(ctx, rec)
    pc = rec["postcheck"]
    rev = sb / "revised"
    check("the attempt PASSES: the read-only directory is repaired, not punished",
          ok, str(pc.get("errors"))[:200])
    check("the package carries the canonical raw-data directory",
          (rev / "raw_data").is_dir() and not (rev / "raw_figs").exists())
    check("the edited data table was restored to the original bytes",
          (rev / "raw_data" / "dataset_summary.tsv").read_bytes() == pris_tsv)
    check("the dropped figure came back",
          (rev / "raw_data" / "Fig1.png").read_bytes() == pris_png)
    check("the file the original does not have was removed",
          not (rev / "raw_data" / "scratch_notes.csv").exists())
    check("the template's own reference names raw_data/ and not the removed spelling",
          "raw_data/Fig1.png" in (rev / "cnb01A-3-suppAll-b.tex").read_text(encoding="utf-8")
          and "raw_figs/" not in (rev / "cnb01A-3-suppAll-b.tex").read_text(encoding="utf-8"))
    # Fig1.png is NOT in `restored`: the document-recovery layer already brought
    # it back from the base before this layer ran, so only the two EDITED files
    # needed restoring (`dropped`/`preserved` counters stay separate).
    check("the run record carries the raw-data report",
          rec["raw_data"]["present"] and len(rec["raw_data"]["restored"]) == 2
          and rec["raw_data"]["dropped"] == ["raw_data/scratch_notes.csv"],
          json.dumps(rec["raw_data"])[:200])
    warns = " | ".join(pc.get("warnings") or [])
    check("the repair is recorded as a warning naming the files",
          "READ-ONLY raw data" in warns and "dataset_summary.tsv" in warns
          and "scratch_notes.csv" in warns, warns[-260:])
    check("the frozen original itself is untouched",
          (ctx.pristine / "raw_data" / "dataset_summary.tsv").read_bytes() == pris_tsv
          and (ctx.pristine / "raw_data" / "stats.tex").read_text(encoding="utf-8")
          == "% stats\n")
    ok_pristine, detail = nb.pristine_integrity(ctx)
    check("the pristine manifest still verifies", ok_pristine, detail)


def test_clean_package_is_a_no_op():
    print()
    print("== a package that left the raw data alone ==")
    tmp = scratch("paper_areas_clean_")
    ctx = build_root(tmp)
    rec, sb = build_revise_sandbox(ctx, tamper=False)
    warns = []
    info = nb.verify_readonly_raw_data(ctx, sb / "revised", warns)
    rev = sb / "revised"
    check("the canonical directory is present and nothing is migrated",
          (rev / "raw_data").is_dir() and not (rev / "raw_figs").exists()
          and "renamed" not in info, json.dumps(info)[:160])
    check("nothing inside it is restored or dropped",
          info["restored"] == [] and info["dropped"] == [], json.dumps(info)[:160])
    check("no rename/migration warning is recorded", warns == [], str(warns)[:200])
    check("every raw-data file still has the original bytes",
          all((rev / "raw_data" / p.name).read_bytes() == p.read_bytes()
              for p in (ctx.pristine / "raw_data").rglob("*") if p.is_file()))


def main() -> int:
    try:
        test_names_and_resolution()
        test_readonly_enforcement()
        test_clean_package_is_a_no_op()
    finally:
        for tmp in TMPDIRS:
            shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print(f"{len(FAILS)} INPUT-AREA CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL INPUT-AREA CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

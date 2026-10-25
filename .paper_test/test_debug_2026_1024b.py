#!/usr/bin/env python3
"""Regressions for the 2026-10-24 debug round (C01-C07).

Each defect check pins a failure that was reproduced against HEAD b3d5aff; the
control checks pin the behaviour that must keep working (the canonical evidence
link is still followed, the package's own files are still copied, and a missing
`pdftotext` still records its gap row):

* C01: `setup`/`copy_into` followed a TOP-LEVEL evidence symlink (`raw_data/`
  -> an arbitrary directory or file outside the package), materializing local
  files into the pipeline root. The canonical per-root evidence store
  (`<root>/non_revised/<area>`) must still be followed when the copy names the
  root that owns it -- and only then.
* C02: a legend line without terminal punctuation merged the following bound
  section heading and its body into the caption span, so the pipeline's
  main-text count disagreed with `count_words.py` (3 vs 15 words) and the
  legend looked over-long.
* C04: `LENGTH_COVER_CLOSING_RE` read "Thank you for considering ..." as the
  letter's close and reported 0 persuading words (the skill script reported 19).
* C05: `redline`/`track` accepted a nonexistent `--root`, created it through the
  run log, wrote empty manifests and exited 0. A typo must be an error and must
  leave the filesystem unchanged.
* C07: a PDF that `pdftotext` cannot parse was silently treated as image-only;
  no FMT-PDF0 gap row was recorded (the missing-tool path already records one).

Run: python3 .paper_test/test_debug_2026_1024b.py
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

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_c24", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_c24"] = nb
spec.loader.exec_module(nb)

FAILS = []
SCRATCH = Path(tempfile.mkdtemp(prefix="paper_c24_"))


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def tmpdir(name: str) -> Path:
    path = SCRATCH / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def run(args, **kw):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True,
                          cwd=str(WS), timeout=600, **kw)


# ---------------------------------------------------------------------------
# C01 -- evidence symlinks are followed only when canonical
# ---------------------------------------------------------------------------
def test_copy_into_evidence_symlink():
    print()
    print("== C01: copy_into follows only the canonical evidence store ==")
    base = tmpdir("c01_copy")
    src = base / "src"
    src.mkdir()
    (src / "ms.md").write_text("body\n", encoding="utf-8")
    secret = base / "secret"
    secret.mkdir()
    (secret / "key").write_text("TOP SECRET\n", encoding="utf-8")
    os.symlink(secret, src / "raw_data")
    dst = base / "dst"
    nb.copy_into(src, dst)
    check("copy_into does not follow an evidence link outside the package",
          not (dst / "raw_data").exists()
          or not (dst / "raw_data" / "key").exists(),
          str(sorted(p for p in dst.rglob("*"))) if dst.exists() else "(no dst)")
    check("copy_into still copies the package's own files",
          (dst / "ms.md").read_text(encoding="utf-8") == "body\n")

    # A single-file target is the same class.
    base2 = tmpdir("c01_copy_file")
    src2 = base2 / "src"
    src2.mkdir()
    (src2 / "ms.md").write_text("body\n", encoding="utf-8")
    (base2 / "private.txt").write_text("TOP SECRET\n", encoding="utf-8")
    os.symlink(base2 / "private.txt", src2 / "raw_data")
    dst2 = base2 / "dst"
    nb.copy_into(src2, dst2)
    check("copy_into does not follow an evidence link to a single file",
          not (dst2 / "raw_data").exists()
          or (dst2 / "raw_data").read_text(encoding="utf-8") != "TOP SECRET\n")

    # The canonical link a version corpus really carries MUST still be followed
    # -- but only against the root that OWNS the store (`store` here).
    base3 = tmpdir("c01_canonical")
    store = base3 / "store" / "non_revised" / "raw_data"
    store.mkdir(parents=True)
    (store / "table.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    pkg = base3 / "pkg"
    pkg.mkdir()
    (pkg / "ms.md").write_text("body\n", encoding="utf-8")
    os.symlink(os.path.relpath(store, pkg), pkg / "raw_data")
    out = base3 / "out"
    nb.copy_into(pkg, out, root=base3 / "store")
    check("copy_into still follows the canonical <root>/non_revised/<area> link",
          (out / "raw_data" / "table.csv").is_file(),
          str(sorted(p.relative_to(out).as_posix() for p in out.rglob("*"))))


def test_setup_evidence_symlink():
    print()
    print("== C01: setup refuses an outside evidence link ==")
    base = tmpdir("c01_setup")
    src = base / "src"
    src.mkdir()
    (src / "ms.md").write_text("body\n", encoding="utf-8")
    secret = base / "secret"
    secret.mkdir()
    (secret / "key").write_text("TOP SECRET\n", encoding="utf-8")
    os.symlink(secret, src / "raw_data")
    root = base / "root"
    r = run([str(WS / "paper_pipeline.py"), "setup", "--source", str(src),
             "--root", str(root), "--rounds", "1"])
    leaked = ((root / "non_revised" / "raw_data" / "key").is_file()
              or (root / "non_revised" / "raw_data" / "key").is_file())
    check("setup does not materialize an outside evidence link",
          r.returncode == 0 and not leaked, f"rc={r.returncode} leaked={leaked}")
    check("setup names the skipped evidence link in a warning",
          "skipped" in (r.stdout + r.stderr) and "symlink" in (r.stdout + r.stderr),
          (r.stdout + r.stderr)[-300:])

    # A link to ANOTHER root's canonical store is not THIS root's evidence:
    # setup refuses it exactly like an arbitrary outside link (the old check
    # followed any target whose parent was named non_revised).
    base2 = tmpdir("c01_setup_canonical")
    store = base2 / "store" / "non_revised" / "raw_data"
    store.mkdir(parents=True)
    (store / "table.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    src2 = base2 / "src"
    src2.mkdir()
    (src2 / "ms.md").write_text("body\n", encoding="utf-8")
    os.symlink(os.path.relpath(store, src2), src2 / "raw_data")
    root2 = base2 / "root"
    r2 = run([str(WS / "paper_pipeline.py"), "setup", "--source", str(src2),
              "--root", str(root2), "--rounds", "1"])
    check("setup refuses a link to another root's canonical store",
          r2.returncode == 0
          and not (root2 / "non_revised" / "raw_data" / "table.csv").is_file(),
          f"rc={r2.returncode} out={(r2.stdout + r2.stderr)[-300:]!r}")
    check("setup names the refused store link in a warning",
          "skipped" in (r2.stdout + r2.stderr) and "symlink" in (r2.stdout + r2.stderr),
          (r2.stdout + r2.stderr)[-300:])


# ---------------------------------------------------------------------------
# C02 -- caption span stops at a bound section heading
# ---------------------------------------------------------------------------
def test_caption_span():
    print()
    print("== C02: a legend does not swallow the next bound section ==")
    d = tmpdir("c02")
    doc = ("Abstract\nA B C D E\n\nIntroduction\nIntro one two three.\n\n"
           "Figure 1 | Legend without a final period\nDiscussion\n"
           "Discussion alpha beta gamma delta epsilon zeta eta theta iota kappa\n"
           "References\nRef.\n")
    (d / "ms.md").write_text(doc, encoding="utf-8")
    prof = nb.load_venue_profile("nature-biotechnology")
    rows = nb.scan_lengths_in_sources([(d, "", ())], profile=prof)["rows"]
    row = [r for r in rows if r["section"] == "main text"][0]
    r = run(["paper-skills/paper-review/scripts/count_words.py", str(d / "ms.md"),
             "--venue-profile", "venue_profiles/nature-biotechnology.json",
             "--section", "main-text", "--json"])
    script_words = json.loads(r.stdout)["rows"][0]["words"] if r.returncode == 0 else None
    check("the pipeline stops the legend at the bound heading",
          row["words"] == 15, f"{row['words']} words, note={row.get('note')!r}")
    check("the pipeline and count_words.py agree on the main text",
          script_words == row["words"], f"pipeline={row['words']} script={script_words}")
    caps = nb.scan_captions_in_sources([(d, "", ())], limit=10)["captions"]
    cap_words = [c["words"] for c in caps if c["caption"] == "Figure 1"]
    check("the M18 legend span stops at the heading too",
          cap_words == [8], f"{caps}")


# ---------------------------------------------------------------------------
# C04 -- a "Thank you for considering" opener is body, not the close
# ---------------------------------------------------------------------------
def test_cover_letter_opener():
    print()
    print("== C04: a thanks opener does not end the persuading part ==")
    d = tmpdir("c04")
    (d / "cover_letter.md").write_text(
        "Dear Editor,\n\n"
        "Thank you for considering our manuscript for publication in your journal.\n"
        "We believe the work is novel and important.\n\n"
        "Sincerely,\nThe Authors\n", encoding="utf-8")
    prof = nb.load_venue_profile("nature-biotechnology")
    rows = nb.scan_lengths_in_sources([(d, "", ())], profile=prof)["rows"]
    row = [r for r in rows if r["section"] == "cover letter"][0]
    r = run(["paper-skills/paper-review/scripts/count_words.py",
             str(d / "cover_letter.md"),
             "--venue-profile", "venue_profiles/nature-biotechnology.json", "--json"])
    script_words = json.loads(r.stdout)["rows"][0]["words"] if r.returncode == 0 else None
    check("the pipeline counts the body after a thanks opener",
          row["words"] == 19, f"{row['words']} words, total={row.get('total_words')}")
    check("the pipeline and count_words.py agree on the cover letter",
          script_words == row["words"], f"pipeline={row['words']} script={script_words}")


# ---------------------------------------------------------------------------
# C05 -- redline/track refuse a path that is not a pipeline root
# ---------------------------------------------------------------------------
def test_missing_root():
    print()
    print("== C05: redline/track refuse a nonexistent root ==")
    base = tmpdir("c05")
    for cmd in ("redline", "track"):
        root = base / f"typo-{cmd}"
        r = run([str(WS / "paper_pipeline.py"), cmd, "--root", str(root)])
        check(f"{cmd} exits nonzero on a nonexistent root",
              r.returncode != 0, f"rc={r.returncode} out={(r.stdout + r.stderr)[-200:]!r}")
        check(f"{cmd} creates nothing for a nonexistent root", not root.exists(),
              str(sorted(p.name for p in root.rglob('*'))) if root.exists() else "")
    empty = base / "empty-dir"
    empty.mkdir()
    r = run([str(WS / "paper_pipeline.py"), "redline", "--root", str(empty)])
    check("redline exits nonzero on an existing empty directory",
          r.returncode != 0, f"rc={r.returncode}")
    check("redline leaves no reports/ in a directory that is not a root",
          not (empty / "reports").exists())


# ---------------------------------------------------------------------------
# C07 -- a corrupt PDF is a recorded gap, not an image-only PDF
# ---------------------------------------------------------------------------
def test_pdf_failure_gap():
    print()
    print("== C07: a pdftotext failure is recorded ==")
    if shutil.which("pdftotext") is None:
        print("[ok ] test_pdf_failure_gap  -- SKIP: pdftotext not installed")
        return
    d = tmpdir("c07")
    (d / "main.md").write_text("Abstract\nA B.\n\nIntroduction\nBody.\n", encoding="utf-8")
    (d / "supp.pdf").write_bytes(b"not a pdf\n")
    info = nb.scan_format_in_sources([(d, "", ())])
    rows = [r for r in info["rows"]
            if r["rule"] == "FMT-PDF0" and r["document"].endswith("supp.pdf")]
    check("a PDF pdftotext cannot parse produces an FMT-PDF0 gap row", bool(rows),
          str([r["rule"] for r in info["rows"]]))
    check("the gap row names the tool failure",
          bool(rows) and "pdftotext" in (rows[0].get("evidence") or ""),
          str(rows[:1]))
    # The missing-tool path keeps its own per-file gap row.
    real_which = shutil.which
    nb.shutil.which = lambda name: None if name == "pdftotext" else real_which(name)
    try:
        info2 = nb.scan_format_in_sources([(d, "", ())])
    finally:
        nb.shutil.which = real_which
    check("a missing pdftotext still produces an FMT-PDF0 row",
          any(r["rule"] == "FMT-PDF0" and r["document"].endswith("supp.pdf")
              for r in info2["rows"]), str([r["rule"] for r in info2["rows"]]))


def main() -> int:
    try:
        test_copy_into_evidence_symlink()
        test_setup_evidence_symlink()
        test_caption_span()
        test_cover_letter_opener()
        test_missing_root()
        test_pdf_failure_gap()
    finally:
        # `setup` chmod-protects the evidence copy; a plain rmtree cannot remove
        # entries under a read-only directory.
        nb.rmtree_force(SCRATCH, ignore_errors=True)
    print()
    if FAILS:
        print(f"[FAIL] {len(FAILS)} check(s) failed: {FAILS}")
        return 1
    print("[ok ] all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

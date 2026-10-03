#!/usr/bin/env python3
"""`human_review_feedback/` is a first-class EVIDENCE area (never submission text).

Run:  python3 .paper_test/test_human_review_feedback_area.py

The real editors'/reviewers' comments of a submission now live in their own
top-level directory beside `raw_data/`. The area is:
  * read-only (an INPUT: restored byte-for-byte from the pristine original);
  * never submission text (the review converter marks `area:
    human_review_feedback`, its text goes to WORK/evidence/, and no written-
    surface sweep counts or quotes it);
  * the journal modes' primary feedback source (any file name, including a
    non-English one; previous response-to-reviewers documents are context);
  * VISIBLE TO JUDGES under the labeled `evidence/human_review_feedback/`
    directory, so a judge can score how well a version addresses the human
    concerns while still seeing `evidence/raw_data/` for correctness.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
SCRIPTS = WS / "paper-skills" / "paper-review" / "scripts"
spec = importlib.util.spec_from_file_location("paper_hf", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_hf"] = nb
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


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print("== HF1: the review converter treats the area as EVIDENCE ==")
    tmp = scratch("paper_hf_conv_")
    sub = tmp / "sub"
    (sub / "human_review_feedback").mkdir(parents=True)
    (sub / "raw_data").mkdir()
    (sub / "manuscript.txt").write_text("Abstract\nWe used scRNA-seq.\n", encoding="utf-8")
    # A cover letter is a SUBMISSION document even when its name says "editor":
    # the evidence-name guard must never swallow it.
    (sub / "cover_letter_to_editor.txt").write_text(
        "Dear Editor,\nWe submit our manuscript for consideration.\n", encoding="utf-8")
    (sub / "human_review_feedback" / "审稿意见.txt").write_text(
        "Reviewer 1:\n\nThe claims are too strong for the evidence.\n", encoding="utf-8")
    (sub / "human_review_feedback" / "response_to_reviewers.txt").write_text(
        "Dear editor, in the previous round we promised new experiments.\n", encoding="utf-8")
    (sub / "raw_data" / "x.tsv").write_text("a\tb\n1\t2\n", encoding="utf-8")
    work = tmp / "work"
    r = subprocess.run([sys.executable, str(SCRIPTS / "convert_corpus.py"),
                        "--submission", str(sub), "--work", str(work)],
                       capture_output=True, text=True)
    check("HF1 the converter runs", r.returncode == 0, r.stderr[-200:])
    inv = {e["path"]: e for e in json.loads((work / "inventory.json").read_text(encoding="utf-8"))}
    fb = inv["human_review_feedback/审稿意见.txt"]
    prev = inv["human_review_feedback/response_to_reviewers.txt"]
    check("HF1 the feedback file is area=human_review_feedback, not editable, no document role",
          fb["area"] == "human_review_feedback" and fb["editable"] is False
          and fb["role"] == "human review feedback (evidence)", str(fb)[:200])
    check("HF1 a previous response is context, not a concern source",
          prev["role"] == "previous response to reviewers (evidence context)")
    check("HF1 area text goes to WORK/evidence and never to WORK/corpus",
          not any(p.name.startswith("human_review_feedback__")
                  for p in (work / "corpus").iterdir())
          and any("human_review_feedback__" in p.name for p in (work / "evidence").iterdir()))
    check("HF1 the submission document keeps its normal area",
          inv["manuscript.txt"]["area"] == "submission"
          and inv["manuscript.txt"]["role"] == "main text")

    print()
    print("== HF2: the written-surface scans never count the area ==")
    lens = nb.scan_lengths_in_sources([(sub, "", ())])
    check("HF2 M19 counts the manuscript and the cover letter, never the evidence",
          {r["document"] for r in lens["rows"]} == {"manuscript.txt", "cover_letter_to_editor.txt"}
          and any(r["section"] == "cover letter" for r in lens["rows"]),
          str([(r["document"], r["section"]) for r in lens["rows"]]))
    check("HF2 corpus_text_documents excludes the area",
          sorted(n for n, _ in nb.corpus_text_documents([(sub, "", ())]))
          == ["cover_letter_to_editor.txt", "manuscript.txt"])
    check("HF2 the evidence-area detection is shared",
          nb.is_evidence_rel("human_review_feedback/x.txt")
          and nb.is_evidence_rel("raw_data/x.tsv") and nb.is_evidence_rel("raw_figs/x.png")
          and not nb.is_evidence_rel("manuscript.txt"))

    print()
    print("== HF3: the area is READ-ONLY (restored from the pristine original) ==")
    pristine = tmp / "pristine"
    cand = tmp / "cand"
    for base in (pristine, cand):
        (base / "human_review_feedback").mkdir(parents=True)
    (pristine / "human_review_feedback" / "r1.txt").write_text("reviewer one\n", encoding="utf-8")
    (pristine / "human_review_feedback" / "r2.txt").write_text("reviewer two\n", encoding="utf-8")
    os.chmod(pristine / "human_review_feedback" / "r1.txt", 0o400)
    os.chmod(pristine / "human_review_feedback" / "r2.txt", 0o400)
    os.chmod(pristine / "human_review_feedback", 0o500)
    (cand / "human_review_feedback" / "r1.txt").write_text("TAMPERED\n", encoding="utf-8")
    (cand / "human_review_feedback" / "added.txt").write_text("agent scratch\n", encoding="utf-8")
    ctx = nb.Ctx(tmp / "fake_root")
    ctx.pristine = pristine
    warns = []
    info = nb.enforce_readonly_human_feedback(ctx, cand, warns)
    check("HF3 the tampered file is restored",
          (cand / "human_review_feedback" / "r1.txt").read_text(encoding="utf-8")
          == "reviewer one\n" and info["restored"], str(info))
    check("HF3 the dropped file is copied back",
          (cand / "human_review_feedback" / "r2.txt").is_file())
    check("HF3 the added file is removed",
          not (cand / "human_review_feedback" / "added.txt").exists()
          and info["dropped"] == ["human_review_feedback/added.txt"], str(info))
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        modes = {stat.S_IMODE((cand / "human_review_feedback" / n).stat().st_mode)
                 for n in ("r1.txt", "r2.txt")}
        check("HF3 the author's read-only modes survive", modes == {0o400}, str(modes))
    else:
        print("[skip] HF3 the author's read-only modes survive -- running as root")
    check("HF3 the deviation is named in one warning",
          any(w.startswith("READ-ONLY human review feedback:") and "put back" in w
              for w in warns), str(warns)[:200])

    print()
    print("== HF4: judges see the area, clearly labeled, plus raw_data ==")
    tmp = scratch("paper_hf_judge_")
    root = tmp / "judge_root"
    (root / "runs").mkdir(parents=True)
    (root / "non_revised" / "human_review_feedback").mkdir(parents=True)
    (root / "non_revised" / "raw_data").mkdir(parents=True)
    (root / "non_revised" / "manuscript.md").write_text(
        "# Title\n\nFigure 1 | A caption.\n", encoding="utf-8")
    (root / "non_revised" / "manuscript.tex").write_text(
        "\\documentclass{article}\n\\usepackage{graphicx}\n\\begin{document}\n"
        "\\includegraphics{raw_data/fig1.png}\n\\end{document}\n", encoding="utf-8")
    (root / "non_revised" / "human_review_feedback" / "审稿意见.txt").write_text(
        "Reviewer 1:\n\nThe claims are too strong.\n", encoding="utf-8")
    (root / "non_revised" / "human_review_feedback" / "original_submission").mkdir()
    (root / "non_revised" / "human_review_feedback" / "original_submission"
     / "submitted.txt").write_text("The version the reviewers saw.\n", encoding="utf-8")
    (root / "non_revised" / "raw_data" / "data.tsv").write_text("a\tb\n1\t2\n", encoding="utf-8")
    (root / "non_revised" / "raw_data" / "fig1.png").write_bytes(b"\x89PNG-fake")
    ctx = nb.Ctx(root)
    ctx.cfg = {"rounds": 1, "judges": 1, "rewrites": [0], "revises": [1], "source": ""}
    ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [], "log": [],
                 "source_manifest": nb.hash_manifest(root / "non_revised"),
                 "original_digest": nb.corpus_tree_digest(root / "non_revised")}
    rec = ctx.register("r1_a1", "a1", 1, "runs/r1_a1")
    nb.copy_into(ctx.pristine, ctx.sandbox_of(rec) / "base")
    (ctx.sandbox_of(rec)).mkdir(parents=True, exist_ok=True)
    dst = tmp / "view"
    nb.build_judge_view(ctx, 1, "a1", dst, time.time(), "hf-seed")
    paths = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file())
    check("HF4 the feedback reaches the judge under the labeled evidence directory",
          any(p.startswith("evidence/human_review_feedback/") for p in paths), str(paths))
    check("HF4 the reviewer-visible original submission keeps its label",
          any(p.startswith("evidence/human_review_feedback/original_submission/")
              for p in paths), str(paths))
    check("HF4 raw_data reaches the judge too",
          any(p.startswith("evidence/raw_data/") for p in paths), str(paths))
    check("HF4 the submission file stays anonymous",
          "manuscript.md" not in paths and any(p.endswith(".md") for p in paths), str(paths))
    tex = next(p for p in dst.rglob("*.tex")).read_text(encoding="utf-8")
    m = re.search(r"\\includegraphics\{([^}]*)\}", tex)
    check("HF4 a manuscript reference into raw_data is rewritten to the labeled path",
          m is not None and m.group(1).startswith("evidence/raw_data/")
          and (dst / m.group(1)).is_file(), str(m.group(1) if m else None))
    judge_prompt = nb.judge_prompt(dst, "judge_test_j1", 1, "a1", 1, 1, ["v1"],
                                   venue=nb.default_venue_profile())
    check("HF4 the judge prompt explains the evidence areas and their use",
          "THE EVIDENCE AREAS" in judge_prompt
          and "evidence/human_review_feedback" in judge_prompt
          and "ADDRESS" in judge_prompt.upper())
    check("HF4 the judge prompt explains the reviewer-visible submission",
          "original_submission" in judge_prompt)

    print()
    print("== HF5: original_submission/ is labeled EVIDENCE, never feedback or the submission ==")
    tmp = scratch("paper_hf_orig_")
    src = tmp / "src"
    (src / "human_review_feedback" / "original_submission").mkdir(parents=True)
    (src / "human_review_feedback" / "reviewer_letter.txt").write_text(
        "Reviewer 1:\n\nThe claims are too strong for the evidence.\n", encoding="utf-8")
    (src / "human_review_feedback" / "original_submission" / "submitted_manuscript.txt").write_text(
        "Introduction\nThis is the version the reviewers actually saw.\n", encoding="utf-8")
    ctx = nb.Ctx(tmp / "root")
    ctx.pristine = src
    ctx.cfg = {"revision_mode": "transfer", "journal": "Frontiers in Immunology",
               "journal_feedback_from": "iScience", "rounds": 1, "judges": [1],
               "rewrites": [1], "revises": [1]}
    hits = [label for _p, label in nb.journal_feedback_files(ctx)]
    check("HF5 original_submission/ is never discovered as a feedback document",
          any(h.endswith("reviewer_letter.txt") for h in hits)
          and not any("original_submission" in h for h in hits), str(hits))
    sb = tmp / "runs" / "r1_feedback"
    sb.mkdir(parents=True)
    nb._write_journal_feedback_inputs(ctx, sb)
    staged = sb / "feedback" / "original_submission" / "submitted_manuscript.txt"
    original = src / "human_review_feedback" / "original_submission" / "submitted_manuscript.txt"
    seed = json.loads((sb / "feedback" / "CONCERN_SEED.json").read_text(encoding="utf-8"))
    check("HF5 the reviewer-visible manuscript is staged byte-for-byte and labeled",
          staged.is_file()
          and staged.read_bytes() == original.read_bytes()
          and seed["original_submission"]["present"] is True
          and seed["original_submission"]["files"]
          == ["original_submission/submitted_manuscript.txt"], str(seed.get("original_submission")))
    check("HF5 the staged manuscript is never enumerated as feedback",
          not (sb / "feedback" / "files" / "original_submission").exists()
          and not any("submitted_manuscript" in p.name
                      for p in (sb / "feedback" / "text").glob("*"))
          and all("submitted_manuscript" not in (row.get("source") or "")
                  for row in (seed.get("candidates") or [])), str(seed)[:200])
    check("HF5 every journal prompt names the reviewer-visible copy and its rules",
          "original_submission" in nb.feedback_prompt(ctx, sb, 1, [])
          and "original_submission" in nb.journal_review_block(ctx, sb)
          and "original_submission" in nb.journal_rewrite_block(ctx)
          and "original_submission" in nb.journal_revise_block(ctx))
    check("HF5 the staged copy verifies clean",
          nb.original_submission_staging_problems(ctx, sb) == [])
    nb._write_journal_feedback_inputs(ctx, sb)          # a retry re-stages it
    check("HF5 re-staging a READ-ONLY copy is idempotent (retry-safe)",
          staged.is_file() and staged.read_bytes() == original.read_bytes()
          and nb.original_submission_staging_problems(ctx, sb) == [])
    os.chmod(staged, 0o644)
    staged.write_text("TAMPERED\n", encoding="utf-8")
    check("HF5 a modified staged file is caught",
          any("was modified" in e for e in
              nb.original_submission_staging_problems(ctx, sb)))
    os.chmod(staged.parent, 0o755)
    staged.unlink()
    check("HF5 a dropped staged file is caught",
          any("was dropped" in e for e in
              nb.original_submission_staging_problems(ctx, sb)))
    (sb / "feedback" / "original_submission" / "extra.txt").write_text("x\n", encoding="utf-8")
    check("HF5 an added staged file is caught",
          any("was added" in e for e in
              nb.original_submission_staging_problems(ctx, sb)))

    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print("  -", f)
        return 1
    print("ALL human_review_feedback EVIDENCE-AREA CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        cleanup()

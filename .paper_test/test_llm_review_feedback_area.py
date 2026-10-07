#!/usr/bin/env python3
"""`llm_review_feedback/` is a first-class EVIDENCE area, like human feedback.

Run:  python3 .paper_test/test_llm_review_feedback_area.py

A setup --source directory may carry a sibling of `human_review_feedback/` named
`llm_review_feedback/` holding a machine-generated review (any file types) whose
FALSE POSITIVE findings were filtered out upstream. It is:
  * read-only (an INPUT: restored byte-for-byte from the pristine original);
  * never submission text (the review converter marks `area:
    llm_review_feedback`, its text goes to WORK/evidence/, and no written-
    surface sweep counts or quotes it);
  * a journal-mode feedback source exactly like the human area: staged under
    feedback/llm/{files,text}/ and seeded into the concern ledger with its
    origin kept, so every remaining finding is answered (a row closed
    `not-applicable`/`disagree` still needs the recorded rationale);
  * VISIBLE TO JUDGES under the labeled `evidence/llm_review_feedback/`
    directory, where it is judged like the human concerns and never dismissed
    merely because a model wrote it.
  * the trigger of the `llm` revision mode (option 5): when the config records
    no explicit mode and the area is non-empty, it is auto-selected -- only that
    area drives the concern ledger; renaming it to
    `llm_review_feedback.disabled` (an inert, never-submitted name) turns the
    mode off, and an EXPLICIT `--revision-mode continue` overrides it too.
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
STUB = WS / ".paper_test" / "stub_agent.py"
STUB_JUDGE = WS / ".paper_test" / "stub_judge.py"
spec = importlib.util.spec_from_file_location("paper_llm", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_llm"] = nb
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


LLM_TEXT = ("Reviewer (LLM):\n\nThe sample size is too small for the claim made in the "
            "abstract and the confidence interval is never reported.\n\n"
            "The methods do not state the sequencing depth or the number of cells "
            "profiled, so the benchmark cannot be reproduced.\n")


def make_source(root: Path, with_human: bool = True) -> Path:
    src = root / "src"
    (src / "llm_review_feedback").mkdir(parents=True, exist_ok=True)
    (src / "llm_review_feedback" / "llm_review.md").write_text(LLM_TEXT, encoding="utf-8")
    if with_human:
        (src / "human_review_feedback").mkdir(exist_ok=True)
        (src / "human_review_feedback" / "editor_letter.txt").write_text(
            "Editor:\n\nThe reviewers ask for the missing depth information.\n",
            encoding="utf-8")
    (src / "manuscript.txt").write_text(
        "Abstract\nWe used scRNA-seq to profile the cells.\n", encoding="utf-8")
    return src


def ctx_for(src: Path, tmp: Path, mode: str = "transfer"):
    ctx = nb.Ctx(tmp / "root")
    ctx.pristine = src
    ctx.cfg = {"revision_mode": mode, "journal": "iScience",
               "journal_feedback_from": "iScience", "rounds": 1, "judges": [1],
               "rewrites": [1], "revises": [1]}
    return ctx


def test_converter_and_scans():
    print()
    print("== LL1: the review converter and the written-surface scans treat the area as EVIDENCE ==")
    tmp = scratch("paper_llm_conv_")
    src = make_source(tmp)
    (src / "raw_data").mkdir()
    (src / "raw_data" / "x.tsv").write_text("a\tb\n1\t2\n", encoding="utf-8")
    (src / "cover_letter_to_editor.txt").write_text(
        "Dear Editor,\nWe submit our manuscript for consideration.\n", encoding="utf-8")
    work = tmp / "work"
    r = subprocess.run([sys.executable, str(SCRIPTS / "convert_corpus.py"),
                        "--submission", str(src), "--work", str(work)],
                       capture_output=True, text=True)
    check("LL1 the converter runs", r.returncode == 0, r.stderr[-300:])
    inv = {e["path"]: e for e in json.loads((work / "inventory.json").read_text(encoding="utf-8"))}
    entry = inv["llm_review_feedback/llm_review.md"]
    check("LL1 the area is inventoried as llm_review_feedback, not editable, no submission role",
          entry["area"] == "llm_review_feedback" and entry["editable"] is False
          and "LLM review feedback" in entry["role"] and "pre-filtered" in entry["role"],
          str(entry)[:260])
    check("LL1 the evidence text goes to WORK/evidence, never WORK/corpus",
          not any(p.name.startswith("llm_review_feedback__") for p in (work / "corpus").iterdir())
          and any("llm_review_feedback__" in p.name for p in (work / "evidence").iterdir()))
    check("LL1 the area is shared evidence detection",
          nb.is_evidence_rel("llm_review_feedback/x.md")
          and nb.is_llm_feedback_rel("llm_review_feedback/x.md")
          and not nb.is_llm_feedback_rel("human_review_feedback/x.md")
          and not nb.is_evidence_rel("manuscript.txt"))
    check("LL1 M19/corpus_text_documents never count it",
          sorted(n for n, _ in nb.corpus_text_documents([(src, "", ())]))
          == ["cover_letter_to_editor.txt", "manuscript.txt"]
          and {row["document"] for row in nb.scan_lengths_in_sources([(src, "", ())])["rows"]}
          == {"cover_letter_to_editor.txt", "manuscript.txt"})


def test_readonly_area():
    print()
    print("== LL2: the area is READ-ONLY (restored byte-for-byte) ==")
    tmp = scratch("paper_llm_ro_")
    pristine = tmp / "pristine"
    cand = tmp / "cand"
    for base in (pristine, cand):
        (base / "llm_review_feedback").mkdir(parents=True)
    (pristine / "llm_review_feedback" / "review.md").write_text(LLM_TEXT, encoding="utf-8")
    (pristine / "llm_review_feedback" / "report.xlsx").write_bytes(b"PK-fake-xlsx")
    (cand / "llm_review_feedback" / "review.md").write_text("TAMPERED\n", encoding="utf-8")
    (cand / "llm_review_feedback" / "added.txt").write_text("agent scratch\n", encoding="utf-8")
    ctx = nb.Ctx(tmp / "root")
    ctx.pristine = pristine
    warns = []
    info = nb.enforce_readonly_llm_feedback(ctx, cand, warns)
    check("LL2 the tampered file is restored",
          (cand / "llm_review_feedback" / "review.md").read_text(encoding="utf-8") == LLM_TEXT
          and info["restored"], str(info))
    check("LL2 the dropped file is copied back",
          (cand / "llm_review_feedback" / "report.xlsx").is_file())
    check("LL2 the added file is removed",
          not (cand / "llm_review_feedback" / "added.txt").exists()
          and info["dropped"] == ["llm_review_feedback/added.txt"], str(info))
    check("LL2 the deviation is named in one warning",
          any(w.startswith("READ-ONLY LLM review feedback:") and "put back" in w
              for w in warns), str(warns)[:220])
    check("LL2 the human area is unaffected by the LLM pass",
          nb.enforce_readonly_llm_feedback(ctx, cand, [])["files"] == info["files"])


def test_judge_view():
    print()
    print("== LL3: judges see the area labeled, and the judge text stays blinded ==")
    tmp = scratch("paper_llm_judge_")
    root = tmp / "judge_root"
    (root / "runs").mkdir(parents=True)
    (root / "non_revised" / "llm_review_feedback").mkdir(parents=True)
    (root / "non_revised" / "manuscript.md").write_text(
        "# Title\n\nFigure 1 | A caption.\n", encoding="utf-8")
    (root / "non_revised" / "llm_review_feedback" / "llm_review.md").write_text(
        LLM_TEXT, encoding="utf-8")
    ctx = nb.Ctx(root)
    ctx.cfg = {"rounds": 1, "judges": 1, "rewrites": [0], "revises": [1], "source": ""}
    ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [], "log": [],
                 "source_manifest": nb.hash_manifest(root / "non_revised"),
                 "original_digest": nb.corpus_tree_digest(root / "non_revised")}
    rec = ctx.register("r1_a1", "a1", 1, "runs/r1_a1")
    nb.copy_into(ctx.pristine, ctx.sandbox_of(rec) / "base")
    (ctx.sandbox_of(rec)).mkdir(parents=True, exist_ok=True)
    dst = tmp / "view"
    nb.build_judge_view(ctx, 1, "a1", dst, time.time(), "llm-seed")
    paths = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file())
    check("LL3 the LLM review reaches the judge under the labeled evidence directory",
          any(p.startswith("evidence/llm_review_feedback/") for p in paths), str(paths))
    check("LL3 the submission file stays anonymous",
          "manuscript.md" not in paths and any(p.endswith(".md") for p in paths), str(paths))
    prompt = nb.judge_prompt(dst, "judge_test_j1", 1, "tok9", 1, 1, ["v1"],
                             venue=nb.default_venue_profile())
    check("LL3 the judge prompt names the area and the pre-filtered rule",
          "evidence/llm_review_feedback" in prompt
          and "FILTERED OUT" in prompt and "same standing" in prompt)
    forbidden = {r"\bround\b": "round", r"\barm\b": "arm", r"\brewrite\b": "rewrite",
                 r"\brevised\b": "revised", r"\brevision\b": "revision",
                 r"\bintegration\b": "integration", r"\bmerge\b": "merge",
                 r"\bchampion\b": "champion", r"\b(?:a1|a2|w1|i1)\b": "arm id",
                 r"\br\d+_judge": "round-prefixed run id", r"CHANGELOG": "CHANGELOG",
                 r"MANUAL_STEPS": "MANUAL_STEPS", r"REVISION_REPORT": "REVISION_REPORT",
                 r"DIFF_LEDGER": "DIFF_LEDGER", r"AUTHOR TO COMPLETE": "marker"}
    hits = {label: re.findall(pat, prompt, re.I) for pat, label in forbidden.items()
            if re.findall(pat, prompt, re.I)}
    check("LL3 the new evidence text leaks no provenance vocabulary to the judge",
          not hits, str(hits))


def test_feedback_staging():
    print()
    print("== LL4: the feedback/concerns sessions ingest the LLM review with its origin ==")
    tmp = scratch("paper_llm_stage_")
    src = make_source(tmp)
    ctx = ctx_for(src, tmp)
    sb = tmp / "runs" / "r1_feedback"
    sb.mkdir(parents=True)
    seed = nb._write_journal_feedback_inputs(ctx, sb)
    safe = "llm_review_feedback__llm_review.md"
    staged = sb / "feedback" / "llm" / "files" / safe
    staged_text = sb / "feedback" / "llm" / "text" / (safe + ".txt")
    check("LL4 the LLM files are staged byte-for-byte under feedback/llm/",
          staged.is_file()
          and staged.read_bytes() == (src / "llm_review_feedback" / "llm_review.md").read_bytes()
          and staged_text.is_file(), str(sorted(p.name for p in sb.rglob('*'))[:12]))
    data = json.loads((sb / "feedback" / "CONCERN_SEED.json").read_text(encoding="utf-8"))
    check("LL4 the seed records the LLM stream and origins",
          data.get("llm_files") == ["llm_review_feedback/llm_review.md"]
          and data.get("files") == ["human_review_feedback/editor_letter.txt"]
          and {c.get("origin") for c in data.get("candidates") or []} == {"human", "llm"},
          json.dumps(data)[:260])
    check("LL4 the rendered seed tags LLM candidates as pre-filtered",
          "(LLM review, false positives pre-filtered)" in nb._journal_seed_text(ctx, sb))
    prompt = nb.feedback_prompt(ctx, sb, 1, seed)
    check("LL4 the feedback prompt names feedback/llm/ and its standing",
          "feedback/llm/files/" in prompt and "feedback/llm/text/" in prompt
          and "FALSE POSITIVES WERE ALREADY FILTERED OUT" in prompt
          and "LLM review (pre-filtered)" in prompt)
    concerns_prompt = nb.concerns_prompt(ctx, sb, 1, seed)
    check("LL4 the scoped concerns prompt carries the same rule",
          "feedback/llm/" in concerns_prompt and "not-applicable" in concerns_prompt
          and "disagree" in concerns_prompt)
    # The ledger's verbatim check reads BOTH text trees.
    concerns = sb / "concerns"
    concerns.mkdir(parents=True)
    quote = "The sample size is too small for the claim made in the abstract"
    nb.write_json_atomic(concerns / "JF_concerns.json",
                         {"concerns": [{"id": "L1", "source": "llm_review.md",
                                        "author": "LLM review (pre-filtered)", "quote": quote,
                                        "summary": "small sample", "action": "text",
                                        "manuscript_location": "manuscript.txt",
                                        "disposition": "to-fix", "evidence_needed": ""}]})
    (concerns / "JF_concerns.md").write_text("| id |\n|---|\n| L1 |\n", encoding="utf-8")
    errs, warns = [], []
    nb.journal_ledger_problems(ctx, sb, errs, warns)
    check("LL4 an LLM quote passes the verbatim check",
          not any("not verbatim" in e for e in errs), str(errs)[:200])
    nb.write_json_atomic(concerns / "JF_concerns.json",
                         {"concerns": [{"id": "L1", "source": "llm_review.md",
                                        "author": "LLM review (pre-filtered)",
                                        "quote": "a paraphrase that never appears",
                                        "summary": "x", "action": "text",
                                        "manuscript_location": "manuscript.txt",
                                        "disposition": "to-fix", "evidence_needed": ""}]})
    errs2, _w2 = [], []
    nb.journal_ledger_problems(ctx, sb, errs2, _w2)
    check("LL4 a paraphrase still fails",
          any("not verbatim" in e for e in errs2), str(errs2)[:200])
    # An LLM-only corpus: the stage must not demand a human letter.
    tmp2 = scratch("paper_llm_only_")
    src2 = make_source(tmp2, with_human=False)
    ctx2 = ctx_for(src2, tmp2)
    check("LL4 the human stream is empty for an LLM-only corpus",
          nb.journal_feedback_files(ctx2) == []
          and [l for _p, l in nb.journal_llm_feedback_files(ctx2)]
          == ["llm_review_feedback/llm_review.md"])
    sb2 = tmp2 / "runs" / "r1_feedback"
    sb2.mkdir(parents=True)
    nb._write_journal_feedback_inputs(ctx2, sb2)
    check("LL4 an LLM-only corpus stages without dying",
          (sb2 / "feedback" / "llm" / "files" / safe).is_file()
          and not any((sb2 / "feedback" / "files").iterdir()))
    # Human findings can be filtered too, but only with a recorded rationale.
    skill = (WS / "paper-skills" / "paper-revise" / "SKILL.md").read_text(encoding="utf-8")
    check("LL4 human-reviewer false positives are filterable with a recorded rationale",
          "False positives → discard, but only with a recorded concrete rationale" in skill
          and "not-applicable" in skill and "disagree" in skill)


def test_llm_mode_e2e_autodetected():
    print()
    print("== LL5: the llm mode is auto-detected and runs end to end ==")
    tmp = scratch("paper_llm_e2e_")
    src = make_source(tmp, with_human=False)
    (src / "manuscript.txt").write_text(
        "Abstract\nWe used scRNA-seq to profile the cells.\n\n"
        "Introduction\nscRNA-seq was performed once and the claims follow.\n", encoding="utf-8")
    root = tmp / "root"
    # NO --revision-mode: the non-empty llm_review_feedback/ area selects it.
    r = subprocess.run(
        [sys.executable, str(WS / "paper_pipeline.py"), "setup", "--source", str(src),
         "--root", str(root), "--rounds", "1", "--rewrites", "0", "--revises", "1",
         "--integrators", "0x0", "--judges", "1", "--journal", "iScience"],
        capture_output=True, text=True, timeout=600)
    check("LL5 setup accepts an LLM-only corpus without --revision-mode", r.returncode == 0,
          (r.stdout + r.stderr)[-300:])
    check("LL5 setup announces the directory-driven mode",
          "revision mode auto-detected: llm" in r.stdout, r.stdout[-400:])
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("LL5 the auto-detected mode is recorded as llm",
          cfg.get("revision_mode") == "llm", str(cfg.get("revision_mode")))
    r = subprocess.run(
        [sys.executable, str(WS / "paper_pipeline.py"), "run", "--root", str(root),
         "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
         "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
         "--timeout", "300", "--retries", "0"], capture_output=True, text=True, timeout=900)
    check("LL5 the run completes", r.returncode == 0, (r.stdout + r.stderr)[-500:])
    ledger = root / "runs" / "r1_feedback" / "concerns" / "JF_concerns.json"
    data = json.loads(ledger.read_text(encoding="utf-8")) if ledger.is_file() else {}
    check("LL5 the concern ledger is built from the LLM review",
          data.get("concerns") and all("LLM review" in (c.get("author") or "")
                                       for c in data["concerns"]), json.dumps(data)[:260])
    check("LL5 the feedback sandbox carries the staged LLM stream",
          (root / "runs" / "r1_feedback" / "feedback" / "llm" / "files"
           / "llm_review_feedback__llm_review.md").is_file())
    check("LL5 no journal submission is published in this mode",
          not (root / "journal_submission").exists())


def test_mode_explicit_override_and_disable_switch():
    print()
    print("== LL6: explicit modes win, and `.disabled` is an inert off-switch ==")
    tmp = scratch("paper_llm_mode_")
    src = make_source(tmp, with_human=False)
    root = tmp / "root_explicit"
    r = subprocess.run(
        [sys.executable, str(WS / "paper_pipeline.py"), "setup", "--source", str(src),
         "--root", str(root), "--revision-mode", "llm", "--rounds", "1"],
        capture_output=True, text=True, timeout=600)
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8")) \
        if (root / "pipeline_config.json").is_file() else {}
    check("LL6 `--revision-mode llm` is accepted and recorded",
          r.returncode == 0 and cfg.get("revision_mode") == "llm",
          (r.stdout + r.stderr)[-200:])
    # An explicit `continue` overrides the directory-driven mode.
    root2 = tmp / "root_continue"
    r = subprocess.run(
        [sys.executable, str(WS / "paper_pipeline.py"), "setup", "--source", str(src),
         "--root", str(root2), "--revision-mode", "continue", "--rounds", "1"],
        capture_output=True, text=True, timeout=600)
    cfg2 = json.loads((root2 / "pipeline_config.json").read_text(encoding="utf-8")) \
        if (root2 / "pipeline_config.json").is_file() else {}
    check("LL6 an explicit continue wins over the directory",
          r.returncode == 0 and not str(cfg2.get("revision_mode") or "").strip(),
          str(cfg2.get("revision_mode")))
    # The rename is the off-switch, and the renamed tree must stay inert.
    tmp3 = scratch("paper_llm_disabled_")
    src3 = make_source(tmp3, with_human=False)
    (src3 / "llm_review_feedback").rename(src3 / "llm_review_feedback.disabled")
    check("LL6 the disabled name is not the feedback area and not submission content",
          not nb.llm_feedback_present_in(src3)
          and nb.is_disabled_evidence_rel("llm_review_feedback.disabled/llm_review.md")
          and nb.is_evidence_rel("llm_review_feedback.disabled/llm_review.md")
          and nb.evidence_area_of("llm_review_feedback.disabled/llm_review.md") == "")
    check("LL6 the disabled tree is excluded from the corpus text and the judge view",
          all(not n.startswith("llm_review_feedback.disabled")
              for n, _ in nb.corpus_text_documents([(src3, "", ())]))
          and all(not rel.startswith("llm_review_feedback.disabled")
                  for rel, _p in nb.corpus_dir_view_files(src3)))
    root3 = tmp3 / "root_disabled"
    r = subprocess.run(
        [sys.executable, str(WS / "paper_pipeline.py"), "setup", "--source", str(src3),
         "--root", str(root3), "--rounds", "1"],
        capture_output=True, text=True, timeout=600)
    cfg3 = json.loads((root3 / "pipeline_config.json").read_text(encoding="utf-8")) \
        if (root3 / "pipeline_config.json").is_file() else {}
    check("LL6 the disabled rename turns the auto-detection off",
          r.returncode == 0 and not str(cfg3.get("revision_mode") or "").strip()
          and "auto-detected: llm" not in r.stdout,
          str(cfg3.get("revision_mode")) + r.stdout[-200:])
    # Both streams present, mode llm: ONLY the LLM stream feeds the ledger.
    tmp4 = scratch("paper_llm_both_")
    src4 = make_source(tmp4, with_human=True)
    ctx = ctx_for(src4, tmp4, mode="llm")
    check("LL6 mode llm ignores the human letter as a concern source",
          nb.journal_feedback_files(ctx) == []
          and [l for _p, l in nb.journal_llm_feedback_files(ctx)]
          == ["llm_review_feedback/llm_review.md"])
    sb = tmp4 / "runs" / "r1_feedback"
    sb.mkdir(parents=True)
    nb._write_journal_feedback_inputs(ctx, sb)
    data = json.loads((sb / "feedback" / "CONCERN_SEED.json").read_text(encoding="utf-8"))
    check("LL6 only the LLM stream is staged in mode llm",
          data.get("files") == [] and data.get("llm_files")
          and not any((sb / "feedback" / "files").iterdir())
          and {c.get("origin") for c in data.get("candidates") or []} == {"llm"})


def main() -> int:
    sections = (("converter", test_converter_and_scans),
                ("read-only", test_readonly_area),
                ("judge", test_judge_view),
                ("staging", test_feedback_staging),
                ("e2e", test_llm_mode_e2e_autodetected),
                ("modes", test_mode_explicit_override_and_disable_switch))
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
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL llm_review_feedback EVIDENCE-AREA CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

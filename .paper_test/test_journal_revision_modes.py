#!/usr/bin/env python3
"""The four journal revision modes, end to end (offline stub agents).

Run:  python3 .paper_test/test_journal_revision_modes.py

    option 1  transfer   revise for a NEW journal; NO response letter; rewrites allowed
    option 2  resubmit   new submission to the SAME journal; response letter REQUIRED
    option 3  major      major revision; response letter REQUIRED; concern-scoped edits only
    option 4  minor      as 3, minor revision

The modes read the editors'/reviewers' feedback (here
`raw_data/iScience_feedback_from_reviewers_and_editors.txt`), enumerate it into a
concern ledger, and -- for modes 2-4 -- write the point-by-point response letter
and assemble `journal_submission/` WITHOUT the raw-data evidence area.

The last section pins the most important compatibility rule: with no
`--revision-mode` (the default) the historical workflow is unchanged -- the
round plan has no journal stages, the review prompt carries no journal block,
and the config records mode "none".
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
STUB = WS / ".paper_test" / "stub_agent.py"
STUB_JUDGE = WS / ".paper_test" / "stub_judge.py"
spec = importlib.util.spec_from_file_location("paper_jr", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_jr"] = nb
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


def run_cli(*argv, timeout=600):
    return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *map(str, argv)],
                          capture_output=True, text=True, timeout=timeout)


def build_source(root: Path) -> Path:
    src = root / "src"
    (src / "raw_data").mkdir(parents=True)
    (src / "human_review_feedback").mkdir(parents=True)
    (src / "manuscript.txt").write_text(
        "Abstract\nWe used scRNA-seq to profile the cells.\n\n"
        "Introduction\nscRNA-seq was performed once and the claims follow.\n", encoding="utf-8")
    # The real editors'/reviewers' comments live in their own area now; the file
    # name is deliberately NOT English, to pin the area-based detection.
    (src / "human_review_feedback" / "审稿意见.txt").write_text(
        "Reviewer 1:\n\n"
        "1. The sample size is too small and the claims are too strong for the evidence.\n\n"
        "2. The methods do not describe the sequencing depth or the number of cells profiled.\n",
        encoding="utf-8")
    # ... and a previous response is context, never a concern source.
    (src / "human_review_feedback" / "response_to_reviewers.txt").write_text(
        "Dear editor, in the previous round we promised new experiments.\n", encoding="utf-8")
    return src


def setup_and_run(tmp: Path, mode: str, *, rewrites: int = 0, judges: int = 1,
                  target: str = "iScience", source_journal: str = "iScience") -> Path:
    src = build_source(tmp)
    root = tmp / "root"
    r = run_cli("setup", "--source", str(src), "--root", str(root),
                "--rounds", "1", "--rewrites", str(rewrites), "--revises", "1",
                "--integrators", "0x0", "--judges", str(judges),
                "--revision-mode", mode,
                "--journal-feedback-from", source_journal, "--journal", target)
    if r.returncode != 0:
        raise RuntimeError(f"setup failed: {r.stdout[-500:]}{r.stderr[-500:]}")
    argv = ["run", "--root", str(root),
            "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
            "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
            "--timeout", "300", "--retries", "0"]
    r = run_cli(*argv)
    if r.returncode != 0:
        raise RuntimeError(f"run failed: {r.stdout[-1500:]}{r.stderr[-800:]}")
    return root


def submission_files(root: Path) -> list:
    d = root / "journal_submission"
    return sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()) \
        if d.is_dir() else []


def main() -> int:
    print("== J1: option 3 (major revision) -- scoped edits + response + package ==")
    tmp = scratch("paper_jr_major_")
    root = setup_and_run(tmp, "major")
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("J1 setup normalises the scoped plan",
          cfg["revision_mode"] == "major" and cfg["rounds"] == 1
          and list(cfg["rewrites"]) == [0] and list(cfg["revises"]) == [1]
          and list(cfg["integrators"]) == [0], json.dumps(
              {k: cfg.get(k) for k in ("rounds", "rewrites", "revises", "integrators")}))
    rec = json.loads((root / "state.json").read_text(encoding="utf-8"))["rounds"]["1"]
    check("J1 the scoped round closed with the revision as champion",
          rec.get("status") == "done" and rec.get("champion") == "a2"
          and rec.get("scoped") is True, str(rec)[:300])
    files = submission_files(root)
    check("J1 the submission carries the manuscript and the response letter",
          "manuscript.txt" in files and "RESPONSE_TO_REVIEWERS.md" in files
          and "response_map.json" in files, str(files))
    check("J1 the submission excludes the raw-data evidence area",
          not any(f.startswith(("raw_data/", "raw_figs/", "human_review_feedback/"))
                  for f in files))
    check("J1 the submission excludes pipeline bookkeeping",
          not any(f in ("CHANGELOG.md", "REVISION_REPORT.md", "revision_report.json",
                        "DIFF_LEDGER.md", "MANUAL_STEPS.md", "VISUAL_CHECK.md") for f in files),
          str(files))
    sub_manifest = json.loads((root / "journal_submission.json").read_text(encoding="utf-8"))
    check("J1 the package manifest records the mode and the absence of raw_data",
          sub_manifest["mode"] == "major" and sub_manifest["raw_data_included"] is False
          and sub_manifest["option"] == 3)
    sd = root / "runs" / "r1_concerns"
    ledger = json.loads((sd / "concerns" / "JF_concerns.json").read_text(encoding="utf-8"))
    check("J1 the concern ledger enumerates every reviewer point",
          len(ledger["concerns"]) >= 2, str(len(ledger["concerns"])))
    findings = json.loads((sd / "review" / "findings.json").read_text(encoding="utf-8"))
    check("J1 every concern is a JF finding and nothing else",
          findings["findings"] and all(f.get("check") == "JF" and f.get("concern")
                                        for f in findings["findings"]))
    rd = json.loads((root / "runs" / "r1_response" / "response" / "response_map.json")
                    .read_text(encoding="utf-8"))
    check("J1 the response map covers every concern exactly once",
          sorted(x["id"] for x in rd["rows"])
          == sorted(c["id"] for c in ledger["concerns"]))
    r = run_cli("decide", "--root", str(root))
    check("J1 decide reports the scoped revision instead of failing",
          r.returncode == 0 and "no judge panel" in r.stdout, r.stdout[-200:])
    r = run_cli("status", "--root", str(root))
    check("J1 status names the revision mode", "revision mode: major" in r.stdout)
    r = run_cli("run", "--root", str(root), "--only", "1",
                "--agent-cmd", json.dumps([sys.executable, str(STUB)]))
    check("J1 --only is refused in a journal mode",
          r.returncode != 0 and "does not apply to revision mode" in (r.stdout + r.stderr),
          (r.stdout + r.stderr)[-200:])
    # J8: the response statuses are tied to the concern ledger.
    ctx1 = nb.Ctx(root)
    ctx1.load()
    rec1 = ctx1.run("r1_response")
    map_path = ctx1.sandbox_of(rec1) / "response" / "response_map.json"
    original_map = map_path.read_text(encoding="utf-8")
    bad = json.loads(original_map)
    bad["rows"][0]["status"] = "already-addressed"
    bad["rows"][0]["changes"] = []
    map_path.write_text(json.dumps(bad), encoding="utf-8")
    _ok, errs1, _w, _ = nb.postcheck_response(ctx1, rec1)
    check("J8 'already-addressed' is refused when the ledger says to-fix",
          any("only valid when the concern ledger" in e for e in errs1), str(errs1)[:200])
    map_path.write_text(original_map, encoding="utf-8")
    # J9: marked-up copies ship BESIDE the clean documents, never over them.
    red = root / "redlines" / "r1_a2" / "from-original"
    red.mkdir(parents=True, exist_ok=True)
    (red / "manuscript.txt").write_text("marked copy", encoding="utf-8")
    target1, label1 = nb.journal_final_target(ctx1)
    nb.publish_journal_submission(ctx1, target1, label1,
                                  response_dir=ctx1.sandbox_of(ctx1.run("r1_response")))
    sub = root / "journal_submission"
    check("J9 the marked copy ships under tracked_changes/",
          (sub / "tracked_changes" / "manuscript.txt").is_file())
    check("J9 the clean document is not overwritten by the marked copy",
          (sub / "manuscript.txt").read_text(encoding="utf-8") != "marked copy")
    check("J9 the manifest names the marked copies",
          json.loads((root / "journal_submission.json").read_text(encoding="utf-8"))
          ["marked_changes"] == ["tracked_changes/manuscript.txt"])

    print()
    print("== J2: option 4 (minor revision) ==")
    tmp = scratch("paper_jr_minor_")
    root = setup_and_run(tmp, "minor")
    files = submission_files(root)
    check("J2 the minor revision assembles the same shape of submission",
          "manuscript.txt" in files and "RESPONSE_TO_REVIEWERS.md" in files
          and not any(f.startswith("raw_data/") for f in files), str(files))
    check("J2 the mode is recorded",
          json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
          ["revision_mode"] == "minor")

    print()
    print("== J3: option 1 (transfer) -- rewrites allowed, NO response letter ==")
    tmp = scratch("paper_jr_transfer_")
    root = setup_and_run(tmp, "transfer", rewrites=1, target="Frontiers in Immunology")
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("J3 the transfer keeps the rewrite arms", list(cfg["rewrites"]) == [1])
    files = submission_files(root)
    check("J3 the submission carries NO response letter",
          "RESPONSE_TO_REVIEWERS.md" not in files and "response_map.json" not in files,
          str(files))
    check("J3 the submission still excludes raw_data",
          not any(f.startswith("raw_data/") for f in files))
    wsb = root / "runs" / "r1_w1"
    prompt = (wsb / "PROMPT.md").read_text(encoding="utf-8")
    check("J3 the rewrite prompt carries the concern block",
          "the rewrite answers the concerns" in prompt
          and (wsb / "concerns" / "JF_concerns.json").is_file())
    rp = (root / "runs" / "r1_review" / "PROMPT.md").read_text(encoding="utf-8")
    check("J3 the review prompt carries the reconciliation block",
          "JOURNAL FEEDBACK RECONCILIATION" in rp)
    check("J3 the transfer wrote no response run", not (root / "runs" / "r1_response").exists())

    print()
    print("== J4: option 2 (resubmit) -- response letter required ==")
    tmp = scratch("paper_jr_resubmit_")
    root = setup_and_run(tmp, "resubmit")
    files = submission_files(root)
    check("J4 the resubmit carries the response letter",
          "RESPONSE_TO_REVIEWERS.md" in files and "response_map.json" in files, str(files))
    recon = json.loads((root / "runs" / "r1_review" / "review" / "concerns_reconciled.json")
                       .read_text(encoding="utf-8"))["rows"]
    ledger = json.loads((root / "runs" / "r1_feedback" / "concerns" / "JF_concerns.json")
                        .read_text(encoding="utf-8"))["concerns"]
    check("J4 the review reconciled every concern of the letter",
          sorted(x["id"] for x in recon) == sorted(c["id"] for c in ledger))
    check("J4 the letter covers every concern",
          sorted(x["id"] for x in json.loads(
              (root / "journal_submission" / "response_map.json").read_text(encoding="utf-8")
          )["rows"]) == sorted(c["id"] for c in ledger))

    print()
    print("== J5: the scoped scope guard ==")
    tmp = scratch("paper_jr_scope_")
    sb = tmp / "runs" / "r1_a2_revise"
    (sb / "base").mkdir(parents=True)
    (sb / "revised").mkdir(parents=True)
    (sb / "base" / "manuscript.txt").write_text("original text\n", encoding="utf-8")
    (sb / "revised" / "manuscript.txt").write_text("revised text\n", encoding="utf-8")
    (sb / "revised" / "revision_report.json").write_text(
        json.dumps([{"id": "C1", "verdict": "fixed", "files": ["manuscript.txt"]}]),
        encoding="utf-8")
    errs = nb.scoped_scope_problems(None, sb, sb / "revised")
    check("J5 a named change passes the scope guard", not errs, str(errs))
    (sb / "revised" / "revision_report.json").write_text("[]\n", encoding="utf-8")
    errs = nb.scoped_scope_problems(None, sb, sb / "revised")
    check("J5 an unnamed change fails the scope guard", bool(errs), str(errs))
    (sb / "revised" / "other.txt").write_text("new file\n", encoding="utf-8")
    errs = nb.scoped_scope_problems(None, sb, sb / "revised")
    check("J5 an added file fails the scope guard",
          any("added" in e for e in errs), str(errs))
    # A version-token rename is the same document, not add + delete.
    (sb / "revised" / "other.txt").unlink()
    (sb / "revised" / "manuscript.txt").unlink()
    (sb / "revised" / "manuscript-9b2c7e4.txt").write_text("revised text\n", encoding="utf-8")
    (sb / "revised" / "revision_report.json").write_text(
        json.dumps([{"id": "C1", "files": ["manuscript-9b2c7e4.txt"]}]), encoding="utf-8")
    errs = nb.scoped_scope_problems(None, sb, sb / "revised")
    check("J5 a version-token rename is not add+delete and passes when named",
          not errs, str(errs))

    print()
    print("== J6: the default workflow is unchanged (mode none) ==")
    tmp = scratch("paper_jr_none_")
    src = build_source(tmp)
    root = tmp / "root"
    r = run_cli("setup", "--source", str(src), "--root", str(root), "--rounds", "1")
    check("J6 setup without a mode succeeds", r.returncode == 0, r.stderr[-200:])
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    # The key is OMITTED for a default root: a mode-none pipeline_config.json
    # stays byte-identical to the historical one (`journal_mode_of` reads a
    # missing key as "none"), which is the strongest form of "unchanged".
    check("J6 the default root does not record a journal mode",
          "revision_mode" not in cfg, json.dumps(sorted(cfg)))
    ctx = nb.Ctx(root)
    ctx.load()
    kinds = {e["kind"] for e in nb.round_run_plan(ctx, 1)}
    check("J6 the round plan has no journal stages",
          not (kinds & {"feedback", "concerns", "response"}), str(sorted(kinds)))
    check("J6 journal_mode_of reports none", nb.journal_mode_of(ctx) == "none")
    r = run_cli("set-revision-mode", "--root", str(root))
    check("J6 set-revision-mode --show prints the current mode",
          r.returncode == 0 and "mode: none" in r.stdout, r.stdout[-200:])
    r = run_cli("set-revision-mode", "major", "--root", str(root))
    check("J6 switching the default root to a journal mode succeeds",
          r.returncode == 0, (r.stdout + r.stderr)[-200:])
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("J6 the switch records and normalises the mode",
          cfg.get("revision_mode") == "major" and list(cfg.get("rewrites") or []) == [0]
          and list(cfg.get("revises") or []) == [1]
          and list(cfg.get("integrators") or []) == [0] and cfg.get("audit") == "off",
          json.dumps({k: cfg.get(k) for k in ("revision_mode", "rewrites", "revises",
                                              "integrators", "audit")}))
    ctx_switched = nb.Ctx(root)
    ctx_switched.load()
    kinds = {e["kind"] for e in nb.round_run_plan(ctx_switched, 1)}
    check("J6 the switched root plans the scoped journal stages",
          {"concerns", "revise", "response"} <= kinds
          and "review" not in kinds and "rewrite" not in kinds, str(sorted(kinds)))

    print()
    print("== J7: feedback auto-detection and explicit paths ==")
    tmp = scratch("paper_jr_detect_")
    src = tmp / "src"
    (src / "raw_data").mkdir(parents=True)
    (src / "human_review_feedback").mkdir(parents=True)
    (src / "human_review_feedback" / "审稿意见.txt").write_text(
        "Reviewer 1:\n\nThe claims are too strong for the evidence.\n", encoding="utf-8")
    (src / "human_review_feedback" / "response_to_reviewers.txt").write_text(
        "Dear editor, we previously promised more experiments.\n", encoding="utf-8")
    # Legacy shape: a feedback-named file under raw_data still works when the
    # dedicated area is absent or empty.
    (src / "raw_data" / "iScience_feedback_from_reviewers_and_editors.txt").write_text(
        "Reviewer 1:\n\nThe claims are too strong for the evidence.\n", encoding="utf-8")
    (src / "cover_letter_to_editor.docx").write_text("stub cover letter", encoding="utf-8")
    (src / "response_to_reviewers.docx").write_text("stub reply", encoding="utf-8")
    ctx2 = nb.Ctx(tmp / "root")
    ctx2.pristine = src
    ctx2.cfg = {"revision_mode": "major", "journal_feedback": []}
    hits = [label for _p, label in nb.journal_feedback_files(ctx2)]
    check("J7 the dedicated area wins, any file name, and needs no heuristic",
          hits == ["human_review_feedback/审稿意见.txt"], str(hits))
    prev = [label for _p, label in nb.journal_previous_responses(ctx2)]
    check("J7 a previous response is context, never the letter",
          prev == ["human_review_feedback/response_to_reviewers.txt"], str(prev))
    # With no dedicated area, the legacy raw_data name heuristic still applies.
    legacy = tmp / "legacy"
    (legacy / "raw_data").mkdir(parents=True)
    (legacy / "raw_data" / "reviewer_comments.txt").write_text("Reviewer 2:\n\nToo strong.\n",
                                                               encoding="utf-8")
    ctx2.pristine = legacy
    hits = [label for _p, label in nb.journal_feedback_files(ctx2)]
    check("J7 the legacy raw_data location still works",
          hits == ["raw_data/reviewer_comments.txt"], str(hits))
    ctx2.cfg = {"revision_mode": "major", "journal_feedback": [str(tmp / "missing.txt")]}
    refused = False
    try:
        nb.journal_feedback_files(ctx2)
    except SystemExit:
        refused = True
    check("J7 an explicit missing feedback path is refused", refused)

    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print("  -", f)
        return 1
    print("ALL JOURNAL REVISION-MODE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        cleanup()

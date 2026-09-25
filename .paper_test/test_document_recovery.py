#!/usr/bin/env python3
"""Regression tests for the document-recovery layer (candidate C01).

repro of the observed r1_a2_revise failure: the revise agent drops
`raw_figs/entire_pipeline.git-snapshot.txt` from its package on every attempt,
and v2.1.0 turns that recoverable drop into a hard failure -> rebuild sandbox ->
full 45-minute agent session -> identical failure x3 -> round incomplete
(~3 h wall clock thrown away by a 900-byte file).

Run:  python3 .paper_test/test_document_recovery.py

Every check FAILS on the pre-fix tree and PASSES once the backfill layer is in
place, so this file is both the repro script and the regression guard:

    PAPER_WS=/tmp/paper_base python3 .paper_test/test_document_recovery.py   # red
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xfix as xf  # noqa: E402

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_recovery", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_recovery"] = nb
spec.loader.exec_module(nb)

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def make_docx(path: Path, text: str) -> None:
    """Minimal but valid OOXML package (word/document.xml)."""
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", doc)


def build_root(tmp: Path):
    """A pipeline root whose pristine copy mimics the real SOURCE_DIR layout."""
    root = tmp / "root"
    src = tmp / "source"
    (src / "raw_figs").mkdir(parents=True)
    make_docx(src / "cnb01A-1-coverLetter-b.docx", "cover letter v b")
    make_docx(src / "cnb01B-2-mainText-b.docx", "main text v b")
    (src / "cnb01A-3-suppAll-b.tex").write_text("\\documentclass{article}\n")
    (src / "cnb01A-3-suppAll-b.pdf").write_bytes(b"%PDF-compiled-supp")
    (src / "nr-reporting-summary-filled-b.pdf").write_bytes(b"%PDF-reporting-summary")
    # raw_figs assets: data + the file that broke the real run
    (src / "raw_figs" / "entire_pipeline.git-snapshot.txt").write_text("commit abc123\n")
    (src / "raw_figs" / "dataset_summary.tsv").write_text("sample\tcells\n")
    (src / "raw_figs" / "Fig5_scRNA_swarm_grid.png").write_bytes(b"\x89PNG-fake")
    (src / "raw_figs" / "Fig5_scRNA_swarm_grid.pdf").write_bytes(b"%PDF-fig5")
    (src / "raw_figs" / "cnb01-Fig1-full.pptx").write_bytes(b"PK-fake-pptx")
    # derived build outputs the agent is told to leave out
    (src / "cnb01A-3-suppAll-b.aux").write_text("\\relax\n")
    (src / "cnb01A-3-suppAll-b.log").write_text("latex log\n")
    (src / "cnb01A-3-suppAll-b.synctex.gz").write_bytes(b"\x1f\x8b-fake")

    root.mkdir(parents=True)
    shutil.copytree(src, root / "non-revised")
    (root / "pipeline_config.json").write_text(json.dumps(
        {"rounds": 1, "judges": 1, "source": str(src)}))
    ctx = nb.Ctx(root)
    ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "source_manifest": nb.hash_manifest(root / "non-revised"),
                 "original_digest": "x", "judge_salt": "testsalt"}
    ctx.cfg = {"rounds": 1, "judges": 1, "source": str(src), "caption_limit": 0}
    return ctx


def build_revise_sandbox(ctx, drop=(), empty=(), rename=False, edited_pdf_twin=True):
    """Materialize an r1_a2_revise sandbox whose agent 'forgot' the files in `drop`."""
    rid = "r1_a2_revise"
    sb = ctx.runs_dir / rid
    sb.mkdir(parents=True)
    shutil.copytree(ctx.pristine, sb / "base")
    shutil.copytree(ctx.pristine, sb / "non-revised")
    (sb / "review").mkdir()
    (sb / "review" / "findings.json").write_text(json.dumps(
        {"submission_dir": "./base", "guidelines_source": "test",
         "findings": [{"id": "F-001", "location": "x", "category": 0, "check": "M1",
                       "severity": "Minor", "evidence": "e", "explanation": "x",
                       "status": "resolvable"}],
         "artifacts": {}, "coverage": xf.coverage_rows()}))
    rev = sb / "revised"
    rev.mkdir()
    for p in sorted(ctx.pristine.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ctx.pristine).as_posix()
        if rel in drop or p.name.endswith((".aux", ".log", ".synctex.gz")):
            continue
        if rename and rel == "cnb01B-2-mainText-b.docx":
            continue
        dst = rev / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
    if rename:  # the agent renamed the edited main text one version deeper
        make_docx(rev / "cnb01B-2-mainText-c.docx", "main text v c (edited)")
    if edited_pdf_twin and (rev / "cnb01A-3-suppAll-b.tex").is_file():
        # the agent edited the .tex but left its compiled PDF out (deliberate)
        (rev / "cnb01A-3-suppAll-b.tex").write_text("\\documentclass{book}\n% edited\n")
        (rev / "cnb01A-3-suppAll-b.pdf").unlink()
    for rel in empty:
        (rev / rel).write_bytes(b"")
    # bookkeeping the revise contract requires (including the L1-L11 pass)
    xf.write_language_pass(rev)
    (rev / "revision_report.json").write_text(json.dumps(
        [{"id": "F-001", "verdict": "fixed", "rationale": "done"}]))
    (rev / "CHANGELOG.md").write_text("# changelog\n")
    (rev / "MANUAL_STEPS.md").write_text("1. (none)\n")
    (rev / "VISUAL_CHECK.md").write_text(
        "Renderer: none available; pages not visually verified; manual step recorded.")
    (sb / "_pipeline_done.json").write_text(json.dumps(
        {"stage": "revise", "run_id": rid, "round": 1, "status": "complete",
         "summary": {"findings_total": 1, "fixed": 1, "critical_remaining": 0,
                     "manual_items": 0}}))
    rec = ctx.register(rid, "revise", 1, f"runs/{rid}", upstream_run_id="r1_a2_review",
                       source_id="a1")
    rec["inputs_manifest"] = {"base": nb.hash_manifest(sb / "base"),
                              "non-revised": nb.hash_manifest(sb / "non-revised"),
                              "review": nb.hash_manifest(sb / "review")}
    return rec, sb


def main() -> int:
    tmpdirs = []

    def scratch(prefix):
        tmp = Path(tempfile.mkdtemp(prefix=prefix))
        tmpdirs.append(tmp)
        return tmp

    # ---- D1: THE observed failure -------------------------------------
    print("== D1: the agent drops raw_figs/entire_pipeline.git-snapshot.txt ==")
    tmp = scratch("paper_rec_d1_")
    ctx = build_root(tmp)
    rec, sb = build_revise_sandbox(ctx, drop=("raw_figs/entire_pipeline.git-snapshot.txt",))
    ok = nb.postcheck(ctx, rec)
    pc = rec["postcheck"]
    warn_text = " ".join(pc["warnings"])
    check("D1 run is not FAILED (was: hard error, 3 attempts, round lost)", ok,
          str(pc["errors"]))
    check("D1 dropped file restored into revised/",
          (sb / "revised" / "raw_data" / "entire_pipeline.git-snapshot.txt").is_file())
    check("D1 RECOVERY warning names the file",
          "RECOVERY" in warn_text and "entire_pipeline.git-snapshot.txt" in warn_text)
    check("D1 no missing-document error remains", not pc["errors"])
    check("D1 document_set reports nothing missing",
          not (rec.get("document_set") or {}).get("missing"))
    check("D1 the drop is recorded on the run record",
          (rec.get("backfill") or {}).get("restored")
          == ["raw_figs/entire_pipeline.git-snapshot.txt"])
    check("D1 corpus digest computed over the REPAIRED package",
          bool(rec.get("corpus_digest")))

    # ---- D2: non-editable assets are covered too -----------------------
    print("== D2: dropped non-editable assets (png/pdf/pptx/tsv) are restored ==")
    tmp = scratch("paper_rec_d2_")
    ctx = build_root(tmp)
    drop = ("raw_figs/Fig5_scRNA_swarm_grid.png", "raw_figs/Fig5_scRNA_swarm_grid.pdf",
            "raw_figs/cnb01-Fig1-full.pptx", "raw_figs/dataset_summary.tsv")
    rec, sb = build_revise_sandbox(ctx, drop=drop)
    ok = nb.postcheck(ctx, rec)
    restored = set((rec.get("backfill") or {}).get("restored") or [])
    check("D2 run ok", ok, str(rec["postcheck"]["errors"]))
    check("D2 all four assets restored (the old check never covered them)",
          restored == set(drop), str(restored))

    # ---- D3: derived outputs stay out ---------------------------------
    print("== D3: derived build outputs are NOT restored ==")
    tmp = scratch("paper_rec_d3_")
    ctx = build_root(tmp)
    rec, sb = build_revise_sandbox(ctx)
    ok = nb.postcheck(ctx, rec)
    check("D3 run ok", ok, str(rec["postcheck"]["errors"]))
    check("D3 .aux not backfilled", not (sb / "revised" / "cnb01A-3-suppAll-b.aux").exists())
    check("D3 .log not backfilled", not (sb / "revised" / "cnb01A-3-suppAll-b.log").exists())
    check("D3 nothing restored for a complete package",
          not (rec.get("backfill") or {}).get("restored"),
          str((rec.get("backfill") or {}).get("restored")))

    # ---- D4: compiled-PDF twin logic ----------------------------------
    print("== D4: compiled-PDF twin logic ==")
    tmp = scratch("paper_rec_d4a_")
    ctx = build_root(tmp)
    rec, sb = build_revise_sandbox(ctx, edited_pdf_twin=True)
    ok = nb.postcheck(ctx, rec)
    check("D4a run ok with an EDITED .tex and its compiled PDF left out", ok,
          str(rec["postcheck"]["errors"]))
    check("D4a compiled PDF NOT restored (would contradict the revised source)",
          not (sb / "revised" / "cnb01A-3-suppAll-b.pdf").exists())
    check("D4a stale-PDF warning names the file",
          any("cnb01A-3-suppAll-b.pdf" in w for w in rec["postcheck"]["warnings"]))
    tmp = scratch("paper_rec_d4b_")
    ctx = build_root(tmp)
    rec, sb = build_revise_sandbox(ctx, edited_pdf_twin=False)
    (sb / "revised" / "cnb01A-3-suppAll-b.pdf").unlink()
    nb.postcheck(ctx, rec)
    check("D4b unchanged-twin PDF restored",
          (sb / "revised" / "cnb01A-3-suppAll-b.pdf").is_file())
    tmp = scratch("paper_rec_d4c_")
    ctx = build_root(tmp)
    rec, sb = build_revise_sandbox(ctx, edited_pdf_twin=False)
    (sb / "revised" / "nr-reporting-summary-filled-b.pdf").unlink()
    nb.postcheck(ctx, rec)
    check("D4c no-twin data PDF restored",
          (sb / "revised" / "nr-reporting-summary-filled-b.pdf").is_file())

    # ---- D5: renames are not duplicated -------------------------------
    print("== D5: renamed documents are not duplicated by the backfill ==")
    tmp = scratch("paper_rec_d5_")
    ctx = build_root(tmp)
    rec, sb = build_revise_sandbox(ctx, rename=True)
    ok = nb.postcheck(ctx, rec)
    check("D5 run ok after the rename", ok, str(rec["postcheck"]["errors"]))
    check("D5 old name NOT re-added (content survived as ...-c.docx)",
          not (sb / "revised" / "cnb01B-2-mainText-b.docx").exists())
    check("D5 document_set finds no missing docs",
          not (rec.get("document_set") or {}).get("missing"),
          str((rec.get("document_set") or {}).get("missing")))

    # ---- D6: truncation ------------------------------------------------
    print("== D6: zero-byte (truncated) candidate file is restored ==")
    tmp = scratch("paper_rec_d6_")
    ctx = build_root(tmp)
    rec, sb = build_revise_sandbox(ctx, empty=("raw_figs/entire_pipeline.git-snapshot.txt",))
    ok = nb.postcheck(ctx, rec)
    f = sb / "revised" / "raw_data" / "entire_pipeline.git-snapshot.txt"
    check("D6 run ok", ok, str(rec["postcheck"]["errors"]))
    check("D6 truncation restored non-empty", f.is_file() and f.stat().st_size > 0)

    # ---- D7: the same recovery in the INTEGRATION stage ---------------
    print("== D7: integration-stage backfill works against self/ ==")
    tmp = scratch("paper_rec_d7_")
    ctx = build_root(tmp)
    rec, sb = build_revise_sandbox(ctx)
    rec["status"] = "done"
    recb = ctx.register("r1_i1", "integrate", 1, "runs/r1_i1", self_id="a1",
                        other_ids=["w1"], pool_ids=["a1", "w1"])
    sb17 = ctx.runs_dir / "r1_i1"
    shutil.copytree(sb / "revised", sb17 / "self", dirs_exist_ok=True)
    shutil.copytree(sb / "revised", sb17 / "others" / "w1", dirs_exist_ok=True)
    shutil.copytree(ctx.pristine, sb17 / "non-revised")
    rev17 = sb17 / "integrated"
    rev17.mkdir()
    for p in sorted((sb17 / "self").rglob("*")):
        if p.is_file():
            dst = rev17 / p.relative_to(sb17 / "self")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
    (rev17 / "raw_figs" / "entire_pipeline.git-snapshot.txt").unlink()
    (rev17 / "DIFF_LEDGER.md").write_text("| D1 | (a) | ported |\n")
    (rev17 / "CHANGELOG.md").write_text("# changelog\n")
    (sb17 / "_pipeline_done.json").write_text(json.dumps(
        {"stage": "integrate", "run_id": "r1_i1", "round": 1, "status": "complete",
         "summary": {"ported": 1, "kept_base": 0, "ignored_cosmetic": 0,
                     "shared_defects_left": 0, "donors_read": 1,
                     "critical_remaining": 0, "manual_items": 0}}))
    recb["inputs_manifest"] = {"self": nb.hash_manifest(sb17 / "self"),
                               "others": nb.hash_manifest(sb17 / "others"),
                               "non-revised": nb.hash_manifest(sb17 / "non-revised")}
    ok = nb.postcheck(ctx, recb)
    check("D7 integration run ok, git snapshot restored from self/",
          ok and (rev17 / "raw_data" / "entire_pipeline.git-snapshot.txt").is_file(),
          str(recb["postcheck"]["errors"]))

    # ---- D8: the file name survives console truncation ----------------
    print("== D8: names-first missing-file message ==")
    tmp = scratch("paper_rec_d8_")
    ctx = build_root(tmp)
    rec, sb = build_revise_sandbox(ctx, drop=("raw_figs/entire_pipeline.git-snapshot.txt",))
    # Make the file un-restorable: backfill refuses to delete a non-empty
    # directory, so the document-set check reports it missing and the pipeline
    # itself (not this test) formats the names-first warning.
    ghost = sb / "revised" / "raw_figs" / "entire_pipeline.git-snapshot.txt"
    ghost.mkdir()
    (ghost / "keep").write_text("agent scratch\n")
    nb.postcheck(ctx, rec)
    warns = (rec.get("postcheck") or {}).get("warnings") or []
    missing = [w for w in warns if w.startswith("MISSING FROM THE CANDIDATE")]
    line = missing[0] if missing else ""
    check("D8 the filename is visible inside the first 140 chars",
          "raw_figs/entire_pipeline.git-snapshot.txt" in line[:140], line)

    # ---- D9: the retry budget is per invocation -----------------------
    print("== D9: a fresh `run` grants a failed run a fresh retry budget ==")
    tmp = scratch("paper_rec_d9_")
    root = tmp / "root"
    (root / "runs").mkdir(parents=True)
    (root / "reports").mkdir(parents=True)
    ctx9 = nb.Ctx(root)
    rec9 = ctx9.register("r1_a2_revise", "revise", 1, "runs/r1_a2_revise", source_id="a1")
    ctx9.sandbox_of(rec9).mkdir(parents=True, exist_ok=True)
    rec9["attempts"] = 3                  # lifetime count from earlier invocations
    rec9["status"] = "failed"
    rec9["last_error"] = "process-level failure from an earlier invocation"
    ctx9.save_state()
    started = []

    def fake_rebuild(c, r):
        c.sandbox_of(r).mkdir(parents=True, exist_ok=True)
        r["status"] = "pending"

    def fake_execute(c, ids, cmd, timeout, jobs):
        started.extend(ids)
        return {rid: {"rc": 1, "dur": 0.1, "error": "agent exited rc=1", "log": None}
                for rid in ids}

    def fake_apply(c, results):
        for rid, res in results.items():
            r = c.run(rid)
            r["status"] = "failed"
            r["attempts"] = (r.get("attempts") or 0) + 1
            r["last_error"] = res["error"]

    real_rebuild, real_execute, real_apply = nb.rebuild_sandbox, nb.execute_wave, nb.apply_results
    nb.rebuild_sandbox, nb.execute_wave, nb.apply_results = fake_rebuild, fake_execute, fake_apply
    try:
        nb.run_phase(ctx9, ["r1_a2_revise"], cmd=["true"], timeout=10, jobs=1, retries=2,
                     manual=False, nowait=False, poll=1, label="revise",
                     retry_backoff=0, retry_backoff_max=0)
    finally:
        nb.rebuild_sandbox, nb.execute_wave, nb.apply_results = real_rebuild, real_execute, real_apply
    check("D9 three attempts granted in this invocation (was: 0, no-op exit)",
          len(started) == 3, f"started={started}")

    # ---- D10: judge label case/whitespace slips ------------------------
    print("== D10: judge-sheet label normalization ==")
    rec10 = {"id": "r1_judge_t1_j1", "round": 1, "target_id": "a2", "judge_index": 1,
             "label_map": {"v1": "orig", "v2": "a1"}, "judge_target_token": "tABCDEF12"}
    sheet = {"run_id": "r1_judge_t1_j1", "target_id": "tABCDEF12", "round": 1, "judge_index": 1,
             "comparisons": [{"opponent_label": "V1", "score": 1, "reason": "a bit better"},
                             {"opponent_label": " v2 ", "score": -1, "reason": "a bit worse"}]}
    verrs, vwarns = nb.validate_judge_sheet(sheet, rec10)
    check("D10a 'V1'/' v2 ' normalise without errors", not verrs, str(verrs))
    # Count the NORMALIZATION warnings, not every warning: a legacy sheet also
    # collects the graded-basis "UNCALIBRATED" warnings under judge contract v2.
    check("D10b normalization is reported as warnings",
          sum(1 for w in vwarns if "was normalised to" in w) == 2, str(vwarns))
    check("D10c judge_sheet_complete accepts the normalized sheet",
          nb.judge_sheet_complete(sheet, rec10))
    bad_sheet = dict(sheet, comparisons=[{"opponent_label": "V1", "score": 1, "reason": "x"}])
    verrs2, _ = nb.validate_judge_sheet(bad_sheet, rec10)
    check("D10d a genuinely omitted label still fails (panel integrity kept)",
          any("omit" in e for e in verrs2), str(verrs2))

    # ---- D11: the aggregator resolves the normalized label -------------
    print("== D11: aggregate_round resolves normalized labels ==")
    tmp = scratch("paper_rec_d11_")
    ctx11 = build_root(tmp)
    ctx11.state["original_digest"] = nb.manifest_digest(nb.hash_manifest(ctx11.pristine))
    rec11, sb11 = build_revise_sandbox(ctx11)
    rec11["status"] = "done"
    rec11["corpus_digest"] = nb.recompute_corpus_digest(ctx11, 1, "a2")
    rec11["content_fingerprint"] = nb.corpus_content_fingerprint(ctx11, 1, "a2")
    jid = "r1_judge_tAAA_j1"
    sjr = ctx11.register(jid, "judge", 1, f"runs/{jid}", target_id="a2", judge_index=1,
                         label_map={"v1": "orig"}, judge_target_token="tAAA")
    sjr["status"] = "done"
    sjr["scores"] = {"run_id": jid, "target_id": "tAAA", "round": 1, "judge_index": 1,
                     "comparisons": [{"opponent_label": "V1", "score": 2, "reason": "better"}]}
    jid2 = "r1_judge_tBBB_j1"
    sjr2 = ctx11.register(jid2, "judge", 1, f"runs/{jid2}", target_id="orig", judge_index=1,
                          label_map={"v1": "a2"}, judge_target_token="tBBB")
    sjr2["status"] = "done"
    sjr2["scores"] = {"run_id": jid2, "target_id": "tBBB", "round": 1, "judge_index": 1,
                      "comparisons": [{"opponent_label": "v1", "score": -2,
                                       "reason": "worse (negated into a2's frame)"}]}
    agg = nb.aggregate_round(ctx11, 1, ["orig", "a2"])
    check("D11 normalized 'V1' resolved: a2 collected its directed score",
          agg["stats"]["a2"]["n"] == 2, f"n={agg['stats']['a2']['n']}")
    shutil.rmtree(tmp, ignore_errors=True)

    for tmp in tmpdirs:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print(f"{len(FAILS)} DOCUMENT-RECOVERY CHECK(S) FAILED")
        for name in FAILS:
            print("  -", name)
        return 1
    print("ALL DOCUMENT-RECOVERY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

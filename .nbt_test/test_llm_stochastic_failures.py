#!/usr/bin/env python3
"""Regression tests for stochastic-LLM failure modes (the agent is untrusted).

Every case below is a failure an LLM agent in this pipeline can plausibly
produce: a marker or ledger wrapped in a markdown fence, a JSON `null` where an
object was asked for, a half-written file, a document replaced by a symlink or a
directory, a file the process cannot read, an unreadable artifact tree.

The contract these tests pin is: NO agent-side mistake may CRASH the
orchestrator, and none may be silently ACCEPTED as a complete package. Every
case must end in exactly one of two states:

  * repaired/usable -- `ok` (the run proceeds) with a RECOVERY/normalisation
    warning that names what was fixed, or
  * a clean failure -- `ok=False` (the attempt is retried) with an actionable
    error, and the run record left consistent (`finished` unset, no digest).

Run:  python3 .nbt_test/test_llm_stochastic_failures.py

`NBT_WS` retargets the harness at a baseline copy; most cases fail there (the
crash cases mask a real PermissionError/JSON crash on the pre-fix tree).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_stoch", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_stoch"] = nb
spec.loader.exec_module(nb)

# Fixture builders live in the document-recovery suite (it imports cleanly).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_document_recovery import build_revise_sandbox, build_root  # noqa: E402

FAILS = []
SKIPS = []
RUN_AS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def skip(name, why):
    SKIPS.append(name)
    print(f"[skip] {name}  -- {why}")


def forced_chmod(path: Path, mode: int):
    """chmod that does not depend on the process umask."""
    path.chmod(mode)
    return path


def new_case(prefix="nbt_stoch_"):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    ctx = build_root(tmp)
    rec, sb = build_revise_sandbox(ctx)
    return tmp, ctx, rec, sb


def run_postcheck(ctx, rec):
    """Run the real postcheck; return (ok, errors, warnings, crashed_exception)."""
    try:
        ok = nb.postcheck(ctx, rec)
    except Exception as e:                                          # noqa: BLE001
        return None, [f"{type(e).__name__}: {e}"], [], e
    pc = rec.get("postcheck") or {}
    return ok, list(pc.get("errors") or []), list(pc.get("warnings") or []), None


def cleanup(tmp: Path):
    # Restore permissions so the temporary tree can be removed.
    for p in tmp.rglob("*"):
        try:
            if p.is_dir() and not p.is_symlink():
                p.chmod(0o755)
            elif not p.is_symlink():
                p.chmod(0o644)
        except OSError:
            pass
    shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    # =================================================================
    # A. Marker / ledger JSON an LLM actually writes
    # =================================================================
    print("== A. agent-written JSON shapes ==")

    # A1: complete marker wrapped in a markdown fence -> recovered, run proceeds
    tmp, ctx, rec, sb = new_case()
    marker = sb / "_pipeline_done.json"
    marker.write_text("```json\n" + marker.read_text() + "\n```")
    ok, errs, warns, crash = run_postcheck(ctx, rec)
    check("A1 fenced marker does not crash", crash is None, str(crash))
    check("A1 fenced marker is recovered (run proceeds, no marker error)",
          ok is True and not any("marker" in e.lower() for e in errs), str(errs[:1]))
    cleanup(tmp)

    # A2: marker introduced by prose -> recovered
    tmp, ctx, rec, sb = new_case()
    marker = sb / "_pipeline_done.json"
    marker.write_text("Here is the completion marker:\n" + marker.read_text() + "\nDone.\n")
    ok, errs, warns, crash = run_postcheck(ctx, rec)
    check("A2 prose-wrapped marker is recovered", ok is True and crash is None,
          f"ok={ok} errs={errs[:1]}")
    cleanup(tmp)

    # A3: marker is a JSON array / string / null -> clean failure, never a crash
    for label, payload in (("array", "[1, 2, 3]"), ("string", '"complete"'), ("null", "null")):
        tmp, ctx, rec, sb = new_case()
        (sb / "_pipeline_done.json").write_text(payload)
        ok, errs, warns, crash = run_postcheck(ctx, rec)
        check(f"A3 marker as JSON {label} fails cleanly",
              crash is None and ok is False and errs, f"ok={ok} errs={errs[:1]}")
        check(f"A3 marker as JSON {label} left the run record consistent",
              rec["status"] == "failed" and not rec.get("finished")
              and not rec.get("corpus_digest"))
        cleanup(tmp)

    # A4: empty (0-byte) marker -> clean failure
    tmp, ctx, rec, sb = new_case()
    (sb / "_pipeline_done.json").write_text("")
    ok, errs, warns, crash = run_postcheck(ctx, rec)
    check("A4 empty marker fails cleanly", crash is None and ok is False, str(crash))
    cleanup(tmp)

    # A5: marker path is a DIRECTORY (agent created the wrong thing) -> clean failure
    tmp, ctx, rec, sb = new_case()
    (sb / "_pipeline_done.json").unlink()
    (sb / "_pipeline_done.json").mkdir()
    ok, errs, warns, crash = run_postcheck(ctx, rec)
    check("A5 marker-directory fails cleanly", crash is None and ok is False, str(crash))
    cleanup(tmp)

    # A6: ledger truncated mid-write -> clean failure naming the file
    tmp, ctx, rec, sb = new_case()
    ledger = sb / "revised" / "revision_report.json"
    ledger.write_text(ledger.read_text()[:40])
    ok, errs, warns, crash = run_postcheck(ctx, rec)
    check("A6 truncated ledger fails cleanly and is named",
          crash is None and ok is False and any("revision_report.json" in e for e in errs),
          str(errs[:1]))
    cleanup(tmp)

    # A7: ledger is `null` -> clean failure (exists + parses is not "complete")
    tmp, ctx, rec, sb = new_case()
    (sb / "revised" / "revision_report.json").write_text("null")
    ok, errs, warns, crash = run_postcheck(ctx, rec)
    check("A7 JSON-null ledger fails cleanly", crash is None and ok is False
          and any("revision_report.json" in e for e in errs), str(errs[:1]))
    cleanup(tmp)

    # A8: ledger shapes that ARE a ledger -> accepted (bare list, or a dict with
    # one of the tolerated row keys)
    for label, payload in (
            ("bare list", [{"id": "F-001", "verdict": "fixed"}]),
            ("findings key", {"findings": [{"id": "F-001", "verdict": "fixed"}]}),
            ("revisions key", {"revisions": [{"id": "F-001", "verdict": "fixed"}]}),
            ("rows key", {"rows": [{"id": "F-001", "verdict": "fixed"}]})):
        tmp, ctx, rec, sb = new_case()
        (sb / "revised" / "revision_report.json").write_text(json.dumps(payload))
        ok, errs, warns, crash = run_postcheck(ctx, rec)
        check(f"A8 ledger as {label} is accepted", crash is None and ok is True, str(errs[:1]))
        cleanup(tmp)

    # A8b: the row list named the way the revise skill names it ("coverage
    # table"), as a mapping keyed by finding id, or as an id list -> accepted.
    # Observed failure this pins: r1_a2_revise (42/42) and r2_a2_revise (28/28)
    # wrote complete ledgers under `coverage` / `coverage_table`, were told they
    # named no finding id, and failed every attempt of the stage.
    for label, payload in (
            ("coverage key", {"coverage": [{"id": "F-001", "final_status": "fixed"}]}),
            ("coverage_table key",
             {"run_id": "r2_a2_revise", "stage": "revise", "round": 2,
              "findings_total": 1, "finding_ids": ["F-001"],
              "coverage_table": [{"id": "F-001", "final_status": "fixed",
                                  "edit_ids": ["A7"], "evidence": "A7 hunk 2"}]}),
            ("mapping keyed by finding id",
             {"F-001": {"verdict": "fixed", "evidence": "A7 hunk 2"}}),
            ("id list", {"findings_total": 1, "finding_ids": ["F-001"]})):
        tmp, ctx, rec, sb = new_case()
        (sb / "revised" / "revision_report.json").write_text(json.dumps(payload))
        ok, errs, warns, crash = run_postcheck(ctx, rec)
        check(f"A8b a ledger naming the id via the {label} is accepted",
              crash is None and ok is True, str(errs[:1]))
        cleanup(tmp)

    # A8c: an id that only appears inside prose is not structured naming -> the
    # ledger still fails (the gate must stay a gate).
    tmp, ctx, rec, sb = new_case()
    (sb / "revised" / "revision_report.json").write_text(json.dumps(
        {"summary": "F-001 was reviewed and fixed; details in CHANGELOG.md"}))
    ok, errs, warns, crash = run_postcheck(ctx, rec)
    check("A8c an id that only appears inside a prose string does not count",
          crash is None and ok is False and any("finding id" in e for e in errs),
          str(errs[:1]))
    cleanup(tmp)

    # A8d: a ledger that names only SOME of the frozen ids still fails and names
    # the missing ones (no rubber stamp).
    tmp, ctx, rec, sb = new_case()
    (sb / "revised" / "revision_report.json").write_text(json.dumps(
        {"coverage_table": [{"id": "F-001", "final_status": "fixed"}]}))
    _orig_frozen = nb.frozen_finding_ids
    nb.frozen_finding_ids = lambda ctx_, rec_: ["F-001", "F-002"]
    try:
        ok, errs, warns, crash = run_postcheck(ctx, rec)
    finally:
        nb.frozen_finding_ids = _orig_frozen
    check("A8d a ledger that names only some ids names the missing one and fails",
          crash is None and ok is False and any("F-002" in e for e in errs), str(errs[:1]))
    cleanup(tmp)

    # A9: ledger is an unrecognised-but-non-empty report object while the frozen
    # review lists findings -> rejected. The object names no finding row, so the
    # "no finding silently dropped" property cannot be proven from it (U3); the
    # prompts pin the path and the row contract, so a report object is not a
    # ledger just because it parses.
    tmp, ctx, rec, sb = new_case()
    (sb / "revised" / "revision_report.json").write_text(json.dumps({"status": "done"}))
    ok, errs, warns, crash = run_postcheck(ctx, rec)
    check("A9 an unrecognised report object cannot prove ledger coverage",
          crash is None and ok is False and any("finding id" in e for e in errs),
          str(errs[:1]))
    cleanup(tmp)

    # A9b: ledger is an EMPTY list -> clean failure (nothing was delivered)
    tmp, ctx, rec, sb = new_case()
    (sb / "revised" / "revision_report.json").write_text("[]")
    ok, errs, warns, crash = run_postcheck(ctx, rec)
    check("A9b empty-list ledger fails cleanly", crash is None and ok is False, str(errs[:1]))
    cleanup(tmp)

    # A10: ledger carries a UTF-8 BOM -> accepted
    tmp, ctx, rec, sb = new_case()
    ledger = sb / "revised" / "revision_report.json"
    ledger.write_text("\ufeff" + ledger.read_text())
    ok, errs, warns, crash = run_postcheck(ctx, rec)
    check("A10 BOM-prefixed ledger is accepted", crash is None and ok is True, str(errs[:1]))
    cleanup(tmp)

    # =================================================================
    # B. The agent leaves the wrong KIND of filesystem entry behind
    # =================================================================
    print("== B. filesystem shapes the agent can leave behind ==")

    # B1: base document replaced by a symlink to the base copy (a plausible
    # "save space" trick or a bad `cp -s`) -> repaired, run proceeds
    tmp, ctx, rec, sb = new_case()
    # the package is materialized under the corpus's own spelling (`raw_figs/`);
    # the postcheck canonicalises it to `raw_data/`, which is where the check
    # looks afterwards.
    doc = sb / "revised" / "raw_figs" / "entire_pipeline.git-snapshot.txt"
    tgt = sb / "base" / "raw_figs" / "entire_pipeline.git-snapshot.txt"
    doc.unlink()
    doc.symlink_to(tgt)
    ok, errs, warns, crash = run_postcheck(ctx, rec)
    doc = sb / "revised" / "raw_data" / "entire_pipeline.git-snapshot.txt"
    check("B1 symlinked document does not crash", crash is None, str(crash))
    check("B1 symlinked document is replaced by a regular file",
          doc.is_file() and not doc.is_symlink(), f"is_symlink={doc.is_symlink()}")
    check("B1 the replacement is reported",
          any("RECOVERY" in w and "symlink" in w for w in warns), str(warns[:1]))
    cleanup(tmp)

    # B2: base document replaced by a BROKEN symlink (exists() is False for it)
    tmp, ctx, rec, sb = new_case()
    doc = sb / "revised" / "raw_figs" / "entire_pipeline.git-snapshot.txt"
    doc.unlink()
    doc.symlink_to("/nonexistent/target")
    ok, errs, warns, crash = run_postcheck(ctx, rec)
    doc = sb / "revised" / "raw_data" / "entire_pipeline.git-snapshot.txt"
    check("B2 broken symlink does not crash", crash is None, str(crash))
    check("B2 broken symlink is repaired from the base",
          doc.is_file() and not doc.is_symlink(), f"is_file={doc.is_file()}")
    check("B2 the repair is reported", any("RECOVERY" in w for w in warns), str(warns[:1]))
    cleanup(tmp)

    # B3: base document replaced by an EMPTY directory -> repaired
    tmp, ctx, rec, sb = new_case()
    doc = sb / "revised" / "raw_figs" / "entire_pipeline.git-snapshot.txt"
    doc.unlink()
    doc.mkdir()
    ok, errs, warns, crash = run_postcheck(ctx, rec)
    doc = sb / "revised" / "raw_data" / "entire_pipeline.git-snapshot.txt"
    check("B3 empty-directory placeholder does not crash", crash is None, str(crash))
    check("B3 empty-directory placeholder is repaired",
          doc.is_file() and not doc.is_dir(), f"is_dir={doc.is_dir()}")
    check("B3 the repair is reported",
          any("RECOVERY" in w and "directory" in w for w in warns), str(warns[:1]))
    cleanup(tmp)

    # B4: base document replaced by a NON-EMPTY directory (real work at the wrong
    # path) -> refused with an error, never silently deleted
    doc_rel = "raw_figs/entire_pipeline.git-snapshot.txt"
    tmp = Path(tempfile.mkdtemp(prefix="nbt_stoch_"))
    ctx = build_root(tmp)
    rec, sb = build_revise_sandbox(ctx, drop=(doc_rel,))
    doc = sb / "revised" / "raw_figs" / "entire_pipeline.git-snapshot.txt"
    doc.mkdir()
    (doc / "notes.md").write_text("agent scratch that must not be deleted\n")
    ok, errs, warns, crash = run_postcheck(ctx, rec)
    doc = sb / "revised" / "raw_data" / "entire_pipeline.git-snapshot.txt"
    check("B4 non-empty directory is refused, not deleted",
          crash is None and (doc / "notes.md").is_file(), f"ok={ok}")
    check("B4 the refusal is an error naming the path",
          ok is False and any("NON-EMPTY directory" in e for e in errs), str(errs[:1]))
    cleanup(tmp)

    # =================================================================
    # C. Files the process cannot read (permissions/locks)
    # =================================================================
    print("== C. unreadable files and directories ==")

    # C1: candidate document chmod 000 -> restored from the base, run proceeds
    if RUN_AS_ROOT:
        skip("C1 unreadable candidate file is restored", "running as root: chmod is not enforced")
    else:
        tmp, ctx, rec, sb = new_case()
        doc = sb / "revised" / "raw_figs" / "entire_pipeline.git-snapshot.txt"
        forced_chmod(doc, 0o000)
        ok, errs, warns, crash = run_postcheck(ctx, rec)
        check("C1 unreadable candidate file does not crash", crash is None, str(crash))
        check("C1 unreadable candidate file is restored and hashed",
              ok is True and bool(rec.get("corpus_digest"))
              and any("NOT READABLE" in w for w in warns), f"ok={ok} errs={errs[:1]}")
        cleanup(tmp)

    # C2: an unreadable DIRECTORY under revised/ cannot be walked -> clean
    # failure with the run record left consistent (never a traceback)
    if RUN_AS_ROOT:
        skip("C2 unreadable directory fails cleanly", "running as root: chmod is not enforced")
    else:
        tmp, ctx, rec, sb = new_case()
        d = sb / "revised" / "raw_figs"
        forced_chmod(d, 0o000)
        ok, errs, warns, crash = run_postcheck(ctx, rec)
        check("C2 unreadable candidate directory does not crash the orchestrator",
              crash is None, str(crash))
        check("C2 unreadable candidate directory fails the attempt cleanly",
              ok is False and rec["status"] == "failed" and not rec.get("finished")
              and rec.get("corpus_digest") is None, f"ok={ok} status={rec['status']}")
        check("C2 the failure is reported in the run record",
              bool(errs), str(errs[:1]))
        cleanup(tmp)

    # C3: an unreadable frozen input in an a1 sandbox -> clean failure, no crash
    if RUN_AS_ROOT:
        skip("C3 unreadable a1 input fails cleanly", "running as root: chmod is not enforced")
    else:
        tmp, ctx, rec, sb = new_case()
        a1 = ctx.register("r1_a1", "a1", 1, "runs/r1_a1", source_id="orig")
        a1sb = ctx.sandbox_of(a1)
        a1sb.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ctx.pristine, a1sb / "base", dirs_exist_ok=True)
        a1["inputs_manifest"] = {"base": nb.hash_manifest(a1sb / "base")}
        forced_chmod(a1sb / "base" / "raw_figs" / "entire_pipeline.git-snapshot.txt", 0o000)
        ok, errs, warns, crash = run_postcheck(ctx, a1)
        check("C3 unreadable frozen input does not crash", crash is None, str(crash))
        check("C3 the attempt fails cleanly instead", ok is False and rec is not None, f"ok={ok}")
        cleanup(tmp)

    # =================================================================
    # D. Judge sheets: garbage without crash, and recovery where safe
    # =================================================================
    print("== D. judge-sheet failure modes ==")

    def judge_case(mutate):
        tmp = Path(tempfile.mkdtemp(prefix="nbt_stoch_j_"))
        ctx = build_root(tmp)
        rid = "r1_judge_tABCDEF12_j1"
        sb = ctx.runs_dir / rid
        sb.mkdir(parents=True)
        (sb / "target").mkdir()
        (sb / "original").mkdir()
        (sb / "field").mkdir()
        shutil.copytree(ctx.pristine, sb / "original", dirs_exist_ok=True)
        (sb / "field" / "v1").mkdir()
        shutil.copytree(ctx.pristine, sb / "field" / "v1", dirs_exist_ok=True)
        art = sb / "judge_review" / "artifacts"
        art.mkdir(parents=True)
        (art / "M1_acronyms.md").write_text("| a |\n")
        # The field contains Word documents, so the visual record is part of the
        # judge contract too (this suite is about sheet recovery, not that gate).
        (art / "VIS_visual.md").write_text("Renderer: none; pages not visually verified.\n")
        (sb / "scores.json").write_text(json.dumps(
            {"run_id": rid, "target_id": "tABCDEF12", "round": 1, "judge_index": 1,
             "comparisons": [{"opponent_label": "v1", "score": 1, "reason": "better"}]}))
        (sb / "_pipeline_done.json").write_text(json.dumps(
            {"stage": "judge", "run_id": rid, "round": 1, "status": "complete", "summary": {}}))
        mutate(sb)
        rec = ctx.register(rid, "judge", 1, "runs/" + rid, target_id="a2", judge_index=1,
                           label_map={"v1": "orig"}, judge_target_token="tABCDEF12")
        rec["inputs_manifest"] = {"target": nb.hash_manifest(sb / "target"),
                                  "original": nb.hash_manifest(sb / "original"),
                                  "field": nb.hash_manifest(sb / "field")}
        result = run_postcheck(ctx, rec)
        return tmp, rec, result

    # D1: truncated sheet -> clean failure
    tmp, rec, (ok, errs, warns, crash) = judge_case(
        lambda sb: (sb / "scores.json").write_text('{"run_id": "r1_judge_tABCDEF12_j1", "comp'))
    check("D1 truncated judge sheet fails cleanly", crash is None and ok is False, str(errs[:1]))
    cleanup(tmp)

    # D2: fenced sheet -> recovered, panel keeps the comparison
    tmp, rec, (ok, errs, warns, crash) = judge_case(
        lambda sb: (sb / "scores.json").write_text(
            "```json\n" + (sb / "scores.json").read_text() + "\n```"))
    check("D2 fenced judge sheet is recovered", crash is None and ok is True, str(errs[:1]))
    check("D2 the recovered sheet carries the comparison",
          (rec.get("scores") or {}).get("comparisons") is not None)
    cleanup(tmp)

    # D3: null comparison entry / float score / null label -> clean failures
    def null_entry(sb):
        (sb / "scores.json").write_text(json.dumps(
            {"run_id": "r1_judge_tABCDEF12_j1", "target_id": "tABCDEF12", "round": 1,
             "judge_index": 1,
             "comparisons": [None, {"opponent_label": "v1", "score": 1, "reason": "ok"}]}))
    tmp, rec, (ok, errs, warns, crash) = judge_case(null_entry)
    check("D3a null comparison entry fails cleanly", crash is None and ok is False, str(errs[:1]))
    cleanup(tmp)

    def float_score(sb):
        (sb / "scores.json").write_text(json.dumps(
            {"run_id": "r1_judge_tABCDEF12_j1", "target_id": "tABCDEF12", "round": 1,
             "judge_index": 1,
             "comparisons": [{"opponent_label": "v1", "score": 2.5, "reason": "x"}]}))
    tmp, rec, (ok, errs, warns, crash) = judge_case(float_score)
    check("D3b fractional score fails cleanly (no silent truncation)",
          crash is None and ok is False and any("integer" in e for e in errs), str(errs[:1]))
    cleanup(tmp)

    def null_label(sb):
        (sb / "scores.json").write_text(json.dumps(
            {"run_id": "r1_judge_tABCDEF12_j1", "target_id": "tABCDEF12", "round": 1,
             "judge_index": 1,
             "comparisons": [{"opponent_label": None, "score": 1, "reason": "x"}]}))
    tmp, rec, (ok, errs, warns, crash) = judge_case(null_label)
    check("D3c null opponent label fails cleanly (panel integrity kept)",
          crash is None and ok is False and any("omit" in e for e in errs), str(errs[:1]))
    cleanup(tmp)

    # =================================================================
    # E. Review-stage rejection paths stay clean
    # =================================================================
    print("== E. review-stage failure modes ==")

    def review_case(mutate):
        tmp = Path(tempfile.mkdtemp(prefix="nbt_stoch_r_"))
        ctx = build_root(tmp)
        rid = "r1_a2_review"
        sb = ctx.runs_dir / rid
        sb.mkdir(parents=True)
        shutil.copytree(ctx.pristine, sb / "base")
        shutil.copytree(ctx.pristine, sb / "non-revised")
        (sb / "review").mkdir()
        (sb / "review" / "findings.json").write_text(json.dumps(
            {"submission_dir": "./base", "guidelines_source": "t",
             "findings": [{"id": "F-001", "location": "x", "category": 0, "check": "M1",
                           "severity": "Minor", "evidence": "e", "explanation": "x",
                           "status": "resolvable"}], "artifacts": {}, "coverage": []}))
        (sb / "_pipeline_done.json").write_text(json.dumps(
            {"stage": "review", "run_id": rid, "round": 1, "status": "complete"}))
        mutate(sb)
        rec = ctx.register(rid, "review", 1, "runs/" + rid, source_id="a1")
        rec["inputs_manifest"] = {"base": nb.hash_manifest(sb / "base"),
                                  "non-revised": nb.hash_manifest(sb / "non-revised")}
        result = run_postcheck(ctx, rec)
        return tmp, rec, result

    tmp, rec, (ok, errs, warns, crash) = review_case(
        lambda sb: (sb / "review" / "findings.json").write_text('["F-001"]'))
    check("E1 findings.json as a list fails cleanly", crash is None and ok is False, str(errs[:1]))
    cleanup(tmp)

    tmp, rec, (ok, errs, warns, crash) = review_case(
        lambda sb: (sb / "review" / "findings.json").write_text("null"))
    check("E2 findings.json as JSON null fails cleanly",
          crash is None and ok is False and any("JSON object" in e for e in errs), str(errs[:1]))
    cleanup(tmp)

    tmp, rec, (ok, errs, warns, crash) = review_case(
        lambda sb: (sb / "review" / "findings.json").write_text(
            (sb / "review" / "findings.json").read_text()[:120]))
    check("E3 truncated findings.json fails cleanly",
          crash is None and ok is False and any("malformed" in e for e in errs), str(errs[:1]))
    cleanup(tmp)

    print()
    if SKIPS:
        print(f"skipped {len(SKIPS)}: {', '.join(SKIPS)}")
    if FAILS:
        print(f"{len(FAILS)} STOCHASTIC-FAILURE CHECK(S) FAILED")
        for name in FAILS:
            print("  -", name)
        return 1
    print("ALL STOCHASTIC-FAILURE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Checks for the round-4 audit findings (judge bias, retry context, visual gate).

Each check is written to PASS while the defect is present, so this file is the
reproduction for the findings recorded in
`nbt_audit_data/PIPELINE_AUDIT_FINDINGS.md`. When a finding is fixed, the
matching check must be inverted (see the note in each section) -- it is a
regression guard for the defect, not for the fix.

Run:  python3 .nbt_test/test_pipeline_audit_findings.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_audit", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_audit"] = nb
spec.loader.exec_module(nb)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_document_recovery import build_root  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def make_version(root: Path, vid: str, when: float, prose: str, sandbox: str = None):
    """One version corpus: the stage's output dir + the mandated bookkeeping.

    The output directory comes from the pipeline itself (revised/ for a revised
    candidate, rewritten/ for a rewritten one, integrated/ for an integrated
    one), so this helper cannot drift from the corpus contract. The round's base
    lives in its a1 sandbox's base/ instead (it is a copy, not an output).
    """
    run_dir = root / "runs" / (sandbox or f"r1_{vid}")
    rev = run_dir / "base" if vid == nb.A1_ID else run_dir / nb.output_dir_for_vid(vid)
    rev.mkdir(parents=True, exist_ok=True)
    (rev / "manuscript-p.docx").write_bytes(b"PK\x03\x04 fake docx for " + vid.encode())
    (rev / "README.md").write_text(f"# {prose}\n")
    (rev / "CHANGELOG.md").write_text(f"# changelog\n{prose}\n")
    (rev / "revision_report.json").write_text(json.dumps([{"id": "F-001", "verdict": "fixed"}]))
    for p in [rev, *rev.rglob("*")]:
        os.utime(p, (when, when))
    return rev


def judge_sandbox_manifest(ctx, target_vid, field_vids, times):
    """Materialize a judge sandbox exactly as the pipeline does and read it back."""
    tmp = Path(tempfile.mkdtemp(prefix="judge_manifest_"))
    root = ctx.root
    fresh = [target_vid, *field_vids]
    for vid, when in zip(fresh, times):
        make_version(root, vid, when, f"version {vid}")
    for vid in fresh:
        rid = nb.rid_for_fresh(1, vid)
        sid = "a1" if vid == nb.A1_ID else nb.arm_of_vid(vid)
        rec = ctx.register(rid, sid, 1, f"runs/{rid}", source_id="a1", produces=vid)
        rec["status"] = "done"
        rec["corpus_digest"] = nb.recompute_corpus_digest(ctx, 1, vid)
        rec["content_fingerprint"] = nb.corpus_content_fingerprint(ctx, 1, vid)
    field = [{"id": v, "digest": ctx.run(nb.rid_for_fresh(1, v))["corpus_digest"],
              "kind": "fresh"} for v in fresh]
    nb.materialize_judges(ctx, 1, field)
    return root, tmp


def main() -> int:
    # =================================================================
    # F1 - FIXED (C01): judge sandboxes must NOT carry per-version timestamps,
    #   and the prompt must name metadata as an unusable signal. The pre-fix
    #   reproduction is frozen in
    #   nbt_audit_data/repros/test_audit_findings_prepatch.py (F1a-F1d).
    # =================================================================
    print("== F1. judged views carry no version-order metadata ==")
    tmp = Path(tempfile.mkdtemp(prefix="nbt_f1_"))
    try:
        ctx = build_root(tmp)
        # a2 is produced by revise; w1 by the rewrite stage; i1/i2 are integrated
        now = time.time()
        ctx.cfg["rewrites"], ctx.cfg["revises"] = [1], [1]   # pool: a1, w1, a2
        rev = make_version(tmp, "a2", now - 4000, "first revision")
        make_version(tmp, "w1", now - 2000, "rewrite of the base")
        make_version(tmp, "i1", now - 500, "integration of a1 with w1 and a2")

        # the pipeline copies a version corpus into a judge sandbox with
        # copy_into(), which preserves mtimes (shutil.copy2)
        dest = tmp / "judge_target"
        nb.copy_into(rev, dest, skip_aux=True, strip_bookkeeping=True,
                     normalize_mtime=True)
        m = (dest / "manuscript-p.docx").stat().st_mtime
        check("F1a the judged copy does NOT keep the version's original mtime",
              abs(m - (now - 4000)) > 60, f"src={now-4000:.0f} dst={m:.0f}")

        # and the spread is large enough to order the versions
        times = [rev.stat().st_mtime,
                 (tmp / "runs/r1_w1/rewritten").stat().st_mtime,
                 (tmp / "runs/r1_i1/integrated").stat().st_mtime]
        spread = max(times) - min(times)
        # the SOURCE sandboxes still differ (they are the run's own record); what
        # matters is that the materialized views do not carry that difference --
        # asserted on a real judge sandbox by F1e below.
        check("F1b source sandboxes do differ in mtime (so the leak would be real)",
              spread > 60, f"spread={spread:.0f}s")
        # behavioural: nested files are equalized too
        nested = tmp / "deep" / "sub"
        nested.mkdir(parents=True)
        (nested / "doc.md").write_text("x\n")
        os.utime(nested / "doc.md", (now - 9999, now - 9999))
        dest2 = tmp / "judge_field_v1"
        nb.copy_into(tmp / "deep", dest2, normalize_mtime=True)
        check("F1c nested field files are equalized as well",
              abs((dest2 / "sub" / "doc.md").stat().st_mtime - (now - 9999)) > 60)

        # the judge prompt must warn about exactly this; it does not
        prompt_text = " ".join(
            [nb.JUDGE_DIRECTIVES, nb.VISUAL_INSPECTION_RULE, nb.AUX_FILES_RULE])
        has_mtime_rule = bool(re.search(r"(?i)(mtime|modification time|timestamp)", prompt_text))
        check("F1d the judge prompt names metadata (mtimes) as an unusable signal",
              has_mtime_rule and "File METADATA says nothing" in nb.JUDGE_DIRECTIVES)

        # F1e: asserted on a REAL judge sandbox built by the pipeline, not on the
        # helper: every view the judge can see carries one and the same mtime.
        tmp1 = Path(tempfile.mkdtemp(prefix="nbt_f1e_"))
        ctx1 = build_root(tmp1)
        # materialize_judges() requires the full fresh field: register a1 too.
        a1sb = ctx1.root / "runs" / "r1_a1" / "base"
        a1sb.mkdir(parents=True)
        shutil.copy2(ctx1.pristine / "raw_figs" / "entire_pipeline.git-snapshot.txt",
                     a1sb / "manuscript-p.docx")
        a1rec = ctx1.register("r1_a1", "a1", 1, "runs/r1_a1", source_id="orig")
        a1rec["status"] = "done"
        a1rec["corpus_digest"] = nb.recompute_corpus_digest(ctx1, 1, "a1")
        a1rec["content_fingerprint"] = nb.corpus_content_fingerprint(ctx1, 1, "a1")
        ctx1.cfg["rewrites"], ctx1.cfg["revises"] = [1], [1]   # pool: a1, w1, a2
        stamps = {}
        for vid, sandbox, delta in (("w1", "r1_w1", -7000), ("a2", "r1_a2_revise", -6000),
                                    ("i1", "r1_i1", -4000), ("i2", "r1_i2", -3000),
                                    ("i3", "r1_i3", -2000)):
            d = ctx1.root / "runs" / sandbox / nb.output_dir_for_vid(vid)
            d.mkdir(parents=True)
            (d / "manuscript-p.docx").write_bytes(b"PK " + vid.encode())
            when = time.time() + delta
            for q in (d, d / "manuscript-p.docx"):
                os.utime(q, (when, when))
            r = ctx1.register(sandbox, {"a2": "revise", "w1": "rewrite"}.get(vid, "integrate"), 1,
                              f"runs/{sandbox}", source_id="a1", produces=vid)
            r["status"] = "done"
            r["corpus_digest"] = nb.recompute_corpus_digest(ctx1, 1, vid)
            r["content_fingerprint"] = nb.corpus_content_fingerprint(ctx1, 1, vid)
            stamps[vid] = when
        field = [{"id": v, "digest": ctx1.run(nb.rid_for_fresh(1, v))["corpus_digest"],
                  "kind": "fresh"} for v in ("w1", "a2", "i1", "i2", "i3")]
        nb.materialize_judges(ctx1, 1, field)
        # A judge run id is an OPAQUE token (no round/arm prefix), so the run is
        # found by kind, not by a glob on its name.
        sb = ctx1.sandbox_of(ctx1.runs(kind="judge", round_no=1)[0])
        views = [sb / "target"] + sorted((sb / "field").iterdir())
        # Judge views are ANONYMIZED now (opaque "f0001<ext>" names), so the
        # check walks every file it can see instead of one known file name.
        mtimes = {round(p.stat().st_mtime) for d in views for p in d.rglob("*")}
        check("F1e a real judge sandbox shows ONE mtime across target/ and field/*",
              len(mtimes) == 1, f"{len(mtimes)} distinct mtimes")
        per_view = [sorted(p.name for p in d.rglob("*") if p.is_file()) for d in views]
        check("F1e' those views still carry the document (nothing was dropped)",
              all(len(v) == 1 for v in per_view), str(per_view))
        check("F1e'' judge views are anonymized (no source name survives)",
              all(not any("manuscript" in n for n in v) for v in per_view), str(per_view))
        shutil.rmtree(tmp1, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # =================================================================
    # F2 - FIXED (C02): the label permutation must depend on the per-root
    #   secret, exactly as judge_token_for does. Pre-fix reproduction:
    #   nbt_audit_data/repros/test_audit_findings_prepatch.py (F2a/F2b/F2b').
    # =================================================================
    print("== F2. judge label -> version mapping is not recomputable ==")
    a = nb.sample_labels(1, "a2", 1, 3, salt="root-secret-A")
    b = nb.sample_labels(1, "a2", 1, 3, salt="root-secret-A")
    c = nb.sample_labels(1, "a2", 1, 3, salt="root-secret-B")
    check("F2a the permutation is reproducible for ONE root (re-runs keep the mapping)",
          a == b, f"{a} vs {b}")
    # The judge is TOLD the target_id token, the round and its judge index, so a
    # judge that knows the pipeline can brute-force the small id space. Nothing
    # in the call depends on the per-root salt that protects the session token.
    # behavioural: judge_token_for() mixes in the per-root secret, so the same
    # (round, version, judge) yields DIFFERENT tokens in different roots. The
    # label permutation must behave the same way to be unguessable from inside
    # a sandbox; it does not - it is a pure function of public inputs.
    roots = []
    for salt in ("root-secret-A", "root-secret-B"):
        tmp = Path(tempfile.mkdtemp(prefix="nbt_salt_"))
        ctx = build_root(tmp)
        ctx.state["judge_salt"] = salt
        roots.append((ctx, tmp))
    token_a = nb.judge_token_for(roots[0][0], 1, "a2")
    token_b = nb.judge_token_for(roots[1][0], 1, "a2")
    labels_a = nb.sample_labels(1, "a2", 1, 3, salt=nb.judge_salt_of(roots[0][0]))
    labels_b = nb.sample_labels(1, "a2", 1, 3, salt=nb.judge_salt_of(roots[1][0]))
    check("F2b the session token changes with the per-root secret",
          token_a != token_b, f"{token_a} vs {token_b}")
    check("F2b' the label permutation changes with it too (no in-sandbox brute force)",
          labels_a != labels_b, f"{labels_a} vs {labels_b}")
    check("F2b'' the permutation is still deterministic WITHIN a root",
          labels_a == nb.sample_labels(1, "a2", 1, 3, salt=nb.judge_salt_of(roots[0][0])))
    for _ctx, t in roots:
        shutil.rmtree(t, ignore_errors=True)
    check("F2c the public label space is a permutation of the small v1..vk set",
          sorted(nb.sample_labels(1, "a2", 1, 4, salt=nb.judge_salt_of(roots[0][0])))
          == ["v1", "v2", "v3", "v4"])
    check("F2d a legacy root with no salt keeps the old, unsalted mapping",
          nb.sample_labels(1, "a2", 1, 3, salt="") == nb.sample_labels(1, "a2", 1, 3))

    # =================================================================
    # F3 - FIXED (C06): a "visually inspected" claim must be evidenced by
    #   rendered pages, while the documented "not visually verified" escape
    #   hatch stays open. Pre-fix reproduction: F3a in
    #   nbt_audit_data/repros/test_audit_findings_prepatch.py (the claim passed
    #   with nothing rendered).
    # =================================================================
    print("== F3. visual-inspection claims are evidenced ==")
    tmp = Path(tempfile.mkdtemp(prefix="nbt_f3_"))
    try:
        art = tmp / "VISUAL_CHECK.md"
        art.write_text("Renderer: LibreOffice 7.6. All 12 pages rendered and looked at; "
                       "no defects found. No corrections needed.\n")
        errs, warns = [], []
        nb.check_visual_artifact(art, "the visual-inspection record", errs, warns,
                                 render_roots=[tmp])
        check("F3a a full visual claim with NO rendered files now FAILS",
              bool(errs) and any("no rendered page" in e for e in errs), f"errs={errs[:1]}")
        (tmp / "page-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        errs, warns = [], []
        nb.check_visual_artifact(art, "the visual-inspection record", errs, warns,
                                 render_roots=[tmp])
        check("F3b the same claim with a rendered page passes",
              not errs, f"errs={errs[:1]}")
        (tmp / "page-1.png").unlink()
        art.write_text("Renderer: none available. All pages NOT visually verified; "
                       "rendering handed to the author in MANUAL_STEPS.md.\n")
        errs, warns = [], []
        nb.check_visual_artifact(art, "the visual-inspection record", errs, warns,
                                 render_roots=[tmp])
        check("F3c the documented escape hatch still passes (with a warning)",
              not errs and warns, f"errs={errs[:1]}")
        check("F3d the pipeline detects renderers on this machine (so it can check)",
              nb.visual_tools_available())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # =================================================================
    # F4 - FIXED (C03): a retried attempt must be told why the last one failed.
    #   Pre-fix reproduction: F4a/F4b in
    #   nbt_audit_data/repros/test_audit_findings_prepatch.py (the regenerated
    #   prompt was byte-identical to the first attempt's).
    # =================================================================
    print("== F4. retry prompts carry the previous failure ==")
    tmp = Path(tempfile.mkdtemp(prefix="nbt_f4_"))
    try:
        ctx = build_root(tmp)
        sb = tmp / "runs" / "r1_a2_revise"
        sb.mkdir(parents=True)
        (sb / "base").mkdir()
        (sb / "base" / "manuscript.md").write_text("text\n")
        (sb / "revised").mkdir()
        (sb / "revised" / "manuscript.md").write_text("text revised\n")
        failure = ("revised/revision_report.json is EMPTY/unfinished (structured output): it "
                   "lists no revision row at all")
        # a first attempt (no failure recorded) gets the neutral block
        p_first = nb.revise_prompt(sb, "r1_a2_revise", 1, prior_failure=nb.prior_failure_block({}))
        check("F4a the first attempt's prompt is neutral (no false failure claim)",
              "FIRST ATTEMPT" in p_first and failure not in p_first)
        rec = ctx.register("r1_a2_revise", "revise", 1, "runs/r1_a2_revise", source_id="a1")
        rec["last_error"] = failure
        rec["postcheck"] = {"ok": False, "errors": [failure], "warnings": []}
        note = nb.prior_failure_block(rec)
        p2 = nb.revise_prompt(sb, "r1_a2_revise", 1, prior_failure=note)
        check("F4b the retry prompt carries the previous failure",
              failure in p2 and "PREVIOUS ATTEMPT FAILED" in p2)
        check("F4c the failure text is fenced as data, not as an instruction",
              "not an instruction" in p2)
        check("F4d no placeholder is left in any directive template",
              "@@PRIOR_FAILURE@@" not in p2)
        # cross and review prompts get the same block
        p_cross = nb.integrate_prompt(sb, "r1_i1", 1, "a1", ["w1", "a2"], prior_failure=note)
        check("F4e the cross prompt carries it too",
              failure in p_cross and "@@PRIOR_FAILURE@@" not in p_cross)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    # =================================================================
    # F5 - FIXED (C04): the agent's own bookkeeping must NOT reach a judge
    #   corpus or a pin. The pre-fix reproduction (same fixture, all six files
    #   leaking) is frozen in
    #   nbt_audit_data/repros/test_audit_findings_prepatch.py.
    # =================================================================
    print("== F5. judge/pinned corpora exclude the agent's bookkeeping ==")
    tmp = Path(tempfile.mkdtemp(prefix="nbt_f5_"))
    try:
        ctx = build_root(tmp)
        # the pipeline's revise run for a2 is r1_a2_revise - the sandbox
        # corpus_sources() reads
        rev = make_version(ctx.root, "a2", time.time(), "first revision",
                           sandbox="r1_a2_revise")
        # the mandated bookkeeping set from the revise/cross prompts
        for name in ("MANUAL_STEPS.md", "REVISION_REPORT.md", "DIFF_LEDGER.md",
                     "VISUAL_CHECK.md"):
            (rev / name).write_text("# pipeline bookkeeping\n")
        rec = ctx.register("r1_a2_revise", "revise", 1, "runs/r1_a2_revise", source_id="a1")
        rec["status"] = "done"
        rec["corpus_digest"] = nb.recompute_corpus_digest(ctx, 1, "a2")
        dest = ctx.root / "judge_target"
        nb.build_corpus_dir(ctx, 1, "a2", dest)
        present = sorted(p.name for p in dest.iterdir() if p.is_file())
        leaked = [n for n in ("CHANGELOG.md", "MANUAL_STEPS.md", "REVISION_REPORT.md",
                              "revision_report.json", "DIFF_LEDGER.md", "VISUAL_CHECK.md")
                  if n in present]
        check("F5a the judge target carries none of the agent's bookkeeping files",
              not leaked, f"leaked={leaked}")
        check("F5b the judge target still carries the submission document",
              "manuscript-p.docx" in present, f"present={present}")
        manifest_files = set(nb.corpus_manifest(ctx, 1, "a2")["files"])
        check("F5c the recorded corpus identity excludes bookkeeping too (pins stay verifiable)",
              not any(f.lower() in nb.CORPORA_STRIP_BOOKKEEPING for f in manifest_files),
              f"manifest={sorted(manifest_files)}")
        check("F5d the sandbox keeps the bookkeeping (postchecks/manual count read it there)",
              (rev / "MANUAL_STEPS.md").is_file() and (rev / "CHANGELOG.md").is_file())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for name in FAILS:
            print("  -", name)
        return 1
    print("AUDIT SUITE PASSED")
    print("  asserted as FIXED: F1 (C01 metadata leak), F2 (C02 label seeding), "
          "F3 (C06 visual gate), F4 (C03 retry context), F5 (C04 bookkeeping leak)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

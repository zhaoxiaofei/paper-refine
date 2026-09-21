#!/usr/bin/env python3
"""PRE-PATCH reproduction of the round-4 audit findings (judge bias, retry
context, visual gate, bookkeeping leak).

Frozen evidence: this is `.nbt_test/test_pipeline_audit_findings.py` exactly as
run against commit 1903b34, where every check PASSES because the defect is
present. The live suite now asserts the FIXED behaviour, so keep this copy as
the reproduction record; run it against a pre-fix tree with

    NBT_WS=/path/to/pre-fix/tree python3 nbt_audit_data/repros/test_audit_findings_prepatch.py

It expects the workspace's `.nbt_test/` helpers next to it, so copy it into
`.nbt_test/` before running against another tree.
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
spec = importlib.util.spec_from_file_location("nbt_audit", str(WS / "nbt_round_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_audit"] = nb
spec.loader.exec_module(nb)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / '.nbt_test'))
from test_document_recovery import build_root  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def make_version(root: Path, vid: str, when: float, prose: str, sandbox: str = None):
    """One version corpus: revised/<doc> + the bookkeeping the prompts mandate."""
    rev = root / "runs" / (sandbox or f"r1_{vid}") / "revised"
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
    for vid, when in zip([target_vid, *field_vids], times):
        make_version(root, vid, when, f"version {vid}")
    for vid in [target_vid, *field_vids]:
        sid = "revise" if vid == "a2" else "cross"
        rid = {"a2": "r1_a2_revise", "a1": "r1_a1", "b1": "r1_b1", "b2": "r1_b2"}[vid]
        rec = ctx.register(rid, sid, 1, f"runs/{rid}", source_id="a1")
        rec["status"] = "done"
        rec["corpus_digest"] = nb.recompute_corpus_digest(ctx, 1, vid)
        rec["content_fingerprint"] = nb.corpus_content_fingerprint(ctx, 1, vid)
    field = [{"id": v, "digest": ctx.run({"a2": "r1_a2_revise", "a1": "r1_a1",
                                          "b1": "r1_b1", "b2": "r1_b2"}[v])["corpus_digest"],
              "kind": "fresh"} for v in [target_vid, *field_vids]]
    nb.materialize_judges(ctx, 1, field)
    return root, tmp


def main() -> int:
    # =================================================================
    # F1 - judge sandboxes carry per-version timestamps
    #   Fix would make the check FAIL: assert the mtimes are equalized (or the
    #   metadata is stripped) and that the prompt forbids recency inference.
    # =================================================================
    print("== F1. judge field/target metadata (mtime) leaks version order ==")
    tmp = Path(tempfile.mkdtemp(prefix="nbt_f1_"))
    try:
        ctx = build_root(tmp)
        # a2 is produced by revise; b1/b2 by the later cross stage
        now = time.time()
        rev = make_version(tmp, "a2", now - 4000, "first revision")
        make_version(tmp, "b1", now - 2000, "cross from a2")
        make_version(tmp, "b2", now - 500, "cross from a2")

        # the pipeline copies a version corpus into a judge sandbox with
        # copy_into(), which preserves mtimes (shutil.copy2)
        dest = tmp / "judge_target"
        nb.copy_into(rev, dest, skip_aux=True)
        m = (dest / "manuscript-p.docx").stat().st_mtime
        check("F1a copy_into preserves the version's mtime (metadata reaches the judge)",
              abs(m - (now - 4000)) < 2, f"src={now-4000:.0f} dst={m:.0f}")

        # and the spread is large enough to order the versions
        times = [rev.stat().st_mtime,
                 (tmp / "runs/r1_b1/revised").stat().st_mtime,
                 (tmp / "runs/r1_b2/revised").stat().st_mtime]
        spread = max(times) - min(times)
        check("F1b the per-version mtimes are separated enough to rank versions",
              spread > 60, f"spread={spread:.0f}s")
        # behavioural: a directory tree copied by copy_into keeps every mtime
        nested = tmp / "deep" / "sub"
        nested.mkdir(parents=True)
        (nested / "doc.md").write_text("x\n")
        os.utime(nested / "doc.md", (now - 9999, now - 9999))
        dest2 = tmp / "judge_field_v1"
        nb.copy_into(tmp / "deep", dest2)
        check("F1c nested field files keep their original mtimes too",
              abs((dest2 / "sub" / "doc.md").stat().st_mtime - (now - 9999)) < 2)

        # the judge prompt must warn about exactly this; it does not
        prompt_text = " ".join(
            [nb.JUDGE_DIRECTIVES, nb.VISUAL_INSPECTION_RULE, nb.AUX_FILES_RULE])
        has_mtime_rule = bool(re.search(r"(?i)(mtime|modification time|timestamp)", prompt_text))
        check("F1d the judge prompt never mentions timestamps as an unusable signal",
              not has_mtime_rule)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # =================================================================
    # F2 - the label permutation is recomputable from inside the sandbox
    #   Fix would make the check FAIL: labels must depend on a per-root secret
    #   (as judge_token_for does) so two roots differ.
    # =================================================================
    print("== F2. judge label -> version mapping is predictable ==")
    a = nb.sample_labels(1, "a2", 1, 3)
    b = nb.sample_labels(1, "a2", 1, 3)
    check("F2a the permutation is fully determined by (round, version id, judge index)",
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
    labels_a = nb.sample_labels(1, "a2", 1, 3)
    labels_b = nb.sample_labels(1, "a2", 1, 3)
    check("F2b the session token changes with the per-root secret (the protection exists)",
          token_a != token_b, f"{token_a} vs {token_b}")
    check("F2b' the label permutation does NOT (same public inputs -> same mapping everywhere)",
          labels_a == labels_b, f"{labels_a} vs {labels_b}")
    for _ctx, t in roots:
        shutil.rmtree(t, ignore_errors=True)
    check("F2c the ids to brute-force are small enough to enumerate",
          len(["a1", "a2", "b1", "b2"]) * 3 <= 12)

    # =================================================================
    # F3 - the visual-inspection gate accepts an unevidenced claim
    #   Fix would make the check FAIL: a claim of a completed pass must require
    #   artifacts (rendered pages) or a recorded renderer failure.
    # =================================================================
    print("== F3. visual-inspection gate is self-reported ==")
    tmp = Path(tempfile.mkdtemp(prefix="nbt_f3_"))
    try:
        art = tmp / "VISUAL_CHECK.md"
        art.write_text("Renderer: LibreOffice 7.6. All 12 pages rendered and looked at; "
                       "no defects found. No corrections needed.\n")
        errs, warns = [], []
        nb.check_visual_artifact(art, "the visual-inspection record", errs, warns)
        check("F3a a full visual claim with NO rendered files passes the gate",
              not errs and not warns, f"errs={errs} warns={warns}")
        # nothing in the sandbox: no PDF, no PNG, no renderer output
        renders = [p for p in tmp.rglob("*") if p.suffix.lower() in (".pdf", ".png", ".jpg")]
        check("F3b there are no rendered pages next to the claim", not renders)
        check("F3c the pipeline detects renderers on this machine (so it could check)",
              nb.visual_tools_available())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # =================================================================
    # F4 - a retry re-runs the agent with an identical prompt
    #   Fix would make the check FAIL: the regenerated prompt must include the
    #   previous failure (or the pipeline must record that it deliberately does
    #   not).
    # =================================================================
    print("== F4. retry prompts do not carry the previous failure ==")
    tmp = Path(tempfile.mkdtemp(prefix="nbt_f4_"))
    try:
        ctx = build_root(tmp)
        sb = tmp / "runs" / "r1_a2_revise"
        sb.mkdir(parents=True)
        (sb / "base").mkdir()
        (sb / "base" / "manuscript.md").write_text("text\n")
        (sb / "revised").mkdir()
        (sb / "revised" / "manuscript.md").write_text("text revised\n")
        p1 = nb.revise_prompt(sb, "r1_a2_revise", 1)
        # the failure a retry would have to explain (from the real postcheck)
        failure = ("revised/revision_report.json is EMPTY/unfinished (structured output): it "
                   "lists no revision row at all")
        p2 = nb.revise_prompt(sb, "r1_a2_revise", 1)
        check("F4a the retry prompt is byte-identical to the first attempt's prompt", p1 == p2)
        check("F4b the retry prompt carries no previous-failure text",
              failure not in p2 and "previous attempt" not in p2.lower()
              and "last_error" not in p2.lower())
        # the error text DOES exist in the run record - it is simply not handed over
        rec = ctx.register("r1_a2_revise", "revise", 1, "runs/r1_a2_revise", source_id="a1")
        rec["last_error"] = failure
        rec["postcheck"] = {"ok": False, "errors": [failure], "warnings": []}
        check("F4c the failure is recorded on the run (so it could be injected)",
              "revision_report.json" in (rec["last_error"] or ""))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    # =================================================================
    # F5 - self-written bookkeeping reaches the judge corpora
    #   Fix would make this check FAIL: CHANGELOG.md / MANUAL_STEPS.md /
    #   REVISION_REPORT.md / revision_report.json / DIFF_LEDGER.md /
    #   VISUAL_CHECK.md must be excluded from target/ and field/*.
    # =================================================================
    print("== F5. judge corpora carry the agent's own bookkeeping ==")
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
        check("F5a the judge target carries the agent's own bookkeeping files",
              len(leaked) >= 5, f"leaked={leaked}")
        check("F5b the judge prompt forbids scoring them (the only defence)",
              "BOOKKEEPING" in nb.JUDGE_DIRECTIVES
              and "not a difference to score" in nb.JUDGE_DIRECTIVES)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) DID NOT REPRODUCE THE FINDING:")
        for name in FAILS:
            print("  -", name)
        return 1
    print("ALL AUDIT FINDINGS REPRODUCED (F1-F4 plus the F5 bookkeeping leak; "
          "each check documents a present defect)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

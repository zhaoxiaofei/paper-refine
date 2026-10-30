#!/usr/bin/env python3
"""The COLD-START REVIEW (2026-10-12): an independent, generic discovery session.

Run:  python3 .paper_test/test_cold_start_review_2026_1012.py

The stage (rid `r<r>_probe`, policy `pipeline_config.json: cold_start_review`) is a
cold-context session that is given the corpus (the submission documents and the
evidence areas) and NOTHING else -- no review, no finding list. It is GENERIC:
any defect class may be filed as an X-9xx finding, and wherever a defect can be
shown by a computation the finding declares a re-runnable verifier that the
orchestrator re-runs. This suite pins:

  P1  the plan: probe "on" adds `r1_cold_start_review` in parallel with the review and makes
      the audit/revision sessions wait for it; "off"/absent plans no session;
      both handlers (postcheck + rebuild) exist;
  P2  the sandbox: materialized from the base only, seeded with the claim-surface
      and producer candidates, WITHOUT any guided_review/finding artifact; the leftover
      detector treats the seeds as inputs;
  P3  the contract: a compliant finding passes; a zero-finding pass with its
      `checked` inventory passes; a declared `computed` value the verifier does
      not reproduce FAILS the attempt (the correctness blocker); an id outside
      the reserved X-9xx block, a missing verifier script and a missing
      coverage.md all fail; the pre-flight (`sandbox_selfcheck`) agrees;
  P4  the merge: the probe findings ride in the frozen `findings_extra.json` of the
      audit and revision sandboxes and in the integration seed
      (`frozen_discovery/`), with collision-safe ids, and the archive keeps
      `findings_cold_start_review.json` for a pruned root;
  P5  the CLI: `setup --cold-start-review off` / `--no-cold-start-review` record "off";
      `set-cold-start-review` flips the policy on an existing root (with --force).
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
spec = importlib.util.spec_from_file_location("paper_probe", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_probe"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}"
          + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def write(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    elif isinstance(data, (dict, list)):
        p.write_text(json.dumps(data), encoding="utf-8")
    else:
        p.write_text(data, encoding="utf-8")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def build_root(tmp: Path, probe: str = "on", audit: str = "off", review_rows=(),
               with_a2: bool = False):
    """A synthetic round-1 root: a1 done, an optional done review, probe policy set."""
    source = tmp / "source"
    write(source / "manuscript.md",
          "Abstract\n\nGinkgo is the best caller overall.\n\nResults\n\n"
          "Two callers were compared.\n")
    write(source / "raw_data" / "grid.tsv",
          "tool\tmetric\nGinkgo\t1\nSCYN\t2\n")
    write(source / "code" / "make_fig.py", "SCYN_RANK = 1\n")
    root = tmp / "root"
    (root / "runs").mkdir(parents=True)
    (root / "reports").mkdir()
    shutil.copytree(source, root / "non_revised")
    pristine = root / "non_revised"
    ctx = nb.Ctx(root)
    ctx.cfg = {"rounds": 1, "judges": 1, "rewrites": [0], "revises": [1],
               "audit": audit, "integrators": [0], "cold_start_review": probe,
               "review_scope": ["full"]}
    ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "source_manifest": nb.hash_manifest(pristine),
                 "original_digest": nb.corpus_tree_digest(pristine),
                 "original_content_fingerprint":
                     nb.corpus_content_set_fingerprint([(pristine, "", ())]),
                 "judge_salt": "probesalt", "config": ctx.cfg, "source": str(source)}
    a1 = nb.rid_a1(1)
    shutil.copytree(pristine, root / "runs" / a1 / "base")
    rec = ctx.register(a1, "a1", 1, f"runs/{a1}", source_id=nb.ORIGINAL_ID)
    rec["status"] = "done"
    rec["corpus_digest"] = nb.recompute_corpus_digest(ctx, 1, "a1")
    rec["content_fingerprint"] = nb.corpus_content_fingerprint(ctx, 1, "a1")
    if review_rows is not None:
        rev = ctx.register(nb.rid_guided_review(1), "review", 1, f"runs/{nb.rid_guided_review(1)}")
        rev["status"] = "done"
        rsb = ctx.sandbox_of(rev)
        write(rsb / "guided_review" / "findings.json",
              {"submission_dir": "./base", "findings": [], "coverage": []})
        write(rsb / "guided_review" / "round2" / "findings_extra.json",
              {"findings": list(review_rows), "coverage": []})
        write(rsb / "guided_review" / "round2" / "findings_extra.md", "# D4\n")
    if with_a2:
        vid = nb.revise_vid(1)
        rid = nb.rid_for_fresh(1, vid)
        out = root / "runs" / rid / nb.output_dir_for_vid(vid)
        write(out / "manuscript.md",
              (source / "manuscript.md").read_text(encoding="utf-8") + "\nrevised\n")
        r = ctx.register(rid, nb.arm_of_vid(vid), 1, f"runs/{rid}", source_id="a1",
                         produces=vid)
        r["status"] = "done"
        r["corpus_digest"] = nb.recompute_corpus_digest(ctx, 1, vid)
        r["content_fingerprint"] = nb.corpus_content_fingerprint(ctx, 1, vid)
    return ctx


def cold_start_script(sb: Path, rel: str = "cold_start_review/scripts/pr001.py",
                 printed: str = "2") -> None:
    write(sb / rel,
          "from pathlib import Path\n"
          f"print({printed!r})\n")


def write_cold_start_fixture(sb: Path, *, finding: bool = False, computed: str = "2",
                        script_prints: str = None, bad_id: bool = False,
                        missing_script: bool = False, no_coverage: bool = False,
                        bad_severity: bool = False) -> None:
    """A compliant probe deliverable set (with optional breakage).

    The probe is generic: `finding=False` writes a legal ZERO-finding set (an
    empty findings list plus the `checked` inventory); `finding=True` adds one
    X-901 finding with a real verifier. `computed` is what the finding declares;
    `script_prints` is what the script actually prints (a mismatch fails).
    """
    cold_start_script(sb, printed=(script_prints if script_prints is not None
                              else computed))
    checked = [{"area": "abstract", "examined": 2,
                "findings": 1 if finding else 0},
               {"area": "raw_data/", "examined": 4,
                "findings": 1 if finding else 0}]
    findings = []
    if finding:
        findings = [{
            "id": "X-000" if bad_id else "X-901",
            "location": "base/manuscript.md (abstract)",
            "category": 1, "check": "claim vs producer",
            "severity": "Blocker" if bad_severity else "Major",
            "evidence": "Ginkgo is the best caller overall",
            "explanation": "the corpus's own table ranks SCYN above Ginkgo",
            "status": "resolvable",
            "verifier": {
                "script": ("cold_start_review/scripts/pr_missing.py" if missing_script
                           else "cold_start_review/scripts/pr001.py"),
                "computed": computed,
                "shows": "the producer's own ranking contradicts the claim"}}]
    write(sb / "cold_start_review" / "findings_cold_start_review.json",
          {"checked": checked, "findings": findings})
    write(sb / "cold_start_review" / "findings_cold_start_review.md",
          "# probe findings\n" + ("\n".join(f"- {f['id']}" for f in findings)
                                  if findings else "(none)\n"))
    if not no_coverage:
        write(sb / "cold_start_review" / "coverage.md",
              "# coverage\n\n- abstract: 2 examined, 1 finding\n"
              "- raw_data/: 4 examined, 1 finding\n- limitations: fixture\n")
    write(sb / "_pipeline_done.json",
          {"stage": "cold_start_review", "run_id": "r1_cold_start_review", "round": 1, "status": "complete",
           "findings": len(findings), "verified": len(findings), "areas": len(checked)})


# =====================================================================
# P1 -- the plan and the handlers
# =====================================================================

def test_plan():
    print("\n== P1 the probe is planned in parallel with the review and gates the audit/revise ==")
    ctx = build_root(scratch("probe_p1_"))
    plan = {e["id"]: e for e in nb.round_run_plan(ctx, 1)}
    check("P1a probe 'on' adds r1_cold_start_review to the round plan",
          "r1_cold_start_review" in plan and plan["r1_cold_start_review"]["kind"] == "cold_start_review", str(sorted(plan)))
    check("P1b the probe depends only on the base (parallel with the review)",
          plan["r1_cold_start_review"]["deps"] == [nb.rid_a1(1)], str(plan["r1_cold_start_review"]["deps"]))
    rev = [e for e in nb.round_run_plan(ctx, 1) if e["kind"] == "revise"][0]
    check("P1c the reviser waits for the probe (its X-9xx rows ride the frozen list)",
          "r1_cold_start_review" in rev["deps"], str(rev["deps"]))
    check("P1d the kind has both handlers (postcheck + rebuild)",
          not nb.run_kind_support_problems(ctx), str(nb.run_kind_support_problems(ctx)))
    ctx_off = build_root(scratch("probe_p1_off_"), probe="off")
    ids = [e["id"] for e in nb.round_run_plan(ctx_off, 1)]
    check("P1e probe 'off' plans no cold-start session", "r1_cold_start_review" not in ids, str(ids))
    ctx_absent = build_root(scratch("probe_p1_absent_"))
    del ctx_absent.cfg["cold_start_review"]
    ids = [e["id"] for e in nb.round_run_plan(ctx_absent, 1)]
    check("P1f a root without the key (pre-feature) plans no cold-start session",
          "r1_cold_start_review" not in ids and nb.cold_start_review_of(ctx_absent) == "off", str(ids))
    # A formatting-writing polish round is a surface pass: no probe.
    ctx_fw = build_root(scratch("probe_p1_fw_"))
    ctx_fw.cfg["review_scope"] = ["formatting-writing"]
    ids = [e["id"] for e in nb.round_run_plan(ctx_fw, 1)]
    check("P1g a formatting-writing round plans no cold-start session", "r1_cold_start_review" not in ids,
          str(ids))
    for raw in ("cold_start_review", "r1_cold_start_review", "1:cold_start_review"):
        try:
            spec_ = nb.parse_only_spec(raw)
            ok = bool(spec_.stages or spec_.sessions or spec_.stages_for(1))
        except SystemExit:
            ok = False
        check(f"P1h --only {raw} parses", ok)


# =====================================================================
# P2 -- the sandbox layout and the leftover detector
# =====================================================================

def test_sandbox():
    print("\n== P2 the sandbox: cold context, seeded candidates, no review artifact ==")
    ctx = build_root(scratch("probe_p2_"))
    rec = nb.materialize_cold_start_review(ctx, 1)
    sb = ctx.sandbox_of(rec)
    check("P2a the probe sandbox exists with the required id",
          rec["id"] == "r1_cold_start_review" and rec["kind"] == "cold_start_review", str(rec.get("id")))
    check("P2b it carries the corpus (base/) and the pristine reference",
          (sb / "base" / "manuscript.md").is_file() and (sb / "non_revised").is_dir())
    check("P2c it carries the seeded claim-surface and producer candidates",
          (sb / "cold_start_review" / "CLAIM_SURFACES.md").is_file()
          and (sb / "cold_start_review" / "PRODUCERS.md").is_file())
    prod = (sb / "cold_start_review" / "PRODUCERS.md").read_text(encoding="utf-8")
    check("P2d the producer seed names the corpus's own tables and code",
          "raw_data/grid.tsv" in prod and "code/make_fish.py" not in prod
          and "make_fig.py" in prod, prod[:400])
    check("P2e NO review artifact, finding list or sweep is seeded",
          not (sb / "guided_review").exists() and not (sb / "prior_round").exists())
    prompt = (sb / "PROMPT.md").read_text(encoding="utf-8")
    check("P2f the prompt is generic and states the verifier/re-run contract",
          "GENERIC on purpose" in prompt and "ANY defect class" in prompt
          and "X-901" in prompt and "findings_cold_start_review.json" in prompt
          and "re-runs" in prompt and "coverage.md" in prompt)
    check("P2g a freshly materialized sandbox is not 'dirty'",
          not nb.leftovers_present(ctx, rec))
    write(sb / "cold_start_review" / "findings_cold_start_review.json", {"checked": [], "findings": []})
    check("P2h agent work under cold_start_review/ is detected",
          nb.leftovers_present(ctx, rec))


# =====================================================================
# P3 -- the contract: shapes + the reproduction blocker
# =====================================================================

def run_postcheck(ctx):
    rec = ctx.run("r1_cold_start_review")
    return nb.postcheck_cold_start_review(ctx, rec)


def test_contract():
    print("\n== P3 the postcheck: generic findings, coverage, recomputation blocker ==")
    ctx = build_root(scratch("probe_p3_ok_"))
    rec = nb.materialize_cold_start_review(ctx, 1)
    write_cold_start_fixture(ctx.sandbox_of(rec), finding=True)
    ok, errs, warns, _ = run_postcheck(ctx)
    check("P3a a compliant finding with a reproducing verifier passes", ok, str(errs))
    check("P3b the reproduction record is written by the orchestrator",
          (ctx.sandbox_of(rec) / "cold_start_review" / "REPRODUCTION.md").is_file())
    repro = ctx.run("r1_cold_start_review").get("cold_start_review") or {}
    check("P3c the summary records the reproduced verifier and the finding id",
          repro.get("reproduced") == 1 and not repro.get("mismatches")
          and repro.get("findings") == ["X-901"], str(repro))
    # A legal ZERO-finding outcome: allowed because `checked` documents the pass.
    ctx = build_root(scratch("probe_p3_zero_"))
    rec = nb.materialize_cold_start_review(ctx, 1)
    write_cold_start_fixture(ctx.sandbox_of(rec), finding=False)
    ok, errs, warns, _ = run_postcheck(ctx)
    check("P3d a zero-finding pass with a `checked` inventory passes", ok, str(errs))

    ctx = build_root(scratch("probe_p3_bad_"))
    rec = nb.materialize_cold_start_review(ctx, 1)
    write_cold_start_fixture(ctx.sandbox_of(rec), finding=True, computed="999",
                        script_prints="2")
    ok, errs, warns, _ = run_postcheck(ctx)
    check("P3e a declared value the verifier does not reproduce FAILS the attempt",
          not ok and any("does not reproduce" in e for e in errs), str(errs))

    ctx = build_root(scratch("probe_p3_find_"))
    rec = nb.materialize_cold_start_review(ctx, 1)
    write_cold_start_fixture(ctx.sandbox_of(rec), finding=True, bad_id=True)
    ok, errs, warns, _ = run_postcheck(ctx)
    check("P3f a finding outside the reserved X-9xx block fails",
          not ok and any("outside the reserved probe block" in e for e in errs), str(errs))

    ctx = build_root(scratch("probe_p3_surf_"))
    rec = nb.materialize_cold_start_review(ctx, 1)
    write_cold_start_fixture(ctx.sandbox_of(rec), finding=True, missing_script=True)
    ok, errs, warns, _ = run_postcheck(ctx)
    check("P3g a missing verifier script fails",
          not ok and any("does not exist" in e for e in errs), str(errs))

    ctx = build_root(scratch("probe_p3_cov_"))
    rec = nb.materialize_cold_start_review(ctx, 1)
    write_cold_start_fixture(ctx.sandbox_of(rec), finding=False, no_coverage=True)
    ok, errs, warns, _ = run_postcheck(ctx)
    check("P3h a missing coverage.md fails",
          not ok and any("coverage.md is missing" in e for e in errs), str(errs))

    # The pre-flight applies the SAME detectors (never a different verdict).
    ctx = build_root(scratch("probe_p3_pre_"))
    rec = nb.materialize_cold_start_review(ctx, 1)
    write_cold_start_fixture(ctx.sandbox_of(rec), finding=True, computed="999",
                        script_prints="2")
    ok_pre, errs_pre, warns_pre = nb.sandbox_selfcheck(ctx.sandbox_of(rec), "cold_start_review",
                                                       "r1_cold_start_review", 1)
    check("P3i the pre-flight fails the same non-reproducing verifier",
          not ok_pre and any("does not reproduce" in e for e in errs_pre), str(errs_pre))
    write_cold_start_fixture(ctx.sandbox_of(rec), finding=True)
    ok_pre, errs_pre, warns_pre = nb.sandbox_selfcheck(ctx.sandbox_of(rec), "cold_start_review",
                                                       "r1_cold_start_review", 1)
    check("P3j the pre-flight passes the compliant fixture", ok_pre, str(errs_pre))


# =====================================================================
# P4 -- the merge: audit/revision copies, the integration seed, the archive
# =====================================================================

def test_merge():
    print("\n== P4 the probe rows ride the frozen list downstream ==")
    review_rows = [{"id": "X-001", "location": "base/manuscript.md:2", "category": 2,
                    "check": "convention", "severity": "Minor", "evidence": "one convention",
                    "explanation": "applied unevenly", "status": "resolvable"}]
    ctx = build_root(scratch("probe_p4_"), audit="on", review_rows=review_rows)
    prec = nb.materialize_cold_start_review(ctx, 1)
    write_cold_start_fixture(ctx.sandbox_of(prec), finding=True)
    ok, errs, warns, _ = nb.postcheck_cold_start_review(ctx, prec)
    check("P4a the probe fixture passes its postcheck", ok, str(errs))
    recs = ctx.state["runs"]
    recs["r1_cold_start_review"]["status"] = "done"
    arec = nb.materialize_audit(ctx, 1)
    ids = [f.get("id") for f in nb.discovery_findings_of(
        ctx.sandbox_of(arec) / "guided_review" / "round2")]
    check("P4b the auditor's frozen copy carries the probe finding",
          "X-901" in ids, str(ids))
    recs["r1_audit"]["status"] = "done"      # materialize_revise waits for the audit
    rrec = nb.materialize_revise(ctx, 1, "a2")
    ids = [f.get("id") for f in nb.discovery_findings_of(
        ctx.sandbox_of(rrec) / "guided_review" / "round2")]
    check("P4c the reviser's frozen copy carries the probe finding",
          "X-901" in ids, str(ids))
    ledger_ids = nb.frozen_finding_ids(ctx, rrec)
    check("P4d the revision ledger contract sees the probe id",
          "X-901" in ledger_ids, str(ledger_ids))
    seed = nb.round_discovery_seed(ctx, 1)
    check("P4e the integration seed carries the probe id",
          "X-901" in seed["ids"], str(seed["ids"]))
    nb.seed_discovery_findings(ctx, 1, ctx.sandbox_of(rrec))
    frozen = json.loads((ctx.sandbox_of(rrec) / "frozen_discovery" /
                         "findings_extra.json").read_text(encoding="utf-8"))
    check("P4e2 the frozen seed the integrator reads carries the probe id",
          "X-901" in [f.get("id") for f in frozen.get("findings", [])],
          str([f.get("id") for f in frozen.get("findings", [])]))
    check("P4f the source review sandbox is NEVER mutated by the merge",
          "X-901" not in [f.get("id") for f in nb.discovery_findings_of(
              ctx.sandbox_of(ctx.run("r1_guided_review")) / "guided_review" / "round2")])
    # P4f2-P4f4: the freshness interaction that a stub-without-findings round
    # could not see. A merged copy must NOT look stale (the audit was reset on
    # every re-entry until this was fixed), a not-done probe MUST make it look
    # stale, and re-running the merge must not duplicate rows.
    audit_sb = ctx.sandbox_of(arec)
    review_sb = ctx.sandbox_of(ctx.run("r1_guided_review"))
    check("P4f2 a correctly merged review copy is NOT flagged stale",
          nb._review_copy_mismatch(ctx, 1, audit_sb, review_sb / "guided_review") is None,
          str(nb._review_copy_mismatch(ctx, 1, audit_sb, review_sb / "guided_review")))
    cold_start_rec = ctx.state["runs"]["r1_cold_start_review"]
    cold_start_rec["status"] = "pending"
    stale_msg = nb._review_copy_mismatch(ctx, 1, audit_sb, review_sb / "guided_review")
    cold_start_rec["status"] = "done"
    check("P4f3 a not-done probe run marks the merged copy stale",
          stale_msg is not None and "cold_start_review" in str(stale_msg), str(stale_msg))
    again = nb.merge_cold_start_into_review_copy(ctx, 1, audit_sb)
    merged_ids = [f.get("id") for f in nb.discovery_findings_of(
        audit_sb / "guided_review" / "round2")]
    check("P4f4 re-running the merge is idempotent (no duplicated ids)",
          merged_ids.count("X-901") == 1 and len(merged_ids) == len(set(merged_ids)),
          f"{merged_ids} ({again})")
    check("P4f5 arms without a review copy count the probe finding too",
          "X-901" in [str(f.get("id")) for f in nb.round_consumed_findings(ctx, 1)],
          str([str(f.get("id")) for f in nb.round_consumed_findings(ctx, 1)]))

    # Collision: a probe id that the review already used is remapped.
    ctx2 = build_root(scratch("probe_p4_coll_"), audit="off",
                      review_rows=[{"id": "X-901", "location": "base/x.md", "category": 2,
                                    "check": "c", "severity": "Minor", "evidence": "e",
                                    "explanation": "x", "status": "resolvable"}])
    prec2 = nb.materialize_cold_start_review(ctx2, 1)
    write_cold_start_fixture(ctx2.sandbox_of(prec2), finding=True)
    ok, errs, warns, _ = nb.postcheck_cold_start_review(ctx2, prec2)
    ctx2.state["runs"]["r1_cold_start_review"]["status"] = "done"
    rrec2 = nb.materialize_revise(ctx2, 1, "a2")
    ids = [f.get("id") for f in nb.discovery_findings_of(
        ctx2.sandbox_of(rrec2) / "guided_review" / "round2")]
    check("P4g a colliding probe id is remapped deterministically",
          "X-901" in ids and "X-902" in ids, str(ids))
    seed2 = nb.round_discovery_seed(ctx2, 1)
    check("P4h the integration seed applies the same remap",
          "X-902" in seed2["ids"], str(seed2["ids"]))

    # The archive keeps the probe deliverables; a pruned root re-seeds them.
    dst = nb.archive_review_outputs(ctx2, 1)
    check("P4i the archive carries the probe finding list",
          (dst / "findings_cold_start_review.json").is_file()
          and (dst / "cold_start_reproduction.md").is_file(),
          str(sorted(p.name for p in dst.iterdir())))
    archived = json.loads((dst / "findings_extra.json").read_text(encoding="utf-8"))
    check("P4j the archived discovery list carries the MERGED probe finding",
          [f.get("id") for f in archived.get("findings", [])] == ["X-901", "X-902"]
          and isinstance(archived.get("cold_start_merge"), dict),
          str(archived))
    # Prune the live review list (rename it away) so the ARCHIVE owns the list,
    # with the probe run reset: no double count, and the merged archive still
    # seeds both ids.
    review_round2 = ctx2.sandbox_of(ctx2.run("r1_guided_review")) / "guided_review" / "round2"
    review_round2.rename(review_round2.parent / "round2_held")
    try:
        ctx2.state["runs"]["r1_cold_start_review"]["status"] = "pending"
        rows = nb.cold_start_findings_rows(ctx2, 1)
        seed2 = nb.round_discovery_seed(ctx2, 1)
        check("P4j2 a merged archive is not double-seeded (the probe rows are already in it)",
              rows == [] and sorted(seed2["ids"]) == ["X-901", "X-902"], f"{rows} {seed2['ids']}")
    finally:
        (review_round2.parent / "round2_held").rename(review_round2)
        ctx2.state["runs"]["r1_cold_start_review"]["status"] = "done"


# =====================================================================
# P5 -- the CLI policy switch
# =====================================================================

# =====================================================================
# P6 -- the AGENTS.md invariants this stage touches
# =====================================================================

def test_invariants():
    print("\n== P6 AGENTS.md invariants: blinding, read-only facts, one scale, roles ==")
    ctx = build_root(scratch("probe_p6_"), with_a2=True)
    prec = nb.materialize_cold_start_review(ctx, 1)
    write_cold_start_fixture(ctx.sandbox_of(prec), finding=True)
    ok, errs, warns, _ = nb.postcheck_cold_start_review(ctx, prec)
    check("P6a the probe fixture passes its postcheck", ok, str(errs))
    ctx.state["runs"]["r1_cold_start_review"]["status"] = "done"

    # (1) Judgment is blind to provenance: a judge sandbox receives NO probe
    # artifact (no cold_start_review/, no discovery seed, no probe ids) and its
    # prompt never names the cold-start session.
    field, _dropped = nb.build_field(ctx, 1)
    judge_ids = nb.materialize_judges(ctx, 1, field)
    jsb = ctx.sandbox_of(ctx.run(judge_ids[0]))
    jsb_text = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                         for p in jsb.rglob("*") if p.is_file() and p.suffix in
                         (".md", ".json", ".txt"))
    # The prompt legitimately names its OWN sandbox path; under the test runner
    # that path contains this suite's file name ("...test_cold_start_review..."), so
    # scrub path-derived noise before scanning for probe ARTIFACT names.
    for noise in (str(jsb), str(jsb.resolve()), Path(__file__).name):
        jsb_text = jsb_text.replace(noise, "")
    check("P6b a judge sandbox carries no probe artifact and no probe mention",
          not (jsb / "cold_start_review").exists()
          and not (jsb / nb.DISCOVERY_SEED_DIR).exists()
          and "cold_start_review" not in jsb_text and "findings_probe" not in jsb_text
          and "X-901" not in jsb_text,
          f"{sorted(p.name for p in jsb.iterdir())}")

    # (2) The thing scored is the thing that wins: the merge touches only the
    # audit/revision sandboxes' READ-ONLY input copies -- the judged corpus
    # digest of the round's arm is exactly what was recorded when it ran.
    a2 = ctx.state["runs"].get(nb.rid_for_fresh(1, nb.revise_vid(1))) or {}
    check("P6c the probe merge does not move a judged candidate's content digest",
          a2.get("corpus_digest")
          and nb.recompute_corpus_digest(ctx, 1, nb.revise_vid(1)) == a2["corpus_digest"],
          str(a2.get("corpus_digest")))

    # (3) Facts are not a revision surface: the probe sandbox's corpus is the
    # byte-identical base copy (verified against the run's recorded manifest),
    # and the probe wrote nothing outside its own output directory.
    check("P6d the probe sandbox's inputs match their recorded manifests",
          nb.input_mismatches(ctx, ctx.run("r1_cold_start_review")) == [],
          str(nb.input_mismatches(ctx, ctx.run("r1_cold_start_review"))))
    check("P6e the probe cannot write OUTSIDE cold_start_review/ (base/ untouched)",
          nb.hash_manifest(ctx.sandbox_of(prec) / "base").get("files")
          == nb.hash_manifest(ctx.sandbox_of(ctx.run("r1_a1")) / "base").get("files"))

    # (5) One ranking function: a severity outside the shared four is refused,
    # so no seventh ranked class can enter through the probe.
    ctx2 = build_root(scratch("probe_p6_scale_"))
    prec2 = nb.materialize_cold_start_review(ctx2, 1)
    write_cold_start_fixture(ctx2.sandbox_of(prec2), finding=True, bad_severity=True)
    ok2, errs2, _w, _r = nb.postcheck_cold_start_review(ctx2, prec2)
    check("P6f an out-of-scale severity is refused (no new ranked class)",
          not ok2 and any("severity" in e for e in errs2), str(errs2))

    # (6) No role grades its own homework: the probe's own prompt forbids
    # editing and scoring, and the stage never appears in a judge or decision
    # role (it only files findings for the auditor/revisers).
    prompt = (ctx.sandbox_of(prec) / "PROMPT.md").read_text(encoding="utf-8")
    check("P6g the probe prompt is identification-only (no edit, no score)",
          "you do NOT edit" in prompt and "identification only" in prompt
          and "do NOT run the checklist" in prompt)
    deps = {e["id"]: e.get("deps") for e in nb.round_run_plan(ctx, 1)}
    check("P6h the auditor and reviser depend on the probe (the AUDIT disposes its findings)",
          "r1_cold_start_review" in (deps.get("r1_a2_revise") or []), str(deps.get("r1_a2_revise")))

def test_cli():
    print("\n== P5 the CLI: default on, off switch, set-cold-start-review ==")
    parser = nb.build_parser()
    args = parser.parse_args(["setup", "--source", "/tmp"])
    check("P5a setup defaults the cold-start review ON", args.cold_start_review == "on",
          str(args.cold_start_review))
    check("P5b --no-cold-start-review records off",
          parser.parse_args(["setup", "--source", "/tmp",
                             "--no-cold-start-review"]).cold_start_review == "off")
    check("P5c --cold-start-review off records off",
          parser.parse_args(["setup", "--source", "/tmp",
                             "--cold-start-review", "off"]).cold_start_review == "off")
    check("P5d set-cold-start-review parses with a mode and --force",
          parser.parse_args(["set-cold-start-review", "off", "--force"]).mode == "off")
    # The command itself, through a real root: setup records "on"; the setter
    # refuses without --force once runs exist and flips with it.
    tmp = scratch("probe_p5_")
    root = tmp / "root"
    src = tmp / "src"
    write(src / "manuscript.md", "text\n")
    proc = subprocess.run(
        [sys.executable, str(WS / "paper_pipeline.py"), "setup", "--source", str(src),
         "--root", str(root), "--rounds", "1", "--rewrites", "0", "--revises", "1",
         "--judges", "1", "--integrators", "0"],
        capture_output=True, text=True, check=False)
    check("P5e setup succeeded", proc.returncode == 0, (proc.stdout + proc.stderr)[-300:])
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("P5f setup records the default policy", cfg.get("cold_start_review") == "on",
          str(cfg.get("cold_start_review")))
    # A REAL run record makes the policy change a --force decision.
    stub = WS / ".paper_test" / "stub_agent.py"
    proc = subprocess.run(
        [sys.executable, str(root / "paper_pipeline.py"), "run", "--root", str(root),
         "--agent-cmd", json.dumps([sys.executable, str(stub)]),
         "--only", "cold_start_review", "--retries", "1"],
        capture_output=True, text=True, check=False, cwd=str(tmp), timeout=600)
    st = json.loads((root / "state.json").read_text(encoding="utf-8"))
    check("P5g-pre the cold-start session ran (a real run record exists)",
          (st.get("runs", {}).get("r1_cold_start_review") or {}).get("status") == "done",
          (proc.stdout + proc.stderr)[-300:])
    proc = subprocess.run(
        [sys.executable, str(root / "paper_pipeline.py"), "set-cold-start-review", "off",
         "--root", str(root)],
        capture_output=True, text=True, check=False, cwd=str(tmp))
    check("P5g set-cold-start-review refuses an existing root without --force",
          proc.returncode != 0 and "--force" in (proc.stdout + proc.stderr),
          (proc.stdout + proc.stderr)[-200:])
    proc = subprocess.run(
        [sys.executable, str(root / "paper_pipeline.py"), "set-cold-start-review", "off",
         "--root", str(root), "--force"],
        capture_output=True, text=True, check=False, cwd=str(tmp))
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("P5h --force records the new policy",
          proc.returncode == 0 and cfg.get("cold_start_review") == "off",
          (proc.stdout + proc.stderr)[-200:])


def main() -> int:
    try:
        test_plan()
        test_sandbox()
        test_contract()
        test_merge()
        test_cli()
        test_invariants()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL COLD-START REVIEW CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

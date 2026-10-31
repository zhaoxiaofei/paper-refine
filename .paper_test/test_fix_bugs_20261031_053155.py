#!/usr/bin/env python3
"""Regression checks for the 2026-10-31 05:31 fix-bugs wave (C01..C41, R01..R03).

Run:  python3 .paper_test/test_fix_bugs_20261031_053155.py

Every Cxx is a candidate the verify-findings stage kept as a TRUE_POSITIVE.
Each check pins the smallest observed defect and fails on the pre-fix tree.
R01-R03 are the verify-fixes review findings repaired by the repair stage.
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
sys.path.insert(0, str(WS / ".paper_test"))
import test_cold_start_review_2026_1012 as cc  # noqa: E402

nb = cc.nb
TMPDIRS = []
FAILS = []


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def cli(*argv, timeout=300):
    return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *argv],
                          capture_output=True, text=True, timeout=timeout)


def make_source(tmp: Path) -> Path:
    src = tmp / "src"
    src.mkdir()
    (src / "manuscript.md").write_text("Abstract\n\nText.\n\nResults\n\nMore.\n",
                                      encoding="utf-8")
    return src


def setup_root(tmp: Path, *extra) -> Path:
    src = make_source(tmp)
    root = tmp / "root"
    p = cli("setup", "--source", str(src), "--root", str(root), "--venue", "generic",
            "--rounds", "1", "--rewrites", "0", "--revises", "1", *extra)
    if p.returncode != 0:
        print(p.stdout + p.stderr)
    return root


# ---------------------------------------------------------------------------
# C01-C04 -- the no-guided-review producer path (audit/revise/archive/consumed)
# ---------------------------------------------------------------------------
def no_guided_ctx():
    ctx = cc.build_root(scratch("fb0531_nog_"), probe="on", audit="off", review_rows=None)
    ctx.cfg["guided_review"] = "off"
    ctx.state["config"] = ctx.cfg
    prec = nb.materialize_cold_start_review(ctx, 1)
    cc.write_cold_start_fixture(ctx.sandbox_of(prec), finding=True)
    ok, errs, _warns, _res = nb.postcheck_cold_start_review(ctx, prec)
    prec["status"] = "done"
    if not ok:
        print("probe fixture errors:", errs)
    return ctx, prec


def test_c01_c04():
    print("\n== C01-C04: --no-guided-review downstream producer ==")
    ctx, prec = no_guided_ctx()
    audit_rec = nb.materialize_audit(ctx, 1)
    audit_rec["status"] = "done"
    revise_rec = nb.materialize_revise(ctx, 1, nb.revise_vid(1))
    revise_rec["status"] = "done"
    reset = nb.revalidate_round_inputs(ctx, 1)
    check("C01 a completed audit/revise is not reset on re-entry",
          reset == [] and ctx.run(nb.rid_audit(1))["status"] == "done"
          and revise_rec["status"] == "done", str(reset))
    frozen = json.loads((ctx.sandbox_of(audit_rec) / "guided_review" /
                         "findings.json").read_text(encoding="utf-8"))
    check("C02 the synthesized coverage has one row per required audit check",
          [r["check"] for r in frozen["coverage"]] == list(nb.AUDIT_COVERAGE_CHECKS)
          and nb.audit_coverage_problems({"coverage": frozen["coverage"]}) == [],
          str(len(frozen["coverage"])))
    check("C04 the frozen list carries the cold-start finding",
          [str(f.get("id")) for f in nb.round_consumed_findings(ctx, 1)] == ["X-901"],
          str(nb.round_consumed_findings(ctx, 1)))
    dst = nb.archive_review_outputs(ctx, 1)
    check("C03 the no-guided archive carries the synthesized frozen list",
          (dst / "findings.json").is_file() and (dst / "findings_extra.json").is_file()
          and (dst / "findings_cold_start_review.json").is_file(),
          str(sorted(p.name for p in dst.iterdir())))
    rows = nb.write_round_review_findings(ctx, 1)
    check("C03b the archived findings feed the review-findings CSV",
          "X-901" in rows.read_text(encoding="utf-8"))
    # A probe RETRY that changes the list must still reach the synthesized
    # consumers (the comparison is against what the probe would synthesize now).
    probe_doc = ctx.sandbox_of(prec) / nb.COLD_START_FINDINGS_REL
    doc = json.loads(probe_doc.read_text(encoding="utf-8"))
    doc["findings"].append({"id": "X-902", "location": "base/manuscript.md",
                            "category": 0, "check": "M1", "severity": "Minor",
                            "evidence": "e", "explanation": "x", "status": "resolvable"})
    probe_doc.write_text(json.dumps(doc), encoding="utf-8")
    reset2 = nb.revalidate_round_inputs(ctx, 1)
    check("C01b a changed probe list still resets the synthesized consumers",
          nb.rid_audit(1) in reset2 and revise_rec["id"] in reset2, str(reset2))



def test_c03_scoped_archive():
    tmp = scratch("fb0531_scoped_arch_")
    csb = tmp / "r1_concerns"
    (csb / "concerns").mkdir(parents=True)
    (csb / "concerns" / "ledger.json").write_text('{"concerns": []}', encoding="utf-8")

    class C:
        cfg = {"guided_review": "on", "revision_mode": "major"}
        reports_dir = tmp / "reports"

        def run(self, rid):
            return {"sandbox": str(csb), "status": "done"} if rid == "r1_concerns" else None

        def sandbox_of(self, rec):
            return Path(rec["sandbox"])

    C.reports_dir.mkdir()
    saved = nb.journal_is_scoped
    nb.journal_is_scoped = lambda ctx: True
    try:
        dst = nb.archive_review_outputs(C(), 1)
    finally:
        nb.journal_is_scoped = saved
    check("C03c a concern-scoped round archives the concerns ledger",
          (dst / "ledger.json").is_file(), str(list(dst.iterdir())))


# ---------------------------------------------------------------------------
# C05/C06/C09 -- the plan / CLI guards
# ---------------------------------------------------------------------------
def test_c05_c06_c09():
    print("\n== C05/C06/C09: setup and the round plan ==")
    tmp = scratch("fb0531_cli_")
    root = setup_root(tmp, "--no-guided-review")
    saved = (root / "pipeline_config.json").read_text(encoding="utf-8")
    p = cli("set-cold-start-review", "off", "--root", str(root), "--force")
    check("C05 set-cold-start-review off is refused on a no-guided root",
          p.returncode == 2 and "only finding source" in (p.stdout + p.stderr)
          and (root / "pipeline_config.json").read_text(encoding="utf-8") == saved,
          (p.stdout + p.stderr)[-200:])

    tmp2 = scratch("fb0531_cli2_")
    src = make_source(tmp2)
    p = cli("setup", "--source", str(src), "--root", str(tmp2 / "r"), "--venue", "generic",
            "--rounds", "1", "--rewrites", "2", "--revises", "0", "--no-guided-review")
    check("C06 --no-guided-review with --revises 0 is refused",
          p.returncode == 2 and "no review session is planned" in (p.stdout + p.stderr),
          (p.stdout + p.stderr)[-200:])

    root2 = setup_root(scratch("fb0531_plan_"), "--review-split", "phases",
                       "--review-scope", "formatting-writing")
    ctx = nb.Ctx(root2)
    ctx.load()
    ids = [e["id"] for e in nb.round_run_plan(ctx, 1)]
    check("C09 a non-full review scope plans no duplicate session B",
          "r1_guided_review_b" not in ids, str(ids))
    root3 = setup_root(scratch("fb0531_plan_full_"), "--review-split", "phases")
    ctx3 = nb.Ctx(root3)
    ctx3.load()
    ids3 = [e["id"] for e in nb.round_run_plan(ctx3, 1)]
    check("C09b a full-scope split still plans both review sessions",
          "r1_guided_review_b" in ids3, str(ids3))


# ---------------------------------------------------------------------------
# C07 -- the decision report / certification names the gap
# ---------------------------------------------------------------------------
def test_c07():
    print("\n== C07: the decision report names the no-guided gap ==")
    root = setup_root(scratch("fb0531_dec_"), "--no-guided-review")
    ctx = nb.Ctx(root)
    ctx.load()
    text = nb.build_decision_report(
        ctx, [], {"pristine_ok": True, "pristine_detail": "ok", "pinned_errors": [],
                  "evidence_not_verifiable": []}, [], {"round": 1, "pin": {}, "stored": {}})
    check("C07 the no-guided report states the NAMED GAP and the real producer",
          "NAMED GAP" in text and "cold_start_review" in text
          and "review contract was satisfied" not in text)
    check("C07b the certification label names the gap",
          "named gap" in nb.certification_label(
              {"certified": True, "guided_review_gap": "x"}).lower())


# ---------------------------------------------------------------------------
# C11/C12 -- session ids and legacy tokens
# ---------------------------------------------------------------------------
def test_c11_c12():
    print("\n== C11/C12: session ids ==")
    check("C11 the split-review entry names the canonical guided_review_b",
          nb.session_id_of_entry({"id": "r1_guided_review_b"}) == "guided_review_b")
    check("C12 the legacy reviewer/review_b tokens still resolve",
          nb.parse_only_spec("reviewer").session_tokens_for(1) == ["guided_review"]
          and nb.parse_only_spec("review_b").session_tokens_for(1) == ["guided_review_b"])


# ---------------------------------------------------------------------------
# C13-C20/C42-C46/C48/C51 -- documentation truth
# ---------------------------------------------------------------------------
def test_docs():
    print("\n== C13-C20/C42-C46/C48/C51: documentation ==")
    loader = (WS / "paper_pipeline.py").read_text(encoding="utf-8")
    check("C13 the loader docstring uses the guided_review areas/ids",
          "writes\n                      review/*" not in loader
          and "runs/r<R>_review/" not in loader
          and "guided_review/findings.json" in loader)
    check("C14 the quick-start uses r2_guided_review and no removed 'none' mode",
          "retry  --root ./paper_rounds --run r2_guided_review" in loader
          and "# none | transfer" not in loader)
    parts = sorted((WS / "paper_pipeline_parts").glob("p*.py"))
    heads = []
    for p in parts:
        head = "\n".join(p.read_text(encoding="utf-8").splitlines()[:2])
        heads.append((p.name, head))
    check("C15 all 20 part headers carry the real bundle count",
          len(parts) == 20 and all(f"/20 of the pipeline" in h for _n, h in heads),
          str([n for n, h in heads if "/20 of the pipeline" not in h]))
    parts_readme = (WS / "paper_pipeline_parts/README.md").read_text(encoding="utf-8")
    check("C16 the parts README describes the guided-review switch, not TARGETED-REVIEW",
          "TARGETED-REVIEW" not in parts_readme and "--no-guided-review" in parts_readme)
    cli_src = (WS / "paper_pipeline_parts/p17_cli.py").read_text(encoding="utf-8")
    check("C17 the CLI help no longer advertises the probe/old review ids",
          "`r<r>_probe`" not in cli_src and "--only reviewer" not in cli_src)
    readme = (WS / "README.md").read_text(encoding="utf-8")
    check("C18 README names r<r>_cold_start_review",
          "r<r>_probe" not in readme and "r<r>_cold_start_review" in readme)
    prompts = (WS / "paper_pipeline_parts/p03_prompts.py").read_text(encoding="utf-8")
    check("C19 the rename did not corrupt 'targeted' prose",
          "Guided revisions:" not in prompts and "Guided edits only" not in prompts
          and "ONE guided edit" not in prompts)
    p07 = (WS / "paper_pipeline_parts/p07_stage_quality_journal.py").read_text(encoding="utf-8")
    check("C10 the D0-D5 warning is gated on a full-scope, discovery-owing pass",
          'round_review_scope(ctx, int(rec.get("round") or 1)) == "full"' in p07
          and "and not _split_a" in p07)
    decide = (WS / "paper_pipeline_parts/p12_conflicts_decide.py").read_text(encoding="utf-8")
    check("C20 the fixed review-provenance paragraph names M1-M36 / J1-J5",
          'every check id M1-M36 and ' in decide and 'J1-J5 carries a ' in decide)
    ptest_readme = (WS / ".paper_test/README.md").read_text(encoding="utf-8")
    check("C42 the test README says 1:review selects BOTH review runs",
          "selects BOTH review runs" in ptest_readme)
    check("C43 the test README uses r<r>_guided_review and cold-start vocabulary",
          "plans no `r<r>_review`" not in ptest_readme
          and "plans no `r<r>_guided_review`" in ptest_readme)
    cold = (WS / ".paper_test/test_cold_start_review_2026_1012.py").read_text(encoding="utf-8")
    prof = (WS / ".paper_test/test_execution_profile.py").read_text(encoding="utf-8")
    check("C44 test docstrings name the current run id",
          "r<r>_probe" not in cold and "r1_review" not in prof)
    check("C45 comments no longer call r1_review a run id",
          "r1_review._agent.log" not in (WS / "paper_pipeline_parts/p05_state_corpus.py").read_text(encoding="utf-8")
          and "r<r>_review_b" not in (WS / "paper_pipeline_parts/p07_stage_quality_journal.py").read_text(encoding="utf-8"))
    check("C46 the repository-layout table names env/ and the test-env scripts",
          "| `env/` |" in readme and "create-test-env.sh" in readme
          and "export-test-env.sh" in readme)
    agents = (WS / "AGENTS.md").read_text(encoding="utf-8")
    check("C48 both refusal lists name the review-feedback revision modes",
          "transfer`, `resubmit`, `llm" in readme and "transfer`, `resubmit`, `llm" in agents)
    check("C51 the cold-start table states the N=0 rule",
          "--revises 0` plans no review" in readme)


# ---------------------------------------------------------------------------
# C21/C22/C23/C26 -- root policies
# ---------------------------------------------------------------------------
def test_policies():
    print("\n== C21/C22/C23/C26: recorded plan and policy keys ==")
    tmp = scratch("fb0531_plan_restore_")
    src = make_source(tmp)
    root = tmp / "root"
    p = cli("setup", "--source", str(src), "--root", str(root), "--venue", "generic",
            "--rounds", "3", "--rewrites", "2,1,1", "--revises", "1,2,1",
            "--integrators", "0xFFFFFFFF")
    check("C21 setup for the restore test succeeded", p.returncode == 0,
          (p.stdout + p.stderr)[-200:])
    cli("set-revision-mode", "major", "--root", str(root))
    cli("set-revision-mode", "continue", "--root", str(root))
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("C21 leaving a scoped mode restores the custom plan",
          cfg["rounds"] == 3 and cfg["rewrites"] == [2, 1, 1]
          and cfg["revises"] == [1, 2, 1]
          and cfg["integrators"] == [0xFFFFFFFF] * 3,
          str({k: cfg[k] for k in ("rounds", "rewrites", "revises", "integrators")}))

    # A legacy root without the cold-start key must get it back ABSENT.
    tmp2 = scratch("fb0531_legacy_")
    root2 = setup_root(tmp2)
    cfg_path = root2 / "pipeline_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.pop("cold_start_review", None)
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    cli("set-revision-mode", "major", "--root", str(root2))
    cli("set-revision-mode", "continue", "--root", str(root2))
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    check("C23 a legacy root keeps the cold-start key absent after a round-trip",
          "cold_start_review" not in cfg, str(cfg.get("cold_start_review")))

    # A removed policy key is refused, never silently defaulted.
    cfg["probe_review"] = "off"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    p = cli("status", "--root", str(root2))
    check("C22 a removed policy key is refused with its replacement named",
          p.returncode != 0 and "cold_start_review" in (p.stdout + p.stderr),
          (p.stdout + p.stderr)[-160:])

    tmp3 = scratch("fb0531_stop_")
    src3 = make_source(tmp3)
    p = cli("setup", "--source", str(src3), "--root", str(tmp3 / "r"), "--venue", "generic",
            "--rounds", "1", "--rewrites", "0", "--revises", "1",
            "--stop-after-no-progress", "-1")
    check("C26 a negative --stop-after-no-progress is refused",
          p.returncode == 2 and "must be >= 0" in (p.stdout + p.stderr),
          (p.stdout + p.stderr)[-160:])


# ---------------------------------------------------------------------------
# C29/C30/C31/C33/C35/C38/C73 -- postcheck and helper contracts
# ---------------------------------------------------------------------------
def test_helpers():
    print("\n== C29-C38/C73: postcheck helpers ==")
    check("C29 a bare clean/unable is not a coverage disposition",
          not nb._coverage_disposition_ok("clean")
          and not nb._coverage_disposition_ok("unable")
          and nb._coverage_disposition_ok("clean -- basis: artifact.md")
          and nb._coverage_disposition_ok("unable -- no renderer"))
    full = [{"check": c, "disposition": "clean -- basis: fixture"}
            for c in nb.AUDIT_COVERAGE_CHECKS]
    filler = [{"check": c, "disposition": "x"} for c in nb.AUDIT_COVERAGE_CHECKS]
    check("C30 audit coverage rejects a one-word filler disposition",
          nb.audit_coverage_problems({"coverage": full}) == []
          and any("not a real disposition" in p
                  for p in nb.audit_coverage_problems({"coverage": filler})))

    tmp = scratch("fb0531_prior_")
    sb = tmp / "sb"
    outside = tmp / "outside.md"
    outside.write_text("## M37 -- outside\n", encoding="utf-8")
    p = sb / "prior_round" / "new_sweeps.md"
    p.parent.mkdir(parents=True)
    p.symlink_to(outside)
    check("C73 an unreadable prior sweep file is UNKNOWN, not 'no proposals'",
          nb.prior_proposal_ids(sb) is None)
    # A symlinked known_index must not be read through (the outside file names
    # M1/J5; reading it would wrongly satisfy the D0 range check).
    r2 = sb / "guided_review" / "round2"
    r2.mkdir(parents=True)
    (r2 / "known_index.md").symlink_to(outside)
    errs, _warns = nb.discovery_contract_problems(sb)
    check("C31 a symlinked agent artifact is not read through",
          any("known_index.md never names both ends" in e for e in errs), str(errs)[:200])

    tmp2 = scratch("fb0531_profile_")
    psb = tmp2 / "sb"
    psb.mkdir()
    outdir = tmp2 / "outside"
    outdir.mkdir()
    (psb / "INSTRUCTIONS").symlink_to(outdir, target_is_directory=True)
    try:
        nb.page_stage_prompt(psb, "BODY", [("Rule", "BODY")], "audit", "medium")
        refused = False
    except SystemExit:
        refused = True
    check("C32 paging refuses an agent-planted INSTRUCTIONS symlink",
          refused and list(outdir.iterdir()) == [])

    tmp3 = scratch("fb0531_ro_")
    src = tmp3 / "src" / "raw_data"
    src.mkdir(parents=True)
    (src / "a.tsv").write_text("x", encoding="utf-8")
    pristine = tmp3 / "pristine"
    shutil.copytree(tmp3 / "src", pristine)

    class C:
        pass

    c = C()
    c.pristine = pristine
    pkg = tmp3 / "pkg"
    shutil.copytree(pristine, pkg)
    (pkg / "raw_data" / "added.txt").write_text("x", encoding="utf-8")
    warns = []
    orig = Path.unlink

    def refuse(self, *a, **k):
        raise PermissionError("locked")

    Path.unlink = refuse
    try:
        nb.enforce_readonly_raw_data(c, pkg, warns)
    finally:
        Path.unlink = orig
    check("C33 a failed cleanup of an added read-only file is reported",
          any("could not remove added file" in w for w in warns), str(warns))

    src12 = (WS / "paper_pipeline_parts/p12_conflicts_decide.py").read_text(encoding="utf-8")
    check("C35 agent-written report/audit JSON is read without revive",
          "report = read_json(cand, revive=False, lenient=True)" in src12
          and 'audit.json", revive=False, lenient=True' in src12)

    tmp4 = scratch("fb0531_split_")
    rep = tmp4 / "reports"
    rep.mkdir()

    class S:
        cfg = {"review_split": "phases"}
        reports_dir = rep

        def __init__(self):
            self.boxes = {}

        def run(self, rid):
            return {"sandbox": str(self.boxes[rid])} if rid in self.boxes else None

        def sandbox_of(self, rec):
            return Path(rec["sandbox"])

    s = S()
    s.boxes["r1_guided_review_b"] = tmp4 / "B"
    s.boxes["r1_guided_review"] = tmp4 / "A"
    for d in (tmp4 / "A" / "guided_review", tmp4 / "B" / "guided_review"):
        d.mkdir(parents=True)
        (d / "findings.json").write_text("{}", encoding="utf-8")
    check("C38 the prior-round fallback prefers session B's merged list",
          nb.prior_review_dir(s, 2) == tmp4 / "B" / "guided_review",
          str(nb.prior_review_dir(s, 2)))


# ---------------------------------------------------------------------------
# C39/C40/C53 -- test-environment scripts
# ---------------------------------------------------------------------------
def test_scripts():
    print("\n== C39/C40/C53: test-environment scripts ==")
    create = (WS / "scripts/create-test-env.sh").read_text(encoding="utf-8")
    check("C39 the verification runs the pipeline with cwd = the checkout",
          "cwd=ws" in create and 'os.path.join(ws, "paper_pipeline.py")' in create)
    check("C40 the Python assertion honours PAPER_REFINE_TEST_PYTHON",
          "PAPER_REFINE_TEST_EXPECT_PYTHON" in create
          and "sys.version_info[:2] == want" in create)
    p = subprocess.run(["bash", str(WS / "scripts/export-test-env.sh"), "--out"],
                       capture_output=True, text=True, timeout=60)
    check("C53 --out without a value prints the usage error, not an unbound variable",
          p.returncode == 2 and "requires a directory argument" in (p.stdout + p.stderr),
          (p.stdout + p.stderr)[-120:])


# ---------------------------------------------------------------------------
# R01-R03 -- the verify-fixes repair round
# ---------------------------------------------------------------------------
def test_repair_r01_r02_r03():
    print("\n== R01-R03: verify-fixes repair checks ==")
    # R01: a split review with a non-full scope plans only session A, so every
    # consumer must resolve A (not the unplanned B) and the audit/revise
    # materializers must actually run.
    ctx = cc.build_root(scratch("repair_r01_"), probe="off", audit="on",
                        review_rows=())
    ctx.cfg["review_split"] = "phases"
    ctx.cfg["review_scope"] = ["formatting-writing"]
    ctx.state["config"] = ctx.cfg
    producer = nb.review_producer_rid(ctx, 1)
    check("R01a a split non-full scope resolves the single review session A",
          producer == nb.rid_guided_review(1), producer)
    ctx_full = cc.build_root(scratch("repair_r01_full_"), probe="off", audit="off",
                             review_rows=())
    ctx_full.cfg["review_split"] = "phases"
    ctx_full.cfg["review_scope"] = ["full"]
    ctx_full.state["config"] = ctx_full.cfg
    check("R01a2 a full-scope split still resolves session B",
          nb.review_producer_rid(ctx_full, 1) == nb.rid_guided_review_b(1),
          nb.review_producer_rid(ctx_full, 1))
    arec = rrec = None
    err = ""
    try:
        arec = nb.materialize_audit(ctx, 1)
        ctx.state["runs"][nb.rid_audit(1)]["status"] = "done"
        rrec = nb.materialize_revise(ctx, 1, nb.revise_vid(1))
    except Exception as e:                                       # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    check("R01b split + formatting-writing reaches the audit and revise materializers",
          arec is not None and rrec is not None
          and (ctx.sandbox_of(arec) / "guided_review" / "findings.json").is_file()
          and (ctx.sandbox_of(rrec) / "guided_review" / "findings.json").is_file(),
          err)
    stale = []
    reset = []
    if arec is not None and rrec is not None:
        stale = (nb._input_freshness_problems(ctx, arec)
                 + nb._input_freshness_problems(ctx, rrec))
        reset = nb.revalidate_round_inputs(ctx, 1)
    check("R01c re-entry freshness resolves the same producer for audit and revise",
          arec is not None and rrec is not None and stale == [] and reset == [],
          f"{stale} {reset}")

    # R02: the documented environment proof runs `paper_pipeline.py --version`.
    p = cli("--version", timeout=120)
    check("R02 the documented global --version prints VERSION and exits 0",
          p.returncode == 0 and nb.VERSION in p.stdout,
          f"rc={p.returncode} stdout={p.stdout!r} stderr={p.stderr[-160:]!r}")

    # R03: both copies of the revision skill carry the targeted-revision H1.
    skill = (WS / "paper-skills/paper-revise/SKILL.md").read_text(encoding="utf-8")
    prompt = (WS / "paper-skills/prompts/adress_issues.prompt.md").read_text(
        encoding="utf-8")
    check("R03 the revision skill and its prompt are headed Targeted Revision",
          "# Targeted Revision — adress_issues" in skill
          and "# Targeted Revision — adress_issues" in prompt
          and "# Guided Revision — adress_issues" not in skill + prompt)


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    test_c01_c04()
    test_c03_scoped_archive()
    test_c05_c06_c09()
    test_c07()
    test_c11_c12()
    test_docs()
    test_policies()
    test_helpers()
    test_scripts()
    test_repair_r01_r02_r03()
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("ALL 2026-10-31 05:31 FIX-BUGS + REPAIR CHECKS PASSED")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""The 2026-10-10 discovery parity: integrate the review's X-* list, judges re-derive their own.

Run:  python3 .paper_test/test_discovery_parity_2026_1010.py

The review skill's phase-3 discovery round (D0-D5, `review/round2/`) is the only
source of defect classes the frozen checklist does not own; its findings (ids
`X-*`) are what the revision arms must resolve. Two consistency gaps are closed
here:

  * the INTEGRATION stage used to be told nothing about the list, so a donor's X
    fix could be dropped as an "unnamable" difference and the round's revision
    work could vanish from the integrated package;
  * the JUDGE panel used to ignore that class of findings entirely. A judge is
    COMPLETELY blind to where a package came from (no other session's findings,
    no round, no producing agent), so it is NOT handed any list: contract v5
    requires the judge to RE-DERIVE its own bounded discovery pass over every
    side -- one disposed file per side under `judge_review/discovery/` -- and to
    score any X-class difference as a normal ledger row (the shared class rule
    decides the tier).

  P1  the review's list is RESOLVED like every other round artifact
      (`round_discovery_dir`: the review sandbox, part B under a split review,
      the archived `reports/round<r>_review/` copy) and an auditor `drop` takes
      the id out of force;
  P2  it is SEEDED, byte-for-byte, into the INTEGRATION sandbox
      (`frozen_discovery/findings_extra.{json,md}`, read-only, recorded in the
      run's input manifest), its prompt names the ids, and NO judge sandbox ever
      receives a discovery seed (complete blinding);
  P3  the judge's OWN discovery pass is enforced: one disposed file per side
      (missing/empty = failed run, structural softness = warning), X-* rows cite
      the judge's own ids, and the census credits an X defect to the version
      that still carries it;
  P4  the integration ledger must reconcile every X id (ported / kept-base /
      no-donor-fix), so a revision cannot be lost in the merge;
  P5  a real stub round proves the whole chain with one X id.

P1-P2 fail on the pre-parity tree; P3-P5 fail on the seeded-list tree (where the
judge was handed another session's list instead of re-deriving its own).

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_disc", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_disc"] = nb
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


X_FINDINGS = [
    {"id": "X-001", "location": "base/manuscript-a.md:2", "category": 2,
     "check": "convention applied unevenly", "severity": "Major",
     "evidence": "the term is spelled two ways in one section",
     "explanation": "one convention, applied in one place and not another",
     "status": "resolvable"},
    {"id": "X-002", "location": "base/manuscript-a.md:3", "category": 5,
     "check": "pointer without a target", "severity": "Minor",
     "evidence": "the sentence promises a deposit that is never located",
     "explanation": "a supported item whose pointer is missing",
     "status": "resolvable"},
]


def build_root(tmp: Path, judges: int = 1, rewrites: int = 0, revises: int = 1,
               audit: str = "off", discovery=True, archive=False, drop_x=None,
               x_findings=None):
    """A synthetic round-1 root with a done review carrying a discovery list."""
    source = tmp / "source"
    write(source / "manuscript-a.md", "title\none convention here\nmore text\n")
    root = tmp / "root"
    (root / "runs").mkdir(parents=True)
    (root / "reports").mkdir()
    shutil.copytree(source, root / "non-revised")
    pristine = root / "non-revised"
    ctx = nb.Ctx(root)
    ctx.cfg = {"rounds": 1, "judges": judges, "rewrites": [rewrites], "revises": [revises],
               "audit": audit, "integrators": [0]}
    ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "source_manifest": nb.hash_manifest(pristine),
                 "original_digest": nb.corpus_tree_digest(pristine),
                 "original_content_fingerprint":
                     nb.corpus_content_set_fingerprint([(pristine, "", ())]),
                 "judge_salt": "discsalt", "config": ctx.cfg, "source": str(source)}
    a1 = nb.rid_a1(1)
    shutil.copytree(pristine, root / "runs" / a1 / "base")
    rec = ctx.register(a1, "a1", 1, f"runs/{a1}", source_id=nb.ORIGINAL_ID)
    rec["status"] = "done"
    rec["corpus_digest"] = nb.recompute_corpus_digest(ctx, 1, "a1")
    rec["content_fingerprint"] = nb.corpus_content_fingerprint(ctx, 1, "a1")

    def register_fresh(vid, text):
        rid = nb.rid_for_fresh(1, vid)
        out = ctx.root / "runs" / rid / nb.output_dir_for_vid(vid)
        write(out / "manuscript-a.md", text)
        r = ctx.register(rid, nb.arm_of_vid(vid), 1, f"runs/{rid}", source_id="a1",
                         produces=vid)
        r["status"] = "done"
        r["corpus_digest"] = nb.recompute_corpus_digest(ctx, 1, vid)
        r["content_fingerprint"] = nb.corpus_content_fingerprint(ctx, 1, vid)
        return r

    register_fresh(nb.revise_vid(1), "title\none Convention here\nmore text\n")
    # The round's review, carrying the discovery deliverables.
    rev = ctx.register(nb.rid_review(1), "review", 1, f"runs/{nb.rid_review(1)}")
    rev["status"] = "done"
    rsb = ctx.sandbox_of(rev)
    (rsb / "review").mkdir(parents=True, exist_ok=True)
    write(rsb / "review" / "findings.json",
          {"submission_dir": "./base", "findings": [], "coverage": []})
    if discovery:
        rows = X_FINDINGS if x_findings is None else x_findings
        write(rsb / "review" / "round2" / "findings_extra.json",
              {"findings": rows, "coverage": []})
        write(rsb / "review" / "round2" / "findings_extra.md",
              "# D4\n\n" + "\n".join(f"- {f['id']}: {f['explanation']}" for f in rows))
    if archive:
        write(ctx.reports_dir / "round1_review" / "findings_extra.json",
              {"findings": X_FINDINGS, "coverage": []})
        write(ctx.reports_dir / "round1_review" / "findings_extra.md", "# D4 archived\n")
        # The pruned-round case: no live review sandbox content at all.
        shutil.rmtree(rsb / "review" / "round2", ignore_errors=True)
    if audit == "on":
        arec = ctx.register(nb.rid_audit(1), "audit", 1, f"runs/{nb.rid_audit(1)}")
        arec["status"] = "done"
        disps = [{"id": f["id"], "verdict": "confirm", "reason": "x" * 30,
                  "evidence": "y" * 60, "severity_after": f["severity"]} for f in X_FINDINGS]
        if drop_x:
            for d in disps:
                if d["id"] == drop_x:
                    d["verdict"] = "drop"
                    d["reason"] = ("the quoted text does not exist in base/: the passage states "
                                   "a pointer that is resolved two lines later")
        write(ctx.sandbox_of(arec) / "audit" / "audit.json",
              {"round": 1, "dispositions": disps, "adds": [],
               "counts": {"confirmed": len(disps), "dropped": 1 if drop_x else 0, "added": 0},
               "coverage": [], "notes": "fixture"})
    return ctx


# =====================================================================
# P1 -- resolution: the review sandbox, the archive, and the auditor's drops
# =====================================================================

def test_resolution():
    print("\n== P1 the frozen discovery list is resolved like every round artifact ==")
    ctx = build_root(scratch("disc_p1_"))
    found = nb.round_discovery_dir(ctx, 1)
    check("P1a the review sandbox owns the list",
          found is not None and found.as_posix().endswith("runs/r1_review/review/round2"),
          str(found))
    seed = nb.round_discovery_seed(ctx, 1)
    check("P1b the seed carries both X ids in file order",
          seed["ids"] == ["X-001", "X-002"] and not seed["dropped"], str(seed))

    ctx2 = build_root(scratch("disc_p1_arch_"), archive=True)
    seed2 = nb.round_discovery_seed(ctx2, 1)
    check("P1c a pruned round falls back to reports/round1_review/",
          seed2["ids"] == ["X-001", "X-002"] and str(seed2["source"]).endswith("round1_review"),
          f"{seed2['ids']} from {seed2['source']}")

    ctx3 = build_root(scratch("disc_p1_drop_"), audit="on", drop_x="X-002")
    seed3 = nb.round_discovery_seed(ctx3, 1)
    check("P1d an auditor DROP takes the id out of force (and is reported)",
          seed3["ids"] == ["X-001", "X-002"]
          and [d[0] for d in seed3["dropped"]] == ["X-002"],
          str(seed3))

    ctx4 = build_root(scratch("disc_p1_none_"), discovery=False)
    seed4 = nb.round_discovery_seed(ctx4, 1)
    check("P1e a round with no discovery deliverables seeds nothing",
          seed4["ids"] == [] and seed4["source"] is None, str(seed4))


# =====================================================================
# P2 -- the seed reaches the INTEGRATOR (and only the integrator)
# =====================================================================

def test_integrate_seed_and_blinding():
    print("\n== P2 the list is seeded into the integration sandbox, never into a judge's ==")
    ctx = build_root(scratch("disc_p2_"))
    irec = nb.materialize_integrate(ctx, 1, 1)
    isb = ctx.sandbox_of(irec)
    src = nb.round_discovery_dir(ctx, 1) / "findings_extra.json"
    seeded = isb / "frozen_discovery" / "findings_extra.json"
    check("P2a the integration sandbox carries the list byte-for-byte",
          seeded.is_file() and seeded.read_bytes() == src.read_bytes(), str(seeded))
    check("P2b the integration run records the ids it must reconcile",
          irec.get("discovery_ids") == ["X-001", "X-002"], str(irec.get("discovery_ids")))
    iprompt = (isb / "PROMPT.md").read_text(encoding="utf-8")
    check("P2c the integration prompt states the port/keep/reconcile rule",
          "INTEGRATE THE FIXES" in iprompt and "preserves X-001" in iprompt
          and "must reconcile EVERY X id" in iprompt)
    check("P2d the seed is a recorded read-only input",
          (irec.get("inputs_manifest") or {}).get(nb.DISCOVERY_SEED_DIR) is not None
          and not nb.input_mismatches(ctx, irec), str(nb.input_mismatches(ctx, irec)))
    seeded.write_text("tampered", encoding="utf-8")
    check("P2e modifying the seed is a manifest mismatch",
          any(nb.DISCOVERY_SEED_DIR in e for e in nb.input_mismatches(ctx, irec)),
          str(nb.input_mismatches(ctx, irec)))

    ctx_j = build_root(scratch("disc_p2_judge_"))
    field, _dropped = nb.build_field(ctx_j, 1)
    jids = nb.materialize_judges(ctx_j, 1, field)
    jsb = ctx_j.sandbox_of(ctx_j.run(jids[0]))
    check("P2f a judge sandbox carries NO discovery seed (complete blinding)",
          not (jsb / nb.DISCOVERY_SEED_DIR).exists()
          and (ctx_j.run(jids[0]).get("inputs_manifest") or {}).get(nb.DISCOVERY_SEED_DIR) is None
          and ctx_j.run(jids[0]).get("discovery_ids") is None)
    jprompt = (jsb / "PROMPT.md").read_text(encoding="utf-8")
    check("P2g the judge prompt names no discovery seed",
          "frozen_discovery" not in jprompt and "findings_extra" not in jprompt)
    ctx_none = build_root(scratch("disc_p2_none_"), discovery=False)
    irec_n = nb.materialize_integrate(ctx_none, 1, 1)
    check("P2h a round with no discovery list seeds no integration directory and says so",
          not (ctx_none.sandbox_of(irec_n) / nb.DISCOVERY_SEED_DIR).exists()
          and irec_n.get("discovery_ids") == []
          and "no frozen discovery findings" in
              (ctx_none.sandbox_of(irec_n) / "PROMPT.md").read_text("utf-8"))
    ctx_empty = build_root(scratch("disc_p2_empty_"), x_findings=[])
    irec_e = nb.materialize_integrate(ctx_empty, 1, 1)
    check("P2i a discovery phase that found no X finding seeds nothing",
          not (ctx_empty.sandbox_of(irec_e) / nb.DISCOVERY_SEED_DIR).exists()
          and irec_e.get("discovery_ids") == [])


# =====================================================================
# P3 -- the judge RE-DERIVES its own discovery findings (contract v5)
# =====================================================================

def judge_sandbox(tmp: Path, labels=("v1", "v2"), sides=("target", "v1", "v2"), rows=5,
                  finding=False, ledger=()):
    """A minimal judge sandbox: the discovery files (+ an optional sheet)."""
    sb = tmp / "judge_x_j1"
    header = "| class | probe | checked | disposition |\n|---|---|---|---|\n"
    for side in sides:
        body = []
        for i in range(rows):
            row = f"| class {i} | probe the class | {side}/f000{i}.md | "
            row += (f"finding - X-{i + 1:03d}: {side}/f000{i}.md: evidence"
                    if finding and i == 0
                    else f"clean - checked: {side}/f000{i}.md")
            body.append(row + " |")
        write(sb / "judge_review" / "discovery" / f"{side}.md",
              header + "\n".join(body) + "\n")
    if ledger:
        comps = [{"opponent_label": labels[0], "score": 2, "basis": "consistency",
                  "resolved": [{"check": cid, "tier": "consistency", "severity": "minor",
                                "evidence": "fixture"} for cid in ledger],
                  "introduced": [],
                  "checks": {c: "clean -- fixture" for c in nb.JUDGE_COVERAGE_CHECKS},
                  "reason": "fixture"}]
        write(sb / "scores.json", {"run_id": "judge_x_j1", "target_id": "tok",
                                   "judge_index": 1, "comparisons": comps, "notes": ""})
    return sb, {"kind": "judge", "label_map": {l: l for l in labels}, "judge_index": 1}


def test_judge_discovery_contract():
    print("\n== P3 the judge re-derives its own X-* pass over every side ==")
    # No discovery pass at all -> a failed run (an unrun pass is indistinguishable
    # from one that found nothing; no list is handed to a judge).
    tmp = scratch("disc_p3_none_")
    sb = tmp / "judge_x_j1"
    (sb / "judge_review").mkdir(parents=True)
    errs, warns = nb.judge_discovery_problems(sb, {"kind": "judge", "label_map": {"v1": "a2"}})
    check("P3a a missing discovery pass fails the run",
          errs and nb.JUDGE_DISCOVERY_DIR in errs[0], str(errs))
    # One side missing -> the same scrutiny was not applied to every side.
    sb2, rec2 = judge_sandbox(scratch("disc_p3_side_"), sides=("target", "v1"))
    errs, warns = nb.judge_discovery_problems(sb2, rec2)
    check("P3b a missing SIDE file fails the run and names the side",
          errs and "v2" in errs[0], str(errs))
    # Empty file -> failed run; too few rows -> warning (placeholder look).
    sb3, rec3 = judge_sandbox(scratch("disc_p3_empty_"), rows=0)
    errs, warns = nb.judge_discovery_problems(sb3, rec3)
    check("P3c a discovery file with no disposed row fails the run",
          len(errs) == 3 and all("no table rows" in e for e in errs), str(errs))
    sb4, rec4 = judge_sandbox(scratch("disc_p3_thin_"), rows=2)
    errs, warns = nb.judge_discovery_problems(sb4, rec4)
    check("P3d a thin pass is a warning, not a failure",
          not errs and warns and "placeholder" in warns[0], f"{errs} {warns}")
    # A compliant pass: 5 disposed rows per side.
    sb5, rec5 = judge_sandbox(scratch("disc_p3_ok_"))
    errs, warns = nb.judge_discovery_problems(sb5, rec5)
    check("P3e a compliant pass (every side, disposed rows) passes",
          not errs and not warns, f"{errs} {warns}")
    # The pass's own ids: defined by the file it cites; an undefined id is a warning.
    sb6, rec6 = judge_sandbox(scratch("disc_p3_ids_"), finding=True, ledger=("X-001",))
    errs, warns = nb.judge_discovery_problems(sb6, rec6)
    check("P3f a row citing a pass finding resolves",
          not errs and not warns, f"{errs} {warns}")
    sb7, rec7 = judge_sandbox(scratch("disc_p3_undef_"), finding=True,
                              ledger=("X-001", "X-999"))
    errs, warns = nb.judge_discovery_problems(sb7, rec7)
    check("P3g a row citing an undefined X id is warned about",
          not errs and warns and "X-999" in warns[0], f"{errs} {warns}")
    # The sheet-side validators: an X citation is a normal row; the coverage map
    # stays the frozen ids (no X entries required, none needed).
    row = {"check": "X-001", "tier": "consistency", "severity": "major",
           "evidence": "fixture evidence here"}
    comp = {"opponent_label": "v1", "score": 2, "basis": "consistency", "resolved": [row],
            "introduced": [],
            "checks": {c: "clean -- fixture" for c in nb.JUDGE_COVERAGE_CHECKS},
            "reason": "fixture"}
    errs, warns = nb.judge_basis_problems(comp, "c[0]", strict=True)
    check("P3h an X row derives cleanly and is not warned about",
          not errs and not warns, f"{errs} {warns}")
    errs, warns = nb.judge_coverage_problems(comp, "c[0]", strict=True)
    check("P3i the coverage map stays the frozen ids alone",
          not errs and not warns, f"{errs} {warns}")
    # The census (the ranking's leading comparator) reads an X row like any
    # other: a defect the target RESOLVED is attributed to the opponent.
    census = nb.build_issue_census([("sess1", "a2", "a1", comp)], ["a1", "a2"])
    check("P3j an X row feeds the census in its mapped tier (credited to the version "
          "that still carries the defect)",
          census["a1"]["tiers"]["consistency"]["severities"]["major"]["total"] == 1
          and census["a2"]["tiers"]["consistency"]["severities"]["major"]["total"] == 0,
          str({v: census[v]["tiers"]["consistency"]["total"] for v in ("a1", "a2")}))
    check("P3k the contract version is 5", nb.JUDGE_CONTRACT_VERSION == 5,
          str(nb.JUDGE_CONTRACT_VERSION))


def test_judge_prompt():
    print("\n== P3b the judge prompt demands the pass and stays provenance-free ==")
    prompt = nb.judge_prompt(Path("/tmp/x"), "judge_tok_j1", 1, "tok", 1, 2, ["v1", "v2"])
    flat = " ".join(prompt.split())
    check("P3b1 the prompt demands the judge's own discovery pass on every side",
          "YOUR OWN DISCOVERY PASS" in prompt
          and "judge_review/discovery/target.md" in prompt
          and "judge_review/discovery/<label>.md" in prompt
          and "SAME candidates and depth for each side" in flat)
    check("P3b2 the prompt maps a discovered difference to the shared class rule",
          "the shared defect-class rule gives the finding's category" in prompt)
    check("P3b3 the prompt hands over no list and no seed vocabulary",
          "frozen_discovery" not in prompt and "findings_extra" not in prompt)
    forbidden = {
        r"\bround\b": "round", r"\barm\b": "arm", r"\brewrite\b": "rewrite",
        r"\brevised\b": "revised", r"\brevision\b": "revision",
        r"\bintegration\b": "integration", r"\bmerge\b": "merge",
        r"\bchampion\b": "champion", r"\b(?:a1|a2|w1|i1)\b": "arm id",
        r"\br\d+_judge": "round-prefixed run id", r"CHANGELOG": "bookkeeping name",
        r"MANUAL_STEPS": "bookkeeping name", r"REVISION_REPORT": "bookkeeping name",
        r"DIFF_LEDGER": "bookkeeping name", r"AUTHOR TO COMPLETE": "marker token",
    }
    hits = {name: re.findall(pat, prompt, re.I) for pat, name in forbidden.items()}
    hits = {k: v for k, v in hits.items() if v}
    check("P3b4 the judge prompt is free of provenance vocabulary", not hits, str(hits))
    check("P3b5 the blinding rule is stated with its one venue-level exception",
          "BLINDING RULE" in prompt and "venue-level exception" in prompt
          and "identical for every session" in prompt)


# =====================================================================
# P4 -- the integration ledger reconciles the list
# =====================================================================

def test_integration_ledger():
    print("\n== P4 the integration ledger reconciles every X id ==")
    tmp = scratch("disc_p4_")
    ledger = tmp / "integrated" / "DIFF_LEDGER.md"
    write(ledger, "| id | donor | finding effect |\n|---|---|---|\n"
                  "| D-001 | a2 | preserves X-001 |\n| X-002 | (discovery) | preserves X-002 |\n")
    check("P4a a ledger that names every id reconciles",
          nb.discovery_ledger_reconciliation_problems(ledger, ["X-001", "X-002"]) == [])
    write(ledger, "| id | donor | finding effect |\n|---|---|---|\n"
                  "| D-001 | a2 | preserves X-001 |\n")
    probs = nb.discovery_ledger_reconciliation_problems(ledger, ["X-001", "X-002"])
    check("P4b an unreconciled id is reported with its id",
          len(probs) == 1 and "X-002" in probs[0], str(probs))
    check("P4c no discovery list -> no requirement",
          nb.discovery_ledger_reconciliation_problems(ledger, []) == [])
    ctx = build_root(scratch("disc_p4_sb_"))
    rec = nb.materialize_integrate(ctx, 1, 1)
    sb = ctx.sandbox_of(rec)
    probs = nb.discovery_ledger_reconciliation_problems(
        sb / nb.INTEGRATION_LEDGER_REL, rec["discovery_ids"])
    check("P4d the postcheck's reader names the integration ledger and the missing ids",
          len(probs) == 1 and probs[0].startswith(nb.INTEGRATION_LEDGER_REL)
          and "X-001" in probs[0] and "X-002" in probs[0], str(probs))
    write(sb / nb.INTEGRATION_LEDGER_REL,
          "# ledger\n\n| id | donor | location | size | donor says | self says | verdict | why | "
          "effect | artifact | finding effect |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
          "| X-001 | (discovery) | frozen_discovery/findings_extra.json | small | — | — | "
          "keep-self | fixture | none | integrated/work/diffs/D-000.md | preserves X-001 |\n"
          "| X-002 | (discovery) | frozen_discovery/findings_extra.json | small | — | — | "
          "keep-self | fixture | none | integrated/work/diffs/D-000.md | preserves X-002 |\n")
    led = nb.integration_ledger_report(sb / nb.INTEGRATED_DIR, [], expect_both_levels=False)
    check("P4e the reconciliation rows stay valid ledger rows",
          led["rows"] == 2 and not led["missing_artifact"] and not led["missing_finding"],
          str(led))


# =====================================================================
# P5 -- one real (stub-agent) round: review -> audit -> revise -> integrate -> judge
# =====================================================================

def test_end_to_end_round():
    print("\n== P5 a stub round carries the discovery contracts through every stage ==")
    tmp = scratch("disc_p5_")
    source = tmp / "source"
    write(source / "manuscript-o.md", "# Title\n\nstub text\n")
    root = tmp / "root"
    setup = [sys.executable, str(WS / "paper_pipeline.py"), "setup",
             "--source", str(source), "--root", str(root), "--rounds", "1", "--judges", "1",
             "--rewrites", "0", "--revises", "1", "--integrators", "1"]
    proc = subprocess.run(setup, capture_output=True, text=True, timeout=900)
    check("P5a setup", proc.returncode == 0, (proc.stderr or "")[-300:])
    here = Path(__file__).resolve().parent
    run = [sys.executable, str(WS / "paper_pipeline.py"), "run", "--root", str(root),
           "--agent-cmd", json.dumps([sys.executable, str(here / "stub_agent.py")]),
           "--judge-agent-cmd", json.dumps([sys.executable, str(here / "stub_judge.py")]),
           "--retries", "0"]
    env = dict(os.environ, PAPER_STUB_DISCOVERY_X="1")
    proc = subprocess.run(run, capture_output=True, text=True, timeout=1800, env=env, cwd="/tmp")
    check("P5b the stub round completes with the discovery contracts on",
          proc.returncode == 0, (proc.stdout or "")[-800:])
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    runs = state.get("runs") or {}
    judge_runs = [r for r in runs if runs[r].get("kind") == "judge"]
    ok = bool(judge_runs)
    for rid in judge_runs:
        sb = root / "runs" / rid
        labels = list((runs[rid].get("label_map") or {}).keys())
        ok = ok and not (sb / nb.DISCOVERY_SEED_DIR).exists()
        ok = ok and (sb / nb.JUDGE_DISCOVERY_DIR / "target.md").is_file()
        ok = ok and all((sb / nb.JUDGE_DISCOVERY_DIR / f"{l}.md").is_file() for l in labels)
    check("P5c judge sandboxes carry their OWN pass for every side and no seed", ok)
    int_runs = [r for r in runs if runs[r].get("kind") == "integrate"]
    led = (root / "runs" / int_runs[0] / "integrated" / "DIFF_LEDGER.md").read_text(
        encoding="utf-8") if int_runs else ""
    check("P5d the integrated ledger reconciles X-001", bool(int_runs) and "X-001" in led,
          led[:200])
    rev_runs = [r for r in runs if runs[r].get("kind") == "revise"]
    rep = (root / "runs" / rev_runs[0] / "revised" / "revision_report.json").read_text(
        encoding="utf-8") if rev_runs else ""
    check("P5e the revision ledger named X-001", bool(rev_runs) and "X-001" in rep, rep[:200])
    aud_runs = [r for r in runs if runs[r].get("kind") == "audit"]
    aud = (root / "runs" / aud_runs[0] / "audit" / "audit.json").read_text(
        encoding="utf-8") if aud_runs else ""
    check("P5f the auditor disposed X-001", bool(aud_runs) and "X-001" in aud, aud[:200])


def main():
    try:
        test_resolution()
        test_integrate_seed_and_blinding()
        test_judge_discovery_contract()
        test_judge_prompt()
        test_integration_ledger()
        test_end_to_end_round()
    finally:
        cleanup()
    if FAILS:
        print(f"\n{len(FAILS)} FAILURE(S):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

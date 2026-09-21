#!/usr/bin/env python3
"""Regression suite for the pool/integration change requests.

Run:  python3 .nbt_test/test_change_requests.py

Covers four areas plus two end-to-end runs:

  CR1  every round stages M REWRITTEN candidates first (w1..wM) and N
       reviewed-and-then-revised candidates (a2..a{1+N}, ONE shared review pass
       feeding N revise sessions), and EVERY pool member is then reworked ONCE
       by an integration run that sees the WHOLE pool as donors
       (i1 = a1 <- (w1..wM, a2..), i2 = w1 <- (a1, w2.., a2..), ...).
       Asserted: no pairwise "cross-pollination" arms exist anywhere.
  CR2  M (--rewrites) and N (--revises) are command-line parameters that accept
       either one integer or a per-round list; a short list is extended by
       repeating its last element, a long one is truncated; defaults [2,1]/[1,1].
  CR3  the optional `docx` CLI (including `docx diff`) is probed and documented
       in every prompt, useable by every agent and required of none.
  CR4  the cmd-line defaults --rounds 2 / --jobs 255 still hold.

The end-to-end sections drive real rounds with `.nbt_test/stub_agent.py` (and a
deterministic panel, `stub_judge.py`, so the outcome does not depend on hash
ordering), first with the default plan and then with a custom --rewrites /
--revises plan.

`NBT_WS` retargets the suite at a baseline copy of the tree (red before the
change, green after).
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xfix as xf  # noqa: E402

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_cr", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_cr"] = nb
spec.loader.exec_module(nb)

STUB = Path(__file__).resolve().parent / "stub_agent.py"
STUB_JUDGE = Path(__file__).resolve().parent / "stub_judge.py"
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def write(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


# =====================================================================
# CR1a - ids, plans, dependency graph
# =====================================================================

def test_plan_and_ids():
    print("== CR1a: the per-round plan, version ids and the dependency graph ==")
    check("CR1a the pool is [base, rewrites..., revisions...]",
          nb.round_pool_ids(2, 1) == ["a1", "w1", "w2", "a2"],
          str(nb.round_pool_ids(2, 1)))
    check("CR1a the candidates are every fresh arm except the base",
          nb.round_candidate_ids(2, 1) == ["w1", "w2", "a2", "i1", "i2", "i3", "i4"],
          str(nb.round_candidate_ids(2, 1)))
    check("CR1a there is ONE integrated candidate per pool member",
          nb.round_integrated_ids(2, 1) == ["i1", "i2", "i3", "i4"],
          str(nb.round_integrated_ids(2, 1)))
    check("CR1a the fresh ids are the pool plus the integrated candidates",
          nb.round_fresh_ids(1, 1) == ["a1", "w1", "a2", "i1", "i2", "i3"],
          str(nb.round_fresh_ids(1, 1)))
    check("CR1a the integrated id count is K = 1 + M + N",
          all(len(nb.round_integrated_ids(m, n)) == 1 + m + n
              for m in range(0, 4) for n in range(0, 4)))
    check("CR1a arm_of_vid classifies every arm",
          [nb.arm_of_vid(v) for v in ("a1", "w3", "a2", "a7", "i5")] ==
          ["base", "rewrite", "revise", "revise", "integrate"],
          str([nb.arm_of_vid(v) for v in ("a1", "w3", "a2", "a7", "i5")]))
    check("CR1a there is no pairwise 'b*' arm any more",
          not nb.is_fresh_vid("b1") and not nb.is_fresh_vid("b2")
          and nb.arm_of_vid("b1") == "pinned",
          str(nb.arm_of_vid("b1")))
    try:
        nb.rid_for_fresh(1, "b1")
        bad = None
    except KeyError as e:
        bad = str(e)
    check("CR1a a legacy b* id is not a round-local version id", bad is not None, str(bad))
    check("CR1a each arm maps to its own run id",
          (nb.rid_for_fresh(2, "a1"), nb.rid_for_fresh(2, "w2"), nb.rid_for_fresh(2, "a3"),
           nb.rid_for_fresh(2, "i4")) ==
          ("r2_a1", "r2_w2", "r2_a3_revise", "r2_i4"),
          str((nb.rid_for_fresh(2, "a1"), nb.rid_for_fresh(2, "w2"),
               nb.rid_for_fresh(2, "a3"), nb.rid_for_fresh(2, "i4"))))
    check("CR1a every arm writes its own output package",
          [nb.output_dir_for_vid(v) for v in ("w1", "a2", "i1")] ==
          ["rewritten", "revised", "integrated"],
          str([nb.output_dir_for_vid(v) for v in ("w1", "a2", "i1")]))
    check("CR1a output_dir_for_kind mirrors the arms",
          [nb.output_dir_for_kind(k) for k in ("rewrite", "revise", "integrate")] ==
          ["rewritten", "revised", "integrated"])
    # dependency graph
    check("CR1a a rewrite needs the round's base only",
          nb.upstream_deps({"kind": "rewrite", "round": 1, "id": "r1_w2"}) == ["r1_a1"])
    check("CR1a the review needs the round's base",
          nb.upstream_deps({"kind": "review", "round": 1, "id": "r1_review"}) == ["r1_a1"])
    check("CR1a a revise needs the base AND the frozen review",
          nb.upstream_deps({"kind": "revise", "round": 1, "id": "r1_a2_revise"}) ==
          ["r1_a1", "r1_review"])
    check("CR1a an integration run needs the WHOLE pool",
          nb.upstream_deps({"kind": "integrate", "round": 1, "id": "r1_i2",
                            "pool_ids": ["a1", "w1", "w2", "a2"]}) ==
          ["r1_a1", "r1_w1", "r1_w2", "r1_a2_revise"],
          str(nb.upstream_deps({"kind": "integrate", "round": 1, "id": "r1_i2",
                                "pool_ids": ["a1", "w1", "w2", "a2"]})))
    check("CR1a a judge needs every arm it scores",
          nb.upstream_deps({"kind": "judge", "round": 1, "id": "r1_judge_x_j1",
                            "target_id": "i1", "field_ids": ["w1", "r1_a2", "orig"]}) ==
          ["r1_i1", "r1_w1"], str(nb.upstream_deps(
              {"kind": "judge", "round": 1, "id": "r1_judge_x_j1", "target_id": "i1",
               "field_ids": ["w1", "r1_a2", "orig"]})))


def test_per_round_counts():
    print()
    print("== CR2: --rewrites / --revises (integer or per-round list) ==")
    check("CR2 the documented defaults are M=[2,1] and N=[1,1]",
          list(nb.DEFAULTS["rewrites"]) == [2, 1] and list(nb.DEFAULTS["revises"]) == [1, 1],
          f"{nb.DEFAULTS['rewrites']} / {nb.DEFAULTS['revises']}")
    check("CR2 a single integer applies to every round",
          nb.parse_round_counts(3, 4, "--rewrites") == [3, 3, 3, 3],
          str(nb.parse_round_counts(3, 4, "--rewrites")))
    check("CR2 a list is taken element by element",
          nb.parse_round_counts([3, 1, 2], 3, "--rewrites") == [3, 1, 2])
    check("CR2 a short list is EXTENDED BY REPEATING ITS LAST ELEMENT",
          nb.parse_round_counts([2, 1], 5, "--rewrites") == [2, 1, 1, 1, 1],
          str(nb.parse_round_counts([2, 1], 5, "--rewrites")))
    check("CR2 a one-element list extends to every round",
          nb.parse_round_counts([4], 3, "--rewrites") == [4, 4, 4])
    check("CR2 a longer list is truncated to --rounds entries",
          nb.parse_round_counts([1, 2, 3, 4], 2, "--rewrites") == [1, 2])
    check("CR2 string values (the CLI form) are accepted",
          nb.parse_round_counts(["2,1"], 3, "--rewrites") == [2, 1, 1]
          or nb.parse_round_counts(["2", "1"], 3, "--rewrites") == [2, 1, 1])
    for bad in (-1, ["1", "-2"]):
        try:
            nb.parse_round_counts(bad, 2, "--rewrites")
            died = False
        except SystemExit:
            died = True
        check(f"CR2 a negative count is refused ({bad!r})", died)
    # the per-round view used by the pipeline
    tmp = scratch("nbt_cr_plan_")
    ctx = nb.Ctx(tmp)
    ctx.cfg = {"rounds": 4, "rewrites": [2, 1], "revises": [1]}
    check("CR2 round_counts follows the config list per round",
          [nb.round_counts(ctx, r) for r in (1, 2, 3, 4)] ==
          [(2, 1), (1, 1), (1, 1), (1, 1)],
          str([nb.round_counts(ctx, r) for r in (1, 2, 3, 4)]))
    ctx2 = nb.Ctx(tmp)
    ctx2.cfg = {"rounds": 2, "rewrites": 1, "revises": 2}
    check("CR2 a single integer in the config applies to every round",
          [nb.round_counts(ctx2, r) for r in (1, 2)] == [(1, 2), (1, 2)],
          str([nb.round_counts(ctx2, r) for r in (1, 2)]))


# =====================================================================
# CR1b - integration: one run per pool member, the WHOLE pool as donors
# =====================================================================

def build_round1_root(tmp: Path, judges=1, pristine: Path = None):
    """A synthetic round-1 root whose base is a copy of its pristine original."""
    root = tmp / "root"
    (root / "runs").mkdir(parents=True)
    (root / "reports").mkdir()
    if pristine is None:
        write(tmp / "source" / "manuscript-b.md", "identical base text\n")
        pristine = tmp / "source"
    shutil.copytree(pristine, root / "non-revised")
    pristine = root / "non-revised"
    ctx = nb.Ctx(root)
    ctx.cfg = {"rounds": 1, "judges": judges, "rewrites": [1], "revises": [1]}
    ctx.state = {"version": nb.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "source_manifest": nb.hash_manifest(pristine),
                 "original_digest": nb.corpus_tree_digest(pristine),
                 "original_content_fingerprint":
                     nb.corpus_content_set_fingerprint([(pristine, "", ())]),
                 "judge_salt": "testsalt", "config": ctx.cfg, "source": str(pristine)}
    a1 = nb.rid_a1(1)
    shutil.copytree(pristine, root / "runs" / a1 / "base")
    rec = ctx.register(a1, "a1", 1, f"runs/{a1}", source_id=nb.ORIGINAL_ID)
    rec["status"] = "done"
    rec["corpus_digest"] = nb.recompute_corpus_digest(ctx, 1, "a1")
    rec["content_fingerprint"] = nb.corpus_content_fingerprint(ctx, 1, "a1")
    return ctx


def register_fresh(ctx, vid: str, text: str):
    """Materialize one fresh arm's output package and register it as done."""
    rid = nb.rid_for_fresh(1, vid)
    kind = nb.arm_of_vid(vid)
    out = ctx.root / "runs" / rid / nb.output_dir_for_vid(vid)
    write(out / "manuscript-p.md", text)
    if kind == "integrate":
        write(out / "DIFF_LEDGER.md", "# ledger\n")
    rec = ctx.register(rid, kind, 1, f"runs/{rid}", source_id="a1", produces=vid)
    rec["status"] = "done"
    rec["corpus_digest"] = nb.recompute_corpus_digest(ctx, 1, vid)
    rec["content_fingerprint"] = nb.corpus_content_fingerprint(ctx, 1, vid)
    rec["summary"] = {"critical_remaining": 0, "manual_items": 0}
    return rec


def test_integration_materialization():
    print()
    print("== CR1b: every pool member is reworked once, with the whole pool ==")
    tmp = scratch("nbt_cr_integ_")
    ctx = build_round1_root(tmp)
    ctx.cfg = {"rounds": 1, "judges": 1, "rewrites": [2], "revises": [1]}
    pool = nb.round_pool_ids(2, 1)
    for vid, text in (("w1", "rewrite one\n"), ("w2", "rewrite two\n"), ("a2", "revision\n")):
        register_fresh(ctx, vid, text)
    # the integration runs materialize only now, one per pool member
    runs = []
    for k in range(1, len(pool) + 1):
        rec = nb.materialize_integrate(ctx, 1, k)
        runs.append(rec)
        sb = ctx.sandbox_of(rec)
        expect_self = pool[k - 1]
        expect_others = [v for v in pool if v != expect_self]
        others = sorted(p.name for p in (sb / "others").iterdir() if p.is_dir()) \
            if (sb / "others").is_dir() else []
        check(f"CR1b i{k} takes pool member {expect_self!r} as its base",
              rec["self_id"] == expect_self and (sb / "self" / "manuscript-p.md").is_file()
              or (expect_self == "a1" and (sb / "self" / "manuscript-b.md").is_file()),
              f"self_id={rec.get('self_id')}")
        check(f"CR1b i{k} sees EVERY other pool member as a donor",
              others == sorted(expect_others), f"{others} vs {sorted(expect_others)}")
        check(f"CR1b i{k} writes its own package to integrated/",
              (sb / "integrated").is_dir() and nb.output_dir_for_vid(rec["produces"])
              == "integrated")
        prompt = (sb / "PROMPT.md").read_text(encoding="utf-8")
        check(f"CR1b i{k} prompt names the whole donor set",
              all(v in prompt for v in expect_others) and "@@OTHER" not in prompt,
              prompt[:120])
    check("CR1b there is exactly one integration run per pool member",
          [r["self_id"] for r in runs] == pool and len(runs) == len(pool),
          str([r["self_id"] for r in runs]))
    check("CR1b integration runs are independent (no pairwise pairing)",
          all(len(r["other_ids"]) == len(pool) - 1 for r in runs)
          and len({r["id"] for r in runs}) == len(pool))
    # materializing an integration run needs the WHOLE pool
    tmp2 = scratch("nbt_cr_integ2_")
    ctx2 = build_round1_root(tmp2)
    ctx2.cfg = {"rounds": 1, "judges": 1, "rewrites": [2], "revises": [1]}
    register_fresh(ctx2, "w1", "rewrite one\n")
    register_fresh(ctx2, "w2", "rewrite two\n")
    try:
        nb.materialize_integrate(ctx2, 1, 1)
        err = ""
    except RuntimeError as e:
        err = str(e)
    check("CR1b an integration run refuses to start before the pool is complete",
          "whole pool" in err.lower() or "not done" in err.lower(), err[:120])


def test_integration_postcheck():
    print()
    print("== CR1b: the integration run's contract ==")
    tmp = scratch("nbt_cr_ipc_")
    ctx = build_round1_root(tmp)
    ctx.cfg = {"rounds": 1, "judges": 1, "rewrites": [1], "revises": [1], "audit": "off"}
    register_fresh(ctx, "w1", "rewrite\n")
    register_fresh(ctx, "a2", "revision\n")
    rec = nb.materialize_integrate(ctx, 1, 2)          # i2 = w1 <- (a1, a2)
    sb = ctx.sandbox_of(rec)
    out = sb / "integrated"
    write(out / "manuscript-p.md", "integrated text\n")
    # the ledger contract (2026-09-22): one artifact per row, a size class, and
    # the finding effect; both size classes because the pool has both rewrite
    # levels. The L1-L11 language pass is required of every package stage.
    xf.write_language_pass(out)
    (out / "work" / "diffs").mkdir(parents=True, exist_ok=True)
    (out / "work" / "diffs" / "D1.md").write_text("outline diff\n", encoding="utf-8")
    (out / "work" / "diffs" / "D2.md").write_text("before/after\n", encoding="utf-8")
    write(out / "DIFF_LEDGER.md",
          "| id | donor | location | size | donor says | self says | verdict | why | effect | "
          "artifact | finding effect |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
          "| D1 | a1 | p1 | large | (e) | (e) | drop | not nameable: no defect | none | "
          "integrated/work/diffs/D1.md | preserves F-001 |\n"
          "| D2 | a2 | p3 | small | (a) | (a) | port | the donor fix is better | none | "
          "integrated/work/diffs/D2.md | none |\n")
    write(out / "MANUAL_STEPS.md", "- (none)\n")
    nb.write_json_atomic(sb / nb.MARKER_FILE,
                         {"stage": "integrate", "run_id": rec["id"], "round": 1,
                          "status": "complete",
                          "summary": {"ported": 1, "kept_base": 0, "ignored_cosmetic": 1,
                                      "shared_defects_left": 0, "donors_read": 2,
                                      "critical_remaining": 0, "manual_items": 0}})
    ok = nb.postcheck(ctx, rec)
    check("CR1b a complete integration run passes its postcheck", ok,
          str((rec.get("postcheck") or {}).get("errors")))
    # the ledger must mention every donor
    write(out / "DIFF_LEDGER.md", "# ledger\n\n| D1 | a1 | (e) | IGNORED |\n")
    nb.reset_run_record(rec)
    nb.write_json_atomic(sb / nb.MARKER_FILE,
                         {"stage": "integrate", "run_id": rec["id"], "round": 1,
                          "status": "complete", "summary": {"donors_read": 2}})
    ok = nb.postcheck(ctx, rec)
    warns = " ".join((rec.get("postcheck") or {}).get("warnings", []))
    check("CR1b a donor missing from the ledger is REPORTED (warning)", ok and "donor" in warns,
          warns[:160])
    # a missing ledger is a failure
    tmp2 = scratch("nbt_cr_ipc2_")
    ctx2 = build_round1_root(tmp2)
    ctx2.cfg = {"rounds": 1, "judges": 1, "rewrites": [1], "revises": [1]}
    register_fresh(ctx2, "w1", "rewrite\n")
    register_fresh(ctx2, "a2", "revision\n")
    rec2 = nb.materialize_integrate(ctx2, 1, 2)
    sb2 = ctx2.sandbox_of(rec2)
    write(sb2 / "integrated" / "manuscript-p.md", "integrated\n")
    nb.write_json_atomic(sb2 / nb.MARKER_FILE,
                         {"stage": "integrate", "run_id": rec2["id"], "round": 1,
                          "status": "complete", "summary": {}})
    ok2 = nb.postcheck(ctx2, rec2)
    check("CR1b a missing integrated/DIFF_LEDGER.md FAILS the run",
          not ok2 and any("DIFF_LEDGER.md" in e
                          for e in (rec2.get("postcheck") or {}).get("errors", [])),
          str((rec2.get("postcheck") or {}).get("errors"))[:160])


# =====================================================================
# CR1c - the rewrite arm and the shared review / N revisions
# =====================================================================

def test_rewrite_and_revise_arms():
    print()
    print("== CR1c: M rewrites first, then ONE review feeding N revisions ==")
    tmp = scratch("nbt_cr_rw_")
    ctx = build_round1_root(tmp)
    # the auditor's dependency is exercised elsewhere; here the revise arms are
    # materialized straight from the review.
    ctx.cfg = {"rounds": 1, "judges": 1, "rewrites": [2], "revises": [2], "audit": "off"}
    r1 = nb.materialize_rewrite(ctx, 1, 1)
    r2 = nb.materialize_rewrite(ctx, 1, 2)
    check("CR1c two rewrite runs are staged independently from the same base",
          r1["id"] == "r1_w1" and r2["id"] == "r1_w2" and r1["produces"] == "w1"
          and r2["produces"] == "w2",
          f"{r1['id']}/{r2['id']}")
    check("CR1c both rewrites write rewritten/ and read the base",
          all((ctx.sandbox_of(r) / "rewritten").is_dir()
              and (ctx.sandbox_of(r) / "base" / "manuscript-b.md").is_file()
              for r in (r1, r2)))
    prompt1 = (ctx.sandbox_of(r1) / "PROMPT.md").read_text(encoding="utf-8")
    prompt2 = (ctx.sandbox_of(r2) / "PROMPT.md").read_text(encoding="utf-8")
    check("CR1c each rewrite knows it is one of M independent rewrites",
          "rewrite 1 of 2" in prompt1 and "rewrite 2 of 2" in prompt2,
          prompt1[:60])
    # the single review
    rev = nb.materialize_review(ctx, 1)
    check("CR1c the round has ONE review run", rev["id"] == "r1_review", rev["id"])
    check("CR1c the review depends on the base only",
          nb.upstream_deps(rev) == ["r1_a1"])
    write(ctx.sandbox_of(rev) / "review" / "findings.json", "{}")
    rev["status"] = "done"
    # N revisions from the same frozen review
    a2 = nb.materialize_revise(ctx, 1, "a2")
    a3 = nb.materialize_revise(ctx, 1, "a3")
    check("CR1c N revise runs are materialized (a2..a1+N)",
          a2["id"] == "r1_a2_revise" and a3["id"] == "r1_a3_revise"
          and a2["produces"] == "a2" and a3["produces"] == "a3")
    check("CR1c every revise run consumes the SAME frozen review copy",
          nb.hash_manifest(ctx.sandbox_of(a2) / "review")
          == nb.hash_manifest(ctx.sandbox_of(a3) / "review")
          == nb.hash_manifest(ctx.sandbox_of(rev) / "review"))
    prompt_a2 = (ctx.sandbox_of(a2) / "PROMPT.md").read_text(encoding="utf-8")
    prompt_a3 = (ctx.sandbox_of(a3) / "PROMPT.md").read_text(encoding="utf-8")
    check("CR1c the revise prompts know their index and total",
          "revision 1 of 2" in " ".join(prompt_a2.split())
          and "revision 2 of 2" in " ".join(prompt_a3.split()),
          " ".join(prompt_a2.split())[:80])
    # zero-revise rounds are allowed as long as something else produces a candidate
    tmp2 = scratch("nbt_cr_n0_")
    ctx2 = build_round1_root(tmp2)
    ctx2.cfg = {"rounds": 1, "judges": 1, "rewrites": [1], "revises": [0]}
    check("CR1c M/N may be zero as long as M+N >= 1",
          nb.round_counts(ctx2, 1) == (1, 0)
          and nb.round_pool_ids(*nb.round_counts(ctx2, 1)) == ["a1", "w1"],
          str(nb.round_counts(ctx2, 1)))


# =====================================================================
# CR1d - the field, judging and selection
# =====================================================================

def test_field_and_selection():
    print()
    print("== CR1d: every arm is scored and can win ==")
    tmp = scratch("nbt_cr_sel_")
    ctx = build_round1_root(tmp, judges=1)
    ctx.cfg = {"rounds": 1, "judges": 1, "rewrites": [1], "revises": [1]}
    for vid, text in (("w1", "rewritten text\n"), ("a2", "revised text\n"),
                      ("i1", "i1 text\n"), ("i2", "i2 text\n"), ("i3", "i3 text\n")):
        register_fresh(ctx, vid, text)
    field, dropped = nb.build_field(ctx, 1)
    ids = [e["id"] for e in field]
    check("CR1d the field holds the base(deduped), every arm and every integration",
          ids == ["orig", "w1", "a2", "i1", "i2", "i3"], str(ids))
    check("CR1d the base still deduplicates into the original",
          [d["id"] for d in dropped] == ["a1"], str(dropped))
    others = {v: [w for w in ids if w != v] for v in ids}
    for vid in ids:
        labels = [f"v{i}" for i in range(1, len(others[vid]) + 1)]
        comps = []
        for lab, opp in zip(labels, others[vid]):
            if vid == "i1":
                score = 2                      # the integrated candidate is best
            elif opp == "i1":
                score = -2
            else:
                score = 0
            comps.append({"opponent_label": lab, "score": score, "reason": "unit"})
        rid = nb.rid_judge(1, nb.judge_target_token(1, vid), 1)
        ctx.state["runs"][rid] = {
            "id": rid, "kind": "judge", "round": 1, "status": "done",
            "target_id": vid, "judge_index": 1, "label_map": dict(zip(labels, others[vid])),
            "scores": {"run_id": rid, "round": 1, "target_id": vid, "judge_index": 1,
                       "comparisons": comps},
            "attempts": 1, "sandbox": f"runs/{rid}"}
    agg = nb.aggregate_round(ctx, 1, ids)
    check("CR1d the integrated candidate has a complete panel",
          agg["stats"]["i1"]["complete"] and agg["stats"]["i1"]["n"] == 10,
          str({k: agg["stats"]["i1"][k] for k in ("n", "expected_n", "complete")}))
    sel = nb.select_champion(ctx, 1, agg)
    check("CR1d every arm is eligible (none is excluded from selection)",
          {"w1", "a2", "i1", "i2", "i3"} <= set(sel["eligible"]), str(sel["eligible"]))
    check("CR1d an INTEGRATED candidate wins when the panel ranks it first",
          sel["champion"] == "i1", f"champion={sel['champion']} "
          f"ranking={[(r['id'], r['median']) for r in sel['ranking']]}")
    check("CR1d the ranking key keeps every arm on the same terms (panel stats first, then the "
          "self-reported counts (severity, then the category-2 writing count), the "
          "provenance-free content digest and the id)",
          "ranking key: (-median, -mean, IQR, critical_remaining, writing_remaining, digest, id)"
          in " ".join(sel["trace"]))


# =====================================================================
# CR3 - the optional docx CLI
# =====================================================================

def test_docx_cli():
    print()
    print("== CR3: the docx CLI is probed and every prompt documents it ==")
    probes = list(nb.VISUAL_TOOL_PROBES)
    check("CR3 docx is probed as a visual renderer",
          ("docx (`docx render`) command", "docx") in probes, str(probes))
    check("CR3 the docx probe sits after docx2pdf.sh and before soffice "
          "(the docx-converter MCP probe comes first)",
          [exe for _l, exe in probes[:4]] == ["mcp:docx-converter", "docx2pdf.sh", "docx",
                                              "soffice"],
          str([exe for _l, exe in probes[:4]]))
    import shutil as _sh
    want_label = "docx (`docx render`) command"
    summary = nb.visual_tools_summary()
    if _sh.which("docx"):
        check("CR3 the detected-renderer summary names docx on this machine",
              want_label in summary, summary)
    else:
        check("CR3 the summary omits docx when the command is absent",
              want_label not in summary, summary)
    block = nb.docx_cli_block()
    check("CR3 the docx block documents `docx diff` (available, not mandatory)",
          "docx diff" in block and "--against SNAPSHOT" in block)
    check("CR3 the docx block documents the other docx commands",
          all(cmd in block for cmd in ("docx read", "docx outline", "docx wc", "docx render",
                                       "docx validate")))
    check("CR3 the docx block says every stage may use it, including judges",
          # The block is shared with the judge prompt, so it may not name the
          # pipeline's stages; the invariant is that NO agent is excluded.
          "every agent, including the judges" in block
          and "no stage is forbidden from using it" in block)
    check("CR3 the docx block says it is optional and never scored",
          "NEVER required" in block and "never scored" in block.lower())
    old = nb.docx_cli_available
    try:
        nb.docx_cli_available = lambda: False
        check("CR3 a machine without the CLI is described honestly",
              nb.DOCX_CLI_MISSING in nb.docx_cli_block())
    finally:
        nb.docx_cli_available = old
    sb = Path("/tmp/nbt_cr_sb")
    prompts = {
        "review": nb.review_prompt(sb, "r1_review", 1),
        "rewrite": nb.rewrite_prompt(sb, "r1_w1", 1),
        "revise": nb.revise_prompt(sb, "r1_a2_revise", 1),
        "integrate": nb.integrate_prompt(sb, "r1_i2", 1, "w1", ["a1", "a2"]),
        "judge": nb.judge_prompt(sb, "r1_judge_t1_j1", 1, "t1", 1, 3, ["v1"]),
    }
    for name, text in prompts.items():
        unresolved = sorted(set(re.findall(r"@@[A-Z0-9_]+@@", text)))
        check(f"CR3 the {name} prompt carries the optional-docx rule",
              "OPTIONAL TOOLING" in text and "docx diff" in text and not unresolved,
              str(unresolved))
    check("CR3 the visual rule offers `docx render` as a converter",
          "docx render FILE --out pages/" in nb.VISUAL_INSPECTION_RULE)


# =====================================================================
# CR4 - the cmd-line defaults
# =====================================================================

def test_cli_defaults():
    print()
    print("== CR4: --rounds 2, --jobs 255, --rewrites 2,1, --revises 1,1 ==")
    check("CR4 DEFAULTS['rounds'] is 2", nb.DEFAULTS["rounds"] == 2, str(nb.DEFAULTS["rounds"]))
    check("CR4 DEFAULTS['jobs'] is 255", nb.DEFAULTS["jobs"] == 255, str(nb.DEFAULTS["jobs"]))
    parser = nb.build_parser()
    setup_args = parser.parse_args(["setup", "--source", "/tmp/nonexistent-source"])
    run_args = parser.parse_args(["run"])
    check("CR4 `setup` defaults to 2 rounds / no --rewrites value / no --revises value",
          setup_args.rounds == 2 and setup_args.rewrites is None and setup_args.revises is None,
          f"{setup_args.rounds} {setup_args.rewrites} {setup_args.revises}")
    check("CR4 `run` defaults to 255 jobs", run_args.jobs == 255, str(run_args.jobs))
    check("CR4 `setup --rewrites 2,1 --revises 1` parses into the plan lists",
          parser.parse_args(["setup", "--source", "/tmp/x", "--rewrites", "2,1",
                             "--revises", "1"]).rewrites == "2,1")
    choices = parser._subparsers._group_actions[0].choices
    subs = {a.dest: a for a in choices["setup"]._actions}
    run_subs = {a.dest: a for a in choices["run"]._actions}
    check("CR4 setup help documents --rewrites and --revises",
          "REWRITTEN" in (subs["rewrites"].help or "").upper()
          and "REVIEWED-AND-THEN-REVISED" in (subs["revises"].help or "").upper(),
          subs["revises"].help)
    check("CR4 run help advertises the 255-job default",
          "default: 255" in (run_subs["jobs"].help or ""))
    check("CR4 usage examples use the new defaults",
          "[--rounds 2]" in nb.USAGE_EXAMPLES and "--jobs 255" in nb.USAGE_EXAMPLES)


# =====================================================================
# End-to-end runs
# =====================================================================

def run_pipeline(root: Path, source: Path, rounds: int = None, jobs: int = None,
                 judges: int = 1, rewrites: str = None, revises: str = None):
    setup = [sys.executable, str(WS / "nbt_pipeline.py"), "setup",
             "--source", str(source), "--root", str(root), "--judges", str(judges)]
    if rounds is not None:
        setup += ["--rounds", str(rounds)]
    if rewrites is not None:
        setup += ["--rewrites", rewrites]
    if revises is not None:
        setup += ["--revises", revises]
    subprocess.run(setup, capture_output=True, text=True, check=True)
    run = [sys.executable, str(WS / "nbt_pipeline.py"), "run", "--root", str(root),
           "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
           # The production stages run on the generic stub; the panel runs on a
           # stub with one explicit rule (prefer the rewrite organization, with
           # no later edits stacked on it), so the end-to-end assertions are
           # about the PIPELINE's behaviour, not about hash ordering.
           "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
           "--retries", "0"]
    if jobs is not None:
        run += ["--jobs", str(jobs)]
    return subprocess.run(run, capture_output=True, text=True, timeout=900)


def test_end_to_end_default_plan():
    print()
    print("== CR1e/CR4 e2e: the default plan (M=[2,1], N=[1,1]) ==")
    tmp = scratch("nbt_cr_e2e_")
    source = tmp / "source"
    write(source / "manuscript-b.md", "title\n")
    write(source / "refs-b.bib", "x\n")
    write(source / "raw_figs" / "data.tsv", "a\tb\n")
    root = tmp / "root"
    proc = run_pipeline(root, source)            # CR4: all defaults
    out = proc.stdout + proc.stderr
    check("CR1e e2e the default run completes", proc.returncode == 0, out[-400:])
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    check("CR4 e2e setup recorded the default plan and the 255-job policy",
          cfg.get("rounds") == 2 and cfg.get("rewrites") == [2, 1]
          and cfg.get("revises") == [1, 1]
          and (state.get("run_policy") or {}).get("jobs") == 255,
          f"{cfg.get('rewrites')} {cfg.get('revises')} "
          f"{(state.get('run_policy') or {}).get('jobs')}")
    runs = state["runs"]
    check("CR1e e2e round 1 staged M=2 rewrites and round 2 M=1",
          runs["r1_w1"]["status"] == "done" and runs["r1_w2"]["status"] == "done"
          and "r2_w1" in runs and "r2_w2" not in runs,
          str(sorted(k for k in runs if re.search(r"_w\d+$", k))))
    check("CR1e e2e ONE review pass per round feeds the revise sessions",
          sum(1 for k in runs if k.endswith("_review")) == 2
          and all(runs[k]["status"] == "done"
                  for k in ("r1_review", "r2_review", "r1_a2_revise", "r2_a2_revise")),
          str(sorted(k for k in runs if "review" in k or "revise" in k)))
    r1 = state["rounds"]["1"]
    r2 = state["rounds"]["2"]
    check("CR1e e2e round 1's field is the default plan's pool + integrations",
          sorted(r1["field"]) == ["a2", "i1", "i2", "i3", "i4", "orig", "w1", "w2"],
          str(r1["field"]))
    check("CR1e e2e every pool member got its own integration run",
          all(runs[f"r1_i{k}"]["self_id"] == src
              for k, src in enumerate(["a1", "w1", "w2", "a2"], 1))
          and sorted(runs[f"r1_i{k}"]["other_ids"] for k in (1, 2, 3, 4))
          == sorted([["w1", "w2", "a2"], ["a1", "w2", "a2"],
                     ["a1", "w1", "a2"], ["a1", "w1", "w2"]]),
          str({k: (runs[k].get("self_id"), runs[k].get("other_ids"))
               for k in ("r1_i1", "r1_i2", "r1_i3", "r1_i4")}))
    check("CR1e e2e no pairwise 'b*' arm was staged",
          not any(re.search(r"_b\d+$", k) for k in runs), str(sorted(runs)))
    check("CR1e e2e the rewritten candidate won round 1 (stub judge rule)",
          r1["champion"] == "w1", f"champion={r1['champion']} field={r1['field']}")
    check("CR1e e2e the winner is pinned and republished",
          (root / "pinned/r1_w1/documents/manuscript-c.md").is_file()
          and (root / "round1_winner/manuscript-c.md").is_file()
          and r1["winner_digest"] == r1["pin_digest"])
    check("CR1e e2e round 2's base IS the rewritten candidate of round 1",
          runs["r2_a1"].get("source_id") == "r1_w1"
          and runs["r2_a1"].get("base_source_digest") == r1["pin_digest"])
    check("CR1e e2e round 2 keeps the incumbent when the panel sees no difference",
          r2["champion"] == "a1" and r2["pin_id"] == "r2_a1",
          f"champion={r2['champion']} field={r2['field']}")
    # per-run integration donor sets in round 2 (M=1, N=1)
    check("CR1e e2e round 2 integrates three pool members with the whole pool",
          all(runs[f"r2_i{k}"]["status"] == "done" for k in (1, 2, 3))
          and runs["r2_i2"]["self_id"] == "w1"
          and sorted(runs["r2_i2"]["other_ids"]) == ["a1", "a2"],
          str({k: (runs[k].get("self_id"), runs[k].get("other_ids"))
               for k in ("r2_i1", "r2_i2", "r2_i3")}))
    manifest = json.loads((root / "redlines/manifest.json").read_text(encoding="utf-8"))
    vids = {v["version"] for v in manifest["versions"]}
    check("CR1e e2e tracked changes cover every candidate of the last round",
          vids == set(nb.round_candidate_ids(1, 1)), str(sorted(vids)))
    dec = subprocess.run([sys.executable, str(WS / "nbt_pipeline.py"), "decide",
                          "--root", str(root)], capture_output=True, text=True, timeout=600)
    check("CR1e e2e decide certifies the run", dec.returncode == 0,
          (dec.stdout + dec.stderr)[-300:])
    report = (root / "reports/DECISION_REPORT.md").read_text(encoding="utf-8")
    check("CR1e e2e the decision report describes the pool and the integration stage",
          "M=" in report and "INTEGRATION" in report.upper() and "i1" in report)
    check("CR1e e2e the run log names the integration donor sets",
          "i1 = a1 <- (w1, w2, a2)" in out and "Sessions start as soon as their inputs exist" in out,
          out[-200:])


def test_end_to_end_custom_plan():
    print()
    print("== CR2 e2e: a custom plan (--rewrites 1 --revises 2) ==")
    tmp = scratch("nbt_cr_e2e2_")
    source = tmp / "source"
    write(source / "manuscript-b.md", "title\n")
    write(source / "refs-b.bib", "x\n")
    root = tmp / "root"
    proc = run_pipeline(root, source, rounds=1, rewrites="1", revises="2")
    out = proc.stdout + proc.stderr
    check("CR2 e2e the custom plan runs to completion", proc.returncode == 0, out[-400:])
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    check("CR2 e2e the plan is stored as given",
          cfg.get("rewrites") == [1] and cfg.get("revises") == [2],
          f"{cfg.get('rewrites')} {cfg.get('revises')}")
    check("CR2 e2e a single round with a one-element list is normalized to that round",
          cfg.get("rounds") == 1)
    runs = state["runs"]
    r1 = state["rounds"]["1"]
    check("CR2 e2e M=1 produced exactly one rewrite and N=2 two revisions",
          runs["r1_w1"]["status"] == "done" and "r1_w2" not in runs
          and runs["r1_a2_revise"]["status"] == "done"
          and runs["r1_a3_revise"]["status"] == "done",
          str(sorted(k for k in runs if re.search(r"_[wa]\d+", k))))
    check("CR2 e2e both revisions consumed the ONE frozen review copy",
          nb.hash_manifest(root / "runs/r1_a2_revise/review")
          == nb.hash_manifest(root / "runs/r1_a3_revise/review")
          == nb.hash_manifest(root / "runs/r1_review/review"))
    check("CR2 e2e the field is the custom pool's arms plus K=4 integrations",
          sorted(r1["field"]) == ["a2", "a3", "i1", "i2", "i3", "i4", "orig", "w1"],
          str(r1["field"]))
    check("CR2 e2e the integration runs cover the custom pool",
          sorted([runs[f"r1_i{k}"]["self_id"] for k in range(1, 5)]) ==
          ["a1", "w1", "a2", "a3"]
          or sorted([runs[f"r1_i{k}"]["self_id"] for k in range(1, 5)]) ==
          ["a1", "a2", "a3", "w1"],
          str([runs[f"r1_i{k}"]["self_id"] for k in range(1, 5)]))
    check("CR2 e2e the plan is recorded on the round",
          r1.get("plan", {}).get("rewrites") == 1 and r1.get("plan", {}).get("revises") == 2,
          str(r1.get("plan")))


def main() -> int:
    sections = (("CR1a", test_plan_and_ids),
                ("CR2", test_per_round_counts),
                ("CR1b", test_integration_materialization),
                ("CR1b", test_integration_postcheck),
                ("CR1c", test_rewrite_and_revise_arms),
                ("CR1d", test_field_and_selection),
                ("CR3", test_docx_cli),
                ("CR4", test_cli_defaults),
                ("CR1e-default", test_end_to_end_default_plan),
                ("CR2-e2e", test_end_to_end_custom_plan))
    try:
        for name, fn in sections:
            try:
                fn()
            except Exception as e:                              # noqa: BLE001
                # A baseline tree (NBT_WS=<pre-change copy>) does not even define
                # the new symbols: report that as a failure of the section
                # instead of dying with a traceback, so this file works as a
                # repro script (red before the change, green after).
                check(f"{name} section completed", False, f"{type(e).__name__}: {e}")
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL CHANGE-REQUEST CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""`--execution-profile` and `--guided-review`: the recorded policies.

Run:  python3 .paper_test/test_execution_profile.py

What this suite pins:

  * `--execution-profile high` is the pipeline's own shell: the eleven stage
    prompts render to the frozen sha256 below (a golden regenerated only by a
    deliberate prompt change), a default root's
    `pipeline_config.json` carries NO new key, and the round plan is the
    documented one.  `high` is the default, so an untouched root is byte-
    identical to the old code's.
  * `medium` keeps every rule but pages the elaborative ones: each stage prompt
    is materially smaller, the paged text really ships in the sandbox
    (`INSTRUCTIONS/PROFILE_RULES.md`), and the stage contract is stated inline.
  * `--no-guided-review` plans NO guided review, runs the probe as the only
    finding source, synthesizes the frozen review view with the missing pass
    recorded as a NAMED GAP, and tells the audit/revise sessions so.
    `setup` refuses every combination that would leave the round with no
    finding source.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = HERE.parent
STUB = HERE / "stub_agent.py"
STUB_JUDGE = HERE / "stub_judge.py"
FAILS = []

# The eleven stage prompts, rendered by `.paper_test/render_stage_prompts.py`.
# They are the `--execution-profile high` SHELL pin: a prompt may only change by
# a deliberate, reviewed edit, and the profile logic must not perturb `high` by
# itself.  Regenerate with:
#   PAPER_RENDER_SANDBOX=$PWD/tmp/render-sandbox/r1_review \
#     python .paper_test/render_stage_prompts.py .
# and paste the hashes here in the SAME commit that changes the prompts.
GOLDEN = {
    "review": "a781a7284eeb9ccf",
    "review_split_a": "8acbdb1f60a171b4",
    "review_scoped": "be7f6ba4186c618c",
    "cold_start_review": "7d168e9e6f95c876",
    "audit": "d2d4579cfd1dec78",
    "revise": "1db4da9a492b5c65",
    "integrate": "0e2a94a006921bf9",
    "rewrite": "a7331dbb7a9d95a4",
    "judge": "0031c40b30aeec88",
    "revision_audit": "074eaee68fccba2b",
    "revision_repair": "afcc7d353ce5e7e2",
}


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"[ok ] {name}")
    else:
        print(f"[FAIL] {name}" + (f" -- {detail}" if detail else ""))
        FAILS.append(name)


def cli(*argv, timeout=1200):
    return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *argv],
                          capture_output=True, text=True, timeout=timeout)


def make_source(tmp: Path) -> Path:
    src = tmp / "src"
    src.mkdir()
    (src / "manuscript.md").write_text(
        "Abstract\n\n" + ("word " * 90).strip() + "\n\nIntroduction\n\n"
        + ("text " * 160).strip() + "\n\nFigure 1 | A caption here.\n\nMethods\n\nx\n",
        encoding="utf-8")
    return src


def pipeline_module():
    if str(WS) not in sys.path:
        sys.path.insert(0, str(WS))
    for mod in [m for m in sys.modules if m == "paper_pipeline"]:
        del sys.modules[mod]
    return importlib.import_module("paper_pipeline")


def render_prompts() -> dict:
    """Every stage prompt, path-normalised exactly as the golden capture was."""
    P = pipeline_module()
    prof = P.load_venue_profile("generic")
    sb = (WS / "tmp" / "render-sandbox" / "r1_guided_review").resolve()
    import shutil
    shutil.rmtree(sb, ignore_errors=True)
    (sb / "base").mkdir(parents=True)
    (sb / "base" / "manuscript.md").write_text("# m\n\ntext.\n", encoding="utf-8")
    out = {
        "review": P.review_prompt(sb, "r1_guided_review", 1, venue=prof, scope="full"),
        "review_split_a": P.review_prompt(sb, "r1_guided_review", 1, venue=prof, split="a"),
        "review_scoped": P.review_prompt(sb, "r1_guided_review", 1, venue=prof,
                                         scope="formatting-writing"),
        "cold_start_review": P.cold_start_review_prompt(sb, "r1_cold_start_review", 1, venue=prof),
        "audit": P.audit_prompt(sb, "r1_audit", 1, venue=prof),
        "revise": P.revise_prompt(sb, "r1_a2_revise", 1, venue=prof, audit=True),
        "integrate": P.integrate_prompt(sb, "r1_i1", 1, "v1", ["v2", "v3"], venue=prof),
        "rewrite": P.rewrite_prompt(sb, "r1_w1", 1, venue=prof),
        "judge": P.judge_prompt(sb, "judge_x_j1", 1, "v1", 1, 2, [], venue=prof),
        "revision_audit": P.revision_audit_prompt(sb, "r1_revision_audit", 1),
        "revision_repair": P.revision_repair_prompt(sb, "r1_repair", 1, 3),
    }
    # The sandbox path first (it lives UNDER the checkout), then the checkout,
    # exactly the normalisation the golden capture used.
    return {name: t.replace(str(sb), "<SANDBOX>").replace(str(WS.resolve()), "<CHECKOUT>")
            for name, t in out.items()}


def test_high_profile_is_the_old_pipeline() -> None:
    """`high` renders the pre-profile prompts, byte for byte."""
    texts = render_prompts()
    bad = []
    for name, want in GOLDEN.items():
        got = hashlib.sha256(texts[name].encode()).hexdigest()[:16]
        if got != want:
            bad.append(f"{name} {got} != {want}")
    check("high: the 11 stage prompts match the frozen shell golden",
          not bad, "; ".join(bad[:4]))
    check("high: no prompt carries the medium contract or a paged-rule pointer",
          not any("EXECUTION PROFILE: medium" in t or "[PROFILE RULES" in t
                  for t in texts.values()))


def test_medium_profile_pages_the_elaborations() -> None:
    """`medium` is materially smaller, ships the paged rules, states the contract."""
    P = pipeline_module()
    prof = P.load_venue_profile("generic")
    sb = (WS / "tmp" / "render-sandbox" / "r2_guided_review").resolve()
    import shutil
    shutil.rmtree(sb, ignore_errors=True)
    (sb / "base").mkdir(parents=True)
    calls = {
        "review": lambda p: P.review_prompt(sb, "r1_guided_review", 1, venue=prof, execution_profile=p),
        "cold_start_review": lambda p: P.cold_start_review_prompt(sb, "r1_cold_start_review", 1, venue=prof, execution_profile=p),
        "audit": lambda p: P.audit_prompt(sb, "r1_audit", 1, venue=prof, execution_profile=p),
        "revise": lambda p: P.revise_prompt(sb, "r1_a2_revise", 1, venue=prof, execution_profile=p),
        "integrate": lambda p: P.integrate_prompt(sb, "r1_i1", 1, "v1", ["v2"], venue=prof,
                                                  execution_profile=p),
        "rewrite": lambda p: P.rewrite_prompt(sb, "r1_w1", 1, venue=prof, execution_profile=p),
        "judge": lambda p: P.judge_prompt(sb, "judge_x_j1", 1, "v1", 1, 2, [], venue=prof,
                                          execution_profile=p),
    }
    ratios = {}
    for name, fn in calls.items():
        high, medium = fn("high"), fn("medium")
        ratios[name] = len(medium) / max(1, len(high))
    worst = max(ratios.items(), key=lambda kv: kv[1])
    check("medium: every stage prompt is at most 75% of the high prompt",
          worst[1] <= 0.75, f"largest ratio {worst[0]}={worst[1]:.2f}")
    review = calls["review"]("medium")
    check("medium: the capacity contract is the first thing in the prompt",
          review.lstrip().startswith("=== EXECUTION PROFILE: medium"))
    check("medium: the contract still binds the postchecks and the deliverables",
          "THE POSTCHECKS ARE UNCHANGED" in review and "_pipeline_done.json" in review)
    rules = sb / "INSTRUCTIONS" / "PROFILE_RULES.md"
    check("medium: the paged rule text really ships in the sandbox", rules.is_file())
    check("medium: the paged file is substantial (the rules were moved, not dropped)",
          rules.is_file() and rules.stat().st_size > 10_000,
          f"{rules.stat().st_size if rules.is_file() else 0} bytes")
    body = rules.read_text(encoding="utf-8") if rules.is_file() else ""
    check("medium: the paged file states the bounded-read policy and the headings",
          "READ POLICY" in body and "\n## " in body)
    check("medium: the pointer names the file it points at",
          "INSTRUCTIONS/PROFILE_RULES.md" in review)
    # The paging must not be a no-op: the pointers replaced real text.
    check("medium: the prompt carries PROFILE RULES pointers", "[PROFILE RULES —" in review)


def test_config_records_the_policy() -> None:
    """A default root records nothing new; an opted-in root records the policy."""
    tmp = Path(tempfile.mkdtemp())
    src = make_source(tmp)
    default_root, med_root, off_root = tmp / "default", tmp / "medium", tmp / "off"
    for root, extra in ((default_root, []), (med_root, ["--execution-profile", "medium"]),
                        (off_root, ["--no-guided-review"])):
        proc = cli("setup", "--source", str(src), "--root", str(root),
                   "--venue", "generic", *extra)
        check(f"setup succeeds: {' '.join(extra) or 'default'}", proc.returncode == 0,
              (proc.stderr or proc.stdout)[-300:])
    cfg = json.loads((default_root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("high/default: pipeline_config.json carries no execution_profile key",
          "execution_profile" not in cfg)
    check("high/default: pipeline_config.json carries no guided_review key",
          "guided_review" not in cfg)
    med = json.loads((med_root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("medium: the profile is recorded in pipeline_config.json",
          med.get("execution_profile") == "medium")
    off = json.loads((off_root / "pipeline_config.json").read_text(encoding="utf-8"))
    check("no-guided-review: the policy is recorded", off.get("guided_review") == "off")
    check("no-guided-review: the NAMED GAP is recorded with it",
          "M1-M36" in str(off.get("guided_review_gap"))
          and "UNREVIEWED" in str(off.get("guided_review_gap")))
    # The policy must survive into the root's own config mirror.
    P = pipeline_module()
    ctx = P.Ctx(off_root)
    ctx.load()
    check("no-guided-review: the loaded root reports the policy",
          P.guided_review_of(ctx) == "off")
    medctx = P.Ctx(med_root)
    medctx.load()
    check("medium: the loaded root reports its profile",
          P.execution_profile_of(medctx) == "medium")
    check("high: a root without the key reads as high",
          P.execution_profile_of(P.Ctx(default_root)) == "high")


def test_plan_drops_the_guided_review() -> None:
    """`--no-guided-review` plans no review run and keeps the probe."""
    tmp = Path(tempfile.mkdtemp())
    src = make_source(tmp)
    root = tmp / "off"
    proc = cli("setup", "--source", str(src), "--root", str(root), "--venue", "generic",
               "--rounds", "2", "--rewrites", "0", "--revises", "1", "--no-guided-review")
    check("setup: --no-guided-review root is built", proc.returncode == 0,
          (proc.stderr or proc.stdout)[-300:])
    P = pipeline_module()
    ctx = P.Ctx(root)
    ctx.load()
    ids = [e["id"] for e in P.round_run_plan(ctx, 1)]
    check("plan: no r1_guided_review session is planned", "r1_guided_review" not in ids, str(ids))
    check("plan: no split review session is planned", "r1_guided_review_b" not in ids, str(ids))
    check("plan: the probe IS planned", "r1_cold_start_review" in ids, str(ids))
    deps = {e["id"]: e["deps"] for e in P.round_run_plan(ctx, 1)}
    check("plan: the auditor consumes the probe", "r1_cold_start_review" in deps.get("r1_audit", []),
          str(deps.get("r1_audit")))
    check("plan: the reviser consumes the probe, never a review",
          "r1_cold_start_review" in deps.get("r1_a2_revise", [])
          and "r1_guided_review" not in deps.get("r1_a2_revise", []),
          str(deps.get("r1_a2_revise")))
    # The default root still plans the guided review.
    on_root = tmp / "on"
    cli("setup", "--source", str(src), "--root", str(on_root), "--venue", "generic",
        "--rounds", "1", "--rewrites", "0", "--revises", "1")
    on_ctx = P.Ctx(on_root)
    on_ctx.load()
    on_ids = [e["id"] for e in P.round_run_plan(on_ctx, 1)]
    check("plan: a default root still plans r1_guided_review + r1_cold_start_review",
          "r1_guided_review" in on_ids and "r1_cold_start_review" in on_ids, str(on_ids))


def test_setup_refuses_a_round_with_no_finding_source() -> None:
    """Every combination that would leave the round with nothing is refused."""
    tmp = Path(tempfile.mkdtemp())
    src = make_source(tmp)
    cases = {
        "probe off": ["--no-guided-review", "--no-cold-start-review"],
        "review split": ["--no-guided-review", "--review-split", "phases"],
        "scoped mode": ["--no-guided-review", "--revision-mode", "major"],
        "polish scope": ["--no-guided-review", "--review-scope", "formatting-writing"],
        "decision letter": ["--no-guided-review", "--revision-mode", "resubmit"],
    }
    for name, extra in cases.items():
        root = tmp / ("r-" + name.replace(" ", "-"))
        proc = cli("setup", "--source", str(src), "--root", str(root),
                   "--venue", "generic", *extra)
        check(f"setup refuses --no-guided-review with {name}",
              proc.returncode != 0 and "--no-guided-review" in (proc.stderr + proc.stdout),
              (proc.stderr or proc.stdout)[-200:])


def test_end_to_end_without_guided_review() -> None:
    """A full stub round runs on the probe alone and records the gap everywhere."""
    tmp = Path(tempfile.mkdtemp())
    src = make_source(tmp)
    root = tmp / "root"
    proc = cli("setup", "--source", str(src), "--root", str(root), "--venue", "generic",
               "--rounds", "1", "--rewrites", "0", "--revises", "1", "--judges", "1",
               "--no-guided-review")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    proc = cli("run", "--root", str(root),
               "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
               "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
               "--retries", "1", "--jobs", "1", timeout=1800)
    check("e2e: the round completes on the probe alone", proc.returncode == 0,
          (proc.stderr or proc.stdout)[-600:])
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    runs = state.get("runs") or {}
    kinds = [rec.get("kind") for rec in runs.values()]
    check("e2e: no review run was recorded", "review" not in kinds, str(sorted(set(kinds))))
    check("e2e: the cold-start review, audit and revise runs exist",
          {"cold_start_review", "audit", "revise"} <= set(kinds), str(sorted(set(kinds))))
    for sandbox in sorted(root.glob("runs/*")):
        rel = sandbox / "guided_review" / "findings.json"
        if sandbox.name in ("r1_audit", "r1_a2_revise"):
            check(f"e2e: {sandbox.name} received the synthesized frozen review", rel.is_file())
            if rel.is_file():
                doc = json.loads(rel.read_text(encoding="utf-8"))
                check(f"e2e: {sandbox.name}'s frozen review records the NAMED GAP",
                      doc.get("guided_review") == "off"
                      and "UNREVIEWED" in str(doc.get("named_gap"))
                      and all("unable" in str(row.get("disposition"))
                              for row in doc.get("coverage") or []))
                extra = sandbox / "guided_review" / "round2" / "findings_extra.json"
                check(f"e2e: {sandbox.name}'s discovery list names the probe as its source",
                      extra.is_file()
                      and json.loads(extra.read_text(encoding="utf-8")).get("source")
                      == "cold_start_review")
    check("e2e: the audit prompt states that no guided review ran",
          "NO GUIDED REVIEW" in (root / "runs" / "r1_audit" / "PROMPT.md")
          .read_text(encoding="utf-8"))
    check("e2e: the revise prompt states that no guided review ran",
          "NO GUIDED REVIEW" in (root / "runs" / "r1_a2_revise" / "PROMPT.md")
          .read_text(encoding="utf-8"))
    check("e2e: the probe prompt makes it the round's only coverage",
          "ONLY COVERAGE" in (root / "runs" / "r1_cold_start_review" / "PROMPT.md").read_text(encoding="utf-8"))


def test_medium_end_to_end() -> None:
    """A medium root writes the paged rules beside every stage prompt."""
    tmp = Path(tempfile.mkdtemp())
    src = make_source(tmp)
    root = tmp / "root"
    proc = cli("setup", "--source", str(src), "--root", str(root), "--venue", "generic",
               "--rounds", "1", "--rewrites", "0", "--revises", "1", "--judges", "1",
               "--execution-profile", "medium")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    proc = cli("run", "--root", str(root),
               "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
               "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
               "--retries", "1", "--jobs", "1", timeout=1800)
    check("e2e/medium: the round completes", proc.returncode == 0,
          (proc.stderr or proc.stdout)[-600:])
    prompts = list(root.glob("runs/*/PROMPT.md"))
    check("e2e/medium: stage prompts were written", len(prompts) >= 4, str(len(prompts)))
    missing = [p.parent.name for p in prompts
               if not (p.parent / "INSTRUCTIONS" / "PROFILE_RULES.md").is_file()]
    check("e2e/medium: every stage sandbox carries the paged rules", not missing, str(missing))
    small = [p.parent.name for p in prompts
             if "EXECUTION PROFILE: medium" not in p.read_text(encoding="utf-8")]
    check("e2e/medium: every stage prompt states the medium profile", not small, str(small))


if __name__ == "__main__":
    test_high_profile_is_the_old_pipeline()
    test_medium_profile_pages_the_elaborations()
    test_config_records_the_policy()
    test_plan_drops_the_guided_review()
    test_setup_refuses_a_round_with_no_finding_source()
    test_end_to_end_without_guided_review()
    test_medium_end_to_end()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
        sys.exit(1)
    print("EXECUTION PROFILE + GUIDED REVIEW: ALL CHECKS PASSED")

#!/usr/bin/env python3
"""`--strict-artifacts fix`: the scoped ARTIFACT-REPAIR session — red on the pre-fix tree.

The reported problem: an artifact-quality failure (a seeded decision table left
empty or closed with one blanket sentence) cost a FULL re-run of the stage — the
2026-09-22 root paid 26 minutes and produced a different 102-finding review to
fix one disposition column. `fix` spends one bounded session on the failed
attempt's tables instead, and the mode is defined by what that session may NOT
do, because the layer it repairs exists precisely because an LLM once closed 96
rows with one sentence:

  A. policy      `--strict-artifacts [on|fix|off]` (+ `--fix-artifacts` /
                 `--non-strict-artifacts`), the legacy boolean in an old root's
                 config, and `strict_dispositions`/`artifact_repair_enabled`.
  B. scope       ONLY a review whose every postcheck error is an artifact-quality
                 message is repairable; one other error, the wrong policy, the
                 wrong stage, or an attempt already repaired is not.
  C. guard       the repair's three scopes: `review/work/` scratch is free, the
                 decision tables are cell-editable but their ROWS are identity
                 (no add/delete/reorder/re-word), and everything else --
                 findings.json/md, round2/, the other artifact files, the
                 prompt, the marker -- is byte-identical.
  D. prompt      names the problems, the writable scope, the disposition rule
                 and the `unable — manual verification required` escape; carries
                 no unresolved `@@TOKEN@@`.
  E. end to end  with a stub agent: attempt 1 fails on the seeded tables, ONE
                 repair session clears them and the run is done with the repair
                 recorded; a repair that clears nothing fails like any other
                 attempt; a repair that edits findings.json, drops a seeded row
                 or rewrites a non-decision artifact is REJECTED by the guard;
                 `on` never starts a repair, `off` records the report as a
                 warning and completes.

Run:  python3 .nbt_test/test_artifact_repair.py
`NBT_WS` retargets the suite at another copy of the tree.
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

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
HERE = Path(__file__).resolve().parent
STUB_REPAIR = HERE / "stub_repair_agent.py"
spec = importlib.util.spec_from_file_location("nbt_rep", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_rep"] = nb
spec.loader.exec_module(nb)

FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(p)
    return p


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fake_ctx(policy: str):
    ctx = nb.Ctx(Path("/tmp/x"))
    ctx.cfg = {"artifact_policy": policy}
    return ctx


def ctx_of(root: Path):
    """A Ctx over a finished stub root (config + state loaded from disk)."""
    ctx = nb.Ctx(root)
    ctx.cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    ctx.state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    return ctx


print("== A. the policy is three-valued (and readable from an old root) ==")
check("A1 the default policy is `on`",
      nb.artifact_policy_of(fake_ctx(nb.DEFAULT_ARTIFACT_POLICY)) == "on")
check("A2 `fix` is its own policy and implies strict dispositions",
      nb.artifact_policy_of(fake_ctx("fix")) == "fix"
      and nb.strict_dispositions(fake_ctx("fix")) and nb.artifact_repair_enabled(fake_ctx("fix")))
check("A3 `off` is advisory for the gate and never repairs",
      not nb.strict_dispositions(fake_ctx("off"))
      and not nb.artifact_repair_enabled(fake_ctx("off")))
for raw, want in (("fail", "on"), ("strict", "on"), ("repair", "fix"), ("auto", "fix"),
                  ("warn", "off"), ("advisory", "off")):
    check(f"A4 the alias {raw!r} resolves to {want!r}",
          nb.artifact_policy_of(fake_ctx(raw)) == want)
legacy_on = nb.Ctx(Path("/tmp/x")); legacy_on.cfg = {"strict_artifacts": True}
legacy_off = nb.Ctx(Path("/tmp/x")); legacy_off.cfg = {"strict_dispositions": False}
empty = nb.Ctx(Path("/tmp/x")); empty.cfg = {}
check("A5 an old root's boolean config is read as on/off",
      nb.artifact_policy_of(legacy_on) == "on" and nb.artifact_policy_of(legacy_off) == "off"
      and nb.artifact_policy_of(empty) == "on")


def setup_root(tmp: Path, policy: str = None, *, rounds: int = 1, judges: str = "1",
               rewrites: str = "1", revises: str = "1", audit: str = None,
               integrators: str = None) -> Path:
    source = tmp / "source"
    (source / "raw_figs").mkdir(parents=True)
    write(source / "manuscript-b.md", "title\n")
    write(source / "raw_figs" / "data.tsv", "a\tb\n")
    root = tmp / "root"
    cmd = [sys.executable, str(WS / "nbt_pipeline.py"), "setup", "--source", str(source),
           "--root", str(root), "--rounds", str(rounds), "--judges", str(judges),
           "--rewrites", str(rewrites), "--revises", str(revises)]
    if audit is not None:
        cmd += ["--audit", audit]
    if integrators is not None:
        cmd += ["--integrators", integrators]
    if policy:
        cmd += ["--strict-artifacts", policy]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return root


cfg_root = setup_root(scratch("nbt_rep_cfg_"), "fix")
cfg = json.loads((cfg_root / "pipeline_config.json").read_text(encoding="utf-8"))
check("A6 `setup --strict-artifacts fix` records the policy AND the legacy boolean",
      cfg.get("artifact_policy") == "fix" and cfg.get("strict_artifacts") is True,
      json.dumps({k: cfg.get(k) for k in ("artifact_policy", "strict_artifacts")}))
cfg_off = json.loads((setup_root(scratch("nbt_rep_cfg2_"), "off") / "pipeline_config.json")
                     .read_text(encoding="utf-8"))
check("A7 `--strict-artifacts off` records off/false",
      cfg_off.get("artifact_policy") == "off" and cfg_off.get("strict_artifacts") is False)
cfg_bare = json.loads((setup_root(scratch("nbt_rep_cfg3_")) / "pipeline_config.json")
                      .read_text(encoding="utf-8"))
check("A8 a bare `--strict-artifacts` (and the default) means on",
      cfg_bare.get("artifact_policy") == "on")

print()
print("== B. every stage has a repair profile; content failures never do ==")
ART_PROBLEM = ("decision artifact artifacts/OUTLINE.md: 1 of 1 OUTLINE rows carry no summary "
               "(the hierarchy pass cannot be audited)")


def rec_of(kind: str, errors: list, **extra):
    rec = {"id": f"r1_{kind}", "kind": kind, "round": 1, "attempts_done": 1,
           "postcheck": {"ok": False, "errors": list(errors), "warnings": []}}
    rec.update(extra)
    return rec


# One representative BOOKKEEPING problem per stage -- the class the repair exists
# for -- plus one CONTENT problem per stage that must stay a plain failure.
REPAIRABLE = {
    "review": [ART_PROBLEM],
    "audit": ["3 frozen finding id(s) are neither confirmed nor dropped (silence is not a "
              "disposition): F-004, F-005, F-006"],
    "rewrite": ["rewritten/REWRITE_REPORT.md is missing: it is this stage's ledger (the "
                "organization map, what was deliberately left unchanged, and the problems the "
                "rewrite surfaced -- the feedback/reference deliverable for later stages and "
                "the author)"],
    "revise": ["revised/revision_report.json does not name 2 of the frozen review's 5 finding "
               "id(s): F-002, F-004 -- the ledger is one row per finding id (the deliverable "
               "that proves no finding was silently dropped); an id must appear as structured "
               "data (a row's id field, a mapping key or an id list), not only in prose"],
    "integrate": ["integrated/DIFF_LEDGER.md is missing: it is this stage's ledger (one row per "
                  "ported or deliberately skipped difference, with the hierarchy-based "
                  "justification, covering EVERY donor)"],
    "judge": ["comparisons[0] has no `checks` coverage map; contract v3 requires one "
              "disposition per frozen check id for EVERY opponent (M1, M2, ...)"],
}
NOT_REPAIRABLE = {
    "review": ["review/artifacts/M1_acronyms.md lists 25 M1b long-form row(s) ... but "
               "review/findings.json raises no M1 finding"],
    "audit": ["review/ was modified after the sandbox was built"],
    "rewrite": ["rewritten/ is missing or empty (the full rewritten candidate is this stage's "
                "deliverable; a non-empty rewritten/ is required, though it is not by itself a "
                "completion signal)"],
    "revise": ["revised/ is missing or empty (a non-empty revised/ is required, though it is "
               "not by itself a completion signal)"],
    "integrate": ["others/ is missing: this run consumes the WHOLE candidate pool"],
    "judge": ["comparisons omit 2 issued label(s): ['v1', 'v3'] (the prompt requires exactly "
              "one entry per issued opponent label)"],
}
for kind, errs in sorted(REPAIRABLE.items()):
    check(f"B-{kind}: its bookkeeping problem is repairable under `fix`",
          nb.repairable_artifact_failure(fake_ctx("fix"), rec_of(kind, errs)) == errs,
          str(nb.repairable_artifact_failure(fake_ctx("fix"), rec_of(kind, errs)))[:120])
for kind, errs in sorted(NOT_REPAIRABLE.items()):
    check(f"B-{kind}: a content/contract failure is NOT repairable",
          nb.repairable_artifact_failure(fake_ctx("fix"), rec_of(kind, errs)) == [],
          str(errs)[:120])
check("B1 a MIXED failure is not repairable (one unrepairable error blocks the repair)",
      nb.repairable_artifact_failure(
          fake_ctx("fix"), rec_of("revise", REPAIRABLE["revise"] + NOT_REPAIRABLE["revise"])) == [])
check("B2 policy `on`/`off` never repair",
      nb.repairable_artifact_failure(fake_ctx("on"), rec_of("audit", REPAIRABLE["audit"])) == []
      and nb.repairable_artifact_failure(fake_ctx("off"),
                                         rec_of("audit", REPAIRABLE["audit"])) == [])
check("B3 a stage with no profile (the a1 base copy) is never repair-scheduled",
      nb.repairable_artifact_failure(fake_ctx("fix"), rec_of("a1", ["anything"])) == [])
check("B4 an attempt that already had its repair is not repaired again",
      nb.repairable_artifact_failure(
          fake_ctx("fix"), rec_of("judge", REPAIRABLE["judge"], repair_attempts=[1])) == [])
check("B5 a clean attempt has nothing to repair",
      nb.repairable_artifact_failure(fake_ctx("fix"),
                                     rec_of("judge", [], postcheck={"ok": True, "errors": []}))
      == [])

print()
print("== C. the guard: byte-identical outside the scope, evidence pinned inside ==")


def fake_rec(kind: str) -> dict:
    return {"id": f"r1_{kind}", "kind": kind, "round": 1, "attempts_done": 1,
            "sandbox": f"runs/r1_{kind}"}


# --- review: the decision tables (cells editable, rows are identity) ---------
sb = scratch("nbt_rep_guard_") / "r1_review"
write(sb / "PROMPT.md", "stage prompt\n")
write(sb / "base" / "manuscript-b.md", "title\n")
write(sb / "review" / "findings.json", json.dumps({"findings": []}))
write(sb / "review" / "round2" / "new_sweeps.md", "# none\n")
write(sb / "review" / "work" / "notes.md", "scratch\n")
write(sb / "review" / "artifacts" / "M1_acronyms.md",
      "| acronym | context | disposition |\n|---|---|---|\n| CN | main text | OK — rule M1(k) |\n")
OUTLINE = ("| # | document | heading | paragraph | summary | disposition |\n|---|---|---|---|---|---|\n"
           "| 1 | d.docx | Intro | 0 | claim one |  |\n"
           "| 2 | d.docx | Intro | 1 | claim two |  |\n")
write(sb / "review" / "artifacts" / "OUTLINE.md", OUTLINE)
rec_review = fake_rec("review")
guard = nb.snapshot_repair_guard(sb, rec_review)
check("C1 the snapshot covers the protected files and every decision table",
      "review/findings.json" in guard["files"]
      and "review/artifacts/M1_acronyms.md" in guard["files"]
      and "PROMPT.md" in guard["files"]
      and "review/work/notes.md" not in guard["files"]
      and "base/manuscript-b.md" not in guard["files"]
      and len(guard["tables"]["artifacts/OUTLINE.md"]) == 2,
      str(sorted(guard["files"]))[:200])

write(sb / "review" / "artifacts" / "OUTLINE.md",
      OUTLINE.replace("| claim one |  |", "| the introduction | OK — one topic |")
            .replace("| claim two |  |",
                     "| the introduction | unable — manual verification required: the author "
                     "must confirm the second claim |"))
write(sb / "review" / "work" / "fill.py", "print('scratch')\n")
write(sb / "review" / "artifacts" / "REPAIR_NOTES.md", "what I filled\n")
check("C2 filling judged cells (summary + disposition), scratch and a NEW artifact file are in scope",
      nb.repair_guard_problems(sb, guard, rec_review) == [],
      str(nb.repair_guard_problems(sb, guard, rec_review)))

write(sb / "review" / "artifacts" / "OUTLINE.md", OUTLINE.replace("Intro", "Introduction"))
problems = nb.repair_guard_problems(sb, guard, rec_review)
check("C3 re-wording a row's own evidence is rejected",
      any("rewrote the seeded rows of review/artifacts/OUTLINE.md" in p for p in problems),
      str(problems)[:200])

write(sb / "review" / "artifacts" / "OUTLINE.md", "\n".join(OUTLINE.splitlines()[:3]) + "\n")
problems = nb.repair_guard_problems(sb, guard, rec_review)
check("C4 deleting a seeded row is rejected",
      any("a row was deleted, added or reordered" in p for p in problems), str(problems)[:200])
write(sb / "review" / "artifacts" / "OUTLINE.md", OUTLINE)

dirty = json.loads((sb / "review" / "findings.json").read_text(encoding="utf-8"))
dirty["findings"].append({"id": "F-999"})
write(sb / "review" / "findings.json", json.dumps(dirty))
write(sb / "review" / "artifacts" / "M1_acronyms.md", "| acronym |\n|---|\n| CN |\n")
write(sb / "PROMPT.md", "rewritten\n")
problems = nb.repair_guard_problems(sb, guard, rec_review)
check("C5 editing the finding list, a non-decision artifact or the prompt is rejected",
      any("MODIFIED review/findings.json" in p for p in problems)
      and any("MODIFIED review/artifacts/M1_acronyms.md" in p for p in problems)
      and any("MODIFIED PROMPT.md" in p for p in problems), str(problems)[:240])
write(sb / "review" / "findings.json", json.dumps({"findings": []}))
write(sb / "review" / "artifacts" / "M1_acronyms.md",
      "| acronym | context | disposition |\n|---|---|---|\n| CN | main text | OK — rule M1(k) |\n")
write(sb / "PROMPT.md", "stage prompt\n")
check("C6 the fixture is back in scope after C5",
      nb.repair_guard_problems(sb, guard, rec_review) == [],
      str(nb.repair_guard_problems(sb, guard, rec_review))[:200])
write(sb / "review" / "round2" / "sneaky.md", "x\n")
check("C7 a file CREATED outside the writable scope is rejected",
      any("CREATED review/round2/sneaky.md" in p
          for p in nb.repair_guard_problems(sb, guard, rec_review)),
      str(nb.repair_guard_problems(sb, guard, rec_review))[:200])

# --- audit: existing dispositions stand, only `confirm` may be added ---------
sb_a = scratch("nbt_rep_audit_") / "r1_audit"
write(sb_a / "review" / "findings.json", json.dumps({"findings": [{"id": "F-001"}]}))
AUDIT = {"dispositions": [{"id": "F-001", "verdict": "drop", "reason": "x" * 30,
                           "evidence": "y" * 50}],
         "adds": [{"id": "AU-1"}]}
write(sb_a / "audit" / "audit.json", json.dumps(AUDIT))
rec_audit = fake_rec("audit")
guard_a = nb.snapshot_repair_guard(sb_a, rec_audit)
AUDIT_FIXED = {"dispositions": [{"id": "F-001", "verdict": "drop", "reason": "x" * 30,
                                 "evidence": "y" * 50},
                                {"id": "F-002", "verdict": "confirm",
                                 "reason": "frozen finding F-001's own text", "evidence": "z" * 50}],
               "adds": [{"id": "AU-1"}]}
write(sb_a / "audit" / "audit.json", json.dumps(AUDIT_FIXED))
check("C8 an added `confirm` row (and an untouched drop) is in scope",
      nb.repair_guard_problems(sb_a, guard_a, rec_audit) == [],
      str(nb.repair_guard_problems(sb_a, guard_a, rec_audit)))
AUDIT_BAD = dict(AUDIT_FIXED, dispositions=[
    dict(AUDIT_FIXED["dispositions"][0], verdict="confirm"),
    dict(AUDIT_FIXED["dispositions"][1], verdict="drop", reason="too short")])
write(sb_a / "audit" / "audit.json", json.dumps(AUDIT_BAD))
problems = nb.repair_guard_problems(sb_a, guard_a, rec_audit)
check("C9 rewriting an existing disposition and adding a new `drop` are rejected",
      any("rewrote the existing disposition of F-001" in p for p in problems)
      and any("it added a 'drop' disposition for F-002" in p for p in problems),
      str(problems)[:240])
write(sb_a / "audit" / "audit.json", json.dumps(
    dict(AUDIT_FIXED, adds=[{"id": "AU-1"}, {"id": "AU-2"}])))
check("C10 inventing an `AU-` finding is rejected",
      any("it invented finding(s) AU-2" in p
          for p in nb.repair_guard_problems(sb_a, guard_a, rec_audit)),
      str(nb.repair_guard_problems(sb_a, guard_a, rec_audit))[:200])
write(sb_a / "audit" / "audit.json", json.dumps(AUDIT_FIXED))

# --- judge: the ledger is the judgement, the integer is derived --------------
sb_j = scratch("nbt_rep_judge_") / "judge_tok_j1"
SHEET = {"run_id": "judge_tok_j1", "target_id": "tok", "judge_index": 1,
         "comparisons": [
             {"opponent_label": "v1", "score": 2, "basis": "correctness",
              "resolved": [{"tier": "correctness", "severity": "Major", "evidence": "e"}],
              "introduced": [], "checks": {"M1": "clean — nothing to flag"}},
             {"opponent_label": "v2", "score": 0, "basis": "none",
              "resolved": [], "introduced": [], "checks": {"M1": "unable — not read"}}]}
write(sb_j / "scores.json", json.dumps(SHEET))
write(sb_j / "target" / "ms.md", "target\n")
rec_judge = fake_rec("judge")
guard_j = nb.snapshot_repair_guard(sb_j, rec_judge)
FIXED = json.loads(json.dumps(SHEET))
FIXED["comparisons"][0]["checks"]["M2"] = "unable — the repair did not examine M2"
FIXED["comparisons"][0]["score"] = 3          # recomputed from the ledger
write(sb_j / "scores.json", json.dumps(FIXED))
check("C11 adding an `unable` coverage entry and recomputing the integer are in scope",
      nb.repair_guard_problems(sb_j, guard_j, rec_judge) == [],
      str(nb.repair_guard_problems(sb_j, guard_j, rec_judge)))
BAD = json.loads(json.dumps(FIXED))
BAD["comparisons"][0]["checks"]["M1"] = "clean — rewritten by the repair"
BAD["comparisons"][0]["resolved"] = []
BAD["comparisons"][0]["checks"]["M3"] = "clean — invented coverage"
write(sb_j / "scores.json", json.dumps(BAD))
problems = nb.repair_guard_problems(sb_j, guard_j, rec_judge)
check("C12 rewriting the ledger, an existing coverage entry or adding `clean` are rejected",
      any("rewrote v1's resolved/introduced ledger" in p for p in problems)
      and any("rewrote v1's existing `checks[M1]`" in p for p in problems)
      and any("only add `unable` coverage" in p for p in problems),
      str(problems)[:300])
BAD2 = json.loads(json.dumps(FIXED))
BAD2["comparisons"] = [c for c in BAD2["comparisons"] if c["opponent_label"] != "v2"]
write(sb_j / "scores.json", json.dumps(BAD2))
check("C13 removing a comparison is rejected (every issued label keeps its row)",
      any("it removed the comparison(s) v2" in p
          for p in nb.repair_guard_problems(sb_j, guard_j, rec_judge)),
      str(nb.repair_guard_problems(sb_j, guard_j, rec_judge))[:200])
write(sb_j / "scores.json", json.dumps(FIXED))

# --- the package stages: bookkeeping yes, the manuscript no ------------------
sb_r = scratch("nbt_rep_revise_") / "r1_a2_revise"
write(sb_r / "revised" / "manuscript-b.docx", "PK-docx-bytes")
write(sb_r / "revised" / "REVISION_REPORT.md", "# report\n")
write(sb_r / "revised" / "work" / "R6_language.md", "| step |\n|---|\n")
write(sb_r / "review" / "findings.json", json.dumps({"findings": []}))
rec_rev = fake_rec("revise")
guard_r = nb.snapshot_repair_guard(sb_r, rec_rev)
write(sb_r / "revised" / "revision_report.json", json.dumps([{"id": "F-001"}]))
write(sb_r / "revised" / "work" / "notes.md", "scratch\n")
check("C14 the package's bookkeeping + work/ scratch are in scope",
      nb.repair_guard_problems(sb_r, guard_r, rec_rev) == [],
      str(nb.repair_guard_problems(sb_r, guard_r, rec_rev)))
write(sb_r / "revised" / "manuscript-b.docx", "EDITED manuscript bytes")
problems = nb.repair_guard_problems(sb_r, guard_r, rec_rev)
check("C15 editing a manuscript file inside the package is rejected",
      any("MODIFIED revised/manuscript-b.docx" in p for p in problems), str(problems)[:200])
write(sb_r / "revised" / "manuscript-b.docx", "PK-docx-bytes")
write(sb_r / "review" / "findings.json", json.dumps({"findings": [{"id": "F-1"}]}))
check("C16 editing the frozen review is rejected for a package stage",
      any("MODIFIED review/findings.json" in p
          for p in nb.repair_guard_problems(sb_r, guard_r, rec_rev)),
      str(nb.repair_guard_problems(sb_r, guard_r, rec_rev))[:200])

print()
print("== D. the repair prompt, per stage ==")
ART_REVIEW = "review/artifacts/OUTLINE.md"
prompt_cases = {
    "review": (sb, ART_PROBLEM, ["THE TABLES IN PLAY", "Never close many rows with the same "
                                "sentence"]),
    "audit": (sb_a, REPAIRABLE["audit"][0], ["ONLY add a `confirm` row", "audit/audit.json",
                                             "may NOT create, widen"]),
    "rewrite": (sb_r, REPAIRABLE["rewrite"][0], ["REWRITE_REPORT.md", "visual record",
                                                 "manuscript"]),
    "revise": (sb_r, REPAIRABLE["revise"][0], ["revision_report.json", "R6_language.md",
                                               "VISUAL_CHECK.md"]),
    "integrate": (sb_r, REPAIRABLE["integrate"][0], ["DIFF_LEDGER.md", "donor", "size class"]),
    "judge": (sb_j, REPAIRABLE["judge"][0], ["resolved/introduced", "`unable — <why>`",
                                             "judge_review/"]),
}
for kind, (sandbox, problem, needles) in sorted(prompt_cases.items()):
    ctx = nb.Ctx(sandbox.parent)
    ctx.cfg = {"artifact_policy": "fix"}
    text = nb.repair_prompt(ctx, {"id": f"r1_{kind}", "kind": kind, "round": 1,
                                  "attempts_done": 1, "sandbox": sandbox.name}, [problem])
    missing = [n for n in needles if n not in text]
    check(f"D-{kind}: the prompt names the stage, the problem and its own rules",
          not missing and problem in text and f"stage {kind}" in text and "@@" not in text,
          f"missing={missing}")
    check(f"D-{kind}: it demands the honest escape and the same postcheck",
          "unable — manual verification required" in text
          and "re-runs the SAME postcheck" in text)
print("== E. end to end with a stub repairer ==")


def run_review(tmp: Path, policy: str, env_extra: dict = None):
    root = setup_root(tmp, policy)
    env = dict(os.environ)
    env["NBT_REPAIR_STUB_BAD"] = "r1_review"
    env.update(env_extra or {})
    proc = subprocess.run([sys.executable, str(root / "nbt_pipeline.py"), "run",
                           "--root", str(root), "--only", "review", "--retries", "0",
                           "--retry-backoff", "0", "--agent-cmd",
                           json.dumps([sys.executable, str(STUB_REPAIR)])],
                          capture_output=True, text=True, timeout=900, env=env)
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    return root, proc, state["runs"]["r1_review"]


root_fix, proc_fix, rec_fix = run_review(scratch("nbt_rep_e2e_fix_"), "fix")
repairs = rec_fix.get("repairs") or []
check("E1 the failed attempt went to exactly ONE repair session",
      len(repairs) == 1 and repairs[0]["attempt"] == 2,
      json.dumps([(r.get("attempt"), r.get("ok")) for r in repairs]))
check("E2 the repair cleared the problems and the run is done",
      rec_fix["status"] == "done" and repairs and repairs[0]["ok"] is True,
      str(rec_fix.get("status")))
check("E3 the repair's own attempt is in the history as `artifact-repair`",
      [(e["attempt"], e["source"], e["ok"]) for e in rec_fix["attempts_log"]]
      == [(1, "postcheck", False), (2, "artifact-repair", True)],
      str([(e["attempt"], e["source"], e["ok"]) for e in rec_fix["attempts_log"]]))
check("E4 the record names the artifacts the repair rewrote (its diff)",
      bool(repairs) and any("review/artifacts/OUTLINE.md" in c for c in repairs[0]["changed"])
      and any("review/artifacts/M20_formatting.md" in c for c in repairs[0]["changed"]),
      str((repairs or [{}])[0].get("changed"))[:200])
check("E5 the record carries the problems it was given and its transcript",
      bool(repairs) and len(repairs[0]["problems"]) >= 9
      and repairs[0]["transcript"].startswith(f"runs/{rec_fix['id']}/"),
      str((repairs or [{}])[0].get("transcript")))
history = "\n".join(nb.attempt_history_lines(ctx_of(root_fix)))
check("E6 the attempt history shows the repair and what it changed",
      "artifact repair (attempt 2" in history and "cleared" in history
      and "review/artifacts/OUTLINE.md" in history, history[:240])

root_nofix, proc_nofix, rec_nofix = run_review(scratch("nbt_rep_e2e_nofix_"), "fix",
                                               {"NBT_REPAIR_STUB_NOFIX": "1"})
rep_nofix = (rec_nofix.get("repairs") or [{}])[0]
check("E7 a repair that does not clear the problems fails the attempt",
      rec_nofix["status"] == "failed" and rep_nofix.get("ok") is False
      and [e["attempt"] for e in rec_nofix["attempts_log"]] == [1, 2]
      and rec_nofix["attempts_log"][1]["ok"] is False,
      str([(e["attempt"], e["source"], e["ok"]) for e in rec_nofix["attempts_log"]]))
check("E8 the failed repair is reported with the problems that remain",
      len(rep_nofix.get("postcheck_errors") or []) >= 9,
      str(len(rep_nofix.get("postcheck_errors") or [])))

for env_name, want in (("NBT_REPAIR_STUB_EVIL", "review/findings.json"),
                       ("NBT_REPAIR_STUB_DROP", "a row was deleted, added or reordered"),
                       ("NBT_REPAIR_STUB_DROP_OTHER", "MODIFIED review/artifacts/M1_acronyms.md")):
    root_bad, proc_bad, rec_bad = run_review(scratch(f"nbt_rep_e2e_{env_name.lower()}_"), "fix",
                                             {env_name: "1"})
    rep_bad = (rec_bad.get("repairs") or [{}])[0]
    check(f"E9 {env_name} is rejected by the scope guard",
          rec_bad["status"] == "failed" and rep_bad.get("ok") is False
          and any(want in p for p in (rep_bad.get("out_of_scope") or []))
          and rep_bad.get("postcheck_errors") is None,
          str(rep_bad.get("out_of_scope"))[:200])

root_on, proc_on, rec_on = run_review(scratch("nbt_rep_e2e_on_"), "on")
check("E10 policy `on` never starts a repair session",
      not rec_on.get("repairs") and "[repair]" not in proc_on.stdout
      and rec_on["status"] == "failed", proc_on.stdout[-200:])
root_off, proc_off, rec_off = run_review(scratch("nbt_rep_e2e_off_"), "off")
check("E11 policy `off` records the report as warnings and completes",
      rec_off["status"] == "done" and not rec_off["postcheck"]["errors"]
      and len(rec_off["postcheck"]["warnings"]) >= 9 and not rec_off.get("repairs"),
      f"errors={len(rec_off['postcheck']['errors'])} "
      f"warnings={len(rec_off['postcheck']['warnings'])}")

for d in TMPDIRS:
    shutil.rmtree(d, ignore_errors=True)

print()
print("== F. end to end: one repair session per stage (audit/rewrite/revise/integrate/judge) ==")


def run_stages(tmp: Path, policy: str, *, stages: str, bad: str = None, rewrites: str = "1",
               revises: str = "0", judges: str = "1", audit: str = None,
               integrators: str = None, env_extra: dict = None, retries: str = "0"):
    """Drive the real CLI for a subset of stages, with the stub as every agent."""
    root = setup_root(tmp, policy, judges=judges, rewrites=rewrites, revises=revises,
                      audit=audit, integrators=integrators)
    env = dict(os.environ)
    if bad:
        env["NBT_REPAIR_STUB_BAD"] = bad
    env.update(env_extra or {})
    proc = subprocess.run([sys.executable, str(root / "nbt_pipeline.py"), "run",
                           "--root", str(root), "--only", stages, "--retries", retries,
                           "--retry-backoff", "0",
                           "--agent-cmd", json.dumps([sys.executable, str(STUB_REPAIR)]),
                           "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_REPAIR)])],
                          capture_output=True, text=True, timeout=900, env=env)
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    return root, proc, state


def repaired(state: dict, rid: str) -> bool:
    """The run is done and its one repair session cleared the problems."""
    rec = state["runs"].get(rid) or {}
    reps = rec.get("repairs") or []
    return (rec.get("status") == "done" and len(reps) == 1 and reps[0].get("ok") is True
            and [(e["attempt"], e["source"], e["ok"]) for e in rec.get("attempts_log") or []]
            == [(1, "postcheck", False), (2, "artifact-repair", True)])


# --- audit: the repair may only ADD `confirm` dispositions ------------------
root_a, proc_a, state_a = run_stages(scratch("nbt_rep_f_audit_"), "fix", stages="review,audit",
                                     bad="r1_audit", revises="1", audit="on")
check("F1 audit: a broken disposition sheet is repaired and the run is done",
      repaired(state_a, "r1_audit"),
      str([(r["id"], r["status"], len(r.get("repairs") or []))
           for r in state_a["runs"].values()]))
audit_doc = json.loads((root_a / "runs" / "r1_audit" / "audit" / "audit.json")
                       .read_text(encoding="utf-8"))
frozen = json.loads((root_a / "runs" / "r1_audit" / "review" / "findings.json")
                    .read_text(encoding="utf-8"))["findings"]
ids = {str(r.get("id")) for r in audit_doc["dispositions"]}
check("F2 audit: every frozen id is disposed again, and no verdict was invented as a drop",
      {str(f["id"]) for f in frozen} <= ids
      and all(str(r.get("verdict")).lower() == "confirm" for r in audit_doc["dispositions"]),
      f"{len(ids)} ids")

# --- rewrite: the repair rewrites the missing report ------------------------
root_w, proc_w, state_w = run_stages(scratch("nbt_rep_f_rewrite_"), "fix", stages="rewrite",
                                     bad="r1_w1")
report = root_w / "runs" / "r1_w1" / "rewritten" / "REWRITE_REPORT.md"
check("F3 rewrite: the deleted REWRITE_REPORT.md is written again and the run is done",
      repaired(state_w, "r1_w1") and report.is_file()
      and "Organization map" in report.read_text(encoding="utf-8"),
      report.read_text(encoding="utf-8")[:120] if report.is_file() else "missing")

# --- revise: the repair completes the revision ledger -----------------------
root_r, proc_r, state_r = run_stages(scratch("nbt_rep_f_revise_"), "fix", stages="review,revise",
                                     bad="r1_a2_revise", revises="1", audit="off")
ledger = json.loads((root_r / "runs" / "r1_a2_revise" / "revised" / "revision_report.json")
                    .read_text(encoding="utf-8"))
frozen_r = json.loads((root_r / "runs" / "r1_a2_revise" / "review" / "findings.json")
                      .read_text(encoding="utf-8"))["findings"]
named = {str((row or {}).get("id")) for row in ledger if isinstance(row, dict)}
check("F4 revise: the ledger names every frozen id again and the run is done",
      repaired(state_r, "r1_a2_revise")
      and {str(f["id"]) for f in frozen_r} <= named
      and any(str(r.get("verdict")) == "unable" for r in ledger),
      f"named={sorted(named)}")

# --- integrate: the repair writes the donor ledger --------------------------
root_i, proc_i, state_i = run_stages(scratch("nbt_rep_f_integrate_"), "fix",
                                     stages="rewrite,integrate", bad="r1_i1", rewrites="2",
                                     integrators="0x1")
diff = root_i / "runs" / "r1_i1" / "integrated" / "DIFF_LEDGER.md"
donors = sorted(p.name for p in (root_i / "runs" / "r1_i1" / "others").iterdir() if p.is_dir())
check("F5 integrate: the deleted DIFF_LEDGER.md is written again (one row per donor)",
      repaired(state_i, "r1_i1") and diff.is_file()
      and all(d in diff.read_text(encoding="utf-8") for d in donors) and donors,
      f"donors={donors}")

# --- judge: the repair completes the coverage map, never the ledger ---------
root_j, proc_j, state_j = run_stages(scratch("nbt_rep_f_judge_"), "fix", stages="rewrite,judge",
                                     bad="judge_", rewrites="2", integrators="0x0")
judges = {rid: rec for rid, rec in state_j["runs"].items()
          if "_judge_" in rid or rid.startswith("judge_")}
check("F6 judge: every broken sheet is repaired and every judge run is done",
      bool(judges) and all(rec["status"] == "done" for rec in judges.values())
      and all(rec.get("repairs") for rec in judges.values()),
      str([(rid, rec["status"], len(rec.get("repairs") or [])) for rid, rec in judges.items()]))
sheet = json.loads((root_j / "runs" / sorted(judges)[0] / "scores.json").read_text(encoding="utf-8"))
covered = {c.get("opponent_label"): set((c.get("checks") or {})) for c in sheet["comparisons"]}
check("F7 judge: the repaired sheet covers every frozen check id with `unable` rows",
      all(covered and all(cid in ids for cid in
                          [f"M{i}" for i in range(1, 18)] + ["M18", "M19", "M20", "M21", "M22",
                                                            "M23", "M24"] + ["J1", "J2", "J3", "J4"])
          for ids in covered.values()),
      str({k: len(v) for k, v in covered.items()}))

# --- the guard, end to end, for a package stage -----------------------------
root_e, proc_e, state_e = run_stages(scratch("nbt_rep_f_evil_"), "fix", stages="review,revise",
                                     bad="r1_a2_revise", revises="1", audit="off",
                                     env_extra={"NBT_REPAIR_STUB_EVIL": "1"})
rec_e = state_e["runs"]["r1_a2_revise"]
rep_e = (rec_e.get("repairs") or [{}])[0]
check("F8 a repair that edits the package is rejected before its postcheck",
      rec_e["status"] == "failed" and rep_e.get("ok") is False
      and rep_e.get("postcheck_errors") is None
      and any("MODIFIED revised/" in p for p in (rep_e.get("out_of_scope") or [])),
      str(rep_e.get("out_of_scope"))[:200])

# --- the attempt record and the run log hold EVERY error --------------------
rec_f = state_e["runs"]["r1_a2_revise"]
first = (rec_f.get("attempts_log") or [{}])[0]
postcheck = [l for l in (proc_e.stdout + proc_e.stderr).splitlines()]
check("F9 the attempt record keeps every error, with the true count",
      first.get("n_errors") == len(first.get("errors") or []) >= 1
      and not any("NOT copied into state.json" in e for e in first.get("errors") or []),
      f"n_errors={first.get('n_errors')}")
check("F10 the console prints every error of a failed attempt",
      all(e in "\n".join(postcheck) for e in first.get("errors") or []),
      str(first.get("errors"))[:160])
run_logs = sorted((root_e / "reports").glob("run-*.log"))
log_text = run_logs[-1].read_text(encoding="utf-8") if run_logs else ""
check("F11 the invocation's console is kept in reports/run-*.log (attempts included)",
      bool(run_logs) and all(e in log_text for e in first.get("errors") or [])
      and str(run_logs[-1].relative_to(root_e)) in (state_e.get("run_logs") or []),
      str([p.name for p in run_logs]))


print()
if FAILS:
    print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
    sys.exit(1)
print("ALL ARTIFACT-REPAIR CHECKS PASSED")

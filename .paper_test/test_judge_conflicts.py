#!/usr/bin/env python3
"""Cross-judge conflict audit: the j1-vs-j2 inversion from the 2026-10-04 run.

Run:  python3 .paper_test/test_judge_conflicts.py

The detector must surface every class of contradiction between independent
judge sessions -- opposite integer scores, the same claim filed as `resolved`
by one session and `introduced` by another, different numbers quoted for the
same claim, and divergent check dispositions -- and must NOT call "one judge
cited more numbers than the other" a contradiction.  The report renderer must
turn the findings into checkbox items (the manual TODO list).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import types
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_conflicts",
                                              str(WS / "paper_pipeline.py"))
pc = importlib.util.module_from_spec(spec)
sys.modules["paper_conflicts"] = pc
spec.loader.exec_module(pc)

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(F"OK {name}")
    else:
        FAILS.append(F"{name}: {detail}")
        print(F"FAIL {name}: {detail}")


def opinion(run, idx, target, opponent, score, *, resolved=(), introduced=(),
            checks=None, reason=""):
    return {
        "judge_run": run, "judge_index": idx, "target": target,
        "opponent": opponent, "opponent_label": "v1", "score": score,
        "basis": "correctness", "reason": reason,
        "resolved": list(resolved), "introduced": list(introduced),
        "checks": checks or {},
    }


def judge_sheet_run(rid, target, idx, opponent="i2", score=1):
    return {
        "id": rid, "kind": "judge", "round": 1, "status": "done",
        "target_id": target, "judge_index": idx,
        "label_map": {"v1": opponent},
        "scores": {"comparisons": [{
            "opponent_label": "v1", "score": score, "basis": "none",
            "resolved": [], "introduced": [], "checks": {}, "reason": "",
        }]},
    }


class FakeCtx:
    def __init__(self, runs, field=("i1", "i2")):
        self._runs = list(runs)
        self._field = list(field)
        self.state = {}

    def runs(self, kind=None, round_no=None):
        return [r for r in self._runs
                if (kind is None or r.get("kind") == kind)
                and (round_no is None or r.get("round") == round_no)]

    def round_rec(self, r):
        return {"field": list(self._field)}


J1_TEXT = ("Methods: 'several hundred to more than a thousand evaluable cells "
           "per sample'; source data show 173-1,307 (v1 states 'approximately "
           "170 to more than 1,300')")
J2_TEXT = ("Methods: 'approximately 170 to more than 1,300 evaluable cells per "
           "sample'; Fig. 3d source (n_cells) gives 508-1,307; target's wording fits")


def main():
    # The exact round-2 shape: same target/opponent, opposite scores, the ACT
    # cell-range claim filed on both sides, different quoted numbers.
    ops = [
        opinion("judge_j1", 1, "r1_i4", "i2", -2, checks={"M15": "clean"},
                introduced=[{"check": "M4", "tier": "correctness",
                             "severity": "major", "evidence": J1_TEXT}],
                reason="Target keeps a data-contradicted evaluable-cell range"),
        opinion("judge_j2", 2, "r1_i4", "i2", +2, checks={"M15": "findings"},
                resolved=[{"check": "M15", "tier": "correctness",
                           "severity": "major", "evidence": J2_TEXT}],
                reason="Target states the ACT per-sample cell range the figure "
                       "source supports"),
    ]
    conflicts = pc.detect_round_judge_conflicts(ops)
    by_kind = {}
    for c in conflicts:
        by_kind.setdefault(c["kind"], []).append(c)

    sd = by_kind.get("score_disagreement", [])
    check("opposite score is a blocker", any(c["severity"] == "blocker" for c in sd),
          [c["severity"] for c in sd])
    ci = by_kind.get("claim_inversion", [])
    check("resolved-vs-introduced is a blocker", any(c["severity"] == "blocker" for c in ci),
          [c["severity"] for c in ci])
    check("both judge runs are named",
          any(set(c["judges"]) == {"judge_j1", "judge_j2"} for c in ci))
    nc = by_kind.get("numeric_contradiction", [])
    check("173 vs 508 is a numeric contradiction",
          any(c["severity"] == "major" and "508" in c["summary"] for c in nc),
          [c["summary"] for c in nc])
    cd = by_kind.get("check_disposition", [])
    check("M15 clean-vs-findings is flagged",
          any("M15" in c["summary"] for c in cd), [c["summary"] for c in cd])

    # More detail on one side (a subset of numbers) is NOT a contradiction.
    subset = [
        opinion("judge_a", 1, "i1", "orig", 1,
                resolved=[{"check": "M4", "tier": "correctness", "severity": "major",
                           "evidence": ("Methods and S23-S30 legend: 50-kb bins "
                                        "contradict the sidecar bin_size = 1,000,000; "
                                        "target states 1 Mb")}]),
        opinion("judge_b", 2, "i1", "orig", 1,
                resolved=[{"check": "M4", "tier": "correctness", "severity": "major",
                           "evidence": ("v1 Methods p94 and SI S23-S30 legend say "
                                        "50-kb bins; the shipped Fig. 4 source JSON "
                                        "has bin_size=1000000, n_bins 2620-3089; "
                                        "target says 1 Mb")}]),
    ]
    subset_conflicts = pc.detect_round_judge_conflicts(subset)
    check("a numeric subset is detail, not a contradiction",
          not any(c["kind"] == "numeric_contradiction" for c in subset_conflicts),
          [c["kind"] for c in subset_conflicts])

    # Distinct check subjects stay distinct through the merge.
    a = {"kind": "check_disposition", "severity": "minor", "member": "x",
         "opponent": "y", "judges": ["j1", "j2"], "subject": "check:M15",
         "summary": "M15", "evidence": [], "manual_check": "m"}
    b = {"kind": "check_disposition", "severity": "minor", "member": "x",
         "opponent": "y", "judges": ["j1", "j2"], "subject": "check:J3",
         "summary": "J3", "evidence": [], "manual_check": "m"}
    merged = pc._merge_judge_conflicts([a, b], [])
    check("different check subjects stay separate", len(merged) == 2,
          [m.get("subject") for m in merged])

    # The report is a manual TODO list.
    for i, c in enumerate(conflicts, 1):
        c["id"] = F"C2-{i:03d}"
    data = {"round": 2, "generated": "test", "conflicts": conflicts,
            "counts": pc._judge_conflict_counts(conflicts)}
    md = pc.judge_conflicts_markdown(data)
    check("report renders checkbox items", "- [ ]" in md and "C2-001" in md)
    check("report names the blocker severity", "blocker" in md)

    # The LLM auditor is ON by default: `decide` reuses the backend `run`
    # recorded, unless the operator disables it or forces manual mode.
    recorded = [sys.executable, "-c", "pass"]
    fake_ctx = types.SimpleNamespace(state={"conflict_agent": {
        "cmd": recorded, "source": "judge-backend"}})
    plain = types.SimpleNamespace(no_conflict_agent=False, conflict_agent=None,
                                  conflict_agent_cmd=None, agent=None, agent_cmd=None)
    saved_env = os.environ.pop("PAPER_AGENT_CMD", None)
    saved_conflict_env = os.environ.pop("PAPER_CONFLICT_AGENT_CMD", None)
    try:
        preset = pc.AGENT_PRESETS.get("codex-lite") or []
        check("the lightweight conflict preset exists",
              any("model_reasoning_effort" in str(x) for x in preset), str(preset))
        check("decide reuses the recorded audit backend by default",
              pc.conflict_agent_cmd_from_args(plain, fake_ctx) == recorded)
        off = types.SimpleNamespace(no_conflict_agent=True, conflict_agent=None,
                                    conflict_agent_cmd=None, agent=None, agent_cmd=None)
        check("--no-conflict-agent keeps the deterministic pass",
              pc.conflict_agent_cmd_from_args(off, fake_ctx) is None)
        manual = types.SimpleNamespace(no_conflict_agent=False, conflict_agent="manual",
                                       conflict_agent_cmd=None, agent=None, agent_cmd=None)
        check("--conflict-agent manual keeps the deterministic pass",
              pc.conflict_agent_cmd_from_args(manual, fake_ctx) is None)
        disabled_ctx = types.SimpleNamespace(state={"conflict_agent": {
            "cmd": None, "source": "disabled"}})
        check("a run recorded as disabled keeps decide deterministic",
              pc.conflict_agent_cmd_from_args(plain, disabled_ctx) is None)
        provider_ctx = types.SimpleNamespace(state={"judge_provider": {
            "judge": "codex", "judge_manual": False}})
        got = pc.conflict_agent_cmd_from_args(plain, provider_ctx)
        if shutil.which("codex"):
            check("a legacy agent-driven root defaults to the configured agent",
                  bool(got) and got[0] == "codex", str(got))
        else:
            check("a legacy root without codex stays deterministic", got is None, str(got))
        stub_judge = [sys.executable, "stub_judge.py"]
        rc_cmd, rc_src = pc.resolve_round_audit_cmd(None, True, stub_judge, False, {})
        check("a custom/stub judge backend is the per-round auditor",
              rc_cmd == stub_judge and rc_src == "judge-backend", F"{rc_cmd}/{rc_src}")
        rc_cmd, rc_src = pc.resolve_round_audit_cmd(None, True, stub_judge, False,
                                                    {"cmd": recorded, "source": "recorded"})
        check("a recorded audit backend is reused per round",
              rc_cmd == recorded and rc_src == "recorded", F"{rc_cmd}/{rc_src}")
        codex_judge = ["codex", "exec", "-"]
        rc_cmd, rc_src = pc.resolve_round_audit_cmd(None, True, codex_judge, False, {})
        if shutil.which("codex"):
            check("a preset judge backend gets the lightweight per-round auditor",
                  rc_src == "lightweight-default"
                  and any("model_reasoning_effort" in str(x) for x in (rc_cmd or [])),
                  F"{rc_cmd}/{rc_src}")
        else:
            check("a preset judge backend falls back to itself without codex",
                  rc_cmd == codex_judge and rc_src == "judge-backend", F"{rc_cmd}/{rc_src}")
        rc_cmd, rc_src = pc.resolve_round_audit_cmd(recorded, True, stub_judge, False, {})
        check("an explicit conflict backend wins per round",
              rc_cmd == recorded and rc_src == "conflict-agent", F"{rc_cmd}/{rc_src}")
        rc_cmd, rc_src = pc.resolve_round_audit_cmd(None, False, stub_judge, False, {})
        check("--no-conflict-agent disables the per-round auditor",
              rc_cmd is None and rc_src == "disabled", F"{rc_cmd}/{rc_src}")
        rc_cmd, rc_src = pc.resolve_round_audit_cmd(None, True, codex_judge, True, {})
        check("manual judge mode keeps the per-round auditor deterministic",
              rc_cmd is None and rc_src == "manual", F"{rc_cmd}/{rc_src}")
        rc_cmd, rc_src = pc.resolve_round_audit_cmd(recorded, True, None, True, {})
        check("an explicit audit backend still runs in manual judge mode",
              rc_cmd == recorded and rc_src == "conflict-agent", F"{rc_cmd}/{rc_src}")
        orig_sel, orig_round_judges = pc.judge_selection, pc.round_judges
        try:
            sel_ctx = FakeCtx([judge_sheet_run("j1", "i1", 1),
                               judge_sheet_run("j2", "i1", 2),
                               judge_sheet_run("j3", "i1", 3)])
            pc.round_judges = lambda _ctx, _r: 2
            pc.judge_selection = lambda _ctx, _r: {("i1", 1)}
            sel_ops = pc.round_judge_opinions(sel_ctx, 1)
            check("per-round opinions mirror the judge-session selection",
                  [o["judge_run"] for o in sel_ops] == ["j1"],
                  [o["judge_run"] for o in sel_ops])
            pc.judge_selection = lambda _ctx, _r: set()
            all_ops = pc.round_judge_opinions(sel_ctx, 1)
            check("out-of-range judge sheets are ignored by the audit",
                  [o["judge_run"] for o in all_ops] == ["j1", "j2"],
                  [o["judge_run"] for o in all_ops])
        finally:
            pc.judge_selection, pc.round_judges = orig_sel, orig_round_judges
        os.environ["PAPER_CONFLICT_AGENT_CMD"] = json.dumps(recorded)
        check("PAPER_CONFLICT_AGENT_CMD is the audit's lightweight default",
              pc.default_conflict_agent_cmd() == recorded
              and pc.conflict_agent_cmd_from_args(plain, None) == recorded)
        rc_cmd, rc_src = pc.resolve_round_audit_cmd(None, True, None, True, {})
        check("the audit-specific env enables the auditor in manual judge mode",
              rc_cmd == recorded and rc_src == "conflict-agent-env", F"{rc_cmd}/{rc_src}")
        del os.environ["PAPER_CONFLICT_AGENT_CMD"]
        heavy = [sys.executable, "heavy_model.py"]
        os.environ["PAPER_AGENT_CMD"] = json.dumps(heavy)
        got = pc.default_conflict_agent_cmd()
        if shutil.which("codex"):
            check("the lightweight preset beats a heavy PAPER_AGENT_CMD",
                  bool(got) and any("model_reasoning_effort" in str(x) for x in got),
                  str(got))
        del os.environ["PAPER_AGENT_CMD"]
        manual_cmd_args = types.SimpleNamespace(
            no_conflict_agent=False, conflict_agent="manual",
            conflict_agent_cmd=json.dumps(recorded), agent=None, agent_cmd=None)
        check("an explicit audit command wins over --conflict-agent manual",
              pc.conflict_agent_cmd_from_args(manual_cmd_args, None) == recorded)
        manual_provider = types.SimpleNamespace(state={"judge_provider": {
            "judge": "stub", "judge_manual": True}})
        check("a legacy manual-mode root keeps decide deterministic",
              pc.conflict_agent_cmd_from_args(plain, manual_provider) is None)
    finally:
        if saved_env is not None:
            os.environ["PAPER_AGENT_CMD"] = saved_env
        if saved_conflict_env is not None:
            os.environ["PAPER_CONFLICT_AGENT_CMD"] = saved_conflict_env

    if FAILS:
        print(F"\n{len(FAILS)} judge-conflict check(s) FAILED")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("\nAll judge-conflict checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

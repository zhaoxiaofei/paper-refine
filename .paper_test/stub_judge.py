#!/usr/bin/env python3
"""Deterministic offline judge for the rewrite-arm end-to-end test.

Unlike `stub_agent.py` (which scores by whole-tree digest and therefore ranks
whatever the hash order happens to favour), this judge implements one
deliberate, documented rule so the end-to-end suite can assert the CHANGE
REQUEST's outcome: the REWRITTEN candidate must be able to WIN the round, be
pinned, and become the next round's base.

RULE: score the target against each opponent on this deterministic profile of
its .md documents, compared as a lexicographic tuple:

    (has the rewrite stage's marker line, -number of "stub edit for" lines)

so the REWRITE arm itself (marker present, no later edit stacked on it) ranks
above every package derived from it, and every package that carries the
rewrite's organization ranks above the packages that do not. Each comparison is
scored +2, 0 or -2 by the sign of the profile comparison -- exactly the "one
clear, verifiable difference" a real judge would be asked to score.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REWRITE_MARKER = "stub rewrite for"
EDIT_MARKER = "stub edit for"


def profile(d: Path) -> tuple:
    if not d.is_dir():
        return (0, 0)
    text = ""
    for p in sorted(d.rglob("*.md")):
        try:
            text += p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return (1 if REWRITE_MARKER in text else 0, -text.count(EDIT_MARKER))


def stub_basis(score: int) -> dict:
    """The graded basis (judge contract v2) for a deterministic stub score."""
    if score > 0:
        return {"basis": "consistency",
                "resolved": [{"check": "M1", "tier": "consistency", "severity": "major",
                              "evidence": "stub: the rewrite marker keeps the target organized"}],
                "introduced": []}
    if score < 0:
        return {"basis": "consistency", "resolved": [],
                "introduced": [{"check": "M1", "tier": "consistency", "severity": "major",
                                "evidence": "stub: the opponent carries more edit markers"}]}
    return {"basis": "none", "resolved": [], "introduced": []}


JUDGE_CHECK_IDS = ([f"M{i}" for i in range(1, 18)]
                   + ["M18", "M19", "M20", "M21", "M22", "M23", "M24"]
                   + [f"J{i}" for i in range(1, 5)])


def stub_checks(score: int) -> dict:
    out = {c: "clean -- stub: organization profile compared" for c in JUDGE_CHECK_IDS}
    if score:
        out["M1"] = "findings -- stub: organization profile (see resolved/introduced)"
    return out


def main() -> int:
    sb = Path.cwd()
    prompt = (sb / "PROMPT.md").read_text(encoding="utf-8")
    name = sb.name
    token = re.search(r'"target_id":\s*"([^"]+)"', prompt).group(1)
    jidx = int(re.search(r'"judge_index":\s*(\d+)', prompt).group(1))
    labels = re.findall(r"no more, no fewer:\s*(.+)", prompt)[0].strip()
    labels = [x.strip() for x in labels.split(",")]
    target_profile = profile(sb / "target")
    comps = []
    for lab in labels:
        opp_profile = profile(sb / "field" / lab)
        score = 0 if target_profile == opp_profile else \
            (2 if target_profile > opp_profile else -2)
        comps.append({"opponent_label": lab, "score": score,
                      "reason": "rewrite-organization profile comparison (stub judge)",
                      "checks": stub_checks(score),
                      **stub_basis(score)})
    # No "round": the session id is an opaque token and a judge is never told
    # which round it belongs to (see judge_prompt/rid_judge).
    (sb / "scores.json").write_text(json.dumps({
        "run_id": name, "target_id": token, "judge_index": jidx, "comparisons": comps,
        "notes": "deterministic stub judge"}), encoding="utf-8")
    jr = sb / "judge_review"
    (jr / "artifacts").mkdir(parents=True, exist_ok=True)
    (jr / "inventory.md").write_text("# inventory (stub judge)\n", encoding="utf-8")
    (jr / "artifacts" / "M1_acronyms.md").write_text("| row |\n|---|\n", encoding="utf-8")
    (jr / "artifacts" / "VIS_visual.md").write_text(
        "# visual inspection (stub judge)\n\nno renderer used by this stub; pages NOT visually "
        "verified\n", encoding="utf-8")
    (sb / "_pipeline_done.json").write_text(json.dumps(
        {"stage": "judge", "run_id": name, "status": "complete", "error": None}),
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

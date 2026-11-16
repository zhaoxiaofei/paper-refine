#!/usr/bin/env python3
"""The 2026-11-16 brief_communication failure: the prompt must point at a skill path.

The review session had already read one skill reference when a compaction pushed
the skill root out of context.  It then ran

    find / -path '*paper-skills/paper-review/references/sweeps.md'

to recover the path, and the harness stopped the session.  The orchestration
header now states how to locate the pack, points at the pipeline root's
``paper-skills/`` fallback, and forbids a root scan; it reaches every stage
prompt (the review, cold-start review, revise, audit, integrate, rewrite, judge
and revision-audit builders all prepend it).

The prompt must stay generic: paper-refine does not know where a particular
harness mounts the pack, so it must not hard-code a harness path or name a
harness guard.  The eval's own bridge prompt supplies its mount (for example
``/skills``) without paper-refine encoding it.

Run:  python3 .paper_test/test_skill_paths_20261116.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
FAILS = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'ok ' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)
    return ok


def load_pipeline():
    spec = importlib.util.spec_from_file_location("paperp_skill_paths", WS / "paper_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["paperp_skill_paths"] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    np = load_pipeline()
    with tempfile.TemporaryDirectory() as tmp:
        sb = Path(tmp)
        prompts = {
            "review": np.review_prompt(sb, "r1_guided_review", 1),
            "cold_start_review": np.cold_start_review_prompt(
                sb, "r1_cold_start_review", 1
            ),
            "revise": np.revise_prompt(sb, "r1_a2_revise", 1),
            "audit": np.audit_prompt(sb, "r1_audit", 1),
            "judge": np.judge_prompt(
                sb, "r1_judge_t1_j1", 1, "t1", 1, 3, ["v1"]
            ),
        }
        for name, text in prompts.items():
            check(f"{name}: names the frozen paper-skills fallback",
                  "paper-skills/paper-review/" in text)
            check(f"{name}: forbids a root scan", "find /" in text)
            check(f"{name}: does not hard-code a harness skill mount",
                  "/skills/paper-review" not in text)
            check(f"{name}: does not name a harness guard",
                  "leak guard" not in text.lower())

    if FAILS:
        print(f"\n{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("\nSKILL PATH CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Full retries and auxiliary sessions are counted separately.

The reported gap (2026-11-12 root, `r1_a2_revise`): the console printed
`[attempt 5/3]` for the run's THIRD launch. The retry budget was not overrun —
the display used the `attempts` counter, which numbers every session that wrote
into the run's record (here two re-verifies of a process that died after
writing complete artifacts), so non-retry sessions were charged to
`attempts/run`. This suite guards the split:

  A. counters   `attempts` (record identity) and `stage_attempts` (budgeted full
                attempts) move independently; scoped repairs, CONTINUATIONS and
                re-verifications get their own counters.
  B. launch     the `[attempt N/M]` tag is the FULL-attempt ordinal and can
                never exceed M; the auxiliary sessions are named beside it.
  C. summary    the end-of-invocation FAILED cell reports full attempts against
                the budget and lists the auxiliary sessions separately.
  D. table      the status/DECISION_REPORT cell is `full+aux`.
  E. reset      `retry --run` resets the per-invocation counters with `attempts`.

Run:  python3 .paper_test/test_attempt_count_split.py
`PAPER_WS` retargets the suite at a baseline (pre-fix -> red) tree.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_count", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_count"] = nb
spec.loader.exec_module(nb)

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


print("== A. the two counters move independently ==")
rec = {"id": "r1_a2_revise", "attempts": 0}
nb.bump_attempt(rec)
check("a recorded session bumps `attempts` but NOT the retry budget",
      rec["attempts"] == 1 and nb.stage_attempts(rec) == 0,
      f"attempts={rec['attempts']} stage_attempts={nb.stage_attempts(rec)}")
nb.bump_stage_attempt(rec)
check("a full stage attempt bumps `stage_attempts` and leaves `attempts` alone",
      rec["stage_attempts"] == 1 and rec["attempts"] == 1,
      f"attempts={rec['attempts']} stage_attempts={rec['stage_attempts']}")
nb.bump_scoped_repair(rec)
nb.bump_continuation(rec)
nb.bump_reverification(rec)
check("auxiliary sessions have their own counters",
      (rec["scoped_repairs"], rec["continuation_sessions"], rec["reverifications"]) == (1, 1, 1)
      and nb.stage_attempts(rec) == 1,
      str({k: rec.get(k) for k in ("stage_attempts", "scoped_repairs",
                                    "continuation_sessions", "reverifications")}))
check("the auxiliary summary names each kind once",
      nb.auxiliary_session_summary(rec) == "1 scoped repair, 1 continuation, 1 re-verification",
      nb.auxiliary_session_summary(rec))

print()
print("== B. the launch tag counts full attempts only (the 5/3 report) ==")
# The incident's shape at the third launch: 2 re-verifies between 3 launches,
# i.e. 4 recorded sessions, of which only 2 are full attempts so far.
incident = {"id": "r1_a2_revise", "attempts": 4, "attempts_done": 4,
            "stage_attempts": 2, "reverifications": 2}
tag = nb.attempt_start_suffix(incident, 3, 2)
check("the third launch is attempt 3/3, never 5/3", "[attempt 3/3" in tag and "5/3" not in tag,
      tag)
check("the tag cannot exceed the budget even though 4 sessions are recorded",
      "4/3" not in tag and "3/4" not in tag, tag)
check("the re-verifies are named beside the attempt, not added to it",
      "2 re-verifications" in tag, tag)
check("the first attempt gets no tag",
      nb.attempt_start_suffix({"id": "x", "attempts": 0}, 3, 0) == "", "")
# The budget is granted PER INVOCATION: a resumed `run` re-grants it, so the
# numerator comes from the live budget, never from the lifetime session count.
resumed = dict(incident, stage_attempts=4, attempts=7)
check("a resumed invocation starts at attempt 1 again, never 5/3",
      nb.attempt_start_suffix(resumed, 3, 0) == "", "")
check("its second launch is 2/3 even though 7 sessions are recorded",
      "[attempt 2/3" in nb.attempt_start_suffix(resumed, 3, 1),
      nb.attempt_start_suffix(resumed, 3, 1))
mixed = dict(incident, attempts=6, scoped_repairs=1, continuation_sessions=2)
tag = nb.attempt_start_suffix(mixed, 3, 2)
check("a scoped repair and continuations are named too",
      "1 scoped repair" in tag and "2 continuations" in tag, tag)

print()
print("== C. the FAILED summary separates retries from the rest ==")
cell = nb.failed_run_cell("r1_a2_revise", mixed, 3, 2)
check("it reports the invocation's budget usage, not the lifetime count",
      "2 of 3 attempt(s) spent" in cell, cell)
check("it does not report the 6 recorded sessions as retries",
      "6 attempt" not in cell and "6 full" not in cell, cell)
check("it lists the auxiliary sessions", "1 scoped repair" in cell, cell)
legacy = nb.failed_run_cell("r_old", {"attempts": 2}, 3, 1)
check("it reports only what this invocation spent (never the lifetime count)",
      "1 of 3 attempt(s) spent" in legacy and "2 of 3" not in legacy, legacy)
check("it still names the lifetime full launches when they differ from the budget",
      "2 full launch(es)" in legacy, legacy)

print()
print("== D. the run table's cell is full+aux ==")
check("a run with auxiliary sessions shows `full+aux`",
      nb.attempt_split_cell(mixed) == "2+5", nb.attempt_split_cell(mixed))
check("an ordinary run stays a plain number",
      nb.attempt_split_cell({"attempts": 2, "stage_attempts": 2}) == "2",
      nb.attempt_split_cell({"attempts": 2, "stage_attempts": 2}))

print()
print("== E. `retry --run` resets the per-invocation counters ==")
nb.reset_run_record(mixed)
check("the next invocation starts at zero on every counter",
      nb.stage_attempts(mixed) == 0 and nb.auxiliary_sessions(mixed) == 0
      and mixed["attempts"] == 0,
      str({k: mixed.get(k) for k in ("attempts", "stage_attempts", "scoped_repairs",
                                      "continuation_sessions", "reverifications")}))

print()
if FAILS:
    print(f"{len(FAILS)} CHECK(S) FAILED: " + ", ".join(FAILS))
    raise SystemExit(1)
print("ALL ATTEMPT-COUNT-SPLIT CHECKS PASSED")

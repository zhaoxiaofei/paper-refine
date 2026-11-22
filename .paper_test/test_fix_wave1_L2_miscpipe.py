#!/usr/bin/env python3
"""Regression checks for fix-bugs wave 1 batch L2_miscpipe (run 20261122-112829).

Each check pins one candidate this batch re-verified and patched. Run:

  conda run -n paper-refine-test python .paper_test/test_fix_wave1_L2_miscpipe.py
"""
from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp  # noqa: E402

FAILS: list[str] = []
TMP = Path(tempfile.mkdtemp(prefix="fix_wave1_L2_miscpipe_"))


def check(label: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(label)


class Ctx:
    def __init__(self, runs, field):
        self._runs, self._field = list(runs), list(field)

    def runs(self, kind=None, round_no=None):
        return [r for r in self._runs
                if (kind is None or r.get("kind") == kind)
                and (round_no is None or r.get("round") == round_no)]

    def round_rec(self, r):
        return {"field": list(self._field)}

    def state(self):
        return {}


def judge_sheet(comps, target="v1", rid="j1", j=1):
    return {"id": rid, "kind": "judge", "round": 1, "status": "done",
            "target_id": target, "judge_index": j, "label_map": {"v2": "v2"},
            "scores": {"comparisons": comps}}


def comp(score):
    return {"opponent_label": "v2", "score": score, "basis": "none",
            "resolved": [], "introduced": [], "checks": {}, "reason": ""}


# F67: a rejected first row must not reserve the (target, judge, opponent) slot.
cov = {}
ops = pp.round_judge_opinions(
    Ctx([judge_sheet([comp(None), comp(2)])], ["v1", "v2"]), 1, coverage=cov)
check("F67 a valid second row survives a malformed first row for the same opponent",
      [o["score"] for o in ops] == [2] and cov["dropped"].get("missing_score") == 1,
      f"{[o['score'] for o in ops]} / {cov.get('dropped')}")
ops2 = pp.round_judge_opinions(
    Ctx([judge_sheet([comp(2), comp(-2)])], ["v1", "v2"]), 1)
check("F67 two valid duplicate rows still collapse to one opinion",
      [o["score"] for o in ops2] == [2], str([o["score"] for o in ops2]))

# F98/F134/F183/F184: the shipped CLI help describes what the code does.
cli = (ROOT / "paper_pipeline_parts/p17_cli.py").read_text(encoding="utf-8")
check("F98 decide help documents exit 4 for a provisional (auto-promoted) answer",
      "4 a provisional answer under" in cli
      and "incomplete (--require-complete)" not in cli)
check("F184 --require-complete help names the provisional cases",
      "exit 4 unless the answer is a complete" in cli
      and "exit non-zero unless all configured rounds are complete" not in cli)
check("F134 --package-winner help no longer says a provisional winner is never packaged",
      "is never packaged" not in cli and "winner IS packaged" in cli)
check("F183 --execution-profile help makes no model/window claim",
      "limited-context model" not in cli and "one GPU" not in cli
      and "~100k tokens" not in cli
      and "not a model-class claim" in cli)

# F99: a version/state suffix marks an article-type MANUSCRIPT.
check("F99 editorial_final / editorial_revised are manuscripts, not journal feedback",
      pp.is_journal_feedback_name("editorial_final.docx") is False
      and pp.is_journal_feedback_name("editorial_revised.docx") is False
      and pp.is_journal_feedback_name("editorial_final_v2.docx") is False
      and pp.is_journal_feedback_name("editor_decision_letter.docx") is True
      and pp.is_journal_feedback_name("editorial.docx") is False)

# F170: a four-digit year does not start a numbered reviewer point.
rows = pp.seed_concern_candidates(
    "Reviewer 1\n2020. We enrolled 40 patients.\nThe methods are unclear.")
check("F170 a bibliographic year does not split/truncate the reviewer block",
      len(rows) == 1 and "2020." in rows[0]["excerpt"]
      and "The methods are unclear." in rows[0]["excerpt"],
      str(rows))

# F172: deleting item 5 must not leave a 4 -> 6 jump in the inline contract.
import re  # noqa: E402
nums = [int(m.group(1)) for m in
        re.finditer(r"(?m)^\s*(\d)\.\s", pp.MEDIUM_PROFILE_CONTRACT_INLINE)]
check("F172 the inline medium contract is numbered 1..5 without a gap",
      nums == [1, 2, 3, 4, 5], str(nums))

# F179: the Verifier bullet stays inside the finding's nested list.
row = {"id": "X-901", "check": "M4", "severity": "major",
       "verifier": {"script": "v.py", "computed": "0"}}
md = pp._cold_start_findings_md([row])
check("F179 the Verifier bullet is indented under the finding, not at column 0",
      "\n  - Verifier:" in md and "\n- Verifier:" not in md, md)
md2 = pp._cold_start_findings_md([row], 2)
check("F179 the level argument controls the finding/field indentation",
      md2.startswith("  - X-901") and "\n    - Verifier:" in md2, md2)

# F142: latexmk output is drained by run_bounded (capped) and its overrun handled.
src = (ROOT / "paper_pipeline_parts/p15_pdf.py").read_text(encoding="utf-8")
check("F142 the compiler run drains through run_bounded, not a TemporaryFile",
      "run_bounded(" in src and "TemporaryFile() as out_tmp" not in src)
pkg = TMP / "latexpkg"
pkg.mkdir(parents=True)
(pkg / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
saved_which, saved_run = pp.shutil.which, pp.run_bounded
pp.shutil.which = lambda _n: "/usr/bin/latexmk"

def _over(*_a, **_k):
    raise pp.ToolOutputOverBudget("tool output over 999 bytes (stdout=1000, stderr=0)")

pp.run_bounded = _over
try:
    res = pp.compile_latex_pdf(pkg, "main.tex", pkg / "main.pdf", timeout=5)
finally:
    pp.shutil.which, pp.run_bounded = saved_which, saved_run
check("F142 an over-budget compile returns a structured refusal, never raises",
      res.get("ok") is False and "budget" in str(res.get("error")),
      str(res))

# F89: the bundle preflight requires the formatter's four ordered parts.
want = {"paper_docx_format_parts/p00_core.py",
        "paper_docx_format_parts/p01_text_rules.py",
        "paper_docx_format_parts/p02_layout_edit.py",
        "paper_docx_format_parts/p03_report_cli.py"}
check("F89 PIPELINE_REQUIRED_PARTS names all four formatter parts",
      want <= set(pp.PIPELINE_REQUIRED_PARTS),
      str(want - set(pp.PIPELINE_REQUIRED_PARTS)))
tmp = TMP / "bundle"
for name in pp.PIPELINE_ASSET_DIRS:
    (tmp / name).mkdir(parents=True, exist_ok=True)
for name in list(pp.PIPELINE_MODULE_FILES) + list(pp.PIPELINE_REQUIRED_ASSET_FILES):
    (tmp / name).parent.mkdir(parents=True, exist_ok=True)
    (tmp / name).write_text("x", encoding="utf-8")
for name in pp.PIPELINE_REQUIRED_PARTS:
    if "paper_docx_format_parts" in name:
        continue
    (tmp / name).parent.mkdir(parents=True, exist_ok=True)
    (tmp / name).write_text("x", encoding="utf-8")
missing = pp._missing_bundle_assets(tmp)
check("F89 a bundle with no formatter parts is refused by the preflight",
      want <= set(missing), str(missing))

# F86: the shipped prompt prose states the manuscript rule, not a scorer's reward.
prompts = (ROOT / "paper_pipeline_parts/p03_prompts.py").read_text(encoding="utf-8")
check("F86 no stage prompt states the benchmark's reward model",
      "benchmark credits" not in prompts and "restored claim" not in prompts
      and "An in-place correction PRESERVES the claim" in prompts
      and "a rewrite preserves the" in prompts)

# F166: a received-direction row's label names opponent_id.
root = TMP / "reports"
root.mkdir(parents=True)
C = type("C", (), {"reports_dir": root, "root": root,
                   "round_rec": lambda self, r: {}})()
base = {"round": 1, "basis": "correctness", "resolved": "", "introduced": "", "reason": ""}
st = {"n": 2, "median": 0.5, "mean": 0.5}
rows = [dict(base, member="v1", direction="own", credited=1, opponent_id="v2",
             opponent_label="v2", sheet_target="v1", source_judge_run="j",
             source_judge_index=1, score_as_written=1),
        dict(base, member="v2", direction="received", credited=-1, opponent_id="v1",
             opponent_label="v2", sheet_target="v1", source_judge_run="j",
             source_judge_index=1, score_as_written=1)]
csvp = pp.write_round_raw_scores(
    C, 1, {"field": ["v1", "v2"], "stats": {"v1": st, "v2": st}, "score_rows": rows})
got = {r["direction"]: r["opponent_label"] for r in csv.DictReader(open(csvp))}
check("F166 the received row's opponent_label names opponent_id",
      got.get("own") == "v2" and got.get("received") == "v1", str(got))

# F44: "published by this decision" is false when the copy was left unchanged.
unchanged = pp.decide_certification(
    [], [{"round": 1, "mismatch": None}], True, {}, None, False, False, 1, 1,
    {"files": 3, "action": "unchanged"}, None)
created = pp.decide_certification(
    [], [{"round": 1, "mismatch": None}], True, {}, None, False, False, 1, 1,
    {"files": 3, "action": "created"}, None)
legacy = pp.decide_certification(
    [], [{"round": 1, "mismatch": None}], True, {}, None, False, False, 1, 1,
    {"files": 3}, None)


def report(cert):
    lines = pp._load_pipeline_module(
        "paper_pipeline_parts/decision_report.py").header_lines(
        generated="x", root="/r", version="1", config_line="c", venue_lines=[],
        certification=cert, verdict="CERTIFIED",
        clean_readme_name="final_clean_version.readme.md",
        integrity={"hash_checks": "verified", "pristine_ok": True,
                   "pristine_detail": "ok", "pinned_errors": []},
        pin_count=1, problems=[])
    return " ".join(ln for ln in lines if "final_clean_version/" in ln)


check("F44 an unchanged copy is not reported as published by this decision",
      unchanged["clean_version"]["published"] is False
      and "left unchanged from an earlier decision" in report(unchanged)
      and "published by this decision" not in report(unchanged))
check("F44 a created copy is still reported as published by this decision",
      created["clean_version"]["published"] is True
      and "published by this decision" in report(created))
check("F44 a legacy {'files': N} record keeps the published meaning",
      legacy["clean_version"]["published"] is True)

print()
if FAILS:
    print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
    sys.exit(1)
print("ALL L2_miscpipe CHECKS PASSED")

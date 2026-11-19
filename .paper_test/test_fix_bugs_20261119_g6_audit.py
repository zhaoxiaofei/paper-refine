#!/usr/bin/env python3
"""g6_audit -- regression tests for the defect-audit fixes (F099, F100, F101,
F102, F108).

Run:  python3 .paper_test/test_fix_bugs_20261119_g6_audit.py

Every check FAILS on the pre-fix tree and PASSES on the fixed one:

  * F099  a reason made only of repeated filler tokens ("x x x", "ok ok ok",
          "n/a n/a") is not a usable audit basis;
  * F100  a stored ok:true audit with an unlabelled row is not reused as a
          successful audit and does not rebuild the TP-only family;
  * F101  a failed re-audit removes the previous successful auditedTP_* files
          instead of leaving a successful-looking record beside ok:false;
  * F102  if the old audit.json cannot be removed, the attempt fails instead of
          reading the previous run's verdicts as its own;
  * F108  an audit.json symlink is refused: the target is never copied into
          reports/.../audit.previous.json.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_g6_audit", str(WS / "paper_pipeline.py"))
pp = importlib.util.module_from_spec(spec)
sys.modules["paper_g6_audit"] = pp
spec.loader.exec_module(pp)

FAILS = []
TMPDIRS = []

GOOD_REASON = "quoted text present at line 42"


def check(name, cond, detail=""):
    if cond:
        print(f"OK {name}")
    else:
        FAILS.append(f"{name}: {detail}")
        print(f"FAIL {name}: {detail}")


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def make_ctx(root: Path):
    ctx = types.SimpleNamespace(
        root=root,
        reports_dir=root / "reports",
        state={},
        runs=lambda kind=None, round_no=None: [],
        round_rec=lambda r: {"field": ["a", "b"]},
        save_state=lambda: None,
    )
    ctx.reports_dir.mkdir(parents=True, exist_ok=True)
    return ctx


def synthetic_agg() -> dict:
    """One version, one judge session, one defect row (enough for the audit)."""
    observations = [
        ("judge_j1", "a", "b", {
            "score": 2, "basis": "correctness", "resolved": [],
            "introduced": [{"check": "J3", "tier": "writing", "severity": "minor",
                            "evidence": "alpha wording row"}]}),
    ]
    return {
        "field": ["a", "b"],
        "issue_census": pp.build_issue_census(observations, ["a", "b"],
                                              sessions_expected=1),
        "issue_rows": pp.build_issue_ledger_rows(observations, ["a", "b"]),
        "score_rows": [],
        "stats": {},
    }


def stub_audit(reason: str = GOOD_REASON, label: str = "TP") -> list:
    code = (
        "import json;"
        "d=json.load(open('defects.json'));"
        "v=[{'defect_id':x['defect_id'],'label':%r,'reason':%r} for x in d['defects']];"
        "json.dump({'verdicts':v},open('audit.json','w'))" % (label, reason)
    )
    return [sys.executable, "-c", code]


def audited_files(ctx) -> list:
    return sorted(p.name for p in ctx.reports_dir.glob("round1_auditedTP_*"))


def meta_of(ctx) -> dict:
    p = ctx.reports_dir / "round1_defect_audit.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


# ---------------------------------------------------------------------------
# F099 -- filler repetitions are not a usable reason
# ---------------------------------------------------------------------------
def test_f099() -> None:
    print("\n== F099: repeated filler tokens are rejected ==")
    for value in ("x x x", "ok ok ok", "n/a n/a", "x", "checked", "ok",
                  "abc abc abc"):
        check(f"F099 {value!r} is filler", not pp._defect_audit_reason_ok(value))
    for value in ("stub reason", "checked the quoted text",
                  "quoted text present at Results paragraph 2",
                  "text present at line 42"):
        check(f"F099 {value!r} is a real basis",
              pp._defect_audit_reason_ok(value))


# ---------------------------------------------------------------------------
# F100 -- a stored ok:true audit with an unlabelled row is not successful
# ---------------------------------------------------------------------------
def test_f100() -> None:
    print("\n== F100: incomplete stored audit is not reused as success ==")
    ctx = make_ctx(scratch("g6_f100_"))
    agg = synthetic_agg()
    first = pp.write_round_defect_audit(ctx, 1, agg=agg, agent_cmd=stub_audit(),
                                        timeout=60)
    check("F100 the first audit succeeds", first.get("ok") is True, first)
    check("F100 the first audit writes the TP-only family", bool(audited_files(ctx)),
          audited_files(ctx))
    meta = meta_of(ctx)
    meta["verdicts"][0]["label"] = ""
    (ctx.reports_dir / "round1_defect_audit.json").write_text(json.dumps(meta),
                                                              encoding="utf-8")
    again = pp.write_round_defect_audit(ctx, 1, agg=agg, agent_cmd=stub_audit(),
                                        timeout=60)
    check("F100 a stored unlabelled row is not a successful reuse",
          again.get("used") is True and again.get("reused") is True
          and again.get("ok") is False,
          {k: again.get(k) for k in ("used", "reused", "ok")})
    check("F100 the unlabelled row is counted, not silently dropped",
          again.get("incomplete") == 1 and again.get("tp") == 0,
          (again.get("incomplete"), again.get("tp")))
    check("F100 an incomplete stored audit writes no TP-only family",
          audited_files(ctx) == [], audited_files(ctx))
    check("F100 the stored record is rewritten with ok:false",
          meta_of(ctx).get("ok") is False, meta_of(ctx).get("ok"))


# ---------------------------------------------------------------------------
# F101 -- a failed re-audit removes the previous successful family
# ---------------------------------------------------------------------------
def test_f101() -> None:
    print("\n== F101: a failed re-audit leaves no stale auditedTP_* files ==")
    ctx = make_ctx(scratch("g6_f101_"))
    agg = synthetic_agg()
    first = pp.write_round_defect_audit(ctx, 1, agg=agg, agent_cmd=stub_audit(),
                                        timeout=60)
    check("F101 the first audit succeeds and writes the family",
          first.get("ok") is True and len(audited_files(ctx)) == 6,
          (first.get("ok"), audited_files(ctx)))
    failed = pp.write_round_defect_audit(ctx, 1, agg=agg,
                                         agent_cmd=[sys.executable, "-c", "pass"],
                                         timeout=60, force=True)
    check("F101 the forced re-audit fails", failed.get("ok") is False, failed)
    check("F101 the previous auditedTP family is gone", audited_files(ctx) == [],
          audited_files(ctx))
    check("F101 the round record says ok:false", meta_of(ctx).get("ok") is False,
          meta_of(ctx).get("ok"))


# ---------------------------------------------------------------------------
# F102 -- an un-removable old audit.json fails the attempt
# ---------------------------------------------------------------------------
def test_f102() -> None:
    print("\n== F102: an un-removable old audit.json is a failed attempt ==")
    ctx = make_ctx(scratch("g6_f102_"))
    agg = synthetic_agg()
    first = pp.write_round_defect_audit(ctx, 1, agg=agg, agent_cmd=stub_audit(),
                                        timeout=60)
    check("F102 the first audit succeeds", first.get("ok") is True, first)
    sandbox = ctx.reports_dir / "defect_audit_round1"
    check("F102 the first answer is on disk", (sandbox / "audit.json").is_file())

    real_unlink = Path.unlink

    def fail_unlink(self, *args, **kwargs):
        if self.name == "audit.json" and self.parent.name == "defect_audit_round1":
            raise OSError("simulated unlink failure")
        return real_unlink(self, *args, **kwargs)

    Path.unlink = fail_unlink
    try:
        # The agent writes NOTHING: pre-fix, the old answer is read as this
        # attempt's fresh verdicts.
        second = pp.write_round_defect_audit(
            ctx, 1, agg=agg, agent_cmd=[sys.executable, "-c", "pass"],
            timeout=60, force=True)
    finally:
        Path.unlink = real_unlink
    check("F102 an un-removable old answer fails the attempt",
          second.get("used") is True and second.get("ok") is False,
          {k: second.get(k) for k in ("used", "ok", "error")})
    check("F102 no stale verdict is accepted as this attempt's answer",
          second.get("tp") == 0 and second.get("incomplete") == 1
          and all(x["audit_label"] is None for x in second.get("labelled") or []),
          (second.get("tp"), second.get("incomplete"),
           [x["audit_label"] for x in second.get("labelled") or []]))
    check("F102 the failure is recorded on disk", meta_of(ctx).get("ok") is False,
          meta_of(ctx).get("ok"))
    check("F102 the previous submission is still archived as evidence",
          (sandbox / "audit.previous.json").is_file())


# ---------------------------------------------------------------------------
# F108 -- a symlinked audit.json is refused, not copied
# ---------------------------------------------------------------------------
def test_f108() -> None:
    print("\n== F108: a symlinked audit.json is refused ==")
    root = scratch("g6_f108_")
    ctx = make_ctx(root)
    secret_dir = scratch("g6_f108_secret_")
    secret = secret_dir / "host_secret.txt"
    secret.write_text("TOP-SECRET-HOST-CONTENT", encoding="utf-8")
    sandbox = ctx.reports_dir / "defect_audit_round1"
    sandbox.mkdir(parents=True)
    os.symlink(secret, sandbox / "audit.json")
    check("F108 the fixture answer is a symlink",
          (sandbox / "audit.json").is_symlink())
    _verdicts, info = pp.run_defect_audit_agent(
        ctx, 1, {"defects": [{"defect_id": "r1-D0001"}]},
        [sys.executable, "-c", "pass"], timeout=60)
    check("F108 the symlinked answer is refused",
          info.get("ok") is False and "regular file" in (info.get("error") or ""),
          info.get("error"))
    check("F108 the target is never copied into audit.previous.json",
          not (sandbox / "audit.previous.json").exists(),
          sorted(p.name for p in sandbox.iterdir()))
    leaked = []
    for p in sandbox.rglob("*"):
        if p.is_symlink() or not p.is_file():
            continue
        try:
            if "TOP-SECRET-HOST-CONTENT" in p.read_text(encoding="utf-8",
                                                        errors="replace"):
                leaked.append(str(p))
        except OSError:
            pass
    check("F108 no reports-tree file carries the host content", leaked == [], leaked)

    # Legitimate behaviour is preserved: a REGULAR previous answer is archived
    # before the attempt clears it (F169).
    ctx2 = make_ctx(scratch("g6_f108b_"))
    sandbox2 = ctx2.reports_dir / "defect_audit_round1"
    sandbox2.mkdir(parents=True)
    (sandbox2 / "audit.json").write_text(
        json.dumps({"verdicts": [{"defect_id": "r1-D0001", "label": "TP",
                                  "reason": GOOD_REASON}]}), encoding="utf-8")
    pp.run_defect_audit_agent(ctx2, 1, {"defects": [{"defect_id": "r1-D0001"}]},
                              [sys.executable, "-c", "pass"], timeout=60)
    check("F108 a regular previous answer is still archived",
          (sandbox2 / "audit.previous.json").is_file()
          and "r1-D0001" in (sandbox2 / "audit.previous.json").read_text(
              encoding="utf-8"),
          sorted(p.name for p in sandbox2.iterdir()))


def main() -> int:
    try:
        test_f099()
        test_f100()
        test_f101()
        test_f102()
        test_f108()
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)
    if FAILS:
        print(f"\n{len(FAILS)} g6_audit check(s) FAILED")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("\nAll g6_audit checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

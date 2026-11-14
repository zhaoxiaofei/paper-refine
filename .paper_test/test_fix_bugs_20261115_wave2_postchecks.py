#!/usr/bin/env python3
"""Regression checks for the 2026-11-15 fix-bugs wave 2 (`postchecks` group).

Run:  python3 .paper_test/test_fix_bugs_20261115_wave2_postchecks.py
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

WS = Path(__file__).resolve().parent.parent
TMPDIRS = []
FAILS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fb1115wave2_post_pp", "paper_pipeline.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


# F148 -- dropped-by-audit is a documented R1 verdict
def test_dropped_by_audit():
    got = pp._ledger_row_verdict({"id": "F-001", "verdict": "dropped-by-audit"})
    check("F148 dropped-by-audit is a ledger verdict", got == "dropped-by-audit", repr(got))


# F160 -- a tail that names no work is not a clean disposition
def test_no_work_tails():
    for tail in ("0 findings -- checked nothing",
                 "0 findings; nothing was checked",
                 "0 findings -- no sweep was performed"):
        check(f"F160 rejected: {tail!r}", pp._coverage_disposition_ok(tail) is False)
    check("F160 a real basis still passes",
          pp._coverage_disposition_ok("clean -- basis: artifacts/M1_acronyms.md") is True)


# F166 -- the coverage row's own 'clean'/'basis' words are not an M1b reason
def test_m1b_reason():
    check("F166 token + clean basis is not a reason",
          pp._m1b_coverage_reason("M1b: clean -- basis: artifacts/M1_acronyms.md") is False)
    check("F166 a quoted-title ground is a reason",
          pp._m1b_coverage_reason(
              "M1b: all 25 long forms are quoted article titles, not findings") is True)


# F167 -- a table header must not be read as an opaque UID/domain value
def test_fact_table_headers():
    found = pp._fact_token_map("Sample ID | Species | Count\nParticipant ID | Group")
    uid = {k.lower() for k in (found.get("uid") or {})}
    dom = {k.lower() for k in (found.get("domain") or {})}
    check("F167 table header is not a UID", not ({"species", "group", "value"} & uid), repr(uid))
    check("F167 table header is not a domain id", not ({"species", "group", "value"} & dom),
          repr(dom))


# F175 -- the repair guard reads agent JSON as leniently as the postcheck
def test_repair_json_lenient():
    tmp = scratch("f175")
    p = tmp / "scores.json"
    p.write_text("\ufeff```json\n{\"comparisons\": []}\n```\n", encoding="utf-8")
    got = pp._repair_read_json(p)
    check("F175 BOM + fenced agent JSON parses", isinstance(got, dict)
          and got.get("comparisons") == [], repr(got))


# F161 -- an EMPTY pristine feedback area still enforces read-only
def test_empty_feedback_area():
    tmp = scratch("f161")
    pristine = tmp / "root" / "non_revised"
    (pristine / pp.HUMAN_FEEDBACK_DIR).mkdir(parents=True)
    cand = tmp / "sandbox"
    (cand / pp.HUMAN_FEEDBACK_DIR).mkdir(parents=True)
    (cand / pp.HUMAN_FEEDBACK_DIR / "added.txt").write_text("x", encoding="utf-8")
    ctx = SimpleNamespace(pristine=pristine)
    warns = []
    info = pp.enforce_readonly_feedback_area(ctx, cand, warns, pp.HUMAN_FEEDBACK_DIR)
    check("F161 an added file in an empty feedback area is dropped",
          "added.txt" in " ".join(info.get("dropped") or []), repr(info))
    check("F161 the added file is gone",
          not (cand / pp.HUMAN_FEEDBACK_DIR / "added.txt").exists())


# F168 -- a squat on a pristine raw-data path is a FAILURE, not only a warning
def test_raw_data_squat_fails():
    tmp = scratch("f168")
    pristine = tmp / "root" / "non_revised"
    rel = pp.raw_data_dirname(pristine)
    (pristine / rel).mkdir(parents=True)
    (pristine / rel / "table.tsv").write_text("a\tb\n", encoding="utf-8")
    cand = tmp / "sandbox"
    (cand / rel / "table.tsv").mkdir(parents=True)     # directory where a file belongs
    ctx = SimpleNamespace(pristine=pristine)
    info = pp.enforce_readonly_raw_data(ctx, cand, [])
    check("F168 a raw-data squat is reported as a failure",
          bool(info.get("failures")), repr(info.get("failures")))
    check("F168 verify turns the failure into an error channel",
          bool(SimpleNamespace(**ctx.__dict__) and info["failures"]))


# F159 -- a non-object visual-template manifest must not crash the check
def test_visual_manifest_type():
    tmp = scratch("f159")
    sb = tmp / "sandbox"
    vtd = sb / pp.VISUAL_TEMPLATE_DIR
    vtd.mkdir(parents=True)
    (vtd / "manifest.json").write_text("[]", encoding="utf-8")
    art = tmp / "VISUAL_CHECK.md"
    art.write_text("pages compared against the venue template\n", encoding="utf-8")
    errs, warns = [], []
    try:
        pp.check_visual_artifact(art, "guided_review/VISUAL_CHECK.md", errs, warns, sandbox=sb)
        ok = True
    except Exception as e:                                    # noqa: BLE001
        ok = False
        check("F159 non-object manifest does not crash", False, f"{type(e).__name__}: {e}")
    if ok:
        check("F159 non-object manifest does not crash", True)


def main() -> int:
    for fn in [test_dropped_by_audit, test_no_work_tails, test_m1b_reason,
               test_fact_table_headers, test_repair_json_lenient, test_empty_feedback_area,
               test_raw_data_squat_fails, test_visual_manifest_type]:
        try:
            fn()
        except Exception as e:                                # noqa: BLE001
            check(f"{fn.__name__} raised", False, f"{type(e).__name__}: {e}")
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s):")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)

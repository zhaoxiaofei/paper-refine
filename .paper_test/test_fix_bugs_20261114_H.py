#!/usr/bin/env python3
"""Regression assertions for group H of the 2026-11-14 fix-bugs wave (F76-F85, F162).

Run:  python3 .paper_test/test_fix_bugs_20261114_H.py

Every check is a prompt-text or file-path invariant; the fixtures are temporary
directories only. Self-contained: no network, no repository writes.
"""
from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = HERE.parent
FAILS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"[ok ] {name}")
    else:
        print(f"[FAIL] {name}" + (f" -- {detail}" if detail else ""))
        FAILS.append(name)


def pipeline():
    if str(WS) not in sys.path:
        sys.path.insert(0, str(WS))
    for mod in [m for m in sys.modules if m == "paper_pipeline"]:
        del sys.modules[mod]
    return importlib.import_module("paper_pipeline")


def run() -> None:
    P = pipeline()
    with tempfile.TemporaryDirectory(prefix="fixbugs_h_") as td:
        sb = Path(td) / "sb"
        sb.mkdir()

        review = P.review_prompt(sb, "r1_guided_review", 1)
        audit = P.audit_prompt(sb, "r1_audit", 1)
        cold = P.cold_start_review_prompt(sb, "r1_cold_start_review", 1)
        integrate = P.integrate_prompt(sb, "r1_i1", 1, "a1", ["w1"])
        judge = P.judge_prompt(sb, "r1_judge_t1_j1", 1, "t1", 1, 2, ["v1"])
        rewrite = P.rewrite_prompt(sb, "r1_w1", 1)

        # F76: the identification-only prompts must not carry the editable
        # hand-off bullets unqualified.
        for name, text in (("review", review), ("audit", audit), ("cold", cold)):
            check(f"F76 {name}: read-only override follows the hand-off rule",
                  "THE HAND-OFF BULLETS ABOVE ARE REPORT-ONLY HERE" in text)
            check(f"F76 {name}: the override token is resolved",
                  "@@READ_ONLY_HANDOFF@@" not in text)
        for mode in ("readme", "off"):
            for name, fn in (
                ("review", lambda m: P.review_prompt(sb, "r1_guided_review", 1,
                                                     author_to_complete=m)),
                ("audit", lambda m: P.audit_prompt(sb, "r1_audit", 1,
                                                   author_to_complete=m)),
                ("cold", lambda m: P.cold_start_review_prompt(
                    sb, "r1_cold_start_review", 1, author_to_complete=m)),
            ):
                text = fn(mode)
                check(f"F76 {name} ({mode}): found/absent is report-only",
                      "write the fact into the document" in text
                      and "REPORTING the value (or the\nverified negative)" in text)

        # F77: ONE required DIFF_LEDGER schema, the postcheck's columns.
        first = integrate.split("=== LEDGER (required) ===")[1].split(
            "=== WHAT DOES NOT APPLY")[0]
        check("F77 integrate: the first required ledger defers to DIFF_LEDGER_RULE",
              "INTEGRATION DIFFERENCE LEDGER above" in first)
        check("F77 integrate: the pre-check column set is gone",
              "class (a)-(f)" not in first and "KEPT-BASE" not in first)
        check("F77 integrate: every postcheck ledger column is specified",
              all(col in integrate for col in P.INTEGRATION_LEDGER_COLUMNS))

        # F78: no provenance vocabulary in the judge prompt, and no blinding lie.
        check("F78 judge: legacy/token-increment vocabulary is gone",
              "LEGACY package" not in judge and "_revN" not in judge)
        check("F78 judge: the blinding rule still promises no version tokens",
              "no digests or version tokens" in judge)
        check("F78 judge: anonymization is stated where matching is explained",
              "every name you can see here is anonymized" in judge
              and "content-hash version token" in judge)

        # F79: content-identical is ONE candidate; the comparison is 0.
        check("F79 judge: byte-identical is score 0 with no evidence exception",
              "the comparison is 0 with an empty resolved list" in judge
              and "There is no evidence exception" in judge
              and "unless\na real difference in the admitted evidence" not in judge)

        # F80: an operator-supplied path or retry diagnostic must survive the
        # later @@...@@ substitution passes verbatim.
        diag = "DIAG-START @@MARKER_ROOT@@ and @@SELFCHECK@@ DIAG-END"
        token_dir = Path(td) / "sb-@@MARKER_ROOT@@_@@SELFCHECK@@"
        token_dir.mkdir()
        for name, text in (
            ("audit", P.audit_prompt(token_dir, "r1_audit", 1, prior_failure=diag)),
            ("integrate", P.integrate_prompt(token_dir, "r1_i1", 1, "a1", ["w1"],
                                             prior_failure=diag)),
            ("rewrite", P.rewrite_prompt(token_dir, "r1_w1", 1, prior_failure=diag)),
        ):
            check(f"F80 {name}: prior_failure text is verbatim data", diag in text)
            check(f"F80 {name}: the sandbox path is not rewritten",
                  str(token_dir.resolve()) in text)

        # F83: the cold-start prompt states WHERE and HOW the marker is written.
        check("F83 cold: marker location/HOW rule is rendered",
              "LOCATION, and it is part of the contract" in cold
              and "as the last ACTION" in cold)
        check("F83 cold: no unresolved marker token", "@@MARKER_ROOT@@" not in cold)

        # F84: a split reviewer sees ONE id namespace, coverage example included.
        split_a = P.review_prompt(sb, "r1_guided_review", 1, split="a",
                                  split_mode="phases")
        split_b = P.review_prompt(sb, "r1_guided_review_b", 1, split="b",
                                  split_mode="phases")
        check("F84 split A: coverage example uses FA ids",
              '"detail": "FA-003, FA-004"' in split_a
              and '"detail": "F-003, F-004"' not in split_a)
        check("F84 split B: coverage example uses FB ids",
              '"detail": "FB-003, FB-004"' in split_b
              and '"detail": "F-003, F-004"' not in split_b)

        # F162: the M24/GLOSSARY tables the postcheck reads are under artifacts/.
        sweeps = (WS / "paper-skills/paper-review/references/sweeps.md").read_text(
            encoding="utf-8")
        check("F162 sweeps: M24 artifact path is guided_review/artifacts/",
              "**Artifact.** `guided_review/artifacts/M24_concepts.md`" in sweeps
              and "`guided_review/artifacts/GLOSSARY.md` (decisions)" in sweeps)
        check("F162 sweeps: work/ copies are labelled seeds only",
              "the `work/` copies are working seeds only" in sweeps)
        check("F162 audit: names the reviewer's disposed artifacts table",
              "the reviewer's disposed\n   `guided_review/artifacts/M24_concepts.md`"
              in audit)
        check("F162 postcheck: DECISION_ARTIFACTS is the canonical artifacts/ path",
              "artifacts/M24_concepts.md" in P.DECISION_ARTIFACTS
              and "artifacts/GLOSSARY.md" in P.DECISION_ARTIFACTS)


def main() -> int:
    try:
        run()
    except Exception as exc:                                     # noqa: BLE001
        check("test_fix_bugs_20261114_H completed", False,
              f"{type(exc).__name__}: {exc}")
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL GROUP H CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

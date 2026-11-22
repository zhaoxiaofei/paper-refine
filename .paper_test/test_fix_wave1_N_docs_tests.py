#!/usr/bin/env python3
"""Regression checks for the documentation / test-quality candidates of the
2026-11-22 11:28 fix-bugs wave (batch N).

Run: python3 .paper_test/test_fix_wave1_N_docs_tests.py

  F38  the A8c check is no longer a tautology (`... or True`)
  F63  the guided-review e2e check names the post-rename run kinds
  F152 the F109 prompt checks assert on the RENDERED review prompt
  F169 the F023 test names the real shell backup writer
  F164 the README names the real PKG set (there is no PKG-13)
  F165 the README counts four PKG-6/7/8/9 classes, matching its enumeration
  F185 the test README names a CLI flag that exists (--no-cold-start-review)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS))

import paper_pipeline as pp  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def text(rel):
    return (WS / rel).read_text(encoding="utf-8")


def main() -> int:
    focused = text(".paper_test/test_focused_audit_2026_1009.py")
    check("F38 the A8c check is not a tautology",
          "or True)" not in focused
          and "any(a in e for e in errs_fw for a in content_artifacts)" in focused)

    profile_test = text(".paper_test/test_execution_profile.py")
    check("F63 the e2e check names guided_review",
          '{"guided_review", "guided_review_b", "review"} & set(kinds)' in profile_test)
    kinds = ["guided_review"]
    check("F63 a leaked guided review now fails the old assertion",
          bool(({"guided_review", "guided_review_b", "review"} & set(kinds))))

    g7 = text(".paper_test/test_fix_bugs_20261119_g7_docs_config.py")
    check("F152 the F109 checks use the rendered prompt",
          "pp.review_prompt(scratch(\"f109\"), \"r1_guided_review\", 1)" in g7)
    sb = Path(tempfile.mkdtemp(prefix="f109-"))
    rendered = pp.review_prompt(sb, "r1_guided_review", 1)
    check("F152 the rendered review prompt names M1-M36 and J1-J5",
          "mechanical sweeps M1–M36" in rendered and "passes J1–J5" in rendered)

    readme = text("README.md")
    check("F164 the README names the real PKG range",
          "PKG-11 to PKG-26" not in readme
          and "PKG-11, PKG-12, PKG-14 to PKG-26" in readme)
    check("F165 the README counts four classes", "four classes of statement" in readme)

    installer = text("install_agent_tooling.sh")
    check("F169 the F023 check names the real shell backup writer",
          "set -o noclobber" in installer and "cp -p --" not in installer)

    test_readme = text(".paper_test/README.md")
    check("F185 the test README names the real flag",
          "(probe off," not in test_readme
          and "`--no-cold-start-review`" in test_readme)

    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL N-BATCH DOCS/TEST CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

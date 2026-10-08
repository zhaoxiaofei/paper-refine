#!/usr/bin/env python3
"""The skill scripts' EVIDENCE-area sets are the pipeline's set.

`paper_pipeline.EVIDENCE_DIRNAMES` names the READ-ONLY input areas
(`raw_data/`, legacy `raw_figs/`, `human_review_feedback/` and, since the LLM
review mode, `llm_review_feedback/`). The bundled skill scripts carry their own
copies of that set, and several of them say so in a comment ("keep in step with
paper_pipeline.EVIDENCE_DIRNAMES") -- but the copies were not extended when
`llm_review_feedback/` was added, with real consequences:

  * `revision_token.py` treated a 7-hex token inside `llm_review_feedback/` as
    the package's OWN naming evidence, so the paper-revise skill raised its
    "the package was edited after its token was applied" alarm on a package the
    pipeline's own `revision_token_for_dir()` reads as consistent;
  * `count_words.py` counted an LLM review against the submission's
    abstract/main-text limits instead of refusing it as evidence.

This suite fails on the stale sets and pins the two observable behaviours. It is
the cross-implementation guard for the invariant, so the next evidence area
cannot be added to one side only.

Run:  python3 .paper_test/test_skill_evidence_dirs.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_evdirs", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_evdirs"] = nb
spec.loader.exec_module(nb)

SKILL_SCRIPTS = [
    ("paper-revise", "revision_token.py"),
    ("paper-review", "convert_corpus.py"),
    ("paper-review", "count_words.py"),
    ("paper-review", "enumerate_conventions.py"),
    ("paper-review", "extract_acronyms.py"),
    ("paper-review", "extract_citations.py"),
    ("paper-review", "extract_numbers.py"),
    ("paper-review", "extract_occurrences.py"),
]
TOKEN_SCRIPT = WS / "paper-skills" / "paper-revise" / "scripts" / "revision_token.py"
COUNT_SCRIPT = WS / "paper-skills" / "paper-review" / "scripts" / "count_words.py"
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    import shutil
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def skill_set(script: Path) -> set:
    """The EVIDENCE-area set a bundled skill script defines."""
    mod_spec = importlib.util.spec_from_file_location(f"skill_{script.stem}", str(script))
    mod = importlib.util.module_from_spec(mod_spec)
    sys.modules[f"skill_{script.stem}"] = mod
    mod_spec.loader.exec_module(mod)
    names = set()
    for attr in ("EVIDENCE_DIRNAMES", "EVIDENCE_DIRS"):
        got = getattr(mod, attr, None)
        if got is not None:
            names |= set(got)
    return names


def test_sets_agree():
    print("== the skill scripts name exactly the pipeline's evidence areas ==")
    want = set(nb.EVIDENCE_DIRNAMES)
    check("the pipeline carries llm_review_feedback as an evidence area",
          "llm_review_feedback" in want, str(sorted(want)))
    for pkg, name in SKILL_SCRIPTS:
        script = WS / "paper-skills" / pkg / "scripts" / name
        got = skill_set(script)
        check(f"{pkg}/scripts/{name} names the pipeline's evidence areas",
              got == want, f"{sorted(got)} vs {sorted(want)}")


def test_token_and_count_agree():
    print()
    print("== an llm_review_feedback/ name is evidence in both implementations ==")
    tmp = scratch("paper_evdirs_pkg_")
    pkg = tmp / "pkg"
    (pkg / "llm_review_feedback").mkdir(parents=True)
    (pkg / "ms-a.md").write_text("manuscript body text\n", encoding="utf-8")
    (pkg / "llm_review_feedback" / "review-4f3a9c1.txt").write_text(
        "the LLM review: figure 2's legend is wrong\n", encoding="utf-8")
    script = subprocess.run([sys.executable, str(TOKEN_SCRIPT), str(pkg), "--json"],
                            capture_output=True, text=True)
    check("revision_token.py --json succeeds", script.returncode == 0, script.stderr[-200:])
    info = json.loads(script.stdout)
    pipe = nb.revision_token_for_dir(pkg)
    check("a 7-hex token inside llm_review_feedback/ is NOT naming evidence",
          info["hex_tokens"] == [] and info["tokens_seen"] == ["a"],
          json.dumps({"hex": info["hex_tokens"], "seen": info["tokens_seen"]}))
    check("the tool and the pipeline derive the same token and naming evidence",
          info["token"] == pipe["token"] and info["hex_tokens"] == pipe["hex_tokens"]
          and info["tokens_seen"] == pipe["tokens_seen"],
          json.dumps({"tool": info, "pipeline": pipe})[:300])
    counted = subprocess.run([sys.executable, str(COUNT_SCRIPT),
                              str(pkg / "llm_review_feedback" / "review-4f3a9c1.txt")],
                             capture_output=True, text=True)
    check("count_words.py refuses an llm_review_feedback/ file as evidence",
          counted.returncode == 1 and "evidence" in counted.stderr.lower(),
          (counted.stdout + counted.stderr)[-200:])
    print()


def main() -> int:
    try:
        test_sets_agree()
        test_token_and_count_agree()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL EVIDENCE-AREA AGREEMENT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

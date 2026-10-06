#!/usr/bin/env python3
"""A crash mid-write must never leave a file that later runs trust.

Run:  python3 .paper_test/test_atomic_prompts.py

Every stage sandbox is considered "already materialized" from the EXISTENCE of
its `PROMPT.md` (`if not prompt.is_file(): ... prompt.write_text(...)`), and the
venue README is rewritten in place by `add-venue`. A plain `Path.write_text`
truncates the destination first, so a crash between the truncate and the write
leaves a PARTIAL file that the existence check then freezes in place -- the next
invocation hands the agent a truncated prompt (or publishes a truncated venue
list) and no digest check ever notices. This suite pins:

  * the crash behaviour of the atomic writer itself: a writer that dies
    half-way leaves NO destination file and no temporary behind;
  * the structural rule: no `X.write_text(...)` may sit inside an
    `if not X.is_file()/exists():` guard in paper_pipeline.py (those writes go
    through `write_text_atomic`).
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_atomic_prompts",
                                              str(WS / "paper_pipeline.py"))
pd = importlib.util.module_from_spec(spec)
sys.modules["paper_atomic_prompts"] = pd
spec.loader.exec_module(pd)

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(F"OK {name}")
    else:
        FAILS.append(F"{name}: {detail}")
        print(F"FAIL {name}: {detail}")


def guarded_plain_writes(tree) -> list:
    """[(line, target, attr)] for non-atomic writes inside negated-existence guards."""
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
                and isinstance(test.operand, ast.Call)):
            continue
        call = test.operand
        if not (isinstance(call.func, ast.Attribute)
                and call.func.attr in ("is_file", "exists")):
            continue
        guarded = ast.unparse(call.func.value)
        for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr in ("write_text", "write_bytes")
                    and ast.unparse(inner.func.value) == guarded):
                bad.append((node.lineno, guarded, inner.func.attr))
    return bad


def main() -> int:
    # ---- 1. the atomic writer survives a crash with no half-written file ----
    root = Path(tempfile.mkdtemp(prefix="atomic_prompt_test_"))
    try:
        dst = root / "PROMPT.md"
        tmp = pd.tmp_path_for(dst)

        def crash_half_way(p: Path) -> None:
            p.write_text("half a pro", encoding="utf-8")
            raise RuntimeError("simulated crash")

        try:
            pd._atomic_write_bytes(tmp, dst, crash_half_way)
            check("the crashing writer re-raises", False, "no exception")
        except RuntimeError:
            check("the crashing writer re-raises", True)
        check("a crash leaves NO destination file for the is_file() guard to trust",
              not dst.exists(), dst)
        check("a crash leaves no temporary file behind",
              not list(root.glob("*.tmp")), sorted(p.name for p in root.iterdir()))

        pd.write_text_atomic(dst, "the whole prompt\n")
        check("a completed atomic write lands the full text",
              dst.read_text(encoding="utf-8") == "the whole prompt\n")
        # The existence guard now sees a COMPLETE file, and a later write is
        # still free to replace it atomically.
        pd.write_text_atomic(dst, "rewritten\n")
        check("a later atomic write replaces the file in place",
              dst.read_text(encoding="utf-8") == "rewritten\n")
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)

    # ---- 2. the structural rule in the pipeline ----------------------------
    tree = ast.parse((WS / "paper_pipeline.py").read_text(encoding="utf-8"))
    bad = guarded_plain_writes(tree)
    check("no non-atomic write hides behind an if-not-exists guard",
          not bad, bad)
    atomic_sites = [n.lineno for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "write_text_atomic"]
    # 18 of the 19 call sites are the stage prompts / the venue README row
    # (the pre-fix tree had 10); a revert of the guard fix drops this sharply.
    check("the stage-prompt writers go through write_text_atomic",
          len(atomic_sites) >= 18, len(atomic_sites))

    if FAILS:
        print(F"\n{len(FAILS)} atomic-prompt check(s) FAILED")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("\nAll atomic-prompt checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""F47 regression: usage/validation errors exit 2, matching README's exit table.

OnlySpec.validate (agents/run/retry --only) and the redline/track --round and
--version validators are operator-input errors. Run: python3 .paper_test/test_fix_bugs_20261114_R.py
"""
from __future__ import annotations
import importlib.util, shutil, subprocess, sys, tempfile
from pathlib import Path
WS = Path(__file__).resolve().parent.parent
FAILS = []
def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)
_spec = importlib.util.spec_from_file_location("paper_pipeline_fixbugs_r", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(_spec)
sys.modules["paper_pipeline_fixbugs_r"] = nb
_spec.loader.exec_module(nb)
def exit_code_of(fn):
    try:
        fn()
    except SystemExit as exc:
        return exc.code
    return None
def test_validate_unit():
    only = nb.OnlySpec(); only.rounds = {4}
    check("OnlySpec.validate refuses an out-of-range --only round with exit 2",
          exit_code_of(lambda: only.validate(3)) == 2)
def test_cli():
    tmp = Path(tempfile.mkdtemp(prefix="fixbugs_r_"))
    try:
        src = tmp / "src"; src.mkdir()
        (src / "manuscript.md").write_text("Abstract\n\n" + ("word " * 100).strip() + "\n\nIntroduction\n\n" + ("text " * 200).strip() + "\n", encoding="utf-8")
        root = tmp / "root"
        cli = lambda *a: subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *a], capture_output=True, text=True, timeout=300)
        p = cli("setup", "--source", str(src), "--root", str(root), "--rounds", "3")
        check("3-round fixture root", p.returncode == 0, (p.stdout + p.stderr)[-200:])
        q = cli("agents", "--root", str(root), "--only", "4")
        out = q.stdout + q.stderr
        check("`agents --only 4` exits 2 (usage error)", q.returncode == 2 and "do not exist" in out, f"rc={q.returncode}")
        q = cli("run", "--root", str(root), "--only", "4", "--manual")
        check("`run --only 4` exits 2 (usage error)", q.returncode == 2, f"rc={q.returncode}")
        for cmd, args in (("redline", ["--round", "0"]), ("track", ["--round", "0"]),
                          ("redline", ["--version", "zz"]), ("track", ["--version", "zz"])):
            q = cli(cmd, "--root", str(root), *args)
            check(f"`{cmd} {' '.join(args)}` exits 2 (usage error)",
                  q.returncode == 2, f"rc={q.returncode} {(q.stdout + q.stderr)[-160:]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
if __name__ == "__main__":
    test_validate_unit(); test_cli()
    sys.exit(1 if FAILS else 0)

#!/usr/bin/env python3
"""`decide` publishes <root>/final_clean_version/ with the generation counter +1.

Run:  python3 .paper_test/test_final_clean_version.py

The user's naming convention carries a generation counter in the second
dash-separated filename field (cnb-11-2-mainText-b.docx -> field "11"). The
clean version published by `decide`/`run-decide` must increment that counter by
one (guarded: a missing or non-numeric field keeps the name), repoint the
references inside the text files to the new names, stay byte-stable across a
second `decide`, and be usable directly as the next run's --source.

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_fcv", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_fcv"] = nb
spec.loader.exec_module(nb)

STUB = Path(__file__).resolve().parent / "stub_agent.py"
STUB_JUDGE = Path(__file__).resolve().parent / "stub_judge.py"
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


def write(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data, encoding="utf-8")


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print()
    print("== FCV: final_clean_version increments the cnb-<N>- counter ==")
    tmp = scratch("paper_fcv_")
    source = tmp / "source"
    write(source / "cnb-11-2-mainText-b.md", "Abstract\n\n" + ("word " * 100).strip()
          + "\n\nIntroduction\n\n" + ("text " * 200).strip() + "\n\nMethods\n\nx\n")
    write(source / "cnb-11-3-supp-b.tex",
          "\\documentclass{article}\n"
          "\\addbibresource{cnb-11-3-supp-b.bib}\n"
          "\\begin{document}\nsupplementary\n\\end{document}\n")
    write(source / "cnb-11-3-supp-b.bib", "@article{x}\n")
    write(source / "cnb-11-nr-reporting-summary-b.md", "reporting summary\n")
    write(source / "refs.bib", "@article{y}\n")
    write(source / "notes-final.md", "notes\n")
    root = tmp / "root"

    def run(argv):
        return subprocess.run([sys.executable, str(WS / "paper_pipeline.py")] + argv,
                              capture_output=True, text=True, timeout=900)

    proc = run(["setup", "--source", str(source), "--root", str(root), "--rounds", "1",
                "--rewrites", "0", "--revises", "1", "--judges", "1"])
    check("FCV setup succeeds", proc.returncode == 0, (proc.stdout + proc.stderr)[-200:])
    proc = run(["run-decide", "--root", str(root),
                "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
                "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
                "--retries", "0"])
    out = proc.stdout + proc.stderr
    check("FCV run-decide succeeds", proc.returncode == 0, out[-300:])
    final = root / "final_clean_version"
    names = sorted(p.name for p in final.rglob("*") if p.is_file()) if final.is_dir() else []
    check("FCV final_clean_version exists and carries files", bool(names), str(names))
    check("FCV every cnb-11-* generation counter became cnb-12-*",
          any(n.startswith("cnb-12-") for n in names)
          and not any(n.startswith("cnb-11-") for n in names), str(names))
    check("FCV the incremented reporting-summary name is present",
          any(n.startswith("cnb-12-nr-reporting-summary") for n in names), str(names))
    check("FCV a name whose second dash-field is not an integer is untouched",
          "refs.bib" in names and "notes-final.md" in names)
    tex = next((p for p in final.rglob("*.tex")), None)
    tex_text = tex.read_text(encoding="utf-8") if tex else ""
    check("FCV the LaTeX reference was repointed to the new bib name",
          "cnb-12-3-supp" in tex_text and "cnb-11-" not in tex_text, tex_text[:120])
    check("FCV decide announced the increment",
          "filename counter" in out and "incremented" in out, out[-300:])
    decision = json.loads((root / "reports" / "decision.json").read_text(encoding="utf-8"))
    info = decision["final"]["final_clean_version"]
    check("FCV decision.json records the renamed count and both digests",
          info.get("renamed", 0) >= 4 and info.get("pin_digest") != info.get("digest"),
          json.dumps(info)[:200])
    # idempotence: a second decide leaves the tree byte-identical (no churn)
    before = sorted(nb.sha256_file(p) for p in final.rglob("*") if p.is_file())
    proc = run(["decide", "--root", str(root)])
    after = sorted(nb.sha256_file(p) for p in final.rglob("*") if p.is_file())
    check("FCV a second decide leaves final_clean_version unchanged",
          before == after and "unchanged" in (proc.stdout + proc.stderr), out[-120:])
    superseded = list((root / "_superseded").glob("final_clean_version.*")) \
        if (root / "_superseded").is_dir() else []
    check("FCV no superseded copy was archived on the repeat run", not superseded,
          str(superseded))
    # the incremented package is a usable --source for the next run
    proc = run(["setup", "--source", str(final), "--root", str(tmp / "next_root"),
                "--rounds", "1"])
    check("FCV the incremented package seeds the next pipeline run",
          proc.returncode == 0, (proc.stdout + proc.stderr)[-200:])
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL FINAL-CLEAN-VERSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

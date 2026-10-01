#!/usr/bin/env python3
"""Read-only evidence areas are SYMLINKED into sandboxes, not copied.

raw_data/ and human_review_feedback/ are inputs: nothing may write them and
every stage sandbox needs them, so each sandbox's `non_revised/` carries
RELATIVE symlinks to the root's canonical copy (`<root>/non_revised/<area>`),
which is chmod-protected read-only. That removes gigabytes of duplication
without weakening the guarantees:

  * the content is identical and readable through the link;
  * a write through the link fails (permission) instead of corrupting every
    sandbox's evidence, and the canonical copy keeps its modes;
  * the INPUT manifests (and every corpus/view walk) FOLLOW directory links,
    so identity, tampering checks and judge views still see the evidence;
  * a platform without symlink support falls back to real copies;
  * `enforce_readonly_*` never writes THROUGH a link, and `rmtree_force` never
    deletes the canonical store.

Run:  python3 .paper_test/test_evidence_symlinks.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paper_syml", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_syml"] = nb
spec.loader.exec_module(nb)

STUB = WS / ".paper_test" / "stub_agent.py"
FAILS = []
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def make_source(tmp: Path) -> Path:
    src = tmp / "source"
    (src / "raw_data").mkdir(parents=True)
    (src / "raw_data" / "table.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (src / "raw_data" / "readme.txt").write_text("evidence\n", encoding="utf-8")
    (src / "human_review_feedback").mkdir()
    (src / "human_review_feedback" / "reviewer1.txt").write_text(
        "reviewer comment\n", encoding="utf-8")
    (src / "manuscript.md").write_text("# Title\n\ntext\n", encoding="utf-8")
    return src


def setup_root(tmp: Path) -> tuple:
    src = make_source(tmp)
    root = tmp / "root"
    r = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
                        "--source", str(src), "--root", str(root),
                        "--rounds", "1", "--judges", "1",
                        "--rewrites", "1", "--revises", "0", "--integrators", "0"],
                       capture_output=True, text=True, timeout=600)
    check("setup succeeds on a corpus with evidence areas", r.returncode == 0,
          (r.stdout + r.stderr)[-300:])
    ctx = nb.Ctx(root)
    ctx.load()
    return src, root, ctx


def test_linked_sandbox_input(tmp: Path, root: Path, ctx):
    print()
    print("== the sandbox input links the canonical evidence areas ==")
    canon = ctx.pristine / "raw_data"
    check("the root keeps ONE canonical copy of raw_data",
          canon.is_dir() and not canon.is_symlink(), str(canon))
    if not IS_ROOT:
        modes = [stat.S_IMODE(p.stat().st_mode) for p in [canon, *canon.iterdir()]]
        check("the canonical evidence areas are chmod-protected read-only",
              all(m & 0o222 == 0 for m in modes), str([oct(m) for m in modes]))
    dst = tmp / "sb_non_revised"
    info = nb.ensure_pristine_input(ctx, dst)
    check("evidence areas become RELATIVE symlinks to the canonical copy",
          info["rebuilt"] is True
          and (dst / "raw_data").is_symlink()
          and not os.path.isabs(os.readlink(dst / "raw_data"))
          and (dst / "raw_data").resolve() == canon.resolve()
          and (dst / "human_review_feedback").is_symlink(),
          str(info))
    check("the manuscript part is a REAL copy (stages may copy/edit it)",
          (dst / "manuscript.md").is_file() and not (dst / "manuscript.md").is_symlink())
    check("the evidence is readable through the link",
          (dst / "raw_data" / "table.csv").read_text(encoding="utf-8") == "a,b\n1,2\n"
          and (dst / "human_review_feedback" / "reviewer1.txt").is_file())
    check("no disk duplication (same inode through the link)",
          (dst / "raw_data" / "table.csv").stat().st_ino
          == (canon / "table.csv").stat().st_ino)
    again = nb.ensure_pristine_input(ctx, dst)
    check("ensure_pristine_input is idempotent (no rebuild when intact)",
          again["rebuilt"] is False, str(again))
    if not IS_ROOT:
        try:
            (dst / "raw_data" / "table.csv").write_text("hacked\n", encoding="utf-8")
            blocked = False
        except OSError:
            blocked = True
        check("a write through the link is BLOCKED (canonical store protected)",
              blocked and (canon / "table.csv").read_text(encoding="utf-8") == "a,b\n1,2\n")
    check("input manifests FOLLOW the links (evidence is part of the identity)",
          "raw_data/table.csv" in (nb.hash_manifest(dst, follow_dir_links=True).get("files") or {})
          and "human_review_feedback/reviewer1.txt"
          in (nb.hash_manifest(dst, follow_dir_links=True).get("files") or {}))


def test_fallback_without_symlinks(tmp: Path, ctx):
    print()
    print("== a platform without symlinks falls back to real copies ==")
    dst = tmp / "sb_copy_mode"
    real_symlink = nb.os.symlink
    try:
        nb.os.symlink = lambda *a, **k: (_ for _ in ()).throw(OSError("symlinks disabled"))
        info = nb.ensure_pristine_input(ctx, dst)
    finally:
        nb.os.symlink = real_symlink
    check("the areas are copied and the fallback is reported",
          info["linked"] == [] and sorted(info["copied"]) == ["human_review_feedback", "raw_data"]
          and info["fallback_reason"] and (dst / "raw_data").is_dir()
          and not (dst / "raw_data").is_symlink(), str(info))
    check("the copied evidence is readable and complete",
          (dst / "raw_data" / "table.csv").read_text(encoding="utf-8") == "a,b\n1,2\n")


def test_tamper_detection_and_enforcement(tmp: Path, root: Path, ctx):
    print()
    print("== tampering is still detectable; enforcement never writes through a link ==")
    # A COPY-mode sandbox: the manifest follows links, and a modified copy is
    # reported by input_mismatches exactly as before.
    sb = root / "runs" / "r1_w1"
    (sb / "non_revised" / "raw_data").mkdir(parents=True)
    shutil.copy2(ctx.pristine / "raw_data" / "table.csv", sb / "non_revised" / "raw_data")
    (sb / "non_revised" / "human_review_feedback").mkdir()
    shutil.copy2(ctx.pristine / "human_review_feedback" / "reviewer1.txt",
                 sb / "non_revised" / "human_review_feedback")
    rec = {"id": "r1_w1", "sandbox": "runs/r1_w1",
           "inputs_manifest": {"non_revised": nb.hash_manifest(sb / "non_revised",
                                                               follow_dir_links=True)}}
    check("an intact input reports no mismatch", nb.input_mismatches(ctx, rec) == [],
          str(nb.input_mismatches(ctx, rec)))
    p = sb / "non_revised" / "raw_data" / "table.csv"
    p.chmod(0o600)
    p.write_text("changed\n", encoding="utf-8")
    check("a modified input is reported", bool(nb.input_mismatches(ctx, rec)))
    # A package that carries the canonical link onward: enforcement must verify
    # it and never write through it.
    pkg = tmp / "pkg"
    pkg.mkdir()
    os.symlink(os.path.relpath(ctx.pristine / "raw_data", pkg), pkg / "raw_data")
    warns = []
    info = nb.enforce_readonly_raw_data(ctx, pkg, warns)
    check("enforce_readonly_raw_data accepts the canonical link without writing",
          info.get("linked") is True and (pkg / "raw_data").is_symlink()
          and (ctx.pristine / "raw_data" / "table.csv").read_text(encoding="utf-8")
          == "a,b\n1,2\n", str(info))
    # A corpus walk (judge views, manifests) must see through the link.
    files = dict(nb.corpus_dir_view_files(pkg))
    check("corpus walks follow the linked evidence area",
          any(r.endswith("table.csv") for r in files), str(files))


def test_prune_keeps_the_store(tmp: Path, root: Path, ctx):
    print()
    print("== deleting a sandbox never deletes the canonical store ==")
    sb = tmp / "sb_delete"
    nb.ensure_pristine_input(ctx, sb)
    check("the sandbox links the store", (sb / "raw_data").is_symlink())
    nb.rmtree_force(sb)
    check("the sandbox is gone, the store survives",
          not sb.exists() and (ctx.pristine / "raw_data" / "table.csv").is_file())


def test_end_to_end_rewrite(tmp: Path, root: Path, ctx):
    print()
    print("== a real stage run works with the linked input ==")
    r = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "run",
                        "--root", str(root), "--only", "r1_w1", "--jobs", "1",
                        "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
                        "--retries", "0"],
                       capture_output=True, text=True, timeout=1800)
    out = r.stdout + r.stderr
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    check("the rewrite stage itself completes (the partial --only round stays incomplete)",
          (state["runs"].get("r1_w1") or {}).get("status") == "done", out[-400:])
    sb = root / "runs" / "r1_w1"
    check("the stage sandbox's evidence areas are symlinks to the store",
          (sb / "non_revised" / "raw_data").is_symlink()
          and (sb / "non_revised" / "raw_data").resolve()
          == (ctx.pristine / "raw_data").resolve(), out[-200:])
    check("the store is intact after the run",
          (ctx.pristine / "raw_data" / "table.csv").read_text(encoding="utf-8") == "a,b\n1,2\n")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="paper_syml_"))
    _src, root, ctx = setup_root(tmp)
    test_linked_sandbox_input(tmp, root, ctx)
    test_fallback_without_symlinks(tmp, ctx)
    test_tamper_detection_and_enforcement(tmp, root, ctx)
    test_prune_keeps_the_store(tmp, root, ctx)
    test_end_to_end_rewrite(tmp, root, ctx)
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL EVIDENCE-SYMLINK CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

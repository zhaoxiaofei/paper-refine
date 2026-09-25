#!/usr/bin/env python3
"""`raw_data/` is READ-ONLY, recursively -- and the pipeline must still work.

Run:  python3 .paper_test/test_raw_data_readonly.py

The 2026-09-25 `decide` runs died inside `publish_final_clean` with
`PermissionError` on `final_clean_version.tmp/raw_data/...` and then again while
deleting that temp tree: the operator's raw-data directory is read-only BY
CONTRACT (the corpus rule is "raw data is an input: never edit, rename, add or
drop anything inside it"), often enforced with `chmod -R a-w`, and every
pipeline-owned copy inherits those modes. Asserts, with a fixture whose
`raw_data/` is chmod 0500 (dirs) / 0400 (files):

  * the permission helpers: `make_tree_writable` hands back the write bits,
    skips raw_data entirely, and `restore_modes` puts back exactly what it
    changed; `rmtree_force` deletes a tree that a plain `shutil.rmtree` cannot;
  * `setup` ingests such a corpus without a single permission error, keeps the
    read-only modes (they are the author's protection, not an accident), and the
    formatter never even opens a file under raw_data (a deliberately malformed
    `.docx` there is not reported as a failed repair);
  * a full stub round + `decide` publishes `final_clean_version/`: the manuscript
    filenames get their +1 generation counter, while raw_data keeps its names,
    its bytes and its read-only modes (a counter-looking file there is NOT
    renamed), with no `final_clean_version.tmp` left behind and a repeat `decide`
    reporting `unchanged`;
  * the ONE sanctioned write inside raw_data (restoring a package from the
    pristine original) still works when the file is read-only: `enforce_/
    verify_readonly_raw_data` restores the bytes, drops an added file, and
    leaves the read-only modes in place;
  * `retry` rebuilds a sandbox whose raw_data is read-only and `prune` deletes
    the read-only-containing sandboxes, both without permission errors.

Root never sees these failures (permission bits do not stop root), so the
mode-specific assertions are reported as `[skip]` there -- the content
assertions always run.
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
spec = importlib.util.spec_from_file_location("paper_rawdata", str(WS / "paper_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["paper_rawdata"] = nb
spec.loader.exec_module(nb)

STUB = WS / ".paper_test" / "stub_agent.py"
STUB_JUDGE = WS / ".paper_test" / "stub_judge.py"
FAILS = []
TMPDIRS = []
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def skip(name, why):
    print(f"[skip] {name}  -- {why}")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        nb.rmtree_force(tmp, ignore_errors=True)


def cli(*argv, timeout=900):
    return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *map(str, argv)],
                          capture_output=True, text=True, timeout=timeout)


def write(p: Path, data: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data, encoding="utf-8")


def lock_tree(root: Path, dir_mode=0o500, file_mode=0o400) -> None:
    """Make a tree read-only the way the operator does (`chmod -R a-w`)."""
    for p in sorted(root.rglob("*"), key=lambda q: len(q.parts), reverse=True):
        os.chmod(p, dir_mode if p.is_dir() else file_mode)
    os.chmod(root, dir_mode)


def modes_of(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        out[p.relative_to(root).as_posix()] = stat.S_IMODE(p.stat().st_mode)
    return out


def digests_of(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = nb.sha256_file(p)
    return out


def raw_data_dirs(sb: Path) -> list:
    """Every raw-data directory inside one sandbox (they sit under base/,
    non_revised/, self/, others/<vid>/, ... -- never at the sandbox root)."""
    if not sb.is_dir():
        return []
    return [p for p in sorted(sb.rglob("*"))
            if p.is_dir() and p.name in nb.RAW_DATA_DIRNAMES and p.parent != sb.parent]


def same_tree(a: Path, b: Path) -> bool:
    return digests_of(a) == digests_of(b) and modes_of(a) == modes_of(b)


def make_source(tmp: Path, name: str = "src", with_docx_trap: bool = True) -> Path:
    """A tiny corpus whose raw_data/ is read-only (and holds traps).

    `with_docx_trap` adds a malformed .docx to raw_data: the formatter must never
    open it (raw data is an input). The round fixtures leave it out, because a
    .docx in the corpus makes the visual-inspection postcheck demand a rendered
    page from the offline stub agent -- a different rule, unrelated to
    permissions.
    """
    src = tmp / name
    write(src / "cnb-13-2-mainText-671cca0.md",
          "Abstract\n\n" + ("word " * 60).strip() + "\n\nIntroduction\n\n"
          + ("text " * 120).strip() + "\n\nMethods\n\nx\n")
    write(src / "cnb-13-1-coverLetter-671cca0.md",
          "Dear Editor,\n\n" + ("persuade " * 320).strip() + "\n\nSincerely,\nA. Author\n")
    raw = src / "raw_data"
    write(raw / "bench-results-26-07-15.tex",
          "% builder\n\\input{../cnb-13-2-mainText-671cca0.md}\n")
    write(raw / "cnb-13-data.csv", "sample,value\na,1\n")
    if with_docx_trap:
        write(raw / "broken.docx", "this is not an OOXML package\n")
    lock_tree(raw)
    return src


# =====================================================================
# RO1 — the permission helpers
# =====================================================================

def test_helpers():
    print()
    print("== RO1: write-bit helpers and force-rmtree ==")
    check("RO1 raw-data paths are recognised in both spellings",
          nb.is_raw_data_rel("raw_data/x/y.csv") and nb.is_raw_data_rel("raw_figs/a.pdf")
          and not nb.is_raw_data_rel("figures/raw_data-ish.csv")
          and not nb.is_raw_data_rel("ms.md"))
    tmp = scratch("paper_ro_helper_")
    pkg = tmp / "pkg"
    (pkg / "raw_data").mkdir(parents=True)
    write(pkg / "ms.tex", "x\n")
    write(pkg / "raw_data" / "d.csv", "a\n")
    lock_tree(pkg)
    plan = nb.make_tree_writable(pkg, skip_top=nb.RAW_DATA_DIRNAMES)
    check("RO1 make_tree_writable clears the blocking bits", bool(plan)
          and os.access(pkg / "ms.tex", os.W_OK))
    check("RO1 ... and never touches raw_data",
          stat.S_IMODE((pkg / "raw_data").stat().st_mode) == 0o500
          and stat.S_IMODE((pkg / "raw_data" / "d.csv").stat().st_mode) == 0o400,
          f"{oct(stat.S_IMODE((pkg / 'raw_data').stat().st_mode))} "
          f"{oct(stat.S_IMODE((pkg / 'raw_data' / 'd.csv').stat().st_mode))}")
    nb.restore_modes(plan)
    check("RO1 restore_modes puts every recorded mode back",
          stat.S_IMODE((pkg / "ms.tex").stat().st_mode) == 0o400)
    if IS_ROOT:
        skip("RO1 a plain rmtree fails on the read-only tree", "running as root")
    else:
        failed = False
        try:
            shutil.rmtree(pkg)
        except OSError:
            failed = True
        check("RO1 a plain rmtree fails on the read-only tree (the bug's shape)", failed)
    check("RO1 rmtree_force deletes it anyway", nb.rmtree_force(pkg) and not pkg.exists())


# =====================================================================
# RO2 — setup ingests a read-only raw_data
# =====================================================================

def test_setup_ingests_readonly(tmp: Path):
    print()
    print("== RO2: setup over a read-only raw_data ==")
    src = make_source(tmp)
    want_digests, want_modes = digests_of(src / "raw_data"), modes_of(src / "raw_data")
    root = tmp / "root"
    proc = cli("setup", "--source", src, "--root", root, "--rounds", "1",
               "--rewrites", "0", "--revises", "1", "--judges", "1")
    check("RO2 setup succeeds with a read-only raw_data", proc.returncode == 0,
          (proc.stdout + proc.stderr)[-300:])
    check("RO2 no permission error is reported",
          "PermissionError" not in (proc.stdout + proc.stderr)
          and "Permission denied" not in (proc.stdout + proc.stderr))
    pristine = root / "non_revised" / "raw_data"
    check("RO2 the pristine copy keeps every raw-data file byte-for-byte",
          digests_of(pristine) == want_digests, str(sorted(digests_of(pristine))))
    check("RO2 ... and their read-only modes",
          modes_of(pristine) == want_modes, str(modes_of(pristine)))
    fmt_path = root / "reports" / "FORMAT_FIX_original.json"
    fmt = json.loads(fmt_path.read_text(encoding="utf-8")) if fmt_path.is_file() else {}
    touched = json.dumps([fmt.get("documents"), fmt.get("failed"), fmt.get("per_file")])
    check("RO2 the formatter never opens a raw_data file",
          "broken.docx" not in touched and "raw_data" not in touched
          and fmt.get("fixed") == 0 and not fmt.get("failed"), touched[:200])
    check("RO2 the source itself is untouched",
          digests_of(src / "raw_data") == want_digests and modes_of(src / "raw_data") == want_modes)


def setup_round_root(tmp: Path, name: str = "round-root", src_name: str = "round-src"):
    """A second, docx-free fixture for the round: raw_data stays read-only."""
    src = make_source(tmp, name=src_name, with_docx_trap=False)
    root = tmp / name
    proc = cli("setup", "--source", src, "--root", root, "--rounds", "1",
               "--rewrites", "0", "--revises", "1", "--judges", "1")
    check("RO3 setup succeeds for the round fixture", proc.returncode == 0,
          (proc.stdout + proc.stderr)[-200:])
    return root, src


def run_round(root: Path) -> subprocess.CompletedProcess:
    return cli("run", "--root", root,
               "--agent-cmd", json.dumps([sys.executable, str(STUB)]),
               "--judge-agent-cmd", json.dumps([sys.executable, str(STUB_JUDGE)]),
               "--retries", "0")


# =====================================================================
# RO3 — a full stub round + decide publishes the next generation
# =====================================================================

def test_round_and_publish(root: Path, src: Path):
    print()
    print("== RO3: run + decide with a read-only raw_data ==")
    run = run_round(root)
    check("RO3 the round runs to completion", run.returncode == 0,
          (run.stdout + run.stderr)[-300:])
    seen = 0
    for pkg in sorted((root / "runs").glob("r*/")):
        for area in raw_data_dirs(pkg):
            seen += 1
            check(f"RO3 {pkg.name} carries {area.relative_to(pkg).as_posix()} read-only and "
                  f"unchanged", same_tree(area, src / "raw_data"))
    check("RO3 the stage sandboxes really carry raw-data copies", seen > 0, str(seen))
    dec = cli("decide", "--root", root)
    check("RO3 decide publishes final_clean_version", dec.returncode == 0
          and (root / "final_clean_version").is_dir(), (dec.stdout + dec.stderr)[-400:])
    check("RO3 no PermissionError and no leftover temp tree",
          "PermissionError" not in (dec.stdout + dec.stderr)
          and not (root / "final_clean_version.tmp").exists())
    clean = root / "final_clean_version"
    if not (clean / "raw_data").is_dir():
        check("RO3 the published package carries raw_data/", False, str(sorted(clean.iterdir())))
        return
    names = sorted(p.name for p in clean.glob("cnb-*"))
    check("RO3 the manuscript filenames carry the +1 generation counter",
          any(n.startswith("cnb-14-2-mainText") for n in names)
          and any(n.startswith("cnb-14-1-coverLetter") for n in names), str(names))
    raw_names = sorted(p.name for p in (clean / "raw_data").iterdir())
    check("RO3 raw_data keeps its names (nothing is renamed inside it)",
          raw_names == sorted(p.name for p in (src / "raw_data").iterdir()), str(raw_names))
    check("RO3 ... its bytes ...",
          digests_of(clean / "raw_data") == digests_of(src / "raw_data"))
    check("RO3 ... and its read-only modes",
          modes_of(clean / "raw_data") == modes_of(src / "raw_data"),
          f"{modes_of(clean / 'raw_data')} != {modes_of(src / 'raw_data')}")
    check("RO3 the published tree's manuscript files are writable for the next run",
          all(os.access(clean / n, os.W_OK) for n in names) or IS_ROOT, str(names))
    again = cli("decide", "--root", root)
    check("RO3 a repeat decide is idempotent (unchanged, no crash)",
          again.returncode == 0 and "unchanged" in again.stdout
          and digests_of(clean / "raw_data") == digests_of(src / "raw_data"),
          (again.stdout + again.stderr)[-200:])


# =====================================================================
# RO4 — the ONE sanctioned write inside raw_data: restoring it
# =====================================================================

def test_restore_from_pristine(root: Path, src: Path):
    print()
    print("== RO4: restoring a package's raw_data from the pristine copy ==")
    pkg = root / "round1_winner"
    target = pkg / "raw_data" / "bench-results-26-07-15.tex"
    check("RO4 the published winner exists", pkg.is_dir() and target.is_file(), str(pkg))
    original = target.read_bytes()
    os.chmod(target.parent, 0o700)
    os.chmod(target, 0o600)
    target.write_text("EDITED BY A STAGE THAT IGNORED THE RULE\n", encoding="utf-8")
    extra = pkg / "raw_data" / "added-by-the-agent.csv"
    extra.write_text("x\n", encoding="utf-8")
    lock_tree(pkg / "raw_data")
    ctx = nb.Ctx(root)
    ctx.load()
    warns = []
    info = nb.verify_readonly_raw_data(ctx, pkg, warns)
    check("RO4 the modified file is restored despite being read-only",
          target.read_bytes() == original and info["restored"], str(info["restored"]))
    check("RO4 the added file is dropped", not extra.exists() and info["dropped"],
          str(info["dropped"]))
    check("RO4 ... and the read-only modes are exactly as they were",
          stat.S_IMODE(target.stat().st_mode) == 0o400
          and stat.S_IMODE(target.parent.stat().st_mode) == 0o500,
          f"{oct(stat.S_IMODE(target.stat().st_mode))} "
          f"{oct(stat.S_IMODE(target.parent.stat().st_mode))}")
    check("RO4 the deviation is named in one warning",
          any("put back to the pristine original" in w for w in warns), str(warns[:1]))


# =====================================================================
# RO5 — retry rebuilds and prune deletes read-only sandboxes
# =====================================================================

def test_retry_and_prune(root: Path, src: Path, tmp: Path):
    print()
    print("== RO5: retry and prune over read-only sandboxes ==")
    # A. prune deletes sandboxes that contain read-only raw_data (the deletion
    #    half of the bug: shutil.rmtree cannot unlink inside a 0500 directory).
    sandboxes = [p for p in sorted((root / "runs").glob("r1_*")) if raw_data_dirs(p)]
    check("RO5 the completed round has sandboxes carrying raw_data", bool(sandboxes),
          str([p.name for p in sandboxes]))
    prune = cli("prune", "--root", root, "--keep-latest", "0", "--yes")
    check("RO5 prune deletes the read-only-containing sandboxes",
          prune.returncode == 0 and "PermissionError" not in (prune.stdout + prune.stderr),
          (prune.stdout + prune.stderr)[-300:])
    left = [p.name for p in (root / "runs").iterdir()
            if p.is_dir() and not p.name.startswith("_")]
    check("RO5 no sandbox is left behind", not left, str(left))
    # B. retry rebuilds a run whose re-copied raw_data is read-only again.
    root2, src2 = setup_round_root(tmp, name="retry-root", src_name="retry-src")
    check("RO5 the retry fixture runs a round", run_round(root2).returncode == 0)
    retry = cli("retry", "--root", root2, "--run", "r1_a2_revise")
    check("RO5 retry rebuilds a sandbox that carries read-only raw_data",
          retry.returncode == 0, (retry.stdout + retry.stderr)[-300:])
    after = raw_data_dirs(root2 / "runs" / "r1_a2_revise")
    check("RO5 the rebuilt sandbox carries the original raw_data, still read-only",
          bool(after) and all(same_tree(area, src2 / "raw_data") for area in after),
          str([a.relative_to(root2 / 'runs' / 'r1_a2_revise').as_posix() for a in after]))


def main() -> int:
    try:
        tmp = scratch("paper_ro_")
        test_helpers()
        test_setup_ingests_readonly(tmp)
        root, src = setup_round_root(tmp)
        test_round_and_publish(root, src)
        test_restore_from_pristine(root, src)
        test_retry_and_prune(root, src, tmp)
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL READ-ONLY raw_data CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""The cached/parallel hashing that makes `decide` fast must stay exact.

Run:  python3 .nbt_test/test_hash_cache.py

`decide` re-verifies the whole content-addressed chain, which re-hashes the same
corpus dozens of times (every judge sandbox carries a full target + field copy).
The fix is a process-local cache keyed by the file's FULL stat identity plus a
threaded first pass. These checks prove the properties the integrity checks
depend on:

  * the digest is the standard SHA-256 of the bytes;
  * a same-size edit is detected (cache miss by mtime/ctime/size);
  * an edit that RESTORES the mtime is detected (ctime moved);
  * `sha256_files` preserves order, raises by default, and returns the caller's
    `on_error` value when asked;
  * serial and parallel hashing produce identical manifests;
  * `hash_manifest` output is unchanged in structure and content.

`NBT_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("NBT_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("nbt_hash", str(WS / "nbt_pipeline.py"))
nb = importlib.util.module_from_spec(spec)
sys.modules["nbt_hash"] = nb
spec.loader.exec_module(nb)

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
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def test_digest_and_tamper():
    print()
    print("== HC1: the digest is exact, and the default path never hides a change ==")
    tmp = scratch("nbt_hash_")
    f = tmp / "a.bin"
    f.write_bytes(b"alpha" * 4096)
    want = hashlib.sha256(f.read_bytes()).hexdigest()
    check("HC1 sha256_file matches hashlib", nb.sha256_file(f) == want)
    # Same size, different bytes: size alone must not satisfy the cache.
    # The cache is OFF by default (the `run` path), so this re-reads the file.
    check("HC1 the digest cache is off by default (the `run` path)",
          nb.hash_cache_stats()["enabled"] is False)
    data = bytearray(f.read_bytes())
    data[0] ^= 0xFF
    f.write_bytes(bytes(data))
    want2 = hashlib.sha256(bytes(data)).hexdigest()
    check("HC1 a same-size edit is detected",
          nb.sha256_file(f) == want2 and want2 != want)
    # Restore the mtime to the pre-edit value: ctime still moved, so the cache
    # must miss and the tamper must be visible.
    st = f.stat()
    data2 = bytearray(data)
    data2[1] ^= 0x0F
    f.write_bytes(bytes(data2))
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))          # mtime restored
    want3 = hashlib.sha256(bytes(data2)).hexdigest()
    check("HC1 an edit that restores the mtime is detected (ctime moved)",
          nb.sha256_file(f) == want3 and want3 not in (want, want2))
    check("HC1 the worker count is positive",
          nb.hash_cache_stats()["workers"] >= 1,
          str(nb.hash_cache_stats()))


def test_cache_fast_path():
    print()
    print("== HC2: with the cache on, an unchanged file is not re-read ==")
    tmp = scratch("nbt_hash_cache_")
    f = tmp / "b.bin"
    f.write_bytes(b"stable" * 1000)
    want = hashlib.sha256(f.read_bytes()).hexdigest()
    saved, nb.HASH_CACHE_ENABLED = nb.HASH_CACHE_ENABLED, True
    real = nb.hashlib.sha256
    calls = {"n": 0}

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    try:
        nb.hashlib.sha256 = counting
        first = nb.sha256_file(f)
        n_after_first = calls["n"]
        second = nb.sha256_file(f)
        check("HC2 the digest is right both times", first == want and second == want)
        check("HC2 the second call is a cache hit (no hashlib call)",
              calls["n"] == n_after_first, f"{n_after_first} -> {calls['n']}")
        # A *changed* mtime invalidates the key (setting "now" would land in the
        # same one-second bucket on coarse-timestamp filesystems, which is
        # exactly why the cache is never enabled where writers may be running).
        st = f.stat()
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns - 10_000_000_000))
        third = nb.sha256_file(f)
        check("HC2 a touched file is hashed again",
              third == want and calls["n"] > n_after_first)
    finally:
        nb.hashlib.sha256 = real
        nb.HASH_CACHE_ENABLED = saved


def test_command_scoping():
    print()
    print("== HC3: the cache is enabled only for a quiescent decide/status ==")
    tmp = scratch("nbt_hash_cmd_")
    note = nb.configure_hash_cache_for_command("run", tmp)
    check("HC3 `run` never uses the cache",
          nb.hash_cache_stats()["enabled"] is False and note == "")
    note = nb.configure_hash_cache_for_command("decide", tmp)
    check("HC3 `decide` on a quiescent root enables the cache",
          nb.hash_cache_stats()["enabled"] is True and note == "")
    (tmp / nb.LOCK_FILE).write_text(
        '{"pid": %d, "what": "run", "since": "now"}' % os.getpid(), encoding="utf-8")
    note = nb.configure_hash_cache_for_command("decide", tmp)
    check("HC3 a live lock disables the cache and says so",
          nb.hash_cache_stats()["enabled"] is False and "holds" in note, note)
    (tmp / nb.LOCK_FILE).unlink()
    forced = nb._HASH_CACHE_FORCED
    try:
        nb._HASH_CACHE_FORCED = True
        nb.configure_hash_cache_for_command("run", tmp)
        check("HC3 NBT_HASH_CACHE=1 forces the cache on even for `run`",
              nb.hash_cache_stats()["enabled"] is True)
        nb._HASH_CACHE_FORCED = False
        nb.configure_hash_cache_for_command("decide", tmp)
        check("HC3 NBT_HASH_CACHE=0 forces the cache off even for `decide`",
              nb.hash_cache_stats()["enabled"] is False)
    finally:
        nb._HASH_CACHE_FORCED = forced
        nb.configure_hash_cache_for_command("run", tmp)      # back to the safe default


def test_batch_helper():
    print()
    print("== HC4: sha256_files preserves order and propagates errors ==")
    tmp = scratch("nbt_hash2_")
    paths = []
    for i in range(5):
        p = tmp / f"f{i}.bin"
        p.write_bytes(bytes([i]) * (1000 + i))
        paths.append(p)
    want = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    check("HC4 parallel digests are in the input order", nb.sha256_files(paths) == want)
    saved = nb.HASH_WORKERS
    try:
        nb.HASH_WORKERS = 1
        check("HC4 serial digests are identical", nb.sha256_files(paths) == want)
    finally:
        nb.HASH_WORKERS = saved
    missing = tmp / "missing.bin"
    raised = False
    try:
        nb.sha256_files([paths[0], missing])
    except OSError:
        raised = True
    check("HC4 a missing file raises by default", raised)
    check("HC4 on_error returns the caller's marker in place",
          nb.sha256_files([paths[0], missing], on_error="<unreadable>")
          == [want[0], "<unreadable>"])


def test_manifest_identity():
    print()
    print("== HC5: manifests are byte-identical to a serial reference ==")
    tmp = scratch("nbt_hash3_")
    (tmp / "sub").mkdir()
    for i in range(7):
        (tmp / "sub" / f"g{i}.txt").write_text("x" * (10 + i), encoding="utf-8")
    (tmp / "top.txt").write_text("top\n", encoding="utf-8")
    (tmp / "manuscript.tracked.docx").write_bytes(b"aux")
    got = nb.hash_manifest(tmp)
    ref = {"files": {p.relative_to(tmp).as_posix():
                     hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted(tmp.rglob("*")) if p.is_file()},
           "count": 0}
    ref["count"] = len(ref["files"])
    check("HC5 hash_manifest equals the reference manifest", got == ref, str(got)[:160])
    check("HC5 a second manifest is identical (cache path)",
          nb.hash_manifest(tmp) == got)
    check("HC5 corpus_tree_manifest still drops the auxiliaries",
          "manuscript.tracked.docx" not in nb.corpus_tree_manifest(tmp)["files"])
    saved = nb.HASH_WORKERS
    try:
        nb.HASH_WORKERS = 1
        check("HC5 serial and parallel manifests are identical",
              nb.hash_manifest(tmp) == got)
    finally:
        nb.HASH_WORKERS = saved


def test_decide_end_to_end():
    print()
    print("== HC6: two decides on one root produce identical outputs ==")
    tmp = scratch("nbt_hash_e2e_")
    source = tmp / "source"
    source.mkdir()
    (source / "manuscript-b.md").write_text(
        "Abstract\n\n" + ("word " * 100).strip() + "\n\nIntroduction\n\n"
        + ("text " * 200).strip() + "\n\nFigure 1 | A caption here.\n\nMethods\n\nx\n",
        encoding="utf-8")
    (source / "refs-b.bib").write_text("@article{x}\n", encoding="utf-8")
    root = tmp / "root"
    stub = Path(__file__).resolve().parent / "stub_agent.py"
    stub_judge = Path(__file__).resolve().parent / "stub_judge.py"

    def run(argv):
        return subprocess.run([sys.executable, str(WS / "nbt_pipeline.py")] + argv,
                              capture_output=True, text=True, timeout=600)

    proc = run(["setup", "--source", str(source), "--root", str(root), "--rounds", "1",
                "--rewrites", "0", "--revises", "1", "--judges", "1"])
    check("HC6 setup succeeds", proc.returncode == 0, (proc.stdout + proc.stderr)[-200:])
    proc = run(["run", "--root", str(root),
                "--agent-cmd", json.dumps([sys.executable, str(stub)]),
                "--judge-agent-cmd", json.dumps([sys.executable, str(stub_judge)]),
                "--retries", "0"])
    check("HC6 the stub round completes", proc.returncode == 0,
          (proc.stdout + proc.stderr)[-300:])
    first = run(["decide", "--root", str(root)])
    check("HC6 the first decide succeeds", first.returncode == 0,
          (first.stdout + first.stderr)[-300:])
    check("HC6 a quiescent decide does not warn about the cache",
          "holds" not in (first.stdout + first.stderr))
    j1 = json.loads((root / "reports" / "decision.json").read_text(encoding="utf-8"))
    r1 = (root / "reports" / "DECISION_REPORT.md").read_text(encoding="utf-8")
    second = run(["decide", "--root", str(root)])
    check("HC6 the second decide succeeds", second.returncode == 0,
          (second.stdout + second.stderr)[-300:])
    j2 = json.loads((root / "reports" / "decision.json").read_text(encoding="utf-8"))
    r2 = (root / "reports" / "DECISION_REPORT.md").read_text(encoding="utf-8")
    j1.pop("generated", None)
    j2.pop("generated", None)
    check("HC6 decision.json is identical (minus the generation time)", j1 == j2)
    norm = lambda t: re.sub(r"Generated: [^\n]+", "Generated: X", t)
    check("HC6 DECISION_REPORT.md is identical (minus the generation time)",
          norm(r1) == norm(r2))
    clean = root / "final_clean_version"
    files = sorted(p.name for p in clean.rglob("*") if p.is_file()) if clean.is_dir() else []
    check("HC6 decide publishes <root>/final_clean_version",
          clean.is_dir() and "manuscript-b.md" in files, str(files))
    check("HC6 the clean version carries no pipeline bookkeeping/auxiliaries",
          not any(n.lower() in ("changelog.md", "manual_steps.md", "revision_report.md",
                                "revision_report.json", "diff_ledger.md", "rewrite_report.md")
                  or n.endswith((".tracked.docx", ".before-after.docx")) for n in files),
          str(files))
    check("HC6 decision.json records the clean version and its digest",
          (j2.get("final", {}).get("final_clean_version") or {}).get("path") == str(clean)
          and (j2.get("final", {}).get("final_clean_version") or {}).get("digest"))


def test_run_decide():
    print()
    print("== HC7: run-decide runs the rounds and decides, in series ==")
    tmp = scratch("nbt_hash_rd_")
    source = tmp / "source"
    source.mkdir()
    (source / "manuscript-b.md").write_text(
        "Abstract\n\n" + ("word " * 100).strip() + "\n\nIntroduction\n\n"
        + ("text " * 200).strip() + "\n\nFigure 1 | A caption here.\n\nMethods\n\nx\n",
        encoding="utf-8")
    (source / "refs-b.bib").write_text("@article{x}\n", encoding="utf-8")
    root = tmp / "root"
    stub = Path(__file__).resolve().parent / "stub_agent.py"
    stub_judge = Path(__file__).resolve().parent / "stub_judge.py"

    def run(argv):
        return subprocess.run([sys.executable, str(WS / "nbt_pipeline.py")] + argv,
                              capture_output=True, text=True, timeout=600)

    proc = run(["setup", "--source", str(source), "--root", str(root), "--rounds", "1",
                "--rewrites", "0", "--revises", "1", "--judges", "1"])
    check("HC7 setup succeeds", proc.returncode == 0, (proc.stdout + proc.stderr)[-200:])
    proc = run(["run-decide", "--root", str(root),
                "--agent-cmd", json.dumps([sys.executable, str(stub)]),
                "--judge-agent-cmd", json.dumps([sys.executable, str(stub_judge)]),
                "--retries", "0"])
    out = proc.stdout + proc.stderr
    check("HC7 run-decide succeeds", proc.returncode == 0, out[-400:])
    check("HC7 both phases ran (round summary + FINAL decision)",
          "summary" in out and "FINAL (round" in out)
    check("HC7 the decision report was written",
          (root / "reports" / "DECISION_REPORT.md").is_file())
    check("HC7 final_clean_version was published",
          (root / "final_clean_version" / "manuscript-b.md").is_file())
    check("HC7 the clean version is announced as a ready --source",
          "setup --source" in out and "final_clean_version" in out)
    check("HC7 run-decide honours decide's flags",
          run(["run-decide", "--help"]).returncode == 0
          and "--package-winner" in run(["run-decide", "--help"]).stdout)


def main() -> int:
    for fn in (test_digest_and_tamper, test_cache_fast_path, test_command_scoping,
               test_batch_helper, test_manifest_identity, test_decide_end_to_end,
               test_run_decide):
        try:
            fn()
        except Exception as e:                                   # noqa: BLE001
            check(f"{fn.__name__} completed", False, f"{type(e).__name__}: {e}")
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL HASH-CACHE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

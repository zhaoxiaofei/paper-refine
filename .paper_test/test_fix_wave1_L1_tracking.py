#!/usr/bin/env python3
"""Regression checks for the difference-tracking candidates of the
2026-11-22 11:28 fix-bugs wave (batch L1).

Run: python3 .paper_test/test_fix_wave1_L1_tracking.py

  F118 write_text_logging_fallback never raises and never mkdirs through a link
  F131 the tracking copy refuses an over-budget DOCX part
  F138 `track --version <never-materialized>` exits 4 like `redline`
  F209 a symlinked recorded copy is stale, never fresh
  F212 an unreadable new document makes the stored entry stale
"""
from __future__ import annotations

import importlib.util
import stat
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
WS = HERE.parent
_spec = importlib.util.spec_from_file_location(
    "difference_tracking_lib", HERE / "difference_tracking_lib.py")
lib = importlib.util.module_from_spec(_spec)
sys.modules["difference_tracking_lib"] = lib
_spec.loader.exec_module(lib)
nb = lib.nb

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix):
    return lib.scratch(prefix)


def test_f118_never_raises():
    tmp = scratch("f118")
    base, cand = tmp / "a.tex", tmp / "b.tex"
    base.write_text("old line\n", encoding="utf-8")
    cand.write_text("new line\n", encoding="utf-8")
    track = tmp / "tracking" / "r1_w1"
    track.mkdir(parents=True)
    blocker = track / "original"
    blocker.write_text("a regular file where the directory should be\n",
                       encoding="utf-8")
    out = blocker / "x.tex"
    raised = None
    try:
        res = nb.write_text_logging_fallback(base, cand, out, "original", "boom")
    except Exception as e:                                  # noqa: BLE001
        raised, res = e, None
    check("F118 a regular file at the parent does not raise", raised is None, repr(raised))
    check("F118 the failure is reported", bool(res) and res.get("ok") is False, repr(res))

    outside = tmp / "outside"
    outside.mkdir()
    linked = tmp / "linked" / "r1_w1"
    linked.parent.mkdir()
    linked.symlink_to(outside, target_is_directory=True)
    out2 = linked / "original" / "x.tex"
    raised = None
    try:
        res = nb.write_text_logging_fallback(base, cand, out2, "original", "boom")
    except Exception as e:                                  # noqa: BLE001
        raised, res = e, None
    check("F118 a symlinked parent does not raise", raised is None, repr(raised))
    check("F118 the symlinked parent is refused and nothing is created outside",
          bool(res) and res.get("ok") is False
          and not (outside / "original").exists(), repr(res))


def test_f131_budget():
    tmp = scratch("f131")
    base, cand, out = tmp / "base.docx", tmp / "cand.docx", tmp / "tracked.docx"
    lib.make_docx(base, ["Title", "The old abstract text."])
    lib.make_docx(cand, ["Title", "The new abstract text."])
    with zipfile.ZipFile(cand, "a", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/media/big.bin", b"\0" * (65 * 1024 * 1024))
    res = nb.write_docx_logging_fallback(base, cand, out, "original", "boom")
    texts = nb._docx_paragraph_texts(out)
    check("F131 an over-budget part is refused, not copied",
          res.get("ok") is not True
          or any("could not be copied" in str(t) for t in texts),
          f"res={res!r} texts={texts!r}")


def test_f138_exit_code():
    tmp = scratch("f138")
    source = lib.build_source(tmp)
    ctx = lib.build_root(tmp, source, rounds=1)
    args = SimpleNamespace(redline_cmd=None, round=None, version="w99",
                           tool="none", no_pdf=True)
    code = 0
    try:
        nb._cmd_track_locked(ctx, args)
    except SystemExit as e:                                 # noqa: PERF203
        code = e.code
    check("F138 a never-materialized requested version exits 4", code == 4, repr(code))


def _tracking_fixture(prefix):
    tmp = scratch(prefix)
    source = lib.build_source(tmp)
    ctx = lib.build_root(tmp, source, rounds=1)
    manifest = nb.run_difference_tracking(ctx, rounds=[1], versions=["w1"])
    entry = next(v for v in manifest["versions"] if v["version"] == "w1")
    baselines = nb.tracking_baselines(ctx, 1, "w1")
    srcs = nb.fresh_package_sources(ctx, 1, "w1")
    return ctx, entry, baselines, srcs


def test_f209_symlinked_copy_is_stale():
    ctx, entry, baselines, srcs = _tracking_fixture("f209")
    check("F209 the untouched entry is fresh",
          nb.tracking_entry_is_fresh(ctx, entry, baselines, srcs))
    row = next(c for c in entry["comparisons"]
               if c.get("ok") and (c.get("fallback_out") or c.get("out")))
    rel = row.get("fallback_out") if row.get("fallback") else row.get("out")
    recorded = ctx.root / str(rel)
    target = ctx.pristine / "manuscript-a.docx"
    recorded.unlink()
    recorded.symlink_to(target)
    check("F209 a symlink at the recorded copy path is stale",
          nb.tracking_entry_is_fresh(ctx, entry, baselines, srcs) is False)


def test_f212_unreadable_new_document_is_stale():
    ctx, entry, baselines, srcs = _tracking_fixture("f212")
    check("F212 the untouched entry is fresh",
          nb.tracking_entry_is_fresh(ctx, entry, baselines, srcs))
    new_doc = ctx.root / "runs/r1_w1/rewritten/added.docx"
    lib.make_docx(new_doc, ["A newly added document."])
    new_doc.chmod(0)
    try:
        check("F212 an unreadable new document makes the entry stale",
              nb.tracking_entry_is_fresh(ctx, entry, baselines, srcs) is False)
    finally:
        new_doc.chmod(stat.S_IRUSR | stat.S_IWUSR)


def main() -> int:
    test_f118_never_raises()
    test_f131_budget()
    test_f138_exit_code()
    test_f209_symlinked_copy_is_stale()
    test_f212_unreadable_new_document_is_stale()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        lib.cleanup()
        return 1
    print("ALL L1 TRACKING CHECKS PASSED")
    lib.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())

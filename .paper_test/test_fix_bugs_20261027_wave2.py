#!/usr/bin/env python3
"""Regression checks for the 2026-10-27 fix-bugs wave 2.

Run:  python3 .paper_test/test_fix_bugs_20261027_wave2.py

Every check here pins one of the six candidates wave 1 confirmed but deferred
(F23, F45, F46, F47, F48, F51).  The pre-fix tree fails each one; the suite is
hermetic (temporary roots only) and deliberately small.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs1027w2_pp", "paper_pipeline.py")
dfl = load("fixbugs1027w2_dfl", ".paper_test/docx_format_lib.py")
pf = dfl.fmt

FAILS = []
TMPDIRS = []


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def run(argv, **kw):
    return subprocess.run([sys.executable] + [str(a) for a in argv],
                          capture_output=True, text=True, **kw)


def synthetic_root(prefix: str):
    """A minimal valid pipeline root (config + empty registry)."""
    tmp = scratch(prefix)
    root = tmp / "root"
    root.mkdir()
    (root / "pipeline_config.json").write_text(json.dumps({"rounds": 1, "judges": [1]}),
                                              encoding="utf-8")
    (root / "state.json").write_text(json.dumps({
        "version": pp.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [], "log": []}),
        encoding="utf-8")
    ctx = pp.Ctx(root)
    ctx.load()
    return tmp, root, ctx


def register(ctx, rid: str, kind: str, sandbox: Path, **extra) -> dict:
    rec = {"id": rid, "kind": kind, "round": 1, "status": "done",
           "sandbox": f"runs/{rid}", "attempts": 1}
    rec.update(extra)
    ctx.state.setdefault("runs", {})[rid] = rec
    return rec


# ---------------------------------------------------------------------------
# F23 -- a run-on journal emphasis must lose only the prose, never the title
# ---------------------------------------------------------------------------
def test_f23_journal_run_on_emphasis():
    print()
    print("== F23: journal_italics=everywhere keeps the title inside a run-on run ==")
    tmp = scratch("fixbugs1027w2_f23_")
    xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{dfl.P[1:-1]}" xmlns:r="{dfl.R[1:-1]}" xmlns:mc="{dfl.MC[1:-1]}" xmlns:w14="{dfl.W14[1:-1]}" mc:Ignorable="w14">
<w:body>
  <w:p><w:r><w:rPr><w:i/></w:rPr><w:t>Nature Methods and other leading journals.</w:t></w:r></w:p>
</w:body></w:document>"""
    docx = dfl.make_package(tmp / "journal.docx", xml)
    policy = pf.load_policy(None)
    policy["journal_italics"] = "everywhere"
    before = {r["rule"] for r in pf.scan_paths([tmp], policy)["rows"]}
    check("F23 the scan reports the run-on emphasis", "FMT-T6f" in before, str(sorted(before)))
    out = tmp / "journal.fixed.docx"
    rep = pf.fix_package(docx, out, policy)
    with zipfile.ZipFile(out) as z:
        fixed = z.read("word/document.xml").decode("utf-8")
    paras = pf.paragraphs(fixed)
    runs = [(pf.text_of(run), pf.run_is_italic({}, None, run))
            for _r0, _r1, run in pf.runs(paras[0][2])]
    check("F23 the journal title stays italic", ("Nature Methods", True) in runs, str(runs))
    check("F23 only the continuation prose is made roman",
          any(text.strip().startswith("and other leading journals") and not italic
              for text, italic in runs), str(runs))
    after = {r["rule"] for r in pf.scan_paths([out], policy)["rows"]}
    check("F23 the fix verifies and leaves no journal-emphasis row",
          rep["ok"] and "FMT-T6f" not in after, f"ok={rep['ok']} after={sorted(after)}")


# ---------------------------------------------------------------------------
# F45 -- split-review session B notices that session A was retried
# ---------------------------------------------------------------------------
def test_f45_split_review_a_freshness():
    print()
    print("== F45: review session B follows a retried session A ==")
    _tmp, root, ctx = synthetic_root("fixbugs1027w2_f45_")
    ctx.cfg["review_split"] = "phases"
    a1 = root / "runs" / "r1_a1"
    (a1 / "base").mkdir(parents=True)
    (a1 / "base" / "doc.txt").write_text("base\n", encoding="utf-8")
    register(ctx, "r1_a1", "a1", a1)

    a = root / "runs" / "r1_guided_review"
    (a / "guided_review").mkdir(parents=True)
    (a / "guided_review" / "findings.json").write_text('{"findings": []}\n', encoding="utf-8")
    register(ctx, "r1_guided_review", "guided_review", a)

    b = root / "runs" / "r1_guided_review_b"
    (b / "base").mkdir(parents=True)
    (b / "base" / "doc.txt").write_text("base\n", encoding="utf-8")
    (b / "guided_review_a").mkdir()
    (b / "guided_review_a" / "findings.json").write_text('{"findings": []}\n', encoding="utf-8")
    rec = register(ctx, "r1_guided_review_b", "guided_review", b,
                   inputs_manifest={"base": pp.hash_manifest(b / "base"),
                                    "guided_review_a": pp.hash_manifest(b / "guided_review_a")})
    check("F45 a matching review_a is fresh", pp._input_freshness_problems(ctx, rec) == [],
          str(pp._input_freshness_problems(ctx, rec)))
    (a / "guided_review" / "findings.json").write_text(
        '{"findings": [{"id": "FA-1", "new": true}]}\n', encoding="utf-8")
    probs = pp._input_freshness_problems(ctx, rec)
    check("F45 a retried session A makes B's frozen review_a stale",
          any("guided_review_a" in p for p in probs), str(probs))


# ---------------------------------------------------------------------------
# F46 -- the journal feedback is manifested and revalidated
# ---------------------------------------------------------------------------
def _journal_root(tmp: Path):
    src = tmp / "src"
    (src / "raw_data").mkdir(parents=True)
    (src / "human_review_feedback").mkdir()
    (src / "manuscript.txt").write_text(
        "Abstract\nWe used scRNA-seq to profile the cells.\n", encoding="utf-8")
    (src / "human_review_feedback" / "review.txt").write_text(
        "Reviewer 1:\n1. The sample size is too small for the claims.\n", encoding="utf-8")
    root = tmp / "root"
    proc = run([WS / "paper_pipeline.py", "setup", "--source", src, "--root", root,
                "--rounds", "1", "--rewrites", "0", "--revises", "1",
                "--integrators", "0x0", "--judges", "1",
                "--revision-mode", "transfer", "--journal", "iScience",
                "--journal-feedback-from", "iScience"])
    if proc.returncode != 0:
        raise RuntimeError(f"setup failed: {proc.stdout[-400:]}{proc.stderr[-400:]}")
    ctx = pp.Ctx(root)
    ctx.load()
    pp.materialize_a1(ctx, 1)
    ctx.run("r1_a1")["status"] = "done"
    ctx.save_state()
    return root, ctx


def test_f46_feedback_manifest_and_freshness():
    print()
    print("== F46: staged feedback is hash-pinned and downstream copies revalidate ==")
    tmp = scratch("fixbugs1027w2_f46_")
    root, ctx = _journal_root(tmp)
    fb_rec = pp.materialize_feedback(ctx, 1)
    check("F46 the feedback run manifests its staged feedback area",
          isinstance((fb_rec.get("inputs_manifest") or {}).get("feedback"), dict),
          str(sorted(fb_rec.get("inputs_manifest") or {})))
    fbsb = ctx.sandbox_of(fb_rec)
    text_file = sorted((fbsb / "feedback" / "text").glob("*.txt"))[0]

    # A downstream review sandbox is born with the same staged copies.
    review = root / "runs" / "r1_guided_review"
    (review / "base").mkdir(parents=True)
    shutil.copytree(root / "runs" / "r1_a1" / "base", review / "base", dirs_exist_ok=True)
    shutil.copytree(fbsb / "feedback", review / "feedback")
    shutil.copytree(fbsb / "concerns", review / "concerns")
    fb_rec["status"] = "done"
    rec = register(ctx, "r1_guided_review", "guided_review", review,
                   inputs_manifest={"base": pp.hash_manifest(review / "base"),
                                    "feedback": pp.hash_manifest(review / "feedback"),
                                    "concerns": pp.hash_manifest(review / "concerns")})
    ctx.save_state()
    before = pp._input_freshness_problems(ctx, rec)
    check("F46 a downstream copy matching the current letter is fresh",
          not any("feedback/" in p for p in before), str(before))

    # A session edits the staged text after the sandbox was built...
    text_file.write_text(text_file.read_text(encoding="utf-8") + "FABRICATED QUOTE.\n",
                         encoding="utf-8")
    mism = pp.input_mismatches(ctx, fb_rec)
    check("F46 editing the staged quote source is a hard input mismatch",
          any("feedback/ was modified" in e for e in mism), str(mism))
    probs = pp._input_freshness_problems(ctx, rec)
    check("F46 a re-staged letter makes a done downstream sandbox stale",
          any("feedback/" in p and "current" in p for p in probs), str(probs))


# ---------------------------------------------------------------------------
# F47 -- a symlinked stage package aborts the postcheck before recovery writes
# ---------------------------------------------------------------------------
def test_f47_symlinked_stage_package():
    print()
    print("== F47: a symlinked revised/ is refused before recovery follows it ==")
    tmp, root, ctx = synthetic_root("fixbugs1027w2_f47_")
    rec = {"id": "r1_a2_revise", "kind": "revise", "round": 1,
           "sandbox": "runs/r1_a2_revise", "status": "failed", "attempts": 1}
    sb = root / "runs" / "r1_a2_revise"
    (sb / "base").mkdir(parents=True)
    (sb / "base" / "doc.txt").write_text("base content\n", encoding="utf-8")
    outside = tmp / "outside"
    outside.mkdir()
    (sb / "revised").symlink_to(outside, target_is_directory=True)
    ok, errs, _warns, _ = pp.postcheck_revise(ctx, rec)
    check("F47 the symlinked package root fails the postcheck",
          not ok and any("SYMLINK" in e for e in errs), str(errs[:3]))
    check("F47 recovery does not copy base files through the link",
          not (outside / "doc.txt").exists(), str(sorted(p.name for p in outside.iterdir())))


# ---------------------------------------------------------------------------
# F48 -- recovery does not put non-shippable residue back into the package
# ---------------------------------------------------------------------------
def test_f48_backfill_skips_non_shippable():
    print()
    print("== F48: backfill never restores .DS_Store / bytecode into the corpus ==")
    _tmp, root, ctx = synthetic_root("fixbugs1027w2_f48_")
    rec = {"id": "r1_a2_revise", "kind": "revise", "round": 1,
           "sandbox": "runs/r1_a2_revise", "status": "failed", "attempts": 1}
    sb = root / "runs" / "r1_a2_revise"
    (sb / "base" / "code").mkdir(parents=True)
    (sb / "base" / ".DS_Store").write_text("junk\n", encoding="utf-8")
    (sb / "base" / "code" / "helper.pyc").write_text("junk\n", encoding="utf-8")
    (sb / "revised").mkdir()
    warns = []
    rep = pp.backfill_missing_files(ctx, rec, [(sb / "base", "", ())], warns)
    check("F48 the stage strip's residue is not restored",
          rep["restored"] == [], str(rep["restored"]))
    check("F48 no residue reaches the revised package",
          not (sb / "revised" / ".DS_Store").exists()
          and not (sb / "revised" / "code" / "helper.pyc").exists())


# ---------------------------------------------------------------------------
# F51 -- a text-equal paragraph with a non-text edit is still a change
# ---------------------------------------------------------------------------
def _docx(path: Path, body: str) -> None:
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   f'<?xml version="1.0"?><w:document {ns}><w:body>{body}'
                   f'</w:body></w:document>')


def test_f51_text_equal_nontext_edit():
    print()
    print("== F51: a drawing inside a text-equal paragraph is marked in the redline ==")
    tmp = scratch("fixbugs1027w2_f51_")
    base, revised, out = tmp / "base.docx", tmp / "revised.docx", tmp / "redline.docx"
    _docx(base, "<w:p><w:r><w:t>Same text</w:t></w:r></w:p>")
    _docx(revised, "<w:p><w:r><w:t>Same text</w:t><w:drawing/></w:r></w:p>")
    info = pp.builtin_tracked_changes(base, revised, out)
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    check("F51 the non-text edit is tracked, not silently dropped",
          info["paragraphs_inserted"] >= 1 and info["paragraphs_deleted"] >= 1
          and "<w:drawing" in xml, str(info))
    check("F51 both a deletion and an insertion carry the paragraph",
          "<w:del " in xml and "<w:ins " in xml and "<w:delText>Same text</w:delText>" in xml,
          xml[:300])


def main() -> int:
    try:
        test_f23_journal_run_on_emphasis()
        test_f45_split_review_a_freshness()
        test_f46_feedback_manifest_and_freshness()
        test_f47_symlinked_stage_package()
        test_f48_backfill_skips_non_shippable()
        test_f51_text_equal_nontext_edit()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): " + ", ".join(FAILS))
        return 1
    print("ALL 2026-10-27 WAVE-2 FIX CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

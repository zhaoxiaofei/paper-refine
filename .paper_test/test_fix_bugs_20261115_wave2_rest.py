#!/usr/bin/env python3
"""Regression checks for the 2026-11-15 fix-bugs wave 2 (`rest` group).

Each check pins one candidate re-validated on the tree and repaired this wave.
Hermetic: every fixture lives under tempfile.mkdtemp().

Run:  python3 .paper_test/test_fix_bugs_20261115_wave2_rest.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import inspect
import io
import json
import shutil
import subprocess
import sys
import tempfile
import types
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
TMPDIRS = []
FAILS = []

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fb1115wave2_rest_pp", "paper_pipeline.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cli(*args, cwd=None):
    return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *args],
                          cwd=str(cwd or WS), capture_output=True, text=True, timeout=300)


def write_docx(path: Path, paragraphs, extra_parts=None) -> None:
    body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in paragraphs)
    xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml", xml)
        for name, data in (extra_parts or {}).items():
            z.writestr(name, data)


# ---------------------------------------------------------------------------
# F212 -- the no-eligible fallback carries the tie-break block
# ---------------------------------------------------------------------------
def test_ranking_no_eligible_tiebreak():
    out = pp.derive_ranking({}, [], None, {}, 10, 1)
    tb = out.get("tiebreak") or {}
    check("F212 no-eligible carries tiebreak", tb.get("floor") == 10
          and tb.get("cells_used") == 0 and tb.get("cell_total", tb.get("cells_total")) > 0,
          repr(tb))


# ---------------------------------------------------------------------------
# F207 -- a plan row naming an absent file is reported, and a pure insertion
# into a file that was never created is a no-op
# ---------------------------------------------------------------------------
def test_repair_missing_file():
    tmp = scratch("f207")
    sb = tmp / "sandbox"
    (sb / "revised").mkdir(parents=True)
    rows = [{"id": "R1", "file": "missing.md", "wrong": "old text", "correct": "new text"}]
    probs = pp.repair_plan_literal_problems(sb, rows)
    check("F207 absent plan target is a problem", any("does not exist" in p for p in probs),
          repr(probs))
    pre = tmp / "pre"
    cur = tmp / "cur"
    pre.mkdir()
    cur.mkdir()
    ins = [{"id": "R2", "file": "new.md", "wrong": "", "correct": "hello"}]
    bad = pp._revised_repair_violations(pre, cur, ins, {"R2"}, with_reasons=True)
    check("F207 pure insertion into an uncreated file is a no-op",
          "new.md" in bad and "never created" in str(bad.get("new.md")), repr(bad))


# ---------------------------------------------------------------------------
# F213 -- a nested --source survives a refused interrupted-root setup
# ---------------------------------------------------------------------------
def test_setup_nesting_before_delete():
    tmp = scratch("f213")
    root = tmp / "root"
    src = root / "src"
    src.mkdir(parents=True)
    (src / "main.md").write_text("# T\n\n## Abstract\nx\n", encoding="utf-8")
    (root / "PIPELINE_SETUP_IN_PROGRESS").write_text("x", encoding="utf-8")
    (root / "pipeline_config.json").write_text("{}", encoding="utf-8")
    res = cli("setup", "--source", str(src), "--root", str(root))
    check("F213 nested source is refused", res.returncode == 2, res.stderr[-300:])
    check("F213 nested source survives the refusal", src.is_dir() and (src / "main.md").is_file())


# ---------------------------------------------------------------------------
# F223 -- a second glob-less declaration does not absorb a later example glob
# ---------------------------------------------------------------------------
def test_declaration_per_hint_state():
    tmp = scratch("f223")
    root = tmp / "pkg"
    root.mkdir()
    (root / "README.md").write_text(
        "# Package\n\nOnly `ms-*.docx` will be submitted.\n\n"
        "The following will be submitted:\n\n"
        "Unrelated examples: `fig-*.png`, `*.log`\n", encoding="utf-8")
    dec = pp.declared_submission_set(root)
    pats = set(dec.get("patterns") or [])
    check("F223 first declaration glob kept", "ms-*.docx" in pats, repr(sorted(pats)))
    check("F223 later example glob not absorbed", "fig-*.png" not in pats, repr(sorted(pats)))


# ---------------------------------------------------------------------------
# F229/F232 -- containment: no caption or media exemption from outside root
# ---------------------------------------------------------------------------
def test_pkg_containment():
    tmp = scratch("f229_232")
    root = tmp / "pkg"
    root.mkdir()
    outside = tmp / "outside.png"
    outside.write_bytes(b"OUTSIDE")
    digest = pp._cached_sha256(outside)
    exc = {"closure": set(), "tex_sources": [], "media": {digest: ["doc.docx::word/media/x"]}}
    ok, _why = pp.pkg10_reference_exempt(root, "../outside.png", exc)
    check("F232 ../ target is not exempt", ok is False)
    check("F229 no caption dir outside root",
          pp._in_not_carried_areas("code/x.pdf", ["code"]) is True)


# ---------------------------------------------------------------------------
# F230/F231/F237 -- author README declarations, md prose, README skip
# ---------------------------------------------------------------------------
def test_pkg3_and_readme():
    check("F231 markdown is a PKG-3 prose surface", pp._pkg3_prose_document("main.md") is True)
    check("F231 txt is a PKG-3 prose surface", pp._pkg3_prose_document("paper.txt") is True)
    tmp = scratch("f237")
    root = tmp / "pkg"
    root.mkdir()
    (root / "README.md").write_text(
        "This package's analysis is described elsewhere.\n"
        "The 31 effective findings of this round are in the ledger.\n", encoding="utf-8")
    rows = pp.internal_artifact_rows(root)
    check("F237 author README is not a PKG-1 row", rows == [], repr(rows))


# ---------------------------------------------------------------------------
# F239/F240/F241 -- readiness consumes read gaps and a failed ledger read,
# and the status readme enumerates blocking findings
# ---------------------------------------------------------------------------
def test_readiness_gaps_and_readme():
    final = {"path": "", "hygiene": {
        "package_consistency": {"document_read_gaps": [
            {"rule": "FMT-X1", "file": "main.docx", "detail": "unreadable"}]},
    }, "open_items": {"error": "PermissionError: nope", "items": [], "discarded": []}}
    rd = pp.package_readiness(final)
    rules = {f.get("rule") for f in rd["findings"]}
    check("F239 document_read_gaps reaches readiness", "FMT-X1" in rules, repr(sorted(rules)))
    check("F240 failed open-items read blocks readiness", "REV-0" in rules, repr(sorted(rules)))
    check("F240 failed read makes the package not ready", rd["submission_ready"] is False)
    class _Ctx:
        root = Path("/tmp/root")
    text = pp.final_clean_readme_text(
        _Ctx(), {"certified": False, "submission_ready": False,
                 "package_findings": [{"rule": "PKG-11", "detail": "blocking fact"}]},
        {}, final)
    check("F241 blocking findings are enumerated", "PKG-11" in text and "blocking fact" in text)


# ---------------------------------------------------------------------------
# F245/F246/F248 -- trend dedupe, TODO parser problems, bare sample-size claim
# ---------------------------------------------------------------------------
def test_small_p12_predicates():
    got = pp.trend_order(["/nonexistent/a", "/nonexistent/a"])
    check("F245 repeated root listed once", len(got) == 1, repr(got))
    rows = pp.unit_of_analysis_rows(
        [("main.docx", "Pairwise comparisons used 606-1,989 paired cells."),
         ("notes.txt", "n is the number of donors whose paired differences enter the test.")])
    check("F248 bare range is a sample-size claim", bool(rows), repr(rows))


# ---------------------------------------------------------------------------
# F249/F250/F251 -- redline fidelity: mark fallback, table weight, base-only part
# ---------------------------------------------------------------------------
def test_redline_fidelity_fixes():
    tmp = scratch("f249_251")
    base = tmp / "base.docx"
    rev = tmp / "rev.docx"
    brk = f'<w:r><w:br/></w:r><w:r><w:t>tail</w:t></w:r>'
    body_b = f'<w:p><w:r><w:t>alpha</w:t></w:r></w:p><w:p>{brk}</w:p>'
    body_r = f'<w:p><w:r><w:t>beta</w:t></w:r></w:p><w:p><w:r><w:t>tail</w:t></w:r></w:p>'
    for path, body, extra in (
            (base, body_b, {"word/header1.xml": "<hdr/>"}),
            (rev, body_r, {})):
        xml = (f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>{body}'
               f'</w:body></w:document>')
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("word/document.xml", xml)
            for n, d in extra.items():
                z.writestr(n, d)
    out = tmp / "out.docx"
    info = pp.builtin_tracked_changes(base, rev, out)
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        doc = z.read("word/document.xml").decode()
    check("F251 a base-only part is not carried into the redline",
          "word/header1.xml" not in names, repr(sorted(names)))
    check("F249 base-only break is marked as a deletion", "w:del" in doc and "w:br" in doc)
    mw = pp.redline_minimal_weight(base, rev)
    check("F250 minimal weight counts real changed words", (mw.get("ins") or 0)
          + (mw.get("del") or 0) > 0, repr(mw))


# ---------------------------------------------------------------------------
# F256 -- a subdirectory master resolves ../includes against the package
# ---------------------------------------------------------------------------
def test_rewire_parent_path():
    tmp = scratch("f256")
    pkg = tmp / "pkg"
    (pkg / "sections").mkdir(parents=True)
    (pkg / "masters").mkdir()
    tracked = {"sections/intro.tex": pkg / "sections" / "intro.tracking-a1.tex"}
    new, rw = pp.rewire_tracking_tex(
        "\\input{../sections/intro}\n", pkg / "masters" / "main.tex", tracked, pkg_root=pkg)
    check("F256 ../ include is rewired", bool(rw) and "intro.tracking-a1" in new,
          f"{rw} / {new}")


# ---------------------------------------------------------------------------
# F261 -- a symlink-loop include is refused, not a crash
# ---------------------------------------------------------------------------
def test_tex_symlink_loop():
    tmp = scratch("f261")
    base = tmp / "m"
    base.mkdir()
    (base / "loop.tex").symlink_to("loop.tex")
    got = pp._tex_include_path(base, "loop")
    check("F261 symlink-loop include returns None", got is None, repr(got))


# ---------------------------------------------------------------------------
# F208 -- an unjudged auto-promoted round carries NO defect census
# ---------------------------------------------------------------------------
def test_f208_auto_round_payload():
    class _Ctx:
        def run(self, rid):
            return {"id": rid, "corpus_digest": "d" * 64}
    _agg, sel = pp.auto_round_payload(_Ctx(), 1, vid="w1", mode="revise")
    row = (sel.get("ranking") or [{}])[0]
    check("F208 an auto-promoted row has no fabricated zero-defect total",
          row.get("defect_prefix_total") is None
          and row.get("defect_prefix_census") is None, repr(row.get("defect_prefix_total")))
    check("F208 the auto-promoted round is marked unjudged",
          sel.get("judged") is False and sel.get("auto_promoted") is True, repr(sel.get("judged")))
    check("F208 a missing census sorts as missing evidence, never as zero defects",
          pp.champion_sort_key(row)[0] == 10 ** 9, repr(pp.champion_sort_key(row)))


# ---------------------------------------------------------------------------
# F209 -- the scoped close verifies the copied winner against the recorded digest
# ---------------------------------------------------------------------------
def test_f209_scoped_winner_digest():
    src = inspect.getsource(pp.drive_round)
    blk = src[src.index("win_dst = winner_dir_of(ctx, r)"):][:2600]
    check("F209 the scoped winner copy is hashed with the corpus-manifest rule",
          "win_manifest = corpus_dir_manifest(win_tmp)" in blk
          and "win_digest = manifest_digest(win_manifest)" in blk)
    check("F209 the copy is compared with the revision's recorded digest",
          "_recorded = recorded_version_digest(ctx, r, a2)" in blk
          and "win_digest != _recorded" in blk and "die(" in blk)
    check("F209 the winner digest records the verified copy",
          'rrec["winner_digest"] = win_digest' in blk)


# ---------------------------------------------------------------------------
# F210 -- manual mode says run does NOT re-verify a failed attempt
# ---------------------------------------------------------------------------
def test_f210_manual_recovery_message():
    rec = {"id": "r1_judge_a", "kind": "judge", "round": 1, "status": "failed",
           "attempts": 1, "sandbox": "runs/r1_judge_a",
           "postcheck": {"ok": False, "errors": ["REVIEW.md missing"], "warnings": []},
           "last_error": "REVIEW.md missing", "started": "x", "attempts_log": []}
    calls = []

    class _Ctx:
        def run(self, rid):
            return rec if rid == rec["id"] else None

        def save_state(self):
            pass

    real = pp.postcheck
    pp.postcheck = lambda *a, **k: calls.append(1)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            result = pp.run_phase(_Ctx(), [rec["id"]], cmd=["true"], timeout=1, jobs=1,
                                  retries=0, manual=True, nowait=False, poll=1, label="test")
    finally:
        pp.postcheck = real
    out = buf.getvalue()
    check("F210 the manual recovery message states run does not re-verify",
          "does NOT re-verify a failed attempt" in out, out[-240:])
    check("F210 no postcheck is run for a preserved failed attempt",
          calls == [] and result == (False, False), f"{calls} {result}")


# ---------------------------------------------------------------------------
# F234 -- OOXML media parts are capped and streamed, not read whole
# ---------------------------------------------------------------------------
def test_f234_media_budget():
    tmp = scratch("f234")
    p = tmp / "ms.docx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "<w:document/>")
        z.writestr("word/media/image1.png", b"x" * 400)
    real_part = pp.MEDIA_PART_MAX_BYTES
    real_total = pp.MEDIA_TOTAL_MAX_BYTES
    try:
        pp.MEDIA_PART_MAX_BYTES = 100
        pp.MEDIA_TOTAL_MAX_BYTES = 1000
        over = pp.embedded_media_digests(tmp, ["ms.docx"])
        check("F234 an over-budget media part is skipped, not decompressed",
              over == {}, repr(over))
        pp.MEDIA_PART_MAX_BYTES = 10 ** 6
        under = pp.embedded_media_digests(tmp, ["ms.docx"])
        check("F234 an under-budget media part is still hashed",
              len(under) == 1, repr(under))
    finally:
        pp.MEDIA_PART_MAX_BYTES = real_part
        pp.MEDIA_TOTAL_MAX_BYTES = real_total


# ---------------------------------------------------------------------------
# F253 -- the redlines manifest accumulates across per-round invocations
# ---------------------------------------------------------------------------
def test_f253_redline_manifest_accumulates():
    dtl = load("fb1115wave2_rest_dtl", ".paper_test/difference_tracking_lib.py")
    tmp = scratch("f253")
    root = tmp / "root"
    root.mkdir()
    ctx = dtl.build_root(root, dtl.build_source(tmp))
    nb = dtl.nb
    nb.run_redlines(ctx, rounds=[1], tool="builtin", quiet=True)
    first = [v for v in ((nb.read_json(root / "redlines/manifest.json") or {})
                         .get("versions") or []) if v.get("round") == 1]
    nb.run_redlines(ctx, rounds=[2], tool="builtin", quiet=True)
    versions = ((nb.read_json(root / "redlines/manifest.json") or {})
                .get("versions") or [])
    keys = {(v.get("round"), v.get("version")) for v in versions}
    check("F253 the round-1 rows survive the round-2 invocation",
          bool(first) and all((v.get("round"), v.get("version")) in keys for v in first),
          repr(sorted(keys)))
    check("F253 the round-2 rows are recorded too",
          any(v.get("round") == 2 for v in versions), repr(sorted(keys)))


# ---------------------------------------------------------------------------
# F264 -- a scoped root is never a synthesized frozen review
# ---------------------------------------------------------------------------
def test_f264_scoped_frozen_review():
    scoped = types.SimpleNamespace(cfg={"guided_review": "off",
                                        "revision_mode": "major"})
    check("F264 a scoped --no-guided-review root is not a synthesized frozen review",
          pp.frozen_review_is_synthesized(scoped) is False)
    plain = types.SimpleNamespace(cfg={"guided_review": "off"})
    check("F264 a FULL --no-guided-review root still is",
          pp.frozen_review_is_synthesized(plain) is True)


def main() -> int:
    tests = [
        test_ranking_no_eligible_tiebreak,
        test_repair_missing_file,
        test_setup_nesting_before_delete,
        test_declaration_per_hint_state,
        test_pkg_containment,
        test_pkg3_and_readme,
        test_readiness_gaps_and_readme,
        test_small_p12_predicates,
        test_redline_fidelity_fixes,
        test_f208_auto_round_payload,
        test_f209_scoped_winner_digest,
        test_f210_manual_recovery_message,
        test_f234_media_budget,
        test_f253_redline_manifest_accumulates,
        test_f264_scoped_frozen_review,
        test_rewire_parent_path,
        test_tex_symlink_loop,
    ]
    for fn in tests:
        try:
            fn()
        except Exception as e:                                    # noqa: BLE001
            check(f"{fn.__name__} raised", False, f"{type(e).__name__}: {e}")
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s):")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)

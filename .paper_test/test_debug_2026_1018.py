#!/usr/bin/env python3
"""The 2026-10-18 debug round: re-derived defects from the general-audit reports.

Run:  python3 .paper_test/test_debug_2026_1018.py

Every check below was reproduced on the unmodified tree first.  The audit
reports only seeded the list; the assertions pin what was actually wrong:

  * C01 an empty `_pipeline_done.json` (`{}`) satisfied the completion gate
    because a missing `status` was only a warning;
  * C02 any figure PNG/PDF under the package satisfied the visual-inspection
    gate, although the prompt tells sessions to render into `work/`;
  * C03 a stdout context-overflow error was missed whenever stderr carried an
    unrelated warning, so the oversized session was resumed;
  * C04 the documented "every prompt carries a context budget" rule was absent
    from the continuation, repair, template, add-venue and audit prompts;
  * C07 `Supplemental*` and `coverletter*` were classified as `main`;
  * C08 a placeholder-scanner exception was silently reported as "0 markers";
  * C09 PKG-2 rewrote `work/` scratch notes;
  * C10 the documented incumbent-retention rule was missing from the selector
    (pinned in test_grading_scheme.py);
  * C11 non-shippable files under the stage's `code/` area reached the corpus;
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []
TMPDIRS = []


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_debug1018_pipeline", WS / "paper_pipeline.py")


def check(name: str, cond, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# C01: an empty completion marker is not a completion signal
# ---------------------------------------------------------------------------
def test_empty_marker_rejected() -> None:
    print("\n== C01: the completion marker needs a completion status ==")
    rec = {"id": "r1_a2_revise", "kind": "revise", "round": 1}
    errs, warns = [], []
    pp._marker_checks(rec, {}, "revise", errs, warns)
    check("C01 an empty marker is REJECTED",
          bool(errs), f"errs={errs!r} warns={warns!r}")
    errs, warns = [], []
    pp._marker_checks(rec, {"stage": "revise", "run_id": rec["id"], "round": 1,
                            "status": "complete"}, "revise", errs, warns)
    check("C01 a complete marker without the optional summary still passes",
          not errs, f"errs={errs!r}")
    errs, warns = [], []
    pp._marker_checks(rec, {"stage": "revise", "run_id": rec["id"], "round": 1},
                      "revise", errs, warns)
    check("C01 a marker without status is REJECTED",
          any("status" in e for e in errs), f"errs={errs!r}")
    prompt = pp.audit_prompt(Path("/tmp/sb"), "r1_audit", 1)
    check("C01 the audit prompt asks for the status the checker requires",
          '"status": "complete"' in prompt, prompt[-500:])


# ---------------------------------------------------------------------------
# C02: a figure asset is not rendered-page evidence
# ---------------------------------------------------------------------------
def test_visual_evidence_is_render_scratch() -> None:
    print("\n== C02: visual evidence is a rendering, not a shipped figure ==")
    root = scratch("paper_vis_1018_")
    (root / "figures").mkdir(parents=True)
    (root / "figures" / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    art = root / "VISUAL_CHECK.md"
    art.write_text("Renderer: fake. All pages rendered and looked at; no defects found.\n",
                   encoding="utf-8")
    old_probe = pp.visual_tools_available
    pp.visual_tools_available = lambda: True
    try:
        errs, warns = [], []
        pp.check_visual_artifact(art, "the visual record", errs, warns,
                                 render_roots=[root])
        check("C02 a package figure alone does NOT satisfy the gate",
              bool(errs), f"errs={errs[:1]}")
        (root / "work").mkdir()
        (root / "work" / "page-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        errs, warns = [], []
        pp.check_visual_artifact(art, "the visual record", errs, warns,
                                 render_roots=[root])
        check("C02 a render under work/ satisfies the gate",
              not errs, f"errs={errs[:1]}")
        (root / "work" / "page-1.png").unlink()
        art.write_text("Renderer: none. All pages NOT visually verified.\n", encoding="utf-8")
        errs, warns = [], []
        pp.check_visual_artifact(art, "the visual record", errs, warns,
                                 render_roots=[root])
        check("C02 the documented escape hatch still passes (with a warning)",
              not errs and warns, f"errs={errs[:1]} warns={warns[:1]}")
    finally:
        pp.visual_tools_available = old_probe


# ---------------------------------------------------------------------------
# C03: both streams, and the common provider spellings
# ---------------------------------------------------------------------------
def test_context_overflow_both_streams() -> None:
    print("\n== C03: a context overflow is classified on either stream ==")
    mixed = ("ERROR: unexpected status 413 Payload Too Large",
             "warning: retrying request once")
    check("C03 a mixed-stream 413 is context overflow",
          pp.agent_failure_kind(*mixed) == "context_overflow", str(mixed))
    for text in (
            "Error: 400 Your input exceeds the context window of this model",
            "context_length_exceeded",
            "HTTP 413: Request Too Large",
            "Payload Too Large",
            "413 Payload Too Large",
            "Error: 413 Payload Too Large",
            "maximum context length is 4096 tokens",
            "prompt is too long: 250000 tokens > 200000 maximum",
            "input is too long for requested model",
            "too many tokens in the request"):
        check(f"C03 {text[:42]!r} is context overflow",
              pp.agent_failure_kind("", text) == "context_overflow", text)
    check("C03 an ordinary failure stays unclassified",
          pp.agent_failure_kind("", "agent exited rc=1") == "")
    sb = scratch("paper_exec_1018_")
    (sb / "PROMPT.md").write_text("noop", encoding="utf-8")
    rec = {"id": "r1_targeted_review", "kind": "targeted_review", "round": 1, "sandbox": str(sb)}
    cmd = [sys.executable, "-c",
           "import sys; print('ERROR: unexpected status 413 Payload Too Large'); "
           "print('warning: retrying request once', file=sys.stderr); sys.exit(1)"]
    res = pp._execute_attempt_in(sb, rec, cmd, 30)
    check("C03 the CALLER reads stdout even when stderr is non-empty",
          res.get("failure_kind") == "context_overflow", str(res.get("failure_kind")))


# ---------------------------------------------------------------------------
# C04: the context budget travels with every session prompt
# ---------------------------------------------------------------------------
def test_context_budget_is_global() -> None:
    print("\n== C04: every session prompt carries the context budget ==")
    role = {"id": "r1_targeted_review", "kind": "targeted_review", "round": 1}
    prompts = {
        "continuation": pp.resume_prompt(role, ["x"], "stopped", 0),
        "defect audit": pp._defect_audit_prompt(1, 2),
        "conflict audit": pp._judge_conflict_agent_prompt(1),
        "add-venue": pp.add_venue_prompt("demo", Path("/tmp/demo")),
    }
    root = scratch("paper_ctx_1018_")
    ctx = pp.Ctx(root)
    ctx.cfg = {"author_to_complete": "readme"}
    prompts["artifact repair"] = pp.repair_prompt(
        ctx, {"id": "r1_w1", "kind": "rewrite", "round": 1}, ["a problem"])
    src = root / "source"
    src.mkdir()
    (src / "manuscript.docx").write_bytes(b"x")
    prompts["guideline conform"] = pp.apply_template_prompt(
        ctx, root / "out", src, {})
    for name, text in prompts.items():
        check(f"C04 the {name} prompt carries the context budget",
              "CONTEXT BUDGET" in text, text[:80])


# ---------------------------------------------------------------------------
# C07: supplemental and coverletter are document roles
# ---------------------------------------------------------------------------
def test_document_roles() -> None:
    print("\n== C07: supplemental*/coverletter* are document roles ==")
    roles = {name: pp.docx_document_role(name) for name in (
        "Supplemental_Material.docx", "Supplemental.tex", "supplemental_figure_1.pdf",
        "SupplementaryMaterial.docx", "coverletter.docx", "CoverLetter.tex")}
    check("C07 every supplemental spelling is `supp`",
          all(roles[n] == "supp" for n in roles if n.lower().startswith("supp")),
          str(roles))
    check("C07 every coverletter spelling is `cover`",
          all(roles[n] == "cover" for n in roles if n.lower().startswith("cover")),
          str(roles))
    check("C07 the old false-positive names stay `main`",
          all(pp.docx_document_role(n) == "main"
              for n in ("support.docx", "coverage_table.docx", "newsletter.docx")))
    check("C07 the cover-letter line detector sees `coverletter`",
          pp._is_cover_letter_lines([], "coverletter.docx"))
    check("C07 `coverletter` is submission content, not journal feedback",
          pp.is_non_manuscript_rel("coverletter.docx") is False
          and bool(pp.JOURNAL_AUTHORED_REPLY_RE.search("coverletter.docx")))
    check("C07 the word-match still refuses the old substrings",
          all(not pp._COVER_WORD_RE.search(n)
              for n in ("coverage_table.txt", "discovery.md", "recovered_notes.tex")))


# ---------------------------------------------------------------------------
# C08: a scanner failure is not "zero markers"
# ---------------------------------------------------------------------------
def test_placeholder_scan_failure_is_loud() -> None:
    print("\n== C08: a failed placeholder scan is a gap, not a clean package ==")
    root = scratch("paper_ph_1018_")
    pkg = root / "revised"
    pkg.mkdir()
    (pkg / "main.md").write_text("A clean paragraph.\n", encoding="utf-8")
    ctx = pp.Ctx(root)
    ctx.cfg = {}

    def boom(_sources):
        raise OSError("scan unavailable")

    old = pp.scan_placeholders_in_sources
    pp.scan_placeholders_in_sources = boom
    try:
        errs, warns = [], []
        rep = pp.placeholder_residual_report(ctx, root, [(pkg, "", ())],
                                             "revise", True, errs, warns)
    finally:
        pp.scan_placeholders_in_sources = old
    check("C08 the scanner failure FAILS the gate",
          bool(errs), f"errs={errs!r}")
    check("C08 the report records the gap",
          bool(rep.get("handoff_marker_scan_error")), str(rep))
    old_fmt = pp._format_module
    pp._format_module = lambda: None
    try:
        errs, warns = [], []
        rep_none = pp.placeholder_residual_report(ctx, root, [(pkg, "", ())],
                                                  "revise", True, errs, warns)
    finally:
        pp._format_module = old_fmt
    check("C08 an unavailable OOXML engine is a RECORDED gap, not a clean package",
          bool(errs) and bool(rep_none.get("handoff_marker_scan_error")),
          f"errs={errs!r} rep={rep_none!r}")


# ---------------------------------------------------------------------------
# C09: PKG-2 never edits work/ scratch
# ---------------------------------------------------------------------------
def test_pkg2_leaves_work_scratch() -> None:
    print("\n== C09: PKG-2 leaves the package's work/ scratch alone ==")
    root = scratch("paper_pkg2_1018_")
    (root / "work").mkdir()
    (root / "main.md").write_text("See code/analysis.py for the run.\n"
                                  "See work/notes.md for the scratch note.\n",
                                  encoding="utf-8")
    note = root / "work" / "notes.md"
    note.write_text("Scratch note: See code/analysis.py for the run.\n", encoding="utf-8")
    pp.strip_dangling_references_in_dir(root, ["code"], "test")
    check("C09 work/notes.md is byte-identical",
          note.read_text(encoding="utf-8")
          == "Scratch note: See code/analysis.py for the run.\n",
          note.read_text(encoding="utf-8"))
    shipped = (root / "main.md").read_text(encoding="utf-8")
    check("C09 the shipped document was still repaired",
          "code/analysis.py" not in shipped, shipped)
    check("C09 a shipped pointer into work/ is dangling, not 'shipped'",
          "work/notes.md" not in shipped, shipped)


# ---------------------------------------------------------------------------
# C11: the stage sweep also covers the folded code/ area
# ---------------------------------------------------------------------------
def test_code_area_sweep() -> None:
    print("\n== C11: the stage sweep covers code/ as well as the package ==")
    root = scratch("paper_code_1018_")
    sb = root / "runs" / "r1_w1"
    (sb / "base").mkdir(parents=True)
    pkg = sb / "rewritten"
    pkg.mkdir()
    (pkg / "main.md").write_text("text\n", encoding="utf-8")
    (pkg / "work").mkdir()
    (pkg / "work" / "notes.md").write_text("scratch\n", encoding="utf-8")
    cache = sb / "code" / "__pycache__"
    cache.mkdir(parents=True)
    pyc = cache / "m.pyc"
    pyc.write_bytes(b"bytecode")
    junk = pkg / "fig.png:Zone.Identifier"
    junk.write_text("[ZoneTransfer]\nZoneId=3\n", encoding="utf-8")
    ctx = pp.Ctx(root)
    ctx.cfg = {"format_fix": "on", "author_to_complete": "readme"}
    rec = {"id": "r1_w1", "kind": "rewrite", "round": 1,
           "sandbox": "runs/r1_w1"}
    patches = dict(
        ensure_handoff_readme=lambda *a, **k: {},
        hold_internal_readme_notes=lambda *a, **k: [],
        strip_dangling_references_in_dir=lambda *a, **k: {"removed": 0},
        zotero_field_continuity_check=lambda *a, **k: {"errors": []},
        normalize_formatting_in_dir=lambda *a, **k: {"rows": []},
        _scan_rule_delta=lambda *a, **k: [],
        _validate_stage_package=lambda *a, **k: {},
        code_side_evidence=lambda *a, **k: {},
    )
    with mock.patch.multiple(pp, **patches):
        pp._format_fix_stage_package(ctx, rec, pkg, [])
    check("C11 code/__pycache__/m.pyc is gone BEFORE the corpus digest",
          not pyc.exists(), f"stripped={rec.get('non_shippable_strip')!r}")
    check("C11 the stage record names the code/ removal",
          (rec.get("non_shippable_strip") or {}).get("code", {}).get("removed")
          == ["__pycache__/m.pyc"], str(rec.get("non_shippable_strip")))
    check("C11 the package's own junk is gone too",
          not junk.exists(), f"stripped={rec.get('non_shippable_strip')!r}")


def main() -> int:
    test_empty_marker_rejected()
    test_visual_evidence_is_render_scratch()
    test_context_overflow_both_streams()
    test_context_budget_is_global()
    test_document_roles()
    test_placeholder_scan_failure_is_loud()
    test_pkg2_leaves_work_scratch()
    test_code_area_sweep()
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL 2026-10-18 DEBUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

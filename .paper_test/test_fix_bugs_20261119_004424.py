#!/usr/bin/env python3
"""Regression checks for fix-bugs run 20261119-004424, wave 1.

Run:  python3 .paper_test/test_fix_bugs_20261119_004424.py

Every check names the verified candidate it proves. The suite is hermetic
(temporary roots only) and exits 1 on any failure.
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

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS))
import paper_pipeline as pp                                                   # noqa: E402

FAILS: list = []
TMPDIRS: list = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def scratch(prefix: str = "fb1119_") -> Path:
    path = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(path)
    return path


def cleanup() -> None:
    for path in TMPDIRS:
        shutil.rmtree(path, ignore_errors=True)


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}"
          + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def pair(prefix: str, base_files: dict, cand_files: dict):
    root = scratch(prefix)
    base, cand = root / "base", root / "revised"
    base.mkdir()
    cand.mkdir()
    for name, text in base_files.items():
        write(base / name, text)
    for name, text in cand_files.items():
        write(cand / name, text)
    return base, cand


# =====================================================================
# p07 -- content gates
# =====================================================================
def test_f09_docx_reference_entries() -> None:
    print("\n== F09: a DOCX reference-list entry is visible to the reference gate ==")
    from docx import Document

    root = scratch("f09_")
    base, cand = root / "base", root / "revised"
    base.mkdir()
    cand.mkdir()
    for folder, refs in (
            (base, ["[1] Smith J. Alpha. 2020.", "[2] Jones K. Beta. 2021."]),
            (cand, ["[1] Smith J. Alpha. 2020.", "[3] Fake Q. Gamma. 2024."])):
        doc = Document()
        doc.add_paragraph("We measured tumour volume every day.")
        doc.add_heading("References", level=1)
        for ref in refs:
            doc.add_paragraph(ref)
        doc.save(str(folder / "ms.docx"))
    added, removed = pp._reference_entry_changes(base, cand)
    got = pp.content_edit_problems(None, base, cand, "revise",
                                   insertions_allowed=False, deletions_allowed=False)
    check("F09 a fabricated DOCX reference entry is an insertion",
          any("[3] fake q" in x for x in added)
          and any("reference entr" in p for p in got), (added, got))
    check("F09 a deleted DOCX reference entry is a deletion",
          any("[2] jones k" in x for x in removed)
          and any("MISSING" in p for p in got), (removed, got))


def test_f28_exemption_is_consumed() -> None:
    print("\n== F28: a pipeline-removal exemption is consumed one-to-one ==")
    sent = "We measured tumour volume every day in the cohort."
    base, cand = pair("f28_", {"ms.md": f"{sent}\n\n{sent}\n"},
                      {"ms.md": "Another ordinary sentence survives.\n"})
    got = pp.content_edit_problems(None, base, cand, "revise",
                                   exempt_removed=[sent],
                                   insertions_allowed=True, deletions_allowed=False)
    check("F28 deleting the second identical copy is still a deletion",
          any("MISSING" in p for p in got), str(got))


def test_f36_reference_heading_variants() -> None:
    print("\n== F36: 'References and Notes' is a recognised bibliography heading ==")
    base, cand = pair(
        "f36_",
        {"ms.md": "# References and Notes\n[1] Smith J. Alpha. 2020.\n"
                  "[2] Jones K. Beta. 2021.\n"},
        {"ms.md": "# References and Notes\n[1] Smith J. Alpha. 2020.\n"
                  "[3] Fake Q. Gamma. 2024.\n"})
    added, removed = pp._reference_entry_changes(base, cand)
    got = pp.content_edit_problems(None, base, cand, "revise",
                                   insertions_allowed=False, deletions_allowed=False)
    check("F36 entries under the variant heading are compared",
          bool(added) and bool(removed) and bool(got), (added, removed))


def test_f38_rst_html_surfaces() -> None:
    print("\n== F38: .rst/.html prose is also a citation/reference surface ==")
    base, cand = pair(
        "f38_",
        {"ms.rst": "The effect is large.\n\nReferences\n----------\n\n"
                   "[1] Smith J. Alpha. 2020.\n"},
        {"ms.rst": "The effect is large.\n\nReferences\n----------\n\n"
                   "[1] Smith J. Alpha. 2020.\n[2] Fake Q. Gamma. 2024.\n"})
    added, _removed = pp._reference_entry_changes(base, cand)
    check("F38 an .rst reference insertion is seen", bool(added), str(added))
    base2, cand2 = pair("f38b_", {"ms.rst": "Text \\cite{smith2020} here.\n"},
                        {"ms.rst": "Text \\cite{smith2020,jones2021} here.\n"})
    delta = (pp._citation_keys(cand2, include_bibliography=False)
             - pp._citation_keys(base2, include_bibliography=False))
    check("F38 an .rst citation insertion is seen", "jones2021" in delta, str(delta))
    _html = "<html><body><h1>References</h1>{}</body></html>\n"
    base3, cand3 = pair(
        "f38h_",
        {"ms.html": _html.format("<p>[1] Smith J. Alpha. 2020.</p>"
                                 "<p>[2] Jones K. Beta. 2021.</p>")},
        {"ms.html": _html.format("<p>[1] Smith J. Alpha. 2020.</p>"
                                 "<p>[2] Jones K. Beta. 2021.</p>"
                                 "<p>[3] Fake Q. Gamma. 2024.</p>")})
    added3, _removed3 = pp._reference_entry_changes(base3, cand3)
    got3 = pp.content_edit_problems(None, base3, cand3, "revise",
                                    insertions_allowed=False, deletions_allowed=False)
    check("F38 an .html reference insertion is seen",
          any("[3] fake q" in x for x in added3)
          and any("reference entr" in p for p in got3), (added3, got3))
    base4, cand4 = pair(
        "f38hd_",
        {"ms.html": _html.format("<p>[1] Smith J. Alpha. 2020.</p>"
                                 "<p>[2] Jones K. Beta. 2021.</p>")},
        {"ms.html": _html.format("<p>[1] Smith J. Alpha. 2020.</p>")})
    _added4, removed4 = pp._reference_entry_changes(base4, cand4)
    got4 = pp.content_edit_problems(None, base4, cand4, "revise",
                                    insertions_allowed=False, deletions_allowed=False)
    check("F38 an .html reference deletion is seen",
          any("[2] jones k" in x for x in removed4)
          and any("MISSING" in p for p in got4), (removed4, got4))


def test_f117_heading_with_prose() -> None:
    print("\n== F117: prose sharing a line with a LaTeX heading command ==")
    base, cand = pair("f117_", {"ms.tex": "\\section{Methods} We ran the assay in mice.\n"},
                      {"ms.tex": "\\section{Methods}\n"})
    units = pp._content_unit_sentences(base)
    got = pp.content_edit_problems(None, base, cand, "revise",
                                   insertions_allowed=True, deletions_allowed=False)
    check("F117 the prose after a heading command is a content unit",
          any("We ran the assay" in u["text"] for u in units), str(units))
    check("F117 deleting that prose is a deletion", bool(got), str(got))


def test_f120_identity_typos() -> None:
    print("\n== F120: same-domain and wide domain identity spellings ==")
    base, cand = pair("f120_",
                      {"ms.md": "Contact j.smith@univ.edu for data.\n"},
                      {"ms.md": "Contact j.smith@univ.edu for data.\n"
                                "Contact jsmith@univ.edu for code.\n"})
    got = pp.identity_typo_problems(cand)
    check("F120 one domain, two local spellings is reported", bool(got), str(got))
    _b2, cand2 = pair("f120b_", {"ms.md": "Write to a@uni.edu.\n"},
                      {"ms.md": "Write to a@uni.edu.\nAlso a@uni-edu.org.\n"})
    got2 = pp.identity_typo_problems(cand2)
    check("F120 a wider domain typo is reported",
          any("uni-edu.org" in p for p in got2), str(got2))


def test_f121_handoff_dates() -> None:
    print("\n== F121: a hand-off date does not exempt a real fact loss ==")
    base, cand = pair(
        "f121_",
        {"ms.md": "The dose was 11 mg in every animal.\n",
         "MANUAL_STEPS.md": "| T-001 | checked on 2026-11-01 | open |\n"},
        {"ms.md": "The animals were treated.\n",
         "MANUAL_STEPS.md": "| T-001 | checked on 2026-11-01 | open |\n"})
    keys = pp._manual_handoff_keys(cand)
    got = pp.fact_preservation_problems(base, cand, "revise")
    check("F121 date components are not hand-off fact keys",
          not ({"1.0", "11.0", "2026.0"} & keys), str(sorted(keys)))
    check("F121 the deleted '11 mg' value is reported",
          any("11 mg" in p for p in got), str(got))


def test_f124_split_citation() -> None:
    print("\n== F124: a citation moved by a sentence split is not a removal ==")
    base, cand = pair("f124_", {"ms.md": "The effect is large (Smith, 2020).\n"},
                      {"ms.md": "The effect is large. (Smith, 2020).\n"})
    got = pp.content_edit_problems(None, base, cand, "revise",
                                   insertions_allowed=True, deletions_allowed=False)
    check("F124 a surviving citation split across units is not a deletion",
          not any("citation key" in p for p in got), str(got))


def test_f125_thebibliography_correction() -> None:
    print("\n== F125: a thebibliography/bibitem key correction passes ==")

    def tex(key):
        return ("\\documentclass{article}\\begin{document}\n"
                f"As shown \\cite{{{key}}}, the effect is large.\n"
                "\\begin{thebibliography}{9}\n"
                "\\bibitem{smith2020} Smith J. Alpha. 2020.\n"
                "\\bibitem{smith2021} Smith J. Beta. 2021.\n"
                "\\end{thebibliography}\n\\end{document}\n")

    base, cand = pair("f125_", {"ms.tex": tex("smith2020")},
                      {"ms.tex": tex("smith2021")})
    got = pp.content_edit_problems(None, base, cand, "revise",
                                   insertions_allowed=False, deletions_allowed=True)
    check("F125 thebibliography correction is not a new citation",
          not any("smith2021" in p for p in got), str(got))


def test_f126_reference_correction_prose() -> None:
    print("\n== F126: an accepted reference correction is not delete+insert prose ==")
    url = "https://example.org/" + ("a" * 400)
    base, cand = pair(
        "f126_",
        # A genuine in-place correction shares the identity (first author +
        # year); a different-author/different-year entry is a FABRICATED
        # replacement, which F150 of the 2026-11-19 wave now refuses to pair.
        {"ms.md": "# References\n\nSmith J, Doe A, 2020, Short titel, " + url + "\n"},
        {"ms.md": "# References\n\nSmith J, Doe A, 2020, Short title, " + url + "\n"})
    added, removed = pp._reference_entry_changes(base, cand)
    got = pp.content_edit_problems(None, base, cand, "revise",
                                   insertions_allowed=False, deletions_allowed=False)
    check("F126 the entry comparator accepts the correction", not added and not removed,
          (added, removed))
    check("F126 the prose comparator no longer reports it as delete+insert",
          not got, str(got))


def test_f84_set_revision_mode_guided_off() -> None:
    print("\n== F84: the setter keeps setup's --no-guided-review refusal ==")
    root = scratch("f84_")
    src = root / "src"
    src.mkdir()
    write(src / "ms.md", "# Title\n\nA short abstract.\n")
    setup = subprocess.run(
        [sys.executable, str(WS / "paper_pipeline.py"), "setup", "--source", str(src),
         "--root", str(root / "root"), "--rounds", "1", "--rewrites", "0",
         "--revises", "1", "--judges", "1", "--no-guided-review",
         "--revision-audit", "off"],
        capture_output=True, text=True, timeout=300)
    check("F84 the --no-guided-review root is created", setup.returncode == 0,
          (setup.stdout + setup.stderr)[-300:])
    proc = subprocess.run(
        [sys.executable, str(WS / "paper_pipeline.py"), "set-revision-mode",
         "--root", str(root / "root"), "transfer", "--force"],
        capture_output=True, text=True, timeout=300)
    out = proc.stdout + proc.stderr
    check("F84 switching to a feedback mode is refused",
          proc.returncode == 2 and "no-guided-review" in out, out[-400:])


def test_f129_hidden_email() -> None:
    print("\n== F129: a hidden (w:vanish) e-mail is invisible and its loss is a fact loss ==")
    from docx import Document

    root = scratch("f129_")
    base, cand = root / "base", root / "revised"
    base.mkdir()
    cand.mkdir()
    address = "alice@univ.edu"
    for folder, hidden in ((base, False), (cand, True)):
        doc = Document()
        para = doc.add_paragraph(
            f"Contact the corresponding author at {address} for data.")
        if hidden:
            for run in para.runs:
                if address in run.text:
                    run.font.hidden = True
        doc.save(str(folder / "ms.docx"))
    texts, _gap = pp._email_texts_in_file(cand / "ms.docx")
    check("F129 the hidden address is not read as visible text",
          not any(address in t for t in texts), str(texts))
    got = pp.fact_preservation_problems(base, cand, "revise")
    check("F129 hiding the address is reported as a lost fact",
          any(address in p for p in got), str(got))


# =====================================================================
# p05 -- trial selection
# =====================================================================
class FakeCtx:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.runs_dir = self.root / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.cfg = {"tolerate_fail": "on"}
        self._runs = {}

    def sandbox_of(self, rec):
        return self.runs_dir / rec["id"]

    def save_state(self):
        pass

    def log(self, *args, **kwargs):
        pass

    def run(self, rid):
        return self._runs.get(rid)

    def runs(self, kind=None, round_no=None):
        out = list(self._runs.values())
        if kind is not None:
            out = [r for r in out if r.get("kind") == kind]
        if round_no is not None:
            out = [r for r in out if int(r.get("round") or 0) == int(round_no)]
        return out


def _trial(ctx, name, files, errors, marker=None, record=None) -> Path:
    sb = ctx.runs_dir / name
    (sb / "guided_review").mkdir(parents=True, exist_ok=True)
    for f in files:
        (sb / "guided_review" / f).write_text("x\n", encoding="utf-8")
    if marker is not None:
        (sb / "_pipeline_done.json").write_text(json.dumps(marker), encoding="utf-8")
    if record is not None:
        (sb / "record.json").write_text(json.dumps(record), encoding="utf-8")
    return sb


def test_f18_f97_marker_validation() -> None:
    print("\n== F18/F97: an empty or foreign marker is not a usable trial ==")
    rid = "r1_guided_review"
    for label, marker in (("empty", {}),
                          ("foreign", {"stage": "audit", "run_id": "r1_audit"})):
        ctx = FakeCtx(scratch(f"f18_{label}_"))
        rec = {"id": rid, "kind": "guided_review", "status": "failed", "attempt": 1,
               "attempts_log": [{"attempt": 1, "ok": False, "errors": ["e"]}]}
        ctx._runs[rid] = rec
        _trial(ctx, f"{rid}_try1_failed", ["a.md"], ["e"], marker=marker,
               record={"run_id": rid, "kind": "guided_review", "errors": ["e"]})
        check(f"F18/F97 a {label} marker does not make the trial usable",
              pp.best_failed_trial(ctx, rec) is None)
    ctx = FakeCtx(scratch("f97_own_"))
    rec = {"id": rid, "kind": "guided_review", "status": "failed", "attempt": 1,
           "attempts_log": [{"attempt": 1, "ok": False, "errors": ["e"]}]}
    ctx._runs[rid] = rec
    _trial(ctx, f"{rid}_try1_failed", ["a.md"], ["e"],
           marker={"stage": "guided_review", "run_id": rid},
           record={"run_id": rid, "kind": "guided_review", "errors": ["e"]})
    check("F97 this run's own marker still makes the trial usable",
          pp.best_failed_trial(ctx, rec) is not None)


def test_f107_f108_selection() -> None:
    print("\n== F107/F108: missing record and collision-suffixed archive ==")
    rid = "r1_guided_review"
    ctx = FakeCtx(scratch("f107_"))
    rec = {"id": rid, "kind": "guided_review", "status": "failed", "attempt": 2,
           "attempts_log": [{"attempt": 2, "ok": False, "errors": ["e"]}]}
    ctx._runs[rid] = rec
    _trial(ctx, f"{rid}_try1_failed", ["a.md"], [], marker={"run_id": rid}, record=None)
    _trial(ctx, f"{rid}_try2_failed", ["a.md"], ["e1"], marker={"run_id": rid},
           record={"attempt": 2, "kind": "guided_review", "errors": ["e1"]})
    best = pp.best_failed_trial(ctx, rec)
    check("F107 a record-less archive does not win the tie-break",
          best is not None and best["sandbox"].name.endswith("try2_failed")
          and best["record_known"], str(best))
    ctx = FakeCtx(scratch("f108_"))
    rec = {"id": rid, "kind": "guided_review", "status": "failed", "attempt": 2,
           "attempts_log": [{"attempt": 2, "ok": False, "errors": ["e"]}]}
    ctx._runs[rid] = rec
    _trial(ctx, f"{rid}_try1_failed", ["a.md"], [], marker={"run_id": rid},
           record={"run_id": rid, "errors": []})
    _trial(ctx, f"{rid}_try2_failed-2", ["a.md", "b.md"], [], marker={"run_id": rid},
           record={"run_id": rid, "errors": []})
    best = pp.best_failed_trial(ctx, rec)
    check("F108 a collision-suffixed archive is still selectable",
          best is not None and best["sandbox"].name.endswith("-2"), str(best))


def test_f98_f111_generation_and_promotion() -> None:
    print("\n== F98/F111: input generation and the promoted trial's path ==")
    rid = "r1_guided_review"
    ctx = FakeCtx(scratch("f98_"))
    rec = {"id": rid, "kind": "guided_review", "status": "failed", "attempt": 2,
           "inputs_manifest": {"base": {"new.md": "aaa"}},
           "attempts_log": [{"attempt": 2, "ok": False, "errors": ["e"]}]}
    ctx._runs[rid] = rec
    _trial(ctx, f"{rid}_try1_failed", ["a.md"], [], marker={"run_id": rid},
           record={"run_id": rid, "errors": [], "inputs_generation": "OLD"})
    check("F98 an archive from superseded inputs is skipped",
          pp.best_failed_trial(ctx, rec) is None)

    ctx = FakeCtx(scratch("f111_"))
    rec = {"id": rid, "kind": "guided_review", "status": "failed", "attempt": 2,
           "attempts_log": [{"attempt": 2, "ok": False, "errors": ["e"],
                             "archive": f"runs/{rid}_try1_failed"}]}
    ctx._runs[rid] = rec
    _trial(ctx, f"{rid}_try1_failed", ["a.md"], [], marker={"run_id": rid},
           record={"run_id": rid, "errors": [],
                   "moved_to": f"runs/{rid}_try1_failed"})
    used = pp.use_best_failed_trial(ctx, rec)
    active = ctx.sandbox_of(rec)
    record = json.loads((active / "record.json").read_text(encoding="utf-8")) \
        if (active / "record.json").is_file() else {}
    moved = str(record.get("moved_to") or "")
    check("F111 the promoted trial's record points at the active path",
          used and moved == f"runs/{rid}" and (ctx.root / moved).is_dir(),
          (used, moved))
    entry = next((e for e in (rec.get("attempts_log") or [])
                  if isinstance(e, dict) and e.get("attempt") == 2), {})
    check("F111 the promoted trial's attempts_log entry points at the active path",
          used and entry.get("archive") == f"runs/{rid}"
          and entry.get("sandbox_moved_to") == f"runs/{rid}"
          and entry.get("promoted") is True
          and not (ctx.root / f"runs/{rid}_try1_failed").exists(),
          entry)


# =====================================================================
# p08/p09/p12/p20 -- invocation and decision bookkeeping
# =====================================================================
def test_f101_judge_hard_failure() -> None:
    print("\n== F101: a hard-failed judge is a hard failure of the invocation ==")
    original = pp.round_run_plan
    try:
        pp.round_run_plan = lambda ctx, r: [{"id": "r1_a2_revise"}]
        ctx = FakeCtx(scratch("f101_"))
        ctx._runs["r1_a2_revise"] = {"id": "r1_a2_revise", "kind": "revise",
                                     "status": "done", "round": 1}
        ctx._runs["r1_judge_tx_j1"] = {"id": "r1_judge_tx_j1", "kind": "judge",
                                       "status": "failed", "round": 1}
        tolerated, hard = pp._invocation_failure_state(ctx, [1])
        check("F101 a hard-failed judge is in the hard-FAIL list",
              "r1_judge_tx_j1" in hard, (tolerated, hard))
        check("F101 the invocation may not exit zero over it",
              pp._invocation_may_exit_zero(ctx, [1]) is False)
    finally:
        pp.round_run_plan = original


def test_f102_tolerated_reason() -> None:
    print("\n== F102: a tolerated final round names the tolerated reason ==")
    reason = pp.final_clean_reason(
        {"round": 2}, [{"round": 2, "mismatch": None}], 2, None, True, True, {},
        ["round(s) 2: a TOLERATED_FAIL stage's best failed trial was used"])
    check("F102 the tolerated note is the reason, not 'only round 2 of 2'",
          "TOLERATED_FAIL" in reason and "only round" not in reason, reason)


def test_f104_almost_fail_reset() -> None:
    print("\n== F104: a re-drive clears the legacy almost_fail record ==")
    src = (WS / "paper_pipeline_parts" / "p08_selection_driver.py").read_text(
        encoding="utf-8")
    check("F104 the re-drive pops almost_fail beside tolerated_fail",
          'rrec.pop("almost_fail", None)' in src
          and 'rrec.pop("tolerated_fail", None)' in src)


def test_f112_tolerated_selection() -> None:
    print("\n== F112: the re-derived selection keeps the tolerated run list ==")
    sel = pp.selection_with_tolerated(
        {"champion": "w1"},
        {"tolerated_fail": {"failed_runs": ["r1_a2_revise"]}})
    check("F112 the tolerated_fail record is injected",
          sel.get("tolerated_fail", {}).get("failed_runs") == ["r1_a2_revise"], sel)
    check("F112 the original selection is not mutated",
          "tolerated_fail" not in {"champion": "w1"})


# =====================================================================
# p08/p05/p04 -- safety and state
# =====================================================================
def test_f43_symlinked_revised() -> None:
    print("\n== F43: a symlinked revised/ root is refused by the snapshot ==")
    root = scratch("f43_")
    sb = root / "sb"
    sb.mkdir()
    outside = root / "outside"
    outside.mkdir()
    write(outside / "secret.md", "SECRET\n")
    os.symlink(outside, sb / "revised")
    reason = pp._snapshot_revised_prerepair(sb)
    check("F43 the symlinked root is refused",
          bool(reason) and not (sb / "revised_prerepair").exists(), reason)
    check("F43 no outside bytes entered the snapshot",
          not (sb / "revised_prerepair" / "secret.md").exists())


def test_f54_depth_cap() -> None:
    print("\n== F54: a deeply nested tree is a recorded gap ==")
    root = scratch("f54_")
    deep = root
    for _ in range(260):
        deep = deep / "d"
    deep.mkdir(parents=True)
    write(deep / "x.txt", "x")
    gaps = []
    files = pp._iter_tree_files(root, gaps=gaps)
    check("F54 the walk returns instead of raising RecursionError",
          isinstance(files, list) and bool(gaps), (len(files), len(gaps)))


def test_f67_state_mode() -> None:
    print("\n== F67: state.json and its backup are private ==")
    ctx = pp.Ctx(scratch("f67_"))
    ctx.state = {"version": 3, "runs": {}, "rounds": {}, "pinned": [], "log": [],
                 "judge_salt": "abc"}
    ctx.save_state()
    first = ctx.state_path.stat().st_mode & 0o777
    ctx.save_state()
    second = ctx.state_path.stat().st_mode & 0o777
    prev = pp.state_prev_path(ctx.state_path)
    check("F67 state.json is created 0600", second == 0o600, oct(second))
    check("F67 state.json.prev is 0600 too",
          prev.is_file() and (prev.stat().st_mode & 0o777) == 0o600,
          oct(prev.stat().st_mode & 0o777) if prev.is_file() else "missing")
    check("F67 the first save was already private", first == 0o600, oct(first))


def test_f106_classifier_snapshot() -> None:
    print("\n== F106: the previous-attempt record is snapshotted before launch ==")
    src = (WS / "paper_pipeline_parts" / "p08_selection_driver.py").read_text(
        encoding="utf-8")
    snap = src.find('previous_errors = read_text_bounded(sb / "PREVIOUS_ATTEMPT_ERRORS.md")')
    popen = src.find("proc = subprocess.Popen(cmd", max(0, snap))
    check("F106 the snapshot is read before the agent launches",
          0 <= snap < popen, (snap, popen))
    check("F106 the classifier uses the snapshot, not a post-exit read",
          "agent_exclude = (prompt, previous_errors)" in src)


def test_f171_bounded_include() -> None:
    print("\n== F171: an over-budget TeX include is not read whole ==")
    root = scratch("f171_")
    write(root / "huge.tex", "x" * 2000)
    old = pp.TEX_MAX_EXPANDED_CHARS
    try:
        pp.TEX_MAX_EXPANDED_CHARS = 1000
        out = pp._tex_expand_includes("\\input{huge}", root)
    finally:
        pp.TEX_MAX_EXPANDED_CHARS = old
    check("F171 the over-budget include is left as a named gap",
          "\\input{huge}" in out and len(out) < 2000, (len(out), out[:40]))


# =====================================================================
# p13 / docx -- subprocess output and redline interface
# =====================================================================
def test_f61_redline_guard_shape() -> None:
    print("\n== F61: redline_one_pair returns a dict on the input guard ==")
    root = scratch("f61_")
    base = root / "base.docx"
    revised = root / "revised.docx"
    base.write_bytes(b"PK")
    revised.write_bytes(b"PK")
    result = pp.redline_one_pair("builtin", [], base, revised, base)
    check("F61 the input guard returns a mapping with ok=False",
          isinstance(result, dict) and result.get("ok") is False, type(result).__name__)
    check("F61 the refusal names the input guard",
          any(a.get("backend") == "input-guard"
              for a in (result.get("attempts") or [])), str(result))


def test_f58_f73_bounded_children() -> None:
    print("\n== F58/F73: a flooding child is capped and killed ==")
    flood = [sys.executable, "-c",
             "import sys\nfor _ in range(2000): sys.stdout.write('x'*20000)"]
    result = pp._run_redline_cmd(flood, Path("/nonexistent-redline-out"), timeout=30)
    check("F58 the redline backend reports an over-budget stream",
          result.get("ok") is False and "budget" in str(result.get("detail") or ""),
          str(result)[:300])
    fmt = load("fb1119_fmt", "paper_docx_format.py")
    try:
        fmt._run_text_tool(flood, 30)
        raised = False
    except fmt.ToolOutputOverBudget:
        raised = True
    except Exception:                                                 # noqa: BLE001
        raised = False
    check("F73/F58 the formatter's child output is capped while it runs", raised)


def test_f190_pdf_descriptor() -> None:
    print("\n== F190: the PDF reader refuses a symlinked path ==")
    fmt = load("fb1119_fmt2", "paper_docx_format.py")
    root = scratch("f190_")
    outside = root / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4 secret")
    link = root / "planted.pdf"
    os.symlink(outside, link)
    check("F190 a symlinked PDF is not read", fmt._read_pdf_bounded(link) is None)
    real = root / "real.pdf"
    real.write_bytes(b"%PDF-1.4 ok")
    check("F190 a regular PDF is read", fmt._read_pdf_bounded(real) == b"%PDF-1.4 ok")


def test_f195_trackdiff_forms() -> None:
    print("\n== F195: only the shipped docx-trackdiff form is tried ==")
    src = (WS / "paper_pipeline_parts" / "p13_redlines.py").read_text(encoding="utf-8")
    check("F195 the unsupported --base/--revised form is gone",
          '"--base", str(base), "--revised"' not in src)
    check("F195 the unsupported -m docx_trackdiff form is gone",
          '"-m", "docx_trackdiff"' not in src)
    check("F195 the positional form remains",
          '["docx-trackdiff", str(base), str(revised), str(out)]' in src)


# =====================================================================
# prompts / policy / docs / harness
# =====================================================================
def test_f132_policy_flags() -> None:
    print("\n== F132: string policy flags parse the same on both sides ==")
    ctx = pp.Ctx(scratch("f132_"))
    ctx.cfg = {}
    rec = {"content_edit_policy": {"insertions": "false", "deletions": "false",
                                   "prefer_rewrite_over_deletion": "off"}}
    prompt = pp.content_edit_policy_for_sandbox(ctx, rec, ctx.root / "PROMPT.md")
    post = pp.content_edit_policy_allowed(ctx, rec)
    check("F132 the prompt materializer reads 'false' as off", prompt == (False, False), prompt)
    check("F132 prompt and postcheck agree", prompt == post, (prompt, post))
    check("F132 'off' is not a truthy prefer-rewrite",
          pp.prefer_rewrite_for_sandbox(ctx, rec, ctx.root / "PROMPT.md") is False)


def test_f138_ledger_types() -> None:
    print("\n== F138: a non-text ledger cell is not an explanation ==")
    rows = [{"id": "F-001", "verdict": "confirmed", "rationale": 5, "evidence": 6},
            {"id": "F-002", "verdict": "confirmed", "rationale": {"a": "b"},
             "evidence": [1]},
            {"id": "F-003", "verdict": "confirmed", "rationale": "source checked",
             "evidence": "main.md:1"}]
    missing = pp._ledger_rows_without_explanation(rows)
    check("F138 numeric/object/array cells are rejected",
          missing.get("F-001") == ["rationale", "evidence"]
          and missing.get("F-002") == ["rationale", "evidence"], str(missing))
    check("F138 a real text explanation still passes", "F-003" not in missing, str(missing))


def test_f147_dry_run_without_conda() -> None:
    print("\n== F147: --dry-run without conda prints the plan and exits 0 ==")
    env = dict(os.environ, PATH="/usr/bin:/bin")
    proc = subprocess.run(
        [str(WS / "install_dependencies.sh"), "--dry-run", "--no-external",
         "--no-node"],
        capture_output=True, text=True, timeout=300, env=env, cwd=str(WS))
    out = proc.stdout + proc.stderr
    check("F147 the dry run exits 0", proc.returncode == 0, proc.returncode)
    check("F147 the missing conda is a plan note, not a failure",
          "plan: conda is not on PATH" in out and "FAILED:" not in out, out[-400:])


def test_f158_guided_off_prompt() -> None:
    print("\n== F158: the audit prompt names the absent guided-review surfaces ==")
    sb = scratch("f158_")
    text = pp.audit_prompt(sb, "r1_audit", 1, guided_review_off=True)
    check("F158 the note says artifacts/work carry no seeded tables",
          "guided_review/artifacts/" in text and "guided_review/work/" in text
          and "carry no seeded" in text)
    check("F158 the note forbids inventing a table disposition",
          "do not invent a table" in text)


def test_f160_limit_conflict() -> None:
    print("\n== F160: conflicting top-level/per-type length limits are reported ==")
    data = {"id": "probe", "label": "Probe", "journal": "J",
            "article_types": [{"id": "article", "label": "Article",
                               "length_limits": {
                                   "abstract": {"base": 150, "relaxation": 1.0},
                                   "main_text": {"base": 3000, "relaxation": 1.0}}}],
            "length_limits": {"abstract": {"base": 200, "relaxation": 1.0},
                              "main_text": {"base": 4000, "relaxation": 1.0}}}
    try:
        pp.normalize_venue_profile(data, "probe.json")
        reported = ""
    except pp.VenueProfileError as e:
        reported = str(e)
    check("F160 the profile states the conflicting caps",
          "length_limits.abstract" in reported
          and "article_types[article]" in reported, reported)


def test_f90_skip_only_suite() -> None:
    print("\n== F90: a skip-only suite is reported SKIP, not a checked pass ==")
    root = scratch("f90_")
    td = root / ".paper_test"
    td.mkdir()
    shutil.copy2(WS / ".paper_test" / "run_all.py", td / "run_all.py")
    shutil.copy2(WS / ".paper_test" / "run_one.sh", td / "run_one.sh")
    write(td / "test_skiponly.py", 'print("[skip] no tool on this box")\n')
    proc = subprocess.run([sys.executable, str(td / "run_all.py"), "--engine", "python",
                           "-j", "1", "--logs", str(root / "logs")],
                          capture_output=True, text=True, timeout=180)
    out = proc.stdout + proc.stderr
    check("F90 the skip-only suite is tagged SKIP",
          "SKIP  test_skiponly.py" in out, out[-500:])
    check("F90 it is not counted as passed",
          "0 passed, 1 skipped" in out and "1 passed" not in out, out[-500:])


def test_f76_verifier_jail() -> None:
    print("\n== F76: an agent-declared verifier cannot read/write outside its sandbox ==")
    root = scratch("f76_")
    sb = root / "sb"
    scripts = sb / "cold_start_review" / "scripts"
    scripts.mkdir(parents=True)
    secret = root / "SECRET_F76.txt"
    secret.write_text("TOPSECRET", encoding="utf-8")
    escape = root / "ESCAPED_F76.txt"
    write(scripts / "v.py",
          "from pathlib import Path\n"
          "out = []\n"
          "try:\n"
          f"    Path({str(escape)!r}).write_text('escaped')\n"
          "    out.append('ESCAPE_WRITTEN')\n"
          "except OSError:\n"
          "    out.append('ESCAPE_BLOCKED')\n"
          "try:\n"
          f"    out.append(Path({str(secret)!r}).read_text().strip())\n"
          "except OSError:\n"
          "    out.append('READ_BLOCKED')\n"
          "print(' '.join(out))\n")
    findings = [{"id": "X-901", "verifier": {
        "script": "cold_start_review/scripts/v.py",
        "computed": "ESCAPE_BLOCKED READ_BLOCKED", "shows": "containment"}}]
    rep = pp.cold_start_reproduction(sb, findings)
    row = (rep.get("results") or [{}])[0]
    check("F76 the verifier cannot write to its host parent directory",
          not escape.exists(), str(row))
    check("F76 the verifier cannot read a host file by absolute path",
          "TOPSECRET" not in (row.get("produced") or ""), str(row))
    jail = pp._verifier_jail_command(sb, "cold_start_review/scripts/v.py") is not None
    if jail:
        check("F76 the contained verifier still reproduces its computation",
              row.get("status") == "reproduced"
              and row.get("produced") == "ESCAPE_BLOCKED READ_BLOCKED", str(row))
    else:
        check("F76 with no jail the verifier is refused, not run with host access",
              row.get("status") == "no-jail" and rep.get("verified") == 0, str(row))
    # A verifier that reads only its own sandbox still works: the jail changes
    # the boundary, not the documented read/compute/print contract.
    write(sb / "base" / "data.txt", "42")
    write(scripts / "inside.py",
          "from pathlib import Path\nprint(Path('base/data.txt').read_text().strip())\n")
    rep2 = pp.cold_start_reproduction(sb, [{"id": "X-902", "verifier": {
        "script": "cold_start_review/scripts/inside.py", "computed": "42"}}])
    row2 = (rep2.get("results") or [{}])[0]
    check("F76 an inside-the-sandbox verifier still reproduces",
          row2.get("status") == ("reproduced" if jail else "no-jail"), str(row2))
    # ... and a host that cannot build the jail must refuse, never fall back to
    # the orchestrator's own process environment.
    old = pp._verifier_jail_command
    pp._verifier_jail_command = lambda _sb, _script: None
    try:
        rep3 = pp.cold_start_reproduction(sb, findings)
    finally:
        pp._verifier_jail_command = old
    row3 = (rep3.get("results") or [{}])[0]
    check("F76 without a jail the declared verifier is a failure, not an execution",
          row3.get("status") == "no-jail" and rep3.get("verified") == 0
          and "X-901" in (rep3.get("broken") or []), str(row3))
    # The pre-flight and postcheck must report that failure, not pass a
    # verifier they never ran.
    write(sb / pp.COLD_START_FINDINGS_REL, json.dumps({
        "checked": [{"area": "documents", "examined": 1, "findings": 1}],
        "findings": [{
            "id": "X-901", "category": 0, "severity": "major",
            "location": "manuscript.md:1", "evidence": "e", "explanation": "x",
            "check": "claim vs producer", "status": "resolvable",
            "verifier": {"script": "cold_start_review/scripts/v.py",
                         "computed": "ESCAPE_BLOCKED READ_BLOCKED", "shows": "s"}}]}))
    write(sb / pp.COLD_START_COVERAGE_REL, "documents: examined 1, filed 1\n")
    write(sb / pp.MARKER_FILE, json.dumps({
        "stage": "cold_start_review", "status": "complete",
        "run_id": "r1_cold_start_review", "round": 1}))
    pp._verifier_jail_command = lambda _sb, _script: None
    try:
        ok, errs, _warns = pp.sandbox_selfcheck(
            sb, "cold_start_review", "r1_cold_start_review", 1)
    finally:
        pp._verifier_jail_command = old
    check("F76 the pre-flight fails a verifier the host cannot jail",
          ok is False and any("no verifier jail" in e for e in errs), str(errs)[:500])


def test_readme_and_cli_docs() -> None:
    print("\n== F77/F78/F79/F95/F185/F188/F189: documentation matches the tree ==")
    readme = (WS / "README.md").read_text(encoding="utf-8")
    tree = len(list((WS / ".paper_test").glob("test_*.py")))
    m = re.search(r"(\d+) suites", readme)
    check("F77 README's suite count matches the tree",
          m is not None and int(m.group(1)) == tree, (m.group(1) if m else None, tree))
    check("F78 the almost-fail aliases are documented",
          "--almost-fail" in readme and "HIDDEN aliases" in readme)
    check("F95 --conflict-agent lists manual",
          "|qwen|dots|manual}" in readme)
    p17 = (WS / "paper_pipeline_parts" / "p17_cli.py").read_text(encoding="utf-8")
    p09 = (WS / "paper_pipeline_parts" / "p09_setup.py").read_text(encoding="utf-8")
    check("F79 the help names --cold-start-review off, not a probe",
          "with the probe off" not in p17
          and "with `--cold-start-review off`" in p17)
    check("F79 the setup comment no longer says 'no probe'",
          "no probe means" not in p09)
    check("F185 the FORMAT_FIX comment/docstring names the per-label file",
          "FORMAT_FIX_<id>.json" in (WS / "paper_pipeline_parts" / "p00_prelude.py")
          .read_text(encoding="utf-8")
          and "FORMAT_FIX_<label>.json" in (WS / "paper_pipeline_parts" / "p04_utils.py")
          .read_text(encoding="utf-8"))
    p03 = (WS / "paper_pipeline_parts" / "p03_prompts.py").read_text(encoding="utf-8")
    check("F188 the master prompt no longer hard-codes 300-500 cover-letter words",
          "less than 300 or more than 500" not in p03)
    check("F189 the master prompt no longer hard-codes 1.5 spacing",
          "should be 1.5-spaced" not in p03 and "1.5-spaced text" not in p03)


def main() -> int:
    try:
        test_f09_docx_reference_entries()
        test_f28_exemption_is_consumed()
        test_f36_reference_heading_variants()
        test_f38_rst_html_surfaces()
        test_f117_heading_with_prose()
        test_f120_identity_typos()
        test_f121_handoff_dates()
        test_f124_split_citation()
        test_f125_thebibliography_correction()
        test_f126_reference_correction_prose()
        test_f84_set_revision_mode_guided_off()
        test_f129_hidden_email()
        test_f18_f97_marker_validation()
        test_f107_f108_selection()
        test_f98_f111_generation_and_promotion()
        test_f101_judge_hard_failure()
        test_f102_tolerated_reason()
        test_f104_almost_fail_reset()
        test_f112_tolerated_selection()
        test_f43_symlinked_revised()
        test_f54_depth_cap()
        test_f67_state_mode()
        test_f106_classifier_snapshot()
        test_f171_bounded_include()
        test_f61_redline_guard_shape()
        test_f58_f73_bounded_children()
        test_f190_pdf_descriptor()
        test_f195_trackdiff_forms()
        test_f132_policy_flags()
        test_f138_ledger_types()
        test_f147_dry_run_without_conda()
        test_f158_guided_off_prompt()
        test_f160_limit_conflict()
        test_f90_skip_only_suite()
        test_f76_verifier_jail()
        test_readme_and_cli_docs()
    finally:
        cleanup()
    print(f"\nFAILED: {len(FAILS)} check(s): {', '.join(FAILS)}" if FAILS
          else "\nall checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())

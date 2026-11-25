#!/usr/bin/env python3
"""Regression checks for the 2026-11-25 02:31 fix-bugs wave, group B1.

One check block per assigned candidate.  Every fixture is a temp dir (or a
throwaway pipeline root under one); no network, no Word/Office, no repo writes.
The one slow block (F013) runs a single round with the repo's deterministic
stubs, because that candidate's defect only exists on the `decide` path.

Run:  python3 .paper_test/test_fix_bugs_20261125_B1.py
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs1125b1_pp", "paper_pipeline.py")

FAILS = []
TMPDIRS = []

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
    "hKmMIQAAAABJRU5ErkJggg==")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def cleanup() -> None:
    for tmp in TMPDIRS:
        # A chmod-000 fixture must not stop the cleanup.
        for p in [*tmp.rglob("*"), tmp]:
            if p.is_symlink():
                # chmod follows the link; never touch a target outside the fixture.
                continue
            try:
                os.chmod(p, 0o755)
            except OSError:
                pass
        shutil.rmtree(tmp, ignore_errors=True)


def write_docx(path: Path, paragraphs, media: bytes = b"") -> None:
    """A minimal but reader-parseable .docx (zipfile only, no python-docx)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(
        '<w:p><w:r><w:t xml:space="preserve">' + escape(p) + "</w:t></w:r></w:p>"
        for p in paragraphs)
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Default Extension="png" ContentType="image/png"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.'
          'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document {W_NS}><w:body>{body}</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("word/document.xml", doc)
        if media:
            z.writestr("word/media/image1.png", media)


def run_cli(argv, timeout=1200):
    return subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *argv],
                          capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------------------
# F010 -- both transcript diagnoses survive when an attempt hits both
# ---------------------------------------------------------------------------
def check_f010() -> None:
    print("\n== F010: a capped transcript that was also held open keeps BOTH notes ==")
    sb = scratch("fixbugs1125b1_f010_")
    (sb / "PROMPT.md").write_text("prompt", encoding="utf-8")
    old_cap = pp.MAX_TOOL_OUTPUT_BYTES
    old_popen = pp.subprocess.Popen
    stop = threading.Event()

    class _Stream:
        """One read's worth of output, then a pipe nobody closes."""

        def __init__(self, chunk, block):
            self.chunk, self.block, self.calls = chunk, block, 0

        def read(self, n):
            self.calls += 1
            if self.calls == 1:
                return self.chunk
            if self.block:
                stop.wait(30)
            return ""

        def close(self):
            pass

    class _FakeProc:
        pid = 999999

        def __init__(self):
            self.stdin = types.SimpleNamespace(write=lambda s: None, close=lambda: None)
            self.stdout = _Stream("x" * 100, True)
            self.stderr = _Stream("", False)

        def wait(self, timeout=None):
            return 0

    pp.MAX_TOOL_OUTPUT_BYTES = 20
    pp.subprocess.Popen = lambda *a, **k: _FakeProc()
    try:
        rec = {"id": "T1", "attempts_done": 0}
        pp._execute_attempt_in(sb, rec, ["x"], 1, archive_marker=False)
    finally:
        pp.subprocess.Popen = old_popen
        pp.MAX_TOOL_OUTPUT_BYTES = old_cap
        stop.set()
    log = (sb / "_agent.log").read_text(encoding="utf-8", errors="replace")
    check("F010 the incomplete-pipe note survives the byte-cap note",
          "TRANSCRIPT INCOMPLETE" in log and "OUTPUT TRUNCATED" in log,
          log[:400])


# ---------------------------------------------------------------------------
# F013 -- a legacy round is re-derived under the floor it was decided with
# ---------------------------------------------------------------------------
def _decide_args(root: Path):
    return types.SimpleNamespace(
        root=str(root), strict_venue=False, champion_select=None,
        unlink_zotero_fields=False, timeout=None, residual_gate=True,
        format_gate=False, require_ready=False, require_complete=False,
        package_winner=False, skip_hash=False, require_clean_captions=False,
        conflict_agent_cmd=None, defect_audit_cmd=None)


def _setup_root(tmp: Path, rounds=1, judges=1, rewrites=1, revises=0) -> Path:
    src = tmp / "source"
    (src / "raw_data").mkdir(parents=True, exist_ok=True)
    (src / "manuscript-b.md").write_text("Title\n\nAbstract\n\nwords here.\n", encoding="utf-8")
    (src / "raw_data" / "data.tsv").write_text("a\tb\n1\t2\n", encoding="utf-8")
    root = tmp / "root"
    r = run_cli(["setup", "--source", str(src), "--root", str(root),
                 "--rounds", str(rounds), "--judges", str(judges),
                 "--rewrites", str(rewrites), "--revises", str(revises)])
    if r.returncode != 0:
        raise RuntimeError((r.stdout + r.stderr)[-1200:])
    return root


def _run_root(root: Path) -> None:
    argv = ["run", "--root", str(root), "--jobs", "4",
            "--agent-cmd", json.dumps([sys.executable,
                                       str(WS / ".paper_test" / "stub_agent.py")]),
            "--judge-agent-cmd", json.dumps([sys.executable,
                                             str(WS / ".paper_test" / "stub_judge.py")]),
            "--retries", "0", "--retry-backoff", "0"]
    r = run_cli(argv)
    out = r.stdout + r.stderr
    if r.returncode != 0 and "STALE sibling module" in out:
        # A sibling fix-bugs agent edited the maintained tree between setup and
        # run; re-freeze the root from the (consistent) current tree, then retry.
        run_cli(["sync-code", "--root", str(root)])
        r = run_cli(argv)
        out = r.stdout + r.stderr
    if r.returncode != 0:
        raise RuntimeError(out[-2000:])


def check_f013() -> None:
    print("\n== F013: a legacy round re-derives under its own (historical) defect floor ==")
    tmp = scratch("fixbugs1125b1_f013_")
    root = _setup_root(tmp)
    _run_root(root)
    # Make the record look like a pre-F18 legacy record (no recorded floor) and
    # change today's mutable config, as `set-tiebreak-defect-floor` does.
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    rrec = state["rounds"]["1"]
    check("F013 the fixture round was decided with a recorded floor",
          rrec.get("tiebreak_defect_floor") == pp.DEFAULT_TIEBREAK_DEFECT_FLOOR,
          str(rrec.get("tiebreak_defect_floor")))
    rrec.pop("tiebreak_defect_floor", None)
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    cfg = json.loads((root / "pipeline_config.json").read_text(encoding="utf-8"))
    cfg["tiebreak_defect_floor"] = 1
    (root / "pipeline_config.json").write_text(json.dumps(cfg), encoding="utf-8")
    ctx = pp.Ctx(root.resolve())
    ctx.load()
    try:
        pp._cmd_decide_locked(ctx, _decide_args(root.resolve()))
    except SystemExit:
        pass
    decision = json.loads((root / "reports" / "decision.json").read_text(encoding="utf-8"))
    sel_floor = ((decision["rounds"][0].get("selection") or {}).get("tiebreak") or {}).get("floor")
    check("F013 a legacy record ranks under the historical default, not today's config",
          sel_floor == pp.DEFAULT_TIEBREAK_DEFECT_FLOOR, str(sel_floor))
    check("F013 decision.json's score_model documents that same historical floor",
          (decision.get("score_model") or {}).get("tiebreak_defect_floor")
          == pp.DEFAULT_TIEBREAK_DEFECT_FLOOR,
          str((decision.get("score_model") or {}).get("tiebreak_defect_floor")))


# ---------------------------------------------------------------------------
# F016 -- decide with no completed round still writes DECISION_REPORT.md
# ---------------------------------------------------------------------------
def check_f016() -> None:
    print("\n== F016: a no-round decide writes the promised DECISION_REPORT.md ==")
    tmp = scratch("fixbugs1125b1_f016_")
    root = _setup_root(tmp)
    ctx = pp.Ctx(root.resolve())
    ctx.load()
    code = None
    try:
        pp._cmd_decide_locked(ctx, _decide_args(root.resolve()))
    except SystemExit as e:
        code = e.code
    report = root / "reports" / "DECISION_REPORT.md"
    check("F016 the no-round branch still exits 2", code == 2, str(code))
    check("F016 the promised reports/DECISION_REPORT.md is written",
          report.is_file(), "reports/DECISION_REPORT.md is missing")
    text = report.read_text(encoding="utf-8") if report.is_file() else ""
    check("F016 the report states the no-completed-round problems",
          "not complete" in text or "no round has completed" in text, text[:300])
    check("F016 the report does not invent a round-0 'champion None'",
          "champion is **None**" not in text and "There is no final answer" in text,
          text[:300])


# ---------------------------------------------------------------------------
# F017 -- PKG-16 records the LaTeX/PDF main text as a coverage gap
# ---------------------------------------------------------------------------
def check_f017() -> None:
    print("\n== F017: PKG-16 records a non-DOCX main text instead of a clean scan ==")
    pkg = scratch("fixbugs1125b1_f017_") / "pkg"
    pkg.mkdir()
    (pkg / "main.tex").write_text(
        "\\section{Software}\nWe used bedtools 2.30 and STAR 2.7.5.\n", encoding="utf-8")
    write_docx(pkg / "NBT_Reporting_Summary.docx", ["Software and code: Seurat 4.0."])
    rows = pp.scan_form_software_coverage(pkg)
    check("F017 a LaTeX main text is not a silently clean PKG-16 list",
          len(rows) == 1 and rows[0].get("rule") == "PKG-16"
          and rows[0].get("gap") is True, str(rows))
    check("F017 the gap names the main text it could not compare",
          "main.tex" in str(rows[0].get("detail") or "") if rows else False,
          str(rows[0].get("detail") if rows else ""))


# ---------------------------------------------------------------------------
# F092 -- an unreadable PKG-1 text file is a coverage gap, never a clean skip
# ---------------------------------------------------------------------------
def check_f092() -> None:
    print("\n== F092: PKG-1 records an unreadable text file as a coverage gap ==")
    pkg = scratch("fixbugs1125b1_f092_") / "pkg"
    pkg.mkdir()
    p = pkg / "notes.md"
    p.write_text("F-001 internal review material\n", encoding="utf-8")
    os.chmod(p, 0)
    try:
        rows = pp.internal_artifact_rows(pkg)
    finally:
        os.chmod(p, 0o644)
    check("F092 an unreadable file produces a PKG-1 coverage gap",
          len(rows) == 1 and rows[0].get("rule") == "PKG-1"
          and rows[0].get("gap") is True and "notes.md" in str(rows[0].get("file")),
          str(rows))


# ---------------------------------------------------------------------------
# F093 -- PKG-15 reads the units table's own n_units column
# ---------------------------------------------------------------------------
def check_f093() -> None:
    print("\n== F093: PKG-15 compares against the units table's own n_units column ==")
    pkg = scratch("fixbugs1125b1_f093_") / "pkg"
    pkg.mkdir()
    (pkg / "fig_mcb_pooled.tsv").write_text(
        "method\tn_units\tmean\nAneuFinder\t9\t69.37\n", encoding="utf-8")
    (pkg / "fig_units.tsv").write_text(
        "method\tn_units\tmean\nAneuFinder\t21\t69.37\n", encoding="utf-8")
    rows = pp.scan_pooled_table_mismatches(pkg)
    check("F093 a pooled table on 9 of 21 units is reported",
          len(rows) == 1 and rows[0].get("rule") == "PKG-15", str(rows))
    check("F093 the row quotes the units column (21), not the row count (1)",
          "21 pooled units" in str(rows[0].get("detail")) if rows else False,
          str(rows[0].get("detail") if rows else "")[:300])


# ---------------------------------------------------------------------------
# F094 -- PKG-15 accepts a capitalised header
# ---------------------------------------------------------------------------
def check_f094() -> None:
    print("\n== F094: PKG-15 reads a capitalised (`Method`/`Mean`) header ==")
    pkg = scratch("fixbugs1125b1_f094_") / "pkg"
    pkg.mkdir()
    (pkg / "fig_mcb_pooled.tsv").write_text(
        "Method\tN_units\tMean\nAneuFinder\t9\t69.37\n", encoding="utf-8")
    (pkg / "fig_units.tsv").write_text(
        "Method\tN_units\tMean\nAneuFinder\t21\t69.37\n", encoding="utf-8")
    rows = pp.scan_pooled_table_mismatches(pkg)
    check("F094 a capitalised pooled table is compared, not skipped",
          len(rows) == 1 and rows[0].get("rule") == "PKG-15", str(rows))


# ---------------------------------------------------------------------------
# F095 -- PKG-4 records an unreadable DOCX as a coverage gap
# ---------------------------------------------------------------------------
def check_f095() -> None:
    print("\n== F095: PKG-4 records an unreadable DOCX as a coverage gap ==")
    pkg = scratch("fixbugs1125b1_f095_") / "pkg"
    (pkg / "figures").mkdir(parents=True)
    (pkg / "figures" / "Figure1.png").write_bytes(PNG_1X1)
    (pkg / "main.docx").write_bytes(b"not a docx")
    rows = pp.package_display_item_rows(pkg)
    gaps = [r for r in rows if r.get("rule") == "PKG-4" and r.get("gap")]
    check("F095 the unparsable main DOCX is reported as a PKG-4 gap",
          len(gaps) == 1 and "main.docx" in str(gaps[0].get("detail")), str(rows))


# ---------------------------------------------------------------------------
# F096 -- PKG-4 does not claim a document does not embed its artwork
# ---------------------------------------------------------------------------
def check_f096() -> None:
    print("\n== F096: PKG-4 does not claim the document does not embed the figure ==")
    pkg = scratch("fixbugs1125b1_f096_") / "pkg"
    (pkg / "figures").mkdir(parents=True)
    (pkg / "figures" / "Figure1.png").write_bytes(PNG_1X1)
    write_docx(pkg / "main.docx",
               ["As shown in Figure S3, the effect holds."], media=PNG_1X1)
    media = pp.embedded_media_digests(pkg, ["main.docx"])
    check("F096 the fixture really embeds one image part", len(media) == 1, str(media))
    rows = [r for r in pp.package_display_item_rows(pkg) if r.get("reference")]
    detail = str(rows[0].get("detail") if rows else "")
    check("F096 the missing-citation row no longer asserts non-embedding",
          bool(rows) and "does not embed it" not in detail, detail[:300])
    check("F096 the row points at the embedded media it cannot map",
          "embed" in detail and "image" in detail, detail[:300])


# ---------------------------------------------------------------------------
# F097 -- PKG-14 reads DOCX (and PDF) editorial decisions
# ---------------------------------------------------------------------------
def check_f097() -> None:
    print("\n== F097: PKG-14 reads a DOCX decision letter in the feedback area ==")
    base = "enzyme phosphorylation kinetics in tumour cells"
    pkg = scratch("fixbugs1125b1_f097_") / "pkg"
    (pkg / "raw_data").mkdir(parents=True)
    write_docx(pkg / "cover_letter.docx",
               [f"Re: {base}. We confirm the manuscript is not under consideration "
                "elsewhere."])
    (pkg / "raw_data" / "decision.md").write_text(
        f"NBT-A-26-12345 {base}. Decision: rejected on 2026-01-05.", encoding="utf-8")
    md_rows = [r for r in pp.scan_prior_submission_disclosure(pkg)
               if r.get("rule") == "PKG-14"]
    check("F097 the markdown-decision control still yields the PKG-14 row",
          len(md_rows) == 1, str(md_rows))
    (pkg / "raw_data" / "decision.md").unlink()
    write_docx(pkg / "raw_data" / "decision.docx",
               [f"NBT-A-26-12345 {base}. Decision: rejected on 2026-01-05."])
    docx_rows = [r for r in pp.scan_prior_submission_disclosure(pkg)
                 if r.get("rule") == "PKG-14" and not r.get("gap")]
    check("F097 a DOCX decision letter is read, not invisible",
          len(docx_rows) == 1
          and "decision.docx" in str(docx_rows[0].get("detail")), str(docx_rows))
    # An unreadable decision attachment is a named gap, never a clean scan.
    (pkg / "raw_data" / "decision.docx").write_bytes(b"not a docx")
    gap_rows = [r for r in pp.scan_prior_submission_disclosure(pkg)
                if r.get("rule") == "PKG-14" and r.get("gap")]
    check("F097 an unreadable decision attachment is a named PKG-14 gap",
          len(gap_rows) == 1, str(pp.scan_prior_submission_disclosure(pkg)))


# ---------------------------------------------------------------------------
# F098 -- a skipped symlink is a publication problem, not ok:true
# ---------------------------------------------------------------------------
def check_f098() -> None:
    print("\n== F098: an archive that skips a symlink is a publication problem ==")
    tmp = scratch("fixbugs1125b1_f098_")
    pkg = tmp / "pkg"
    pkg.mkdir()
    (pkg / "a.md").write_text("x", encoding="utf-8")
    os.symlink("/etc/hostname", pkg / "link.md")
    out = pp.write_final_clean_zip(pkg, tmp / "pkg.zip")
    check("F098 the fixture archive really skipped the link",
          out.get("skipped_links") == ["pkg/link.md"], str(out.get("skipped_links")))
    problems = pp.final_clean_publication_problems({"zip": out})
    check("F098 the skipped entries reach the publication problems",
          len(problems) == 1 and "link" in problems[0].lower(), str(problems))
    clean = tmp / "clean"
    clean.mkdir()
    (clean / "b.md").write_text("y", encoding="utf-8")
    good = pp.write_final_clean_zip(clean, tmp / "clean.zip")
    check("F098 a link-free package still publishes with no problem",
          pp.final_clean_publication_problems({"zip": good}) == [], str(good))


# ---------------------------------------------------------------------------
# F099 -- a corrupt champion revision ledger is a REV-0 readiness blocker
# ---------------------------------------------------------------------------
def check_f099() -> None:
    print("\n== F099: a corrupt champion revision ledger yields a REV-0 blocker ==")
    root = scratch("fixbugs1125b1_f099_") / "root"
    (root / "reports").mkdir(parents=True)
    ctx = pp.Ctx(root)
    ctx.cfg = {}
    ctx.state = {"version": pp.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": [],
                 "log": [], "original_digest": "d", "config": {}}
    rid = "r1_w1"
    ctx.state["runs"][rid] = {"id": rid, "kind": "revise", "round": 1,
                              "status": "done", "sandbox": f"runs/{rid}"}
    sb = root / "runs" / rid / "revised"
    sb.mkdir(parents=True)
    (sb / "revision_report.json").write_text("{not json", encoding="utf-8")
    final = {"stored": {"champion": "w1", "round": 1, "pin_id": rid},
             "pin": {"id": rid, "produced_by_run": rid}}
    oi = pp.collect_open_review_items(ctx, final)
    check("F099 the corrupt ledger is recorded as an error",
          bool(oi.get("error")) and "revision_report.json" in str(oi.get("error")),
          str(oi.get("error")))
    ready = pp.package_readiness({"open_items": oi}, residuals={})
    check("F099 readiness carries a REV-0 blocker and is NOT submission-ready",
          ready["submission_ready"] is False
          and any(f.get("rule") == "REV-0" for f in ready["findings"]),
          json.dumps([f.get("rule") for f in ready["findings"]]))


# ---------------------------------------------------------------------------
# F100 -- an empty artifact problem list is a gate item, not an IndexError
# ---------------------------------------------------------------------------
def check_f100() -> None:
    print("\n== F100: an empty artifact_quality list does not crash decide ==")
    root = scratch("fixbugs1125b1_f100_") / "root"
    root.mkdir()
    ctx = pp.Ctx(root)
    ctx.cfg = {}
    ctx.state = {"version": pp.STATE_VERSION,
                 "runs": {"G1": {"id": "G1", "kind": "guided_review", "status": "done",
                                 "artifact_quality": {"findings.json": []}}},
                 "rounds": {}, "pinned": [], "log": [], "original_digest": "d"}
    try:
        res = pp.collect_residuals(ctx)
        crashed = ""
    except Exception as e:                                        # noqa: BLE001
        res, crashed = {}, f"{type(e).__name__}: {e}"
    check("F100 an empty problem list does not raise", not crashed, crashed)
    check("F100 it becomes a recorded gating item",
          any("findings.json" in it for it in (res.get("gating") or [])),
          str(res.get("gating")))


# ---------------------------------------------------------------------------
# F110 -- structural drops (duplicate/self/abstained) do not make a panel short
# ---------------------------------------------------------------------------
class _FakeCtx:
    def __init__(self, runs, field=("i1", "i2"), reports=None):
        self._runs = list(runs)
        self._field = list(field)
        self.state = {}
        self.root = Path(reports or scratch("fixbugs1125b1_f110_"))
        self.reports_dir = self.root
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def runs(self, kind=None, round_no=None):
        return [r for r in self._runs
                if (kind is None or r.get("kind") == kind)
                and (round_no is None or r.get("round") == round_no)]

    def round_rec(self, r):
        return {"field": list(self._field)}

    def round_get(self, r):
        return {}


def _judge_sheet(rid, target, idx, comps):
    return {"id": rid, "kind": "judge", "round": 1, "status": "done",
            "target_id": target, "judge_index": idx,
            "label_map": {"v1": "i2"},
            "scores": {"comparisons": comps}}


def _comp(label="v1", score=1, checks=None):
    return {"opponent_label": label, "score": score, "basis": "none",
            "resolved": [], "introduced": [],
            "checks": checks if checks is not None else {}, "reason": ""}


def check_f110() -> None:
    print("\n== F110: a benign duplicate opponent does not make the panel partial ==")
    orig_judges, orig_sel = pp.round_judges, pp.judge_selection
    pp.round_judges = lambda _ctx, _r: 1
    pp.judge_selection = lambda _ctx, _r: set()
    try:
        dup = _FakeCtx([_judge_sheet("j1", "i1", 1, [_comp(), _comp()])])
        coverage = {}
        ops = pp.round_judge_opinions(dup, 1, field=["i1", "i2"], coverage=coverage)
        check("F110 the repeated opponent still yields one opinion",
              len(ops) == 1, str(ops))
        check("F110 coverage counts the structural drop but stays complete",
              coverage.get("complete") is True
              and (coverage.get("dropped") or {}).get("duplicate_opponent") == 1,
              str(coverage))
        try:
            data = pp.write_round_judge_conflicts(dup, 1, agg={"field": ["i1", "i2"]},
                                                  agent_cmd=None, use_agent=False)
            raised = ""
        except RuntimeError as e:
            data, raised = {}, str(e)
        check("F110 the conflict report is written instead of refusing",
              not raised and (data.get("coverage") or {}).get("complete") is True,
              raised or str(data)[:200])

        self_cmp = _judge_sheet("j1", "i1", 1, [_comp()])
        self_cmp["label_map"] = {"v1": "i1"}
        cov_self = {}
        pp.round_judge_opinions(_FakeCtx([self_cmp]), 1, field=["i1", "i2"],
                                coverage=cov_self)
        check("F110 a self-comparison row does not make the extraction partial",
              cov_self.get("complete") is True
              and (cov_self.get("dropped") or {}).get("self_comparison") == 1,
              str(cov_self))

        abst = _FakeCtx([_judge_sheet("j1", "i1", 1,
                                     [_comp(checks={"M1": "unable"})])])
        cov_abs = {}
        pp.round_judge_opinions(abst, 1, field=["i1", "i2"], coverage=cov_abs)
        # F110 and the earlier F002 fix disagree on THIS one drop: F002 requires
        # an abstention to leave the audit incomplete (it is a directed judgment
        # the panel did not make), so the pre-existing tested behaviour wins and
        # only duplicate/self-comparison rows are exempted. Pinned here so a
        # later change cannot quietly flip it either way.
        check("F110 an abstention still leaves the audit incomplete (F002 kept)",
              cov_abs.get("complete") is False
              and (cov_abs.get("dropped") or {}).get("abstained") == 1,
              str(cov_abs))

        # The F028 guard must survive: an unresolvable label is a real gap.
        bad = _FakeCtx([_judge_sheet("j1", "i1", 1,
                                     [_comp(label="vX")])])
        cov_bad = {}
        pp.round_judge_opinions(bad, 1, field=["i1", "i2"], coverage=cov_bad)
        check("F110 an unresolved opponent label is still an incomplete extraction",
              cov_bad.get("complete") is False, str(cov_bad))
    finally:
        pp.round_judges, pp.judge_selection = orig_judges, orig_sel


# ---------------------------------------------------------------------------
# F120 -- a reversed interval is not a valid confidence interval
# ---------------------------------------------------------------------------
def check_f120() -> None:
    print("\n== F120: PKG-12 rejects a reversed confidence interval ==")
    check("F120 a reversed interval no longer parses as a pair",
          pp._parse_ci("[0.5, -0.5]") is None, repr(pp._parse_ci("[0.5, -0.5]")))
    check("F120 an ordered interval still parses",
          pp._parse_ci("[-0.51, -0.02]") == (-0.51, -0.02),
          repr(pp._parse_ci("[-0.51, -0.02]")))
    pkg = scratch("fixbugs1125b1_f120_") / "pkg"
    pkg.mkdir()
    (pkg / "mcb_table.tex").write_text(
        "\\begin{document}\n"
        "\\caption{Small p and an interval entirely below 0 mark a significant "
        "difference.}\n"
        "\\begin{tabular}{lllll}\n"
        "G1 & 10 & 0.03 & 1 & [0.5, -0.5] \\\\\n"
        "\\end{tabular}\n\\end{document}\n", encoding="utf-8")
    rows = pp.scan_mcb_rule_conflicts(pkg)
    check("F120 the malformed interval is reported as an unexamined input",
          any(r.get("gap") and "reversed" in str(r.get("detail")).lower() for r in rows),
          str(rows))


def main() -> int:
    try:
        check_f010()
        check_f016()
        check_f017()
        check_f092()
        check_f093()
        check_f094()
        check_f095()
        check_f096()
        check_f097()
        check_f098()
        check_f099()
        check_f100()
        check_f110()
        check_f120()
        check_f013()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {FAILS}")
        return 1
    print("OK: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

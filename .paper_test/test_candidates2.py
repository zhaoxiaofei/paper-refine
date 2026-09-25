#!/usr/bin/env python3
"""Repro/regression tests for the round-2 candidate set (the audit archives).

Run:  python3 .paper_test/test_candidates2.py

Every check FAILS on the tree as ingested and PASSES once the matching defect is
fixed, so this file is both the repro script and the regression guard for the
round-2 patches. `PAPER_WS` / `PAPER_SKILLS` retarget it at a baseline copy:

    PAPER_WS=/tmp/paper_baseline2 PAPER_SKILLS=/tmp/paper_baseline2 \
        python3 .paper_test/test_candidates2.py     # 11 checks fail there
"""
from __future__ import annotations

import importlib.util
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

DEFAULT_WS = Path(__file__).resolve().parent.parent
WS = Path(os.environ.get("PAPER_WS") or DEFAULT_WS)
# Test the pack this repo vendors by default. The globally installed pack is
# often a different revision, so preferring it silently validated a foreign
# pack; PAPER_SKILLS still wins when a caller wants to point at one explicitly.
SKILLS = Path(os.environ.get("PAPER_SKILLS") or WS / "paper-skills")
NP_PATH = WS / "paper_pipeline.py"
SCRIPTS = SKILLS / "paper-review" / "scripts"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


np = load("paperp2", NP_PATH)

FAILS: list[str] = []
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def check(name: str, cond, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def write(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")


_TMPDIRS: list = []


@atexit.register
def _cleanup_tmpdirs() -> None:
    for d in _TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def tmpdir(tag: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=f"c2_{tag}_"))
    _TMPDIRS.append(p)
    return p


def docx(path: Path, children, texts=("Intro.", "Methods.", "Closing.")) -> None:
    """Minimal OOXML package whose body holds the given raw XML children."""
    body = "".join(children)
    xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("word/document.xml", xml)


def para(text: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


TABLE = ('<w:tbl><w:tr><w:tc><w:p><w:r><w:t>T1</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
SECTPR = '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'


# =====================================================================
# R1 -- builtin_tracked_changes must keep tables where they were
# =====================================================================

def body_children(path: Path):
    """Top-level w:body child tags, parsed as XML (regex counting is unreliable)."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    body = np.ET.fromstring(xml).find("{%s}body" % W_NS)
    return [child.tag.split("}")[1] for child in list(body)]


def test_table_position_preserved():
    tmp = tmpdir("r1")
    base, revised, out = tmp / "base.docx", tmp / "revised.docx", tmp / "out.docx"
    docx(base, [para("Intro."), TABLE, para("Methods."), TABLE, para("Closing."), SECTPR])
    docx(revised, [para("Intro."), TABLE, para("Methods EDITED."), TABLE, para("Closing."),
                   SECTPR])
    info = np.builtin_tracked_changes(base, revised, out)
    check("R1 untouched inline tables keep their positions in the redline",
          body_children(out) == body_children(base),
          f"base={body_children(base)} out={body_children(out)}")
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    check("R1 (regression guard) the diff is still a readable tracked-changes body",
          info["revision_ids"] > 0 and b"<w:ins " in xml.encode()
          and info.get("non_paragraph_changed") is False, f"info={info}")


def test_changed_table_keeps_its_slot():
    tmp = tmpdir("r1b")
    base, revised, out = tmp / "base.docx", tmp / "revised.docx", tmp / "out.docx"
    docx(base, [para("Intro."), TABLE, para("Methods."), SECTPR])
    docx(revised, [para("Intro."), '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>T2</w:t></w:r>'
                                  '</w:p></w:tc></w:tr></w:tbl>', para("Methods."), SECTPR])
    info = np.builtin_tracked_changes(base, revised, out)
    check("R1 (regression guard) an edited table still occupies its base slot and warns",
          body_children(out) == body_children(base) and bool(info.get("warning")),
          f"base={body_children(base)} out={body_children(out)} warn={info.get('warning')!r}")


# =====================================================================
# R2 -- \caption*{} must be seen by the caption scanner
# =====================================================================

def test_starred_caption_scanned():
    tex = (r"\caption*{Figure 1 | Starred caption with many words here.}"
           r"\caption[short]{Figure 2 | Long normal caption text.}"
           r"\captionof{figure}{Figure 3 | Captionof caption.}")
    caps = np._tex_captions(tex)
    check("R2 \\caption*{...} is recognised", len(caps) == 3, f"found={caps}")


# =====================================================================
# R3 -- prior-round finding ids match on id boundaries, not substrings
# =====================================================================

def review_contract_errors(tmp: Path, prior_ids, current_ids, blob_extra=""):
    sb = tmp / "sb"
    (sb / "prior_round").mkdir(parents=True, exist_ok=True)
    (sb / "review" / "artifacts").mkdir(parents=True, exist_ok=True)
    (sb / "prior_round" / "findings.json").write_text(
        json.dumps({"findings": [{"id": i} for i in prior_ids]}), encoding="utf-8")
    cur = {"submission_dir": "./base",
           "findings": [{"id": i} for i in current_ids],
           "coverage": [{"check": c, "disposition": "clean -- basis: a.md"}
                        for c in list(np.REQUIRED_REVIEW_CHECKS) + ["M19", "M18"]]}
    (sb / "review" / "findings.json").write_text(json.dumps(cur), encoding="utf-8")
    (sb / "review" / "artifacts" / "M1.md").write_text("x", encoding="utf-8")
    (sb / "review" / "findings.md").write_text("# findings\n" + blob_extra, encoding="utf-8")
    ctx = type("C", (), {})()
    ctx.cfg = {}
    errs, _warns = [], []
    np.check_review_contract(ctx, sb, cur, errs, _warns)
    return errs


def test_prior_id_boundary():
    tmp = tmpdir("r3")
    errs = review_contract_errors(tmp, ["F-012", "F-055"], ["F-0123", "F-055"])
    check("R3 a new F-0123 does not account for a vanished prior F-012",
          any("F-012" in e for e in errs), f"errs={[e[:80] for e in errs]}")
    tmp2 = tmpdir("r3b")
    errs2 = review_contract_errors(tmp2, ["F-012"], [], blob_extra="\ncarried over from F-012\n")
    check("R3 (regression guard) a genuine mention still satisfies the gate",
          not any("F-012" in e for e in errs2), f"errs={[e[:80] for e in errs2]}")


# =====================================================================
# R4 -- an explicit --judge-agent-cmd beats --judge-agent manual
# =====================================================================

def completed_round_root(tmp: Path) -> Path:
    """A minimal root whose single round is done (so `run` exits immediately)."""
    root = tmp / "root"
    write(root / "pipeline_config.json",
          json.dumps({"rounds": 1, "judges": 1, "source": str(tmp / "src")}))
    write(root / "non-revised" / "manuscript.md", "# v0\n")
    write(root / "round1_winner" / "manuscript.md", "# v0\n")
    state = {"version": np.STATE_VERSION, "runs": {}, "log": [], "pinned": [],
             "source": str(tmp / "src"),
             "source_manifest": np.hash_manifest(root / "non-revised"),
             "rounds": {"1": {"round": 1, "status": "done", "winner_dir": "round1_winner",
                              "winner_id": "a2", "champion": "a2"}}}
    write(root / "state.json", json.dumps(np._json_safe(state)))
    (root / "runs").mkdir(exist_ok=True)
    (root / "reports").mkdir(exist_ok=True)
    return root


def test_judge_agent_cmd_precedence():
    tmp = tmpdir("r4")
    root = completed_round_root(tmp)
    cmd_json = json.dumps([sys.executable, "-c", "pass"])
    proc = subprocess.run([sys.executable, str(NP_PATH), "run", "--root", str(root),
                           "--agent", "manual", "--judge-agent", "manual",
                           "--judge-agent-cmd", cmd_json],
                          capture_output=True, text=True, timeout=180, cwd="/tmp")
    lines = [ln for ln in (proc.stdout or "").splitlines() if "judge sessions" in ln]
    check("R4 --judge-agent-cmd is honoured next to --judge-agent manual",
          bool(lines) and "manual" not in lines[0] and "-c" in lines[0],
          f"rc={proc.returncode} lines={lines}")


# =====================================================================
# R5 -- a field that dedupes to one member must not crash the round
# =====================================================================

def setup_root(tmp: Path, rounds: int = 2, text: str = "# Title\n\nSome text.\n") -> Path:
    src = tmp / "src"
    write(src / "manuscript.md", text)
    proc = subprocess.run([sys.executable, str(NP_PATH), "setup", "--source", str(src),
                           "--root", str(tmp / "root"), "--rounds", str(rounds)],
                          capture_output=True, text=True, cwd="/tmp")
    assert proc.returncode == 0, proc.stderr
    return tmp / "root"


def test_field_of_one_round_completes():
    tmp = tmpdir("r5")
    root = setup_root(tmp)
    ctx = np.Ctx(root)
    ctx.load()
    r = 1
    np.materialize_a1(ctx, r)
    ctx.cfg["rewrites"], ctx.cfg["revises"] = [1], [1]   # pool: a1, w1, a2
    for vid, kind in (("a2", "revise"), ("w1", "rewrite"), ("i1", "integrate"),
                      ("i2", "integrate"), ("i3", "integrate")):
        rid = np.rid_for_fresh(r, vid)
        sb = ctx.runs_dir / rid
        out = sb / np.output_dir_for_vid(vid)
        write(out / "manuscript.md", "# Title\n\nSome text.\n")
        write(out / "CHANGELOG.md", "no changes\n")
        rec = ctx.register(rid, kind, r, f"runs/{rid}", produces=vid)
        rec["status"] = "done"
        rec["corpus_digest"] = np.recompute_corpus_digest(ctx, r, vid)
        rec["content_fingerprint"] = np.corpus_content_fingerprint(ctx, r, vid)
    # the round's review pass is part of the plan too: it is done here, so the
    # scheduler has nothing left to execute and drives straight to the field
    review = ctx.register(np.rid_review(r), "review", r, f"runs/{np.rid_review(r)}",
                          source_id="a1")
    write(ctx.sandbox_of(review) / "review" / "findings.json", "{}")
    review["status"] = "done"
    ctx.save_state()

    def fake_run_phase(ctx, ids, **kw):
        for rid in ids:
            rec = ctx.run(rid)
            if rec is not None and rec.get("status") != "done":
                rec["status"] = "done"
        ctx.save_state()
        return True, False

    np.run_phase = fake_run_phase

    def fake_run_round_runs(ctx_, r_, **kw):
        """The round's DAG scheduler, faked: mark every planned run done."""
        for e in np.round_run_plan(ctx_, r_):
            rec = ctx_.run(e["id"])
            if rec is not None and rec.get("status") != "done":
                rec["status"] = "done"
        ctx_.save_state()
        return True, False

    np.run_round_runs = fake_run_round_runs
    np.run_redlines = lambda *a, **k: {"versions": []}
    outcome, crashed = "", False
    try:
        ok, _paused = np.drive_round(ctx, r, cmd=["true"], timeout=0, jobs=1, retries=0,
                                     manual=False, nowait=False, poll=1, retry_backoff=0,
                                     retry_backoff_max=0, redline=False)
        outcome = f"ok={ok} status={ctx.round_get(r).get('status')} " \
                  f"champion={ctx.round_get(r).get('champion')}"
    except Exception as exc:                                     # noqa: BLE001
        crashed, outcome = True, f"{type(exc).__name__}: {exc}"
    check("R5 a one-member field completes instead of crashing the round",
          not crashed and "champion=a1" in outcome, outcome)


# =====================================================================
# R6 -- in-round retry must not leave downstream sandboxes on stale inputs
# =====================================================================

def test_stale_downstream_inputs_are_reset():
    tmp = tmpdir("r6")
    root = setup_root(tmp)
    ctx = np.Ctx(root)
    ctx.load()
    # This case is about STALE DOWNSTREAM INPUTS, not about the auditor: turn the
    # auditor off so the revise materializes straight after the review (the
    # auditor's own dependency is covered by test_stage_subset).
    ctx.cfg["audit"] = "off"
    ctx.cfg["rewrites"], ctx.cfg["revises"] = [1], [1]   # pool: a1, w1, a2
    r = 1
    np.materialize_a1(ctx, r)
    # the rewrite arm of the round must be materialized and done too: the judge
    # field now contains w1 as a candidate like every other fresh arm.
    np.materialize_rewrite(ctx, r, 1)
    w1 = ctx.run(np.rid_for_fresh(r, "w1"))
    write(ctx.sandbox_of(w1) / "rewritten" / "manuscript.md", "# rewritten\n")
    w1["status"] = "done"
    w1["corpus_digest"] = np.recompute_corpus_digest(ctx, r, "w1")
    w1["content_fingerprint"] = np.corpus_content_fingerprint(ctx, r, "w1")
    np.materialize_review(ctx, r)
    rec_review = ctx.run(np.rid_review(r))
    write(ctx.sandbox_of(rec_review) / "review" / "findings.json", "{}")
    rec_review["status"] = "done"

    np.materialize_revise(ctx, r, "a2")
    rec_a2 = ctx.run(np.rid_for_fresh(r, "a2"))
    write(ctx.sandbox_of(rec_a2) / "revised" / "manuscript.md", "# v2\n")
    rec_a2["status"] = "done"
    rec_a2["corpus_digest"] = np.recompute_corpus_digest(ctx, r, "a2")

    # i2 = w1 <- (a1, a2): a2 is one of its donors
    np.materialize_integrate(ctx, r, 2)
    i2 = ctx.run(np.rid_for_fresh(r, "i2"))
    i2["status"] = "done"
    stale_other = np.hash_manifest(ctx.sandbox_of(i2) / "others")

    # the operator retries the revise run while the round is still incomplete
    np.reset_run_record(rec_a2)
    np.rebuild_sandbox(ctx, rec_a2)
    rec_a2["status"] = "pending"
    write(ctx.sandbox_of(rec_a2) / "revised" / "manuscript.md", "# v3 -- really different\n")
    rec_a2["status"] = "done"
    rec_a2["corpus_digest"] = np.recompute_corpus_digest(ctx, r, "a2")
    ctx.save_state()

    if not hasattr(np, "revalidate_round_inputs"):
        check("R6 an in-round retry resets downstream sandboxes on stale inputs", False,
              "revalidate_round_inputs() missing (defect: stale copies are reused)")
        return
    reset = np.revalidate_round_inputs(ctx, r)
    np.materialize_integrate(ctx, r, 2)
    other_now = np.hash_manifest(ctx.sandbox_of(ctx.run(np.rid_for_fresh(r, "i2"))) / "others")
    fresh = np.corpus_manifest(ctx, r, "a2").get("files") or {}
    donor_a2 = {k.split("/", 1)[1]: v for k, v in (other_now.get("files") or {}).items()
                if k.startswith("a2/")}
    check("R6 an in-round retry resets downstream sandboxes on stale inputs",
          bool(reset) and other_now.get("files") != stale_other.get("files")
          and donor_a2 == fresh,
          f"reset={reset} stale_before={list((stale_other.get('files') or {}).values())[-1][:8]} "
          f"now={list(donor_a2.values())[-1][:8]} fresh={list(fresh.values())[-1][:8]}")


def test_healthy_round_is_not_reset():
    tmp = tmpdir("r6b")
    root = setup_root(tmp)
    ctx = np.Ctx(root)
    ctx.load()
    # same as R6: this case tests the revalidation of a HEALTHY round, not the
    # auditor's dependency, so the auditor is off here.
    ctx.cfg["audit"] = "off"
    ctx.cfg["rewrites"], ctx.cfg["revises"] = [1], [1]   # pool: a1, w1, a2
    r = 1
    np.materialize_a1(ctx, r)
    # the round's rewrite arm is part of the fresh field (it feeds the
    # integration arms and the judge panel like every other candidate).
    np.materialize_rewrite(ctx, r, 1)
    w1 = ctx.run(np.rid_for_fresh(r, "w1"))
    write(ctx.sandbox_of(w1) / "rewritten" / "manuscript.md", "# rewritten\n")
    w1["status"] = "done"
    w1["corpus_digest"] = np.recompute_corpus_digest(ctx, r, "w1")
    w1["content_fingerprint"] = np.corpus_content_fingerprint(ctx, r, "w1")
    np.materialize_review(ctx, r)
    review = ctx.run(np.rid_review(r))
    write(ctx.sandbox_of(review) / "review" / "findings.json", "{}")
    review["status"] = "done"
    np.materialize_revise(ctx, r, "a2")
    a2 = ctx.run(np.rid_for_fresh(r, "a2"))
    write(ctx.sandbox_of(a2) / "revised" / "manuscript.md", "# v2\n")
    a2["status"] = "done"
    a2["corpus_digest"] = np.recompute_corpus_digest(ctx, r, "a2")
    np.materialize_integrate(ctx, r, 1)
    np.materialize_integrate(ctx, r, 2)
    np.materialize_integrate(ctx, r, 3)
    ctx.save_state()
    if not hasattr(np, "revalidate_round_inputs"):
        check("R6 (regression guard) a healthy round is left alone", False, "missing function")
        return
    reset = np.revalidate_round_inputs(ctx, r)
    check("R6 (regression guard) a healthy round is left alone", not reset, f"reset={reset}")


def test_judge_inputs_are_revalidated():
    """A judge sandbox built from a since-retried version must be reset too."""
    tmp = tmpdir("r6c")
    root = setup_root(tmp)
    ctx = np.Ctx(root)
    ctx.load()
    ctx.cfg["audit"] = "off"      # the auditor's dependency is not this case's subject
    ctx.cfg["rewrites"], ctx.cfg["revises"] = [1], [1]   # pool: a1, w1, a2
    r = 1
    np.materialize_a1(ctx, r)
    # the round's rewrite arm feeds the integration arms and the judge panel
    np.materialize_rewrite(ctx, r, 1)
    w1 = ctx.run(np.rid_for_fresh(r, "w1"))
    write(ctx.sandbox_of(w1) / "rewritten" / "manuscript.md", "# rewritten\n")
    w1["status"] = "done"
    w1["corpus_digest"] = np.recompute_corpus_digest(ctx, r, "w1")
    w1["content_fingerprint"] = np.corpus_content_fingerprint(ctx, r, "w1")
    np.materialize_review(ctx, r)
    review = ctx.run(np.rid_review(r))
    write(ctx.sandbox_of(review) / "review" / "findings.json", "{}")
    write(ctx.sandbox_of(review) / "review" / "artifacts" / "M1.md", "x")
    review["status"] = "done"
    np.materialize_revise(ctx, r, "a2")
    a2 = ctx.run(np.rid_for_fresh(r, "a2"))
    write(ctx.sandbox_of(a2) / "revised" / "manuscript.md", "# v2\n")
    a2["status"] = "done"
    a2["corpus_digest"] = np.recompute_corpus_digest(ctx, r, "a2")
    a2["content_fingerprint"] = np.corpus_content_fingerprint(ctx, r, "a2")
    for k, text in ((1, "# v3\n"), (2, "# v4\n"), (3, "# v5\n")):
        np.materialize_integrate(ctx, r, k)
        rec = ctx.run(np.rid_for_fresh(r, np.integrate_vid(k)))
        write(ctx.sandbox_of(rec) / "integrated" / "manuscript.md", text)
        rec["status"] = "done"
        vid = np.freshness_vid(rec)
        rec["corpus_digest"] = np.recompute_corpus_digest(ctx, r, vid)
        rec["content_fingerprint"] = np.corpus_content_fingerprint(ctx, r, vid)
    field, _dropped = np.build_field(ctx, r)
    judge_ids = np.materialize_judges(ctx, r, field)
    healthy = np.revalidate_round_inputs(ctx, r)
    check("R6 (regression guard) materialized judge sandboxes are not reset",
          not healthy and judge_ids, f"reset={healthy} judges={len(judge_ids)}")

    # the operator retries the revise run while the round is still incomplete
    np.reset_run_record(a2)
    np.rebuild_sandbox(ctx, a2)
    write(ctx.sandbox_of(a2) / "revised" / "manuscript.md", "# v5 -- really different\n")
    a2["status"] = "done"
    a2["corpus_digest"] = np.recompute_corpus_digest(ctx, r, "a2")
    a2["content_fingerprint"] = np.corpus_content_fingerprint(ctx, r, "a2")
    ctx.save_state()
    reset = np.revalidate_round_inputs(ctx, r)
    check("R6 judge sandboxes built from a retried version are reset",
          set(judge_ids) <= set(reset)
          and all(ctx.run(rid)["status"] == "stale" for rid in judge_ids),
          f"reset={reset[:4]}... statuses={[ctx.run(x)['status'] for x in judge_ids[:3]]}")


# =====================================================================
# R7-R11 -- the skill-pack scripts
# =====================================================================

def test_sci_exponent_variants():
    eo = load("eo2", SCRIPTS / "extract_occurrences.py")
    pat = eo.variant_pattern("0.031", "value")
    probes = {"0.031": True, ".031": True, "3.1e-02": True, "3.1e-2": True,
              "3.1E-2": True, "3.1 × 10^-2": True}
    got = {p: bool(pat.search(f"the rate was {p} per day")) for p in probes}
    bad = [p for p, want in probes.items() if got[p] != want]
    check("R7 scientific-notation variants written with a one-digit exponent are found",
          not bad, f"pattern={pat.pattern} mismatches={bad}")


def run_convert_corpus(tmp: Path, files: dict) -> tuple:
    sub, work = tmp / "sub", tmp / "work"
    for rel, data in files.items():
        p = sub / rel
        if isinstance(data, bytes):
            write(p, data)
        else:
            write(p, data)
    proc = subprocess.run([sys.executable, str(SCRIPTS / "convert_corpus.py"),
                           "--submission", str(sub), "--work", str(work)],
                          capture_output=True, text=True, timeout=180, cwd="/tmp")
    return work, proc


def xlsx_bytes(shared: list, inline: str = "") -> bytes:
    import io
    wb = ('<?xml version="1.0"?><workbook xmlns="%s" xmlns:r="http://schemas.'
          'openxmlformats.org/officeDocument/2006/relationships"><sheets>'
          '<sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>') % W_NS
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.'
            'openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>')
    cells = "".join(f'<c r="{chr(65+i)}1" t="s"><v>{i}</v></c>' for i in range(len(shared)))
    if inline:
        cells += f'<c r="Z1" t="inlineStr"><is><t>{inline}</t></is></c>'
    sheet = ('<?xml version="1.0"?><worksheet xmlns="%s"><sheetData><row r="1">%s</row>'
             '</sheetData></worksheet>') % (W_NS, cells)
    sst = ('<?xml version="1.0"?><sst xmlns="%s">%s</sst>'
           % (W_NS, "".join(f"<si><t>{s}</t></si>" for s in shared)))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", sst)
    return buf.getvalue()


def test_shared_strings_entities_decoded():
    tmp = tmpdir("r9")
    work, proc = run_convert_corpus(tmp, {"supp.xlsx": xlsx_bytes(["A&amp;B assay", "caf&eacute;"],
                                                                  inline="inline&amp;ok")})
    text = (work / "corpus" / "supp.xlsx.txt").read_text(encoding="utf-8")
    check("R9 xlsx shared strings are entity-decoded like inline strings",
          "A&B assay" in text and "café" in text and "&amp;" not in text,
          f"rc={proc.returncode} text={text[:120]!r}")


def test_flattened_corpus_name_collision_keeps_both_documents():
    tmp = tmpdir("r8")
    work, proc = run_convert_corpus(tmp, {"figs/notes.md": "ALPHA document\n",
                                          "figs__notes.md": "BETA document\n"})
    corpus = work / "corpus"
    texts = [p.read_text(encoding="utf-8") for p in sorted(corpus.glob("*.txt"))]
    joined = "\n".join(texts)
    check("R8 two documents that flatten to one corpus name are both kept",
          "ALPHA" in joined and "BETA" in joined, f"files={[p.name for p in corpus.glob('*')]}")


def test_xlsx_lock_is_binary_bucket():
    tmp = tmpdir("r11")
    work, proc = run_convert_corpus(tmp, {"data.xlsx.lock": "lock"})
    inv = {e["path"]: e["status"] for e in json.loads((work / "inventory.json").read_text())}
    check("R11 a *.xlsx.lock file lands in the read-only/binary bucket",
          inv.get("data.xlsx.lock") == "read-only/binary", f"statuses={inv}")


def test_acronym_definition_attribution():
    tmp = tmpdir("r10")
    work = tmp / "work"
    write(work / "corpus" / "main.md.txt",
          "The RT-PCR (reverse transcription PCR) assay was used.\n"
          "We also ran a PCR (polymerase chain reaction) test.\n"
          "Single-cell RNA (scRNA-seq) was performed.\n")
    proc = subprocess.run([sys.executable, str(SCRIPTS / "extract_acronyms.py"),
                           "--work", str(work), "--out", str(tmp / "art")],
                          capture_output=True, text=True, timeout=180, cwd="/tmp")
    items = json.loads((tmp / "art" / "artifacts" / "M1_acronyms.json")
                       .read_text(encoding="utf-8"))
    by_tok = {i["acronym"]: i for i in items}
    pcr = sorted(by_tok.get("PCR", {}).get("expansions") or [])
    rna = sorted(by_tok.get("RNA", {}).get("expansions") or [])
    check("R10 PCR does not inherit the RT-PCR expansion",
          pcr == ["polymerase chain reaction"], f"PCR expansions={pcr}")
    check("R10 RNA does not inherit the scRNA-seq expansion", rna == [], f"RNA expansions={rna}")


# =====================================================================

def main() -> int:
    print(f"workspace: {WS}\nskills:    {SKILLS}\n")
    print("== R1 builtin writer keeps table positions ==")
    test_table_position_preserved()
    test_changed_table_keeps_its_slot()
    print("\n== R2 starred captions ==")
    test_starred_caption_scanned()
    print("\n== R3 prior-finding id boundaries ==")
    test_prior_id_boundary()
    print("\n== R4 judge backend precedence ==")
    test_judge_agent_cmd_precedence()
    print("\n== R5 one-member field ==")
    test_field_of_one_round_completes()
    print("\n== R6 in-round retry freshness ==")
    test_stale_downstream_inputs_are_reset()
    test_healthy_round_is_not_reset()
    test_judge_inputs_are_revalidated()
    print("\n== R7 extract_occurrences variants ==")
    test_sci_exponent_variants()
    print("\n== R8/A convert_corpus ==")
    test_flattened_corpus_name_collision_keeps_both_documents()
    test_shared_strings_entities_decoded()
    test_xlsx_lock_is_binary_bucket()
    print("\n== R10 extract_acronyms ==")
    test_acronym_definition_attribution()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL ROUND-2 CANDIDATE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

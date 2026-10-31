#!/usr/bin/env python3
"""Regression checks for the 2026-10-31 fix-bugs wave 1.

Run:  python3 .paper_test/test_fix_bugs_20261031_wave1.py

Every Cxx below is a candidate from the verify-findings intersection; each
check failed on the pre-fix tree and pins the smallest observed defect.
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
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
TMPDIRS = []
FAILS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs20261031_pp", "paper_pipeline.py")
pf = load("fixbugs20261031_pf", "paper_docx_format.py")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


class FakeCtx:
    def __init__(self, root: Path, cfg: dict = None):
        self.root = root
        self.cfg = cfg or {}
        self.reports_dir = root / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def run(self, rid):
        return None

    def log(self, *a, **k):
        pass

    def sandbox_of(self, rec):
        return self.root / rec.get("sandbox", "")


# ---------------------------------------------------------------------------
# F01 -- prompt and postcheck derive the split from one predicate
# ---------------------------------------------------------------------------
def test_f01() -> None:
    print("\n== F01: scoped split review uses one split decision ==")
    old = pp.round_review_scope
    try:
        pp.round_review_scope = lambda ctx, r: "formatting-writing"
        fw = FakeCtx(scratch("f01fw_"), {"review_split": "phases"})
        check("F01 a formatting-writing round plans no split",
              pp.review_split_for_round(fw, 1) == "off")
        pp.round_review_scope = lambda ctx, r: "full"
        full = FakeCtx(scratch("f01full_"), {"review_split": "phases"})
        check("F01 a full round keeps its configured split",
              pp.review_split_for_round(full, 1) == "phases")
    finally:
        pp.round_review_scope = old
    src = (WS / "paper_pipeline_parts/p07_stage_quality_journal.py").read_text("utf-8")
    body = src[src.index("def postcheck_review"):]
    body = body[:body.index("\ndef ")]
    check("F01 postcheck_review passes the shared split decision",
          "split=review_split_for_round(ctx, _round)" in body)


# ---------------------------------------------------------------------------
# F02 -- the scoped guard authorizes the exact relative path, never a basename
# ---------------------------------------------------------------------------
def test_f02() -> None:
    print("\n== F02: a bare basename does not authorize another directory ==")
    sb = scratch("f02_") / "r1_a2_revise"
    base, rev = sb / "base", sb / "revised"
    for d in (base, rev):
        (d / "a").mkdir(parents=True)
        (d / "b").mkdir(parents=True)
    (base / "a" / "doc.docx").write_text("A base")
    (base / "b" / "doc.docx").write_text("B base")
    (rev / "a" / "doc.docx").write_text("A base")
    (rev / "b" / "doc.docx").write_text("B CHANGED")
    _ledger(rev, "a/doc.docx")
    errs = pp.scoped_scope_problems(None, sb, rev)
    check("F02 the a/doc.docx row does not authorize b/doc.docx",
          any("b/doc.docx" in e and "no structured row" in e for e in errs), errs)
    _ledger(rev, "b/doc.docx")
    check("F02 the exact relative path authorizes the edit",
          pp.scoped_scope_problems(None, sb, rev) == [])


def _ledger(rev: Path, rel: str) -> None:
    (rev / "revision_report.json").write_text(json.dumps(
        {"ledger": [{"id": "F-1", "file": rel, "final_status": "fixed"}]}))


# ---------------------------------------------------------------------------
# F03 -- a failed publication leaves the previous package intact
# ---------------------------------------------------------------------------
def test_f03() -> None:
    print("\n== F03: failed journal publication keeps the old package ==")
    root = scratch("f03_")
    dst = root / "journal_submission"
    dst.mkdir()
    (dst / "keep.txt").write_text("old valid package")
    ctx = FakeCtx(root)
    try:
        pp.publish_journal_submission(ctx, root / "missing_target", "x")
        failed = False
    except Exception:
        failed = True
    check("F03 the publication fails on a missing target", failed)
    check("F03 the previous package is still there",
          (dst / "keep.txt").is_file() and "old valid package" in
          (dst / "keep.txt").read_text())


# ---------------------------------------------------------------------------
# F05 -- per-limit notes are preserved and rendered as a recorded gap
# ---------------------------------------------------------------------------
def test_f05() -> None:
    print("\n== F05: the profile's per-limit note survives normalization ==")
    probs = []
    clean = pp._clean_length_limits(
        {"source": "s", "main_text": {"base": 3000, "relaxation": 1.25,
                                      "note": "display items capped at 6"},
         "abstract": {"base": 150, "relaxation": 1.1}}, "x", probs)
    check("F05 the main-text note is kept",
          clean["main_text"]["note"] == "display items capped at 6", clean)
    check("F05 the note is readable from the profile",
          pp.load_venue_profile("nature-biotechnology").length_limit_note("main_text")
          .startswith("https://www.nature.com/nbt/content"))
    clause = pp._caps_clause(pp.load_venue_profile("nature-biotechnology"))
    check("F05 M19's cap clause names the unmodelled rules",
          "does NOT model" in clause and "display items" in clause, clause[-160:])


# ---------------------------------------------------------------------------
# F06 -- a legacy snapshot inherits a type's own counting block
# ---------------------------------------------------------------------------
def test_f06() -> None:
    print("\n== F06: legacy snapshot inherits per-type counting ==")
    pp._DISPLAY_RULE_INHERIT_CACHE.clear()
    snap = {"id": "nature-biotechnology", "label": "NBT", "short": "NBT",
            "article_types": [{"id": "brief-communication", "label": "Brief",
                               "counting": None,
                               "length_limits": {"main_text": {"base": 1500,
                                                               "relaxation": 1.0}}}],
            "counting": {"main_text": {"excludes": ["abstract", "methods",
                                                    "references", "figure-legends"]}},
            "tables": {}, "figures": {}, "references": {}, "numbering": {},
            "leftover_phrases": [], "figure_text": {}, "image_dpi": {},
            "foreign_container_headings": [], "page_budget": {}}
    prof = pp._snapshot_profile({"venue": "nature-biotechnology",
                                 "venue_profile": snap}, "nature-biotechnology")
    excludes = prof.with_article_type("brief-communication").main_text_excludes()
    check("F06 Brief Communication uses its own counting block",
          "acknowledgements" in excludes, excludes)


# ---------------------------------------------------------------------------
# F08 -- an unreadable file is never a content-independent marker
# ---------------------------------------------------------------------------
def test_f08() -> None:
    print("\n== F08: two unreadable corpora do not share a fingerprint ==")
    a, b = scratch("f08a_"), scratch("f08b_")
    (a / "x.docx").write_text("secret A")
    (b / "y.png").write_text("secret B")
    os.chmod(a / "x.docx", 0)
    os.chmod(b / "y.png", 0)
    fa = pp.corpus_content_set_fingerprint([(a, "", ())])
    fb = pp.corpus_content_set_fingerprint([(b, "", ())])
    check("F08 different unreadable file sets get different fingerprints",
          len(fa) == 64 and len(fb) == 64 and fa != fb, (fa, fb))
    check("F08 the marker names the unreadable file's relative path",
          pp.corpus_content_set_fingerprint([(a, "", ())]) == fa)
    c = scratch("f08c_")
    (c / "x.txt").write_text("hello")
    check("F08 a readable corpus still fingerprints",
          len(pp.corpus_content_set_fingerprint([(c, "", ())])) == 64)


# ---------------------------------------------------------------------------
# F09 -- filler is not a coverage disposition
# ---------------------------------------------------------------------------
def test_f09() -> None:
    print("\n== F09: one-character/punctuation bases are rejected ==")
    for value in ("clean -- basis: x", "clean -- basis: .", "unable -- ."):
        check(f"F09 {value!r} is filler", not pp._coverage_disposition_ok(value))
    for value in ("clean -- basis: artifacts/M1_acronyms.md",
                  "unable -- no PDF renderer", "3 findings",
                  "out of scope -- formatting-writing round"):
        check(f"F09 {value!r} is a real disposition",
              pp._coverage_disposition_ok(value))


# ---------------------------------------------------------------------------
# F10 -- the operator's audit timeout is honored and recorded
# ---------------------------------------------------------------------------
def test_f10() -> None:
    print("\n== F10: audit timeouts are honored, not floored at 60 s ==")
    seen = []

    def fake(sb, rec, cmd, seconds, **kw):
        seen.append(seconds)
        return {"rc": 0, "dur": 0, "error": None, "log": None}

    old_exec, old_ops = pp._execute_attempt_in, pp.round_judge_opinions
    try:
        pp._execute_attempt_in = fake
        pp.round_judge_opinions = lambda *a, **k: []
        ctx = FakeCtx(scratch("f10_"))
        info = pp.run_defect_audit_agent(ctx, 1, {"defects": []},
                                         ["/bin/true"], timeout=10)[1]
        check("F10 a 10 s defect-audit timeout stays 10 s", seen == [10], seen)
        check("F10 the effective/requested timeout is recorded",
              info.get("timeout") == 10 and info.get("timeout_requested") == 10, info)
        seen.clear()
        info = pp.run_judge_conflict_agent(ctx, 1, {}, ["/bin/true"], timeout=10)[1]
        check("F10 a 10 s conflict-audit timeout stays 10 s", seen == [10], seen)
        check("F10 the conflict audit records both timeout values",
              info.get("timeout") == 10 and info.get("timeout_requested") == 10, info)
    finally:
        pp._execute_attempt_in, pp.round_judge_opinions = old_exec, old_ops


# ---------------------------------------------------------------------------
# F12 -- a negative --timeout is refused everywhere
# ---------------------------------------------------------------------------
def test_f12() -> None:
    print("\n== F12: every command refuses a negative --timeout ==")
    from types import SimpleNamespace
    for value in (None, 0, 10):
        check(f"F12 --timeout {value!r} is kept",
              pp._timeout_seconds(SimpleNamespace(timeout=value), 3600) ==
              (3600 if value is None else value))
    try:
        pp._timeout_seconds(SimpleNamespace(timeout=-1), 3600)
        refused = False
    except SystemExit:
        refused = True
    check("F12 a negative timeout is a usage error", refused)


# ---------------------------------------------------------------------------
# F16 -- one write_text_atomic, with the p04 signature
# ---------------------------------------------------------------------------
def test_f16() -> None:
    print("\n== F16: write_text_atomic has a single definition ==")
    check("F16 the surviving writer takes (path, text, encoding)",
          pp.write_text_atomic.__code__.co_argcount == 3,
          pp.write_text_atomic.__code__.co_argcount)
    check("F16 it is the p04 implementation",
          pp.write_text_atomic.__code__.co_filename.endswith("p04_utils.py"),
          pp.write_text_atomic.__code__.co_filename)


# ---------------------------------------------------------------------------
# F18 -- every prior decision id is scanned
# ---------------------------------------------------------------------------
def test_f18() -> None:
    print("\n== F18: a later decision id is not hidden by the first ==")
    root = scratch("f18_")
    (root / "human_review_feedback").mkdir()
    (root / "human_review_feedback" / "decision.txt").write_text(
        "Nature Genetics-A-12-2024 decision. Title: Benchmarking single-cell copy "
        "number methods. A revision decision followed: Nature Genetics-A-13-2025 "
        "on Benchmarking single-cell copy number methods.", encoding="utf-8")
    (root / "cover_letter.tex").write_text(
        "\\documentclass{article}\\begin{document}Dear Editor, Related manuscripts: "
        "none. Our Benchmarking single-cell copy number methods study is not under "
        "consideration elsewhere.\\end{document}\n", encoding="utf-8")
    rows = pp.scan_prior_submission_disclosure(root, submitted_docs=["cover_letter.tex"])
    ids = {r["reference"] for r in rows}
    check("F18 both the first AND the later decision id are checked",
          any("12-2024" in r for r in ids) and any("13-2025" in r for r in ids), ids)


# ---------------------------------------------------------------------------
# F19 -- a dirty run's materializer is not re-run on every tick
# ---------------------------------------------------------------------------
def test_f19() -> None:
    print("\n== F19: a dirty sandbox is prepared once ==")
    src = (WS / "paper_pipeline_parts/p08_selection_driver.py").read_text("utf-8")
    body = src[src.index("def run_round_runs"):]
    prep = body[body.index("def prepare(e)"):body.index("# ---- manual mode")]
    try:
        guard = prep.index("if rid in dirty_seen")
        materialize = prep.index('e["materialize"](ctx)')
        check("F19 the dirty guard is before the materializer", guard < materialize)
        check("F19 a dirty result is recorded", "dirty_seen.add(rid)" in prep)
    except ValueError as e:
        check("F19 the dirty-run guard exists", False, str(e))


# ---------------------------------------------------------------------------
# F23/F24/F27 -- formatter splices keep the OOXML well-formed
# ---------------------------------------------------------------------------
def test_f23_f24_f27() -> None:
    print("\n== F23/F24/F27: self-closing splices and the front-matter gap ==")
    got = pf._set_para_style('<w:p w:rsidR="X"/>', "Title")
    check("F23 a self-closing paragraph is expanded",
          got == '<w:p w:rsidR="X"><w:pPr><w:pStyle w:val="Title"/></w:pPr></w:p>', got)
    got = pf._rpr_splice('<w:rPr w:rsidR="X"/>', "<w:i/>", "i")
    check("F24 a self-closing rPr keeps its attributes",
          got == '<w:rPr w:rsidR="X"><w:i/></w:rPr>', got)
    doc = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
           '2006/main"><w:body><w:p><w:r><w:t>Title</w:t></w:r></w:p><w:p><w:r>'
           '<w:t>Abstract</w:t></w:r></w:p></w:body></w:document>')
    out, info = pf._front_matter_styles(doc, {"title": "TitleStyle"})
    check("F27 no literal AuthorList style is invented",
          'w:val="AuthorList"' not in out, out[:200])
    check("F27 the unmodelled front-matter style is a named gap",
          bool(info.get("front_matter_gap")), info)


# ---------------------------------------------------------------------------
# F26 -- the pipeline reads figure_ocr with the formatter's off spellings
# ---------------------------------------------------------------------------
def test_f26() -> None:
    print("\n== F26: figure_ocr='off' is false in the pipeline scan ==")
    check("F26 the pipeline has a policy-flag reader",
          pp._policy_flag({"figure_ocr": "off"}, "figure_ocr", True) is False)
    src = (WS / "paper_pipeline_parts/p04_utils.py").read_text("utf-8")
    check("F26 the figure scan uses it",
          'ocr_on = _policy_flag(policy, "figure_ocr", True)' in src)


# ---------------------------------------------------------------------------
# F30 -- a length-truncated chat answer is an error, not success
# ---------------------------------------------------------------------------
def test_f30() -> None:
    print("\n== F30: finish_reason='length' is refused ==")
    qwen = load("fixbugs20261031_qwen", "paper_qwen_agent.py")
    cfg = {"base_url": "http://x", "model": "m", "api_key": "k", "max_tokens": 8}
    qwen._request = lambda *a, **k: (
        200, {"choices": [{"message": {"content": "partial answer"},
                           "finish_reason": "length"}]}, None)
    text, err = qwen.chat_text(cfg, "prompt")
    check("F30 a truncated answer returns no text", text == "", text)
    check("F30 the error names the truncation", "length" in err, err)
    qwen._request = lambda *a, **k: (
        200, {"choices": [{"message": {"content": "complete answer"},
                           "finish_reason": "stop"}]}, None)
    check("F30 a complete answer still passes",
          qwen.chat_text(cfg, "prompt") == ("complete answer", ""))


# ---------------------------------------------------------------------------
# F38/F40/F41/F42 -- the test harness itself
# ---------------------------------------------------------------------------
def test_f38_f42() -> None:
    print("\n== F38/F40/F41/F42: the regression harness does not lie ==")
    src = (WS / ".paper_test/docx_format_lib.py").read_text("utf-8")
    check("F38 the reference-title assertion no longer accepts a plain run",
          "|<w:t>Nature Methods</w:t>" not in src)
    cr = (WS / ".paper_test/change_requests_lib.py").read_text("utf-8")
    check("F40 the base identity check is parenthesized",
          'rec["self_id"] == expect_self\n              and ((sb / "self"'
          in cr)
    sched = load("fixbugs20261031_sched", ".paper_test/parallel_scheduling_lib.py")
    spans = {"a": {"start": 10.0, "end": 20.0},
             "b": {"start": 20.0, "end": 30.0}}
    check("F41 a same-instant hand-off counts as two concurrent sessions",
          sched.max_concurrency(spans) == 2, sched.max_concurrency(spans))
    header = (WS / ".paper_test/arm_levels_lib.py").read_text("utf-8")
    referenced = re.findall(r"python3 (\.paper_test/test_arm_levels[^\s]+\.py)", header)
    check("F42 the documented arm-levels suite exists",
          bool(referenced) and all((WS / p).is_file() for p in referenced), referenced)


# ---------------------------------------------------------------------------
# F47/F48/F49/F50/F52 -- the paper-skills extractors
# ---------------------------------------------------------------------------
def _run_script(rel: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(WS / rel), *args],
                          cwd=str(WS), capture_output=True, text=True, timeout=180)


def test_f47() -> None:
    print("\n== F47: a real markdown H3 is not a synthetic marker ==")
    work = scratch("f47_")
    (work / "corpus").mkdir()
    (work / "corpus" / "main.md.txt").write_text(
        "### FMO (fluorescence minus one)\nWe used FMO controls.\n", encoding="utf-8")
    r = _run_script("paper-skills/paper-review/scripts/extract_acronyms.py",
                    "--work", str(work), "--out", str(work / "out"))
    art = work / "out" / "artifacts" / "M1_acronyms.md"
    row = next((ln for ln in art.read_text("utf-8").splitlines()
                if ln.startswith("| FMO |")), "") if art.is_file() else ""
    check("F47 the H3 definition is inventoried",
          "fluorescence minus one" in row, r.stderr[-200:] or row)


def test_f48_f49() -> None:
    print("\n== F48/F49: reference text and proper names are not families ==")
    work = scratch("f48_")
    (work / "corpus").mkdir()
    (work / "corpus" / "main.md.txt").write_text(
        "We used color analysis.\n\nReferences\n\n"
        "1. Smith J. Colour of the sky. Journal of Colour Science. 2019.\n",
        encoding="utf-8")
    r = _run_script("paper-skills/paper-review/scripts/enumerate_conventions.py",
                    "--work", str(work), "--out", str(work / "out"))
    variants = work / "out" / "STYLE_VARIANTS.md"
    text = variants.read_text("utf-8") if variants.is_file() else ""
    check("F48 a bibliography-only variant is not a manuscript family",
          "Colour" not in text, r.stderr[-200:] or text[:200])
    conv = load("fixbugs20261031_conv",
                "paper-skills/paper-review/scripts/enumerate_conventions.py")
    for a, b in (("Michael", "Michel"), ("Caesar", "Cesar"), ("phoenix", "phenix")):
        check(f"F49 {a}/{b} are not collapsed",
              conv._candidate_key(a) != conv._candidate_key(b))


def test_f50() -> None:
    print("\n== F50: lowercase name particles belong to the surname ==")
    cites = load("fixbugs20261031_cites",
                 "paper-skills/paper-review/scripts/extract_citations.py")
    m = next(iter(cites.AY_CIT_RE.finditer("(van der Waals et al., 2019)")), None)
    got = cites.ay_callout(m)[1] if m else ""
    check("F50 the captured author is 'van der Waals'", got == "van der Waals", got)


def test_f52() -> None:
    print("\n== F52: a LaTeX cover letter is counted without its markup ==")
    work = scratch("f52_")
    tex = work / "cover_letter.tex"
    tex.write_text(
        "\\documentclass{article}\n\\usepackage{geometry}\n\\begin{document}\n"
        "\\noindent Dear Editor,\n\nWe are pleased to submit our manuscript. This "
        "sentence has exactly nineteen words in it for the count test.\n\n"
        "Sincerely,\nThe Authors\n\\end{document}\n", encoding="utf-8")
    r = _run_script("paper-skills/paper-review/scripts/count_words.py",
                    "--section", "cover-letter", str(tex))
    check("F52 the persuading part is 19 words, not 20",
          "cover letter: 19 words" in r.stdout,
          r.stderr[-200:] or r.stdout[-200:])


# ---------------------------------------------------------------------------
# F60 -- the integration rescan covers the rewrite-parity classes
# ---------------------------------------------------------------------------
def test_f60() -> None:
    print("\n== F60: the integration prompt carries the rewrite parity ==")
    sandbox = scratch("f60_")
    text = pp.integrate_prompt(sandbox, "r1_i1", 1, "a1", ["a2", "a3"])
    check("F60 M25-M29 are named in the integration prompt",
          "M25" in text and "M29" in text and "REWRITE-PARITY" in text)
    check("F60 no unresolved @@TOKEN@@ is left",
          not re.search(r"@@[A-Z0-9_]+@@", text))
    check("F60 the coverage sentence names the parity classes",
          "M18-M20, the rewrite-parity" in text)


# ---------------------------------------------------------------------------
# F61/F63/F65/F66/F70/F73 -- documentation and repository hygiene
# ---------------------------------------------------------------------------
def test_docs() -> None:
    print("\n== F61/F63/F65/F66/F70/F73: docs match the CLI ==")
    readme = (WS / "README.md").read_text("utf-8")
    check("F61 the flag summary lists qwen",
          "--agent {codex,claude,dsh,qwen,manual}" in readme)
    block = readme[readme.index("`--strict-venue` (accepted by every subcommand"):
                   readme.index("makes a missing", readme.index("`--strict-venue` (accepted"))]
    check("F66 set-dedup-mode appears exactly once", block.count("`set-dedup-mode`") == 1,
          block.count("`set-dedup-mode`"))
    for cmd in ("set-author-to-complete", "set-placeholder-file",
                "set-cold-start-review", "sync-code"):
        check(f"F66 the count includes {cmd}", f"`{cmd}`" in block)
    hist = (WS / "revision_history/REV_HISTORY.md").read_text("utf-8")
    check("F63 no removed set-probe-review command is documented",
          "set-probe-review" not in hist and "--probe-review" not in hist)
    check("F63 the cold-start review is documented",
          "set-cold-start-review" in hist and "COLD-START REVIEW" in hist)
    check("F63 the old automatic llm selection is gone",
          "returns `llm` automatically" not in hist)
    skills = (WS / "paper-skills/README.md").read_text("utf-8")
    check("F65 the installed directory name matches install_skill.sh",
          "paper-skills-<YYYY-MMDD>-<commit>" in skills and
          "paper-skills-v03" not in skills)
    check("F65 the 0.36 description is the Zotero refresh",
          "offline Zotero refresh" in skills)
    ignore = (WS / ".gitignore").read_text("utf-8")
    check("F70 Word owner files are ignored",
          "~$*.docx" in ignore and "~$*.doc" in ignore)
    test_readme = (WS / ".paper_test/README.md").read_text("utf-8")
    check("F73 the DAG description includes the audit gate",
          "audit marker" in test_readme)


# ---------------------------------------------------------------------------
# F75 -- untrusted DOCX parts are read under the shared budget
# ---------------------------------------------------------------------------
def test_f75() -> None:
    print("\n== F75: docx_style_ids and the parity check honor the part budget ==")
    pkg = scratch("f75_") / "x.docx"
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr("word/styles.xml",
                   '<w:styles xmlns:w="x"><w:style w:styleId="Title"/></w:styles>')
        z.writestr("word/settings.xml",
                   '<w:settings xmlns:w="x"><w:evenAndOddHeaders/></w:settings>')
        z.writestr("word/document.xml", '<w:document xmlns:w="x"><w:body/></w:document>')
    check("F75 a normal package still yields its style ids",
          pf.docx_style_ids(pkg) == ["Title"])
    old = pf.MAX_DOCX_PART_BYTES
    try:
        pf.MAX_DOCX_PART_BYTES = 10
        check("F75 an over-budget styles part is refused, not read",
              pf.docx_style_ids(pkg) == [])
        check("F75 an over-budget template part is refused",
              pf._template_uses_even_odd(pkg) is False)
    finally:
        pf.MAX_DOCX_PART_BYTES = old


# ---------------------------------------------------------------------------
# F77 -- add-venue publication reads staged files through the bounded readers
# ---------------------------------------------------------------------------
def test_f77() -> None:
    print("\n== F77: staged README/profile go through the bounded readers ==")
    d = scratch("f77_")
    sb = d / "sb"
    (sb / "store").mkdir(parents=True)
    (sb / "store" / "README.md").write_text("| `other` | x |\n", encoding="utf-8")
    (sb / "store" / "demo.json").write_text('{"id": "demo", "label": "Demo"}',
                                            encoding="utf-8")
    dest = d / "venues"
    dest.mkdir()
    calls = []
    old_text, old_json = pp.read_text_bounded, pp.read_json
    try:
        pp.read_text_bounded = lambda p, *a, **k: (
            calls.append(("text", str(p))), old_text(p, *a, **k))[1]
        pp.read_json = lambda p, *a, **k: (
            calls.append(("json", str(p))), old_json(p, *a, **k))[1]
        pp.publish_add_venue_staging(sb, dest, "demo")
    finally:
        pp.read_text_bounded, pp.read_json = old_text, old_json
    check("F77 the staged README is read with read_text_bounded",
          any(k == "text" and p.endswith("README.md") for k, p in calls), calls)
    check("F77 the staged profile is read with read_json",
          any(k == "json" and p.endswith("demo.json") for k, p in calls), calls)


# ---------------------------------------------------------------------------
# F79 -- nested revision elements are counted once
# ---------------------------------------------------------------------------
def test_f79() -> None:
    print("\n== F79: nested w:ins/w:del text is counted once ==")
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    doc = (f'<w:document xmlns:w="{W}"><w:body><w:p>'
           '<w:ins w:id="1"><w:r><w:t>one two</w:t></w:r>'
           '<w:ins w:id="2"><w:r><w:t>three</w:t></w:r></w:ins></w:ins>'
           '<w:del w:id="3"><w:r><w:delText>four five</w:delText></w:r>'
           '<w:del w:id="4"><w:r><w:delText>six</w:delText></w:r></w:del></w:del>'
           '</w:p></w:body></w:document>')
    pkg = scratch("f79_") / "x.docx"
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr("word/document.xml", doc)
    weight = pp.redline_markup_weight(pkg)
    check("F79 each nested text run is counted once", weight == {"ins": 3, "del": 3},
          weight)


# ---------------------------------------------------------------------------
# F80 -- latexmk/bibtex diagnostics survive the compile result
# ---------------------------------------------------------------------------
def test_f80() -> None:
    print("\n== F80: compile errors keep the latexmk diagnostics ==")
    here = scratch("f80_")
    bindir = here / "bin"
    bindir.mkdir()
    fake = bindir / "latexmk"
    fake.write_text('#!/bin/sh\n'
                    'echo "Latexmk: Missing input file x.tex"\n'
                    'echo "! LaTeX Error: missing input"\n'
                    'exit 1\n', encoding="utf-8")
    fake.chmod(0o755)
    pkg = here / "pkg"
    pkg.mkdir()
    (pkg / "doc.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    old_path = os.environ.get("PATH", "")
    try:
        os.environ["PATH"] = str(bindir) + os.pathsep + old_path
        res = pp.compile_latex_pdf(pkg, "doc.tex", here / "out.pdf", timeout=60)
    finally:
        os.environ["PATH"] = old_path
    check("F80 the TeX error is the reported cause",
          "LaTeX Error" in str(res.get("error")), res)
    check("F80 the latexmk diagnostic is kept",
          any("Latexmk:" in e for e in (res.get("errors") or [])), res.get("errors"))


# ---------------------------------------------------------------------------
# F83 -- the content hashers refuse a swapped link/FIFO
# ---------------------------------------------------------------------------
def test_f83() -> None:
    print("\n== F83: hashing re-opens a regular file, never a planted link ==")
    d = scratch("f83_")
    (d / "a.txt").write_text("inside")
    outside = d.parent / "outside-secret.txt"
    outside.write_text("OUTSIDE")
    (d / "link.txt").symlink_to(outside)
    try:
        pp.sha256_file(d / "link.txt")
        refused = False
    except OSError:
        refused = True
    check("F83 a symlinked payload is refused", refused)
    os.mkfifo(d / "fifo")
    try:
        pp.sha256_file(d / "fifo")
        fifo_refused = False
    except OSError:
        fifo_refused = True
    check("F83 a FIFO payload is refused", fifo_refused)
    check("F83 a regular payload still hashes",
          len(pp.sha256_file(d / "a.txt")) == 64)


# ---------------------------------------------------------------------------
# Repair-stage regressions (review findings R02/R03, 2026-10-31)
# ---------------------------------------------------------------------------
def test_r02_conflicts_negative_timeout() -> None:
    print("\n== R02: `conflicts` refuses a negative --timeout ==")
    root = scratch("r02_") / "root"
    root.mkdir()
    (root / "pipeline_config.json").write_text("{}", encoding="utf-8")
    base = [sys.executable, str(WS / "paper_pipeline.py"), "conflicts",
            "--root", str(root)]
    neg = subprocess.run(base + ["--timeout", "-1"], capture_output=True, text=True)
    check("R02 `conflicts --timeout -1` exits non-zero",
          neg.returncode != 0, f"rc={neg.returncode} out={neg.stdout[-200:]!r}")
    check("R02 the refusal names the non-negative invariant",
          "--timeout must be a non-negative number of seconds" in neg.stderr,
          neg.stderr[-300:])
    # 0 means "no timeout" and a positive value is still honoured.
    for value in ("0", "30"):
        pos = subprocess.run(base + ["--timeout", value], capture_output=True, text=True)
        check(f"R02 `conflicts --timeout {value}` is accepted",
              pos.returncode == 0 and "--timeout must be a non-negative" not in pos.stderr,
              f"rc={pos.returncode} err={pos.stderr[-200:]!r}")


def test_r03_failed_swap_keeps_old_record() -> None:
    print("\n== R03: a failed journal swap leaves the old record in place ==")
    root = scratch("r03_")
    (root / "reports").mkdir()
    target = root / "pkg"
    target.mkdir()
    (target / "manuscript.txt").write_text("NEW PACKAGE\n", encoding="utf-8")
    dst = root / "journal_submission"
    dst.mkdir()
    (dst / "keep.txt").write_text("old valid package\n", encoding="utf-8")
    old_record = {"mode": "continue", "manifest": {"keep.txt": "oldhash"},
                  "note": "OLD RECORD"}
    (root / "journal_submission.json").write_text(json.dumps(old_record), encoding="utf-8")

    class Ctx:
        def __init__(self, root):
            self.root = root
            self.cfg = {"revision_mode": "continue"}
            self.state = {}
            self.reports_dir = root / "reports"

        def rounds_count(self):
            return 0

    ctx = Ctx(root)
    real_replace = pp.os.replace

    def fail_stage_swap(src, dst_path):
        src, dst_path = Path(src), Path(dst_path)
        if src.name.startswith(".journal_submission.staging-") \
                and dst_path == root / "journal_submission":
            raise OSError("simulated swap failure")
        return real_replace(src, dst_path)

    pp.os.replace = fail_stage_swap
    raised = None
    try:
        pp.publish_journal_submission(ctx, target, "x")
    except BaseException as e:                                    # noqa: BLE001
        raised = e
    finally:
        pp.os.replace = real_replace

    check("R03 the failed swap raises", isinstance(raised, OSError), repr(raised))
    check("R03 the previous package survives",
          (dst / "keep.txt").is_file()
          and (dst / "keep.txt").read_text(encoding="utf-8") == "old valid package\n")
    record = json.loads((root / "journal_submission.json").read_text(encoding="utf-8"))
    check("R03 the previous record is not replaced",
          record.get("note") == "OLD RECORD"
          and sorted((record.get("manifest") or {}).keys()) == ["keep.txt"],
          json.dumps(record)[:300])
    check("R03 the failed staging tree is removed",
          not list(root.glob(".journal_submission.staging-*")))

    # The success path still publishes the new package AND the new record.
    pp.publish_journal_submission(ctx, target, "x")
    check("R03 a successful swap publishes the new package",
          (dst / "manuscript.txt").is_file())
    record = json.loads((root / "journal_submission.json").read_text(encoding="utf-8"))
    record_files = (record.get("manifest") or {}).get("files") or {}
    check("R03 a successful swap publishes the matching new record",
          sorted(record_files) == ["manuscript.txt"],
          json.dumps(record.get("manifest"))[:300])


# ---------------------------------------------------------------------------
def main() -> int:
    print("Regression checks for fix-bugs 2026-10-31 (wave 1)")
    for fn in (test_f01, test_f02, test_f03, test_f05, test_f06, test_f08,
               test_f09, test_f10, test_f12, test_f16, test_f18, test_f19,
               test_f23_f24_f27, test_f26, test_f30, test_f38_f42, test_f47,
               test_f48_f49, test_f50, test_f52, test_f60, test_docs,
               test_f75, test_f77, test_f79, test_f80, test_f83,
               test_r02_conflicts_negative_timeout,
               test_r03_failed_swap_keeps_old_record):
        fn()
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILS:
        print(f"\n{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("\nALL FIX-BUGS (2026-10-31 WAVE 1) CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for the 2026-11-13 fix-bugs wave (run 20261113-180010).

Each check names the verified finding it proves (F002, F003, ...). The suite is
hermetic: no network, no model call, no Word/PowerShell.

Run: python3 .paper_test/test_fix_bugs_20261113_wave1.py
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = Path(os.environ.get("PAPER_WS") or HERE.parent)
SCRIPTS = WS / "paper-skills" / "paper-review" / "scripts"
FAILS = []
TMP = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMP.append(d)
    return d


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def group(name, fn):
    try:
        fn()
    except Exception as exc:                                       # noqa: BLE001
        check(name, False, f"{type(exc).__name__}: {exc}")


sys.path.insert(0, str(HERE))
pipe = load("paper_fixbugs_wave1_pipe", WS / "paper_pipeline.py")
fmt = load("paper_fixbugs_wave1_fmt", WS / "paper_docx_format.py")
import docx_format_lib as dxl                                          # noqa: E402

dn = load("paper_fixbugs_wave1_numbers", SCRIPTS / "extract_numbers.py")
eo = load("paper_fixbugs_wave1_occ", SCRIPTS / "extract_occurrences.py")


# ---------------------------------------------------------------------------
# F031/F042-F059 -- documentation agrees with the code
# ---------------------------------------------------------------------------
def test_docs():
    print("\n== F031/F042-F059: documentation and docstrings match the tree ==")
    readme = (WS / "README.md").read_text("utf-8")
    hist = (WS / "revision_history" / "REV_HISTORY.md").read_text("utf-8")
    venue = (WS / "venue_profiles" / "README.md").read_text("utf-8")
    adapter = (WS / "paper_redlines_adapter.py").read_text("utf-8")
    loader = (WS / "paper_pipeline.py").read_text("utf-8")
    cli = (WS / "paper_pipeline_parts" / "p17_cli.py").read_text("utf-8")

    check("F031 the adapter no longer claims it clears OUT before the probes",
          "before any backend is tried" not in adapter)
    check("F042 README: provisional exits 0 unless --require-complete",
          "exits 4 or 5 in the\nlast two cases" not in readme
          and "provisional one exits 0 unless `--require-complete`" in readme)
    check("F043 README: raw_data is stripped from journal_submission, not the corpus",
          "never shipped in the published package" not in readme
          and "the judged corpus and DOES carry it" in readme)
    check("F044 REV_HISTORY: the removed `none` alias is refused",
          "still accepted everywhere as an alias" not in hist
          and "`none` was removed" in hist)
    check("F045 REV_HISTORY: the removed --with-author-to-complete flags are gone",
          "--with-author-to-complete-in-readme" not in hist
          and "--author-to-complete readme" in hist)
    check("F046 REV_HISTORY: run_all.py defaults to 32 jobs",
          "24 jobs by default" not in hist and "32 jobs by default" in hist)
    check("F048 README's set-revision-mode row lists llm",
          "set-revision-mode continue\\|init\\|transfer\\|resubmit\\|major\\|minor\\|llm"
          in readme)
    check("F049 the loader limits --skip-hash to root-loading commands",
          "Every command also accepts `--skip-hash`" not in loader
          and "Every root-loading command also accepts `--skip-hash`" in loader)
    check("F050 the loader no longer promises final_clean_version on every decide",
          "written on EVERY decide" not in loader
          and "always generated" not in loader
          and "attempted on EVERY decide" in loader)
    check("F051 the worked example runs all three rounds",
          "run BOTH rounds" not in cli and "run ALL THREE rounds" in cli)
    check("F052 venue_profiles/README drops the single-file claim",
          "single-file copy of the script still runs" not in venue
          and "does NOT run" in venue)
    check("F053 the revision-token path is the one that exists",
          "paper-skills/paper-revise/scripts/revision_token.py" in loader
          and "`paper-revise/scripts/revision_token.py`" not in loader)
    check("F054 REV_HISTORY's CLI list names the four current commands",
          all(cmd in hist for cmd in ("sync-code", "set-author-to-complete",
                                      "set-placeholder-file", "set-champion-select")))
    check("F055 venue_profiles/README states the leading-character rule",
          "Must START with a letter or digit" in venue)
    n_suites = len(list((HERE).glob("test_*.py")))
    import re
    m = re.search(r"run them in parallel \u2014 (\d+) suites", readme)
    check("F056 README's suite count matches the tree",
          bool(m) and int(m.group(1)) == n_suites,
          f"README={m.group(1) if m else None} tree={n_suites}")
    check("F057 the execution-profile revise row matches the live render",
          "| revise | 119 KB | 66 KB | 45% |" in readme)
    check("F058 REV_HISTORY describes the loader + ordered parts bundle",
          "single file, stdlib only" not in hist and "paper_pipeline_parts/" in hist)
    state = (WS / "paper_pipeline_parts" / "p05_state_corpus.py").read_text("utf-8")
    check("F059 load_state_file enforces the promised single-link rule",
          "st.st_nlink != 1" in state and "single-link" in state)


# ---------------------------------------------------------------------------
# F002-F015 -- DOCX formatter
# ---------------------------------------------------------------------------
def _minimal_doc(body: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<w:body>{body}</w:body></w:document>')


def test_docx():
    print("\n== F002-F015: DOCX formatter scan/fix ==")
    policy = dict(fmt.POLICY_DEFAULTS)

    # F002: the scratch/evidence test is RELATIVE to the scanned root.
    for anc in ("work", "raw_data"):
        root = scratch("f002_") / anc / "proj"
        root.mkdir(parents=True)
        dxl.make_package(root / "paper.docx")
        res = fmt.scan_paths([root], policy)
        check(f"F002 a package under an ancestor named {anc}/ is still scanned",
              len(res["files"]) == 1, str(res["files"]))
    root = scratch("f002b_")
    (root / "work").mkdir()
    dxl.make_package(root / "work" / "scratch.docx")
    dxl.make_package(root / "paper.docx")
    res = fmt.scan_paths([root], policy)
    check("F002 nested work/ scratch inside the root is still skipped",
          [Path(p).name for p in res["files"]] == ["paper.docx"], str(res["files"]))

    # F003: bounded inflation of a zlib bomb.
    bomb = __import__("zlib").compress(b"\0" * (2 * 1024 * 1024))
    try:
        out = fmt._inflate_bounded(bomb, limit=4096)
    except Exception as exc:                                       # noqa: BLE001
        out = f"raised {exc}"
    check("F003 a decomressed stream over the budget is refused", out is None, str(out)[:60])
    check("F003 a small stream still inflates",
          fmt._inflate_bounded(__import__("zlib").compress(b"hello"), limit=4096) == b"hello")

    # F004: BOM-less UTF-16 DTD is seen by the guard.
    payload = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x [<!ENTITY y "z">]><x/>'
    check("F004 a BOM-less UTF-16 DTD is refused",
          bool(fmt._docx_entity_problem(payload.encode("utf-16-le"), "word/document.xml")))
    z = scratch("f004_") / "s.docx"
    with zipfile.ZipFile(z, "w") as pkg:
        pkg.writestr("word/styles.xml", payload.encode("utf-16-le"))
    with zipfile.ZipFile(z) as pkg:
        check("F004 parse_styles refuses a BOM-less UTF-16 DTD", fmt.parse_styles(pkg) == {})

    # F005: a huge exponent does not raise.
    check("F005 10^99999 is parsed as None instead of OverflowError",
          fmt._parse_p("p = 1e99999") is None and fmt._parse_p("1 \\times 10^{99999}") is None)
    check("F005 an ordinary scientific p still parses",
          fmt._parse_p("1.81e-5") is not None)

    # F007/F010/F012: scanner tri-state, internal anchor, live pStyle.
    xml = _minimal_doc(
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/><w:keepNext w:val="0"/></w:pPr>'
        '<w:r><w:t>Results</w:t></w:r>'
        '<w:hyperlink w:anchor="sec1"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
        '<w:t>see section</w:t></w:r></w:hyperlink></w:p>'
        '<w:sectPr><w:headerReference w:type="default" r:id="rId1"/>'
        '<w:titlePg w:val="0"/></w:sectPr>')
    out, changes, _meta = fmt.fix_document(xml, {}, policy)
    check("F007 keepNext val=0 is turned ON, not duplicated",
          '<w:keepNext/>' in out and '<w:keepNext w:val="0"/>' not in out)
    check("F007 the titlePg val=0 is turned ON", '<w:titlePg/>' in out
          and '<w:titlePg w:val="0"/>' not in out)
    check("F010 an internal w:anchor hyperlink is not unwrapped",
          'w:anchor="sec1"' in out)
    para = ('<w:p><w:pPr><w:pPrChange w:id="1" w:author="A"><w:pPr>'
            '<w:pStyle w:val="Old"/><w:ind w:left="720"/></w:pPr></w:pPrChange>'
            '</w:pPr><w:r><w:rPr><w:spacing w:val="20"/></w:rPr><w:t>x</w:t></w:r></w:p>')
    styled = fmt._set_para_style(para, "New")
    check("F012 the live pStyle is inserted, the pPrChange record is kept",
          '<w:pStyle w:val="New"/>' in styled and 'w:val="Old"' in styled)
    stripped = fmt._strip_direct_props(para)
    check("F013 revision-record ind and run character spacing are preserved",
          '<w:ind w:left="720"/>' in stripped and '<w:spacing w:val="20"/>' in stripped)
    live = ('<w:p><w:pPr><w:style w:val="x"/><w:ind w:left="720"/>'
            '<w:spacing w:before="240"/><w:jc w:val="center"/></w:pPr></w:p>')
    live_out = fmt._strip_direct_props(live)
    check("F013 live paragraph ind/spacing/jc are still stripped",
          "<w:ind" not in live_out and "<w:spacing" not in live_out
          and "<w:jc" not in live_out)

    # F008: evenAndOddHeaders w:val=0 is present-but-off; the writer flips it ON.
    parts = {"[Content_Types].xml": b"<Types/>",
             "word/settings.xml": b'<w:settings xmlns:w="http://schemas.openxmlformats.org/'
                                  b'wordprocessingml/2006/main"><w:evenAndOddHeaders '
                                  b'w:val="0"/></w:settings>'}
    changed = fmt._with_even_odd_headers(parts)
    check("F008 evenAndOddHeaders val=0 is flipped on in place",
          changed is True and b'<w:evenAndOddHeaders/>' in parts["word/settings.xml"]
          and b'val="0"' not in parts["word/settings.xml"])

    # F009/F011: self-closing w:t / w:instrText are not opening tags.
    frag = ('<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:r><w:t xml:space="preserve"/></w:r><w:r><w:t>abc</w:t></w:r></w:p>')
    frags = fmt._text_fragments(frag)
    check("F009 a self-closing w:t is not read as an opening text element",
          len(frags) == 1 and frags[0][2] == "abc", str([f[2] for f in frags]))
    check("F009 _TEXT_EDGE_TOKENS does not match a self-closing w:t",
          fmt._TEXT_EDGE_TOKENS.fullmatch('<w:t xml:space="preserve"/>') is None)
    instr = ('<w:p><w:r><w:instrText xml:space="preserve"/></w:r>'
             '<w:r><w:instrText> PAGE </w:instrText></w:r></w:p>')
    hits = fmt.INSTR_RE.findall(instr)
    check("F011 a self-closing w:instrText does not swallow the next instruction",
          len(hits) == 1 and "PAGE" in hits[0], str(hits))

    # F014/F015: one deviant paragraph is drift; paragraph-mark spacing is not.
    def _para(i, extra=""):
        return (0, 0, f'<w:p><w:pPr><w:pStyle w:val="Body"/>{extra}</w:pPr><w:r><w:t>'
                      f'Paragraph number {i} has enough words in it to count as body prose.'
                      f'</w:t></w:r></w:p>')
    rows = fmt.style_convention_rows(
        [_para(0), _para(1), _para(2), _para(3, '<w:spacing w:before="240"/>')],
        {}, "x.docx")
    check("F014 a single deviant paragraph is reported, not exempted",
          any(r["rule"] == "FMT-T10b" for r in rows), str([r["rule"] for r in rows]))
    mark = _para(0)
    mark = (0, 0, mark[2].replace("<w:pPr>", "<w:pPr><w:rPr><w:spacing w:val=\"20\"/>"
                                        "</w:rPr>"))
    rows = fmt.style_convention_rows([mark] + [_para(i) for i in range(1, 5)], {}, "x.docx")
    check("F015 paragraph-mark character spacing is not reported as paragraph spacing",
          not rows, str([r["rule"] for r in rows]))


# ---------------------------------------------------------------------------
# F030-F112 -- pipeline/scripts units
# ---------------------------------------------------------------------------
def test_pipeline():
    print("\n== F027/F030/F034-F112: pipeline and script units ==")
    # F027: a set-but-empty allowlist fails closed (node is the shipped test).
    try:
        node = subprocess.run(["node", "containment.test.mjs"], cwd=WS / "mcp-docx-compare",
                              capture_output=True, text=True, timeout=120)
        check("F027 containment.mjs refuses a set-but-empty allowlist",
              node.returncode == 0 and "PASSED" in node.stdout, node.stderr[-200:])
    except FileNotFoundError:
        check("F027 containment.mjs test (node unavailable)", True, "skipped, no node")

    # F034
    rows = [{"check": "M1", "location": f"p{i}", "evidence": "x",
             "disposition": ("Checked against the manuscript and the base corpus; "
                             "no defect was found in this row.")}
            for i in range(13)]
    rows[0]["disposition"] = ("see M1: checked against the manuscript and the base "
                              "corpus; no defect was found.")
    probs = pipe.disposition_artifact_problems(rows)
    check("F034 one id-bearing row no longer exempts a templated closure",
          any("TEMPLATE" in p for p in probs), str(probs)[:200])

    # F035/F036
    check("F035 a compliant zero-finding re-probe is dispositioned",
          pipe.prior_proposal_dispositioned("M37", "M37: no anomalies -- checked: base/", ""))
    check("F035 a real denial is still not a re-probe",
          not pipe.prior_proposal_dispositioned("M37", "we did not re-probe M37", ""))
    check("F036 the M1b reason may be written before the token",
          pipe._m1b_coverage_reason(
              "All 25 long forms are quoted article titles, not findings (M1b rows)"))

    # F037/F038/F041 -- source invariants of the table checks.
    p07 = (WS / "paper_pipeline_parts" / "p07_stage_quality_journal.py").read_text("utf-8")
    p06 = (WS / "paper_pipeline_parts" / "p06_postchecks.py").read_text("utf-8")
    p08 = (WS / "paper_pipeline_parts" / "p08_selection_driver.py").read_text("utf-8")
    p12 = (WS / "paper_pipeline_parts" / "p12_conflicts_decide.py").read_text("utf-8")
    p14 = (WS / "paper_pipeline_parts" / "p14_tracking.py").read_text("utf-8")
    p19 = (WS / "paper_pipeline_parts" / "p19_profiles.py").read_text("utf-8")
    check("F037 the empty-key dedup guard compares a 3-tuple",
          "key != (\"\", \"\", \"\")" in p07)
    check("F041 the plan-binding regex accepts an en dash",
          "fact\\s+removed\\s*[\u2014\u2013:-]" in p07)
    # F038: a one-word skip reason is still refused for `not-a-concern`.
    sb = scratch("f038_")
    (sb / "concerns").mkdir()
    (sb / "concerns" / "SEED_COVERAGE.md").write_text(
        "| seed id | concern ids | disposition |\n|---|---|---|\n"
        "| S001 |  | not-a-concern -- x |\n", encoding="utf-8")
    probs = pipe.journal_seed_coverage_problems(sb, {"candidates": [{"seed_id": "S001"}]}, [])
    check("F038 `not-a-concern -- x` needs a real three-word reason",
          any("at least three words" in p for p in probs), str(probs)[:160])

    # F039/F084
    check("F039 a science compound named feedback_loop is a manuscript",
          not pipe.is_journal_feedback_name("feedback_loop.txt"))
    check("F039 editor decision feedback is still feedback",
          pipe.is_journal_feedback_name("reviewer_comments.txt"))
    check("F084 editorial.v2.docx is an article-type manuscript",
          not pipe.is_journal_feedback_name("editorial.v2.docx"))

    # F060/F098 -- recorded paths that escape or contain NUL are refused, not raised.
    tmp = scratch("f060_")
    for bad in ("a\x00b", "../outside"):
        try:
            pipe.contained_under(tmp, bad)
            refused = False
        except SystemExit:
            refused = True
        except ValueError:
            refused = False
        check(f"F060/F098 a recorded path {bad!r} is refused (not a traceback)", refused)

    # F066/F067
    check("F066 a typographic minus is read as a negative number",
          pipe._conflict_numbers("−12 vs −14") == {-12, -14})
    check("F067 a dangling code/foo.py is not 'shipped' by a basename elsewhere",
          pipe._pkg2_name_resolution("code/foo.py",
                                     (set(), {"foo.py"}, {}, {}, {}))[0] == "unknown")

    # F069/F090/F095/F106 -- unreadable/symlinked files are reported, not fatal.
    d = scratch("f069_")
    (d / "locked").mkdir()
    (d / "locked" / "x").write_text("x")
    (d / "ok.txt").write_text("y")
    os.chmod(d / "locked", 0)
    try:
        man = pipe.hash_manifest(d, on_error="<unreadable>")
        check("F069 an unreadable directory does not abort hash_manifest",
              man.get("count") == 1, str(man))
    finally:
        os.chmod(d / "locked", 0o755)

    d = scratch("f090_")
    (d / "paper.tex").write_text("hello")
    os.chmod(d / "paper.tex", 0)
    try:
        got = pipe.list_track_files([(d, "", ())])
        check("F090 an unreadable .tex is skipped instead of aborting track", got == [], str(got))
    finally:
        os.chmod(d / "paper.tex", 0o644)

    d = scratch("f095_")
    outside = scratch("f095_out_") / "README.md"
    outside.write_text("See REVISION_REPORT for details.\n", encoding="utf-8")
    (d / "README.md").symlink_to(outside)
    check("F095 a symlinked README is not read", pipe.readme_internal_note_rows(d / "README.md") == [])

    d = scratch("f106_")
    (d / "doc.docx").write_text("x")
    os.chmod(d / "doc.docx", 0)
    try:
        man = pipe.corpus_tree_manifest(d)
        check("F106 corpus_tree_manifest records an unreadable payload",
              man["files"].get("doc.docx") == "<unreadable>", str(man))
    finally:
        os.chmod(d / "doc.docx", 0o644)

    # F070: nested work/ is not tracked.
    d = scratch("f070_")
    (d / "supp" / "work").mkdir(parents=True)
    (d / "supp" / "paper.tex").write_text("x")
    (d / "supp" / "work" / "scratch.tex").write_text("x")
    got = pipe.list_track_files([(d, "", ("work",))])
    check("F070 nested supp/work/ scratch is not tracked",
          [r["rel"] for r in got] == ["supp/paper.tex"], str(got))

    # F073: round-qualified pre-rename review spellings.
    for tok, want in (("r1_reviewer", "guided_review"),
                      ("r1_review_b", "guided_review_b"),
                      ("2:reviewer", "guided_review")):
        spec = pipe.parse_only_spec(tok)
        check(f"F073 {tok} selects {want}",
              bool(spec and want in (spec.sessions.get(1) or []) + (spec.sessions.get(2) or [])))

    # F076/F077/F078
    pat = dict(dn.LABEL_PATTERNS)["percentage"]
    pairs = {t: (pat.search(t).group(1) if pat.search(t) else None)
             for t in ("12,345%", "12345%")}
    check("F076 thousands-separated and 5-digit percentages are whole numbers",
          pairs == {"12,345%": "12,345", "12345%": "12345"}, str(pairs))
    check("F077 ≤0.05 and ≤0.050 share one numeric key",
          dn._metric_key("p-value", "≤0.05") == dn._metric_key("p-value", "≤0.050"))
    cp = eo.variant_pattern("copy", "term")
    an = eo.variant_pattern("analysis", "term")
    check("F078 copy matches copies and not copyes",
          bool(cp.search("copies")) and not cp.search("copyes"))
    check("F078 analysis matches analyses and not analysises",
          bool(an.search("analyses")) and not an.search("analysises"))

    # F080
    sub = scratch("f080_")
    (sub / "paper.md").write_text("x")
    r = subprocess.run([sys.executable, str(SCRIPTS / "convert_corpus.py"),
                        "--submission", str(sub), "--work", str(sub / "work")],
                       capture_output=True, text=True, timeout=60)
    check("F080 WORK inside SUBMISSION_DIR is refused",
          r.returncode == 2 and "overlaps the submission" in (r.stdout + r.stderr),
          (r.stdout + r.stderr)[-160:])

    # F081: an over-budget xlsx part is not read.
    class _Info:
        file_size = 70 * 1024 * 1024

    class _Z:
        def getinfo(self, name):
            return _Info()

        def read(self, name):
            raise AssertionError("over-budget part was read")

    conv = load("paper_fixbugs_wave1_conv", SCRIPTS / "convert_corpus.py")
    check("F081 an over-budget xlsx part is refused before z.read",
          conv._xlsx_part(_Z(), "xl/worksheets/sheet1.xml") is None)

    # F082
    class _C:
        cfg = {"revision_mode": "llm"}

    check("F082 an llm-mode rewrite depends on the feedback run",
          "r1_feedback" in pipe.upstream_deps({"kind": "rewrite", "round": 1}, _C()))

    # F083: a fabricated before-span is refused when previous_package lacks the file.
    sb = scratch("f083_")
    (sb / "previous_package").mkdir()
    target = scratch("f083_target_")
    (target / "paper.md").write_text("The revised sentence is here.\n")
    probs = pipe._response_change_span_problems(
        sb, target, [{"id": "R1", "changes": [{"file": "paper.md", "operation": "edit",
                                               "location": "Results",
                                               "before": "The old sentence.",
                                               "after": "The revised sentence."}]}])
    check("F083 a missing previous_package file cannot certify a before-span",
          any("previous_package/paper.md is missing" in p for p in probs), str(probs)[:200])

    # F101: a symlink at the destination is refused and the outside file survives.
    src = scratch("f101_src_")
    (src / "a.txt").write_text("new")
    dst = scratch("f101_dst_")
    outside = scratch("f101_out_") / "secret.txt"
    outside.write_text("orig")
    (dst / "a.txt").symlink_to(outside)
    try:
        pipe.copy_into(src, dst)
        refused = False
    except OSError:
        refused = True
    check("F101 copy_into refuses a symlinked destination entry",
          refused and outside.read_text() == "orig")

    # F102
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"></Types>')
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
                   'wordprocessingml/2006/main"><w:body><w:p w:rsidR=\'00AB12\' '
                   'w:rsidRDefault="00CD34"><w:r><w:t>x</w:t></w:r></w:p></w:body></w:document>')
    clean, _notes = pipe._sanitize_ooxml_bytes(buf.getvalue())
    with zipfile.ZipFile(io.BytesIO(clean)) as z:
        doc = z.read("word/document.xml").decode("utf-8")
    check("F102 single-quoted rsid attributes are stripped",
          "rsidR" not in doc and "00AB12" not in doc, doc[:160])

    # F103
    out = pipe._rewrite_rels_package_targets(
        b"<Relationship Id='r1' Target='supp%20file.docx'/>",
        "word/_rels/document.xml.rels", {"supp file.docx": "new file.docx"})
    check("F103 single-quoted + percent-encoded rel targets are rewritten",
          b"Target='new%20file.docx'" in out, out.decode("utf-8", "replace"))

    # F105/F106 covered above; F105 expected digest omits an unreadable payload.
    d = scratch("f105_")
    f = d / "a.txt"
    f.write_text("x")
    os.chmod(f, 0)
    orig = pipe.corpus_files_for_view
    pipe.corpus_files_for_view = lambda ctx, r, vid: [("a.txt", f)]

    class _S:
        state = {}

    try:
        got = pipe.expected_view_digest(_S(), 1, "w1", "seed")
        check("F105 expected_view_digest omits an unreadable payload instead of raising",
              got == [], str(got))
    finally:
        pipe.corpus_files_for_view = orig
        os.chmod(f, 0o644)

    # F107
    text = pipe._rewrite_view_references(
        "Data: ftp://host/data.csv and file:///C:/data.csv",
        "main.md", "f0001.md", {"data.csv": "f0001.csv"})
    check("F107 ftp/file URLs keep their filename in the judge view",
          "ftp://host/data.csv" in text and "file:///C:/data.csv" in text, text)

    # F109
    base = scratch("f109_base_")
    cand = scratch("f109_cand_")
    (base / "fig1.png").write_bytes(b"PNGDATA")
    (cand / "fig1-renamed.png").write_bytes(b"PNGDATA")
    res = pipe.document_set_check([(base, "", ())], [(cand, "", ())])
    check("F109 a renamed non-editable file is not reported as invented",
          res["added_non_editable"] == [], str(res["added_non_editable"]))

    # F110: passing ctx's area list can drop code/.
    root = scratch("f110_")
    (root / "code").mkdir()
    (root / "code" / "foo.py").write_text("x")
    (root / "paper.md").write_text("# Paper\nthe analysis is in code/foo.py\n")
    with_code = pipe.cold_start_obligation_rows(root, area_names=["code"])
    without = pipe.cold_start_obligation_rows(root, area_names=["raw_data"])
    check("F110 the cold-start PKG-2 rows honour submit_code: on",
          any("code/foo.py" in str(r) for r in with_code)
          and not any("code/foo.py" in str(r) for r in without))

    # F111/F112
    check("F111 a commented-out \\caption is not a caption",
          [c for _k, c in pipe._tex_caption_units("% \\caption{Ghost}\n\\caption{Real}")]
          == ["Real"])
    src = scratch("f112_")
    (src / "supp" / "work").mkdir(parents=True)
    (src / "paper.md").write_text("# Abstract\none two three\n# Introduction\nfour five six seven\n")
    (src / "supp" / "work" / "scratch.md").write_text("# Abstract\n" + "word " * 100 + "\n")
    counted = pipe.scan_lengths_in_sources([(src, "", ("work",))])
    check("F112 nested supp/work/ prose is not charged to the word cap",
          "scratch.md" not in str(counted.get("documents") or ""), str(counted.get("documents")))

    # F019: a converted reviewer document keeps its semantic suffix in every
    # skill script, so it is not reclassified as the authors' manuscript.
    f019_ok, f019_bad = True, []
    for fname, fn_name in (
            ("count_words.py", "is_evidence_path"),
            ("enumerate_conventions.py", "_non_manuscript"),
            ("extract_acronyms.py", "is_evidence_name"),
            ("extract_citations.py", "is_non_manuscript"),
            ("extract_numbers.py", "is_non_manuscript"),
            ("extract_occurrences.py", "is_non_manuscript")):
        mod = load("paper_fixbugs_wave1_" + fname.replace(".py", ""), SCRIPTS / fname)
        is_evidence = getattr(mod, fn_name)
        for name in ("paper.review.docx.txt", "paper.comments.md.txt",
                     "paper.notes.pdf.txt"):
            if not is_evidence(name):
                f019_ok = False
                f019_bad.append(f"{fname}:{name}")
        for name in ("paper.docx.txt", "paper.md"):
            if is_evidence(name):
                f019_ok = False
                f019_bad.append(f"{fname}:{name} is not evidence")
    check("F019 (semantic-suffix regex inspected across all six scripts)",
          f019_ok, ", ".join(f019_bad))

    # F020: the skill and the pipeline subtract the same caption span, even
    # when a heading line sits inside the span.
    f020 = scratch("f020_")
    f020_text = ("Funding\n1. Introduction\nCopy-number (CN) burden.\n"
                 "Figure 1. legend text here\n**Methods**\nKeywords\n## Abstract\n")
    (f020 / "ms.md").write_text(f020_text, encoding="utf-8")
    words = load("paper_fixbugs_wave1_words", SCRIPTS / "count_words.py")
    skill_main = [r for r in words.sections(f020_text) if r[0] == "main text"]
    pipe_main = [r for r in pipe.scan_lengths_in_sources([(f020, "", ())])["rows"]
                 if r["section"] == "main text"]
    check("F020 (caption span subtraction inspected against scan_lengths_in_sources)",
          len(skill_main) == 1 and len(pipe_main) == 1
          and skill_main[0][1] == pipe_main[0]["words"] == 3
          and "5 caption word(s) subtracted" in skill_main[0][2]
          and "5 caption word(s) subtracted" in pipe_main[0]["note"],
          f"skill={skill_main} pipeline={pipe_main}")

    # F021: each cap is rendered independently in the summary line.
    f021 = scratch("f021_")
    doc021 = f021 / "p.md"
    doc021.write_text("# Abstract\none two three\n# Introduction\nfour five six\n",
                      encoding="utf-8")

    def _count021(*extra):
        return subprocess.run([sys.executable, str(SCRIPTS / "count_words.py"),
                               str(doc021), *extra],
                              capture_output=True, text=True, timeout=60).stdout

    abstract_only = _count021("--base-abstract", "100")
    both_caps = _count021("--base-abstract", "100", "--base-main-text", "200")
    no_caps = _count021()
    check("F021 (per-cap summary text inspected)",
          "abstract <= 110 words" in abstract_only
          and "no abstract/main-text cap configured" not in abstract_only
          and "abstract <= 110 words" in both_caps
          and "main text <= 250 words" in both_caps
          and "no abstract/main-text cap configured" in no_caps,
          repr((abstract_only[:80], both_caps[:80], no_caps[:80])))

    # F030: PEP 503 normalization makes `python_docx` find `python-docx`.
    etc = load("paper_fixbugs_wave1_env", WS / "scripts" / "env_test_closure.py")
    check("F030 (PEP 503 normalization inspected)",
          etc._norm_dist("python_docx") == etc._norm_dist("python-docx")
          == etc._norm_dist("Python.Docx") == "python-docx"
          and etc._norm_dist("foo_bar.baz") == "foo-bar-baz",
          etc._norm_dist("Python.Docx"))

    # F068: a code/ document is not manuscript prose in either scan.
    f068 = scratch("f068_")
    (f068 / "code").mkdir()
    (f068 / "code" / "notes.md").write_text(
        "# Abstract\none two three\n# Introduction\nfour five six\n"
        "Figure 1. A caption in the analysis notes.\n", encoding="utf-8")
    f068_lengths = pipe.scan_lengths_in_sources([(f068, "", ())])
    f068_captions = pipe.scan_captions_in_sources([(f068, "", ())])
    f068_pref_lengths = pipe.scan_lengths_in_sources([(f068 / "code", "code/", ())])
    check("F068 (code/ skip inspected in both scans)",
          "code/notes.md" not in str(f068_lengths.get("documents") or "")
          and not f068_captions.get("captions")
          and not f068_pref_lengths.get("documents"),
          f"lengths={f068_lengths.get('documents')} "
          f"captions={f068_captions.get('captions')}")

    # F097: the no-section fallback counts the SAME prose as auto mode.
    f097 = scratch("f097_")
    tex097 = f097 / "nopreamble_section.tex"
    tex097.write_text(
        "\\documentclass[11pt]{article}\n\\usepackage[utf8]{inputenc}\n"
        "\\usepackage{graphicx,amsmath,booktabs}\n\\newcommand{\\R}{\\mathbb{R}}\n"
        "\\begin{document}\nPlain prose words here and several more words in the body.\n"
        "\\end{document}\n", encoding="utf-8")

    def _f097(section):
        r = subprocess.run([sys.executable, str(SCRIPTS / "count_words.py"),
                            str(tex097), "--section", section, "--json"],
                           capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout)["rows"][0]["words"]

    f097_main, f097_auto = _f097("main-text"), _f097("auto")
    check("F097 (LaTeX-stripped fallback inspected)",
          f097_main == f097_auto == 12, f"main-text={f097_main} auto={f097_auto}")

    # F100/F017/F018/F016/F065/F072/F075/F063/F064: the remaining fixes are
    # static contracts whose exact wording/guard is the observable.
    p07 = (WS / "paper_pipeline_parts" / "p07_stage_quality_journal.py").read_text("utf-8")
    p04 = (WS / "paper_pipeline_parts" / "p04_utils.py").read_text("utf-8")
    mjs = (WS / "scripts" / "install-codex-mcp.mjs").read_text("utf-8")
    sh = (WS / "install_agent_tooling.sh").read_text("utf-8")
    check("F100 response/redline publication refuses a symlink",
          "refusing to publish {src}: it is a symlink" in p07
          and "refusing to publish tracked-changes entry" in p07)
    check("F017 --only names no Codex server is a hard error",
          "--only names no Codex server" in mjs)
    check("F018 mergePatch splices the block into its old span",
          "Splice the new block into the OLD block's span" in mjs)
    check("F016 the codex MCP state read survives a non-zero codex exit",
          "|| printf 'unreadable\\n')" in sh)
    check("F065 panel completeness tracks duplicate/missing opponent slots",
          "slot_problems" in p08 and "duplicate_comparisons" in p08)
    check("F072 tracking resolves winner_dir with containment",
          "contained_under(ctx.root, wname)" in p14)
    check("F075 severity '-' is used when no census row exists",
          "rank_nonzero" in p08 and "no census exists" in p08)
    check("F063 the paged-rules probe is byte-bounded",
          "read_text_bounded(base)" in p19)
    check("F064 the seeded-ledger comparison is byte-bounded",
          "read_text_bounded(path) == text" in (WS / "paper_pipeline_parts" /
                                                "p05_state_corpus.py").read_text("utf-8"))


def main() -> int:
    try:
        group("docs", test_docs)
        group("docx", test_docx)
        group("pipeline", test_pipeline)
    finally:
        for d in TMP:
            shutil.rmtree(d, ignore_errors=True)
    if FAILS:
        print(f"\n{len(FAILS)} check(s) FAILED")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("\nAll fix-bugs wave-1 checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

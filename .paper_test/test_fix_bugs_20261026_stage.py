#!/usr/bin/env python3
"""Regressions for the confirmed findings of the 2026-10-26 fix-bugs stage.

Hermetic: temp dirs only, no network, no Word. Run:
    python3 .paper_test/test_fix_bugs_20261026_stage.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []
TMPDIRS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def mini_docx(path: Path, body: str, styles: str = "") -> Path:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = (f'<w:document xmlns:w="{ns}"><w:body>{body}<w:sectPr/></w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml", xml)
        if styles:
            z.writestr("word/styles.xml",
                       f'<w:styles xmlns:w="{ns}">{styles}</w:styles>')
    return path


def p(text: str, ppr: str = "") -> str:
    props = f"<w:pPr>{ppr}</w:pPr>" if ppr else ""
    return (f'<w:p>{props}<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>')


pp = load("stage_pp", WS / "paper_pipeline.py")
fmt = load("stage_fmt", WS / "paper_docx_format.py")
qa = load("stage_qa", WS / "paper_qwen_agent.py")
cc = load("stage_cc", WS / "paper-skills/paper-review/scripts/convert_corpus.py")
cw = load("stage_cw", WS / "paper-skills/paper-review/scripts/count_words.py")
eo = load("stage_eo", WS / "paper-skills/paper-review/scripts/extract_occurrences.py")
rt = load("stage_rt", WS / "paper-skills/paper-revise/scripts/revision_token.py")


# ---------------------------------------------------------------- F-001
def test_f001_tex_paragraphs():
    print("\n== F-001: .tex paragraphs survive the strip ==")
    d = scratch("f001_")
    tex = d / "a.tex"
    tex.write_text("First paragraph with tumor.\n\nSecond paragraph with colour.\n\n"
                   "Third paragraph.\n\nFourth paragraph.\n")
    got = pp.text_source_paragraphs(tex)
    check("a four-paragraph .tex yields four paragraphs", len(got) == 4, repr(got))


# ---------------------------------------------------------------- F-002
def test_f002_missing_marker():
    print("\n== F-002: PROMPT.md is not a missing deliverable ==")
    d = scratch("f002_")
    sb = d / "sandbox"
    sb.mkdir()
    (sb / "PROMPT.md").write_text("prompt")

    class Ctx:
        def sandbox_of(self, rec):
            return sb

    msg = ("completion marker _pipeline_done.json missing (it is prompted as the very last "
           "step; a non-empty output directory is NOT completion) -- write "
           "`_pipeline_done.json` in the sandbox ROOT, next to PROMPT.md")
    got = pp.repair_missing_deliverable(Ctx(), {"kind": "guided_review"}, [msg])
    check("an absent marker is still reported when PROMPT.md exists",
          got == "_pipeline_done.json", repr(got))


# ---------------------------------------------------------------- F-003
def test_f003_judge_selection():
    print("\n== F-003: a plain run drops a remembered judge selection ==")
    old = pp.round_judges
    pp.round_judges = lambda ctx, r: 4
    try:
        rec = {"judges_enabled": ["w1_j1"]}
        pp._apply_judge_selection(rec, None, True, 1, SimpleNamespace())
        check("plain run pops judges_enabled", "judges_enabled" not in rec, repr(rec))

        class Only:
            def judge_spec_for(self, r):
                return ["w2_j1"]

        rec = {}
        pp._apply_judge_selection(rec, Only(), False, 1, SimpleNamespace())
        check("--only judge session records the selection",
              rec.get("judges_enabled") == ["w2_j1"], repr(rec))
    finally:
        pp.round_judges = old


# ---------------------------------------------------------------- F-005
def test_f005_reference_list_t8():
    print("\n== F-005: T8d/T8e skip the numbered reference list ==")
    d = scratch("f005_")
    pkg = mini_docx(d / "ref.docx",
                    p("We used tumor and color.")
                    + p("References", '<w:pStyle w:val="Heading1"/>')
                    + p("1. A tumour atlas of colour pathways."))
    rep = fmt.analyse_package(pkg, fmt.load_policy(None))
    rows = [r for r in rep["rows"] if r["rule"] in ("FMT-T8d", "FMT-T8e")]
    check("the reference title does not create a T8d/T8e row", rows == [], str(rows))
    res = fmt.fix_package(pkg, d / "ref.out.docx", fmt.load_policy(None))
    check("the fixer accepts its own reference-list output", res.get("ok") is True,
          str(res.get("error") or res.get("verified")))


# ---------------------------------------------------------------- F-006
def test_f006_unreadable_plain_copy():
    print("\n== F-006: an unreadable text source is recorded, not raised ==")
    with mock.patch("builtins.open", side_effect=PermissionError("denied")):
        text, notes = cc.plain_copy("/nope.md")
    check("plain_copy returns an unreadable note", text == "" and notes
          and "unreadable" in notes[0], repr(notes))


# ---------------------------------------------------------------- F-007
def test_f007_revision_token_parity():
    print("\n== F-007: the shipped token script matches its pipeline twin ==")
    d = scratch("f007_")
    (d / "supp" / "work").mkdir(parents=True)
    (d / "supp" / "work" / "render.png").write_text("x")
    (d / "paper.txt").write_text("paper")
    check("nested work/ is scratch", not rt.is_payload(d / "supp" / "work" / "render.png", d))
    os.symlink(d / "paper.txt", d / "link.txt")
    names = [x.name for x in rt.tree_files(d)]
    check("a file symlink is not package content", "link.txt" not in names, repr(names))


# ---------------------------------------------------------------- F-013
def test_f013_page_plural():
    print("\n== F-013: '12-page' satisfies the template page count ==")
    d = scratch("f013_")
    sb = d / "sandbox"
    (sb / "visual_template").mkdir(parents=True)
    (sb / "visual_template" / "manifest.json").write_text(json.dumps({
        "renderer": "word",
        "documents": [{"source": "Article_template.docx", "pages": 12, "ok": True}]}))
    art = d / "VISUAL_CHECK.md"
    art.write_text("Compared article_template.docx at its 12-page render; template section.")
    errs, warns = [], []
    pp.check_visual_artifact(art, "VISUAL", errs, warns, render_roots=[], sandbox=sb)
    check("a natural plural page count is accepted", errs == [], repr(errs))


# ---------------------------------------------------------------- F-015
def test_f015_invalidate_judges():
    print("\n== F-015: invalidate_from_round resets judges_enabled ==")
    d = scratch("f015_")
    rec = {"status": "done", "judges_enabled": ["w1_j1"], "winner_dir": "winner1",
           "completed": True}

    class Ctx:
        root = d
        reports_dir = d / "reports"
        state = {}

        def rounds_count(self):
            return 1

        def round_rec(self, r):
            return rec

        def runs(self, **kw):
            return []

        def log(self, *a, **k):
            pass

        def save_state(self):
            pass

    Ctx.reports_dir.mkdir()
    pp.invalidate_from_round(Ctx(), 1, "test")
    check("the remembered judge panel is dropped", "judges_enabled" not in rec, repr(rec))


# ---------------------------------------------------------------- F-016
def test_f016_strict_journal():
    print("\n== F-016: set-journal --strict-venue refuses a mismatch ==")
    d = scratch("f016_")

    class Profile:
        id = "nat"
        journal_matches = staticmethod(lambda name: False)

        @staticmethod
        def known_journals():
            return ["Nature Biotechnology"]

    class Ctx:
        def __init__(self, *a, **k):
            self.root = d
            self.state = {"runs": []}
            self.cfg = {}
            self.cfg_path = d / "pipeline_config.json"
            self.reports_dir = d / "reports"
            self.reports_dir.mkdir(exist_ok=True)

        def load(self):
            pass

        @contextlib.contextmanager
        def lock(self, name):
            yield

        def log(self, *a, **k):
            pass

        def save_state(self):
            pass

    args = SimpleNamespace(journal="Other Journal", show=False, strict_venue=True,
                           force=True, root=d, json=False)
    old = (pp.Ctx, pp._venue_command_root, pp.begin_run_log, pp._validate_journal_name,
           pp.venue_profile_of, pp.venue_id_of)
    pp.Ctx = Ctx
    pp._venue_command_root = lambda args, cmd: d
    pp.begin_run_log = lambda *a, **k: None
    pp._validate_journal_name = lambda name: name
    pp.venue_profile_of = lambda ctx, required=False: Profile()
    pp.venue_id_of = lambda ctx: "nat"
    try:
        try:
            pp.cmd_set_journal(args)
            refused = False
        except SystemExit:
            refused = True
        check("the mismatch is an error, not a warning", refused)
        check("the rejected journal was not written",
              not (d / "pipeline_config.json").exists())
    finally:
        (pp.Ctx, pp._venue_command_root, pp.begin_run_log, pp._validate_journal_name,
         pp.venue_profile_of, pp.venue_id_of) = old


# ---------------------------------------------------------------- F-017
def test_f017_ai_nonuse_scope():
    print("\n== F-017: a blanket 'prepared without AI' denial is not scoped ==")
    blanket = ("This manuscript was prepared without generative AI.\n\n"
               "In the revision stage we used ChatGPT to refine the text.")
    rows = pp.ai_disclosure_contradiction_rows([("m.txt", blanket)])
    check("the blanket denial contradicts the disclosed use", len(rows) == 1, str(rows))
    scoped = ("The initial draft was prepared without generative AI.\n\n"
              "In the revision stage we used ChatGPT to refine the text.")
    rows2 = pp.ai_disclosure_contradiction_rows([("m.txt", scoped)])
    check("an artifact-scoped denial stays quiet", rows2 == [], str(rows2))


# ---------------------------------------------------------------- F-021
def test_f021_section_break_paragraph():
    print("\n== F-021: a section-break paragraph is never deleted ==")
    d = scratch("f021_")
    sect = ('<w:p><w:pPr><w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'
            '</w:pPr><w:r><w:br w:type="page"/></w:r></w:p>')
    pkg = mini_docx(d / "sect.docx", sect + p("After"))
    # Exercise the document fixer directly: a rejected package is no longer
    # written to --out (F41), and this fixture's FMT-S1 row keeps the package
    # unverified while the structural property under test is still checkable.
    with zipfile.ZipFile(pkg) as z:
        before = z.read("word/document.xml").decode()
    xml, _changes, _meta = fmt.fix_document(before, {}, fmt.load_policy(None))
    check("the mid-document section survives",
          xml.count("<w:sectPr") == 2 and "pgSz" in xml, xml[:400])


# ---------------------------------------------------------------- F-024
def test_f024_bad_cover_limit():
    print("\n== F-024: a non-numeric cover-letter limit is a clean row ==")
    d = scratch("f024_")
    prof = d / "prof.json"
    prof.write_text(json.dumps({
        "id": "test", "default_article_type": "article",
        "article_types": [{"id": "article", "label": "Article", "length_limits": {
            "abstract": {"base": 150, "relaxation": 10},
            "main_text": {"base": 1000, "relaxation": 100},
            "cover_letter": {"min": "abc", "max": 500}}}]}))
    letter = d / "letter.txt"
    letter.write_text("Dear Editor,\nWe submit this work.\nSincerely,\nA\n")
    proc = subprocess.run(
        [sys.executable, str(WS / "paper-skills/paper-review/scripts/count_words.py"),
         str(letter), "--venue-profile", str(prof), "--section", "cover-letter"],
        cwd=str(WS), text=True, capture_output=True)
    check("the malformed profile does not traceback",
          proc.returncode == 0 and "Traceback" not in proc.stderr,
          f"rc={proc.returncode} err={proc.stderr[-200:]!r}")
    check("the malformed limit is reported as no cap",
          "non-numeric" in proc.stderr, proc.stderr[-200:])


# ---------------------------------------------------------------- F-026
def test_f026_mixed_case_profile():
    print("\n== F-026: a mixed-case profile filename resolves ==")
    import shutil
    d = scratch("f026_")
    (d / "venue_profiles").mkdir()
    shutil.copy(WS / "venue_profiles/generic.json", d / "venue_profiles/Generic.json")
    prof = pp.load_venue_profile("generic", d)
    check("the listed id resolves to the mixed-case file", prof.id == "generic", prof.id)


# ---------------------------------------------------------------- F-054/F-106
def test_f054_even_odd_sections():
    print("\n== F-054/106: every section is inspected, in any attribute order ==")
    d = scratch("f054_")
    sect1 = ('<w:p><w:pPr><w:sectPr><w:headerReference w:id="rId1" w:type="even"/>'
             '</w:sectPr></w:pPr></w:p>')
    sect2 = '<w:p><w:pPr><w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:pPr></w:p>'
    pkg = mini_docx(d / "t.docx", sect1 + sect2 + p("Body"))
    check("an even header in the FIRST section is found",
          fmt._template_uses_even_odd(pkg) is True)


# ---------------------------------------------------------------- F-133/161/162/175-178
def test_name_gates():
    print("\n== F-133/161/162/175-178: the six review name gates agree ==")
    strict = []
    for name in ("extract_numbers", "extract_citations", "extract_occurrences",
                 "enumerate_conventions"):
        mod = load("gate_" + name, WS / f"paper-skills/paper-review/scripts/{name}.py")
        strict.append(getattr(mod, "is_non_manuscript", None)
                      or getattr(mod, "_non_manuscript"))
    wide = [
        load("gate_acr", WS / "paper-skills/paper-review/scripts/extract_acronyms.py")
        .is_evidence_name,
        cw.is_evidence_path,
    ]
    # convert_corpus is a role guesser, not a name gate; test its regexes directly.
    cases = {
        "base_editor.docx.txt": False,
        "prime_editor.txt": False,
        "genome_editor_assay.txt": False,
        "referees.docx.txt": True,
        # bare "editors" carries no document role, so it is the authors' file
        # (the pipeline rule); the four copies must agree on that too.
        "editors.docx": False,
        "decision_email.docx.txt": True,
        "ReviewersComments.docx.txt": True,
        "reviewercomments.docx.txt": True,
        "RefereeReport.docx.txt": True,
        "feedbackreportform.txt": True,
        "letters_to_the_editor.docx": False,
        "letter.to.the.editor.docx": False,
        "editorial_board.docx": False,
        "the_editorial.docx": False,
        "letter_to_the_editor.final.docx.txt": False,
        "letter_to_the_editor.tar.gz.txt": False,
        "letter_to_editor.docx": False,
        "letter_to_the_editor.reply.txt": True,
        "editorial.review.txt": True,
        "editorial.notes.txt": True,
        "biofeedback_results.txt": False,
        "immune_response.md": False,
        "dose_response.txt": False,
    }
    for name, want in cases.items():
        got = [fn(name) for fn in strict]
        check(f"four strict sweeps agree on {name!r}", all(g == want for g in got),
              f"want={want} got={got}")
        got_wide = [fn(name) for fn in wide]
        check(f"acronyms/count_words agree on {name!r}", all(g == want for g in got_wide),
              f"want={want} got={got_wide}")
    check("convert_corpus does not label biofeedback as feedback",
          not cc.FEEDBACK_NAME_RE.search("biofeedback_traces.csv"))
    check("convert_corpus does not label dose_response as a reply",
          not cc.REPLY_NAME_RE.search("dose_response.docx"))
    check("convert_corpus does not treat photocoverage as a cover letter",
          not cc.COVER_LETTER_ROLE_RE.search("photocoverage.docx"))


# ---------------------------------------------------------------- F-078
def test_f078_atx_headings():
    print("\n== F-078: Markdown ATX headings are headings ==")
    text = ("## Abstract\nWe studied this.\n\n## Methods\nWe did things here.\n\n"
            "## Results\nMore text follows.\n")
    rows = cw.sections(text)
    kinds = [r[0] for r in rows]
    check("## Abstract is not one 'whole file' row", "whole file" not in kinds, repr(rows))
    check("the abstract is counted", "abstract" in kinds, repr(rows))


# ---------------------------------------------------------------- F-079
def test_f079_spacing_direct_child():
    print("\n== F-079: caption spacing is a pPr child, never rPr ==")
    d = scratch("f079_")
    body = ('<w:p><w:pPr><w:rPr><w:spacing w:val="20"/></w:rPr></w:pPr>'
            '<w:r><w:t>Figure 1. A caption here.</w:t></w:r></w:p>')
    pkg = mini_docx(d / "cap.docx", body)
    res = fmt.fix_package(pkg, d / "cap.out.docx", fmt.load_policy(None))
    check("the fixer succeeds", res.get("ok") is True, str(res.get("error")))
    with zipfile.ZipFile(d / "cap.out.docx") as z:
        xml = z.read("word/document.xml").decode()
    ppr = xml[xml.find("<w:pPr>"):xml.find("</w:pPr>") + 8]
    check("the paragraph spacing is a direct pPr child",
          ppr.find("<w:spacing w:before=") != -1
          and ppr.find("<w:spacing w:before=") < ppr.find("<w:rPr>"), ppr)
    check("the character spacing inside rPr is preserved",
          "<w:rPr><w:spacing w:val=\"20\"/></w:rPr>" in ppr, ppr)


# ---------------------------------------------------------------- F-084
def test_f084_name_defined():
    print("\n== F-084: the format-fix warning path has its name ==")
    d = scratch("f084_")
    pkg = mini_docx(d / "head.docx",
                    p("Results", '<w:pStyle w:val="Heading1"/>') + p("Body text."))
    warns = []
    res = pp.normalize_formatting_in_dir(pkg.parent, fmt.load_policy(None), "test",
                                         warns=warns, artifacts_dir=None)
    check("the summary is written without a NameError", isinstance(res, dict), repr(res))
    check("the caller-facing warning still fires", bool(warns), repr(warns))


# ---------------------------------------------------------------- F-085
def test_f085_error_cache():
    print("\n== F-085: a failed lookup is not cached as a fact ==")
    d = scratch("f085_")
    (d / "reports").mkdir()
    entry = {"verdict": "error", "hits": [], "errors": ["boom"], "checked_at": pp.utcnow()}
    pp.write_json_atomic(d / "reports" / "placeholder_lookup_cache.json", {"doi|x": entry})

    class Ctx:
        root = d

    class Mod:
        calls = 0

        @staticmethod
        def lookup_kind(kind, query, timeout=None):
            Mod.calls += 1
            return {"verdict": "found", "hits": ["ok"], "errors": [],
                    "checked_at": pp.utcnow()}

    old = (pp._format_module, pp.placeholder_lookup_of, pp.lookup_network_available)
    pp._format_module = lambda: Mod
    pp.placeholder_lookup_of = lambda ctx: "online"
    pp.lookup_network_available = lambda timeout=None: True
    try:
        rows = pp._lookup_batch(Ctx(), [{"kind": "doi", "query": "x"}], "test")
    finally:
        (pp._format_module, pp.placeholder_lookup_of, pp.lookup_network_available) = old
    check("a cached error is retried", Mod.calls == 1 and rows[0]["verdict"] == "found",
          f"calls={Mod.calls} rows={rows}")


# ---------------------------------------------------------------- F-093
def test_f093_dangling_symlink():
    print("\n== F-093: a dangling symlink is not contained ==")
    import shutil
    if not shutil.which("node"):
        check("node unavailable: containment check skipped", True)
        return
    script = """
import { containsPath, allowedRoots } from './mcp-docx-compare/containment.mjs';
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
const d = mkdtempSync(path.join(tmpdir(), 'cont-'));
const root = path.join(d, 'root');
mkdirSync(root);
const outside = path.join(d, 'outside.txt');
writeFileSync(outside, 'x');
symlinkSync(outside, path.join(root, 'dangling'));
process.stdout.write(containsPath(path.join(root, 'dangling'), allowedRoots(root)) ? '1' : '0');
"""
    proc = subprocess.run([shutil.which("node"), "--input-type=module", "-e", script],
                          cwd=str(WS), text=True, capture_output=True)
    check("a dangling link inside the root is refused",
          proc.returncode == 0 and proc.stdout.strip() == "0",
          f"rc={proc.returncode} out={proc.stdout!r} err={proc.stderr[-200:]!r}")


# ---------------------------------------------------------------- F-098
def test_f098_docx_render_once():
    print("\n== F-098: each DOCX is rendered once per set ==")
    d = scratch("f098_")
    src1, src2 = d / "s1", d / "s2"
    src1.mkdir()
    src2.mkdir()
    mini_docx(src1 / "one.docx", p("Body one."))
    mini_docx(src2 / "two.docx", p("Body two."))
    calls = []

    def fake_convert(docx, out_dir):
        calls.append(Path(docx).name)
        return {"ok": True, "tool": "fake", "pages": 1}

    old = pp.convert_docx_to_pdf_persistent
    pp.convert_docx_to_pdf_persistent = fake_convert
    try:
        ctx = SimpleNamespace(root=d / "root")
        ctx.root.mkdir()
        pp.render_pdf_set(ctx, "test", [(src1, "", ()), (src2, "", ())],
                          ctx.root / "out", previous={})
    finally:
        pp.convert_docx_to_pdf_persistent = old
    check("two documents are rendered exactly twice", sorted(calls) == ["one.docx", "two.docx"],
          repr(calls))


# ---------------------------------------------------------------- F-104
def test_f104_zero_timeout():
    print("\n== F-104: --timeout 0 stays 'no timeout' ==")
    check("0 is preserved", pp._timeout_seconds(SimpleNamespace(timeout=0), 14400) == 0)
    check("None takes the default",
          pp._timeout_seconds(SimpleNamespace(timeout=None), 14400) == 14400)
    check("a positive value is kept",
          pp._timeout_seconds(SimpleNamespace(timeout=60), 14400) == 60)


# ---------------------------------------------------------------- F-153
def test_f153_foreign_guard():
    print("\n== F-153: set-champion-select passes the foreign-pipeline guard ==")
    check("the command is guarded", "set-champion-select" in pp.FOREIGN_GUARD_COMMANDS)


# ---------------------------------------------------------------- F-157/158/159
def test_f157_section_headings():
    print("\n== F-157/158/159: the remaining section headings are classified ==")
    cases = {
        "Materials & Methods": "methods",
        "Literature Cited": "references",
        "Works Cited": "references",
        "Conflicts of Interest": "competing-interests",
        "Code availability": "data-availability",
    }
    for heading, kind in cases.items():
        check(f"pipeline classifies {heading!r}",
              pp._length_section_kind(heading) == kind,
              pp._length_section_kind(heading))
        check(f"the skill counter classifies {heading!r}",
              cw.section_kind(heading) == kind, cw.section_kind(heading))


# ---------------------------------------------------------------- F-160
def test_f160_numbered_keywords():
    print("\n== F-160: a numbered Keywords heading does not reopen a section ==")
    text = ("## Abstract\nA one two.\n\n## Methods\nM one two.\n\n"
            "1. Keywords\nkw one two\n\n## Results\nR one two.\n")
    rows = cw.sections(text)
    check("the abstract stops at ## Methods", rows[0][0] == "abstract" and rows[0][1] == 3,
          repr(rows))
    check("Methods and Keywords stay out of the main text",
          rows[1][0] == "main text" and rows[1][1] == 3, repr(rows))


# ---------------------------------------------------------------- F-186
def test_f186_leading_whitespace():
    print("\n== F-186: redline offsets include leading whitespace ==")
    from xml.etree import ElementTree as ET

    def para(text):
        return ET.fromstring(
            '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>')

    def flatten(el, accept):
        out = []
        for ch in el:
            tag = ch.tag.split("}")[-1]
            if tag == "t":
                out.append(ch.text or "")
            elif tag == "delText":
                if not accept:
                    out.append(ch.text or "")
            elif tag == "ins":
                if accept:
                    out.append(flatten(ch, accept))
            elif tag == "del":
                if not accept:
                    out.append(flatten(ch, accept))
            else:
                out.append(flatten(ch, accept))
        return "".join(out)

    got = pp._replace_para(para("  Hello world"), para("  Hello there"), [0], "2026")
    check("accepting reproduces the revised paragraph",
          flatten(got, True) == "  Hello there", repr(flatten(got, True)))
    check("rejecting reproduces the base paragraph",
          flatten(got, False) == "  Hello world", repr(flatten(got, False)))


# ---------------------------------------------------------------- F-187
def test_f187_inline_table_position():
    print("\n== F-187: a logging fallback keeps an inline table in place ==")
    d = scratch("f187_")
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def doc(body):
        return f'<w:document xmlns:w="{ns}"><w:body>{body}<w:sectPr/></w:body></w:document>'

    def table(text):
        return f'<w:tbl><w:tr><w:tc>{p(text)}</w:tc></w:tr></w:tbl>'

    def write(path, body):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("[Content_Types].xml",
                       '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                       'package/2006/content-types"/>')
            z.writestr("word/document.xml", doc(body))

    base, cand, out = d / "b.docx", d / "c.docx", d / "o.docx"
    write(base, p("One") + table("Cell") + p("Two"))
    write(cand, p("One") + table("Cell") + p("Two changed"))
    pp.write_docx_logging_fallback(base, cand, out, "base", "test")
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode()
    check("the table stays between its neighbouring paragraphs",
          xml.find("One") < xml.find("<w:tbl") < xml.find("Two"), xml[:600])


# ---------------------------------------------------------------- F-188
def test_f188_nested_evidence_symlink():
    print("\n== F-188: a nested evidence symlink does not escape the area ==")
    d = scratch("f188_")
    base = d / "pkg"
    area = base / "raw_data"
    outside = d / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside")
    area.mkdir(parents=True)
    (area / "real.csv").write_text("a,b")
    os.symlink(outside, area / "sub")
    entries = pp._entries_in(area, base)
    check("only the real file is enumerated",
          set(entries) == {"raw_data/real.csv"}, repr(entries))
    fb = pp.feedback_area_entries(base, "raw_data")
    check("the feedback-area walk has the same guard",
          set(fb) == {"raw_data/real.csv"}, repr(fb))


# ---------------------------------------------------------------- F-189
def test_f189_cold_start_script_containment():
    print("\n== F-189: a replaced cold_start_review directory cannot execute outside ==")
    d = scratch("f189_")
    sb = d / "sb"
    sb.mkdir()
    outside = d / "outside"
    (outside / "scripts").mkdir(parents=True)
    (outside / "scripts" / "evil.py").write_text("print('REPRODUCED')\n")
    os.symlink(outside, sb / "cold_start_review")
    out = pp.cold_start_reproduction(sb, [{"id": "X-901", "verifier": {
        "script": "cold_start_review/scripts/evil.py", "computed": "REPRODUCED"}}])
    check("the outside script is not executed",
          out["results"][0]["status"] == "missing" and out["reproduced"] == 0,
          repr(out))
    sb2 = d / "sb2"
    (sb2 / "cold_start_review").mkdir(parents=True)
    os.symlink(outside, sb2 / "cold_start_review" / "scripts")
    out2 = pp.cold_start_reproduction(sb2, [{"id": "X-902", "verifier": {
        "script": "cold_start_review/scripts/evil.py", "computed": "REPRODUCED"}}])
    check("a replaced scripts directory is refused",
          out2["results"][0]["status"] == "missing" and out2["reproduced"] == 0,
          repr(out2))


# ---------------------------------------------------------------- F-067
def test_f067_empty_value():
    print("\n== F-067: an empty --value is refused ==")
    d = scratch("f067_")
    (d / "corpus").mkdir()
    old = sys.argv
    sys.argv = ["extract_occurrences.py", "--work", str(d), "--value", ""]
    try:
        try:
            eo.main()
            refused = False
        except SystemExit as exc:
            refused = (exc.code == 2)
        check("an empty value exits 2 instead of matching every position", refused)
    finally:
        sys.argv = old


# ---------------------------------------------------------------- F-203
def test_f203_qwen_content():
    print("\n== F-203: a null/list chat content is not the answer 'None' ==")
    cfg = {"model": "m", "max_tokens": 1, "base_url": "http://x", "api_key": "k"}
    old = qa._request
    try:
        qa._request = lambda *a, **k: (200, {"choices": [{"message": {"content": None}}]}, "")
        text, err = qa.chat_text(cfg, "hi")
        check("null content is an error", text == "" and "empty" in err, repr((text, err)))
        qa._request = lambda *a, **k: (200, {"choices": [{"message": {
            "content": [{"type": "text", "text": "Hello"}, {"type": "text", "text": "!"}]}}]}, "")
        text, err = qa.chat_text(cfg, "hi")
        check("content parts are joined", (text, err) == ("Hello!", ""), repr((text, err)))

    finally:
        qa._request = old


# ---------------------------------------------------------------- F-205
def test_f205_italic_double_splice():
    print("\n== F-205: an italic journal run is edited once ==")
    d = scratch("f205_")
    italic = ('<w:p><w:r><w:rPr><w:i/></w:rPr>'
              '<w:t>Nature Methods and other leading journals</w:t></w:r></w:p>')
    pkg = mini_docx(d / "ital.docx", p("We used color.") + italic)
    res = fmt.fix_package(pkg, d / "ital.out.docx", fmt.load_policy(None))
    check("the fixer accepts the document", res.get("ok") is True, str(res.get("error")))
    with zipfile.ZipFile(d / "ital.out.docx") as z:
        xml = z.read("word/document.xml").decode()
    from xml.etree import ElementTree as ET
    try:
        ET.fromstring(xml)
        parsed = True
    except ET.ParseError:
        parsed = False
    check("the output remains well-formed XML", parsed)


# ---------------------------------------------------------------- F-206
def test_f206_doubled_word_case():
    print("\n== F-206: case-insensitive doubled words are not deleted ==")
    check("'a A-to-I' is not a doubled word",
          not fmt._DOUBLED_WORD_RE.search("a A-to-I editing rate"))
    check("'NOR or OR' is not a doubled word",
          not fmt._DOUBLED_WORD_RE.search("a NOR or OR gate"))
    check("a real doubled word still matches",
          bool(fmt._DOUBLED_WORD_RE.search("the the result")))
    check("a sentence-initial 'The the' still matches",
          bool(fmt._DOUBLED_WORD_RE.search("The the result")))


# ---------------------------------------------------------------- F-210
def test_f210_keepnext_order():
    print("\n== F-210: keepNext precedes one keepLines ==")
    d = scratch("f210_")
    head = ('<w:p><w:pPr><w:pStyle w:val="Heading1"/><w:keepLines/></w:pPr>'
            '<w:r><w:t>Results</w:t></w:r></w:p>')
    pkg = mini_docx(d / "head.docx", head + p("Body text."))
    res = fmt.fix_package(pkg, d / "head.out.docx", fmt.load_policy(None))
    check("the fixer succeeds", res.get("ok") is True, str(res.get("error")))
    with zipfile.ZipFile(d / "head.out.docx") as z:
        xml = z.read("word/document.xml").decode()
    ppr = xml[xml.find("<w:pPr>"):xml.find("</w:pPr>") + 8]
    check("keepLines is not duplicated", ppr.count("<w:keepLines") == 1, ppr)
    check("keepNext precedes keepLines", ppr.find("<w:keepNext") < ppr.find("<w:keepLines"), ppr)


def cleanup():
    for d in TMPDIRS:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    for fn in (test_f001_tex_paragraphs, test_f002_missing_marker,
               test_f003_judge_selection, test_f005_reference_list_t8,
               test_f006_unreadable_plain_copy, test_f007_revision_token_parity,
               test_f013_page_plural, test_f015_invalidate_judges,
               test_f016_strict_journal, test_f017_ai_nonuse_scope,
               test_f021_section_break_paragraph,
               test_f024_bad_cover_limit, test_f026_mixed_case_profile,
               test_f054_even_odd_sections, test_name_gates, test_f078_atx_headings, test_f079_spacing_direct_child,
               test_f084_name_defined, test_f085_error_cache,
               test_f093_dangling_symlink,
               test_f098_docx_render_once,
               test_f104_zero_timeout,
               test_f153_foreign_guard, test_f157_section_headings,
               test_f160_numbered_keywords, test_f186_leading_whitespace,
               test_f187_inline_table_position, test_f188_nested_evidence_symlink, test_f189_cold_start_script_containment,
               test_f067_empty_value,
               test_f203_qwen_content, test_f205_italic_double_splice,
               test_f206_doubled_word_case, test_f210_keepnext_order):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append(fn.__name__)
    cleanup()
    print(f"\n{'FAILED' if FAILS else 'PASSED'}: {len(FAILS)} failure(s)")
    sys.exit(1 if FAILS else 0)

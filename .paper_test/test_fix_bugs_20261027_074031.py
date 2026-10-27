#!/usr/bin/env python3
"""Regression checks for the 2026-10-27 03_fix_bugs wave (run 074031).

Each check pins a confirmed finding from
debug_runs/20261027-074031/02_verify_findings/verified_findings.
Hermetic: temp dirs only, no network, no Word.

Run:  python3 .paper_test/test_fix_bugs_20261027_074031.py
"""
from __future__ import annotations

import contextlib
import csv
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
from types import SimpleNamespace
from unittest import mock

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs1027b_pp", "paper_pipeline.py")
pf = load("fixbugs1027b_pf", "paper_docx_format.py")
cw = load("fixbugs1027b_cw", "paper-skills/paper-review/scripts/count_words.py")

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


def mini_docx(path: Path, body: str, styles: str = "") -> Path:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{ns}"><w:body>{body}<w:sectPr/></w:body></w:document>')
        if styles:
            z.writestr("word/styles.xml", f'<w:styles xmlns:w="{ns}">{styles}</w:styles>')
    return path


# ---------------------------------------------------------------- F01
def test_f01_floor_zero_empty_prefix():
    print()
    print("== F01: --tiebreak-defect-floor 0 uses the empty prefix ==")
    check("floor 0 stops at the empty prefix (no census cell leads)",
          pp.tiebreak_prefix_cells({"v": [0, 5]}, ["v"], 0) == 0,
          pp.tiebreak_prefix_cells({"v": [0, 5]}, ["v"], 0))
    check("floor 1 still needs the first cell",
          pp.tiebreak_prefix_cells({"v": [1, 5]}, ["v"], 1) == 1)
    key_a = pp.champion_sort_key({"defect_prefix_census": (),
                                  "median": 2.0, "mean": 2.0, "iqr": 0.0, "digest": "a"})
    key_b = pp.champion_sort_key({"defect_prefix_census": (),
                                  "median": 1.0, "mean": 1.0, "iqr": 0.0, "digest": "b"})
    check("floor 0 makes the median decide (higher median wins the sort key)",
          key_a < key_b, f"{key_a} vs {key_b}")


# ---------------------------------------------------------------- F02
def test_f02_ranking_text():
    print()
    print("== F02: the ranking description matches the per-cell census key ==")
    model = pp.score_model_doc()
    blob = " ".join(str(model.get(k) or "") for k in
                    ("ranking", "tiebreaks", "tiebreak_notes"))
    check("the score model no longer says a per-cell count is not a rung",
          "never a rung of its own" not in blob)
    check("the score model describes the ordered census at the prefix",
          "per-cell" in blob or "census" in blob, blob[:200])


# ---------------------------------------------------------------- F09
class _FakeCtx:
    def __init__(self, root, **kw):
        self.root = Path(root)
        self.cfg_path = self.root / "pipeline_config.json"
        self.cfg = {
            "rounds": 3, "rewrites": [2, 0, 0], "revises": [1, 1, 1],
            "integrators": [3, 3, 3], "review_scope": ["formatting-writing"],
            "champion_select": "integrate", "audit": "on",
            "revision_audit": "on", "probe_review": "on",
        }
        self.state = {"runs": {}}
        self.pristine = self.root / "pristine"
        self.pristine.mkdir()
        self.locked = []

    def load(self, need_cfg=True):
        pass

    @contextlib.contextmanager
    def lock(self, what):
        self.locked.append(what)
        yield

    def log(self, *a, **k):
        pass

    def save_state(self):
        pass


def test_f09_scoped_mode_restore():
    print()
    print("== F09: leaving a scoped mode restores champion_select/review_scope ==")
    tmp = scratch("f09_")
    (tmp / "pipeline_config.json").write_text("{}", encoding="utf-8")
    (tmp / "state.json").write_text(json.dumps(
        {"version": pp.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": []}),
        encoding="utf-8")
    fake = _FakeCtx(tmp)
    old_ctx, old_mode = pp.Ctx, pp.journal_mode_of
    pp.Ctx = lambda *a, **k: fake
    pp.journal_mode_of = lambda ctx: str(ctx.cfg.get("revision_mode") or "continue")
    try:
        dd = SimpleNamespace(root=str(tmp), mode="major", show=False, force=True,
                             journal_feedback=None, journal_feedback_from=None,
                             strict_venue=False)
        pp.cmd_set_revision_mode(dd)
        check("entering major forces champion_select=revise",
              fake.cfg.get("champion_select") == "revise", fake.cfg.get("champion_select"))
        back = SimpleNamespace(root=str(tmp), mode="continue", show=False, force=True,
                               journal_feedback=None, journal_feedback_from=None,
                               strict_venue=False)
        pp.cmd_set_revision_mode(back)
        check("leaving major restores champion_select=integrate",
              fake.cfg.get("champion_select") == "integrate",
              fake.cfg.get("champion_select"))
        check("leaving major restores the operator's review_scope",
              fake.cfg.get("review_scope") == ["formatting-writing"],
              fake.cfg.get("review_scope"))
    finally:
        pp.Ctx, pp.journal_mode_of = old_ctx, old_mode


# ---------------------------------------------------------------- F10
def test_f10_copy_asset_dirs_atomic():
    print()
    print("== F10: copy_asset_dirs keeps the old bundle on a failed replace ==")
    tmp = scratch("f10_")
    src, dst = tmp / "src", tmp / "dst"
    (src / "parts").mkdir(parents=True)
    (src / "parts" / "new.py").write_text("new\n", encoding="utf-8")
    (dst / "parts").mkdir(parents=True)
    (dst / "parts" / "old.py").write_text("old\n", encoding="utf-8")
    real_replace = os.replace

    def boom(a, b):
        # Fail the final rename into place, but allow the rollback from the
        # aside-moved old tree (a real failure would not spare that name).
        if str(b).endswith("parts") and "copy-old" not in str(a):
            raise OSError("simulated ENOSPC")
        return real_replace(a, b)

    with mock.patch("os.replace", side_effect=boom):
        try:
            pp.copy_asset_dirs(src, dst, names=("parts",))
        except OSError:
            pass
    check("the old parts tree survives a failed replacement",
          (dst / "parts" / "old.py").is_file(),
          sorted(p.name for p in dst.rglob("*")))
    leftovers = [p.name for p in dst.iterdir() if "copy-tmp" in p.name]
    check("no .copy-tmp is left behind", not leftovers, leftovers)


# ---------------------------------------------------------------- F11
def test_f11_sync_code_lock():
    print()
    print("== F11: sync-code holds the root lock while replacing the bundle ==")
    tmp = scratch("f11_")
    (tmp / "state.json").write_text(json.dumps(
        {"version": pp.STATE_VERSION, "runs": {}, "rounds": {}, "pinned": []}),
        encoding="utf-8")
    calls = []
    orig = pp.Ctx.lock

    @contextlib.contextmanager
    def spy(self, what):
        calls.append(what)
        yield

    pp.Ctx.lock = spy
    try:
        pp.cmd_sync_code(SimpleNamespace(root=str(tmp)))
    except SystemExit as e:
        check("sync-code ran (no SystemExit)", False, str(e))
        return
    finally:
        pp.Ctx.lock = orig
    check("sync-code takes ctx.lock('sync-code') for the replacement",
          calls == ["sync-code"], calls)


# ---------------------------------------------------------------- F12
def test_f12_conform_lock():
    print()
    print("== F12: conform holds the root lock while it replaces the package ==")
    tmp = scratch("f12_")
    fake = _FakeCtx(tmp)
    old_ctx = pp.Ctx
    old_templates = pp.venue_word_templates
    old_rebuild = pp.rebuild_package_from_templates
    pp.Ctx = lambda *a, **k: fake
    pp.venue_word_templates = lambda ctx: [tmp / "tpl.docx"]
    (tmp / "tpl.docx").write_bytes(b"x")
    pp.rebuild_package_from_templates = lambda *a, **k: {
        "ok": True, "documents_rebuilt": 0, "files_copied": 0, "files": [],
        "dest": str(k.get("dest") or "")}
    try:
        pp.cmd_apply_template(SimpleNamespace(
            root=str(tmp), agent=None, source=str(tmp), dest=str(tmp / "template_package"),
            force=False, strict_venue=False))
    except SystemExit as e:
        check("conform ran (no SystemExit)", False, str(e))
        return
    finally:
        pp.Ctx = old_ctx
        pp.venue_word_templates = old_templates
        pp.rebuild_package_from_templates = old_rebuild
    check("conform takes ctx.lock('conform') around the rebuild",
          fake.locked == ["conform"], fake.locked)


# ---------------------------------------------------------------- F14
def test_f14_is_within_symlink_loop():
    print()
    print("== F14: is_within returns False on a symlink loop ==")
    tmp = scratch("f14_")
    a, b = tmp / "a", tmp / "b"
    os.symlink(b, a)
    os.symlink(a, b)
    try:
        got = pp.is_within(a, tmp)
    except RuntimeError as e:
        check("is_within does not raise on a symlink loop", False, str(e))
        return
    check("is_within(loop) is False", got is False, got)


# ---------------------------------------------------------------- F17
def _header_template(path: Path, attrs: str) -> Path:
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    r = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document {w} {r}><w:body><w:sectPr>{attrs}</w:sectPr></w:body></w:document>')
        z.writestr("word/header1.xml", f'<w:hdr {w}><w:p><w:r><w:t>VI</w:t></w:r></w:p></w:hdr>')
        z.writestr("word/_rels/document.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId6" Type="http://schemas.openxmlformats.org/'
                   'officeDocument/2006/relationships/header" Target="header1.xml"/>'
                   '</Relationships>')
        z.writestr("word/settings.xml", f'<w:settings {w}/>')
    return path


def test_f17_front_parts_attr_order():
    print()
    print("== F17: header/footer references are read in any attribute order ==")
    tmp = scratch("f17_")
    tpl = _header_template(tmp / "tpl.docx",
                           '<w:headerReference r:id="rId6" w:type="default"/>')
    with zipfile.ZipFile(tpl) as z:
        parts, names = {}, set(z.namelist())
        res = pf._template_front_parts(z, parts, names)
    check("a headerReference with r:id before w:type is harvested",
          any(k.startswith("word/header_venue_") for k in parts), sorted(parts))


# ---------------------------------------------------------------- F19
def test_f19_mixed_case_docx():
    print()
    print("== F19: docx_files_under sees mixed-case extensions ==")
    tmp = scratch("f19_")
    (tmp / "a.docx").write_bytes(b"x")
    (tmp / "B.DOCX").write_bytes(b"x")
    (tmp / "C.Docx").write_bytes(b"x")
    got = [p.name for p in pf.docx_files_under(tmp)]
    check("Main.Docx is included", "C.Docx" in got, got)


# ---------------------------------------------------------------- F21
def test_f21_abstract_not_body():
    print()
    print("== F21: the abstract is not a body-paragraph layout outlier ==")
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

    def p(text, ppr=""):
        props = f"<w:pPr>{ppr}</w:pPr>" if ppr else ""
        return f'<w:p>{props}<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'

    abstract = ("This abstract has many words and it is quite long so that it reaches the "
                "body paragraph length threshold of twenty five words easily here and "
                "continues for a while.")
    b1 = ("This body paragraph is also long enough to be counted and it has a first line "
          "indent applied to it for the test and it keeps going with more words now.")
    b2 = ("This second body paragraph is long enough as well but it is indented and "
          "therefore part of the majority in this example and it has enough words too.")
    body = (p(abstract) + p("Keywords: alpha, beta, gamma") + p("Introduction")
            + p(b1, '<w:ind w:firstLine="360"/>') + p(b2, '<w:ind w:firstLine="360"/>'))
    xml = f'<w:document {w}><w:body>{body}</w:body></w:document>'
    paras = pf.paragraphs(xml)
    rows = pf.layout_consistency_rows(xml, paras, None, "d.docx")
    t8f = [r for r in rows if r["rule"] == "FMT-T8f"]
    check("the abstract is not named as the minority body paragraph",
          not t8f, [r["evidence"] for r in t8f])


# ---------------------------------------------------------------- F22
def test_f22_spelling_masks_urls():
    print()
    print("== F22: spelling counts ignore URL/code spellings the fixer masks ==")
    rows = pf.variant_rows(["colour and see https://example.org/color-chart"], [False])
    t8d = [r for r in rows if r["rule"] == "FMT-T8d"]
    check("a URL spelling does not create a mechanical FMT-T8d row", not t8d,
          [r["evidence"] for r in t8d])


# ---------------------------------------------------------------- F25
def test_f25_tripled_word():
    print()
    print("== F25: a tripled doubled word is fully repaired ==")
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    para = f'<w:p {w}><w:r><w:t xml:space="preserve">the the the</w:t></w:r></w:p>'
    spans = [s for s in pf.hygiene_spans(para) if s["rule"] == "FMT-G1"]
    text = pf.text_of(para)
    for sp in sorted(spans, key=lambda x: -x["start"]):
        text = text[:sp["start"]] + (sp["repl"] or "") + text[sp["end"]:]
    check("'the the the' collapses to 'the'", text == "the", repr(text))


# ---------------------------------------------------------------- F45
def test_f45_paired_relationship():
    print()
    print("== F45: part_rels also reads a paired <Relationship> entry ==")
    tmp = scratch("f45_")
    docx = tmp / "p.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
        z.writestr("word/_rels/document.xml.rels",
                   '<Relationships><Relationship Id="rId1" Type="http://schemas.'
                   'openxmlformats.org/officeDocument/2006/relationships/image" '
                   'Target="media/a.png"></Relationship></Relationships>')
    with zipfile.ZipFile(docx) as z:
        got = pf.part_rels(z, "word/document.xml")
    check("the paired image relationship is found",
          got.get("rId1") == "media/a.png", got)


# ---------------------------------------------------------------- F46
def test_f46_szcs_not_sz():
    print()
    print("== F46: a complex-script size is not read as the run size ==")
    cell = '<w:r><w:rPr><w:szCs w:val="40"/></w:rPr><w:t>x</w:t></w:r>'
    check("a lone w:szCs does not inflate the cell font size",
          pf._cell_font_pt({}, cell) == pf.TABLE_TOKEN_FALLBACK_PT,
          pf._cell_font_pt({}, cell))



# ---------------------------------------------------------------- F28
def test_f28_caption_parity():
    print()
    print("== F28: count_words.CAPTION matches the pipeline's CAPTION_START_RE ==")
    check("panel-range prose is not a caption",
          cw.CAPTION.match("Figure 2a-b shows that p53 levels rose.") is None,
          repr(cw.CAPTION.match("Figure 2a-b shows that p53 levels rose.")))
    check("'Supp. Fig. 2 | ...' is a caption",
          cw.CAPTION.match("Supp. Fig. 2 | Legend text.") is not None)


# ---------------------------------------------------------------- F30
def test_f30_bare_number_limits():
    print()
    print("== F30: count_words accepts the bare-number length-limit shorthand ==")
    tmp = scratch("f30_")
    profile = tmp / "p.json"
    profile.write_text(json.dumps({
        "id": "v", "length_limits": {"abstract": 100, "main_text": 1000},
    }), encoding="utf-8")
    ms = tmp / "ms.md"
    ms.write_text("Abstract\n\nA short abstract here.\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(WS / "paper-skills/paper-review/scripts/count_words.py"),
         "--venue-profile", str(profile), "--json", str(ms)],
        capture_output=True, text=True)
    try:
        caps = json.loads(proc.stdout).get("caps") or {}
    except ValueError:
        caps = {}
    check("bare-number abstract cap is 100", caps.get("abstract") == 100, (caps, proc.stderr))
    check("bare-number main_text cap is 1000", caps.get("main text") == 1000, caps)


# ---------------------------------------------------------------- F31
def test_f31_venue_profile_case():
    print()
    print("== F31: a bare --venue-profile id resolves case-insensitively ==")
    tmp = scratch("f31_")
    ms = tmp / "ms.md"
    ms.write_text("Abstract\n\nA short abstract here.\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(WS / "paper-skills/paper-review/scripts/count_words.py"),
         "--venue-profile", "NATURE-BIOTECHNOLOGY", "--json", str(ms)],
        capture_output=True, text=True)
    check("NATURE-BIOTECHNOLOGY resolves", proc.returncode == 0,
          (proc.returncode, proc.stderr[-300:]))


# ---------------------------------------------------------------- F32
def test_f32_scientific_notation():
    print()
    print("== F32: --value 1e-3 also finds 0.001 ==")
    eo = load("fixbugs1027b_eo", "paper-skills/paper-review/scripts/extract_occurrences.py")
    pat = eo.variant_pattern("1e-3", "value")
    check("1e-3 value pattern matches 0.001", bool(pat.search("0.001")),
          pat.pattern[:120])


# ---------------------------------------------------------------- F33
def test_f33_pairwise_bad_encoding():
    print()
    print("== F33: pairwise_scores reports an undecodable CSV cleanly ==")
    ps = load("fixbugs1027b_ps", "pairwise_scores.py")
    tmp = scratch("f33_")
    bad = tmp / "round1_raw_scores.csv"
    bad.write_bytes(b"member,opponent_id,credited\n\xff,1,2\n")
    try:
        ps.collect([bad], "mean", False, True)
    except SystemExit as e:
        check("a clean SystemExit names the unreadable file", "could not read" in str(e),
              str(e))
    except UnicodeDecodeError as e:
        check("UnicodeDecodeError does not escape", False, str(e))
    else:
        check("collect accepted the file", False)


# ---------------------------------------------------------------- F35
def test_f35_pdf_signature():
    print()
    print("== F35: docx2pdf.sh rejects a non-PDF render ==")
    tmp = scratch("f35_")
    binp = tmp / "bin"
    binp.mkdir()
    docx = tmp / "a.docx"
    docx.write_bytes(b"PK\x03\x04not-a-real-docx")
    pdf = tmp / "a.pdf"
    stub = binp / "powershell.exe"
    stub.write_text("#!/bin/sh\nprintf 'X' > \"$STUB_PDF\"\n")
    stub.chmod(0o755)
    env = dict(os.environ, PATH=f"{binp}:{os.environ.get('PATH', '')}",
               STUB_PDF=str(pdf))
    proc = subprocess.run(["bash", str(WS / "docx2pdf.sh"), str(docx)],
                          capture_output=True, text=True, env=env)
    check("a one-byte non-PDF is a failure", proc.returncode != 0,
          (proc.returncode, proc.stdout[-200:], proc.stderr[-200:]))


# ---------------------------------------------------------------- F36
def test_f36_redline_package():
    print()
    print("== F36: docxcompare.sh rejects a non-OOXML redline ==")
    tmp = scratch("f36_")
    binp = tmp / "bin"
    binp.mkdir()
    a, b = tmp / "a.docx", tmp / "b.docx"
    a.write_bytes(b"PK\x03\x04a")
    b.write_bytes(b"PK\x03\x04b")
    out = tmp / "out.docx"
    stub = binp / "powershell.exe"
    stub.write_text("#!/bin/sh\nprintf 'X' > \"$STUB_OUT\"\n")
    stub.chmod(0o755)
    env = dict(os.environ, PATH=f"{binp}:{os.environ.get('PATH', '')}",
               STUB_OUT=str(out))
    proc = subprocess.run(["bash", str(WS / "docxcompare.sh"), str(a), str(b), str(out)],
                          capture_output=True, text=True, env=env)
    check("a one-byte non-OOXML output is a failure", proc.returncode != 0,
          (proc.returncode, proc.stdout[-300:], proc.stderr[-300:]))


# ---------------------------------------------------------------- F38
def test_f38_resolved_suffix():
    print()
    print("== F38: docxcompare.sh checks the RESOLVED input suffix ==")
    tmp = scratch("f38_")
    binp = tmp / "bin"
    binp.mkdir()
    real_pdf = tmp / "real.pdf"
    real_pdf.write_bytes(b"%PDF-1.4 x")
    alias = tmp / "alias.docx"
    os.symlink(real_pdf, alias)
    b = tmp / "b.docx"
    b.write_bytes(b"PK\x03\x04b")
    stub = binp / "powershell.exe"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    env = dict(os.environ, PATH=f"{binp}:{os.environ.get('PATH', '')}")
    proc = subprocess.run(["bash", str(WS / "docxcompare.sh"), str(alias), str(b)],
                          capture_output=True, text=True, env=env)
    check("a .docx link resolving to a PDF is refused with exit 2",
          proc.returncode == 2 and "resolves" in proc.stderr,
          (proc.returncode, proc.stderr[-300:]))



# ---------------------------------------------------------------- F43
def test_f43_rmtree_symlink():
    print()
    print("== F43: rmtree_force actually removes a symlink ==")
    tmp = scratch("f43_")
    target = tmp / "target"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    link = tmp / "link"
    os.symlink(target, link)
    got = pp.rmtree_force(link)
    check("the symlink is gone", not os.path.lexists(link), os.path.lexists(link))
    check("the target tree is untouched", (target / "keep.txt").is_file())
    check("rmtree_force reports success", got is True, got)


# ---------------------------------------------------------------- F47
def test_f47_non_utf8_readme():
    print()
    print("== F47: a non-UTF-8 staged README still merges a row ==")
    tmp = scratch("f47_")
    staged = tmp / "README.md"
    staged.write_bytes(b"| `other` | caf\xe9 |\n")
    dest = tmp / "venues_readme.md"
    dest.write_text("## Shipped profiles\n\n| id | description |\n|---|---|\n", encoding="utf-8")
    try:
        got = pp._merge_readme_row(staged, dest, "new-venue", {"label": "New Venue"})
    except UnicodeDecodeError as e:
        check("a non-UTF-8 staged README does not crash the merge", False, str(e))
        return
    check("the row was merged", "new-venue" in dest.read_text(encoding="utf-8"), (got, dest.read_text(encoding="utf-8")))


# ---------------------------------------------------------------- F53
def test_f53_report_recovery_loop():
    print()
    print("== F53: the recovery loop does not clobber the no-round default r ==")
    import inspect
    src = inspect.getsource(pp.build_decision_report)
    check("the recovery loop binds its own variable, not r",
          'for r in integrity["recovery"]' not in src)


# ---------------------------------------------------------------- F56
def test_f56_empty_rounds():
    print()
    print("== F56: an explicit rounds=[] renders no round ==")
    tmp = scratch("f56_")
    calls = []

    class C:
        root = tmp

        def rounds_count(self):
            return 2

    old = pp.round_produced_ids
    pp.round_produced_ids = lambda ctx, r: calls.append(r) or []
    try:
        pp.run_pdf_conversion(C(), rounds=[], include_original=False, quiet=True)
    finally:
        pp.round_produced_ids = old
    check("no round is enumerated for rounds=[]", calls == [], calls)


# ---------------------------------------------------------------- F60
def test_f60_judge_view_dir_names():
    print()
    print("== F60: judge-view directories start at d01 as documented ==")
    tmp = scratch("f60_")
    f1 = tmp / "a.png"
    f1.write_bytes(b"x")
    f2 = tmp / "b.tex"
    f2.write_text("x", encoding="utf-8")
    dir_names, file_map = pp._view_layout(
        [("figures/a.png", f1), ("main.tex", f2)], 1, "v1", "seed")
    check("the first anonymous directory is d01",
          dir_names.get("figures") == "d01", dir_names)


# ---------------------------------------------------------------- F61
def test_f61_note_id_token():
    print()
    print("== F61: a REREAD note for F-0123 does not satisfy F-012 ==")
    import inspect
    src = inspect.getsource(pp.postcheck_revise)
    check("the J5 note check uses a whole-token id test",
          "_finding_id_mentioned(fid, p.name)" in src and "fid in p.name" not in src)
    check("the helper rejects a longer id", pp._finding_id_mentioned(
        "F-012", "RESTRUCTURE_F-0123.md") is False)



# ---------------------------------------------------------------- F16
def test_f16_live_style_only():
    print()
    print("== F16: live formatting is not read through w:pPrChange ==")
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    para = (f'<w:p {w}><w:pPr><w:pPrChange w:id="1" w:author="a"><w:pPr>'
            f'<w:pStyle w:val="Heading1"/></w:pPr></w:pPrChange></w:pPr>'
            f'<w:r><w:t>Normal text</w:t></w:r></w:p>')
    check("a style held only in the revision record is not the live style",
          not pf._para_style(para), repr(pf._para_style(para)))
    out = pf.insert_into_ppr(para, "<w:keepNext/>")
    check("keepNext lands on the live paragraph, not inside pPrChange",
          out.find("<w:keepNext/>") < out.find("<w:pPrChange"),
          out)


# ---------------------------------------------------------------- F18
def test_f18_revision_record_italic():
    print()
    print("== F18: the italic repair leaves w:rPrChange byte-identical ==")
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    run = ('<w:r><w:rPr><w:i w:val="0"/><w:rPrChange w:id="1" w:author="a">'
           '<w:rPr><w:i/></w:rPr></w:rPrChange></w:rPr>'
           '<w:t>Smith et al. 2020</w:t></w:r>')
    xml = (f'<w:document {w}><w:body><w:p><w:pPr><w:pStyle w:val="Bibliography"/>'
           f'</w:pPr>{run}</w:p></w:body></w:document>')
    styles = {"Normal": {}, "Bibliography": {}}
    policy = pf.load_policy(None)
    out, changes, _meta = pf.fix_document(xml, styles, policy)
    check("the revision record keeps its original <w:i/>",
          "<w:rPrChange" in out and "<w:i/>" in out.split("<w:rPrChange", 1)[1],
          out[:300])
    check("a roman run is not reported as an italic repair",
          not any("unintended italic" in str(c) for c in changes), changes)
    # The explicit off-override must also stay in the LIVE rPr when the
    # revision record alone carries a schema-successor tag (w:color): scanning
    # the whole rPr for the insert position used to splice it into rPrChange.
    rpr = ('<w:rPr><w:i/><w:rPrChange w:id="1" w:author="a"><w:rPr>'
           '<w:color w:val="FF0000"/></w:rPr></w:rPrChange></w:rPr>')
    new_rpr, changed = pf._rpr_set_emphasis(rpr, False)
    record = lambda s: s[s.find("<w:rPrChange"):s.find("</w:rPrChange>")
                          + len("</w:rPrChange>")]
    check("the explicit off-override stays out of the revision record",
          changed and record(new_rpr) == record(rpr), new_rpr)
    check("the live rPr carries the explicit off-override",
          '<w:i w:val="0"/>' in new_rpr.split("<w:rPrChange")[0], new_rpr)


# ---------------------------------------------------------------- F23
def test_f23_character_style_italic():
    print()
    print("== F23: a character-style italic is not pinned off by a caption merge ==")
    styles = {"Normal": {"i": 0}, "Emphasis": {"i": 1, "basedOn": None}}
    run = '<w:r><w:rPr><w:rStyle w:val="Emphasis"/></w:rPr><w:t>x</w:t></w:r>'
    check("rStyle Emphasis outranks the paragraph style",
          pf._effective_run_flag(styles, "Normal", run, "i") is True,
          pf._effective_run_flag(styles, "Normal", run, "i"))
    direct = '<w:r><w:rPr><w:i/></w:rPr><w:t>x</w:t></w:r>'
    check("direct rPr still outranks the paragraph style",
          pf._effective_run_flag(styles, "Normal", direct, "i") is True)


# ---------------------------------------------------------------- F41
def test_f41_fix_output_atomic():
    print()
    print("== F41: a rejected fix leaves a pre-existing --out untouched ==")
    tmp = scratch("f41_")
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    src = mini_docx(tmp / "in.docx", f'<w:p {w}><w:r><w:t>Text.</w:t></w:r></w:p>')
    out = tmp / "out.docx"
    out.write_bytes(b"GOOD-PREVIOUS")
    policy = pf.load_policy(None)
    old_validate = pf.validate_package
    pf.validate_package = lambda path: (False, "simulated schema failure")
    try:
        rep = pf.fix_package(src, out, policy)
    finally:
        pf.validate_package = old_validate
    check("the rejected fix is not ok", rep.get("ok") is False, rep.get("ok"))
    check("the pre-existing output is untouched", out.read_bytes() == b"GOOD-PREVIOUS",
          out.read_bytes()[:40])
    leftovers = [p.name for p in tmp.iterdir() if ".tmp-" in p.name]
    check("no temp package is left behind", not leftovers, leftovers)


# ---------------------------------------------------------------- F42
def test_f42_zip_tmp_cleanup():
    print()
    print("== F42: a failed final-clean archive leaves no .tmp behind ==")
    tmp = scratch("f42_")
    pkg = tmp / "final_clean_version_x"
    pkg.mkdir()
    (pkg / "a.txt").write_text("x", encoding="utf-8")
    old = pp.shutil.copyfileobj

    def boom(*a, **k):
        raise OSError("simulated ENOSPC")

    pp.shutil.copyfileobj = boom
    try:
        res = pp.write_final_clean_zip(pkg, tmp / "pkg.zip")
    finally:
        pp.shutil.copyfileobj = old
    check("the failure is recorded instead of raised", res.get("ok") is False, res)
    leftovers = [p.name for p in tmp.iterdir() if p.name.endswith(".tmp")]
    check("no .tmp archive is left behind", not leftovers, leftovers)



# ---------------------------------------------------------------- F26
def _m19_limits():
    return {"abstract": {"cap": 100, "relaxation": 1.0},
            "main text": {"cap": 1000, "relaxation": 1.0}}


def test_f26_inline_abstract():
    print()
    print("== F26: an inline 'Abstract: ...' line yields an abstract row ==")
    lines = ["Title", "", "Abstract: We studied the effect of the drug in cells.",
             "", "Introduction", "", "Body prose follows here."]
    rows = pp._length_rows_for_lines(lines, "x.md", limits=_m19_limits())
    abstract = [r for r in rows if r["section"] == "abstract"]
    check("an abstract row exists for the inline layout", bool(abstract), rows)
    if abstract:
        check("the inline remainder is counted as abstract text",
              abstract[0]["words"] >= 8, abstract[0])
    main = [r for r in rows if r["section"] == "main text"]
    if main:
        check("the abstract sentence is not charged to the main text",
              "studied the effect" not in " ".join(lines[1:]) or main[0]["words"] < 10,
              main[0])


# ---------------------------------------------------------------- F27
def test_f27_keyword_block():
    print()
    print("== F27: keyword continuation lines are not main text ==")
    base = ["Title", "", "Abstract", "", "A short abstract.", "",
            "Introduction", "", "Body prose in the manuscript."]
    with_kw = ["Title", "", "Abstract", "", "A short abstract.", "",
               "Keywords: alpha, beta, gamma", "alpha, beta, gamma", "",
               "Introduction", "", "Body prose in the manuscript."]
    r1 = [r for r in pp._length_rows_for_lines(base, "a.md", limits=_m19_limits())
          if r["section"] == "main text"]
    r2 = [r for r in pp._length_rows_for_lines(with_kw, "a.md", limits=_m19_limits())
          if r["section"] == "main text"]
    check("the keyword list adds no words to the main text",
          bool(r1) and bool(r2) and r1[0]["words"] == r2[0]["words"],
          (r1, r2))



# ---------------------------------------------------------------- F49/F50
def _open_item_fixture(report_obj):
    tmp = scratch("f49_")
    runs = tmp / "runs"
    sb = runs / "r1"
    out = sb / "revised"
    out.mkdir(parents=True)
    if report_obj is not None:
        (out / "revision_report.json").write_text(json.dumps(report_obj), encoding="utf-8")

    class C:
        root = tmp
        runs_dir = runs
        state = {"runs": {"r1": {"id": "r1", "kind": "revise", "sandbox": "runs/r1"}},
                 "pinned": []}

    final = {"stored": {}, "pin": {"produced_by_run": "r1"}}
    return C(), final, out


def test_f49_bare_list_ledger():
    print()
    print("== F49: a bare-list revision ledger is read, not crashed on ==")
    ctx, final, _out = _open_item_fixture([
        {"id": "F-1", "verdict": "manual-required", "check": "M1"},
        {"id": "F-2", "verdict": "confirmed", "check": "M2"},
    ])
    try:
        info = pp.collect_open_review_items(ctx, final)
    except AttributeError as e:
        check("a bare-list ledger does not raise", False, str(e))
        return
    check("the manual-required row is an open item",
          [i["id"] for i in info["items"]] == ["F-1"], info["items"])
    check("the manual-required status is read from verdict",
          info["items"] and info["items"][0]["status"] == "manual-required", info["items"])


def test_f50_manual_steps_count():
    print()
    print("== F50: a plain bullet counts as a hand-off item ==")
    ctx, final, out = _open_item_fixture({})
    (out / "MANUAL_STEPS.md").write_text(
        "# MANUAL_STEPS\n\n- Verify the accession number in the repository.\n",
        encoding="utf-8")
    info = pp.collect_open_review_items(ctx, final)
    check("the MANUAL_STEPS bullet is counted", info["manual_steps_items"] == 1,
          info["manual_steps_items"])
    write = pp.write_open_items_sibling(ctx, info)
    sibling = ctx.root / pp.FINAL_CLEAN_STEPS_NAME
    check("the sibling header carries the file's own item count",
          "Open item(s): 1" in sibling.read_text(encoding="utf-8")
          and write.get("items") == 1, (write, sibling.read_text(encoding="utf-8")[:200]))



# ---------------------------------------------------------------- F29
def test_f29_letter_type_not_cover():
    print()
    print("== F29: a Letter-to-the-Editor manuscript is not a cover letter ==")
    tmp = scratch("f29_")
    profile = tmp / "p.json"
    profile.write_text(json.dumps({
        "id": "v", "default_article_type": "letter-to-the-editor",
        "article_types": [{"id": "letter-to-the-editor", "label": "Letter to the Editor",
                           "length_limits": {"main_text": {"base": 1000, "relaxation": 1.0}}}],
    }), encoding="utf-8")
    ms = tmp / "letter_to_the_editor.md"
    ms.write_text("Dear Editor,\n\nWe read the paper with interest and have comments.\n",
                  encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(WS / "paper-skills/paper-review/scripts/count_words.py"),
         "--venue-profile", str(profile), "--article-type", "letter-to-the-editor",
         "--json", str(ms)], capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        data = {}
    sections = [r.get("section") for r in data.get("rows") or []]
    check("the manuscript is not reported as a cover letter",
          "cover letter" not in sections, (sections, proc.stderr))


# ---------------------------------------------------------------- F48
def test_f48_unreadable_corpus_file():
    print()
    print("== F48: one unreadable corpus file is a recorded gap, not a crash ==")
    scripts = [
        ("extract_numbers.py", ["--work", "W", "--out", "O"]),
        ("extract_acronyms.py", ["--work", "W", "--out", "O"]),
        ("extract_citations.py", ["--work", "W", "--out", "O"]),
        ("extract_occurrences.py", ["--work", "W", "--out", "O", "--term", "alpha"]),
    ]
    for name, argv in scripts:
        tmp = scratch("f48_")
        work = tmp / "work"
        (work / "corpus").mkdir(parents=True)
        (work / "corpus" / "good.txt").write_text(
            "Alpha cells were counted and p = 0.03 in the assay.\n", encoding="utf-8")
        (work / "corpus" / "bad.txt").mkdir()          # open() raises IsADirectoryError
        out = tmp / "out"
        args = [sys.executable, str(WS / "paper-skills/paper-review/scripts" / name)]
        args += [str(a) if a not in ("W", "O") else str(work if a == "W" else out)
                 for a in argv]
        proc = subprocess.run(args, capture_output=True, text=True)
        check(f"{name}: exits 0 with the bad file skipped", proc.returncode == 0,
              (proc.returncode, proc.stderr[-300:]))
        check(f"{name}: records file-unreadable", "file-unreadable" in proc.stderr,
              proc.stderr[-300:])


# ---------------------------------------------------------------- F64
def test_f64_backup_collision():
    print()
    print("== F64: a same-second backup collision does not nest the package ==")
    tmp = scratch("f64_")
    home = tmp / "home"
    backup = home / ".codex" / "backup"
    skills = home / ".codex" / "skills"
    backup.mkdir(parents=True)
    skills.mkdir(parents=True)
    old = skills / "paper-skills-old"
    old.mkdir()
    (old / "SKILL.md").write_text("old", encoding="utf-8")
    (backup / "paper-skills-old").mkdir()
    (backup / "paper-skills-old.20260101000000").mkdir()
    binp = tmp / "bin"
    binp.mkdir()
    for tool in ("npm", "git"):
        q = binp / tool
        q.write_text("#!/bin/sh\nexit 0\n")
        q.chmod(0o755)
    datef = binp / "date"
    datef.write_text("#!/bin/sh\ncase \"$1\" in\n  +%Y%m%d%H%M%S) echo 20260101000000 ;;\n"
                     "  +%Y-%m%d) echo 2026-0101 ;;\n  *) exec /bin/date \"$@\" ;;\nesac\n")
    datef.chmod(0o755)
    env = dict(os.environ, HOME=str(home), PATH=f"{binp}:{os.environ.get('PATH', '')}",
               MCP_TOOLS_DIR=str(tmp / "tools"))
    proc = subprocess.run(["bash", str(WS / "install_skill.sh")],
                          capture_output=True, text=True, env=env)
    nested = backup / "paper-skills-old.20260101000000" / "paper-skills-old"
    check("the backup did not land inside an existing directory",
          not nested.exists(), sorted(str(p.relative_to(backup)) for p in backup.rglob("*"))[:8])
    suffix = backup / "paper-skills-old.20260101000000.1"
    check("the package is at a fresh timestamped path",
          (suffix / "SKILL.md").is_file(),
          sorted(p.name for p in backup.iterdir()))


# ---------------------------------------------------------------- F65
def test_f65_env_home_expansion():
    print()
    print("== F65: env-provided DSH_HOME/CODEX_HOME expand '~' ==")
    tmp = scratch("f65_")
    env = dict(os.environ, DSH_HOME="~/.dsh", CODEX_HOME="~/.codex")
    proc = subprocess.run(["node", str(WS / "scripts/install-codex-mcp.mjs"), "--dry-run"],
                          capture_output=True, text=True, env=env)
    got = proc.stdout + proc.stderr
    home = os.path.expanduser("~")
    check("the profile path resolves under the real home",
          f"{home}/.dsh/profiles/headless" in got, got[-300:])
    check("no cwd-relative '~/.dsh' path is reported",
          "paper-refine/~/.dsh" not in got, got[-300:])



# ---------------------------------------------------------------- F08
def test_f08_winner_dir_containment():
    print()
    print("== F08: invalidate_from_round refuses a winner_dir outside the root ==")
    tmp = scratch("f08_")
    root = tmp / "root"
    root.mkdir()
    reports = root / "reports"
    reports.mkdir()
    outside = tmp / "outside"
    outside.mkdir()
    (outside / "valuable.txt").write_text("keep me", encoding="utf-8")
    rec = {"winner_dir": "../outside"}

    class C:
        def __init__(self):
            self.root = root
            self.reports_dir = reports
            self.state = {"pinned": []}

        def rounds_count(self):
            return 1

        def round_rec(self, r):
            return rec

        def runs(self, round_no=None):
            return []

        def log(self, *a, **k):
            pass

        def save_state(self):
            pass

    try:
        pp.invalidate_from_round(C(), 1, "test")
    except SystemExit as e:
        check("the escaping record is refused", True, str(e))
    else:
        check("the escaping record is refused", False, "no SystemExit")
    check("the outside directory is untouched",
          (outside / "valuable.txt").is_file(),
          sorted(str(p.relative_to(tmp)) for p in tmp.rglob("*")))



# ---------------------------------------------------------------- F06
def test_f06_audit_readonly_areas():
    print()
    print("== F06: the revision audit may not edit review/ or base/ ==")
    tmp = scratch("f06_")
    sb = tmp / "runs" / "r1"
    for name in ("base", "review", "audit", "raw_data", "code", "revised",
                 "revision_audit"):
        (sb / name).mkdir(parents=True)
    (sb / "revised" / "manuscript.md").write_text("judged text\n", encoding="utf-8")
    (sb / "review" / "findings.json").write_text('{"findings": []}', encoding="utf-8")
    rec = {"id": "r1", "kind": "revise", "round": 1, "status": "done"}

    class C:
        root = tmp

        def sandbox_of(self, _rec):
            return sb

        def runs(self, round_no=None):
            return []

        def round_rec(self, r):
            return {"status": "pending"}

        def save_state(self):
            pass

        def log(self, *a, **k):
            pass

    old = {
        "_run_aux_session": pp._run_aux_session,
        "revision_audit_of": pp.revision_audit_of,
        "journal_is_scoped": pp.journal_is_scoped,
        "round_is_done": pp.round_is_done,
    }

    def fake_session(_sb, _rec, _cmd, _timeout, _prompt, _log):
        # The audit edits a read-only area (review/) but writes a valid,
        # empty plan where it is allowed to write.
        (_sb / "review" / "findings.json").write_text('{"findings": ["tampered"]}',
                                                     encoding="utf-8")
        (_sb / "revision_audit" / "REPAIR_PLAN.json").write_text('{"rows": []}',
                                                                encoding="utf-8")
        return {"rc": 0, "dur": 1.0, "error": ""}

    try:
        pp._run_aux_session = fake_session
        pp.revision_audit_of = lambda ctx: "on"
        pp.journal_is_scoped = lambda ctx: False
        pp.round_is_done = lambda ctx, r: False
        pp.run_revision_chain(C(), rec, [], 10)
    finally:
        pp._run_aux_session = old["_run_aux_session"]
        pp.revision_audit_of = old["revision_audit_of"]
        pp.journal_is_scoped = old["journal_is_scoped"]
        pp.round_is_done = old["round_is_done"]
    audit = rec.get("revision_audit") or {}
    check("an audit that edits review/ fails", audit.get("status") == "failed", audit)
    check("the failure names the modified area", "review" in str(audit.get("error") or ""),
          audit.get("error"))



# ---------------------------------------------------------------- F15
def test_f15_nontext_offsets():
    print()
    print("== F15: noBreakHyphen/sym advance the text-space offsets ==")
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    para = (f'<w:p {w}><w:r><w:t>ten</w:t><w:noBreakHyphen/><w:t>year</w:t>'
            f'</w:r></w:p>')
    text = pf.text_of(para)
    lines = pf.visual_text_lines(para)
    check("the visual line covers the whole rendered text",
          lines == [(0, len(text))], (text, lines))
    # A space AFTER the break must be a leading space of the SECOND line, not a
    # whitespace-only first line that covers (and deletes) the break.
    br = (f'<w:p {w}><w:r><w:t>end</w:t><w:br/><w:t xml:space="preserve"> next</w:t>'
          f'</w:r></w:p>')
    spans = pf.hygiene_spans(br)
    check("the line break survives the hygiene repair",
          any(sp["rule"] == "FMT-P4" or sp["rule"] == "FMT-G1" for sp in spans)
          and not any(sp["start"] == 3 and sp["end"] == 4 for sp in spans),
          [(sp["rule"], sp["start"], sp["end"]) for sp in spans])
    fld = (f'<w:p {w}><w:fldSimple w:instr="REF x"><w:r><w:t>ab</w:t>'
           f'<w:noBreakHyphen/><w:t>cd</w:t></w:r></w:fldSimple></w:p>')
    ranges = pf.field_result_text_ranges(fld)
    check("the protected range ends at the rendered text end",
          ranges and ranges[-1][1] == len(pf.text_of(fld))
          and all(a < b for a, b in ranges), ranges)


# ---------------------------------------------------------------- F63
def test_f63_failed_npm_keeps_live_tool():
    print()
    print("== F63: a failed npm ci keeps the previously installed converter ==")
    tmp = scratch("f63_")
    home = tmp / "home"
    tools = tmp / "tools"
    for name in ("mcp-docx-converter", "mcp-docx-compare"):
        (tools / name).mkdir(parents=True)
        (tools / name / "keep.txt").write_text("old", encoding="utf-8")
    binp = tmp / "bin"
    binp.mkdir()
    git = binp / "git"
    git.write_text("#!/bin/sh\nexit 0\n")
    git.chmod(0o755)
    npm = binp / "npm"
    npm.write_text("#!/bin/sh\ncase \"$*\" in\n  *mcp-docx-converter*) exit 1 ;;\n"
                   "  *) exit 0 ;;\nesac\n")
    npm.chmod(0o755)
    env = dict(os.environ, HOME=str(home), PATH=f"{binp}:{os.environ.get('PATH', '')}",
               MCP_TOOLS_DIR=str(tools))
    proc = subprocess.run(["bash", str(WS / "install_skill.sh")],
                          capture_output=True, text=True, env=env)
    check("the install fails", proc.returncode != 0, proc.returncode)
    check("the previously working converter is still installed",
          (tools / "mcp-docx-converter" / "keep.txt").is_file(),
          sorted(str(p.relative_to(tools)) for p in tools.rglob("*"))[:8])



# ---------------------------------------------------------------- F40
def test_f40_mcp_timeout_kills_group():
    print()
    print("== F40: an MCP timeout kills the PowerShell/Word process group ==")
    tmp = scratch("f40_")
    parent = tmp / "parent.sh"
    pidfile = tmp / "child.pid"
    parent.write_text(
        "#!/bin/sh\nsleep 30 &\necho $! > \"$1\"\nwait\n", encoding="utf-8")
    parent.chmod(0o755)
    helper = (WS / "mcp-docx-compare/run-child.mjs").as_uri()
    script = tmp / "check.mjs"
    script.write_text(f"""
import {{ runFile }} from {json.dumps(helper)};
import {{ readFileSync }} from 'node:fs';
let killed = false;
try {{
  await runFile({json.dumps(str(parent))}, [{json.dumps(str(pidfile))}], {{ timeout: 400 }});
}} catch (e) {{
  killed = e.killed === true && /timed out/.test(e.message);
}}
await new Promise((r) => setTimeout(r, 300));
let alive = true;
try {{
  const pid = Number(readFileSync({json.dumps(str(pidfile))}, 'utf8').trim());
  process.kill(pid, 0);
}} catch {{
  alive = false;
}}
if (!killed) {{ console.error('timeout was not reported'); process.exit(1); }}
if (alive) {{ console.error('grandchild survived the timeout'); process.exit(1); }}
console.log('group killed');
""", encoding="utf-8")
    proc = subprocess.run(["node", str(script)], capture_output=True, text=True)
    check("the whole process group is killed on timeout",
          proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr))



def main() -> int:
    try:
        test_f01_floor_zero_empty_prefix()
        test_f02_ranking_text()
        test_f09_scoped_mode_restore()
        test_f10_copy_asset_dirs_atomic()
        test_f11_sync_code_lock()
        test_f12_conform_lock()
        test_f14_is_within_symlink_loop()
        test_f17_front_parts_attr_order()
        test_f19_mixed_case_docx()
        test_f21_abstract_not_body()
        test_f22_spelling_masks_urls()
        test_f25_tripled_word()
        test_f45_paired_relationship()
        test_f46_szcs_not_sz()
        test_f28_caption_parity()
        test_f30_bare_number_limits()
        test_f31_venue_profile_case()
        test_f32_scientific_notation()
        test_f33_pairwise_bad_encoding()
        test_f35_pdf_signature()
        test_f36_redline_package()
        test_f38_resolved_suffix()
        test_f43_rmtree_symlink()
        test_f47_non_utf8_readme()
        test_f53_report_recovery_loop()
        test_f56_empty_rounds()
        test_f60_judge_view_dir_names()
        test_f61_note_id_token()
        test_f16_live_style_only()
        test_f18_revision_record_italic()
        test_f23_character_style_italic()
        test_f41_fix_output_atomic()
        test_f42_zip_tmp_cleanup()
        test_f26_inline_abstract()
        test_f27_keyword_block()
        test_f49_bare_list_ledger()
        test_f50_manual_steps_count()
        test_f29_letter_type_not_cover()
        test_f48_unreadable_corpus_file()
        test_f64_backup_collision()
        test_f65_env_home_expansion()
        test_f08_winner_dir_containment()
        test_f06_audit_readonly_areas()
        test_f15_nontext_offsets()
        test_f63_failed_npm_keeps_live_tool()
        test_f40_mcp_timeout_kills_group()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)}: {FAILS}")
        return 1
    print("OK all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

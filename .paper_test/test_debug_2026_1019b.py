#!/usr/bin/env python3
"""Regression tests for the 2026-10-19 audit findings (debug stage).

Each test pins a failure that was reproduced against the pre-fix tree:

* F01: a header needing both an image-ratio repair and a duplicate-PAGE repair
  kept the distorted image while `fix_package` reported success;
* F02: `repair_layout_package` returned ok without writing `--out` on a clean
  package;
* F03: FMT-S10 ignored the `w:fldSimple` serialization of a PAGE field;
* F04: `figure_ocr=false` switched off the non-OCR FMT-IM4 check and did not
  switch off embedded-DOCX OCR;
* F05: a recorded module digest was not compared with the frozen file, so a
  tampered/missing formatter still let the root run and the stage scan pass;
* F06: `copy_into` followed a submission symlink outside the package;
* F07: the stale-module message suggested the frozen driver (`sync-code` then
  refused it) and misattributed local drift;
* F08: negation-blind claim/logic regexes reported correct negative prose;
* F09: `.PDF`/`.MD` were invisible to the case-sensitive glob, short PDFs were
  dropped, and a missing `pdftotext` produced no gap row.

Run: python3 .paper_test/test_debug_2026_1019b.py
     (the harness form; `python3 -m pytest -q ...` also works)
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import struct
import sys
import zipfile
import zlib
from pathlib import Path

from bundle_source_lib import copy_bundle
try:
    import pytest
except ModuleNotFoundError:                     # the script runner has no pytest
    from pytest_shim import pytest

WS = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("paper_docx_format",
                                              str(WS / "paper_docx_format.py"))
fmt = importlib.util.module_from_spec(spec)
sys.modules["paper_docx_format"] = fmt
spec.loader.exec_module(fmt)

pspec = importlib.util.spec_from_file_location("paper_pipeline", str(WS / "paper_pipeline.py"))
pp = importlib.util.module_from_spec(pspec)
sys.modules["paper_pipeline"] = pp
pspec.loader.exec_module(pp)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _png(w: int, h: int) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _page_field_para(n: int = 1) -> str:
    return (f'<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
            f'<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r><w:t>{n}</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')


def _make_header_package(path: Path) -> Path:
    """A referenced header with a distorted 10x10 image and two PAGE fields."""
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{W}" '
           f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
           f'<w:body><w:p><w:r><w:t>Body text.</w:t></w:r></w:p>'
           f'<w:sectPr><w:headerReference w:type="default" r:id="rIdH"/></w:sectPr>'
           f'</w:body></w:document>')
    header = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              f'<w:hdr xmlns:w="{W}" '
              f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
              f'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
              f'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
              f'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
              f'<w:p><w:r><w:drawing><wp:inline><wp:extent cx="2000000" cy="1000000"/>'
              f'<wp:docPr id="1" name="Picture 1"/><a:graphic><a:graphicData '
              f'uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
              f'<pic:nvPicPr><pic:cNvPr id="1" name="image1.png"/><pic:cNvPicPr/></pic:nvPicPr>'
              f'<pic:blipFill><a:blip r:embed="rIdImg"/><a:stretch><a:fillRect/></a:stretch>'
              f'</pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/>'
              f'<a:ext cx="2000000" cy="1000000"/></a:xfrm><a:prstGeom prst="rect">'
              f'<a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
              f'</wp:inline></w:drawing></w:r></w:p>{_page_field_para(1)}{_page_field_para(1)}'
              f'</w:hdr>')
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Default Extension="png" ContentType="image/png"/>'
             '<Default Extension="rels" '
             'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Override PartName="/word/document.xml" ContentType="application/vnd.'
             'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             '<Override PartName="/word/header1.xml" ContentType="application/vnd.'
             'openxmlformats-officedocument.wordprocessingml.header+xml"/></Types>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'relationships"><Relationship Id="rId1" Type="http://schemas.'
                   'openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                   'Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", doc)
        z.writestr("word/_rels/document.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'relationships"><Relationship Id="rIdH" Type="http://schemas.'
                   'openxmlformats.org/officeDocument/2006/relationships/header" '
                   'Target="header1.xml"/></Relationships>')
        z.writestr("word/header1.xml", header)
        z.writestr("word/_rels/header1.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'relationships"><Relationship Id="rIdImg" Type="http://schemas.'
                   'openxmlformats.org/officeDocument/2006/relationships/image" '
                   'Target="media/image1.png"/></Relationships>')
        z.writestr("word/media/image1.png", _png(10, 10))
    return path


def _make_clean_package(path: Path) -> Path:
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>Clean body text.'
           f'</w:t></w:r></w:p><w:sectPr/></w:body></w:document>')
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Default Extension="rels" '
             'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Override PartName="/word/document.xml" ContentType="application/vnd.'
             'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'relationships"><Relationship Id="rId1" Type="http://schemas.'
                   'openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                   'Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", doc)
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _temp_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    copy_bundle(WS, root)
    (root / "pipeline_config.json").write_text("{}", encoding="utf-8")
    (root / "state.json").write_text(json.dumps({
        "version": 3, "runs": {}, "rounds": {}, "pinned": [], "log": [],
        "pipeline": {
            "path": str(WS / "paper_pipeline.py"),
            "sha256": _sha(root / "paper_pipeline.py"),
            "version": pp.VERSION,
            "modules": pp.module_manifest(root),
        },
    }), encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# F01
# ---------------------------------------------------------------------------
def test_fix_package_keeps_header_geometry_when_removing_duplicate_page(tmp_path):
    src = _make_header_package(tmp_path / "in.docx")
    out = tmp_path / "out.docx"
    rep = fmt.fix_package(src, out, dict(fmt.POLICY_DEFAULTS))
    assert rep["ok"], rep
    with zipfile.ZipFile(out) as z:
        header = z.read("word/header1.xml").decode("utf-8")
        sizes = fmt.media_pixel_sizes(z)
    assert 'cy="2000000"' in header, header
    rows = fmt.drawing_geometry_rows(header, {"rIdImg": "media/image1.png"}, sizes,
                                     "header1.xml", dict(fmt.POLICY_DEFAULTS))[0]
    assert not [r for r in rows if r["rule"] == "FMT-IM1"], rows
    assert len(fmt.PAGE_FIELD_INSTR_RE.findall(header)) == 1


# ---------------------------------------------------------------------------
# F02
# ---------------------------------------------------------------------------
def test_repair_layout_writes_output_on_clean_package(tmp_path):
    src = _make_clean_package(tmp_path / "clean.docx")
    out = tmp_path / "clean.fixed.docx"
    rep = fmt.repair_layout_package(src, out, dict(fmt.POLICY_DEFAULTS))
    assert rep["ok"], rep
    assert out.is_file(), rep
    assert out.read_bytes() == src.read_bytes(), "a no-op repair must copy byte-for-byte"


# ---------------------------------------------------------------------------
# F03
# ---------------------------------------------------------------------------
def test_page_field_fld_simple_duplicate_is_scanned_and_fixed():
    footer = (f'<?xml version="1.0"?><w:ftr xmlns:w="{W}">'
              f'<w:p><w:fldSimple w:instr=" PAGE \\* Arabic "><w:r><w:t>1</w:t></w:r>'
              f'</w:fldSimple></w:p>'
              f'<w:p><w:fldSimple w:instr=" PAGE \\* Arabic "><w:r><w:t>1</w:t></w:r>'
              f'</w:fldSimple></w:p></w:ftr>')
    rows = fmt.page_field_rows([("word/footer1.xml", footer)], "x.docx")
    assert [r["rule"] for r in rows] == ["FMT-S10"], rows
    fixed = fmt.apply_edits(footer, fmt.page_field_fixes(footer))
    assert len(fmt.PAGE_FIELD_INSTR_RE.findall(fixed)) == 1, fixed
    assert "fldSimple" in fixed


# ---------------------------------------------------------------------------
# F04
# ---------------------------------------------------------------------------
def test_figure_ocr_off_still_runs_non_ocr_resolution_check(tmp_path):
    (tmp_path / "fig.png").write_bytes(_png(10, 10))
    policy = dict(fmt.POLICY_DEFAULTS, min_image_dpi=450, min_figure_text_pt=5,
                  figure_print_width_in=6.5, figure_ocr=False)
    info = pp.scan_format_in_sources([(tmp_path, "", ())], policy=policy)
    rules = {r["rule"] for r in info["rows"]}
    assert "FMT-IM4" in rules, info["rows"]
    assert "FMT-IM6" in rules, info["rows"]          # recorded gap, not a silent pass


def test_figure_ocr_off_does_not_call_embedded_ocr(tmp_path, monkeypatch):
    src = _make_header_package(tmp_path / "in.docx")
    calls = []
    monkeypatch.setattr(fmt, "figure_text_size_rows",
                        lambda *a, **k: calls.append(a) or [])
    info = fmt.analyse_package(src, dict(fmt.POLICY_DEFAULTS, min_figure_text_pt=5,
                                         figure_ocr=False))
    assert calls == []
    assert any(r["rule"] == "FMT-IM6" for r in info["rows"]), info["rows"]


# ---------------------------------------------------------------------------
# F05
# ---------------------------------------------------------------------------
def test_recorded_module_mismatch_is_refused(tmp_path, capfd):
    root = _temp_root(tmp_path)
    state = json.loads((root / "state.json").read_text())
    state["pipeline"]["modules"]["paper_docx_format.py"] = "0" * 64
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    ctx = pp.Ctx(root)
    ctx.load(need_cfg=False)
    with pytest.raises(SystemExit):
        pp.refuse_foreign_pipeline(ctx, "run")
    err = capfd.readouterr().err
    assert "do NOT match its state.json manifest" in err, err
    assert "paper_docx_format.py" in err, err


def test_deleted_frozen_module_is_refused(tmp_path, capfd):
    root = _temp_root(tmp_path)
    (root / "paper_docx_format.py").unlink()
    ctx = pp.Ctx(root)
    ctx.load(need_cfg=False)
    with pytest.raises(SystemExit):
        pp.refuse_foreign_pipeline(ctx, "run")
    err = capfd.readouterr().err
    assert "do NOT match its state.json manifest" in err, err
    assert "paper_docx_format.py" in err, err


def test_missing_formatter_is_a_recorded_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "_format_module", lambda: None)
    info = pp.scan_format_in_sources([(tmp_path, "", ())])
    assert info.get("unavailable"), info
    errs, warns = pp.scan_regression_problems(None, [(tmp_path, "", ())],
                                              [(tmp_path, "", ())], "stage")
    assert errs, (errs, warns)
    assert "UNAVAILABLE" in errs[0], errs


# ---------------------------------------------------------------------------
# F06
# ---------------------------------------------------------------------------
def test_copy_into_skips_symlinks(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    (src / "main.txt").write_text("main\n")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-LOCAL-FILE\n")
    os.symlink(secret, src / "leak.txt")
    pp.copy_into(src, dst)
    assert not (dst / "leak.txt").exists(), "the symlink target must not be copied"
    assert (dst / "main.txt").read_text() == "main\n"


# ---------------------------------------------------------------------------
# F07
# ---------------------------------------------------------------------------
def test_stale_module_message_names_the_maintained_checkout(tmp_path, capfd):
    root = _temp_root(tmp_path)
    with (root / "paper_docx_format.py").open("a") as f:
        f.write("\n# local drift\n")
    ctx = pp.Ctx(root)
    ctx.load(need_cfg=False)
    with pytest.raises(SystemExit):
        pp.refuse_foreign_pipeline(ctx, "run")
    err = capfd.readouterr().err
    assert "state.json manifest" in err, err
    assert str(WS / "paper_pipeline.py") in err, err
    assert str(root / "paper_pipeline.py") not in err, err
    note = pp.pipeline_snapshot_note(ctx)
    assert "does NOT match" in note and "<maintained>" not in note, note


# ---------------------------------------------------------------------------
# F08
# ---------------------------------------------------------------------------
def test_negated_claims_are_not_contradictions_or_logic_rows():
    assert fmt.claim_contradiction_rows([
        ("a", "We have not shipped the per-candidate tables."),
        ("b", "The tables are not part of that repository."),
    ]) == []
    assert fmt.claim_contradiction_rows([
        ("a", "We haven't shipped the per-candidate tables."),
        ("b", "The tables are not part of that repository."),
    ]) == [], "a contraction is a negation"
    assert fmt.logic_rows([
        "This does not test whether the estimate is low, because the premise was "
        "assumed."
    ]) == []
    # A negation in an EARLIER sentence must not suppress a later affirmative
    # expectation-as-evidence defect (the guard is sentence-scoped).
    assert fmt.logic_rows([
        "The effect was not significant. We expected the estimate to be low, "
        "which implies the premise holds."
    ]), "an earlier sentence's negation must not hide a later FMT-T9L"
    # The intended positive shapes must still fire.
    assert fmt.claim_contradiction_rows([
        ("a", "The tables were shipped as per-candidate tables."),
        ("b", "The tables are not part of that repository."),
    ])
    assert fmt.logic_rows([
        "It tests whether the estimate is low, because the premise was assumed."
    ])


# ---------------------------------------------------------------------------
# F09
# ---------------------------------------------------------------------------
def test_pdf_and_text_enumeration_is_case_insensitive(tmp_path):
    (tmp_path / "UPPER.PDF").write_text("x")
    (tmp_path / "MIXED.Pdf").write_text("x")
    (tmp_path / "notes.MD").write_text("Some text.")
    (tmp_path / "refs.BIB").write_text("@article{a,title={T}}")
    assert [p.name for p in pp._files_under_ci(tmp_path, (".pdf",))] == \
        ["MIXED.Pdf", "UPPER.PDF"]
    assert [p.name for p in pp._files_under_ci(tmp_path, (".md", ".bib"))] == \
        ["notes.MD", "refs.BIB"]


def test_short_pdf_is_scanned(tmp_path, monkeypatch):
    (tmp_path / "short.pdf").write_bytes(b"%PDF-1.4\n")
    # `_pdf_text_info` is stubbed (the scan needs the text/error pair), but the
    # scan still gates on `shutil.which`; declare the tool present so the test
    # does not depend on the host.
    real_which = shutil.which
    monkeypatch.setattr(pp.shutil, "which",
                        lambda name: "/usr/bin/pdftotext" if name == "pdftotext"
                        else real_which(name))
    monkeypatch.setattr(pp, "_pdf_text_info", lambda _p: (
        "The six metrics are intCN_accuracy, intCN_PCC, nonintCN_PCC, "
        "CN_genome_cov_frac, and intCN_modal_frac.", ""))
    info = pp.scan_format_in_sources([(tmp_path, "", ())])
    assert any(r["rule"] == "FMT-CN1" and r["document"].endswith("short.pdf")
               for r in info["rows"]), info["rows"]


def test_missing_pdftotext_is_a_gap_row(tmp_path, monkeypatch):
    (tmp_path / "SUPP.PDF").write_bytes(b"%PDF-1.4\n")
    real_which = shutil.which
    monkeypatch.setattr(pp.shutil, "which",
                        lambda name: None if name == "pdftotext" else real_which(name))
    info = pp.scan_format_in_sources([(tmp_path, "", ())])
    assert any(r["rule"] == "FMT-PDF0" and r["document"].endswith("SUPP.PDF")
               for r in info["rows"]), info["rows"]


# ---------------------------------------------------------------------------
# F12
# ---------------------------------------------------------------------------
def test_round2_validation_doc_matches_the_module_manifest():
    # The dated working records live in revision_history/ (repo bookkeeping,
    # never submitted), not in the repository root.
    text = (WS / "revision_history" / "ROUND2_ISSUE_VALIDATION_2026-1019.md"
            ).read_text(encoding="utf-8")
    assert "three-module" not in text, "the validation record still says three modules"
    assert "paper_qwen_agent.py" in text
    # The module manifest also freezes the two render/track shims (2026-10-25
    # fix stage, F132); the validation record's four modules must all remain.
    assert {"paper_pipeline.py", "paper_docx_format.py",
            "paper_redlines_adapter.py", "paper_qwen_agent.py"} \
        <= set(pp.PIPELINE_MODULE_FILES)


# ---------------------------------------------------------------------------
# F13: the new sync-code path, its frozen-root refusal, and the four-module copy
# ---------------------------------------------------------------------------
def test_sync_code_copies_the_maintained_bundle(tmp_path):
    import subprocess
    root = _temp_root(tmp_path)
    for name in ("paper_redlines_adapter.py", "paper_qwen_agent.py"):
        shutil.copy2(WS / name, root / name)
    with (root / "paper_docx_format.py").open("a") as f:
        f.write("\n# stale copy\n")
    p = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "sync-code",
                        "--root", str(root)], capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert (root / "paper_docx_format.py").read_bytes() == \
        (WS / "paper_docx_format.py").read_bytes()
    state = json.loads((root / "state.json").read_text())
    for name in pp.PIPELINE_MODULE_FILES:
        assert state["pipeline"]["modules"][name] == _sha(root / name), name


def test_sync_code_refuses_a_frozen_root(tmp_path):
    import subprocess
    root = _temp_root(tmp_path)
    p = subprocess.run([sys.executable, str(root / "paper_pipeline.py"), "sync-code",
                        "--root", str(root)], capture_output=True, text=True, timeout=120)
    assert p.returncode != 0, (p.stdout, p.stderr)
    assert "MAINTAINED tree" in (p.stdout + p.stderr)
    assert str(WS / "paper_pipeline.py") in (p.stdout + p.stderr)


# ---------------------------------------------------------------------------
# F13: the Qwen adapter's main() path reports a tunnel failure as exit 2
# ---------------------------------------------------------------------------
def test_qwen_main_surfaces_tunnel_failure(monkeypatch, capsys):
    qspec = importlib.util.spec_from_file_location(
        "paper_qwen_agent_test", str(WS / "paper_qwen_agent.py"))
    qa = importlib.util.module_from_spec(qspec)
    sys.modules["paper_qwen_agent_test"] = qa
    qspec.loader.exec_module(qa)
    monkeypatch.setattr(qa, "ensure_tunnel", lambda _cfg: "no tunnel")
    assert qa.main(["--tunnel", "off"]) == 2
    assert "no tunnel" in capsys.readouterr().err


if __name__ == "__main__":
    # `run_all.py` executes suites as scripts; without this block the file ran
    # only its imports and exited 0, which the harness counted as PASS with zero
    # checks (and failed outright when pytest was not installed).
    from pytest_shim import run_tests
    raise SystemExit(run_tests(globals()))




#!/usr/bin/env python3
"""Regression tests for the 2026-10-30 fix-bugs wave.

Every check here is a repro for one verified finding (Cxx ids in the stage
ledger): it failed on the pre-fix tree and passes now. Run:

    python3 .paper_test/test_fix_bugs_20261030.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import types
import zipfile
import zlib
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fixbugs30_pp", "paper_pipeline.py")
fmt = load("fixbugs30_fmt", "paper_docx_format.py")
ec = load("fixbugs30_ec", "paper-skills/paper-review/scripts/extract_citations.py")
stub = load("fixbugs30_stub", ".paper_test/stub_agent.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def bad_docx(p: Path) -> None:
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document")


def png(p: Path) -> None:
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    p.write_bytes(sig + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                  + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
                  + chunk(b"IEND", b""))


class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# ---------------------------------------------------------------------------
# F21 -- the month "May" is not an underclaim hedge
# ---------------------------------------------------------------------------
def test_f21_may_month() -> None:
    print("\n== F21: month 'May' vs the modal 'may' ==")
    check("a capitalised month is not an underclaim row",
          fmt.claim_strength_rows(
              ["In May 2020 the cohort showed a clear increase overall."]) == [])
    rows = fmt.claim_strength_rows(
        ["The data may support a larger effect than this study reports."])
    check("the lower-case modal verb is still an underclaim row",
          len(rows) == 1 and rows[0]["direction"] == "under"
          and rows[0]["markers"] == "may", str(rows))


# ---------------------------------------------------------------------------
# F24 -- the skill and the formatter agree on year-shaped ranges
# ---------------------------------------------------------------------------
def test_f24_year_range_parity() -> None:
    print("\n== F24: year-shaped ranges ==")
    check("the formatter treats a year range as no citation",
          fmt._marker_range_numbers(2019, 2020) == [])
    check("the skill's twin does the same",
          ec.parse_nums("2019-2020") == [], str(ec.parse_nums("2019-2020")))
    check("an ordinary citation range still expands on both sides",
          ec.parse_nums("12-14") == [12, 13, 14]
          and fmt._marker_range_numbers(12, 14) == [12, 13, 14])


# ---------------------------------------------------------------------------
# F40 -- decimals and percentages are not hidden by the integer floor
# ---------------------------------------------------------------------------
def test_f40_small_numbers() -> None:
    print("\n== F40: decimal/percent conflicts ==")
    check("a p-value decimal is kept", pp._conflict_numbers("p = 0.021") == {0.021})
    check("a percentage is kept", pp._conflict_numbers("5% vs 8%") == {5, 8})
    check("the integer floor still drops figure/check ids",
          pp._conflict_numbers("Fig. 3d in M4") == set())


# ---------------------------------------------------------------------------
# F28 -- validate_paths does not compile a symlinked .tex
# ---------------------------------------------------------------------------
def test_f28_tex_symlink() -> None:
    print("\n== F28: .tex symlinks ==")
    d = scratch("fixbugs30_f28_")
    (d / "real.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    (d / "link.tex").symlink_to("/etc/hostname")
    rep = fmt.validate_paths([d])
    files = [Path(r["file"]).name for r in rep["results"]]
    check("the symlinked .tex is not validated",
          files == ["real.tex"], str(files))


# ---------------------------------------------------------------------------
# F34 -- the p12 package scans do not open symlinked DOCX/PDF
# ---------------------------------------------------------------------------
def test_f34_package_scans() -> None:
    print("\n== F34: package scan symlinks ==")
    d = scratch("fixbugs30_f34_")
    root = d / "pkg"
    root.mkdir()
    outside = d / "outside"
    outside.mkdir()
    png(outside / "x.png")
    (outside / "x.docx").write_bytes(b"not read")
    (outside / "x.pdf").write_bytes(b"not read")
    (root / "leak.docx").symlink_to(outside / "x.docx")
    (root / "leak.pdf").symlink_to(outside / "x.pdf")
    seen = []
    real_paras = pp._docx_paragraphs
    real_tables = pp._docx_table_rows
    real_run = pp.run_bounded
    try:
        pp._docx_paragraphs = lambda p, *a, **k: seen.append(("paras", Path(p).name)) or []
        pp._docx_table_rows = lambda p, *a, **k: seen.append(("tables", Path(p).name)) or []
        pp.run_bounded = lambda argv, *a, **k: seen.append(
            ("pdf", Path(str(argv[-2])).name)) or (1, "", "")
        pp.package_front_matter_glue_rows(root)
        pp.affinity_definition_rows(root)
        pp.display_provenance_rows(root)
        pp.package_pdf_rows(root)
    finally:
        pp._docx_paragraphs = real_paras
        pp._docx_table_rows = real_tables
        pp.run_bounded = real_run
    check("none of the package scans opens the symlinked files",
          not any(n == "leak.docx" or n == "leak.pdf" for _kind, n in seen), str(seen))


# ---------------------------------------------------------------------------
# F36 -- a symlinked package file is not copied into a rebuilt package
# ---------------------------------------------------------------------------
def test_f36_template_package_files() -> None:
    print("\n== F36: template package files ==")
    d = scratch("fixbugs30_f36_")
    src = d / "src"
    src.mkdir()
    (src / "real.txt").write_text("ok\n", encoding="utf-8")
    (src / "leak.txt").symlink_to("/etc/hostname")
    names = [p.name for p in pp.template_package_files(src)]
    check("the symlink is not a package file", names == ["real.txt"], str(names))
    dst = d / "dst"
    pp._stage_source_package(dst, src)
    check("the staged source does not carry the link target",
          (dst / "real.txt").is_file() and not (dst / "leak.txt").exists(),
          str(sorted(p.name for p in dst.iterdir())))


# ---------------------------------------------------------------------------
# F49 -- a failed tool staging is reported, not swallowed
# ---------------------------------------------------------------------------
def test_f49_copy_session_tools() -> None:
    print("\n== F49: tool staging failure ==")
    d = scratch("fixbugs30_f49_")
    real = shutil.copyfile

    def boom(*a, **k):
        raise OSError("simulated disk full")

    try:
        shutil.copyfile = boom
        raised = ""
        try:
            pp._copy_session_tools(d)
        except RuntimeError as e:
            raised = str(e)
    finally:
        shutil.copyfile = real
    check("a staging OSError fails loudly", "could not stage" in raised
          and "disk full" in raised, raised)


# ---------------------------------------------------------------------------
# F50 -- artifact copies never follow a planted symlink
# ---------------------------------------------------------------------------
def test_f50_artifact_copy() -> None:
    print("\n== F50: artifact copies ==")
    d = scratch("fixbugs30_f50_")
    link = d / "findings_extra.md"
    link.symlink_to("/etc/hostname")
    dst = d / "out" / "findings_extra.md"
    wrote = pp._copy_bytes_if_different(link, dst)
    check("a symlinked artifact is not copied",
          wrote is False and not dst.exists(), str(wrote))
    real = d / "real.md"
    real.write_text("seed\n", encoding="utf-8")
    check("a real artifact still copies", pp._copy_bytes_if_different(real, dst) is True
          and dst.read_text(encoding="utf-8") == "seed\n")


# ---------------------------------------------------------------------------
# F60 -- an evidence link is followed only when it is the owning root's
# ---------------------------------------------------------------------------
def test_f60_evidence_link_containment() -> None:
    print("\n== F60: evidence-link containment ==")
    d = scratch("fixbugs30_f60_")
    root = d / "root"
    (root / "non_revised" / "raw_data").mkdir(parents=True)
    (root / "non_revised" / "raw_data" / "real.txt").write_text("real\n", encoding="utf-8")
    write(root / "state.json", "{}")
    outside = d / "outside" / "non_revised" / "raw_data"
    outside.mkdir(parents=True)
    (outside / "secret.txt").write_text("secret\n", encoding="utf-8")
    (root / "raw_data").symlink_to(outside, target_is_directory=True)
    files = [p.relative_to(root).as_posix()
             for p in pp._iter_tree_files(root, follow_dir_links=True)]
    check("an outside link shaped like an evidence area is refused",
          "raw_data/secret.txt" not in files, str(files))
    # A link that IS the root's canonical store is still followed.
    root2 = d / "root2"
    (root2 / "non_revised" / "raw_data").mkdir(parents=True)
    (root2 / "non_revised" / "raw_data" / "real.txt").write_text("real\n", encoding="utf-8")
    write(root2 / "state.json", "{}")
    (root2 / "raw_data").symlink_to(root2 / "non_revised" / "raw_data",
                                    target_is_directory=True)
    names = [p.relative_to(root2).as_posix()
             for p in pp._iter_tree_files(root2, follow_dir_links=True)]
    check("the canonical evidence link is still followed",
          "raw_data/real.txt" in names, str(names))
    # A materialized copy OUTSIDE every run root keeps the documented
    # target-shape fallback (the evidence-symlink design depends on it).
    mat = d / "materialized"
    mat.mkdir()
    (mat / "raw_data").symlink_to(root2 / "non_revised" / "raw_data",
                                  target_is_directory=True)
    names = [p.relative_to(mat).as_posix()
             for p in pp._iter_tree_files(mat, follow_dir_links=True)]
    check("a materialized evidence link outside a run root is followed",
          "raw_data/real.txt" in names, str(names))


# ---------------------------------------------------------------------------
# F37 -- Zotero DOCX readers honour the part budget and refuse DTDs
# ---------------------------------------------------------------------------
def test_f37_zotero_part_guard() -> None:
    print("\n== F37: Zotero part guard ==")
    d = scratch("fixbugs30_f37_")
    big = d / "big.docx"
    with zipfile.ZipFile(big, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
        z.writestr("word/footnotes.xml", "<w:footnotes>" + ("A" * 4000) + "</w:footnotes>")
    real_cap = fmt.MAX_DOCX_PART_BYTES
    try:
        fmt.MAX_DOCX_PART_BYTES = 512
        rep = fmt.zotero_report_for_docx(big)
    finally:
        fmt.MAX_DOCX_PART_BYTES = real_cap
    check("an over-budget part is reported, not decompressed",
          any("limit" in e for e in rep.get("errors") or []), str(rep.get("errors")))
    dtd = d / "dtd.docx"
    with zipfile.ZipFile(dtd, "w") as z:
        z.writestr("word/document.xml",
                   '<!DOCTYPE x [<!ENTITY a "b">]><w:document/>')
    rep2 = fmt.zotero_report_for_docx(dtd)
    check("an XML DTD/entity declaration is refused",
          any("DTD/entity" in e or "ENTITY" in e for e in rep2.get("errors") or []),
          str(rep2.get("errors")))


# ---------------------------------------------------------------------------
# F38 -- PDF helper output is bounded (no capture_output)
# ---------------------------------------------------------------------------
def test_f38_bounded_pdf_output() -> None:
    print("\n== F38: bounded PDF tool output ==")
    d = scratch("fixbugs30_f38_")
    binp = d / "bin"
    binp.mkdir()
    fake = binp / "pdftotext"
    write(fake, "#!/usr/bin/env python3\nimport sys\nsys.stdout.write('x' * 5000)\n")
    fake.chmod(0o755)
    pdf = d / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    real_cap = getattr(fmt, "MAX_TOOL_OUTPUT_BYTES", None)
    real_path = os.environ.get("PATH", "")
    try:
        fmt.MAX_TOOL_OUTPUT_BYTES = 64
        os.environ["PATH"] = str(binp) + os.pathsep + real_path
        res = fmt.check_pdf(pdf, {})
    finally:
        if real_cap is not None:
            fmt.MAX_TOOL_OUTPUT_BYTES = real_cap
        os.environ["PATH"] = real_path
    evidence = " ".join(str(r.get("evidence") or "") for r in res.get("rows") or [])
    check("the over-budget child is named instead of allocated",
          res.get("ok") is False and "over 64 bytes" in evidence,
          f"ok={res.get('ok')} evidence={evidence[:160]}")


# ---------------------------------------------------------------------------
# F26 -- zotero-check / zotero-refresh refuse a malformed DOCX
# ---------------------------------------------------------------------------
def test_f26_zotero_malformed() -> None:
    print("\n== F26: malformed DOCX is not CLEAN ==")
    d = scratch("fixbugs30_f26_")
    bad = d / "bad.docx"
    bad_docx(bad)
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = fmt.cmd_zotero_check(Args(file=str(bad), json=None))
    check("zotero-check exits 1", rc == 1, f"rc={rc} out={out.getvalue()[:120]}")
    rc2 = fmt.cmd_zotero_refresh(Args(file=str(bad), out=None, policy=None,
                                      unlink=False, json=None))
    check("zotero-refresh exits 1", rc2 == 1, f"rc={rc2}")


# ---------------------------------------------------------------------------
# F66 / F68 -- scan-figures: honest summary and a parsed term source
# ---------------------------------------------------------------------------
def test_f66_f68_scan_figures() -> None:
    print("\n== F66/F68: scan-figures ==")
    d = scratch("fixbugs30_f66_")
    figs = d / "figs"
    figs.mkdir()
    png(figs / "f.png")
    buf = []

    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = fmt.cmd_scan_figures(Args(paths=[str(figs)], from_docx=None, terms=None,
                                       json=None, strict=False))
    text = out.getvalue()
    check("a clean figure scan does not claim an OOXML formatting pass",
          "OOXML formatting" not in text and "figure-label scan" in text, text[:160])
    check("the clean figure scan exits 0", rc == 0, f"rc={rc}")
    bad = d / "bad.docx"
    bad_docx(bad)
    out2 = io.StringIO()
    with contextlib.redirect_stdout(out2), contextlib.redirect_stderr(io.StringIO()):
        rc2 = fmt.cmd_scan_figures(Args(paths=[str(figs)], from_docx=[str(bad)],
                                        terms=None, json=None, strict=False))
    check("a malformed --from-docx source is a named error",
          rc2 == 2, f"rc={rc2}")


# ---------------------------------------------------------------------------
# F07 -- the deletion audit enforces its disposition vocabulary
# ---------------------------------------------------------------------------
def test_f07_deletion_audit_vocabulary() -> None:
    print("\n== F07: deletion-audit dispositions ==")
    d = scratch("fixbugs30_f07_")
    (d / "revision_audit").mkdir()
    rows = [{"document": "m.md", "line": 3,
             "paragraph": "A fact-bearing paragraph."}]
    p = d / "revision_audit" / "DELETED_PARAGRAPHS.md"
    p.write_text(pp.deletion_audit_markdown(rows), encoding="utf-8")
    probs = pp.deletion_audit_problems(d)
    check("an empty seed is still reported", bool(probs), str(probs))
    p.write_text(pp.deletion_audit_markdown(rows).replace(
        "|  |", "| x |", 1), encoding="utf-8")
    probs = pp.deletion_audit_problems(d)
    check("a one-word 'x' disposition is rejected",
          any("outside the seeded vocabulary" in q for q in probs), str(probs))
    p.write_text(pp.deletion_audit_markdown(rows).replace(
        "|  |", "| OK — the fact survives in Sec. 2 of m.md |", 1), encoding="utf-8")
    check("the documented OK form passes", pp.deletion_audit_problems(d) == [],
          str(pp.deletion_audit_problems(d)))


# ---------------------------------------------------------------------------
# F12 -- the revision ledger requires a documented verdict
# ---------------------------------------------------------------------------
def test_f12_ledger_verdict() -> None:
    print("\n== F12: revision-ledger verdicts ==")
    d = scratch("fixbugs30_f12_")
    pkg = d / "pkg"
    pkg.mkdir()

    def errs_for(payload):
        write(pkg / "revision_report.json", json.dumps(payload))
        return pp.revision_ledger_problems(pkg, ["F-001"], 1)[0]

    check("an undocumented verdict string is rejected",
          any("without a VERDICT" in e for e in errs_for(
              [{"id": "F-001", "verdict": "whatever", "rationale": "x"}])),
          str(errs_for([{"id": "F-001", "verdict": "whatever", "rationale": "x"}])))
    check("a documented verdict passes",
          errs_for([{"id": "F-001", "verdict": "confirmed", "rationale": "x"}]) == [])
    check("a documented final status passes",
          errs_for([{"id": "F-001", "final_status": "fixed-with-caveat",
                     "rationale": "x"}]) == [])


# ---------------------------------------------------------------------------
# F10 / F11 -- the review contract validates fields and dispositions
# ---------------------------------------------------------------------------
def _review_sandbox(d: Path) -> Path:
    sb = d / "sb"
    (sb / "base").mkdir(parents=True)
    return sb


def _coverage() -> list:
    ids = [f"M{i}" for i in range(1, 37)] + [f"J{i}" for i in range(1, 6)]
    return [{"check": c, "disposition": "clean -- basis: fixture artifact"} for c in ids]


def test_f10_review_finding_fields() -> None:
    print("\n== F10: review finding fields ==")
    d = scratch("fixbugs30_f10_")
    sb = _review_sandbox(d)
    fj = {"submission_dir": "./base",
          "findings": [{"id": "F-001", "location": "", "check": "M1",
                        "evidence": "", "explanation": "", "category": 9,
                        "severity": "huge"}],
          "coverage": _coverage()}
    errs = []
    pp.check_review_contract(None, sb, fj, errs, [], split="off")
    joined = " ".join(errs)
    check("a malformed finding is reported",
          "malformed finding" in joined and "F-001" in joined, joined[:240])
    check("the category, severity and missing fields are named",
          all(k in joined for k in ("severity", "category", "location", "evidence",
                                    "explanation")), joined[:240])


def test_f11_coverage_disposition() -> None:
    print("\n== F11: coverage dispositions ==")
    d = scratch("fixbugs30_f11_")
    sb = _review_sandbox(d)
    fj = {"submission_dir": "./base", "findings": [], "coverage": _coverage()}
    fj["coverage"][0]["disposition"] = "x"
    errs = []
    pp.check_review_contract(None, sb, fj, errs, [], split="off")
    check("a filler disposition is rejected",
          any("real disposition" in e for e in errs), str(errs)[:240])
    fj["coverage"][0]["disposition"] = "0 findings -- nothing in this class"
    errs = []
    pp.check_review_contract(None, sb, fj, errs, [], split="off")
    check("a documented disposition passes",
          not any("real disposition" in e for e in errs), str(errs)[:240])


# ---------------------------------------------------------------------------
# F13 -- setup refuses a tree without the companion modules
# ---------------------------------------------------------------------------
def test_f13_setup_missing_modules() -> None:
    print("\n== F13: setup refuses a missing formatter ==")
    d = scratch("fixbugs30_f13_")
    co = d / "checkout"
    co.mkdir()
    shutil.copy2(WS / "paper_pipeline.py", co / "paper_pipeline.py")
    for name in ("paper_pipeline_parts", "paper_docx_format_parts"):
        shutil.copytree(WS / name, co / name,
                        ignore=shutil.ignore_patterns("__pycache__"))
    src = d / "source"
    src.mkdir()
    write(src / "manuscript.md", "# Title\n\nSome text.\n")
    r = subprocess.run([sys.executable, str(co / "paper_pipeline.py"), "setup",
                        "--source", str(src), "--root", str(d / "root")],
                       capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
    check("setup exits non-zero", r.returncode != 0, f"rc={r.returncode} out={out[-200:]}")
    check("the missing module is named",
          "paper_docx_format.py" in out, out[-300:])


# ---------------------------------------------------------------------------
# F14 -- page budgets come from the venue profile, not the prompt constant
# ---------------------------------------------------------------------------
def test_f14_page_budget_source() -> None:
    print("\n== F14: page budgets are venue rules ==")
    rule = pp.defect_class_rule()
    check("the default profile names the missing page budget as a gap",
          "NO PAGE BUDGET IS A RULE THIS VENUE STATED" in rule
          and "at most TWO pages" not in rule)
    vis = pp.visual_inspection_block("out/visual.md")
    check("the visual block names the gap",
          "states NO page budget" in vis and "at most TWO pages" not in vis)
    prof = pp.VenueProfile({"id": "pbfix", "label": "PB fix",
                            "page_budget": {"front_page_keywords": True,
                                            "cover_letter_max_pages": 2,
                                            "source": "author guidelines p.4"}})
    declared = pp.defect_class_rule(prof)
    check("a profile that states the rule gets it asserted with its source",
          "at most 2 page(s)" in declared and "the FRONT PAGE must carry" in declared
          and "author guidelines p.4" in declared, declared[:240])
    check("the standing exemptions use the same gated rule",
          "at most 2 page(s)" in pp.standing_exemptions_text(prof)
          and "states no page budget" in pp.standing_exemptions_text())


# ---------------------------------------------------------------------------
# F08 -- the revision-audit stub disposes the seeded deletion table
# ---------------------------------------------------------------------------
def test_f08_revision_audit_stub() -> None:
    print("\n== F08: revision-audit stub ==")
    d = scratch("fixbugs30_f08_")
    rows = [{"document": "m.md", "line": 3,
             "paragraph": "A fact-bearing paragraph the revision removed."}]
    write(d / "revision_audit" / "DELETED_PARAGRAPHS.md",
          pp.deletion_audit_markdown(rows))
    stub._revision_audit_stub(d)
    check("the stub disposes every seeded deletion row",
          pp.deletion_audit_problems(d) == [], str(pp.deletion_audit_problems(d)))


# ---------------------------------------------------------------------------
# R02 -- a malformed page_budget block is refused, not silently dropped
# ---------------------------------------------------------------------------
def test_r02_page_budget_validation() -> None:
    print("\n== R02: page_budget validation ==")
    base = json.loads((WS / "venue_profiles" / "generic.json").read_text(encoding="utf-8"))
    cases = (({"page_budget": "two pages"}, "must be an object"),
             ({"page_budget": {"cover_letter_max_pages": "two", "source": "x"}},
              "must be an integer"),
             ({"page_budget": {"front_page_keywords": True}}, "source is required"),
             ({"page_budget": {"front_page_keywords": "yes", "source": "x"}},
              "must be true or false"))
    for bad, needle in cases:
        data = dict(base)
        data.update(bad)
        try:
            pp.normalize_venue_profile(data, "r02")
            ok, detail = False, "accepted"
        except pp.VenueProfileError as e:
            ok, detail = needle in str(e), str(e)
        check(f"an invalid page_budget is refused: {sorted(bad['page_budget']) if isinstance(bad['page_budget'], dict) else bad['page_budget']}",
              ok, detail)
    data = dict(base)
    data["page_budget"] = {"front_page_keywords": True, "cover_letter_max_pages": 2,
                           "source": "author guidelines p.4"}
    got = pp.normalize_venue_profile(data, "r02")["page_budget"]
    check("a valid page_budget is carried with its source",
          got == data["page_budget"], str(got))


# ---------------------------------------------------------------------------
# R03 -- refresh and the Zotero style parts refuse a DTD/entity part
# ---------------------------------------------------------------------------
def test_r03_zotero_dtd_parts() -> None:
    print("\n== R03: Zotero refresh/style part DTD ==")
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    good = f'<w:document {w}><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>'
    dtd = f'<!DOCTYPE x [<!ENTITY a "b">]><w:document {w}/>'
    d = scratch("fixbugs30_r03_")

    def make(name, main, settings=None):
        p = d / name
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("word/document.xml", main)
            if settings is not None:
                z.writestr("word/settings.xml", settings)
        return p

    rep = fmt.refresh_zotero_package(make("main.docx", dtd))
    check("refresh refuses a DTD-bearing main part",
          rep.get("ok") is False and "DTD" in str(rep.get("skip")), str(rep.get("skip")))
    rep = fmt.zotero_report_for_docx(
        make("style.docx", good, f'<!DOCTYPE x [<!ENTITY a "b">]><w:settings {w}/>'))
    check("the style-part reader reports a DTD-bearing part",
          any("DTD" in e for e in rep.get("errors") or []), str(rep.get("errors")))


# ---------------------------------------------------------------------------
# R04 -- leading-dot decimals and spaced percentages are quantitative tokens
# ---------------------------------------------------------------------------
def test_r04_number_tokens() -> None:
    print("\n== R04: small number tokens ==")
    check("a leading-dot decimal is kept", pp._conflict_numbers("p = .05") == {0.05},
          str(pp._conflict_numbers("p = .05")))
    check("a pair of leading-dot decimals is kept",
          pp._conflict_numbers(".05 vs .50") == {0.05, 0.5},
          str(pp._conflict_numbers(".05 vs .50")))
    check("a percentage written with a space is kept",
          pp._conflict_numbers("5 % vs 8 %") == {5, 8},
          str(pp._conflict_numbers("5 % vs 8 %")))
    check("integer ids still hit the floor", pp._conflict_numbers("M4 and Fig. 3d") == set(),
          str(pp._conflict_numbers("M4 and Fig. 3d")))


# ---------------------------------------------------------------------------
# R05 -- the two p04 conform prompts pass the venue profile
# ---------------------------------------------------------------------------
def test_r05_conform_prompts() -> None:
    print("\n== R05: conform prompts carry the page budget ==")
    d = scratch("fixbugs30_r05_")
    src = d / "src"
    src.mkdir()
    (src / "m.docx").write_bytes(b"x")
    data = json.loads((WS / "venue_profiles" / "generic.json").read_text(encoding="utf-8"))
    data["page_budget"] = {"front_page_keywords": True, "cover_letter_max_pages": 2,
                           "source": "author guidelines p.4"}
    ctx = types.SimpleNamespace(cfg={"venue": "generic", "venue_profile": data}, root=d)
    for label, prompt in (
            ("guideline-conform", pp.apply_guideline_conform_prompt(ctx, src)),
            ("template-first", pp.apply_template_prompt(ctx, d, src, {"main": None}))):
        check(f"{label} asserts the declared page budget",
              "at most 2 page(s)" in prompt and "states NO page budget" not in prompt,
              prompt[:160])


# ---------------------------------------------------------------------------
# R06 -- FMT-T8g/T8h are venue-gated, not unconditional
# ---------------------------------------------------------------------------
def _page_rule_docx(path: Path, split_front: bool, pages: int) -> None:
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    brk = "<w:lastRenderedPageBreak/>" if split_front else ""
    doc = (f'<w:document {w}><w:body>'
           '<w:p><w:r><w:t>CopyNumBench: a benchmark</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Authors: A, B and C</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Abstract</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Copy-number callers diverge, so we benchmark them.</w:t></w:r></w:p>'
           f'<w:p><w:r>{brk}<w:t>Keywords: copy-number, benchmark.</w:t></w:r></w:p>'
           '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Introduction</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Body text here.</w:t></w:r></w:p>'
           '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>')
    app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
           '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
           f'extended-properties"><Pages>{pages}</Pages></Properties>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("_rels/.rels", "<Relationships/>")
        z.writestr("word/document.xml", doc)
        z.writestr("docProps/app.xml", app)


def test_r06_page_rules_are_profile_gated() -> None:
    print("\n== R06: FMT-T8g/T8h follow the venue profile ==")
    d = scratch("fixbugs30_r06_")
    letter = d / "Cover_Letter.docx"
    main = d / "main.docx"
    _page_rule_docx(letter, split_front=False, pages=3)
    _page_rule_docx(main, split_front=True, pages=1)
    bare = dict(fmt.POLICY_DEFAULTS)
    rows = fmt.analyse_package(letter, bare)["rows"] + fmt.analyse_package(main, bare)["rows"]
    check("a policy with no page_budget files no page-budget row",
          not [r for r in rows if r["rule"] in ("FMT-T8g", "FMT-T8h")],
          str([r["rule"] for r in rows]))
    declared = dict(bare, page_budget={"front_page_keywords": True,
                                       "cover_letter_max_pages": 2,
                                       "source": "author guidelines p.4"})
    lrows = fmt.analyse_package(letter, declared)["rows"]
    mrows = fmt.analyse_package(main, declared)["rows"]
    hit = [r for r in lrows if r["rule"] == "FMT-T8h"]
    check("a declared cover-letter budget files FMT-T8h against that budget",
          bool(hit) and "budget is 2" in hit[0]["evidence"], str(hit))
    check("a declared front-page rule files FMT-T8g",
          any(r["rule"] == "FMT-T8g" for r in mrows), str([r["rule"] for r in mrows]))
    data = json.loads((WS / "venue_profiles" / "generic.json").read_text(encoding="utf-8"))
    data["page_budget"] = {"front_page_keywords": True, "cover_letter_max_pages": 2,
                           "source": "author guidelines p.4"}
    ctx = types.SimpleNamespace(cfg={"venue": "generic", "venue_profile": data}, root=d)
    check("format_policy_of carries the profile's page budget",
          pp.format_policy_of(ctx).get("page_budget") == data["page_budget"],
          str(pp.format_policy_of(ctx).get("page_budget")))


# ---------------------------------------------------------------------------
# R07 -- scan-figures --from-docx uses the guarded DOCX part reader
# ---------------------------------------------------------------------------
def test_r07_scan_figures_part_budget() -> None:
    print("\n== R07: scan-figures --from-docx part budget ==")
    d = scratch("fixbugs30_r07_")
    terms = d / "terms.docx"
    with zipfile.ZipFile(terms, "w") as z:
        z.writestr("word/document.xml",
                   '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
                   '2006/main"><w:body><w:p><w:r><w:t>' + "A" * 5000
                   + '</w:t></w:r></w:p></w:body></w:document>')
    figs = d / "figs"
    figs.mkdir()
    png(figs / "f.png")
    args = Args(paths=[str(figs)], from_docx=[str(terms)], terms=None, json=None,
                strict=False)
    real = fmt.MAX_DOCX_PART_BYTES
    try:
        fmt.MAX_DOCX_PART_BYTES = 100
        rc = fmt.cmd_scan_figures(args)
    finally:
        fmt.MAX_DOCX_PART_BYTES = real
    check("an over-budget --from-docx part is a named error (rc 2)", rc == 2, f"rc={rc}")


# ---------------------------------------------------------------------------
# R08 -- pdfinfo/OCR/convert output goes through the bounded runner
# ---------------------------------------------------------------------------
def test_r08_tool_output_caps() -> None:
    print("\n== R08: pdfinfo/OCR/convert output caps ==")
    d = scratch("fixbugs30_r08_")
    for tool, body in (("tesseract", 'python3 -c \'print("A"*5000)\'\n'),
                       ("pdfinfo", 'python3 -c \'print("A"*5000)\'\nprintf "Form: XFA\\n"\n'),
                       ("convert", 'python3 -c \'print("A"*5000)\'\n')):
        p = d / tool
        write(p, "#!/bin/sh\n" + body)
        p.chmod(0o755)
    real_cap, real_path = fmt.MAX_TOOL_OUTPUT_BYTES, os.environ.get("PATH", "")
    try:
        fmt.MAX_TOOL_OUTPUT_BYTES = 64
        os.environ["PATH"] = str(d) + ":" + real_path
        check("over-budget tesseract output is not returned",
              fmt._ocr_text(d / "f.png") is None, str(fmt._ocr_text(d / "f.png")))
        check("over-budget pdfinfo output is not parsed",
              fmt._pdfinfo_form(d / "f.pdf") == "", repr(fmt._pdfinfo_form(d / "f.pdf")))
        # A short OCR pass plus an over-budget convert: only the base pass survives.
        write(d / "tesseract", "#!/bin/sh\nprintf 'ok\\n'\n")
        (d / "tesseract").chmod(0o755)
        variants = fmt._ocr_text_variants(d / "f.png")
        check("over-budget convert output is not used",
              [v.strip() for v in (variants or [])] == ["ok"], str(variants))
    finally:
        fmt.MAX_TOOL_OUTPUT_BYTES = real_cap
        os.environ["PATH"] = real_path


# ---------------------------------------------------------------------------
# R10 -- an old snapshot inherits a page budget added to the profile file
# ---------------------------------------------------------------------------
def test_r10_page_budget_snapshot() -> None:
    print("\n== R10: page_budget snapshot inheritance ==")
    d = scratch("fixbugs30_r10_")
    base = json.loads((WS / "venue_profiles" / "generic.json").read_text(encoding="utf-8"))
    declared = dict(base, page_budget={"front_page_keywords": True,
                                       "cover_letter_max_pages": 2,
                                       "source": "author guidelines p.4"})
    write(d / "venue_profiles" / "generic.json", json.dumps(declared))
    write(d / "state.json", "{}")
    snapshot = dict(base)
    snapshot.pop("page_budget", None)
    prof = pp._snapshot_profile({"venue": "generic", "venue_profile": snapshot},
                                "generic", root=d)
    check("an old snapshot inherits the profile's page budget",
          bool(prof) and prof.data.get("page_budget") == declared["page_budget"],
          str(prof.data.get("page_budget") if prof else None))
    explicit = pp._snapshot_profile(
        {"venue": "generic", "venue_profile": dict(snapshot, page_budget=None)},
        "generic", root=d)
    check("an explicit null snapshot block still wins",
          bool(explicit) and explicit.data.get("page_budget") is None,
          str(explicit.data.get("page_budget") if explicit else None))


def main() -> int:
    tests = (test_f07_deletion_audit_vocabulary, test_f08_revision_audit_stub,
             test_f10_review_finding_fields, test_f11_coverage_disposition,
             test_f12_ledger_verdict, test_f13_setup_missing_modules,
             test_f14_page_budget_source, test_f21_may_month,
             test_f24_year_range_parity, test_f26_zotero_malformed,
             test_f28_tex_symlink, test_f34_package_scans,
             test_f36_template_package_files, test_f37_zotero_part_guard,
             test_f38_bounded_pdf_output, test_f49_copy_session_tools,
             test_f50_artifact_copy, test_f60_evidence_link_containment,
             test_f66_f68_scan_figures, test_f40_small_numbers,
             test_r02_page_budget_validation, test_r03_zotero_dtd_parts,
             test_r04_number_tokens, test_r05_conform_prompts,
             test_r06_page_rules_are_profile_gated,
             test_r07_scan_figures_part_budget, test_r08_tool_output_caps,
             test_r10_page_budget_snapshot)
    for fn in tests:
        try:
            fn()
        except Exception as e:                                      # noqa: BLE001
            check(f"{fn.__name__} completed", False, f"{type(e).__name__}: {e}")
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL FIX-BUGS REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

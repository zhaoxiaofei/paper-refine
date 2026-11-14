#!/usr/bin/env python3
"""Regression checks for the 2026-11-15 fix-bugs wave 2, group `docx_report`.

Candidates F52/F53/F54/F57/F58/F60/F61/F62/F63 (all in
paper_docx_format_parts/p03_report_cli.py). Every fixture is hermetic under
tempfile.mkdtemp(); CLI checks drive paper_docx_format.py as a subprocess so a
hang (the FIFO defect) is a failed check, not a wedged suite.

Run:  python3 .paper_test/test_fix_bugs_20261115_wave2_docx_report.py
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
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
TMPDIRS = []
FAILS = []
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

spec = importlib.util.spec_from_file_location(
    "fb1115wave2_docx_fmt", str(WS / "paper_docx_format.py"))
fmt = importlib.util.module_from_spec(spec)
sys.modules["fb1115wave2_docx_fmt"] = fmt
spec.loader.exec_module(fmt)


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def fmt_cli(*args, cwd=None, timeout=60):
    return subprocess.run([sys.executable, str(WS / "paper_docx_format.py"), *args],
                          cwd=str(cwd or WS), capture_output=True, text=True,
                          timeout=timeout)


# ---------------------------------------------------------------------------
# minimal DOCX fixture
# ---------------------------------------------------------------------------
CT = ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      '<Default Extension="xml" ContentType="application/xml"/>'
      '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
      '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
      '</Types>')
RELS = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>')


def para(text: str = "", style: str = None, runs: str = None) -> str:
    pr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    body = runs if runs is not None else f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'
    return f"<w:p>{pr}{body}</w:p>"


def make_docx(path: Path, paras, extra_styles: str = "",
              settings: str = None) -> Path:
    path = Path(path)
    style_xml = (f'<w:styles xmlns:w="{W}">'
                 f'<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
                 f'<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
                 f'{extra_styles}</w:styles>')
    doc = f'<w:document xmlns:w="{W}"><w:body>{"".join(paras)}</w:body></w:document>'
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", style_xml)
        if settings is not None:
            z.writestr("word/settings.xml", settings)
    return path


def xfa_pdf_bytes() -> bytes:
    body = b"xfa:datasets <xfa:datasets><author>Alice</author></xfa:datasets>"
    return (b"%PDF-1.4\n1 0 obj\n<< >>\nstream\n" + body
            + b"\nendstream\nendobj\ntrailer\n%%EOF\n")


# ---------------------------------------------------------------------------
# F52 -- writers must not overwrite their input or follow a symlink at --out
# ---------------------------------------------------------------------------
def test_f52_output_guards() -> None:
    print("\n== F52: xfa-export / repair-layout output guards ==")
    d = scratch("fixbugs1115w2_f52_")
    form = d / "form.pdf"
    form.write_bytes(xfa_pdf_bytes())
    same = d / "same.pdf"
    same.write_bytes(form.read_bytes())
    res = fmt_cli("xfa-export", str(same), "--out", str(same), cwd=d)
    check("F52 xfa-export refuses --out == input (exit 2)",
          res.returncode == 2, f"rc={res.returncode} err={res.stderr[-200:]}")
    check("F52 the input PDF is byte-identical after the refusal",
          same.read_bytes() == form.read_bytes(), "input was replaced")

    victim = d / "victim.txt"
    victim.write_text("VICTIM\n", encoding="utf-8")
    link = d / "answers.txt"
    link.symlink_to(victim)
    res = fmt_cli("xfa-export", str(form), "--out", str(link), cwd=d)
    check("F52 xfa-export refuses a symlink at --out (exit 2)",
          res.returncode == 2, f"rc={res.returncode}")
    check("F52 the symlink target is untouched",
          victim.read_text(encoding="utf-8") == "VICTIM\n",
          victim.read_text(encoding="utf-8")[:40])

    clean = make_docx(d / "clean.docx", [para("Hello world.")])
    victim2 = d / "victim2.txt"
    victim2.write_text("VICTIM2\n", encoding="utf-8")
    out_link = d / "repaired.docx"
    out_link.symlink_to(victim2)
    rep = fmt.repair_layout_package(clean, out_link, dict(fmt.POLICY_DEFAULTS))
    check("F52 a clean repair refuses a symlink at OUT",
          not rep.get("ok") and "symlink" in str(rep.get("error") or "").lower(),
          str(rep.get("error")))
    check("F52 the repair symlink target is untouched",
          victim2.read_text(encoding="utf-8") == "VICTIM2\n",
          victim2.read_text(encoding="utf-8")[:40])


# ---------------------------------------------------------------------------
# F53 -- FIFOs / non-regular files are input errors, never a blocking read
# ---------------------------------------------------------------------------
def test_f53_special_files() -> None:
    print("\n== F53: FIFO/special-file input guards ==")
    if not hasattr(os, "mkfifo"):
        check("F53 platform has mkfifo", True, "skipped: no mkfifo")
        return
    d = scratch("fixbugs1115w2_f53_")
    fifo = d / "trap.docx"
    os.mkfifo(fifo)
    try:
        res = fmt_cli("scan", str(d), cwd=d, timeout=20)
        check("F53 scan of a directory holding a FIFO returns (no hang)",
              res.returncode != 124, f"rc={res.returncode}")
        check("F53 scan refuses the non-regular named input (exit 2)",
              res.returncode == 2, f"rc={res.returncode} err={res.stderr[-160:]}")
        res = fmt_cli("validate", str(d), cwd=d, timeout=20)
        check("F53 validate of a FIFO directory returns (no hang)",
              res.returncode != 124, f"rc={res.returncode}")
        res = fmt_cli("scan", str(fifo), cwd=d, timeout=20)
        check("F53 an explicitly named FIFO .docx is a clean input error",
              res.returncode == 2, f"rc={res.returncode} err={res.stderr[-160:]}")
        # The shared reader reports FMT-X1 instead of opening the FIFO.
        res = fmt.analyse_package(fifo, dict(fmt.POLICY_DEFAULTS))
        check("F53 analyse_package reports FMT-X1 for a FIFO",
              [r["rule"] for r in res["rows"]] == ["FMT-X1"],
              str([r["rule"] for r in res["rows"]]))
        pdf_fifo = d / "trap.pdf"
        os.mkfifo(pdf_fifo)
        res = fmt_cli("check-pdf", str(pdf_fifo), cwd=d, timeout=20)
        check("F53 check-pdf on a FIFO returns instead of blocking",
              res.returncode != 124 and res.returncode != 0,
              f"rc={res.returncode}")
    finally:
        for p in (fifo, d / "trap.pdf"):
            try:
                if p.exists() or p.is_symlink():
                    p.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# F54 -- one reference-list definition for scan AND fix (template restyle)
# ---------------------------------------------------------------------------
def test_f54_restyled_references() -> None:
    print("\n== F54: restyled reference list is classified as references ==")
    d = scratch("fixbugs1115w2_f54_")
    ref_style = ('<w:style w:type="paragraph" w:styleId="RefsCustom">'
                 '<w:name w:val="References"/></w:style>')
    journal_run = ('<w:r><w:t xml:space="preserve">1. Smith J. (2020) A study. </w:t></w:r>'
                   '<w:r><w:rPr><w:i/></w:rPr><w:t>Nature Methods</w:t></w:r>'
                   '<w:r><w:t xml:space="preserve"> 5: 1-2.</w:t></w:r>')
    spaced_run = ('<w:r><w:t xml:space="preserve"> 2. Doe A. (2021) Another. </w:t></w:r>'
                  '<w:r><w:rPr><w:i/></w:rPr><w:t>Cell</w:t></w:r>'
                  '<w:r><w:t xml:space="preserve"> 3: 4.</w:t></w:r>')
    src = make_docx(d / "restyled.docx", [
        para("Introduction", "Heading1"),
        para("We used methods described before."),
        para("References", "Heading1"),
        para("", "RefsCustom", runs=journal_run),
        para("", "RefsCustom", runs=spaced_run),
    ], extra_styles=ref_style)
    policy = dict(fmt.POLICY_DEFAULTS)
    res = fmt.analyse_package(src, policy)
    rules = [r["rule"] for r in res["rows"]]
    check("F54 a restyled reference list is not FMT-T6c prose",
          "FMT-T6c" not in rules, str(rules))
    check("F54 the leading space inside the restyled list is not FMT-P4",
          "FMT-P4" not in rules, str(rules))
    out = d / "fixed.docx"
    rep = fmt.fix_package(src, out, policy)
    check("F54 fix accepts its own restyled-reference scan", bool(rep.get("ok")),
          str(rep.get("error")))
    with zipfile.ZipFile(out) as z:
        fixed_xml = z.read("word/document.xml").decode("utf-8", "replace")
    check("F54 the reference journal titles keep their italics",
          '<w:i/>' in fixed_xml and 'w:i w:val="0"' not in fixed_xml,
          "an italic was cleared in the reference list")

    # The finding-tier reference rules must also fire on the restyled list.
    src2 = make_docx(d / "restyled2.docx", [
        para("References", "Heading1"),
        para("", "RefsCustom", runs='<w:r><w:t xml:space="preserve">1. Poe A. (2021) '
                                    'A study. Cell 3: 4.</w:t></w:r>'),
        para("", "RefsCustom", runs='<w:r><w:t xml:space="preserve">2. Roe B. </w:t></w:r>'
                                    '<w:r><w:rPr><w:b/></w:rPr><w:t>(2022)</w:t></w:r>'
                                    '<w:r><w:t xml:space="preserve"> Title. Lancet 9: 8.'
                                    '</w:t></w:r>'),
    ], extra_styles=ref_style)
    rules2 = [r["rule"] for r in fmt.analyse_package(src2, policy)["rows"]]
    check("F54 FMT-T6d fires on a restyled reference with no italic title",
          "FMT-T6d" in rules2, str(rules2))
    check("F54 FMT-T6h fires on a bold year in the restyled list",
          "FMT-T6h" in rules2, str(rules2))


# ---------------------------------------------------------------------------
# F57 -- scan-figures reports a gap, not a clean pass, when nothing was read
# ---------------------------------------------------------------------------
def test_f57_scan_figures_gaps() -> None:
    print("\n== F57: scan-figures unreadable/absent figure ==")
    d = scratch("fixbugs1115w2_f57_")
    broken = d / "broken.png"
    broken.write_bytes(b"not a real png\n")
    res = fmt_cli("scan-figures", str(broken), "--strict", "--json",
                  str(d / "fig.json"), cwd=d)
    check("F57 a corrupt figure under --strict exits 1",
          res.returncode == 1, f"rc={res.returncode} out={res.stdout[-160:]}")
    if (d / "fig.json").is_file():
        rows = json.loads((d / "fig.json").read_text(encoding="utf-8"))["rows"]
        check("F57 the unreadable figure yields an FMT-IM5 gap row",
              any(r["rule"] == "FMT-IM5" for r in rows), str(rows))
    else:
        check("F57 scan-figures wrote the --json report", False, "missing fig.json")
    res = fmt_cli("scan-figures", str(d / "notes.md"), "--strict", cwd=d)
    check("F57 an explicitly named non-image is an input error (exit 2)",
          res.returncode == 2, f"rc={res.returncode}")
    empty = d / "empty"
    empty.mkdir()
    res = fmt_cli("scan-figures", str(empty), "--strict", cwd=d)
    check("F57 an empty figure directory is NOT CHECKED (exit 2, not 0)",
          res.returncode == 2 and "not checked" in res.stdout,
          f"rc={res.returncode} out={res.stdout[-160:]}")


# ---------------------------------------------------------------------------
# F58 -- FMT-Z5 read catches encrypted/unsupported-compression entries
# ---------------------------------------------------------------------------
def _corrupt_settings_compression(p: Path) -> None:
    data = bytearray(p.read_bytes())
    with zipfile.ZipFile(p) as z:
        off = z.getinfo("word/settings.xml").header_offset
    data[off + 8:off + 10] = struct.pack("<H", 99)      # local header method
    name = b"word/settings.xml"
    idx = data.find(b"PK\x01\x02", 1)
    while idx >= 0:
        nl = struct.unpack_from("<H", data, idx + 28)[0]
        if bytes(data[idx + 46:idx + 46 + nl]) == name:
            data[idx + 10:idx + 12] = struct.pack("<H", 99)   # central dir
            break
        idx = data.find(b"PK\x01\x02", idx + 4)
    p.write_bytes(data)


def test_f58_z5_unsupported_entry() -> None:
    print("\n== F58: unreadable Zotero style store is a reported gap ==")
    d = scratch("fixbugs1115w2_f58_")
    src = make_docx(d / "badsettings.docx", [para("Hello.")],
                    settings=f'<w:settings xmlns:w="{W}"></w:settings>')
    _corrupt_settings_compression(src)
    raised = None
    try:
        res = fmt.analyse_package(src, dict(fmt.POLICY_DEFAULTS))
    except Exception as exc:                                    # noqa: BLE001
        raised = exc
        res = {"rows": []}
    check("F58 analyse_package does not raise on a bad settings entry",
          raised is None, repr(raised))
    check("F58 the unreadable style store is a named FMT-Z5 gap",
          any(r["rule"] == "FMT-Z5" and "could not be read" in r["evidence"]
              for r in res["rows"]),
          str([(r["rule"], r["evidence"][:50]) for r in res["rows"]]))
    out = fmt_cli("scan", str(d / "badsettings.docx"), cwd=d)
    check("F58 scan finishes without a traceback and reports the gap",
          out.returncode == 0 and "Traceback" not in out.stderr
          and "FMT-Z5" in out.stdout,
          f"rc={out.returncode} err={out.stderr[-200:]}")


# ---------------------------------------------------------------------------
# F60 -- a stray field end is a structural fault, never CLEAN
# ---------------------------------------------------------------------------
def test_f60_stray_field_end() -> None:
    print("\n== F60: zotero-check fails a structurally broken field ==")
    d = scratch("fixbugs1115w2_f60_")
    src = make_docx(d / "stray.docx", [
        para("", runs='<w:r><w:fldChar w:fldCharType="end"/></w:r>')])
    report = fmt.zotero_report_for_docx(src)
    faults = fmt.zotero_structural_faults(report)
    check("F60 end-outside-field is a structural fault",
          any("end-outside-field" in f for f in faults), str(report.get("errors")))
    res = fmt_cli("zotero-check", str(src), cwd=d)
    check("F60 zotero-check exits 1 on the stray field end",
          res.returncode == 1, f"rc={res.returncode}")
    check("F60 zotero-check does not print CLEAN on a stray field end",
          "CLEAN" not in res.stdout, res.stdout[-200:])
    check("F60 the fault is printed",
          "end-outside-field" in res.stdout, res.stdout[-200:])


# ---------------------------------------------------------------------------
# F61 -- validate ignores the same work/ scratch that scan does
# ---------------------------------------------------------------------------
def test_f61_work_scratch() -> None:
    print("\n== F61: validate/scan agree that work/ is not a deliverable ==")
    d = scratch("fixbugs1115w2_f61_")
    make_docx(d / "main.docx", [para("Hello world.")])
    (d / "work").mkdir()
    (d / "work" / "scratch.docx").write_bytes(b"not a zip\n")
    scan = fmt.scan_paths([d], dict(fmt.POLICY_DEFAULTS))
    check("F61 scan sees exactly the deliverable", len(scan["files"]) == 1,
          str(scan["files"]))
    rep = fmt.validate_paths([d])
    check("F61 validate ignores the scratch DOCX under work/",
          rep["ok"] is True and rep["files"] == 1 and rep["failed"] == 0,
          f"files={rep['files']} failed={rep['failed']}")
    # A directly named deliverable is still validated, even under work/.
    rep2 = fmt.validate_paths([d / "work" / "scratch.docx"])
    check("F61 an explicitly named path is still validated",
          rep2["files"] == 1 and rep2["failed"] == 1,
          f"files={rep2['files']} failed={rep2['failed']}")


# ---------------------------------------------------------------------------
# F62 -- every --json report path is guarded against its input documents
# ---------------------------------------------------------------------------
def test_f62_json_guards() -> None:
    print("\n== F62: --json must not replace an input/output document ==")
    d = scratch("fixbugs1115w2_f62_")
    src = make_docx(d / "main.docx", [para("Hello world.")])
    original = src.read_bytes()
    res = fmt_cli("scan", str(src), "--json", str(src), cwd=d)
    check("F62 scan --json over its own input is refused (exit 2)",
          res.returncode == 2, f"rc={res.returncode}")
    check("F62 scan leaves the input DOCX byte-identical",
          src.read_bytes() == original, "input was replaced by the report")
    res = fmt_cli("validate", str(src), "--json", str(src), cwd=d)
    check("F62 validate --json over its own input is refused (exit 2)",
          res.returncode == 2, f"rc={res.returncode}")
    check("F62 validate leaves the input DOCX byte-identical",
          src.read_bytes() == original, "input was replaced")
    out = d / "fixed.docx"
    res = fmt_cli("fix", str(src), "--out", str(out), "--json", str(out), cwd=d)
    check("F62 fix --json over its own --out is refused (exit 2)",
          res.returncode == 2, f"rc={res.returncode}")
    check("F62 fix did not create a JSON-bearing output", not out.exists(),
          "out was written before the guard")
    res = fmt_cli("zotero-check", str(src), "--json", str(src), cwd=d)
    check("F62 zotero-check --json over its input is refused (exit 2)",
          res.returncode == 2, f"rc={res.returncode}")
    check("F62 zotero-check leaves the input byte-identical",
          src.read_bytes() == original, "input was replaced")


# ---------------------------------------------------------------------------
# F63 -- every FORMAT_SCAN row carries its tier
# ---------------------------------------------------------------------------
def test_f63_row_tiers() -> None:
    print("\n== F63: every scanner row carries `tier` ==")
    d = scratch("fixbugs1115w2_f63_")
    bad = d / "bad.docx"
    bad.write_bytes(b"not a zip\n")
    res = fmt.analyse_package(bad, dict(fmt.POLICY_DEFAULTS))
    check("F63 the FMT-X1 row carries a tier",
          res["rows"] and res["rows"][0].get("tier") == "finding",
          str(res["rows"][0].keys()) if res["rows"] else "no rows")

    emph = make_docx(d / "emph.docx", [
        para("", runs='<w:r><w:t xml:space="preserve">We published in </w:t></w:r>'
                      '<w:r><w:rPr><w:i/></w:rPr><w:t>Nature Methods</w:t></w:r>'
                      '<w:r><w:t> last year.</w:t></w:r>')])
    rows = fmt.analyse_package(emph, dict(fmt.POLICY_DEFAULTS))["rows"]
    emph_rows = [r for r in rows if r["rule"] == "FMT-T6c"]
    check("F63 the emphasis row is produced", bool(emph_rows), str([r["rule"] for r in rows]))
    check("F63 the emphasis row carries a tier",
          bool(emph_rows) and "tier" in emph_rows[0],
          str(emph_rows[0].keys()) if emph_rows else "no row")

    letter = make_docx(d / "CoverLetter.docx", [para("Dear Editor")])
    (d / "CoverLetter.pdf").write_bytes(b"%PDF-1.4 broken\n")
    policy = dict(fmt.POLICY_DEFAULTS,
                  cover_letter={"manuscript_article_type_names": ["original article"]},
                  page_budget={"cover_letter_max_pages": 2})
    rows = fmt.analyse_package(letter, policy)["rows"]
    t8h = [r for r in rows if r["rule"] == "FMT-T8h"]
    check("F63 the FMT-T8h gap row carries a tier",
          bool(t8h) and "tier" in t8h[0],
          str(t8h[0].keys()) if t8h else "no FMT-T8h gap")
    for r in rows:
        check(f"F63 every row carries tier ({r['rule']})", "tier" in r, str(r.keys()))


def main() -> int:
    print("== 2026-11-15 fix-bugs wave 2 (docx_report) regression checks ==")
    test_f52_output_guards()
    test_f53_special_files()
    test_f54_restyled_references()
    test_f57_scan_figures_gaps()
    test_f58_z5_unsupported_entry()
    test_f60_stray_field_end()
    test_f61_work_scratch()
    test_f62_json_guards()
    test_f63_row_tiers()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s):")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)

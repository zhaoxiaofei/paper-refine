#!/usr/bin/env python3
"""Regression checks for fix-bugs wave 1 batch A_p04 (run 20261122-112829).

Every check pins a candidate this batch re-verified and patched in
`paper_pipeline_parts/p04_utils.py`; each fails on the pre-patch tree.

Run:  conda run -n paper-refine-test python .paper_test/test_fix_wave1_A_p04.py
"""
from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import tracemalloc
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp  # noqa: E402

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
FAILS: list[str] = []
TMP = Path(tempfile.mkdtemp(prefix="fix_wave1_A_p04_"))


def check(label: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(label)


def docx(path: Path, body_xml: str, parts: dict | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{W}"><w:body>{body_xml}</w:body></w:document>')
        for name, data in (parts or {}).items():
            z.writestr(name, data)
    return path


def para(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def forge_uncompressed_size(path: Path, part: str, value: int) -> None:
    """Patch the CENTRAL-DIRECTORY uncompressed size (attacker-controlled)."""
    raw = bytearray(path.read_bytes())
    i = raw.find(b"PK\x01\x02")
    while i >= 0:
        nlen = struct.unpack("<H", raw[i + 28:i + 30])[0]
        if bytes(raw[i + 46:i + 46 + nlen]) == part.encode():
            raw[i + 24:i + 28] = struct.pack("<I", value)
            break
        i = raw.find(b"PK\x01\x02", i + 1)
    path.write_bytes(bytes(raw))


def check_f04() -> None:
    print("\n== F04: a forged small declared size never inflates the part unbounded ==")
    p = TMP / "f04.docx"
    payload = b"<a:theme>" + b"A" * (8 * 1024 * 1024) + b"</a:theme>"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/theme/theme1.xml", payload)
    forge_uncompressed_size(p, "word/theme/theme1.xml", 100)
    old = pp.MAX_DOCX_PART_BYTES
    pp.MAX_DOCX_PART_BYTES = 4096
    try:
        tracemalloc.start()
        report = (pp._protected_template_parts_report(p)
                  if hasattr(pp, "_protected_template_parts_report") else None)
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    finally:
        pp.MAX_DOCX_PART_BYTES = old
    check("F04 the forged part is read bounded (peak < 2 MB for 8 MB declared-small)",
          report is not None and peak < 2 * 1024 * 1024, f"peak={peak} report={report}")
    check("F04 the part is reported UNREADABLE instead of hashed from a lie",
          report is not None and "word/theme/theme1.xml" in report[1], str(report))


def check_f06_f93() -> None:
    print("\n== F06/F93: UTF-16 body + footnotes/endnotes are real document text ==")
    src = TMP / "src6"
    src.mkdir()
    body = ('<?xml version="1.0" encoding="UTF-16"?><w:document xmlns:w="%s"><w:body>'
            '<w:p><w:r><w:t>Abstract</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>We enrolled 24 patients.</w:t></w:r></w:p>'
            '</w:body></w:document>' % W)
    with zipfile.ZipFile(src / "u16.docx", "w") as z:
        z.writestr("word/document.xml", b"\xff\xfe" + body.encode("utf-16-le"))
    docs = pp.corpus_text_documents([(src, "", None)])
    got = [t for _n, rows in docs for t, _a, _b in rows]
    check("F06 a legal UTF-16 word/document.xml yields its paragraphs",
          got == ["Abstract", "We enrolled 24 patients."], str(got))
    notes = {"word/footnotes.xml": f'<w:footnotes xmlns:w="{W}"><w:footnote><w:p>'
                                   f'<w:r><w:t>Footnote content is real prose.</w:t></w:r>'
                                   f'</w:p></w:footnote></w:footnotes>'}
    f93 = docx(TMP / "f93.docx", para("Body paragraph."), parts=notes)
    check("F93 footnotes/endnotes enter the paragraph multiset",
          pp._docx_paragraph_texts(f93) == ["Body paragraph.",
                                            "Footnote content is real prose."],
          str(pp._docx_paragraph_texts(f93)))
    # end-to-end: dropping the footnote now fails parity
    sb = TMP / "f93_sb"
    (sb / "out").mkdir(parents=True)
    src93 = TMP / "f93_src"
    src93.mkdir()
    docx(src93 / "main.docx", para("Body paragraph."), parts=notes)
    docx(sb / "out" / "main.docx", para("Body paragraph."))
    (sb / "out" / "REPLACEMENT_LEDGER.md").write_text(
        '```json\n{"exceptions": []}\n```\n', encoding="utf-8")
    rep = pp.template_rewrite_postcheck(sb, src93, {})
    check("F93 a rewrite that drops a footnote no longer passes parity",
          rep["coverage"]["ratio"] < 1.0, str(rep.get("coverage")))


def check_f07() -> None:
    print("\n== F07: a truncated document is not its complete nested child ==")
    check("F07 truncated object around a nested list is refused",
          pp._json_from_text('Here is the document:\n{"findings": [{"id": "F1"}]', True) is None)
    check("F07 truncated array of complete children is refused",
          pp._json_from_text('Here is the document:\n[{"id": "F1"}, {"id": "F2"', True) is None)
    check("F07 control: a prose opener still yields the later document",
          pp._json_from_text('prose { unclosed then {"a":1}', True) == {"a": 1})


def check_f17() -> None:
    print("\n== F17: link/../.. cannot collapse past the containment walk ==")
    run = TMP / "run17"
    (run / "sb").mkdir(parents=True)
    outside = TMP / "outside17"
    outside.mkdir()
    (run / "sb" / "link").symlink_to(outside, target_is_directory=True)
    pp.register_write_anchor(run)
    escaped = TMP / "planted17.txt"
    try:
        pp.write_text_atomic(run / "sb" / "link" / ".." / ".." / "planted17.txt", "PWNED")
        write_raised = False
    except OSError:
        write_raised = True
    check("F17 the atomic writer refuses link/../../name", write_raised)
    check("F17 no byte landed above the run root", not escaped.exists())
    try:
        pp._refuse_symlinked_read_parent(run / "sb" / "link" / ".." / ".." / "x.txt")
        read_raised = False
    except OSError:
        read_raised = True
    check("F17 the bounded reader refuses the same shape", read_raised)
    try:
        pp.write_text_atomic(run / "sb" / "ok.txt", "ok")
        legit = (run / "sb" / "ok.txt").read_text(encoding="utf-8") == "ok"
    except OSError:
        legit = False
    check("F17 a legitimate write inside the root still works", legit)


def check_f23() -> None:
    print("\n== F23: a swapped-in hardlink is not truncated before the guard ==")
    dst = TMP / "f23_dst.txt"
    dst.write_text("KEEP ME\n", encoding="utf-8")
    temp = pp.tmp_path_for(dst)
    os.unlink(temp)
    os.link(dst, temp)
    try:
        pp._open_reserved_tmp(temp, "wb")
        raised = False
    except OSError:
        raised = True
    check("F23 the replaced temporary is refused", raised)
    check("F23 the destination keeps its bytes", dst.read_bytes() == b"KEEP ME\n",
          str(dst.read_bytes()))
    dst.unlink()


def check_f51_f151() -> None:
    print("\n== F51/F151: asset names are not addresses; the date shape is exact ==")
    src = TMP / "src51"
    src.mkdir()
    (src / "main.tex").write_text(
        "See figures/plot@2x.png and write to jane.doe@uzh.ch.\n", encoding="utf-8")
    found, _gaps = pp._email_addresses_in_sources([(src, "", None)])
    check("F51 an @2x asset filename is not a contact address",
          set(found) == {"jane.doe@uzh.ch"}, str(found))
    pkg = TMP / "pkg151"
    (pkg / "work").mkdir(parents=True)
    row = {"after": "jane.doe@uzh.ch", "source_url": "https://www.uzh.ch/people/jane",
           "query": "Jane Doe e-mail", "checked_at": "2026-1-1",
           "evidence": "contact: jane.doe@uzh.ch"}
    (pkg / "work" / "EMAIL_VERIFICATION.json").write_text(
        json.dumps({"verifications": [row]}), encoding="utf-8")
    records, problems = pp._email_verification_rows(pkg)
    check("F151 a non-YYYY-MM-DD checked_at is refused",
          records == [] and bool(problems), f"{records} {problems}")
    row["checked_at"] = "2026-01-01"
    (pkg / "work" / "EMAIL_VERIFICATION.json").write_text(
        json.dumps({"verifications": [row]}), encoding="utf-8")
    records, problems = pp._email_verification_rows(pkg)
    check("F151 a real YYYY-MM-DD date is still accepted",
          len(records) == 1 and not problems, f"{records} {problems}")


def check_f77_f83_f87() -> None:
    print("\n== F77/F83/F87: template report + ledger fence + style quote ==")
    tpl = TMP / "f77_tpl.docx"
    with zipfile.ZipFile(tpl, "w") as z:
        z.writestr("word/theme/theme1.xml", "<a:theme/>")
        z.writestr("word/numbering.xml", "<w:numbering/>")
    raw = bytearray(tpl.read_bytes())
    i = raw.find(b"PK\x01\x02")
    while i >= 0:
        nlen = struct.unpack("<H", raw[i + 28:i + 30])[0]
        if bytes(raw[i + 46:i + 46 + nlen]) == b"word/numbering.xml":
            raw[i + 20:i + 22] = struct.pack("<H", 3)   # forge COMPRESSED size
            break
        i = raw.find(b"PK\x01\x02", i + 1)
    tpl.write_bytes(bytes(raw))
    report = (pp._protected_template_parts_report(tpl)
              if hasattr(pp, "_protected_template_parts_report") else None)
    check("F77 one unreadable part no longer loses every protected hash",
          report is not None and "word/theme/theme1.xml" in report[0]
          and "word/numbering.xml" in report[1], str(report))
    src = TMP / "f77_src"
    src.mkdir()
    docx(src / "main.docx", para("Alpha paragraph one content"))
    sb = TMP / "f77_sb"
    (sb / "out").mkdir(parents=True)
    docx(sb / "out" / "main.docx", para("Alpha paragraph one content"))
    (sb / "out" / "REPLACEMENT_LEDGER.md").write_text(
        '```json\n{"exceptions": []}\n```\n', encoding="utf-8")
    rep = pp.template_rewrite_postcheck(sb, src, {"main": tpl})
    check("F77 the derived-parts gate reports UNVERIFIED instead of passing",
          any("not derived from the templates" in e for e in rep.get("errors") or []),
          str(rep.get("errors"))[:200])

    led = TMP / "f83_ledger.md"
    led.write_text('``` json\n{"exceptions": [{"kind": "addition", "output": '
                   '"a new output paragraph here", "reason": "required"}]}\n```\n',
                   encoding="utf-8")
    rows, probs = pp._template_ledger_exceptions(led)
    check("F83 a CommonMark-legal '``` json' fence is read",
          len(rows) == 1 and not probs, f"{rows} {probs}")

    tpl87 = docx(TMP / "tpl87.docx", para("Alpha paragraph one content"), parts={
        "word/styles.xml": "<w:styles><w:style w:styleId='JournalTitle'/></w:styles>"})
    sb87 = TMP / "f87_sb"
    (sb87 / "out").mkdir(parents=True)
    docx(sb87 / "out" / "main.docx", para("Alpha paragraph one content"), parts={
        "word/styles.xml": '<w:styles><w:style w:styleId="Normal"/></w:styles>'})
    (sb87 / "out" / "REPLACEMENT_LEDGER.md").write_text(
        '```json\n{"exceptions": []}\n```\n', encoding="utf-8")
    rep = pp.template_rewrite_postcheck(sb87, src, {"main": tpl87})
    check("F87 a single-quoted template style id is still required",
          any("styles" in e for e in rep.get("errors") or []),
          str(rep.get("errors"))[:200])


def check_f108_f146_f163() -> None:
    print("\n== F108/F146/F163: code/ text excluded; manual-step fences and pipes ==")
    src = TMP / "src108"
    (src / "code").mkdir(parents=True)
    (src / "main.tex").write_text("Body text.\n", encoding="utf-8")
    (src / "code" / "analysis_notes.txt").write_text("TODO 12.5% of the corpus.\n",
                                                     encoding="utf-8")
    docs = pp.corpus_text_documents([(src, "", None)])
    check("F108 code/ TEXT is not manuscript prose",
          [n for n, _r in docs] == ["main.tex"], str([n for n, _r in docs]))
    m146 = TMP / "m146.md"
    m146.write_text("1. one\n```\n2. two\n3. three\n", encoding="utf-8")
    check("F146 an unterminated fence does not hide the later steps",
          pp.count_manual_steps(m146) == 3, str(pp.count_manual_steps(m146)))
    m163 = TMP / "m163.md"
    m163.write_text("- real step\na|b|c\nSee item | two.\n", encoding="utf-8")
    check("F163 prose lines with pipes add no phantom table row",
          pp.count_manual_steps(m163) == 1, str(pp.count_manual_steps(m163)))
    mtable = TMP / "mtable.md"
    mtable.write_text("| step | owner |\n|---|---|\n| a | x |\n| b | y |\n",
                      encoding="utf-8")
    check("F163 a real GFM table still counts its data rows",
          pp.count_manual_steps(mtable) == 2, str(pp.count_manual_steps(mtable)))


def main() -> int:
    check_f04()
    check_f06_f93()
    check_f07()
    check_f17()
    check_f23()
    check_f51_f151()
    check_f77_f83_f87()
    check_f108_f146_f163()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("ALL A_p04 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

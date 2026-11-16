#!/usr/bin/env python3
"""Regressions for the 2026-11-17 fix-bugs wave 1 (verified-findings set).

One check per confirmed candidate that this wave patched. Each check fails on
the pre-wave tree and passes after the smallest fix.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS))
import paper_pipeline as pp                                        # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("[ok ] " if ok else "[FAIL] ") + name + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def pkg(files, root=None):
    d = Path(tempfile.mkdtemp(dir=root))
    for name, text in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return d


def docx_bytes(parts):
    buf = None
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return buf.getvalue()


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def main() -> int:
    print("\n== F002/F086: function words / one shared token do not pair unrelated units ==")
    b = pkg({"m.md": "The samples were stored at 4 C.\n\nAnother ordinary sentence follows."})
    c = pkg({"m.md": "The mice were housed at 22 C.\n\nAnother ordinary sentence follows."})
    got = pp.content_edit_problems(None, b, c, "x", insertions_allowed=False,
                                   deletions_allowed=False)
    check("F086 unrelated function-word frames are not paired", bool(got), str(got)[:200])

    b = pkg({"m.md": "The treatment reduced tumor growth in the mice cohort."})
    c = pkg({"m.md": "The treatment increased liver enzyme levels in the rats cohort."})
    got = pp.content_edit_problems(None, b, c, "x", insertions_allowed=False,
                                   deletions_allowed=False)
    check("F002 one shared content token is not an in-place rewrite", bool(got), str(got)[:200])

    print("\n== F003/F004/F010: values removed/added inside a surviving sentence ==")
    b = pkg({"m.md": "The dose was 55 mg and the tumour weight was 30 g in every animal."})
    c = pkg({"m.md": "The dose was 55 mg in every animal."})
    got = pp.fact_preservation_problems(b, c, "x")
    check("F003 a value removed from a surviving sentence is reported",
          any("30 g" in p for p in got), str(got)[:200])
    b = pkg({"m.md": "The dose was 55 mg in the treated group."})
    c = pkg({"m.md": "The dose was 55 mg in the treated group of 12 patients at 3 sites."})
    got = pp.fact_preservation_problems(b, c, "x")
    check("F004 an appended value is reported", any("12" in p or "3" in p for p in got),
          str(got)[:200])
    b = pkg({"m.md": "We observed 3 adverse events in this cohort of patients."})
    c = pkg({"m.md": "We observed adverse events in this cohort of patients."})
    got = pp.fact_preservation_problems(b, c, "x")
    check("F010 a single-digit fact is not ignored", any("3" in p for p in got), str(got)[:200])
    # R01 (verified F010 acceptance case): DELETING the sentence that carries the
    # single digit, in the default permissive mode, must report the lost value.
    b = pkg({"m.md": "The dose was 55 mg.\n\nThe pH was 7."})
    c = pkg({"m.md": "The dose was 55 mg."})
    got = pp.fact_preservation_problems(b, c, "x")
    check("R01 a deleted sentence's single-digit fact is reported",
          any("7" in p for p in got), str(got)[:200])
    b = pkg({"m.md": "The dose was 5 mg.\n\nAnother sentence follows here."})
    c = pkg({"m.md": "Another sentence follows here."})
    got = pp.fact_preservation_problems(b, c, "x")
    check("R01 a deleted single-digit measurement is reported",
          any("5 mg" in p for p in got), str(got)[:200])
    # ... but a display label is not a fact, and a deleted list item's leading
    # "1." is a marker: neither may create a fact-loss message.
    for marker_text in ("See Table 1 for the groups.", "1. First list item text."):
        b = pkg({"m.md": marker_text + "\n\nAnother sentence follows here."})
        c = pkg({"m.md": "Another sentence follows here."})
        check(f"R01 a marker number is still not a fact ({marker_text[:14]})",
              pp.fact_preservation_problems(b, c, "x") == [])
    # R12-3: a same-sentence replacement is still a correction.
    b = pkg({"m.md": "We selected 12 blocks along the transect and matched the plots."})
    c = pkg({"m.md": "We selected 6 blocks along the transect and matched the plots."})
    check("R12-3 a changed value in a surviving sentence stays allowed",
          pp.fact_preservation_problems(b, c, "x") == [])

    print("\n== F005/F006: reference entries and removed citation keys ==")
    b = pkg({"m.md": "Body sentence one is here.\n\n## References\n\n[1] Smith J. A real paper. 2020."})
    c = pkg({"m.md": "Body sentence one is here.\n\n## References\n\n[1] Smith J. A real paper. 2020.\n"
                      "[2] Fake A. Fabricated paper. 2026."})
    got = pp.content_edit_problems(None, b, c, "x", insertions_allowed=False,
                                   deletions_allowed=False)
    check("F005 a fabricated reference entry is a content insertion",
          any("reference" in p.lower() for p in got), str(got)[:200])
    b = pkg({"m.md": "This claim is supported by prior work \\cite{smith2020} in the field."})
    c = pkg({"m.md": "This claim is supported by prior work in the field."})
    got = pp.content_edit_problems(None, b, c, "x", insertions_allowed=False,
                                   deletions_allowed=False)
    check("F006 a removed citation key is a deletion",
          any("citation key" in p for p in got), str(got)[:200])

    print("\n== F012/F013/F014/F130/F241: deletion audit and table/row units ==")
    b = pkg({"m.md": "This is false.\n\nThe treatment worked very well in this cohort."})
    c = pkg({"m.md": "The treatment worked very well in this cohort."})
    rows = pp.deletion_audit_rows(b, c)
    check("F012 a short deleted paragraph seeds an audit row",
          any(r.get("paragraph") == "This is false." for r in rows), str(rows)[:200])
    b = pkg({"m.md": "| group | n | mean |\n|---|---|---|\n| A | 12 | 3.4 |\n| B | 7 | 2.1 |"})
    c = pkg({"m.md": "| group | mean |\n|---|---|\n| A | 3.4 |\n| B | 2.1 |"})
    got = pp.content_edit_problems(None, b, c, "x", insertions_allowed=False,
                                   deletions_allowed=False)
    check("F013 a removed Markdown table column is a missing row", bool(got), str(got)[:200])
    b = pkg({"m.tex": "\\begin{tabular}{ll}\na & b \\\\\nc & d \\\\\n\\end{tabular}"})
    c = pkg({"m.tex": "\\begin{tabular}{ll}\na & b \\\\\n\\end{tabular}"})
    got = pp.content_edit_problems(None, b, c, "x", insertions_allowed=False,
                                   deletions_allowed=False)
    check("F014 a removed LaTeX tabular row is a missing row", bool(got), str(got)[:200])
    b = pkg({"m.md": "| a | b |\n|---|---|\n| 1 | 2 |"})
    c = pkg({"m.md": "| a | b |\n|---|---|\n| 1 | 2 |\n| 9 | 9 |"})
    got = pp.content_edit_problems(None, b, c, "x", insertions_allowed=False,
                                   deletions_allowed=False)
    check("F241 a short table row is a content unit", bool(got), str(got)[:200])
    b = pkg({"m.md": "Same paragraph is deleted here.\n\nSame paragraph is deleted here.\n\nUnique."})
    c = pkg({"m.md": "Same paragraph is deleted here.\n\nUnique."})
    rows = pp.deletion_audit_rows(b, c)
    check("F130 one deleted duplicate paragraph is audited", len(rows) == 1, str(rows)[:200])

    print("\n== F015/F016/F018: citation extractor ==")
    script = WS / "paper-skills" / "paper-review" / "scripts" / "extract_citations.py"
    work = pkg({"corpus/main.tex.txt": "As shown \\cite[12]{smith2020}.\n\n"
                                       "\\begin{thebibliography}{9}\n\\bibitem{smith2020} Smith J. 2020.\n"
                                       "\\end{thebibliography}\n"})
    out = Path(tempfile.mkdtemp())
    subprocess.run([sys.executable, str(script), "--work", str(work), "--out", str(out)],
                   check=True, capture_output=True, text=True, timeout=60)
    data = json.loads((out / "artifacts" / "M2_citations.json").read_text())
    check("F015 a \\cite page option is not a numeric call-out",
          12 not in (data.get("orphan_callouts") or []), str(data.get("orphan_callouts")))
    work = pkg({"corpus/main.md.txt": "Text cites [1] and [2].\n\nReferences\n(1) Smith J. 2020. A study.\n"
                                  "(2) Jones K. 2021. Another study.\n"})
    out = Path(tempfile.mkdtemp())
    subprocess.run([sys.executable, str(script), "--work", str(work), "--out", str(out)],
                   check=True, capture_output=True, text=True, timeout=60)
    data = json.loads((out / "artifacts" / "M2_citations.json").read_text())
    check("F016 a parenthesized numeric list is parsed",
          not (data.get("orphan_callouts") or []), str(data.get("orphan_callouts")))
    work = pkg({"corpus/main.md.txt": "Text cites [1] and [2].\n\nReferences\n[1] Smith J. 2020. A study. Nature.\n"
                                  "[2] Smith J. 2020. A study. Nature.\n"})
    out = Path(tempfile.mkdtemp())
    subprocess.run([sys.executable, str(script), "--work", str(work), "--out", str(out)],
                   check=True, capture_output=True, text=True, timeout=60)
    data = json.loads((out / "artifacts" / "M2_citations.json").read_text())
    check("F018 duplicate entry text under distinct numbers is reported",
          bool(data.get("duplicate_entry_text")), str(data.get("duplicate_entry_text")))

    print("\n== F021/F184/F185: certification and ranking ==")
    cert = pp.decide_certification([], [{"mismatch": None}], True, {}, None, False, False,
                                   2, 2, {"files": ["x"]}, "", auto_promoted=[1])
    check("F021 an auto-promoted champion is never certified", cert["certified"] is False,
          str(cert))
    row = {"defect_prefix_total": 1, "median": 9.0, "mean": 9.0, "iqr": 0.0,
           "digest": "aa"}
    check("F184 a one-total census is not used as the leading key",
          pp.champion_sort_key(row)[0] == 10 ** 9, str(pp.champion_sort_key(row)))
    stats = {
        "w1": {"n": 6, "complete": True, "vs_original_complete": True,
               "anti_regression_ok": True, "digest": "w1", "median": 2.0,
               "mean": 2.0, "iqr": 0.0, "vs_original": 2.0, "vs_base": 2.0},
        "r1": {"n": 0, "complete": False, "digest": "r1", "median": 2.0,
               "mean": 2.0, "iqr": 0.0},
    }
    got = pp.derive_ranking(stats, ["w1"], "r1", {}, 0, 1)
    check("F185 the incumbent is retained when its panel is incomplete",
          got["champion"] == pp.A1_ID, str(got)[:300])

    print("\n== F059/F082/F094/F103/F156/F160: local helpers ==")
    d = pkg({"a.md": "x"})
    old = pp.MAX_PAYLOAD_BYTES
    try:
        pp.MAX_PAYLOAD_BYTES = 0
        tok = pp.revision_token_for_dir(d)
    finally:
        pp.MAX_PAYLOAD_BYTES = old
    check("F059 an unreadable package keeps per-file detail in the token",
          bool(tok.get("unreadable")), str(tok))
    d = pkg({})
    cache = d / "__pycache__"
    cache.mkdir()
    (cache / "m.pyc").write_bytes(b"x")
    pp.strip_non_shippable_files_in_dir(d)
    check("F082 an emptied __pycache__ is removed", not cache.exists())
    # R05: the directory sweep must not delete a cache directory inside a
    # read-only evidence area, even when the sweep emptied it.
    d = pkg({"keep.txt": "x"})
    ev = d / "raw_data" / "__pycache__"
    ev.mkdir(parents=True)
    (ev / "m.pyc").write_bytes(b"x")
    res = pp.strip_non_shippable_files_in_dir(d)
    check("R05 an evidence-area __pycache__ is left untouched",
          ev.is_dir() and (ev / "m.pyc").is_file()
          and "raw_data/__pycache__/m.pyc" in res.get("kept_in_evidence", []),
          str(res))
    import paper_docx_format as f
    def app1(orient):
        tiff = (b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1)
                + struct.pack("<HHI", 0x0112, 3, 1) + struct.pack("<H", orient)
                + b"\x00\x00" + struct.pack("<I", 0))
        payload = b"Exif\x00\x00" + tiff
        return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    body = struct.pack(">BHHB", 8, 200, 400, 3) + b"\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    data = b"\xff\xd8" + app1(6) + b"\xff\xc0" + struct.pack(">H", len(body) + 2) + body + b"\xff\xd9"
    check("F094 EXIF orientation 6 swaps the rendered dimensions",
          f.image_pixel_size(data) == (200, 400), str(f.image_pixel_size(data)))
    field = lambda cid: {"kind": "item", "citationID": cid, "instr": "x",
                         "visible_text": cid}
    zres = f.zotero_field_continuity_problems(
        {"fields": [field("c1"), field("c2")], "errors": [], "text": "c1 c2"},
        {"fields": [field("c3"), field("c4")], "errors": [], "text": "c3 c4",
         "parity_rows": []})
    check("F103 replacing every citationID is a hard error", bool(zres["errors"]),
          str(zres["errors"]))
    check("F156 hyphenated names are not counts",
          [m.group(0) for m in f.NUMBER_RE.finditer("IL-6 and COVID-19 in 12 patients.")] == ["12"])
    check("F160 a space-grouped quantity is one number",
          [m.group(0) for m in f.NUMBER_RE.finditer("We processed 12 000 cells.")] == ["12 000"])

    print("\n== F133/F145/F154/F158/F161/F179/F189: gates and helpers ==")
    for value in ("a|b", "a\\|b", "C:\\data\\x.csv"):
        row = "| T | x | " + pp.md_table_cell(value) + " |"
        check(f"F133 markdown cell round trip {value!r}",
              pp._manual_md_cells(row)[-1] == value, repr(pp._manual_md_cells(row)[-1]))
    b = pkg({"response.md": "We thank the reviewer. The analysis now includes 12 samples."})
    c = pkg({"response.md": "We thank the reviewer. The analysis now includes 14 samples."})
    check("F145 a response document is not manuscript prose",
          pp.content_edit_problems(None, b, c, "x", insertions_allowed=False,
                                   deletions_allowed=False) == [])
    d = Path(tempfile.mkdtemp()) / "bad.docx"
    d.write_bytes(docx_bytes({
        "word/document.xml": f'<w:document xmlns:w="{W_NS}"><w:body><w:p><w:r><w:t>body</w:t></w:r></w:p></w:body></w:document>',
        "word/footnotes.xml": "<w:footnotes><broken>"}))
    check("F154 a malformed notes part fails the read closed",
          pp._docx_paragraphs_with_styles(d, include_notes=True) is None)
    d = Path(tempfile.mkdtemp()) / "ins.docx"
    d.write_bytes(docx_bytes({
        "word/document.xml": f'<w:document xmlns:w="{W_NS}"><w:body><w:p><w:ins>'
                              f'<w:r><w:t>corre</w:t></w:r><w:r><w:t>spondence</w:t></w:r>'
                              f'</w:ins></w:p></w:body></w:document>'}))
    weight = pp.redline_markup_weight(d)
    check("F158 a word split across runs is one word", weight["ins"] == 1, str(weight))
    got = pp.strip_dangling_references_in_dir(Path("/nonexistent_pkg_audit"), ["code"], "x")
    check("F161 a non-directory scan is not ok", got.get("ok") is False, str(got))
    try:
        pp._json_safe({1: "a", "1": "b"})
        raised = False
    except ValueError:
        raised = True
    check("F179 colliding JSON keys are refused", raised)
    check("F189 an anonymous scores sheet is not adopted",
          pp._signal_names_this_run({}, {"id": "r1", "kind": "judge",
                                         "target_id": "w1"}, pp.SCORES_FILE) is False)

    print("\n== F151: a corrupt cells_used is not indexed from the end ==")
    census = {"r1_a2": {"tiers": {"correctness": {"severities": {
        "fatal": {"own": 1, "peer": 0}, "critical": {"own": 0, "peer": 0},
        "major": {"own": 0, "peer": 0}, "minor": {"own": 0, "peer": 0}}}}}}
    agg = {"issue_census": census}
    check("F151 a negative cells_used reports None",
          pp.census_prefix_total(agg, {"tiebreak": {"cells_used": -1}}, "r1_a2") is None)
    check("F151 a non-numeric cells_used reports None",
          pp.census_prefix_total(agg, {"tiebreak": {"cells_used": "x"}}, "r1_a2") is None)

    print("\n== F099: cold-start inventory never drops the coverage row ==")
    d = pkg({"a.txt": "a", "b.txt": "b", "c.txt": "c"})
    rows = pp.cold_start_obligation_rows(d, limit=1)
    check("F099 the coverage row survives a one-row limit",
          bool(rows) and rows[-1].get("family") == "coverage", str(rows))
    # R03: the truncation row must count every original row the limit dropped.
    full = pp.cold_start_obligation_rows(d, limit=100)
    originals = [x for x in full if x.get("family") != "coverage"]
    rows = pp.cold_start_obligation_rows(d, limit=2)
    trunc = [x for x in rows if x.get("family") == "truncation"]
    check("R03 the truncation row counts every omitted inventory row",
          bool(trunc) and f"{len(originals)} row(s) omitted" in trunc[0]["obligation"],
          str(rows))

    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

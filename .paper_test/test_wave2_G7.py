#!/usr/bin/env python3
"""Regression checks for fix-bugs wave 2, group G7 (run 20261115-220228).

One check block per re-validated candidate (C030 C031 C116 C118 C119 C120
C121 C122 C124 C125 C126 C127 C129 C186 C114).  Hermetic: temp roots only; no
network, no Word, no agent runs.

Run:  python3 -B .paper_test/test_wave2_G7.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp          # noqa: E402

FAILS = []
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def check(label, cond, detail=""):
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def tmpdir(tag):
    return Path(tempfile.mkdtemp(prefix=f"fb1115w2_G7_{tag}_"))


def make_docx(path, body_xml, extra_parts=()):
    xml = (f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>'
           f'{body_xml}</w:body></w:document>')
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
        for name, data in extra_parts:
            z.writestr(name, data)


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# C030 -- the PKG-2 stage repair must use the BASE's PKG-10 closure
# ---------------------------------------------------------------------------
def test_c030_stage_strip_uses_base_area():
    print()
    print("== C030 the PKG-2 repair does not delete a pointer the base carries ==")
    tex = ("\\documentclass{article}\n\\begin{document}\n\\input{raw_data/data.tex}\n"
           "The values are stored in raw_data/data.tex for reanalysis.\n\\end{document}\n")
    root = tmpdir("c030")
    sb = root / "runs" / "r1_revise"
    (sb / "base" / "raw_data").mkdir(parents=True)
    (sb / "revised").mkdir()
    (sb / "base" / "raw_data" / "data.tex").write_text("x=1\n", encoding="utf-8")
    (sb / "base" / "main.tex").write_text(tex, encoding="utf-8")
    (sb / "revised" / "main.tex").write_text(tex, encoding="utf-8")
    rep = pp.strip_dangling_references_in_dir(sb / "revised", ["raw_data"], "revise")
    after = (sb / "revised" / "main.tex").read_text(encoding="utf-8")
    check("C030 the sentence naming a file the base's .tex inputs survives",
          "The values are stored in raw_data/data.tex for reanalysis." in after,
          repr(after))
    check("C030 nothing is removed and the re-scan is clean",
          rep["removed"] == 0 and rep["remaining"] == [] and rep["ok"], json.dumps(rep)[:300])

    # A genuinely missing area is still a dangling reference: the fix must not
    # stop the repair for packages whose corpus really does not carry it.
    lonely = tmpdir("c030b") / "stage"
    lonely.mkdir()
    (lonely / "main.tex").write_text(tex, encoding="utf-8")
    rep2 = pp.strip_dangling_references_in_dir(lonely, ["raw_data"], "stage")
    check("C030 a genuinely absent area is still removed",
          rep2["removed"] == 1
          and "reanalysis" not in (lonely / "main.tex").read_text(encoding="utf-8"),
          json.dumps(rep2)[:300])


# ---------------------------------------------------------------------------
# C031 -- a skipped publication must not deny the older directory's existence
# ---------------------------------------------------------------------------
def test_c031_skipped_publication_names_stale_dir():
    print()
    print("== C031 a skipped publication reports the older package on disk ==")
    root = tmpdir("c031") / "root"
    root.mkdir()
    stale = root / pp.final_clean_dirname(root)
    stale.mkdir()
    (stale / "main.md").write_text("OLD CHAMPION BYTES", encoding="utf-8")
    ctx = type("C", (), {"root": root})()
    res = pp.publish_final_clean(ctx, {"stored": {}, "pin": {}}, True, "")
    check("C031 the skipped record names the directory still on disk",
          res.get("skipped") and str(res.get("stale_dir") or "") == str(stale),
          json.dumps({k: str(v) for k, v in res.items()})[:300])
    txt = pp.final_clean_readme_text(ctx, {}, {"pin": {}}, res)
    check("C031 the readme does not claim no champion directory exists",
          "There is no champion directory to start the next run from" not in txt, txt[:0])
    check("C031 the readme names the stale directory and says it is NOT this decision's",
          str(stale) in txt and "NOT this decision's" in txt,
          "\n".join(l for l in txt.splitlines() if str(stale) in l)[:300])


# ---------------------------------------------------------------------------
# C118 -- one invalid package-CSV row must not discard the classified inventory
# ---------------------------------------------------------------------------
def test_c118_csv_row_by_row():
    print()
    print("== C118 a bad package-CSV row keeps the valid rows ==")
    root = tmpdir("c118")
    action = list(pp.MANUAL_ACTIONS)[0]
    (root / "MANUAL_TODO.csv").write_text(
        "TODO item ID,importance,author_action,description\n"
        f"T-001,SEVERE,{action},Needs a fix.\n"
        f"T-002,major,{action},Second item.\n", encoding="utf-8")
    ctx = type("C", (), {"root": root})()
    out = pp.write_open_items_sibling(ctx, {
        "manual_todo_csv": "MANUAL_TODO.csv", "items": [],
        "manual_steps_text": "", "run": "r1_a2_revise", "kind": "revise"})
    steps = (root / pp.FINAL_CLEAN_STEPS_NAME).read_text(encoding="utf-8")
    check("C118 the valid row is carried into the delivered sibling",
          "T-002" in steps and out.get("items") == 1, json.dumps(out)[:300])
    check("C118 the invalid row is reported, not silently dropped",
          any("T-001" in p and "SEVERE" in p for p in (out.get("problems") or [])),
          json.dumps(out.get("problems"))[:300])
    check("C118 the classified CSV sibling is written",
          out.get("todo_csv") and Path(out["todo_csv"]).is_file(), str(out.get("todo_csv")))


# ---------------------------------------------------------------------------
# C119 -- the document-read cap is a named gap, never a silent truncation
# ---------------------------------------------------------------------------
def test_c119_document_cap_gap():
    print()
    print("== C119 the 25-document scan cap records the documents it did not read ==")
    root = tmpdir("c119")
    for i in range(25):
        (root / f"a{i:02d}.md").write_text(f"filler {i}\n", encoding="utf-8")
    (root / "a25.md").write_text(
        "We drafted this manuscript without generative AI. Later we used ChatGPT to "
        "refine the text.\n", encoding="utf-8")
    texts = pp.package_document_texts(root)
    check("C119 25 documents are read and the 26th is not",
          len(texts) == 25 and not any(r == "a25.md" for r, _ in texts), str(len(texts)))
    check("C119 the unread document is a named coverage gap, not silence",
          bool(texts.gaps) and any("NOT read" in g for g in texts.gaps), str(texts.gaps))
    rows = pp.package_contradiction_rows(root)
    check("C119 the gap reaches the delivered readiness rows",
          any(r.get("gap") for r in rows), json.dumps(rows)[:300])


# ---------------------------------------------------------------------------
# C120 -- a PDF inspector exception is a coverage gap, not a blocking finding
# ---------------------------------------------------------------------------
def test_c120_pdf_inspector_gap():
    print()
    print("== C120 a PDF inspector failure is a coverage gap, not a package defect ==")
    root = tmpdir("c120")
    (root / "main.pdf").write_bytes(b"%PDF-1.4\n")

    class FakeMod:
        pdf_artifact_rows = staticmethod(
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("pdftotext exploded")))

    real = pp._format_module
    pp._format_module = lambda: FakeMod()
    try:
        rows = pp.package_pdf_rows(root)
    finally:
        pp._format_module = real
    gap = [r for r in rows if r.get("gap")]
    check("C120 the failure is recorded as a gap row", len(gap) == 1, json.dumps(rows)[:300])
    check("C120 the gap is advisory and not an accusation of an empty export",
          gap and gap[0].get("advisory") and "NOT evaluated" in gap[0].get("detail", ""),
          str(gap)[:300])
    readiness = pp.package_readiness({"path": str(root),
                                     "hygiene": {"pdf_artifacts": rows}})
    check("C120 readiness stays true and nothing blocks on the un-run scan",
          readiness["submission_ready"] and readiness["blocking_findings"] == 0
          and pp.readiness_gate_problems(readiness, True) == [],
          json.dumps({k: readiness[k] for k in ("submission_ready", "blocking_findings")}))


# ---------------------------------------------------------------------------
# C121 -- PKG-11 sees one-character header typos
# ---------------------------------------------------------------------------
def test_c121_one_char_header_typo():
    print()
    print("== C121 PKG-11 compares spellings across normalized buckets ==")
    rows = "p1\t0.1\t0.2\np2\t0.2\t0.3\np3\t0.3\t0.4\n"
    root = tmpdir("c121")
    (root / "t1.tsv").write_text("method\tconcentration\tvalue\n" + rows, encoding="utf-8")
    (root / "t2.tsv").write_text("method\tconcentraton\tvalue\n" + rows, encoding="utf-8")
    found = pp.scan_column_name_near_misses(root)
    check("C121 the one-character substitution is reported",
          len(found) == 1 and found[0]["reference"] == "concentration"
          and found[0]["counterpart"]["column"] == "concentraton",
          json.dumps(found)[:300])
    other = tmpdir("c121b")
    (other / "a.tsv").write_text("method\tconcentration\tvalue\n" + rows, encoding="utf-8")
    (other / "b.tsv").write_text("method\tpublication\tvalue\n" + rows, encoding="utf-8")
    check("C121 unrelated headers in one directory are not a family",
          pp.scan_column_name_near_misses(other) == [],
          json.dumps(pp.scan_column_name_near_misses(other))[:300])
    case = tmpdir("c121c")
    (case / "a.tsv").write_text("method\tMixMHCpred_aff\tvalue\n" + rows, encoding="utf-8")
    (case / "b.tsv").write_text("method\tMixMHCPred_aff\tvalue\n" + rows, encoding="utf-8")
    check("C121 the case-only variant is still reported",
          len(pp.scan_column_name_near_misses(case)) == 1)


# ---------------------------------------------------------------------------
# C122 -- the PKG-6 guard uses sentence boundaries, not a 40-char distance
# ---------------------------------------------------------------------------
def test_c122_sentence_boundary():
    print()
    print("== C122 a nearby sentence is still a separate claim ==")
    close = ("We drafted this manuscript without generative AI. Later we used ChatGPT "
             "to refine the text.")
    rows = pp.ai_disclosure_contradiction_rows([("main.md", close)])
    check("C122 the contradiction 32 characters away is reported",
          len(rows) == 1 and rows[0]["rule"] == "PKG-6", json.dumps(rows)[:300])
    same = ("We did not use ChatGPT to draft the manuscript; no generative AI was "
            "involved.")
    check("C122 a use negated in the denial's OWN sentence stays quiet",
          pp.ai_disclosure_contradiction_rows([("main.md", same)]) == [],
          json.dumps(pp.ai_disclosure_contradiction_rows([("main.md", same)]))[:200])


# ---------------------------------------------------------------------------
# C126 -- removing a mid-line sentence keeps one separator
# ---------------------------------------------------------------------------
def test_c126_midline_removal_separator():
    print()
    print("== C126 a mid-line removal does not glue its neighbours ==")
    root = tmpdir("c126")
    (root / "main.md").write_text(
        "The benchmark is described in the supplement. The command is in "
        "code/run.py. Done.\n", encoding="utf-8")
    rep = pp.strip_dangling_references_in_dir(root, ["code"], "x")
    after = (root / "main.md").read_text(encoding="utf-8")
    check("C126 the pointer sentence is removed", rep["removed"] == 1, json.dumps(rep)[:200])
    check("C126 the neighbours keep a separator",
          after == "The benchmark is described in the supplement. Done.\n", repr(after))
    root2 = tmpdir("c126b")
    (root2 / "m.md").write_text("Methods\nWe ran code/a.py. Done.\n", encoding="utf-8")
    pp.strip_dangling_references_in_dir(root2, ["code"], "x")
    check("C126 a line-start removal gets no leading space",
          (root2 / "m.md").read_text(encoding="utf-8") == "Methods\nDone.\n",
          repr((root2 / "m.md").read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# C129 -- the delivered zip never follows a file symlink
# ---------------------------------------------------------------------------
def test_c129_zip_skips_symlinks():
    print()
    print("== C129 the package archive carries no symlink target bytes ==")
    base = tmpdir("c129")
    pkg = base / "pkg"
    pkg.mkdir()
    (pkg / "main.md").write_text("ok", encoding="utf-8")
    secret = base / "secret.txt"
    secret.write_text("TOP SECRET OUTSIDE CONTENT\n", encoding="utf-8")
    (pkg / "linked.md").symlink_to(secret)
    res = pp.write_final_clean_zip(pkg, base / "pkg.zip")
    names = zipfile.ZipFile(base / "pkg.zip").namelist()
    check("C129 the symlink is not archived",
          all(not n.endswith("linked.md") for n in names), str(names))
    check("C129 the outside bytes are not in the archive",
          b"TOP SECRET" not in (base / "pkg.zip").read_bytes())
    check("C129 the skipped link is reported",
          res["files"] == 1 and res.get("skipped_links"), json.dumps(res)[:300])


# ---------------------------------------------------------------------------
# C186 -- a PKG-2 coverage gap is not a must-repair dangling reference
# ---------------------------------------------------------------------------
def test_c186_pkg2_coverage_gap():
    print()
    print("== C186 a PKG-2 coverage gap is reported as 'not examined' ==")
    root = tmpdir("c186")
    (root / "main.docx").write_bytes(b"not a zip")
    rows = pp.non_submitted_reference_rows(root, [])
    check("C186 the unreadable DOCX is a coverage_gap row",
          len(rows) == 1 and rows[0].get("coverage_gap"), json.dumps(rows)[:300])
    ctx = type("C", (), {"root": root})()
    final = {"path": str(root), "files": 1, "digest": "d" * 64,
             "hygiene": {"non_submitted_references": rows}}
    txt = pp.final_clean_readme_text(ctx, {}, {"pin": {}}, final)
    check("C186 the readme does not call it a dangling reference to repair",
          "dangling reference(s) (PKG-2) remain" not in txt, txt[:0])
    check("C186 the readme names the not-examined document",
          "could NOT be scanned" in txt and "main.docx" in txt,
          "\n".join(l for l in txt.splitlines() if "could NOT" in l)[:300])
    rd = pp.package_readiness(final)
    check("C186 readiness does not block on a scan that never ran",
          rd["submission_ready"] and rd["blocking_findings"] == 0, json.dumps(rd)[:200])


# ---------------------------------------------------------------------------
# C114 -- the built-in redline refuses an over-budget DOCX
# ---------------------------------------------------------------------------
def test_c114_redline_byte_budget():
    print()
    print("== C114 the built-in redline caps decompressed parts ==")
    root = tmpdir("c114")
    base, rev, out = root / "b.docx", root / "r.docx", root / "out.docx"
    make_docx(base, '<w:p><w:r><w:t>hello</w:t></w:r></w:p>')
    make_docx(rev, '<w:p><w:r><w:t>hello world</w:t></w:r></w:p>')
    old = pp.REDLINE_PART_MAX_BYTES
    pp.REDLINE_PART_MAX_BYTES = 10
    try:
        res = pp.redline_one_pair("builtin", [], base, rev, out)
    finally:
        pp.REDLINE_PART_MAX_BYTES = old
    detail = (res.get("attempts") or [{}])[-1].get("detail", "")
    check("C114 an over-budget package is a recorded backend failure",
          not res.get("ok") and "byte budget" in detail, detail[:200])
    check("C114 no partial redline is left at OUT", not out.exists())
    ok = pp.redline_one_pair("builtin", [], base, rev, out)
    check("C114 a normal package still redlines", bool(ok.get("ok")),
          json.dumps(ok.get("attempts") or [])[:200])


# ---------------------------------------------------------------------------
# C124 -- pre-existing tracked changes are not the backend's own markup
# ---------------------------------------------------------------------------
def test_c124_inherited_markup_not_counted():
    print()
    print("== C124 inherited w:ins is not charged to the backend ==")
    big = " ".join(f"word{i}" for i in range(300))

    def body(tail):
        return ('<w:p><w:r><w:t>para one</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>para two</w:t></w:r></w:p>'
                f'<w:p><w:ins w:id="9" w:author="a" w:date="t"><w:r><w:t>{big}'
                f'</w:t></w:r></w:ins><w:r><w:t> {tail}</w:t></w:r></w:p>')

    root = tmpdir("c124")
    base, rev, out = root / "b.docx", root / "r.docx", root / "o.docx"
    make_docx(base, body("tail"))
    make_docx(rev, body("HEAD"))
    pp.builtin_tracked_changes(base, rev, out)
    fid = pp.redline_fidelity(base, rev, out)
    check("C124 the base's own 300 marked words are subtracted",
          fid.get("base_marked_words") == 300
          and fid.get("own_marked_words") == fid["marked_words"] - 300,
          json.dumps(fid))
    check("C124 a two-word edit is not reported as over-marked",
          fid["over_marked"] is False, json.dumps(fid))


# ---------------------------------------------------------------------------
# C125 -- redline_one_pair honours 'never raises' through the output guard
# ---------------------------------------------------------------------------
def test_c125_output_guard_never_raises():
    print()
    print("== C125 a symlinked output directory is a recorded attempt, not a raise ==")
    root = tmpdir("c125")
    (root / "elsewhere").mkdir()
    (root / "redlines").symlink_to(root / "elsewhere")
    base, rev = root / "b.docx", root / "r.docx"
    make_docx(base, '<w:p><w:r><w:t>hello</w:t></w:r></w:p>')
    make_docx(rev, '<w:p><w:r><w:t>hello world</w:t></w:r></w:p>')
    res = pp.redline_one_pair("builtin", [], base, rev,
                              root / "redlines" / "r1_w1" / "out.docx")
    check("C125 redline_one_pair returns an attempt log with a dict shape",
          isinstance(res, dict) and res.get("ok") is False
          and res["attempts"][0]["backend"] == "output-guard",
          json.dumps(res)[:300])
    check("C125 the failure names the symlinked directory",
          "symlinked" in str(res["attempts"][0]["detail"]), str(res["attempts"][0]))

    (root / "tracking").symlink_to(root / "elsewhere")
    pair = {"base_path": base, "cand_path": rev, "base_rel": "b.docx",
            "cand_rel": "r.docx", "basis": "test",
            "base_digest": sha256(base), "cand_digest": sha256(rev)}
    ctx = type("Ctx", (), {"root": root})()
    rec = pp.track_one_pair(ctx, 1, "w1", "a1", ".docx", pair, "builtin", None, {},
                            in_package=False)
    check("C125 track_one_pair records the failure instead of propagating it",
          rec.get("ok") is False and "difference tracking failed" in (rec.get("warning") or ""),
          json.dumps(rec)[:300])


# ---------------------------------------------------------------------------
# C116 -- latex_root_documents reads a bounded head
# ---------------------------------------------------------------------------
def test_c116_bounded_tex_read():
    print()
    print("== C116 the compile-root scan does not load a huge .tex whole ==")
    root = tmpdir("c116")
    (root / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}x\\end{document}\n", encoding="utf-8")
    (root / "frag.tex").write_text("no class here\n", encoding="utf-8")
    check("C116 a normal root is detected",
          pp.latex_root_documents(root) == ["main.tex"],
          str(pp.latex_root_documents(root)))
    real = pp.MAX_JSON_BYTES
    pp.MAX_JSON_BYTES = 8
    gaps = []
    try:
        roots = pp.latex_root_documents(root, gaps=gaps)
    finally:
        pp.MAX_JSON_BYTES = real
    check("C116 an over-budget .tex is skipped, not read",
          roots == [] and len(gaps) == 2, f"{roots} / {gaps}")
    check("C116 the skip is a named gap", all("NOT examined" in g for g in gaps), str(gaps))
    check("C116 a normal read restores the root",
          pp.latex_root_documents(root) == ["main.tex"])


# ---------------------------------------------------------------------------
# C127 -- render_pdf_set never raises when the set path is blocked by a file
# ---------------------------------------------------------------------------
def test_c127_render_set_blocked_path():
    print()
    print("== C127 a path blocked by a file is a recorded document failure ==")
    root = tmpdir("c127")
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}hi\\end{document}\n", encoding="utf-8")
    make_docx(pkg / "main.docx", '<w:p><w:r><w:t>hi</w:t></w:r></w:p>')
    (root / "pdfs").mkdir()
    (root / "pdfs" / "r1_w1").write_text("a file blocking the set dir", encoding="utf-8")
    ctx = type("Ctx", (), {"root": root})()
    docs = pp.render_pdf_set(ctx, "r1_w1", [(pkg, "", ())], root / "pdfs" / "r1_w1")
    docx = [d for d in docs if d.get("kind") == "docx"]
    check("C127 the DOCX attempt is recorded instead of raising",
          len(docx) == 1 and docx[0].get("ok") is False, json.dumps(docs)[:300])
    check("C127 the failure names the blocked render directory",
          "render directory could not be created" in str(docx[0].get("error")),
          str(docx[0].get("error")))


def cleanup():
    import shutil
    for d in Path(tempfile.gettempdir()).glob("fb1115w2_G7_*"):
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    try:
        test_c030_stage_strip_uses_base_area()
        test_c031_skipped_publication_names_stale_dir()
        test_c118_csv_row_by_row()
        test_c119_document_cap_gap()
        test_c120_pdf_inspector_gap()
        test_c121_one_char_header_typo()
        test_c122_sentence_boundary()
        test_c126_midline_removal_separator()
        test_c129_zip_skips_symlinks()
        test_c186_pkg2_coverage_gap()
        test_c114_redline_byte_budget()
        test_c124_inherited_markup_not_counted()
        test_c125_output_guard_never_raises()
        test_c116_bounded_tex_read()
        test_c127_render_set_blocked_path()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} failure(s)")
        for f in FAILS:
            print("  -", f)
        return 1
    print("PASSED: 0 failure(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

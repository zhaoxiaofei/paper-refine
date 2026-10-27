#!/usr/bin/env python3
"""The 2026-10-14 debug round: the PKG-2 dangling-reference scan, the redlines
adapter's exit-code contract, the XFA answer bound, the FMT-R1 repair, the
DOCX false-clean path, the submission tripwire's message, `xml:space`, and the
six skill sweeps' cover-letter rule.

Every check below is a defect an independent audit of commit `1e8a442` reported
and this round reproduced on the tree:

  * `non_submitted_reference_rows` (PKG-2) cannot see the normal prose form of
    the reference it exists to report (`See README.md.` -- the sentence-final
    period is inside the "not a filename" lookahead), reports at most ONE
    reference per line (and the area pattern is tried first, so a README beside
    an area path is lost), reports a README name inside a URL QUERY as the
    author's file, cannot see names the stripper removes (`README+.md`), and
    tells the author to run `set-submit-code on` for `code/README.md`, a switch
    that never restores a README;
  * `paper_redlines_adapter.py` swallows a non-zero `SystemExit` from the
    backend's `main` without checking the code or dropping the partial OUT, so
    a backend that truncates OUT and exits 1 is reported as a SUCCESS;
  * `XFA_LEAF_RE`'s `{1,400}` bound makes a longer answer leaf invisible: a
    filled form with a >400-character answer counts as UNFILLED and
    `xfa_export_text` (which promises "every answer") drops it;
  * the FMT-R1 repair re-adds the article number when the entry already
    carries it ("Volume 11-2020, 565825 (2020)" -> "11, 565825 565825");
  * `fix_docx_in_place` returns `note: already clean` for an UNREADABLE
    package, dropping `fix_package`'s `ok: false` + error (a false-clean);
  * the submission tripwire reports the leaked area with `p.name` -- `p` is the
    tracked-changes loop's variable (unbound when there are no redlines), so
    the guard raises UnboundLocalError instead of `die()`;
  * `_set_wt_text` writes a replacement with boundary spaces without adding
    `xml:space="preserve"` (its twin `rewrite_text_spans` does), so Word drops
    the space a "verified" repair wrote;
  * the six skill sweeps disagree about a cover letter whose name also reads
    as a reply (`cover_letter_response.md`): `extract_citations.py` tests the
    cover rule FIRST and five siblings do not (two lack it entirely).
  * the shipped docs and the CLI help still named the pre-rename
    `final_clean_version/` while `decide` publishes `final_clean_version_<root
    name>/` (plus a sibling `.zip`): a reader following the docs looks for a
    directory that no longer exists.

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
HERE = Path(__file__).resolve().parent
FAILS = []
TMPDIRS = []


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


nb = _load("nb_dbg1014", WS / "paper_pipeline.py")
fmt = _load("fmt_dbg1014", WS / "paper_docx_format.py")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def check(name: str, cond, detail: str = "") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def cleanup() -> None:
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 1. PKG-2: the dangling-reference rows
# ---------------------------------------------------------------------------

def test_pkg2_reference_rows():
    print()
    print("== P1 the PKG-2 dangling-reference scan ==")
    tmp = scratch("dbg1014_pkg2_")
    root = tmp / "sub"
    root.mkdir(parents=True)
    (root / "notes.md").write_text(
        "See README.md.\n"
        "See docs/README-dev.txt.\n"
        "Read README+.md for the extra notes.\n"
        "Mirror: https://github.com/team/repo/README.md\n"
        "Query: https://example.com/get?file=README.md\n"
        "See README.md and also raw_data/tables.tsv.\n"
        "Both (README-dev.md) and README.md apply.\n"
        "See code/README.md here\n", encoding="utf-8")
    rows = nb.non_submitted_reference_rows(root, ["raw_data", "llm_review_feedback"])
    by_line: dict = {}
    for r in rows:
        by_line.setdefault(r["line"], []).append(r)

    def refs(line: int) -> list:
        return [r["reference"] for r in by_line.get(line, [])]

    check("P1 a sentence-final README reference is reported",
          refs(1) == ["README.md"], str(rows)[:300])
    check("P1 a sentence-final nested reference is reported",
          refs(2) == ["docs/README-dev.txt"], str(refs(2)))
    check("P1 a README name the stripper removes is reported",
          refs(3) == ["README+.md"], str(refs(3)))
    check("P1 a URL ending in a README name is still not a row",
          refs(4) == [], str(refs(4)))
    check("P1 a README name inside a URL query is not the author's file",
          refs(5) == [], str(refs(5)))
    check("P1 two references on one line are both reported",
          sorted(refs(6)) == ["README.md", "raw_data/tables.tsv"], str(refs(6)))
    check("P1 two README references on one line are both reported",
          sorted(refs(7)) == ["README-dev.md", "README.md"], str(refs(7)))
    check("P1 a code/README reference names the README rule, not the code switch",
          refs(8) == ["code/README.md"]
          and "set-submit-code" not in (by_line[8][0]["detail"] if by_line.get(8) else ""),
          str(by_line.get(8))[:300])

    # The scanner must see the names the stripper drops: `is_non_submitted_
    # readme_name` removes any `readme*.(md|txt)` basename, and a submission
    # that drops a file without telling the author is the defect PKG-2 exists
    # for. A name containing a SPACE stays out on purpose: allowing whitespace
    # in the name class would bridge unrelated prose ("README and methods.md").
    dropped = ["README.md", "README+.md", "README(x).md", "readmesh.md", "readme2.md",
               "README-dev.txt"]
    for name in dropped:
        one = tmp / f"one_{name.replace('.', '_')}"
        one.mkdir()
        (one / "notes.md").write_text(f"See {name} for details\n", encoding="utf-8")
        got = [r["reference"] for r in nb.non_submitted_reference_rows(one, ["raw_data"])]
        check(f"P1 the stripper's own name class is reported: {name}",
              nb.is_non_submitted_readme_name(name) and got == [name], str(got))


# ---------------------------------------------------------------------------
# 2. the redlines adapter's exit-code contract
# ---------------------------------------------------------------------------

def test_redlines_adapter_exit_code():
    print()
    print("== P2 the redlines adapter treats a non-zero backend exit as failure ==")
    tmp = scratch("dbg1014_rl_")
    shim = tmp / "shim"
    shim.mkdir()
    (shim / "redlines.py").write_text(
        "import sys\n"
        "def main(argv):\n"
        "    with open(argv[3], 'wb') as fh:\n"
        "        fh.write(b'PARTIAL')\n"
        "    sys.exit(3)\n", encoding="utf-8")
    base, rev, out = tmp / "base.docx", tmp / "revised.docx", tmp / "out.docx"
    base.write_bytes(b"base")
    rev.write_bytes(b"revised")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(shim) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, str(WS / "paper_redlines_adapter.py"), str(base), str(rev), str(out)],
        env=env, capture_output=True, text=True)
    check("P2 a backend that exits non-zero is not reported as success",
          proc.returncode != 0, f"rc={proc.returncode} out={proc.stdout!r} err={proc.stderr!r}")
    check("P2 the partial output is dropped", not out.exists(), str(out.exists()))


# ---------------------------------------------------------------------------
# 3. the XFA answer bound
# ---------------------------------------------------------------------------

def _xfa_pdf(path: Path, answer: str) -> Path:
    packet = ("<xfa:datasets><xfa:data><form><Software><analysisinfo>"
              + answer + "</analysisinfo></Software></form></xfa:data></xfa:datasets>")
    with open(path, "wb") as fh:
        fh.write(b"%PDF-1.7\n1 0 obj<</AcroForm 2 0 R/XFA[3 0 R]>>endobj\n")
        fh.write(b"stream\n" + fmt.zlib.compress(packet.encode("utf-8")) + b"\nendstream\n")
        fh.write(b"trailer<</Root 1 0 R>>\n%%EOF\n")
    return path


def test_xfa_long_answer():
    print()
    print("== P3 the XFA reader sees an answer longer than 400 characters ==")
    tmp = scratch("dbg1014_xfa_")
    long_answer = "BWA-MEM 0.7.18; " + ("S" * 600)
    pdf = _xfa_pdf(tmp / "long.pdf", long_answer)
    is_xfa, non_empty, is_shell = fmt._xfa_dataset_report(pdf)
    check("P3 a filled form with a long answer is not counted as UNFILLED",
          is_xfa and not is_shell and non_empty == 1,
          f"is_xfa={is_xfa} non_empty={non_empty} shell={is_shell}")
    answers = fmt.xfa_dataset_answers(pdf)
    check("P3 xfa_export_text's source carries the long answer",
          answers == [("analysisinfo", long_answer)], str(answers)[:160] + f"(len={len(long_answer)})")
    short = _xfa_pdf(tmp / "short.pdf", "BWA-MEM 0.7.18")
    check("P3 the short answer still counts",
          fmt._xfa_dataset_report(short)[1] == 1, str(fmt._xfa_dataset_report(short)))
    empty = _xfa_pdf(tmp / "empty.pdf", "")
    check("P3 an empty form still counts zero",
          fmt._xfa_dataset_report(empty)[1] == 0, str(fmt._xfa_dataset_report(empty)))


# ---------------------------------------------------------------------------
# 4. the FMT-R1 repair
# ---------------------------------------------------------------------------

def test_reference_repair_duplicate_page():
    print()
    print("== P4 the FMT-R1 repair does not duplicate the article number ==")
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           "<w:body>"
           '<w:p><w:r><w:t>15.Dong, X. et al. SCCNV tool. Front. Genet. Volume 11-2020, '
           "565825 (2020).</w:t></w:r></w:p>"
           "</w:body></w:document>")
    recs = [{"key": "dong2020", "first_family": "Dong", "author": "Dong, Xiao",
             "title": "SCCNV: a software tool", "year": "2020", "volume": "11",
             "pages": "565825", "doi": "10.3389/fgene.2020.565825"}]
    res = fmt.repair_reference_entries(xml, recs)
    joined = " ".join(fmt.text_of(p[2]) for p in fmt.paragraphs(res["xml"]))
    check("P4 the fused volume is still repaired",
          "Front. Genet. 11, 565825 (2020)." in joined, joined[:200])
    check("P4 the article number is not written twice",
          "565825 565825" not in joined, joined[:200])
    # ... and the entry shape with NO page still gains the bibliography's number.
    xml2 = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>"
            '<w:p><w:r><w:t>15.Dong, X. et al. SCCNV tool. Front. Genet. Volume 11-2020, '
            "(2020).</w:t></w:r></w:p>"
            "</w:body></w:document>")
    res2 = fmt.repair_reference_entries(xml2, recs)
    joined2 = " ".join(fmt.text_of(p[2]) for p in fmt.paragraphs(res2["xml"]))
    check("P4 the paged-less shape still gains volume, article number",
          "Front. Genet. 11, 565825 (2020)." in joined2, joined2[:200])


# ---------------------------------------------------------------------------
# 5. the DOCX false-clean
# ---------------------------------------------------------------------------

def test_fix_docx_in_place_unreadable():
    print()
    print("== P5 an unreadable DOCX is not 'already clean' ==")
    tmp = scratch("dbg1014_fix_")
    p = tmp / "manuscript.docx"
    p.write_bytes(b"this is not a zip container at all")
    rep = nb.fix_docx_in_place(p, {})
    check("P5 the failure is reported, not swallowed as 'already clean'",
          rep.get("note") != "already clean" and bool(rep.get("error")),
          str(rep)[:300])
    check("P5 the original file is left in place",
          p.read_bytes() == b"this is not a zip container at all")


# ---------------------------------------------------------------------------
# 6. the submission tripwire
# ---------------------------------------------------------------------------

def test_submission_tripwire_message():
    print()
    print("== P6 the non-submitted-area tripwire dies cleanly ==")
    tmp = scratch("dbg1014_tw_")
    root = tmp / "root"
    root.mkdir()
    target = tmp / "src"
    (target / "code").mkdir(parents=True)
    (target / "manuscript.txt").write_text("Methods\n", encoding="utf-8")
    (target / "code" / "analysis.py").write_text("print(1)\n", encoding="utf-8")
    ctx = types.SimpleNamespace(root=root, cfg={}, state={}, rounds_count=lambda: 0)
    real = nb.rmtree_force

    def stubborn(path, *a, **k):
        # Simulate the deletion that did not happen: the guard then sees the
        # area still in the package (its error path, never the normal one).
        if Path(path).name == "code":
            return False
        return real(path, *a, **k)

    nb.rmtree_force = stubborn
    try:
        raised = None
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                nb.publish_journal_submission(ctx, target, "label", response_dir=None)
        except BaseException as e:                                # noqa: BLE001
            raised = e
    finally:
        nb.rmtree_force = real
    check("P6 the tripwire raises its own die(), not NameError/UnboundLocalError",
          isinstance(raised, SystemExit) and "NON-SUBMITTED area" in err.getvalue(),
          f"{type(raised).__name__}: {raised} / {err.getvalue()[:200]}")
    check("P6 the message names the leaked area, not a tracked-changes file",
          "(code)" in err.getvalue(), err.getvalue()[:200])


# ---------------------------------------------------------------------------
# 7. xml:space on a repaired w:t
# ---------------------------------------------------------------------------

def test_wt_text_preserve_space():
    print()
    print("== P7 a repaired w:t with boundary whitespace keeps its spaces ==")
    # The replacement ENDS the element (a fused volume at the paragraph's end,
    # replaced by "volume, article number"): without xml:space="preserve" Word
    # ignores the trailing space the repair wrote.
    para = '<w:p><w:r><w:t>Front. Genet. Volume 11-2020</w:t></w:r></w:p>'
    out = fmt._replace_text_in_para(para, "Volume 11-2020", "11, 565825 ")
    check("P7 the replacement lands", bool(out) and "11, 565825" in (out or ""), str(out))
    check("P7 xml:space=preserve is added for a trailing boundary space",
          bool(out) and 'xml:space="preserve"' in out, str(out))
    check("P7 the element text keeps the trailing space",
          bool(out) and "11, 565825 </w:t>" in out, str(out))
    # The FMT-R3 locator replacement STARTS with a space (" (2019). <url>"): at
    # an element boundary Word would drop it and glue the sentences together.
    para2 = '<w:p><w:r><w:t>. https://github.com/jlaffy/infercna</w:t></w:r></w:p>'
    out2 = fmt._replace_text_in_para(para2, ". https://github.com/jlaffy/infercna",
                                     " (2019). https://github.com/jlaffy/infercna")
    check("P7 xml:space=preserve is added for a leading boundary space",
          bool(out2) and 'xml:space="preserve"> (2019).' in (out2 or ""), str(out2))
    # ... and an attribute the source carried still survives verbatim.
    already = '<w:p><w:r><w:t xml:space="preserve">old</w:t></w:r></w:p>'
    out3 = fmt._replace_text_in_para(already, "old", "new")
    check("P7 an existing xml:space still survives verbatim",
          bool(out3) and 'xml:space="preserve"' in out3 and "new" in out3, str(out3))
    internal = '<w:p><w:r><w:t>Front. Genet. Volume 11-2020, (2020).</w:t></w:r></w:p>'
    out4 = fmt._replace_text_in_para(internal, "Volume 11-2020, ", "11, 565825 ")
    check("P7 an internal space is written normally",
          bool(out4) and "11, 565825 (2020)." in fmt.text_of(out4) and out4.count("<w:t") == 1,
          str(out4))


# ---------------------------------------------------------------------------
# 8. the six skill sweeps agree that a cover letter is a submission document
# ---------------------------------------------------------------------------

SKILL_SCRIPTS = {
    "count_words.py": "is_evidence_path",
    "extract_acronyms.py": "is_evidence_name",
    "extract_citations.py": "is_non_manuscript",
    "extract_numbers.py": "is_non_manuscript",
    "extract_occurrences.py": "is_non_manuscript",
    "enumerate_conventions.py": "_non_manuscript",
}

CORPUS_NAMES = [
    "cover_letter_response.md",      # a cover letter that also reads as a reply
    "cover_letter.md",               # an ordinary cover letter
    "cover_letter_to_reviewers.docx.txt",
    "RESPONSE_TO_REVIEWERS.md",      # the pipeline's own reply name
    "point-by-point_response.md",
    "dose_response.csv",             # a data name, not a reply (by-name rule)
    "methods.md",
]


def test_skill_cover_letter_rule():
    print()
    print("== P8 the six sweeps apply the cover-letter rule first ==")
    verdicts = {}
    for script, fn_name in sorted(SKILL_SCRIPTS.items()):
        mod = _load(f"skill_{script[:-3]}", WS / "paper-skills" / "paper-review"
                    / "scripts" / script)
        fn = getattr(mod, fn_name)
        verdicts[script] = {n: bool(fn(n)) for n in CORPUS_NAMES}
    for name in CORPUS_NAMES:
        got = {s: v[name] for s, v in verdicts.items()}
        check(f"P8 the sweeps agree on {name!r}", len(set(got.values())) == 1, str(got))
    check("P8 a cover letter named *response* is a submission document everywhere",
          all(not v["cover_letter_response.md"] for v in verdicts.values()),
          str({s: v["cover_letter_response.md"] for s, v in verdicts.items()}))
    check("P8 an ordinary cover letter is a submission document everywhere",
          all(not v["cover_letter.md"] for v in verdicts.values()),
          str({s: v["cover_letter.md"] for s, v in verdicts.items()}))
    check("P8 the pipeline's reply name is still evidence",
          all(v["RESPONSE_TO_REVIEWERS.md"] for v in verdicts.values()),
          str({s: v["RESPONSE_TO_REVIEWERS.md"] for s, v in verdicts.items()}))
    check("P8 a reply file outside the areas is still evidence by name",
          all(v["point-by-point_response.md"] for v in verdicts.values()),
          str({s: v["point-by-point_response.md"] for s, v in verdicts.items()}))


# ---------------------------------------------------------------------------
# 9. the numeric occurrence guard and the scratch ignore rule
# ---------------------------------------------------------------------------

def test_value_occurrence_decimal_guard():
    print()
    print("== P9 --value 12 does not match inside 12.5 ==")
    tmp = scratch("dbg1014_val_")
    work = tmp / "work"
    (work / "corpus").mkdir(parents=True)
    out = tmp / "out"
    doc = work / "corpus" / "notes.txt"
    doc.write_text("The dose was 12.5 mg and the count was 12 in cohort A.\n",
                   encoding="utf-8")
    script = (WS / "paper-skills" / "paper-review" / "scripts"
              / "extract_occurrences.py")
    proc = subprocess.run([sys.executable, str(script), "--value", "12",
                           "--work", str(work), "--out", str(out)],
                          capture_output=True, text=True)
    body = proc.stdout + proc.stderr
    check("P9 the run succeeds", proc.returncode == 0, body[:300])
    art = out / "occurrences_12.json"
    blocks = json.loads(art.read_text(encoding="utf-8")) if art.exists() else []
    value = next((b for b in blocks if b.get("mode") == "value"), {})
    matches = [o["match"] for o in value.get("occurrences", [])]
    check("P9 only the standalone 12 is inventoried (12.5 is a different value)",
          matches == ["12"], f"matches={matches} body={body[:200]}")


def test_scratch_dirs_are_not_tracked():
    print()
    print("== P10 the mkdtemp scratch shape is ignored and untracked ==")
    ignore = (WS / ".gitignore").read_text(encoding="utf-8")
    check("P10 .gitignore covers the tmp<random> shape the debug runs create",
          any(line.strip() and not line.strip().startswith("#")
              and line.strip().rstrip("/").startswith("tmp")
              and line.strip().rstrip("/") != "tmp" for line in ignore.splitlines()),
          ignore[-400:])
    for stray in ("tmp04yv2pe9", "tmp1phhddwc", "tmphvt8_zlt"):
        check(f"P10 {stray}/ is not tracked", not (WS / stray).exists()
              or not subprocess.run(["git", "ls-files", "--error-unmatch", stray],
                                    cwd=WS, capture_output=True).returncode == 0)


# ---------------------------------------------------------------------------
# 11. the remaining confirmed defects of the same round
# ---------------------------------------------------------------------------

def test_entity_round_trip():
    print()
    print("== P11 &quot;/&apos; are decoded once, not re-escaped ==")
    x = 'He said &quot;hello&quot; and it&apos;s fine.'
    decoded = fmt.unesc(x)
    check("P11 the XML quotes decode to real quotes",
          decoded == 'He said "hello" and it\'s fine.', repr(decoded))
    check("P11 re-escaping does not double-escape them",
          "&amp;quot;" not in fmt.esc(decoded), repr(fmt.esc(decoded)))
    check("P11 the decode is stable (single pass)",
          fmt.unesc(fmt.esc(decoded)) == decoded, repr(fmt.unesc(fmt.esc(decoded))))
    para = '<w:p><w:r><w:t>He said &quot;hello&quot;.</w:t></w:r></w:p>'
    check("P11 the paragraph reader sees the quotes, not the reference",
          fmt.text_of(para) == 'He said "hello".', repr(fmt.text_of(para)))
    check("P11 an already-escaped reference stays literal (no double decode)",
          fmt.unesc("&amp;quot;") == "&quot;", repr(fmt.unesc("&amp;quot;")))


def test_multi_run_formatting_is_refused():
    print()
    print("== P12 a multi-run match that would drop formatting is refused ==")
    plain = ('<w:p><w:r><w:t>Front. Genet. Volume </w:t></w:r>'
             '<w:r><w:t>11-2020, (2020).</w:t></w:r></w:p>')
    out = fmt._replace_text_in_para(plain, "Volume 11-2020, ", "11, 565825 ")
    check("P12 a plain multi-run match is still replaced",
          bool(out) and "11, 565825" in fmt.text_of(out), str(out)[:160])
    bold = ('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Front. Genet. Volume </w:t></w:r>'
            '<w:r><w:t>11-2020, (2020).</w:t></w:r></w:p>')
    refused = fmt._replace_text_in_para(bold, "Volume 11-2020, ", "11, 565825 ")
    check("P12 a run carrying w:rPr makes the replacement refuse (None)",
          refused is None, str(refused)[:200])
    italic_second = ('<w:p><w:r><w:t>Front. Genet. Volume </w:t></w:r>'
                     '<w:r><w:rPr><w:i/></w:rPr><w:t>11-2020, (2020).</w:t></w:r></w:p>')
    check("P12 w:rPr on ANY touched run refuses",
          fmt._replace_text_in_para(italic_second, "Volume 11-2020, ",
                                    "11, 565825 ") is None)


def test_bib_comments_are_not_facts():
    print()
    print("== P13 a commented-out .bib entry supplies no facts ==")
    tmp = scratch("dbg1014_bib_")
    bib = tmp / "refs.bib"
    bib.write_text(
        "% @article{commented2020,\n"
        "%   title = {A commented out paper},\n"
        "%   author = {Off, Switch},\n"
        "%   volume = {9}, pages = {111}, date = {2020}\n"
        "% }\n"
        "@article{live2020,\n  title = {A live paper},\n  author = {Zed, Wren},\n"
        "  volume = {3}, pages = {7}, date = {2021}\n}\n"
        "@article{percent2022,\n  title = {Growth was 100% in controls},\n"
        "  author = {Pct, Pat},\n  volume = {4}, pages = {8}, date = {2022}\n}\n",
        encoding="utf-8")
    keys = [r["key"] for r in fmt.load_bib_facts([bib])]
    check("P13 the commented-out entry is skipped",
          "commented2020" not in keys, str(keys))
    check("P13 the live entries are still parsed",
          keys == ["live2020", "percent2022"], str(keys))


def test_cmd_fix_removes_rejected_output():
    print()
    print("== P14 the rejected --out artifact is removed, not left as a good file ==")
    tmp = scratch("dbg1014_cmdfix_")
    src = tmp / "in.docx"
    src.write_bytes(b"not a real docx")
    out = tmp / "out.docx"
    out.write_bytes(b"the rejected artifact")
    real = fmt.fix_package
    fmt.fix_package = lambda s, o, p: {
        "ok": False, "changes": [], "error": "verification failed: stub",
        "verified": {"text_identical": True, "parts_intact": True,
                     "mechanical_findings_before": 1, "mechanical_findings_after": 1,
                     "schema_detail": "stub"}}
    try:
        rc = fmt.cmd_fix(types.SimpleNamespace(
            file=str(src), out=str(out), policy=None, json=None,
            unlink_zotero_fields=False))
    finally:
        fmt.fix_package = real
    check("P14 cmd_fix still reports the failure", rc == 1, str(rc))
    check("P14 a pre-existing output survives a rejected fix", out.exists(), str(out.exists()))


def test_json_from_text_picks_the_document():
    print()
    print("== P15 the lenient JSON reader returns the embedded document ==")
    check("P15 a bare document parses", nb._json_from_text('{"a": 1}', True) == {"a": 1})
    check("P15 a fenced document parses",
          nb._json_from_text('```json\n{"a": 1}\n```', True) == {"a": 1})
    check("P15 an introduced document parses",
          nb._json_from_text("Here it is: {\"a\": 1}", True) == {"a": 1})
    got = nb._json_from_text(
        'The schema is {"example": true}. And the data is: {"n": 12, "ok": true}', True)
    check("P15 an in-prose EXAMPLE does not win over the payload",
          got == {"n": 12, "ok": True}, str(got))
    check("P15 a document buried in lots of prose is still refused",
          nb._json_from_text("A" * 1000 + '{"a": 1}' + "B" * 1000, True) is None)
    check("P15 a truncated document is still refused",
          nb._json_from_text('{"a": 1', True) is None)


def test_zotero_refresh_refuses_aux_field_parts():
    print()
    print("== P18 a live Zotero field outside document.xml is refused, not ignored ==")

    def parts_with(part: str, body: str) -> dict:
        return {"word/document.xml": b"<w:document/>",
                part: body.encode("utf-8")}

    field = ('<w:p><w:r><w:instrText>ADDIN ZOTERO_ITEM CSL_CITATION {"id":1}'
             "</w:instrText></w:r></w:p>")
    for part in ("word/header1.xml", "word/footer2.xml", "word/comments.xml",
                 "word/footnotes.xml", "word/endnotes.xml"):
        rep = fmt.refresh_zotero_parts(parts_with(part, field))
        check(f"P18 a Zotero field in {part} makes the refresh refuse",
              bool(rep.get("skip")) and part in str(rep.get("skip")), str(rep)[:200])
    plain = fmt.refresh_zotero_parts(parts_with("word/header1.xml", "<w:p/>"))
    check("P18 a header with no Zotero field is not refused for its part",
          "header1.xml" not in str(plain.get("skip") or ""), str(plain)[:200])


def test_mcp_config_array_parsing():
    print()
    print("== P16 a legal TOML args array is not silently dropped ==")
    tmp = scratch("dbg1014_mcp_")
    cfg = tmp / "config.toml"
    real = nb.codex_config_path
    import contextlib as _ctx
    for label, line, want in [
        ("double-quoted (JSON-compatible)", 'args = ["node", "server.js"]',
         ["node", "server.js"]),
        ("TOML literal strings", "args = ['node', 'server.js']", ["node", "server.js"]),
        ("TOML trailing comma", 'args = ["node", "server.js",]', ["node", "server.js"]),
        ("a bracket inside an argument", 'args = ["--filter", "a]b", "s.js"]',
         ["--filter", "a]b", "s.js"]),
        ("empty array", "args = []", []),
    ]:
        cfg.write_text('[mcp_servers.docx]\ncommand = "node"\n' + line + "\n",
                       encoding="utf-8")
        nb.codex_config_path = lambda p=cfg: p
        try:
            spec = nb.mcp_server_spec("docx")
        finally:
            nb.codex_config_path = real
        check(f"P16 {label}", spec.get("args") == want and spec.get("command") == "node",
              str(spec))
    cfg.write_text('[mcp_servers.docx]\ncommand = "node"\nargs = [node, "s.js"]\n',
                   encoding="utf-8")
    nb.codex_config_path = lambda p=cfg: p
    try:
        spec = nb.mcp_server_spec("docx")
    finally:
        nb.codex_config_path = real
    check("P16 a malformed array is reported unreadable, not as 'no arguments'",
          spec == {}, str(spec))


def test_scan_and_validate_report_missing_paths():
    print()
    print("== P17 a path that does not exist is not a clean report ==")
    missing = "/tmp/dbg1014_definitely_missing_file.docx"
    for cmd in ("scan", "validate"):
        proc = subprocess.run([sys.executable, str(WS / "paper_docx_format.py"), cmd, missing],
                              capture_output=True, text=True)
        check(f"P17 `{cmd}` refuses a missing path (no 'clean'/0-failure claim)",
              proc.returncode != 0 and "no such file" in (proc.stdout + proc.stderr),
              f"rc={proc.returncode} out={(proc.stdout + proc.stderr)[:200]!r}")


def test_docs_name_the_published_directory():
    print()
    print("== P19 the user-facing docs and CLI help name the published directory ==")
    # `decide` publishes `final_clean_version_<root name>/` (see
    # final_clean_dirname); a doc/help line that still spells the bare
    # `final_clean_version/` sends the operator to a directory that does not
    # exist. The sibling status file (`final_clean_version.readme.md`) and the
    # suffixed name itself are not matches -- the token needs the trailing `/`.
    stale = []
    for rel in ("README.md", "AGENTS.md", ".paper_test/README.md"):
        for i, line in enumerate((WS / rel).read_text(encoding="utf-8").splitlines(), 1):
            if "final_clean_version/" in line:
                stale.append(f"{rel}:{i}: {line.strip()[:100]}")
    for argv in (["--help"], ["decide", "--help"], ["conform", "--help"]):
        proc = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), *argv],
                              capture_output=True, text=True, timeout=120)
        for line in (proc.stdout + proc.stderr).splitlines():
            if "final_clean_version/" in line:
                stale.append(f"CLI {' '.join(argv)}: {line.strip()[:100]}")
    check("P19 nothing names the pre-rename final_clean_version/ as the published path",
          not stale, " | ".join(stale)[:400])


def main() -> int:
    test_pkg2_reference_rows()
    test_redlines_adapter_exit_code()
    test_xfa_long_answer()
    test_reference_repair_duplicate_page()
    test_fix_docx_in_place_unreadable()
    test_submission_tripwire_message()
    test_wt_text_preserve_space()
    test_skill_cover_letter_rule()
    test_value_occurrence_decimal_guard()
    test_scratch_dirs_are_not_tracked()
    test_entity_round_trip()
    test_multi_run_formatting_is_refused()
    test_bib_comments_are_not_facts()
    test_cmd_fix_removes_rejected_output()
    test_json_from_text_picks_the_document()
    test_mcp_config_array_parsing()
    test_scan_and_validate_report_missing_paths()
    test_zotero_refresh_refuses_aux_field_parts()
    test_docs_name_the_published_directory()
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL 2026-10-14 DEBUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

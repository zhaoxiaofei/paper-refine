#!/usr/bin/env python3
"""The 2026-10-16 debug round: the defects an independent audit of `938e3bd`
reported and this round reproduced on the tree.

Run:  python3 .paper_test/test_debug_2026_1016.py

Every check below is a reproduced defect (the audit's report only seeds the
list; each one was re-derived here):

  * `fix_document` step 2 moved/removed a break-only paragraph INSIDE a table
    cell, leaving `<w:tc></w:tc>` -- schema-invalid OOXML the well-formedness
    and text-identity checks cannot see (the sibling step 2b already had the
    guard, so a cell lost its only paragraph);
  * the `redlines` adapter fell through to an unbound `res` when a module-level
    helper raised `SystemExit(0)` -> `UnboundLocalError` instead of the
    documented probe/exit code;
  * `install_skill.sh` re-run on the same day copied the tool INTO the existing
    `<tool>-<version>` snapshot (`cp -r` into an existing dir), so the
    snapshot's top level kept the previous run's bytes and the fresh copy sat
    one level down;
  * the skill's `revision_token.py` derived a DIFFERENT token than the pipeline
    (`paper_pipeline.revision_token_for_dir`) for the same package -- twice: a
    bookkeeping family (`code_scans`/`format_scan`/`format_fix`/`pkg2`) was in
    one `BOOKKEEPING_NAME_RE` but not the other, and `tree_files` did not seed
    its ancestor set with the root inode, so a link back at the package
    (`loop -> .`) duplicated the walk;
  * `classify_context` in extract_acronyms/extract_citations/extract_numbers
    still tested `"cover" in name` (the substring), naming `discovery.md`,
    `coverage_table.txt` and `recovered_samples.md` a cover letter -- the very
    bug the module comment documents `_COVER_WORD_RE` to prevent;
  * `_strip_latex` left `p12` from `\\pageref{p12}` in the M19 word count and
    read `\\$5 to \\$6` as math;
  * `strip_reference_sentences` crashed on a non-UTF-8 `word/document.xml`
    instead of returning its own `{"ok": False, "error": ...}` record;
  * `publish_final_clean` reported the NEW `final_digest` while serving the
    OLD bytes: same file names + different content took the `unchanged` branch;
  * `declared_submission_set` stopped at the first `README*` that did not carry
    a declaration (so a sibling `README_SUBMISSION.md` was never read) and its
    `README*` glob missed a lowercase `readme.md` the rest of the pipeline
    treats as a readme;
  * PKG-8 (`unit_of_analysis_rows`) fired on a caption whose unit IS defined,
    because it pairs with the first DIFFERENT declaration and never checks for
    a matching one;
  * PKG-7 (`truncated_identifier_rows`) matched only lowercase hex, so the same
    35-vs-40 hex identifier printed in caps was silent;
  * `_raw_data_key` folded two distinct raw-data files (`cohort_a.tsv` /
    `cohort_b.tsv`) into one key, so the read-only byte verification silently
    skipped one file of every colliding pair.

D15 is the one check in this file with no audit row behind it: the double-check
pass found that swapping `_entries_in`'s key from the folded name to the exact
path left `raw_data_advisories` reading those keys token-blind, so a compliant
winner carrying the base's token names was reported as a deviation. It is a
guard, not a repro of an original defect (the baseline passes it).

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

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

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
HERE = Path(__file__).resolve().parent
FAILS = []
TMPDIRS = []
W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_debug1016_pipeline", WS / "paper_pipeline.py")
fmt = _load("paper_debug1016_format", WS / "paper_docx_format.py")


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def skip(name, why):
    print(f"[skip] {name}  -- {why}")


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def write(p: Path, text: str, mode: int = None) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if mode is not None:
        os.chmod(p, mode)


def make_docx(path: Path, paras: list) -> None:
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>'
                   for p in paras)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document {W_NS}><w:body>{body}</w:body></w:document>')


# =====================================================================
# D1. fix_document: a table cell must keep its `<w:p>`
# =====================================================================

def test_break_only_paragraph_in_table_cell():
    print()
    print("== D1: a break-only paragraph inside a table cell is not spliced out ==")
    xml = (f'<w:document {W_NS}><w:body>'
           '<w:p><w:r><w:t>Normal paragraph.</w:t></w:r></w:p>'
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:br w:type="page"/></w:r></w:p></w:tc>'
           '<w:tc><w:p><w:r><w:t>cell text</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
           '<w:p><w:r><w:t>After.</w:t></w:r></w:p>'
           '</w:body></w:document>')
    new, changes, _meta = fmt.fix_document(xml, {}, fmt.load_policy(None))
    cells = re.findall(r"<w:tc>.*?</w:tc>", new, re.S)
    check("D1 every table cell still carries a paragraph",
          len(cells) == 2 and all("<w:p>" in c and "</w:p>" in c for c in cells),
          repr(cells))
    check("D1 the cell's own page break is not moved into another cell",
          'w:type="page"' in new and "pageBreakBefore" not in cells[1],
          repr(cells[1]))
    check("D1 the document text is unchanged", "cell text" in new, new[:200])
    # The body-level case the rule exists for still works.
    body = (f'<w:document {W_NS}><w:body>'
            '<w:p><w:r><w:t>Title page.</w:t></w:r></w:p>'
            '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
            '<w:p><w:r><w:t>Introduction.</w:t></w:r></w:p>'
            '</w:body></w:document>')
    fixed, changes, _meta = fmt.fix_document(body, {}, fmt.load_policy(None))
    check("D1 a BODY break-only paragraph still moves onto the next paragraph",
          "pageBreakBefore" in fixed and "was the empty p1" in " ".join(changes),
          str(changes))


# =====================================================================
# D2. paper_redlines_adapter: a clean SystemExit is not an exception
# =====================================================================

def test_adapter_clean_systemexit():
    print()
    print("== D2: a redlines helper that exits 0 does not crash the adapter ==")
    tmp = scratch("paper_adapter_exit0_")
    write(tmp / "redlines.py",
          "def compare_docx(*a):\n    raise SystemExit(0)\n")
    write(tmp / "base.docx", "base")
    write(tmp / "revised.docx", "revised")
    env = dict(os.environ, PYTHONPATH=str(tmp))
    proc = subprocess.run([sys.executable, str(WS / "paper_redlines_adapter.py"),
                           "base.docx", "revised.docx", "out.docx"],
                          cwd=str(tmp), capture_output=True, text=True, env=env, timeout=120)
    out = proc.stdout + proc.stderr
    check("D2 the adapter reports exit 5 (no supported interface), not a traceback",
          proc.returncode == 5 and "UnboundLocalError" not in out
          and "NameError" not in out and "Traceback" not in out,
          f"rc={proc.returncode} {out[-200:]}")


# =====================================================================
# D3. install_skill.sh: a same-day re-run keeps ONE flat snapshot
# =====================================================================

def test_install_skill_rerun():
    print()
    print("== D3: a same-day re-run does not nest the versioned tool snapshot ==")
    if not shutil.which("bash"):
        skip("D3 install_skill.sh re-run", "no bash on this machine")
        return
    tmp = scratch("paper_install_skill_")
    repo = tmp / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    shutil.copy2(WS / "install_skill.sh", repo / "install_skill.sh")
    write(repo / "paper-skills" / "SKILL.md", "# skills\n")
    for tool in ("mcp-docx-converter", "mcp-docx-compare"):
        write(repo / tool / "index.js", f"// {tool} version ONE\n")
        write(repo / tool / "package.json", json.dumps({"name": tool}))
    write(repo / "docx2pdf.sh", "#!/bin/sh\n", mode=0o755)
    write(repo / "docxcompare.sh", "#!/bin/sh\n", mode=0o755)
    bindir = tmp / "bin"
    write(bindir / "npm", "#!/bin/sh\nexit 0\n", mode=0o755)
    env = dict(os.environ, HOME=str(tmp / "home"), MCP_TOOLS_DIR=str(tmp / "tools"),
               PATH=f"{bindir}:{os.environ.get('PATH','')}")
    run = ["bash", str(repo / "install_skill.sh")]
    first = subprocess.run(run, capture_output=True, text=True, env=env, timeout=180)
    check("D3 the first install succeeds", first.returncode == 0,
          (first.stdout + first.stderr)[-200:])
    write(repo / "mcp-docx-converter" / "index.js", "// mcp-docx-converter version TWO\n")
    second = subprocess.run(run, capture_output=True, text=True, env=env, timeout=180)
    check("D3 the same-day re-run succeeds", second.returncode == 0,
          (second.stdout + second.stderr)[-200:])
    versions = sorted((tmp / "tools").glob("mcp-docx-converter-*"))
    check("D3 the versioned snapshot exists", len(versions) == 1,
          str([v.name for v in versions]))
    if versions:
        snap = versions[0]
        top = (snap / "index.js").read_text(encoding="utf-8") if (snap / "index.js").is_file() \
            else ""
        check("D3 the snapshot's TOP level carries the fresh bytes", "version TWO" in top,
              repr(top))
        check("D3 the snapshot is not nested inside itself",
              not (snap / "mcp-docx-converter").exists(),
              str(sorted(p.name for p in snap.iterdir())))


# =====================================================================
# D4. the skill and the pipeline must derive the SAME revision token
# =====================================================================

def test_revision_token_agreement():
    print()
    print("== D4: paper_pipeline.revision_token_for_dir == revision_token.py ==")
    if str(WS) not in sys.path:
        sys.path.insert(0, str(WS))
    rt = _load("paper_debug1016_token",
               WS / "paper-skills" / "paper-revise" / "scripts" / "revision_token.py")
    # a) plain package
    plain = scratch("paper_token_plain_")
    write(plain / "paper.txt", "manuscript body\n")
    a, b = pp.revision_token_for_dir(plain), rt.revision_token(plain)
    check("D4 a plain package gets the same token from both implementations",
          a["token"] == b["token"] and a["token"], f"{a['token']} vs {b['token']}")
    # b) the bookkeeping family the pipeline excludes
    book = scratch("paper_token_bookkeeping_")
    write(book / "paper.txt", "manuscript body\n")
    write(book / "code_scans_2026-1016.json", "{}\n")
    a, b = pp.revision_token_for_dir(book), rt.revision_token(book)
    check("D4 a pipeline measurement artifact is bookkeeping for BOTH implementations",
          a["token"] == b["token"], f"{a['token']} vs {b['token']}")
    # c) a link back at the package
    loop = scratch("paper_token_loop_")
    write(loop / "paper.txt", "manuscript body\n")
    os.symlink(".", loop / "loop")
    a, b = pp.revision_token_for_dir(loop), rt.revision_token(loop)
    check("D4 a self-link is walked once by BOTH implementations",
          a["token"] == b["token"], f"{a['token']} vs {b['token']}")
    # d) a token-looking name inside a DISABLED evidence area is inert for both
    dis = scratch("paper_token_disabled_")
    write(dis / "paper.txt", "manuscript body\n")
    write(dis / "raw_data.disabled" / "figure-4f3a9c1.png", "png\n")
    a, b = pp.revision_token_for_dir(dis), rt.revision_token(dis)
    check("D4 a disabled evidence area is inert for BOTH implementations",
          a["consistent"] == b["consistent"] and a["hex_tokens"] == b["hex_tokens"],
          f"pipeline {a['hex_tokens']}/{a['consistent']} vs "
          f"skill {b['hex_tokens']}/{b['consistent']}")


# =====================================================================
# D5. classify_context: the WORD "cover", not the substring
# =====================================================================

def test_cover_word_classification():
    print()
    print("== D5: discovery.md is not a cover letter ==")
    base = WS / "paper-skills" / "paper-review" / "scripts"
    for name in ("extract_acronyms", "extract_citations", "extract_numbers"):
        mod = _load(f"paper_debug1016_{name}", base / f"{name}.py")
        wrong = {n: mod.classify_context(n)
                 for n in ("discovery.md", "coverage_table.txt", "recovered_samples.md")}
        check(f"D5 {name}: a name that merely CONTAINS 'cover' is not a cover letter",
              all(v != "cover letter" for v in wrong.values()), json.dumps(wrong))
        right = {n: mod.classify_context(n) for n in ("cover_letter.md", "cover-letter.txt")}
        check(f"D5 {name}: a real cover-letter name still classifies",
              all(v == "cover letter" for v in right.values()), json.dumps(right))


# =====================================================================
# D6. _strip_latex: no phantom words, no escaped-dollar math
# =====================================================================

def test_strip_latex():
    print()
    print("== D6: the M19 LaTeX prose reader ==")
    sys.path.insert(0, str(WS / "paper-skills" / "paper-review" / "scripts"))
    cw = _load("paper_debug1016_count_words",
               WS / "paper-skills" / "paper-review" / "scripts" / "count_words.py")
    pairs = [(pp._strip_latex, "pipeline"), (cw._strip_latex, "count_words")]
    for fn, label in pairs:
        out = fn(r"See \pageref{p12} for details.")
        check(f"D6 {label}: \\pageref{{p12}} leaves no phantom 'p12' word",
              "p12" not in out, repr(out))
        out = fn(r"The \eqref{eq:1} and \autoref{fig:2} above.")
        check(f"D6 {label}: the reference-command family is stripped",
              "eq:1" not in out and "fig:2" not in out, repr(out))
        out = fn(r"It costs \$5 to \$6 per unit.")
        check(f"D6 {label}: an ESCAPED dollar is not math",
              "5" in out and "to" in out and "6" in out, repr(out))
    a = pp._strip_latex(r"See \pageref{p12} and \$5 to \$6.")
    b = cw._strip_latex(r"See \pageref{p12} and \$5 to \$6.")
    check("D6 the pipeline and the skill strip identically", a == b, f"{a!r} vs {b!r}")


# =====================================================================
# D7. strip_reference_sentences on a non-UTF-8 document.xml
# =====================================================================

def test_strip_reference_sentences_encoding():
    print()
    print("== D7: a non-UTF-8 document.xml returns a record, never a crash ==")
    tmp = scratch("paper_strip_enc_")
    src = tmp / "src.docx"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document {W_NS}><w:body><w:p><w:r><w:t>See base.tsv</w:t>'
                   f'</w:r></w:p></w:body></w:document>'.encode("utf-16"))
    out = tmp / "out.docx"
    try:
        res = fmt.strip_reference_sentences(src, out, lambda text: [(0, 4)])
    except Exception as e:                                          # noqa: BLE001
        check("D7 a non-UTF-8 document.xml is reported, not raised", False,
              f"{type(e).__name__}: {e}")
        return
    check("D7 the record carries ok=False and an error naming the decode failure",
          res.get("ok") is False and "error" in res, json.dumps(res)[:200])


# =====================================================================
# D8. publish_final_clean: what it reports is what it serves
# =====================================================================

def test_publish_reports_the_served_bytes():
    print()
    print("== D8: a re-decide over changed bytes republishes ==")
    root = scratch("paper_publish_stale_")
    write(root / "pipeline_config.json",
          json.dumps({"rounds": 1, "judges": [1], "source": "/tmp/src",
                      "venue": "nature-biotechnology", "article_type": "article"}))
    winner = root / "round1_winner"
    make_docx(winner / "paper.docx", ["version one"])
    ctx = pp.Ctx(root)
    ctx.load(need_cfg=False)
    final = {"stored": {"winner_dir": "round1_winner", "champion": "a2", "round": 1},
             "pin": {"id": "r1_a2"}}
    first = pp.publish_final_clean(ctx, final, True, "")
    check("D8 the first publish creates the package",
          first.get("action") == "created" and not first.get("skipped"),
          json.dumps({k: v for k, v in first.items() if k != "hygiene"})[:200])
    dst = Path(first["path"])
    # Same file NAMES, different bytes (the ordinary formatter/strip re-decide).
    make_docx(winner / "paper.docx", ["version two rewritten"])
    second = pp.publish_final_clean(ctx, final, True, "")
    on_disk = pp.corpus_dir_manifest(dst)
    check("D8 the returned digest describes the bytes on disk",
          pp.manifest_digest(on_disk) == second.get("digest"),
          f"returned={str(second.get('digest'))[:12]} disk={pp.manifest_digest(on_disk)[:12]} "
          f"action={second.get('action')}")
    check("D8 the stale copy was NOT reported as unchanged",
          second.get("action") != "unchanged", str(second.get("action")))
    body = ""
    with zipfile.ZipFile(dst / "paper.docx") as z:
        body = z.read("word/document.xml").decode("utf-8")
    check("D8 the served document carries the new content", "version two" in body,
          body[:160])


# =====================================================================
# D9. declared_submission_set: find the declaration
# =====================================================================

def test_declared_submission_readmes():
    print()
    print("== D9: the package's own declaration is found ==")
    decl = ("# What will be submitted\n\nOnly files matching `*.@(docx|pdf)` will be "
            "submitted to the venue.\n")
    pkg = scratch("paper_decl_sibling_")
    make_docx(pkg / "paper.docx", ["Title"])
    write(pkg / "notes.txt", "internal\n")
    write(pkg / "README.md", "# Package notes\n\nHow to rebuild this package.\n")
    write(pkg / "README_SUBMISSION.md", decl)
    res = pp.declared_submission_set(pkg)
    check("D9 a non-declaring README.md does not hide README_SUBMISSION.md",
          res["declared"] is True and res["readme"] == "README_SUBMISSION.md"
          and res["files"] == ["paper.docx"],
          json.dumps({k: v for k, v in res.items() if k != "carried_not_submitted"})[:220])
    low = scratch("paper_decl_lower_")
    make_docx(low / "paper.docx", ["Title"])
    write(low / "readme.md", decl)
    res2 = pp.declared_submission_set(low)
    check("D9 a lowercase readme.md declaring the set is honoured",
          res2["declared"] is True and res2["readme"] == "readme.md",
          json.dumps({k: v for k, v in res2.items() if k != "carried_not_submitted"})[:220])


# =====================================================================
# D10/D11. the package scans: PKG-8 and PKG-7
# =====================================================================

def test_pkg8_pkg7():
    print()
    print("== D10/D11: PKG-8 unit pairing and PKG-7 hex case ==")
    texts = [("main.docx",
              "Figure 3 | Pairwise comparisons used 606-1,989 paired cells (n = 12)."),
             ("main.docx", "Statistical tests: n is the number of cells that entered."),
             ("supp.docx", "In the mouse experiment, n is the number of mice per group.")]
    rows = pp.unit_of_analysis_rows(texts)
    check("D10 a caption whose unit IS defined elsewhere is not a PKG-8 row",
          rows == [], json.dumps(rows)[:240])
    unpaired = [("main.docx",
                 "Figure 3 | Pairwise comparisons used 606-1,989 paired cells (n = 12)."),
                ("supp.docx", "In the mouse experiment, n is the number of mice per group.")]
    rows = pp.unit_of_analysis_rows(unpaired)
    check("D10 a genuinely unpaired caption still files one PKG-8 row",
          len(rows) == 1 and rows[0]["rule"] == "PKG-8", json.dumps(rows)[:240])
    lower = pp.truncated_identifier_rows([("a.txt", "commit c30bc1ab2fdcc9ddb1e2f"),
                                          ("b.txt", "commit c30bc1ab2fdcc9ddb1e2f012345")])
    upper = pp.truncated_identifier_rows([("a.txt", "commit C30BC1AB2FDCC9DDB1E2F"),
                                          ("b.txt", "commit C30BC1AB2FDCC9DDB1E2F012345")])
    check("D11 PKG-7 fires for a lowercase truncated identifier",
          len(lower) == 1 and lower[0]["rule"] == "PKG-7", json.dumps(lower)[:200])
    check("D11 PKG-7 fires for the SAME identifier printed in caps",
          len(upper) == 1 and upper[0]["rule"] == "PKG-7", json.dumps(upper)[:200])
    check("D11 PKG-7 keeps the document's own spelling in the evidence",
          "C30BC1AB2FDCC9DDB1E2F" in json.dumps(upper), json.dumps(upper)[:240])


# =====================================================================
# D12. read-only raw data: no file of a colliding pair is invisible
# =====================================================================

class _RawCtx:
    """The one attribute `enforce_readonly_raw_data` reads from a Ctx."""

    def __init__(self, pristine: Path):
        self.pristine = pristine


def test_occurrence_value_patterns():
    print()
    print("== D14: a number's own spelling is one of its occurrence patterns ==")
    eo = _load("paper_debug1016_occurrences",
               WS / "paper-skills" / "paper-review" / "scripts" / "extract_occurrences.py")
    cases = [("1,234", "The cohort included 1,234 samples."),
             ("0.031", "The mean was 0.031 in this cohort."),
             ("1e-3", "The rate was 1e-3 per site.")]
    for value, text in cases:
        pat = eo.variant_pattern(value, "value")
        check(f"D14 the value {value!r} is found in its own spelling",
              bool(pat.search(text)), pat.pattern[:120])
    pat = eo.variant_pattern("5", "value")
    check("D14 the value 5 does not match inside 5,000",
          not pat.search("5,000 cells were counted"), pat.pattern[:120])


def test_raw_data_key_collisions():
    print()
    print("== D12: the raw-data verification sees every file of a colliding pair ==")
    pristine = scratch("paper_raw_pristine_")
    write(pristine / "raw_data" / "cohort_a.tsv", "a1\n")
    write(pristine / "raw_data" / "cohort_b.tsv", "b1\n")
    # (a) an edit of the file the folded key used to shadow is caught
    cand = scratch("paper_raw_edit_")
    write(cand / "raw_data" / "cohort_a.tsv", "TAMPERED\n")
    write(cand / "raw_data" / "cohort_b.tsv", "b1\n")
    warns = []
    rec = pp.enforce_readonly_raw_data(_RawCtx(pristine), cand, warns)
    check("D12 an edit of the colliding pair's first file is restored",
          (cand / "raw_data" / "cohort_a.tsv").read_text(encoding="utf-8") == "a1\n"
          and (cand / "raw_data" / "cohort_b.tsv").read_text(encoding="utf-8") == "b1\n",
          f"restored={rec.get('restored')} warns={warns[-1:]}")
    # (b) a DROPPED file of the pair is put back, and the surviving file stays
    cand2 = scratch("paper_raw_drop_")
    write(cand2 / "raw_data" / "cohort_b.tsv", "b1\n")
    warns2 = []
    pp.enforce_readonly_raw_data(_RawCtx(pristine), cand2, warns2)
    check("D12 a dropped file of the colliding pair is put back",
          (cand2 / "raw_data" / "cohort_a.tsv").is_file()
          and (cand2 / "raw_data" / "cohort_b.tsv").read_text(encoding="utf-8") == "b1\n",
          str(sorted(p.name for p in (cand2 / "raw_data").iterdir())))
    # (b2) the mirror case: the OTHER file of the pair survives
    cand2b = scratch("paper_raw_drop2_")
    write(cand2b / "raw_data" / "cohort_a.tsv", "a1\n")
    pp.enforce_readonly_raw_data(_RawCtx(pristine), cand2b, [])
    check("D12 ... and the same holds when the second file was dropped",
          (cand2b / "raw_data" / "cohort_b.tsv").is_file()
          and (cand2b / "raw_data" / "cohort_a.tsv").read_text(encoding="utf-8") == "a1\n"
          and (cand2b / "raw_data" / "cohort_b.tsv").read_text(encoding="utf-8") == "b1\n",
          str(sorted(p.name for p in (cand2b / "raw_data").iterdir())))
    # (c) the documented token-name matching still works (no collision involved:
    #     the package carries the base's token name and keeps it)
    pristine2 = scratch("paper_raw_pristine2_")
    write(pristine2 / "raw_data" / "dataset_summary.tsv", "s1\n")
    cand3 = scratch("paper_raw_token_")
    write(cand3 / "raw_data" / "dataset_summary-4f3a9c1.tsv", "s1\n")
    pp.enforce_readonly_raw_data(_RawCtx(pristine2), cand3, [])
    check("D12 a package's token-named copy is still matched to the original",
          (cand3 / "raw_data" / "dataset_summary-4f3a9c1.tsv").is_file()
          and (cand3 / "raw_data" / "dataset_summary-4f3a9c1.tsv").read_text(
              encoding="utf-8") == "s1\n"
          and not (cand3 / "raw_data" / "dataset_summary.tsv").exists(),
          str(sorted(p.name for p in (cand3 / "raw_data").iterdir())))


def test_raw_data_advisories_pairing():
    print()
    print("== D15: the advisory report uses the SAME pairing as the enforcement ==")
    pristine = scratch("paper_raw_adv_pristine_")
    write(pristine / "raw_data" / "dataset_summary.tsv", "s1\n")
    root = scratch("paper_raw_adv_root_")
    pin = "r1_a1"

    class AdvCtx:
        """The attributes `raw_data_advisories` reads from a Ctx."""

        def __init__(self):
            self.root = root
            self.pristine = pristine
            self.pins_dir = root / "pins"
            self.state = {"pinned": [{"id": pin}]}

        def rounds_count(self):
            return 0

    docs = pp.pinned_docs_dir(AdvCtx(), {"id": pin})
    # (a) the package carries the BASE's token name, byte-identical: compliant,
    #     so the advisory must stay quiet. This pins the pairing rule to the
    #     one `enforce_readonly_raw_data` uses -- reading `raw_data_entries`'s
    #     exact-path keys WITHOUT the token-insensitive fallback called this
    #     compliant package a deviation (2026-10-16 double-check: the two
    #     callers of the new key semantics have to agree).
    write(docs / "raw_data" / "dataset_summary-4f3a9c1.tsv", "s1\n")
    notes = pp.raw_data_advisories(AdvCtx())
    check("D15 a token-named copy of the pristine data raises no advisory",
          notes == [], json.dumps(notes)[:240])
    # (b) ... and the same file with DIFFERENT bytes is still reported.
    write(docs / "raw_data" / "dataset_summary-4f3a9c1.tsv", "TAMPERED\n")
    notes = pp.raw_data_advisories(AdvCtx())
    check("D15 an edited token-named copy is still reported",
          len(notes) == 1 and "raw_data/dataset_summary.tsv" in notes[0],
          json.dumps(notes)[:240])


# =====================================================================
# D13. the MCP converter probe must not depend on the ambient PATH
# =====================================================================

def test_mcp_probe_is_hermetic():
    print()
    print("== D13: the converter probe follows the fixture, not the machine ==")
    tmp = scratch("paper_mcp_hermetic_")
    script = tmp / "server" / "index.js"
    write(script, "// fake mcp server\n")
    write(script.parent / "docx2pdf.sh", "#!/bin/sh\n", mode=0o755)
    node = tmp / "node"
    write(node, "#!/bin/sh\n", mode=0o755)
    cfg = tmp / "config.toml"
    write(cfg, '[mcp_servers."docx-converter"]\n'
               f'command = "{node}"\nargs = ["{script}"]\n')
    real_path = pp.codex_config_path
    real_env = os.environ.get("PATH")
    empty = tmp / "empty-bin"
    empty.mkdir()
    pp.codex_config_path = lambda: cfg
    try:
        os.environ["PATH"] = str(empty)
        check("D13 a companion beside the server script keeps the server usable",
              pp.mcp_server_configured("docx-converter") is True,
              pp.mcp_server_unusable_reason("docx-converter") or "usable")
        os.unlink(script.parent / "docx2pdf.sh")
        check("D13 ... and the SAME fixture is unusable without the companion",
              pp.mcp_server_configured("docx-converter") is False,
              pp.mcp_server_unusable_reason("docx-converter") or "usable")
    finally:
        pp.codex_config_path = real_path
        if real_env is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = real_env


def main() -> int:
    test_break_only_paragraph_in_table_cell()
    test_adapter_clean_systemexit()
    test_install_skill_rerun()
    test_revision_token_agreement()
    test_cover_word_classification()
    test_strip_latex()
    test_strip_reference_sentences_encoding()
    test_publish_reports_the_served_bytes()
    test_declared_submission_readmes()
    test_pkg8_pkg7()
    test_raw_data_key_collisions()
    test_raw_data_advisories_pairing()
    test_mcp_probe_is_hermetic()
    test_occurrence_value_patterns()
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL 2026-10-16 DEBUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

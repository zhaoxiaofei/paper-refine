#!/usr/bin/env python3
"""The 2026-10-13 debug round: the crash paths, the two DOCX fix-path corruptions
and the wrong-verdict defects an independent audit of commit `6bd5840` reported
and this round reproduced on the tree.

Run:  python3 .paper_test/test_debug_2026_1013.py

Every check below was a real, reproduced failure before this round's patches:

  * `sandbox_selfcheck` raised NameError (`_prompt`) on a review sandbox whose
    findings.json is missing or broken -- exactly the pre-flight state it exists
    to diagnose -- and `check_review_contract` raised NameError (`seen_rows`)
    when findings.json carried no coverage table;
  * `upstream_deps` had no `probe` branch, so a `retry`/`--only` on a probe whose
    round base was pending bypassed the DepsNotMet defer path and died in
    `materialize_probe`'s RuntimeError instead of waiting;
  * `repair_reference_entries` appended TWO edits for one paragraph when two
    rules fired on one entry (FMT-R1 fused volume + FMT-R2 bare year), and
    `apply_edits` splices at ORIGINAL offsets -- the second replacement ate the
    bytes after the paragraph and the emitted XML no longer parsed;
  * `rewrite_text_spans` never merged overlapping spans (an FMT-P3 doubled space
    nested inside an FMT-T8a journal drop), so the text matched neither edit
    while the `applied` ledger claimed both ran;
  * all three `pdftotext` call sites re-raised `subprocess.TimeoutExpired` out of
    the scan (the sibling helpers catch the tuple deliberately);
  * `_bold_label_runs` decoded run text with `saxutils.unescape`, which does not
    know numeric references, and then re-escaped it into `&amp;#8211;` junk that
    the text-identity check could not see;
  * `heading_like_paragraphs` detected tables with a lazy first-`</w:tbl>` regex
    (the bug `_table_paragraph_indices` documents and fixes with balanced
    counting), so a nested table let outer-cell lines be retagged as headings;
  * `_zotero_entry_match_score` let AttributeError escape when `issued` is not an
    object (hand-/agent-edited citation JSON);
  * `zotero-refresh` exited 0 on a REFUSED refresh, contradicting its docstring;
  * `start_run_log` returned the truthy empty `Path()`, so a failed open was
    recorded as `.`; `setup --root <an existing FILE>` crashed with
    NotADirectoryError; `corpus_identity.revision_token` stored the whole report
    DICT where EVIDENCE_PACK.md renders a token string; the template prompt built
    `Path("")` for a pack with no main-text template; the round-1 winner tracking
    built a phantom empty baseline (writer and freshness reader disagreed); the
    corpus scanners read a collided path from BOTH sources; `count_words`
    answered a shapeless `--section abstract` request with silence;
  * `extract_occurrences` term mode anchored with `\\b`, so `--term "CD4+"` and
    `--term "C++"` found NOTHING, and a whitespace-only term matched the empty
    string in every word;
  * `revision_token.py` hashed suffixed bookkeeping names (`worklog_2026-10-11.md`)
    that `paper_pipeline.BOOKKEEPING_NAME_RE` excludes, so the two twins derived
    DIFFERENT tokens for one package;
  * `REF_ENTRY_RE` rejected `1)` numbering (NUM_ENTRY_RE accepts it), the
    author-year branch read ordinary date prose as a call-out, and a bracketed
    number after a measurement word was dropped from the cited set entirely;
  * `count_words` counted `\\cite[p.5]{x}`'s optional argument and math bodies;
  * `enumerate_conventions`' data-driven layer could never emit a two-surface
    family (the canonical surface was skipped), so `analysed`+`analyzed` produced
    ZERO candidates;
  * `convert_corpus` classified a text-free but annotated .docx as failed;
    `extract_acronyms`
    overwrote `short_after[ctx]` per file instead of accumulating.

The `D9` checks are the DOUBLE-CHECK follow-ups: defects the second read of this
round's own patches found, each reproduced on the committed bytes first --

  * `_marker_range_numbers` returned BOTH endpoints of an EQUAL-ended range
    (`12-12` -> `[12, 12]`), so the refresh's count guard and FMT-Z3 read a
    one-item field as a two-number cluster (a false half-updated row);
  * the `zotero-refresh` exit-status rule read the CLEAN document's
    "every marker already matches ..." skip as a refusal and exited 1;
  * the template prompt, one line below the fixed MAIN-TEXT read line, still
    named "the main template" as the supplementary's write target in a pack
    that ships no main-text template;
  * `setup --root <a FILE>/sub` (the FILE check's own defect class, one path
    component deeper) died in a NotADirectoryError traceback.

The same block closes the double-check's one remaining static claim: `D9 a split
round consumed list is the MERGED A+B one` EXECUTES the C03 contract (it passes
on the fixed tree and was reverse-checked -- reverting the C03 branch to the old
`ctx.run(rid_targeted_review(r))` read makes it fail).

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import html
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
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


nb = _load("paperp_dbg1013", WS / "paper_pipeline.py")
fmt = _load("paperf_dbg1013", WS / "paper_docx_format.py")
SCRIPTS = WS / "paper-skills" / "paper-review" / "scripts"
REVISE_SCRIPTS = WS / "paper-skills" / "paper-revise" / "scripts"
cw = _load("count_words_dbg1013", SCRIPTS / "count_words.py")
ec = _load("extract_citations_dbg1013", SCRIPTS / "extract_citations.py")
eo = _load("extract_occurrences_dbg1013", SCRIPTS / "extract_occurrences.py")
en = _load("enumerate_conventions_dbg1013", SCRIPTS / "enumerate_conventions.py")
cc = _load("convert_corpus_dbg1013", SCRIPTS / "convert_corpus.py")
rt = _load("revision_token_dbg1013", REVISE_SCRIPTS / "revision_token.py")


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def cleanup():
    for tmp in TMPDIRS:
        shutil.rmtree(tmp, ignore_errors=True)


def _para(text: str) -> str:
    return ('<w:p w:rsidR="00A" w:rsidRDefault="00A">'
            '<w:r><w:rPr><w:rFonts w:ascii="Times"/></w:rPr>'
            f'<w:t xml:space="preserve">{text}</w:t></w:r></w:p>')


def _doc(*paras: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>' + "".join(paras) + '</w:body></w:document>')


class _FakeCtx:
    """The two Ctx methods `unmet_deps` uses, with no run on disk."""

    def __init__(self, runs=None):
        self._runs = runs or {}
        self.cfg = {}

    def run(self, rid):
        return self._runs.get(rid)


# =====================================================================
# D1 -- the two NameError crash paths
# =====================================================================

def test_selfcheck_and_contract_crashes():
    print()
    print("== D1 review selfcheck / contract crash on the states they diagnose ==")
    sb = scratch("dbg1013_h1_")
    (sb / "base").mkdir()
    try:
        ok, errs, warns = nb.sandbox_selfcheck(sb, "review", "r1_targeted_review", 1)
        raised = None
    except Exception as e:                                            # noqa: BLE001
        ok, errs, raised = None, [], e
    check("D1 selfcheck without findings.json returns a verdict (no NameError)",
          raised is None, f"{type(raised).__name__}: {raised}" if raised else "")
    check("D1 the missing deliverable is reported",
          not ok and any("findings.json" in e for e in errs), str(errs[:2]))

    sb2 = scratch("dbg1013_h2_")
    (sb2 / "base").mkdir()
    art = sb2 / nb.ARTIFACTS_REL
    art.mkdir(parents=True)
    (art / "M1_acronyms.md").write_text(
        "# M1\n\n## M1b - long form reused\n\n| Long form | Short | Where |\n"
        "|---|---|---|\n| some long form | SLF | abstract |\n", encoding="utf-8")
    fj = {"submission_dir": "base", "findings": []}
    errs2, warns2 = [], []
    try:
        nb.check_review_contract(None, sb2, fj, errs2, warns2, scope="full", split="off")
        raised2 = None
    except Exception as e:                                            # noqa: BLE001
        raised2 = e
    check("D2 contract check without a coverage table returns (no NameError)",
          raised2 is None, f"{type(raised2).__name__}: {raised2}" if raised2 else "")
    check("D2 the missing coverage table is reported",
          any("coverage table" in e for e in errs2), str(errs2[:1]))
    check("D2 the M1b gate still runs and reports the un-disposed rows",
          any("M1b" in e for e in errs2), str([e for e in errs2 if "M1b" in e][:1]))


# =====================================================================
# D3 -- the probe stage is a base consumer
# =====================================================================

def test_probe_dependency():
    print()
    print("== D3 the probe review declares its round base as an upstream dep ==")
    deps = nb.upstream_deps({"kind": "probe", "round": 2})
    check("D3 upstream_deps(probe) names r2_a1", deps == [nb.rid_a1(2)], str(deps))
    ctx = _FakeCtx()                                   # no runs at all: base missing
    blocked = nb.unmet_deps(ctx, {"kind": "probe", "round": 2})
    check("D3 a missing base is a DepsNotMet defer, not an empty list",
          bool(blocked) and "r2_a1" in blocked[0], str(blocked))


# =====================================================================
# D4 -- the two DOCX fix-path corruptions
# =====================================================================

def test_docx_fix_paths():
    print()
    print("== D4 same-span edits and overlapping spans ==")
    xml = _doc(_para("References"),
               _para("15. Dong H, Zhang X. A reproducible assay. Volume 11-2020. (2020)."))
    recs = [{"key": "dong2020", "first_family": "Dong", "author": "Dong H",
             "title": "A reproducible assay", "year": "2020", "volume": "11",
             "pages": "565825", "doi": "10.1038/s41587-020-0000"}]
    res = fmt.repair_reference_entries(xml, recs)
    rules = sorted({r["rule"] for r in res["repairs"]})
    check("D4 both rules fired on the one entry", rules == ["FMT-R1", "FMT-R2"], str(rules))
    check("D4 the repair is reported as changed", res["changed"] is True,
          str(res["skipped"])[:160])
    try:
        ET.fromstring(res["xml"])
        well_formed = True
    except ET.ParseError as e:
        well_formed = False
        print("      parse error:", e)
    check("D4 the repaired document is still well-formed XML", well_formed)
    texts = [fmt.text_of(p[2]) for p in fmt.paragraphs(res["xml"])]
    check("D4 both repairs are in the emitted entry",
          len(texts) == 2 and "11, 565825" in texts[1] and "Available at https://doi.org/" in texts[1],
          str(texts[1:])[:200])

    para = ('<w:p><w:r><w:t xml:space="preserve">'
            'As shown (Garvin, 2015,  Nature Methods) earlier.</w:t></w:r></w:p>')
    text = fmt.text_of(para)
    start = text.index("Nature")
    drop = (text.index(",  Nature"), text.index(") earlier"), "")
    inner = (start, start + 1, "")
    new_para, applied = fmt.rewrite_text_spans(para, [drop, inner])
    new_text = fmt.text_of(new_para)
    check("D4 the nested edit is not claimed as applied",
          all(a[:2] != inner for a in applied), str(applied))
    check("D4 the emitted text matches the ledger",
          new_text == "As shown (Garvin, 2015) earlier."
          and all(new_text[a[0]:a[0] + len(a[3])] == a[3] or not a[3] for a in applied),
          repr(new_text))


# =====================================================================
# D5 -- pdftotext may not abort a scan
# =====================================================================

def test_pdftotext_timeout():
    print()
    print("== D5 a stalled pdftotext is a reported row, not a traceback ==")
    # The bounded runner (F38) is the seam the PDF helpers use now; patch IT,
    # not the subprocess module, or the timeout is never raised.
    real_run = getattr(fmt, "_run_text_tool", None)

    def _boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="pdftotext", timeout=60)

    fmt._run_text_tool = _boom
    try:
        pdf = scratch("dbg1013_pdf_") / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        try:
            rep = fmt.check_pdf(pdf, {})
            raised = None
        except Exception as e:                                        # noqa: BLE001
            rep, raised = None, e
        check("D5 check_pdf returns instead of raising", raised is None,
              f"{type(raised).__name__}: {raised}" if raised else "")
        check("D5 check_pdf reports the failure as a high row",
              isinstance(rep, dict) and rep.get("ok") is False
              and any(r.get("severity") == "high" for r in rep.get("rows") or []),
              str(rep)[:200] if rep else "")
        try:
            rows = fmt.pdf_artifact_rows(pdf)
            raised2 = None
        except Exception as e:                                        # noqa: BLE001
            rows, raised2 = None, e
        check("D5 pdf_artifact_rows returns instead of raising", raised2 is None,
              f"{type(raised2).__name__}: {raised2}" if raised2 else "")
    finally:
        if real_run is None:
            del fmt._run_text_tool
        else:
            fmt._run_text_tool = real_run


# =====================================================================
# D6 -- DOCX engine correctness fixes
# =====================================================================

def test_docx_engine_fixes():
    print()
    print("== D6 numeric references, nested tables, malformed citation JSON ==")
    para = ('<w:p><w:r><w:t>* Correspondence: an en&#8211;dash name</w:t></w:r></w:p>')
    out = fmt._bold_label_runs(para)
    check("D6 the numeric character reference is decoded, not double-escaped",
          "&amp;#" not in out, out[:160])
    check("D6 the visible text is unchanged by the label bolding",
          fmt.text_of(out) == fmt.text_of(para), fmt.text_of(out))

    inner = ('<w:tbl><w:tr><w:tc><w:p><w:r><w:t>inner</w:t></w:r></w:p></w:tc></w:tr>'
             '</w:tbl>')
    outer = ('<w:tbl><w:tr><w:tc><w:p><w:r><w:t>cell before</w:t></w:r></w:p>'
             + inner +
             '<w:p><w:r><w:rPr><w:b/><w:sz w:val="44"/></w:rPr>'
             '<w:t>Heading That Is Bold</w:t></w:r></w:p>'
             '</w:tc></w:tr></w:tbl>')
    doc = _doc('<w:p><w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t>body text here</w:t></w:r></w:p>',
               outer)
    found = [t for _i, t, _s in fmt.heading_like_paragraphs(doc)]
    check("D6 a paragraph after a NESTED table is not read as a body heading",
          "Heading That Is Bold" not in found, str(found))

    try:
        score = fmt._zotero_entry_match_score(
            "Smith J. A study. Nature 2020.", {"issued": "2020", "title": "A study"})
        raised = None
    except Exception as e:                                            # noqa: BLE001
        score, raised = None, e
    check("D6 a non-object 'issued' does not raise", raised is None,
          f"{type(raised).__name__}: {raised}" if raised else "")


# =====================================================================
# D7 -- CLI / bookkeeping contracts
# =====================================================================

def test_cli_contracts():
    print()
    print("== D7 zotero-refresh exit status, run-log sentinel, template prompt ==")
    real = fmt.refresh_zotero_package
    args = type("A", (), {})()
    args.file = "x.docx"
    args.out = None
    args.policy = None
    args.json = None
    args.unlink = False
    try:
        fmt.refresh_zotero_package = lambda *_a, **_k: {
            "ok": True, "changed": False, "skip": "the document's markers are not a numeric "
                                                  "citation style"}
        rc_refused = fmt.cmd_zotero_refresh(args)
        fmt.refresh_zotero_package = lambda *_a, **_k: {
            "ok": True, "changed": False, "skip": "no live citation fields"}
        rc_nothing = fmt.cmd_zotero_refresh(args)
    finally:
        fmt.refresh_zotero_package = real
    check("D7 a REFUSED refresh exits 1", rc_refused == 1, f"rc={rc_refused}")
    check("D7 'no live citation fields' (nothing to do) still exits 0",
          rc_nothing == 0, f"rc={rc_nothing}")

    file_root = scratch("dbg1013_log_") / "aroot.txt"
    file_root.write_text("not a directory\n", encoding="utf-8")
    old_log = nb.CURRENT_RUN_LOG
    try:
        path = nb.begin_run_log("status", file_root, ["paper_pipeline.py"])
    finally:
        nb.CURRENT_RUN_LOG = old_log
    check("D7 a failed run-log open returns None, never Path('.')",
          path is None, repr(path))

    root = scratch("dbg1013_prompt_")
    ctx = nb.Ctx(root)
    src = root / "source"
    src.mkdir()
    (src / "manuscript.docx").write_bytes(b"PK\x03\x04stub")
    prompt = nb.apply_template_prompt(ctx, root / "sandbox", src,
                                      {"cover": Path("/venue/word/cover.docx")})
    check("D7 a pack with no main-text template does not promise an empty file name",
          "venue_template/word/  --" not in prompt and "no MAIN-TEXT template" in prompt,
          [ln for ln in prompt.splitlines() if "MAIN-TEXT" in ln or "main text" in ln][:2])

    # round 1 has no previous winner: no empty-token baseline may reach the
    # writer (it appended a phantom "no base corpus" skip row).
    ctx2 = nb.Ctx(scratch("dbg1013_win_"))
    b1 = nb.winner_tracking_baselines(ctx2, 1)
    b2 = nb.winner_tracking_baselines(ctx2, 2)
    check("D7 round-1 winner tracking has ONE baseline (the original)",
          len(b1) == 1 and b1[0][0] == nb.TRACK_TOKEN_ORIGINAL
          and all(t for t, _s, _n in b1), str([t for t, _s, _n in b1]))
    check("D7 round 2+ winner tracking also names the previous winner",
          [t for t, _s, _n in b2] == [nb.TRACK_TOKEN_ORIGINAL, "winner1"], str(b2))


# =====================================================================
# D8 -- the paper-skills script defects
# =====================================================================

_CLEAN_STYLE = "http://www.zotero.org/styles/nature-biotechnology"
_CLEAN_ITEMS = {
    "K1": {"title": "Alpha diversity in single cells", "family": "Alvarez", "year": 2020},
    "K2": {"title": "Beta catenin signalling atlas", "family": "Bianchi", "year": 2021},
}


def _cite_field_para(cid: str, marker: str, keys: list, visible: str) -> str:
    """One live Zotero citation field, its `itemData` embedded (library-free)."""
    payload = {
        "citationID": cid,
        "properties": {"formattedCitation": marker, "plainCitation": visible, "noteIndex": 0},
        "citationItems": [
            {"id": k + "/1",
             "uris": [f"http://zotero.org/users/local/AAA/items/{k}"],
             "itemData": {"type": "article-journal", "title": _CLEAN_ITEMS[k]["title"],
                          "author": [{"family": _CLEAN_ITEMS[k]["family"], "given": "A"}],
                          "issued": {"date-parts": [[_CLEAN_ITEMS[k]["year"]]]}}}
            for k in keys],
        "schema": "https://github.com/citation-style-language/schema/raw/master/"
                  "csl-citation.json",
    }
    instr = html.escape("ADDIN ZOTERO_ITEM CSL_CITATION "
                        + json.dumps(payload, ensure_ascii=False), quote=False)
    return ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve">{instr}</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r><w:t>{visible}</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')


def _bib_entry_para(number: int, text: str, opener: str = "") -> str:
    return ('<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>' + opener
            + f'<w:r><w:t>{number}.</w:t></w:r>'
            + f'<w:r><w:tab/><w:t xml:space="preserve">{text}</w:t></w:r></w:p>')


def _clean_zotero_docx(path: Path) -> Path:
    """A DOCX the offline refresh finds ALREADY clean (cached markers = ranks).

    Two citation fields (K1 rank 1, K2 rank 2) whose cached markers and visible
    runs already show those ranks, a bibliography field whose entries run in
    rank order, and ONE Zotero style store: `zotero_refresh_document` takes its
    `not edits and not bib_rebuilt` branch, the nothing-to-do skip.
    """
    bib_open = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                '<w:r><w:instrText xml:space="preserve">ADDIN ZOTERO_BIBL '
                '{"uncited":[],"omitted":[],"custom":[]} CSL_BIBLIOGRAPHY</w:instrText></w:r>'
                '<w:r><w:fldChar w:fldCharType="separate"/></w:r>')
    body = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">',
            '<w:body>',
            '<w:p><w:r><w:t>Main text.</w:t></w:r></w:p>',
            _cite_field_para("citeA", r"\super 1\nosupersub{}", ["K1"], "1"),
            _cite_field_para("citeB", r"\super 2\nosupersub{}", ["K2"], "2"),
            '<w:p><w:r><w:t>References</w:t></w:r></w:p>',
            _bib_entry_para(1, "Alvarez, A. et al. Alpha diversity in single cells. "
                               "Journal 1, 1-9 (2020).", opener=bib_open),
            _bib_entry_para(2, "Bianchi, B. et al. Beta catenin signalling atlas. "
                               "Journal 2, 1-9 (2021)."),
            '<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>',
            "</w:body></w:document>"]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml", "\n".join(body))
        z.writestr("word/settings.xml",
                   '<?xml version="1.0"?><w:settings xmlns:w="http://schemas.'
                   'openxmlformats.org/wordprocessingml/2006/main"><w:docVars><w:docVar '
                   'w:name="ZOTERO_PREF_1" w:val="&lt;data&gt;&lt;style id=&quot;'
                   f'{_CLEAN_STYLE}&quot;/&gt;&lt;/data&gt;"/></w:docVars></w:settings>')
    return path


def _refresh_args(path):
    """The `zotero-refresh` CLI namespace for one file."""
    args = type("A", (), {})()
    args.file, args.out, args.policy, args.json, args.unlink = str(path), None, None, None, False
    return args


def test_double_check_followups():
    print()
    print("== D9 follow-ups found while double-checking this round's own fixes ==")
    equal_marker = r"\super 12-12\nosupersub{}"
    check("D9 an equal-ended citation range names ONE number (no duplicate endpoint)",
          fmt._marker_range_numbers(12, 12) == [12]
          and fmt._marker_numbers(equal_marker) == [12]
          and ec.parse_nums("12-12") == [12],
          f"{fmt._marker_numbers(equal_marker)} / {ec.parse_nums('12-12')}")
    check("D9 the endpoint rules this round pinned are unchanged",
          fmt._marker_range_numbers(1, 250) == [1, 250]
          and fmt._marker_range_numbers(8, 3) == [8, 3]     # written order (1012::D4)
          and fmt._marker_range_numbers(2019, 2020) == []
          and fmt._marker_range_numbers(3, 5) == [3, 4, 5]
          and sorted(fmt._marker_range_numbers(8, 3)) == sorted(ec.parse_nums("8-3")),
          str([fmt._marker_range_numbers(a, b)
               for a, b in ((1, 250), (8, 3), (2019, 2020), (3, 5))]))

    tmp = scratch("dbg1013_cleanx_")
    clean = _clean_zotero_docx(tmp / "clean.docx")
    res = fmt.refresh_zotero_package(clean)
    check("D9 a document the refresh finds CLEAN reports nothing_to_do, not a refusal",
          res.get("ok") and not res.get("changed") and res.get("nothing_to_do") is True
          and "already matches" in str(res.get("skip")),
          json.dumps({k: v for k, v in res.items() if k != "zotero"})[:220])
    check("D9 a clean document's `zotero-refresh` exits 0 (a no-repair is a success)",
          fmt.cmd_zotero_refresh(_refresh_args(clean)) == 0)
    broken = tmp / "broken.docx"
    broken.write_bytes(b"not a zip")
    check("D9 a REFUSED refresh still exits 1 (the C18 rule keeps its meaning)",
          fmt.cmd_zotero_refresh(_refresh_args(broken)) == 1)

    root = scratch("dbg1013_prompt2_")
    src = root / "source"
    src.mkdir()
    (src / "manuscript.docx").write_bytes(b"PK\x03\x04stub")
    ctx = nb.Ctx(root)
    cover_only = nb.apply_template_prompt(ctx, root / "sb", src,
                                          {"cover": Path("/venue/word/cover.docx")})
    supp_lines = [l.strip() for l in cover_only.splitlines() if "the supplementary <-" in l]
    check("D9 a pack with no main-text template names no main template anywhere",
          "the main template (no separate one ships)" not in cover_only
          and supp_lines == ["- the supplementary <- the source document itself "
                             "(no supplementary or main-text template ships)"],
          str(supp_lines))
    main_only = nb.apply_template_prompt(ctx, root / "sb2", src,
                                         {"main": Path("/venue/word/main.docx")})
    check("D9 a main-only pack still builds the supplementary from the main template",
          [l.strip() for l in main_only.splitlines() if "the supplementary <-" in l]
          == ["- the supplementary <- the main template (no separate supplementary "
              "template ships)"],
          str([l.strip() for l in main_only.splitlines() if "the supplementary <-" in l]))

    parent = scratch("dbg1013_rootp_") / "afile.txt"
    parent.write_text("not a directory\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(WS / "paper_pipeline.py"), "setup",
                           "--source", str(src), "--root", str(parent / "sub")],
                          capture_output=True, text=True, timeout=300)
    out = proc.stdout + proc.stderr
    check("D9 a --root under a FILE parent dies cleanly (no NotADirectoryError traceback)",
          proc.returncode != 0 and "Traceback" not in out
          and "ERROR: cannot create the root directory" in out,
          out.strip().splitlines()[-1][:170] if out.strip() else "")

    # 5. C03: the round verified this statically (five sibling call sites), so
    #    the contract is EXECUTED here instead. Under `--review-split`
    #    `merge_review_parts` writes the ONE frozen list (A's rows + B's) into
    #    session B's `targeted_review/`, so an arm with no `targeted_review/` copy of its own must
    #    be cross-checked against THAT list, not against A's partial one. These
    #    two checks pass on the fixed tree BY CONSTRUCTION and are the reason
    #    the fix cannot silently regress: reverting the C03 read to
    #    `ctx.run(rid_targeted_review(r))` was verified to make the first one fail.
    sroot = scratch("dbg1013_split_")
    sctx = nb.Ctx(sroot)
    sctx.cfg = {"review_split": "phases"}
    for rid, ids in (("r1_targeted_review", ["F-A1"]), ("r1_targeted_review_b", ["F-A1", "B-F-A2"])):
        sb = sroot / "runs" / rid / "targeted_review"
        sb.mkdir(parents=True)
        (sb / "findings.json").write_text(json.dumps(
            {"submission_dir": "base",
             "findings": [{"id": i, "check": "M1", "location": "p1", "evidence": "e"}
                          for i in ids]}), encoding="utf-8")
        sctx.state["runs"][rid] = {"id": rid, "kind": "targeted_review", "round": 1,
                                   "status": "done", "sandbox": f"runs/{rid}"}
    merged = [str(f.get("id")) for f in nb.round_consumed_findings(sctx, 1)]
    check("D9 a split round consumed list is the MERGED A+B one (never A alone)",
          merged == ["F-A1", "B-F-A2"], str(merged))
    sctx.cfg = {"review_split": "off"}
    single = [str(f.get("id")) for f in nb.round_consumed_findings(sctx, 1)]
    check("D9 with no split the round's frozen list still reads session A",
          single == ["F-A1"], str(single))


# =====================================================================
# D8 -- the paper-skills script defects
# =====================================================================

def test_skill_scripts():
    print()
    print("== D8 skill-script scanners and counters ==")
    check("D8 term mode finds a term ending in '+'",
          eo.variant_pattern("CD4+", "term").findall("CD4+ T cells") == ["CD4+"])
    check("D8 term mode still finds an ordinary hyphenated term",
          eo.variant_pattern("scRNA-seq", "term").findall("scRNA-seq data") == ["scRNA-seq"])
    try:
        eo.variant_pattern("   ", "term")
        empty_rejected = False
    except ValueError:
        empty_rejected = True
    check("D8 a whitespace-only term is rejected (it used to match every word edge)",
          empty_rejected)

    check("D8 a 1)-numbered reference entry is parsed",
          bool(ec.REF_ENTRY_RE.match("1) Smith J. Nature 2019.")))
    check("D8 an unexpandable citation range keeps its endpoints",
          ec.parse_nums("1-250") == [1, 250] and ec.parse_nums("8-3") == [3, 8]
          and ec.parse_nums("1-3") == [1, 2, 3],
          f"1-250 -> {ec.parse_nums('1-250')}")
    check("D8 a cover letter is a submission document even if its name says 'response'",
          ec.is_non_manuscript("cover_letter_response.docx.txt") is False
          and ec.is_non_manuscript("author_response.md") is True)
    date_prose = "The samples between January and February 2019 were collected."
    check("D8 ordinary date prose is not an author-year call-out",
          not [m for m in ec.AY_CIT_RE.finditer(date_prose)
               if not ec.is_date_prose(m)])
    month_pair = [m for m in ec.AY_CIT_RE.finditer("As May and Smith 2019 showed.")
                  if not ec.is_date_prose(m)]
    check("D8 a real two-author call-out that happens to start with a month is kept",
          bool(month_pair), str([m.group(0) for m in month_pair]))
    # ...and the other side stays pinned (validate_skill C10/C24): an interval
    # SHAPE after a measurement word is a measurement interval, not a citation.
    m2work = scratch("dbg1013_m2_")
    (m2work / "corpus").mkdir()
    (m2work / "corpus" / "paper.txt").write_text(
        "Results\nThe signal fell in the interval [2, 5] units. Protein folding differed at "
        "the whole-genome level [12], as shown.\n\nReferences\n1. A. One. 2019.\n"
        "12. L. Twelve. 2020.\n", encoding="utf-8")
    m2out = m2work.parent / "m2_out"
    subprocess.run([sys.executable, str(SCRIPTS / "extract_citations.py"),
                    "--work", str(m2work), "--out", str(m2out)],
                   check=True, capture_output=True)
    m2 = json.loads((m2out / "artifacts" / "M2_citations.json").read_text(encoding="utf-8"))
    raws = [c["raw"] for c in m2["callouts"]]
    check("D8 a real call-out after a measurement word is CITED (no false 'never cited')",
          "[12]" in raws and 12 in m2["callouts"][raws.index("[12]")]["refs"], str(raws))
    check("D8 an interval shape after a measurement word is not a call-out",
          "[2, 5]" not in raws and "[2, 5]" in [s["raw"] for s in m2["suspect_brackets"]],
          str(m2["suspect_brackets"]))

    cited = "We measured cohorts \\cite[p.5]{x} and 8 more."
    prose = cw._line_text(cited)
    check("D8 a LaTeX optional argument is not counted",
          prose == "We measured cohorts and 8 more." and cw.count_words(prose) == 6,
          repr(prose))
    math = cw._line_text("The value $p<0.05$ was fixed.")
    check("D8 inline math is not counted",
          math == "The value was fixed." and cw.count_words(math) == 4, repr(math))
    tex = ("\\section{Methods}\n"
           "\\begin{equation}\nE = m c^2 + \\alpha \\beta\n\\end{equation}\n"
           "Plain prose here.\n")
    lines, _caps, _end = cw.tex_lines(tex)
    check("D8 a display-math body is not counted as prose",
          "Plain prose here." in lines and not any("alpha" in ln for ln in lines),
          str(lines))

    corpus = scratch("dbg1013_enc_") / "corpus"
    corpus.mkdir(parents=True)
    (corpus / "abstract.md").write_text(
        "We analysed the samples and analysed them again.\n", encoding="utf-8")
    (corpus / "intro.md").write_text(
        "They analyzed the data and analyzed it.\n", encoding="utf-8")
    cands = en.collect_candidates(en.read_text_files(str(corpus)))
    forms = sorted(f for c in cands if c["key"] == "analyzed" for f in c["forms"])
    check("D8 the data-driven convention layer reports an unlisted -ise/-ize family",
          forms == ["analysed", "analyzed"], str(cands)[:200])

    docx = scratch("dbg1013_docx_") / "figure_only.docx"
    import zipfile
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.'
                   'org/wordprocessingml/2006/main"><w:body/></w:document>')
        z.writestr("docProps/core.xml",
                   '<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.'
                   'openxmlformats.org/package/2006/metadata/core-properties">'
                   '<cp:lastModifiedBy>x</cp:lastModifiedBy></cp:coreProperties>')
    entry = cc.convert_one(str(docx), "figure_only.docx")
    check("D8 a text-free but annotated .docx is not 'failed'",
          entry["status"] == "converted-empty", entry["status"])

    # the two token twins must agree on a package carrying suffixed bookkeeping
    pkg = scratch("dbg1013_tok_")
    (pkg / "cnb-11-3-main-a.docx").write_bytes(b"PK\x03\x04 fake payload bytes")
    (pkg / "cnb-11-3-main-a.tex").write_text("\\documentclass{article}\nMain text.\n")
    (pkg / "worklog_2026-10-11.md").write_text("work log\n")
    (pkg / "changelog.md").write_text("changelog\n")
    a = nb.revision_token_for_dir(pkg)
    b = rt.revision_token(pkg)
    check("D8 revision_token.py and its pipeline twin derive the SAME token",
          a["token"] and a["token"] == b["token"], f"{a['token']} vs {b['token']}")

    # extract_acronyms: short-form uses accumulate across files of one context
    work = scratch("dbg1013_acr_")
    (work / "corpus").mkdir()
    (work / "corpus" / "intro_a.txt").write_text(
        "Tumour necrosis factor (TNF) is central. TNF drives growth. TNF is used.\n",
        encoding="utf-8")
    (work / "corpus" / "intro_b.txt").write_text(
        "We used TNF again here.\n", encoding="utf-8")
    out = work.parent / "acr_out"
    subprocess.run([sys.executable, str(SCRIPTS / "extract_acronyms.py"),
                    "--work", str(work), "--out", str(out)],
                   check=True, capture_output=True)
    data = json.loads((out / "artifacts" / "M1_acronyms.json").read_text(encoding="utf-8"))
    uses = (data[0].get("short_form_uses") or {}) if data else {}
    check("D8 short-form uses accumulate across files sharing a context",
          uses.get("main text") == 4, str(uses))

    # a shapeless document must still appear in an M19 sweep (never silence)
    plain = scratch("dbg1013_plain_") / "blob.txt"
    plain.write_text("Just a blob of text with no headings at all.\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(SCRIPTS / "count_words.py"),
                           "--section", "abstract", str(plain)],
                          capture_output=True, text=True)
    check("D8 --section abstract on a shapeless file answers with a row, not silence",
          proc.returncode == 0 and "blob.txt" in proc.stdout
          and "blob.txt" in proc.stdout.splitlines()[-1],
          proc.stdout.strip().splitlines()[-1:] or "")

    # the later-source override applies to the text scanners too
    root2 = scratch("dbg1013_ovr_")
    a, b = root2 / "a", root2 / "b"
    (a / "code").mkdir(parents=True)
    (b / "code").mkdir(parents=True)
    (a / "code" / "notes.md").write_text("STALE note text here.\n", encoding="utf-8")
    (b / "code" / "notes.md").write_text("FRESH note text here.\n", encoding="utf-8")
    sources = [(a, "", ()), (b, "", ())]
    docs = nb.corpus_text_documents(sources)
    check("D8 a path two sources provide is read ONCE, from the later source",
          [d[0] for d in docs] == ["code/notes.md"]
          and docs[0][1][0][0].startswith("FRESH"),
          str([(d[0], d[1][0][0][:12]) for d in docs]))


def main() -> int:
    test_selfcheck_and_contract_crashes()
    test_probe_dependency()
    test_docx_fix_paths()
    test_pdftotext_timeout()
    test_docx_engine_fixes()
    test_cli_contracts()
    test_double_check_followups()
    test_skill_scripts()
    cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL 2026-10-13 DEBUG CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

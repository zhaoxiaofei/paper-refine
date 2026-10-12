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

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
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
        ok, errs, warns = nb.sandbox_selfcheck(sb, "review", "r1_review", 1)
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
          len(texts) == 2 and "11, 565825" in texts[1] and "Preprint at" in texts[1],
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
    real_run = fmt.subprocess.run

    def _boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="pdftotext", timeout=60)

    fmt.subprocess.run = _boom
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
        fmt.subprocess.run = real_run


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

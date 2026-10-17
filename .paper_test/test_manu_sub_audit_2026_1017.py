#!/usr/bin/env python3
"""The 2026-10-17 manuscript-submission audit: the three operator rules + the new scans.

Run:  python3 .paper_test/test_manu_sub_audit_2026_1017.py

The operator's three rules for this round:

  1. `--without-author-to-complete` / `--with-author-to-complete`: the pipeline
     may stop writing the literal "[AUTHOR TO COMPLETE: ...]" hand-off marker.
     With it off, a missing item goes to the package's own manual-steps report
     and a shipped marker is a DEFECT (the delivered CopyNumBench main text
     still carried "versions of bedtools, Seurat, cellsnp-lite and UCSC
     liftOver", and the NeoHeteroclitic Reporting Summary was five markers).
  2. files in `raw_data/` (and the other non-carried areas) may not be
     referenced by the main manuscript -- except figures/tables and files a
     `.tex` file in `raw_data/`'s parent directory inputs, directly or through
     nested inputs (the CopyNumBench README states the same positive half).
  3. placeholder files are IGNORED: a file that stands in for data it does not
     contain (the operator's example: "the haplotypes in Chisel ACT are
     actually the HG008 haplotypes (placeholders)") is never a producer, and a
     declared placeholder's real partner stays evidence.

The suite also pins the three package self-consistency scans added for the
issues the audit found: PKG-11 (headers differing by one letter silently drop a
table), PKG-12 (a statistics row whose p and its own interval disagree), PKG-14
(a cover letter that denies a prior submission the package documents).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
FAILS = []
TMPDIRS = []


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_audit_1017_pipeline", WS / "paper_pipeline.py")
fmt = _load("paper_audit_1017_format", WS / "paper_docx_format.py")


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(d)
    return d


def cleanup():
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def write_docx(path: Path, paragraphs, with_media: bytes = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(
        "<w:p><w:r><w:t xml:space=\"preserve\">" + p.replace("&", "&amp;").replace("<", "&lt;")
        + "</w:t></w:r></w:p>" for p in paragraphs)
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
          'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
          '<Default Extension="png" ContentType="image/png"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.'
          'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            'relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document {ns}><w:body>' + body + '</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
        if with_media:
            z.writestr("word/media/image1.png", with_media)


class Ctx:
    def __init__(self, root: Path, cfg: dict = None):
        self.root = Path(root)
        self.cfg = dict(cfg or {})


# ---------------------------------------------------------------------------
# 1. --without-author-to-complete / --with-author-to-complete
# ---------------------------------------------------------------------------
def test_author_to_complete_policy():
    print("\n== author-to-complete policy ==")
    on, off = Ctx("/tmp/x", {}), Ctx("/tmp/x", {"author_to_complete": "off"})
    check("on is the default for a root without the key", pp.author_to_complete_of(on) is True)
    check("the config key 'off' turns the marker convention off",
          pp.author_to_complete_of(off) is False)
    check("a JSON boolean false is honoured", pp.author_to_complete_of(
        Ctx("/tmp/x", {"author_to_complete": False})) is False)
    for fn in (pp.review_prompt, pp.audit_prompt, pp.probe_prompt,
               pp.revise_prompt, pp.integrate_prompt, pp.rewrite_prompt):
        args = (Path("/tmp/sb"), "r1_a1", 1) if fn is not pp.integrate_prompt else (
            Path("/tmp/sb"), "r1_i1", 1, "a1", ["a2"])
        t_on = fn(*args, author_to_complete=True)
        t_off = fn(*args, author_to_complete=False)
        check(f"{fn.__name__}: ON carries the marker rule",
              "PIPELINE HAND-OFF PLACEHOLDERS" in t_on)
        check(f"{fn.__name__}: OFF carries the no-marker rule",
              "PIPELINE HAND-OFF ITEMS" in t_off and "PIPELINE HAND-OFF PLACEHOLDERS" not in t_off)
    t = pp.revise_prompt(Path("/tmp/sb"), "r1_a2", 1, author_to_complete=False)
    check("revise OFF replaces every restated scaffolding sentence",
          all(a not in t for a, _b in pp.HANDOFF_PROMPT_REWRITES))
    # Each rewrite pair must still MATCH a real prompt: an excerpt edited upstream
    # would otherwise leave two contradictory instructions in one prompt.
    revise_on = pp.revise_prompt(Path("/tmp/sb"), "r1_a2", 1, author_to_complete=True)
    integrate_on = pp.integrate_prompt(Path("/tmp/sb"), "r1_i1", 1, "a1", ["a2"],
                                      author_to_complete=True)
    rewrite_on = pp.rewrite_prompt(Path("/tmp/sb"), "r1_w1", 1, author_to_complete=True)
    carriers = [(revise_on, 0), (revise_on, 1), (integrate_on, 2), (rewrite_on, 3)]
    for prompt_text, idx in carriers:
        a, _b = pp.HANDOFF_PROMPT_REWRITES[idx]
        check(f"excerpt {idx} is still present in its prompt (ON)", a in prompt_text)
    for prompt_text, idx in carriers:
        a, b = pp.HANDOFF_PROMPT_REWRITES[idx]
        off = pp.apply_author_to_complete_prompt(prompt_text, False)
        check(f"excerpt {idx} is replaced in its prompt (OFF)", a not in off and b in off)
    j_on = pp.judge_prompt(Path("/tmp/sb"), "j1", 1, "t", 1, 1, ["a"],
                           author_to_complete=True)
    j_off = pp.judge_prompt(Path("/tmp/sb"), "j1", 1, "t", 1, 1, ["a"],
                            author_to_complete=False)
    check("the judge never sees the marker token in either mode",
          "[AUTHOR TO COMPLETE" not in j_on and "[AUTHOR TO COMPLETE" not in j_off)
    check("the judge's OFF rule scores the missing item, not the marker",
          "no-placeholder policy" in j_off and "no-placeholder policy" not in j_on)
    # Readiness must not say "ready" about a marker the certification gate refuses.
    fc = {"hygiene": {}}
    res = {"items": ["r1_a2_revise: 6 searchable hand-off marker(s) are still in the "
                     "delivered package and the sandbox carries no lookup verdict for them"]}
    r_on = pp.package_readiness(fc, residuals=res, author_to_complete=True)
    r_off = pp.package_readiness(fc, residuals=res, author_to_complete=False)
    check("readiness names the shipped marker (ON: advisory hand-off)",
          [f for f in r_on["findings"] if f.get("rule") == "AUTH-1"]
          and all(f.get("advisory") for f in r_on["findings"] if f.get("rule") == "AUTH-1"))
    check("readiness names the shipped marker (OFF: blocking defect)",
          [f for f in r_off["findings"] if f.get("rule") == "AUTH-1"]
          and not any(f.get("advisory") for f in r_off["findings"]
                      if f.get("rule") == "AUTH-1"))


def test_author_to_complete_cli():
    print("\n== author-to-complete CLI ==")
    src = scratch("atc_src_")
    write_docx(src / "ms-1-mainText-abcdef0.docx", ["Title", "Body."])
    root = scratch("atc_root_") / "root"
    cmd = [sys.executable, str(WS / "paper_pipeline.py"), "setup", "--root", str(root),
           "--source", str(src), "--rounds", "1", "--without-author-to-complete"]
    r = __import__("subprocess").run(cmd, capture_output=True, text=True, timeout=300)
    check("setup accepts --without-author-to-complete", r.returncode == 0, r.stderr[-300:])
    cfg = json.loads((root / "pipeline_config.json").read_text())
    check("setup records author_to_complete: off", cfg.get("author_to_complete") == "off")
    r2 = __import__("subprocess").run(
        [sys.executable, str(WS / "paper_pipeline.py"), "set-author-to-complete", "--root",
         str(root), "on"], capture_output=True, text=True, timeout=120)
    cfg = json.loads((root / "pipeline_config.json").read_text())
    check("set-author-to-complete on flips the policy", r2.returncode == 0
          and cfg.get("author_to_complete") == "on", r2.stderr[-200:])


# ---------------------------------------------------------------------------
# 2. raw_data references: figures/tables/tex-input closure only
# ---------------------------------------------------------------------------
def build_ref_package(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "raw_data" / "source_data").mkdir(parents=True)
    (root / "raw_data" / "source_data" / "fig1.tsv").write_text("a\tb\n1\t2\n")
    (root / "raw_data" / "source_data" / "stale_extra.tsv").write_text("x\ty\n3\t4\n")
    (root / "supplementary_source_files").mkdir()
    (root / "supplementary_source_files" / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\nIMAGEDATA")
    # a parent-directory .tex that inputs a nested .tex, which includes the figure
    (root / "ms-1-supp-abcdef0.tex").write_text(
        "\\documentclass{article}\\begin{document}\\input{ms-1-suppFigs-abcdef0.tex}"
        "\\end{document}\n")
    (root / "ms-1-suppFigs-abcdef0.tex").write_text(
        "\\includegraphics[width=1in]{supplementary_source_files/fig1.png}\n"
        "\\pgfplotstableread[col sep=tab]{raw_data/source_data/fig1.tsv}\\t\n")
    (root / "ms-1-mainText-abcdef0.docx") if False else None
    write_docx(root / "ms-1-mainText-abcdef0.docx",
               ["Title",
                "The balloon values are in raw_data/source_data/fig1.tsv (see the figure).",
                "A stale pointer lives in raw_data/source_data/stale_extra.tsv."])
    return root


def test_raw_area_reference_rule():
    print("\n== PKG-10 raw-area reference rule ==")
    root = build_ref_package(scratch("pkg10_"))
    # The .tex closure: nested input + includegraphics + pgfplotstableread.
    closure, sources = pp.tex_input_closure(root, ["raw_data"])
    check("the parent .tex sources are found",
          sorted(sources) == ["ms-1-supp-abcdef0.tex", "ms-1-suppFigs-abcdef0.tex"], str(sources))
    check("the nested \\input target is in the closure",
          "ms-1-suppfigs-abcdef0.tex" in closure)
    check("an \\includegraphics target is in the closure",
          "supplementary_source_files/fig1.png" in closure)
    check("a \\pgfplotstableread target is in the closure",
          "raw_data/source_data/fig1.tsv" in closure, str(sorted(closure)))
    check("a raw_data file the .tex does not input is NOT in the closure",
          "raw_data/source_data/stale_extra.tsv" not in closure)
    exc = pp.area_reference_exceptions(root, ["raw_data"],
                                       ["ms-1-mainText-abcdef0.docx"])
    check("the figures/tables exception: an inputted file is exempt",
          pp.pkg10_reference_exempt(root, "supplementary_source_files/fig1.png", exc)[0])
    check("a raw_data file outside the closure is NOT exempt",
          not pp.pkg10_reference_exempt(root, "raw_data/source_data/stale_extra.tsv", exc)[0])
    rows = pp.non_submitted_reference_rows(root, ["raw_data"])
    refs = [r.get("reference") for r in rows]
    check("a reference into raw_data outside the exception is reported", 
          any("stale_extra.tsv" in str(x) for x in refs), str(refs))
    check("the reference into the inputted display item is not reported",
          not any("fig1.tsv" in str(x) for x in refs), str(refs))
    check("the row carries the PKG-10 marker",
          all(r.get("area_rule") == "PKG-10" for r in rows
              if "stale_extra" in str(r.get("reference"))))
    # The mechanical strip removes the stale sentence and keeps the figure one.
    report = pp.strip_dangling_references_in_dir(root, ["raw_data"], "t")
    text = pp._docx_paragraphs(root / "ms-1-mainText-abcdef0.docx")
    joined = "\n".join(text or [])
    check("the dangling sentence is removed", "stale_extra" not in joined, joined)
    check("the legitimate figure/source sentence survives", "fig1.tsv" in joined)
    check("the removal is recorded", report.get("removed", 0) >= 1)


def test_embedded_figure_exception():
    print("\n== PKG-10 embedded-figure exception ==")
    root = scratch("pkg10_media_")
    (root / "raw_data").mkdir()
    png = b"\x89PNG\r\n\x1a\nSAME-BYTES"
    (root / "raw_data" / "Fig3.png").write_bytes(png)
    write_docx(root / "ms-1-mainText-abcdef0.docx",
               ["The main text displays raw_data/Fig3.png as Fig. 3."], with_media=png)
    exc = pp.area_reference_exceptions(root, ["raw_data"],
                                       ["ms-1-mainText-abcdef0.docx"])
    ok, why = pp.pkg10_reference_exempt(root, "raw_data/Fig3.png", exc)
    check("a figure whose bytes the submission embeds is exempt", ok, why)
    check("the reason names the submitted document", "ms-1-mainText" in why, why)


def test_tex_target_forms():
    print("\n== TeX input target forms ==")
    src = (r"\includegraphics[width=1in]{supp\_figs/fig1.pdf}"
           r"\inputminted{python}{code/run.py}"
           r"\DTLloaddb{mydb}{data/table.csv}"
           r"\import{sub/}{part.tex}"
           r"% \includegraphics{commented/out.png}"
           "\n")
    targets = pp.tex_input_targets(src)
    check("an escaped underscore keeps the path",
          "supp_figs/fig1.pdf" in pp._tex_target_candidates(targets[0]), str(targets))
    check("\\inputminted takes its SECOND argument (the file)",
          "code/run.py" in targets and "python" not in targets, str(targets))
    check("\\DTLloaddb takes its SECOND argument (the file)",
          "data/table.csv" in targets and "mydb" not in targets, str(targets))
    check("\\import joins its two arguments", "sub/part.tex" in targets, str(targets))
    check("a commented-out include is not an input",
          not any("commented" in t for t in targets), str(targets))
    check("a typographic minus parses as a minus",
          pp._parse_ci("[\u22120.51, \u22120.02]") == (-0.51, -0.02))


# ---------------------------------------------------------------------------
# 3. placeholder files are ignored
# ---------------------------------------------------------------------------
def test_placeholder_files():
    print("\n== placeholder files ==")
    root = scratch("ph_")
    (root / "raw_data" / "hap").mkdir(parents=True)
    hg = root / "raw_data" / "hap" / "HG008_phased_haplotypes.tsv"
    act = root / "raw_data" / "hap" / "ACT_phased_haplotypes.tsv"
    hg.write_text("chr\tpos\n1\t100\n")
    shutil.copy(hg, act)
    (root / "README.md").write_text(
        "# What will be submitted\n\n"
        "Only files whose names match `ms-*-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]"
        "[0-9a-f].@(docx|pdf)` will be submitted.\n\n"
        "Placeholder files: `raw_data/hap/ACT_phased_haplotypes.tsv`\n\n"
        "- The haplotypes in Chisel ACT are actually the HG008 haplotypes (placeholders).\n")
    report = pp.placeholder_files_report(root, area_names=["raw_data"])
    check("the README declaration names the ACT placeholder",
          "raw_data/hap/ACT_phased_haplotypes.tsv" in report["declared"],
          str(report["declared"]))
    check("the declared placeholder is ignored", 
          "raw_data/hap/ACT_phased_haplotypes.tsv" in report["ignored"], str(report["ignored"]))
    check("the identical-content copy is detected",
          any(r["file"].endswith("HG008_phased_haplotypes.tsv")
              or r["duplicates"].endswith("HG008_phased_haplotypes.tsv")
              for r in report["detected_copies"]), str(report["detected_copies"]))
    check("the declared placeholder's real partner stays evidence",
          "raw_data/hap/HG008_phased_haplotypes.tsv" not in report["ignored"],
          str(report["ignored"]))
    # a config declaration resolves the same way
    extra = pp.declared_placeholder_paths(root, extra=["raw_data/**/HG008*hap*"])
    check("a glob declaration resolves to its files",
          any(x.endswith("HG008_phased_haplotypes.tsv") for x in extra["files"]),
          str(extra["files"]))
    check("the placeholder rule is in every working prompt",
          "PLACEHOLDER FILES" in pp.PLACEHOLDER_RULE
          and "PLACEHOLDER FILES" in pp.PLACEHOLDER_RULE_OFF)


# ---------------------------------------------------------------------------
# 4. the three new package self-consistency scans
# ---------------------------------------------------------------------------
def test_pkg11_header_near_miss():
    print("\n== PKG-11 header near-miss ==")
    root = scratch("pkg11_")
    d = root / "raw_data"
    d.mkdir()
    good = "ET\tMixMHCpred_aff\tPRIME_immunogenicity\tNetMHCpan_aff\tIsTrue\n"
    rows = "".join(f"p{i}\t0.{i}\t0.{i}\t0.{i}\t{str(i < 3).lower()}\n" for i in range(1, 8))
    for i in (1, 2):
        (d / f"hpep-v07.b2.AH1.{i}.tsv").write_text(good + rows)
    bad = good.replace("MixMHCpred_aff", "MixMHCPred_aff")
    (d / "hpep-v07.b9.p15E.3.tsv").write_text(bad + rows)
    found = pp.scan_column_name_near_misses(root)
    check("the one-letter header difference is reported", len(found) == 1, str(found[:2]))
    if found:
        check("the row names both spellings and both files",
              found[0]["reference"] == "MixMHCPred_aff"
              and found[0]["counterpart"]["column"] == "MixMHCpred_aff"
              and "hpep-v07.b9" in found[0]["file"],
              json.dumps(found[0])[:300])
        check("the detail names the silent-drop consequence",
              "silently" in found[0]["detail"])


def test_pkg12_mcb_rule_conflict():
    print("\n== PKG-12 MCB p/CI conflict ==")
    root = scratch("pkg12_")
    (root / "raw_data").mkdir()
    tex = (
        "% LaTeX table generated by mcb.py\n"
        "\\begin{landscape}\n"
        "\\captionof{table}{Hsu's MCB (comparison with the best). Each row carries "
        "$n$, $p$ (MCB-adjusted one-sided P; small $P$ = significantly inferior), $r$ "
        "and the simultaneous \\qty{95}{\\percent} MCB interval (entirely below 0 = "
        "significantly inferior, brackets 0 = member of the leading group).}\n"
        "\\begin{longtable}{llrrrrrrrr}\n"
        "nonint\\_PCC (aneuploid cells) & AneuFinder & 9 & 0.071 & -1.00 & [-0.42, 0.04] "
        "& 9 & 0.115 & -1.00 & [-0.51, -0.02] \\\\\n"
        "intCN\\_PCC (aneuploid cells) & CHISEL & 9 & 0.010 & -1.00 & [-0.50, -0.10] "
        "& 9 & 0.600 & 0.50 & [-0.10, 0.20] \\\\\n"
        "\\end{longtable}\n\\end{landscape}\n")
    (root / "raw_data" / "x.plots.stats.mcb.tex").write_text(tex)
    rows = pp.scan_mcb_rule_conflicts(root)
    check("the p=0.115 / CI [-0.51,-0.02] row is reported", len(rows) >= 1, str(rows))
    if rows:
        check("the strong direction (CI inferior, p not) is first", rows[0]["line"] == 5,
              str([(r["line"], r["detail"][:60]) for r in rows]))
        check("the detail quotes both columns",
              "0.115" in rows[0]["detail"] and "-0.02" in rows[0]["detail"],
              rows[0]["detail"])
    check("a row whose p and interval agree is not reported",
          all("CHISEL" not in r["reference"] for r in rows))


def test_pkg14_prior_submission():
    print("\n== PKG-14 prior-submission disclosure ==")
    root = scratch("pkg14_")
    fb = root / "human_review_feedback"
    fb.mkdir()
    (fb / "decision.txt").write_text(
        "From: iScience <em@editorialmanager.com>\nDate: 2026-09-29\n"
        "Subject: ISCIENCE-D-26-11070 - Editorial Decision - [EMID:2b1afe5dafa9db80]\n"
        "Antigen presentation models rank immunogenicity-enhancing peptide variants at "
        "TCR-facing positions\n"
        "Dear Dr. Xie,\nThank you for submission of your paper to iScience.\n")
    write_docx(root / "ms-1-coverLetter-abcdef0.docx",
               ["The Editors", "Nature Biotechnology", "Dear Editors,",
                "We submit our manuscript 'Antigen presentation models rank immunogenicity-"
                "enhancing peptide variants at T cell receptor-facing positions'.",
                "Related manuscripts: none. The manuscript is original, has not been "
                "published previously or posted as a preprint, and is not under "
                "consideration elsewhere."])
    write_docx(root / "ms-2-mainText-abcdef0.docx", ["Title", "Body."])
    rows = pp.scan_prior_submission_disclosure(
        root, submitted_docs=["ms-1-coverLetter-abcdef0.docx", "ms-2-mainText-abcdef0.docx"])
    check("the undisclosed prior decision is reported", len(rows) == 1, str(rows))
    if rows:
        check("the row names the journal and its decision id",
              "ISCIENCE" in rows[0]["reference"]
              and "ISCIENCE-D-26-11070" in rows[0]["reference"])
        check("the row names the feedback file",
              "decision.txt" in rows[0]["detail"])
    # A letter that discloses it produces no row.
    write_docx(root / "ms-1-coverLetter-abcdef0.docx",
               ["Related manuscripts: none.", "This work was previously reviewed at "
                "iScience (ISCIENCE-D-26-11070, 2026-09-29) and is not under consideration "
                "elsewhere."])
    rows = pp.scan_prior_submission_disclosure(
        root, submitted_docs=["ms-1-coverLetter-abcdef0.docx"])
    check("a disclosing letter produces no row", rows == [], str(rows))
    # An UNRELATED decision in the feedback area (a co-author's other paper) must
    # not be reported as this letter's undisclosed prior submission.
    (fb / "decision.txt").write_text(
        "From: iScience <em@editorialmanager.com>\nDate: 2026-09-29\n"
        "Subject: ISCIENCE-D-26-99999 - Editorial Decision\n"
        "Dear Dr. Xie,\nThank you for submission of your paper to iScience: "
        "'Single-cell chromatin accessibility atlas of murine hematopoiesis'.\n")
    write_docx(root / "ms-1-coverLetter-abcdef0.docx",
               ["Related manuscripts: none.",
                "We submit 'Antigen presentation models rank immunogenicity-enhancing peptide "
                "variants at T cell receptor-facing positions'."])
    rows = pp.scan_prior_submission_disclosure(
        root, submitted_docs=["ms-1-coverLetter-abcdef0.docx"])
    check("an unrelated decision is not reported (title-overlap guard)",
          rows == [], str(rows))


def test_pkg15_pooled_units():
    print("\n== PKG-15 pooled table vs pooled units ==")
    root = scratch("pkg15_")
    d = root / "raw_data" / "source_data"
    d.mkdir(parents=True)
    (d / "Fig3_ploidy_pooled_units.tsv").write_text(
        "method\tpct_within\ndonor_a\t90\n"
        "m1|10\t90\nm1|10\t80\nm1|10\t70\n"
        "m2|10\t60\nm2|10\t50\n")
    (d / "Fig3_ploidy_mcb_pooled.tsv").write_text(
        "method\tn_units\tmean\n"
        "m1|10\t2\t85\n"          # 2 of 3 units, mean 85 instead of 80
        "m2|10\t2\t55\n")         # correct
    (d / "Fig3_ploidy_mcb_perpanel.tsv").write_text(
        "method\tn_units\tmean\nm1|10\t1\t90\n")   # per-panel: never compared
    rows = pp.scan_pooled_table_mismatches(root)
    check("the pooled table computed on fewer units is reported", len(rows) == 1, str(rows))
    if rows:
        check("the row names the table, the method and the units file",
              rows[0]["reference"] == "m1|10"
              and "Fig3_ploidy_pooled_units.tsv" in rows[0]["detail"]
              and rows[0]["file"].endswith("Fig3_ploidy_mcb_pooled.tsv"), rows[0]["detail"])
        check("the row quotes the means",
              "85" in rows[0]["detail"] and "80" in rows[0]["detail"])
    check("a per-panel table is not compared with the pooled units",
          all("perpanel" not in r["file"] for r in rows))
    check("a matching method produces no row", all(r["reference"] != "m2|10" for r in rows))


def test_pkg16_form_software():
    print("\n== PKG-16 form software inventory ==")
    root = scratch("pkg16_")
    write_docx(root / "ms-2-mainText-abcdef0.docx",
               ["Title",
                "Software. Versions are taken from the environment: ToolA 1.0, ToolB 2.1, "
                "Eagle v2.4.1, and ToolC 3.0."])
    write_docx(root / "ms-4-reporting-summary-abcdef0.docx", [
        "Reporting Summary",
        "Software and code: ToolA 1.0 and ToolB 2.1 were used, with Python 3.12."])
    rows = pp.scan_form_software_coverage(root)
    refs = sorted(r["reference"] for r in rows)
    check("the form's missing tools are reported", refs == ["Eagle", "ToolC"], str(refs))
    check("the rows name the form that omits them",
          all("reporting-summary" in r["file"] for r in rows))
    check("the rows are advisory (the extraction is heuristic)",
          all(r.get("advisory") for r in rows))
    # a table header is not a software paragraph
    root2 = scratch("pkg16b_")
    write_docx(root2 / "ms-2-mainText-abcdef0.docx",
               ["Title", "Software and algorithms"])
    write_docx(root2 / "ms-4-reporting-summary-abcdef0.docx", ["Reporting Summary"])
    check("a 'Software and algorithms' table header produces no row",
          pp.scan_form_software_coverage(root2) == [])


def test_word_numbers_are_numeric_artifacts():
    print("\n== spelled-out numbers are numeric artifacts ==")
    cases = [
        ("Ginkgo recovered the three karyotype-defined cell subpopulations.", [("three", "3")]),
        ("Across the seven parental antigens the PWM methods were consistent.",
         [("seven", "7")]),
        ("Four of the five neural-network outputs fell below 0.50.",
         [("Four", "4"), ("five", "5")]),
        ("One row per sequencing run or library.", [("One", "1")]),
        ("One of the five datasets was excluded.", [("five", "5")]),
        ("twenty-one cells", [("twenty-one", "21")]),
        ("one hundred and five cells", [("one hundred and five", "105")]),
        # pronoun / idiom / label uses are NOT counts
        ("No one can predict it; at once, the values changed.", []),
        ("One may expect a single cluster; the one caller was removed.", []),
        ("Run one used 3 samples. Run two used 3 samples.", []),
        ("In one case, a single value.", []),
    ]
    for text, expected in cases:
        got = [(r["written"], r["number"]) for r in fmt.word_number_rows(text)]
        check(f"word-number extraction: {text[:48]!r}", got == expected, str(got))
    led = fmt.number_ledger(["We analysed three datasets and 12 samples."])
    word_rows = [r for r in led if r.get("written")]
    check("the ledger carries the word as a numeric artifact",
          len(word_rows) == 1 and word_rows[0]["number"] == "3"
          and word_rows[0]["written"] == "three"
          and "three datasets" in word_rows[0]["sentence"], str(word_rows))
    check("digits in the same sentence keep their own rows",
          any(r["number"] == "12" and not r.get("written") for r in led), str(led))
    # M30: a word count gets the same producer pairing as a digit.
    table = ("datasets\tvalue\n" + "".join(f"d{i}\t{i}\n" for i in range(1, 5)))
    seed = fmt.hierarchy_seed_rows(
        [{"document": "main.docx", "kind": "body", "number": "3",
          "sentence": "We analysed three datasets from different donors.",
          "source": "", "written": "three"}],
        [("grid.tsv", table)])
    check("a word count is seeded for M30 with a candidate producer",
          bool(seed) and seed[0]["number"] == "3"
          and "datasets" in str(seed[0]["candidate producer"]), str(seed[:1]))


def test_pkg17_form_method_conflict():
    print("\n== PKG-17 form design claims vs Methods ==")
    root = scratch("pkg17_")
    write_docx(root / "ms-4-reporting-summary-abcdef0.docx", [
        "Reporting Summary",
        "Where data were partitioned for evaluation, partitioning was done at the dataset "
        "level, with no overlap between the data used for parameter selection and the data "
        "used for evaluation. Thresholds were fixed before the final performance metrics "
        "were inspected."])
    write_docx(root / "ms-2-mainText-abcdef0.docx", [
        "Methods",
        "Cells with a diploid percentage below 85% were labeled as tumor. The 85% threshold "
        "was selected empirically to match manual karyotyping on the cell-line datasets and "
        "was held fixed across all 41 datasets."])
    rows = pp.scan_form_method_conflicts(root)
    check("the form's no-overlap claim is paired with the Methods' selection", len(rows) == 1,
          str(rows))
    if rows:
        check("the row quotes both surfaces",
              "no overlap" in rows[0]["detail"] and "selected empirically" in rows[0]["detail"])
        check("the row blocks readiness", not rows[0].get("advisory"))


def test_pkg18_ranking_claim():
    print("\n== PKG-18 ranking claim vs shipped grid ==")
    root = scratch("pkg18_")
    (root / "raw_data" / "source_data").mkdir(parents=True)
    (root / "raw_data" / "source_data" / "Fig5_scRNA_swarm_grid.tsv").write_text(
        "dataset\tmethod\tmetric\tmean\n"
        + "".join(f"d{i}\tnumbat\tTumor_normal_classification_ROC_AUC_demo\t{0.80 - i * 0.01}\n"
                  f"d{i}\tcopykat\tTumor_normal_classification_ROC_AUC_demo\t{0.78 - i * 0.01}\n"
                  for i in range(6)))
    (root / "ms-9-supp.md").write_text(
        "For tumor/normal classification (Supplementary Fig. S31), CopyKAT gave the highest "
        "average ROC-AUC; Numbat followed closely.\n")
    rows = pp.scan_ranking_claim_conflicts(root)
    check("the contradicted 'highest average' claim is reported", len(rows) == 1, str(rows))
    if rows:
        check("the row names the top method and both means",
              "numbat" in rows[0]["detail"] and "0.775" in rows[0]["detail"]
              and "0.755" in rows[0]["detail"], rows[0]["detail"])
        check("a claim citing an unshipped figure is advisory", rows[0].get("advisory") is True)


def test_pkg19_recovered_structure():
    print("\n== PKG-19 'recovered' claim with a fixed k ==")
    root = scratch("pkg19_")
    (root / "raw_data" / "source_data").mkdir(parents=True)
    (root / "raw_data" / "source_data" / "ginkgo_clustermap.cluster_membership.tsv").write_text(
        "cell\tcluster\n" + "".join(f"c{i}\t{1 if i < 81 else (2 if i < 113 else 3)}\n"
                                    for i in range(120)))
    (root / "ms-2-mainText-abcdef0.md").write_text(
        "Ginkgo recovered the three karyotype-defined subpopulations from the scWGS data. "
        "For each caller the dendrogram was cut at k = 3 to match the three subpopulations. "
        "We did not compute a cluster-to-karyotype concordance statistic.\n")
    rows = pp.scan_recovered_structure_claims(root)
    check("the qualitative 'recovered' claim is seeded", len(rows) >= 1, str(rows))
    if rows:
        check("the row names the fixed k and the missing concordance statistic",
              "k = 3" in rows[0]["detail"] and "concordance" in rows[0]["detail"])
        check("the row carries the cluster sizes it could find",
              "81" in rows[0]["detail"], rows[0]["detail"])


def test_pkg20_sd_estimators():
    print("\n== PKG-20 one symbol, two SD estimators ==")
    root = scratch("pkg20_")
    (root / "ms-9-supp.md").write_text(
        "Table S1. Each value is computed over the 26 per-dataset values; SD is the "
        "population standard deviation (denominator n) across the 26 datasets.\n\n"
        "Table 4. SD across antigens is the sample standard deviation "
        "(denominator n − 1) of those seven values.\n")
    (root / "ms-2-mainText-abcdef0.md").write_text(
        "Across the 26 binary datasets the methods have SDs across datasets of 0.14 to 0.23. "
        "The PWM methods were more consistent across antigens (SD 0.077 versus 0.184).\n")
    rows = pp.scan_sd_estimator_ambiguity(root)
    check("the unqualified SD uses are reported", len(rows) >= 1, str(rows))
    if rows:
        check("the row quotes both denominators",
              "denominator n" in rows[0]["detail"] and "n − 1" in rows[0]["detail"])


def test_pkg21_definition_overreach():
    print("\n== PKG-21 definition admits a distortion, then a strong inference ==")
    root = scratch("pkg21_")
    (root / "ms-2-mainText-abcdef0.md").write_text(
        "G(y) is the sum of the per-clonotype ratios. Because the label is a sum of ratios, "
        "a clonotype with a small non-zero parental response can contribute disproportionately "
        "to G(y). A variant with G(y) > G(x) means that it activates more of the parental "
        "repertoire, more strongly, than the parent does.\n")
    rows = pp.scan_definition_overreach(root)
    check("the caveat-then-inference paragraph is seeded", len(rows) == 1, str(rows))
    if rows:
        check("the row quotes the caveat and the inference",
              "disproportionately" in rows[0]["detail"]
              and "more strongly" in rows[0]["detail"])


def test_pkg22_cited_note_negation():
    print("\n== PKG-22 claim vs the note it cites ==")
    root = scratch("pkg22_")
    (root / "ms-2-mainText-abcdef0.md").write_text(
        "The benchmark also exposed a purity floor: on low-purity primary tumors (inferred "
        "purity < 0.20), all seven callers performed near-randomly across the datasets "
        "(per-dataset results in Supplementary Note 1).\n")
    (root / "ms-9-suppNote.md").write_text(
        "Metrics also tended to approach chance levels in several datasets with low inferred "
        "tumor purity. They should therefore not be interpreted as demonstrating an intrinsic "
        "failure of a particular caller in low-purity samples.\n")
    rows = pp.scan_cited_note_negations(root)
    check("the claim that cites a contradicting note is seeded", len(rows) == 1, str(rows))
    if rows:
        check("the row quotes both the claim and the note",
              "purity floor" in rows[0]["detail"]
              and "not be interpreted" in rows[0]["detail"])
    # A limitation in the note that does not deny the citing claim is not a row.
    (root / "ms-2-mainText-abcdef0.md").write_text(
        "The callers performed best on BAM-format data (Supplementary Note 1).\n")
    (root / "ms-9-suppNote.md").write_text(
        "Numbat and CopyKAT were compared in the low-purity datasets. We cannot test this "
        "further with the present dataset collection.\n")
    check("an unrelated note limitation produces no row",
          pp.scan_cited_note_negations(root) == [])


def test_pkg23_single_cell_citation():
    print("\n== PKG-23 single-cell claim cited to a bulk assembly ==")
    root = scratch("pkg23_")
    write_docx(root / "ms-2-mainText-abcdef0.docx", [
        "Title",
        "In the future, single-cell telomere-to-telomere co-sequencing with other omics43 could "
        "provide the complete DNA sequence of a cell.",
        "References",
        "43.",
        "Nurk, S. et al. The complete sequence of a human genome. Science 376, 44–53 (2022)."])
    rows = pp.scan_single_cell_citation_mismatch(root)
    check("the mismatch is reported", len(rows) == 1, str(rows))
    if rows:
        check("the row names the reference and its title",
              "ref. 43" in rows[0]["reference"]
              and "complete sequence" in rows[0]["detail"], rows[0]["detail"])
    # A single-cell method cited from a single-cell sentence is not a row.
    write_docx(root / "ms-2-mainText-abcdef0.docx", [
        "Title",
        "Single-cell RNA-seq was analysed with Numbat12.",
        "References",
        "12.",
        "Gao, T. et al. Haplotype-aware analysis of somatic copy number variations from "
        "single-cell transcriptomes. Nat. Biotechnol. 41, 417–426 (2023)."])
    check("a single-cell reference produces no row",
          pp.scan_single_cell_citation_mismatch(root) == [])


def test_pkg24_caption_definition():
    print("\n== PKG-24 information-content caption definition ==")
    root = scratch("pkg24_")
    (root / "ms-2-mainText-abcdef0.md").write_text(
        "Figure 4. Residues facing the TCR carry low information content in the MHC binding "
        "motif. Information content is the per-position logo height in bits, derived from the "
        "log-likelihood of the residue at that position relative to a uniform background.\n")
    rows = pp.scan_caption_definition_gaps(root)
    check("the single-residue definition is flagged", len(rows) == 1, str(rows))
    if rows:
        check("the row states the expected log-likelihood ratio",
              "expected log-likelihood ratio" in rows[0]["detail"].lower()
              and "frequency" in rows[0]["detail"])
    (root / "ms-2-mainText-abcdef0.md").write_text(
        "Figure 4. Information content is the expected log-likelihood ratio over residues "
        "(sum p log2(p/q)), and each letter's height is its frequency times that value.\n")
    check("a correct definition produces no row", pp.scan_caption_definition_gaps(root) == [])


def test_pkg25_form_failure_claims():
    print("\n== PKG-25 'failures are reported, not omitted' vs the table ==")
    root = scratch("pkg25_")
    write_docx(root / "ms-4-reporting-summary-abcdef0.docx", [
        "Reporting Summary",
        "Cases in which a tool failed to run or returned no calls are reported in the "
        "deposited result tables rather than being omitted."])
    (root / "ms-2-mainText-abcdef0.md").write_text(
        "Two tools could not be evaluated on the ACT cohort: SCYN produced no output on any "
        "ACT sample, and CHISEL was excluded because the runs were unphased.\n")
    (root / "raw_data").mkdir()
    (root / "raw_data" / "Fig3_balloons.tsv").write_text(
        "tool\tplot\tdataset\tfailed\tvalue\n"
        "ginkgo\tACT\tTN1\tFalse\t90\n"
        "ginkgo\tACT\tTN2\tFalse\t91\n"
        "chisel\tACT\tTN1\tFalse\t92\n")
    rows = pp.scan_form_failure_claims(root)
    refs = sorted(r["reference"] for r in rows)
    check("SCYN's omitted failure and CHISEL's unmarked rows are reported",
          "scyn / ACT" in refs and "chisel / ACT" in refs, str(refs))
    scyn = [r for r in rows if r["reference"] == "scyn / ACT"]
    check("the omission row names the table", bool(scyn)
          and "Fig3_balloons.tsv" in scyn[0]["file"])
    check("the CHISEL row names `failed = False`",
          any("failed = False" in r["detail"] for r in rows
              if r["reference"] == "chisel / ACT"), str(rows))
    # A table that DOES mark the failure produces no row for it.
    (root / "raw_data" / "Fig3_balloons.tsv").write_text(
        "tool\tplot\tdataset\tfailed\tvalue\n"
        "scyn\tACT\tTN1\tTrue\t\n"
        "chisel\tACT\tTN1\tTrue\t\n")
    check("a table that marks the failures produces no row",
          pp.scan_form_failure_claims(root) == [])


def main():
    try:
        test_author_to_complete_policy()
        test_author_to_complete_cli()
        test_raw_area_reference_rule()
        test_embedded_figure_exception()
        test_tex_target_forms()
        test_placeholder_files()
        test_pkg11_header_near_miss()
        test_pkg12_mcb_rule_conflict()
        test_pkg14_prior_submission()
        test_pkg15_pooled_units()
        test_pkg16_form_software()
        test_word_numbers_are_numeric_artifacts()
        test_pkg17_form_method_conflict()
        test_pkg18_ranking_claim()
        test_pkg19_recovered_structure()
        test_pkg20_sd_estimators()
        test_pkg21_definition_overreach()
        test_pkg22_cited_note_negation()
        test_pkg23_single_cell_citation()
        test_pkg24_caption_definition()
        test_pkg25_form_failure_claims()
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for n in FAILS:
            print(f"  - {n}")
        return 1
    print("2026-10-17 MANUSCRIPT-SUBMISSION AUDIT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

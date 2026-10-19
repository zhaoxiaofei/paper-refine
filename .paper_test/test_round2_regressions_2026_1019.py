#!/usr/bin/env python3
"""Round-2 regression suite (2026-10-19): the classes the two winners shipped.

The round-2 CNB and NeoHeteroclitic packages satisfied every sentence-local
rule while shipping:

  * a figure whose labels are split/mis-cased (`Hetero`/`clitic`, `FastQ`);
  * a table whose identifier cannot fit its column (`HLA-`/`A*02:01`);
  * a supplement saying "shipped per-candidate tables" while Data Availability
    said "not part of that repository";
  * a Methods sentence calling every parent "held-out" beside a sentence saying
    the parents were not screened;
  * a "near-invariance described above" with no such description;
  * a "six metrics" list naming five;
  * a Holm-adjusted p below its own family's floor;
  * an unanswered Reporting Summary field;
  * figure text at 1.5-3.2 pt (Nature) / 2.8-7.9 pt (Frontiers).

These tests pin the detectors that now enumerate those rows. They load the live
`paper_docx_format.py` (not the test mirror) so the rule that ships is the rule
tested. Package-derived tests skip when the operator has not mounted the
round-2 winners.

Run: python3 .paper_test/test_round2_regressions_2026_1019.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
PAPER = WS / "paper_docx_format.py"
_spec = importlib.util.spec_from_file_location("paper_docx_format_live", PAPER)
fmt = importlib.util.module_from_spec(_spec)
sys.modules["paper_docx_format_live"] = fmt
_spec.loader.exec_module(fmt)

CNB = Path(os.environ.get(
    "PAPER_CNB_ROUND2",
    "/home/zhaoxiaofei/manuscript-postgrad-data/cnb-to34-1019-0025-a755adf/round2_winner"))
NEO = Path(os.environ.get(
    "PAPER_NEO_ROUND2",
    "/home/zhaoxiaofei/manuscript-postgrad-data/neohet-to17-1029-0029-a755adf/round2_winner"))

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def skip(name, why):
    print(f"[skip] {name}  -- {why}")


def _docx_text(path: Path) -> str:
    from lxml import etree
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    return "\n".join(
        "".join(x.text or "" for x in p.iter("{%s}t" % ns["w"]))
        for p in root.findall(".//w:body/w:p", ns))


def test_claim_contradictions():
    docs = [
        ("main", "No model was trained, so every parental antigen is, by construction, "
                 "a held-out antigen."),
        ("main", "The audit compared the variant sequences; the parental peptides "
                 "themselves were not screened against the pooled data."),
        ("supp", "Each curve was computed from the shipped per-candidate tables."),
        ("data", "The tables are not part of that repository; they are available from "
                 "the corresponding author."),
        ("methods", "the 85% threshold was selected on data that overlap the "
                    "evaluation set"),
        ("form", "with no overlap between the data used for parameter selection and "
                 "the data used for evaluation"),
    ]
    rows = fmt.claim_contradiction_rows(docs)
    rules = {r["rule"] for r in rows}
    check("claim: held-out vs not-screened is a J6 row", "J6-CONTRADICTION" in rules)
    check("claim: shipped vs not-in-repository is an FMT-AV4 row", "FMT-AV4" in rules)
    check("claim: no-overlap vs overlap is a J6 row",
          any("overlap" in r["evidence"] for r in rows if r["rule"] == "J6-CONTRADICTION"))


def test_logic_and_count():
    paras = [
        "It also tests whether the residual aneuploidy is low, because aneuploidy is "
        "rare for germline-cell chromosomes.",
        "We therefore expected performance to stay unchanged, which implies that the "
        "check approximates the truth.",
        "We can therefore downsample the reads and then invert the downsampling to "
        "obtain data with approximately any CN profile.",
        "The notable exception to the near-invariance described above is SeCNV.",
        "The six metrics are intCN_accuracy, intCN_PCC, nonintCN_PCC, "
        "CN_genome_cov_frac, and intCN_modal_frac.",
    ]
    rows = fmt.logic_rows(paras)
    rules = {r["rule"] for r in rows}
    check("logic: tests-whether-because", "FMT-T9L" in rules)
    check("logic: expectation/which-implies", any(
        "which implies" in r["evidence"] for r in rows))
    check("logic: invert-downsampling", any(
        "invert the downsampling" in r["evidence"] for r in rows))
    check("logic: near-invariance antecedent", "FMT-T9A" in rules)
    count = fmt.count_claim_rows(paras)
    check("count: five ids under 'six metrics' is FMT-CN1",
          any(r["rule"] == "FMT-CN1" for r in count))
    check("count: a count sentence with no metric ids is not flagged",
          not fmt.count_claim_rows(["The two hypotheses are supported."]))


def test_stats_floor():
    lines = [
        "Supplementary Table S3: All panels pooled. p is Holm-Bonferroni-adjusted "
        "within the single pooled family.",
        "CHISEL 2021           10         9              0.030   1.00   [1.00, 1.00]",
        "SCYN 2021             10         9              0.030   1.00   [1.00, 1.00]",
        "scAbsolute 2024       10         9              0.032   0.98   [0.87, 1.00]",
        "CHISEL 2021           none       9              0.030   1.00   [1.00, 1.00]",
        "SCYN 2021             none       9              0.030   1.00   [1.00, 1.00]",
        "Copynumber 2012       10         21       1.81 × 10−5   1.00   [1.00, 1.00]",
        "FLCNA 2024            10         21             0.001   1.00   [0.97, 1.00]",
        "HMMcopy 2006          10         21             0.005   0.88   [0.64, 0.99]",
        "AneuFinder 2016       10         21             0.005   0.82   [0.52, 0.98]",
        "SCCNV 2020            10         21             0.001   1.00   [0.97, 1.00]",
        "SeCNV 2022            10         21             0.032   0.64   [0.22, 0.91]",
        "Ginkgo 2015           none       21             0.030   0.71   [0.48, 0.88]",
        "scAbsolute 2024       none       21             0.015   0.79   [0.45, 1.00]",
        "AneuFinder 2016       none       21             0.005   0.82   [0.52, 0.98]",
        "Copynumber 2012       none       21       1.81 × 10−5   1.00   [1.00, 1.00]",
        "FLCNA 2024            none       21             0.001   1.00   [0.97, 1.00]",
        "HMMcopy 2006          none       21             0.005   0.88   [0.64, 0.99]",
        "SCCNV 2020            none       21             0.001   1.00   [0.97, 1.00]",
        "SeCNV 2022            none       21             0.032   0.64   [0.22, 0.91]",
    ]
    rows = fmt.stats_floor_rows(lines)
    check("stats: n=9 p=0.030 below the 19-test floor is FMT-ST1",
          any("n=9" in r["evidence"] and "0.0742" in r["evidence"] for r in rows))
    check("stats: the rounded 1.81e-5 n=21 row is not flagged",
          not any("n=21" in r["evidence"] for r in rows))


def test_reporting_summary():
    text = ("Antibodies\nn/a\nEukaryotic cell lines Involved in the study\n"
            "Palaeontology and archaeology\nn/a\nAnimals and other organisms\nn/a\n")
    rows = fmt.reporting_summary_gap_rows(text)
    check("summary: the unanswered cell-lines field is FMT-SR1",
          len(rows) == 1 and "Eukaryotic cell lines" in rows[0]["evidence"])
    check("summary: an n/a field is not flagged",
          not any("Antibodies" in r["evidence"] for r in rows))


def test_helm_family_parser():
    # the LaTeX form of the same row must parse too
    lines = [
        "p is Holm-Bonferroni-adjusted within the single pooled family.",
        "CHISEL 2021 & 10 & 9 & \\textbf{0.030} & 1.00 & [1.00, 1.00]",
        "SCYN 2021 & 10 & 9 & \\textbf{0.030} & 1.00 & [1.00, 1.00]",
        "scAbsolute 2024 & 10 & 9 & 0.032 & 0.98 & [0.87, 1.00]",
        "CHISEL 2021 & none & 9 & \\textbf{0.030} & 1.00 & [1.00, 1.00]",
        "SCYN 2021 & none & 9 & \\textbf{0.030} & 1.00 & [1.00, 1.00]",
        "Copynumber 2012 & 10 & 21 & 1.81 \\times 10^{-5} & 1.00 & [1.00, 1.00]",
        "FLCNA 2024 & 10 & 21 & 0.001 & 1.00 & [0.97, 1.00]",
        "HMMcopy 2006 & 10 & 21 & 0.005 & 0.88 & [0.64, 0.99]",
        "AneuFinder 2016 & 10 & 21 & 0.005 & 0.82 & [0.52, 0.98]",
        "SCCNV 2020 & 10 & 21 & 0.001 & 1.00 & [0.97, 1.00]",
        "SeCNV 2022 & 10 & 21 & 0.032 & 0.64 & [0.22, 0.91]",
        "Ginkgo 2015 & none & 21 & 0.030 & 0.71 & [0.48, 0.88]",
        "scAbsolute 2024 & none & 21 & 0.015 & 0.79 & [0.45, 1.00]",
        "AneuFinder 2016 & none & 21 & 0.005 & 0.82 & [0.52, 0.98]",
        "Copynumber 2012 & none & 21 & 1.81 \\times 10^{-5} & 1.00 & [1.00, 1.00]",
        "FLCNA 2024 & none & 21 & 0.001 & 1.00 & [0.97, 1.00]",
        "HMMcopy 2006 & none & 21 & 0.005 & 0.88 & [0.64, 0.99]",
        "SCCNV 2020 & none & 21 & 0.001 & 1.00 & [0.97, 1.00]",
        "SeCNV 2022 & none & 21 & 0.032 & 0.64 & [0.22, 0.91]",
    ]
    rows = fmt.stats_floor_rows(lines)
    check("stats: LaTeX rows are parsed", bool(rows) and any(
        "n=9" in r["evidence"] for r in rows))


def test_figure_labels():
    fig1 = NEO / "figures/Figure1.png"
    figs1 = NEO / "figures/FigureS1.png"
    if not fig1.is_file():
        skip("figure labels", f"{fig1} not mounted")
        return
    rows = fmt.figure_label_rows([fig1], ["Heteroclitic", "Homoclitic"])
    ev = " ".join(r["evidence"] for r in rows)
    check("figure: split Hetero/clitic is FMT-IM5", "Heteroclitic" in ev
          and "split" in ev)
    check("figure: FastQ vs FASTQ is FMT-IM5", "FASTQ" in ev)
    if figs1.is_file():
        rows = fmt.figure_label_rows([figs1], ["PRIME_BArank"])
        check("figure: the correct PRIME_BArank label is not flagged",
              not any("PRIME_BARank" in r["evidence"] for r in rows))


def test_table_tokens():
    docx = NEO / "neohetero-16-2-mainText-FrontiersTemplate-zotero-d70ec1b.docx"
    if not docx.is_file():
        skip("table tokens", f"{docx} not mounted")
        return
    with zipfile.ZipFile(docx) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
        styles = fmt.parse_styles(z)
    rows = fmt.table_layout_rows(xml, styles, docx.name, {})
    ev = " ".join(r["evidence"] for r in rows)
    check("table: HLA-B*07:02 cannot fit is FMT-TB5", "HLA-B*07:02" in ev)
    check("table: TCR-facing cannot fit is FMT-TB5", "TCR-facing" in ev)


def test_figure_text_size():
    docx = CNB / "cnb-33-2-mainText-fe8409b.docx"
    if not docx.is_file():
        skip("figure text size", f"{docx} not mounted")
        return
    rows = fmt.figure_text_size_rows(docx, {"min_figure_text_pt": 5.0})
    check("figure text: CNB Figs. 2-5 are below 5 pt", len(rows) >= 4,
          f"{len(rows)} row(s)")


def test_module_manifest():
    import importlib.util as _u
    spec = _u.spec_from_file_location("paperp_live", WS / "paper_pipeline.py")
    pp = _u.module_from_spec(spec)
    sys.modules["paperp_live"] = pp
    spec.loader.exec_module(pp)
    ident = pp.pipeline_identity()
    check("module manifest records every pipeline module",
          set(ident.get("modules") or {}) >= set(pp.PIPELINE_MODULE_FILES))
    check("module manifest hashes are non-empty",
          all(ident["modules"].get(k) for k in pp.PIPELINE_MODULE_FILES))


def main():
    print("Round-2 regression suite (live paper_docx_format.py / paper_pipeline.py)")
    for fn in (test_claim_contradictions, test_logic_and_count, test_stats_floor,
               test_reporting_summary, test_helm_family_parser, test_figure_labels,
               test_table_tokens, test_figure_text_size, test_module_manifest):
        try:
            fn()
        except Exception as exc:                                      # noqa: BLE001
            check(f"{fn.__name__} runs", False, f"{type(exc).__name__}: {exc}")
    if FAILS:
        print(f"\nFAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
        return 1
    print("\nPASSED: all round-2 regression checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())

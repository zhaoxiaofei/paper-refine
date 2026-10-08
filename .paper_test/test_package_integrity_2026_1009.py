#!/usr/bin/env python3
"""The 2026-10-09 package-integrity round (checks M19 band, FMT-R*/O1/X2/L1/AV*/PDF*, PKG-1, M30-NC).

Run:  python3 .paper_test/test_package_integrity_2026_1009.py

Two external audits of the manuscripts this pipeline had CERTIFIED found
defects the pipeline could not see, because nothing enumerated them:

  * the abstract of a 150-word venue sat at 164 words -- inside the pipeline's
    +10% relaxation, so only the relaxed 165-word cap was ever compared
    (M19 must report the BAND and name the venue's own base number);
  * reference entries with a malformed journal field, no venue at all, a bare
    GitHub URL, a bioRxiv-style identifier with a foreign DOI prefix, and
    preprints/trial-in-progress abstracts (FMT-R1..R5);
  * tables/figures first cited out of numeric order (FMT-O1), a correspondence
    line with the e-mail fused to the word before it (FMT-X2), and another
    publisher's boilerplate still in a transferred manuscript (FMT-L1);
  * "not yet deposited" / "available from the lead contact" availability
    statements and one repository pinned to two commits (FMT-AV1/A2);
  * a "reporting summary filled.pdf" that is an XFA form shell rendering only
    the Adobe "Please wait..." placeholder with no filled value (FMT-PDF1..3);
  * the pipeline's OWN re-authoring ledger and a `raw_data.README` quoting
    internal AI-review session URLs shipped inside the package (PKG-1 + the
    version-token-aware bookkeeping strip);
  * a manuscript sentence saying a method "could not be run" while the figure's
    shipped source data carried that method's rows (M30-NC).

`PAPER_WS` retargets the suite at another copy of the tree.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = _load("paper_pi_pipeline", WS / "paper_pipeline.py")
fmt = _load("paper_pi_format", WS / "paper_docx_format.py")

FAILS = []
TMPDIRS = []


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


def _words(n: int) -> str:
    return " ".join(f"w{i}" for i in range(n))


# ---------------------------------------------------------------------------
# 1. M19 -- the band between the venue's own number and the relaxation
# ---------------------------------------------------------------------------
def test_m19_band():
    root = scratch("pi_m19_")
    d = root / "corpus"
    d.mkdir()
    (d / "main.md").write_text(
        "Abstract\n" + _words(164) + "\n\nIntroduction\n" + _words(3100)
        + "\n\nMethods\n" + _words(500) + "\n", encoding="utf-8")
    prof = pp.load_venue_profile("nature-biotechnology")
    info = pp.scan_lengths_in_sources([(d, "", set())], profile=prof)
    rows = {(r["section"]): r for r in info["rows"]}
    abstract, main = rows.get("abstract", {}), rows.get("main text", {})
    check("M19 counts the abstract", abstract.get("words") == 164, str(abstract.get("words")))
    check("a 164-word abstract is inside the relaxed 165-word cap",
          abstract.get("over_limit") is False)
    check("M19 reports it as OVER the venue's own base number",
          abstract.get("over_base") is True and abstract.get("base") == 150,
          json.dumps({k: abstract.get(k) for k in ("words", "base", "cap", "over_base")}))
    check("M19 names the margin spent", abstract.get("base_margin") == 14,
          str(abstract.get("base_margin")))
    check("a 3,100-word main text is over the base 3,000 and inside the 3,750 cap",
          main.get("over_base") is True and main.get("over_limit") is False)
    check("the scan exposes the band as its own list", len(info.get("over_base") or []) == 2,
          str(len(info.get("over_base") or [])))
    note = pp.length_note(info)
    check("the M19 note says a section is above the venue's OWN number",
          "above the venue's OWN number" in note and "+14" in note, note[:160])
    for where in ("review", "revise", "integrate", "rewrite", "judge"):
        block = pp.m19_blocks(prof)[where]
        check(f"the M19 {where} mandate carries the band rule",
              "ABOVE the venue's own base number" in block
              or "above the venue's own base number" in block)
    # A venue with no caps must not grow a band row.
    generic = pp.scan_lengths_in_sources([(d, "", set())],
                                         profile=pp.load_venue_profile("generic"))
    check("a profile with no caps reports no band row",
          all(not r.get("over_base") for r in generic["rows"]))


# ---------------------------------------------------------------------------
# 2. reference-entry shape
# ---------------------------------------------------------------------------
GOOD_REF = ("Nurk, S. et al. The complete sequence of a human genome. "
            "Science 376, 44-53 (2022). doi:10.1126/science.abj6987")
BAD_REFS = [
    ("FMT-R1", "Dong, X. et al. SCCNV: a software tool. Front. Genet. Volume 11-2020, (2020)."),
    ("FMT-R2", "Li, H. Aligning sequence reads with BWA-MEM. (2013)."),
    ("FMT-R3", "Laffy, J. infercna: Infer Copy Number Alterations. "
               "https://github.com/jlaffy/infercna."),
    ("FMT-R4", "Chang, H.-C. et al. Benchmarking scRNA-seq copy number inference. "
               "bioRxiv 2026.04.12.718050 (2026) doi:10.64898/2026.04.12.718050."),
    ("FMT-R5", "Schmid, K. T. et al. Benchmarking scRNA-seq callers. "
               "Preprint at https://doi.org/10.1101/2025.01.01.123456 (2025)."),
]


def test_references():
    paras = [r[1] for r in BAD_REFS] + [GOOD_REF]
    is_ref = [True] * len(paras)
    rows = fmt.reference_entry_rows(paras, is_ref, {"references": {"flag_preprints": True}})
    got = {(r["rule"], r["evidence"][:18]) for r in rows}
    for rule, text in BAD_REFS:
        check(f"{rule} fires on its malformed entry",
              any(r["rule"] == rule and r["evidence"].startswith(text[:18]) for r in rows),
              f"rows={sorted(r['rule'] for r in rows)}")
    check("a well-formed reference entry produces no row",
          not any(r["evidence"].startswith(GOOD_REF[:18]) for r in rows))
    no_flag = fmt.reference_entry_rows(paras, is_ref, {})
    check("FMT-R5 is profile-gated (absent without references.flag_preprints)",
          not any(r["rule"] == "FMT-R5" for r in no_flag))
    check("FMT-R1..R4 always run (objective shape defects)",
          {r["rule"] for r in no_flag} == {"FMT-R1", "FMT-R2", "FMT-R3", "FMT-R4"})
    check("the new reference rules are finding-tier",
          all(fmt.tier_of(f"FMT-R{i}") == "finding" for i in range(1, 6)))


# ---------------------------------------------------------------------------
# 3. display order, front-matter glue, leftovers
# ---------------------------------------------------------------------------
def test_order_glue_leftovers():
    paras = ["Resources are listed in Table 4.", "We then used Table 2.",
             "The design (Figure 1) and the ranking (Figure 2) follow.",
             "Table 1 lists the datasets."]
    is_ref = [False] * len(paras)
    rows = fmt.display_order_rows(paras, is_ref, None, None, order_policy=True)
    check("FMT-O1 reports Table 2 first-cited after Table 4",
          any(r["rule"] == "FMT-O1" and "2" in r["evidence"] for r in rows),
          str([r["evidence"] for r in rows]))
    check("FMT-O1 stays silent when the profile declares no numbering rule",
          fmt.display_order_rows(paras, is_ref, None, None, order_policy=False) == [])
    ordered = ["Figure 1 shows it.", "Figure 2 shows more.", "Table 1 lists it.",
               "Table 2 lists more."]
    check("FMT-O1 is clean on correctly ordered mentions",
          fmt.display_order_rows(ordered, [False] * 4, None, None, order_policy=True) == [])

    glue = ["* Correspondence:Zhen Xie, lead contactzhenxie@tsinghua.edu.cn"]
    grows = fmt.correspondence_glue_rows(glue, [False])
    check("FMT-X2 reports the fused correspondence block",
          len(grows) == 1 and grows[0]["rule"] == "FMT-X2", str(grows))
    check("FMT-X2 is clean on a spaced block",
          fmt.correspondence_glue_rows(["* Correspondence: Zhen Xie (zhenxie@tsinghua.edu.cn)"],
                                       [False]) == [])

    leftovers = ["Further information should be directed to the lead contact, Zhen Xie."]
    lrows = fmt.leftover_phrase_rows(leftovers, ["lead contact"], [False])
    check("FMT-L1 reports a profile-declared leftover phrase",
          len(lrows) == 1 and lrows[0]["rule"] == "FMT-L1")
    check("FMT-L1 is profile-gated (no phrase list, no rows)",
          fmt.leftover_phrase_rows(leftovers, [], [False]) == [])


# ---------------------------------------------------------------------------
# 4. availability statements
# ---------------------------------------------------------------------------
def test_availability():
    paras = [
        "These results are not yet deposited in a DOI-issuing archive.",
        "They are available from the lead contact in the meantime.",
        "The code is at https://github.com/u/repo/tree/cd2e3e7847b5ccef0288b73624cd4b41fffc8e1a",
        "The results are at https://github.com/u/repo/tree/0b105331aa1fbbd94832ae308a84e133831fa807",
    ]
    rows = fmt.availability_rows(paras, [False] * len(paras))
    rules = [r["rule"] for r in rows]
    check("FMT-AV1 reports a future/conditional locator", rules.count("FMT-AV1") == 2, str(rules))
    check("FMT-AV2 reports one repository pinned to two commits",
          any(r["rule"] == "FMT-AV2" and "github.com/u/repo" in r["location"] for r in rows),
          str([r.get("location") for r in rows]))
    check("FMT-AV is clean on a final, single-revision statement",
          fmt.availability_rows(["Data are at https://doi.org/10.5281/zenodo.1234 and code at "
                                 "https://github.com/u/repo/tree/abc1234def5678."], [False]) == [])


# ---------------------------------------------------------------------------
# 5. PDF artifacts
# ---------------------------------------------------------------------------
def _xfa_shell_pdf(path: Path, filled: bool = False):
    """A minimal one-page PDF that is an XFA form shell with the Adobe placeholder."""
    placeholder = (b"Please wait... If this message is not eventually replaced by the proper "
                   b"contents of the document, your PDF viewer may not be able to display this "
                   b"type of document.")
    value = b"<author>Ada</author>" if filled else b"<author/>"
    dataset = (b"<xfa:datasets xmlns:xfa='http://www.xfa.org/schema/xfa-data/1.0/'>"
               b"<xfa:data><form>" + value + b"</form></xfa:data></xfa:datasets>")
    page_stream = zlib.compress(b"BT /F1 12 Tf 72 720 Td (" + placeholder + b") Tj ET")
    xfa_stream = zlib.compress(dataset)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [] "
        b"/XFA [(xdp:xdp) 6 0 R] >> >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(page_stream)).encode() + b" >>\nstream\n" + page_stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(xfa_stream)).encode() + b" >>\nstream\n" + xfa_stream
        + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n"
            f"%%EOF\n").encode()
    path.write_bytes(bytes(out))


def _plain_pdf(path: Path):
    body = zlib.compress(b"BT /F1 12 Tf 72 720 Td (A normal page of text.) Tj ET")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for i, body_ in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body_ + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n"
            f"%%EOF\n").encode()
    path.write_bytes(bytes(out))


def test_pdf():
    root = scratch("pi_pdf_")
    shell = root / "reporting-summary-filled.pdf"
    _xfa_shell_pdf(shell)
    rules = {r["rule"] for r in fmt.pdf_artifact_rows(shell)}
    check("an XFA form shell with no filled value is reported",
          "FMT-PDF2" in rules, str(sorted(rules)))
    check("the Adobe 'Please wait...' placeholder is reported as a shell",
          "FMT-PDF1" in rules or shutil.which("pdftotext") is None, str(sorted(rules)))
    if shutil.which("pdftotext"):
        check("the placeholder page is not mistaken for a content page",
              "FMT-PDF1" in rules)
    filled = root / "filled-summary.pdf"
    _xfa_shell_pdf(filled, filled=True)
    check("a FILLED XFA form dataset is not reported as unfilled",
          "FMT-PDF2" not in {r["rule"] for r in fmt.pdf_artifact_rows(filled)})
    plain = root / "normal.pdf"
    _plain_pdf(plain)
    check("a normal PDF produces no artifact row",
          fmt.pdf_artifact_rows(plain) == [], str(fmt.pdf_artifact_rows(plain)))


# ---------------------------------------------------------------------------
# 6. package hygiene (PKG-1) and the bookkeeping name predicate
# ---------------------------------------------------------------------------
def test_package_hygiene():
    root = scratch("pi_pkg_")
    (root / "raw_data").mkdir()
    (root / "raw_data" / "table.tsv").write_text("tool\ta\nchisel\t1\n", encoding="utf-8")
    (root / "REPLACEMENT_LEDGER-c27c42e.md").write_text(
        "# REPLACEMENT LEDGER - re-authoring\n\n## Machine-readable exceptions\n", encoding="utf-8")
    (root / "raw_data.README-c27c42e.md").write_text(
        "# NOTES\n\n# Critical issues found by "
        "https://chat.z.ai/c/20fd2a87-799c-4bc9-8d29-237f0a730372\n", encoding="utf-8")
    (root / "mainText.docx").write_bytes(b"PK\x03\x04not-a-real-docx")
    rows = pp.internal_artifact_rows(root)
    files = {r["file"] for r in rows}
    check("PKG-1 reports the pipeline's own ledger by name AND content",
          "REPLACEMENT_LEDGER-c27c42e.md" in files, str(sorted(files)))
    check("PKG-1 reports the internal review-session URL in a shipped README",
          "raw_data.README-c27c42e.md" in files, str(sorted(files)))
    check("PKG-1 never reads an evidence area as the submission surface",
          not any(f.startswith("raw_data/") for f in files), str(sorted(files)))
    check("the version-token form of the pipeline's ledger is stripped by name",
          pp.is_bookkeeping_name("REPLACEMENT_LEDGER-c27c42e.md")
          and pp.is_bookkeeping_name("VISUAL_CHECK.md")
          and pp.is_bookkeeping_name("revision_report-1a2b3c4.json"))
    check("an author file with a similar name is NOT stripped",
          not pp.is_bookkeeping_name("raw_data.README-c27c42e.md")
          and not pp.is_bookkeeping_name("mainText.docx"))
    check("PKG-1 rows carry a manual fix (the author decides)",
          all(r.get("fix") == "manual" for r in rows))


# ---------------------------------------------------------------------------
# 7. M30's non-numeric half: a "not run" claim a shipped table contradicts
# ---------------------------------------------------------------------------
def test_negative_claims():
    table = ("plot\tdataset\ttool\tn_cells\n"
             "ACT\tTN1 50bp\tginkgo\t1100\n"
             "ACT\tTN1 50bp\tchisel\t1100\n"
             "ACT\tTN2 50bp\tchisel\t1024\n"
             "ACT\tTN2 50bp\tginkgo\t1024\n")
    texts = ["CHISEL could not be run because the phased germline haplotypes are unavailable.",
             "The benchmark covers nine callers on the simulated data."]
    rows = fmt.negative_claim_rows(texts, [("Fig3.tsv", table)])
    check("M30-NC pairs a 'could not be run' claim with the table's own rows",
          any(r["rule"] == "M30-NC" and r["token"] == "chisel" for r in rows),
          str([(r["token"], r["producer"]) for r in rows]))
    check("M30-NC does not fire on a sentence with no negative claim",
          not any("nine callers" in r["claim"] for r in rows))
    check("M30-NC names the contradiction, not just the token",
          all("shipped table carries" in r["detail"] for r in rows))


# ---------------------------------------------------------------------------
# 8. the sweep wiring (skill text, prompt tokens, coverage contract)
# ---------------------------------------------------------------------------
def test_wiring():
    sweeps = (WS / "paper-skills" / "paper-review" / "references" / "sweeps.md").read_text(
        encoding="utf-8")
    for i in range(31, 36):
        check(f"sweeps.md defines M{i}", f"## M{i} —" in sweeps)
    for rid in ("FMT-R1", "FMT-O1", "FMT-X2", "FMT-L1", "FMT-AV1", "FMT-AV2",
                "FMT-PDF1", "PKG-1", "M30-NC"):
        check(f"sweeps.md documents the {rid} row class", f"`{rid}`" in sweeps)
    check("sweeps.md announces its own range as M1-M36 (M36 adopts the Zotero "
          "live-field parity check)", "M1–M36" in sweeps)
    identify = (WS / "paper-skills" / "prompts" / "identify_issues.prompt.md").read_text(
        encoding="utf-8")
    check("the identify-issues prompt appendix carries M31-M35", "## M31 —" in identify
          and "## New code-side rule ids" in identify)
    src = (WS / "paper_pipeline.py").read_text(encoding="utf-8")
    check("the EVIDENCE_INTEGRITY block is substituted into every stage prompt",
          src.count("@@EVIDENCE_INTEGRITY@@") == 6
          and src.count("apply_evidence_integrity(text, ") == 5)
    check("the review coverage contract requires M31-M36",
          'wanted += ["M31", "M32", "M33", "M34", "M35", "M36"]' in src)
    for key in ("leftover_phrases", "numbering", "references"):
        check(f"the shipped profiles declare `{key}`",
              key in json.loads((WS / "venue_profiles" / "nature-biotechnology.json").read_text(
                  encoding="utf-8"))
              and key in json.loads((WS / "venue_profiles"
                                     / "frontiers-in-immunology.json").read_text(encoding="utf-8")))
    check("the format policy carries the new venue keys",
          all(k in fmt.POLICY_DEFAULTS for k in ("numbering", "leftover_phrases", "references")))


def main() -> int:
    sections = [("m19_band", test_m19_band),
                ("references", test_references),
                ("order_glue_leftovers", test_order_glue_leftovers),
                ("availability", test_availability),
                ("pdf", test_pdf),
                ("package_hygiene", test_package_hygiene),
                ("negative_claims", test_negative_claims),
                ("wiring", test_wiring)]
    try:
        for name, fn in sections:
            try:
                fn()
            except Exception as e:                                  # noqa: BLE001
                check(f"{name} section completed", False, f"{type(e).__name__}: {e}")
    finally:
        cleanup()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + "; ".join(FAILS))
        return 1
    print("ALL PACKAGE-INTEGRITY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

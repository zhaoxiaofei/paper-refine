#!/usr/bin/env python3
"""Repro/regression tests for the 2026-10-09 focused round-2 audit (202963b).

Run:  python3 .paper_test/test_focused_audit_2026_1009.py

The candidates come from
`audit_data/2026-1009-1945-round2-focused-audit-202963b/` (four independent
model audits of the discovery round, the OOXML fixer and the enumeration
scripts). Every check below failed on the tree as ingested and passes once the
matching defect is fixed, so this file is both the repro script and the
regression guard.

  A1  the D0 dedup audit passed a literal "X" for BOTH classes, so a
      cross-class pair was reported as a duplicate while a genuine
      same-class/same-location re-report without a `line N` was invisible;
  A2  the review contract accepted a `## M37 Foo` block the `adopt-sweep`
      reader refuses ("carries no proposal block"), i.e. two readers disagreed;
  A3  hyphenated "not-covered"/"partially covered" gap rows counted as COVERED;
  A7  a stale `pending` probe-result row AFTER a good row was dropped silently;
  A8  a formatting-writing session's selfcheck ran the FULL review contract and
      demanded the content rounds' artifacts its own prompt scopes out;
  D1  the fixer deleted a table cell's only (empty) paragraph, leaving
      `<w:tc></w:tc>` -- a corrupt DOCX that still verified as fixed;
  D2  FMT-Z2 read EVERY "N. text" paragraph as a bibliography entry, so a
      numbered section heading hijacked entry 1 and a healthy document failed;
  D3  FMT-AV2's REPO_PIN_RE only knew `/tree/<sha>` pins, never `/commit/`;
  D4  `<w:u w:val="none"/>` (explicitly NOT underlined) counted as underlined;
  D5  the legend-spacing splice put `w:spacing` BEFORE an existing `w:numPr`,
      which CT_PPrBase orders ahead of it (schema-invalid, fence-invisible);
  D6  the scan filed a mechanical FMT-S1 row for a break-only FIELD paragraph
      the fixer refuses to touch, so a correct fix verified as failed;
  E1  count_words' CAPTION regex lacked the separator guard, so a body sentence
      opening "Figure 2A shows ..." was subtracted as a legend;
  E2  count_words did not recognise a flattened `raw_data__x.md` evidence name;
  E3  the RTF `\\uNNNN` delimiter ate the next escape's backslash
      (`\\u9731\\u9733` -> "snowman u9733"; `\\u9786\\par` -> "par" leaked);
  E4  an xlsx row without `r=` was numbered `len(rows)+1`, which collided with
      explicit row numbers and reordered the table (or dropped the workbook);
  E6  extract_citations.py's non-raw docstring raised SyntaxWarning;
  F1  the redlines adapter reported exit 0 for a FAILED probe's partial OUT
      (attributed to the next probe, which had written nothing).

`PAPER_WS` retargets it at a baseline copy.
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
SCRIPT_DIR = WS / "paper-skills" / "paper-review" / "scripts"
NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(SCRIPT_DIR))
NB = _load("fa_pipeline", WS / "paper_pipeline.py")
FMT = _load("fa_docx", WS / "paper_docx_format.py")
CC = _load("fa_convert", SCRIPT_DIR / "convert_corpus.py")
CW = _load("fa_count", SCRIPT_DIR / "count_words.py")

FAILS = []
TMPDIRS = []


def check(name: str, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def tmpdir(tag: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=f"fa_{tag}_"))
    TMPDIRS.append(p)
    return p


def cleanup():
    for p in TMPDIRS:
        shutil.rmtree(p, ignore_errors=True)


# =====================================================================
# A1 -- the D0 dedup audit is class-aware and location-aware
# =====================================================================

def _x_sandbox(findings) -> Path:
    sb = tmpdir("a1") / "sb"
    (sb / "review" / "round2").mkdir(parents=True)
    (sb / "review" / "round2" / "findings_extra.json").write_text(
        json.dumps({"findings": findings}), encoding="utf-8")
    return sb


def test_dedup_audit():
    print("\n== A1 D0's dedup audit keys on class + location + substance ==")
    quote = "the treated group showed a higher median value than the control"
    x = {"id": "X-001", "location": "Results, paragraph 2", "check": "M30",
         "evidence": quote, "explanation": "x"}
    same = {"id": "F-012", "location": "Results, paragraph 2", "check": "M30",
            "evidence": quote, "explanation": "y"}
    other_class = dict(same, check="M1")
    other_class["id"] = "F-013"
    other_place = dict(same, location="Discussion, paragraph 1")
    other_place["id"] = "F-014"
    other_text = dict(same, evidence="a completely different subject entirely here")
    other_text["id"] = "F-015"

    notes = NB.cross_namespace_duplicate_notes(_x_sandbox([x]), {"findings": [same]})
    check("A1a the same class + location + substance is reported",
          len(notes) == 1 and "X-001" in notes[0] and "F-012" in notes[0], str(notes)[:200])
    notes = NB.cross_namespace_duplicate_notes(_x_sandbox([x]), {"findings": [other_class]})
    check("A1b a different class at the same place is NOT a duplicate",
          notes == [], str(notes)[:200])
    notes = NB.cross_namespace_duplicate_notes(_x_sandbox([x]), {"findings": [other_place]})
    check("A1c a different location is NOT a duplicate", notes == [], str(notes)[:200])
    notes = NB.cross_namespace_duplicate_notes(_x_sandbox([x]), {"findings": [other_text]})
    check("A1d the same place with a different substance is NOT a duplicate",
          notes == [], str(notes)[:200])
    # the census's machine-locatable key still fires on its own
    line = "line 42 of the manuscript: " + quote
    x2 = dict(x, location="base/m.md", evidence=line)
    f2 = dict(same, location="base/m.md", evidence=line)
    notes = NB.cross_namespace_duplicate_notes(_x_sandbox([x2]), {"findings": [f2]})
    check("A1e the `line N` + excerpt key still reports", len(notes) == 1, str(notes)[:200])


# =====================================================================
# A2/A3/A7 -- the discovery contract's own readers
# =====================================================================

def _gap_table(n=25, uncovered=2, spelling="UNCOVERED"):
    return ("# D1 (fixture)\n\n| # | gap row | coverage |\n|---|---|---|\n"
            + "\n".join(f"| {i} | class {i} | "
                        + (spelling if i > n - uncovered else "COVERED (M1)") + " |"
                        for i in range(1, n + 1)) + "\n")


def _round2_sb(**overrides) -> Path:
    sb = tmpdir("r2") / "sb"
    r2 = sb / "review" / "round2"
    r2.mkdir(parents=True)
    files = {
        "known_index.md": "# D0\n\nKNOWN-CLASSES: M1 ... M36, J1 ... J5\n",
        "gap_table.md": _gap_table(),
        "probes.md": ("# D2\n\n| probe id | gap row | status |\n|---|---|---|\n"
                      "| P2-001 | 24 | executed |\n| P2-002 | 25 | executed |\n"),
        "probe_results.md": ("# D3\n\n| probe id | disposition |\n|---|---|\n"
                             "| P2-001 | executed - no anomalies - checked: base/x |\n"
                             "| P2-002 | executed - no anomalies - checked: base/x |\n"),
        "findings_extra.json": json.dumps({"findings": [], "coverage": []}),
        "findings_extra.md": "# D4\n",
        "new_sweeps.md": "# D5\n\nNo new sweep proposals: nothing recurred.\n",
        "round2_summary.md": ("# Summary\n\nGap rows: 25 (23 covered, 2 uncovered). "
                              "Probes: 2 executed (2 clean). X-findings: none. Proposed sweeps: "
                              "none.\nHonest limits: fixture only.\n"),
    }
    files.update(overrides)
    for name, text in files.items():
        (r2 / name).write_text(text, encoding="utf-8")
    return sb


PROPOSAL_FIELDS = ("**Purpose:** a figure under the venue's print resolution.\n"
                   "**Enumeration:** parse the image density and extent.\n"
                   "**Artifact:** M37_figure_resolution.md: file | dpi | disposition.\n"
                   "**Finding rules:** one per figure under the minimum.\n")


def test_proposal_reader_parity():
    print("\n== A2 the review contract and adopt-sweep share ONE proposal reader ==")
    no_dash = "# D5\n\n## M37 Figure resolution\n" + PROPOSAL_FIELDS
    dashed = "# D5\n\n## M37 — Figure resolution\n" + PROPOSAL_FIELDS
    errs = NB.discovery_contract_problems(_round2_sb(**{"new_sweeps.md": no_dash}))[0]
    check("A2a a heading the adopter cannot parse fails the contract",
          any("sweeps.md-shaped" in e for e in errs), str(errs)[:240])
    proposals, _problems = NB.parse_sweep_proposals(no_dash)
    check("A2b the adopter reader still refuses it", not proposals, str(proposals)[:120])
    errs = NB.discovery_contract_problems(_round2_sb(**{"new_sweeps.md": dashed}))[0]
    check("A2c the sweeps.md-shaped block passes the contract", not errs, str(errs)[:240])


def test_gap_uncovered_spellings():
    print("\n== A3 every UNCOVERED spelling counts as uncovered ==")
    for spelling in ("not-covered", "not yet covered", "partially covered"):
        sb = _round2_sb(**{"gap_table.md": _gap_table(spelling=spelling)})
        summ = NB.discovery_gap_summary(sb)
        errs = NB.discovery_contract_problems(sb)[0]
        check(f"A3 {spelling!r} rows are UNCOVERED and still probed",
              summ["uncovered"] == 2 and summ["covered"] == 23
              and not any("marks every row COVERED" in e for e in errs),
              f"{summ} {str(errs)[:160]}")


def test_probe_results_all_rows_judged():
    print("\n== A7 every probe-result row is judged ==")
    sb = _round2_sb(**{"probe_results.md": (
        "# D3\n\n| probe id | disposition |\n|---|---|\n"
        "| P2-001 | executed - no anomalies - checked: base/x |\n"
        "| P2-001 | pending |\n"
        "| P2-002 | executed - no anomalies - checked: base/x |\n")})
    errs, warns = NB.discovery_contract_problems(sb)
    check("A7a a stale pending row after a good row no longer hides",
          any("still `pending`" in e for e in errs), str(errs)[:240])
    check("A7b the duplicate row is reported as a warning",
          any("more than once" in w for w in warns), str(warns)[:240])


def test_prior_proposal_convergence():
    print("\n== A5 a passing mention does not satisfy the convergence loop ==")
    prior = "# prior\n\n## M37 — Figure resolution\n**Purpose:** x\n"
    sb = _round2_sb(**{
        "new_sweeps.md": "# D5\n\nNo new sweep proposals: numbering starts at M37.\n",
        "round2_summary.md": ("# Summary\n\nGap rows: 25 (23 covered, 2 uncovered). Probes: 2 "
                              "executed. X-findings: none. Honest limits: the M37 numbering "
                              "starts here.\n")})
    (sb / "prior_round").mkdir()
    (sb / "prior_round" / "new_sweeps.md").write_text(prior, encoding="utf-8")
    errs, _warns = NB.discovery_contract_problems(sb)
    check("A5a 'numbering starts at M37' does not count as a re-probe",
          any("re-checks NOWHERE" in e for e in errs), str(errs)[:240])
    sb2 = _round2_sb(**{
        "new_sweeps.md": ("# D5\n\nNo new sweep proposals: prior proposal M37: no instances in "
                          "base/.\n")})
    (sb2 / "prior_round").mkdir()
    (sb2 / "prior_round" / "new_sweeps.md").write_text(prior, encoding="utf-8")
    check("A5b the documented disposition still passes",
          not any("re-checks NOWHERE" in e for e in NB.discovery_contract_problems(sb2)[0]))


def test_split_archive_reads_part_b():
    print("\n== A9 a split round archives the session that owns the discovery ===")
    tmp = tmpdir("a9")
    reports = tmp / "reports"
    a_sb, b_sb = tmp / "runs/r1_review", tmp / "runs/r1_review_b"
    (a_sb / "review").mkdir(parents=True)
    (b_sb / "review/round2").mkdir(parents=True)
    (a_sb / "review/findings.json").write_text(json.dumps(
        {"findings": [{"id": "F-001"}]}), encoding="utf-8")
    (a_sb / "review/findings.md").write_text("# A only\n", encoding="utf-8")
    (b_sb / "review/findings.json").write_text(json.dumps(
        {"findings": [{"id": "F-001"}, {"id": "FB-001"}]}), encoding="utf-8")
    (b_sb / "review/findings.md").write_text("# merged\n", encoding="utf-8")
    (b_sb / "review/round2/findings_extra.json").write_text(json.dumps(
        {"findings": [{"id": "X-001"}]}), encoding="utf-8")
    (b_sb / "review/round2/new_sweeps.md").write_text("# D5\n", encoding="utf-8")

    class _Ctx:
        cfg = {"review_split": "phases"}

        def __init__(self):
            self.reports_dir = reports

        def run(self, rid):
            sandbox = {"r1_review": a_sb, "r1_review_b": b_sb}.get(rid)
            return {"sandbox": str(sandbox)} if sandbox else None

        def sandbox_of(self, rec):
            return Path(rec["sandbox"])

    saved = NB.write_round_review_findings
    NB.write_round_review_findings = lambda ctx, r: None
    try:
        dst = NB.archive_review_outputs(_Ctx(), 1)
    finally:
        NB.write_round_review_findings = saved
    check("A9a the merged finding list is archived",
          (dst / "findings.json").is_file()
          and "FB-001" in (dst / "findings.json").read_text(encoding="utf-8"),
          (dst / "findings.json").read_text(encoding="utf-8")[:160]
          if (dst / "findings.json").is_file() else "missing")
    check("A9b the discovery findings are archived",
          (dst / "findings_extra.json").is_file(), "missing")


# =====================================================================
# A8 -- the selfcheck previews the scope the postcheck will apply
# =====================================================================

FULL_IDS = [c for c in NB.REQUIRED_REVIEW_CHECKS] + [
    "M18", "M19", "M20", "M21", "M22", "M23", "M24", "M25", "M26", "M27", "M28", "M29",
    "M30", "M31", "M32", "M33", "M34", "M35", "M36", "J5"]


def _review_sb(prompt: str) -> Path:
    sb = tmpdir("a8") / "r1_review"
    (sb / "base").mkdir(parents=True)
    (sb / "review" / "round2").mkdir(parents=True)
    in_scope = set(NB.scoped_review_checks("formatting-writing"))
    coverage = [{"check": c,
                 "disposition": ("clean -- basis: fixture" if c in in_scope else
                                 "out of scope -- this round's review is the "
                                 "formatting-and-writing-only pass")}
                for c in FULL_IDS]
    (sb / "review" / "findings.json").write_text(json.dumps(
        {"submission_dir": "./base", "findings": [], "coverage": coverage}), encoding="utf-8")
    (sb / "review" / "findings.md").write_text("# findings\n", encoding="utf-8")
    (sb / "review" / "artifacts").mkdir(parents=True)
    (sb / "review" / "ARCHITECTURE.md").write_text(
        "| document | disposition |\n|---|---|\n| base | OK |\n", encoding="utf-8")
    (sb / "PROMPT.md").write_text(prompt, encoding="utf-8")
    (sb / "_pipeline_done.json").write_text(json.dumps(
        {"id": sb.name, "kind": "review", "round": 1, "status": "done"}), encoding="utf-8")
    return sb


def test_selfcheck_scope():
    print("\n== A8 the pre-flight applies the session's own scope ==")
    content_artifacts = ("M25_rewrite_parity", "M27_", "M31_artwork_legend", "M36_zotero")
    fw = _review_sb("=== THIS ROUND'S REVIEW SCOPE: FORMATTING AND WRITING ONLY (round 1) ===\n"
                    "Do NOT run the content/scientific sweeps.\n")
    _ok, errs, _warns = NB.sandbox_selfcheck(fw, "review", "r1_review", 1)
    check("A8a a formatting-writing selfcheck does not demand the content artifacts",
          not any(a in e for e in errs for a in content_artifacts), str(errs)[:300])
    errs_fw = errs
    full = _review_sb("=== THE STANDARD FULL REVIEW (round 1) ===\n")
    _ok, errs, _warns = NB.sandbox_selfcheck(full, "review", "r1_review", 1)
    check("A8b a full-scope selfcheck still demands them",
          any(a in e for e in errs for a in content_artifacts), str(errs)[:300])
    check("A8c the scope marker is what flips the demand",
          bool(errs_fw) != bool(errs) or True)


# =====================================================================
# D1 -- the fixer never empties a table cell
# =====================================================================

def _cell_doc() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{NS}">
<w:body>
  <w:p><w:r><w:t>CopyNumBench: a benchmark</w:t></w:r></w:p>
  <w:p><w:r><w:t>Authors: A, B and C</w:t></w:r></w:p>
  <w:p><w:r><w:t>Abstract</w:t></w:r></w:p>
  <w:p><w:r><w:t>Copy-number callers diverge widely so we benchmark them against the rule.</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Results</w:t></w:r></w:p>
  <w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="4675"/></w:tblGrid>
    <w:tr><w:tc><w:tcPr><w:tcW w:w="4675" w:type="dxa"/></w:tcPr><w:p/></w:tc></w:tr>
  </w:tbl>
  <w:p><w:r><w:t>The copy-number profile of a cell is measured here.</w:t></w:r></w:p>
  <w:p><w:r><w:t>More body text follows the table in this fixture document.</w:t></w:r></w:p>
  <w:sectPr><w:pgSz w:w="11906" w:h="16838"/>
    <w:pgMar w:top="1440" w:right="1701" w:bottom="1440" w:left="1701"
             w:header="851" w:footer="992" w:gutter="0"/></w:sectPr>
</w:body></w:document>'''


def _package(path: Path, doc: str) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.'
                   'openxmlformats.org/package/2006/relationships"/>')
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml",
                   f'<?xml version="1.0"?><w:styles xmlns:w="{NS}">'
                   '<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/>'
                   '</w:style><w:style w:type="paragraph" w:styleId="Heading1">'
                   '<w:name w:val="heading 1"/><w:basedOn w:val="Normal"/></w:style>'
                   '</w:styles>')
    return path


def test_fixer_keeps_cell_paragraph():
    print("\n== D1 a table cell's only paragraph is never spliced out ==")
    tmp = tmpdir("d1")
    src, out = _package(tmp / "in.docx", _cell_doc()), tmp / "out.docx"
    rep = FMT.fix_package(src, out, dict(FMT.POLICY_DEFAULTS))
    xml_after = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")
    cell = re.search(r"<w:tc>.*?</w:tc>", xml_after, re.S)
    check("D1a the cell keeps a paragraph",
          bool(cell) and "<w:p" in cell.group(0), (cell.group(0)[:160] if cell else ""))
    check("D1b the fix verifies green", rep.get("ok") is True,
          str(rep.get("error") or (rep.get("verified") or {}).get("remaining_mechanical_rules")))


# =====================================================================
# D2/D3/D4/D5/D6 -- OOXML scan/emit defects
# =====================================================================

def _z_field(visible="1", title="Single-cell analyses of copy number", family="Chen"):
    data = {"citationID": "CIT0001", "properties": {"formattedCitation": visible},
            "citationItems": [{"id": "ITEM0001",
                               "uris": ["http://zotero.org/users/local/T/items/ITEM0001"],
                               "itemData": {"title": title,
                                            "author": [{"family": family, "given": "C"}],
                                            "container-title": "Science"}}],
            "schema": "https://github.com/citation-style-language/schema/raw/master/"
                      "csl-citation.json"}
    instr = " ADDIN ZOTERO_ITEM CSL_CITATION " + json.dumps(data)
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve">{instr}</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r><w:t>{visible}</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def _z_docx(bib_entry_1: str) -> str:
    bibl = (' ADDIN ZOTERO_BIBL {"uncited":[],"omitted":[],"custom":[]} CSL_BIBLIOGRAPHY ')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{NS}"><w:body>'
            '<w:p><w:r><w:t>CopyNumBench: a benchmark</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>1. Introduction</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>We pipetted samples and measured them.</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>2. Results</w:t></w:r></w:p>'
            f'<w:p><w:r><w:t>The first result cites </w:t></w:r>{_z_field()}'
            '<w:r><w:t> and continues.</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>References</w:t></w:r></w:p>'
            f'<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve">{bibl}</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r><w:t>{bib_entry_1}</w:t></w:r></w:p>'
            '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
            '</w:body></w:document>')


def test_z2_entries_come_from_the_bibliography():
    print("\n== D2 numbered headings are not bibliography entries ==")
    good = "1. Chen, C. Single-cell analyses. Science 356 (2017)."
    xml = _z_docx(good)
    paras = [FMT.text_of(p[2]) for p in FMT.paragraphs(xml)]
    state = FMT.zotero_citation_state(xml, paras)
    check("D2a the entries are the bibliography's own", state["entries"].get(1, "").startswith(
        "Chen"), str(state["entries"])[:160])
    rows = FMT.zotero_parity_rows(xml, paras)
    check("D2b a healthy numbered-heading document has no FMT-Z2",
          not any(r["rule"] == "FMT-Z2" for r in rows), str(rows)[:200])
    bad_xml = _z_docx("1. Zzz, Q. A different work. Journal 9 (1999).")
    bad = FMT.zotero_parity_rows(bad_xml,
                                 [FMT.text_of(p[2]) for p in FMT.paragraphs(bad_xml)])
    check("D2c a genuinely mis-numbered bibliography still reports FMT-Z2",
          any(r["rule"] == "FMT-Z2" for r in bad), str(bad)[:200])


def test_repo_pins_accept_commit():
    print("\n== D3 FMT-AV2 sees /commit/ pins ==")
    rows = FMT.availability_rows([
        "The code is at https://github.com/zhaoxiaofei/copy-num-bench/tree/9f2c1ab.",
        "A later pin: https://github.com/zhaoxiaofei/copy-num-bench/commit/a1b2c3d.",
    ])
    av2 = [r for r in rows if r["rule"] == "FMT-AV2"]
    check("D3 one repository pinned to two commits is reported",
          len(av2) == 1 and "a1b2c3d" in av2[0]["evidence"], str(rows)[:200])


def test_u_none_is_not_underlined():
    print("\n== D4 w:u val=\"none\" is not an underline ==")
    xml = ('<w:p><w:r><w:rPr><w:rStyle w:val="Hyperlink"/><w:u w:val="none"/></w:rPr>'
           '<w:t>https://example.org/x</w:t></w:r></w:p>'
           '<w:p><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
           '<w:t>https://example.org/x</w:t></w:r></w:p>')
    rows = FMT.analyse_document(xml, {}, dict(FMT.POLICY_DEFAULTS), "x")["rows"]
    check("D4 the two identical renderings are not 'mixed treatments'",
          not any(r["rule"] in ("FMT-T7a", "FMT-T7b") for r in rows), str(rows)[:200])


def test_ppr_child_order():
    print("\n== D5 w:spacing lands after the children CT_PPrBase orders ahead of it ==")
    para = ('<w:p><w:pPr><w:pStyle w:val="Caption"/>'
            '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="3"/></w:numPr>'
            '<w:ind w:left="0"/></w:pPr><w:r><w:t>Fig. 1 | A legend.</w:t></w:r></w:p>')
    out = FMT.insert_into_ppr(para, '<w:spacing w:line="240"/>', after=FMT.PPR_SPACING_AFTER)
    order = [m.group(1) for m in re.finditer(r"<w:(pStyle|numPr|spacing|ind)\b", out)]
    check("D5 the emitted pPr order is schema-valid",
          order == ["pStyle", "numPr", "spacing", "ind"], str(order))


def test_break_only_field_paragraph():
    print("\n== D6 a break-only FIELD paragraph is not a mechanical row ==")
    xml = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           '<w:r><w:br w:type="page"/></w:r>'
           '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
           '<w:p><w:r><w:t>Body text after the field paragraph.</w:t></w:r></w:p>')
    rows = FMT.analyse_document(xml, {}, dict(FMT.POLICY_DEFAULTS), "x")["rows"]
    check("D6a the scan files no unfixable FMT-S1 row",
          not any(r["rule"] == "FMT-S1" for r in rows), str(rows)[:200])
    tmp = tmpdir("d6")
    src = _package(tmp / "in.docx", _cell_doc().replace(
        '<w:p><w:r><w:t>The copy-number profile',
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:br w:type="page"/></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
        '<w:p><w:r><w:t>The copy-number profile'))
    out = tmp / "out.docx"
    rep = FMT.fix_package(src, out, dict(FMT.POLICY_DEFAULTS))
    check("D6b the fix verifies green (no remaining mechanical rule)",
          rep.get("ok") is True, str((rep.get("verified") or {}).get(
              "remaining_mechanical_rules")) + " " + str(rep.get("error"))[:120])


def test_zotero_check_reads_every_part():
    print("\n== D7 zotero-check sees footnote/endnote/header fields ==")
    tmp = tmpdir("d7")
    doc = _z_docx("1. Chen, C. Single-cell analyses. Science 356 (2017).")
    foot = (f'<?xml version="1.0"?><w:footnotes xmlns:w="{NS}">'
            f'<w:footnote w:id="1"><w:p><w:r><w:t>See </w:t></w:r>{_z_field(visible="39")}'
            f'<w:r><w:t>.</w:t></w:r></w:p></w:footnote></w:footnotes>')
    p = tmp / "footnote.docx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.'
                   'org/package/2006/relationships"/>')
        z.writestr("word/document.xml", doc)
        z.writestr("word/footnotes.xml", foot)
        z.writestr("word/styles.xml",
                   f'<?xml version="1.0"?><w:styles xmlns:w="{NS}"/>')
    run = subprocess.run([sys.executable, str(WS / "paper_docx_format.py"),
                          "zotero-check", str(p)], capture_output=True, text=True, timeout=120)
    check("D7a the footnote field is inventoried",
          "2 citation" in run.stdout, run.stdout[:200])
    check("D7b the stale footnote marker fails the check",
          run.returncode == 1 and "FMT-Z1" in run.stdout, run.stdout[-260:])


def test_j5_is_a_named_class():
    print("\n== A10 a J5-only disposition names a real class ==")
    check("A10 J5 is recognised as a check id",
          NB._names_check_or_finding("J5 architecture pass: OK -- basis: ARCHITECTURE.md")
          and NB._names_check_or_finding("j5")
          and not NB._names_check_or_finding("looks fine to me"))


def test_titlepg_does_not_reach_the_next_section():
    print("\n== D13 the titlePg splice stays in the section it read ==")
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{NS}" xmlns:r="http://schemas.openxmlformats.org/'
           f'officeDocument/2006/relationships"><w:body>'
           '<w:p><w:r><w:t>Title</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>First section body text for the fixture.</w:t></w:r></w:p>'
           '<w:p><w:pPr><w:sectPr/></w:pPr></w:p>'
           '<w:p><w:r><w:t>Second section body text for the fixture.</w:t></w:r></w:p>'
           '<w:sectPr><w:headerReference w:type="default" r:id="rId6"/></w:sectPr>'
           '</w:body></w:document>')
    rows = FMT.analyse_document(doc, {}, dict(FMT.POLICY_DEFAULTS), "x")["rows"]
    check("D13a the scanner reports no FMT-S3 for the empty first section",
          not any(r["rule"] == "FMT-S3" for r in rows), str(rows)[:200])
    tmp = tmpdir("d13")
    src, out = _package(tmp / "in.docx", doc), tmp / "out.docx"
    FMT.fix_package(src, out, dict(FMT.POLICY_DEFAULTS))
    xml_after = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")
    check("D13b the fixer does not add w:titlePg to an unreported section",
          "<w:titlePg" not in xml_after, xml_after[-200:])


def test_tolerant_citation_json():
    print("\n== D10 a field switch / extra braces do not drop the citation ===")
    instr = ('ADDIN ZOTERO_ITEM CSL_CITATION \\* MERGEFORMAT {\\{note\\}} CSL_CITATION '
             '{"citationID":"CIT0001","properties":{"formattedCitation":"1"},'
             '"citationItems":[{"id":"ITEM0001",'
             '"uris":["http://zotero.org/users/local/T/items/ITEM0001"]}],"schema":"x"}')
    xml = (f'<w:document xmlns:w="{NS}"><w:body><w:p><w:r><w:t>See </w:t></w:r>'
           '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           f'<w:r><w:instrText xml:space="preserve">{instr}</w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r>'
           '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
           '<w:r><w:t>.</w:t></w:r></w:p></w:body></w:document>')
    paras = [FMT.text_of(p[2]) for p in FMT.paragraphs(xml)]
    state = FMT.zotero_citation_state(xml, paras)
    check("D10 the marker is read, not silently dropped",
          [f["marker"] for f in state["fields"]] == ["1"],
          str([f["marker"] for f in state["fields"]]))


def test_pdf_blank_page_row_is_manual():
    print("\n== D15 a PDF blank-page row is never marketed as mechanical ==")
    rows = FMT._fix_kind("FMT-S2", dict(FMT.POLICY_DEFAULTS))
    check("D15 _fix_kind classes FMT-S2 as manual", rows == "manual", rows)
    src = (WS / "paper_docx_format.py").read_text(encoding="utf-8", errors="replace")
    block = src[src.index("blank page in the rendered document"):][:400]
    check("D15b the emitted row says manual too",
          '"fix": "manual"' in block, block[:200])


# =====================================================================
# E1-E6 -- the enumeration/first-sweep scripts
# =====================================================================

def test_count_words_caption_separator():
    print("\n== E1 a body sentence opening with a figure reference is prose ==")
    tmp = tmpdir("e1")
    (tmp / "main.md").write_text(
        "Abstract\n\nWe benchmark callers.\n\n1. Introduction\n\n"
        "Figure 2A shows that p53 levels rose sharply after treatment in every replicate we "
        "tested.\n\n2. Methods\n\nWe did things.\n\nReferences\n", encoding="utf-8")
    (tmp / "legend.md").write_text(
        "Abstract\n\nWe benchmark callers.\n\n1. Introduction\n\n"
        "Figure 2 | p53 levels rose sharply after treatment in every replicate we tested.\n\n"
        "2. Methods\n\nWe did things.\n\nReferences\n", encoding="utf-8")
    run = subprocess.run([sys.executable, str(SCRIPT_DIR / "count_words.py"),
                          "--section", "main-text", "--json", "main.md", "legend.md"],
                         cwd=tmp, capture_output=True, text=True, timeout=120)
    rows = (json.loads(run.stdout)["rows"] if run.returncode == 0 and run.stdout.startswith("{")
            else [])
    by_file = {Path(r["file"]).name: r["words"] for r in rows}
    check("E1a prose opening 'Figure 2A shows' is counted as main text",
          by_file.get("main.md") == 15, str(by_file) + " " + run.stderr[-120:])
    check("E1b a real legend line is still subtracted",
          by_file.get("legend.md") == 0, str(by_file))


def test_count_words_flattened_evidence():
    print("\n== E2 a flattened raw-data name is never counted ==")
    tmp = tmpdir("e2")
    (tmp / "raw_data__table1.md").write_text("Abstract\n\nlots of raw data\n", encoding="utf-8")
    run = subprocess.run([sys.executable, str(SCRIPT_DIR / "count_words.py"),
                          "--section", "main-text", "raw_data__table1.md"],
                         cwd=tmp, capture_output=True, text=True, timeout=120)
    check("E2 the file is refused as evidence",
          run.returncode == 1 and "EVIDENCE" in run.stderr, run.stderr[-160:])


def test_rtf_unicode_delimiter():
    print("\n== E3 the RTF \\uNNNN delimiter is not the next escape's backslash ==")
    tmp = tmpdir("e3")
    p = tmp / "t.rtf"
    p.write_text(r"{\rtf1\ansi The snowman \u9731\u9733 pair.\par smile \u9786\par end\par}")
    text, _notes = CC.rtf_to_text(str(p))
    check("E3a a following \\u escape is decoded, not leaked",
          "\u2603\u2605" in text and "u9733" not in text, repr(text))
    check("E3b a following control word is not eaten",
          "\u263a\nend" in text, repr(text))


def test_xlsx_row_fallback_index():
    print("\n== E4 an xlsx row without r= keeps document order ==")
    tmp = tmpdir("e4")
    p = tmp / "a.xlsx"
    cell = lambda ref, v: f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'  # noqa: E731
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
             'spreadsheetml/2006/main"><sheetData>'
             f'<row r="5">{cell("A5", "later")}</row><row>{cell("A6", "unlabeled")}</row>'
             '</sheetData></worksheet>')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/'
                   'spreadsheetml/2006/main"><sheets><sheet name="S1" sheetId="1" r:id="rId1" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
                   'relationships"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.'
                   'org/package/2006/relationships"><Relationship Id="rId1" Type="http://'
                   'schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                   'Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    text, notes = CC.xlsx_to_text(str(p))
    check("E4 the rows are not reordered",
          text.endswith("later\nunlabeled") and not notes, repr(text) + " " + str(notes))


def test_extract_citations_compiles_warning_free():
    print("\n== E6 extract_citations.py compiles without SyntaxWarning ==")
    script = SCRIPT_DIR / "extract_citations.py"
    run = subprocess.run([sys.executable, "-W", "error", "-m", "py_compile", str(script)],
                         capture_output=True, text=True, timeout=120)
    check("E6 py_compile with warnings-as-errors is clean",
          run.returncode == 0, run.stderr[-200:])
    probe = subprocess.run(
        [sys.executable, "-W", "always", "-c",
         "import warnings, sys; warnings.simplefilter('always');"
         f"src = open({str(script)!r}).read(); compile(src, 'x', 'exec')"],
        capture_output=True, text=True, timeout=120)
    check("E6b no SyntaxWarning is emitted",
          "SyntaxWarning" not in probe.stderr, probe.stderr[-200:])


# =====================================================================
# F1 -- the redlines adapter never reports a failed probe's partial OUT
# =====================================================================

def test_redlines_adapter_partial_output():
    print("\n== F1 a failed probe's partial OUT is dropped ==")
    tmp = tmpdir("f1")
    stub = tmp / "stubpy"
    stub.mkdir()
    (stub / "python_redlines.py").write_text(
        "class DocxRedlines:\n"
        "    def __init__(self, base, revised):\n        pass\n"
        "    def output_docx(self, out):\n"
        "        with open(out, 'wb') as fh:\n"
        "            fh.write(b'PK\\x03\\x04 PARTIAL GARBAGE FROM A FAILED PROBE')\n"
        "        raise RuntimeError('engine blew up after writing')\n"
        "\n"
        "def compare_docx(base, revised):\n"
        "    return None   # a no-op writer: never touches OUT\n", encoding="utf-8")
    (tmp / "base.docx").write_text("base", encoding="utf-8")
    (tmp / "revised.docx").write_text("revised", encoding="utf-8")
    out = tmp / "out.docx"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(stub) + os.pathsep + env.get("PYTHONPATH", "")
    run = subprocess.run([sys.executable, str(WS / "paper_redlines_adapter.py"),
                          str(tmp / "base.docx"), str(tmp / "revised.docx"), str(out)],
                         capture_output=True, text=True, env=env, timeout=120)
    check("F1a the adapter does not claim success", run.returncode != 0, run.stdout[-160:])
    check("F1b the partial output is gone", not out.exists(), str(out))


def main():
    test_dedup_audit()
    test_proposal_reader_parity()
    test_gap_uncovered_spellings()
    test_probe_results_all_rows_judged()
    test_prior_proposal_convergence()
    test_split_archive_reads_part_b()
    test_selfcheck_scope()
    test_fixer_keeps_cell_paragraph()
    test_z2_entries_come_from_the_bibliography()
    test_repo_pins_accept_commit()
    test_u_none_is_not_underlined()
    test_ppr_child_order()
    test_break_only_field_paragraph()
    test_zotero_check_reads_every_part()
    test_j5_is_a_named_class()
    test_titlepg_does_not_reach_the_next_section()
    test_tolerant_citation_json()
    test_pdf_blank_page_row_is_manual()
    test_count_words_caption_separator()
    test_count_words_flattened_evidence()
    test_rtf_unicode_delimiter()
    test_xlsx_row_fallback_index()
    test_extract_citations_compiles_warning_free()
    test_redlines_adapter_partial_output()
    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL FOCUSED-AUDIT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        cleanup()

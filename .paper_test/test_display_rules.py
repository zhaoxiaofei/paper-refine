#!/usr/bin/env python3
"""The venue's DISPLAY-ITEM rules (tables + figures): profile -> prompts -> scan -> gate.

A table's or a figure's caption and its place in the manuscript are DECIDED
venue facts, so they come from the venue profile (the `tables` and `figures`
blocks, which share one schema) and nowhere else:

  * `paper_docx_format.table_conformance_rows` / `figure_conformance_rows` scan
    one document body and report, per kind, *1 (the item carries no caption),
    *2 (the caption sits on the wrong side) and *3 (the item appears before the
    item's area) -- FMT-TB1..3 for tables, FMT-FG1..3 for figures -- and NOTHING
    when the policy declares no rule for that kind (a rule no venue stated is
    never invented);
  * the item AREA is the venue's own tables/figures heading (e.g. "Figure titles
    and legends"), else the first captioned item of that kind; a document with
    neither is not placement-checked (the caption rule still is), and a
    SUPPLEMENTARY/cover/feedback document is out of scope entirely -- the rule
    is about the manuscript body;
  * `tables.special` / `figures.special` are the honest escape hatches for the
    items a publisher really does treat differently: a Cell Press-style
    key-resources table that lives inside the methods with no "Table N." label,
    or a front-matter figure such as a graphical abstract that is not part of
    the numbered figure sequence. The profile names it, the scan exempts it, and
    an unrelated item is still checked;
  * `display_rule_text` renders both rules into the review/judge/revise/rewrite
    prompts, and `scan_regression_problems` FAILS a package-producing stage
    whose delivered package still carries one of those rows when the profile
    declared the rule (the stage retries with the postcheck message);
  * a root whose recorded profile snapshot predates the `tables`/`figures`
    fields inherits the venue's shipped blocks (and only those) so the rules
    reach roots created before this check existed.

Run:  python3 .paper_test/test_display_rules.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("paperp", WS / "paper_pipeline.py")
np = importlib.util.module_from_spec(spec)
sys.modules["paperp"] = np
spec.loader.exec_module(np)
fspec = importlib.util.spec_from_file_location("paper_docx_format",
                                               WS / "paper_docx_format.py")
fmt = importlib.util.module_from_spec(fspec)
sys.modules["paper_docx_format"] = fmt
fspec.loader.exec_module(fmt)

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def para(text, style=None):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def table(rows):
    trs = "".join(
        "<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>"
                           for c in row) + "</w:tr>"
        for row in rows)
    return f"<w:tbl>{trs}</w:tbl>"


def image():
    """A body paragraph carrying an embedded picture (an OOXML `w:drawing`)."""
    return ('<w:p><w:r><w:drawing xmlns:wp="urn:unit-fixture">'
            '<wp:inline/></w:drawing></w:r></w:p>')


def document(*blocks):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>" + "".join(blocks) + "</w:body></w:document>")


def policy(tables=None, figures=None):
    pol = dict(fmt.POLICY_DEFAULTS)
    if tables is not None:
        pol["tables"] = tables
    if figures is not None:
        pol["figures"] = figures
    return pol


def write_docx(dirp: Path, name: str, xml: str) -> Path:
    dirp.mkdir(parents=True, exist_ok=True)
    p = dirp / name
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/'
                   '2006/content-types"><Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.'
                   'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.'
                                  'openxmlformats.org/package/2006/relationships"/>')
        z.writestr("word/document.xml", xml)
        z.writestr("word/styles.xml",
                   '<?xml version="1.0"?><w:styles xmlns:w="http://schemas.'
                   'openxmlformats.org/wordprocessingml/2006/main">'
                   '<w:style w:type="paragraph" w:styleId="Heading1">'
                   '<w:name w:val="heading 1"/></w:style></w:styles>')
    return p


# The manuscript shape this check was written for: a reagent table (the previous
# publisher's "key resources" table) sitting inside the methods with no caption,
# then the venue's own tables area at the end with captioned tables.
KEY_RESOURCES_DOC = document(
    para("Article title", style="Heading1"),
    para("Materials and Methods", style="Heading1"),
    para("Key resources"),
    table([["REAGENT or RESOURCE", "SOURCE", "IDENTIFIER"], ["antibody", "vendor", "AB-1"]]),
    para("The methods continue with prose about the assay and its controls."),
    para("Tables", style="Heading1"),
    para("Table 1. Curated datasets used to benchmark the ranking"),
    table([["Dataset", "Source"], ["D1", "study"]]),
    para("Table 2. Antigen presentation models evaluated for reuse"),
    table([["Method", "Family"], ["MMP_aff", "PWM"]]),
    para("Dist, distance; EL, eluted ligand."))

FRONTIERS_TABLES = {
    "source": "unit fixture (the venue's own template: tables at the end; captions before)",
    "note": "no special tables",
    "placement": "end", "caption": "before", "special": []}

# The figure counterpart of the same manuscript shape: a front-matter image (the
# previous publisher's graphical abstract, with no "Figure N." label and outside
# the numbered sequence) and the venue's own collected legends at the end.
FRONTIERS_FIGURES = {
    "source": "unit fixture (the venue's own template: figure legends at the end)",
    "note": "no special figures",
    "placement": "end", "caption": "any", "special": []}

FRONT_MATTER_FIGURE_DOC = document(
    para("Article title", style="Heading1"),
    para("Graphical abstract"),
    image(),
    para("Introduction", style="Heading1"),
    para("The introduction prose cites Figure 1 and Figure 2."),
    para("Results", style="Heading1"),
    para("The results prose."),
    para("Figure titles and legends", style="Heading1"),
    para("Figure 1 | The pipeline overview."),
    para("Figure 2. Benchmark results per antigen."),
    para("Figure 3. Sequence logos of the presenting allotypes."))


def test_scan_detects_the_reported_defect():
    print("== scan: the uncaptioned, out-of-area table is FMT-TB1 + FMT-TB3 ==")
    rows, inv = fmt.table_conformance_rows(KEY_RESOURCES_DOC, policy(FRONTIERS_TABLES),
                                           "mainText.docx")
    rules = [r["rule"] for r in rows]
    check("the reagent table is reported twice: no caption and outside the tables area",
          rules == ["FMT-TB1", "FMT-TB3"], str(rules))
    check("the rows name the table, its shape, its section and the text above it",
          all("table 1" in r["location"] and "Materials and Methods" in r["location"]
              for r in rows)
          and "2x3" in rows[1]["evidence"],
          json.dumps([{k: r[k] for k in ("location", "evidence")} for r in rows])[:300])
    check("both rows are finding-tier, so the review must dispose them",
          all(r["tier"] == "finding" and r["fix"] == "editorial" for r in rows),
          str([(r["tier"], r["fix"]) for r in rows]))
    check("the captioned end tables are not reported",
          [e["index"] for e in inv] == [1, 2, 3]
          and inv[0]["in_area"] is False
          and inv[1]["in_area"] is True and inv[2]["in_area"] is True,
          str([(e["index"], e["in_area"], e["caption"][:20]) for e in inv]))
    check("the inventory carries the header and the caption side",
          inv[0]["header"].startswith("REAGENT or RESOURCE")
          and inv[1]["caption_side"] == "before" and inv[0]["caption_side"] == "",
          json.dumps(inv[0])[:200])


def test_no_rule_no_rows():
    print()
    print("== no declared rule -> no rows (the module never invents a rule) ==")
    rows, inv = fmt.table_conformance_rows(KEY_RESOURCES_DOC, policy(), "mainText.docx")
    check("an empty policy reports nothing", rows == [] and len(inv) == 3, str(rows))
    check("a source-only block (no placement/caption) reports nothing",
          fmt.table_conformance_rows(
              KEY_RESOURCES_DOC,
              policy({"source": "the venue says nothing we can check"}), "x")[0] == [])


def test_special_tables_are_exempt():
    print()
    print("== the venue's own exception: a declared special table is not forced ==")
    cell_press = {
        "source": "unit fixture (a publisher whose key-resources table lives in the methods)",
        "placement": "end", "caption": "before",
        "special": [{"match": r"^key\s+resources\b", "placement": "inline",
                     "caption": "none",
                     "source": "STAR Methods key resources table"}]}
    rows, inv = fmt.table_conformance_rows(KEY_RESOURCES_DOC, policy(cell_press), "x")
    check("the special table is exempt from BOTH the caption and the placement rule",
          rows == [] and inv[0]["special"].startswith("^key"), str([r["rule"] for r in rows]))
    check("the exemption is recorded on the table's inventory row",
          inv[0]["wants_caption"] == "none" and inv[0]["wants_placement"] == "inline",
          json.dumps({k: inv[0][k] for k in ("special", "wants_caption", "wants_placement")}))
    partial = dict(cell_press)
    partial["special"] = [{"match": r"^key\s+resources\b", "placement": "inline"}]
    rows, _inv = fmt.table_conformance_rows(KEY_RESOURCES_DOC, policy(partial), "x")
    check("an exemption that states only the placement still enforces the caption",
          [r["rule"] for r in rows] == ["FMT-TB1"], str([r["rule"] for r in rows]))
    # an unrelated table is never swallowed by another table's exemption
    other = document(
        para("Methods", style="Heading1"),
        para("Supplementary assay conditions"),
        table([["Condition", "Value"], ["pH", "7.4"]]),
        para("Tables", style="Heading1"),
        para("Table 1. Results"), table([["A", "B"]]))
    rows, _inv = fmt.table_conformance_rows(other, policy(cell_press), "x")
    check("a table the exemption does not match is still reported",
          [r["rule"] for r in rows] == ["FMT-TB1", "FMT-TB3"], str([r["rule"] for r in rows]))


def test_caption_side_and_prose():
    print()
    print("== caption side, caption-shaped prose, and a lone captioned table ==")
    after = document(
        para("Methods", style="Heading1"),
        table([["A", "B"]]),
        para("Table 1. Results of the assay."))
    rows, inv = fmt.table_conformance_rows(after, policy(
        {"placement": "any", "caption": "before"}), "x")
    check("a caption after the table is FMT-TB2 (not FMT-TB1)",
          [r["rule"] for r in rows] == ["FMT-TB2"] and inv[0]["caption_side"] == "after",
          str([r["rule"] for r in rows]))
    prose = document(
        para("Methods", style="Heading1"),
        para("Table 3 shows a schematic of the assay."),
        table([["A", "B"]]),
        para("Tables", style="Heading1"),
        para("Table 1. Results"), table([["A", "B"]]))
    rows, inv = fmt.table_conformance_rows(prose, policy(FRONTIERS_TABLES), "x")
    check("a body sentence starting 'Table 3 shows' is not mistaken for a caption",
          [r["rule"] for r in rows] == ["FMT-TB1", "FMT-TB3"], str([r["rule"] for r in rows]))
    lone = document(para("Methods", style="Heading1"), para("Prose."),
                    para("Table 4. A single captioned table."), table([["A", "B"]]))
    rows, _inv = fmt.table_conformance_rows(lone, policy(FRONTIERS_TABLES), "x")
    check("a lone captioned table (no tables heading) is not reported",
          rows == [], str([r["rule"] for r in rows]))


def test_latex_caption_rule():
    print()
    print("== LaTeX: a table float with no \\caption is a finding, one with is not ==")
    tex = ("\\begin{table}[ht]\n\\begin{tabular}{ll}\na & b \\\\\n\\end{tabular}\n"
           "\\end{table}\n"
           "\\begin{table}\n\\caption{With a caption}\n"
           "\\begin{tabular}{ll}\nc & d \\\\\n\\end{tabular}\n\\end{table}\n")
    rows = fmt.display_rule_rows_from_text(tex, policy(FRONTIERS_TABLES), "main.tex")
    check("exactly the caption-less float is reported, with its line number",
          len(rows) == 1 and rows[0]["rule"] == "FMT-TB1" and "line 1" in rows[0]["location"],
          json.dumps(rows)[:200])
    check("no declared rule -> no LaTeX rows",
          fmt.display_rule_rows_from_text(tex, policy(), "main.tex") == [])


def test_figures_scan_detects_the_reported_shape():
    print()
    print("== figures: a front-matter image outside the legend area is FMT-FG3 ==")
    rows, inv = fmt.figure_conformance_rows(FRONT_MATTER_FIGURE_DOC,
                                            policy(figures=FRONTIERS_FIGURES),
                                            "mainText.docx")
    check("only the front-matter image is reported, as FMT-FG3",
          [r["rule"] for r in rows] == ["FMT-FG3"], str([r["rule"] for r in rows]))
    check("the row names the figure, its position and the text above it",
          "figure 1" in rows[0]["location"] and "Graphical abstract" in rows[0]["location"],
          rows[0]["location"])
    check("the collected legends are in the legend area and are not reported",
          [(e["item"], e["in_area"]) for e in inv]
          == [("image", False), ("legend", True), ("legend", True), ("legend", True)],
          str([(e["item"], e["caption"][:24], e["in_area"]) for e in inv]))
    check("the legend items carry their own caption as the caption",
          inv[1]["caption_side"] == "self"
          and inv[1]["caption"].startswith("Figure 1 |"),
          json.dumps(inv[1])[:200])
    check("a supplementary/cover/response document is out of scope (the rule is the "
          "manuscript's)",
          fmt.figure_conformance_rows(FRONT_MATTER_FIGURE_DOC,
                                      policy(figures=FRONTIERS_FIGURES),
                                      "neohetero-suppInfo.docx")[0] == []
          and fmt.figure_conformance_rows(FRONT_MATTER_FIGURE_DOC,
                                          policy(figures=FRONTIERS_FIGURES),
                                          "coverLetter-to-editor.docx")[0] == []
          and fmt.figure_conformance_rows(FRONT_MATTER_FIGURE_DOC,
                                          policy(figures=FRONTIERS_FIGURES),
                                          "response_to_reviewers.docx")[0] == [],
          "a scope check leaked")
    check("no figures rule declared -> no figure rows (and the table rule is untouched)",
          fmt.figure_conformance_rows(FRONT_MATTER_FIGURE_DOC, policy(), "x.docx")[0] == [])


def test_figures_special_and_caption_side():
    print()
    print("== figures: the graphical-abstract exemption, caption side, LaTeX ==")
    graphical = {
        "source": "unit fixture (a front-matter figure the publisher numbered separately)",
        "placement": "end", "caption": "any",
        "special": [{"match": r"^graphical\s+abstract\b", "placement": "inline",
                     "caption": "none", "source": "unit fixture"}]}
    rows, inv = fmt.figure_conformance_rows(FRONT_MATTER_FIGURE_DOC,
                                            policy(figures=graphical), "mainText.docx")
    check("the graphical abstract is exempt from the placement rule",
          rows == [] and inv[0]["special"].startswith("^graphical"), str(rows))
    check("the exemption is recorded on the item's inventory row",
          inv[0]["wants_placement"] == "inline" and inv[0]["wants_caption"] == "none",
          json.dumps(inv[0])[:200])
    other = dict(graphical)
    other["special"] = []
    check("without the exemption the same figure is reported again",
          [r["rule"] for r in fmt.figure_conformance_rows(
              FRONT_MATTER_FIGURE_DOC, policy(figures=other), "x.docx")[0]] == ["FMT-FG3"])
    inline = document(para("Results", style="Heading1"), image(),
                      para("Figure 1 | Inline legend below the image."))
    pinned = {"placement": "any", "caption": "before"}
    check("a caption on the other side of the image is FMT-FG2",
          [r["rule"] for r in fmt.figure_conformance_rows(
              inline, policy(figures=pinned), "x.docx")[0]] == ["FMT-FG2"])
    no_legend = document(para("Results", style="Heading1"), image(),
                         para("A prose paragraph that is not a legend."))
    check("an image with no caption at all is FMT-FG1 (a pinned side)",
          [r["rule"] for r in fmt.figure_conformance_rows(
              no_legend, policy(figures={"placement": "any", "caption": "after"}),
              "x.docx")[0]] == ["FMT-FG1"])
    same_para = ('<w:p><w:r><w:drawing xmlns:wp="urn:unit-fixture"><wp:inline/>'
                 '</w:drawing></w:r><w:r><w:t>Figure 1 | The legend in the same '
                 'paragraph.</w:t></w:r></w:p>')
    shared = document(para("Results", style="Heading1"), same_para,
                      para("A prose paragraph after the figure."))
    for side in ("before", "after", "any"):
        rows, inv = fmt.figure_conformance_rows(
            shared, policy(figures={"placement": "any", "caption": side}), "x.docx")
        check(f"an image whose legend shares its own paragraph is not FMT-FG1/FG2 "
              f"(caption: {side})",
              rows == [] and inv[0]["caption_side"] == "self",
              str([r["rule"] for r in rows]))
    tex = ("\\begin{figure}\n\\includegraphics{a}\n\\end{figure}\n"
           "\\begin{figure}\n\\caption{With a caption}\n\\end{figure}\n"
           "\\begin{table}\n\\begin{tabular}{ll}a & b \\\\\n\\end{tabular}\n\\end{table}\n")
    rows = fmt.display_rule_rows_from_text(
        tex, policy(tables={"placement": "any", "caption": "before"},
                    figures={"placement": "any", "caption": "after"}), "main.tex")
    check("LaTeX reports the caption-less figure and table floats, each by line",
          [(r["rule"], r["location"].split()[1]) for r in rows]
          == [("FMT-TB1", "7"), ("FMT-FG1", "1")],
          str([(r["rule"], r["location"]) for r in rows]))
    check("a `caption: any` venue does not demand a LaTeX float caption",
          fmt.display_rule_rows_from_text(
              tex, policy(figures={"placement": "any", "caption": "any"}),
              "main.tex") == [])


def test_figures_shipped_profiles_and_gate():
    print()
    print("== figures: shipped profiles, snapshot inheritance, prompts and the gate ==")
    fr = np.load_venue_profile("frontiers-in-immunology")
    check("the shipped Frontiers profile declares the figure rule from its own template",
          fr.declares_figure_rule and fr.figures["placement"] == "end"
          and fr.figures["caption"] == "any"
          and "Figure legends should be placed at the end" in fr.figures["source"],
          json.dumps(fr.figures)[:200])
    check("the shipped NBT profile declares no figure rule (nothing is invented)",
          np.load_venue_profile("nature-biotechnology").declares_figure_rule is False)
    example = np.load_venue_profile("example-journal")
    check("the illustrative profile carries one special table and one special figure",
          len(example.tables.get("special") or []) == 1
          and len(example.figures.get("special") or []) == 1)
    text = np.display_rule_text(fr)
    check("the prompt text renders BOTH kinds, with their check ids",
          "FMT-TB1" in text and "FMT-FG1" in text and "FMT-FG3" in text
          and "figure/legend area" in text)
    check("a profile that declares only one kind renders the other as no-rule",
          "declares NO figure rule" in np.display_rule_text(
              np.load_venue_profile("nature-biotechnology")))
    bad = {"id": "bad-venue", "label": "Bad",
           "figures": {"placement": "middle"}}
    try:
        np.normalize_venue_profile(bad, origin="unit fixture")
        raised = False
    except np.VenueProfileError as e:
        raised = "figures.placement" in str(e)
    check("an invalid figures.placement is refused at profile load", raised)
    tmp = Path(tempfile.mkdtemp(prefix="paper_fig_"))
    root = tmp / "root"
    (root / "venue_profiles").mkdir(parents=True)
    src = (WS / "venue_profiles" / "frontiers-in-immunology.json").read_text(encoding="utf-8")
    (root / "venue_profiles" / "frontiers-in-immunology.json").write_text(src,
                                                                         encoding="utf-8")
    snapshot = json.loads(src)
    snapshot.pop("tables", None)
    snapshot.pop("figures", None)
    ctx = np.Ctx(root)
    ctx.cfg = {"venue": "frontiers-in-immunology", "venue_profile": snapshot}
    pol = np.format_policy_of(ctx)
    check("a pre-schema snapshot inherits BOTH shipped display rules",
          (pol.get("tables") or {}).get("placement") == "end"
          and (pol.get("figures") or {}).get("placement") == "end",
          json.dumps({"tables": pol.get("tables", {}).get("placement"),
                      "figures": pol.get("figures", {}).get("placement")}))
    snapshot2 = json.loads(src)
    snapshot2["figures"] = {"placement": "any", "caption": "any", "special": []}
    ctx2 = np.Ctx(root)
    ctx2.cfg = {"venue": "frontiers-in-immunology", "venue_profile": snapshot2}
    pol2 = np.format_policy_of(ctx2)
    check("a snapshot that carries its own `figures` block is authoritative",
          (pol2.get("figures") or {}).get("placement") == "any"
          and (pol2.get("tables") or {}).get("placement") == "end",
          json.dumps({k: (v or {}).get("placement") for k, v in
                      (("tables", pol2.get("tables")), ("figures", pol2.get("figures")))}))
    sb = Path(tempfile.mkdtemp(prefix="paper_fig_prompt_"))
    review = np.review_prompt(sb, "r1_review", 1, venue=fr)
    judge = np.judge_prompt(sb, "r1_judge_t_j1", 1, "tok", 1, 2, ["v1"], venue=fr)
    check("the review and judge prompts carry the figure rule (no token left)",
          "FMT-FG3" in review and "FMT-FG3" in judge
          and "@@DISPLAY_RULE@@" not in review and "@@DISPLAY_RULE@@" not in judge)
    # The gate: a delivered package that still carries the front-matter figure
    # (and no table defect) is refused, and the error names the figure rule.
    gate_root = Path(tempfile.mkdtemp(prefix="paper_fig_gate_"))
    (gate_root / "venue_profiles").mkdir(parents=True)
    (gate_root / "venue_profiles" / "frontiers-in-immunology.json").write_text(
        src, encoding="utf-8")
    ctx3 = np.Ctx(gate_root)
    ctx3.cfg = {"venue": "frontiers-in-immunology"}
    after = gate_root / "after"
    write_docx(after, "mainText.docx", FRONT_MATTER_FIGURE_DOC)
    errs, _warns = np.scan_regression_problems(ctx3, [(after, "", ())], [(after, "", ())],
                                               "unit fixture")
    check("the delivered package is REFUSED while the figure rule is unmet",
          any("FMT-FG3" in e and "figure rule is not met" in e for e in errs),
          json.dumps(errs)[:300])
    ok = gate_root / "ok"
    write_docx(ok, "mainText.docx", document(
        para("Results", style="Heading1"), para("Prose."),
        para("Figure titles and legends", style="Heading1"),
        para("Figure 1 | The pipeline overview.")))
    check("a package whose only figure is its collected legend passes the gate",
          np.scan_regression_problems(ctx3, [(ok, "", ())], [(ok, "", ())],
                                      "unit fixture")[0] == [])


def test_profile_schema_and_rendering():
    print()
    print("== the profile's `tables` block: schema, rendering, snapshots ==")
    prof = np.load_venue_profile("frontiers-in-immunology")
    check("the shipped Frontiers profile declares its table rule",
          prof.declares_table_rule and prof.tables["placement"] == "end"
          and prof.tables["caption"] == "before" and prof.tables["special"] == [],
          json.dumps(prof.tables)[:200])
    check("the shipped NBT profile declares its table rule (tables at the end)",
          np.load_venue_profile("nature-biotechnology").declares_table_rule)
    check("the generic profile declares none (nothing is invented for it)",
          np.load_venue_profile("generic").declares_table_rule is False)
    text = np.display_rule_text(prof)
    check("the rule text states the placement, the caption side and the check ids",
          "FMT-TB1" in text and "FMT-TB2" in text and "FMT-TB3" in text
          and "immediately BEFORE" in text and "No special" in text or "NO SPECIAL" in text,
          text[:200])
    check("the generic profile renders the report-only wording",
          "declares NO table rule" in np.display_rule_text(
              np.load_venue_profile("generic")))
    bad = {"id": "bad-venue", "label": "Bad", "tables": {"placement": "middle"}}
    try:
        np.normalize_venue_profile(bad, origin="unit fixture")
        raised = False
    except np.VenueProfileError as e:
        raised = "placement" in str(e)
    check("an invalid placement is refused at profile load", raised)
    bad2 = {"id": "bad-venue", "label": "Bad",
            "tables": {"special": [{"match": "("}]}}
    try:
        np.normalize_venue_profile(bad2, origin="unit fixture")
        raised = False
    except np.VenueProfileError as e:
        raised = "regular expression" in str(e)
    check("an invalid special-table regex is refused at profile load", raised)
    # A snapshot recorded BEFORE the tables schema existed inherits the shipped
    # block (and only that block).
    tmp = Path(tempfile.mkdtemp(prefix="paper_table_"))
    root = tmp / "root"
    (root / "venue_profiles").mkdir(parents=True)
    src = (WS / "venue_profiles" / "frontiers-in-immunology.json").read_text(encoding="utf-8")
    (root / "venue_profiles" / "frontiers-in-immunology.json").write_text(src,
                                                                         encoding="utf-8")
    snapshot = json.loads(src)
    snapshot.pop("tables", None)
    ctx = np.Ctx(root)
    ctx.cfg = {"venue": "frontiers-in-immunology", "venue_profile": snapshot}
    pol = np.format_policy_of(ctx)
    check("an old snapshot (no `tables` key) inherits the shipped table rule",
          (pol.get("tables") or {}).get("placement") == "end"
          and (pol.get("tables") or {}).get("caption") == "before",
          json.dumps(pol.get("tables"))[:200])
    snapshot2 = json.loads(src)
    snapshot2["tables"] = {"placement": "any", "caption": "any", "special": []}
    ctx2 = np.Ctx(root)
    ctx2.cfg = {"venue": "frontiers-in-immunology", "venue_profile": snapshot2}
    pol2 = np.format_policy_of(ctx2)
    check("a snapshot that carries its own `tables` block is authoritative",
          (pol2.get("tables") or {}).get("placement") == "any",
          json.dumps(pol2.get("tables"))[:200])
    ctx3 = np.Ctx(root)
    ctx3.cfg = {"venue": "frontiers-in-immunology", "venue_profile": snapshot,
                "format_policy": {"tables": {"placement": "inline", "caption": "any",
                                             "special": []}}}
    check("an operator's own format_policy.tables wins over the profile",
          np.format_policy_of(ctx3)["tables"]["placement"] == "inline")


def test_prompt_and_gate():
    print()
    print("== the rule reaches the prompts, and a producing stage is gated on it ==")
    prof = np.load_venue_profile("frontiers-in-immunology")
    sb = Path(tempfile.mkdtemp(prefix="paper_table_prompt_"))
    review = np.review_prompt(sb, "r1_review", 1, venue=prof)
    judge = np.judge_prompt(sb, "r1_judge_t_j1", 1, "tok", 1, 2, ["v1"], venue=prof)
    check("the review prompt carries the venue's table rule (and no token is left)",
          "FMT-TB1" in review and "@@TABLE_RULE@@" not in review)
    check("the judge prompt carries it too",
          "FMT-TB1" in judge and "@@TABLE_RULE@@" not in judge)
    check("the no-rule venue prompt says so instead of inventing a rule",
          "declares NO table rule" in np.review_prompt(
              sb, "r1_review", 1, venue=np.load_venue_profile("generic")))
    # The gate itself, over a delivered package that still carries the defect.
    root = Path(tempfile.mkdtemp(prefix="paper_table_gate_"))
    (root / "venue_profiles").mkdir(parents=True)
    (root / "venue_profiles" / "frontiers-in-immunology.json").write_text(
        (WS / "venue_profiles" / "frontiers-in-immunology.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    ctx = np.Ctx(root)
    ctx.cfg = {"venue": "frontiers-in-immunology"}
    before = root / "before"
    after = root / "after"
    write_docx(before, "mainText.docx", document(
        para("Methods", style="Heading1"), para("Tables", style="Heading1"),
        para("Table 1. Results"), table([["A", "B"]])))
    write_docx(after, "mainText.docx", KEY_RESOURCES_DOC)
    errs, warns = np.scan_regression_problems(ctx, [(before, "", ())], [(after, "", ())],
                                              "unit fixture")
    check("the delivered package is REFUSED while the venue table rule is unmet",
          any("FMT-TB1" in e for e in errs) and any("FMT-TB3" in e for e in errs)
          and all("table rule is not met" in e for e in errs)
          and any("move this table" in e for e in errs),
          json.dumps(errs)[:300])
    check("a compliant package passes the same gate",
          np.scan_regression_problems(ctx, [(before, "", ())], [(before, "", ())],
                                      "unit fixture")[0] == [],
          str(np.scan_regression_problems(ctx, [(before, "", ())], [(before, "", ())],
                                          "unit fixture")[0])[:200])
    # and with a profile that declares no rule, nothing is gated
    ctx2 = np.Ctx(root)
    ctx2.cfg = {"venue": "generic"}
    check("a venue with no declared table rule is not gated",
          np.scan_regression_problems(ctx2, [(after, "", ())], [(after, "", (()))],
                                      "unit fixture")[0] == [])


def main() -> int:
    test_scan_detects_the_reported_defect()
    test_no_rule_no_rows()
    test_special_tables_are_exempt()
    test_caption_side_and_prose()
    test_latex_caption_rule()
    test_figures_scan_detects_the_reported_shape()
    test_figures_special_and_caption_side()
    test_figures_shipped_profiles_and_gate()
    test_profile_schema_and_rendering()
    test_prompt_and_gate()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) FAILED: " + ", ".join(FAILS))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Regression checks for fix-bugs wave 3 (2026-11-15): the 19 confirmed-but-unfixed items.

Each check pins one candidate re-validated on the current tree and repaired in
this wave. Hermetic: fixtures under tempfile.mkdtemp(); no network, no run root.

Run:  python3 .paper_test/test_fix_bugs_20261115_wave3.py
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

WS = Path(__file__).resolve().parent.parent
TMPDIRS = []
FAILS = []
NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{%s}" % NS


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(WS / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pp = load("fb1115wave3_pp", "paper_pipeline.py")


def check(name: str, cond, detail="") -> None:
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def scratch(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    TMPDIRS.append(tmp)
    return tmp


def docx(path: Path, body: str, notes: str = None) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{NS}"><w:body>{body}</w:body></w:document>')
        if notes is not None:
            z.writestr("word/footnotes.xml",
                       f'<w:footnotes xmlns:w="{NS}">{notes}</w:footnotes>')


def para(t: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'


def cell(t: str) -> str:
    return f"<w:tc>{para(t)}</w:tc>"


def f05() -> None:
    print("\n== F05: a full in-place rewrite at the same anchor is a match ==")
    base = {"document": "main.md", "line": 1,
            "text": "We used a linear model to estimate the effect of canopy openness.",
            "norm": "we used a linear model to estimate the effect of canopy openness.",
            "tokens": set("we used a linear model to estimate the effect of canopy openness"
                          .split())}
    cand = {"document": "main.md", "line": 1,
            "text": "Canopy openness was modelled with a linear regression.",
            "norm": "canopy openness was modelled with a linear regression.",
            "tokens": set("canopy openness was modelled with a linear regression".split())}
    check("F05 the fixture is below the 0.55 threshold",
          pp._content_unit_similarity(base, cand) < pp._CONTENT_UNIT_MATCH)
    missing, added = pp._match_content_units([base], [cand])
    check("F05 the positionally anchored rewrite matches", missing == [] and added == [],
          f"missing={missing} added={added}")
    other = dict(cand, text="The sample was stored at -80 degrees.",
                 norm="the sample was stored at -80 degrees.",
                 tokens=set("the sample was stored at -80 degrees".split()))
    missing2, added2 = pp._match_content_units([base], [other])
    check("F05 an unrelated same-line unit is still not a match",
          bool(missing2) and bool(added2))


def f112() -> None:
    print("\n== F112: an unreadable manual list is UNKNOWN, never 0 ==")
    d = scratch("fb1115_f112_")
    (d / "MANUAL_STEPS.md").write_text("* one\n* two\n", encoding="utf-8")
    os.chmod(d / "MANUAL_STEPS.md", 0)
    try:
        check("F112 count_manual_steps returns the unreadable sentinel",
              pp.count_manual_steps(d / "MANUAL_STEPS.md") == pp.MANUAL_STEPS_UNREADABLE)
        errs, _warns = pp.manual_todo_gate(d, write=False)
        check("F112 the gate reports the unreadable list instead of 0 items",
              any("unreadable" in e.lower() or "UNKNOWN" in e for e in errs), str(errs))
    finally:
        os.chmod(d / "MANUAL_STEPS.md", 0o644)


def f149() -> None:
    print("\n== F149: a disposed ledger row needs BOTH rationale and evidence ==")
    d = scratch("fb1115_f149_")
    payloads = [
        ("an empty rationale/evidence pair fails",
         {"id": "F-001", "verdict": "confirmed", "final_status": "fixed"},
         "missing rationale and evidence"),
        ("a rationale without evidence fails",
         {"id": "F-001", "verdict": "confirmed", "final_status": "fixed",
          "rationale": "checked the source"},
         "missing evidence"),
        ("an evidence cell without rationale fails",
         {"id": "F-001", "verdict": "confirmed", "final_status": "fixed",
          "evidence": "main.md:3 now states the corrected value"},
         "missing rationale"),
    ]
    for label, row, needle in payloads:
        (d / "revision_report.json").write_text(json.dumps([row]), encoding="utf-8")
        errs, _ = pp.revision_ledger_problems(d, ["F-001"], 1)
        check(f"F149 {label}",
              any(needle in e for e in errs), str(errs))
    (d / "revision_report.json").write_text(json.dumps([{
        "id": "F-001", "verdict": "confirmed", "final_status": "fixed",
        "rationale": "checked the source",
        "evidence": "main.md:3 now states the corrected value"}]), encoding="utf-8")
    errs2, _ = pp.revision_ledger_problems(d, ["F-001"], 1)
    check("F149 both recorded cells pass", errs2 == [], str(errs2))


def f155() -> None:
    print("\n== F155: a deleted visual_template manifest cannot skip the venue comparison ==")
    d = scratch("fb1115_f155_")
    (d / "venue_template" / "word").mkdir(parents=True)
    (d / "venue_template" / "word" / "template.docx").write_bytes(b"x")
    (d / "page.pdf").write_bytes(b"%PDF-1.4")
    vis = d / "VISUAL_CHECK.md"
    vis.write_text("We visually inspected the pages and compared them to the journal template.",
                   encoding="utf-8")
    errs = []
    pp.check_visual_artifact(vis, "the visual record", errs, [], sandbox=d, render_roots=[d])
    check("F155 the missing seeded-template manifest is an error",
          any("visual_template/manifest.json is missing" in e for e in errs), str(errs))
    vis.write_text("The pages were NOT visually verified; rendering was impossible here.",
                   encoding="utf-8")
    errs2 = []
    pp.check_visual_artifact(vis, "the visual record", errs2, [], sandbox=d, render_roots=[d])
    check("F155 the documented unavailability sentence keeps the escape hatch",
          errs2 == [], str(errs2))


def f162() -> None:
    print("\n== F162: an unreadable pristine subtree never authorises a delete ==")
    d = scratch("fb1115_f162_")
    pristine, cand = d / "pristine", d / "cand"
    (pristine / "raw_data" / "sub").mkdir(parents=True)
    (pristine / "raw_data" / "sub" / "x.tsv").write_text("a\tb\n1\t2\n", encoding="utf-8")
    (cand / "raw_data" / "sub").mkdir(parents=True)
    (cand / "raw_data" / "sub" / "x.tsv").write_text("a\tb\n1\t2\n", encoding="utf-8")
    os.chmod(pristine / "raw_data" / "sub", 0)
    try:
        ctx = pp.Ctx(d / "root")
        ctx.pristine = pristine
        warns = []
        info = pp.enforce_readonly_raw_data(ctx, cand, warns)
        check("F162 the partial walk does not delete the candidate file",
              (cand / "raw_data" / "sub" / "x.tsv").is_file())
        check("F162 the walk gap is recorded as a failure",
              bool(info.get("failures")) and info.get("dropped") == [], str(info))
    finally:
        os.chmod(pristine / "raw_data" / "sub", 0o755)


def f164() -> None:
    print("\n== F164: the documented short-row repair keeps row identity ==")
    d = scratch("fb1115_f164_")
    before = ("# OUTLINE\n\n| # | document | heading | paragraph | summary | disposition |\n"
              "|---|---|---|---|---|---|\n"
              "| 1 | paper.docx | Intro | 3 | The paper motivates X. |\n"
              "| 2 | paper.docx | Methods | 1 | The paper describes Y. |  |\n")
    after = before.replace(
        "| 1 | paper.docx | Intro | 3 | The paper motivates X. |\n",
        "| 1 | paper.docx | Intro | 3 | The paper motivates X. | OK - inside the bar |\n")
    check("F164 the short row has the same identity before and after",
          pp._repair_table_rows(before) == pp._repair_table_rows(after),
          f"{pp._repair_table_rows(before)} != {pp._repair_table_rows(after)}")
    art = d / "guided_review" / "artifacts"
    art.mkdir(parents=True)
    (art / "OUTLINE.md").write_text(after, encoding="utf-8")
    guard = {"tables": {"artifacts/OUTLINE.md": {
        "rows": pp._repair_table_rows(before),
        "skeleton": pp._repair_table_skeleton(before)}}}
    check("F164 the row-identity guard accepts the repair",
          pp._repair_row_identity_problems(d, guard) == [],
          str(pp._repair_row_identity_problems(d, guard)))


def f170() -> None:
    print("\n== F170: a header-only seeded table is reported even beside a filled table ==")
    d = scratch("fb1115_f170_")
    art = d / "artifacts"
    art.mkdir(parents=True)
    (art / "M2_references.md").write_text(
        "# M2\n\n| # | document | entry | identifier | resolver | disposition |\n"
        "|---|---|---|---|---|---|\n\n"
        "| # | check | detail | disposition |\n|---|---|---|---|\n"
        "| 1 | M2 | coverage table added by the session | OK - all entries checked |\n",
        encoding="utf-8")
    report = pp.artifact_quality_report(
        d, seeded_row_counts={"artifacts/M2_references.md": 3})
    problems = report.get("artifacts/M2_references.md") or []
    check("F170 the emptied seeded table is reported",
          any("header-only disposition table" in p for p in problems), str(problems))


def f171() -> None:
    print("\n== F171: a symlink inside the writable scope is refused ==")
    d = scratch("fb1115_f171_")
    sb = d / "sb"
    (sb / "revised" / "work").mkdir(parents=True)
    outside = d / "outside.txt"
    outside.write_text("ORIGINAL\n", encoding="utf-8")
    (sb / "revised" / "work" / "notes.md").symlink_to(outside)
    rec = {"id": "revise_1", "kind": "revise", "round": 1}
    guard = pp.snapshot_repair_guard(sb, rec)
    check("F171 the symlink is not listed editable", guard["editable"] == [],
          str(guard["editable"]))
    outside.write_text("REWRITTEN BY THE REPAIR\n", encoding="utf-8")
    problems = pp.repair_guard_problems(sb, guard, rec)
    check("F171 the guard reports the symlink",
          any("symlink" in p for p in problems), str(problems))


def f172() -> None:
    print("\n== F172: a file symlink under a read-only area is removed ==")
    d = scratch("fb1115_f172_")
    pristine, cand = d / "pristine", d / "cand"
    (pristine / "raw_data").mkdir(parents=True)
    (pristine / "raw_data" / "x.tsv").write_text("a\n", encoding="utf-8")
    (cand / "raw_data").mkdir(parents=True)
    (cand / "raw_data" / "x.tsv").write_text("a\n", encoding="utf-8")
    outside = d / "outside.tsv"
    outside.write_text("TAMPERED\n", encoding="utf-8")
    (cand / "raw_data" / "evil.tsv").symlink_to(outside)
    ctx = pp.Ctx(d / "root")
    ctx.pristine = pristine
    warns = []
    info = pp.enforce_readonly_raw_data(ctx, cand, warns)
    check("F172 the symlink is removed and recorded",
          not (cand / "raw_data" / "evil.tsv").is_symlink()
          and "raw_data/evil.tsv" in (info.get("dropped") or []), str(info))
    check("F172 the removal is warned about", any("symlink" in w for w in warns), str(warns))


def f176() -> None:
    print("\n== F176: the repair record lists the bookkeeping file it rewrote ==")
    d = scratch("fb1115_f176_")
    sb = d / "sb"
    (sb / "revised").mkdir(parents=True)
    p = sb / "revised" / "revision_report.json"
    p.write_text('{"findings":[]}', encoding="utf-8")
    rec = {"id": "revise_1", "kind": "revise", "round": 1}
    guard = pp.snapshot_repair_guard(sb, rec)
    p.write_text('{"findings":[{"id":"F-1","verdict":"fixed"}]}', encoding="utf-8")
    check("F176 the changed list names the rewritten ledger",
          "revised/revision_report.json" in pp.guard_changed_paths(sb, guard),
          str(pp.guard_changed_paths(sb, guard)))


def f177() -> None:
    print("\n== F177: a deleted M1b section is not a clean audit ==")
    missing = ("# M1 — ACRONYM INVENTORY (artifact)\n\n"
               "| acronym | exempt? | expansion(s) as written |\n|---|---|---|\n| CN | audit | copy number |\n")
    present = missing + "\n## M1b — LONG FORMS RE-USED AFTER THEIR FIRST USE\n\n" \
                        "| acronym | context | long form |\n|---|---|---|\n" \
                        "| - | - | no long-form re-use detected |\n"
    check("F177 the extractor inventory without its M1b section is flagged",
          pp.m1b_audit_section_missing(missing))
    check("F177 an extractor inventory with the section passes",
          not pp.m1b_audit_section_missing(present))
    check("F177 a hand-written minimal M1 table is not mistaken for a deleted seed",
          not pp.m1b_audit_section_missing("# M1\n\n| acronym |\n|---|\n| CN |\n"))


def f179() -> None:
    print("\n== F179: only the RECORDED pipeline removal is exempt ==")
    base_text = ("The data are in raw_data/tables.tsv. The effect was 0.4.\n")
    recorded = [("main.md", "The data are in raw_data/tables.tsv.")]
    for label, revised, removed, should_pass in (
            ("the recorded pipeline removal passes", "The effect was 0.4.\n",
             recorded, True),
            # The same deletion is NOT exempt when the pipeline did not record it:
            # a deletion-only change used to pass on the subsequence rule alone.
            ("an unrelated deletion fails", "The effect was 0.4.\n", [], False),
            ("an unrelated replacement fails", "The effect was 0.9.\n",
             recorded, False),
            ("a deletion the pipeline did not record fails",
             "The effect was 0.4.\n",
             [("main.md", "The data are in raw_data/fabricated.tsv.")], False)):
        d = scratch("fb1115_f179_")
        (d / "base").mkdir()
        (d / "revised").mkdir()
        (d / "base" / "main.md").write_text(base_text, encoding="utf-8")
        (d / "revised" / "main.md").write_text(revised, encoding="utf-8")
        errs = pp.scoped_scope_problems(None, d, d / "revised",
                                        pipeline_changed=["main.md"],
                                        removed=removed)
        check(f"F179 {label}",
              (not errs) if should_pass else bool(errs), str(errs))


def f184() -> None:
    print("\n== F184: the response preflight runs the postcheck's local gates ==")
    d = scratch("fb1115_f184_")
    (d / "target").mkdir()
    (d / "target" / "main.md").write_text("x", encoding="utf-8")
    (d / "response").mkdir()
    (d / "response" / "RESPONSE_TO_REVIEWERS.md").write_text(
        "# Response\n\nWe fixed it.\n", encoding="utf-8")
    (d / "response" / "response_map.json").write_text(json.dumps({"rows": [{
        "id": "C1", "status": "addressed", "response": "Fixed.",
        "changes": [{"file": "missing.md", "operation": "edit"}]}]}), encoding="utf-8")
    errs = pp.response_local_problems(d)
    check("F184 the missing concern block is caught",
          any("does not carry a `## C1` block" in e for e in errs), str(errs))
    check("F184 the missing Comment quotation is caught",
          any("no **Comment:** line" in e for e in errs), str(errs))
    check("F184 the invented change file is caught",
          any("missing.md" in e and "does not exist" in e for e in errs), str(errs))


def f192() -> None:
    print("\n== F192: DOCX/Markdown table rows are content and deletion units ==")
    d = scratch("fb1115_f192_")
    b, c = d / "b", d / "c"
    b.mkdir()
    c.mkdir()
    body_b = (para("We measured the following quantities in the cohort.") + "<w:tbl><w:tr>"
              + cell("55.3") + cell("12.1") + "</w:tr><w:tr>" + cell("61.8") + cell("44.0")
              + "</w:tr></w:tbl>" + para("The animals were housed under standard conditions."))
    body_c = (para("We measured the following quantities in the cohort.")
              + para("The animals were housed under standard conditions."))
    docx(b / "main.docx", body_b)
    docx(c / "main.docx", body_c)
    check("F192 the deleted DOCX table seeds deletion rows",
          len(pp.deletion_audit_rows(b, c)) >= 2, str(pp.deletion_audit_rows(b, c)))
    content = pp.content_edit_problems(None, b, c, "revise",
                                       insertions_allowed=False, deletions_allowed=False)
    check("F192 the content policy sees the deleted table", bool(content), str(content))
    facts = pp.fact_preservation_problems(b, c, "revise")
    check("F192 the fact gate sees the lost values", bool(facts), str(facts))
    mb, mc = d / "mb", d / "mc"
    mb.mkdir()
    mc.mkdir()
    base = ("| group | mean | n |\n|---|---|---|\n| A | 10.5 | 12 |\n| B | 11.2 | 15 |\n\n"
            "The table reports values.\n")
    (mb / "main.md").write_text(base, encoding="utf-8")
    (mc / "main.md").write_text(base.replace("| B | 11.2 | 15 |\n", ""), encoding="utf-8")
    md_content = pp.content_edit_problems(None, mb, mc, "revise",
                                          insertions_allowed=False, deletions_allowed=False)
    check("F192 a deleted Markdown table row is a missing unit",
          any("B | 11.2 | 15" in e for e in md_content), str(md_content))


def f193() -> None:
    print("\n== F193: DOCX footnotes/endnotes are manuscript text ==")
    d = scratch("fb1115_f193_")
    b, c = d / "b", d / "c"
    b.mkdir()
    c.mkdir()
    a = "The animals were housed under standard conditions for the whole study."
    btxt = "The dose was 55 mg per animal and was repeated after twelve hours."
    docx(b / "main.docx", para(a) + para(btxt))
    docx(c / "main.docx", para(a) + para("The protocol details are given in the note.")
         + '<w:p><w:r><w:footnoteReference w:id="1"/></w:r></w:p>',
         notes='<w:footnote w:id="1">' + para(btxt) + "</w:footnote>")
    paras = pp._docx_paragraphs(c / "main.docx", include_notes=True)
    check("F193 the footnote text is read", btxt in (paras or []), str(paras))
    content = pp.content_edit_problems(None, b, c, "revise",
                                       insertions_allowed=False, deletions_allowed=False)
    check("F193 moving a sentence into a footnote is not a deletion",
          not any(btxt in e and "MISSING" in e for e in content), str(content))


def f211() -> None:
    print("\n== F211: pin/publish refuse a version with no recorded digest ==")
    class Ctx:
        def __init__(self, root):
            self.root = root
            self.pins_dir = root / "pins"
            self.reports_dir = root / "reports"
            self.pins_dir.mkdir(parents=True)
            self.reports_dir.mkdir()
            self.state = {"pinned": []}

        def log(self, *a, **k):
            pass

        def run(self, _rid):
            return {}

    saved = {n: getattr(pp, n) for n in (
        "build_corpus_dir", "recorded_version_digest", "stats_row_for",
        "caption_info_for", "effective_content_fingerprint", "placeholder_info_for")}

    def fake_build(_ctx, _r, _vid, dst):
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "main.md").write_text("x", encoding="utf-8")

    pp.build_corpus_dir = fake_build
    pp.recorded_version_digest = lambda *a: None
    pp.stats_row_for = lambda *a: {}
    pp.caption_info_for = lambda *a: {}
    pp.effective_content_fingerprint = lambda *a: ""
    pp.placeholder_info_for = lambda *a: {}
    try:
        ctx = Ctx(scratch("fb1115_f211_"))
        try:
            pp.pin_champion(ctx, 1, "a2", {})
            pinned = False
        except SystemExit:
            pinned = True
        check("F211 pin_champion refuses the absent digest", pinned)
        try:
            pp.publish_winner(ctx, 1, "a2", {"id": "r1_a2"}, {})
            published = False
        except SystemExit:
            published = True
        check("F211 publish_winner refuses the absent pin digest", published)
    finally:
        for name, value in saved.items():
            setattr(pp, name, value)


def f227_f228() -> None:
    print("\n== F227/F228: reference-sentence repair keeps includes and paragraphs ==")
    d = scratch("fb1115_f227_")
    (d / "raw_data").mkdir()
    (d / "raw_data" / "Fig1.png").write_bytes(b"png")
    tex = ("\\documentclass{article}\n\\begin{document}\n"
           "See \\includegraphics{raw_data/Fig1.png} for the results from code/analysis.py.\n"
           "\\end{document}\n")
    (d / "supp.tex").write_text(tex, encoding="utf-8")
    rep = pp.strip_dangling_references_in_dir(d, ["raw_data", "code"], "demo")
    after = (d / "supp.tex").read_text(encoding="utf-8")
    check("F227 the include sharing the sentence survives",
          "\\includegraphics" in after, repr(after))
    check("F227 the prose pointer is still reported as remaining",
          any(r.get("reference") == "code/analysis.py" for r in rep.get("remaining") or []),
          str(rep.get("remaining")))
    d2 = scratch("fb1115_f228_")
    text = "Notes\nThe benchmark ran on the study cohorts\n\nSee code/analysis.py for details.\n"
    (d2 / "notes.md").write_text(text, encoding="utf-8")
    pp.strip_dangling_references_in_dir(d2, ["code"], "demo")
    after2 = (d2 / "notes.md").read_text(encoding="utf-8")
    check("F228 the preceding unpunctuated paragraph survives",
          "The benchmark ran on the study cohorts" in after2, repr(after2))
    check("F228 only the pointer sentence is removed",
          "See code/analysis.py" not in after2, repr(after2))


def f252() -> None:
    print("\n== F252: a paragraph-mark-only change is a rejectable w:pPrChange ==")
    lib = load("fb1115wave3_dtl", ".paper_test/difference_tracking_lib.py")
    nb = lib.nb
    d = scratch("fb1115_f252_")
    b, r, out = d / "b.docx", d / "r.docx", d / "o.docx"
    docx(b, '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
            '<w:r><w:t>Results</w:t></w:r></w:p>')
    docx(r, '<w:p><w:pPr><w:pStyle w:val="Heading2"/><w:numPr>'
            '<w:ilvl w:val="1"/><w:numId w:val="7"/></w:numPr></w:pPr>'
            '<w:r><w:t>Results</w:t></w:r></w:p>')
    info = nb.builtin_tracked_changes(b, r, out)
    import xml.etree.ElementTree as ET
    root = ET.fromstring(zipfile.ZipFile(out).read("word/document.xml"))
    p = root.find(W + "body").find(W + "p")
    ppr = p.find(W + "pPr")
    change = ppr.find(W + "pPrChange") if ppr is not None else None
    check("F252 the paragraph carries a w:pPrChange", change is not None,
          ET.tostring(ppr).decode() if ppr is not None else "no pPr")
    old = change.find(W + "pPr") if change is not None else None
    old_style = old.find(W + "pStyle") if old is not None else None
    check("F252 the base style is recorded for reject-all",
          old_style is not None and old_style.get(W + "val") == "Heading1")
    check("F252 no identical-text delete/insert is counted",
          info.get("paragraphs_inserted") == 0 and info.get("paragraphs_deleted") == 0,
          str(info))


def main() -> int:
    for fn in (f05, f112, f149, f155, f162, f164, f170, f171, f172, f176, f177,
               f179, f184, f192, f193, f211, f227_f228, f252):
        fn()
    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} check(s):")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)

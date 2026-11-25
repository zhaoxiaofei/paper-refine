#!/usr/bin/env python3
"""Wave-2 (run 20261115-081714) regression checks for this stage's fixes.

Direct-function tests: each one exercises the exact construct a candidate named.
Run with: python3 .paper_test/test_fix_bugs_20261115_run2_wave2.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper_pipeline as pp          # noqa: E402
import paper_docx_format as fmt      # noqa: E402

FAILS = []


def check(label, cond, detail=""):
    if cond:
        print(f"[ok ] {label}" + (f"  -- {detail}" if detail else ""))
    else:
        print(f"[FAIL] {label}" + (f"  -- {detail}" if detail else ""))
        FAILS.append(label)


def tmpdir(tag):
    return Path(tempfile.mkdtemp(prefix=f"fb2_{tag}_"))


# ---------------------------------------------------------------------------
# p07 content policy
# ---------------------------------------------------------------------------
def test_content_policy():
    print("\n== p07 content policy ==")
    check("F012 an abbreviation before a capitalised sentence splits",
          pp._content_sentence_parts("The method follows Smith et al. The results were "
                                     "significant.") ==
          ["The method follows Smith et al.", "The results were significant."])
    check("F012 'etc.' also splits before a cap",
          len(pp._content_sentence_parts("We collected samples, etc. The results were "
                                         "significant.")) == 2)
    check("F026 a sentence-final number is a fact",
          pp._fact_survival_tokens("The odds ratio was 0.5.") == ["0.5"])
    check("F093 the sign is part of the fact key",
          pp._fact_survival_keys([{"text": "The sample was kept at -55 C."}]) == {"-55.0"})
    check("F094 scientific notation is one fact",
          pp._fact_survival_keys([{"text": "The rate was 1.2e-4 per cell."}]) ==
          {"0.00012"})
    base = [{"document": "m.md", "line": 1,
             "text": "The treatment reduced tumour volume by 40 percent in the high dose "
                     "group.",
             "norm": "the treatment reduced tumour volume by 40 percent in the high dose "
                     "group.",
             "tokens": set("the treatment reduced tumour volume by 40 percent in the "
                            "high dose group.".split())},
            {"document": "m.md", "line": 1,
             "text": "Body weight remained stable throughout the study period.",
             "norm": "body weight remained stable throughout the study period.",
             "tokens": set("body weight remained stable throughout the study "
                            "period.".split())}]
    # F001 of the 2026-11-19 wave narrows the positional pass: a sentence
    # rewritten at the same slot is a rewrite only when it still carries the
    # original content (similarity floor). This fixture is a full-sentence
    # rewrite of the SAME claim; an unrelated same-slot replacement is the
    # defect F001 rejects.
    cand = [dict(base[0], text="The treatment lowered tumour volume by 40 percent in "
                               "the high dose group.",
                 norm="the treatment lowered tumour volume by 40 percent in the high "
                      "dose group.",
                 tokens=set("the treatment lowered tumour volume by 40 percent in the "
                            "high dose group.".split())),
            dict(base[1])]
    missing, added = pp._match_content_units(base, cand)
    check("F047 a same-line full rewrite anchors by sentence slot",
          missing == [] and added == [], f"missing={missing} added={added}")
    check("F049 '4 C.' is a sentence boundary",
          len(pp._content_sentence_parts("The samples were stored at 4 C. The mice were "
                                         "housed at 22 C.")) == 2)
    check("F049 'Vitamin D.' is a sentence boundary",
          len(pp._content_sentence_parts("Vitamin D. Levels were low.")) == 2)
    check("F053 a trailing \\cite stays with its sentence",
          pp._content_sentence_parts("The effect was large.\\cite{smith2020} The next "
                                     "claim follows here.")[0].endswith("\\cite{smith2020}"))
    check("F081 a .bbl bibitem defines its key",
          pp._bib_keys_in_text(r"\bibitem{smith2020} Smith.") == {"smith2020"})
    for prose in ("However, A recent study found that the treatment worked.",
                  "Notably, B cells expanded after treatment."):
        check(f"F040 prose is not a reference entry: {prose[:12]!r}",
              not pp._DELETED_PARA_SKIP_RE.match(prose)
              and pp._deleted_para_candidate(prose) != "")
    check("F040 a real numbered/author reference is still skipped",
          pp._deleted_para_candidate("Smith, J. 2020. A title. Journal.") == "")

    # F009: a multi-sentence hand-off marker is one unit, not two deletions.
    root = tmpdir("f009")
    base, cand = root / "base", root / "cand"
    base.mkdir(); cand.mkdir()
    marker = ("[AUTHOR TO COMPLETE: Add the grant number. It is printed on the cover "
              "sheet.]")
    (base / "m.md").write_text("We measured the plots.\n\n" + marker + "\n",
                               encoding="utf-8")
    (cand / "m.md").write_text("We measured the plots.\n", encoding="utf-8")
    ctx = pp.Ctx(root)
    ctx.cfg = {"author_to_complete": "readme"}
    got = pp.content_edit_problems(ctx, base, cand, "wave2", insertions_allowed=True,
                                   deletions_allowed=False)
    check("F009 removing a multi-sentence marker is not a deletion", got == [], str(got))

    # F129: a surviving copy elsewhere must not hide a per-sentence unit change.
    b = [{"document": "m.md", "line": 1, "text": "The dose was 55 mg in cohort A.",
          "norm": "the dose was 55 mg in cohort a.",
          "tokens": set("the dose was 55 mg in cohort a.".split())},
         {"document": "m.md", "line": 2, "text": "The dose was 55 mg in cohort B.",
          "norm": "the dose was 55 mg in cohort b.",
          "tokens": set("the dose was 55 mg in cohort b.".split())}]
    c = [dict(b[0]), dict(b[1], text="The dose was 55 ml in cohort B.",
                           norm="the dose was 55 ml in cohort b.",
                           tokens=set("the dose was 55 ml in cohort b.".split()))]
    changed = pp._fact_unit_change_examples(b, c)
    check("F129 a changed unit is reported even when a copy survives elsewhere",
          bool(changed), str(changed))


# ---------------------------------------------------------------------------
# p12 PKG-2 / decision / readiness
# ---------------------------------------------------------------------------
def test_pkg2_and_decision():
    print("\n== p12 PKG-2, decision and readiness ==")
    t = "The data are at https://example.org and the analysis is in code/x.py."
    i = t.index("code/x.py")
    check("F014 an unrelated URL in another clause does not exempt the path",
          pp._pkg2_external_locator(t, i, i + len("code/x.py")) is False)
    t2 = ("The analysis scripts and README.md are archived at "
          "https://github.com/acme/project.")
    i2 = t2.index("README.md")
    check("F014 a locator in the reference's own clause still exempts it",
          pp._pkg2_external_locator(t2, i2, i2 + len("README.md")) is True)
    pats = pp._pkg2_area_patterns(["raw_data", "code"])
    idx = ({"x"}, set(), {}, {}, ())
    for ref in ("../raw_data/t.tsv", "./raw_data/t.tsv"):
        spans = pp.pkg2_reference_spans(f"Use {ref} now.", pats, idx)
        check(f"F085 {ref} is a reference", bool(spans), str(spans))
    for text in ("See the appendix % raw_data/t.tsv\n",
                 "% We used code/run.py.\n"):
        check(f"F098 a path in a LaTeX comment is not a reference ({text[:14]!r})",
              pp.pkg2_reference_spans(text, pats, idx, tex=True) == [])
    # F096/F058/F032: structural blocks are reported, never wholesale deleted.
    tbl = "| Model | File |\n|---|---|\n| A | code/run.py |\n"
    s, e = tbl.index("code/run.py"), tbl.index("code/run.py") + 12
    new, removed, structural, held = pp._drop_reference_sentences_text(tbl, [(s, e)])
    check("F058 a Markdown table is not deleted wholesale", removed == [] and structural)
    tex = ("\\caption{The counts are in\nraw_data/tables.tsv.}\n"
           "We then ran the model.\n")
    s = tex.index("raw_data/tables.tsv")
    new, removed, structural, held = pp._drop_reference_sentences_text(
        tex, [(s, s + len("raw_data/tables.tsv"))])
    check("F032 a multi-line command argument is not corrupted",
          removed == [] and new == tex)
    check("F024 a negated disposition does not reconcile the id",
          pp.discovery_ledger_missing("X-004 | NOT PORTED -- left unchanged",
                                      ["X-004"]) == ["X-004"])
    check("F024 a real ported row reconciles the id",
          pp.discovery_ledger_missing("| X-004 | ported | ok |", ["X-004"]) == [])
    # F005: an id quoted in another row's evidence list is not a row identity.
    ledger = [{"id": "F-001", "verdict": "fixed", "rationale": "x",
               "evidence": ["F-002"]}]
    check("F005 a quoted id is not a disposed row",
          pp.ledger_named_ids(ledger, ["F-001", "F-002"]) == {"F-001"})
    # F042: aggregate status counts must reconcile with detail rows.
    readiness = pp.package_readiness(
        {"open_items": {"statuses": {"manual-required": 3}, "items": [],
                        "discarded": []}, "path": ""},
        author_to_complete="off")
    check("F042 a recorded count with no rows is not submission-ready",
          readiness["submission_ready"] is False and
          any("detail row" in str(f.get("detail")) for f in readiness["findings"]))


# ---------------------------------------------------------------------------
# p06 postchecks / p05 state / p02 journal / docx
# ---------------------------------------------------------------------------
def test_postchecks_state_journal_docx():
    print("\n== p06/p05/p02/docx ==")
    # F056: a zero-byte / text-renamed render is not evidence.
    d = tmpdir("f056")
    (d / "work").mkdir()
    (d / "work" / "empty.pdf").write_bytes(b"")
    (d / "work" / "fake.png").write_bytes(b"not an image")
    (d / "work" / "real.pdf").write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    got = pp.render_evidence_files([d])
    check("F056 empty/magic-less renders are rejected",
          [p.name for p in got] == ["real.pdf"], str(got))
    # F160: an impossible calendar date is rejected.
    pkg = tmpdir("f160")
    (pkg / "work").mkdir()
    (pkg / "work" / "EMAIL_VERIFICATION.json").write_text(json.dumps([{
        "after": "new@uni.edu", "source_url": "https://www.nature.com/page",
        "query": "new uni email", "checked_at": "2026-99-99",
        "evidence": "The address is new@uni.edu on the page."}]))
    base, cand = tmpdir("f160b"), tmpdir("f160c")
    (base / "m.md").write_text("No contact.\n")
    (cand / "m.md").write_text("Contact new@uni.edu.\n")
    errs, _warns = pp.email_address_change_problems([(base, "", ())],
                                                    [(cand, "", ())], pkg, "x")
    check("F160 an impossible checked_at is rejected", bool(errs), str(errs))
    # F080/F088/F090: hand-off markers and keys.
    items = pp._handoff_items_from_manual_steps(
        "- [AUTHOR TO COMPLETE: add n=12] and [AUTHOR TO COMPLETE: fix DOI] please")
    check("F080 two markers on one line are two items", items == ["add n=12", "fix DOI"])
    items2 = pp._handoff_items_from_manual_steps(
        "Text [AUTHOR TO COMPLETE: a\nmulti-line item] tail")
    check("F080 a multi-line marker is not lost",
          len(items2) == 1 and "a multi-line item" in items2[0], str(items2))
    key = pp._handoff_item_key("revised/main.tex", "software version")
    got = pp._handoff_description_key(
        "F-001 [manual-required; major] revised/main.tex: software version",
        {key[1]: {key}})
    check("F090 the generated id/status prefix is not part of the item key", got == key)
    # F164: SVG metadata is stripped.
    raw = (b'<svg xmlns:dc="http://purl.org/dc/elements/1.1/" '
           b'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">'
           b'<metadata><dc:creator>Alice</dc:creator></metadata><!-- hi -->'
           b'<rect inkscape:label="x"/></svg>')
    out, notes = pp._sanitize_svg_bytes(raw)
    check("F164 SVG metadata is stripped",
          b"Alice" not in out and b"<!--" not in out, str(notes))
    # F159: code_literal_rows does not follow a symlink out of the corpus.
    f159 = tmpdir("f159")
    (f159 / "code").mkdir()
    outside = f159 / "outside.py"
    outside.write_text("API_KEY = 'secret'\n")
    (f159 / "code" / "config.py").symlink_to(outside)
    rows = fmt.code_literal_rows([(f159 / "code", "", ())])
    check("F159 a symlinked code file is not read", rows == [], str(rows))
    # F213: a non-fatal contained_under.
    check("F213 an escaping recorded path resolves to None, not SystemExit",
          pp.contained_under_or_none("/tmp", "../etc") is None)


# ---------------------------------------------------------------------------
# docx formatting
# ---------------------------------------------------------------------------
def test_docx_format():
    print("\n== docx formatting ==")
    paras = [("p0", 0, '<w:p><w:r><w:t>References</w:t></w:r></w:p>'),
             ("p1", 1, '<w:p><w:r><w:t>1. Smith J. Title. Journal. 2020.</w:t></w:r></w:p>'),
             ("p2", 2, '<w:p><w:r><w:t>Appendix</w:t></w:r></w:p>'),
             ("p3", 3, '<w:p><w:r><w:t>1. Step one</w:t></w:r></w:p>')]
    flags = fmt._reference_para_flags(paras)
    check("F055 only the contiguous numbered reference run is flagged",
          flags == [False, True, False, False], str(flags))
    # F166: a drawing-bearing caption continuation is in the block, editorial.
    xml = ('<w:p><w:r><w:t>Figure 1. A caption</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>continued legend</w:t></w:r><w:r><w:drawing/></w:r></w:p>')
    ps = fmt.paragraphs(xml)
    blocks = fmt.caption_block_ranges(ps)
    check("F166 a drawing continuation is part of the caption block",
          bool(blocks and blocks[0]["continuations"] and
               blocks[0]["mergeable"] is False), str(blocks))
    # R02/F202: header/footer prose must reach the shared DOCX paragraph
    # reader, including a descriptively named part and the bare name.
    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    p = tmpdir("f202") / "hf.docx"

    def part(root, text):
        return (f'<?xml version="1.0"?><w:{root} xmlns:w="{w_ns}">'
                f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:{root}>')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{w_ns}"><w:body><w:p><w:r>'
                   f'<w:t>body text</w:t></w:r></w:p></w:body></w:document>')
        z.writestr("word/header1.xml", part("hdr", "numbered header text"))
        z.writestr("word/header_venue_default.xml",
                   part("hdr", "descriptive header text"))
        z.writestr("word/footer.xml", part("ftr", "bare footer text"))
        z.writestr("word/footnotes.xml",
                   f'<w:footnotes xmlns:w="{w_ns}"><w:footnote w:id="1">'
                   f'<w:p><w:r><w:t>footnote text</w:t></w:r></w:p>'
                   f'</w:footnote></w:footnotes>')
    texts = pp._docx_paragraphs(p, include_notes=True)
    for needle in ("body text", "footnote text", "numbered header text",
                   "descriptive header text", "bare footer text"):
        check("F202 header/footer prose is read: " + needle,
              needle in (texts or []), str(texts))


def main() -> int:
    test_content_policy()
    test_pkg2_and_decision()
    test_postchecks_state_journal_docx()
    test_docx_format()
    if FAILS:
        print(f"\n{len(FAILS)} check(s) FAILED")
        return 1
    print("\nALL WAVE-2 REGRESSION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

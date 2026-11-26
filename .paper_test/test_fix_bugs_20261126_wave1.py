#!/usr/bin/env python3
"""Regression checks for the 2026-11-26 fix-bugs wave 1 (verified F001-F098).

Small, hermetic unit checks plus source-contract assertions for the stage-level
gates. Run: python3 .paper_test/test_fix_bugs_20261126_wave1.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import stat
import struct
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

WS = Path(os.environ.get("PAPER_WS") or Path(__file__).resolve().parent.parent)
spec = importlib.util.spec_from_file_location("fixbugs1126w1", str(WS / "paper_pipeline.py"))
pp = importlib.util.module_from_spec(spec)
sys.modules["fixbugs1126w1"] = pp
spec.loader.exec_module(pp)

FAILS = []
TMP = []


def scratch(prefix="fixbugs1126_"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    TMP.append(d)
    return d


def mini_docx(path, text, payload):
    """A minimal parseable .docx: one paragraph plus one binary part."""
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
           '2006/main"><w:body><w:p><w:r><w:t>' + text
           + '</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml)
        zf.writestr("word/media/image1.png", payload)


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def source(rel):
    return (WS / rel).read_text(encoding="utf-8")


def concern_row(i, quote="fix the claim", **kw):
    row = {"id": i, "source": "editor.txt", "author": "Reviewer 1", "action": "text",
           "disposition": "to-fix", "quote": quote, "summary": "fix",
           "manuscript_location": "manuscript.txt:1", "evidence_needed": ""}
    row.update(kw)
    return row


def repair_doc(rows):
    d = scratch()
    (d / "concern_repair").mkdir()
    (d / "concern_repair" / "REPAIR_LEDGER.json").write_text(
        json.dumps({"rows": rows}), encoding="utf-8")
    return d


def audit_row(i, verdict="defective", defects=None):
    return {"id": i, "verdict": verdict,
            "defects": defects if defects is not None else [],
            "reason": "stub reason with enough words", "evidence": "stub evidence"}


def png_chunk(kind, payload):
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))


def test_concern_repair():
    print("== concern repair: no-op corrections, merge, residual ==")
    orig = [concern_row("R1-1"), concern_row("R1-2")]
    audit = {"rows": [audit_row("R1-1", "defective",
                                [{"type": "wrong-disposition", "wrong": "to-fix",
                                  "correct": "already-addressed", "basis": "x"}]),
                      audit_row("R1-2", "confirmed")]}
    sb = repair_doc([{"id": "R1-1", "verdict": "confirmed", "action": "corrected",
                      "reason": "stub reason with enough words", "evidence": "x"},
                     {"id": "R1-2", "verdict": "confirmed", "action": "no-change",
                      "reason": "stub reason with enough words", "evidence": "x"}])
    errs = pp.concern_repair_ledger_problems(sb, audit, orig, orig)
    check("F001 a 'corrected' row that changed nothing is refused",
          any("byte-identical" in e for e in errs), str(errs))
    changed = [dict(orig[0], disposition="already-addressed"), orig[1]]
    errs = pp.concern_repair_ledger_problems(sb, audit, orig, changed)
    check("F001 a real correction passes", not any("byte-identical" in e for e in errs),
          str(errs))

    dup_audit = {"rows": [audit_row("R1-1", "defective",
                                    [{"type": "duplicate", "wrong": "R1-1",
                                      "correct": "R1-2", "basis": "same demand"}]),
                          audit_row("R1-2", "confirmed")]}
    sb = repair_doc([{"id": "R1-1", "verdict": "confirmed", "action": "merged",
                      "reason": "stub reason with enough words", "evidence": "x"},
                     {"id": "R1-2", "verdict": "confirmed", "action": "no-change",
                      "reason": "stub reason with enough words", "evidence": "x"}])
    errs = pp.concern_repair_ledger_problems(sb, dup_audit, orig, [orig[1]])
    check("F084 a confirmed duplicate merge passes", not any("lost it" in e for e in errs),
          str(errs))


def test_response_repair():
    print("== response repair ==")
    sb = scratch()
    (sb / "response_repair").mkdir()
    audit = {"rows": [audit_row("R1-1", "defective",
                                [{"type": "missing-answer", "location": "response/x:1",
                                  "wrong": "no answer", "correct": "answer", "basis": "x"}])]}
    (sb / "response_repair" / "REPAIR_LEDGER.json").write_text(json.dumps({
        "rows": [{"id": "R1-1", "verdict": "confirmed", "action": "kept",
                  "reason": "stub reason with enough words", "evidence": "x"}]}),
        encoding="utf-8")
    errs = pp.response_repair_ledger_problems(sb, audit, {"R1-1"})
    check("F002 a confirmed defective row kept unchanged is refused",
          any("record `corrected`" in e for e in errs), str(errs))


def test_prompt_contracts():
    print("== prompt/document contracts ==")
    p08 = source("paper_pipeline_parts/p08_selection_driver.py")
    check("F004 the concern-scoped audit block is passed to the prompt",
          "journal_block=_journal_audit_block" in p08)
    p24 = source("paper_pipeline_parts/p24_deliverable_audits.py")
    check("F005 the response prompts do not call the ledger human-only",
          "REPAIRED human concern ledger" not in p24
          and "admitted" in p24)
    check("F006 the repair prompt no longer offers the rejected `manual` status",
          "planned`/`manual" not in p24 and "mark it planned\n" in p24)
    check("F010 --only response_audit drives finalization instead of a no-op",
          "_final_stages" in source("paper_pipeline_parts/p09_setup.py"))
    check("F012 the concern-repair record carries feedback_files",
          'rec["feedback_files"] = list(con_rec.get("feedback_files") or [])' in p24)
    check("F017 the repaired response bytes get a final write-quality audit",
          "_final_rec" in source("paper_pipeline_parts/p07_stage_quality_journal.py"))
    check("F027 the legacy check includes the Claude Code config",
          '"$HOME/.claude.json"' in source("install_agent_tooling.sh"))
    readme = source("README.md")
    check("F053 README no longer says transfer skips conform",
          "`transfer` skips the stage" not in readme)
    check("F054 README documents the no-.docx fallback",
          "A corpus without any `.docx` still runs" in readme)
    check("F061 an unmeasured census row no longer fabricates zero issues",
          '"issues": (_issue_summary_from_census' in source("paper_pipeline_parts/ranking.py"))


def test_regex_and_text_rules():
    print("== text rules ==")
    fmt = pp._format_module()
    # The formatter module is the format part; use its split_sentences.
    check("F036 a middle initial is not a sentence boundary",
          fmt.split_sentences("John F. Kennedy was elected.") == ["John F. Kennedy was elected."],
          str(fmt.split_sentences("John F. Kennedy was elected.")))
    check("F036 a lower-case symbol still ends the sentence",
          fmt.split_sentences("We used vitamin C. The cells grew.")
          == ["We used vitamin C.", "The cells grew."],
          str(fmt.split_sentences("We used vitamin C. The cells grew.")))
    paras = ["Name | Value", "| --- | --- |", "The sample size was forty two | 42."]
    check("F041 an unoutered table row is table context",
          fmt._table_row_context(paras, 2), str(fmt._table_row_context(paras, 2)))
    p21 = pp
    U = lambda t: {"text": t, "tokens": re.findall(r"[^\W_]+", t.lower())}
    check("F034 a curly-apostrophe negation is not contained",
          p21._content_unit_contained(U("treatment was effective"),
                                      [U("treatment wasn\u2019t effective")]) is False)
    check("F037 curly/ASCII movement denials are refused",
          p21._reason_denies_movement("OK - wasn't moved to Methods")
          and p21._reason_denies_movement("OK - wasn\u2019t moved to Methods"))
    check("F035 `e.g.` is an example marker",
          p21._json_from_text('{"a":1}\ne.g. {"b":2}', True) == {"a": 1})
    # R07: only real name contexts suppress the boundary, not every
    # capitalized label.
    for phrase in ("Participants were in Group A. The results were clear.",
                   "This is Type B. It differs.",
                   "This is Phase I. It differs.",
                   "See Figure A. It shows the data."):
        check(f"R07 {phrase.split('.')[0]!r} ends the sentence",
              len(fmt.split_sentences(phrase)) == 2, str(fmt.split_sentences(phrase)))
    check("R07 a middle initial still does not split",
          fmt.split_sentences("Robert J. Smith reported.")
          == ["Robert J. Smith reported."],
          str(fmt.split_sentences("Robert J. Smith reported.")))
    # R03/F042: the defect is behavioural, not a comment.
    rows = fmt.number_format_rows([
        "Chromosome position 1234 was observed in the sample.",
        "We counted 1,000 cells."])
    check("F042 a chromosome position is not a thousands-separator quantity",
          not any(r.get("rule") == "FMT-T9h" for r in rows), str(rows))
    rows = fmt.number_format_rows(["We processed 1,000 samples and 2500 cells."])
    check("F042 a plain 4-digit quantity still participates",
          any(r.get("rule") == "FMT-T9h" for r in rows), str(rows))


def test_count_words():
    print("== count_words fences ==")
    spec2 = importlib.util.spec_from_file_location(
        "fixbugs1126_cw", str(WS / "paper-skills/paper-review/scripts/count_words.py"))
    cw = importlib.util.module_from_spec(spec2)
    sys.modules["fixbugs1126_cw"] = cw
    spec2.loader.exec_module(cw)
    body = "Intro here.\n\n````\ncode\n````\n\nAfter the code there is prose.\n"
    out = cw.strip_markdown_nonprose(body)
    check("F033 trailing prose after a 4-backtick fence survives", "After the code" in out, out)
    body = "Intro here.\n\n~~~~\ncode\n~~~~~\n\nAfter the tilde fence.\n"
    check("F033 a longer closing fence closes",
          "After the tilde fence" in cw.strip_markdown_nonprose(body))
    body = "Intro here.\n\n```\nunclosed code\n"
    check("F033 an unclosed fence still runs to EOF",
          "unclosed" not in cw.strip_markdown_nonprose(body))


def test_rtf_html():
    print("== RTF / HTML feedback ==")
    out = pp._rtf_plain_text(r"{\rtf1 \u8217\'92 hello \u8217s}")
    check("F048 a \\u fallback is not duplicated and does not eat real text",
          out == "\u2019 hello \u2019s", repr(out))
    out = pp._rtf_plain_text(r"{\rtf1 {\uc0 \u8217} after \u8217\'92}")
    check("F082 group-scoped \\uc does not leak", out == "\u2019 after \u2019", repr(out))
    out = pp._html_plain_text("<table><tr><td>foo</td><td>bar</td></tr></table>")
    check("F051 adjacent table cells are separated", out == "foo\nbar", repr(out))


def test_png_and_gap_gates():
    print("== PNG / discovery gates ==")
    d = scratch()
    real = (b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + png_chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
            + png_chunk(b"IEND", b""))
    stub = (b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + png_chunk(b"IDAT", b"x"))
    (d / "real.png").write_bytes(real)
    (d / "stub.png").write_bytes(stub)
    check("F049 a real PNG passes", pp._png_is_a_real_image(d / "real.png"))
    check("F049 a one-byte IDAT stub is refused", not pp._png_is_a_real_image(d / "stub.png"))
    check("F044 a borrowed DROPPED sentence does not dispose the row",
          pp.discovery_ledger_missing("X-001: the donor DROPPED this row\n", ["X-001"])
          == ["X-001"])
    check("F044 the row's own prose disposition passes",
          pp.discovery_ledger_missing("X-001: PORTED -- changed\n", ["X-001"]) == [])
    check("F050 `row 1` is not a named issue class",
          not pp._discovery_rows) if False else None
    gap = d / "guided_review" / "round2"
    gap.mkdir(parents=True)
    (gap / "gap_table.md").write_text(
        "| class | status |\n|---|---|\n| row 1 | uncovered |\n", encoding="utf-8")
    check("F050 a row-number-only class table has zero classes",
          pp.discovery_gap_summary(d)["rows"] == 0, str(pp.discovery_gap_summary(d)))


def test_audit_evidence():
    print("== audit evidence gates ==")
    base = scratch()
    (base / "main.md").write_text("a\nb\n", encoding="utf-8")
    def audit(ev):
        return {"round": 1, "notes": "checked",
                "counts": {"confirmed": 0, "dropped": 1, "added": 0},
                "dispositions": [{"id": "F-1", "verdict": "drop",
                                  "reason": "the quoted sentence is absent from the base",
                                  "evidence": ev}]}
    check("F089 a fabricated short locator is refused",
          bool(pp.audit_artifact_problems(audit("nope.md:1"), ["F-1"], 1,
                                          base_dir=base)))
    check("F089 a resolving short locator is accepted",
          pp.audit_artifact_problems(audit("main.md:2"), ["F-1"], 1, base_dir=base) == [])
    same = "the quoted text does not appear at the cited location in the manuscript F-1 F-2"
    a = {"dispositions": [{"id": i, "verdict": "drop", "reason": same, "evidence": same}
                          for i in ("F-1", "F-2")], "adds": []}
    check("F077 shared evidence that names every id is still refused",
          any("SAME evidence" in e for e in pp.audit_artifact_problems(a, ["F-1", "F-2"])))


def test_write_repair_and_policy():
    print("== bounded write repair / policy / hashes ==")
    d = scratch()
    pre, post = d / "pre", d / "post"
    pre.mkdir(); post.mkdir()
    plan = [{"id": "RP-1", "file": "new.md", "location": "1", "wrong": "",
             "correct": "The whole new file.\n", "basis": "x", "edit": "add", "evidence": "x"}]
    ledger = d / "LEDGER.json"
    (post / "new.md").write_text("The whole new file.\n", encoding="utf-8")
    ledger.write_text(json.dumps({"rows": [{"id": "RP-1", "verdict": "confirmed",
        "reason": "checked", "before": "", "after": "The whole new file."}]}), encoding="utf-8")
    check("F015 a new file with exactly its confirmed content passes",
          pp._write_repair_check(pre, post, plan, ledger) is None)
    (post / "new.md").write_text("The whole new file.\nArbitrary extra bytes.\n",
                                 encoding="utf-8")
    try:
        pp._write_repair_check(pre, post, plan, ledger)
        ok = False
    except ValueError:
        ok = True
    check("F015 a new file with unplanned bytes is refused", ok)
    bpre, bpost = d / "bpre", d / "bpost"
    bpre.mkdir(); bpost.mkdir()
    (bpre / "x.docx").write_bytes(b"a"); (bpost / "x.docx").write_bytes(b"b")
    check("F020 a binary change with no text span is refused",
          bool(pp._repair_spans_cover(bpre, bpost, "x.docx", [])))
    check("F091 a boolean false turns the audit off",
          pp._deliverable_audit_policy(SimpleNamespace(cfg={"response_audit": False}),
                                       "response_audit") == "off")
    # R08: an empty environment value is UNSET, not off; a JSON null config
    # value means the default on.
    with mock.patch.dict(os.environ, {"PAPER_RESPONSE_AUDIT": ""}):
        check("R08 an empty env value falls back to the configured on",
              pp._deliverable_audit_policy(
                  SimpleNamespace(cfg={"response_audit": "on"}),
                  "response_audit") == "on")
    check("R08 a null config value means the default on",
          pp._deliverable_audit_policy(
              SimpleNamespace(cfg={"response_audit": None}), "response_audit") == "on")
    # R10: unplanned whitespace bytes in a created file are refused; only one
    # final line ending is optional.
    for content, why in (("  The whole new file.  \n", "leading/trailing spaces"),
                         ("\n\nThe whole new file.\n\n", "extra blank lines")):
        (post / "new.md").write_text(content, encoding="utf-8")
        try:
            pp._write_repair_check(pre, post, plan, ledger)
            refused = False
        except ValueError:
            refused = True
        check(f"R10 a new file with {why} is refused", refused)
    (post / "new.md").write_text("The whole new file.\n", encoding="utf-8")
    # R04: a visible-text change must not authorize a DOCX binary-part swap.
    dpre, dpost = d / "dpre", d / "dpost"
    dpre.mkdir(); dpost.mkdir()
    mini_docx(dpre / "x.docx", "before text", b"red")
    mini_docx(dpost / "x.docx", "after text", b"blue")
    check("R04 a text change does not authorize a binary DOCX part swap",
          bool(pp._repair_spans_cover(dpre, dpost, "x.docx",
                                      [("before text", "after text")])))
    mini_docx(dpre / "z.docx", "before text", b"red")
    mini_docx(dpost / "z.docx", "after text", b"red")
    check("R04 a genuine text-only DOCX repair passes",
          pp._repair_spans_cover(dpre, dpost, "z.docx",
                                 [("before text", "after text")]) is None)
    check("F075 Cookie headers are redacted",
          "abc123" not in pp.redact_secrets("Cookie: session=abc123")
          and "abc123" not in pp.redact_secrets("Set-Cookie: session=abc123; HttpOnly"))
    check("F093 J05 and J5 are one dedup class",
          pp.dedup_class_id("J05") == pp.dedup_class_id("J5") == "J5")
    check("F071 a repair marker naming the deliverable stage is adopted",
          _marker_check())


def _marker_check():
    d = scratch()
    (d / "_pipeline_done.json").write_text(json.dumps({
        "status": "complete", "stage": "concerns", "run_id": "r1_concern_repair"}),
        encoding="utf-8")
    return pp._own_completion_signal(d, "concern_repair", pp.MARKER_FILE,
                                     {"id": "r1_concern_repair",
                                      "kind": "concern_repair"}) is not None


def test_review_repairs_20261126():
    print("== review-repair regressions (R05/R06/R09/R11) ==")
    # R05: a decision word borrowed into the SAME cell is not a disposition.
    check("R05 a same-cell borrowed DROPPED sentence does not dispose the row",
          pp.discovery_ledger_missing(
              "| X-001 \u2014 the donor DROPPED this row | evidence |\n",
              ["X-001"]) == ["X-001"])
    check("R05 the same-cell `| X-001 PORTED |` form still passes",
          pp.discovery_ledger_missing("| X-001 PORTED | note |\n", ["X-001"]) == [])
    # R06: a short locator must resolve INSIDE base/, not merely to a file.
    base = scratch()
    (base / "main.md").write_text("a\nb\n", encoding="utf-8")
    outside = base.parent / (base.name + "_outside.md")
    outside.write_text("x\ny\n", encoding="utf-8")

    def audit(ev):
        return {"round": 1, "notes": "checked",
                "counts": {"confirmed": 0, "dropped": 1, "added": 0},
                "dispositions": [{"id": "F-1", "verdict": "drop",
                                  "reason": "the quoted sentence is absent from the base manuscript",
                                  "evidence": ev}]}

    check("R06 a ../ traversal locator is refused",
          bool(pp.audit_artifact_problems(audit("../" + outside.name + ":1"),
                                          ["F-1"], 1, base_dir=base)))
    check("R06 an absolute locator is refused",
          bool(pp.audit_artifact_problems(audit(str(outside) + ":1"),
                                          ["F-1"], 1, base_dir=base)))
    check("R06 a resolving locator in base/ still passes",
          pp.audit_artifact_problems(audit("main.md:2"), ["F-1"], 1,
                                     base_dir=base) == [])
    # R09: a `corrected` row must apply the audited wrong->correct replacement.
    orig = [concern_row("R1-1")]
    audit9 = {"rows": [audit_row("R1-1", "defective",
                                 [{"type": "wrong-disposition", "wrong": "to-fix",
                                   "correct": "already-addressed", "basis": "x"}])]}
    sb = repair_doc([{"id": "R1-1", "verdict": "confirmed", "action": "corrected",
                      "reason": "stub reason with enough words", "evidence": "x"}])
    errs = pp.concern_repair_ledger_problems(
        sb, audit9, orig, [dict(orig[0], summary="unrelated new summary")])
    check("R09 an unrelated-field correction is refused",
          any("audited replacement" in e for e in errs), str(errs))
    errs = pp.concern_repair_ledger_problems(
        sb, audit9, orig, [dict(orig[0], disposition="already-addressed")])
    check("R09 the audited replacement passes",
          not any("audited replacement" in e for e in errs), str(errs))
    # R11: a clean closure that says `no new finding` is not a finding row.
    d = scratch()
    dd = d / "judge_x_j1" / "judge_review" / "discovery"
    dd.mkdir(parents=True)
    header = "| class | probe | checked | disposition |\n|---|---|---|---|\n"
    for side in ("target", "v1"):
        body = [f"| class {i} | probe | {side}/f{i}.md | clean - checked: {side}/f{i}.md |"
                for i in range(4)]
        phrase = ("clean -- checked: no new finding in methods.md:12" if side == "v1"
                  else "clean -- checked: no finding in methods.md:12")
        body.append(f"| class 4 | probe | methods.md:12 | {phrase} |")
        (dd / f"{side}.md").write_text(header + "\n".join(body) + "\n", encoding="utf-8")
    errs, warns = pp.judge_discovery_problems(
        d / "judge_x_j1", {"kind": "judge", "label_map": {"v1": "a2"}})
    check("R11 `no new finding` is a clean closure, not a finding row",
          not errs and not warns, f"{errs} {warns}")


def test_planned_changes_and_human_verbatim():
    print("== response draft / human verbatim ==")
    letter = ("## R1-1 — x\n**Comment:** \"q\"\n**Response:** a\n"
              "**Planned changes:** base/main.md:12\n"
              "## R1-2 — y\n**Comment:** \"q\"\n**Response:** b\n"
              "**Planned changes:** none\n")
    got = pp.response_planned_change_paths(letter)
    check("F009 planned changes parse to a path or 'none'",
          got == {"R1-1": ["main.md"], "R1-2": [None]}, str(got))
    sb = scratch()
    (sb / "feedback" / "text").mkdir(parents=True)
    (sb / "feedback" / "text" / "editor.txt.txt").write_text(
        "Reviewer 1: The datas is wrong.\n", encoding="utf-8")
    check("F007 the converted `.txt.txt` spelling binds to the human text",
          pp.response_comment_human_verbatim(
              None, sb, {"source": "editor.txt.txt"}, "The datas is wrong."))
    check("F007 appended invented text is refused",
          not pp.response_comment_human_verbatim(
              None, sb, {"source": "editor.txt.txt"},
              "The datas is wrong. The authors should also rewrite the abstract."))
    check("F007 a human row naming no staged file fails closed",
          not pp.response_comment_human_verbatim(
              None, sb, {"source": "missing.txt"}, "anything"))


def test_mcp_and_install_sources():
    print("== MCP / installer sources ==")
    conv = source("mcp-docx-converter/index.js")
    comp = source("mcp-docx-compare/index.js")
    check("F022 cleanup unlinks the symlink instead of its resolved target",
          "unlinkSync(spawnOutput)" in comp and "unlinkSync(finalPdf)" in conv)
    check("F023 a resolved non-.docx input is refused",
          "resolves to a non-.docx file" in conv)
    check("F024 merge frees the kept server name for replacement",
          "usedNames.delete(requested)" in source("scripts/install-codex-mcp.mjs"))
    scripts = [source(f"paper-skills/paper-review/scripts/{n}") for n in
               ("extract_numbers.py", "extract_citations.py", "extract_acronyms.py")]
    check("F043 every review script checks every path component",
          all("_symlink_component" in s for s in scripts))


def test_docx_and_conflicts():
    print("== docx / conflict helpers ==")
    check("F063 the exemplar reader uses the shared heading predicate",
          "_docx_heading_style(style, style_names)" in source(
              "paper_pipeline_parts/p01_venues.py"))
    check("F064 supplementary no-space labels keep their S",
          pp._pkg4_cited_labels("FigureS2") == ["s2"]
          and pp._pkg4_cited_labels("FigureS2-S4") == ["s2", "s4"])
    p12 = source("paper_pipeline_parts/p12_conflicts_decide.py")
    check("F045 RTF/DOC evidence is converted or gapped",
          '".rtf", ".doc", ".odt"' in p12 and "editorial decisions were NOT checked" in p12)
    p05 = source("paper_pipeline_parts/p05_state_corpus.py")
    check("F046 reports/ and venue_profiles/ are protected",
          "reports_dir.resolve()" in p05 and "venue_profiles = root / \"venue_profiles\"" in p05)
    check("F047 a non-regular report path fails closed",
          "cand.exists() or cand.is_symlink()" in p12)
    check("F005 no human-only response ledger wording",
          "REPAIRED human concern ledger" not in source(
              "paper_pipeline_parts/p24_deliverable_audits.py"))
    check("F067 a bare unknown row is refused",
          "bare `unknown` row" in source("paper_pipeline_parts/p07_stage_quality_journal.py"))
    check("F068 finding evidence must be contained in the concern quote",
          "_ev.lower() not in _quote.lower()" in source(
              "paper_pipeline_parts/p07_stage_quality_journal.py"))
    check("F096 `major finding` is shape-gated",
          "_is_finding_row" in source("paper_pipeline_parts/p07_stage_quality_journal.py"))
    check("F098 reviewer numbers are checked as tokens",
          "author_numbers" in source("paper_pipeline_parts/p07_stage_quality_journal.py"))


def main():
    tests = [test_concern_repair, test_response_repair, test_prompt_contracts,
             test_regex_and_text_rules, test_count_words, test_rtf_html,
             test_png_and_gap_gates, test_audit_evidence,
             test_write_repair_and_policy, test_review_repairs_20261126,
             test_planned_changes_and_human_verbatim,
             test_mcp_and_install_sources, test_docx_and_conflicts]
    for t in tests:
        try:
            t()
        except Exception as exc:                                   # noqa: BLE001
            check(f"{t.__name__} raised", False, f"{type(exc).__name__}: {exc}")
    for p in TMP:
        shutil.rmtree(p, ignore_errors=True)
    print(f"\n{'PASS' if not FAILS else 'FAIL'}: {len(FAILS)} failure(s)")
    for f in FAILS:
        print(f"  - {f}")
    raise SystemExit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
